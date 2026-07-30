# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Lumina Studio.

Usage:
    pyinstaller lumina_studio.spec
"""

import os
import sysconfig
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
ROOT = Path.cwd()
NATIVE_EXT_SUFFIX = sysconfig.get_config_var("EXT_SUFFIX") or (".pyd" if os.name == "nt" else ".so")
NATIVE_EXT_PATH = ROOT / f"clipper2_batch{NATIVE_EXT_SUFFIX}"
native_binaries = [(str(NATIVE_EXT_PATH), ".")] if NATIVE_EXT_PATH.exists() else []
GLB_V2_PACKAGES = ("rasterio", "manifold3d")
GLB_V2_HIDDENIMPORTS = ("rasterio.features", "manifold3d")


def collect_glb_v2_package(package_name):
    """Collect optional GLB v2 dependencies used by dynamic imports."""

    try:
        return collect_all(package_name)
    except Exception as exc:
        print(
            f"WARNING: Could not collect optional GLB v2 package {package_name!r}: {exc}",
        )
        return [], [], []


glb_v2_datas = []
glb_v2_binaries = []
glb_v2_hiddenimports = []
for glb_v2_package in GLB_V2_PACKAGES:
    package_datas, package_binaries, package_hiddenimports = collect_glb_v2_package(
        glb_v2_package,
    )
    glb_v2_datas.extend(package_datas)
    glb_v2_binaries.extend(package_binaries)
    glb_v2_hiddenimports.extend(package_hiddenimports)

backend_datas = [
    # Includes the app-owned Workshop Registry key set and offline snapshot in
    # assets/workshop-registry/ alongside the existing runtime assets.
    ('assets', 'assets'),
    *glb_v2_datas,
]
backend_binaries = [
    *native_binaries,
    *glb_v2_binaries,
]
backend_hiddenimports = [
    'clipper2_batch',
    *GLB_V2_HIDDENIMPORTS,
    *glb_v2_hiddenimports,
]

a = Analysis(
    ['api_server.py'],
    pathex=[],
    binaries=backend_binaries,
    datas=backend_datas,
    hiddenimports=backend_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='lumina-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)
