"""The exported project must supply native identities used by startup G-code."""

import json
from pathlib import Path
import zipfile

import trimesh

from utils.bambu_3mf_writer import BambuStudio3MFWriter


def test_a2l_export_retains_native_ids_in_material_order(tmp_path: Path) -> None:
    output = tmp_path / "a2l-native-identities.3mf"
    writer = BambuStudio3MFWriter(
        str(output), printer_id="bambu-lab-a2l", slicer="BambuStudio",
        nozzle_size="0.4", device_profile_id="BambuStudio:bbl:bambu-lab-a2l:0.4",
        build_plate_id="smooth-pei-plate",
        native_filament_profiles={
            "Matte Red": "Bambu PLA Matte @BBL A2L 0.4 nozzle",
            "Basic White": "Bambu PLA Basic @BBL A2L 0.4 nozzle",
        },
    )
    for index, (name, colour) in enumerate([
        ("Matte Red", (220, 20, 30)), ("Basic White", (240, 240, 240)),
    ]):
        mesh = trimesh.creation.box(extents=(4, 4, 1))
        mesh.apply_translation((index * 4, 0, 0.5))
        writer.add_mesh(mesh, name, colour)

    writer.export()

    with zipfile.ZipFile(output) as archive:
        project = json.loads(archive.read("Metadata/project_settings.config"))
    assert "filament_ids[initial_filament_id]" in project["machine_start_gcode"]
    assert project["filament_ids"] == ["GFA01", "GFA00"]
    assert project["filament_colour"] == ["#DC141E", "#F0F0F0"]
    assert project["filament_settings_id"] == [
        "Bambu PLA Matte @BBL A2L 0.4 nozzle",
        "Bambu PLA Basic @BBL A2L 0.4 nozzle",
    ]
