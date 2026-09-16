"""Verify that a PyInstaller User or Developer artifact contains all pinned models."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.vision.model_assets import (
    is_expected_nudenet_model,
    is_expected_viddexa_model,
    is_expected_yolo_model,
)
from app.vision.model_manifest import CATALOG, ModelRole, spec_by_id


def verify_model_bundle(bundle: Path) -> None:
    if not bundle.is_dir():
        raise RuntimeError(f"Bundle directory does not exist: {bundle}")
    nudenet = spec_by_id("nudenet_640m")
    assert nudenet is not None
    roots = [
        path.parent
        for path in bundle.rglob(nudenet.required_files[0].name)
        if path.parent.name == "models"
    ]
    if len(roots) != 1:
        raise RuntimeError(f"Bundle must contain exactly one {nudenet.bundled_path}.")
    root = roots[0]
    for spec in CATALOG:
        if not spec.required:
            continue
        bundled = root.parent / spec.bundled_path
        if spec.id == "nudenet_640m":
            valid = is_expected_nudenet_model(bundled)
        elif spec.id == "yolo11_nsfw_small":
            valid = is_expected_yolo_model(bundled)
        elif spec.role is ModelRole.REGION_RANKER:
            valid = is_expected_viddexa_model(bundled, spec.id)
        else:
            raise RuntimeError(f"Unknown required model: {spec.id}")
        if not valid:
            raise RuntimeError(f"Bundled {spec.label} failed verification.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="PyInstaller dist directory or .app")
    args = parser.parse_args(argv)
    verify_model_bundle(args.bundle)
    print("Verified all four bundled models.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
