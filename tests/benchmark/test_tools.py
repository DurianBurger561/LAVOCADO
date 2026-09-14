"""Developer Lab offline tools keep visual and product metrics separate."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from developer.benchmark.dataset import (
    create_dataset,
    import_paths,
    open_dataset,
    update_sample,
)
from developer.benchmark.diagnostic_worker import detector_comparison, ranker_signal
from developer.benchmark.preprocessor_benchmark import benchmark_preprocessor
from tests.benchmark.helpers import write_png


class FakeNudeModel:
    def __init__(self, inference_resolution: int, **_kwargs) -> None:
        self.size = inference_resolution

    def detect(self, _image):
        if self.size == 640:
            return [{"class": "FEMALE_BREAST_EXPOSED", "score": 0.99, "box": [0, 0, 8, 8]}]
        return []


class FakeRanker:
    def classify(self, _image):
        return {"normal": 0.1, "porn": 0.8, "hentai": 0.1}


class EmptyRanker:
    def classify(self, _image):
        return {}


class LabToolTests(unittest.TestCase):
    def test_detector_comparison_uses_visual_truth_not_product_allow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = create_dataset(root, "visual")
            import_paths(dataset, [write_png(root / "medical.png")], mode="copy")
            sample = dataset.samples[0]
            update_sample(dataset, sample.id, expected="allow", expected_visual="violation")
            progress = []
            with patch("app.vision.model_assets.resolve_nudenet_model_path", return_value=root / "640m.onnx"):
                result = detector_comparison(dataset, model_factory=FakeNudeModel, progress=progress.append)

            self.assertTrue(result["ok"])
            self.assertIsNone(result["product_block"])
            self.assertEqual(result["summaries"]["nudenet_640m"]["visual_recall"], 1.0)
            self.assertEqual(result["summaries"]["nudenet_320n"]["visual_recall"], 0.0)
            self.assertEqual(progress[0]["completed"], 1)
            self.assertNotIn("medical.png", str(result))
            self.assertEqual(open_dataset(dataset.document_path).samples[0].expected_visual, "violation")

    def test_ranker_signal_never_produces_product_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = create_dataset(root, "ranker")
            import_paths(dataset, [write_png(root / "frame.png")], mode="copy")
            result = ranker_signal(dataset, model_name="viddexa_nano", ranker=FakeRanker())
            self.assertTrue(result["ok"])
            self.assertEqual(result["rows"][0]["rank_risk"], 0.8)
            self.assertIsNone(result["product_block"])
            self.assertNotIn("frame.png", str(result))
            empty = ranker_signal(dataset, model_name="viddexa_nano", ranker=EmptyRanker())
            self.assertTrue(empty["rows"][0]["inference_failed"])

    def test_preprocessor_tool_uses_only_synthetic_pixels(self) -> None:
        result = benchmark_preprocessor(iterations=2, width=32, height=24, size=16)
        self.assertTrue(result["ok"])
        self.assertTrue(result["synthetic_pixels_only"])
        self.assertEqual(result["iterations"], 2)
        with self.assertRaises(ValueError):
            benchmark_preprocessor(iterations=0)
        with self.assertRaisesRegex(ValueError, "16 megapixels"):
            benchmark_preprocessor(iterations=1, width=8192, height=8192)
