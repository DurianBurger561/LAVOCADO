"""Compatibility facade for desktop-platform setup helpers."""

from __future__ import annotations

from typing import Any

from app.platforms import (
    SUPPORTED_SYSTEMS,
    ScreenCaptureError,
    UnsupportedPlatformError,
    prepare_desktop_environment,
    screen_capture_help,
    tkinter_help,
)
from app.platforms.windows import enable_dpi_awareness


def enable_windows_dpi_awareness(user32: Any | None = None) -> bool:
    """Preserve the original public helper while delegating to Windows."""

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
