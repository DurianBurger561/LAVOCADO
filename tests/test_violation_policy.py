"""Tests for the shared visual-violation policy."""

import unittest

from app.settings.schema import default_vision_settings, merge_vision_settings
from app.vision.nudenet_adapter import detections_to_evidence
from app.vision.violation_policy import (
    ThresholdPolicy,
    ViolationEvidenceType,
    evidence_type_for_label,
    is_borderline_score,
    strongest_evidence,
    threshold_for_label,
)
from app.vision.yolo_adapter import (
    detections_to_evidence as yolo_detections_to_evidence,
)


class ViolationPolicyTests(unittest.TestCase):
    def test_nudenet_labels_map_to_anatomy_types(self) -> None:
        self.assertEqual(
            evidence_type_for_label("FEMALE_GENITALIA_EXPOSED"),
            ViolationEvidenceType.GENITAL_EXPOSURE,
        )
        self.assertEqual(
            evidence_type_for_label("MALE_GENITALIA_EXPOSED"),
            ViolationEvidenceType.GENITAL_EXPOSURE,
        )
        self.assertEqual(
            evidence_type_for_label("ANUS_EXPOSED"),
            ViolationEvidenceType.ANUS_EXPOSURE,
        )
        self.assertEqual(
            evidence_type_for_label("FEMALE_BREAST_EXPOSED"),
            ViolationEvidenceType.BREAST_EXPOSURE,
        )
        self.assertEqual(
            evidence_type_for_label("BUTTOCKS_EXPOSED"),
            ViolationEvidenceType.BUTTOCKS_EXPOSURE,
        )

    def test_unmapped_nudenet_labels_are_not_violations(self) -> None:
        self.assertIsNone(evidence_type_for_label("FACE_FEMALE"))
        self.assertIsNone(evidence_type_for_label("BELLY_EXPOSED"))

    def test_yolo_sexual_act_labels_map(self) -> None:
        for label in ("blowjob", "vaginal sex", "anal-sex", "handjob"):
            with self.subTest(label=label):
                self.assertEqual(
                    evidence_type_for_label(label),
                    ViolationEvidenceType.SEXUAL_ACT,
                )

    def test_nudenet_adapter_emits_only_policy_labels(self) -> None:
        evidence = detections_to_evidence(
            [
                {"class": "FACE_FEMALE", "score": 0.99, "box": [0, 0, 1, 1]},
                {
                    "class": "FEMALE_GENITALIA_EXPOSED",
                    "score": 0.81,
                    "box": [1, 2, 3, 4],
                },
            ]
        )

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].label, "FEMALE_GENITALIA_EXPOSED")
        self.assertEqual(
            evidence[0].evidence_type,
            ViolationEvidenceType.GENITAL_EXPOSURE,
        )

    def test_yolo_adapter_maps_sexual_act_and_anatomy(self) -> None:
        evidence = yolo_detections_to_evidence(
            [
                {"class": "blowjob", "score": 0.9, "box": [0, 0, 10, 10]},
                {"class": "penis", "score": 0.7, "box": [1, 1, 2, 2]},
                {"class": "person", "score": 0.99, "box": [0, 0, 1, 1]},
            ]
        )

        types = {item.evidence_type for item in evidence}
        self.assertEqual(
            types,
            {
                ViolationEvidenceType.SEXUAL_ACT,
                ViolationEvidenceType.GENITAL_EXPOSURE,
            },
        )
        strongest = strongest_evidence(evidence)
        assert strongest is not None
        self.assertEqual(strongest.evidence_type, ViolationEvidenceType.SEXUAL_ACT)

    def test_thresholds_come_from_shared_policy(self) -> None:
        self.assertEqual(threshold_for_label("FEMALE_BREAST_EXPOSED"), 0.65)
        self.assertEqual(threshold_for_label("blowjob"), 0.45)
        self.assertEqual(threshold_for_label("sexual-contact", "yolo11"), 0.45)
        self.assertIsNone(threshold_for_label("FACE_FEMALE"))

    def test_yolo_aliases_share_persisted_canonical_threshold(self) -> None:
        settings = merge_vision_settings(
            default_vision_settings(),
            {"thresholds": {"yolo11_nsfw_small": {
                "sex": {"proposal": 0.70, "strong": 0.75}
            }}},
        )
        policy = ThresholdPolicy.from_settings(settings)

        self.assertEqual(policy.strong("sexual-contact", "yolo11"), 0.75)
        self.assertEqual(policy.proposal("sexual-contact", "yolo11"), 0.70)

    def test_borderline_band_is_below_threshold(self) -> None:
        self.assertTrue(is_borderline_score(0.60, 0.65, 0.10))
        self.assertFalse(is_borderline_score(0.65, 0.65, 0.10))
        self.assertFalse(is_borderline_score(0.50, 0.65, 0.10))


if __name__ == "__main__":
    unittest.main()
