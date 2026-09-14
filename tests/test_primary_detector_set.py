"""Primary model invocation produces typed evidence, never product decisions."""

import unittest

import numpy as np

from app.platforms.capture.models import CaptureFrame
from app.vision.preprocessor import FramePreprocessor
from app.vision.primary_detector_set import PrimaryDetectorSet
from app.vision.violation_policy import ViolationEvidence, ViolationEvidenceType


class FakePrimary:
    def __init__(self) -> None:
        self.calls: list[tuple[np.ndarray, int, int]] = []

    def detect(
        self, image: np.ndarray, *, input_size: int, frame_sequence: int
    ) -> list[ViolationEvidence]:
        self.calls.append((image, input_size, frame_sequence))
        return [
            ViolationEvidence(
                ViolationEvidenceType.BREAST_EXPOSURE,
                "FEMALE_BREAST_EXPOSED", 0.8, (1, 2, 3, 4),
                "nudenet_640m", frame_sequence,
            ),
        ]


class FakeSupplementary:
    def __init__(self) -> None:
        self.calls: list[tuple[np.ndarray, int]] = []

    def detect_evidence(
        self, image: np.ndarray, *, frame_sequence: int
    ) -> list[ViolationEvidence]:
        self.calls.append((image, frame_sequence))
        return [
            ViolationEvidence(
                ViolationEvidenceType.SEXUAL_ACT,
                "blowjob",
                0.9,
                (0, 0, 2, 2),
                "yolo11",
                frame_sequence,
            )
        ]


class PrimaryDetectorSetTests(unittest.TestCase):
    def test_merges_primary_and_supplementary_evidence_once(self) -> None:
        frame = CaptureFrame(np.zeros((8, 8, 3), dtype=np.uint8), sequence=7)
        primary = FakePrimary()
        supplementary = FakeSupplementary()
        detector_set = PrimaryDetectorSet(
            primary, supplementary=supplementary, full_input_size=640
        )

        result = detector_set.detect(FramePreprocessor(frame))

        self.assertEqual(len(primary.calls), 1)
        self.assertIs(primary.calls[0][0], frame.image)
        self.assertEqual(primary.calls[0][1], 640)
        self.assertEqual(primary.calls[0][2], 7)
        self.assertEqual(supplementary.calls, [(frame.image, 7)])
        self.assertEqual(len(result.primary), 1)
        self.assertEqual(len(result.evidence), 2)
        self.assertEqual(result.evidence[0].frame_sequence, 7)
        self.assertEqual(result.evidence[1].evidence_type, ViolationEvidenceType.SEXUAL_ACT)
        self.assertFalse(hasattr(result, "blocked"))


if __name__ == "__main__":
    unittest.main()
