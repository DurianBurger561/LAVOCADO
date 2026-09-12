"""Tests for conservative NudeNet and Viddexa decision fusion."""

import unittest

import numpy as np

from app.vision.capture import CapturedFrame
from app.vision.decision import DecisionEngine


class FakeContextClassifier:
    def __init__(self, scores: dict[str, float] | None) -> None:
        self.scores = scores
        self.received_shapes: list[tuple[int, ...]] = []

    def classify(self, image: np.ndarray) -> dict[str, float] | None:
        self.received_shapes.append(image.shape)
        return self.scores


def captured_frame() -> CapturedFrame:
    return CapturedFrame(
        original_frame=np.zeros((1080, 1920, 3), dtype=np.uint8),
        model_frame=np.zeros((360, 640, 3), dtype=np.uint8),
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


class DecisionEngineTests(unittest.TestCase):
    def test_strong_nudenet_candidate_does_not_need_context(self) -> None:
        context = FakeContextClassifier({"porn": 1.0})

        result = DecisionEngine(context).evaluate(
            result_with_detection(0.80),
            captured_frame(),
        )

        self.assertTrue(result["blocked"])
        self.assertEqual(result["source"], "nudenet_full")
        self.assertEqual(result["region"], (300, 150, 900, 450))
        self.assertEqual(context.received_shapes, [])

    def test_porn_can_confirm_a_borderline_nudenet_detection(self) -> None:
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

        self.assertTrue(result["blocked"])
        self.assertEqual(result["label"], "FEMALE_BREAST_EXPOSED")
        self.assertEqual(result["source"], "nudenet_borderline_context")
        self.assertEqual(result["context_label"], "porn")
        self.assertEqual(result["region"], (75, 37, 1125, 563))
        self.assertEqual(context.received_shapes, [(526, 1050, 3)])

    def test_porn_below_confirmation_threshold_does_not_block(self) -> None:
        context = FakeContextClassifier({"normal": 0.11, "porn": 0.89})

        result = DecisionEngine(context).evaluate(
            result_with_detection(0.60),
            captured_frame(),
        )

        self.assertFalse(result["blocked"])
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
                self.assertEqual(result["source"], "nudenet_borderline")


if __name__ == "__main__":
    unittest.main()
