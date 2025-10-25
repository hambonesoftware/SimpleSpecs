# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for the SimpleSpecs backend service."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

project_root = Path(__file__).resolve().parent

block_cipher = None

datas = [
    (str(project_root / "frontend"), "frontend"),
    (str(project_root / "backend" / "resources"), "backend/resources"),
]

hiddenimports = collect_submodules("backend")

analysis = Analysis(
    [str(project_root / "backend" / "__main__.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="SimpleSpecs",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SimpleSpecs",
)
