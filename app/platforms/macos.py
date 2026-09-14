"""macOS desktop integration."""

from __future__ import annotations

import os
import subprocess
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

NAME = "Darwin"
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

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class MacOSWindowProvider:
    """Read the frontmost process and window through System Events."""

    def __init__(
        self,
        runner: CommandRunner = subprocess.run,
        identity_reader: Callable[[], tuple[str | None, str | None, int | None]] | None = None,
    ) -> None:
        self._runner = runner
        self._identity_reader = identity_reader or _frontmost_application_identity

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
        try:
            native_name, bundle_id, process_id = self._identity_reader()
        except Exception:  # noqa: BLE001 - optional native identity lookup
            native_name, bundle_id, process_id = None, None, None
        if not native_name or native_name.casefold() != app_name.casefold():
            bundle_id, process_id = None, None
        return WindowInfo(
            title=title,
            app_name=app_name,
            app_identifier=bundle_id,
            process_id=process_id,
            **bounds,
        )


class MacOSPlatform:
    """Provide all macOS-specific services behind one adapter."""

    name = NAME

    def __init__(
        self,
        *,
        environ: Environment | None = None,
        home: Path | None = None,
        window_provider: WindowProvider | None = None,
    ) -> None:
        self._environ = os.environ if environ is None else environ
        self._home = Path.home() if home is None else home
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
            self._window_provider = MacOSWindowProvider()
        return self._window_provider.active_window()

    def get_foreground_application(self) -> ApplicationContext | None:
        return application_from_window(self.get_foreground_window())

    def create_website_reader(self):
        from app.platforms.website.macos_ax import MacOSAXWebsiteReader

        return MacOSAXWebsiteReader()

    def create_screen_capture(self):
        from app.platforms.capture import (
            create_macos_capture,
            resolve_capture_backend_mode,
        )

        return create_macos_capture(resolve_capture_backend_mode(self._environ))

    def screen_capture_help(self) -> str:
        return screen_capture_help()

    def prepare_webview_environment(self) -> str | None:
        return prepare_webview_environment(self._environ)


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


def _frontmost_application_identity() -> tuple[str | None, str | None, int | None]:
    """Use NSRunningApplication rather than a mutable name as the rule key."""

    try:
        import AppKit

        running = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if running is None:
            return None, None, None
        return (
            running.localizedName(),
            running.bundleIdentifier(),
            int(running.processIdentifier()),
        )
    except Exception:  # noqa: BLE001 - optional AppKit identity lookup
        return None, None, None


def create_window_provider() -> MacOSWindowProvider:
    return MacOSWindowProvider()


def prepare_desktop_environment() -> None:
    return None


def screen_capture_help() -> str:
    return (
        "Allow Terminal or LAVOCADO in System Settings > Privacy & Security > "
        "Screen & System Audio Recording, then restart the application."
    )


def default_data_dir(_environ: Mapping[str, str], home: Path) -> Path:
    return home / "Library" / "Application Support" / "LAVOCADO"


def prepare_webview_environment(
    _environ: MutableMapping[str, str],
) -> str | None:
    """Use pywebview's native Cocoa backend selection."""

    return None
