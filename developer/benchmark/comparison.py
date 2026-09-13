"""Multi-config comparison. Never announces a Best Overall winner."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


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
                "tp": summary.get("tp"),
                "tn": summary.get("tn"),
                "fp": summary.get("fp"),
                "fn": summary.get("fn"),
            }
        )
    highlights = {
        "highest_recall": _best(rows, "recall", highest=True),
        "lowest_fnr": _best(rows, "fnr", highest=False),
        "lowest_fpr": _best(rows, "fpr", highest=False),
        "lowest_latency": _best(rows, "p95_latency_ms", highest=False),
    }
    return {"rows": rows, "highlights": highlights}


def sort_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    descending = key in {"recall", "precision", "accuracy"}
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
    detector = str(config.get("detector") or "detector")
    context = config.get("context_model") or "off"
    size = config.get("full_input_size")
    rows = config.get("tile_rows")
    columns = config.get("tile_columns")
    tiles = "full" if rows in (None, 0) else f"{rows}x{columns}"
    return f"{detector} {size} {context} {tiles}"
