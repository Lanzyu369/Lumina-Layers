from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import pytest
import trimesh

from utils.bambu_3mf_writer import (
    BambuStudio3MFWriter,
    read_wipe_tower_placement_warnings,
)


def _add_material_boxes(
    writer: BambuStudio3MFWriter,
    *,
    width: float,
    depth: float,
    height: float = 2.0,
    count: int = 4,
) -> None:
    for index in range(count):
        writer.add_mesh(
            trimesh.creation.box(extents=[width, depth, height]),
            f"Material {index + 1}",
            ((index * 50) % 255, (index * 80) % 255, (index * 110) % 255),
        )


def _project_settings(writer: BambuStudio3MFWriter) -> dict[str, object]:
    return json.loads(writer._build_project_settings_bytes().decode("utf-8"))


@pytest.mark.parametrize(
    ("printer_id", "slicer", "expected_volume"),
    (
        # The bundled project template carries 30 mm3 but does not persist it
        # as a project override. Bambu Studio therefore slices with its native
        # 45 mm3 material default, which is the value footprint planning must
        # reserve.
        ("bambu-a1-mini", "BambuStudio", 45.0),
        ("bambu-a1-mini", "OrcaSlicer", 45.0),
        ("flashforge-creator-5", "FlashStudio", 30.0),
        ("anycubic-kobra-3-v2", "AnycubicSlicerNext", 20.0),
    ),
)
def test_tower_planning_uses_native_slicer_prime_volume(
    printer_id: str,
    slicer: str,
    expected_volume: float,
) -> None:
    writer = BambuStudio3MFWriter(
        "prime-volume.3mf",
        printer_id=printer_id,
        slicer=slicer,
    )

    assert writer._resolve_tower_purge_volume(
        writer._get_base_config_template()
    ) == pytest.approx(expected_volume)


def test_safe_p1s_layout_preserves_native_tower_settings() -> None:
    writer = BambuStudio3MFWriter(
        "safe-p1s.3mf",
        printer_id="bambu-p1s",
        slicer="BambuStudio",
    )
    _add_material_boxes(writer, width=100.0, depth=100.0)

    settings = _project_settings(writer)
    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.adapted is False
    assert settings["wipe_tower_x"] == ["18.5216"]
    assert settings["wipe_tower_y"] == ["214.154"]
    assert settings["prime_tower_width"] == "220"
    assert settings["wipe_tower_rotation_angle"] == "0"
    assert writer._get_build_item_translation()[:2] == pytest.approx((128.0, 128.0))


@pytest.mark.parametrize("slicer", ("BambuStudio", "OrcaSlicer"))
def test_a1_mini_uses_vertical_strip_for_tall_model(
    slicer: str,
) -> None:
    writer = BambuStudio3MFWriter(
        "a1-mini-tall.3mf",
        printer_id="bambu-a1-mini",
        slicer=slicer,
    )
    _add_material_boxes(writer, width=100.0, depth=155.0)

    settings = _project_settings(writer)
    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.requires_manual_adjustment is False
    assert placement.adapted is True
    assert float(settings["prime_tower_width"]) <= 174.0
    # Bambu/Orca clamp imported X/Y against the unrotated footprint. A physical
    # vertical strip therefore has to be produced by narrowing the tower so its
    # purge-derived depth becomes the long axis, without a 90-degree rotation.
    assert settings["wipe_tower_rotation_angle"] == "0"
    assert placement.tower_bounds.height > placement.tower_bounds.width
    assert placement.tower_width == pytest.approx(30.0)
    assert placement.tower_depth > placement.tower_width
    assert placement.tower_bounds.right + 3.0 <= 178.0 + 1e-6
    assert float(settings["wipe_tower_x"][0]) == pytest.approx(
        placement.tower_bounds.left
    )
    assert float(settings["wipe_tower_y"][0]) == pytest.approx(
        placement.tower_bounds.bottom
    )
    assert set(settings["different_settings_to_system"][0].split(";")) >= {
        "prime_tower_width",
        "wipe_tower_rotation_angle",
        "wipe_tower_x",
        "wipe_tower_y",
    }


def test_a1_mini_adapted_strip_keeps_visible_physical_edge_clearance() -> None:
    writer = BambuStudio3MFWriter(
        "a1-mini-real-wide.3mf",
        printer_id="bambu-a1-mini",
        slicer="BambuStudio",
    )
    _add_material_boxes(writer, width=110.0, depth=124.0, height=1.2)

    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.requires_manual_adjustment is False
    assert placement.adapted is True
    assert placement.reason in {"adapted_right", "adapted_left"}
    assert placement.tower_width == pytest.approx(30.0)
    assert placement.tower_bounds.height > placement.tower_bounds.width
    physical_tower = placement.tower_bounds.expanded(3.0)
    assert physical_tower.left >= 4.0 - 1e-6
    assert physical_tower.bottom >= 4.0 - 1e-6
    assert physical_tower.right <= 176.0 + 1e-6
    assert physical_tower.top <= 176.0 + 1e-6


def test_elegoo_cc2_adapted_strip_keeps_visible_physical_edge_clearance() -> None:
    writer = BambuStudio3MFWriter(
        "cc2-real-wide.3mf",
        printer_id="elegoo-cc2",
        slicer="ElegooSlicer",
    )
    _add_material_boxes(writer, width=200.0, depth=115.0, height=1.2)

    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.requires_manual_adjustment is False
    assert placement.adapted is True
    assert placement.tower_width == pytest.approx(200.0)
    physical_tower = placement.tower_bounds.expanded(3.0)
    assert physical_tower.left >= 4.0 - 1e-6
    assert physical_tower.bottom >= 4.0 - 1e-6
    assert physical_tower.right <= 252.0 + 1e-6
    assert physical_tower.top <= 224.0 + 1e-6


def test_a1_mini_uses_nearest_feasible_width_when_30_mm_would_squeeze_model() -> None:
    writer = BambuStudio3MFWriter(
        "a1-mini-real-tall.3mf",
        printer_id="bambu-a1-mini",
        slicer="BambuStudio",
    )
    _add_material_boxes(writer, width=130.0, depth=146.6)

    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.requires_manual_adjustment is False
    assert placement.reason in {"adapted_right", "adapted_left"}
    assert placement.tower_width == pytest.approx(22.0)
    assert placement.tower_bounds.height > placement.tower_bounds.width
    assert placement.model_bounds.width == pytest.approx(130.0)
    model_brim_right = placement.model_bounds.right + 5.0
    tower_brim_left = placement.tower_bounds.left - 3.0
    assert tower_brim_left - model_brim_right >= 8.0 - 1e-6


@pytest.mark.parametrize("material_count", (4, 5, 6, 8))
def test_orca_multicolor_project_collapses_dual_variant_filament_arrays(
    material_count: int,
) -> None:
    writer = BambuStudio3MFWriter(
        "a1-mini-orca-multicolor.3mf",
        printer_id="bambu-a1-mini",
        slicer="OrcaSlicer",
        color_mode=(
            "8-Color Max"
            if material_count == 8
            else "6-Color"
            if material_count == 6
            else "5-Color Extended"
            if material_count == 5
            else "4-Color"
        ),
    )
    _add_material_boxes(
        writer,
        width=110.0,
        depth=124.0,
        count=material_count,
    )

    settings = _project_settings(writer)

    assert len(settings["filament_colour"]) == material_count
    assert len(settings["filament_settings_id"]) == material_count
    for key in (
        "filament_extruder_variant",
        "filament_flow_ratio",
        "filament_max_volumetric_speed",
        "filament_retraction_length",
        "filament_self_index",
        "flush_volumes_vector",
    ):
        assert len(settings[key]) == material_count


def test_profile_model_brim_is_reserved_unless_explicitly_disabled() -> None:
    writer = BambuStudio3MFWriter(
        "profile-brim.3mf",
        printer_id="bambu-a1-mini",
        slicer="OrcaSlicer",
    )
    _add_material_boxes(writer, width=100.0, depth=100.0)

    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.model_outer_bounds.width == pytest.approx(114.0)

    no_brim_writer = BambuStudio3MFWriter(
        "no-brim.3mf",
        printer_id="bambu-a1-mini",
        slicer="OrcaSlicer",
        settings={"brim_type": "no_brim", "brim_width": "5"},
    )
    _add_material_boxes(no_brim_writer, width=100.0, depth=100.0)

    no_brim_placement = no_brim_writer._get_wipe_tower_placement()

    assert no_brim_placement is not None
    assert no_brim_placement.model_outer_bounds.width == pytest.approx(104.0)


@pytest.mark.parametrize(
    "printer_id",
    ["flashforge-creator-5", "flashforge-creator-5-pro"],
)
def test_c5_family_uses_30_mm_vertical_strip_for_tall_model(printer_id: str) -> None:
    writer = BambuStudio3MFWriter(
        "c5-long-strip.3mf",
        printer_id=printer_id,
        slicer="FlashStudio",
    )
    # The native 35 mm tower is valid for small models and must be preserved.
    # Flash Studio expands a nominal narrow tower to a roughly 58.5 x 61 mm
    # interface footprint. A 200 mm horizontal setting is therefore clamped
    # back into this tall model; the native-safe fallback is the 30 mm width
    # idiom plus a left translation of the unchanged model.
    _add_material_boxes(writer, width=180.0, depth=203.0)

    settings = _project_settings(writer)
    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.adapted is True
    assert placement.requires_manual_adjustment is False
    assert placement.reason in {"adapted_right", "adapted_left"}
    assert float(settings["prime_tower_width"]) == pytest.approx(30.0)
    assert settings["enable_prime_tower"] == "1"
    assert placement.tower_bounds.width == pytest.approx(58.5)
    assert placement.tower_bounds.height >= 61.0
    assert placement.model_bounds.width == pytest.approx(180.0)
    assert placement.model_bounds.left == pytest.approx(5.0)
    model_brim_right = placement.model_bounds.right + 5.0
    assert placement.tower_bounds.left - model_brim_right >= 7.5 - 1e-6


def test_kobra_3_v2_reserves_anycubic_native_tower_envelope() -> None:
    writer = BambuStudio3MFWriter(
        "kobra-3-v2-native-envelope.3mf",
        printer_id="anycubic-kobra-3-v2",
        slicer="AnycubicSlicerNext",
    )
    # Anycubic Slicer Next clamps a nominal 30 mm tower to X=205 and
    # Y=197.5 on the 255 mm Kobra 3 V2 bed. This exposes a native envelope
    # of 50 x 57.5 mm that is larger than the generic volume estimate.
    _add_material_boxes(writer, width=180.0, depth=203.0)

    settings = _project_settings(writer)
    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.adapted is True
    assert placement.requires_manual_adjustment is False
    assert placement.reason in {"adapted_right", "adapted_left"}
    assert float(settings["prime_tower_width"]) == pytest.approx(30.0)
    assert settings["wipe_tower_rotation_angle"] == "0"
    assert placement.tower_bounds.width == pytest.approx(50.0)
    assert placement.tower_bounds.height >= 57.5
    assert placement.model_bounds.width == pytest.approx(180.0)
    assert placement.model_bounds.left >= 5.0
    model_brim_right = placement.model_bounds.right + 5.0
    assert placement.tower_bounds.left - model_brim_right >= 8.0 - 1e-6


def test_impossible_layout_still_exports_with_tower_and_embedded_warning(tmp_path: Path) -> None:
    output_path = tmp_path / "manual-adjustment-required.3mf"
    writer = BambuStudio3MFWriter(
        str(output_path),
        printer_id="bambu-a1-mini",
        slicer="OrcaSlicer",
    )
    _add_material_boxes(writer, width=179.0, depth=179.0)

    exported_path = writer.export()

    assert Path(exported_path).is_file()
    with zipfile.ZipFile(exported_path) as package:
        settings = json.loads(package.read("Metadata/project_settings.config"))
        placement = json.loads(package.read("Metadata/lumina_wipe_tower_placement.json"))
        model_root = ET.fromstring(package.read("3D/3dmodel.model"))

    assert settings["enable_prime_tower"] == "1"
    assert float(settings["prime_tower_width"]) > 0.0
    assert placement["requires_manual_adjustment"] is True
    assert placement["warning_code"] == "wipe_tower_manual_adjustment_required"
    assert read_wipe_tower_placement_warnings(exported_path) == [
        "wipe_tower_manual_adjustment_required"
    ]

    namespace = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    build_item = model_root.find("m:build/m:item", namespace)
    assert build_item is not None
    transform = [float(value) for value in build_item.attrib["transform"].split()]
    assert transform[:9] == pytest.approx([1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0])


def test_safe_export_embeds_no_manual_warning(tmp_path: Path) -> None:
    output_path = tmp_path / "safe.3mf"
    writer = BambuStudio3MFWriter(
        str(output_path),
        printer_id="bambu-p1s",
        slicer="BambuStudio",
    )
    _add_material_boxes(writer, width=80.0, depth=80.0)

    writer.export()

    assert read_wipe_tower_placement_warnings(output_path) == []


def test_missing_printable_area_exports_with_manual_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "missing-printable-area.3mf"
    writer = BambuStudio3MFWriter(
        str(output_path),
        printer_id="bambu-p1s",
        slicer="BambuStudio",
    )
    _add_material_boxes(writer, width=80.0, depth=80.0)
    template = writer._get_base_config_template()
    template.pop("printable_area", None)
    monkeypatch.setattr(writer, "_get_base_config_template", lambda: template)

    writer.export()

    with zipfile.ZipFile(output_path) as package:
        placement = json.loads(
            package.read("Metadata/lumina_wipe_tower_placement.json")
        )

    assert placement["available"] is False
    assert placement["requires_manual_adjustment"] is True
    assert placement["warning_code"] == "wipe_tower_manual_adjustment_required"
    assert placement["reason"] == "printable_area_unavailable"
    assert read_wipe_tower_placement_warnings(output_path) == [
        "wipe_tower_manual_adjustment_required"
    ]
