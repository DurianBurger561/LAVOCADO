"""Cross-platform foreground-window metadata and blocklist matching."""

from __future__ import annotations

import ctypes
import logging
import platform
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Any, Protocol

from app import config

LOGGER = logging.getLogger(__name__)

MACOS_WINDOW_SCRIPT = """
tell application "System Events"
    set frontProcess to first application process whose frontmost is true
    set appName to name of frontProcess
    set windowTitle to ""
    set xPosition to ""
    set yPosition to ""
    set windowWidth to ""
    set windowHeight to ""
    try
        set frontWindow to front window of frontProcess
        set windowTitle to name of frontWindow
        set windowPosition to position of frontWindow
        set windowSize to size of frontWindow
        set xPosition to (item 1 of windowPosition) as text
        set yPosition to (item 2 of windowPosition) as text
        set windowWidth to (item 1 of windowSize) as text
        set windowHeight to (item 2 of windowSize) as text
    end try
    set fieldSeparator to ASCII character 31
    return appName & fieldSeparator & windowTitle & fieldSeparator & xPosition & fieldSeparator & yPosition & fieldSeparator & windowWidth & fieldSeparator & windowHeight
end tell
"""


@dataclass(frozen=True, slots=True)
class WindowInfo:
    """Minimal foreground-window data held in memory for one check."""

    title: str
    app_name: str = ""
    left: int | None = None
    top: int | None = None
    width: int | None = None
    height: int | None = None

    @property
    def center(self) -> tuple[int, int] | None:
        if None in (self.left, self.top, self.width, self.height):
            return None
        assert self.left is not None
        assert self.top is not None
        assert self.width is not None
        assert self.height is not None
        if self.width < 1 or self.height < 1:
            return None
        return self.left + self.width // 2, self.top + self.height // 2


@dataclass(frozen=True, slots=True)
class BlocklistResult:
    blocked: bool
    matched_term: str | None = None
    window: WindowInfo | None = None


class WindowProvider(Protocol):
    def active_window(self) -> WindowInfo | None: ...


class WindowWatcher:
    """Match configured terms against the active app and window title."""

    def __init__(
        self,
        blocked_terms: Sequence[str] = config.BLOCKED_APPS,
        provider: WindowProvider | None = None,
        system_name: str | None = None,
    ) -> None:
        self._blocked_terms = tuple(
            term.strip() for term in blocked_terms if term.strip()
        )
        self._provider = provider
        self._system_name = system_name

    def check(self) -> BlocklistResult:
        if not self._blocked_terms:
            return BlocklistResult(blocked=False)

        try:
            if self._provider is None:
                self._provider = create_window_provider(self._system_name)
            window = self._provider.active_window()
        except Exception:
            LOGGER.exception(
                "Could not read the active window; skipping blocklist check"
            )
            return BlocklistResult(blocked=False)
        if window is None:
            return BlocklistResult(blocked=False)

        searchable = f"{window.app_name}\n{window.title}".casefold()
        for term in self._blocked_terms:
            if term.casefold() in searchable:
                return BlocklistResult(
                    blocked=True,
                    matched_term=term,
                    window=window,
                )

        return BlocklistResult(blocked=False, window=window)


class _WindowsRect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class WindowsWindowProvider:
    def __init__(
        self,
        user32: Any | None = None,
        kernel32: Any | None = None,
    ) -> None:
        self._user32 = user32
        self._kernel32 = kernel32
        if self._user32 is None:
            self._user32 = ctypes.windll.user32
            self._kernel32 = ctypes.windll.kernel32
            self._configure_api()

    def _configure_api(self) -> None:
        from ctypes import wintypes

        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
        self._user32.GetWindowTextLengthW.restype = ctypes.c_int
        self._user32.GetWindowTextW.argtypes = (
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        )
        self._user32.GetWindowTextW.restype = ctypes.c_int
        self._user32.GetWindowRect.argtypes = (
            wintypes.HWND,
            ctypes.POINTER(_WindowsRect),
        )
        self._user32.GetWindowRect.restype = wintypes.BOOL
        self._user32.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        )
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        )
        self._kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL

    def active_window(self) -> WindowInfo | None:
        window_handle = self._user32.GetForegroundWindow()
        if not window_handle:
            return None

        title_length = max(0, self._user32.GetWindowTextLengthW(window_handle))
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        self._user32.GetWindowTextW(
            window_handle,
            title_buffer,
            len(title_buffer),
        )

        rectangle = _WindowsRect()
        has_rectangle = bool(
            self._user32.GetWindowRect(window_handle, ctypes.byref(rectangle))
        )
        if not has_rectangle:
            return WindowInfo(
                title=title_buffer.value,
                app_name=self._app_name(window_handle),
            )

        return WindowInfo(
            title=title_buffer.value,
            app_name=self._app_name(window_handle),
            left=rectangle.left,
            top=rectangle.top,
            width=rectangle.right - rectangle.left,
            height=rectangle.bottom - rectangle.top,
        )

    def _app_name(self, window_handle: int) -> str:
        if self._kernel32 is None:
            return ""

        from ctypes import wintypes

        process_id = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(
            window_handle,
            ctypes.byref(process_id),
        )
        if not process_id.value:
            return ""

        process_handle = self._kernel32.OpenProcess(
            0x1000,  # PROCESS_QUERY_LIMITED_INFORMATION
            False,
            process_id.value,
        )
        if not process_handle:
            return ""

        try:
            path_buffer = ctypes.create_unicode_buffer(32768)
            path_length = wintypes.DWORD(len(path_buffer))
            if not self._kernel32.QueryFullProcessImageNameW(
                process_handle,
                0,
                path_buffer,
                ctypes.byref(path_length),
            ):
                return ""
            return PureWindowsPath(path_buffer.value).stem
        finally:
            self._kernel32.CloseHandle(process_handle)


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class MacOSWindowProvider:
    def __init__(self, runner: CommandRunner = subprocess.run) -> None:
        self._runner = runner

    def active_window(self) -> WindowInfo | None:
        result = self._runner(
            ["osascript", "-e", MACOS_WINDOW_SCRIPT],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
        if result.returncode != 0:
            return None

        fields = result.stdout.rstrip("\n").split("\x1f")
        if len(fields) != 6:
            return None

        app_name, title, left, top, width, height = fields
        bounds = _parse_bounds(left, top, width, height)
        return WindowInfo(title=title, app_name=app_name, **bounds)


class LinuxWindowProvider:
    def __init__(
        self,
        runner: CommandRunner = subprocess.run,
        executable_finder: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._runner = runner
        self._executable_finder = executable_finder

    def active_window(self) -> WindowInfo | None:
        if not self._executable_finder("xprop"):
            return None

        root = self._run(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
        window_id_match = re.search(r"0x[0-9a-fA-F]+", root)
        if window_id_match is None or window_id_match.group() == "0x0":
            return None
        window_id = window_id_match.group()

        properties = self._run(
            ["xprop", "-id", window_id, "_NET_WM_NAME", "WM_NAME", "WM_CLASS"]
        )
        title = _x_property(properties, "_NET_WM_NAME") or _x_property(
            properties,
            "WM_NAME",
        )
        app_name = _x_window_class(properties)

        bounds: dict[str, int | None] = {}
        if self._executable_finder("xwininfo"):
            geometry = self._run(["xwininfo", "-id", window_id])
            bounds = {
                "left": _x_number(geometry, "Absolute upper-left X"),
                "top": _x_number(geometry, "Absolute upper-left Y"),
                "width": _x_number(geometry, "Width"),
                "height": _x_number(geometry, "Height"),
            }

        return WindowInfo(
            title=title,
            app_name=app_name,
            **bounds,
        )

    def _run(self, command: list[str]) -> str:
        result = self._runner(
            command,
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
        return result.stdout if result.returncode == 0 else ""


def create_window_provider(system_name: str | None = None) -> WindowProvider:
    current_system = system_name or platform.system()
    if current_system == "Windows":
        return WindowsWindowProvider()
    if current_system == "Darwin":
        return MacOSWindowProvider()
    if current_system == "Linux":
        return LinuxWindowProvider()
    raise RuntimeError(
        f"Foreground-window detection is unsupported on {current_system}"
    )


def _parse_bounds(
    left: str,
    top: str,
    width: str,
    height: str,
) -> dict[str, int | None]:
    try:
        return {
            "left": round(float(left)),
            "top": round(float(top)),
            "width": round(float(width)),
            "height": round(float(height)),
        }
    except ValueError:
        return {"left": None, "top": None, "width": None, "height": None}


def _x_property(output: str, property_name: str) -> str:
    match = re.search(
        rf"^{re.escape(property_name)}[^=]*=\s*\"([^\"]*)\"",
        output,
        re.MULTILINE,
    )
    return "" if match is None else match.group(1)


def _x_window_class(output: str) -> str:
    match = re.search(r"^WM_CLASS[^=]*=(.*)$", output, re.MULTILINE)
    if match is None:
        return ""
    values = re.findall(r'"([^\"]*)"', match.group(1))
    return values[-1] if values else ""


def _x_number(output: str, field: str) -> int | None:
    match = re.search(rf"^\s*{re.escape(field)}:\s*(-?\d+)", output, re.MULTILINE)
    return None if match is None else int(match.group(1))
