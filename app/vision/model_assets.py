"""Locate and validate pinned local vision-model assets."""

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

YOLO11_NSFW_SMALL_FILENAME = "yolo11.pt"
YOLO11_NSFW_SMALL_SIZE = 19_159_379
YOLO11_NSFW_SMALL_SHA256 = (
    "cd268d5ac84058fc9f3681bcc5446775e7ca1fdcf53948277a8b7ba12055eb10"
)
YOLO11_NSFW_SMALL_REPO = "erax-ai/EraX-NSFW-V1.0"
YOLO11_NSFW_SMALL_REVISION = "aea60ac8d2ebcbe0fcbb29e623eba99945b988a6"
YOLO11_NSFW_SMALL_REMOTE_NAME = "erax_nsfw_yolo11s.pt"
YOLO11_NSFW_SMALL_DOWNLOAD_URL = (
    "https://huggingface.co/erax-ai/EraX-NSFW-V1.0/resolve/"
    f"{YOLO11_NSFW_SMALL_REVISION}/{YOLO11_NSFW_SMALL_REMOTE_NAME}"
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


def bundled_yolo_model_path(root: Path | None = None) -> Path:
    """Return the conventional location of the pinned YOLO11 NSFW Small file."""

    return (
        (resource_root() if root is None else root)
        / "models"
        / YOLO11_NSFW_SMALL_FILENAME
    )


def _user_model_path(filename: str, data_dir: Path | None) -> Path | None:
    if data_dir is None:
        return None
    return Path(data_dir) / "models" / filename


def resolve_yolo_model_path(
    *,
    environ: Mapping[str, str] | None = None,
    root: Path | None = None,
    data_dir: Path | None = None,
) -> Path | None:
    """Resolve an explicit YOLO override or a local models/yolo11.pt file."""

    environ = os.environ if environ is None else environ
    override = str(environ.get("LAVOCADO_YOLO_MODEL", "")).strip()
    candidates = []
    if override:
        candidates.append(Path(override).expanduser())
    user_path = _user_model_path(YOLO11_NSFW_SMALL_FILENAME, data_dir)
    if user_path is not None:
        candidates.append(user_path)
    candidates.append(bundled_yolo_model_path(root))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def resolve_nudenet_model_path(
    *,
    environ: Mapping[str, str] | None = None,
    root: Path | None = None,
    data_dir: Path | None = None,
) -> Path | None:
    """Resolve an explicit override, user download, or bundled model."""

    environ = os.environ if environ is None else environ
    override = environ.get("LAVOCADO_NUDENET_MODEL")
    candidates = []
    if override:
        candidates.append(Path(override).expanduser())
    user_path = _user_model_path(NUDENET_640M_FILENAME, data_dir)
    if user_path is not None:
        candidates.append(user_path)
    candidates.append(bundled_nudenet_model_path(root))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def model_file_sha256(path: Path) -> str:
    """Calculate a model checksum without loading the whole file into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_expected_nudenet_model(path: Path) -> bool:
    """Return whether a file matches the pinned official 640m asset."""

    return _matches_pinned_file(path, NUDENET_640M_SIZE, NUDENET_640M_SHA256)


def is_expected_yolo_model(path: Path) -> bool:
    """Return whether a file matches the pinned YOLO11 NSFW Small asset."""

    return _matches_pinned_file(
        path, YOLO11_NSFW_SMALL_SIZE, YOLO11_NSFW_SMALL_SHA256
    )


def _matches_pinned_file(path: Path, size: int, digest: str) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == size
        and model_file_sha256(path) == digest
    )
