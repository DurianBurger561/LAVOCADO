"""Detector-only and full pipeline session behavior."""

from __future__ import annotations

import unittest

import numpy as np

from app.vision.decision import DecisionEngine
from app.vision.detectors.base import DetectionEvidence
from app.vision.pipeline import VisionPipeline
from developer.benchmark.configs import TARGET_DETECTOR, BenchmarkConfig
from developer.benchmark.dataset import BenchmarkSample
from developer.benchmark.session import BenchmarkSession


class RecordingDetector:
    def __init__(self) -> None:
        self.detect_calls = 0
        self.check_calls = 0

    def detect(self, frame, *, input_size: int):
        self.detect_calls += 1
        del input_size, frame
        return [
            DetectionEvidence(
                label="FEMALE_BREAST_EXPOSED",
                confidence=0.91,
                box=(1.0, 2.0, 3.0, 4.0),
                model="nudenet_640m",
            )
        ]

    def check(self, image):
        self.check_calls += 1
        return {
            "blocked": True,
            "reason": "strong",
            "label": "FEMALE_BREAST_EXPOSED",
            "confidence": 0.91,
            "box": [1, 2, 3, 4],
            "check_points": [
                {"class": "FEMALE_BREAST_EXPOSED", "score": 0.91, "box": [1, 2, 3, 4]}
            ],
        }


class SessionTests(unittest.TestCase):
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
        session = BenchmarkSession(config, detector=detector, context_ranker=None)
        sample = BenchmarkSample("000001", "a.png", "block", False, set())
        raw = session.run_detector_only(
            sample,
            np.zeros((20, 20, 3), dtype=np.uint8),
            sample_hash="hash",
        )
        self.assertEqual(raw.detections[0]["class"], "FEMALE_BREAST_EXPOSED")
        self.assertGreaterEqual(detector.detect_calls, 1)

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
        check_after_inference = detector.check_calls
        session.evaluate_policy(sample, image, raw)
        session.evaluate_policy(sample, image, raw)
        self.assertEqual(detector.detect_calls, detect_after_inference)
        self.assertEqual(detector.check_calls, check_after_inference)
