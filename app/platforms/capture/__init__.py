"""Cross-platform screen-capture contracts and fallback implementations."""

from app.platforms.capture.base import ScreenCaptureBackend
from app.platforms.capture.errors import (
    CaptureError,
    CaptureFatalError,
    CapturePermissionDeniedError,
    CaptureRecoverableError,
    CaptureUnavailableError,
)
from app.platforms.capture.factory import (
    create_linux_capture,
    create_macos_capture,
    create_windows_capture,
)
from app.platforms.capture.fallback import FallbackCaptureBackend
from app.platforms.capture.linux_session import (
    LinuxCaptureRoute,
    LinuxDisplayProtocol,
    LinuxSessionInfo,
    LinuxSessionKind,
    detect_linux_session,
)
from app.platforms.capture.linux_portal import PipeWirePortalCapture
from app.platforms.capture.linux_xshm import XShmAvailability, XShmCapture
from app.platforms.capture.macos_screencapturekit import ScreenCaptureKitCapture
from app.platforms.capture.models import (
    CaptureBackendStatus,
    CaptureFrame,
    MonitorInfo,
    Rect,
)
from app.platforms.capture.mss_fallback import MSSCapture
from app.platforms.capture.windows_dxgi import WindowsDXGICapture

__all__ = [
    "CaptureBackendStatus",
    "CaptureError",
    "CaptureFatalError",
    "CaptureFrame",
    "CapturePermissionDeniedError",
    "CaptureRecoverableError",
    "CaptureUnavailableError",
    "FallbackCaptureBackend",
    "LinuxCaptureRoute",
    "LinuxDisplayProtocol",
    "LinuxSessionInfo",
    "LinuxSessionKind",
    "MSSCapture",
    "MonitorInfo",
    "PipeWirePortalCapture",
    "Rect",
    "ScreenCaptureBackend",
    "ScreenCaptureKitCapture",
    "WindowsDXGICapture",
    "XShmAvailability",
    "XShmCapture",
    "create_linux_capture",
    "create_macos_capture",
    "create_windows_capture",
    "detect_linux_session",
]
