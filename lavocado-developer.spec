# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

sys.path.insert(0, SPECPATH)

from lavocado_packaging.spec_common import (
    DEVELOPER_APP_NAME,
    DEVELOPER_BUNDLE_NAME,
    developer_datas,
    developer_hiddenimports,
    macos_plist,
    model_dependency_binaries,
    platform_hiddenimports,
)

platform_hidden_imports = platform_hiddenimports()
analysis = Analysis(
    ["developer_main.py"],
    pathex=[],
    binaries=model_dependency_binaries(),
    datas=developer_datas(Path(SPECPATH)),
    hiddenimports=developer_hiddenimports(platform_hidden_imports),
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
    name=DEVELOPER_APP_NAME,
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
    name=DEVELOPER_APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        bundle,
        name=f"{DEVELOPER_BUNDLE_NAME}.app",
        bundle_identifier="org.lavocado.desktop.developer",
        info_plist=macos_plist(),
    )
