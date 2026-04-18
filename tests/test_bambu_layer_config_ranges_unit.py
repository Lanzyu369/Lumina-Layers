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


def _parse_range(xml_bytes: bytes) -> tuple[float, float, float]:
    root = ET.fromstring(xml_bytes)
    object_elem = root.find("./object")
    assert object_elem is not None
    assert object_elem.attrib["id"] == "1"

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
    try:
        return BambuStudio3MFWriter(
            output_path,
            settings={},
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
    )

    assert xml_bytes is not None
    min_z, max_z, layer_height = _parse_range(xml_bytes)
    assert min_z == 0.0
    assert max_z == 2.0
    assert layer_height == 0.2


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


def test_face_double_z_range() -> None:
    xml_bytes = _call_build_layer_config_ranges_xml(
        base_height_mm=0.8,
        color_height_mm=2.4,
        nozzle_mm=0.4,
        face="double",
    )

    assert xml_bytes is not None
    min_z, max_z, layer_height = _parse_range(xml_bytes)
    assert min_z == 2.4
    assert max_z == 3.2
    assert layer_height == 0.2


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
        xml_bytes = package.read("Metadata/layer_config_ranges.xml")

    root = ET.fromstring(xml_bytes)
    object_elem = root.find("./object")
    range_elem = root.find("./object/range")
    layer_height_elem = root.find("./object/range/option[@opt_key='layer_height']")

    assert object_elem is not None
    assert object_elem.attrib["id"] == "1"
    assert range_elem is not None
    assert range_elem.attrib["min_z"] == "2.3999999999999999"
    assert range_elem.attrib["max_z"] == "3.2000000000000002"
    assert layer_height_elem is not None
    assert (layer_height_elem.text or "") == "0.20000000000000001"


@given(
    nozzle=st.sampled_from([0.2, 0.4]),
    base=st.floats(min_value=0.08, max_value=5.0, allow_nan=False, allow_infinity=False),
    color=st.floats(min_value=0.08, max_value=20.0, allow_nan=False, allow_infinity=False),
    face=st.sampled_from(["up", "down", "double"]),
)
def test_layer_config_property_layer_height_and_z_order(
    nozzle: float,
    base: float,
    color: float,
    face: str,
) -> None:
    xml_bytes = _call_build_layer_config_ranges_xml(
        base_height_mm=base,
        color_height_mm=color,
        nozzle_mm=nozzle,
        face=face,
        fine_layer_height_mm=0.04,
    )

    assert xml_bytes is not None
    min_z, max_z, layer_height = _parse_range(xml_bytes)
    assert layer_height == nozzle * 0.5
    assert max_z > min_z
