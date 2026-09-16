"""Tests for selectable primary detectors and context rankers."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from app.platforms.capture.models import CaptureFrame
from app.settings.presets import apply_preset
from app.settings.schema import sanitize_vision_settings
from app.settings.storage import load_vision_settings, save_vision_settings
from app.vision.change_map import ChangeMap, build_change_map, tile_change_scores
from app.vision.context.factory import load_context_ranker, normalize_context_name
from app.vision.context.off import OffContextRanker
from app.vision.detectors.factory import (
    PRIMARY_YOLO,
    load_primary_bundle,
    normalize_primary_name,
)
from app.vision.detectors.nudenet import NudeNetPrimaryDetector
from app.vision.detectors.yolo11_nsfw import Yolo11NsfwDetector
from app.vision.evidence import decay_evidence, evidence_from_confidence, is_confirmed
from app.vision.preprocessor import FramePreprocessor
from app.vision.scheduler import TileScheduler
from app.vision.tiles import TileState, mark_checked, rank_tiles
from app.vision.tracking import CandidateTrack, CandidateTracker
from app.vision.violation_policy import (
    DetectionTier,
    ViolationEvidenceType,
    tier_for_score,
)
from app.vision.yolo_adapter import Yolo11Adapter


class FakeNudeModel:
    def detect(self, image: np.ndarray) -> list[dict[str, object]]:
        del image
        return [
            {"class": "FACE_FEMALE", "score": 0.99, "box": [0, 0, 4, 4]},
            {"class": "FEMALE_BREAST_EXPOSED", "score": 0.71, "box": [1, 1, 8, 8]},
        ]


class FakeYolo:
    def __init__(self) -> None:
        self.imgsz = None
        self.received_imgsz = None

    def detect(self, image: np.ndarray) -> list[dict[str, object]]:
        del image
        self.received_imgsz = self.imgsz
        return [{"class": "breast", "score": 0.8, "box": [2, 2, 6, 6]}]


class DetectorAbstractionTests(unittest.TestCase):
    @staticmethod
    def prepared(size: int, sequence: int = 1):
        return FramePreprocessor(
            CaptureFrame(np.zeros((size, size, 3), dtype=np.uint8), sequence=sequence)
        ).prepare_full(960 if size == 32 else 640)

    def test_nudenet_keeps_original_labels(self) -> None:
        detector = NudeNetPrimaryDetector(model=FakeNudeModel())
        evidence = detector.detect(
            self.prepared(16)
        )

        self.assertEqual(detector.name, "nudenet_640m")
        self.assertEqual([item.label for item in evidence], ["FEMALE_BREAST_EXPOSED"])

    def test_nudenet_detect_emits_typed_anatomy_evidence(self) -> None:
        evidence = NudeNetPrimaryDetector(model=FakeNudeModel()).detect(
            self.prepared(16),
        )
        self.assertEqual([item.label for item in evidence], ["FEMALE_BREAST_EXPOSED"])
        self.assertAlmostEqual(evidence[0].confidence, 0.71)

    def test_yolo_uses_input_size_and_own_labels(self) -> None:
        model = FakeYolo()
        detector = Yolo11NsfwDetector(Yolo11Adapter(model), default_input_size=640)
        evidence = detector.detect(
            self.prepared(32)
        )

        self.assertEqual(detector.name, "yolo11_nsfw_small")
        self.assertEqual(evidence[0].label, "breast")
        self.assertEqual(model.received_imgsz, 960)

    def test_yolo_unavailable_falls_back_to_nudenet(self) -> None:
        bundle = load_primary_bundle(PRIMARY_YOLO, yolo_enabled=False)
        self.assertEqual(bundle.requested, PRIMARY_YOLO)
        self.assertIsInstance(bundle.primary, NudeNetPrimaryDetector)
        self.assertTrue(str(bundle.name).startswith("nudenet"))
        self.assertEqual(bundle.yolo_status, "unavailable")

    def test_normalize_primary_aliases(self) -> None:
        self.assertEqual(normalize_primary_name("YOLO11"), PRIMARY_YOLO)
        self.assertEqual(normalize_primary_name("bogus"), "nudenet_640m")


class ContextRankerTests(unittest.TestCase):
    def test_off_ranker_never_blocks_and_returns_batch(self) -> None:
        ranker = OffContextRanker()
        frames = [np.zeros((4, 4, 3), dtype=np.uint8), np.ones((4, 4, 3), dtype=np.uint8)]
        results = ranker.classify_batch(frames)
        self.assertEqual(ranker.name, "off")
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].porn_score, 0.0)
        self.assertIsNone(ranker.classify(frames[0]))

    def test_unavailable_context_becomes_off(self) -> None:
        factory = Mock(side_effect=ImportError("missing"))
        with self.assertLogs("app.vision.context_classifier", level="WARNING"):
            ranker = load_context_ranker("viddexa_nano", pipeline_factory=factory)
        self.assertEqual(ranker.name, "off")

    def test_context_ranker_uses_bundled_model_path(self) -> None:
        factory = Mock(return_value=Mock())
        with tempfile.TemporaryDirectory() as temporary:
            local_path = Path(temporary)
            with patch(
                "app.vision.context.viddexa_nano.resolve_viddexa_model_path",
                return_value=local_path,
            ):
                ranker = load_context_ranker("viddexa_nano", pipeline_factory=factory)

        self.assertEqual(ranker.name, "viddexa_nano")
        self.assertEqual(factory.call_args.kwargs["model"], str(local_path))
        self.assertEqual(factory.call_args.kwargs["model_kwargs"], {"local_files_only": True})

    def test_nano_and_mini_names(self) -> None:
        self.assertEqual(normalize_context_name("nano"), "viddexa_nano")
        self.assertEqual(normalize_context_name("mini"), "viddexa_mini")
        self.assertEqual(normalize_context_name("off", enabled=False), "off")


class SettingsSchemaTests(unittest.TestCase):
    def test_invalid_values_are_clamped(self) -> None:
        settings = sanitize_vision_settings(
            {
                "detector": {"primary": "nope", "full_input_size": 9999},
                "tiles": {"rows": 9, "overlap": 0.99, "checks_per_scan": 99},
                "recheck": {"crop_expansion": 9},
            }
        )
        self.assertEqual(settings.detector.primary, "nudenet_640m")
        self.assertEqual(settings.detector.full_input_size, 640)
        self.assertEqual(settings.tiles.rows, 2)
        self.assertEqual(settings.tiles.overlap, 0.25)
        self.assertEqual(settings.tiles.checks_per_scan, 2)
        self.assertEqual(settings.recheck.crop_expansion, 2.5)
        settings = sanitize_vision_settings(
            {
                "recheck": {"proposal_margin": 0.99},
                "temporal": {"decay": 0.01, "evidence_threshold": 9},
                "scan": {"change_sensitivity": 0.9},
            }
        )
        self.assertEqual(settings.recheck.proposal_margin, 0.20)
        self.assertEqual(settings.temporal.decay, 0.3)
        self.assertEqual(settings.temporal.evidence_threshold, 3.5)
        self.assertEqual(settings.scan.change_sensitivity, 0.05)

    def test_nudenet_locks_input_size_to_640(self) -> None:
        settings = sanitize_vision_settings(
            {
                "detector": {
                    "primary": "nudenet_640m",
                    "full_input_size": 1280,
                    "tile_input_size": 960,
                }
            }
        )
        self.assertEqual(settings.detector.full_input_size, 640)
        self.assertEqual(settings.detector.tile_input_size, 640)

    def test_presets_and_persistence(self) -> None:
        import tempfile
        from pathlib import Path

        high = apply_preset("high_recall")
        self.assertEqual(high.preset, "high_recall")
        self.assertEqual(high.tiles.checks_per_scan, 2)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir)
            save_vision_settings(high, path)
            loaded = load_vision_settings(path)
        self.assertEqual(loaded.tiles.checks_per_scan, 2)
        self.assertEqual(load_vision_settings(Path("/missing/dir")).detector.primary, "nudenet_640m")
        self.assertEqual(
            sanitize_vision_settings({"temporal": {"confirmation": "nope"}}).temporal.confirmation,
            "boolean",
        )
        self.assertEqual(
            sanitize_vision_settings({"temporal": {"confirmation": "evidence"}}).temporal.confirmation,
            "evidence",
        )


class TilePriorityTests(unittest.TestCase):
    def test_context_change_age_and_starvation(self) -> None:
        tiles = [
            TileState(0, (0, 0, 10, 10), context_score=0.9, change_score=0.1, skipped_scans=0),
            TileState(1, (10, 0, 20, 10), context_score=0.1, change_score=0.8, skipped_scans=0),
            TileState(2, (0, 10, 10, 20), context_score=0.0, change_score=0.0, skipped_scans=3),
        ]
        ranked = rank_tiles(tiles, max_skip=3)
        self.assertEqual(ranked[0].index, 2)
        self.assertEqual(ranked[0].priority_score, float("inf"))
        mark_checked(tiles, {2}, scan_id=1)
        self.assertEqual(tiles[2].skipped_scans, 0)
        self.assertEqual(tiles[0].skipped_scans, 1)


class TrackingAndEvidenceTests(unittest.TestCase):
    def test_candidate_identity_keeps_typed_evidence_separate(self) -> None:
        tracker = CandidateTracker()
        common = {
            "monitor_index": 1,
            "box": (10, 10, 40, 40),
            "label": "same_raw_label",
            "confidence": 0.8,
            "source": "full",
            "evidence_delta": 1.0,
        }
        anatomy = tracker.match_or_create(
            **common, frame_sequence=1,
            evidence_type=ViolationEvidenceType.BREAST_EXPOSURE,
        )
        act = tracker.match_or_create(
            **common, frame_sequence=2,
            evidence_type=ViolationEvidenceType.SEXUAL_ACT,
        )

        self.assertNotEqual(anatomy.id, act.id)
        self.assertIs(anatomy.evidence_type, ViolationEvidenceType.BREAST_EXPOSURE)
        self.assertIs(act.evidence_type, ViolationEvidenceType.SEXUAL_ACT)

    def test_same_region_matches_and_different_monitor_does_not(self) -> None:
        tracker = CandidateTracker()
        first = tracker.match_or_create(
            monitor_index=1,
            box=(10, 10, 40, 40),
            label="FEMALE_BREAST_EXPOSED",
            confidence=0.7,
            source="full",
            frame_sequence=1,
            evidence_delta=1.2,
        )
        moved = tracker.match_or_create(
            monitor_index=1,
            box=(14, 12, 44, 42),
            label="FEMALE_BREAST_EXPOSED",
            confidence=0.8,
            source="focused",
            frame_sequence=2,
            evidence_delta=1.2,
        )
        other = tracker.match_or_create(
            monitor_index=2,
            box=(10, 10, 40, 40),
            label="FEMALE_BREAST_EXPOSED",
            confidence=0.8,
            source="full",
            frame_sequence=2,
            evidence_delta=1.2,
        )
        self.assertIsNotNone(first)
        self.assertEqual(first.id, moved.id)
        self.assertEqual(moved.fresh_frame_hits, 2)
        self.assertNotEqual(first.id, other.id)

    def test_same_frame_does_not_add_a_fresh_hit(self) -> None:
        tracker = CandidateTracker()
        first = tracker.match_or_create(
            monitor_index=1,
            box=(0, 0, 20, 20),
            label="ANUS_EXPOSED",
            confidence=0.8,
            source="full",
            frame_sequence=4,
            evidence_delta=1.0,
        )
        again = tracker.match_or_create(
            monitor_index=1,
            box=(0, 0, 20, 20),
            label="ANUS_EXPOSED",
            confidence=0.9,
            source="local",
            frame_sequence=4,
            evidence_delta=1.0,
        )
        self.assertEqual(first.fresh_frame_hits, 1)
        self.assertEqual(again.fresh_frame_hits, 1)

    def test_evidence_accumulation_and_decay(self) -> None:
        added = evidence_from_confidence(0.8, "FEMALE_BREAST_EXPOSED")
        self.assertGreater(added, 1.0)
        self.assertAlmostEqual(decay_evidence(1.8, 0.5), 0.9)
        self.assertTrue(
            is_confirmed(
                fresh_hits=2,
                evidence_score=2.6,
                min_fresh_hits=2,
                evidence_threshold=2.5,
                window_hits=2,
                required_window_hits=2,
                confirmation="both",
            )
        )
        self.assertFalse(
            is_confirmed(
                fresh_hits=1,
                evidence_score=3.0,
                min_fresh_hits=2,
                evidence_threshold=2.5,
                confirmation="evidence",
            )
        )
        self.assertFalse(
            is_confirmed(
                fresh_hits=2,
                evidence_score=1.0,
                min_fresh_hits=2,
                evidence_threshold=2.5,
                window_hits=2,
                required_window_hits=2,
                confirmation="both",
            )
        )
        self.assertTrue(
            is_confirmed(
                fresh_hits=2,
                evidence_score=0.1,
                min_fresh_hits=2,
                evidence_threshold=2.5,
                window_hits=2,
                required_window_hits=2,
                confirmation="boolean",
            )
        )


class PerModelThresholdTests(unittest.TestCase):
    def test_nudenet_and_yolo_keep_independent_strong_values(self) -> None:
        from app.vision.violation_policy import ThresholdPolicy

        settings = sanitize_vision_settings(
            {
                "thresholds": {
                    "nudenet_640m": {
                        "FEMALE_BREAST_EXPOSED": {"proposal": 0.55, "strong": 0.65}
                    },
                    "yolo11_nsfw_small": {
                        "breast": {"proposal": 0.40, "strong": 0.60}
                    },
                }
            }
        )
        policy = ThresholdPolicy.from_settings(settings)
        self.assertEqual(
            policy.strong("FEMALE_BREAST_EXPOSED", "nudenet_640m"), 0.65
        )
        self.assertEqual(policy.strong("breast", "yolo11_nsfw_small"), 0.60)
        self.assertEqual(
            policy.tier(0.62, "FEMALE_BREAST_EXPOSED", "nudenet_640m"),
            DetectionTier.PROPOSAL,
        )
        self.assertEqual(
            policy.tier(0.62, "breast", "yolo11_nsfw_small"),
            DetectionTier.STRONG,
        )

    def test_invalid_threshold_pairs_are_clamped_and_ordered(self) -> None:
        settings = sanitize_vision_settings(
            {
                "thresholds": {
                    "yolo11_nsfw_small": {
                        "breast": {"proposal": 0.99, "strong": 0.20}
                    }
                }
            }
        )
        pair = settings.thresholds.yolo11_nsfw_small["breast"]
        self.assertLess(pair["proposal"], pair["strong"])
        self.assertIn(pair["strong"], (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75))


class ProposalTierTests(unittest.TestCase):
    def test_ignore_proposal_and_strong_bands(self) -> None:
        self.assertEqual(
            tier_for_score(0.20, "FEMALE_BREAST_EXPOSED", margin=0.10),
            DetectionTier.IGNORE,
        )
        self.assertEqual(
            tier_for_score(0.60, "FEMALE_BREAST_EXPOSED", margin=0.10),
            DetectionTier.PROPOSAL,
        )
        self.assertEqual(
            tier_for_score(0.80, "FEMALE_BREAST_EXPOSED", margin=0.10),
            DetectionTier.STRONG,
        )


class ChangeMapAndSchedulerTests(unittest.TestCase):
    def test_change_scores_rise_where_pixels_change(self) -> None:
        previous = np.zeros((40, 80, 3), dtype=np.uint8)
        current = np.zeros((40, 80, 3), dtype=np.uint8)
        current[0:20, 40:80] = 255
        change = build_change_map(current, build_change_map(previous, None).gray)
        regions = ((0, 0, 40, 20), (40, 0, 80, 20), (0, 20, 40, 40), (40, 20, 80, 40))
        scores = tile_change_scores(change, regions, current.shape)
        self.assertGreater(scores[1], scores[0])
        self.assertGreater(scores[1], scores[2])

    def test_scheduler_focused_and_starvation(self) -> None:
        settings = sanitize_vision_settings(None)
        scheduler = TileScheduler(settings)
        tiles = [
            TileState(0, (0, 0, 10, 10), context_score=0.1, skipped_scans=0),
            TileState(1, (10, 0, 20, 10), context_score=0.2, skipped_scans=3),
        ]
        plan = scheduler.plan(
            monitor_index=1,
            tiles=tiles,
            change_map=None,
            active_track=None,
            is_active_monitor=True,
        )
        self.assertIn(1, plan.tile_indexes)
        self.assertTrue(plan.run_full)

    def test_scheduler_focused_skips_full_scan(self) -> None:
        settings = sanitize_vision_settings(None)
        scheduler = TileScheduler(settings)
        track = CandidateTrack(
            id=1,
            monitor_index=1,
            label="FEMALE_BREAST_EXPOSED",
            box=(4, 4, 12, 12),
        )
        plan = scheduler.plan(
            monitor_index=1,
            tiles=[],
            change_map=None,
            active_track=track,
            is_active_monitor=True,
        )
        self.assertEqual(plan.mode, "focused")
        self.assertFalse(plan.run_full)
        self.assertEqual(plan.roi, track.box)

    def test_high_change_uses_aggressive_budget(self) -> None:
        settings = sanitize_vision_settings(None)
        scheduler = TileScheduler(settings)
        tiles = [
            TileState(0, (0, 0, 10, 10), context_score=0.1, skipped_scans=0),
            TileState(1, (10, 0, 20, 10), context_score=0.2, skipped_scans=0),
        ]
        change = ChangeMap(
            gray=np.zeros((4, 4), dtype=np.uint8),
            previous=None,
            difference=np.ones((4, 4), dtype=np.float32),
        )
        plan = scheduler.plan(
            monitor_index=1,
            tiles=tiles,
            change_map=change,
            active_track=None,
            is_active_monitor=True,
        )
        self.assertEqual(plan.mode, "aggressive")
        self.assertGreaterEqual(len(plan.tile_indexes), 1)

    def test_exhausted_budget_skips_extra_tiles(self) -> None:
        settings = sanitize_vision_settings(
            {"scan": {"vision_budget_ms": 50}}
        )
        scheduler = TileScheduler(settings)
        tiles = [TileState(0, (0, 0, 10, 10), skipped_scans=0)]
        plan = scheduler.plan(
            monitor_index=1,
            tiles=tiles,
            change_map=None,
            active_track=None,
            is_active_monitor=True,
            elapsed_ms=80.0,
        )
        self.assertEqual(plan.tile_indexes, ())


if __name__ == "__main__":
    unittest.main()
