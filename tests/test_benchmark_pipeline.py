"""Vision Benchmark vs Full Pipeline Benchmark must stay separate."""

import unittest

from app.context.models import ContextPolicyAction
from app.vision.benchmarking import evaluate_full_pipeline, vision_ground_truth


class BenchmarkSplitTests(unittest.TestCase):
    def test_vision_benchmark_marks_medical_anatomy_as_violation(self) -> None:
        label = vision_ground_truth(
            [
                {
                    "class": "FEMALE_GENITALIA_EXPOSED",
                    "score": 0.81,
                    "box": [0, 0, 10, 10],
                }
            ]
        )

        self.assertEqual(label, "violation")

    def test_vision_benchmark_ignores_unmapped_labels(self) -> None:
        self.assertEqual(
            vision_ground_truth(
                [{"class": "FACE_FEMALE", "score": 0.99, "box": [0, 0, 1, 1]}]
            ),
            "clear",
        )

    def test_full_pipeline_whitelist_skips_vision(self) -> None:
        summary = evaluate_full_pipeline(
            app_action=ContextPolicyAction.NORMAL,
            website_action=ContextPolicyAction.FULL_BYPASS,
            vision_result={"classification": "violation"},
            temporal_confirmed=True,
        )

        self.assertEqual(summary["policy"], "full_bypass")
        self.assertFalse(summary["vision_called"])
        self.assertFalse(summary["protection"])

    def test_full_pipeline_blacklist_protects_without_vision(self) -> None:
        summary = evaluate_full_pipeline(
            app_action=ContextPolicyAction.FULL_BYPASS,
            website_action=ContextPolicyAction.FORCE_BLOCK,
        )

        self.assertEqual(summary["policy"], "force_block")
        self.assertFalse(summary["vision_called"])
        self.assertTrue(summary["protection"])

    def test_full_pipeline_unknown_website_runs_vision(self) -> None:
        summary = evaluate_full_pipeline(
            app_action=ContextPolicyAction.NORMAL,
            website_action=None,
            vision_result={"classification": "violation"},
            temporal_confirmed=True,
        )

        self.assertEqual(summary["policy"], "normal")
        self.assertTrue(summary["vision_called"])
        self.assertTrue(summary["protection"])

    def test_same_medical_image_is_protected_in_normal_context(self) -> None:
        vision = vision_ground_truth(
            [
                {
                    "class": "FEMALE_GENITALIA_EXPOSED",
                    "score": 0.81,
                    "box": [0, 0, 10, 10],
                }
            ]
        )
        summary = evaluate_full_pipeline(
            app_action=ContextPolicyAction.NORMAL,
            website_action=ContextPolicyAction.NORMAL,
            vision_result={"classification": vision},
            temporal_confirmed=True,
        )

        self.assertEqual(vision, "violation")
        self.assertTrue(summary["vision_called"])
        self.assertTrue(summary["protection"])


if __name__ == "__main__":
    unittest.main()
