"""Runner keeps completed rows after cancel."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.vision.decision import DecisionEngine
from app.vision.pipeline import VisionPipeline
from developer.benchmark.configs import BenchmarkConfig
from developer.benchmark.dataset import create_dataset, import_paths, update_sample
from developer.benchmark.runner import BenchmarkRunner
from developer.benchmark.session import BenchmarkSession

try:
    from benchmark.helpers import write_png
except ImportError:
    from tests.benchmark.helpers import write_png


class FakeDetector:
    def detect(self, image, *, input_size: int = 640, frame_sequence: int):
        del image, input_size, frame_sequence
        return []


class RunnerTests(unittest.TestCase):
    def test_cancel_keeps_completed_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset = create_dataset(root, "run")
            paths = [write_png(root / f"{index}.png", (index, 2, 3)) for index in range(3)]
            import_paths(dataset, paths, mode="reference")
            for sample in dataset.samples:
                update_sample(dataset, sample.id, expected="allow")
            config = BenchmarkConfig(
                id="c1",
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

            def factory(cfg, cache=None, **kwargs):
                pipeline = VisionPipeline(detector, DecisionEngine(local_detector=detector))
                return BenchmarkSession(cfg, pipeline=pipeline, cache=cache)

            runner = BenchmarkRunner(dataset, [config], session_factory=factory)

            def on_progress(progress):
                if int(progress.get("sample_index") or 0) >= 1:
                    runner.request_cancel()

            run = runner.start(on_progress=on_progress)
            self.assertTrue(run.cancelled)
            self.assertGreaterEqual(len(run.rows), 1)
            self.assertLess(len(run.rows), 3)
            self.assertTrue((dataset.results_dir / f"{run.id}.json").is_file())
