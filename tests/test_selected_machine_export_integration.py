"""Export real 3MFs without depending on other machines' source files."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import zipfile
import xml.etree.ElementTree as ET

import fatcat_metadata as fatcat
import pytest
import trimesh

from utils.bambu_3mf_writer import BambuStudio3MFWriter
from utils.fatcat_metadata import native_project_source_catalog


@pytest.mark.parametrize("machine", ["p2s", "x2d"])
def test_export_with_unrelated_machine_sources_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, machine: str,
) -> None:
    package = Path(fatcat.__file__).parent
    shutil.copytree(package / "fatcat_metadata_data", tmp_path / "fatcat_metadata_data")
    monkeypatch.setattr(fatcat, "__file__", str(tmp_path / Path(fatcat.__file__).name))
    native_project_source_catalog.cache_clear()
    sources = tmp_path / "fatcat_metadata_data/native_project_sources/profiles/BambuStudio/BBL/machine"
    for name in ("Bambu Lab H2D Pro 0.4 nozzle template wrapping_detection_gcode.json",
                 "Bambu Lab A1 mini 0.4 nozzle template machine_start_gcode.json"):
        (sources / name).unlink()
    output = tmp_path / f"{machine}.3mf"
    writer = BambuStudio3MFWriter(
        str(output), printer_id="bambu-p2s" if machine == "p2s" else "bambu-lab-x2d",
        slicer="BambuStudio",
        nozzle_size="0.4", device_profile_id=f"BambuStudio:bbl:bambu-lab-{machine}:0.4",
        build_plate_id="textured-pei-plate", watermark="",
    )
    writer.add_mesh(trimesh.creation.box(extents=(10, 10, 1)), "PLA red", (255, 0, 0))
    second = trimesh.creation.box(extents=(10, 10, 1))
    second.apply_translation((12, 0, 0))
    writer.add_mesh(second, "PLA blue", (0, 0, 255))
    assert writer.export() == str(output)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        settings = json.loads(archive.read("Metadata/project_settings.config"))
        assert settings["printer_settings_id"] == f"Bambu Lab {machine.upper()} 0.4 nozzle"
        assert settings["printer_model"] == f"Bambu Lab {machine.upper()}"
        assert settings["nozzle_diameter"] == ["0.4"] * (2 if machine == "x2d" else 1)
        assert len(settings["machine_start_gcode"]) > 100
        assert {"#FF0000", "#0000FF"}.issubset(settings["filament_colour"])
        models = [ET.fromstring(archive.read(name)) for name in archive.namelist()
                  if name.startswith("3D/") and name.endswith(".model")]
        assert sum(len(model.findall(".//{*}triangle")) for model in models) >= 24
    native_project_source_catalog.cache_clear()
