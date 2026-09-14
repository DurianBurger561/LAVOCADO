"""Verify that a PyInstaller User or Developer artifact contains all pinned models."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.vision.model_assets import (
    VIDDEXA_MODEL_FILES,
    is_expected_nudenet_model,
    is_expected_viddexa_model,
    is_expected_yolo_model,
)


def verify_model_bundle(bundle: Path) -> None:
    if not bundle.is_dir():
        raise RuntimeError(f"Bundle directory does not exist: {bundle}")
    roots = [
        path.parent
        for path in bundle.rglob("640m.onnx")
        if path.parent.name == "models"
    ]
    if len(roots) != 1:
        raise RuntimeError("Bundle must contain exactly one models/640m.onnx.")
    root = roots[0]
    if not is_expected_nudenet_model(root / "640m.onnx"):
        raise RuntimeError("Bundled NudeNet 640m failed verification.")
    if not is_expected_yolo_model(root / "yolo11.pt"):
        raise RuntimeError("Bundled YOLO11 NSFW Small failed verification.")
    for model_id in VIDDEXA_MODEL_FILES:
        if not is_expected_viddexa_model(root / model_id, model_id):
            raise RuntimeError(f"Bundled {model_id} failed verification.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="PyInstaller dist directory or .app")
    args = parser.parse_args(argv)
    verify_model_bundle(args.bundle)
    print("Verified all four bundled models.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
