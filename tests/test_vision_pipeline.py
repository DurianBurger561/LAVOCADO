"""Tests for the NORMAL-only vision pipeline wrapper."""

import unittest
from unittest.mock import patch

import numpy as np

from app.platforms.capture.models import CaptureFrame
from app.vision.decision import DecisionEngine
from app.vision.pipeline import VisionPipeline
from app.vision.preprocessor import FramePreprocessor
from app.vision.violation_policy import (
    ViolationEvidence,
    ViolationEvidenceType,
    VisualViolationClassification,
)
from app.vision.yolo_adapter import Yolo11Adapter


class FakeDetector:
    def __init__(self, evidence: list[ViolationEvidence] | None = None) -> None:
        self.evidence = list(evidence or [])
        self.checked = 0

    def detect(
        self, image: object, *, input_size: int = 640, frame_sequence: int
    ) -> list[ViolationEvidence]:
        del input_size, frame_sequence
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
    def test_reset_clears_shadow_and_resets_decision_state_once(self) -> None:
        engine = DecisionEngine()
        pipeline = VisionPipeline(FakeDetector(), engine)
        pipeline.last_shadow = {"hit": True}

        with patch.object(engine, "reset", wraps=engine.reset) as reset:
            pipeline.reset()

        self.assertEqual(reset.call_count, 1)
        self.assertIsNone(pipeline.last_shadow)

    def test_plans_per_monitor_and_skips_full_detector_for_focused_roi(self) -> None:
        captured = frame()
        prepared = FramePreprocessor(captured)
        detector = FakeDetector()
        local_detector = FakeDetector()
        decision_engine = DecisionEngine(local_detector=local_detector)
        decision_engine.tracker.match_or_create(
            monitor_index=1,
            box=(1, 1, 4, 4),
            label="FEMALE_BREAST_EXPOSED",
            confidence=0.9,
            source="nudenet_full",
            frame_sequence=2,
            evidence_delta=1.0,
        )
        pipeline = VisionPipeline(detector, decision_engine)

        with patch.object(
            decision_engine.scan_planner,
            "prepare_scan",
            wraps=decision_engine.scan_planner.prepare_scan,
        ) as plan_scan:
            focused = pipeline.prepare_scan(
                captured, 1, prepared_frame=prepared
            )
            normal = pipeline.prepare_scan(captured, 2, prepared_frame=prepared)
            result = pipeline.evaluate(
                captured, monitor_index=1, scan_plan=focused,
                prepared_frame=prepared,
            )

        self.assertEqual(focused.mode, "focused")
        self.assertNotEqual(normal.mode, "focused")
        self.assertEqual(plan_scan.call_count, 2)
        self.assertEqual(detector.checked, 0)
        self.assertEqual(local_detector.checked, 1)
        self.assertEqual(result.scan_mode, "focused")
        self.assertEqual(decision_engine.scheduler.last_plan(1), focused)
        self.assertEqual(decision_engine.scheduler.last_plan(2), normal)

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
        self.assertIs(result.evidence_type, ViolationEvidenceType.SEXUAL_ACT)
        evidence_types = {item.evidence_type for item in result.evidence}
        self.assertIn(ViolationEvidenceType.SEXUAL_ACT, evidence_types)


if __name__ == "__main__":
    unittest.main()
