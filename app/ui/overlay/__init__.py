"""Create one concrete overlay backend per supported desktop platform."""

from __future__ import annotations

from app.ui.overlay.base import OverlayBackend
from app.ui.overlay.macos_process_backend import MacOSProcessOverlayBackend
from app.ui.overlay.tk_backend import TkOverlayBackend


def create_overlay_backend(platform_name: str) -> OverlayBackend:
    if platform_name == "Darwin":
        return MacOSProcessOverlayBackend()
    if platform_name == "Windows":
        return TkOverlayBackend(platform_name)
    raise ValueError(f"Unsupported overlay platform: {platform_name}")


__all__ = ["OverlayBackend", "create_overlay_backend"]
