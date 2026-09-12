"""One policy wrapper for native-primary and MSS fallback capture."""

from __future__ import annotations

import logging

from app.platforms.capture.base import ScreenCaptureBackend
from app.platforms.capture.errors import (
    CaptureError,
    CapturePermissionDeniedError,
    CaptureRecoverableError,
    CaptureUnavailableError,
)
from app.platforms.capture.models import CaptureBackendStatus, CaptureFrame, MonitorInfo

LOGGER = logging.getLogger(__name__)


class FallbackCaptureBackend:
    """Use a preferred backend, switching permanently to fallback on failure."""

    name = "native_with_mss_fallback"

    def __init__(
        self,
        primary: ScreenCaptureBackend,
        fallback: ScreenCaptureBackend,
        *,
        recovery_attempts: int = 1,
    ) -> None:
        if recovery_attempts < 0:
            raise ValueError("recovery_attempts cannot be negative")
        self._primary = primary
        self._fallback = fallback
        self._recovery_attempts = recovery_attempts
        self._active: ScreenCaptureBackend | None = None
        self._fallback_reason: str | None = None

    def start(self) -> None:
        if self._active is not None:
            return
        try:
            self._primary.start()
        except CapturePermissionDeniedError:
            raise
        except (CaptureUnavailableError, CaptureRecoverableError) as error:
            self._activate_fallback(error)
        else:
            self._active = self._primary

    def stop(self) -> None:
        active = self._active
        self._active = None
        if active is not None:
            active.stop()

    def monitors(self) -> list[MonitorInfo]:
        return self._require_active().monitors()

    def get_latest_frame(self, monitor_id: str) -> CaptureFrame | None:
        active = self._require_active()
        if active is self._fallback:
            return active.get_latest_frame(monitor_id)

        try:
            return active.get_latest_frame(monitor_id)
        except CapturePermissionDeniedError:
            raise
        except CaptureUnavailableError as error:
            self._activate_fallback(error)
        except CaptureRecoverableError as error:
            return self._recover_or_fallback(monitor_id, error)
        return self._require_active().get_latest_frame(monitor_id)

    def status(self) -> CaptureBackendStatus:
        active = self._active
        active_status = None if active is None else active.status()
        return CaptureBackendStatus(
            preferred_backend=self._primary.name,
            active_backend=None if active is None else active.name,
            fallback=active is self._fallback,
            fallback_reason=self._fallback_reason,
            healthy=bool(active_status and active_status.healthy),
            error=None if active_status is None else active_status.error,
            session=None if active_status is None else active_status.session,
            monitor_count=0 if active_status is None else active_status.monitor_count,
            frame_age_ms=None if active_status is None else active_status.frame_age_ms,
        )

    def _recover_or_fallback(
        self,
        monitor_id: str,
        initial_error: CaptureRecoverableError,
    ) -> CaptureFrame | None:
        latest_error: Exception = initial_error
        for _attempt in range(self._recovery_attempts):
            try:
                self._primary.stop()
                self._primary.start()
                return self._primary.get_latest_frame(monitor_id)
            except CapturePermissionDeniedError:
                self._active = None
                raise
            except (CaptureUnavailableError, CaptureRecoverableError) as error:
                latest_error = error
        self._activate_fallback(latest_error)
        return self._require_active().get_latest_frame(monitor_id)

    def _activate_fallback(self, error: Exception) -> None:
        try:
            self._primary.stop()
        except CaptureError:
            LOGGER.debug("Could not stop failed native capture", exc_info=True)
        self._fallback_reason = f"{type(error).__name__}: {error}"
        self._fallback.start()
        self._active = self._fallback

    def _require_active(self) -> ScreenCaptureBackend:
        if self._active is None:
            raise RuntimeError("Capture backend has not been started")
        return self._active
