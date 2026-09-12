"""Temporary compatibility facade for the next migration phase."""

from __future__ import annotations

from typing import Any

from app.platforms import (
    SUPPORTED_SYSTEMS,
    ScreenCaptureError,
    UnsupportedPlatformError,
    create_platform_adapter,
)
from app.platforms.windows import enable_dpi_awareness


def prepare_desktop_environment(system_name: str | None = None) -> str:
    adapter = create_platform_adapter(system_name)
    adapter.prepare_environment()
    return adapter.name


def tkinter_help(system_name: str | None = None) -> str:
    try:
        return create_platform_adapter(system_name).tkinter_help()
    except UnsupportedPlatformError:
        return "Install a Python distribution that includes Tcl/Tk."


def screen_capture_help(system_name: str | None = None) -> str:
    try:
        return create_platform_adapter(system_name).screen_capture_help()
    except UnsupportedPlatformError:
        return "The operating system did not allow screen capture."


def enable_windows_dpi_awareness(user32: Any | None = None) -> bool:
    return enable_dpi_awareness(user32)


__all__ = [
    "SUPPORTED_SYSTEMS",
    "ScreenCaptureError",
    "UnsupportedPlatformError",
    "enable_windows_dpi_awareness",
    "prepare_desktop_environment",
    "screen_capture_help",
    "tkinter_help",
]
