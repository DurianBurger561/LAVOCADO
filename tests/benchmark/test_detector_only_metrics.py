"""Detector Only must not compute product Block/Allow FP/FN."""

from __future__ import annotations

import unittest

from developer.benchmark.metrics import summarize_detector_rows, summarize_rows
from developer.benchmark.results import BenchmarkRun, finalize_run


class DetectorOnlyMetricsTests(unittest.TestCase):
    def test_detector_summary_has_no_confusion_counts(self) -> None:
        summary = summarize_detector_rows(
            [
                {
                    "target": "detector_only",
                    "expected": "block",
                    "raw": {
                        "detections": [
                            {
                                "class": "FEMALE_BREAST_EXPOSED",
                                "score": 0.91,
                                "box": [1, 2, 3, 4],
                            }
                        ],
                        "inference_ms": 12.0,
                    },
                }
            ]
        )
        self.assertEqual(summary["target"], "detector_only")
        self.assertEqual(summary["detection_count"], 1)
        self.assertNotIn("tp", summary)
        self.assertNotIn("fn", summary)
        self.assertNotIn("recall", summary)
        self.assertNotIn("accuracy", summary)

    def test_finalize_run_does_not_fallback_detector_rows_into_product_metrics(self) -> None:
        run = BenchmarkRun(
            id="d1",
            created_at="2026-01-01T00:00:00+00:00",
            dataset_name="desk",
            dataset_hash="x",
            engine_version=1,
            product_version="LAVOCADO Developer",
            configs=[{"id": "c1", "benchmark_target": "detector_only"}],
            rows=[
                {
                    "config_id": "c1",
                    "target": "detector_only",
                    "expected": "block",
                    "predicted": "block",
                    "raw": {
                        "detections": [{"class": "FEMALE_BREAST_EXPOSED", "score": 0.8, "box": None}],
                        "inference_ms": 9.0,
                    },
                }
            ],
        )
        finalize_run(run)
        summary = run.summaries["c1"]
        self.assertEqual(summary["target"], "detector_only")
        self.assertNotIn("tp", summary)
        product = summarize_rows(run.rows)
        self.assertIn("tp", product)
