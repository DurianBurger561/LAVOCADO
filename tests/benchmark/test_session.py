"""Detector-only and full pipeline session behavior."""

from __future__ import annotations

import unittest

import numpy as np

from app.vision.decision import DecisionEngine
from app.vision.pipeline import VisionPipeline
from app.vision.violation_policy import ViolationEvidence, ViolationEvidenceType
from developer.benchmark.configs import TARGET_DETECTOR, BenchmarkConfig
from developer.benchmark.dataset import BenchmarkSample
from developer.benchmark.session import BenchmarkSession, CachedPrimaryDetector


class RecordingDetector:
    def __init__(self) -> None:
        self.detect_calls = 0

    def detect(self, frame, *, input_size: int, frame_sequence: int):
        self.detect_calls += 1
        del input_size, frame
        return [
            ViolationEvidence(
                evidence_type=ViolationEvidenceType.BREAST_EXPOSURE,
                label="FEMALE_BREAST_EXPOSED",
                confidence=0.91,
                bbox=(1.0, 2.0, 3.0, 4.0),
                model="nudenet_640m",
                frame_sequence=frame_sequence,
            )
        ]


class SessionTests(unittest.TestCase):
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

        first = detector.detect(frame, input_size=640, frame_sequence=1)
        second = detector.detect(frame, input_size=640, frame_sequence=2)

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
        session.evaluate_policy(sample, image, raw)
        session.evaluate_policy(sample, image, raw)
        self.assertEqual(detector.detect_calls, detect_after_inference)
