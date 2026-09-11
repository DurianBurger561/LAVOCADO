"""Desktop-platform setup and actionable dependency errors."""

from __future__ import annotations

import ctypes
import platform
from typing import Any

SUPPORTED_SYSTEMS = frozenset({"Windows", "Darwin", "Linux"})


class UnsupportedPlatformError(RuntimeError):
    """Raised when LAVOCADO is started on an unsupported operating system."""


class ScreenCaptureError(RuntimeError):
    """Raised when the operating system prevents screen capture."""


def prepare_desktop_environment(system_name: str | None = None) -> str:
    """Validate the OS and apply setup required before creating windows."""

    current_system = system_name or platform.system()
    if current_system not in SUPPORTED_SYSTEMS:
        raise UnsupportedPlatformError(
            f"LAVOCADO does not currently support {current_system or 'this OS'}. "
            "Supported systems: Windows, macOS, and Linux."
        )

    if current_system == "Windows":
        enable_windows_dpi_awareness()

    return current_system


def enable_windows_dpi_awareness(user32: Any | None = None) -> bool:
    """Best-effort enable Windows Per-Monitor V2 DPI awareness."""

    if user32 is None:
        try:
            user32 = ctypes.windll.user32
        except AttributeError:
            return False

    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 is HANDLE(-4).
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return True
    except (AttributeError, OSError):
        pass

    try:
        return bool(user32.SetProcessDPIAware())
    except (AttributeError, OSError):
        return False


def tkinter_help(system_name: str | None = None) -> str:
    """Return platform-specific instructions for installing Tkinter."""

    current_system = system_name or platform.system()
    if current_system == "Linux":
        return "Install it on Ubuntu/WSL with: sudo apt install python3-tk"
    if current_system == "Darwin":
        return "Install a current Python build from python.org with Tcl/Tk support."
    if current_system == "Windows":
        return "Repair the python.org installation and enable the Tcl/Tk feature."
    return "Install a Python distribution that includes Tcl/Tk."


def screen_capture_help(system_name: str | None = None) -> str:
    """Return platform-specific guidance for screen-capture failures."""

    current_system = system_name or platform.system()
    if current_system == "Darwin":
        return (
            "Allow Terminal or LAVOCADO in System Settings > Privacy & Security > "
            "Screen & System Audio Recording, then restart the application."
        )
    if current_system == "Linux":
        return (
            "Screen capture is unavailable. On Wayland, allow the desktop's "
            "screen-capture prompt or run under an X11-compatible session."
        )
    if current_system == "Windows":
        return "Screen capture is unavailable. Check remote-session and display access."
    return "The operating system did not allow screen capture."
