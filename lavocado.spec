# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

sys.path.insert(0, SPECPATH)

from lavocado_packaging.spec_common import (
    USER_APP_NAME,
    USER_EXCLUDES,
    macos_plist,
    platform_hiddenimports,
    user_datas,
)

platform_hidden_imports = platform_hiddenimports()
analysis = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=user_datas(Path(SPECPATH)),
    hiddenimports=platform_hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(USER_EXCLUDES),
    noarchive=False,
    optimize=0,
)
analysis.pure = type(analysis.pure)(
    [item for item in analysis.pure if not str(item[0]).startswith("developer")]
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=USER_APP_NAME,
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
    name=USER_APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        bundle,
        name="LAVOCADO.app",
        bundle_identifier="org.lavocado.desktop",
        info_plist=macos_plist(),
    )
