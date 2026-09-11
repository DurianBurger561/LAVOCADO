"""Capture and resize the primary screen."""

from __future__ import annotations

import mss
import numpy as np
from PIL import Image

from app import config


class Capturer:
    """Capture the primary monitor as a BGR NumPy array."""

    def __init__(self, monitor_index: int = 1) -> None:
        self._capture = mss.mss()
        self._monitor_index = monitor_index

    def grab(self) -> np.ndarray:
        """Capture and resize one screen frame."""

        if not 0 < self._monitor_index < len(self._capture.monitors):
            raise ValueError(
                f"Monitor {self._monitor_index} is unavailable. "
                f"Found {len(self._capture.monitors) - 1} monitor(s)."
            )

        monitor = self._capture.monitors[self._monitor_index]
        screenshot = self._capture.grab(monitor)

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

    def __enter__(self) -> "Capturer":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
