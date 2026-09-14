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

    def test_selects_borderline_without_mutating_raw_detections(self) -> None:
        raw = [{"class": "FEMALE_BREAST_EXPOSED", "score": 0.60}]

        selected = self.engine.borderline_detection(raw)

        self.assertEqual(selected["threshold"], 0.65)
        self.assertEqual(raw, [{"class": "FEMALE_BREAST_EXPOSED", "score": 0.60}])

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
