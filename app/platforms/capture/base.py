"""Interface implemented by pull-based and streaming capture backends."""

from __future__ import annotations

from typing import Protocol

from app.platforms.capture.models import CaptureBackendStatus, CaptureFrame, MonitorInfo


class ScreenCaptureBackend(Protocol):
    """Provide latest frames without exposing platform APIs to vision code."""

    @property
    def name(self) -> str: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def monitors(self) -> list[MonitorInfo]: ...

    def get_latest_frame(self, monitor_id: str) -> CaptureFrame | None: ...

    def status(self) -> CaptureBackendStatus: ...
