"""Vision Benchmark: Visual Policy Ground Truth only, no viewing intent."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from nudenet import NudeDetector
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import config
from app.vision.model_assets import resolve_nudenet_model_path
from developer.benchmark.ground_truth import (
    VISION_GROUND_TRUTH_NOTE,
    visual_policy_classification,
)


def load_bgr_image(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        rgb_image = np.asarray(image.convert("RGB"), dtype=np.uint8)
    return np.ascontiguousarray(rgb_image[:, :, ::-1])


def score_image(model: NudeDetector, image_path: Path) -> tuple[float, str, list[dict[str, Any]]]:
    image = load_bgr_image(image_path)
    started = time.perf_counter()
    detections = list(model.detect(image))
    elapsed = time.perf_counter() - started
    return elapsed, visual_policy_classification(detections).value, detections


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Scenario metadata such as medical/education/art/news. Ignored by Vision GT.",
    )
    parser.add_argument("images", nargs="*", type=Path)
    args = parser.parse_args()

    print(f"lab=vision_benchmark ground_truth={VISION_GROUND_TRUTH_NOTE}")
    print("labels=violation,clear (not viewing-purpose Allow/Block)")
    if args.tag:
        print(
            "scenario_metadata_ignored="
            + ",".join(str(tag) for tag in args.tag)
        )
    if not args.images:
        return 0

    image_paths = [path.expanduser().resolve() for path in args.images]
    missing = [path for path in image_paths if not path.is_file()]
    if missing:
        parser.error(f"image not found: {missing[0]}")

    model_path = resolve_nudenet_model_path()
    if model_path is None:
        parser.error("models/640m.onnx is missing; run scripts/download_models.py")
    model = NudeDetector(
        model_path=str(model_path),
        inference_resolution=config.NUDENET_INFERENCE_RESOLUTION,
    )

    durations: list[float] = []
    violations = 0
    for index, image_path in enumerate(image_paths, start=1):
        elapsed, label, _detections = score_image(model, image_path)
        durations.append(elapsed)
        violations += int(label == "violation")
        print(f"image_{index}: visual_policy={label}")
    print(
        f"images={len(durations)}, violations={violations}, "
        f"mean_ms={statistics.mean(durations) * 1000:.1f}, "
        f"median_ms={statistics.median(durations) * 1000:.1f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
