"""Compare uncached image primitives with one-generation prepared-frame reuse.

Uses synthetic pixels only. Timings are diagnostic, not pass/fail thresholds.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from app.platforms.capture.models import CaptureFrame
from app.vision.preprocessor import FramePreprocessor, TileSpec
from app.vision.regions import crop_region, overlapping_tile_regions
from developer.benchmark.metrics import median


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


def benchmark_preprocessor(
    *, iterations: int = 30, width: int = 1920, height: int = 1080, size: int = 640
) -> dict[str, object]:
    if min(iterations, width, height, size) < 1:
        raise ValueError("iterations and dimensions must be positive")
    if width * height > 16_777_216:
        raise ValueError("synthetic frame must be at most 16 megapixels")

    image = np.zeros((height, width, 3), dtype=np.uint8)
    frame = CaptureFrame(image=image, monitor_id="synthetic", sequence=1)
    baseline: list[float] = []
    prepared: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        old_result = _uncached(frame, size)
        baseline.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        new_result = _prepared(frame, size)
        prepared.append((time.perf_counter() - start) * 1000)
        if not np.array_equal(old_result[0], new_result[0]):
            raise RuntimeError("prepared resize changed pixels")
        if new_result[0] is not new_result[1]:
            raise RuntimeError("prepared resize was not reused")

    old_ms = median(baseline)
    new_ms = median(prepared)
    return {
        "ok": True,
        "metric_kind": "preprocessor_microbenchmark",
        "frame_size": [width, height],
        "input_size": size,
        "iterations": iterations,
        "uncached_median_ms": round(old_ms, 3),
        "prepared_median_ms": round(new_ms, 3),
        "speedup": round(old_ms / new_ms, 3) if new_ms else None,
        "synthetic_pixels_only": True,
    }
