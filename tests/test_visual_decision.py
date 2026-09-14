"""The visual decision core only transforms evidence and scalar payloads."""

import unittest

from app.settings.schema import default_vision_settings
from app.vision.violation_policy import (
    ThresholdPolicy,
    ViolationEvidence,
    ViolationEvidenceType,
    VisualViolationClassification,
)
from app.vision.visual_decision import VisualDecisionEngine


def breast(score: float) -> ViolationEvidence:
    return ViolationEvidence(
        ViolationEvidenceType.BREAST_EXPOSURE,
        "FEMALE_BREAST_EXPOSED",
        score,
        None,
        "nudenet_640m",
        2,
    )


class VisualDecisionEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = VisualDecisionEngine(
            ThresholdPolicy.from_settings(default_vision_settings()),
            borderline_margin=0.1,
        )

    def test_assesses_strong_proposal_and_clear_without_side_effects(self) -> None:
        strong = self.engine.assess([breast(0.80), breast(0.60)])
        proposal = self.engine.assess([breast(0.60)])
        clear = self.engine.assess([breast(0.20)])

        self.assertIs(strong.classification, VisualViolationClassification.VIOLATION)
        self.assertEqual(strong.strong, breast(0.80))
        self.assertIs(proposal.classification, VisualViolationClassification.UNCERTAIN)
        self.assertEqual(proposal.proposal, breast(0.60))
        self.assertIs(clear.classification, VisualViolationClassification.CLEAR)

    def test_primary_assessment_uses_its_policy_and_highest_confidence(self) -> None:
        policy = ThresholdPolicy(
            tables={
                "nudenet_640m": {
                    "FEMALE_BREAST_EXPOSED": {"proposal": 0.60, "strong": 0.70},
                    "FEMALE_GENITALIA_EXPOSED": {"proposal": 0.40, "strong": 0.50},
                },
                "yolo11_nsfw_small": {},
            }
        )
        engine = VisualDecisionEngine(policy)
        genital = ViolationEvidence(
            ViolationEvidenceType.GENITAL_EXPOSURE,
            "FEMALE_GENITALIA_EXPOSED",
            0.71,
            None,
            "nudenet_640m",
            2,
        )

        clear = engine.assess_primary((breast(0.68),))
        strong = engine.assess_primary((genital, breast(0.72)))

        self.assertIs(clear.classification, VisualViolationClassification.CLEAR)
        self.assertIsNone(clear.strong)
        self.assertIsNone(clear.threshold)
        self.assertIs(strong.classification, VisualViolationClassification.VIOLATION)
        self.assertEqual(strong.strong, breast(0.72))
        self.assertEqual(strong.threshold, 0.70)

    def test_selects_borderline_without_mutating_evidence(self) -> None:
        evidence = (breast(0.60),)

        selected = self.engine.borderline_candidate(evidence)

        self.assertIsNotNone(selected)
        self.assertEqual(selected.threshold, 0.65)
        self.assertEqual(selected.evidence, breast(0.60))
        self.assertEqual(evidence, (breast(0.60),))

    def test_borderline_band_can_include_evidence_below_proposal(self) -> None:
        engine = VisualDecisionEngine(
            ThresholdPolicy.from_settings(default_vision_settings()),
            borderline_margin=0.20,
        )

        selected = engine.borderline_candidate((breast(0.50), breast(0.20)))

        self.assertIsNotNone(selected)
        self.assertEqual(selected.evidence, breast(0.50))
        self.assertEqual(selected.threshold, 0.65)

    def test_finalize_does_not_mutate_payload(self) -> None:
        payload = {
            "classification": VisualViolationClassification.CLEAR,
            "source": "nudenet_none",
            "evidence": [],
        }

        result = self.engine.finalize(payload, frame_sequence=2, monitor_index=1)

        self.assertIs(result.classification, VisualViolationClassification.CLEAR)
        self.assertEqual(
            payload,
            {
                "classification": VisualViolationClassification.CLEAR,
                "source": "nudenet_none",
                "evidence": [],
            },
        )

    def test_finalize_rejects_untyped_classification(self) -> None:
        with self.assertRaisesRegex(TypeError, "must be typed"):
            self.engine.finalize(
                {"classification": "violation", "evidence": []},
                frame_sequence=2,
                monitor_index=1,
            )


if __name__ == "__main__":
    unittest.main()
