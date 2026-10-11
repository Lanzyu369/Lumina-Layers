# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Lumina Studio.

Usage:
    pyinstaller lumina_studio.spec
"""

import importlib
import json
import sys
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path

SPEC_ROOT = Path(SPEC).resolve().parent
if str(SPEC_ROOT) not in sys.path:
    sys.path.insert(0, str(SPEC_ROOT))

from PyInstaller.utils.hooks import collect_all, get_module_file_attribute

from scripts.fatcat_packaging_contract import validate_fatcat_packaging_contract
from scripts.fatcat_packaging_contract import (
    FATCAT_ADAPTER_MODULE,
    FATCAT_MODULE,
)
from scripts.native_svg_packaging_contract import validate_native_svg_runtime_version

block_cipher = None
ROOT = Path.cwd()
GLB_V2_PACKAGES = ("rasterio", "manifold3d")
GLB_V2_HIDDENIMPORTS = ("rasterio.features", "manifold3d")
NEROUED_3MF_PACKAGE = "neroued_3mf"
NEROUED_3MF_HIDDENIMPORTS = ("neroued_3mf", "neroued_3mf._neroued_3mf")
FATCAT_METADATA_MODULE = FATCAT_MODULE
LUMINA_SVG_CORE_PACKAGE = "lumina_svg_core"
validate_native_svg_runtime_version(importlib.import_module(LUMINA_SVG_CORE_PACKAGE))
LUMINA_SVG_CORE_EXTENSION = "lumina_svg_core._lumina_svg_core"
LUMINA_SVG_COMPENSATION_EXTENSION = "lumina_svg_core._lumina_svg_compensation"
COLORCHECKER_DATA_DIR = ROOT / "core" / "colorchecker" / "data"
LUMINA_SVG_CORE_HIDDENIMPORTS = (
    "lumina_svg_core",
    LUMINA_SVG_CORE_EXTENSION,
    LUMINA_SVG_COMPENSATION_EXTENSION,
)


def collect_glb_v2_package(package_name):
    """Collect optional GLB v2 dependencies used by dynamic imports."""

    try:
        return collect_all(package_name)
    except Exception as exc:
        print(
            f"WARNING: Could not collect optional GLB v2 package {package_name!r}: {exc}",
        )
        return [], [], []


def collect_machine_registry_runtime_datas(registry_root):
    """Collect the registry, thumbnails and plate art used by the device picker."""

    registry_root = Path(registry_root).resolve()
    registry_path = registry_root / "registry.json"
    relative_paths = {Path("registry.json")}
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for slicer in registry["slicers"]:
        relative_paths.update(Path(plate["image"]) for plate in slicer.get("build_plates", []))
        relative_paths.update(
            Path(machine["thumbnail"])
            for machine in slicer.get("machines", [])
            if machine.get("thumbnail")
        )
    for asset_index_path in registry_root.glob("slicers/*/*/picker-assets.json"):
        asset_index = json.loads(asset_index_path.read_text(encoding="utf-8"))
        relative_paths.add(asset_index_path.relative_to(registry_root))
        relative_paths.update(Path(image) for image in asset_index["thumbnails"].values())

    datas = []
    for relative_path in sorted(relative_paths, key=lambda path: path.as_posix()):
        source_path = (registry_root / relative_path).resolve()
        try:
            source_path.relative_to(registry_root)
        except ValueError as exc:
            raise ValueError(
                f"Machine registry runtime path escapes registry root: {relative_path}"
            ) from exc
        if not source_path.is_file():
            raise FileNotFoundError(
                f"Machine registry runtime file is missing: {relative_path}"
            )
        destination = Path("machine_registry") / relative_path.parent
        datas.append((str(source_path), destination.as_posix()))
    return datas


def collect_fatcat_runtime_package():
    """Collect the top-level Fat Cat extension and its wheel data files."""

    try:
        module_path = Path(get_module_file_attribute(FATCAT_METADATA_MODULE)).resolve()
        fatcat_module = importlib.import_module(FATCAT_METADATA_MODULE)
        importlib.import_module(FATCAT_ADAPTER_MODULE)
        writer_module = importlib.import_module(NEROUED_3MF_PACKAGE)
    except Exception as exc:
        raise RuntimeError(
            "Fat Cat C++ metadata binding is required for the desktop B4 route"
        ) from exc

    data_root = validate_fatcat_packaging_contract(fatcat_module, writer_module)

    datas = []
    for source_path in sorted(data_root.rglob("*")):
        if source_path.is_file():
            relative_path = source_path.relative_to(data_root)
            destination = Path("fatcat_metadata_data") / relative_path.parent
            datas.append((str(source_path), destination.as_posix()))
    return datas, [(str(module_path), ".")], [
        FATCAT_METADATA_MODULE,
        FATCAT_ADAPTER_MODULE,
    ]


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

# This is a required compiled dependency, unlike the optional GLB v2 packages.
# Let packaging fail immediately if its extension or bundled runtime libraries
# cannot be collected.
(
    neroued_3mf_datas,
    neroued_3mf_binaries,
    neroued_3mf_hiddenimports,
) = collect_all(NEROUED_3MF_PACKAGE)

(
    fatcat_metadata_datas,
    fatcat_metadata_binaries,
    fatcat_metadata_hiddenimports,
) = collect_fatcat_runtime_package()

# Native SVG is a required compiled dependency. A missing extension must stop
# packaging instead of silently producing a legacy-only desktop executable.
(
    lumina_svg_core_datas,
    lumina_svg_core_binaries,
    lumina_svg_core_hiddenimports,
) = collect_all(LUMINA_SVG_CORE_PACKAGE)
for extension_name in (LUMINA_SVG_CORE_EXTENSION, LUMINA_SVG_COMPENSATION_EXTENSION):
    lumina_svg_core_extension_path = Path(
        get_module_file_attribute(extension_name)
    ).resolve()
    if not any(
        str(lumina_svg_core_extension_path).endswith(suffix)
        for suffix in EXTENSION_SUFFIXES
    ):
        raise RuntimeError(
            "Native SVG module did not resolve to a CPython extension: "
            f"{lumina_svg_core_extension_path}"
        )
    if not any(
        Path(source_path).resolve() == lumina_svg_core_extension_path
        for source_path, _destination in lumina_svg_core_binaries
    ):
        # Editable installs can split Python and native modules across paths.
        lumina_svg_core_binaries.append(
            (str(lumina_svg_core_extension_path), LUMINA_SVG_CORE_PACKAGE)
        )

backend_datas = [
    # Includes the app-owned Workshop Registry key set and offline snapshot in
    # assets/workshop-registry/ alongside the existing runtime assets.
    ('assets', 'assets'),
    # Runtime registry contract only: device identities and Lumina plate art.
    *collect_machine_registry_runtime_datas(ROOT / 'machine_registry'),
    ('lut-preset', 'lut-preset'),
    # The frozen backend imports the built-in ColorChecker reference registry
    # during app startup; keep its descriptor/reference data beside the module.
    (str(COLORCHECKER_DATA_DIR), 'core/colorchecker/data'),
    *neroued_3mf_datas,
    *fatcat_metadata_datas,
    *lumina_svg_core_datas,
    *glb_v2_datas,
]
backend_binaries = [
    *neroued_3mf_binaries,
    *fatcat_metadata_binaries,
    *lumina_svg_core_binaries,
    *glb_v2_binaries,
]
backend_hiddenimports = [
    *NEROUED_3MF_HIDDENIMPORTS,
    *neroued_3mf_hiddenimports,
    *fatcat_metadata_hiddenimports,
    *LUMINA_SVG_CORE_HIDDENIMPORTS,
    *lumina_svg_core_hiddenimports,
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
    # Electron starts the backend with windowsHide=true and pipes stdout.
    # Keep a console-capable executable so CI and support diagnostics can read
    # --native-svg-self-test JSON from the actual onefile binary.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)
