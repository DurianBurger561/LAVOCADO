# -*- mode: python ; coding: utf-8 -*-

import sys

from PyInstaller.utils.hooks import collect_data_files


nudenet_data = collect_data_files("nudenet", includes=["*.onnx"])

analysis = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=nudenet_data,
    hiddenimports=[],
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
