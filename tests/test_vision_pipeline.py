"""Tests for the NORMAL-only vision pipeline wrapper."""

import unittest

import numpy as np

from app.vision.capture import CapturedFrame
from app.vision.decision import DecisionEngine
from app.vision.pipeline import VisionPipeline
from app.vision.violation_policy import ViolationEvidenceType
from app.vision.yolo_adapter import Yolo11Adapter


class FakeDetector:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.checked = 0

    def check(self, image: object) -> dict[str, object]:
        self.checked += 1
        self.image = image
        return dict(self.result)


class FakeYolo:
    def detect(self, image: np.ndarray) -> list[dict[str, object]]:
        self.image_shape = image.shape
        return [{"class": "blowjob", "score": 0.91, "box": [1, 1, 4, 4]}]


def frame() -> CapturedFrame:
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    return CapturedFrame(original_frame=image, model_frame=image, sequence=3)


class VisionPipelineTests(unittest.TestCase):
    def test_nudenet_only_pipeline_classifies_clear_without_yolo(self) -> None:
        detector = FakeDetector(
            {
                "blocked": False,
                "reason": "",
                "label": None,
                "confidence": 0.0,
                "box": None,
                "check_points": [],
            }
        )
        pipeline = VisionPipeline(detector, DecisionEngine())

        result = pipeline.evaluate(frame())

        self.assertEqual(pipeline.evaluate_calls, 1)
        self.assertEqual(detector.checked, 1)
        self.assertEqual(result["classification"], "clear")
        self.assertFalse(result["blocked"])

    def test_yolo_sexual_act_enters_visual_decision(self) -> None:
        detector = FakeDetector(
            {
                "blocked": False,
                "reason": "",
                "label": None,
                "confidence": 0.0,
                "box": None,
                "check_points": [],
            }
        )
        pipeline = VisionPipeline(
            detector,
            DecisionEngine(),
            yolo_adapter=Yolo11Adapter(FakeYolo()),
        )

        result = pipeline.evaluate(frame())

        self.assertEqual(result["classification"], "violation")
        self.assertEqual(result["source"], "yolo_sexual_act")
        evidence_types = {
            item["evidence_type"]
            for item in result.get("evidence", [])
            if isinstance(item, dict)
        }
        self.assertIn(ViolationEvidenceType.SEXUAL_ACT.value, evidence_types)


if __name__ == "__main__":
    unittest.main()
