"""Standalone detector scoring uses typed visual-policy classifications."""

from __future__ import annotations

import unittest

from app.vision.violation_policy import VisualViolationClassification
from developer.benchmark.ground_truth import visual_policy_classification


class GroundTruthTests(unittest.TestCase):
    def test_exposed_anatomy_is_violation(self) -> None:
        result = visual_policy_classification([
            {"class": "FEMALE_GENITALIA_EXPOSED", "score": 0.91},
        ])

        self.assertIs(result, VisualViolationClassification.VIOLATION)

    def test_non_violation_label_is_clear(self) -> None:
        result = visual_policy_classification([
            {"class": "FACE_FEMALE", "score": 0.99},
        ])

        self.assertIs(result, VisualViolationClassification.CLEAR)
