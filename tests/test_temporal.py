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
        self.assertFalse(verifier.update(True))


if __name__ == "__main__":
    unittest.main()
