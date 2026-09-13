"""Tests for the optional YOLO11 evidence adapter."""

import unittest

import numpy as np

from app.vision.violation_policy import ViolationEvidenceType
from app.vision.yolo_adapter import Yolo11Adapter, load_yolo_adapter


class FakeYolo:
    def __init__(self, detections: list[dict[str, object]]) -> None:
        self.detections = detections
        self.received = 0

    def detect(self, image: np.ndarray) -> list[dict[str, object]]:
        self.received += 1
        self.image_shape = image.shape
        return self.detections


class YoloAdapterTests(unittest.TestCase):
    def test_detect_evidence_uses_shared_policy(self) -> None:
        model = FakeYolo(
            [{"class": "oral-sex", "score": 0.92, "box": [2, 2, 8, 8]}]
        )
        adapter = Yolo11Adapter(model)

        evidence = adapter.detect_evidence(
            np.zeros((16, 16, 3), dtype=np.uint8),
            frame_sequence=9,
        )

        self.assertEqual(model.received, 1)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].evidence_type, ViolationEvidenceType.SEXUAL_ACT)
        self.assertEqual(evidence[0].frame_sequence, 9)
        self.assertEqual(evidence[0].model, "yolo11")

    def test_non_array_input_returns_no_evidence(self) -> None:
        adapter = Yolo11Adapter(FakeYolo([]))

        self.assertEqual(adapter.detect_evidence(1, frame_sequence=1), [])  # type: ignore[arg-type]

    def test_loader_stays_off_by_default(self) -> None:
        self.assertIsNone(load_yolo_adapter())


if __name__ == "__main__":
    unittest.main()
