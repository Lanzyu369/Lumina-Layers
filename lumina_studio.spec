# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.building.build_main import Tree

block_cipher = None

# Get gradio package path
import gradio
gradio_path = os.path.dirname(gradio.__file__)
gradio_parent = os.path.dirname(gradio_path)

# Get setuptools path for jaraco.text data files
import setuptools
setuptools_path = os.path.dirname(setuptools.__file__)
jaraco_text_path = os.path.join(setuptools_path, '_vendor', 'jaraco', 'text')

# Collect all data files from gradio and related packages
gradio_datas = collect_data_files('gradio')
gradio_client_datas = collect_data_files('gradio_client')

# Collect data files from all gradio dependencies that might have version files
try:
    safehttpx_datas = collect_data_files('safehttpx')
except Exception:
    safehttpx_datas = []

try:
    groovy_datas = collect_data_files('groovy')
except Exception:
    groovy_datas = []

try:
    tomlkit_datas = collect_data_files('tomlkit')
except Exception:
    tomlkit_datas = []

try:
    httpx_datas = collect_data_files('httpx')
except Exception:
    httpx_datas = []

try:
    setuptools_datas = collect_data_files('setuptools')
except Exception:
    setuptools_datas = []

try:
    pkg_resources_datas = collect_data_files('pkg_resources')
except Exception:
    pkg_resources_datas = []

try:
    jaraco_text_datas = collect_data_files('jaraco.text')
except Exception:
    jaraco_text_datas = []

all_gradio_datas = gradio_datas + gradio_client_datas + safehttpx_datas + groovy_datas + tomlkit_datas + httpx_datas + setuptools_datas + pkg_resources_datas + jaraco_text_datas

# Collect all submodules
hidden_imports = [
    'gradio',
    'gradio_client',
    'numpy',
    'cv2',
    'PIL',
    'trimesh',
    'scipy',
    'pystray',
    'pytz',
    'networkx',
    'lxml',
    'svglib',
    'reportlab',
    'colormath',
    'svgelements',
    'shapely',
    # Additional hidden imports
    'scipy.spatial.transform',
    'scipy.spatial.distance',
    'scipy.sparse.csgraph',
    'scipy.sparse.linalg',
    'scipy.linalg',
    'scipy.special',
    'trimesh.exchange',
    'trimesh.visual',
    'trimesh.path',
    'trimesh.scene',
    'shapely.geometry',
    'shapely.ops',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'pystray._win32',
    'pkg_resources.py2_warn',
    # Gradio specific imports
    'gradio.blocks_events',
    'gradio.component_meta',
]

# Collect all submodules from core packages
hidden_imports += collect_submodules('gradio')
hidden_imports += collect_submodules('gradio_client')
hidden_imports += collect_submodules('trimesh')
hidden_imports += collect_submodules('scipy')
hidden_imports += collect_submodules('shapely')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),
        ('lut-npy预设', 'lut-npy预设'),
        ('icon.ico', '.'),
        ('LICENSE', '.'),
        ('README.md', '.'),
        ('README_CN.md', '.'),
        ('core', 'core'),
        ('ui', 'ui'),
        ('utils', 'utils'),
        ('config.py', '.'),
        # Include gradio source files (needed for runtime introspection)
        (os.path.join(gradio_parent, 'gradio'), 'gradio'),
        # Include jaraco.text data files (needed by setuptools/pkg_resources)
        (jaraco_text_path, 'setuptools/_vendor/jaraco/text'),
    ] + all_gradio_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'pandas',
        'pytest',
        'IPython',
        'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LuminaStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Set to True to see console output for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LuminaStudio',
)

# Copy icon.ico and lut-npy预设 to the root of dist/LuminaStudio
import shutil
dist_root = os.path.join('dist', 'LuminaStudio')
if os.path.exists('icon.ico'):
    shutil.copy2('icon.ico', os.path.join(dist_root, 'icon.ico'))
if os.path.exists('lut-npy预设'):
    dest_lut = os.path.join(dist_root, 'lut-npy预设')
    if os.path.exists(dest_lut):
        shutil.rmtree(dest_lut)
    shutil.copytree('lut-npy预设', dest_lut)
