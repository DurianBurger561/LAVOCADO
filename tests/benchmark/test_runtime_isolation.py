"""Benchmark sessions must not touch Overlay or Protection history."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from app.vision.decision import DecisionEngine
from app.vision.pipeline import VisionPipeline
from developer.benchmark.configs import BenchmarkConfig
from developer.benchmark.dataset import BenchmarkSample
from developer.benchmark.session import BenchmarkSession


class FakeDetector:
    def detect(self, image, *, input_size: int = 640, frame_sequence: int):
        del image, input_size, frame_sequence
        return []


class IsolationTests(unittest.TestCase):
    def test_session_source_does_not_import_overlay_or_recorder(self) -> None:
        import developer.benchmark.session as session_mod

        source = Path(session_mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("from app.vision.overlay", source)
        self.assertNotIn("from app.intervention.recorder", source)
        self.assertNotIn("import Overlay", source)
        self.assertNotIn("EventRecorder", source)

    def test_full_pipeline_does_not_call_overlay_or_recorder(self) -> None:
        config = BenchmarkConfig(
            id="iso",
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
        detector = FakeDetector()
        pipeline = VisionPipeline(detector, DecisionEngine(local_detector=detector))
        session = BenchmarkSession(config, pipeline=pipeline)
        sample = BenchmarkSample("1", "x.png", "block", False, set())
        image = np.zeros((16, 16, 3), dtype=np.uint8)
        overlay = Mock()
        recorder = Mock()
        with (
            patch("app.vision.overlay.Overlay", overlay),
            patch("app.intervention.recorder.EventRecorder", recorder),
        ):
            session.run_full_pipeline(sample, image, sample_hash="abc")
        overlay.assert_not_called()
        recorder.assert_not_called()
