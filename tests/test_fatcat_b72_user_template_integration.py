"""Native-saved user tuning crosses the real persistent-template boundary."""

from io import BytesIO
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pytest
import trimesh

from core import custom_3mf_templates
import utils.bambu_3mf_writer as writer_module

pytestmark = pytest.mark.skipif(os.environ.get("FATCAT_B4_INTEGRATION") != "1", reason="installed native dependencies required")
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "fatcat"
SOURCE = FIXTURES / "bambu-p1s-02-user-tuned-native-template.3mf"


@pytest.mark.parametrize("policy,count", [(None, 2), (False, 2), (False, 1)])
def test_native_saved_template_keeps_real_tuning_and_routes_new_geometry(tmp_path, monkeypatch, policy, count):
    monkeypatch.setattr(custom_3mf_templates, "_root", lambda: tmp_path / "stored-templates")
    template = custom_3mf_templates.import_template(SOURCE.read_bytes(), "Bambu GUI tuned material")
    with ZipFile(SOURCE) as package:
        original = json.loads(package.read("Metadata/project_settings.config"))
    assert original["nozzle_temperature_initial_layer"][:2] == ["217", "220"]
    assert original["nozzle_temperature"][:2] == ["213", "220"]
    assert original["filament_flow_ratio"][:2] == ["0.93", "0.95"]
    assert original["filament_retraction_length"][:2] == ["0.61", "0.72"]

    output = tmp_path / "new-geometry.3mf"
    writer = writer_module.BambuStudio3MFWriter(
        str(output), printer_id="bambu-p1s", slicer="BambuStudio", nozzle_size="0.2",
        device_profile_id="BambuStudio:bbl:bambu-lab-p1s:0.2", build_plate_id="textured-pei-plate",
        custom_3mf_template_id=template["id"], preserve_template_filament_slots=policy,
        settings={"layer_height": "0.12", "initial_layer_print_height": "0.20"},
        enable_base_layer_height_modifier=False, enable_wipe_tower_auto_placement=False,
    )
    palette = [("White", (230, 240, 250)), ("PETG Black", (10, 20, 30))][:count]
    for name, colour in palette:
        writer.add_mesh(trimesh.creation.box(extents=(6, 5, 1.2)), name, colour)


    composer = writer_module.compose_project_settings
    requests = []

    def capture(source, request):
        requests.append(request)
        return composer(source, request)

    monkeypatch.setattr(writer_module, "compose_project_settings", capture)
    writer.export()
    assert len(requests) == 1
    assert requests[0]["material_mode"] == "preserve_template"
    assert requests[0]["preserve_source_material_settings"] is True
    assert "material_uids" not in requests[0]
    with ZipFile(output) as package:
        final = json.loads(package.read("Metadata/project_settings.config"))
        model = package.read("Metadata/model_settings.config").decode("utf-8")
    slots = 2 if policy is None else count
    for key in ("nozzle_temperature", "nozzle_temperature_initial_layer", "filament_flow_ratio", "filament_retraction_length"):
        assert final[key] == original[key][:slots * 2], key
    for key in ("filament_type", "filament_settings_id"):
        assert final[key] == original[key][:slots], key
    assert final["filament_self_index"] == [str(i + 1) for i in range(slots) for _ in range(2)]
    assert final["print_settings_id"] == original["print_settings_id"]
    assert final["outer_wall_speed"] == original["outer_wall_speed"]
    assert final["filament_colour"][:count] == ["#E6F0FA", "#0A141E"][:count]
    assert len(final["different_settings_to_system"]) == slots + 2
    assert "filament_retraction_length" in final["different_settings_to_system"][1].split(";")
    assert model.count('key="extruder"') >= count
    assert not any(key.startswith("_lumina_template_") for key in final)


@pytest.mark.parametrize("selected_plate,expected,sidecar", [
    (None, "High Temp Plate", "hot_plate"),
    ("smooth-pei-plate", "High Temp Plate", "hot_plate"),
    ("textured-pei-plate", "Textured PEI Plate", "textured_plate"),
])
def test_imported_native_plate_override_survives_unless_explicitly_reselected(
    tmp_path, monkeypatch, selected_plate, expected, sidecar,
):
    source = FIXTURES / "bambu-a1mini-02-smooth-native-sliced.3mf"
    monkeypatch.setattr(custom_3mf_templates, "_root", lambda: tmp_path / "stored-templates")
    record = custom_3mf_templates.import_template(source.read_bytes(), "Native smooth plate")
    loaded = custom_3mf_templates.load_template(record["id"])
    assert loaded["curr_bed_type"] == "Textured PEI Plate"
    assert loaded["_lumina_template_plate_value"] == "High Temp Plate"
    assert loaded["_lumina_template_sidecar_bed"] == "hot_plate"
    output = tmp_path / "native-plate.3mf"
    writer = writer_module.BambuStudio3MFWriter(
        str(output), printer_id="bambu-a1-mini", slicer="BambuStudio", nozzle_size="0.2",
        device_profile_id="BambuStudio:bbl:bambu-lab-a1-mini:0.2",
        build_plate_id=selected_plate, custom_3mf_template_id=record["id"],
        enable_base_layer_height_modifier=False, enable_wipe_tower_auto_placement=False,
    )
    writer.add_mesh(trimesh.creation.box(extents=(6, 5, 1.2)), "White", (230, 240, 250))
    writer.export()
    with ZipFile(output) as package:
        project = json.loads(package.read("Metadata/project_settings.config"))
        model = ET.fromstring(package.read("Metadata/model_settings.config"))
    assert project["curr_bed_type"] == expected
    assert model.find("./plate/metadata[@key='bed_type']").get("value") == expected
    if selected_plate is None:
        assert writer._template_build_plate["sidecar_value"] == sidecar
    for key in ("hot_plate_temp", "textured_plate_temp"):
        assert project[key] == loaded[key]


@pytest.mark.parametrize("policy", [None, True, False])
def test_orca_imported_process_tuning_is_not_an_ordinary_export_default(tmp_path, monkeypatch, policy):
    monkeypatch.setattr(custom_3mf_templates, "_root", lambda: tmp_path / "stored-templates")
    options = dict(
        printer_id="bambu-p1s", slicer="OrcaSlicer", nozzle_size="0.6",
        device_profile_id="OrcaSlicer:bbl:bambu-lab-p1s:0.6",
        build_plate_id="textured-pei-plate", enable_wipe_tower_auto_placement=False,
        enable_base_layer_height_modifier=False,
    )
    source_writer = writer_module.BambuStudio3MFWriter(
        str(tmp_path / "unused.3mf"), **options,
    )
    source_writer.add_mesh(
        trimesh.creation.box(extents=(6, 5, 1.2)), "White", (230, 240, 250)
    )
    source = source_writer._get_base_config_template()
    tuning = {"precise_outer_wall": "1", "outer_wall_speed": "47", "normal_acceleration": "1234"}
    source.update(tuning)
    tokens = set(source["different_settings_to_system"][0].split(";")) | tuning.keys()
    source["different_settings_to_system"][0] = ";".join(sorted(tokens - {""}))
    payload = BytesIO()
    with ZipFile(payload, "w") as package:
        package.writestr("Metadata/project_settings.config", json.dumps(source))
        package.writestr("3D/3dmodel.model", '<model><metadata name="OrcaSlicer">2.4.2</metadata></model>')
    record = custom_3mf_templates.import_template(payload.getvalue(), "Orca process tuning")
    output = tmp_path / "custom-orca.3mf"
    writer = writer_module.BambuStudio3MFWriter(
        str(output), **options, custom_3mf_template_id=record["id"],
        preserve_template_filament_slots=policy,
    )
    writer.add_mesh(trimesh.creation.box(extents=(6, 5, 1.2)), "White", (230, 240, 250))
    writer.export()
    with ZipFile(output) as package:
        final = json.loads(package.read("Metadata/project_settings.config"))
    assert {key: final[key] for key in tuning} == tuning
    assert set(tuning) <= set(final["different_settings_to_system"][0].split(";"))
    slots = 1 if policy is False else len(source["filament_settings_id"])
    assert final["filament_flow_ratio"] == source["filament_flow_ratio"][:slots * 2]
