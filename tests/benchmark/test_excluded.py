"""Excluded samples stay out of TP/TN/FP/FN."""

from __future__ import annotations

import unittest

from developer.benchmark.metrics import outcome_for, summarize_rows


class ExcludedMetricsTests(unittest.TestCase):
    def test_excluded_labelled_sample_is_omitted(self) -> None:
        rows = [
            {
                "expected": "block",
                "predicted": "allow",
                "excluded": True,
                "tags": [],
                "total_ms": 10,
            },
            {
                "expected": "block",
                "predicted": "block",
                "excluded": False,
                "tags": [],
                "total_ms": 12,
            },
        ]
        summary = summarize_rows(rows)
        self.assertEqual(summary["tp"], 1)
        self.assertEqual(summary["fn"], 0)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(outcome_for("block", "allow", excluded=True), "excluded")
