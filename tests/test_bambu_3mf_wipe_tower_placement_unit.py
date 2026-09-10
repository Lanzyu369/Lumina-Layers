from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import pytest
import trimesh

from config import list_printer_profiles
from core.wipe_tower_placement import (
    Rect,
    WipeTowerPlacementRequest,
    _layout_is_safe,
)
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


def _placement_request(
    writer: BambuStudio3MFWriter,
) -> WipeTowerPlacementRequest:
    template = writer._get_base_config_template()
    bounds_min, bounds_max = writer._get_mesh_bounds()
    request = writer._build_wipe_tower_placement_request(
        template,
        model_bounds=Rect(
            float(bounds_min[0]),
            float(bounds_min[1]),
            float(bounds_max[0]),
            float(bounds_max[1]),
        ),
        model_height=float(bounds_max[2] - bounds_min[2]),
        material_count=len(writer._build_material_palette()[0]),
    )
    assert request is not None
    return request


def _auto_placement_profile_slicer_cases() -> tuple[
    tuple[str, str, str | None], ...
]:
    cases: list[tuple[str, str, str | None]] = []
    for profile in list_printer_profiles():
        slicers = list(profile.slicer_templates)
        if profile.brand == "Bambu Lab":
            slicers.insert(0, "BambuStudio")
        if not slicers:
            slicers.append("BambuStudio")
        for slicer in dict.fromkeys(slicers):
            device_profile_id = (
                "SnapmakerOrca:snapmaker:snapmaker-u1:0.4"
                if profile.id == "snapmaker-u1" and slicer == "SnapmakerOrca"
                else None
            )
            cases.append((profile.id, slicer, device_profile_id))
    return tuple(cases)


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


@pytest.mark.parametrize(
    ("printer_id", "slicer", "device_profile_id"),
    _auto_placement_profile_slicer_cases(),
    ids=lambda value: str(value) if value is not None else "default-profile",
)
def test_enabled_auto_placement_replans_typical_model_across_all_profiles(
    printer_id: str,
    slicer: str,
    device_profile_id: str | None,
) -> None:
    writer = BambuStudio3MFWriter(
        "auto-placement.3mf",
        printer_id=printer_id,
        slicer=slicer,
        device_profile_id=device_profile_id,
    )
    _add_material_boxes(writer, width=60.0, depth=60.0, height=1.2)

    request = _placement_request(writer)
    settings = _project_settings(writer)
    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.adapted is True
    assert placement.requires_manual_adjustment is False
    assert placement.reason.startswith("adapted_")
    assert placement.tower_depth > 0.0
    assert _layout_is_safe(placement, request)
    assert placement.model_bounds.width == pytest.approx(request.model_bounds.width)
    assert placement.model_bounds.height == pytest.approx(request.model_bounds.height)
    assert writer._get_build_item_translation()[:2] == pytest.approx(
        placement.model_translation
    )
    assert isinstance(settings["wipe_tower_x"], list)
    assert isinstance(settings["wipe_tower_y"], list)
    assert float(settings["wipe_tower_x"][0]) == pytest.approx(placement.tower_x)
    assert float(settings["wipe_tower_y"][0]) == pytest.approx(placement.tower_y)
    assert float(settings["prime_tower_width"]) == pytest.approx(
        placement.tower_width
    )
    assert float(settings["wipe_tower_rotation_angle"]) == pytest.approx(
        placement.tower_rotation
    )

    assert (placement.tower_x, placement.tower_y) != pytest.approx(
        (request.tower_x, request.tower_y)
    )

    template_shape = (request.tower_width, request.tower_rotation)
    if (placement.tower_width, placement.tower_rotation) == pytest.approx(
        template_shape
    ):
        # A few FlashStudio templates already use the solver's preferred
        # 30 mm tower shape; auto layout must still replace their coordinates.
        assert template_shape == pytest.approx((30.0, 0.0))


def test_qidi_comma_grouped_bed_exclusions_are_parsed_as_polygons() -> None:
    q2_polygons = BambuStudio3MFWriter._parse_bed_exclusion_polygons(
        ["0x0,11x0,11x16,0x16"]
    )
    x_max_polygons = BambuStudio3MFWriter._parse_bed_exclusion_polygons(
        [
            "0x0,16x0,16x13,0x13,0x0,0x0,0x0,0x0,"
            "0x13,6x13,6x23,0x23,0x13,0x13,0x13,0x13,"
            "0x387,53x387,53x390,0x390,0x387,0x387,0x397,0x390,"
            "338x390,338x384,390x384,390x390,0x390"
        ]
    )

    assert q2_polygons == (
        ((0.0, 0.0), (11.0, 0.0), (11.0, 16.0), (0.0, 16.0)),
    )
    assert len(x_max_polygons) == 7
    assert x_max_polygons[0] == (
        (0.0, 0.0),
        (16.0, 0.0),
        (16.0, 13.0),
        (0.0, 13.0),
    )
    assert x_max_polygons[-1] == (
        (338.0, 390.0),
        (338.0, 384.0),
        (390.0, 384.0),
        (390.0, 390.0),
        (0.0, 390.0),
    )


def test_irregular_nine_point_bed_exclusion_remains_one_polygon() -> None:
    points = (
        (0.0, 4.0),
        (1.0, 1.0),
        (4.0, 0.0),
        (7.0, 1.0),
        (8.0, 4.0),
        (7.0, 7.0),
        (4.0, 8.0),
        (1.0, 7.0),
        (0.0, 4.0),
    )

    polygons = BambuStudio3MFWriter._parse_bed_exclusion_polygons(
        [",".join(f"{x:g}x{y:g}" for x, y in points)]
    )

    assert polygons == (points,)


def test_subdivided_rectangle_edges_are_not_treated_as_qidi_sentinels() -> None:
    points = (
        (0.0, 0.0),
        (1.0, 0.0),
        (2.0, 0.0),
        (3.0, 0.0),
        (4.0, 0.0),
        (4.0, 1.0),
        (4.0, 2.0),
        (4.0, 3.0),
        (4.0, 4.0),
        (3.0, 4.0),
        (2.0, 4.0),
        (0.0, 4.0),
        (0.0, 0.0),
    )

    polygons = BambuStudio3MFWriter._parse_bed_exclusion_polygons(
        [",".join(f"{x:g}x{y:g}" for x, y in points)]
    )

    assert polygons == (points,)


@pytest.mark.parametrize(
    ("printer_id", "model_size"),
    (
        ("qidi-q2", (200.0, 180.0)),
        ("qidi-x-max-4", (300.0, 280.0)),
    ),
)
def test_qidi_auto_layout_respects_real_template_bed_exclusions(
    printer_id: str,
    model_size: tuple[float, float],
) -> None:
    writer = BambuStudio3MFWriter(
        "qidi-exclusion-layout.3mf",
        printer_id=printer_id,
        slicer="QIDIStudio",
    )
    _add_material_boxes(writer, width=model_size[0], depth=model_size[1])

    request = _placement_request(writer)
    placement = writer._get_wipe_tower_placement()

    assert request.bed_exclusions
    assert placement is not None
    assert placement.requires_manual_adjustment is False
    assert _layout_is_safe(placement, request)


def test_p1s_auto_layout_uses_compact_right_side_tower() -> None:
    writer = BambuStudio3MFWriter(
        "p1s-auto-layout.3mf",
        printer_id="bambu-p1s",
        slicer="BambuStudio",
    )
    _add_material_boxes(writer, width=60.0, depth=60.0)

    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.reason == "adapted_right"
    assert placement.model_translation == pytest.approx((128.0, 128.0))
    assert placement.tower_x == pytest.approx(219.0)
    assert placement.tower_y == pytest.approx(81.625)
    assert placement.tower_width == pytest.approx(30.0)
    assert placement.tower_rotation == pytest.approx(0.0)


def test_u1_auto_placement_changes_tower_size_and_position_for_typical_model() -> None:
    writer = BambuStudio3MFWriter(
        "u1-typical-auto-placement.3mf",
        printer_id="snapmaker-u1",
        slicer="SnapmakerOrca",
        device_profile_id="SnapmakerOrca:snapmaker:snapmaker-u1:0.4",
    )
    _add_material_boxes(writer, width=60.0, depth=60.0, height=1.2)

    template = writer._get_base_config_template()
    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.adapted is True
    assert placement.requires_manual_adjustment is False
    assert placement.tower_width != pytest.approx(float(template["prime_tower_width"]))
    assert (placement.tower_x, placement.tower_y) != pytest.approx(
        (float(template["wipe_tower_x"][0]), float(template["wipe_tower_y"][0]))
    )


def test_disabled_auto_placement_preserves_u1_template_without_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "snapmaker-u1-auto-placement-disabled.3mf"
    writer = BambuStudio3MFWriter(
        str(output_path),
        printer_id="snapmaker-u1",
        slicer="SnapmakerOrca",
        device_profile_id="SnapmakerOrca:snapmaker:snapmaker-u1:0.4",
        enable_wipe_tower_auto_placement=False,
    )
    _add_material_boxes(writer, width=180.0, depth=230.0)
    template = writer._get_base_config_template()

    def fail_if_solver_runs(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("wipe-tower solver must not run when disabled")

    monkeypatch.setattr(
        "utils.bambu_3mf_writer.solve_wipe_tower_placement",
        fail_if_solver_runs,
    )

    writer.export()

    with zipfile.ZipFile(output_path) as package:
        settings = json.loads(package.read("Metadata/project_settings.config"))
        placement = json.loads(
            package.read("Metadata/lumina_wipe_tower_placement.json")
        )

    for key in (
        "wipe_tower_x",
        "wipe_tower_y",
        "prime_tower_width",
        "wipe_tower_rotation_angle",
    ):
        assert settings[key] == template[key]
    assert placement == {
        "schema_version": 1,
        "enabled": False,
        "available": False,
        "adapted": False,
        "requires_manual_adjustment": False,
        "warning_code": None,
        "reason": "disabled_by_user",
    }
    assert read_wipe_tower_placement_warnings(output_path) == []


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
    # The native 35 mm tower is the template input for small models.
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
