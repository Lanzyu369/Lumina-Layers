from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _registry_root() -> Path:
    return _repo_root() / "machine_registry"


def _load_registry() -> dict[str, Any]:
    path = _registry_root() / "registry.json"
    assert path.exists(), "machine_registry/registry.json must be bundled"
    return json.loads(path.read_text(encoding="utf-8"))


def _slicers_by_id(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    slicers: dict[str, list[dict[str, Any]]] = {}
    for slicer in data["slicers"]:
        slicers.setdefault(str(slicer["slicer_id"]), []).append(slicer)
    return slicers


def _device_ids(data: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for slicer in data["slicers"]:
        for machine in slicer["machines"]:
            for nozzle in machine["nozzles"]:
                ids.add(str(nozzle["device_profile_id"]))
    return ids


def test_bundled_machine_registry_assets_and_templates_exist() -> None:
    root = _registry_root()
    data = _load_registry()
    device_ids: set[str] = set()

    for slicer in data["slicers"]:
        for machine in slicer["machines"]:
            thumbnail = str(machine.get("thumbnail") or "")
            assert thumbnail, f"{machine['display_name']} is missing a thumbnail"
            assert (root / thumbnail).exists(), thumbnail
            for nozzle in machine["nozzles"]:
                device_profile_id = str(nozzle["device_profile_id"])
                assert device_profile_id not in device_ids
                device_ids.add(device_profile_id)
                template_path = root / str(nozzle["template"])
                assert template_path.exists(), str(nozzle["template"])
                template = json.loads(template_path.read_text(encoding="utf-8"))
                assert template.get("printer_model") == machine["display_name"]
                assert str(nozzle["nozzle_size"]) in str(template.get("printer_settings_id", ""))


def test_bundled_machine_registry_keeps_upgraded_ac_and_elegoo_versions() -> None:
    slicers = _slicers_by_id(_load_registry())

    anycubic = slicers["AnycubicSlicerNext"][0]
    assert anycubic["source_version"] == "1.3.2605.22"
    assert anycubic["application_metadata"] == "AnycubicSlicerNext-1.4.1.2"
    assert anycubic["client_version"] == "1.4.1.2 20260604104233"

    elegoo = slicers["ElegooSlicer"][0]
    assert elegoo["source_version"] == "01.05.01.06"
    assert elegoo["application_metadata"] == "ElegooSlicer-01.05.01.06"

    flash_studio = slicers["FlashStudio"][0]
    assert flash_studio["source_version"] == "02.01.01.00"
    assert flash_studio["application_metadata"] == "BambuStudio-2.3.2"
    assert flash_studio["client_version"] == ""
    assert flash_studio["sidecar_policy"] == "orca_like"
    assert {
        machine["display_name"]: [nozzle["nozzle_size"] for nozzle in machine["nozzles"]]
        for machine in flash_studio["machines"]
    } == {
        "Flashforge AD5X": ["0.25", "0.4"],
        "Flashforge Creator 5": ["0.25", "0.4"],
        "Flashforge Creator 5 Pro": ["0.25", "0.4"],
        "Flashforge Guider 3 Ultra": ["0.4"],
        "Flashforge Guider4": ["0.25", "0.4"],
        "Flashforge Guider4 Pro": ["0.25", "0.4"],
    }


def test_bundled_machine_registry_contains_acceptance_profiles() -> None:
    ids = _device_ids(_load_registry())

    assert {
        "AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.4",
        "ElegooSlicer:elegoo:elegoo-centauri-carbon-2:0.4",
        "BambuStudio:bbl:bambu-lab-h2d:0.2",
        "BambuStudio:bbl:bambu-lab-h2d:0.4",
        "BambuStudio:bbl:bambu-lab-x2d:0.4",
        "BambuStudio:bbl:bambu-lab-a2l:0.4",
        "SnapmakerOrca:snapmaker:snapmaker-u1:0.4",
        "FlashStudio:flashforge:flashforge-ad5x:0.25",
        "FlashStudio:flashforge:flashforge-ad5x:0.4",
        "FlashStudio:flashforge:flashforge-creator-5:0.4",
        "FlashStudio:flashforge:flashforge-creator-5-pro:0.25",
        "FlashStudio:flashforge:flashforge-guider-3-ultra:0.4",
        "FlashStudio:flashforge:flashforge-guider4:0.4",
        "FlashStudio:flashforge:flashforge-guider4-pro:0.25",
    } <= ids
