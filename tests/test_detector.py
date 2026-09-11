"""Tests for the LAVOCADO vision decision layer."""

import unittest
from typing import Any

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


if __name__ == "__main__":
    unittest.main()
