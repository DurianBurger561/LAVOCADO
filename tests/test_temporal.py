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

    def test_different_tracks_do_not_confirm_each_other(self) -> None:
        verifier = TemporalVerifier(window_size=3, required_hits=2)

        self.assertFalse(
            verifier.update(True, frame_sequence=1, region=(0, 0, 10, 10), track_id=1)
        )
        self.assertFalse(
            verifier.update(True, frame_sequence=2, region=(50, 50, 60, 60), track_id=2)
        )
        self.assertEqual(verifier.hits, 1)
        self.assertFalse(
            verifier.update(True, frame_sequence=3, region=(48, 48, 62, 62), track_id=2)
        )
        self.assertTrue(
            verifier.update(False, frame_sequence=4, region=(48, 48, 62, 62), track_id=2)
        )

    def test_visual_evidence_decays_when_fresh_frames_do_not_confirm(self) -> None:
        verifier = TemporalVerifier(window_size=3, required_hits=2)

        verifier.update(True, frame_sequence=1, evidence_type="sexual_act")
        verifier.update(False, frame_sequence=2, evidence_type="sexual_act")

        self.assertEqual(verifier.evidence_history, ("sexual_act", None))
        verifier.update(False, frame_sequence=3)
        self.assertEqual(verifier.evidence_history, ("sexual_act", None, None))

    def test_evidence_threshold_rejects_boolean_hits_with_weak_score(self) -> None:
        verifier = TemporalVerifier(
            window_size=3,
            required_hits=2,
            evidence_threshold=2.5,
            decay=0.5,
        )

        self.assertFalse(verifier.update(True, frame_sequence=1, evidence_delta=0.6))
        self.assertFalse(verifier.update(True, frame_sequence=2, evidence_delta=0.6))
        self.assertFalse(verifier.update(False, frame_sequence=3))
        self.assertLess(verifier.evidence_score, 2.5)

    def test_evidence_threshold_confirms_strong_track_hits(self) -> None:
        verifier = TemporalVerifier(
            window_size=3,
            required_hits=2,
            evidence_threshold=2.5,
        )

        self.assertFalse(
            verifier.update(True, frame_sequence=1, track_id=7, evidence_score=1.3)
        )
        self.assertFalse(
            verifier.update(True, frame_sequence=2, track_id=7, evidence_score=2.6)
        )
        self.assertTrue(
            verifier.update(False, frame_sequence=3, track_id=7, evidence_score=2.6)
        )

    def test_same_frame_does_not_raise_evidence_score(self) -> None:
        verifier = TemporalVerifier(
            window_size=3,
            required_hits=2,
            evidence_threshold=2.5,
        )

        verifier.update(True, frame_sequence=4, evidence_delta=1.3)
        verifier.update(True, frame_sequence=4, evidence_delta=1.3)

        self.assertEqual(verifier.hits, 1)
        self.assertAlmostEqual(verifier.evidence_score, 1.3)

    def test_miss_decays_evidence_score(self) -> None:
        verifier = TemporalVerifier(
            window_size=3,
            required_hits=2,
            evidence_threshold=2.5,
            decay=0.5,
        )
        verifier.update(True, frame_sequence=1, evidence_delta=2.0)
        verifier.update(False, frame_sequence=2)

        self.assertAlmostEqual(verifier.evidence_score, 1.0)


if __name__ == "__main__":
    unittest.main()
