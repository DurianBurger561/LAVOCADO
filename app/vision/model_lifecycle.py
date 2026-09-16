"""Pinned required-model catalog, status, and local downloads.

Every catalog model is required in release bundles. Diagnostics and API payloads
never include filesystem paths, page URLs, or pixels.
"""

from __future__ import annotations

import os
import threading
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from app.vision.model_assets import (
    bundled_nudenet_model_path,
    bundled_yolo_model_path,
    is_expected_nudenet_model,
    is_expected_viddexa_model,
    is_expected_yolo_model,
    resolve_nudenet_model_path,
    resolve_viddexa_model_path,
    resolve_yolo_model_path,
    resource_root,
)
from app.vision.model_manifest import (
    CATALOG,
    NUDENET_640M_DOWNLOAD_URL,
    NUDENET_640M_FILENAME,
    NUDENET_640M_SHA256,
    NUDENET_640M_SIZE,
    REQUIRED_MODEL_IDS,
    VIDDEXA_MODEL_FILES,
    YOLO11_NSFW_SMALL_DOWNLOAD_URL,
    YOLO11_NSFW_SMALL_FILENAME,
    YOLO11_NSFW_SMALL_SHA256,
    YOLO11_NSFW_SMALL_SIZE,
    ModelRole,
    ModelSpec,
    spec_by_id,
)

USER_AGENT = "LAVOCADO-model-downloader"


_LOCK = threading.Lock()
_RUNTIME: dict[str, dict[str, Any]] = {}


def models_dir(data_dir: Path | None = None, root: Path | None = None) -> Path:
    if data_dir is not None:
        return Path(data_dir) / "models"
    return (root if root is not None else resource_root()) / "models"


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
    spec = spec_by_id("yolo11_nsfw_small")
    assert spec is not None
    runtime = _RUNTIME.get(spec.id, {})
    if runtime.get("status") == "downloading":
        return _public_row(spec, "downloading", error=runtime.get("error"))
    path = resolve_yolo_model_path(environ=environ, root=root, data_dir=data_dir)
    if path is None:
        return _public_row(spec, "missing")
    if is_expected_yolo_model(path) or str(environ.get("LAVOCADO_YOLO_MODEL", "")).strip():
        return _public_row(spec, "available")
    return _public_row(spec, "invalid")


def _viddexa_status(
    spec: ModelSpec, *, data_dir: Path | None, root: Path | None
) -> dict[str, Any]:
    runtime = _RUNTIME.get(spec.id, {})
    if runtime.get("status") == "downloading":
        return _public_row(spec, "downloading", error=runtime.get("error"))
    if resolve_viddexa_model_path(spec.id, data_dir=data_dir, root=root) is not None:
        return _public_row(spec, "available")
    if runtime.get("status") == "failed":
        return _public_row(spec, "failed", error=runtime.get("error"))
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
        "role": spec.role.value,
        "source": spec.source,
        "revision": spec.revision,
        "status": status,
        "downloadable": spec.downloadable,
        "required": spec.required,
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
        if spec.role is ModelRole.REGION_RANKER:
            rows.append(_viddexa_status(spec, data_dir=data_dir, root=root))
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


def download_huggingface(
    repo_id: str,
    revision: str,
    destination: Path,
    *,
    model_id: str,
    force: bool = False,
) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as error:
        raise RuntimeError(
            "Viddexa download needs the context dependencies."
        ) from error
    snapshot_download(
        repo_id,
        revision=revision,
        local_dir=destination,
        allow_patterns=[item.name for item in VIDDEXA_MODEL_FILES[model_id]],
        force_download=force,
    )


def download_verified_file(
    url: str,
    destination: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    force: bool = False,
    opener: Callable[..., object] | None = None,
    environ: Mapping[str, str] | None = None,
    is_valid: Callable[[Path], bool] | None = None,
) -> Path:
    """Download one file and verify size + SHA-256 before replacing the target."""

    destination = destination.expanduser().resolve()
    checker = is_valid or (
        lambda path: path.is_file()
        and path.stat().st_size == expected_size
        and True
    )
    if destination.exists() and not force and checker(destination):
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(destination.suffix + ".part")
    environment = os.environ if environ is None else environ
    headers = {"User-Agent": USER_AGENT}
    token = environment.get("HF_TOKEN", "").strip() or environment.get(
        "HUGGING_FACE_HUB_TOKEN", ""
    ).strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=120) as response, temporary_path.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
        if not checker(temporary_path):
            actual_size = temporary_path.stat().st_size
            raise RuntimeError(
                "Downloaded model failed verification: "
                f"expected {expected_size} bytes and SHA-256 "
                f"{expected_sha256[:12]}, received {actual_size} bytes."
            )
        os.replace(temporary_path, destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return destination


def download_yolo(
    destination: Path,
    *,
    force: bool = False,
    opener: Callable[..., object] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Download the pinned YOLO11 NSFW Small weights and verify the digest."""

    return download_verified_file(
        YOLO11_NSFW_SMALL_DOWNLOAD_URL,
        destination,
        expected_size=YOLO11_NSFW_SMALL_SIZE,
        expected_sha256=YOLO11_NSFW_SMALL_SHA256,
        force=force,
        opener=opener,
        environ=environ,
        is_valid=is_expected_yolo_model,
    )


def download_model(
    model_id: str,
    *,
    data_dir: Path | None = None,
    root: Path | None = None,
    force: bool = False,
    opener: Callable[..., object] | None = None,
    environ: Mapping[str, str] | None = None,
    huggingface_downloader: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Synchronously download one catalog model. Raises on failure."""

    spec = spec_by_id(model_id)
    if spec is None:
        raise ValueError("Unknown model.")
    directory = models_dir(data_dir, root)
    env = os.environ if environ is None else environ
    if spec.id == "nudenet_640m":
        download_nudenet(
            directory / NUDENET_640M_FILENAME,
            force=force,
            opener=opener,
            environ=environ,
        )
        return _nudenet_status(data_dir=data_dir, root=root, environ=env)
    if spec.id == "yolo11_nsfw_small":
        download_yolo(
            directory / YOLO11_NSFW_SMALL_FILENAME,
            force=force,
            opener=opener,
            environ=environ,
        )
        return _yolo_status(data_dir=data_dir, root=root, environ=env)
    if spec.huggingface_id is None or spec.revision is None:
        raise RuntimeError("Model source is not configured.")
    destination = directory / spec.id
    if not force and is_expected_viddexa_model(destination, spec.id):
        return _viddexa_status(spec, data_dir=data_dir, root=root)
    downloader = huggingface_downloader or download_huggingface
    downloader(
        spec.huggingface_id,
        spec.revision,
        destination,
        model_id=spec.id,
        force=force or destination.exists(),
    )
    if not is_expected_viddexa_model(destination, spec.id):
        raise RuntimeError(f"Downloaded {spec.label} failed pinned-file verification.")
    return _viddexa_status(spec, data_dir=data_dir, root=root)


def download_required_models(
    *,
    data_dir: Path | None = None,
    root: Path | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Download required models. Failures are recorded per model."""

    rows: list[dict[str, Any]] = []
    for model_id in REQUIRED_MODEL_IDS:
        spec = spec_by_id(model_id)
        assert spec is not None
        try:
            rows.append(
                download_model(model_id, data_dir=data_dir, root=root, force=force)
            )
        except Exception as error:  # noqa: BLE001 - per-model download boundary
            rows.append(
                _public_row(spec, "failed", error=str(error.__class__.__name__))
            )
    return rows


def start_download_all(
    *,
    data_dir: Path | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Start a background download for every missing required model."""

    rows = inspect_models(data_dir=data_dir, root=root)
    started: list[dict[str, Any]] = []
    for row in rows:
        if not row["required"]:
            started.append(row)
            continue
        if row["status"] in {"available", "downloading"}:
            started.append(row)
            continue
        started.append(start_download(str(row["id"]), data_dir=data_dir, root=root))
    return started


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
        return Path(data_dir) / "models" / YOLO11_NSFW_SMALL_FILENAME
    return bundled_yolo_model_path(root)
