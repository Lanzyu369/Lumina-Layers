"""Finite B7 matrix uses the actual runtime templates and installed C++ wheel."""

import json
import math
import os
from pathlib import Path
from zipfile import ZipFile

import pytest
import trimesh

from core.machine_registry import load_machine_registry, resolve_machine_registry_root
from utils.bambu_3mf_writer import BambuStudio3MFWriter
from utils.fatcat_metadata import compose_builtin_project_settings
from fatcat_material_assertions import assert_native_materials, native_materials_support_plate
from fatcat_native_source_fixtures import complete_native_project, assert_source_material_snapshot

pytestmark = pytest.mark.skipif(os.environ.get("FATCAT_B4_INTEGRATION") != "1", reason="installed native dependencies required")


def _matrix():
    registry = load_machine_registry(resolve_machine_registry_root() / "registry.json")
    selected = {f"{s}:bbl:bambu-lab-{m}" for s in ("BambuStudio", "OrcaSlicer") for m in ("a1-mini", "a1", "p1s")}
    return [(d, p) for d in registry.devices_by_id.values() if d.machine_profile_id in selected for p in d.build_plates]


@pytest.mark.parametrize("device,plate", _matrix(), ids=[f"{d.device_profile_id}/{p.id}" for d, p in _matrix()])
def test_native_source_preserves_selected_materials_and_selected_plate(tmp_path: Path, device, plate):
    machine = device.machine_profile_id.split(":bbl:bambu-lab-")[1]
    writer = BambuStudio3MFWriter(
        str(tmp_path / "matrix.3mf"), printer_id=f"bambu-{machine}",
        slicer=device.slicer_id, nozzle_size=device.nozzle_size,
        device_profile_id=device.device_profile_id, build_plate_id=plate.id,
        preserve_template_filament_slots=True,
    )
    palette = [("PLA", (18, 52, 86)), ("PLA Blue", (171, 205, 239))]
    for index, (name, colour) in enumerate(palette):
        mesh = trimesh.creation.box(extents=(6.0, 6.0, 1.2))
        mesh.apply_translation((index * 8.0, 0.0, 0.6))
        writer.add_mesh(mesh, name, colour)
    target = writer._select_metadata_target()
    assert target is not None
    request = writer._build_fatcat_project_request(palette, target)
    supported = native_materials_support_plate(slicer_id=device.slicer_id,
        machine_uid=f"bambu-lab:{machine}", nozzle_uid=f"nozzle:{device.nozzle_size}mm",
        material_types=["PLA"] * 2, plate_value=plate.project_value)
    if not supported:
        with pytest.raises(ValueError, match="no available native filament profile"):
            compose_builtin_project_settings(request)
    else:
        result = compose_builtin_project_settings(request)
        final = json.loads(result["project_settings_json"])
        slots = len(final["filament_settings_id"])
        assert request["filament_slot_mode"] == "preserve"
        assert slots == len(palette)
        for key in ("printer_model", "printer_settings_id", "nozzle_diameter", "printable_area", "printable_height"):
            assert key in final, key
        assert final["curr_bed_type"] == plate.project_value
        assert final["filament_colour"][:2] == ["#123456", "#ABCDEF"]
        assert len(final["filament_settings_id"]) == slots
        assert len(final["filament_type"]) == slots
        assert_native_materials(
            final, slicer_id=device.slicer_id, machine_uid=f"bambu-lab:{machine}",
            nozzle_uid=f"nozzle:{device.nozzle_size}mm", material_types=["PLA"] * slots,
        )
        for key in ("layer_height", "initial_layer_height", "initial_layer_print_height"):
            if key in result["effective_settings"]:
                assert result["effective_settings"][key] == final[key]
        assert final["print_compatible_printers"] == [final["printer_settings_id"]]

    # Assemble genuine materials on their supported textured plate and retain
    # the saved plate selection with PETG only in the inactive tail. Native active
    # palette coverage above must not replace preservation of imported tails.
    source = complete_native_project(writer, ["PLA"] * 7 + ["PETG"], material_plate_uid="plate:textured-pei")
    source["curr_bed_type"] = plate.project_value
    source["unmanaged_vendor_array"] = ["opaque3", "opaque1"]
    writer._custom_template = source
    writer._set_project_palette([name for name, _ in palette], dict(palette))
    writer.export()
    with ZipFile(writer.output_path) as package:
        preserved = json.loads(package.read("Metadata/project_settings.config"))
    assert_source_material_snapshot(preserved, source, slicer=device.slicer_id, output_slots=8)
    assert preserved["filament_colour"] == ["#123456", "#ABCDEF"] + source["filament_colour"][2:]
    assert preserved["filament_type"][2:] == ["PLA"] * 5 + ["PETG"]
    assert preserved["unmanaged_vendor_array"] == source["unmanaged_vendor_array"]
    assert preserved["curr_bed_type"] == plate.project_value


@pytest.mark.parametrize("device,plate", _matrix(), ids=[f"{d.device_profile_id}/{p.id}" for d, p in _matrix()])
def test_native_source_compacts_four_materials_and_selected_plate(tmp_path: Path, device, plate):
    machine = device.machine_profile_id.split(":bbl:bambu-lab-")[1]
    writer = BambuStudio3MFWriter(
        str(tmp_path / "compact-matrix.3mf"), printer_id=f"bambu-{machine}",
        slicer=device.slicer_id, nozzle_size=device.nozzle_size,
        device_profile_id=device.device_profile_id, build_plate_id=plate.id,
        preserve_template_filament_slots=False,
    )
    writer.add_mesh(trimesh.creation.box(extents=(6.0, 6.0, 1.2)), "PLA", (18, 52, 86))
    target = writer._select_metadata_target()
    assert target is not None
    palette = [(f"Slot {i}", (10 + i, 20, 30)) for i in range(4)]
    request = writer._build_fatcat_project_request(palette, target)
    assert request["filament_slot_mode"] == "compact"
    supported = native_materials_support_plate(slicer_id=device.slicer_id,
        machine_uid=f"bambu-lab:{machine}", nozzle_uid=f"nozzle:{device.nozzle_size}mm",
        material_types=["PLA"] * 4, plate_value=plate.project_value)
    if not supported:
        with pytest.raises(ValueError, match="no available native filament profile"):
            compose_builtin_project_settings(request)
    else:
        source = writer._get_base_config_template()
        source_matrix = source.get("flush_volumes_matrix") or None
        source_count = math.isqrt(len(source_matrix)) if source_matrix is not None else 0
        if source_matrix is not None:
            assert source_count * source_count == len(source_matrix)
        result = compose_builtin_project_settings(request)
        final = json.loads(result["project_settings_json"])
        assert_native_materials(final, slicer_id=device.slicer_id, machine_uid=f"bambu-lab:{machine}",
                                nozzle_uid=f"nozzle:{device.nozzle_size}mm", material_types=["PLA"] * 4)
        assert final["filament_colour"] == [f"#{10 + i:02X}141E" for i in range(4)]
        assert final["filament_multi_colour"] == final["filament_colour"]
        if source_matrix is not None:
            assert final["flush_volumes_matrix"] == [
                source_matrix[row * source_count + column]
                for row in range(4) for column in range(4)
            ]
        else:
            assert "flush_volumes_matrix" not in final
        assert len(final["different_settings_to_system"]) == 1
        for key in ("printer_settings_id", "nozzle_diameter", "printable_area", "printable_height"):
            assert key in final, key
        assert final["curr_bed_type"] == plate.project_value

    # Exercise the writer's custom-source compact path as well as its native
    # source path. Only declared slot arrays/matrices may be truncated.
    full_source = complete_native_project(writer, ["PLA"] * 7 + ["PETG"], material_plate_uid="plate:textured-pei")
    full_source["curr_bed_type"] = plate.project_value
    full_source["unknown_compact_values"] = [f"opaque{i}" for i in range(16)]
    full_source["flush_volumes_matrix"] = [str(i) for i in range(64)]
    writer._custom_template = full_source
    writer.objects.clear()
    writer._set_project_palette([name for name, _ in palette], dict(palette))
    for index, (name, colour) in enumerate(palette):
        mesh = trimesh.creation.box(extents=(6.0, 6.0, 1.2))
        mesh.apply_translation((index * 8.0, 0.0, 0.6))
        writer.add_mesh(mesh, name, colour)
    writer.export()
    with ZipFile(writer.output_path) as package:
        compact = json.loads(package.read("Metadata/project_settings.config"))
    assert_source_material_snapshot(compact, full_source, slicer=device.slicer_id, output_slots=4)
    assert compact["filament_colour"] == [f"#{10 + i:02X}141E" for i in range(4)]
    assert compact["flush_volumes_matrix"] == [str(row * 8 + column) for row in range(4) for column in range(4)]
    assert compact["unknown_compact_values"] == full_source["unknown_compact_values"]
    assert compact["curr_bed_type"] == plate.project_value
    for key in ("printer_settings_id", "nozzle_diameter", "printable_area", "printable_height",
                "retraction_distances_when_cut"):
        if key in full_source:
            assert compact[key] == full_source[key], key
