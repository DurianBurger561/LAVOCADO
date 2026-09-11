"""Capture and resize the primary screen."""

from __future__ import annotations

from typing import Self

import numpy as np
from mss import MSS
from mss.exception import ScreenShotError
from PIL import Image

from app import config
from app.platform_support import (
    ScreenCaptureError,
    prepare_desktop_environment,
    screen_capture_help,
)
from app.vision.monitors import select_monitor_index


class Capturer:
    """Capture physical monitors as BGR NumPy arrays."""

    def __init__(self, monitor_index: int | None = config.MONITOR_INDEX) -> None:
        prepare_desktop_environment()
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

    def grab(self, monitor_index: int | None = None) -> np.ndarray:
        """Capture and resize one frame from the requested screen."""

        selected_index = (
            self._monitor_index
            if monitor_index is None
            else select_monitor_index(self._capture.monitors, monitor_index)
        )
        monitor = self._capture.monitors[selected_index]
        try:
            screenshot = self._capture.grab(monitor)
        except ScreenShotError as error:
            raise ScreenCaptureError(screen_capture_help()) from error

        # MSS provides BGRA bytes. Convert them into a PIL RGB image.
        image = Image.frombytes(
            "RGB",
            screenshot.size,
            screenshot.bgra,
            "raw",
            "BGRX",
        )

        image.thumbnail(
            (config.THUMBNAIL_SIZE, config.THUMBNAIL_SIZE),
            Image.Resampling.LANCZOS,
        )

        # NudeNet/OpenCV-style arrays use BGR channel order.
        rgb_frame = np.asarray(image, dtype=np.uint8)
        return np.ascontiguousarray(rgb_frame[:, :, ::-1])

    def close(self) -> None:
        """Release screen-capture resources."""

        self._capture.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
