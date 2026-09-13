"""Tests for the NORMAL-only vision pipeline wrapper."""

import unittest

import numpy as np

from app.platforms.capture.models import CaptureFrame
from app.vision.decision import DecisionEngine
from app.vision.detectors.base import DetectionEvidence
from app.vision.pipeline import VisionPipeline
from app.vision.violation_policy import (
    ViolationEvidenceType,
    VisualViolationClassification,
)
from app.vision.yolo_adapter import Yolo11Adapter


class FakeDetector:
    def __init__(self, evidence: list[DetectionEvidence] | None = None) -> None:
        self.evidence = list(evidence or [])
        self.checked = 0

    def detect(self, image: object, *, input_size: int = 640) -> list[DetectionEvidence]:
        del input_size
        self.checked += 1
        self.image = image
        return list(self.evidence)


class FakeYolo:
    def detect(self, image: np.ndarray) -> list[dict[str, object]]:
        self.image_shape = image.shape
        return [{"class": "blowjob", "score": 0.91, "box": [1, 1, 4, 4]}]


def frame() -> CaptureFrame:
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    return CaptureFrame(image=image, sequence=3)


class VisionPipelineTests(unittest.TestCase):
    def test_nudenet_only_pipeline_classifies_clear_without_yolo(self) -> None:
        detector = FakeDetector()
        pipeline = VisionPipeline(detector, DecisionEngine())

        result = pipeline.evaluate(frame())

        self.assertEqual(pipeline.evaluate_calls, 1)
        self.assertEqual(detector.checked, 1)
        self.assertIs(result.classification, VisualViolationClassification.CLEAR)

    def test_yolo_sexual_act_enters_visual_decision(self) -> None:
        detector = FakeDetector()
        pipeline = VisionPipeline(
            detector,
            DecisionEngine(),
            yolo_adapter=Yolo11Adapter(FakeYolo()),
        )

        result = pipeline.evaluate(frame())

        self.assertIs(result.classification, VisualViolationClassification.VIOLATION)
        self.assertEqual(result.reason_codes, ("yolo_sexual_act",))
        evidence_types = {item.evidence_type for item in result.evidence}
        self.assertIn(ViolationEvidenceType.SEXUAL_ACT, evidence_types)


if __name__ == "__main__":
    unittest.main()
