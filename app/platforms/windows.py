"""Windows desktop integration."""

from __future__ import annotations

import ctypes
from collections.abc import Mapping, MutableMapping
from pathlib import Path, PureWindowsPath
from typing import Any

from app.platforms.common import WindowInfo

NAME = "Windows"


class _WindowsRect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class WindowsWindowProvider:
    """Read the foreground window through User32 and Kernel32."""

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


def create_window_provider() -> WindowsWindowProvider:
    return WindowsWindowProvider()


def enable_dpi_awareness(user32: Any | None = None) -> bool:
    """Best-effort enable Windows Per-Monitor V2 DPI awareness."""

    if user32 is None:
        try:
            user32 = ctypes.windll.user32
        except AttributeError:
            return False

    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return True
    except (AttributeError, OSError):
        pass

    try:
        return bool(user32.SetProcessDPIAware())
    except (AttributeError, OSError):
        return False


def prepare_desktop_environment() -> None:
    enable_dpi_awareness()


def tkinter_help() -> str:
    return "Repair the python.org installation and enable the Tcl/Tk feature."


def screen_capture_help() -> str:
    return "Screen capture is unavailable. Check remote-session and display access."


def default_data_dir(environ: Mapping[str, str], home: Path) -> Path:
    local_app_data = environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else home / "AppData" / "Local"
    return base / "LAVOCADO"


def prepare_webview_environment(
    _environ: MutableMapping[str, str],
) -> str | None:
    """Use pywebview's native Windows backend selection."""

    return None
