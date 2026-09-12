"""Download and verify LAVOCADO's pinned local model assets."""

from __future__ import annotations

import argparse
import os
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.vision.model_assets import (
    NUDENET_640M_DOWNLOAD_URL,
    NUDENET_640M_FILENAME,
    NUDENET_640M_SHA256,
    NUDENET_640M_SIZE,
    is_expected_nudenet_model,
)

DEFAULT_DESTINATION = PROJECT_ROOT / "models" / NUDENET_640M_FILENAME


def download_model(destination: Path, *, force: bool = False) -> Path:
    """Download the pinned NudeNet model atomically and verify its digest."""

    destination = destination.expanduser().resolve()
    if destination.exists() and not force:
        if is_expected_nudenet_model(destination):
            print(f"NudeNet 640m is already verified: {destination}")
            return destination
        raise RuntimeError(
            f"Existing model does not match the pinned asset: {destination}. "
            "Pass --force to replace it."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(
        NUDENET_640M_DOWNLOAD_URL,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "LAVOCADO-model-downloader",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    print(
        f"Downloading NudeNet 640m ({NUDENET_640M_SIZE / 1024 / 1024:.1f} MiB)..."
    )
    try:
        with (
            urllib.request.urlopen(request, timeout=120) as response,
            temporary_path.open("wb") as model_file,
        ):
            while chunk := response.read(1024 * 1024):
                model_file.write(chunk)

        if not is_expected_nudenet_model(temporary_path):
            actual_size = temporary_path.stat().st_size
            raise RuntimeError(
                "Downloaded NudeNet model failed verification: "
                f"expected {NUDENET_640M_SIZE} bytes and SHA-256 "
                f"{NUDENET_640M_SHA256}, received {actual_size} bytes."
            )
        os.replace(temporary_path, destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    print(f"Verified NudeNet 640m: {destination}")
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_DESTINATION,
        help="model output path (default: models/640m.onnx)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing unverified model",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    download_model(args.destination, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
