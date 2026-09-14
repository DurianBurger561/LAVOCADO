"""Raw inference cache reuse."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from developer.benchmark.inference_cache import (
    InferenceCache,
    RawInferenceResult,
    cache_key,
)


class CacheTests(unittest.TestCase):
    def test_round_trip_and_key_stability(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = InferenceCache(Path(temp_dir))
            key = cache_key(
                sample_hash="abc",
                model_id="nudenet_640m",
                model_revision="rev",
                input_size=640,
                region_id="full",
                preprocessing_config="full",
            )
            result = RawInferenceResult(
                sample_id="000001",
                model_id="nudenet_640m",
                model_revision="rev",
                input_size=640,
                region_id="full",
                detections=[{"class": "FEMALE_BREAST_EXPOSED", "score": 0.9, "box": [1, 2, 3, 4]}],
                inference_ms=12.5,
            )
            cache.put(key, result)
            loaded = cache.get(key)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.detections[0]["class"], "FEMALE_BREAST_EXPOSED")
            same = cache_key(
                sample_hash="abc",
                model_id="nudenet_640m",
                model_revision="rev",
                input_size=640,
                region_id="full",
                preprocessing_config="full",
            )
            self.assertEqual(key, same)
            changed = cache_key(
                sample_hash="abc",
                model_id="nudenet_640m",
                model_revision="rev",
                input_size=960,
                region_id="full",
                preprocessing_config="full",
            )
            self.assertNotEqual(key, changed)
            self.assertNotEqual(
                key,
                cache_key(
                    sample_hash="abc",
                    model_id="nudenet_640m",
                    model_revision="next-revision",
                    input_size=640,
                    region_id="full",
                    preprocessing_config="full",
                ),
            )
            self.assertNotEqual(
                key,
                cache_key(
                    sample_hash="abc",
                    model_id="nudenet_640m",
                    model_revision="rev",
                    input_size=640,
                    region_id="full",
                    preprocessing_config="rgb:bilinear",
                ),
            )
