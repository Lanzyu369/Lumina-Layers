"""Desktop build packaging contract tests."""

from __future__ import annotations

import json
from pathlib import Path


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


def test_desktop_build_copies_material_seed_to_packaged_resource_directory() -> None:
    build_script = (ROOT / "scripts" / "build_desktop.py").read_text(encoding="utf-8")

    assert 'MATERIALS_RES_DIR = RESOURCES_DIR / "materials"' in build_script
    assert 'target_seed_path = MATERIALS_RES_DIR / "lumina-materials-seed.zip"' in build_script


def test_desktop_build_checks_default_glb_v2_dependencies_before_pyinstaller() -> None:
    build_script = (ROOT / "scripts" / "build_desktop.py").read_text(encoding="utf-8")

    assert "GLB_V2_REQUIRED_MODULES" in build_script
    assert "rasterio.features" in build_script
    assert "manifold3d" in build_script

    deps_index = build_script.index("check_glb_v2_dependencies_available()")
    pyinstaller_index = build_script.index("pyinstaller lumina_studio.spec")
    assert deps_index < pyinstaller_index


def test_electron_build_packages_workshop_security_boundary() -> None:
    package_json = json.loads(
        (ROOT / "electron" / "package.json").read_text(encoding="utf-8")
    )

    assert "workshop-security.cjs" in package_json["build"]["files"]


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
