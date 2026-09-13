"""Unlabelled samples can preview/run detector-only but skip metrics."""

from __future__ import annotations

import unittest

from developer.benchmark.metrics import outcome_for, summarize_rows


class UnlabelledMetricsTests(unittest.TestCase):
    def test_unlabelled_is_not_scored(self) -> None:
        rows = [
            {
                "expected": None,
                "predicted": "block",
                "excluded": False,
                "tags": [],
                "total_ms": 8,
            },
            {
                "expected": "allow",
                "predicted": "allow",
                "excluded": False,
                "tags": [],
                "total_ms": 9,
            },
        ]
        summary = summarize_rows(rows)
        self.assertEqual(summary["tn"], 1)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(outcome_for(None, "block", excluded=False), "unlabelled")
