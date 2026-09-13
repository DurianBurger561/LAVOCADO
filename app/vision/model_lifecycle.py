"""Pinned optional-model catalog, status, and local downloads.

Diagnostics and API payloads never include filesystem paths, URLs of the
current page, or pixels. Downloads go to GitHub/Hugging Face only.
"""

from __future__ import annotations

import os
import threading
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import config
from app.vision.model_assets import (
    NUDENET_640M_DOWNLOAD_URL,
    NUDENET_640M_FILENAME,
    NUDENET_640M_SHA256,
    NUDENET_640M_SIZE,
    bundled_nudenet_model_path,
    bundled_yolo_model_path,
    is_expected_nudenet_model,
    resolve_nudenet_model_path,
    resolve_yolo_model_path,
    resource_root,
)

USER_AGENT = "LAVOCADO-model-downloader"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    label: str
    role: str
    source: str
    downloadable: bool
    revision: str | None = None
    huggingface_id: str | None = None


CATALOG: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="nudenet_640m",
        label="NudeNet 640m",
        role="primary",
        source="github:notAI-tech/NudeNet@v3.4-weights",
        downloadable=True,
        revision=NUDENET_640M_SHA256[:12],
    ),
    ModelSpec(
        id="yolo11_nsfw_small",
        label="YOLO11 NSFW Small",
        role="primary",
        source="local optional weights",
        downloadable=False,
    ),
    ModelSpec(
        id="viddexa_nano",
        label="Viddexa Nano",
        role="context",
        source=f"huggingface:{config.CONTEXT_NANO_MODEL_NAME}",
        downloadable=True,
        revision=config.CONTEXT_NANO_MODEL_REVISION,
        huggingface_id=config.CONTEXT_NANO_MODEL_NAME,
    ),
    ModelSpec(
        id="viddexa_mini",
        label="Viddexa Mini",
        role="context",
        source=f"huggingface:{config.CONTEXT_MINI_MODEL_NAME}",
        downloadable=True,
        revision=config.CONTEXT_MINI_MODEL_REVISION,
        huggingface_id=config.CONTEXT_MINI_MODEL_NAME,
    ),
)

_LOCK = threading.Lock()
_RUNTIME: dict[str, dict[str, Any]] = {}


def models_dir(data_dir: Path | None = None, root: Path | None = None) -> Path:
    if data_dir is not None:
        return Path(data_dir) / "models"
    return (root if root is not None else resource_root()) / "models"


def spec_by_id(model_id: str) -> ModelSpec | None:
    for spec in CATALOG:
        if spec.id == model_id:
            return spec
    return None


def _nudenet_status(
    *,
    data_dir: Path | None,
    root: Path | None,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    runtime = _RUNTIME.get("nudenet_640m", {})
    if runtime.get("status") == "downloading":
        return _public_row(CATALOG[0], "downloading", error=runtime.get("error"))
    path = resolve_nudenet_model_path(
        environ=environ,
        root=root,
        data_dir=data_dir,
    )
    if path is None:
        return _public_row(CATALOG[0], "missing", fallback="nudenet_320n")
    if is_expected_nudenet_model(path):
        return _public_row(CATALOG[0], "available")
    return _public_row(CATALOG[0], "invalid", fallback="nudenet_320n")


def _yolo_status(
    *,
    data_dir: Path | None,
    root: Path | None,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    path = resolve_yolo_model_path(environ=environ, root=root, data_dir=data_dir)
    if path is None:
        return _public_row(CATALOG[1], "missing")
    return _public_row(CATALOG[1], "available")


def _huggingface_cached(repo_id: str, revision: str) -> bool:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        return False
    try:
        snapshot_download(
            repo_id,
            revision=revision,
            local_files_only=True,
        )
    except Exception:  # noqa: BLE001 - missing cache is a status, not a crash
        return False
    return True


def _viddexa_status(spec: ModelSpec) -> dict[str, Any]:
    runtime = _RUNTIME.get(spec.id, {})
    if runtime.get("status") == "downloading":
        return _public_row(spec, "downloading", error=runtime.get("error"))
    if runtime.get("status") == "failed":
        cached = _huggingface_cached(spec.huggingface_id or "", spec.revision or "")
        return _public_row(
            spec,
            "available" if cached else "failed",
            error=None if cached else runtime.get("error"),
        )
    if spec.huggingface_id is None or spec.revision is None:
        return _public_row(spec, "missing")
    if _huggingface_cached(spec.huggingface_id, spec.revision):
        return _public_row(spec, "available")
    return _public_row(spec, "missing")


def _public_row(
    spec: ModelSpec,
    status: str,
    *,
    error: str | None = None,
    fallback: str | None = None,
) -> dict[str, Any]:
    return {
        "id": spec.id,
        "label": spec.label,
        "role": spec.role,
        "source": spec.source,
        "revision": spec.revision,
        "status": status,
        "downloadable": spec.downloadable,
        "fallback": fallback,
        "error": error,
    }


def inspect_models(
    *,
    data_dir: Path | None = None,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return privacy-safe model rows. Never includes filesystem paths."""

    environ = os.environ if environ is None else environ
    rows = [
        _nudenet_status(data_dir=data_dir, root=root, environ=environ),
        _yolo_status(data_dir=data_dir, root=root, environ=environ),
    ]
    for spec in CATALOG:
        if spec.role == "context":
            rows.append(_viddexa_status(spec))
    return rows


def compact_model_status(rows: list[dict[str, Any]] | None = None) -> dict[str, str]:
    rows = inspect_models() if rows is None else rows
    return {str(row["id"]): str(row["status"]) for row in rows}


def download_nudenet(
    destination: Path,
    *,
    force: bool = False,
    opener: Callable[..., object] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Download the pinned NudeNet 640m asset and verify size + SHA-256."""

    destination = destination.expanduser().resolve()
    if destination.exists() and not force and is_expected_nudenet_model(destination):
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(destination.suffix + ".part")
    request = build_nudenet_request(environ)
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=120) as response, temporary_path.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
        if not is_expected_nudenet_model(temporary_path):
            actual_size = temporary_path.stat().st_size
            raise RuntimeError(
                "Downloaded NudeNet model failed verification: "
                f"expected {NUDENET_640M_SIZE} bytes and SHA-256 "
                f"{NUDENET_640M_SHA256[:12]}, received {actual_size} bytes."
            )
        os.replace(temporary_path, destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return destination


def build_nudenet_request(environ: Mapping[str, str] | None = None) -> urllib.request.Request:
    environment = os.environ if environ is None else environ
    headers = {
        "Accept": "application/octet-stream",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = environment.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(NUDENET_640M_DOWNLOAD_URL, headers=headers)


def download_huggingface(repo_id: str, revision: str) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as error:
        raise RuntimeError(
            "Viddexa download needs the optional context dependencies."
        ) from error
    snapshot_download(repo_id, revision=revision)


def download_model(
    model_id: str,
    *,
    data_dir: Path | None = None,
    root: Path | None = None,
    force: bool = False,
    opener: Callable[..., object] | None = None,
    environ: Mapping[str, str] | None = None,
    huggingface_downloader: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """Synchronously download one catalog model. Raises on failure."""

    spec = spec_by_id(model_id)
    if spec is None:
        raise ValueError("Unknown model.")
    if not spec.downloadable:
        raise RuntimeError(
            "YOLO11 NSFW Small is an optional local file. "
            "Place weights as yolo11.pt or set LAVOCADO_YOLO_MODEL."
        )
    if spec.id == "nudenet_640m":
        directory = models_dir(data_dir, root)
        download_nudenet(
            directory / NUDENET_640M_FILENAME,
            force=force,
            opener=opener,
            environ=environ,
        )
        return _nudenet_status(
            data_dir=data_dir,
            root=root,
            environ=os.environ if environ is None else environ,
        )
    if spec.huggingface_id is None or spec.revision is None:
        raise RuntimeError("Model source is not configured.")
    downloader = huggingface_downloader or download_huggingface
    downloader(spec.huggingface_id, spec.revision)
    return _viddexa_status(spec)


def start_download(
    model_id: str,
    *,
    data_dir: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Start a background download and return the current public row."""

    spec = spec_by_id(model_id)
    if spec is None:
        raise ValueError("Unknown model.")
    with _LOCK:
        current = _RUNTIME.get(model_id, {})
        if current.get("status") == "downloading":
            return _public_row(spec, "downloading")
        _RUNTIME[model_id] = {"status": "downloading", "error": None}

    def worker() -> None:
        try:
            download_model(model_id, data_dir=data_dir, root=root)
            with _LOCK:
                _RUNTIME[model_id] = {"status": "available", "error": None}
        except Exception as error:  # noqa: BLE001 - download boundary
            with _LOCK:
                _RUNTIME[model_id] = {
                    "status": "failed",
                    "error": str(error.__class__.__name__),
                }

    thread = threading.Thread(
        target=worker,
        name=f"lavocado-download-{model_id}",
        daemon=True,
    )
    thread.start()
    return _public_row(spec, "downloading")


def reset_runtime_for_tests() -> None:
    with _LOCK:
        _RUNTIME.clear()


def preferred_nudenet_destination(
    data_dir: Path | None = None,
    root: Path | None = None,
) -> Path:
    bundled = bundled_nudenet_model_path(root)
    if data_dir is not None:
        return Path(data_dir) / "models" / NUDENET_640M_FILENAME
    return bundled


def preferred_yolo_destination(
    data_dir: Path | None = None,
    root: Path | None = None,
) -> Path:
    if data_dir is not None:
        return Path(data_dir) / "models" / "yolo11.pt"
    return bundled_yolo_model_path(root)
