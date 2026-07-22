from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.machine_adapter.import_profiles import (
    ImportSource,
    _asset_slug,
    _copy_thumbnail_file,
    run_import,
    run_import_sources,
)


def _write_machine_profile(
    machine_dir: Path,
    filename: str,
    payload: dict,
) -> None:
    path = machine_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_copy_thumbnail_file_bounds_oversized_raster_assets(tmp_path):
    from PIL import Image

    source = tmp_path / "source.png"
    destination = tmp_path / "output" / "cover.png"
    Image.new("RGBA", (3000, 2400), (255, 255, 255, 255)).save(source)

    _copy_thumbnail_file(source, destination)

    with Image.open(destination) as image:
        assert image.size == (1000, 800)


def test_run_import_writes_registry_and_templates(tmp_path):
    source_root = Path("tests/fixtures/machine_adapter")
    output_root = tmp_path / "machine_registry"

    result = run_import(
        slicer_id="BambuStudio",
        source_root=source_root,
        source_version="02.07.01.57",
        vendor_keys=("BBL",),
        output_root=output_root,
    )

    assert result.device_count == 1
    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    assert registry["slicers"][0]["slicer_id"] == "BambuStudio"
    machine = registry["slicers"][0]["machines"][0]
    assert machine["thumbnail"] == "slicers/BambuStudio/02.07.01.57/assets/bambu-lab-h2d_cover.png"
    assert (output_root / machine["thumbnail"]).read_bytes() == b"fake-png-bytes-for-machine-adapter-test\n"
    templates = list((output_root / "slicers").rglob("*.json"))
    assert templates
    template = json.loads(templates[0].read_text(encoding="utf-8"))
    assert template["layer_height"] == "0.08"


def test_run_import_filters_by_machine_name(tmp_path):
    source_root = tmp_path / "profiles"
    machine_dir = source_root / "BBL" / "machine"
    machine_dir.mkdir(parents=True)
    (machine_dir / "fdm_common.json").write_text(
        json.dumps(
            {
                "type": "machine",
                "name": "fdm_common",
                "instantiation": "false",
                "printable_height": "325",
                "printable_area": ["0x0", "350x0", "350x320", "0x320"],
            }
        ),
        encoding="utf-8",
    )
    for model in ("Bambu Lab H2D", "Bambu Lab H2D Pro", "Bambu Lab P1S"):
        (machine_dir / f"{model} 0.4 nozzle.json").write_text(
            json.dumps(
                {
                    "type": "machine",
                    "name": f"{model} 0.4 nozzle",
                    "inherits": "fdm_common",
                    "instantiation": "true",
                    "printer_model": model,
                    "printer_variant": "0.4",
                    "nozzle_diameter": ["0.4"],
                }
            ),
            encoding="utf-8",
        )
    output_root = tmp_path / "machine_registry"

    result = run_import(
        slicer_id="BambuStudio",
        source_root=source_root,
        source_version="02.07.01.57",
        vendor_keys=("BBL",),
        output_root=output_root,
        machine_name="Bambu Lab H2D",
    )

    assert result.device_count == 1
    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    assert registry["slicers"][0]["machines"][0]["display_name"] == "Bambu Lab H2D"


def test_run_import_filters_orca_to_multicolor_non_bambu_profiles(tmp_path):
    source_root = tmp_path / "profiles"
    machine_dir = source_root / "Snapmaker" / "machine"
    machine_dir.mkdir(parents=True)
    _write_machine_profile(
        machine_dir,
        "fdm_common.json",
        {
            "type": "machine",
            "name": "fdm_common",
            "instantiation": "false",
            "printable_height": "270",
            "printable_area": ["0x0", "270x0", "270x270", "0x270"],
        },
    )
    _write_machine_profile(
        machine_dir,
        "Snapmaker A250 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "Snapmaker A250 0.4 nozzle",
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Snapmaker A250",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4"],
            "single_extruder_multi_material": "0",
        },
    )
    _write_machine_profile(
        machine_dir,
        "Snapmaker U1 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "Snapmaker U1 0.4 nozzle",
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Snapmaker U1",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4", "0.4", "0.4", "0.4"],
            "single_extruder_multi_material": "0",
        },
    )
    _write_machine_profile(
        machine_dir,
        "Snapmaker U1 0.4+0.6 nozzle.json",
        {
            "type": "machine",
            "name": "Snapmaker U1 0.4+0.6 nozzle",
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Snapmaker U1",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4", "0.6", "0.4", "0.6"],
            "single_extruder_multi_material": "0",
        },
    )
    output_root = tmp_path / "machine_registry"

    result = run_import(
        slicer_id="OrcaSlicer",
        source_root=source_root,
        source_version="02.04.00.00",
        vendor_keys=("Snapmaker",),
        output_root=output_root,
    )

    assert result.device_count == 1
    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    machines = registry["slicers"][0]["machines"]
    assert [machine["display_name"] for machine in machines] == ["Snapmaker U1"]
    assert machines[0]["nozzles"][0]["device_profile_id"] == "OrcaSlicer:snapmaker:snapmaker-u1:0.4"


def test_run_import_indexes_nested_machine_profiles(tmp_path):
    source_root = tmp_path / "profiles"
    machine_dir = source_root / "Elegoo" / "machine"
    _write_machine_profile(
        machine_dir,
        "fdm_common.json",
        {
            "type": "machine",
            "name": "fdm_common",
            "instantiation": "false",
            "printable_height": "256",
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
        },
    )
    _write_machine_profile(
        machine_dir / "ECC2",
        "Elegoo Centauri Carbon 2 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "Elegoo Centauri Carbon 2 0.4 nozzle",
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Elegoo Centauri Carbon 2",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4"],
            "single_extruder_multi_material": "1",
        },
    )
    output_root = tmp_path / "machine_registry"

    result = run_import(
        slicer_id="ElegooSlicer",
        source_root=source_root,
        source_version="01.05.00.07",
        vendor_keys=("Elegoo",),
        output_root=output_root,
    )

    assert result.device_count == 1
    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    assert registry["slicers"][0]["machines"][0]["display_name"] == "Elegoo Centauri Carbon 2"


def test_run_import_accepts_utf8_bom_machine_profiles(tmp_path):
    source_root = tmp_path / "profiles"
    machine_dir = source_root / "Elegoo" / "machine"
    _write_machine_profile(
        machine_dir,
        "fdm_common.json",
        {
            "type": "machine",
            "name": "fdm_common",
            "instantiation": "false",
            "printable_height": "256",
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
        },
    )
    bom_profile = {
        "type": "machine",
        "name": "Elegoo Centauri Carbon 2 0.4 nozzle",
        "inherits": "fdm_common",
        "instantiation": "true",
        "printer_model": "Elegoo Centauri Carbon 2",
        "printer_variant": "0.4",
        "nozzle_diameter": ["0.4"],
        "single_extruder_multi_material": "1",
    }
    path = machine_dir / "Elegoo Centauri Carbon 2 0.4 nozzle.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(bom_profile).encode("utf-8"))
    output_root = tmp_path / "machine_registry"

    result = run_import(
        slicer_id="ElegooSlicer",
        source_root=source_root,
        source_version="01.05.01.06",
        vendor_keys=("Elegoo",),
        output_root=output_root,
    )

    assert result.device_count == 1
    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    assert registry["slicers"][0]["machines"][0]["display_name"] == "Elegoo Centauri Carbon 2"


def test_orca_elegoo_scope_keeps_only_centauri_family(tmp_path):
    source_root = tmp_path / "profiles"
    machine_dir = source_root / "Elegoo" / "machine"
    _write_machine_profile(
        machine_dir,
        "fdm_common.json",
        {
            "type": "machine",
            "name": "fdm_common",
            "instantiation": "false",
            "printable_height": "256",
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
        },
    )
    _write_machine_profile(
        machine_dir,
        "Elegoo Centauri 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "Elegoo Centauri 0.4 nozzle",
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Elegoo Centauri",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4"],
        },
    )
    _write_machine_profile(
        machine_dir,
        "Elegoo Centauri Carbon 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "Elegoo Centauri Carbon 0.4 nozzle",
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Elegoo Centauri Carbon",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4"],
        },
    )
    _write_machine_profile(
        machine_dir,
        "Elegoo Centauri Carbon 2 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "Elegoo Centauri Carbon 2 0.4 nozzle",
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Elegoo Centauri Carbon 2",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4"],
            "extruder_offset": ["0x1.5"],
            "change_filament_gcode": "M6211 T[next_extruder] L[flush_length]",
        },
    )
    _write_machine_profile(
        machine_dir,
        "Elegoo Neptune 4 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "Elegoo Neptune 4 0.4 nozzle",
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Elegoo Neptune 4",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4"],
            "single_extruder_multi_material": "1",
        },
    )
    _write_machine_profile(
        machine_dir,
        "Elegoo Neptune 2D 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "Elegoo Neptune 2D 0.4 nozzle",
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Elegoo Neptune 2D",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4", "0.4"],
            "single_extruder_multi_material": "0",
        },
    )
    output_root = tmp_path / "machine_registry"

    result = run_import(
        slicer_id="OrcaSlicer",
        source_root=source_root,
        source_version="02.04.00.00",
        vendor_keys=("Elegoo",),
        output_root=output_root,
    )

    assert result.device_count == 3
    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    assert [machine["display_name"] for machine in registry["slicers"][0]["machines"]] == [
        "Elegoo Centauri",
        "Elegoo Centauri Carbon",
        "Elegoo Centauri Carbon 2",
    ]


def test_snapmaker_orca_scope_keeps_only_u1(tmp_path):
    source_root = tmp_path / "profiles"
    machine_dir = source_root / "Snapmaker" / "machine"
    _write_machine_profile(
        machine_dir,
        "fdm_common.json",
        {
            "type": "machine",
            "name": "fdm_common",
            "instantiation": "false",
            "printable_height": "270",
            "printable_area": ["0x0", "270x0", "270x270", "0x270"],
        },
    )
    for model in ("Snapmaker A350", "Snapmaker Artisan", "Snapmaker J1", "Snapmaker U1"):
        _write_machine_profile(
            machine_dir,
            f"{model} 0.4 nozzle.json",
            {
                "type": "machine",
                "name": f"{model} 0.4 nozzle",
                "inherits": "fdm_common",
                "instantiation": "true",
                "printer_model": model,
                "printer_variant": "0.4",
                "nozzle_diameter": ["0.4", "0.4"] if model == "Snapmaker U1" else ["0.4"],
            },
        )
    output_root = tmp_path / "machine_registry"

    result = run_import(
        slicer_id="SnapmakerOrca",
        source_root=source_root,
        source_version="02.02.49.02",
        vendor_keys=("Snapmaker",),
        output_root=output_root,
    )

    assert result.device_count == 1
    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    assert [machine["display_name"] for machine in registry["slicers"][0]["machines"]] == ["Snapmaker U1"]


def test_run_import_sources_merges_multiple_slicers(tmp_path):
    bambu_root = tmp_path / "bambu"
    bambu_machine_dir = bambu_root / "BBL" / "machine"
    snapmaker_root = tmp_path / "orca"
    snapmaker_machine_dir = snapmaker_root / "Snapmaker" / "machine"
    for machine_dir, common_height in ((bambu_machine_dir, "325"), (snapmaker_machine_dir, "270")):
        _write_machine_profile(
            machine_dir,
            "fdm_common.json",
            {
                "type": "machine",
                "name": "fdm_common",
                "instantiation": "false",
                "printable_height": common_height,
                "printable_area": ["0x0", "270x0", "270x270", "0x270"],
            },
        )
    _write_machine_profile(
        bambu_machine_dir,
        "Bambu Lab H2D 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "Bambu Lab H2D 0.4 nozzle",
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Bambu Lab H2D",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4", "0.4"],
            "single_extruder_multi_material": "1",
        },
    )
    _write_machine_profile(
        snapmaker_machine_dir,
        "Snapmaker U1 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "Snapmaker U1 0.4 nozzle",
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Snapmaker U1",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4", "0.4", "0.4", "0.4"],
            "single_extruder_multi_material": "0",
        },
    )
    output_root = tmp_path / "machine_registry"

    result = run_import_sources(
        [
            ImportSource(
                slicer_id="BambuStudio",
                source_root=bambu_root,
                source_version="02.07.00.07",
                vendor_keys=("BBL",),
            ),
            ImportSource(
                slicer_id="OrcaSlicer",
                source_root=snapmaker_root,
                source_version="02.04.00.00",
                vendor_keys=("Snapmaker",),
            ),
        ],
        output_root=output_root,
    )

    assert result.device_count == 2
    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    assert [slicer["slicer_id"] for slicer in registry["slicers"]] == ["BambuStudio", "OrcaSlicer"]


def test_import_source_can_separate_profile_and_client_versions(tmp_path):
    source_root = tmp_path / "profiles"
    machine_dir = source_root / "Anycubic" / "machine"
    _write_machine_profile(
        machine_dir,
        "fdm_machine_common.json",
        {
            "type": "machine",
            "name": "fdm_machine_common",
            "instantiation": "false",
            "printable_height": "260",
            "printable_area": ["0x0", "260x0", "260x260", "0x260"],
        },
    )
    _write_machine_profile(
        machine_dir,
        "Anycubic Kobra X 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "Anycubic Kobra X 0.4 nozzle",
            "inherits": "fdm_machine_common",
            "instantiation": "true",
            "printer_model": "Anycubic Kobra X",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4"],
        },
    )
    output_root = tmp_path / "machine_registry"

    result = run_import_sources(
        [
            ImportSource(
                slicer_id="AnycubicSlicerNext",
                source_root=source_root,
                source_version="1.3.2605.22",
                vendor_keys=("Anycubic",),
                application_metadata="AnycubicSlicerNext-1.4.1.2",
                client_version="1.4.1.2 20260604104233",
            )
        ],
        output_root=output_root,
    )

    assert result.device_count == 1
    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    slicer = registry["slicers"][0]
    assert slicer["source_version"] == "1.3.2605.22"
    assert slicer["application_metadata"] == "AnycubicSlicerNext-1.4.1.2"
    assert slicer["client_version"] == "1.4.1.2 20260604104233"
    assert slicer["machines"][0]["nozzles"][0]["template"].startswith(
        "slicers/AnycubicSlicerNext/1.3.2605.22/"
    )


def test_run_import_preserves_native_quarter_mm_nozzle_profiles(tmp_path):
    source_root = tmp_path / "profiles"
    machine_dir = source_root / "Anycubic" / "machine"
    _write_machine_profile(
        machine_dir,
        "fdm_machine_common.json",
        {
            "type": "machine",
            "name": "fdm_machine_common",
            "instantiation": "false",
            "printable_height": "260",
            "printable_area": ["0x0", "260x0", "260x260", "0x260"],
        },
    )
    _write_machine_profile(
        machine_dir,
        "Anycubic Kobra X 0.25 nozzle.json",
        {
            "type": "machine",
            "name": "Anycubic Kobra X 0.25 nozzle",
            "inherits": "fdm_machine_common",
            "instantiation": "true",
            "printer_model": "Anycubic Kobra X",
            "printer_variant": "0.25",
            "nozzle_diameter": ["0.25"],
        },
    )
    output_root = tmp_path / "machine_registry"

    result = run_import(
        slicer_id="AnycubicSlicerNext",
        source_root=source_root,
        source_version="1.3.2605.22",
        vendor_keys=("Anycubic",),
        output_root=output_root,
    )

    assert result.device_count == 1
    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    nozzle = registry["slicers"][0]["machines"][0]["nozzles"][0]
    assert nozzle["nozzle_size"] == "0.25"
    assert nozzle["device_profile_id"] == "AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.25"
    assert nozzle["template"].endswith("anycubic-kobra-x_0_25.json")


def test_run_import_flash_studio_keeps_current_multicolor_models_and_nozzles(tmp_path):
    source_root = tmp_path / "profiles"
    machine_dir = source_root / "Flashforge" / "machine"
    _write_machine_profile(
        machine_dir,
        "fdm_common.json",
        {
            "type": "machine",
            "name": "fdm_common",
            "instantiation": "false",
            "printable_height": "256",
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
        },
    )
    model_nozzles = {
        "Flashforge AD5X": ("0.25", "0.4", "0.6", "0.8"),
        "Flashforge Creator 5": ("0.25", "0.4", "0.6", "0.8"),
        "Flashforge Creator 5 Pro": ("0.25", "0.4", "0.6", "0.8"),
        "Flashforge Guider 3 Ultra": ("0.4", "0.6", "0.8"),
        "Flashforge Guider4": ("0.25", "0.4", "0.4HF", "0.6", "0.6HF", "0.8HF"),
        "Flashforge Guider4 Pro": ("0.25", "0.4", "0.4HF", "0.6", "0.6HF", "0.8HF"),
        "Flashforge Adventurer 5M": ("0.25", "0.4", "0.6", "0.8"),
        "Flashforge Creator 5S": ("0.4", "0.6", "0.8"),
    }
    registered_profile_names: list[str] = []
    for model, variants in model_nozzles.items():
        for variant in variants:
            nozzle = variant.removesuffix("HF")
            if model.startswith("Flashforge Creator 5S"):
                physical_tools = 6
            elif model in {"Flashforge Creator 5", "Flashforge Creator 5 Pro"}:
                physical_tools = 4
            elif model == "Flashforge Guider 3 Ultra" and nozzle == "0.4":
                physical_tools = 2
            else:
                physical_tools = 1
            profile_name = f"{model} {variant.replace('HF', ' HF')} nozzle"
            _write_machine_profile(
                machine_dir,
                f"{profile_name}.json",
                {
                    "type": "machine",
                    "name": profile_name,
                    "inherits": "fdm_common",
                    "instantiation": "true",
                    "printer_model": model,
                    "printer_variant": variant,
                    "nozzle_diameter": [nozzle] * physical_tools,
                    "single_extruder_multi_material": (
                        "1" if model in {
                            "Flashforge AD5X",
                            "Flashforge Guider4",
                            "Flashforge Guider4 Pro",
                        } else "0"
                    ),
                },
            )
            if model != "Flashforge Creator 5S":
                registered_profile_names.append(profile_name)
    (source_root / "Flashforge.json").write_text(
        json.dumps(
            {
                "version": "02.01.01.00",
                "machine_list": [
                    {"name": name, "sub_path": f"machine/{name}.json"}
                    for name in registered_profile_names
                ],
            }
        ),
        encoding="utf-8",
    )

    output_root = tmp_path / "machine_registry"
    result = run_import(
        slicer_id="FlashStudio",
        source_root=source_root,
        source_version="02.01.01.00",
        vendor_keys=("Flashforge",),
        output_root=output_root,
        application_metadata="BambuStudio-2.3.2",
        client_version="",
    )

    assert result.device_count == 11
    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    slicer = registry["slicers"][0]
    assert slicer["application_metadata"] == "BambuStudio-2.3.2"
    assert slicer["client_version"] == ""
    assert [machine["display_name"] for machine in slicer["machines"]] == [
        "Flashforge AD5X",
        "Flashforge Creator 5",
        "Flashforge Creator 5 Pro",
        "Flashforge Guider 3 Ultra",
        "Flashforge Guider4",
        "Flashforge Guider4 Pro",
    ]
    assert {
        machine["display_name"]: [nozzle["nozzle_size"] for nozzle in machine["nozzles"]]
        for machine in slicer["machines"]
    } == {
        "Flashforge AD5X": ["0.25", "0.4"],
        "Flashforge Creator 5": ["0.25", "0.4"],
        "Flashforge Creator 5 Pro": ["0.25", "0.4"],
        "Flashforge Guider 3 Ultra": ["0.4"],
        "Flashforge Guider4": ["0.25", "0.4"],
        "Flashforge Guider4 Pro": ["0.25", "0.4"],
    }
    guider4 = next(
        machine for machine in slicer["machines"]
        if machine["display_name"] == "Flashforge Guider4"
    )
    assert [nozzle["source_profile_name"] for nozzle in guider4["nozzles"]] == [
        "Flashforge Guider4 0.25 nozzle",
        "Flashforge Guider4 0.4 nozzle",
    ]


def test_run_import_sources_reuses_cover_assets_from_other_sources(tmp_path):
    bambu_root = tmp_path / "bambu"
    orca_root = tmp_path / "orca"
    for source_root in (bambu_root, orca_root):
        machine_dir = source_root / "BBL" / "machine"
        _write_machine_profile(
            machine_dir,
            "fdm_common.json",
            {
                "type": "machine",
                "name": "fdm_common",
                "instantiation": "false",
                "printable_height": "325",
                "printable_area": ["0x0", "350x0", "350x320", "0x320"],
            },
        )
        _write_machine_profile(
            machine_dir,
            "Bambu Lab H2D 0.4 nozzle.json",
            {
                "type": "machine",
                "name": "Bambu Lab H2D 0.4 nozzle",
                "inherits": "fdm_common",
                "instantiation": "true",
                "printer_model": "Bambu Lab H2D",
                "printer_variant": "0.4",
                "nozzle_diameter": ["0.4", "0.4"],
            },
        )
    (bambu_root / "BBL" / "Bambu Lab H2D_cover.png").write_bytes(b"h2d-cover")
    output_root = tmp_path / "machine_registry"

    run_import_sources(
        [
            ImportSource(
                slicer_id="BambuStudio",
                source_root=bambu_root,
                source_version="02.07.00.07",
                vendor_keys=("BBL",),
            ),
            ImportSource(
                slicer_id="OrcaSlicer",
                source_root=orca_root,
                source_version="02.04.00.00",
                vendor_keys=("BBL",),
            ),
        ],
        output_root=output_root,
    )

    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    orca_slicer = next(slicer for slicer in registry["slicers"] if slicer["slicer_id"] == "OrcaSlicer")
    thumbnail = orca_slicer["machines"][0]["thumbnail"]
    assert thumbnail == "slicers/OrcaSlicer/02.04.00.00/assets/bambu-lab-h2d_cover.png"
    assert (output_root / thumbnail).read_bytes() == b"h2d-cover"


def test_run_import_sources_matches_camel_case_cover_assets(tmp_path):
    source_root = tmp_path / "snapmaker"
    machine_dir = source_root / "Snapmaker" / "machine"
    _write_machine_profile(
        machine_dir,
        "fdm_common.json",
        {
            "type": "machine",
            "name": "fdm_common",
            "instantiation": "false",
            "printable_height": "270",
            "printable_area": ["0x0", "270x0", "270x270", "0x270"],
        },
    )
    _write_machine_profile(
        machine_dir,
        "Snapmaker U1 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "Snapmaker U1 0.4 nozzle",
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Snapmaker U1",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4", "0.4", "0.4", "0.4"],
        },
    )
    image_dir = tmp_path / "web" / "images"
    image_dir.mkdir(parents=True)
    (image_dir / "snapmakerU1Cover.png").write_bytes(b"u1-cover")
    output_root = tmp_path / "machine_registry"

    run_import_sources(
        [
            ImportSource(
                slicer_id="SnapmakerOrca",
                source_root=source_root,
                source_version="02.02.49.02",
                vendor_keys=("Snapmaker",),
            ),
        ],
        output_root=output_root,
        asset_search_roots=((image_dir, ""),),
    )

    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    thumbnail = registry["slicers"][0]["machines"][0]["thumbnail"]
    assert thumbnail == "slicers/SnapmakerOrca/02.02.49.02/assets/snapmaker-u1_cover.png"
    assert (output_root / thumbnail).read_bytes() == b"u1-cover"


def test_asset_slug_removes_path_separators_and_parent_segments():
    assert _asset_slug("Bambu/../Lab H2D\\Cover") == "bambu-lab-h2d-cover"


def test_run_import_rejects_duplicate_device_profiles(tmp_path):
    source_root = tmp_path / "profiles"
    machine_dir = source_root / "BBL" / "machine"
    machine_dir.mkdir(parents=True)
    (machine_dir / "fdm_common.json").write_text(
        json.dumps(
            {
                "type": "machine",
                "name": "fdm_common",
                "instantiation": "false",
                "printable_height": "256",
                "printable_area": ["0x0", "256x0", "256x256", "0x256"],
            }
        ),
        encoding="utf-8",
    )
    for name in ("Bambu Lab P1S 0.4 nozzle", "Bambu Lab P1S duplicate 0.4 nozzle"):
        (machine_dir / f"{name}.json").write_text(
            json.dumps(
                {
                    "type": "machine",
                    "name": name,
                    "inherits": "fdm_common",
                    "instantiation": "true",
                    "printer_model": "Bambu Lab P1S",
                    "printer_variant": "0.4",
                    "nozzle_diameter": ["0.4"],
                }
            ),
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match="Duplicate machine registry device profile"):
        run_import(
            slicer_id="BambuStudio",
            source_root=source_root,
            source_version="02.07.01.57",
            vendor_keys=("BBL",),
            output_root=tmp_path / "machine_registry",
        )
