"""Benchmark optional Viddexa tile-ranking latency without saving images.

Viddexa scores are ranking signals only. They are not viewing-purpose labels
and cannot be used as a final Block decision.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.vision.context_classifier import load_context_classifier


def load_bgr_image(path: Path) -> np.ndarray:
    """Read a benchmark image into the same BGR format used by capture."""

    with Image.open(path) as image:
        rgb_image = np.asarray(image.convert("RGB"), dtype=np.uint8)
    return np.ascontiguousarray(rgb_image[:, :, ::-1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    args = parser.parse_args()

    image_paths = [path.expanduser().resolve() for path in args.images]
    missing = [path for path in image_paths if not path.is_file()]
    if missing:
        parser.error(f"image not found: {missing[0]}")

    classifier = load_context_classifier()
    if classifier is None:
        print(
            "Context model unavailable. Install optional dependencies with: "
            "python -m pip install -r requirements-context.txt",
            file=sys.stderr,
        )
        return 2

    durations: list[float] = []
    for index, image_path in enumerate(image_paths, start=1):
        image = load_bgr_image(image_path)
        started = time.perf_counter()
        scores = classifier.classify(image)
        durations.append(time.perf_counter() - started)
        if scores is None:
            print(f"image_{index}: inference failed")
            continue
        top_label, top_score = max(scores.items(), key=lambda item: item[1])
        porn = float(scores.get("porn", 0.0))
        hentai = float(scores.get("hentai", 0.0))
        print(
            f"image_{index}: rank_risk={max(porn, hentai):.4f} "
            f"top={top_label}, score={top_score:.4f} "
            f"product_block=None"
        )

    print(
        f"lab=viddexa_ranking_latency images={len(durations)}, "
        f"mean_ms={statistics.mean(durations) * 1000:.1f}, "
        f"median_ms={statistics.median(durations) * 1000:.1f} "
        f"product_block=None"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
