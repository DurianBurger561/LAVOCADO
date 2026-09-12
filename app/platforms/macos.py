"""macOS desktop integration."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping, MutableMapping
from pathlib import Path

from app.platforms.common import WindowInfo

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
