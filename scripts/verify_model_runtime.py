"""Fail release preparation if any required local model cannot load offline."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.vision.context.factory import load_context_ranker
from app.vision.detectors.factory import load_primary_bundle
from app.vision.detectors.nudenet import NudeNetPrimaryDetector


def verify_model_runtime() -> None:
    nudenet = NudeNetPrimaryDetector()
    if nudenet.model_variant != "640m":
        raise RuntimeError("Pinned NudeNet 640m did not load.")
    yolo = load_primary_bundle("yolo11_nsfw_small")
    if yolo.name != "yolo11_nsfw_small":
        raise RuntimeError("Pinned YOLO11 NSFW Small did not load.")
    for model_id in ("viddexa_nano", "viddexa_mini"):
        if load_context_ranker(model_id).name != model_id:
            raise RuntimeError(f"Pinned {model_id} did not load offline.")


if __name__ == "__main__":
    verify_model_runtime()
    print("Verified all four model runtimes offline.")
