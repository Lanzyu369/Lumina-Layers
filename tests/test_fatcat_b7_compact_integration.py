"""Actual compact writer output, including mixed-source and >template palettes."""

import json
from zipfile import ZipFile

import pytest

from fatcat_writer_cases import CASES, make_writer
import utils.bambu_3mf_writer as writer_module
from fatcat_material_assertions import assert_native_materials



@pytest.mark.parametrize("case", CASES)
def test_real_compact_writer_uses_each_native_material_and_no_legacy(tmp_path, monkeypatch, case):
    output = tmp_path / f"{case}.3mf"
    writer, source, _ = make_writer(output, case)


    writer.export()
    with ZipFile(output) as package:
        final = json.loads(package.read("Metadata/project_settings.config"))
    slicer, machine, nozzle, material_types = {
        "bambu-p1s-02-mixed2": ("BambuStudio", "p1s", "0.2", ["PLA", "PETG"]),
        "orca-p1s-06-mixed2": ("OrcaSlicer", "p1s", "0.6", ["PLA", "PETG"]),
        "orca-p1s-06-distinct2": ("OrcaSlicer", "p1s", "0.6", ["PLA"] * 2),
        "bambu-a1mini-04-expanded10": ("BambuStudio", "a1-mini", "0.4", ["PLA"] * 10),
    }[case]
    assert_native_materials(final, slicer_id=slicer, machine_uid=f"bambu-lab:{machine}",
                            nozzle_uid=f"nozzle:{nozzle}mm", material_types=material_types,
                            skip_material_keys=(
                                ("filament_flow_ratio", "filament_retraction_length", "nozzle_temperature",
                                 "nozzle_temperature_initial_layer")
                                if case == "orca-p1s-06-distinct2" else ()
                            ))
    if case == "bambu-p1s-02-mixed2":
        assert final["filament_type"] == ["PLA", "PETG"]
        assert final["nozzle_temperature"] == ["220", "220", "255", "255"]
        assert final["filament_flow_ratio"][:2] == ["0.98", "0.98"]
        assert final["filament_max_volumetric_speed"][:2] == ["2", "2"]
        assert final["filament_self_index"] == ["1", "1", "2", "2"]
        # Native values replace stale PETG-source tuning, rather than retaining
        # those values under a newly selected PLA name.
        overrides = set(";".join(final["different_settings_to_system"]).split(";"))
        assert not {"filament_flow_ratio", "filament_max_volumetric_speed"} & overrides
    elif case == "orca-p1s-06-distinct2":
        # These four explicit source overrides are excluded from the native
        # comparison above and checked independently, including initial heat.
        for key in ("filament_flow_ratio", "filament_retraction_length", "nozzle_temperature",
                    "nozzle_temperature_initial_layer"):
            assert final[key] == source[key], key
        assert len(final["different_settings_to_system"]) == 4
    elif case == "bambu-a1mini-04-expanded10":
        assert len(final["filament_settings_id"]) == 10
        assert len(final["filament_colour"]) == 10
        if "flush_volumes_matrix" in source:
            assert final["flush_volumes_matrix"] == source["flush_volumes_matrix"]
        else:
            assert "flush_volumes_matrix" not in final
    if case != "orca-p1s-06-distinct2":
        assert len(final["different_settings_to_system"]) == 1


@pytest.mark.parametrize("active_count", [16, 32])
def test_compact_palette_size_does_not_confuse_source_group_width(tmp_path, monkeypatch, active_count):
    writer, source, _ = make_writer(tmp_path / "expanded.3mf", "bambu-a1mini-04-expanded10")
    names = [f"Material {index + 1}" for index in range(active_count)]
    writer._set_project_palette(names, {name: (120, 30, 40) for name in names})
    writer.enable_wipe_tower_auto_placement = False


    writer.export()
    with ZipFile(writer.output_path) as package:
        final = json.loads(package.read("Metadata/project_settings.config"))
    assert len(final["filament_settings_id"]) == active_count
    assert len(final["different_settings_to_system"]) == 1
    # The approved A1 first-variant rule has one effective variant per slot.
    assert final["filament_self_index"] == [str(slot + 1) for slot in range(active_count)]
    if "flush_volumes_matrix" in source:
        assert final["flush_volumes_matrix"] == source["flush_volumes_matrix"]
    else:
        assert "flush_volumes_matrix" not in final


def test_compact_cpp_failure_is_not_retried_through_legacy(tmp_path, monkeypatch):
    writer, _, _ = make_writer(tmp_path / "failure.3mf", "bambu-a1mini-04-expanded10")

    def fail_cpp(*_args, **_kwargs):
        raise RuntimeError("installed compact composer failed")


    monkeypatch.setattr(writer_module, "compose_builtin_project_settings", fail_cpp)
    with pytest.raises(RuntimeError, match="installed compact composer failed"):
        writer.export()


def test_petg_without_a_source_slot_does_not_use_generic_fallback(tmp_path, monkeypatch):
    writer, source, _ = make_writer(tmp_path / "native-petg.3mf", "bambu-a1mini-04-expanded10")
    writer.objects.clear()
    writer._set_project_palette(["PETG Black"], {"PETG Black": (10, 10, 10)})
    import trimesh
    writer.add_mesh(trimesh.creation.box(extents=(4, 4, 1.2)), "PETG Black", (10, 10, 10))


    writer.export()
    with ZipFile(writer.output_path) as package:
        final = json.loads(package.read("Metadata/project_settings.config"))
    assert final["filament_type"] == ["PETG"]
    assert_native_materials(final, slicer_id="BambuStudio", machine_uid="bambu-lab:a1-mini",
                            nozzle_uid="nozzle:0.4mm", material_types=["PETG"])
