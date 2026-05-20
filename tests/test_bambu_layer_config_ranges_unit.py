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


@pytest.mark.parametrize(
    ("slicer", "printer_id"),
    [
        ("BambuStudio", "bambu-h2d"),
        ("OrcaSlicer", "bambu-h2d"),
        ("SnapmakerOrca", "snapmaker-u1"),
        ("ElegooSlicer", "elegoo-cc2"),
        ("AnycubicSlicerNext", "anycubic-kobra-s1"),
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
