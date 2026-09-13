"""Metric formulas from the implementation guide."""

from __future__ import annotations

import unittest

from developer.benchmark.metrics import ConfusionCounts, metric_bundle


class MetricsTests(unittest.TestCase):
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
