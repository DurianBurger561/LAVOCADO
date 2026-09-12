"""Tests for full-resolution and model-sized screen capture."""

import unittest
from unittest.mock import patch

import numpy as np

from app.vision.capture import Capturer


class FakeScreenshot:
    size = (8, 4)
    bgra = bytes([10, 20, 30, 255] * 32)


class FakeMSS:
    def __init__(self) -> None:
        self.monitors = [
            {"left": 0, "top": 0, "width": 8, "height": 4},
            {"left": 0, "top": 0, "width": 8, "height": 4},
        ]
        self.closed = False

    def grab(self, _monitor: dict[str, int]) -> FakeScreenshot:
        return FakeScreenshot()

    def close(self) -> None:
        self.closed = True


class CaptureTests(unittest.TestCase):
    @patch("app.vision.capture.prepare_desktop_environment")
    @patch("app.vision.capture.MSS", return_value=FakeMSS())
    def test_retains_original_and_bounds_model_frame(
        self,
        _mss: object,
        _prepare: object,
    ) -> None:
        with patch("app.vision.capture.config.MODEL_FRAME_MAX_EDGE", 4):
            capturer = Capturer()
            captured = capturer.grab(1)

        self.assertEqual(captured.original_frame.shape, (4, 8, 3))
        self.assertEqual(captured.model_frame.shape, (2, 4, 3))
        self.assertEqual(captured.original_frame.dtype, np.uint8)
        self.assertEqual(captured.model_frame.dtype, np.uint8)
        self.assertTrue(captured.original_frame.flags.c_contiguous)
        self.assertTrue(captured.model_frame.flags.c_contiguous)

    @patch("app.vision.capture.prepare_desktop_environment")
    @patch("app.vision.capture.MSS", return_value=FakeMSS())
    def test_does_not_upscale_small_screen(
        self,
        _mss: object,
        _prepare: object,
    ) -> None:
        with patch("app.vision.capture.config.MODEL_FRAME_MAX_EDGE", 16):
            captured = Capturer().grab(1)

        self.assertEqual(captured.original_frame.shape, (4, 8, 3))
        self.assertEqual(captured.model_frame.shape, (4, 8, 3))


if __name__ == "__main__":
    unittest.main()
