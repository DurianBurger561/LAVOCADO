"""Capture full-resolution screens and prepare NudeNet model frames."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

import numpy as np
from mss import MSS
from mss.exception import ScreenShotError
from PIL import Image

from app import config
from app.platforms import PlatformAdapter, ScreenCaptureError
from app.vision.monitors import monitor_index_at_point, select_monitor_index


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """One in-memory screen capture and its bounded model input."""

    original_frame: np.ndarray
    model_frame: np.ndarray


class Capturer:
    """Capture physical monitors without discarding the original pixels."""

    def __init__(
        self,
        platform_adapter: PlatformAdapter,
        monitor_index: int | None = config.MONITOR_INDEX,
    ) -> None:
        self._platform = platform_adapter
        self._capture = MSS()
        self._configured_monitor_index = monitor_index
        self._monitor_index = select_monitor_index(
            self._capture.monitors,
            monitor_index,
        )

    @property
    def monitor_indexes(self) -> tuple[int, ...]:
        """Return every monitored physical screen index."""

        if self._configured_monitor_index is not None:
            return (self._monitor_index,)
        return tuple(range(1, len(self._capture.monitors)))

    def grab(self, monitor_index: int | None = None) -> CapturedFrame:
        """Capture one screen and return original and model-sized BGR frames."""

        selected_index = (
            self._monitor_index
            if monitor_index is None
            else select_monitor_index(self._capture.monitors, monitor_index)
        )
        monitor = self._capture.monitors[selected_index]
        try:
            screenshot = self._capture.grab(monitor)
        except ScreenShotError as error:
            raise ScreenCaptureError(
                self._platform.screen_capture_help()
            ) from error

        # MSS provides BGRA bytes. Convert them into a PIL RGB image.
        image = Image.frombytes(
            "RGB",
            screenshot.size,
            screenshot.bgra,
            "raw",
            "BGRX",
        )

        original_rgb = np.asarray(image, dtype=np.uint8)
        original_frame = np.ascontiguousarray(original_rgb[:, :, ::-1])

        model_image = image.copy()
        model_image.thumbnail(
            (config.MODEL_FRAME_MAX_EDGE, config.MODEL_FRAME_MAX_EDGE),
            Image.Resampling.LANCZOS,
        )

        # NudeNet/OpenCV-style arrays use BGR channel order.
        model_rgb = np.asarray(model_image, dtype=np.uint8)
        model_frame = np.ascontiguousarray(model_rgb[:, :, ::-1])
        return CapturedFrame(
            original_frame=original_frame,
            model_frame=model_frame,
        )

    def monitor_index_at(self, x: int, y: int) -> int | None:
        """Map a virtual-desktop point to a monitored physical screen."""

        monitor_index = monitor_index_at_point(self._capture.monitors, x, y)
        if monitor_index not in self.monitor_indexes:
            return None
        return monitor_index

    def close(self) -> None:
        """Release screen-capture resources."""

        self._capture.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
