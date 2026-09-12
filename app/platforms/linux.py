"""Linux and WSL desktop integration."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, MutableMapping
from pathlib import Path

from app.platforms.base import (
    Environment,
    WindowInfo,
    WindowProvider,
    data_dir_override,
)

NAME = "Linux"
CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class LinuxWindowProvider:
    """Read EWMH/X11 foreground-window metadata when tools are available."""

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


class LinuxPlatform:
    """Provide all Linux and WSL-specific services behind one adapter."""

    name = NAME

    def __init__(
        self,
        *,
        environ: Environment | None = None,
        home: Path | None = None,
        release: str | None = None,
        window_provider: WindowProvider | None = None,
    ) -> None:
        self._environ = os.environ if environ is None else environ
        self._home = Path.home() if home is None else home
        self._release = platform.release() if release is None else release
        self._window_provider = window_provider

    def prepare_environment(self) -> None:
        return None

    def default_data_dir(self) -> Path:
        override = data_dir_override(self._environ)
        if override is not None:
            return override
        return default_data_dir(self._environ, self._home)

    def get_foreground_window(self) -> WindowInfo | None:
        if self._window_provider is None:
            self._window_provider = LinuxWindowProvider()
        return self._window_provider.active_window()

    def create_screen_capture(self):
        from app.platforms.capture import MSSCapture

        return MSSCapture()

    def prepare_overlay_window(self, _root: object) -> None:
        return None

    def release_overlay_focus(self) -> None:
        return None

    def tkinter_help(self) -> str:
        return tkinter_help()

    def screen_capture_help(self) -> str:
        return screen_capture_help()

    def prepare_webview_environment(self) -> str | None:
        return prepare_webview_environment(self._environ, self._release)


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


def create_window_provider() -> LinuxWindowProvider:
    return LinuxWindowProvider()


def prepare_desktop_environment() -> None:
    return None


def tkinter_help() -> str:
    return "Install it on Ubuntu/WSL with: sudo apt install python3-tk"


def screen_capture_help() -> str:
    return (
        "Screen capture is unavailable. On Wayland, allow the desktop's "
        "screen-capture prompt or run under an X11-compatible session."
    )


def default_data_dir(environ: Mapping[str, str], home: Path) -> Path:
    xdg_data_home = environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else home / ".local" / "share"
    return base / "lavocado"


def is_wsl(
    environ: Mapping[str, str] | None = None,
    release: str | None = None,
) -> bool:
    """Return whether this Linux process is hosted by WSL."""

    environ = os.environ if environ is None else environ
    release = platform.release() if release is None else release
    return bool(environ.get("WSL_DISTRO_NAME") or environ.get("WSL_INTEROP")) or (
        "microsoft" in release.casefold()
    )


def prepare_webview_environment(
    environ: MutableMapping[str, str],
    release: str | None = None,
) -> str:
    """Select Qt and use software rendering by default under WSLg."""

    if is_wsl(environ, release):
        environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
        environ.setdefault("QT_OPENGL", "software")
        environ.setdefault("QT_QUICK_BACKEND", "software")
        flags = environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        if "--disable-gpu" not in flags.split():
            environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
                f"{flags} --disable-gpu".strip()
            )
    return "qt"
