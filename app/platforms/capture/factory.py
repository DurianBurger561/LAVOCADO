"""Construct platform capture stacks without leaking backends into services."""

from __future__ import annotations

from app.platforms.capture.base import ScreenCaptureBackend
from app.platforms.capture.errors import CaptureUnavailableError
from app.platforms.capture.fallback import FallbackCaptureBackend
from app.platforms.capture.linux_portal import PipeWirePortalCapture
from app.platforms.capture.linux_session import LinuxCaptureRoute, LinuxSessionInfo
from app.platforms.capture.linux_xshm import XShmCapture
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


def create_linux_capture(
    session: LinuxSessionInfo,
    *,
    display: str | None = None,
    mode: CaptureBackendMode = CaptureBackendMode.AUTO,
) -> ScreenCaptureBackend:
    """Select the native Linux backend while retaining one MSS safety net."""

    if mode is CaptureBackendMode.MSS:
        return MSSCapture()

    native: ScreenCaptureBackend | None = None
    if session.capture_route is LinuxCaptureRoute.PIPEWIRE_PORTAL:
        native = PipeWirePortalCapture()
    elif session.capture_route is LinuxCaptureRoute.XSHM:
        native = XShmCapture(display=display)

    if native is None:
        if mode is CaptureBackendMode.NATIVE:
            raise CaptureUnavailableError(
                "No native capture backend is available for this Linux session"
            )
        return MSSCapture()
    if mode is CaptureBackendMode.NATIVE:
        return native
    return FallbackCaptureBackend(
        primary=native,
        fallback=MSSCapture(),
    )
