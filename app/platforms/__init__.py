"""Select one explicit desktop-platform implementation."""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from types import ModuleType

from app.platforms import linux, macos, windows
from app.platforms.common import (
    ScreenCaptureError,
    UnsupportedPlatformError,
    WindowInfo,
    WindowProvider,
)

SUPPORTED_SYSTEMS = frozenset({windows.NAME, macos.NAME, linux.NAME})
_PLATFORMS: dict[str, ModuleType] = {
    windows.NAME: windows,
    macos.NAME: macos,
    linux.NAME: linux,
}


def platform_name(system_name: str | None = None) -> str:
    return system_name or platform.system()


def platform_module(system_name: str | None = None) -> ModuleType:
    """Return the adapter module for a supported desktop system."""

    current = platform_name(system_name)
    try:
        return _PLATFORMS[current]
    except KeyError as error:
        raise UnsupportedPlatformError(
            f"LAVOCADO does not currently support {current or 'this OS'}. "
            "Supported systems: Windows, macOS, and Linux."
        ) from error


def create_window_provider(system_name: str | None = None) -> WindowProvider:
    return platform_module(system_name).create_window_provider()


def prepare_desktop_environment(system_name: str | None = None) -> str:
    current = platform_name(system_name)
    platform_module(current).prepare_desktop_environment()
    return current


def tkinter_help(system_name: str | None = None) -> str:
    try:
        return platform_module(system_name).tkinter_help()
    except UnsupportedPlatformError:
        return "Install a Python distribution that includes Tcl/Tk."


def screen_capture_help(system_name: str | None = None) -> str:
    try:
        return platform_module(system_name).screen_capture_help()
    except UnsupportedPlatformError:
        return "The operating system did not allow screen capture."


def default_data_dir(
    system_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else home
    override = environ.get("LAVOCADO_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return platform_module(system_name).default_data_dir(environ, home)


def prepare_webview_environment(
    system_name: str | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> str | None:
    environ = os.environ if environ is None else environ
    return platform_module(system_name).prepare_webview_environment(environ)


__all__ = [
    "SUPPORTED_SYSTEMS",
    "ScreenCaptureError",
    "UnsupportedPlatformError",
    "WindowInfo",
    "WindowProvider",
    "create_window_provider",
    "default_data_dir",
    "platform_module",
    "prepare_desktop_environment",
    "prepare_webview_environment",
    "screen_capture_help",
    "tkinter_help",
]
