"""Shared PyInstaller Analysis inputs. Final Analysis is built per spec."""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    copy_metadata,
)

from app.vision.model_assets import (
    is_expected_nudenet_model,
    is_expected_viddexa_model,
    is_expected_yolo_model,
)
from app.vision.model_manifest import CATALOG, ModelRole

USER_APP_NAME = "LAVOCADO"
DEVELOPER_APP_NAME = "LAVOCADO-Developer"
DEVELOPER_BUNDLE_NAME = "LAVOCADO Developer"
USER_EXCLUDES = (
    "developer",
    "developer.benchmark",
    "developer.benchmark.dataset",
    "developer.benchmark.annotations",
    "developer.benchmark.configs",
    "developer.benchmark.contracts",
    "developer.benchmark.cli",
    "developer.benchmark.engine",
    "developer.benchmark.runner",
    "developer.benchmark.inference_cache",
    "developer.benchmark.metrics",
    "developer.benchmark.comparison",
    "developer.benchmark.failures",
    "developer.benchmark.registry",
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
    "transformers.pipelines",
    "transformers.pipelines.image_classification",
    "transformers.models.auto.configuration_auto",
    "transformers.models.auto.image_processing_auto",
    "transformers.models.auto.modeling_auto",
    "transformers.models.efficientnet.configuration_efficientnet",
    "transformers.models.efficientnet.modeling_efficientnet",
    "transformers.models.efficientnet.image_processing_efficientnet",
)
MODEL_METADATA = (
    "transformers",
    "torch",
    "torchvision",
    "huggingface-hub",
    "safetensors",
    "tokenizers",
)


def model_dependency_metadata() -> list[tuple[str, str]]:
    """Preserve metadata used by Transformers' frozen dependency checks."""

    data: list[tuple[str, str]] = []
    for distribution in MODEL_METADATA:
        data.extend(copy_metadata(distribution))
    return data


def model_dependency_binaries() -> list[tuple[str, str]]:
    """Bundle torchvision ops loaded by file path rather than Python import."""

    binaries = collect_dynamic_libs(
        "torchvision", search_patterns=["*.so", "*.pyd", "*.dll", "*.dylib"]
    )
    if not any(Path(source).stem.startswith("_C") for source, _ in binaries):
        raise SystemExit("torchvision native ops are required for bundled Viddexa models")
    return binaries


def required_model_datas(specpath: Path) -> list[tuple[str, str]]:
    """Only verified pinned files enter either release edition."""

    data: list[tuple[str, str]] = []
    for spec in CATALOG:
        if not spec.required:
            continue
        bundled = specpath / spec.bundled_path
        if spec.id == "nudenet_640m":
            valid = is_expected_nudenet_model(bundled)
        elif spec.id == "yolo11_nsfw_small":
            valid = is_expected_yolo_model(bundled)
        elif spec.role is ModelRole.REGION_RANKER:
            valid = is_expected_viddexa_model(bundled, spec.id)
        else:
            raise RuntimeError(f"Unknown required model: {spec.id}")
        if not valid:
            raise SystemExit(
                f"Verified {spec.bundled_path} is required for packaging; "
                "run: python scripts/download_models.py --model all"
            )
        if spec.role is ModelRole.REGION_RANKER:
            data.extend((str(bundled / item.name), spec.bundled_path) for item in spec.required_files)
        else:
            data.append((str(bundled), "models"))
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
    return nudenet_data + model_data + model_dependency_metadata() + web_data


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
        "developer.benchmark.contracts",
        "developer.benchmark.cli",
        "developer.benchmark.engine",
        "developer.benchmark.runner",
        "developer.benchmark.inference_cache",
        "developer.benchmark.metrics",
        "developer.benchmark.comparison",
        "developer.benchmark.failures",
        "developer.benchmark.registry",
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
