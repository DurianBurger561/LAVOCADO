"""Unit boundaries for candidate rechecks, context ranking, and tile scheduling."""

import unittest

import numpy as np

from app.platforms.capture.models import CaptureFrame
from app.settings.schema import default_vision_settings
from app.vision.candidate_verifier import CandidateVerifier
from app.vision.context.base import ContextResult
from app.vision.preprocessor import FramePreprocessor
from app.vision.scheduler import TileScheduler
from app.vision.tiles import TileState
from app.vision.viddexa_ranker import ViddexaRanker
from app.vision.violation_policy import (
    ThresholdPolicy,
    ViolationEvidence,
    ViolationEvidenceType,
)


class LocalModel:
    def __init__(self) -> None:
        self.images: list[np.ndarray] = []

    def detect(
        self, frame: np.ndarray, *, input_size: int, frame_sequence: int
    ) -> list[ViolationEvidence]:
        self.images.append(frame)
        assert input_size == 640
        return [
            ViolationEvidence(
                ViolationEvidenceType.BREAST_EXPOSURE,
                "FEMALE_BREAST_EXPOSED", 0.8, None, "nudenet_640m", frame_sequence,
            )
        ]


class ContextModel:
    def classify(self, bgr_image: np.ndarray) -> dict[str, float]:
        return {"porn": float(bgr_image.mean()) / 255.0}

    def classify_batch(self, frames: list[np.ndarray]) -> list[ContextResult]:
        return [ContextResult(self.classify(frame), "fake") for frame in frames]


def prepared(image: np.ndarray, sequence: int = 1) -> FramePreprocessor:
    return FramePreprocessor(CaptureFrame(image=image, sequence=sequence))


class VisionComponentTests(unittest.TestCase):
    def test_candidate_verifier_rechecks_original_resolution_roi(self) -> None:
        model = LocalModel()
        verifier = CandidateVerifier(
            model,
            threshold_policy=ThresholdPolicy.from_settings(default_vision_settings()),
            tile_input_size=640,
        )
        source = prepared(np.zeros((8, 8, 3), dtype=np.uint8))

        result = verifier.context_recheck(
            source, (1, 2, 3, 4), model_shape=(8, 8, 3), expansion=1.0
        )

        assert result is not None
        self.assertEqual(result.region, (1, 2, 4, 6))
        self.assertEqual(model.images[0].shape, (4, 3, 3))
        self.assertEqual(result.hit.label, "FEMALE_BREAST_EXPOSED")
        self.assertEqual(result.hit.frame_sequence, 1)

    def test_viddexa_ranks_tiles_but_does_not_emit_violation(self) -> None:
        image = np.zeros((4, 4, 3), dtype=np.uint8)
        image[:2, :2] = 255
        source = prepared(image)
        tiles = [TileState(0, (0, 0, 2, 2)), TileState(1, (2, 0, 4, 2))]
        ranker = ViddexaRanker(ContextModel())

        ranker.refresh_scores(source, tiles)
        top = ranker.top_subtile(source, (0, 0, 4, 4))

        self.assertGreater(tiles[0].context_score, tiles[1].context_score)
        self.assertEqual(top.region, (0, 0, 2, 2))
        self.assertFalse(hasattr(ranker, "blocked"))

    def test_tile_scheduler_owns_change_state_and_reset(self) -> None:
        settings = default_vision_settings()
        scheduler = TileScheduler(settings, rows=2, columns=2, overlap=0)
        ranker = ViddexaRanker(None)
        first = prepared(np.zeros((8, 8, 3), dtype=np.uint8), 1)
        second_image = np.zeros((8, 8, 3), dtype=np.uint8)
        second_image[:4, :4] = 255

        first_tiles, _ = scheduler.refresh_frame(1, first, ranker)
        second_tiles, change = scheduler.refresh_frame(
            1, prepared(second_image, 2), ranker
        )

        self.assertIs(first_tiles, second_tiles)
        self.assertIsNotNone(change)
        self.assertGreater(second_tiles[0].change_score, second_tiles[1].change_score)
        self.assertEqual(scheduler.scan_id(1), 2)
        scheduler.pin_tile(1, 0)
        scheduler.reset()
        self.assertEqual(scheduler.scan_id(1), 0)
        self.assertIsNone(scheduler.last_plan(1))


if __name__ == "__main__":
    unittest.main()
