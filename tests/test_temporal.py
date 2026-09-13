"""Tests for temporal detection confirmation."""

import unittest

from app.vision.temporal import TemporalVerifier


class TemporalVerifierTests(unittest.TestCase):
    def test_confirms_two_hits_in_three_frames(self) -> None:
        verifier = TemporalVerifier(window_size=3, required_hits=2)

        self.assertFalse(verifier.update(False))
        self.assertFalse(verifier.update(True))
        self.assertTrue(verifier.update(True))

    def test_does_not_confirm_only_one_hit(self) -> None:
        verifier = TemporalVerifier(window_size=3, required_hits=2)

        verifier.update(False)
        verifier.update(True)

        self.assertFalse(verifier.update(False))

    def test_reset_clears_previous_hits(self) -> None:
        verifier = TemporalVerifier(window_size=3, required_hits=2)
        verifier.update(True)
        verifier.update(True)

        verifier.reset()

        self.assertEqual(verifier.hits, 0)
        self.assertEqual(verifier.history, ())
        self.assertFalse(verifier.update(True))

    def test_history_is_an_immutable_copy(self) -> None:
        verifier = TemporalVerifier(window_size=3, required_hits=2)
        verifier.update(True)
        verifier.update(False)

        self.assertEqual(verifier.history, (True, False))

    def test_same_frame_sequence_is_not_double_counted(self) -> None:
        verifier = TemporalVerifier(window_size=3, required_hits=2)

        self.assertFalse(verifier.update(True, frame_sequence=7))
        self.assertFalse(verifier.update(True, frame_sequence=7))
        self.assertEqual(verifier.hits, 1)
        self.assertFalse(verifier.update(True, frame_sequence=8))
        self.assertTrue(verifier.update(True, frame_sequence=9))

    def test_non_overlapping_regions_do_not_confirm_each_other(self) -> None:
        verifier = TemporalVerifier(window_size=3, required_hits=2)

        self.assertFalse(
            verifier.update(True, frame_sequence=1, region=(0, 0, 10, 10))
        )
        self.assertFalse(
            verifier.update(True, frame_sequence=2, region=(50, 50, 60, 60))
        )
        self.assertEqual(verifier.hits, 1)


if __name__ == "__main__":
    unittest.main()
