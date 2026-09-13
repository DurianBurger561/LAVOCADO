"""Linux and WSL desktop integration."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping, MutableMapping
from pathlib import Path

from app.context.application import application_from_window
from app.context.models import ApplicationContext
from app.platforms.base import (
    Environment,
    WindowInfo,
    WindowProvider,
    data_dir_override,
)
from app.platforms.capture.linux_session import LinuxSessionInfo, detect_linux_session

NAME = "Linux"
CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class LinuxWindowProvider:
    """Read EWMH/X11 foreground-window metadata when tools are available."""

    def __init__(
        self,
        runner: CommandRunner = subprocess.run,
        executable_finder: Callable[[str], str | None] = shutil.which,
        process_executable_reader: Callable[[int], str | None] | None = None,
    ) -> None:
        self._runner = runner
        self._executable_finder = executable_finder
        self._process_executable_reader = (
            process_executable_reader or _linux_executable_for_pid
        )

    def active_window(self) -> WindowInfo | None:
        if not self._executable_finder("xprop"):
            return None

        root = self._run(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
        window_id_match = re.search(r"0x[0-9a-fA-F]+", root)
        if window_id_match is None or window_id_match.group() == "0x0":
            return None
        window_id = window_id_match.group()

        properties = self._run(
            [
                "xprop", "-id", window_id, "_NET_WM_NAME", "WM_NAME",
                "WM_CLASS", "_NET_WM_PID", "_GTK_APPLICATION_ID",
            ]
        )
        title = _x_property(properties, "_NET_WM_NAME") or _x_property(
            properties,
            "WM_NAME",
        )
        app_name = _x_window_class(properties)
        process_id = _x_process_id(properties)
        try:
            executable = (
                self._process_executable_reader(process_id)
                if process_id is not None
                else None
            )
        except Exception:
            executable = None
        app_identifier = _x_property(properties, "_GTK_APPLICATION_ID") or (
            Path(executable).name if executable else None
        )

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
            app_identifier=app_identifier,
            window_id=window_id,
            process_id=process_id,
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

    def get_foreground_application(self) -> ApplicationContext | None:
        application = application_from_window(self.get_foreground_window())
        if application is not None and application.identifier:
            return application

        # Wayland often exposes no X11 foreground window. AT-SPI supplies a
        # unique active process; its executable is a stable rule key.
        try:
            from app.platforms.website.linux_atspi import _NativeAtspiBridge

            process_id = _NativeAtspiBridge().active_process_id()
            executable = (
                _linux_executable_for_pid(process_id)
                if process_id is not None and process_id > 0
                else None
            )
        except Exception:
            return application
        if not executable:
            return application
        process_name = Path(executable).name
        return ApplicationContext(
            identifier=process_name,
            display_name=process_name,
            process_name=process_name,
            window_id=None,
            captured_at=time.monotonic(),
            process_id=process_id,
        )

    def create_website_reader(self):
        from app.platforms.website.linux_atspi import LinuxAtspiWebsiteReader

        return LinuxAtspiWebsiteReader()

    def create_screen_capture(self):
        from app.platforms.capture import (
            create_linux_capture,
            resolve_capture_backend_mode,
        )

        return create_linux_capture(
            self.desktop_session(),
            display=self._environ.get("DISPLAY"),
            mode=resolve_capture_backend_mode(self._environ),
        )

    def desktop_session(self) -> LinuxSessionInfo:
        """Return the runtime route input used by Linux native capture factories."""

        return detect_linux_session(self._environ, self._release)

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


def _x_process_id(output: str) -> int | None:
    match = re.search(r"^_NET_WM_PID[^=]*=\s*(\d+)", output, re.MULTILINE)
    if match is None:
        return None
    process_id = int(match.group(1))
    return process_id if process_id > 0 else None


def _linux_executable_for_pid(process_id: int) -> str | None:
    try:
        return os.readlink(f"/proc/{process_id}/exe")
    except OSError:
        return None


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

    return detect_linux_session(environ, release).is_wsl


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
