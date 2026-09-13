"""Benchmark Lab must reuse the product Vision / Decision core."""

from __future__ import annotations

import unittest

from app.settings.schema import VisionSettings
from app.vision.decision import DecisionEngine
from app.vision.detectors.factory import load_primary_bundle
from app.vision.pipeline import VisionPipeline
from developer.benchmark import session as session_mod
from developer.benchmark.configs import BenchmarkConfig


class CoreReuseTests(unittest.TestCase):
    def test_session_imports_product_factories(self) -> None:
        self.assertIs(session_mod.DecisionEngine, DecisionEngine)
        self.assertIs(session_mod.VisionPipeline, VisionPipeline)
        self.assertIs(session_mod.load_primary_bundle, load_primary_bundle)

    def test_config_uses_product_settings_schema(self) -> None:
        config = BenchmarkConfig(
            id="reuse",
            benchmark_target="full_protection_pipeline",
            detector="nudenet_640m",
            context_model="off",
            full_input_size=640,
            tile_input_size=None,
            tile_rows=None,
            tile_columns=None,
            tile_overlap=0.0,
            checks_per_scan=None,
            threshold_profile="current",
        )
        settings = config.vision_settings()
        self.assertIsInstance(settings, VisionSettings)
        self.assertEqual(settings.detector.primary, "nudenet_640m")
