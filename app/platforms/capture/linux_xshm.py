"""Linux X11 capture backed by XCB MIT-SHM shared-memory transfers."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from enum import Enum
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
from app.platforms.capture.mss_fallback import normalize_mss_monitors

LOGGER = logging.getLogger(__name__)


class XShmAvailability(str, Enum):
    """Whether the selected MSS Linux engine is actually using MIT-SHM."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


AvailabilityReader = Callable[[Any], XShmAvailability]


class XShmCapture:
    """Capture X11 displays through MIT-SHM without hiding native fallback."""

    name = "linux_xshm"

    def __init__(
        self,
        *,
        display: str | None = None,
        capture_factory: Callable[[], Any] | None = None,
        availability_reader: AvailabilityReader | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._display = display
        self._capture_factory = capture_factory or self._create_capture
        self._availability_reader = availability_reader or _read_xshm_availability
        self._clock_ns = clock_ns
        self._capture: Any | None = None
        self._monitors: list[MonitorInfo] = []
        self._raw_monitors: dict[str, dict[str, Any]] = {}
        self._sequences: dict[str, int] = {}
        self._last_frame_ns: dict[str, int] = {}
        self._availability = XShmAvailability.UNKNOWN

    def start(self) -> None:
        if self._capture is not None:
            return
        capture: Any | None = None
        try:
            capture = self._capture_factory()
            availability = self._availability_reader(capture)
            if availability is XShmAvailability.UNAVAILABLE:
                raise CaptureUnavailableError("MIT-SHM is unavailable")
            raw_monitors = list(capture.monitors)
            monitors = normalize_mss_monitors(raw_monitors)
            if not monitors:
                raise CaptureUnavailableError("XShm found no physical displays")
        except CaptureUnavailableError:
            _close_capture(capture)
            raise
        except Exception as error:
            _close_capture(capture)
            raise CaptureUnavailableError(
                f"XShm initialization failed: {error}"
            ) from error

        self._capture = capture
        self._availability = availability
        self._monitors = monitors
        self._raw_monitors = {
            monitor.id: dict(raw_monitors[monitor.index]) for monitor in monitors
        }
        self._sequences = {monitor.id: 0 for monitor in monitors}
        self._last_frame_ns = {}

    def stop(self) -> None:
        capture = self._capture
        self._capture = None
        self._monitors = []
        self._raw_monitors = {}
        self._sequences = {}
        self._last_frame_ns = {}
        self._availability = XShmAvailability.UNKNOWN
        _close_capture(capture)

    def monitors(self) -> list[MonitorInfo]:
        self._require_started()
        return list(self._monitors)

    def get_latest_frame(self, monitor_id: str) -> CaptureFrame:
        capture = self._require_started()
        key = str(monitor_id)
        monitor = self._raw_monitors.get(key)
        if monitor is None:
            raise CaptureFatalError(f"Unknown XShm monitor id: {monitor_id}")
        try:
            screenshot = capture.grab(monitor)
        except ScreenShotError as error:
            raise CaptureRecoverableError(f"XShm capture failed: {error}") from error

        availability = self._availability_reader(capture)
        self._availability = availability
        if availability is not XShmAvailability.AVAILABLE:
            raise CaptureRecoverableError(
                "MIT-SHM did not remain active; switch to MSS fallback"
            )

        width, height = screenshot.size
        pixels = np.frombuffer(screenshot.bgra, dtype=np.uint8)
        try:
            bgra = pixels.reshape((height, width, 4))
        except ValueError as error:
            raise CaptureFatalError("XShm returned an invalid BGRA frame") from error

        now = self._clock_ns()
        sequence = self._sequences[key] + 1
        self._sequences[key] = sequence
        self._last_frame_ns[key] = now
        return CaptureFrame(
            image=np.ascontiguousarray(bgra[:, :, :3]),
            monitor_id=key,
            timestamp_ns=now,
            sequence=sequence,
            changed_regions=None,
            backend=self.name,
        )

    def status(self) -> CaptureBackendStatus:
        started = self._capture is not None
        now = self._clock_ns()
        newest = max(self._last_frame_ns.values(), default=None)
        age_ms = None if newest is None else max(0.0, (now - newest) / 1_000_000)
        unavailable = self._availability is XShmAvailability.UNAVAILABLE
        return CaptureBackendStatus(
            preferred_backend=self.name,
            active_backend=self.name if started else None,
            fallback=False,
            fallback_reason=None,
            healthy=started and not unavailable,
            error="MIT-SHM is unavailable" if started and unavailable else None,
            session="x11" if started else None,
            monitor_count=len(self._monitors),
            frame_age_ms=age_ms,
        )

    def _create_capture(self) -> MSS:
        return MSS(backend="xshmgetimage", display=self._display)

    def _require_started(self) -> Any:
        if self._capture is None:
            raise CaptureFatalError("XShm capture has not been started")
        return self._capture


def _read_xshm_availability(capture: Any) -> XShmAvailability:
    """Read mss 10.2's native engine state behind one compatibility seam."""

    implementation = getattr(capture, "_impl", None)
    status = getattr(implementation, "shm_status", None)
    name = str(getattr(status, "name", "")).casefold()
    try:
        return XShmAvailability(name)
    except ValueError as error:
        raise RuntimeError("MSS does not expose XShm availability") from error


def _close_capture(capture: Any | None) -> None:
    if capture is None:
        return
    try:
        capture.close()
    except Exception:
        LOGGER.debug("Could not close XShm capture", exc_info=True)
