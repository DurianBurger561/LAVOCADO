"""Locate and validate pinned local vision-model assets."""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from app.vision.model_manifest import (
    NUDENET_640M_FILENAME,
    NUDENET_640M_SHA256,
    NUDENET_640M_SIZE,
    VIDDEXA_MODEL_FILES,
    YOLO11_NSFW_SMALL_FILENAME,
    YOLO11_NSFW_SMALL_SHA256,
    YOLO11_NSFW_SMALL_SIZE,
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


def bundled_viddexa_model_path(model_id: str, root: Path | None = None) -> Path:
    if model_id not in VIDDEXA_MODEL_FILES:
        raise ValueError(f"Unknown Viddexa model: {model_id}")
    return (resource_root() if root is None else root) / "models" / model_id


def has_complete_viddexa_model(directory: Path, model_id: str) -> bool:
    """Cheap runtime presence check; build/download paths also verify SHA-256."""

    return all(
        (directory / item.name).is_file()
        and (directory / item.name).stat().st_size == item.size
        for item in VIDDEXA_MODEL_FILES[model_id]
    )


def is_expected_viddexa_model(directory: Path, model_id: str) -> bool:
    return all(
        _matches_pinned_file(directory / item.name, item.size, item.sha256)
        for item in VIDDEXA_MODEL_FILES[model_id]
    )


def resolve_viddexa_model_path(
    model_id: str,
    *,
    root: Path | None = None,
    data_dir: Path | None = None,
) -> Path | None:
    candidates = []
    if data_dir is not None:
        candidates.append(Path(data_dir) / "models" / model_id)
    candidates.append(bundled_viddexa_model_path(model_id, root))
    return next(
        (path for path in candidates if has_complete_viddexa_model(path, model_id)),
        None,
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
