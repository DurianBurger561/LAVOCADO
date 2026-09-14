"""Lab high-recall metrics never select Recommended."""

from __future__ import annotations

import json
import unittest

from developer.benchmark.high_recall import (
    benchmark_report,
    matrix_jobs,
    percentile,
    sanitize_case,
    select_recommended,
    summarize_cases,
)
from developer.benchmark.matrix import REQUIRED_METRICS, job_count


class HighRecallBenchmarkTests(unittest.TestCase):
    def test_summarize_records_required_metrics_without_recommended(self) -> None:
        cases = [
            {
                "case_id": "1",
                "scene": "thumbnail",
                "target_size": "small",
                "ground_truth": "violation",
                "predicted": "violation",
                "latency_ms": 10,
                "detection_delay_ms": 20,
                "top_tile_hit_rank": 1,
                "shadow_agreement": "both_hit",
            },
            {
                "case_id": "2",
                "scene": "full-screen image",
                "target_size": "large",
                "ground_truth": "clear",
                "predicted": "violation",
                "latency_ms": 30,
                "detection_delay_ms": 40,
                "top_tile_hit_rank": 3,
            },
            {
                "case_id": "3",
                "scene": "chat attachment",
                "target_size": "medium",
                "ground_truth": "violation",
                "predicted": "clear",
                "latency_ms": 50,
                "detection_delay_ms": 80,
                "top_tile_hit_rank": 2,
            },
            {
                "case_id": "4",
                "scene": "normal_apps",
                "target_size": "large",
                "ground_truth": "clear",
                "predicted": "clear",
                "latency_ms": 12,
                "detection_delay_ms": 12,
            },
        ]

        summary = summarize_cases(cases)

        self.assertEqual(summary["true_positives"], 1)
        self.assertEqual(summary["false_positives"], 1)
        self.assertEqual(summary["false_negatives"], 1)
        self.assertEqual(summary["true_negatives"], 1)
        self.assertEqual(summary["recall"], 0.5)
        self.assertEqual(summary["precision"], 0.5)
        self.assertEqual(summary["false_positive_rate"], 0.5)
        self.assertEqual(summary["false_negative_rate"], 0.5)
        self.assertEqual(summary["small_target_recall"], 1.0)
        self.assertEqual(summary["medium_target_recall"], 0.0)
        self.assertEqual(summary["large_target_recall"], 0.0)
        self.assertEqual(summary["top1_tile_hit_rate"], 1 / 3)
        self.assertAlmostEqual(summary["top2_tile_hit_rate"], 2 / 3)
        self.assertEqual(summary["p50_scan_latency_ms"], 21.0)
        self.assertEqual(summary["p95_scan_latency_ms"], 50.0)
        self.assertIsNone(summary["recommended"])
        self.assertIsNone(summary["product_block"])
        self.assertIsNone(select_recommended(summary))
        for metric in REQUIRED_METRICS:
            with self.subTest(metric=metric):
                self.assertIn(metric, summary["metrics_required"])

    def test_output_strips_pixels_and_paths(self) -> None:
        dirty = {
            "case_id": "x",
            "path": "/tmp/secret.png",
            "screenshot": "bytes",
            "url": "https://example.test",
            "window_title": "Private",
            "ground_truth": "clear",
            "predicted": "clear",
        }
        self.assertNotIn("path", sanitize_case(dirty))
        payload = json.dumps(benchmark_report([dirty]))
        for forbidden in ("secret.png", "screenshot", "example.test", "Private"):
            self.assertNotIn(forbidden, payload)
        self.assertIsNone(json.loads(payload)["recommended"])

    def test_matrix_jobs_are_measurement_cells_not_winners(self) -> None:
        jobs = matrix_jobs()
        self.assertEqual(len(jobs), job_count())
        self.assertGreater(len(jobs), 100)
        self.assertTrue(all(job["recommended"] is None for job in jobs[:20]))
        self.assertIsNone(percentile([], 95))
        self.assertEqual(percentile([4.0], 95), 4.0)


if __name__ == "__main__":
    unittest.main()
