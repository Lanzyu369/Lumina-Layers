# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Lumina Studio.

Usage:
    pyinstaller lumina_studio.spec
"""

import importlib
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


def require_desktop_mesh_kernel_modules():
    """Reject direct spec builds that cannot load required release modules."""

    missing = []
    for module_name in GLB_V2_HIDDENIMPORTS:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            missing.append(f"{module_name}: {type(exc).__name__}: {exc}")
    if missing:
        raise RuntimeError(
            "Desktop release requires requirements-glb-v2.txt; unavailable: "
            + "; ".join(missing),
        )


def collect_glb_v2_package(package_name):
    """Collect required desktop mesh-kernel dependencies used dynamically."""

    try:
        return collect_all(package_name)
    except Exception as exc:
        raise RuntimeError(
            "Could not collect required desktop mesh-kernel package "
            f"{package_name!r}: {exc}",
        ) from exc


glb_v2_datas = []
glb_v2_binaries = []
glb_v2_hiddenimports = []
require_desktop_mesh_kernel_modules()
for glb_v2_package in GLB_V2_PACKAGES:
    package_datas, package_binaries, package_hiddenimports = collect_glb_v2_package(
        glb_v2_package,
    )
    glb_v2_datas.extend(package_datas)
    glb_v2_binaries.extend(package_binaries)
    glb_v2_hiddenimports.extend(package_hiddenimports)

backend_datas = [
    ('assets', 'assets'),  # Bundle entire assets/ folder (8-color stacks etc.)
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
