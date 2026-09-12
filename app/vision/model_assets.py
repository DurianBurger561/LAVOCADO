"""Locate and validate optional local vision-model assets."""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Mapping
from pathlib import Path

NUDENET_640M_FILENAME = "640m.onnx"
NUDENET_640M_SIZE = 103_538_690
NUDENET_640M_SHA256 = (
    "04fe3d77980780c1f8297dc6d7f942fd5b3abe6942a188f742a85241e4f634eb"
)
NUDENET_640M_DOWNLOAD_URL = (
    "https://api.github.com/repos/notAI-tech/NudeNet/releases/assets/176832019"
)


def resource_root() -> Path:
    """Return the source tree or PyInstaller extraction root."""

    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root is not None:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[2]


def bundled_nudenet_model_path(root: Path | None = None) -> Path:
    """Return the conventional location of the downloaded 640m model."""

    return (resource_root() if root is None else root) / "models" / NUDENET_640M_FILENAME


def resolve_nudenet_model_path(
    *,
    environ: Mapping[str, str] | None = None,
    root: Path | None = None,
) -> Path | None:
    """Resolve an explicit override or the bundled model when it exists."""

    environ = os.environ if environ is None else environ
    override = environ.get("LAVOCADO_NUDENET_MODEL")
    candidate = (
        Path(override).expanduser()
        if override
        else bundled_nudenet_model_path(root)
    )
    return candidate if candidate.is_file() else None


def model_file_sha256(path: Path) -> str:
    """Calculate a model checksum without loading the whole file into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_expected_nudenet_model(path: Path) -> bool:
    """Return whether a file matches the pinned official 640m asset."""

    return (
        path.is_file()
        and path.stat().st_size == NUDENET_640M_SIZE
        and model_file_sha256(path) == NUDENET_640M_SHA256
    )
