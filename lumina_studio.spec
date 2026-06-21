# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Lumina Studio.

Usage:
    pyinstaller lumina_studio.spec
"""

import os
import sysconfig
from pathlib import Path

block_cipher = None
ROOT = Path.cwd()
NATIVE_EXT_SUFFIX = sysconfig.get_config_var("EXT_SUFFIX") or (".pyd" if os.name == "nt" else ".so")
NATIVE_EXT_PATH = ROOT / f"clipper2_batch{NATIVE_EXT_SUFFIX}"
native_binaries = [(str(NATIVE_EXT_PATH), ".")] if NATIVE_EXT_PATH.exists() else []

a = Analysis(
    ['api_server.py'],
    pathex=[],
    binaries=native_binaries,
    datas=[
        ('assets', 'assets'),  # Bundle entire assets/ folder (8-color stacks etc.)
    ],
    hiddenimports=['clipper2_batch'],
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
