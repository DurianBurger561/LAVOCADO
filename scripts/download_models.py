"""Download and verify LAVOCADO's pinned local model assets."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.vision.model_assets import (
    NUDENET_640M_FILENAME,
    NUDENET_640M_SIZE,
    is_expected_nudenet_model,
)
from app.vision.model_lifecycle import (
    build_nudenet_request,
    download_nudenet,
)
from app.vision.model_lifecycle import download_model as download_catalog_model

DEFAULT_DESTINATION = PROJECT_ROOT / "models" / NUDENET_640M_FILENAME


def build_download_request(
    environ: Mapping[str, str] | None = None,
):
    """Build the GitHub asset request with optional Actions authentication."""

    return build_nudenet_request(environ)


def download_model(destination: Path, *, force: bool = False) -> Path:
    """Download the pinned NudeNet model atomically and verify its digest."""

    destination = destination.expanduser().resolve()
    if destination.exists() and not force and is_expected_nudenet_model(destination):
        print(f"NudeNet 640m is already verified: {destination}")
        return destination
    print(
        f"Downloading NudeNet 640m ({NUDENET_640M_SIZE / 1024 / 1024:.1f} MiB)..."
    )
    path = download_nudenet(destination, force=force)
    print(f"Verified NudeNet 640m: {destination}")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        choices=("nudenet_640m", "viddexa_nano", "viddexa_mini"),
        default="nudenet_640m",
        help="catalog model to download (default: nudenet_640m)",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_DESTINATION,
        help="NudeNet output path (default: models/640m.onnx)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing unverified NudeNet model",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.model == "nudenet_640m":
        download_model(args.destination, force=args.force)
        return 0
    download_catalog_model(args.model, root=PROJECT_ROOT, force=args.force)
    print(f"Verified {args.model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
