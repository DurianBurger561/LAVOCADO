"""Shared PyInstaller Analysis inputs. Final Analysis is built per spec."""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


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
    "developer.benchmark.session",
    "developer.benchmark.ui",
    "developer.benchmark.ui.api",
    "developer.benchmark.ui.dashboard",
)


def require_nudenet_model(specpath: Path) -> Path:
    model_path = specpath / "models" / "640m.onnx"
    if not model_path.is_file():
        raise SystemExit(
            "models/640m.onnx is required for packaging; "
            "run: python scripts/download_models.py"
        )
    return model_path


def platform_collect() -> tuple[list, list, list[str]]:
    platform_binaries: list = []
    platform_data: list = []
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
        from PyInstaller.utils.hooks.gi import get_gi_typelibs

        platform_binaries, platform_data, atspi_hidden_imports = get_gi_typelibs(
            "Atspi", "2.0"
        )
        hidden = [
            "dbus_fast",
            "dbus_fast.aio",
            "gi",
            "gi.repository.Atspi",
            "mss.linux.xgetimage",
            "mss.linux.xshmgetimage",
        ] + atspi_hidden_imports
    return platform_binaries, platform_data, hidden


def user_datas(specpath: Path) -> list[tuple[str, str]]:
    nudenet_data = collect_data_files("nudenet", includes=["*.onnx"])
    model_data = [(str(require_nudenet_model(specpath)), "models")]
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
        "developer.benchmark.session",
        "developer.benchmark.ui",
        "developer.benchmark.ui.api",
        "developer.benchmark.ui.dashboard",
    ]


def macos_plist() -> dict[str, object]:
    return {
        "NSHighResolutionCapable": True,
        "NSScreenCaptureUsageDescription": (
            "LAVOCADO processes the screen locally to detect explicit content."
        ),
    }
