"""Existing runtime hardware and slot policies decide the B7 route."""

from pathlib import Path
import json

import pytest
import trimesh

from core.machine_registry import load_machine_registry, resolve_machine_registry_root
from utils.bambu_3mf_writer import BambuStudio3MFWriter
from utils.fatcat_metadata import compose_builtin_project_settings, select_metadata_target


def _devices():
    registry = load_machine_registry(resolve_machine_registry_root() / "registry.json")
    return [d for d in registry.devices_by_id.values() if d.machine_profile_id in {
        f"{s}:bbl:bambu-lab-{m}" for s in ("BambuStudio", "OrcaSlicer")
        for m in ("a1-mini", "a1", "p1s")
    }]


@pytest.mark.parametrize("device", _devices(), ids=lambda d: d.device_profile_id)
def test_every_existing_device_and_plate_delegates_hardware_selection(device):
    machine = device.machine_profile_id.split(":bbl:bambu-lab-")[1]
    for plate in device.build_plates:
        target = select_metadata_target(
            slicer=device.slicer_id, printer_id=f"bambu-{machine}",
            nozzle_size=device.nozzle_size, device_profile_id=device.device_profile_id,
            build_plate_id=plate.id,
        )
        assert target is not None, (device.device_profile_id, plate.id)
        assert target.hardware_mode == "preserve_source"
        assert target.machine_uid == f"bambu-lab:{machine}"
        assert target.nozzle_uid == f"nozzle:{device.nozzle_size}mm"
        assert target.build_plate_uid.startswith("plate:")


@pytest.mark.parametrize("policy,active_count,migrated", [(False, 4, True), (None, 8, True), (None, 4, True), (True, 8, True)])
def test_full_slot_and_compact_routes_are_explicit(tmp_path: Path, policy, active_count, migrated):
    writer = BambuStudio3MFWriter(
        str(tmp_path / "slots.3mf"), printer_id="bambu-a1-mini", slicer="OrcaSlicer",
        nozzle_size="0.4", device_profile_id="OrcaSlicer:bbl:bambu-lab-a1-mini:0.4",
        build_plate_id="textured-pei-plate", preserve_template_filament_slots=policy,
    )
    target = writer._select_metadata_target()
    assert (target is not None) is migrated


def test_selected_non_default_plate_prepares_the_same_project_for_both_routes(tmp_path: Path):
    writer = BambuStudio3MFWriter(
        str(tmp_path / "smooth.3mf"), printer_id="bambu-a1-mini", slicer="BambuStudio",
        nozzle_size="0.2", device_profile_id="BambuStudio:bbl:bambu-lab-a1-mini:0.2",
        build_plate_id="smooth-pei-plate",
    )
    writer.add_mesh(trimesh.creation.box(extents=(4, 4, 1.2)), "White", (255, 255, 255))
    request = writer._build_fatcat_project_request([("White", (255, 255, 255))], writer._select_metadata_target())
    final = json.loads(compose_builtin_project_settings(request)["project_settings_json"])
    assert final["curr_bed_type"] == "High Temp Plate"
