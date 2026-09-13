"""Adapt platform capture frames for the vision pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

import numpy as np
from PIL import Image

from app import config
from app.platforms import PlatformAdapter
from app.platforms.capture import (
    CaptureBackendStatus,
    CaptureFatalError,
    MonitorInfo,
    Rect,
    ScreenCaptureBackend,
)


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """One full-resolution frame and its bounded NudeNet input."""

    original_frame: np.ndarray
    model_frame: np.ndarray
    monitor_id: str = ""
    timestamp_ns: int = 0
    sequence: int = 0
    changed_regions: tuple[Rect, ...] | None = None
    backend: str = "unknown"


class Capturer:
    """Consume a platform backend without depending on its native API."""

    def __init__(
        self,
        platform_adapter: PlatformAdapter,
        monitor_index: int | None = config.MONITOR_INDEX,
        *,
        backend: ScreenCaptureBackend | None = None,
        model_frame_max_edge: int | None = None,
    ) -> None:
        self._capture = (
            platform_adapter.create_screen_capture() if backend is None else backend
        )
        self._capture.start()
        self._configured_monitor_index = monitor_index
        self._monitors: list[MonitorInfo] = self._capture.monitors()
        self._monitor_by_index = {monitor.index: monitor for monitor in self._monitors}
        self._monitor_index = self._select_monitor_index(monitor_index)
        self._model_frame_max_edge = int(
            config.MODEL_FRAME_MAX_EDGE if model_frame_max_edge is None else model_frame_max_edge
        )

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

    def grab(self, monitor_index: int | None = None) -> CapturedFrame:
        """Return one fresh BGR frame and a bounded copy for NudeNet."""

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
        original_frame = self._validate_frame(captured.image)

        rgb_frame = np.ascontiguousarray(original_frame[:, :, ::-1])
        model_image = Image.fromarray(rgb_frame, mode="RGB")
        model_image.thumbnail(
            (self._model_frame_max_edge, self._model_frame_max_edge),
            Image.Resampling.LANCZOS,
        )
        model_rgb = np.asarray(model_image, dtype=np.uint8)
        model_frame = np.ascontiguousarray(model_rgb[:, :, ::-1])
        return CapturedFrame(
            original_frame=original_frame,
            model_frame=model_frame,
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
