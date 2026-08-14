from __future__ import annotations

from pathlib import Path

from tools.machine_adapter.resolver import (
    resolve_machine_model_settings,
    resolve_machine_profiles,
)


def test_resolver_expands_inherits_and_includes():
    root = Path("tests/fixtures/machine_adapter")

    profiles = resolve_machine_profiles(root=root, vendor_key="BBL")

    assert len(profiles) == 1
    profile = profiles[0]
    assert profile.name == "Bambu Lab H2D 0.4 nozzle"
    assert profile.settings["printer_model"] == "Bambu Lab H2D"
    assert profile.settings["printable_height"] == "325"
    assert profile.settings["machine_start_gcode"] == "G28 ; home"
    assert profile.source_files
    assert all(item.sha256 for item in profile.source_files)


def test_resolver_reads_machine_model_capability_metadata(tmp_path):
    machine_dir = tmp_path / "Elegoo" / "machine" / "ECC2"
    machine_dir.mkdir(parents=True)
    (machine_dir / "Elegoo Centauri Carbon 2.json").write_text(
        """{
          "type": "machine_model",
          "name": "Elegoo Centauri Carbon 2",
          "not_support_bed_type": "Smooth High Temp Plate;Engineering Plate"
        }""",
        encoding="utf-8",
    )

    settings = resolve_machine_model_settings(
        root=tmp_path,
        vendor_key="Elegoo",
        printer_model="Elegoo Centauri Carbon 2",
    )

    assert settings["not_support_bed_type"] == (
        "Smooth High Temp Plate;Engineering Plate"
    )
