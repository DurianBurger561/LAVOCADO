"""Viddexa ranking stats. Porn scores never become product Block accuracy."""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping, Sequence
from types import SimpleNamespace
from typing import Any

import numpy as np

from app.vision.regions import (
    Region,
    crop_region,
    overlapping_tile_regions,
    tile_regions,
)
from developer.benchmark.ranking_metrics import prioritize_tiles, ranking_quality


def box_overlaps_region(box: object, region: Region) -> bool:
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return False
    try:
        x, y, width, height = (float(value) for value in box)
    except (TypeError, ValueError):
        return False
    if width <= 0 or height <= 0:
        return False
    left, top, right, bottom = region
    return x < right and left < x + width and y < bottom and top < y + height


def tiles_with_primary_hits(
    tiles: Sequence[Any],
    detections: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    boxes = [item.get("box") for item in detections if isinstance(item, Mapping)]
    payload: list[dict[str, Any]] = []
    for tile in tiles:
        index = int(getattr(tile, "index", 0))
        region = getattr(tile, "region", None)
        scores = dict(getattr(tile, "context_scores", None) or {})
        hit = False
        if isinstance(region, (list, tuple)) and len(region) == 4:
            region_tuple = (
                int(region[0]),
                int(region[1]),
                int(region[2]),
                int(region[3]),
            )
            hit = any(box_overlaps_region(box, region_tuple) for box in boxes)
        payload.append(
            {
                "index": index,
                "scores": scores,
                "primary_hit": hit,
            }
        )
    return payload


def sample_ranking(
    tiles: Sequence[Any],
    detections: Iterable[Mapping[str, Any]],
    *,
    context_latency_ms: float | None = None,
) -> dict[str, Any] | None:
    """Top-1 / Top-2 relevant-tile placement for one sample.

    Eligible only when at least one tile overlaps a primary detection.
    """

    if not tiles:
        return None
    payload = tiles_with_primary_hits(tiles, detections)
    quality = ranking_quality(payload)
    ordered = prioritize_tiles(payload)
    hit_indexes = {int(tile["index"]) for tile in payload if tile["primary_hit"]}
    if not hit_indexes:
        return {
            "eligible": False,
            "top1": None,
            "top2": None,
            "reciprocal_rank": 0.0,
            "tile_count": len(payload),
            "context_latency_ms": context_latency_ms,
            "product_block": None,
        }
    top_indexes = [int(tile["index"]) for tile in ordered[:2]]
    return {
        "eligible": True,
        "top1": bool(top_indexes) and top_indexes[0] in hit_indexes,
        "top2": any(index in hit_indexes for index in top_indexes),
        "reciprocal_rank": quality["reciprocal_rank"],
        "tile_count": len(payload),
        "context_latency_ms": context_latency_ms,
        "product_block": None,
    }


def measure_ranking(
    classifier: Any,
    image: np.ndarray,
    detections: Iterable[Mapping[str, Any]],
    *,
    rows: int | None,
    columns: int | None,
    overlap: float = 0.0,
    context_model: str | None = None,
) -> dict[str, Any] | None:
    """Classify tiles with the real context ranker and score Top-1 / Top-2."""

    if context_model in {None, "off"} or classifier is None:
        return None
    if rows is None or columns is None or rows < 2 or columns < 2:
        return None
    if not isinstance(image, np.ndarray):
        return None
    regions = overlapping_tile_regions(image.shape, int(rows), int(columns), float(overlap))
    if not regions:
        regions = tile_regions(image.shape, int(rows), int(columns))
    tiles = []
    elapsed_ms = 0.0
    classify = getattr(classifier, "classify", None)
    if not callable(classify):
        return None
    for index, region in enumerate(regions):
        crop = crop_region(image, region)
        if crop is None:
            tiles.append(SimpleNamespace(index=index, region=region, context_scores={}))
            continue
        started = time.perf_counter()
        scores = classify(crop)
        elapsed_ms += (time.perf_counter() - started) * 1000
        tiles.append(
            SimpleNamespace(
                index=index,
                region=region,
                context_scores=dict(scores or {}),
            )
        )
    return sample_ranking(tiles, detections, context_latency_ms=elapsed_ms)


def summarize_ranking(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    eligible = []
    latencies: list[float] = []
    for row in rows:
        ranking = row.get("ranking") if isinstance(row.get("ranking"), dict) else None
        if ranking is None:
            context = row.get("context_summary") if isinstance(row.get("context_summary"), dict) else {}
            ranking = context.get("ranking") if isinstance(context, dict) else None
        if not isinstance(ranking, dict):
            continue
        if isinstance(ranking.get("context_latency_ms"), (int, float)):
            latencies.append(float(ranking["context_latency_ms"]))
        if ranking.get("eligible"):
            eligible.append(ranking)
    if not eligible and not latencies:
        return None
    top1 = [1.0 if item.get("top1") else 0.0 for item in eligible]
    top2 = [1.0 if item.get("top2") else 0.0 for item in eligible]
    return {
        "top1_relevant_tile_rate": None if not top1 else sum(top1) / len(top1),
        "top2_relevant_tile_rate": None if not top2 else sum(top2) / len(top2),
        "eligible_samples": len(eligible),
        "mean_context_latency_ms": None if not latencies else sum(latencies) / len(latencies),
        "product_block": None,
    }
