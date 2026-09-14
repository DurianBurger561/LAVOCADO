"""Lab Viddexa ranking quality is not product Block accuracy."""

import unittest

from developer.benchmark.ranking_metrics import (
    detector_metrics,
    prioritize_tiles,
    ranking_quality,
    recall_gain,
    viddexa_rank_risk,
)


class RankingBenchmarkTests(unittest.TestCase):
    def test_high_porn_score_never_becomes_product_block(self) -> None:
        tiles = [
            {"index": 0, "scores": {"porn": 0.99, "hentai": 0.0}, "primary_hit": False},
            {"index": 1, "scores": {"porn": 0.01}, "primary_hit": False},
        ]

        quality = ranking_quality(tiles)

        self.assertEqual(quality["metric_kind"], "tile_ranking_quality")
        self.assertIsNone(quality["product_block"])
        self.assertFalse(quality["prioritized_primary_hit"])
        self.assertEqual(quality["top_tile_index"], 0)

    def test_ranking_puts_primary_hit_tile_first(self) -> None:
        tiles = [
            {"index": 0, "scores": {"porn": 0.20}, "primary_hit": False},
            {"index": 1, "scores": {"porn": 0.10, "hentai": 0.95}, "primary_hit": True},
            {"index": 2, "scores": {"sexy": 0.99, "porn": 0.0}, "primary_hit": False},
        ]

        ordered = prioritize_tiles(tiles)
        quality = ranking_quality(tiles)

        self.assertEqual([tile["index"] for tile in ordered], [1, 0, 2])
        self.assertTrue(quality["prioritized_primary_hit"])
        self.assertEqual(quality["reciprocal_rank"], 1.0)
        self.assertIsNone(quality["product_block"])
        self.assertLess(viddexa_rank_risk({"sexy": 0.99}), 0.5)

    def test_tile_rescue_reports_recall_gain_not_block_accuracy(self) -> None:
        gain = recall_gain(baseline_hits=6, with_tile_hits=8, positives=10)

        self.assertEqual(gain["baseline_recall"], 0.6)
        self.assertEqual(gain["tile_recall"], 0.8)
        self.assertAlmostEqual(gain["recall_gain"], 0.2)
        self.assertIsNone(gain["product_block"])

    def test_detector_metrics_do_not_take_viddexa_porn_accuracy(self) -> None:
        metrics = detector_metrics(
            true_positives=8,
            false_positives=2,
            false_negatives=2,
            small_target_true_positives=3,
            small_target_positives=5,
            roi_rescue_hits=1,
            tile_rescue_hits=2,
            latency_ms=12.5,
        )

        self.assertEqual(metrics["precision"], 0.8)
        self.assertEqual(metrics["recall"], 0.8)
        self.assertEqual(metrics["small_target_recall"], 0.6)
        self.assertEqual(metrics["roi_rescue_hits"], 1)
        self.assertEqual(metrics["tile_recall_hits"], 2)
        self.assertIsNone(metrics["product_block"])
        self.assertNotIn("porn_accuracy", metrics)


if __name__ == "__main__":
    unittest.main()
