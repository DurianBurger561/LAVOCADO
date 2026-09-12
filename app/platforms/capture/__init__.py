"""Cross-platform screen-capture contracts and fallback implementations."""

from app.platforms.capture.base import ScreenCaptureBackend
from app.platforms.capture.errors import (
    CaptureError,
    CaptureFatalError,
    CapturePermissionDeniedError,
    CaptureRecoverableError,
    CaptureUnavailableError,
)
from app.platforms.capture.fallback import FallbackCaptureBackend
from app.platforms.capture.models import (
    CaptureBackendStatus,
    CaptureFrame,
    MonitorInfo,
    Rect,
)
from app.platforms.capture.mss_fallback import MSSCapture

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
]
