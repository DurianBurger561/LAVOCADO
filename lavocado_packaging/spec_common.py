"""Shared PyInstaller Analysis inputs. Final Analysis is built per spec."""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

from app.vision.model_assets import (
    VIDDEXA_MODEL_FILES,
    is_expected_nudenet_model,
    is_expected_viddexa_model,
    is_expected_yolo_model,
)

USER_APP_NAME = "LAVOCADO"
DEVELOPER_APP_NAME = "LAVOCADO-Developer"
DEVELOPER_BUNDLE_NAME = "LAVOCADO Developer"
USER_EXCLUDES = (
    "developer",
    "developer.benchmark",
    "developer.benchmark.dataset",
    "developer.benchmark.annotations",
    "developer.benchmark.configs",
    "developer.benchmark.engine",
    "developer.benchmark.runner",
    "developer.benchmark.inference_cache",
    "developer.benchmark.metrics",
    "developer.benchmark.comparison",
    "developer.benchmark.exporter",
    "developer.benchmark.results",
    "developer.benchmark.ranking",
    "developer.benchmark.session",
    "developer.benchmark.sweep",
    "developer.benchmark.tags",
    "developer.benchmark.preview",
    "developer.benchmark.ui",
    "developer.benchmark.ui.api",
    "developer.benchmark.ui.dashboard",
    "developer.benchmark.capture_benchmark",
    "developer.benchmark.capture_stability",
    "developer.benchmark.diagnostic_worker",
    "developer.benchmark.hardware_ipc",
    "developer.benchmark.jobs",
    "developer.benchmark.preprocessor_benchmark",
    "developer.benchmark.high_recall",
    "developer.benchmark.matrix",
    "developer.benchmark.ranking_metrics",
)
MODEL_HIDDENIMPORTS = (
    "ultralytics",
    "transformers.pipelines.image_classification",
    "transformers.models.efficientnet.configuration_efficientnet",
    "transformers.models.efficientnet.modeling_efficientnet",
    "transformers.models.efficientnet.image_processing_efficientnet",
)


def require_nudenet_model(specpath: Path) -> Path:
    model_path = specpath / "models" / "640m.onnx"
    if not is_expected_nudenet_model(model_path):
        raise SystemExit(
            "Verified models/640m.onnx is required for packaging; "
            "run: python scripts/download_models.py --model all"
        )
    return model_path


def required_model_datas(specpath: Path) -> list[tuple[str, str]]:
    """Only verified pinned files enter either release edition."""

    yolo_path = specpath / "models" / "yolo11.pt"
    if not is_expected_yolo_model(yolo_path):
        raise SystemExit(
            "Verified models/yolo11.pt is required for packaging; "
            "run: python scripts/download_models.py --model all"
        )
    data = [
        (str(require_nudenet_model(specpath)), "models"),
        (str(yolo_path), "models"),
    ]
    for model_id, files in VIDDEXA_MODEL_FILES.items():
        model_dir = specpath / "models" / model_id
        if not is_expected_viddexa_model(model_dir, model_id):
            raise SystemExit(
                f"Verified models/{model_id} is required for packaging; "
                "run: python scripts/download_models.py --model all"
            )
        data.extend((str(model_dir / item.name), f"models/{model_id}") for item in files)
    return data


def platform_hiddenimports() -> list[str]:
    if sys.platform == "win32":
        from comtypes.client import GetModule

        GetModule("UIAutomationCore.dll")
        hidden = [
            "dxcam",
            "comtypes.client",
            "comtypes.gen.UIAutomationClient",
        ]
    elif sys.platform == "darwin":
        hidden = [
            "AppKit",
            "ApplicationServices",
            "CoreMedia",
            "CoreText",
            "Foundation",
            "Quartz",
            "Quartz.CoreGraphics",
            "Quartz.CoreVideo",
            "ScreenCaptureKit",
            "dispatch",
            "objc",
        ]
    else:
        raise RuntimeError("Packaging supports Windows and macOS only")
    return hidden + list(MODEL_HIDDENIMPORTS)


def user_datas(specpath: Path) -> list[tuple[str, str]]:
    nudenet_data = collect_data_files("nudenet", includes=["*.onnx"])
    model_data = required_model_datas(specpath)
    web_data = [(str(specpath / "app" / "ui" / "web"), "app/ui/web")]
    return nudenet_data + model_data + web_data


def developer_datas(specpath: Path) -> list[tuple[str, str]]:
    lab_ui = specpath / "developer" / "benchmark" / "ui"
    return user_datas(specpath) + [(str(lab_ui), "developer/benchmark/ui")]


def developer_hiddenimports(platform_hidden: list[str]) -> list[str]:
    return list(platform_hidden) + [
        "developer",
        "developer.benchmark",
        "developer.benchmark.dataset",
        "developer.benchmark.annotations",
        "developer.benchmark.configs",
        "developer.benchmark.engine",
        "developer.benchmark.runner",
        "developer.benchmark.inference_cache",
        "developer.benchmark.metrics",
        "developer.benchmark.comparison",
        "developer.benchmark.exporter",
        "developer.benchmark.results",
        "developer.benchmark.ranking",
        "developer.benchmark.session",
        "developer.benchmark.sweep",
        "developer.benchmark.tags",
        "developer.benchmark.preview",
        "developer.benchmark.ui",
        "developer.benchmark.ui.api",
        "developer.benchmark.ui.dashboard",
        "developer.benchmark.capture_benchmark",
        "developer.benchmark.capture_stability",
        "developer.benchmark.diagnostic_worker",
        "developer.benchmark.hardware_ipc",
        "developer.benchmark.jobs",
        "developer.benchmark.preprocessor_benchmark",
        "developer.benchmark.high_recall",
        "developer.benchmark.matrix",
        "developer.benchmark.ranking_metrics",
        "psutil",
    ]


def macos_plist() -> dict[str, object]:
    return {
        "NSHighResolutionCapable": True,
        "NSScreenCaptureUsageDescription": (
            "LAVOCADO processes the screen locally to detect explicit content."
        ),
    }
