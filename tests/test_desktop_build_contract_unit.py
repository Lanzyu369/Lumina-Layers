"""Desktop build packaging contract tests."""

from __future__ import annotations

import json
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path
import runpy
import shutil
import sys
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
FAKE_NATIVE_EXTENSION_PATH = Path("/tmp") / (
    f"_lumina_svg_core{EXTENSION_SUFFIXES[0]}"
)


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


def test_electron_build_packages_workshop_seed_resource_directory() -> None:
    package_json = json.loads(
        (ROOT / "electron" / "package.json").read_text(encoding="utf-8")
    )

    extra_resources = package_json["build"]["extraResources"]
    resource_pairs = {
        (entry.get("from"), entry.get("to"))
        for entry in extra_resources
        if isinstance(entry, dict)
    }

    assert ("resources/workshop-seed", "workshop-seed") in resource_pairs


def _load_spec_namespace(monkeypatch) -> dict[str, object]:
    hooks_module = ModuleType("PyInstaller.utils.hooks")
    hooks_module.collect_all = lambda _package_name: ([], [], [])
    hooks_module.get_module_file_attribute = (
        lambda _module_name: str(FAKE_NATIVE_EXTENSION_PATH)
    )
    utils_module = ModuleType("PyInstaller.utils")
    pyinstaller_module = ModuleType("PyInstaller")
    monkeypatch.setitem(sys.modules, "PyInstaller", pyinstaller_module)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils", utils_module)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks_module)
    monkeypatch.chdir(ROOT)

    def fake_analysis(*_args, **kwargs):
        return SimpleNamespace(
            pure=[],
            zipped_data=[],
            scripts=[],
            binaries=kwargs.get("binaries", []),
            datas=kwargs.get("datas", []),
        )

    return runpy.run_path(
        str(ROOT / "lumina_studio.spec"),
        init_globals={
            "Analysis": fake_analysis,
            "PYZ": lambda *_args, **_kwargs: object(),
            "EXE": lambda *_args, **_kwargs: object(),
        },
    )


def _load_spec_backend_datas(monkeypatch) -> list[tuple[str, str]]:
    namespace = _load_spec_namespace(monkeypatch)
    return namespace["backend_datas"]


def _expanded_machine_registry_manifest(
    datas: list[tuple[str, str]],
) -> set[str]:
    registry_root = (ROOT / "machine_registry").resolve()
    packaged: set[str] = set()
    for raw_source, raw_destination in datas:
        source = Path(raw_source)
        if not source.is_absolute():
            source = ROOT / source
        source = source.resolve()
        if source != registry_root and registry_root not in source.parents:
            continue

        destination = Path(raw_destination)
        if source.is_dir():
            packaged.update(
                (destination / path.relative_to(source)).as_posix()
                for path in source.rglob("*")
                if path.is_file()
            )
        else:
            packaged.add((destination / source.name).as_posix())
    return packaged


def _expected_machine_registry_manifest() -> set[str]:
    data = json.loads(
        (ROOT / "machine_registry" / "registry.json").read_text(encoding="utf-8")
    )
    relative_paths = {"registry.json"}
    for slicer in data["slicers"]:
        relative_paths.update(
            str(plate["image"]) for plate in slicer.get("build_plates", [])
        )
        for machine in slicer["machines"]:
            relative_paths.update(
                str(nozzle["template"]) for nozzle in machine["nozzles"]
            )
    return {f"machine_registry/{path}" for path in relative_paths}


def test_pyinstaller_spec_bundles_only_registry_runtime_contract(monkeypatch) -> None:
    packaged = _expanded_machine_registry_manifest(
        _load_spec_backend_datas(monkeypatch)
    )

    assert packaged == _expected_machine_registry_manifest()
    assert not any("/assets/" in path for path in packaged)
    assert not any("/bed_models/" in path for path in packaged)
    assert "machine_registry/BUILD_PLATE_SOURCES.md" not in packaged


def test_pyinstaller_spec_explicitly_bundles_native_svg_extension(
    monkeypatch,
) -> None:
    namespace = _load_spec_namespace(monkeypatch)

    assert (
        str(FAKE_NATIVE_EXTENSION_PATH.resolve()),
        "lumina_svg_core",
    ) in namespace["backend_binaries"]


def test_pyinstaller_spec_bundles_registry_project_profile_dependencies() -> None:
    spec = (ROOT / "lumina_studio.spec").read_text(encoding="utf-8")

    assert spec.count("('printer_profiles', 'printer_profiles')") == 1


def test_electron_does_not_duplicate_pyinstaller_machine_registry() -> None:
    package_json = json.loads(
        (ROOT / "electron" / "package.json").read_text(encoding="utf-8")
    )

    extra_resources = package_json["build"]["extraResources"]
    assert not any(
        isinstance(entry, dict) and entry.get("to") == "machine_registry"
        for entry in extra_resources
    )


def test_desktop_build_copies_material_seed_to_packaged_resource_directory() -> None:
    build_script = (ROOT / "scripts" / "build_desktop.py").read_text(encoding="utf-8")

    assert 'MATERIALS_RES_DIR = RESOURCES_DIR / "materials"' in build_script
    assert 'target_seed_path = MATERIALS_RES_DIR / "lumina-materials-seed.zip"' in build_script


def test_desktop_build_checks_geometry_dependencies_before_pyinstaller() -> None:
    build_script = (ROOT / "scripts" / "build_desktop.py").read_text(encoding="utf-8")

    assert "CORE_GEOMETRY_REQUIRED_MODULES" in build_script
    assert "GLB_V2_OPTIONAL_MODULES" in build_script
    assert "rasterio.features" in build_script
    assert "manifold3d" in build_script

    deps_index = build_script.rindex("check_core_geometry_dependencies_available()")
    pyinstaller_index = build_script.index("pyinstaller lumina_studio.spec")
    assert deps_index < pyinstaller_index


def test_production_pyinstaller_spec_packages_printer_templates() -> None:
    spec = (ROOT / "lumina_studio.spec").read_text(encoding="utf-8")

    assert "('printer_profiles', 'printer_profiles')" in spec
    assert "('bambu_config_template.json', '.')" in spec


def test_frozen_meipass_loads_packaged_orca_p2s_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production spec must materialize templates where the loader reads."""

    shutil.copytree(ROOT / "printer_profiles", tmp_path / "printer_profiles")
    shutil.copy2(
        ROOT / "bambu_config_template.json",
        tmp_path / "bambu_config_template.json",
    )

    from utils.bambu_3mf_writer import (
        _PRINTER_TEMPLATE_CACHE,
        load_printer_template,
    )

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    _PRINTER_TEMPLATE_CACHE.clear()
    try:
        template = load_printer_template(
            "bambu-p2s",
            slicer="OrcaSlicer",
            nozzle_size="0.4",
        )
    finally:
        _PRINTER_TEMPLATE_CACHE.clear()

    assert template
    assert template["initial_layer_print_height"] == "0.08"
    assert template["print_compatible_printers"] == [
        "Bambu Lab P2S 0.4 nozzle"
    ]


def test_electron_build_packages_workshop_security_boundary() -> None:
    package_json = json.loads(
        (ROOT / "electron" / "package.json").read_text(encoding="utf-8")
    )

    assert "workshop-security.cjs" in package_json["build"]["files"]


def test_electron_build_packages_native_bed_model_bridge() -> None:
    package_json = json.loads(
        (ROOT / "electron" / "package.json").read_text(encoding="utf-8")
    )
    main = (ROOT / "electron" / "main.cjs").read_text(encoding="utf-8")
    preload = (ROOT / "electron" / "preload.cjs").read_text(encoding="utf-8")
    build_script = (ROOT / "scripts" / "build_desktop.py").read_text(
        encoding="utf-8"
    )

    assert "bed-model-bridge.cjs" in package_json["build"]["files"]
    assert "bed-model-bridge.cjs" in build_script
    assert 'ipcMain.handle("get-native-bed-model"' in main
    assert "isAllowedBedModelIpcSender" in main
    assert "fetchNativeBedModel" in main
    # Packaged desktop now serves the bundled UI through the owned local
    # backend endpoint, rather than loading a file:// URL directly.
    assert "backendEndpoint.origin" in main
    assert "loadURL(trustedMainFrameUrl)" in main
    assert "getNativeBedModel" in preload
    assert "get-native-bed-model" in preload


def test_desktop_build_preflights_workshop_security_files() -> None:
    build_script = (ROOT / "scripts" / "build_desktop.py").read_text(encoding="utf-8")

    assert "WORKSHOP_DESKTOP_SECURITY_FILES" in build_script
    assert "check_workshop_desktop_security_files()" in build_script
    check_index = build_script.index("check_workshop_desktop_security_files()")
    electron_build_index = build_script.index('run("pnpm run build"')
    assert check_index < electron_build_index


def test_desktop_build_requires_verified_workshop_seed_before_build() -> None:
    build_script = (
        ROOT / "scripts" / "build_desktop.py"
    ).read_text(encoding="utf-8")

    assert "--workshop-seed-path" in build_script
    assert "verify_workshop_seed" in build_script
    prepare_index = build_script.rindex(
        "prepare_workshop_seed_resource("
    )
    frontend_build_index = build_script.index(
        'run(\n        "pnpm run build"'
    )
    assert prepare_index < frontend_build_index


def test_electron_main_owns_workshop_protocol_token_and_firewall() -> None:
    main = (ROOT / "electron" / "main.cjs").read_text(encoding="utf-8")

    assert "protocol.registerSchemesAsPrivileged" in main
    assert 'protocol.handle("lumina-workshop"' in main
    assert "X-Lumina-Workshop-Desktop-Token" in main
    assert "LUMINA_WORKSHOP_DESKTOP_TOKEN" in main
    assert "LUMINA_WORKSHOP_DATA_DIR" in main
    assert "LUMINA_WORKSHOP_SEED_DIR" in main
    assert "webRequest.onBeforeRequest" in main
    assert "isAllowedWorkshopRequest" in main
    assert "will-frame-navigate" in main
    assert "will-redirect" in main
    assert "setPermissionRequestHandler" in main
    assert "isWorkshopFrameProcessIsolated" in main
    assert "runtime-isolation-unavailable" in main


def test_electron_preload_exposes_runtime_mode_without_desktop_secret() -> None:
    preload = (ROOT / "electron" / "preload.cjs").read_text(encoding="utf-8")

    assert "getWorkshopRuntimeMode" in preload
    assert "get-workshop-runtime-mode" in preload
    assert "WORKSHOP_DESKTOP_TOKEN" not in preload
    assert "workshopSessionToken" not in preload
