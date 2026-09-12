"""macOS desktop integration."""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Callable, Mapping, MutableMapping
from pathlib import Path
from typing import Any

from app.platforms.base import (
    Environment,
    WindowInfo,
    WindowProvider,
    data_dir_override,
)

NAME = "Darwin"
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

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class MacOSWindowProvider:
    """Read the frontmost process and window through System Events."""

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

    def create_screen_capture(self):
        from app.platforms.capture import (
            create_macos_capture,
            resolve_capture_backend_mode,
        )

        return create_macos_capture(resolve_capture_backend_mode(self._environ))

    def prepare_overlay_window(self, root: Any) -> None:
        appkit = None
        application = None
        try:
            import AppKit

            appkit = AppKit
            application = AppKit.NSApplication.sharedApplication()
            application.setActivationPolicy_(
                AppKit.NSApplicationActivationPolicyAccessory
            )
        except Exception:
            LOGGER.debug("AppKit is unavailable for the macOS overlay", exc_info=True)

        try:
            root.tk.call("wm", "attributes", root._w, "-class", "nspanel")
        except Exception:
            LOGGER.debug("Could not create the Tk overlay as an NSPanel", exc_info=True)

        try:
            root.tk.call(
                "::tk::unsupported::MacWindowStyle",
                "style",
                root._w,
                "overlay",
                ("canJoinAllSpaces", "nonActivating"),
            )
        except Exception:
            # Keep the supported Tk fallback on older Aqua/Tk builds.
            try:
                root.tk.call(
                    "::tk::unsupported::MacWindowStyle",
                    "style",
                    root._w,
                    "overlay",
                    "canJoinAllSpaces",
                )
            except Exception:
                LOGGER.debug("Could not set Tk overlay window style", exc_info=True)

        if appkit is None or application is None:
            return

        def configure_native_window(_event: object | None = None) -> None:
            _configure_native_overlay_window(root, application, appkit)

        configure_native_window()
        try:
            root.bind("<Map>", configure_native_window, add="+")
        except Exception:
            LOGGER.debug("Could not bind native overlay setup to map", exc_info=True)

    def release_overlay_focus(self) -> None:
        return None

    def tkinter_help(self) -> str:
        return tkinter_help()

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


def _configure_native_overlay_window(root: Any, application: Any, appkit: Any) -> None:
    """Allow the Tk overlay to participate in other apps' full-screen Spaces."""

    try:
        title = root.title()
        window = next(
            (
                candidate
                for candidate in application.windows()
                if candidate.title() == title
            ),
            None,
        )
        if window is None:
            return

        collection_behavior = int(window.collectionBehavior())
        collection_behavior |= (
            appkit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | appkit.NSWindowCollectionBehaviorCanJoinAllApplications
            | appkit.NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        window.setCollectionBehavior_(collection_behavior)
    except Exception:
        LOGGER.warning(
            "Could not enable macOS full-screen Space participation for the overlay",
            exc_info=True,
        )


def create_window_provider() -> MacOSWindowProvider:
    return MacOSWindowProvider()


def prepare_desktop_environment() -> None:
    return None


def tkinter_help() -> str:
    return "Install a current Python build from python.org with Tcl/Tk support."


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
