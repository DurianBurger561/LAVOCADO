"""Metric formulas from the implementation guide."""

from __future__ import annotations

import unittest

from developer.benchmark.metrics import (
    ConfusionCounts,
    metric_bundle,
    summarize_context_rows,
)


class MetricsTests(unittest.TestCase):
    def test_context_policy_metrics_do_not_use_block_allow_confusion_counts(self) -> None:
        summary = summarize_context_rows([
            {"expected": "normal", "predicted": "normal", "outcome": "correct", "total_ms": 1.0},
            {"expected": "force_block", "predicted": "normal", "outcome": "incorrect", "total_ms": 2.0},
            {"expected": None, "predicted": "normal", "outcome": "unlabelled", "total_ms": 3.0},
        ])

        self.assertEqual(summary["target"], "context_policy")
        self.assertEqual(summary["labelled_count"], 2)
        self.assertEqual(summary["accuracy"], 0.5)
        self.assertNotIn("tp", summary)

    def test_guide_example(self) -> None:
        counts = ConfusionCounts(tp=90, fn=10, tn=95, fp=5)
        bundle = metric_bundle(counts)
        self.assertAlmostEqual(bundle["recall"], 0.90)
        self.assertAlmostEqual(bundle["fnr"], 0.10)
        self.assertAlmostEqual(bundle["fpr"], 0.05)
        self.assertAlmostEqual(bundle["precision"], 90 / 95)
        self.assertAlmostEqual(bundle["accuracy"], 0.925)
        self.assertAlmostEqual(bundle["failure_rate"], 0.075)

    def test_empty_set_is_none_not_zero(self) -> None:
        bundle = metric_bundle(ConfusionCounts())
        self.assertIsNone(bundle["recall"])
        self.assertIsNone(bundle["accuracy"])
        self.assertEqual(bundle["total"], 0)
