"""Record screen-domain high-recall metrics. Never selects Recommended defaults."""

from __future__ import annotations

import json
import statistics
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from developer.benchmark.matrix import (
    ALGORITHM_STAGES,
    CONTEXT_CONFIGS,
    PRIMARY_CONFIGS,
    REQUIRED_METRICS,
    SCREEN_SCENES,
    experimental_disclaimer,
    matrix,
)

FORBIDDEN_OUTPUT_KEYS = (
    "screenshot",
    "original_frame",
    "model_frame",
    "crop",
    "pixels",
    "image_bytes",
    "path",
    "image_path",
    "url",
    "window_title",
    "app_name",
)


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Load manually labelled scalar cases without retaining private fields."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("cases")
    if not isinstance(payload, list):
        raise TypeError("cases file must be a JSON list or an object with cases")
    return [sanitize_case(item) for item in payload if isinstance(item, dict)]


def percentile(values: Sequence[float], percent: float) -> float | None:
    """Median for p50; nearest-rank for other percentiles. Empty is None."""

    if not values:
        return None
    ordered = sorted(float(item) for item in values)
    if abs(percent - 50.0) < 1e-9:
        return float(statistics.median(ordered))
    rank = min(
        len(ordered) - 1,
        max(0, round((percent / 100.0) * (len(ordered) - 1))),
    )
    return ordered[rank]


def sanitize_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Keep scalar labels and counts. Drop pixels, paths, and titles."""

    allowed = {
        "case_id",
        "scene",
        "target_size",
        "ground_truth",
        "predicted",
        "primary",
        "context",
        "algorithm_stage",
        "full_input_size",
        "tile_input_size",
        "latency_ms",
        "detection_delay_ms",
        "top_tile_hit_rank",
        "shadow_agreement",
        "cpu_percent",
        "ram_mb",
        "package_size_bytes",
    }
    clean: dict[str, Any] = {}
    for key, value in case.items():
        lowered = str(key).strip().lower()
        if lowered in FORBIDDEN_OUTPUT_KEYS:
            continue
        if key in allowed:
            clean[key] = value
    return clean


def _is_violation(value: object) -> bool:
    return str(value or "").strip().lower() in {"violation", "true", "1", "positive"}


def _size_bucket(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"small", "medium", "large"}:
        return raw
    return "unknown"


def summarize_cases(
    cases: Iterable[Mapping[str, Any]],
    *,
    cpu_percent: float | None = None,
    ram_mb: float | None = None,
    package_size_bytes: int | None = None,
) -> dict[str, Any]:
    """Compute the Phase 11 metric set. ``recommended`` stays null."""

    rows = [sanitize_case(case) for case in cases]
    tp = fp = fn = tn = 0
    size_pos: dict[str, int] = {"small": 0, "medium": 0, "large": 0}
    size_tp: dict[str, int] = {"small": 0, "medium": 0, "large": 0}
    ranked = 0
    top1 = 0
    top2 = 0
    latencies: list[float] = []
    delays: list[float] = []
    shadow = {"both_hit": 0, "both_miss": 0, "primary_only": 0, "shadow_only": 0}
    for row in rows:
        truth = _is_violation(row.get("ground_truth"))
        predicted = _is_violation(row.get("predicted"))
        if truth and predicted:
            tp += 1
        elif predicted and not truth:
            fp += 1
        elif truth and not predicted:
            fn += 1
        else:
            tn += 1
        bucket = _size_bucket(row.get("target_size"))
        if truth and bucket in size_pos:
            size_pos[bucket] += 1
            if predicted:
                size_tp[bucket] += 1
        rank = row.get("top_tile_hit_rank")
        if rank is not None:
            ranked += 1
            try:
                rank_n = int(rank)
            except (TypeError, ValueError):
                rank_n = 0
            if rank_n == 1:
                top1 += 1
            if 1 <= rank_n <= 2:
                top2 += 1
        if row.get("latency_ms") is not None:
            latencies.append(float(row["latency_ms"]))
        if row.get("detection_delay_ms") is not None:
            delays.append(float(row["detection_delay_ms"]))
        agreement = str(row.get("shadow_agreement") or "")
        if agreement in shadow:
            shadow[agreement] += 1
        if cpu_percent is None and row.get("cpu_percent") is not None:
            cpu_percent = float(row["cpu_percent"])
        if ram_mb is None and row.get("ram_mb") is not None:
            ram_mb = float(row["ram_mb"])
        if package_size_bytes is None and row.get("package_size_bytes") is not None:
            package_size_bytes = int(row["package_size_bytes"])

    positives = tp + fn
    negatives = tn + fp
    return {
        "metric_kind": "high_recall_benchmark",
        "case_count": len(rows),
        "recall": 0.0 if positives == 0 else tp / positives,
        "precision": 0.0 if tp + fp == 0 else tp / (tp + fp),
        "false_positive_rate": 0.0 if negatives == 0 else fp / negatives,
        "false_negative_rate": 0.0 if positives == 0 else fn / positives,
        "small_target_recall": (
            0.0 if size_pos["small"] == 0 else size_tp["small"] / size_pos["small"]
        ),
        "medium_target_recall": (
            0.0 if size_pos["medium"] == 0 else size_tp["medium"] / size_pos["medium"]
        ),
        "large_target_recall": (
            0.0 if size_pos["large"] == 0 else size_tp["large"] / size_pos["large"]
        ),
        "top1_tile_hit_rate": 0.0 if ranked == 0 else top1 / ranked,
        "top2_tile_hit_rate": 0.0 if ranked == 0 else top2 / ranked,
        "median_detection_delay_ms": percentile(delays, 50),
        "p95_detection_delay_ms": percentile(delays, 95),
        "p50_scan_latency_ms": percentile(latencies, 50),
        "p95_scan_latency_ms": percentile(latencies, 95),
        "cpu": cpu_percent,
        "ram": ram_mb,
        "package_size": package_size_bytes,
        "shadow": shadow,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "recommended": None,
        "product_block": None,
        "disclaimer": experimental_disclaimer(),
        "metrics_required": list(REQUIRED_METRICS),
    }


def matrix_jobs() -> list[dict[str, Any]]:
    """Enumerate measurement cells. None of these are recommended defaults."""

    jobs: list[dict[str, Any]] = []
    for primary in PRIMARY_CONFIGS:
        for context in CONTEXT_CONFIGS:
            for stage in ALGORITHM_STAGES:
                for scene in SCREEN_SCENES:
                    jobs.append(
                        {
                            "primary": primary["primary"],
                            "full_input_size": primary["full_input_size"],
                            "tile_input_size": primary["tile_input_size"],
                            "context": context,
                            "algorithm_stage": stage,
                            "scene": scene,
                            "recommended": None,
                        }
                    )
    return jobs


def select_recommended(_summary: Mapping[str, Any] | None = None) -> None:
    """Recommended stays locked until a complete screen-domain dataset exists."""

    del _summary


def benchmark_report(cases: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    summary = summarize_cases(cases)
    summary["matrix"] = matrix()
    summary["job_count"] = len(matrix_jobs())
    summary["recommended"] = select_recommended(summary)
    return summary
