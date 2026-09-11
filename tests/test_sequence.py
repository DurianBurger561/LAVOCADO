"""Tests for the staged intervention sequence."""

import unittest

from app.intervention.sequence import (
    InterventionSequence,
    InterventionStep,
    default_intervention_sequence,
)


class InterventionSequenceTests(unittest.TestCase):
    def test_default_sequence_moves_from_pause_to_breathe_to_ready(self) -> None:
        sequence = default_intervention_sequence()

        self.assertEqual(sequence.current.name, "pause")
        self.assertFalse(sequence.can_dismiss)

        self.assertTrue(sequence.advance())
        self.assertEqual(sequence.current.name, "breathe")
        self.assertFalse(sequence.can_dismiss)

        self.assertTrue(sequence.advance())
        self.assertEqual(sequence.current.name, "ready")
        self.assertTrue(sequence.can_dismiss)

        self.assertFalse(sequence.advance())
        self.assertEqual(sequence.current.name, "ready")

    def test_rejects_an_empty_sequence(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one step"):
            InterventionSequence(())

    def test_rejects_a_non_final_untimed_step(self) -> None:
        untimed = InterventionStep("wait", "Wait", "Wait", "Wait", None)
        ready = InterventionStep(
            "ready",
            "Ready",
            "Ready",
            "Continue",
            None,
            True,
        )

        with self.assertRaisesRegex(ValueError, "only the final"):
            InterventionSequence((untimed, ready))

    def test_requires_a_dismissible_final_step(self) -> None:
        final_step = InterventionStep(
            "ready",
            "Ready",
            "Ready",
            "Continue",
            None,
        )

        with self.assertRaisesRegex(ValueError, "must be dismissible"):
            InterventionSequence((final_step,))


if __name__ == "__main__":
    unittest.main()
