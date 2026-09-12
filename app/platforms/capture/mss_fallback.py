"""Portable MSS screen capture used as every platform's safety net."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np
from mss import MSS
from mss.exception import ScreenShotError

from app.platforms.capture.errors import (
    CaptureFatalError,
    CaptureRecoverableError,
    CaptureUnavailableError,
)
from app.platforms.capture.models import CaptureBackendStatus, CaptureFrame, MonitorInfo


class MSSCapture:
    """Capture full-resolution BGR frames through the portable MSS library."""

    name = "mss"

    def __init__(
        self,
        *,
        capture_factory: Callable[[], Any] = MSS,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._capture_factory = capture_factory
        self._clock_ns = clock_ns
        self._capture: Any | None = None
        self._monitors: list[MonitorInfo] = []
        self._raw_monitors: dict[str, dict[str, Any]] = {}
        self._sequences: dict[str, int] = {}

    def start(self) -> None:
        if self._capture is not None:
            return
        try:
            capture = self._capture_factory()
            raw_monitors = list(capture.monitors)
        except Exception as error:
            raise CaptureUnavailableError(
                f"MSS initialization failed: {error}"
            ) from error

        monitors = normalize_mss_monitors(raw_monitors)
        if not monitors:
            capture.close()
            raise CaptureUnavailableError("MSS found no physical displays")
        self._capture = capture
        self._monitors = monitors
        self._raw_monitors = {
            monitor.id: dict(raw_monitors[monitor.index]) for monitor in monitors
        }
        self._sequences = {monitor.id: 0 for monitor in monitors}

    def stop(self) -> None:
        capture = self._capture
        self._capture = None
        self._monitors = []
        self._raw_monitors = {}
        self._sequences = {}
        if capture is not None:
            capture.close()

    def monitors(self) -> list[MonitorInfo]:
        self._require_started()
        return list(self._monitors)

    def get_latest_frame(self, monitor_id: str) -> CaptureFrame:
        capture = self._require_started()
        monitor = self._raw_monitors.get(str(monitor_id))
        if monitor is None:
            raise CaptureFatalError(f"Unknown MSS monitor id: {monitor_id}")
        try:
            screenshot = capture.grab(monitor)
        except ScreenShotError as error:
            raise CaptureRecoverableError(f"MSS capture failed: {error}") from error

        width, height = screenshot.size
        pixels = np.frombuffer(screenshot.bgra, dtype=np.uint8)
        try:
            bgra = pixels.reshape((height, width, 4))
        except ValueError as error:
            raise CaptureFatalError("MSS returned an invalid BGRA frame") from error
        image = np.ascontiguousarray(bgra[:, :, :3])
        sequence = self._sequences[str(monitor_id)] + 1
        self._sequences[str(monitor_id)] = sequence
        return CaptureFrame(
            image=image,
            monitor_id=str(monitor_id),
            timestamp_ns=self._clock_ns(),
            sequence=sequence,
            changed_regions=None,
            backend=self.name,
        )

    def status(self) -> CaptureBackendStatus:
        started = self._capture is not None
        return CaptureBackendStatus(
            preferred_backend=self.name,
            active_backend=self.name if started else None,
            fallback=False,
            fallback_reason=None,
            healthy=started,
            monitor_count=len(self._monitors),
        )

    def _require_started(self) -> Any:
        if self._capture is None:
            raise CaptureFatalError("MSS capture has not been started")
        return self._capture



def normalize_mss_monitors(
    raw_monitors: list[dict[str, Any]],
) -> list[MonitorInfo]:
    """Normalize MSS's aggregate-plus-physical monitor collection."""

    if len(raw_monitors) < 2:
        return []
    monitors = [
        MonitorInfo(
            id=str(index),
            index=index,
            left=int(raw.get("left", 0)),
            top=int(raw.get("top", 0)),
            width=int(raw.get("width", 0)),
            height=int(raw.get("height", 0)),
            is_primary=bool(raw.get("is_primary", False)),
        )
        for index, raw in enumerate(raw_monitors[1:], start=1)
        if int(raw.get("width", 0)) > 0 and int(raw.get("height", 0)) > 0
    ]
    if monitors and not any(monitor.is_primary for monitor in monitors):
        primary = next(
            (
                monitor
                for monitor in monitors
                if monitor.left == 0 and monitor.top == 0
            ),
            monitors[0],
        )
        monitors = [
            MonitorInfo(
                id=monitor.id,
                index=monitor.index,
                left=monitor.left,
                top=monitor.top,
                width=monitor.width,
                height=monitor.height,
                is_primary=monitor.id == primary.id,
            )
            for monitor in monitors
        ]
    return monitors
