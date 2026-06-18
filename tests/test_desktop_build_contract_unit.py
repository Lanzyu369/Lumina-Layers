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


def test_desktop_build_copies_material_seed_to_packaged_resource_directory() -> None:
    build_script = (ROOT / "scripts" / "build_desktop.py").read_text(encoding="utf-8")

    assert 'MATERIALS_RES_DIR = RESOURCES_DIR / "materials"' in build_script
    assert 'target_seed_path = MATERIALS_RES_DIR / "lumina-materials-seed.zip"' in build_script
