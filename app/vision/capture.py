"""Adapt platform capture frames for the vision pipeline."""

from __future__ import annotations

from typing import Self

import numpy as np

from app.platforms import PlatformAdapter
from app.platforms.capture import (
    CaptureBackendStatus,
    CaptureFatalError,
    CaptureFrame,
    MonitorInfo,
    ScreenCaptureBackend,
)


class Capturer:
    """Consume a platform backend without depending on its native API."""

    def __init__(
        self,
        platform_adapter: PlatformAdapter,
        monitor_index: int | None = None,
        *,
        backend: ScreenCaptureBackend | None = None,
    ) -> None:
        self._capture = (
            platform_adapter.create_screen_capture() if backend is None else backend
        )
        self._capture.start()
        self._configured_monitor_index = monitor_index
        self._monitors: list[MonitorInfo] = self._capture.monitors()
        self._monitor_by_index = {monitor.index: monitor for monitor in self._monitors}
        self._monitor_index = self._select_monitor_index(monitor_index)

    @property
    def monitor_indexes(self) -> tuple[int, ...]:
        """Return every monitored physical screen index."""

        if self._configured_monitor_index is not None:
            return (self._monitor_index,)
        return tuple(monitor.index for monitor in self._monitors)

    @property
    def status(self) -> CaptureBackendStatus:
        """Return the active backend's privacy-safe status."""

        return self._capture.status()

    def grab(self, monitor_index: int | None = None) -> CaptureFrame:
        """Return one fresh full-resolution BGR frame."""

        selected_index = self._monitor_index if monitor_index is None else monitor_index
        monitor = self._monitor_by_index.get(selected_index)
        if monitor is None:
            raise ValueError(
                f"Monitor {selected_index} is unavailable. "
                f"Found {len(self._monitors)} monitor(s)."
            )
        captured = self._capture.get_latest_frame(monitor.id)
        if captured is None:
            raise CaptureFatalError(
                f"Capture backend returned no frame for monitor {monitor.id}"
            )
        return CaptureFrame(
            image=self._validate_frame(captured.image),
            monitor_id=captured.monitor_id,
            timestamp_ns=captured.timestamp_ns,
            sequence=captured.sequence,
            changed_regions=captured.changed_regions,
            backend=captured.backend,
        )

    def monitor_index_at(self, x: int, y: int) -> int | None:
        """Map a virtual-desktop point to a monitored physical screen."""

        for monitor in self._monitors:
            if monitor.contains(x, y) and monitor.index in self.monitor_indexes:
                return monitor.index
        return None

    def monitor_for_index(self, monitor_index: int | None = None) -> MonitorInfo:
        """Return geometry from the active capture backend's monitor topology."""

        self._monitors = self._capture.monitors()
        self._monitor_by_index = {monitor.index: monitor for monitor in self._monitors}
        selected = self._monitor_index if monitor_index is None else monitor_index
        monitor = self._monitor_by_index.get(selected)
        if monitor is None:
            raise ValueError(f"Monitor {selected} is unavailable")
        return monitor

    def close(self) -> None:
        """Release the selected platform capture backend."""

        self._capture.stop()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _select_monitor_index(self, preferred_index: int | None) -> int:
        if not self._monitors:
            self._capture.stop()
            raise CaptureFatalError("No physical monitor is available")
        if preferred_index is not None:
            if preferred_index not in self._monitor_by_index:
                self._capture.stop()
                raise ValueError(
                    f"Monitor {preferred_index} is unavailable. "
                    f"Found {len(self._monitors)} monitor(s)."
                )
            return preferred_index
        primary = next(
            (monitor for monitor in self._monitors if monitor.is_primary),
            self._monitors[0],
        )
        return primary.index

    @staticmethod
    def _validate_frame(image: np.ndarray) -> np.ndarray:
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise CaptureFatalError(
                "Capture backend must return a BGR uint8 H x W x 3 frame"
            )
        return np.ascontiguousarray(image)
