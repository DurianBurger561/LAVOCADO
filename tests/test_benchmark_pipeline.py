"""Vision Benchmark vs Full Pipeline Benchmark must stay separate."""

import unittest

from app.context.models import ContextPolicyAction
from app.vision.benchmarking import (
    VISION_GROUND_TRUTH_NOTE,
    evaluate_full_pipeline,
    format_failure_explorer,
    score_scenario,
    vision_ground_truth,
)


MEDICAL_ANATOMY = [
    {
        "class": "FEMALE_GENITALIA_EXPOSED",
        "score": 0.81,
        "box": [0, 0, 10, 10],
    }
]


class BenchmarkSplitTests(unittest.TestCase):
    def test_vision_benchmark_marks_medical_anatomy_as_violation(self) -> None:
        self.assertEqual(vision_ground_truth(MEDICAL_ANATOMY), "violation")
        self.assertEqual(
            vision_ground_truth(MEDICAL_ANATOMY, scenario_tag="medical"),
            "violation",
        )

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
            detections=MEDICAL_ANATOMY,
            scenario_tag="medical",
        )

        self.assertEqual(summary["policy"], "full_bypass")
        self.assertFalse(summary["vision_called"])
        self.assertFalse(summary["protection"])
        self.assertEqual(summary["scenario_score"], "whitelist_correct")
        self.assertEqual(summary["explorer"]["detector_evidence"], [])
        self.assertEqual(summary["explorer"]["final_action"], "allow")

    def test_full_pipeline_blacklist_protects_without_vision(self) -> None:
        summary = evaluate_full_pipeline(
            app_action=ContextPolicyAction.FULL_BYPASS,
            website_action=ContextPolicyAction.FORCE_BLOCK,
        )

        self.assertEqual(summary["policy"], "force_block")
        self.assertFalse(summary["vision_called"])
        self.assertTrue(summary["protection"])
        self.assertEqual(summary["explorer"]["final_action"], "protect")

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
        vision = vision_ground_truth(MEDICAL_ANATOMY, scenario_tag="education")
        summary = evaluate_full_pipeline(
            app_action=ContextPolicyAction.NORMAL,
            website_action=ContextPolicyAction.NORMAL,
            vision_result={"classification": vision},
            temporal_confirmed=True,
            detections=MEDICAL_ANATOMY,
            temporal_history=(True, True),
            scenario_tag="education",
        )

        self.assertEqual(vision, "violation")
        self.assertTrue(summary["vision_called"])
        self.assertTrue(summary["protection"])
        self.assertEqual(summary["scenario_score"], "visual_true_positive")
        self.assertEqual(
            summary["explorer"]["ground_truth_kind"],
            VISION_GROUND_TRUTH_NOTE,
        )
        self.assertEqual(
            summary["explorer"]["detector_evidence"][0]["label"],
            "FEMALE_GENITALIA_EXPOSED",
        )
        self.assertNotIn("bbox", summary["explorer"]["detector_evidence"][0])

    def test_failure_explorer_lists_required_fields(self) -> None:
        summary = evaluate_full_pipeline(
            app_action=ContextPolicyAction.NORMAL,
            website_action=ContextPolicyAction.NORMAL,
            detections=MEDICAL_ANATOMY,
            temporal_confirmed=True,
            temporal_history=(False, True, True),
            scenario_tag="art",
        )
        text = format_failure_explorer(summary)

        for field in (
            "context_policy",
            "app_rule",
            "website_rule",
            "vision_called",
            "detector_evidence",
            "temporal_state",
            "final_action",
        ):
            with self.subTest(field=field):
                self.assertIn(field, summary["explorer"])
                self.assertIn(field, text)

    def test_scenario_tags_do_not_auto_allow_vision(self) -> None:
        for tag in ("medical", "education", "art", "news"):
            with self.subTest(tag=tag):
                self.assertEqual(
                    score_scenario(
                        evaluate_full_pipeline(
                            app_action=ContextPolicyAction.NORMAL,
                            website_action=ContextPolicyAction.NORMAL,
                            detections=MEDICAL_ANATOMY,
                            temporal_confirmed=True,
                            scenario_tag=tag,
                        )
                    ),
                    "visual_true_positive",
                )


if __name__ == "__main__":
    unittest.main()
