"""Developer-only offline diagnostics routed through Benchmark Lab."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from developer.benchmark.dataset import BenchmarkDataset, open_dataset
from developer.benchmark.hardware_ipc import write_json
from developer.benchmark.preprocessor_benchmark import benchmark_preprocessor

Progress = Callable[[dict[str, Any]], None]


def detector_comparison(
    dataset: BenchmarkDataset,
    *,
    model_factory=None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Measure 320n and 640m with identical in-memory images."""

    from nudenet import NudeDetector

    from app.vision.model_assets import resolve_nudenet_model_path
    from developer.benchmark.ground_truth import visual_policy_classification
    from developer.benchmark.session import load_bgr_image

    model_path = resolve_nudenet_model_path()
    if model_path is None:
        raise RuntimeError("Verified NudeNet 640m model is unavailable")
    create = model_factory or NudeDetector
    models = {
        "nudenet_320n": create(inference_resolution=320),
        "nudenet_640m": create(model_path=str(model_path), inference_resolution=640),
    }
    rows: list[dict[str, Any]] = []
    total = len(dataset.samples)
    for index, sample in enumerate(dataset.samples, start=1):
        image = load_bgr_image(dataset.resolve_path(sample))
        for variant, model in models.items():
            started = time.perf_counter()
            detections = list(model.detect(image))
            elapsed = (time.perf_counter() - started) * 1000
            rows.append({
                "sample_id": sample.id,
                "variant": variant,
                "visual_classification": visual_policy_classification(detections).value,
                "expected_visual": sample.expected_visual,
                "excluded": sample.excluded,
                "detection_count": len(detections),
                "latency_ms": round(elapsed, 3),
                "tags": sorted(sample.tags),
            })
        if progress is not None:
            progress({"completed": index, "total": total, "mode": "detector_compare"})
    summaries: dict[str, Any] = {}
    for variant in models:
        matching = [row for row in rows if row["variant"] == variant]
        labelled = [
            row for row in matching
            if not row["excluded"] and row["expected_visual"] in {"violation", "clear"}
        ]
        tp = sum(row["expected_visual"] == "violation" and row["visual_classification"] == "violation" for row in labelled)
        fp = sum(row["expected_visual"] == "clear" and row["visual_classification"] == "violation" for row in labelled)
        fn = sum(row["expected_visual"] == "violation" and row["visual_classification"] != "violation" for row in labelled)
        latencies = [row["latency_ms"] for row in matching]
        summaries[variant] = {
            "samples": len(matching),
            "visual_labelled": len(labelled),
            "visual_recall": None if tp + fn == 0 else tp / (tp + fn),
            "visual_precision": None if tp + fp == 0 else tp / (tp + fp),
            "mean_latency_ms": statistics.mean(latencies) if latencies else None,
            "median_latency_ms": statistics.median(latencies) if latencies else None,
            "visual_violations": sum(row["visual_classification"] == "violation" for row in matching),
        }
    return {
        "ok": True,
        "mode": "detector_compare",
        "rows": rows,
        "summaries": summaries,
        "product_block": None,
    }


def ranker_signal(
    dataset: BenchmarkDataset,
    *,
    model_name: str,
    ranker=None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Measure full-image Viddexa signal latency, never Block accuracy."""

    from app.vision.context.viddexa_mini import load_viddexa_mini
    from app.vision.context.viddexa_nano import load_viddexa_nano
    from developer.benchmark.session import load_bgr_image

    if model_name not in {"viddexa_nano", "viddexa_mini"}:
        raise ValueError("Select Viddexa Nano or Mini")
    selected = ranker or (
        load_viddexa_nano() if model_name == "viddexa_nano" else load_viddexa_mini()
    )
    if selected is None:
        raise RuntimeError("Local Viddexa model is unavailable")
    rows: list[dict[str, Any]] = []
    for index, sample in enumerate(dataset.samples, start=1):
        image = load_bgr_image(dataset.resolve_path(sample))
        started = time.perf_counter()
        scores = selected.classify(image)
        elapsed = (time.perf_counter() - started) * 1000
        if not scores:
            rows.append({"sample_id": sample.id, "inference_failed": True, "latency_ms": round(elapsed, 3)})
        else:
            top_label, top_score = max(scores.items(), key=lambda item: item[1])
            rows.append({
                "sample_id": sample.id,
                "top_label": top_label,
                "top_score": top_score,
                "rank_risk": max(float(scores.get("porn", 0.0)), float(scores.get("hentai", 0.0))),
                "latency_ms": round(elapsed, 3),
            })
        if progress is not None:
            progress({"completed": index, "total": len(dataset.samples), "mode": "ranker_signal"})
    latencies = [row["latency_ms"] for row in rows]
    return {
        "ok": True,
        "mode": "ranker_signal",
        "model": model_name,
        "rows": rows,
        "mean_latency_ms": statistics.mean(latencies) if latencies else None,
        "median_latency_ms": statistics.median(latencies) if latencies else None,
        "product_block": None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("detector_compare", "ranker_signal", "preprocessor"), required=True)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--model", choices=("viddexa_nano", "viddexa_mini"), default="viddexa_nano")
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--size", type=int, default=640)
    parser.add_argument("--result-file", type=Path)
    parser.add_argument("--progress-file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    progress = (
        (lambda payload: write_json(args.progress_file, payload))
        if args.progress_file is not None else None
    )
    try:
        if args.mode == "preprocessor":
            result = benchmark_preprocessor(
                iterations=args.iterations,
                width=args.width,
                height=args.height,
                size=args.size,
            )
        else:
            if args.dataset is None:
                raise ValueError("Select a Lab dataset first")
            dataset = open_dataset(args.dataset)
            if args.mode == "detector_compare":
                result = detector_comparison(dataset, progress=progress)
            else:
                result = ranker_signal(dataset, model_name=args.model, progress=progress)
    except Exception as error:  # noqa: BLE001 - isolated worker boundary
        result = {"ok": False, "mode": args.mode, "error": type(error).__name__}
    if args.result_file is not None:
        write_json(args.result_file, result)
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
