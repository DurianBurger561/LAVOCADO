"""Compare uncached image primitives with one-generation prepared-frame reuse.

Uses synthetic pixels only. Timings are diagnostic, not pass/fail thresholds.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.platforms.capture.models import CaptureFrame
from app.vision.preprocessor import FramePreprocessor, TileSpec
from app.vision.regions import crop_region, overlapping_tile_regions


def _uncached(frame: CaptureFrame, size: int) -> tuple[np.ndarray, np.ndarray]:
    image = frame.image
    height, width = image.shape[:2]
    scale = min(1.0, size / max(height, width))
    target = (max(1, round(width * scale)), max(1, round(height * scale)))
    first = cv2.resize(image, target, interpolation=cv2.INTER_AREA)
    second = cv2.resize(image, target, interpolation=cv2.INTER_AREA)
    for region in overlapping_tile_regions(image.shape, 2, 2, 0.15):
        crop_region(image, region)
    np.ascontiguousarray(image[:, :, ::-1])
    return first, second


def _prepared(frame: CaptureFrame, size: int) -> tuple[np.ndarray, np.ndarray]:
    prepared = FramePreprocessor(frame)
    first = prepared.resized_long_edge(size)
    second = prepared.resized_long_edge(size)
    prepared.tiles(TileSpec(2, 2, 0.15))
    prepared.rgb()
    return first, second


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--size", type=int, default=640)
    args = parser.parse_args()
    if min(args.iterations, args.width, args.height, args.size) < 1:
        parser.error("iterations and dimensions must be positive")

    image = np.zeros((args.height, args.width, 3), dtype=np.uint8)
    frame = CaptureFrame(image=image, monitor_id="synthetic", sequence=1)
    baseline: list[float] = []
    prepared: list[float] = []
    for _ in range(args.iterations):
        start = time.perf_counter()
        old_result = _uncached(frame, args.size)
        baseline.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        new_result = _prepared(frame, args.size)
        prepared.append((time.perf_counter() - start) * 1000)
        if not np.array_equal(old_result[0], new_result[0]):
            raise RuntimeError("prepared resize changed pixels")
        if new_result[0] is not new_result[1]:
            raise RuntimeError("prepared resize was not reused")

    old_ms = statistics.median(baseline)
    new_ms = statistics.median(prepared)
    print(
        json.dumps(
            {
                "frame_size": [args.width, args.height],
                "input_size": args.size,
                "iterations": args.iterations,
                "uncached_median_ms": round(old_ms, 3),
                "prepared_median_ms": round(new_ms, 3),
                "speedup": round(old_ms / new_ms, 3) if new_ms else None,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
