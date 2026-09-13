"""Compare local NudeNet 320n and 640m latency on user-supplied images."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nudenet import NudeDetector

from app import config
from app.vision.benchmarking import vision_ground_truth
from app.vision.model_assets import resolve_nudenet_model_path
from app.vision.violation_policy import VisualViolationClassification


def is_blocking(detections: list[dict[str, Any]]) -> bool:
    """Apply Visual Violation Policy to raw detections."""

    return vision_ground_truth(detections) == VisualViolationClassification.VIOLATION.value


def benchmark(
    model: NudeDetector,
    image_paths: list[Path],
) -> tuple[list[float], int]:
    """Return per-image latency and the count of threshold-positive images."""

    durations: list[float] = []
    positive_count = 0
    for image_path in image_paths:
        started = time.perf_counter()
        detections = list(model.detect(str(image_path)))
        durations.append(time.perf_counter() - started)
        positive_count += int(is_blocking(detections))
    return durations, positive_count


def print_result(name: str, durations: list[float], positives: int) -> None:
    print(
        f"{name}: images={len(durations)}, positives={positives}, "
        f"mean_ms={statistics.mean(durations) * 1000:.1f}, "
        f"median_ms={statistics.median(durations) * 1000:.1f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    args = parser.parse_args()

    image_paths = [path.expanduser().resolve() for path in args.images]
    missing = [path for path in image_paths if not path.is_file()]
    if missing:
        parser.error(f"image not found: {missing[0]}")

    model_path = resolve_nudenet_model_path()
    if model_path is None:
        parser.error("models/640m.onnx is missing; run scripts/download_models.py")

    baseline_model = NudeDetector(inference_resolution=320)
    upgraded_model = NudeDetector(
        model_path=str(model_path),
        inference_resolution=config.NUDENET_INFERENCE_RESOLUTION,
    )

    baseline_durations, baseline_positives = benchmark(
        baseline_model,
        image_paths,
    )
    upgraded_durations, upgraded_positives = benchmark(
        upgraded_model,
        image_paths,
    )
    print_result("320n", baseline_durations, baseline_positives)
    print_result("640m", upgraded_durations, upgraded_positives)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
