"""Comparison highlights individual metrics, never Best Overall."""

from __future__ import annotations

import unittest

from developer.benchmark.comparison import compare_summaries, sort_rows


class ComparisonTests(unittest.TestCase):
    def test_highlights_without_best_overall(self) -> None:
        configs = [
            {"id": "a", "detector": "nudenet_640m", "full_input_size": 640},
            {"id": "b", "detector": "yolo11_nsfw_small", "full_input_size": 960},
        ]
        summaries = {
            "a": {"recall": 0.88, "fnr": 0.12, "fpr": 0.04, "p95_latency_ms": 140, "precision": 0.9, "accuracy": 0.91},
            "b": {"recall": 0.96, "fnr": 0.04, "fpr": 0.08, "p95_latency_ms": 200, "precision": 0.89, "accuracy": 0.94},
        }
        comparison = compare_summaries(configs, summaries)
        self.assertEqual(comparison["highlights"]["highest_recall"], "b")
        self.assertEqual(comparison["highlights"]["lowest_fnr"], "b")
        self.assertEqual(comparison["highlights"]["lowest_fpr"], "a")
        self.assertEqual(comparison["highlights"]["lowest_latency"], "a")
        self.assertNotIn("best_overall", comparison["highlights"])
        sorted_rows = sort_rows(comparison["rows"], "recall")
        self.assertEqual(sorted_rows[0]["config_id"], "b")
