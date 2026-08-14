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
from tools.machine_adapter.build_plates import (
    LUMINA_NEUTRAL_BUILD_PLATE_SOURCE_VERSION,
    native_build_plate_specs,
    resolve_machine_build_plates,
)
from tools.machine_adapter.update_build_plates import update_registry_build_plates


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


def test_run_import_generates_neutral_build_plates_and_resolves_machine_default(
    tmp_path,
):
    source_root = tmp_path / "Resources" / "profiles"
    fixture_root = Path("tests/fixtures/machine_adapter")
    (source_root / "BBL").mkdir(parents=True)
    for source in (fixture_root / "BBL").rglob("*"):
        if source.is_file():
            destination = source_root / "BBL" / source.relative_to(fixture_root / "BBL")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
    image_root = source_root.parent / "images"
    image_root.mkdir(parents=True)
    (image_root / "bed_cool.png").write_bytes(b"native-cool-plate")
    (image_root / "bed_pei.png").write_bytes(b"native-textured-plate")

    machine_path = next((source_root / "BBL" / "machine").glob("*.json"))
    machine = json.loads(machine_path.read_text(encoding="utf-8"))
    machine["default_bed_type"] = "Textured PEI Plate"
    machine["not_support_bed_type"] = "Cool Plate"
    machine_path.write_text(json.dumps(machine), encoding="utf-8")

    output_root = tmp_path / "machine_registry"
    run_import(
        slicer_id="BambuStudio",
        source_root=source_root,
        source_version="02.07.01.62",
        vendor_keys=("BBL",),
        output_root=output_root,
    )

    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    slicer = registry["slicers"][0]
    assert [plate["id"] for plate in slicer["build_plates"]] == [
        "cool-plate",
        "engineering-plate",
        "smooth-pei-plate",
        "textured-pei-plate",
        "supertack-plate",
    ]
    textured = next(
        plate
        for plate in slicer["build_plates"]
        if plate["id"] == "textured-pei-plate"
    )
    assert textured["display_name_zh"] == "纹理PEI打印板"
    assert textured["source_path"] == (
        "LuminaStudio:generated/build_plates/bed_pei.png"
    )
    assert textured["source_version"] == LUMINA_NEUTRAL_BUILD_PLATE_SOURCE_VERSION
    assert textured["revision"].startswith("sha256:")
    assert (output_root / textured["image"]).read_bytes().startswith(b"\x89PNG")
    imported_machine = slicer["machines"][0]
    assert imported_machine["supported_build_plate_ids"] == [
        "engineering-plate",
        "smooth-pei-plate",
        "textured-pei-plate",
        "supertack-plate",
    ]
    assert imported_machine["default_build_plate_id"] == "textured-pei-plate"


def test_run_import_applies_machine_model_build_plate_restrictions(tmp_path):
    source_root = tmp_path / "Resources" / "profiles"
    machine_dir = source_root / "Elegoo" / "machine" / "ECC2"
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
        "Elegoo Centauri Carbon 2.json",
        {
            "type": "machine_model",
            "name": "Elegoo Centauri Carbon 2",
            "not_support_bed_type": (
                "Smooth High Temp Plate;Engineering Plate;"
                "Textured Cool Plate;Cool Plate (SuperTack)"
            ),
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
            "default_bed_type": "4",
            "single_extruder_multi_material": "1",
        },
    )
    image_root = source_root.parent / "images"
    image_root.mkdir(parents=True)
    for filename in (
        "bed_pc_elegoo.png",
        "bed_engineering.png",
        "bed_high_templ.png",
        "bed_pte_elegoo.png",
        "bed_pei_cool.png",
        "bed_cool_supertack.png",
    ):
        (image_root / filename).write_bytes(filename.encode("ascii"))

    output_root = tmp_path / "machine_registry"
    run_import(
        slicer_id="ElegooSlicer",
        source_root=source_root,
        source_version="01.05.03.04",
        vendor_keys=("Elegoo",),
        output_root=output_root,
    )

    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    machine = registry["slicers"][0]["machines"][0]
    assert machine["supported_build_plate_ids"] == [
        "smooth-cool-plate",
        "textured-pei-plate",
    ]
    assert machine["default_build_plate_id"] == "textured-pei-plate"
    plates = registry["slicers"][0]["build_plates"]
    assert next(plate for plate in plates if plate["id"] == "smooth-cool-plate")[
        "image"
    ].endswith("bed_cool.png")
    assert next(plate for plate in plates if plate["id"] == "textured-pei-plate")[
        "image"
    ].endswith("bed_pei.png")


def test_run_import_respects_native_multi_bed_disable_flag(tmp_path):
    source_root = tmp_path / "Resources" / "profiles"
    machine_dir = source_root / "Flashforge" / "machine"
    _write_machine_profile(
        machine_dir,
        "fdm_common.json",
        {
            "type": "machine",
            "name": "fdm_common",
            "instantiation": "false",
            "printable_height": "220",
            "printable_area": ["0x0", "220x0", "220x220", "0x220"],
        },
    )
    _write_machine_profile(
        machine_dir,
        "Flashforge AD5X 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "Flashforge AD5X 0.4 nozzle",
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Flashforge AD5X",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4"],
            "single_extruder_multi_material": "1",
            "support_multi_bed_types": "0",
        },
    )
    (source_root / "Flashforge.json").write_text(
        json.dumps(
            {
                "version": "02.01.01.00",
                "machine_list": [
                    {
                        "name": "Flashforge AD5X 0.4 nozzle",
                        "sub_path": "machine/Flashforge AD5X 0.4 nozzle.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    image_root = source_root.parent / "images"
    image_root.mkdir(parents=True)
    (image_root / "bed_pei.png").write_bytes(b"flash-bed")

    output_root = tmp_path / "machine_registry"
    run_import(
        slicer_id="FlashStudio",
        source_root=source_root,
        source_version="02.01.01.00",
        vendor_keys=("Flashforge",),
        output_root=output_root,
    )

    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    machine = registry["slicers"][0]["machines"][0]
    assert machine["supported_build_plate_ids"] == []
    assert machine["default_build_plate_id"] == ""


def test_neutral_asset_catalogs_cover_snapmaker_and_anycubic():
    for slicer_id in ("SnapmakerOrca", "AnycubicSlicerNext"):
        specs = native_build_plate_specs(slicer_id)
        assert len(specs) == 6
        assert all(spec.source_filename.endswith(".png") for spec in specs)


def test_flash_studio_catalog_uses_neutral_app_owned_assets():
    specs = native_build_plate_specs("FlashStudio")

    assert len(specs) == 6
    assert specs[3].display_name_zh == "纹理PEI热床"


def test_machine_without_native_multi_bed_support_has_no_selector():
    specs = native_build_plate_specs("FlashStudio")

    supported, default = resolve_machine_build_plates(
        slicer_id="FlashStudio",
        settings={"support_multi_bed_types": "0", "default_bed_type": "4"},
        available_plate_ids={spec.id for spec in specs},
    )

    assert supported == []
    assert default == ""


def test_snapmaker_single_bed_profile_keeps_only_its_native_default():
    specs = native_build_plate_specs("SnapmakerOrca")

    supported, default = resolve_machine_build_plates(
        slicer_id="SnapmakerOrca",
        settings={
            "support_multi_bed_types": "0",
            "default_bed_type": "Textured PEI Plate",
        },
        available_plate_ids={spec.id for spec in specs},
    )

    assert supported == ["textured-pei-plate"]
    assert default == "textured-pei-plate"


def test_update_registry_uses_one_lumina_neutral_asset_set(tmp_path):
    registry_root = tmp_path / "registry"
    slicers = []
    for slicer_id in ("SnapmakerOrca", "AnycubicSlicerNext"):
        slicers.append(
            {
                "slicer_id": slicer_id,
                "source_version": "test-version",
                "build_plates": [],
                "machines": [],
            }
        )
    registry_root.mkdir()
    (registry_root / "registry.json").write_text(
        json.dumps({"schema_version": 1, "generated_at": "test", "slicers": slicers}),
        encoding="utf-8",
    )

    update_registry_build_plates(
        registry_root=registry_root,
        source_roots={},
    )

    registry = json.loads((registry_root / "registry.json").read_text(encoding="utf-8"))
    image_sets = []
    for slicer in registry["slicers"]:
        assert len(slicer["build_plates"]) == 6
        assert all(
            plate["source_path"].startswith("LuminaStudio:generated/build_plates/")
            for plate in slicer["build_plates"]
        )
        assert all(
            plate["source_version"] == LUMINA_NEUTRAL_BUILD_PLATE_SOURCE_VERSION
            for plate in slicer["build_plates"]
        )
        image_sets.append({plate["image"] for plate in slicer["build_plates"]})
    assert image_sets[0] == image_sets[1]
    assert len(image_sets[0]) == 6


def test_update_registry_build_plates_preserves_existing_machine_templates(tmp_path):
    source_root = tmp_path / "Resources" / "profiles"
    image_root = source_root.parent / "images"
    image_root.mkdir(parents=True)
    (image_root / "bed_pei.png").write_bytes(b"plate-art")
    registry_root = tmp_path / "registry"
    template_path = Path("slicers/BambuStudio/v1/metadata_templates/test.json")
    (registry_root / template_path).parent.mkdir(parents=True)
    (registry_root / template_path).write_text(
        json.dumps({"default_bed_type": "Textured PEI Plate"}),
        encoding="utf-8",
    )
    (registry_root / "registry.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "test",
                "slicers": [
                    {
                        "slicer_id": "BambuStudio",
                        "source_version": "v1",
                        "machines": [
                            {
                                "machine_profile_id": "BambuStudio:test:test",
                                "nozzles": [{"template": template_path.as_posix()}],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    update_registry_build_plates(
        registry_root=registry_root,
        source_roots={"BambuStudio": source_root},
    )

    registry = json.loads((registry_root / "registry.json").read_text(encoding="utf-8"))
    assert len(registry["slicers"][0]["build_plates"]) == 5
    assert registry["slicers"][0]["machines"][0]["default_build_plate_id"] == (
        "textured-pei-plate"
    )
    assert json.loads((registry_root / template_path).read_text(encoding="utf-8")) == {
        "default_bed_type": "Textured PEI Plate"
    }


def test_update_registry_recomputes_existing_h2d_plate_scope(tmp_path):
    source_root = tmp_path / "Resources" / "profiles"
    machine_dir = source_root / "BBL" / "machine"
    _write_machine_profile(
        machine_dir,
        "Bambu Lab H2D.json",
        {
            "type": "machine_model",
            "name": "Bambu Lab H2D",
            "not_support_bed_type": "Cool Plate",
            "default_bed_type": "Textured PEI Plate",
        },
    )
    image_root = source_root.parent / "images"
    image_root.mkdir(parents=True)
    (image_root / "bed_cool.png").write_bytes(b"cool")
    (image_root / "bed_pei.png").write_bytes(b"textured")

    registry_root = tmp_path / "registry"
    template_path = Path("slicers/BambuStudio/v1/metadata_templates/h2d.json")
    (registry_root / template_path).parent.mkdir(parents=True)
    (registry_root / template_path).write_text(
        json.dumps({"default_bed_type": "Textured PEI Plate"}),
        encoding="utf-8",
    )
    (registry_root / "registry.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "test",
                "slicers": [
                    {
                        "slicer_id": "BambuStudio",
                        "source_version": "v1",
                        "machines": [
                            {
                                "machine_profile_id": "BambuStudio:bbl:bambu-lab-h2d",
                                "display_name": "Bambu Lab H2D",
                                "vendor_key": "BBL",
                                "supported_build_plate_ids": [
                                    "cool-plate",
                                    "textured-pei-plate",
                                ],
                                "default_build_plate_id": "cool-plate",
                                "nozzles": [{"template": template_path.as_posix()}],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    update_registry_build_plates(
        registry_root=registry_root,
        source_roots={"BambuStudio": source_root},
    )

    registry = json.loads((registry_root / "registry.json").read_text(encoding="utf-8"))
    machine = registry["slicers"][0]["machines"][0]
    assert machine["supported_build_plate_ids"] == [
        "engineering-plate",
        "smooth-pei-plate",
        "textured-pei-plate",
        "supertack-plate",
    ]
    assert machine["default_build_plate_id"] == "textured-pei-plate"


def test_update_registry_intersects_snapmaker_nozzle_plate_scopes(tmp_path):
    snapmaker_root = tmp_path / "Snapmaker" / "Resources" / "profiles"
    orca_root = tmp_path / "Orca" / "Resources" / "profiles"
    orca_images = orca_root.parent / "images"
    orca_images.mkdir(parents=True)
    for filename in (
        "bed_cool.png",
        "bed_engineering.png",
        "bed_high_templ.png",
        "bed_pei.png",
        "bed_pei_cool.png",
        "bed_cool_supertack.png",
    ):
        (orca_images / filename).write_bytes(filename.encode("ascii"))

    registry_root = tmp_path / "registry"
    template_root = registry_root / "slicers/SnapmakerOrca/v1/metadata_templates"
    template_root.mkdir(parents=True)
    multi_template = template_root / "u1_0_4.json"
    single_template = template_root / "u1_0_8.json"
    multi_template.write_text(
        json.dumps({"default_bed_type": "Textured PEI Plate"}),
        encoding="utf-8",
    )
    single_template.write_text(
        json.dumps(
            {
                "default_bed_type": "Textured PEI Plate",
                "support_multi_bed_types": "0",
            }
        ),
        encoding="utf-8",
    )
    (registry_root / "registry.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "test",
                "slicers": [
                    {
                        "slicer_id": "SnapmakerOrca",
                        "source_version": "v1",
                        "machines": [
                            {
                                "machine_profile_id": "SnapmakerOrca:snapmaker:snapmaker-u1",
                                "display_name": "Snapmaker U1",
                                "vendor_key": "Snapmaker",
                                "supported_build_plate_ids": [
                                    spec.id
                                    for spec in native_build_plate_specs("SnapmakerOrca")
                                ],
                                "default_build_plate_id": "textured-pei-plate",
                                "nozzles": [
                                    {"template": multi_template.relative_to(registry_root).as_posix()},
                                    {"template": single_template.relative_to(registry_root).as_posix()},
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    update_registry_build_plates(
        registry_root=registry_root,
        source_roots={
            "SnapmakerOrca": snapmaker_root,
            "OrcaSlicer": orca_root,
        },
    )

    registry = json.loads((registry_root / "registry.json").read_text(encoding="utf-8"))
    machine = registry["slicers"][0]["machines"][0]
    assert machine["supported_build_plate_ids"] == ["textured-pei-plate"]
    assert machine["default_build_plate_id"] == "textured-pei-plate"


def test_full_import_applies_kobra_s1_snapshot_plate_exclusion(tmp_path):
    source_root = tmp_path / "Anycubic" / "Resources" / "profiles"
    machine_dir = source_root / "Anycubic" / "machine"
    _write_machine_profile(
        machine_dir,
        "fdm_common.json",
        {
            "type": "machine",
            "name": "fdm_common",
            "instantiation": "false",
            "printable_height": "250",
            "printable_area": ["0x0", "250x0", "250x250", "0x250"],
        },
    )
    _write_machine_profile(
        machine_dir,
        "Anycubic Kobra S1.json",
        {
            "type": "machine_model",
            "name": "Anycubic Kobra S1",
        },
    )
    _write_machine_profile(
        machine_dir,
        "Anycubic Kobra S1 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "Anycubic Kobra S1 0.4 nozzle",
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Anycubic Kobra S1",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4"],
            "support_multi_bed_types": "1",
            "default_bed_type": "Textured PEI Plate",
        },
    )
    orca_root = tmp_path / "Orca" / "Resources" / "profiles"
    orca_images = orca_root.parent / "images"
    orca_images.mkdir(parents=True)
    for spec in native_build_plate_specs("AnycubicSlicerNext"):
        (orca_images / spec.source_filename).write_bytes(spec.id.encode("ascii"))

    output_root = tmp_path / "registry"
    run_import(
        slicer_id="AnycubicSlicerNext",
        source_root=source_root,
        source_version="1.3.2605.22",
        vendor_keys=("Anycubic",),
        output_root=output_root,
        build_plate_source_roots={"OrcaSlicer": orca_root},
    )

    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    machine = registry["slicers"][0]["machines"][0]
    assert machine["machine_profile_id"] == (
        "AnycubicSlicerNext:anycubic:anycubic-kobra-s1"
    )
    assert "engineering-plate" not in machine["supported_build_plate_ids"]


def test_full_import_intersects_snapmaker_nozzle_plate_scopes(tmp_path):
    source_root = tmp_path / "Snapmaker" / "Resources" / "profiles"
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
    for nozzle, multi_bed in (("0.4", None), ("0.8", "0")):
        payload = {
            "type": "machine",
            "name": f"Snapmaker U1 ({nozzle} nozzle)",
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Snapmaker U1",
            "printer_variant": nozzle,
            "nozzle_diameter": [nozzle, nozzle, nozzle, nozzle],
            "default_bed_type": "Textured PEI Plate",
        }
        if multi_bed is not None:
            payload["support_multi_bed_types"] = multi_bed
        _write_machine_profile(
            machine_dir,
            f"Snapmaker U1 ({nozzle} nozzle).json",
            payload,
        )
    orca_root = tmp_path / "Orca" / "Resources" / "profiles"
    orca_images = orca_root.parent / "images"
    orca_images.mkdir(parents=True)
    for spec in native_build_plate_specs("SnapmakerOrca"):
        (orca_images / spec.source_filename).write_bytes(spec.id.encode("ascii"))

    output_root = tmp_path / "registry"
    run_import(
        slicer_id="SnapmakerOrca",
        source_root=source_root,
        source_version="02.02.49.02",
        vendor_keys=("Snapmaker",),
        output_root=output_root,
        build_plate_source_roots={"OrcaSlicer": orca_root},
    )

    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    machine = registry["slicers"][0]["machines"][0]
    assert [nozzle["nozzle_size"] for nozzle in machine["nozzles"]] == ["0.4", "0.8"]
    assert machine["supported_build_plate_ids"] == ["textured-pei-plate"]
    assert machine["default_build_plate_id"] == "textured-pei-plate"


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
    template_relative_path = slicer["machines"][0]["nozzles"][0]["template"]
    assert template_relative_path.startswith(
        "slicers/AnycubicSlicerNext/1.3.2605.22/"
    )
    template = json.loads(
        (output_root / template_relative_path).read_text(encoding="utf-8")
    )
    assert "version" not in template


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


def test_run_import_flash_studio_defaults_native_project_identity(tmp_path):
    source_root = tmp_path / "profiles"
    machine_dir = source_root / "Flashforge" / "machine"
    _write_machine_profile(
        machine_dir,
        "fdm_common.json",
        {
            "type": "machine",
            "name": "fdm_common",
            "instantiation": "false",
            "printable_height": "220",
            "printable_area": ["0x0", "220x0", "220x220", "0x220"],
        },
    )
    profile_name = "Flashforge AD5X 0.4 nozzle"
    _write_machine_profile(
        machine_dir,
        f"{profile_name}.json",
        {
            "type": "machine",
            "name": profile_name,
            "inherits": "fdm_common",
            "instantiation": "true",
            "printer_model": "Flashforge AD5X",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4"],
            "single_extruder_multi_material": "1",
        },
    )
    (source_root / "Flashforge.json").write_text(
        json.dumps(
            {
                "version": "02.01.01.00",
                "machine_list": [
                    {"name": profile_name, "sub_path": f"machine/{profile_name}.json"}
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
    )

    assert result.device_count == 1
    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    slicer = registry["slicers"][0]
    assert slicer["application_metadata"] == "BambuStudio-2.3.2"
    assert slicer["client_version"] == ""
    template_path = slicer["machines"][0]["nozzles"][0]["template"]
    template = json.loads((output_root / template_path).read_text(encoding="utf-8"))
    assert template["version"] == "2.3.2"


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
