"""Unit tests for Bambu layer_config_ranges metadata generation."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile

import hypothesis.strategies as st
import pytest
import trimesh
from hypothesis import given

from utils import bambu_3mf_writer as writer_module
from utils.bambu_3mf_writer import BambuStudio3MFWriter, export_scene_with_bambu_metadata


def _call_build_layer_config_ranges_xml(**kwargs) -> bytes | None:
    builder = getattr(writer_module, "build_layer_config_ranges_xml", None)
    if builder is None:
        pytest.fail("utils.bambu_3mf_writer.build_layer_config_ranges_xml is missing")
    return builder(**kwargs)


def _parse_range(xml_bytes: bytes, expected_object_id: str = "1") -> tuple[float, float, float]:
    root = ET.fromstring(xml_bytes)
    object_elem = root.find("./object")
    assert object_elem is not None
    assert object_elem.attrib["id"] == expected_object_id

    range_elem = object_elem.find("./range")
    assert range_elem is not None

    extruder_elem = range_elem.find("./option[@opt_key='extruder']")
    layer_height_elem = range_elem.find("./option[@opt_key='layer_height']")
    assert extruder_elem is not None
    assert layer_height_elem is not None
    assert (extruder_elem.text or "") == "0"

    return (
        float(range_elem.attrib["min_z"]),
        float(range_elem.attrib["max_z"]),
        float(layer_height_elem.text or "nan"),
    )


def _make_writer(output_path: str, **kwargs) -> BambuStudio3MFWriter:
    settings = kwargs.pop("settings", {})
    try:
        return BambuStudio3MFWriter(
            output_path,
            settings=settings,
            color_mode="4-Color",
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            **kwargs,
        )
    except TypeError as exc:
        pytest.fail(f"BambuStudio3MFWriter signature missing Task A kwargs: {exc}")


def _make_box_mesh() -> trimesh.Trimesh:
    return trimesh.creation.box(extents=(10, 10, 1))


def _make_scene() -> trimesh.Scene:
    scene = trimesh.Scene()
    scene.add_geometry(_make_box_mesh(), geom_name="Slot 1")
    return scene


def _model_relationship_targets(package: zipfile.ZipFile) -> set[str]:
    rels = ET.fromstring(package.read("3D/_rels/3dmodel.model.rels"))
    return {
        rel.attrib["Target"]
        for rel in rels.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
    }


def test_skip_when_toggle_off(tmp_path) -> None:
    output_path = tmp_path / "toggle-off.3mf"

    try:
        export_scene_with_bambu_metadata(
            scene=_make_scene(),
            output_path=str(output_path),
            slot_names=["Slot 1"],
            preview_colors={"Slot 1": (255, 0, 0)},
            settings={},
            color_mode="4-Color",
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            enable_base_layer_height_modifier=False,
            base_height_mm=0.8,
            color_height_mm=2.4,
            face_orientation="down",
        )
    except TypeError as exc:
        pytest.fail(f"export_scene_with_bambu_metadata signature missing Task A kwargs: {exc}")

    with zipfile.ZipFile(output_path) as package:
        assert "Metadata/layer_config_ranges.xml" not in package.namelist()


def test_skip_when_relief_is_enabled_even_if_modifier_toggle_is_on(tmp_path) -> None:
    output_path = tmp_path / "relief.3mf"
    writer = _make_writer(
        str(output_path),
        enable_base_layer_height_modifier=True,
        enable_relief=True,
        base_height_mm=1.2,
        color_height_mm=0.56,
        face_orientation="up",
        nozzle_size="0.4",
    )
    writer.add_mesh(_make_box_mesh(), "Slot 1", (255, 0, 0))

    writer.export()

    with zipfile.ZipFile(output_path) as package:
        assert "Metadata/layer_config_ranges.xml" not in package.namelist()


def test_skip_when_base_zero() -> None:
    assert (
        _call_build_layer_config_ranges_xml(
            base_height_mm=0.0,
            color_height_mm=2.4,
            nozzle_mm=0.4,
            face="down",
        )
        is None
    )


def test_skip_when_coarse_not_greater() -> None:
    assert (
        _call_build_layer_config_ranges_xml(
            base_height_mm=0.8,
            color_height_mm=2.4,
            nozzle_mm=0.08,
            face="down",
            fine_layer_height_mm=0.08,
        )
        is None
    )


def test_skip_when_invalid_face(tmp_path) -> None:
    writer = _make_writer(
        str(tmp_path / "invalid-face.3mf"),
        face_orientation="weird",
    )

    assert writer.face_orientation == "down"


def test_face_up_z_range() -> None:
    xml_bytes = _call_build_layer_config_ranges_xml(
        base_height_mm=2.0,
        color_height_mm=1.6,
        nozzle_mm=0.4,
        face="up",
        initial_layer_height_mm=0.08,
    )

    assert xml_bytes is not None
    min_z, max_z, layer_height = _parse_range(xml_bytes)
    assert min_z == 0.0
    assert max_z == 2.0
    assert layer_height == 0.16


def test_face_up_accounts_for_fixed_initial_layer_height() -> None:
    xml_bytes = _call_build_layer_config_ranges_xml(
        base_height_mm=0.24,
        color_height_mm=0.4,
        nozzle_mm=0.4,
        face="up",
        fine_layer_height_mm=0.08,
        initial_layer_height_mm=0.08,
    )

    assert xml_bytes is not None
    assert _parse_range(xml_bytes)[2] == pytest.approx(0.16)


@pytest.mark.parametrize("initial_layer_height", [None, 0.0, float("nan")])
def test_face_up_skips_when_initial_layer_height_is_unknown_or_invalid(
    initial_layer_height: float | None,
) -> None:
    assert (
        _call_build_layer_config_ranges_xml(
            base_height_mm=0.24,
            color_height_mm=0.4,
            nozzle_mm=0.4,
            face="up",
            fine_layer_height_mm=0.08,
            initial_layer_height_mm=initial_layer_height,
        )
        is None
    )


def test_face_up_skips_when_remaining_backing_has_no_safe_coarse_height() -> None:
    assert (
        _call_build_layer_config_ranges_xml(
            base_height_mm=0.24,
            color_height_mm=0.4,
            nozzle_mm=0.2,
            face="up",
            fine_layer_height_mm=0.08,
            initial_layer_height_mm=0.08,
        )
        is None
    )


def test_face_down_z_range() -> None:
    xml_bytes = _call_build_layer_config_ranges_xml(
        base_height_mm=0.8,
        color_height_mm=2.4,
        nozzle_mm=0.4,
        face="down",
    )

    assert xml_bytes is not None
    min_z, max_z, layer_height = _parse_range(xml_bytes)
    assert min_z == 2.4
    assert max_z == 3.2
    assert layer_height == 0.2


def test_face_double_skips_layer_config() -> None:
    assert (
        _call_build_layer_config_ranges_xml(
            base_height_mm=0.24,
            color_height_mm=0.4,
            nozzle_mm=0.4,
            face="double",
        )
        is None
    )


@pytest.mark.parametrize("nozzle_mm", [0.2, 0.4])
def test_non_divisible_nominal_height_resolves_to_012(nozzle_mm: float) -> None:
    xml_bytes = _call_build_layer_config_ranges_xml(
        base_height_mm=0.24,
        color_height_mm=0.4,
        nozzle_mm=nozzle_mm,
        face="down",
    )

    assert xml_bytes is not None
    assert _parse_range(xml_bytes)[2] == pytest.approx(0.12)


def test_nozzle_02_uses_01mm() -> None:
    xml_bytes = _call_build_layer_config_ranges_xml(
        base_height_mm=0.4,
        color_height_mm=1.2,
        nozzle_mm=0.2,
        face="down",
        fine_layer_height_mm=0.04,
    )

    assert xml_bytes is not None
    _, _, layer_height = _parse_range(xml_bytes)
    assert layer_height == 0.1


def test_skips_when_no_compatible_height_is_within_limits() -> None:
    assert (
        _call_build_layer_config_ranges_xml(
            base_height_mm=0.32,
            color_height_mm=0.4,
            nozzle_mm=0.2,
            face="down",
            fine_layer_height_mm=0.08,
            min_layer_height_mm=0.04,
            max_layer_height_mm=0.14,
        )
        is None
    )


@pytest.mark.parametrize(
    ("bound_name", "bound_value"),
    [
        pytest.param("min_layer_height_mm", float("nan"), id="min-nan"),
        pytest.param("min_layer_height_mm", float("inf"), id="min-positive-inf"),
        pytest.param("min_layer_height_mm", float("-inf"), id="min-negative-inf"),
        pytest.param("max_layer_height_mm", float("nan"), id="max-nan"),
        pytest.param("max_layer_height_mm", float("inf"), id="max-positive-inf"),
        pytest.param("max_layer_height_mm", float("-inf"), id="max-negative-inf"),
    ],
)
def test_skips_when_optional_layer_height_bound_is_non_finite(
    bound_name: str,
    bound_value: float,
) -> None:
    assert (
        _call_build_layer_config_ranges_xml(
            base_height_mm=0.24,
            color_height_mm=0.4,
            nozzle_mm=0.4,
            face="down",
            fine_layer_height_mm=0.08,
            **{bound_name: bound_value},
        )
        is None
    )


def test_equal_distance_candidates_choose_lower_height() -> None:
    xml_bytes = _call_build_layer_config_ranges_xml(
        base_height_mm=0.48,
        color_height_mm=0.4,
        nozzle_mm=0.4,
        face="down",
    )

    assert xml_bytes is not None
    assert _parse_range(xml_bytes)[2] == pytest.approx(0.16)


def test_layer_range_business_result_is_structured_and_legacy_xml_is_derived_from_it() -> None:
    inputs = {
        "base_height_mm": 0.8,
        "color_height_mm": 2.4,
        "nozzle_mm": 0.4,
        "face": "down",
        "fine_layer_height_mm": 0.08,
        "object_id": 1,
        "enable_base_layer_height_modifier": True,
        "backing_infill_density_percent": 60,
    }

    result = writer_module.build_layer_config_ranges_data(**inputs)
    legacy_xml = _call_build_layer_config_ranges_xml(**inputs)

    assert result is not None
    assert result["model_index"] == 1
    assert result["ranges"]
    assert isinstance(result["ranges"][0]["min_z"], float)
    coarse_range = result["ranges"][0]
    assert coarse_range["use_default_extruder"] is True
    assert coarse_range["layer_height_mm"] == pytest.approx(0.2)
    assert "options" not in coarse_range
    protected_result = writer_module.build_layer_config_ranges_data(
        **{**inputs, "solid_depth_mm": 0.1}
    )
    assert protected_result is not None
    protected_ranges = [
        item for item in protected_result["ranges"]
        if item.get("infill_density_percent") is not None
    ]
    assert protected_ranges
    assert all(item["infill_density_percent"] == 100 for item in protected_ranges)
    assert all("options" not in item for item in result["ranges"])
    assert legacy_xml is not None
    legacy_root = ET.fromstring(legacy_xml)
    assert legacy_root.find("./object").attrib["id"] == str(result["model_index"])
    assert len(legacy_root.findall("./object/range")) == len(result["ranges"])


def test_e2e_writer_produces_valid_xml(tmp_path) -> None:
    output_path = tmp_path / "writer-e2e.3mf"
    writer = _make_writer(
        str(output_path),
        base_height_mm=0.8,
        color_height_mm=2.4,
        face_orientation="down",
        nozzle_size="0.4",
    )
    writer.add_mesh(_make_box_mesh(), "Slot 1", (255, 0, 0))

    writer.export()

    with zipfile.ZipFile(output_path) as package:
        model_bytes = package.read("3D/3dmodel.model")
        xml_bytes = package.read("Metadata/layer_config_ranges.xml")
        cut_bytes = package.read("Metadata/cut_information.xml")
        model_settings_bytes = package.read("Metadata/model_settings.config")
        rels_bytes = package.read("3D/_rels/3dmodel.model.rels")

    model_root = ET.fromstring(model_bytes)
    model_ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    build_item = model_root.find("./m:build/m:item", model_ns)
    assert build_item is not None
    build_object_id = build_item.attrib["objectid"]
    assert build_object_id != "1"

    model_settings = ET.fromstring(model_settings_bytes)
    model_object = model_settings.find("./object")
    assert model_object is not None
    assembly_id = model_object.attrib["id"]
    assert assembly_id == build_object_id

    cut_root = ET.fromstring(cut_bytes)
    cut_object = cut_root.find("./object")
    assert cut_object is not None
    assert cut_object.attrib["id"] == assembly_id

    root = ET.fromstring(xml_bytes)
    object_elem = root.find("./object")
    range_elem = root.find("./object/range")
    layer_height_elem = root.find("./object/range/option[@opt_key='layer_height']")

    assert object_elem is not None
    assert object_elem.attrib["id"] == "1"
    assert object_elem.attrib["id"] != assembly_id
    assert range_elem is not None
    assert range_elem.attrib["min_z"] == "2.3999999999999999"
    assert range_elem.attrib["max_z"] == "3.2000000000000002"
    assert layer_height_elem is not None
    assert (layer_height_elem.text or "") == "0.20000000000000001"

    rels = ET.fromstring(rels_bytes)
    rel_targets = {
        rel.attrib["Target"]
        for rel in rels.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
    }
    assert "/Metadata/cut_information.xml" in rel_targets
    assert "/Metadata/layer_config_ranges.xml" in rel_targets


def test_writer_forwards_layer_heights_and_strict_printer_limits(tmp_path, monkeypatch) -> None:
    output_path = tmp_path / "writer-layer-height-limits.3mf"
    writer = _make_writer(
        str(output_path),
        settings={"layer_height": "0.06", "initial_layer_height": "0.20"},
        base_height_mm=0.24,
        color_height_mm=0.4,
        face_orientation="down",
        nozzle_size="0.2",
    )
    writer.add_mesh(_make_box_mesh(), "Slot 1", (255, 0, 0))
    template = writer._get_base_config_template()
    template["initial_layer_print_height"] = "0.10"
    template["min_layer_height"] = ["0.04", "0.06", "invalid"]
    template["max_layer_height"] = ["0.14", "0.12", None]
    writer._custom_template = template

    captured: dict[str, object] = {}

    def capture_builder_call(**kwargs) -> None:
        captured.update(kwargs)
        return None

    monkeypatch.setattr(
        writer_module,
        "build_layer_config_ranges_data",
        capture_builder_call,
    )
    writer.export()

    assert captured["fine_layer_height_mm"] == pytest.approx(0.06)
    assert captured["initial_layer_height_mm"] == pytest.approx(0.20)
    assert captured["min_layer_height_mm"] == pytest.approx(0.06)
    assert captured["max_layer_height_mm"] == pytest.approx(0.12)


def test_writer_skips_face_up_modifier_when_effective_initial_height_is_missing(
    tmp_path,
    monkeypatch,
) -> None:
    output_path = tmp_path / "missing-initial-layer-height.3mf"
    writer = _make_writer(
        str(output_path),
        base_height_mm=0.24,
        color_height_mm=0.4,
        face_orientation="up",
        nozzle_size="0.4",
    )
    writer.add_mesh(_make_box_mesh(), "Slot 1", (255, 0, 0))
    # Exercise the boundary when the selected target cannot resolve first-layer
    # height. Removing a template value alone still leaves the product default.
    read_layout = writer_module.read_project_layout

    def unresolved_first_layer(*args, **kwargs):
        return {**read_layout(*args, **kwargs), "initial_layer_height": None}

    monkeypatch.setattr(writer_module, "read_project_layout", unresolved_first_layer)
    writer.export()

    with zipfile.ZipFile(output_path) as package:
        assert "Metadata/layer_config_ranges.xml" not in package.namelist()


@pytest.mark.parametrize(
    ("slicer", "printer_id"),
    [
        ("BambuStudio", "bambu-h2d"),
        ("OrcaSlicer", "bambu-h2d"),
        ("SnapmakerOrca", "snapmaker-u1"),
        ("ElegooSlicer", "elegoo-cc2"),
        ("AnycubicSlicerNext", "anycubic-kobra-s1"),
        ("FlashStudio", "flashforge-ad5x"),
    ],
)
def test_bambu_family_layer_config_ranges_is_linked(
    tmp_path,
    slicer: str,
    printer_id: str,
) -> None:
    output_path = tmp_path / f"{slicer}.3mf"

    export_scene_with_bambu_metadata(
        scene=_make_scene(),
        output_path=str(output_path),
        slot_names=["Slot 1"],
        preview_colors={"Slot 1": (255, 0, 0)},
        settings={},
        color_mode="4-Color",
        printer_id=printer_id,
        slicer=slicer,
        enable_base_layer_height_modifier=True,
        base_height_mm=0.8,
        color_height_mm=2.4,
        face_orientation="down",
    )

    with zipfile.ZipFile(output_path) as package:
        assert "Metadata/layer_config_ranges.xml" in package.namelist()
        assert "/Metadata/layer_config_ranges.xml" in _model_relationship_targets(package)


@given(
    nozzle=st.sampled_from([0.2, 0.25, 0.4, 0.6, 0.8]),
    fine_layer_height=st.sampled_from([0.04, 0.06, 0.08, 0.12, 0.16]),
    base_ticks=st.integers(min_value=4, max_value=250),
    color_ticks=st.integers(min_value=4, max_value=1000),
    face=st.sampled_from(["up", "down"]),
    max_layer_height=st.sampled_from([0.12, 0.14, 0.28]),
)
def test_layer_config_property_divisibility_bounds_and_z_order(
    nozzle: float,
    fine_layer_height: float,
    base_ticks: int,
    color_ticks: int,
    face: str,
    max_layer_height: float,
) -> None:
    base = base_ticks * 0.02
    color = color_ticks * 0.02
    xml_bytes = _call_build_layer_config_ranges_xml(
        base_height_mm=base,
        color_height_mm=color,
        nozzle_mm=nozzle,
        face=face,
        fine_layer_height_mm=fine_layer_height,
        initial_layer_height_mm=0.04,
        min_layer_height_mm=0.04,
        max_layer_height_mm=max_layer_height,
    )

    if xml_bytes is None:
        return

    min_z, max_z, layer_height = _parse_range(xml_bytes)
    layer_ticks = round(layer_height / 0.02)
    assert layer_height == pytest.approx(layer_ticks * 0.02)
    if face == "up":
        assert (base_ticks - 2) % layer_ticks == 0
        assert (base_ticks - 2) // layer_ticks >= 1
    else:
        assert base_ticks % layer_ticks == 0
        assert base_ticks // layer_ticks >= 2
    assert layer_height > fine_layer_height
    assert layer_height <= max_layer_height + 1e-9
    assert layer_height <= nozzle * 0.7 + 1e-9
    assert max_z > min_z
    if face == "up":
        assert min_z == pytest.approx(0.0)
        assert max_z == pytest.approx(base)
    else:
        assert min_z == pytest.approx(color)
        assert max_z == pytest.approx(color + base)
