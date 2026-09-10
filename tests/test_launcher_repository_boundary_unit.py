"""Protect the distinction between managed interfaces and launcher ownership."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_studio_retains_loadable_managed_runtime_contract() -> None:
    package = json.loads((ROOT / "electron/package.json").read_text(encoding="utf-8"))
    for name in ("managed-runtime.cjs", "managed-startup.cjs"):
        assert name in package["build"]["files"]
        assert (ROOT / "electron" / name).is_file()
    assert {"from": "launcher-startup.json", "to": "launcher-startup.json"} in package["build"]["extraResources"]
    assert json.loads((ROOT / "electron/launcher-startup.json").read_text(encoding="utf-8")) == {"protocol": 1}


def test_launcher_and_official_distribution_have_explicit_private_owners() -> None:
    ownership = (ROOT / "docs/launcher-repository.md").read_text(encoding="utf-8")
    for repository in ("Lumina-Launcher", "Lumina-Distribution"):
        assert f"https://github.com/lumina-layer-studio/{repository}" in ownership
    for folder in ("frontend", "electron"):
        package = json.loads((ROOT / folder / "package.json").read_text(encoding="utf-8"))
        assert not any("launcher" in name for name in package["scripts"])
    for entry in ("launcher/Cargo.toml", "frontend/src/launcher", "electron/launcher-main.cjs"):
        assert not (ROOT / entry).exists()
