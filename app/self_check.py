"""Non-GUI, offline health check for source and frozen release builds."""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

from app.platforms import create_platform_adapter
from app.settings.schema import SCHEMA_VERSION, default_vision_settings
from app.vision.model_assets import model_file_sha256, resource_root
from app.vision.model_manifest import CATALOG, ModelSpec


def verify_model(spec: ModelSpec, root: Path) -> None:
    """Require the pinned bundled files, then initialize the model locally."""

    location = root / spec.bundled_path
    directory = location if location.is_dir() else location.parent
    for item in spec.required_files:
        file = directory / item.name
        if not file.is_file() or file.stat().st_size != item.size:
            raise RuntimeError(f"{spec.label} bundled files are missing or invalid")
        if model_file_sha256(file) != item.sha256:
            raise RuntimeError(f"{spec.label} bundled digest failed verification")

    if spec.id == "nudenet_640m":
        from app.vision.detectors.nudenet import NudeNetPrimaryDetector

        detector = NudeNetPrimaryDetector(model_path=location)
        if detector.model_variant != "640m":
            raise RuntimeError("NudeNet 640m could not initialize")
    elif spec.id == "yolo11_nsfw_small":
        from app.vision.yolo_adapter import load_yolo_adapter

        adapter = load_yolo_adapter(
            enabled=True, environ={"LAVOCADO_YOLO_MODEL": str(location)}
        )
        if adapter is None:
            raise RuntimeError("YOLO11 NSFW Small could not initialize")
    elif spec.id in {"viddexa_nano", "viddexa_mini"}:
        from app.vision.context.factory import load_context_ranker

        ranker = load_context_ranker(spec.id, data_dir=root)
        if ranker.name != spec.id:
            raise RuntimeError(f"{spec.label} could not initialize offline")
    else:
        raise ValueError(f"Unknown required model: {spec.id}")


def verify_required_models(root: Path | None = None) -> None:
    """Fail release preparation if any required model cannot load offline."""

    selected_root = resource_root() if root is None else Path(root)
    for spec in CATALOG:
        if spec.required:
            verify_model(spec, selected_root)


def _runtime_available() -> bool:
    for module in ("numpy", "cv2", "webview", "nudenet"):
        importlib.import_module(module)
    return True


def _dashboard_available(root: Path, *, developer: bool) -> bool:
    web = root / "app" / "ui" / "web"
    if not all((web / name).is_file() for name in ("index.html", "styles.css", "app.js")):
        return False
    if developer:
        lab = root / "developer" / "benchmark" / "ui"
        return all((lab / name).is_file() for name in ("lab.html", "lab.css", "lab.js"))
    return True


def _settings_available() -> bool:
    return default_vision_settings().to_dict().get("schema_version") == SCHEMA_VERSION


def _sqlite_available() -> bool:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("SELECT 1").fetchone()
    return True


def _platform_available() -> bool:
    return bool(create_platform_adapter().name)


def perform_self_check(
    *, root: Path | None = None, developer: bool = False
) -> dict[str, bool]:
    """Return fixed, privacy-safe checks without opening GUI or using the network."""

    selected_root = resource_root() if root is None else Path(root)
    checks: dict[str, bool] = {}
    operations = (
        ("Runtime", _runtime_available),
        ("Dashboard assets", lambda: _dashboard_available(selected_root, developer=developer)),
        ("Settings schema", _settings_available),
        ("SQLite", _sqlite_available),
        ("Platform adapter", _platform_available),
    )
    for label, operation in operations:
        try:
            checks[label] = bool(operation())
        except Exception:  # noqa: BLE001 - report each independent check
            checks[label] = False
    for spec in CATALOG:
        if not spec.required:
            continue
        try:
            verify_model(spec, selected_root)
        except Exception:  # noqa: BLE001 - no private paths in public report
            checks[spec.label] = False
        else:
            checks[spec.label] = True
    return checks


def print_self_check(*, developer: bool = False) -> int:
    checks = perform_self_check(developer=developer)
    for name, healthy in checks.items():
        print(f"{name:.<24} {'OK' if healthy else 'FAIL'}")
    if not all(checks.values()):
        if not checks["Platform adapter"]:
            print("Unsupported platform. LAVOCADO currently supports Windows and macOS.")
        if any(not checks[spec.label] for spec in CATALOG if spec.required):
            print("A required model failed. Download all pinned models or reinstall the build.")
        if any(not checks[name] for name in ("Runtime", "Dashboard assets", "Settings schema", "SQLite")):
            print("A runtime component failed. Reinstall the build or check its dependencies.")
        return 1
    return 0
