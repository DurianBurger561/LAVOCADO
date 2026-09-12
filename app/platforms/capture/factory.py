"""Construct platform capture stacks without leaking backends into services."""

from __future__ import annotations

from app.platforms.capture.base import ScreenCaptureBackend
from app.platforms.capture.fallback import FallbackCaptureBackend
from app.platforms.capture.macos_screencapturekit import ScreenCaptureKitCapture
from app.platforms.capture.mss_fallback import MSSCapture
from app.platforms.capture.windows_dxgi import WindowsDXGICapture


def create_windows_capture() -> ScreenCaptureBackend:
    """Prefer DXGI on Windows and permanently fall back to MSS if unavailable."""

    return FallbackCaptureBackend(
        primary=WindowsDXGICapture(),
        fallback=MSSCapture(),
    )


def create_macos_capture() -> ScreenCaptureBackend:
    """Prefer ScreenCaptureKit without bypassing a user's permission denial."""

    return FallbackCaptureBackend(
        primary=ScreenCaptureKitCapture(),
        fallback=MSSCapture(),
    )
