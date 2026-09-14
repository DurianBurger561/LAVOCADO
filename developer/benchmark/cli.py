"""Dataset Benchmark Lab CLI; the UI and CLI use the same registry and runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from developer.benchmark.configs import (
    BENCHMARK_TARGETS,
    ConfigSelection,
    expand_configs,
)
from developer.benchmark.contracts import BenchmarkRequest
from developer.benchmark.dataset import open_dataset
from developer.benchmark.registry import BenchmarkRegistry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local Benchmark Lab dataset")
    parser.add_argument("--list", action="store_true", help="List available benchmark categories")
    parser.add_argument("--dataset", type=Path, help="Path to a local dataset.json")
    parser.add_argument(
        "--target",
        choices=sorted(BENCHMARK_TARGETS),
        default="full_protection_pipeline",
    )
    parser.add_argument("--detector", default="nudenet_640m")
    parser.add_argument("--context-model", default="off")
    parser.add_argument("--input-size", type=int, default=640)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = BenchmarkRegistry()
    if args.list:
        print(json.dumps(registry.categories(), indent=2))
        return 0
    if args.dataset is None:
        raise SystemExit("--dataset is required unless --list is set")
    dataset = open_dataset(args.dataset)
    configs = expand_configs(ConfigSelection(
        benchmark_target=args.target,
        detectors=(args.detector,),
        context_models=(args.context_model,),
        full_input_sizes=(args.input_size,),
    ))
    request = BenchmarkRequest(dataset, tuple(configs))
    result = registry.runner(request).start()
    print(json.dumps({
        "run_id": result.id,
        "dataset": result.dataset_name,
        "summaries": result.summaries,
        "cancelled": result.cancelled,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
