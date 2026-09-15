"""Create one concrete overlay backend per supported desktop platform."""

from __future__ import annotations

from pathlib import Path

from app.ui.overlay.base import OverlayBackend
from app.ui.overlay.macos_process_backend import MacOSProcessOverlayBackend
from app.ui.overlay.tk_backend import TkOverlayBackend


def create_overlay_backend(
    platform_name: str,
    *,
    data_dir: Path | None = None,
) -> OverlayBackend:
    if platform_name == "Darwin":
        return MacOSProcessOverlayBackend(data_dir=data_dir)
    if platform_name == "Windows":
        return TkOverlayBackend(platform_name, data_dir=data_dir)
    raise ValueError(f"Unsupported overlay platform: {platform_name}")


__all__ = ["OverlayBackend", "create_overlay_backend"]
