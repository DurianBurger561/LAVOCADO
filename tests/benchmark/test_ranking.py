"""Viddexa Top-1 / Top-2 relevant tile rates. Never product Block accuracy."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from developer.benchmark.metrics import summarize_rows
from developer.benchmark.ranking import (
    measure_ranking,
    sample_ranking,
    summarize_ranking,
)


class FakeRanker:
    name = "viddexa_nano"

    def classify(self, image: np.ndarray) -> dict[str, float]:
        left = float(image[:, : max(1, image.shape[1] // 2)].mean())
        return {
            "porn": left / 255.0,
            "hentai": 0.0,
            "normal": 1.0 - left / 255.0,
            "sexy": 0.0,
            "drawing": 0.0,
        }


class RankingTests(unittest.TestCase):
    def test_top1_when_highest_risk_tile_holds_the_detection(self) -> None:
        tiles = [
            SimpleNamespace(index=0, region=(0, 0, 10, 10), context_scores={"porn": 0.9, "hentai": 0.1}),
            SimpleNamespace(index=1, region=(10, 0, 20, 10), context_scores={"porn": 0.1, "hentai": 0.0}),
        ]
        detections = [{"class": "FEMALE_BREAST_EXPOSED", "score": 0.8, "box": [1, 1, 4, 4]}]
        ranking = sample_ranking(tiles, detections, context_latency_ms=12.0)
        self.assertTrue(ranking["eligible"])
        self.assertTrue(ranking["top1"])
        self.assertTrue(ranking["top2"])
        self.assertIsNone(ranking["product_block"])
        self.assertAlmostEqual(ranking["context_latency_ms"], 12.0)

    def test_top2_when_relevant_tile_is_second(self) -> None:
        tiles = [
            SimpleNamespace(index=0, region=(0, 0, 10, 10), context_scores={"porn": 0.95, "hentai": 0.0}),
            SimpleNamespace(index=1, region=(10, 0, 20, 10), context_scores={"porn": 0.4, "hentai": 0.0}),
        ]
        detections = [{"class": "FEMALE_BREAST_EXPOSED", "score": 0.8, "box": [12, 1, 4, 4]}]
        ranking = sample_ranking(tiles, detections)
        self.assertFalse(ranking["top1"])
        self.assertTrue(ranking["top2"])

    def test_ineligible_without_primary_hit(self) -> None:
        tiles = [
            SimpleNamespace(index=0, region=(0, 0, 10, 10), context_scores={"porn": 0.9}),
        ]
        ranking = sample_ranking(tiles, [])
        self.assertFalse(ranking["eligible"])
        self.assertIsNone(ranking["top1"])

    def test_measure_ranking_times_context_and_skips_off(self) -> None:
        image = np.zeros((20, 20, 3), dtype=np.uint8)
        image[:, :10] = 255
        detections = [{"class": "FEMALE_BREAST_EXPOSED", "score": 0.8, "box": [1, 1, 4, 4]}]
        ranked = measure_ranking(
            FakeRanker(),
            image,
            detections,
            rows=2,
            columns=2,
            overlap=0.0,
            context_model="viddexa_nano",
        )
        self.assertTrue(ranked["eligible"])
        self.assertTrue(ranked["top1"])
        self.assertGreaterEqual(ranked["context_latency_ms"], 0.0)
        self.assertIsNone(
            measure_ranking(
                FakeRanker(),
                image,
                detections,
                rows=2,
                columns=2,
                context_model="off",
            )
        )

    def test_summary_aggregates_top_rates(self) -> None:
        rows = [
            {
                "expected": "block",
                "predicted": "block",
                "excluded": False,
                "tags": [],
                "total_ms": 10,
                "ranking": {
                    "eligible": True,
                    "top1": True,
                    "top2": True,
                    "context_latency_ms": 8.0,
                },
            },
            {
                "expected": "block",
                "predicted": "block",
                "excluded": False,
                "tags": [],
                "total_ms": 11,
                "ranking": {
                    "eligible": True,
                    "top1": False,
                    "top2": True,
                    "context_latency_ms": 12.0,
                },
            },
        ]
        summary = summarize_rows(rows)
        ranking = summary["ranking"]
        self.assertAlmostEqual(ranking["top1_relevant_tile_rate"], 0.5)
        self.assertAlmostEqual(ranking["top2_relevant_tile_rate"], 1.0)
        self.assertAlmostEqual(ranking["mean_context_latency_ms"], 10.0)
        self.assertIsNone(ranking["product_block"])
        self.assertEqual(summarize_ranking([]), None)
