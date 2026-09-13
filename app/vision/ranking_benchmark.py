"""Viddexa ranking metrics. Porn scores never become product Block accuracy."""

from __future__ import annotations

from typing import Any


def viddexa_rank_risk(scores: dict[str, Any] | None) -> float:
    """Porn/hentai risk used only to order tiles for the primary detector."""

    if not scores:
        return 0.0
    return max(
        float(scores.get("porn", 0.0) or 0.0),
        float(scores.get("hentai", 0.0) or 0.0),
    )


def prioritize_tiles(tiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Highest porn/hentai risk first; index is the tie-breaker."""

    return sorted(
        tiles,
        key=lambda tile: (
            -viddexa_rank_risk(tile.get("scores")),
            int(tile.get("index", 0)),
        ),
    )


def ranking_quality(tiles: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure whether ranking put a primary-detector hit first.

    ``product_block`` is always None. Viddexa cannot decide Protection.
    """

    if not tiles:
        return {
            "metric_kind": "tile_ranking_quality",
            "tile_count": 0,
            "top_tile_index": None,
            "reciprocal_rank": 0.0,
            "prioritized_primary_hit": False,
            "product_block": None,
        }
    ordered = prioritize_tiles(tiles)
    top_index = int(ordered[0].get("index", 0))
    hit_indexes = [
        int(tile.get("index", 0))
        for tile in tiles
        if bool(tile.get("primary_hit"))
    ]
    if not hit_indexes:
        return {
            "metric_kind": "tile_ranking_quality",
            "tile_count": len(tiles),
            "top_tile_index": top_index,
            "reciprocal_rank": 0.0,
            "prioritized_primary_hit": False,
            "product_block": None,
        }
    rank = next(
        index
        for index, tile in enumerate(ordered, start=1)
        if int(tile.get("index", 0)) in hit_indexes
    )
    return {
        "metric_kind": "tile_ranking_quality",
        "tile_count": len(tiles),
        "top_tile_index": top_index,
        "reciprocal_rank": 1.0 / rank,
        "prioritized_primary_hit": rank == 1,
        "product_block": None,
    }


def recall_gain(
    *,
    baseline_hits: int,
    with_tile_hits: int,
    positives: int,
) -> dict[str, Any]:
    """Recall added by tile ranking plus primary-detector recheck."""

    total = max(0, int(positives))
    baseline = max(0, int(baseline_hits))
    rescued = max(0, int(with_tile_hits))
    baseline_recall = 0.0 if total == 0 else min(1.0, baseline / total)
    tile_recall = 0.0 if total == 0 else min(1.0, rescued / total)
    return {
        "metric_kind": "tile_recall_gain",
        "baseline_recall": baseline_recall,
        "tile_recall": tile_recall,
        "recall_gain": max(0.0, tile_recall - baseline_recall),
        "product_block": None,
    }


def detector_metrics(
    *,
    true_positives: int,
    false_positives: int,
    false_negatives: int,
    small_target_true_positives: int = 0,
    small_target_positives: int = 0,
    roi_rescue_hits: int = 0,
    tile_rescue_hits: int = 0,
    latency_ms: float | None = None,
) -> dict[str, Any]:
    """NudeNet/YOLO detector metrics. Viddexa scores are not inputs."""

    tp = max(0, int(true_positives))
    fp = max(0, int(false_positives))
    fn = max(0, int(false_negatives))
    precision = 0.0 if tp + fp == 0 else tp / (tp + fp)
    recall = 0.0 if tp + fn == 0 else tp / (tp + fn)
    small_pos = max(0, int(small_target_positives))
    small_tp = max(0, int(small_target_true_positives))
    return {
        "metric_kind": "detector_benchmark",
        "precision": precision,
        "recall": recall,
        "small_target_recall": (
            0.0 if small_pos == 0 else min(1.0, small_tp / small_pos)
        ),
        "roi_rescue_hits": max(0, int(roi_rescue_hits)),
        "tile_recall_hits": max(0, int(tile_rescue_hits)),
        "latency_ms": None if latency_ms is None else float(latency_ms),
        "product_block": None,
    }
