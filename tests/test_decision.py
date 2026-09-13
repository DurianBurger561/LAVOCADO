"""Tests for visual-violation decisions. Viddexa ranks tiles and cannot block."""

import unittest

import numpy as np

from app.vision.capture import CapturedFrame
from app.vision.decision import DecisionEngine
from app.vision.violation_policy import (
    ViolationEvidence,
    ViolationEvidenceType,
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


class FakeLocalDetector:
    inference_resolution = 640

    def __init__(self, candidates: list[bool]) -> None:
        self._candidates = iter(candidates)
        self.received_means: list[int] = []

    def check(self, image: np.ndarray) -> dict[str, object]:
        self.received_means.append(int(image.mean()))
        candidate = next(self._candidates)
        return {
            "blocked": candidate,
            "reason": "local" if candidate else "",
            "label": "FEMALE_BREAST_EXPOSED" if candidate else None,
            "confidence": 0.80 if candidate else 0.0,
            "box": [0, 0, 1, 1] if candidate else None,
            "check_points": [],
        }


def captured_frame() -> CapturedFrame:
    return CapturedFrame(
        original_frame=np.zeros((1080, 1920, 3), dtype=np.uint8),
        model_frame=np.zeros((360, 640, 3), dtype=np.uint8),
        sequence=4,
    )


def result_with_detection(score: float) -> dict[str, object]:
    return {
        "blocked": score >= 0.65,
        "reason": "strong" if score >= 0.65 else "",
        "label": "FEMALE_BREAST_EXPOSED" if score >= 0.65 else None,
        "confidence": score if score >= 0.65 else 0.0,
        "box": [100, 50, 200, 100] if score >= 0.65 else None,
        "check_points": [
            {
                "class": "FEMALE_BREAST_EXPOSED",
                "score": score,
                "box": [100, 50, 200, 100],
            }
        ],
    }


def rescue_frame() -> CapturedFrame:
    original = np.zeros((4, 4, 3), dtype=np.uint8)
    original[0:2, 0:2] = 10
    original[0:2, 2:4] = 20
    original[2:4, 0:2] = 30
    original[2:4, 2:4] = 40
    return CapturedFrame(
        original_frame=original,
        model_frame=np.zeros((4, 4, 3), dtype=np.uint8),
        sequence=1,
    )


def empty_result() -> dict[str, object]:
    return {
        "blocked": False,
        "reason": "",
        "label": None,
        "confidence": 0.0,
        "box": None,
        "check_points": [],
    }


class DecisionEngineTests(unittest.TestCase):
    def test_rescue_ranks_all_tiles_and_skips_low_risk(self) -> None:
        low_context = {"normal": 0.99, "porn": 0.01}
        context = FakeContextClassifier(low_context)
        local_detector = FakeLocalDetector([])
        engine = DecisionEngine(context, local_detector)

        result = engine.evaluate(empty_result(), rescue_frame(), monitor_index=1)

        self.assertFalse(result["blocked"])
        self.assertEqual(result["classification"], "clear")
        self.assertEqual(context.received_means, [10, 20, 30, 40])
        self.assertEqual(local_detector.received_means, [])

    def test_high_porn_needs_local_nudenet_candidate(self) -> None:
        context = FakeContextClassifier({"porn": 0.99})
        local_detector = FakeLocalDetector([False])

        result = DecisionEngine(context, local_detector).evaluate(
            empty_result(),
            rescue_frame(),
            monitor_index=1,
        )

        self.assertFalse(result["blocked"])
        self.assertEqual(result["classification"], "clear")
        self.assertEqual(local_detector.received_means, [10])

    def test_viddexa_cannot_block_without_primary_evidence(self) -> None:
        context = FakeContextClassifier({"porn": 0.99, "hentai": 0.99})
        local_detector = FakeLocalDetector([False])

        result = DecisionEngine(context, local_detector).evaluate(
            empty_result(),
            rescue_frame(),
            monitor_index=1,
        )

        self.assertFalse(result["blocked"])
        self.assertNotEqual(result.get("classification"), "violation")

    def test_local_nudenet_candidate_enters_rescue_temporal_path(self) -> None:
        context = FakeContextClassifier({"porn": 0.99})
        local_detector = FakeLocalDetector([True])

        result = DecisionEngine(context, local_detector).evaluate(
            empty_result(),
            rescue_frame(),
            monitor_index=2,
        )

        self.assertTrue(result["blocked"])
        self.assertEqual(result["classification"], "violation")
        self.assertEqual(result["source"], "rescue_tile")
        self.assertEqual(result["label"], "FEMALE_BREAST_EXPOSED")
        self.assertEqual(result["region"], (0, 0, 2, 2))
        self.assertEqual(result["rescue_tile_index"], 0)

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
        local_detector = FakeLocalDetector([])

        result = DecisionEngine(context, local_detector).evaluate(
            empty_result(),
            rescue_frame(),
            monitor_index=1,
        )

        self.assertFalse(result["blocked"])
        self.assertEqual(local_detector.received_means, [])

    def test_tile_ranking_is_independent_per_monitor(self) -> None:
        context = FakeContextClassifier({"normal": 0.99, "porn": 0.01})
        engine = DecisionEngine(context, FakeLocalDetector([]))

        engine.evaluate(empty_result(), rescue_frame(), monitor_index=1)
        engine.evaluate(empty_result(), rescue_frame(), monitor_index=2)

        self.assertEqual(context.received_means, [10, 20, 30, 40, 10, 20, 30, 40])
        self.assertIsNone(engine.rescue_status(1)["pinned_tile_index"])
        self.assertIsNone(engine.rescue_status(2)["pinned_tile_index"])

    def test_reset_clears_rescue_ranking_and_pinning(self) -> None:
        context = FakeContextClassifier({"normal": 0.99, "porn": 0.01})
        engine = DecisionEngine(context, FakeLocalDetector([]))

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

    def test_decision_engine_ignores_context_identity_fields(self) -> None:
        payload = result_with_detection(0.80)
        payload["hostname"] = "medical.example"
        payload["application_name"] = "chrome.exe"
        payload["medical"] = True

        result = DecisionEngine().evaluate(payload, captured_frame())

        self.assertTrue(result["blocked"])
        self.assertEqual(result["classification"], "violation")
        self.assertNotIn("hostname", result)
        self.assertNotIn("medical", result)

    def test_strong_nudenet_candidate_does_not_need_context(self) -> None:
        context = FakeContextClassifier({"porn": 1.0})

        result = DecisionEngine(context).evaluate(
            result_with_detection(0.80),
            captured_frame(),
        )

        self.assertTrue(result["blocked"])
        self.assertEqual(result["classification"], "violation")
        self.assertEqual(result["source"], "nudenet_full")
        self.assertEqual(result["region"], (300, 150, 900, 450))
        self.assertEqual(context.received_shapes, [])

    def test_strong_anatomy_roi_recheck_confirms_violation(self) -> None:
        local_detector = FakeLocalDetector([True])

        result = DecisionEngine(None, local_detector).evaluate(
            result_with_detection(0.80),
            captured_frame(),
        )

        self.assertTrue(result["blocked"])
        self.assertEqual(result["classification"], "violation")
        self.assertEqual(result["source"], "nudenet_roi")
        self.assertEqual(local_detector.received_means, [0])

    def test_strong_anatomy_without_roi_confirmation_stays_uncertain(self) -> None:
        local_detector = FakeLocalDetector([False])

        result = DecisionEngine(None, local_detector).evaluate(
            result_with_detection(0.80),
            captured_frame(),
        )

        self.assertFalse(result["blocked"])
        self.assertEqual(result["classification"], "uncertain")
        self.assertEqual(result["source"], "anatomy_candidate")

    def test_borderline_roi_recheck_confirms_violation(self) -> None:
        local_detector = FakeLocalDetector([True])

        result = DecisionEngine(None, local_detector).evaluate(
            result_with_detection(0.60),
            captured_frame(),
        )

        self.assertTrue(result["blocked"])
        self.assertEqual(result["classification"], "violation")
        self.assertEqual(result["label"], "FEMALE_BREAST_EXPOSED")
        self.assertEqual(result["source"], "nudenet_roi")
        self.assertEqual(result["region"], (75, 37, 1125, 563))
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

        self.assertFalse(result["blocked"])
        self.assertEqual(result["classification"], "uncertain")
        self.assertEqual(result["source"], "nudenet_borderline")
        self.assertEqual(context.received_shapes, [])

    def test_borderline_without_roi_hit_stays_uncertain(self) -> None:
        local_detector = FakeLocalDetector([False])

        result = DecisionEngine(None, local_detector).evaluate(
            result_with_detection(0.60),
            captured_frame(),
        )

        self.assertFalse(result["blocked"])
        self.assertEqual(result["classification"], "uncertain")
        self.assertEqual(result["source"], "nudenet_borderline")

    def test_sexy_or_hentai_cannot_confirm_borderline(self) -> None:
        for label in ("sexy", "hentai"):
            with self.subTest(label=label):
                context = FakeContextClassifier({label: 0.99, "porn": 0.0})

                result = DecisionEngine(context).evaluate(
                    result_with_detection(0.60),
                    captured_frame(),
                )

                self.assertFalse(result["blocked"])
                self.assertEqual(result["classification"], "uncertain")
                self.assertEqual(result["source"], "nudenet_borderline")

    def test_context_cannot_block_without_a_nudenet_borderline(self) -> None:
        context = FakeContextClassifier({"porn": 0.99})

        result = DecisionEngine(context).evaluate(
            result_with_detection(0.20),
            captured_frame(),
        )

        self.assertFalse(result["blocked"])
        self.assertEqual(result["source"], "nudenet_none")
        self.assertEqual(context.received_shapes, [])

    def test_missing_or_failed_context_keeps_nudenet_only_result(self) -> None:
        for context in (None, FakeContextClassifier(None)):
            with self.subTest(context=context):
                result = DecisionEngine(context).evaluate(
                    result_with_detection(0.60),
                    captured_frame(),
                )

                self.assertFalse(result["blocked"])
                self.assertEqual(result["classification"], "uncertain")
                self.assertEqual(result["source"], "nudenet_borderline")

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
            empty_result(),
            captured_frame(),
            extra_evidence=evidence,
        )

        self.assertTrue(result["blocked"])
        self.assertEqual(result["classification"], "violation")
        self.assertEqual(result["source"], "yolo_sexual_act")
        self.assertEqual(result["label"], "blowjob")

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
            empty_result(),
            captured_frame(),
            extra_evidence=evidence,
        )

        self.assertTrue(result["blocked"])
        self.assertEqual(result["classification"], "violation")
        self.assertEqual(result["source"], "yolo_sexual_act_roi")
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
            empty_result(),
            captured_frame(),
            extra_evidence=evidence,
        )

        self.assertFalse(result["blocked"])
        self.assertEqual(result["classification"], "uncertain")
        self.assertEqual(result["source"], "sexual_act_candidate")


if __name__ == "__main__":
    unittest.main()
