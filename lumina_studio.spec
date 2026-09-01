# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Lumina Studio.

Usage:
    pyinstaller lumina_studio.spec
"""

import json
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
ROOT = Path.cwd()
GLB_V2_PACKAGES = ("rasterio", "manifold3d")
GLB_V2_HIDDENIMPORTS = ("rasterio.features", "manifold3d")
NEROUED_3MF_PACKAGE = "neroued_3mf"
NEROUED_3MF_HIDDENIMPORTS = ("neroued_3mf", "neroued_3mf._neroued_3mf")


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
    """Collect only files required by the packaged machine-registry runtime."""

    registry_root = Path(registry_root).resolve()
    registry_path = registry_root / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    relative_paths = {Path("registry.json")}
    for slicer in registry["slicers"]:
        relative_paths.update(
            Path(plate["image"]) for plate in slicer.get("build_plates", [])
        )
        for machine in slicer["machines"]:
            relative_paths.update(
                Path(nozzle["template"]) for nozzle in machine["nozzles"]
            )

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

backend_datas = [
    # Includes the app-owned Workshop Registry key set and offline snapshot in
    # assets/workshop-registry/ alongside the existing runtime assets.
    ('assets', 'assets'),
    # Runtime registry contract only: registry, Lumina plate art, and referenced templates.
    *collect_machine_registry_runtime_datas(ROOT / 'machine_registry'),
    ('printer_profiles', 'printer_profiles'),
    ('bambu_config_template.json', '.'),
    *neroued_3mf_datas,
    *glb_v2_datas,
]
backend_binaries = [
    *neroued_3mf_binaries,
    *glb_v2_binaries,
]
backend_hiddenimports = [
    *NEROUED_3MF_HIDDENIMPORTS,
    *neroued_3mf_hiddenimports,
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
