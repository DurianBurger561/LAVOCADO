"""Multi-config comparison. Never announces a Best Overall winner."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from developer.benchmark.metrics import Metric


def compare_summaries(
    configs: Iterable[Mapping[str, Any]],
    summaries: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for config in configs:
        config_id = str(config.get("id") or "")
        summary = dict(summaries.get(config_id) or {})
        rows.append(
            {
                "config_id": config_id,
                "label": _config_label(config),
                "detector": config.get("detector"),
                "context_model": config.get("context_model"),
                "full_input_size": config.get("full_input_size"),
                "tile_rows": config.get("tile_rows"),
                "tile_columns": config.get("tile_columns"),
                "recall": summary.get("recall"),
                "fnr": summary.get("fnr"),
                "fpr": summary.get("fpr"),
                "precision": summary.get("precision"),
                "accuracy": summary.get("accuracy"),
                "failure_rate": summary.get("failure_rate"),
                "p95_latency_ms": summary.get("p95_latency_ms"),
                "mean_latency_ms": summary.get("mean_latency_ms"),
                "cpu_percent": summary.get("cpu_percent"),
                "ram_bytes": summary.get("ram_bytes"),
                "top1_relevant_tile_rate": (summary.get("ranking") or {}).get("top1_relevant_tile_rate"),
                "top2_relevant_tile_rate": (summary.get("ranking") or {}).get("top2_relevant_tile_rate"),
                "mean_context_latency_ms": (summary.get("ranking") or {}).get("mean_context_latency_ms"),
                "tp": summary.get("tp"),
                "tn": summary.get("tn"),
                "fp": summary.get("fp"),
                "fn": summary.get("fn"),
            }
        )
    if rows:
        baseline = rows[0]
        for row in rows:
            row["baseline_config_id"] = baseline["config_id"]
            row["recall_gain"] = _delta(row, baseline, "recall", "ratio")
            fn_delta = _delta(row, baseline, "fn", "cases")
            row["false_negative_reduction"] = None if fn_delta is None else -fn_delta
            row["p95_cost_ms"] = _delta(row, baseline, "p95_latency_ms", "ms")
            row["cpu_cost_percent"] = _delta(row, baseline, "cpu_percent", "percent")
            row["ram_cost_bytes"] = _delta(row, baseline, "ram_bytes", "bytes")
    highlights = {
        "highest_recall": _best(rows, "recall", highest=True),
        "lowest_fnr": _best(rows, "fnr", highest=False),
        "lowest_fpr": _best(rows, "fpr", highest=False),
        "lowest_latency": _best(rows, "p95_latency_ms", highest=False),
    }
    return {"rows": rows, "highlights": highlights}


def _delta(
    row: Mapping[str, Any], baseline: Mapping[str, Any], key: str, unit: str
) -> float | None:
    current = row.get(key)
    initial = baseline.get(key)
    return Metric(
        key, float(current) if isinstance(current, (int, float)) else None, unit
    ).difference_from(
        Metric(key, float(initial) if isinstance(initial, (int, float)) else None, unit)
    )


def sort_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    descending = key in {
        "recall",
        "precision",
        "accuracy",
        "top1_relevant_tile_rate",
        "top2_relevant_tile_rate",
    }
    def sort_value(row: dict[str, Any]) -> tuple[int, float]:
        value = row.get(key)
        if not isinstance(value, (int, float)):
            return (1, 0.0)
        return (0, -float(value) if descending else float(value))

    return sorted(rows, key=sort_value)


def _best(rows: list[dict[str, Any]], key: str, *, highest: bool) -> str | None:
    scored: list[tuple[float, str]] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, (int, float)):
            scored.append((float(value), str(row.get("config_id") or "")))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=highest)
    return scored[0][1]


def _config_label(config: Mapping[str, Any]) -> str:
    if config.get("benchmark_target") == "context_policy":
        return "Context Policy"
    detector = str(config.get("detector") or "detector")
    context = config.get("context_model") or "off"
    size = config.get("full_input_size")
    rows = config.get("tile_rows")
    columns = config.get("tile_columns")
    tiles = "full" if rows in (None, 0) else f"{rows}x{columns}"
    return f"{detector} {size} {context} {tiles}"
