"""Tests for visual-violation decisions. Viddexa ranks tiles and cannot block."""

import inspect
import unittest

import numpy as np

from app.platforms.capture.models import CaptureFrame
from app.vision.context.base import ContextResult
from app.vision.decision import DecisionEngine
from app.vision.detectors.base import DetectionEvidence
from app.vision.primary_detector_set import PrimaryDetection
from app.vision.violation_policy import (
    ViolationEvidence,
    ViolationEvidenceType,
    VisualViolationClassification,
)


class FakeContextClassifier:
    def __init__(
        self,
        scores: dict[str, float] | None,
        scores_by_mean: dict[int, dict[str, float]] | None = None,
    ) -> None:
        self.scores = scores
        self.scores_by_mean = scores_by_mean
        self.received_shapes: list[tuple[int, ...]] = []
        self.received_means: list[int] = []

    def classify(self, image: np.ndarray) -> dict[str, float] | None:
        self.received_shapes.append(image.shape)
        image_mean = int(image.mean())
        self.received_means.append(image_mean)
        if self.scores_by_mean is not None:
            return self.scores_by_mean[image_mean]
        return self.scores

    def classify_batch(self, frames: list[np.ndarray]) -> list[ContextResult]:
        return [
            ContextResult(scores=self.classify(frame) or {}, model="fake")
            for frame in frames
        ]


class FakeLocalDetector:
    inference_resolution = 640

    def __init__(self, candidates: list[bool]) -> None:
        self._candidates = iter(candidates)
        self.received_means: list[int] = []

    def detect(self, image: np.ndarray, *, input_size: int) -> list[DetectionEvidence]:
        del input_size
        self.received_means.append(int(image.mean()))
        candidate = next(self._candidates, False)
        if not candidate:
            return []
        return [
            DetectionEvidence(
                label="FEMALE_BREAST_EXPOSED",
                confidence=0.80,
                box=(0.0, 0.0, 1.0, 1.0),
                model="nudenet_640m",
            )
        ]


def captured_frame() -> CaptureFrame:
    return CaptureFrame(
        image=np.zeros((1080, 1920, 3), dtype=np.uint8),
        sequence=4,
    )


def result_with_detection(score: float) -> PrimaryDetection:
    return PrimaryDetection.from_primary(
        (
            DetectionEvidence(
                "FEMALE_BREAST_EXPOSED",
                score,
                (100, 50, 200, 100),
                "nudenet_640m",
            ),
        ),
        frame_sequence=4,
    )


def rescue_frame() -> CaptureFrame:
    original = np.zeros((4, 4, 3), dtype=np.uint8)
    original[0:2, 0:2] = 10
    original[0:2, 2:4] = 20
    original[2:4, 0:2] = 30
    original[2:4, 2:4] = 40
    return CaptureFrame(
        image=original,
        sequence=1,
    )


def empty_result() -> PrimaryDetection:
    return PrimaryDetection.from_primary((), frame_sequence=1)


class DecisionEngineTests(unittest.TestCase):
    def test_rescue_ranks_all_tiles_and_skips_low_risk(self) -> None:
        low_context = {"normal": 0.99, "porn": 0.01}
        context = FakeContextClassifier(low_context)
        local_detector = FakeLocalDetector([False])
        engine = DecisionEngine(context, local_detector)

        result = engine.evaluate(empty_result(), rescue_frame(), monitor_index=1)

        self.assertIsNot(result.classification, VisualViolationClassification.VIOLATION)
        self.assertIs(result.classification, VisualViolationClassification.CLEAR)
        self.assertEqual(context.received_means, [10, 20, 30, 40])
        self.assertEqual(local_detector.received_means, [10])
        self.assertIsNotNone(result.rescue_tile_index)

    def test_high_porn_needs_local_nudenet_candidate(self) -> None:
        context = FakeContextClassifier({"porn": 0.99})
        local_detector = FakeLocalDetector([False])

        result = DecisionEngine(context, local_detector).evaluate(
            empty_result(),
            rescue_frame(),
            monitor_index=1,
        )

        self.assertIsNot(result.classification, VisualViolationClassification.VIOLATION)
        self.assertIs(result.classification, VisualViolationClassification.CLEAR)
        self.assertEqual(len(local_detector.received_means), 1)

    def test_viddexa_cannot_block_without_primary_evidence(self) -> None:
        context = FakeContextClassifier({"porn": 0.99, "hentai": 0.99})
        local_detector = FakeLocalDetector([False])

        result = DecisionEngine(context, local_detector).evaluate(
            empty_result(),
            rescue_frame(),
            monitor_index=1,
        )

        self.assertIsNot(result.classification, VisualViolationClassification.VIOLATION)

    def test_local_nudenet_candidate_enters_rescue_temporal_path(self) -> None:
        context = FakeContextClassifier({"porn": 0.99})
        local_detector = FakeLocalDetector([True])

        result = DecisionEngine(context, local_detector).evaluate(
            empty_result(),
            rescue_frame(),
            monitor_index=2,
        )

        self.assertIs(result.classification, VisualViolationClassification.VIOLATION)
        self.assertIs(result.classification, VisualViolationClassification.VIOLATION)
        self.assertEqual(result.reason_codes, ("rescue_tile",))
        self.assertEqual(result.label, "FEMALE_BREAST_EXPOSED")
        self.assertEqual(result.primary_region, (0, 0, 2, 2))
        self.assertEqual(result.rescue_tile_index, 0)

    def test_rescue_candidate_pins_highest_risk_tile(self) -> None:
        context = FakeContextClassifier({"porn": 0.99})
        local_detector = FakeLocalDetector([True])
        engine = DecisionEngine(context, local_detector)

        engine.evaluate(empty_result(), rescue_frame(), monitor_index=1)

        self.assertEqual(
            engine.rescue_status(1),
            {
                "next_tile_index": 1,
                "pinned_tile_index": 0,
                "pinned_checks_remaining": 2,
            },
        )

    def test_sexy_cannot_request_local_rescue_check(self) -> None:
        context = FakeContextClassifier({"porn": 0.0, "sexy": 0.99})
        local_detector = FakeLocalDetector([False])

        result = DecisionEngine(context, local_detector).evaluate(
            empty_result(),
            rescue_frame(),
            monitor_index=1,
        )

        self.assertIsNot(result.classification, VisualViolationClassification.VIOLATION)
        self.assertEqual(len(local_detector.received_means), 1)

    def test_tile_ranking_is_independent_per_monitor(self) -> None:
        context = FakeContextClassifier({"normal": 0.99, "porn": 0.01})
        engine = DecisionEngine(context, FakeLocalDetector([False]))

        engine.evaluate(empty_result(), rescue_frame(), monitor_index=1)
        engine.evaluate(empty_result(), rescue_frame(), monitor_index=2)

        self.assertEqual(context.received_means, [10, 20, 30, 40, 10, 20, 30, 40])
        self.assertIsNone(engine.rescue_status(1)["pinned_tile_index"])
        self.assertIsNone(engine.rescue_status(2)["pinned_tile_index"])

    def test_reset_clears_rescue_ranking_and_pinning(self) -> None:
        context = FakeContextClassifier({"normal": 0.99, "porn": 0.01})
        engine = DecisionEngine(context, FakeLocalDetector([False]))

        engine.evaluate(empty_result(), rescue_frame(), monitor_index=1)
        engine.reset()
        engine.evaluate(empty_result(), rescue_frame(), monitor_index=1)

        self.assertEqual(context.received_means, [10, 20, 30, 40, 10, 20, 30, 40])
        self.assertEqual(
            engine.rescue_status(1),
            {
                "next_tile_index": 1,
                "pinned_tile_index": None,
                "pinned_checks_remaining": 0,
            },
        )

    def test_decision_engine_accepts_only_visual_evidence(self) -> None:
        parameters = inspect.signature(DecisionEngine.evaluate).parameters
        self.assertNotIn("hostname", parameters)
        self.assertNotIn("application_name", parameters)
        self.assertNotIn("medical", parameters)

        result = DecisionEngine().evaluate(
            result_with_detection(0.80), captured_frame()
        )

        self.assertIs(result.classification, VisualViolationClassification.VIOLATION)
        self.assertNotEqual(result.label, "medical.example")
        self.assertNotIn("hostname", result.reason_codes)
        self.assertNotIn("medical", result.reason_codes)

    def test_strong_nudenet_candidate_does_not_need_context(self) -> None:
        context = FakeContextClassifier({"porn": 1.0})

        result = DecisionEngine(context).evaluate(
            result_with_detection(0.80),
            captured_frame(),
        )

        self.assertIs(result.classification, VisualViolationClassification.VIOLATION)
        self.assertIs(result.classification, VisualViolationClassification.VIOLATION)
        self.assertEqual(result.reason_codes, ("nudenet_full",))
        self.assertEqual(result.primary_region, (100, 50, 300, 150))
        self.assertEqual(context.received_shapes, [])

    def test_strong_anatomy_roi_recheck_confirms_violation(self) -> None:
        local_detector = FakeLocalDetector([True])

        result = DecisionEngine(None, local_detector).evaluate(
            result_with_detection(0.80),
            captured_frame(),
        )

        self.assertIs(result.classification, VisualViolationClassification.VIOLATION)
        self.assertIs(result.classification, VisualViolationClassification.VIOLATION)
        self.assertEqual(result.reason_codes, ("nudenet_roi",))
        self.assertEqual(local_detector.received_means, [0])

    def test_strong_anatomy_without_roi_confirmation_stays_uncertain(self) -> None:
        local_detector = FakeLocalDetector([False])

        result = DecisionEngine(None, local_detector).evaluate(
            result_with_detection(0.80),
            captured_frame(),
        )

        self.assertIsNot(result.classification, VisualViolationClassification.VIOLATION)
        self.assertIs(result.classification, VisualViolationClassification.UNCERTAIN)
        self.assertEqual(result.reason_codes, ("anatomy_candidate",))

    def test_borderline_roi_recheck_confirms_violation(self) -> None:
        local_detector = FakeLocalDetector([True])

        result = DecisionEngine(None, local_detector).evaluate(
            result_with_detection(0.60),
            captured_frame(),
        )

        self.assertIs(result.classification, VisualViolationClassification.VIOLATION)
        self.assertIs(result.classification, VisualViolationClassification.VIOLATION)
        self.assertEqual(result.label, "FEMALE_BREAST_EXPOSED")
        self.assertEqual(result.reason_codes, ("nudenet_roi",))
        self.assertEqual(result.primary_region, (25, 12, 375, 188))
        self.assertEqual(local_detector.received_means, [0])

    def test_viddexa_cannot_confirm_borderline_as_violation(self) -> None:
        context = FakeContextClassifier(
            {
                "normal": 0.03,
                "porn": 0.91,
                "hentai": 0.01,
                "sexy": 0.04,
                "drawing": 0.01,
            }
        )

        result = DecisionEngine(context).evaluate(
            result_with_detection(0.60),
            captured_frame(),
        )

        self.assertIsNot(result.classification, VisualViolationClassification.VIOLATION)
        self.assertIs(result.classification, VisualViolationClassification.UNCERTAIN)
        self.assertEqual(result.reason_codes, ("nudenet_borderline",))

    def test_borderline_without_roi_hit_stays_uncertain(self) -> None:
        local_detector = FakeLocalDetector([False])

        result = DecisionEngine(None, local_detector).evaluate(
            result_with_detection(0.60),
            captured_frame(),
        )

        self.assertIsNot(result.classification, VisualViolationClassification.VIOLATION)
        self.assertIs(result.classification, VisualViolationClassification.UNCERTAIN)
        self.assertEqual(result.reason_codes, ("nudenet_borderline",))

    def test_sexy_or_hentai_cannot_confirm_borderline(self) -> None:
        for label in ("sexy", "hentai"):
            with self.subTest(label=label):
                context = FakeContextClassifier({label: 0.99, "porn": 0.0})

                result = DecisionEngine(context).evaluate(
                    result_with_detection(0.60),
                    captured_frame(),
                )

                self.assertIsNot(result.classification, VisualViolationClassification.VIOLATION)
                self.assertIs(result.classification, VisualViolationClassification.UNCERTAIN)
                self.assertEqual(result.reason_codes, ("nudenet_borderline",))

    def test_context_cannot_block_without_a_nudenet_borderline(self) -> None:
        context = FakeContextClassifier({"porn": 0.99})

        result = DecisionEngine(context).evaluate(
            result_with_detection(0.20),
            captured_frame(),
        )

        self.assertIsNot(result.classification, VisualViolationClassification.VIOLATION)
        self.assertEqual(result.reason_codes, ("nudenet_none",))

    def test_missing_context_still_checks_a_tile(self) -> None:
        local_detector = FakeLocalDetector([True])

        result = DecisionEngine(None, local_detector).evaluate(
            empty_result(),
            rescue_frame(),
            monitor_index=1,
        )

        self.assertIs(result.classification, VisualViolationClassification.VIOLATION)
        self.assertEqual(result.reason_codes, ("rescue_tile",))
        self.assertEqual(len(local_detector.received_means), 1)

    def test_missing_or_failed_context_keeps_nudenet_only_result(self) -> None:
        for context in (None, FakeContextClassifier(None)):
            with self.subTest(context=context):
                result = DecisionEngine(context).evaluate(
                    result_with_detection(0.60),
                    captured_frame(),
                )

                self.assertIsNot(result.classification, VisualViolationClassification.VIOLATION)
                self.assertIs(result.classification, VisualViolationClassification.UNCERTAIN)
                self.assertEqual(result.reason_codes, ("nudenet_borderline",))

    def test_yolo_sexual_act_is_a_visual_violation(self) -> None:
        evidence = [
            ViolationEvidence(
                ViolationEvidenceType.SEXUAL_ACT,
                "blowjob",
                0.88,
                (10, 10, 40, 40),
                "yolo11",
                4,
            )
        ]

        result = DecisionEngine().evaluate(
            PrimaryDetection.from_primary(
                (), frame_sequence=4, supplementary=tuple(evidence)
            ),
            captured_frame(),
        )

        self.assertIs(result.classification, VisualViolationClassification.VIOLATION)
        self.assertIs(result.classification, VisualViolationClassification.VIOLATION)
        self.assertEqual(result.reason_codes, ("yolo_sexual_act",))
        self.assertEqual(result.label, "blowjob")

    def test_sexual_act_roi_recheck_confirms_violation(self) -> None:
        evidence = [
            ViolationEvidence(
                ViolationEvidenceType.SEXUAL_ACT,
                "blowjob",
                0.88,
                (10, 10, 40, 40),
                "yolo11",
                4,
            )
        ]
        local_detector = FakeLocalDetector([True])

        result = DecisionEngine(None, local_detector).evaluate(
            PrimaryDetection.from_primary(
                (), frame_sequence=4, supplementary=tuple(evidence)
            ),
            captured_frame(),
        )

        self.assertIs(result.classification, VisualViolationClassification.VIOLATION)
        self.assertIs(result.classification, VisualViolationClassification.VIOLATION)
        self.assertEqual(result.reason_codes, ("yolo_sexual_act_roi",))
        self.assertEqual(local_detector.received_means, [0])

    def test_sexual_act_without_roi_confirmation_stays_uncertain(self) -> None:
        evidence = [
            ViolationEvidence(
                ViolationEvidenceType.SEXUAL_ACT,
                "blowjob",
                0.88,
                (10, 10, 40, 40),
                "yolo11",
                4,
            )
        ]
        local_detector = FakeLocalDetector([False])

        result = DecisionEngine(None, local_detector).evaluate(
            PrimaryDetection.from_primary(
                (), frame_sequence=4, supplementary=tuple(evidence)
            ),
            captured_frame(),
        )

        self.assertIsNot(result.classification, VisualViolationClassification.VIOLATION)
        self.assertIs(result.classification, VisualViolationClassification.UNCERTAIN)
        self.assertEqual(result.reason_codes, ("sexual_act_candidate",))


if __name__ == "__main__":
    unittest.main()
