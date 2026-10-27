"""Business selections stay in Lumina; compact array formatting moves to C++."""

from pathlib import Path
import json

import pytest
import trimesh

from utils.bambu_3mf_writer import BambuStudio3MFWriter
from utils.fatcat_metadata import (
    build_project_settings_request,
    compose_builtin_project_settings,
    select_metadata_target,
)


def _writer(tmp_path: Path, *, machine="p1s", nozzle="0.2", policy=False):
    writer = BambuStudio3MFWriter(
        str(tmp_path / "compact.3mf"), printer_id=f"bambu-{machine}",
        slicer="BambuStudio", nozzle_size=nozzle,
        device_profile_id=f"BambuStudio:bbl:bambu-lab-{machine}:{nozzle}",
        build_plate_id="textured-pei-plate", preserve_template_filament_slots=policy,
        enable_wipe_tower_auto_placement=False,
    )
    writer.add_mesh(trimesh.creation.box(extents=(4, 4, 1.2)), "White", (240, 240, 240))
    return writer


def _target(writer):
    target = select_metadata_target(
        slicer=writer.slicer, printer_id=writer.printer_id,
        nozzle_size=writer.nozzle_size, device_profile_id=writer.device_profile_id,
        build_plate_id=writer.build_plate_id,
    )
    assert target is not None
    return target


def test_adapter_transmits_compact_intent_without_generating_material_arrays(tmp_path):
    writer = _writer(tmp_path)
    request = build_project_settings_request(
        writer.settings, ["#123456", "#ABCDEF"], target=_target(writer),
        filament_slot_mode="compact", default_filament_source_slot=1,
        filament_source_slots=[None, 0], disable_cut_retraction=True,
    )
    assert request["material_mode"] == "preserve_template"
    assert request["filament_slot_mode"] == "compact"
    assert request["default_filament_source_slot"] == 1
    assert request["filament_source_slots"] == [None, 0]
    assert request["disable_cut_retraction"] is True
    assert "filament_settings_id" not in request
    assert "nozzle_temperature" not in request
    assert "filament_retraction_length" not in request


@pytest.mark.parametrize("policy,count,mode", [
    (None, 4, "auto"), (None, 8, "auto"),
    (True, 8, "preserve"), (False, 4, "compact"),
])
def test_writer_keeps_existing_slot_policy_as_explicit_request(tmp_path, policy, count, mode):
    writer = _writer(tmp_path, machine="a1-mini", nozzle="0.4", policy=policy)
    palette = [(f"Slot {i}", (10, 20, 30)) for i in range(count)]
    request = writer._build_fatcat_project_request(palette, _target(writer))
    assert request["filament_slot_mode"] == mode
    assert not request.get("disable_cut_retraction", False)
    assert len(request["source_materials"]) == count
    final = json.loads(compose_builtin_project_settings(request)["project_settings_json"])
    assert len(final["filament_colour"]) == count


@pytest.mark.parametrize("policy", [True, False])
def test_real_mixed_template_selects_each_native_kind_not_source_parameters(tmp_path, policy):
    writer = _writer(tmp_path, policy=policy)
    base = writer._get_base_config_template()
    request = writer._build_fatcat_project_request(
        [("White", (240, 240, 240)), ("PETG Black", (10, 10, 10))], _target(writer),
    )
    assert request is not None
    assert request["project_source"] == "fatcat_native"
    assert "preserve_source_material_settings" not in request
    final = json.loads(compose_builtin_project_settings(request)["project_settings_json"])
    assert final["filament_type"][:2] == ["PLA", "PETG"]
    assert "filament_source_slots" not in request
    assert base["filament_type"] == ["PLA"]


@pytest.mark.parametrize("policy", [True, False])
def test_petg_without_a_template_source_still_requests_exact_native_petg(tmp_path, policy):
    writer = _writer(tmp_path, machine="a1-mini", nozzle="0.4", policy=policy)
    base = writer._get_base_config_template()
    assert set(base["filament_type"]) == {"PLA"}
    request = writer._build_fatcat_project_request([("PETG Black", (10, 10, 10))], _target(writer))
    final = json.loads(compose_builtin_project_settings(request)["project_settings_json"])
    assert final["filament_type"][0] == "PETG"
    assert writer._build_fatcat_project_request([("White", (240, 240, 240))], _target(writer)) is not None
