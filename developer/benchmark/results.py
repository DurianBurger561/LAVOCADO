"""Persist benchmark runs next to the dataset. No images are stored here."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from developer.benchmark import ENGINE_VERSION
from developer.benchmark.configs import BenchmarkConfig
from developer.benchmark.dataset import BenchmarkDataset, hash_file
from developer.benchmark.metrics import summarize_rows


@dataclass
class BenchmarkRun:
    id: str
    created_at: str
    dataset_name: str
    dataset_hash: str
    engine_version: int
    product_version: str
    configs: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    summaries: dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "dataset_name": self.dataset_name,
            "dataset_hash": self.dataset_hash,
            "engine_version": self.engine_version,
            "product_version": self.product_version,
            "configs": self.configs,
            "rows": self.rows,
            "summaries": self.summaries,
            "cancelled": self.cancelled,
        }


def dataset_hash(dataset: BenchmarkDataset) -> str:
    if dataset.document_path.is_file():
        return hash_file(dataset.document_path)
    return ""


def new_run(dataset: BenchmarkDataset, configs: list[BenchmarkConfig]) -> BenchmarkRun:
    return BenchmarkRun(
        id=uuid4().hex[:16],
        created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        dataset_name=dataset.name,
        dataset_hash=dataset_hash(dataset),
        engine_version=ENGINE_VERSION,
        product_version="LAVOCADO Developer",
        configs=[config.to_dict() for config in configs],
    )


def finalize_run(run: BenchmarkRun) -> BenchmarkRun:
    by_config: dict[str, list[dict[str, Any]]] = {}
    for row in run.rows:
        by_config.setdefault(str(row.get("config_id") or ""), []).append(row)
    summaries = {}
    for config_id, rows in by_config.items():
        pipeline_rows = [row for row in rows if row.get("target") != "detector_only"]
        summaries[config_id] = summarize_rows(pipeline_rows or rows)
    run.summaries = summaries
    return run


def save_run(dataset: BenchmarkDataset, run: BenchmarkRun) -> Path:
    dataset.results_dir.mkdir(parents=True, exist_ok=True)
    path = dataset.results_dir / f"{run.id}.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(run.to_dict(), handle, indent=2)
        handle.write("\n")
    return path


def load_run(path: Path) -> BenchmarkRun:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return BenchmarkRun(
        id=str(payload.get("id") or ""),
        created_at=str(payload.get("created_at") or ""),
        dataset_name=str(payload.get("dataset_name") or ""),
        dataset_hash=str(payload.get("dataset_hash") or ""),
        engine_version=int(payload.get("engine_version") or ENGINE_VERSION),
        product_version=str(payload.get("product_version") or ""),
        configs=list(payload.get("configs") or []),
        rows=list(payload.get("rows") or []),
        summaries=dict(payload.get("summaries") or {}),
        cancelled=bool(payload.get("cancelled")),
    )
