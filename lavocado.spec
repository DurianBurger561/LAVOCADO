# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


nudenet_data = collect_data_files("nudenet", includes=["*.onnx"])
model_path = Path(SPECPATH) / "models" / "640m.onnx"
if not model_path.is_file():
    raise SystemExit(
        "models/640m.onnx is required for packaging; "
        "run: python scripts/download_models.py"
    )
model_data = [(str(model_path), "models")]
web_data = [(str(Path(SPECPATH) / "app" / "ui" / "web"), "app/ui/web")]
if sys.platform == "win32":
    platform_hidden_imports = ["dxcam"]
elif sys.platform == "darwin":
    platform_hidden_imports = [
        "CoreMedia",
        "Foundation",
        "Quartz",
        "Quartz.CoreGraphics",
        "Quartz.CoreVideo",
        "ScreenCaptureKit",
        "dispatch",
        "objc",
    ]
else:
    platform_hidden_imports = []

analysis = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=nudenet_data + model_data + web_data,
    hiddenimports=platform_hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="LAVOCADO",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="LAVOCADO",
)

if sys.platform == "darwin":
    app = BUNDLE(
        bundle,
        name="LAVOCADO.app",
        bundle_identifier="org.lavocado.desktop",
        info_plist={
            "NSHighResolutionCapable": True,
            "NSScreenCaptureUsageDescription": (
                "LAVOCADO processes the screen locally to detect explicit content."
            ),
        },
    )
