"""JSON / CSV export. Source images and annotated previews are not included."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from developer.benchmark.results import BenchmarkRun

JSON_FIELDS = (
    "config",
    "ground_truth",
    "prediction",
    "metrics",
    "labels",
    "confidence",
    "latency",
    "decision_trace",
)


def export_json(run: BenchmarkRun, path: Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": run.id,
        "created_at": run.created_at,
        "dataset_name": run.dataset_name,
        "dataset_hash": run.dataset_hash,
        "engine_version": run.engine_version,
        "product_version": run.product_version,
        "cancelled": run.cancelled,
        "configs": run.configs,
        "summaries": run.summaries,
        "rows": [_row_export(row, run) for row in run.rows],
    }
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return destination


def export_csv(run: BenchmarkRun, path: Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "run_id",
        "config_id",
        "sample_id",
        "expected",
        "predicted",
        "outcome",
        "correct",
        "excluded",
        "tags",
        "label",
        "confidence",
        "latency_ms",
        "source",
        "classification",
    ]
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in run.rows:
            decision = row.get("decision_summary") or {}
            writer.writerow(
                {
                    "run_id": run.id,
                    "config_id": row.get("config_id"),
                    "sample_id": row.get("sample_id"),
                    "expected": row.get("expected"),
                    "predicted": row.get("predicted"),
                    "outcome": row.get("outcome"),
                    "correct": row.get("correct"),
                    "excluded": row.get("excluded"),
                    "tags": ",".join(row.get("tags") or []),
                    "label": decision.get("label"),
                    "confidence": decision.get("confidence"),
                    "latency_ms": row.get("total_ms"),
                    "source": decision.get("source"),
                    "classification": decision.get("classification"),
                }
            )
    return destination


def _row_export(row: dict[str, Any], run: BenchmarkRun) -> dict[str, Any]:
    config = next(
        (item for item in run.configs if item.get("id") == row.get("config_id")),
        {},
    )
    decision = row.get("decision_summary") or {}
    detector = row.get("detector_summary") or {}
    return {
        "config": config,
        "ground_truth": row.get("expected"),
        "prediction": row.get("predicted"),
        "metrics": {"outcome": row.get("outcome"), "correct": row.get("correct")},
        "labels": detector.get("best_label") or decision.get("label"),
        "confidence": detector.get("best_confidence") or decision.get("confidence"),
        "latency": row.get("total_ms"),
        "decision_trace": decision,
        "sample_id": row.get("sample_id"),
        "tags": row.get("tags") or [],
        "excluded": row.get("excluded"),
    }


def default_export_name(run: BenchmarkRun, suffix: str) -> str:
    return f"lavocado-benchmark-{run.id}.{suffix}"
