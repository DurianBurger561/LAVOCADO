"""Tests for the LAVOCADO vision decision layer."""

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from app.vision.detector import Detector


class FakeModel:
    def __init__(self, detections: list[dict[str, Any]]) -> None:
        self.detections = detections

    def detect(self, image: np.ndarray) -> list[dict[str, Any]]:
        return self.detections


class DetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.image = np.zeros((320, 320, 3), dtype=np.uint8)

    def test_allows_non_blocking_detections(self) -> None:
        model = FakeModel(
            [
                {"class": "FACE_FEMALE", "score": 0.99, "box": [0, 0, 10, 10]},
                {
                    "class": "FEMALE_BREAST_EXPOSED",
                    "score": 0.64,
                    "box": [0, 0, 10, 10],
                },
            ]
        )

        result = Detector(model=model).check(self.image)

        self.assertFalse(result["blocked"])
        self.assertIsNone(result["label"])
        self.assertEqual(result["confidence"], 0.0)

    def test_blocks_detection_over_its_threshold(self) -> None:
        model = FakeModel(
            [
                {
                    "class": "FEMALE_GENITALIA_EXPOSED",
                    "score": 0.81,
                    "box": [0, 0, 10, 10],
                }
            ]
        )

        result = Detector(model=model).check(self.image)

        self.assertTrue(result["blocked"])
        self.assertEqual(result["label"], "FEMALE_GENITALIA_EXPOSED")
        self.assertAlmostEqual(result["confidence"], 0.81)

    def test_chooses_strongest_blocking_detection(self) -> None:
        model = FakeModel(
            [
                {
                    "class": "ANUS_EXPOSED",
                    "score": 0.71,
                    "box": [0, 0, 10, 10],
                },
                {
                    "class": "FEMALE_BREAST_EXPOSED",
                    "score": 0.88,
                    "box": [0, 0, 10, 10],
                },
            ]
        )

        result = Detector(model=model).check(self.image)

        self.assertEqual(result["label"], "FEMALE_BREAST_EXPOSED")
        self.assertAlmostEqual(result["confidence"], 0.88)

    def test_loads_640m_with_640_pixel_inference(self) -> None:
        calls: list[dict[str, object]] = []

        def factory(**kwargs: object) -> FakeModel:
            calls.append(kwargs)
            return FakeModel([])

        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "640m.onnx"
            model_path.touch()
            detector = Detector(model_factory=factory, model_path=model_path)

        self.assertEqual(
            calls,
            [{"model_path": str(model_path), "inference_resolution": 640}],
        )
        self.assertEqual(detector.model_variant, "640m")
        self.assertEqual(detector.inference_resolution, 640)

    @patch("app.vision.detector.resolve_nudenet_model_path", return_value=None)
    def test_falls_back_to_bundled_320n_when_640m_is_missing(
        self,
        _resolve: object,
    ) -> None:
        calls: list[dict[str, object]] = []

        def factory(**kwargs: object) -> FakeModel:
            calls.append(kwargs)
            return FakeModel([])

        detector = Detector(model_factory=factory)

        self.assertEqual(calls, [{"inference_resolution": 320}])
        self.assertEqual(detector.model_variant, "320n-fallback")
        self.assertEqual(detector.inference_resolution, 320)

    def test_falls_back_when_640m_cannot_be_loaded(self) -> None:
        calls: list[dict[str, object]] = []

        def factory(**kwargs: object) -> FakeModel:
            calls.append(kwargs)
            if "model_path" in kwargs:
                raise ValueError("bad model")
            return FakeModel([])

        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "640m.onnx"
            model_path.touch()
            detector = Detector(model_factory=factory, model_path=model_path)

        self.assertEqual(calls[-1], {"inference_resolution": 320})
        self.assertEqual(detector.model_variant, "320n-fallback")


if __name__ == "__main__":
    unittest.main()
