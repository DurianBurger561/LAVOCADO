"""Unit boundaries for candidate rechecks, context ranking, and tile scheduling."""

import unittest

import numpy as np

from app.platforms.capture.models import CaptureFrame
from app.settings.schema import default_vision_settings, merge_vision_settings
from app.vision.candidate_verifier import CandidateVerifier
from app.vision.context.base import ContextResult
from app.vision.preprocessor import FramePreprocessor, PreparedFrame
from app.vision.scan_planner import ScanPlanner
from app.vision.scheduler import ScanPlan, TileScheduler
from app.vision.tiles import TileState
from app.vision.tracking import CandidateTracker
from app.vision.viddexa_ranker import ViddexaRanker
from app.vision.violation_policy import (
    ThresholdPolicy,
    ViolationEvidence,
    ViolationEvidenceType,
)


class LocalModel:
    def __init__(self) -> None:
        self.images: list[np.ndarray] = []

    def detect(self, prepared: PreparedFrame) -> tuple[ViolationEvidence, ...]:
        self.images.append(prepared.image)
        assert prepared.input_size == 640
        return (
            ViolationEvidence(
                ViolationEvidenceType.BREAST_EXPOSURE,
                "FEMALE_BREAST_EXPOSED", 0.8, None, "nudenet_640m", prepared.frame_sequence,
            ),
        )


class ContextModel:
    def classify(self, bgr_image: np.ndarray) -> dict[str, float]:
        return {"porn": float(bgr_image.mean()) / 255.0}

    def classify_batch(self, frames: list[np.ndarray]) -> list[ContextResult]:
        return [ContextResult(self.classify(frame), "fake") for frame in frames]


def prepared(image: np.ndarray, sequence: int = 1) -> FramePreprocessor:
    return FramePreprocessor(CaptureFrame(image=image, sequence=sequence))


class VisionComponentTests(unittest.TestCase):
    def test_scan_planner_applies_elapsed_ranking_time_to_vision_budget(self) -> None:
        settings = merge_vision_settings(
            default_vision_settings(), {"scan": {"vision_budget_ms": 50}}
        )
        frame = CaptureFrame(image=np.zeros((8, 8, 3), dtype=np.uint8), sequence=1)

        def plan(elapsed: float) -> ScanPlan:
            times = iter((0.0, elapsed))
            ranker = ViddexaRanker(None)
            planner = ScanPlanner(
                TileScheduler(settings),
                CandidateTracker(),
                ranker,
                crop_expansion=settings.recheck.crop_expansion,
                clock=lambda: next(times),
            )
            return planner.prepare_scan(frame, 1)

        self.assertEqual(len(plan(0.0).tile_indexes), 1)
        self.assertEqual(plan(0.045).tile_indexes, ())

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
        self.assertGreaterEqual(ranker.latency_for(source), 0.0)
        self.assertEqual(ranker.latency_for(prepared(image.copy(), 2)), 0.0)
        self.assertFalse(hasattr(ranker, "blocked"))

    def test_tile_scheduler_owns_change_state_and_reset(self) -> None:
        settings = default_vision_settings()
        scheduler = TileScheduler(
            settings, rows=2, columns=2, overlap=0, pin_followup_checks=2
        )
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
        scheduler.record_rescue_attempt(1, 0, confirmed=True)
        self.assertEqual(scheduler.rescue_status(1)["pinned_tile_index"], 0)
        scheduler.reset()
        self.assertEqual(scheduler.scan_id(1), 0)
        self.assertIsNone(scheduler.last_plan(1))

    def test_scheduler_selects_rescue_tiles_and_isolates_monitor_state(self) -> None:
        scheduler = TileScheduler(
            default_vision_settings(), rows=2, columns=2, overlap=0,
            pin_followup_checks=2,
        )
        source = prepared(np.zeros((8, 8, 3), dtype=np.uint8))
        scheduler.tiles_for(1, source)[3].context_score = 0.9

        ranked = scheduler.rescue_batch(1, source, plan=None, checks_per_scan=1)
        planned = scheduler.rescue_batch(
            1,
            source,
            plan=ScanPlan("monitoring", True, (1,), None, False, 640, 750),
            checks_per_scan=1,
        )
        scheduler.record_rescue_attempt(1, 1, confirmed=True)
        scheduler.mark_checked(1, planned.tiles, {1})
        planned.tiles[2].skipped_scans = scheduler.max_skip
        starved = scheduler.rescue_batch(1, source, plan=None, checks_per_scan=1)
        scheduler.rescue_batch(2, source, plan=None, checks_per_scan=1)
        scheduler.record_rescue_attempt(2, 3, confirmed=False)

        self.assertEqual([tile.index for tile in ranked.selected], [3])
        self.assertEqual([tile.index for tile in planned.selected], [1])
        self.assertEqual([tile.index for tile in ranked.ranked], [3, 0, 1, 2])
        self.assertEqual([tile.index for tile in starved.selected], [2])
        self.assertEqual(scheduler.rescue_status(1)["next_tile_index"], 2)
        self.assertEqual(scheduler.rescue_status(1)["pinned_tile_index"], 1)
        self.assertIsNone(scheduler.rescue_status(2)["pinned_tile_index"])
        self.assertEqual(scheduler.rescue_status(2)["next_tile_index"], 0)
        self.assertEqual(planned.tiles[1].skipped_scans, 0)
        self.assertEqual(planned.tiles[0].skipped_scans, 1)


if __name__ == "__main__":
    unittest.main()
