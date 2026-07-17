"""Desktop build packaging contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_electron_build_packages_material_seed_resource_directory() -> None:
    package_json = json.loads(
        (ROOT / "electron" / "package.json").read_text(encoding="utf-8")
    )

    extra_resources = package_json["build"]["extraResources"]
    resource_pairs = {
        (entry.get("from"), entry.get("to"))
        for entry in extra_resources
        if isinstance(entry, dict)
    }

    assert ("resources/materials", "materials") in resource_pairs


def test_desktop_build_copies_material_seed_to_packaged_resource_directory() -> None:
    build_script = (ROOT / "scripts" / "build_desktop.py").read_text(encoding="utf-8")

    assert 'MATERIALS_RES_DIR = RESOURCES_DIR / "materials"' in build_script
    assert 'target_seed_path = MATERIALS_RES_DIR / "lumina-materials-seed.zip"' in build_script


def test_desktop_build_checks_default_glb_v2_dependencies_before_pyinstaller() -> None:
    build_script = (ROOT / "scripts" / "build_desktop.py").read_text(encoding="utf-8")

    assert "GLB_V2_REQUIRED_MODULES" in build_script
    assert "rasterio.features" in build_script
    assert "manifold3d" in build_script

    deps_index = build_script.index("require_desktop_mesh_kernel_dependencies()")
    pyinstaller_index = build_script.index("pyinstaller lumina_studio.spec")
    assert deps_index < pyinstaller_index


def test_desktop_release_requires_native_mesh_kernel_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A release build must fail before PyInstaller when a wheel cannot load."""

    from scripts import build_desktop

    real_import = build_desktop.importlib.import_module

    def fail_manifold_import(module_name: str):
        if module_name == "manifold3d":
            raise OSError("simulated missing Windows DLL")
        return real_import(module_name)

    monkeypatch.setattr(build_desktop.importlib, "import_module", fail_manifold_import)

    with pytest.raises(RuntimeError, match="requirements-glb-v2.txt"):
        build_desktop.require_desktop_mesh_kernel_dependencies()


def test_formal_windows_workflow_builds_electron_release_and_smokes_frozen_backend() -> None:
    """Windows CI must exercise the same release entry point users download."""

    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(
        encoding="utf-8",
    )

    assert "pip install -r requirements-glb-v2.txt" in workflow
    assert "python scripts/build_desktop.py" in workflow
    assert "dist/lumina-backend.exe" in workflow
    assert "--desktop-native-kernel-smoke" in workflow
    assert "electron/dist_electron" in workflow
    assert "pyinstaller --noconfirm --onefile" not in workflow
    assert "main.py" not in workflow


def test_pyinstaller_spec_fails_when_required_mesh_kernel_collection_fails() -> None:
    """Direct spec invocation must not silently create a fallback-only release."""

    spec = (ROOT / "lumina_studio.spec").read_text(encoding="utf-8")

    assert "Could not collect required desktop mesh-kernel package" in spec
    assert "require_desktop_mesh_kernel_modules()" in spec
    assert "importlib.import_module(module_name)" in spec
    assert "continuing with Python fallback" not in spec


def test_desktop_release_smoke_uses_native_relief_and_produces_watertight_board() -> None:
    """The same callable frozen into the exe must prove native relief behavior."""

    from api.desktop_release_smoke import run_native_relief_smoke

    result = run_native_relief_smoke()

    assert result["status"] == "ok"
    assert result["native_kernel"] == "manifold3d"
    assert result["fallback_called"] is False
    assert result["board_watertight"] is True
    assert result["board_volume"] == pytest.approx(65.0)
