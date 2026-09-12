"""Cross-platform screen-capture contracts and fallback implementations."""

from app.platforms.capture.base import ScreenCaptureBackend
from app.platforms.capture.errors import (
    CaptureError,
    CaptureFatalError,
    CapturePermissionDeniedError,
    CaptureRecoverableError,
    CaptureUnavailableError,
)
from app.platforms.capture.factory import create_macos_capture, create_windows_capture
from app.platforms.capture.fallback import FallbackCaptureBackend
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
    "MSSCapture",
    "MonitorInfo",
    "Rect",
    "ScreenCaptureBackend",
    "ScreenCaptureKitCapture",
    "WindowsDXGICapture",
    "create_macos_capture",
    "create_windows_capture",
]
