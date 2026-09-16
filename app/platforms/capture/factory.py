"""Construct platform capture stacks without leaking backends into services."""

from __future__ import annotations

from app.platforms.capture.base import ScreenCaptureBackend
from app.platforms.capture.fallback import FallbackCaptureBackend
from app.platforms.capture.macos_screencapturekit import ScreenCaptureKitCapture
from app.platforms.capture.mss_fallback import MSSCapture
from app.platforms.capture.override import CaptureBackendMode
from app.platforms.capture.windows_dxgi import WindowsDXGICapture


def create_windows_capture(
    mode: CaptureBackendMode = CaptureBackendMode.AUTO,
) -> ScreenCaptureBackend:
    """Prefer DXGI on Windows and permanently fall back to MSS if unavailable."""

    if mode is CaptureBackendMode.MSS:
        return MSSCapture()
    native = WindowsDXGICapture()
    if mode is CaptureBackendMode.NATIVE:
        return native
    return FallbackCaptureBackend(
        primary=native,
        fallback=MSSCapture(),
    )

def create_macos_capture(
    mode: CaptureBackendMode = CaptureBackendMode.AUTO,
) -> ScreenCaptureBackend:
    """Prefer ScreenCaptureKit without bypassing a user's permission denial."""

    if mode is CaptureBackendMode.MSS:
        return MSSCapture()
    native = ScreenCaptureKitCapture()
    if mode is CaptureBackendMode.NATIVE:
        return native
    return FallbackCaptureBackend(
        primary=native,
        fallback=MSSCapture(),
    )
