"""Detector-only and full pipeline session behavior."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np

from app.platforms.capture.models import CaptureFrame
from app.vision.decision import DecisionEngine
from app.vision.pipeline import VisionPipeline
from app.vision.preprocessor import FramePreprocessor
from app.vision.violation_policy import ViolationEvidence, ViolationEvidenceType
from developer.benchmark.configs import (
    TARGET_CONTEXT_POLICY,
    TARGET_DETECTOR,
    TARGET_FULL_PROTECTION_PIPELINE,
    TARGET_VISION_PIPELINE,
    BenchmarkConfig,
)
from developer.benchmark.dataset import BenchmarkDataset, BenchmarkSample
from developer.benchmark.engine import evaluate_sample
from developer.benchmark.session import BenchmarkSession, CachedPrimaryDetector


class RecordingDetector:
    def __init__(self) -> None:
        self.detect_calls = 0

    def detect(self, prepared):
        self.detect_calls += 1
        self.last_shape = prepared.image.shape
        return (
            ViolationEvidence(
                evidence_type=ViolationEvidenceType.BREAST_EXPOSURE,
                label="FEMALE_BREAST_EXPOSED",
                confidence=0.91,
                bbox=(1.0, 2.0, 3.0, 4.0),
                model="nudenet_640m",
                frame_sequence=prepared.frame_sequence,
            ),
        )


def config_for(target: str) -> BenchmarkConfig:
    return BenchmarkConfig(
        id=target,
        benchmark_target=target,
        detector="nudenet_640m",
        context_model=None,
        full_input_size=640,
        tile_input_size=None,
        tile_rows=None,
        tile_columns=None,
        tile_overlap=0.0,
        checks_per_scan=None,
        threshold_profile="current",
    )


class SessionTests(unittest.TestCase):
    def test_context_policy_target_uses_real_rules_without_loading_an_image_or_model(self) -> None:
        detector_factory = Mock(side_effect=AssertionError("model loaded"))
        session = BenchmarkSession(
            config_for(TARGET_CONTEXT_POLICY),
            detector_factory=detector_factory,
        )
        sample = BenchmarkSample(
            "context",
            "missing.png",
            None,
            False,
            context_fixture={
                "application_identifier": "org.example.browser",
                "website_hostname": "blocked.example",
                "website_rules": [
                    {"domain": "blocked.example", "action": "force_block"}
                ],
            },
            expected_policy="force_block",
        )
        dataset = BenchmarkDataset("context", Path("/missing"), "now", [sample])

        result = evaluate_sample(session, dataset, sample)

        self.assertEqual(result["predicted"], "force_block")
        self.assertEqual(result["outcome"], "correct")
        detector_factory.assert_not_called()

    def test_full_protection_bypass_skips_image_and_detector(self) -> None:
        detector = RecordingDetector()
        session = BenchmarkSession(
            config_for(TARGET_FULL_PROTECTION_PIPELINE),
            pipeline=VisionPipeline(detector, DecisionEngine(local_detector=detector)),
        )
        sample = BenchmarkSample(
            "bypass",
            "missing.png",
            "allow",
            False,
            context_fixture={
                "application_identifier": "org.example.browser",
                "application_rules": [
                    {"identifier": "org.example.browser", "action": "full_bypass"}
                ],
            },
        )
        dataset = BenchmarkDataset("context", Path("/missing"), "now", [sample])

        result = evaluate_sample(session, dataset, sample)

        self.assertEqual(result["predicted"], "allow")
        self.assertEqual(result["context_summary"]["policy_action"], "full_bypass")
        self.assertFalse(result["vision_called"])
        self.assertEqual(detector.detect_calls, 0)

    def test_full_protection_force_block_skips_detector(self) -> None:
        detector = RecordingDetector()
        session = BenchmarkSession(
            config_for(TARGET_FULL_PROTECTION_PIPELINE),
            pipeline=VisionPipeline(detector, DecisionEngine(local_detector=detector)),
        )
        sample = BenchmarkSample(
            "forced",
            "missing.png",
            "block",
            False,
            context_fixture={
                "application_identifier": "org.example.app",
                "application_rules": [
                    {"identifier": "org.example.app", "action": "force_block"}
                ],
            },
        )

        result = session.run_full_pipeline(
            sample,
            np.zeros((20, 20, 3), dtype=np.uint8),
            sample_hash="hash",
        )

        self.assertEqual(result["predicted"], "block")
        self.assertFalse(result["vision_called"])
        self.assertEqual(detector.detect_calls, 0)

    def test_full_protection_normal_requires_temporal_confirmation(self) -> None:
        detector = RecordingDetector()
        session = BenchmarkSession(
            config_for(TARGET_FULL_PROTECTION_PIPELINE),
            pipeline=VisionPipeline(detector, DecisionEngine(local_detector=detector)),
        )
        sample = BenchmarkSample("normal", "image.png", "block", False)

        result = session.run_full_pipeline(
            sample,
            np.zeros((20, 20, 3), dtype=np.uint8),
            sample_hash="hash",
        )

        self.assertEqual(result["context_summary"]["policy_action"], "normal")
        self.assertEqual(result["predicted"], "block")
        self.assertTrue(result["vision_called"])
        self.assertTrue(result["temporal_summary"]["confirmed"])
        self.assertGreaterEqual(result["temporal_summary"]["fresh_frames"], 2)
        self.assertEqual(detector.detect_calls, 1)

    def test_vision_pipeline_is_separate_from_temporal_protection(self) -> None:
        detector = RecordingDetector()
        session = BenchmarkSession(
            config_for(TARGET_VISION_PIPELINE),
            pipeline=VisionPipeline(detector, DecisionEngine(local_detector=detector)),
        )
        sample = BenchmarkSample("vision", "image.png", "block", False)

        result = session.run_vision_pipeline(
            sample,
            np.zeros((20, 20, 3), dtype=np.uint8),
            sample_hash="hash",
        )

        self.assertEqual(result["predicted"], "block")
        self.assertIsNone(result["context_summary"]["policy_action"])
        self.assertIsNone(result["temporal_summary"])
        self.assertEqual(detector.detect_calls, 1)

    def test_cached_evidence_uses_each_replayed_frame_sequence(self) -> None:
        detector = CachedPrimaryDetector(
            [
                {"class": "FACE_FEMALE", "score": 0.99, "box": [0, 0, 1, 1]},
                {
                    "class": "FEMALE_BREAST_EXPOSED",
                    "score": 0.91,
                    "box": [1, 2, 3, 4],
                },
            ],
            "nudenet_640m",
        )
        frame = np.zeros((20, 20, 3), dtype=np.uint8)

        first = detector.detect(FramePreprocessor(CaptureFrame(frame, sequence=1)).prepare_full(640))
        second = detector.detect(FramePreprocessor(CaptureFrame(frame, sequence=2)).prepare_full(640))

        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].evidence_type, ViolationEvidenceType.BREAST_EXPOSURE)
        self.assertEqual(first[0].bbox, (1.0, 2.0, 3.0, 4.0))
        self.assertEqual(first[0].frame_sequence, 1)
        self.assertEqual(second[0].frame_sequence, 2)

    def test_detector_only_returns_raw_detections(self) -> None:
        config = BenchmarkConfig(
            id="det",
            benchmark_target=TARGET_DETECTOR,
            detector="nudenet_640m",
            context_model=None,
            full_input_size=640,
            tile_input_size=None,
            tile_rows=None,
            tile_columns=None,
            tile_overlap=0.0,
            checks_per_scan=None,
            threshold_profile="current",
        )
        detector = RecordingDetector()
        context_factory = Mock(side_effect=AssertionError("context model loaded"))
        session = BenchmarkSession(
            config,
            detector=detector,
            context_factory=context_factory,
        )
        sample = BenchmarkSample("000001", "a.png", "block", False, set())
        raw = session.run_detector_only(
            sample,
            np.zeros((20, 20, 3), dtype=np.uint8),
            sample_hash="hash",
        )
        self.assertEqual(raw.detections[0]["class"], "FEMALE_BREAST_EXPOSED")
        self.assertGreaterEqual(detector.detect_calls, 1)
        context_factory.assert_not_called()
        self.assertIsNone(session.pipeline)

    def test_detector_only_uses_product_full_frame_preparation(self) -> None:
        detector = RecordingDetector()
        session = BenchmarkSession(config_for(TARGET_DETECTOR), detector=detector)

        raw = session.run_detector_only(
            BenchmarkSample("large", "large.png", "block", False, set()),
            np.zeros((1200, 1600, 3), dtype=np.uint8),
            sample_hash="large-hash",
        )

        self.assertEqual(detector.last_shape, (480, 640, 3))
        self.assertGreaterEqual(raw.preprocess_ms, 0.0)
        self.assertEqual(raw.preprocessing_config, session.config.cache_geometry())

    def test_full_pipeline_maps_blocked_to_product_ground_truth(self) -> None:
        config = BenchmarkConfig(
            id="pipe",
            benchmark_target="full_protection_pipeline",
            detector="nudenet_640m",
            context_model=None,
            full_input_size=640,
            tile_input_size=None,
            tile_rows=None,
            tile_columns=None,
            tile_overlap=0.0,
            checks_per_scan=None,
            threshold_profile="current",
        )
        detector = RecordingDetector()
        pipeline = VisionPipeline(detector, DecisionEngine(local_detector=detector))
        session = BenchmarkSession(config, pipeline=pipeline)
        sample = BenchmarkSample("000001", "a.png", "block", False, set())
        result = session.run_full_pipeline(
            sample,
            np.zeros((20, 20, 3), dtype=np.uint8),
            sample_hash="hash",
        )
        self.assertIn(result["predicted"], {"block", "allow"})
        self.assertIn(result["outcome"], {"tp", "tn", "fp", "fn"})
        self.assertIn("decision_summary", result)

    def test_policy_rerun_does_not_call_the_real_detector(self) -> None:
        config = BenchmarkConfig(
            id="policy",
            benchmark_target="full_protection_pipeline",
            detector="nudenet_640m",
            context_model=None,
            full_input_size=640,
            tile_input_size=None,
            tile_rows=None,
            tile_columns=None,
            tile_overlap=0.0,
            checks_per_scan=None,
            threshold_profile="current",
        )
        detector = RecordingDetector()
        session = BenchmarkSession(config, detector=detector, context_ranker=None)
        sample = BenchmarkSample("000001", "a.png", "block", False, set())
        image = np.zeros((20, 20, 3), dtype=np.uint8)
        raw = session.run_detector_only(sample, image, sample_hash="hash")
        detect_after_inference = detector.detect_calls
        session.evaluate_policy(sample, image, raw)
        session.evaluate_policy(sample, image, raw)
        self.assertEqual(detector.detect_calls, detect_after_inference)
