"""Tag-based allow rate and recall."""

from __future__ import annotations

import unittest

from developer.benchmark.metrics import summarize_rows


class TagMetricsTests(unittest.TestCase):
    def test_non_pornographic_purpose_allow_rate(self) -> None:
        rows = [
            {
                "expected": "allow",
                "predicted": "allow",
                "excluded": False,
                "tags": ["non_pornographic_purpose", "medical"],
                "total_ms": 10,
            },
            {
                "expected": "allow",
                "predicted": "block",
                "excluded": False,
                "tags": ["non_pornographic_purpose", "medical"],
                "total_ms": 11,
            },
            {
                "expected": "block",
                "predicted": "block",
                "excluded": False,
                "tags": ["small_target"],
                "total_ms": 12,
            },
        ]
        summary = summarize_rows(rows)
        tags = summary["tag_metrics"]
        self.assertAlmostEqual(tags["non_pornographic_purpose_allow_rate"], 0.5)
        self.assertAlmostEqual(tags["medical"]["allow_rate"], 0.5)
        self.assertAlmostEqual(tags["small_target"]["recall"], 1.0)
