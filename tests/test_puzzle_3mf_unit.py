"""Unit tests for puzzle 3MF assembly."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import zipfile
import xml.etree.ElementTree as ET

import trimesh
import pytest

from core.puzzle_3mf import (
    PuzzlePiece3MFSource,
    _apply_3mf_transform,
    _parse_3mf_transform,
    assemble_puzzle_3mf,
)
from utils.bambu_3mf_writer import BambuStudio3MFWriter

_CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_PROD_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
_NS = {"m": _CORE_NS, "p": _PROD_NS}


def test_3mf_transform_uses_spec_column_layout() -> None:
    """3MF affine values must map to the documented 4-by-3 layout."""

    transform = _parse_3mf_transform(
        "0 1 0 -1 0 0 0 0 1 10 20 3"
    )

    assert _apply_3mf_transform(transform, 2.0, 5.0, 7.0) == (
        5.0,
        22.0,
        10.0,
    )


def test_assemble_puzzle_3mf_preserves_per_piece_local_models_and_offsets() -> None:
    """Combined puzzle 3MF should keep per-piece local geometry and top-level placement."""

    piece_a1 = _reserve_temp_path(".3mf")
    piece_a2 = _reserve_temp_path(".3mf")
    output_path = _reserve_temp_path(".3mf")
    try:
        _write_piece_package(piece_a1, width=10.0, height=8.0)
        _write_piece_package(piece_a2, width=14.0, height=8.0)

        assemble_puzzle_3mf(
            piece_sources=[
                PuzzlePiece3MFSource(label="A1", threemf_path=str(piece_a1), offset_x_mm=0.0, offset_y_mm=20.0),
                PuzzlePiece3MFSource(label="A2", threemf_path=str(piece_a2), offset_x_mm=12.5, offset_y_mm=20.0),
            ],
            output_path=str(output_path),
            preview_colors=None,
            slot_names=None,
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            enable_wipe_tower_auto_placement=False,
        )

        with zipfile.ZipFile(output_path, "r") as archive:
            content_types = archive.read("[Content_Types].xml").decode("utf-8")
            root_model_text = archive.read("3D/3dmodel.model").decode("utf-8")
            root_model = ET.fromstring(archive.read("3D/3dmodel.model"))
            model_settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
            cut_information = ET.fromstring(archive.read("Metadata/cut_information.xml"))
            first_object_model = ET.fromstring(archive.read("3D/Objects/object_1.model"))
            relationships = archive.read("3D/_rels/3dmodel.model.rels").decode("utf-8")
    finally:
        _cleanup_temp_paths(piece_a1, piece_a2, output_path)

    assert 'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"' in root_model_text
    assert 'requiredextensions="p"' in root_model_text
    assert '/3D/Objects/object_1.model' in content_types
    root_objects = root_model.findall("m:resources/m:object", _NS)
    assert [node.get("id") for node in root_objects] == ["10", "11"]
    component_paths = [
        component.get(f"{{{_PROD_NS}}}path")
        for node in root_objects
        for component in node.findall("m:components/m:component", _NS)
    ]
    assert component_paths == [
        "/3D/Objects/object_1.model",
        "/3D/Objects/object_1.model",
        "/3D/Objects/object_1.model",
        "/3D/Objects/object_1.model",
    ]
    component_ids = [
        component.get("objectid")
        for node in root_objects
        for component in node.findall("m:components/m:component", _NS)
    ]
    assert component_ids == ["2", "3", "4", "5"]

    build_items = root_model.findall("m:build/m:item", _NS)
    assert [item.get("transform") for item in build_items] == [
        "1 0 0 0 1 0 0 0 1 0 20 0",
        "1 0 0 0 1 0 0 0 1 12.5 20 0",
    ]

    settings_objects = model_settings.findall("object")
    assert [_metadata_value(node, "name") for node in settings_objects] == ["A1", "A2"]
    assert [
        [_metadata_value(part, "source_file") for part in node.findall("part")]
        for node in settings_objects
    ] == [
        [output_path.name, output_path.name],
        [output_path.name, output_path.name],
    ]

    assemble_items = model_settings.findall("assemble/assemble_item")
    assert [item.get("transform") for item in assemble_items] == [
        "1 0 0 0 1 0 0 0 1 0 20 0",
        "1 0 0 0 1 0 0 0 1 12.5 20 0",
    ]

    cut_objects = cut_information.findall("object")
    assert [node.get("id") for node in cut_objects] == ["1", "2"]

    first_nodes = first_object_model.findall("m:resources/m:object", _NS)
    assert [node.get("id") for node in first_nodes] == ["2", "3", "4", "5"]
    assert _bounds_width(first_nodes[:2]) == 10.0
    assert _bounds_width(first_nodes[2:]) == 14.0
    assert "/3D/Objects/object_1.model" in relationships
    assert "/3D/Objects/object_2.model" not in relationships


def test_assemble_puzzle_3mf_recomputes_tower_for_final_group() -> None:
    """Final tower metadata and transforms must describe the assembled group."""

    piece_a1 = _reserve_temp_path(".3mf")
    piece_a2 = _reserve_temp_path(".3mf")
    output_path = _reserve_temp_path(".3mf")
    try:
        _write_piece_package(piece_a1, width=50.0, height=60.0)
        _write_piece_package(piece_a2, width=50.0, height=60.0)

        assemble_puzzle_3mf(
            piece_sources=[
                PuzzlePiece3MFSource(
                    label="A1",
                    threemf_path=str(piece_a1),
                    offset_x_mm=10.0,
                    offset_y_mm=10.0,
                ),
                PuzzlePiece3MFSource(
                    label="A2",
                    threemf_path=str(piece_a2),
                    offset_x_mm=120.0,
                    offset_y_mm=10.0,
                ),
            ],
            output_path=str(output_path),
            preview_colors={
                0: [255, 255, 255, 255],
                1: [0, 0, 0, 255],
            },
            slot_names=["Slot 1 (White)", "Slot 2 (Black)"],
            printer_id="bambu-a1-mini",
            slicer="BambuStudio",
            enable_wipe_tower_auto_placement=True,
        )

        with zipfile.ZipFile(output_path, "r") as archive:
            placement = json.loads(
                archive.read("Metadata/lumina_wipe_tower_placement.json")
            )
            settings = json.loads(
                archive.read("Metadata/project_settings.config")
            )
            root_model = ET.fromstring(archive.read("3D/3dmodel.model"))
            model_settings = ET.fromstring(
                archive.read("Metadata/model_settings.config")
            )
    finally:
        _cleanup_temp_paths(piece_a1, piece_a2, output_path)

    assert placement["enabled"] is True
    assert placement["adapted"] is True
    assert placement["requires_manual_adjustment"] is False
    assert placement["model_bounds_mm"] == [10.0, 60.0, 170.0, 120.0]
    assert float(settings["wipe_tower_x"][0]) == placement["tower"]["x_mm"]
    assert float(settings["wipe_tower_y"][0]) == placement["tower"]["y_mm"]
    assert float(settings["prime_tower_width"]) == placement["tower"]["width_mm"]
    difference_index = set(
        settings["different_settings_to_system"][0].split(";")
    )
    assert difference_index >= {
        "prime_tower_width",
        "wipe_tower_rotation_angle",
        "wipe_tower_x",
        "wipe_tower_y",
    }
    assert [
        item.get("transform")
        for item in root_model.findall("m:build/m:item", _NS)
    ] == [
        "1 0 0 0 1 0 0 0 1 10 60 0",
        "1 0 0 0 1 0 0 0 1 120 60 0",
    ]
    assert [
        item.get("transform")
        for item in model_settings.findall("assemble/assemble_item")
    ] == [
        "1 0 0 0 1 0 0 0 1 10 60 0",
        "1 0 0 0 1 0 0 0 1 120 60 0",
    ]


def test_assemble_puzzle_3mf_can_disable_final_tower_placement() -> None:
    """Disabled auto placement must keep final piece offsets and emit no warning."""

    piece_path = _reserve_temp_path(".3mf")
    output_path = _reserve_temp_path(".3mf")
    try:
        _write_piece_package(piece_path, width=50.0, height=60.0)

        assemble_puzzle_3mf(
            piece_sources=[
                PuzzlePiece3MFSource(
                    label="A1",
                    threemf_path=str(piece_path),
                    offset_x_mm=10.0,
                    offset_y_mm=10.0,
                ),
            ],
            output_path=str(output_path),
            preview_colors={0: [255, 255, 255, 255]},
            slot_names=["Slot 1 (White)"],
            printer_id="bambu-a1-mini",
            slicer="BambuStudio",
            enable_wipe_tower_auto_placement=False,
        )

        with zipfile.ZipFile(output_path, "r") as archive:
            placement = json.loads(
                archive.read("Metadata/lumina_wipe_tower_placement.json")
            )
            root_model = ET.fromstring(archive.read("3D/3dmodel.model"))
    finally:
        _cleanup_temp_paths(piece_path, output_path)

    assert placement == {
        "schema_version": 1,
        "enabled": False,
        "available": False,
        "adapted": False,
        "requires_manual_adjustment": False,
        "warning_code": None,
        "reason": "disabled_by_user",
    }
    build_item = root_model.find("m:build/m:item", _NS)
    assert build_item is not None
    assert build_item.get("transform") == "1 0 0 0 1 0 0 0 1 10 10 0"


def test_assemble_puzzle_3mf_restores_global_slot_palette_for_sparse_piece() -> None:
    """Combined puzzle 3MF should map sparse local slots back to the global palette."""

    piece_path = _reserve_temp_path(".3mf")
    output_path = _reserve_temp_path(".3mf")
    try:
        _write_sparse_piece_package(
            piece_path,
            materials=[
                ("Slot 1 (White)", "1"),
                ("Slot 3 (Green)", "2"),
            ],
            filament_colours=["#FFFFFF", "#00AE42"],
        )

        assemble_puzzle_3mf(
            piece_sources=[
                PuzzlePiece3MFSource(label="A1", threemf_path=str(piece_path), offset_x_mm=0.0, offset_y_mm=0.0),
            ],
            output_path=str(output_path),
            preview_colors={
                0: [255, 255, 255, 255],
                1: [0, 0, 0, 255],
                2: [0, 174, 66, 255],
            },
            slot_names=["Slot 1 (White)", "Slot 2 (Black)", "Slot 3 (Green)"],
            printer_id="bambu-h2d",
            slicer="BambuStudio",
        )

        with zipfile.ZipFile(output_path, "r") as archive:
            model_settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
            project_settings = json.loads(archive.read("Metadata/project_settings.config").decode("utf-8"))
            object_model = ET.fromstring(archive.read("3D/Objects/object_1.model"))
    finally:
        _cleanup_temp_paths(piece_path, output_path)

    parts = {
        _metadata_value(part, "name"): _metadata_value(part, "extruder")
        for part in model_settings.findall("./object/part")
    }
    assert parts == {
        "Slot 1 (White)": "1",
        "Slot 3 (Green)": "3",
    }
    assert project_settings["filament_colour"] == ["#FFFFFF", "#000000", "#00AE42"]
    pindices = {
        node.get("name"): node.get("pindex")
        for node in object_model.findall("m:resources/m:object", _NS)
    }
    assert pindices == {
        "Slot 1 (White)": "0",
        "Slot 3 (Green)": "2",
    }


@pytest.mark.parametrize("material_index", [1, 2, 3])
@pytest.mark.parametrize("slicer,printer_id", [
    ("BambuStudio", "bambu-h2d"),
    ("OrcaSlicer", "bambu-h2d"),
    ("SnapmakerOrca", "snapmaker-u1"),
])
def test_single_material_piece_object_uses_its_global_extruder(
    tmp_path: Path, material_index: int, slicer: str, printer_id: str,
) -> None:
    """Slicers must retain the material when collapsing a one-volume object."""

    slot_names = ["赛纳PLA蓝色", "纵维立方PLA红色", "赛纳PLA黄色", "Bambu PLA Basic 玉石白"]
    palette = [(47, 49, 129), (182, 61, 68), (248, 224, 65), (255, 254, 252)]
    material_name = slot_names[material_index]
    piece_path = tmp_path / "single-material-piece.3mf"
    output_path = tmp_path / "puzzle.3mf"
    writer = BambuStudio3MFWriter(
        str(piece_path), printer_id=printer_id, slicer=slicer,
        enable_base_layer_height_modifier=False,
        enable_wipe_tower_auto_placement=False,
    )
    writer.add_mesh(trimesh.creation.box(extents=(10, 10, 2)), material_name, palette[material_index])
    writer.export()

    assemble_puzzle_3mf(
        piece_sources=[PuzzlePiece3MFSource(
            label="C11", threemf_path=str(piece_path), offset_x_mm=10, offset_y_mm=10,
        )],
        output_path=str(output_path),
        preview_colors={index: (*rgb, 255) for index, rgb in enumerate(palette)},
        slot_names=slot_names, printer_id=printer_id, slicer=slicer,
        enable_wipe_tower_auto_placement=False,
    )
    with zipfile.ZipFile(output_path) as archive:
        settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
        meshes = ET.fromstring(archive.read("3D/Objects/object_1.model"))
    obj = settings.find("object")
    assert obj is not None
    parts = obj.findall("part")
    assert len(parts) == 1
    expected_extruder = str(material_index + 1)
    assert _metadata_value(parts[0], "name") == material_name
    assert _metadata_value(parts[0], "extruder") == expected_extruder
    assert _metadata_value(obj, "extruder") == expected_extruder
    mesh = meshes.find("m:resources/m:object", _NS)
    assert mesh is not None and mesh.get("pindex") == str(material_index)


def test_assemble_puzzle_3mf_rebuilds_flush_arrays_for_global_palette() -> None:
    """Combined puzzle purge arrays must match the final global slot count."""

    slot_names = [
        "Slot 1 (White)",
        "Slot 2 (Red)",
        "Slot 3 (Yellow)",
        "Slot 4 (Blue)",
    ]
    stale_eight_slot_settings = {
        "filament_colour": ["#FFFFFF"] * 8,
        "filament_type": ["PLA"] * 8,
        "flush_volumes_vector": ["140"] * 8,
        "flush_volumes_matrix": ["0"] * 64,
    }
    piece_path = _reserve_temp_path(".3mf")
    output_path = _reserve_temp_path(".3mf")
    try:
        _write_sparse_piece_package(
            piece_path,
            materials=[(slot_names[0], "1"), (slot_names[3], "4")],
            filament_colours=["#FFFFFF", "#0000FF"],
            project_settings=stale_eight_slot_settings,
        )

        assemble_puzzle_3mf(
            piece_sources=[
                PuzzlePiece3MFSource(
                    label="A1",
                    threemf_path=str(piece_path),
                    offset_x_mm=0.0,
                    offset_y_mm=0.0,
                ),
            ],
            output_path=str(output_path),
            preview_colors={
                0: [255, 255, 255, 255],
                1: [255, 0, 0, 255],
                2: [255, 255, 0, 255],
                3: [0, 0, 255, 255],
            },
            slot_names=slot_names,
            printer_id="bambu-p2s",
            slicer="OrcaSlicer",
        )

        with zipfile.ZipFile(output_path, "r") as archive:
            project_settings = json.loads(
                archive.read("Metadata/project_settings.config").decode("utf-8")
            )
    finally:
        _cleanup_temp_paths(piece_path, output_path)

    assert len(project_settings["filament_colour"]) == len(slot_names)
    assert len(project_settings["flush_volumes_vector"]) == len(slot_names)
    assert len(project_settings["flush_volumes_matrix"]) == len(slot_names) ** 2


def test_assemble_puzzle_3mf_rebuilds_filament_metadata_from_global_material_names() -> None:
    """Combined puzzle 3MF must not inherit stale PETG metadata for PLA material archives."""

    slot_names = [
        "PLA Pro 白色",
        "PLA Pro 青色",
        "PLA Pro 品红色",
        "PLA Pro 黄色",
        "PLA Pro 黑色",
        "PLA Pro 红色",
        "PLA Pro 蓝色",
        "PLA Pro 嫩绿色",
    ]
    filament_colours = [
        "#F2F4F7",
        "#387AC1",
        "#C44C7C",
        "#F1ED3A",
        "#212427",
        "#9C2E33",
        "#2D428A",
        "#7BC26D",
    ]
    stale_petg_settings = {
        "filament_colour": filament_colours,
        "filament_type": ["PETG"] * len(slot_names),
        "filament_settings_id": [
            "Bambu PETG Basic @BBL X1C 0.2 nozzle"
        ]
        * len(slot_names),
        "nozzle_temperature": ["255"] * len(slot_names),
        "nozzle_temperature_initial_layer": ["245"] * len(slot_names),
        "textured_plate_temp": ["70"] * len(slot_names),
        "default_filament_profile": ["Bambu PETG Basic @BBL X1C 0.2 nozzle"],
    }

    piece_path = _reserve_temp_path(".3mf")
    output_path = _reserve_temp_path(".3mf")
    try:
        _write_sparse_piece_package(
            piece_path,
            materials=[
                (slot_names[0], "1"),
                (slot_names[2], "3"),
            ],
            filament_colours=filament_colours,
            project_settings=stale_petg_settings,
        )

        assemble_puzzle_3mf(
            piece_sources=[
                PuzzlePiece3MFSource(label="A1", threemf_path=str(piece_path), offset_x_mm=0.0, offset_y_mm=0.0),
            ],
            output_path=str(output_path),
            preview_colors={
                index: [int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16), 255]
                for index, hex_color in enumerate(filament_colours)
            },
            slot_names=slot_names,
            printer_id="bambu-p1s",
            slicer="BambuStudio",
            nozzle_size="0.2",
        )

        with zipfile.ZipFile(output_path, "r") as archive:
            project_settings = json.loads(archive.read("Metadata/project_settings.config").decode("utf-8"))
    finally:
        _cleanup_temp_paths(piece_path, output_path)

    assert project_settings["filament_colour"] == filament_colours
    assert project_settings["filament_type"] == ["PLA"] * len(slot_names)
    assert project_settings["filament_settings_id"] == [
        "Bambu PLA Basic @BBL X1C 0.2 nozzle"
    ] * len(slot_names)
    assert project_settings["nozzle_temperature"] == ["220"] * len(slot_names)
    assert project_settings["textured_plate_temp"] == ["55"] * len(slot_names)


def test_assemble_puzzle_3mf_refreshes_metadata_files_and_preview_assets() -> None:
    """Combined puzzle 3MF should rebuild shared metadata and preview PNG assets."""

    piece_path = _reserve_temp_path(".3mf")
    output_path = _reserve_temp_path(".3mf")
    overview_png = b"\x89PNG\r\n\x1a\ncombined-preview"
    try:
        _write_piece_package(piece_path, width=10.0, height=8.0)

        assemble_puzzle_3mf(
            piece_sources=[
                PuzzlePiece3MFSource(label="A1", threemf_path=str(piece_path), offset_x_mm=0.0, offset_y_mm=0.0),
            ],
            output_path=str(output_path),
            preview_colors=None,
            slot_names=["Slot 1 (White)"],
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            overview_png_bytes=overview_png,
        )

        with zipfile.ZipFile(output_path, "r") as archive:
            slice_info = archive.read("Metadata/slice_info.config").decode("utf-8")
            filament_sequence = json.loads(
                archive.read("Metadata/filament_sequence.json").decode("utf-8")
            )

            assert "X-BBL-Client-Type" in slice_info
            assert filament_sequence == {"plate_1": {"sequence": []}}
            for preview_asset_path in (
                "Metadata/plate_1.png",
                "Metadata/plate_no_light_1.png",
                "Metadata/top_1.png",
                "Metadata/pick_1.png",
            ):
                assert archive.read(preview_asset_path) == overview_png
    finally:
        _cleanup_temp_paths(piece_path, output_path)


def test_assemble_puzzle_3mf_uses_registry_device_profile_metadata(tmp_path, monkeypatch) -> None:
    """Combined puzzle 3MF should keep selected machine-registry metadata."""

    registry_root = tmp_path / "machine_registry"
    _write_machine_registry_fixture(
        registry_root,
        source_version="98.76.54.32",
        application_metadata="BambuStudio-98.76.54.32",
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    piece_path = _reserve_temp_path(".3mf")
    output_path = _reserve_temp_path(".3mf")
    try:
        _write_piece_package(piece_path, width=10.0, height=8.0)

        assemble_puzzle_3mf(
            piece_sources=[
                PuzzlePiece3MFSource(label="A1", threemf_path=str(piece_path), offset_x_mm=0.0, offset_y_mm=0.0),
            ],
            output_path=str(output_path),
            preview_colors=None,
            slot_names=["Slot 1 (White)"],
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            nozzle_size="0.4",
            device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
        )

        with zipfile.ZipFile(output_path, "r") as archive:
            root_model = ET.fromstring(archive.read("3D/3dmodel.model"))
            slice_info = ET.fromstring(archive.read("Metadata/slice_info.config"))
    finally:
        _cleanup_temp_paths(piece_path, output_path)

    root_metadata = {
        node.attrib["name"]: (node.text or "")
        for node in root_model.findall("m:metadata", {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"})
    }
    assert root_metadata["Application"] == "BambuStudio-98.76.54.32"
    header = slice_info.find("header")
    assert header is not None
    values = {
        item.attrib["key"]: item.attrib["value"]
        for item in header.findall("header_item")
    }
    assert values["X-BBL-Client-Version"] == "98.76.54.32"


def test_assemble_puzzle_3mf_excludes_layer_config_ranges_xml() -> None:
    """Combined puzzle package should not carry the single-piece layer-config modifier file."""

    piece_path = _reserve_temp_path(".3mf")
    output_path = _reserve_temp_path(".3mf")
    try:
        writer = BambuStudio3MFWriter(
            output_path=str(piece_path),
            settings={},
            color_mode="4-Color",
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            nozzle_size="0.4",
            base_height_mm=0.8,
            color_height_mm=2.4,
            face_orientation="down",
        )
        writer.add_mesh(
            trimesh.creation.box(extents=(10.0, 10.0, 1.0)),
            "Slot 1 (White)",
            (255, 255, 255),
        )
        writer.export()

        with zipfile.ZipFile(piece_path, "r") as piece_archive:
            assert "Metadata/layer_config_ranges.xml" in piece_archive.namelist()

        assemble_puzzle_3mf(
            piece_sources=[
                PuzzlePiece3MFSource(label="A1", threemf_path=str(piece_path), offset_x_mm=0.0, offset_y_mm=0.0),
            ],
            output_path=str(output_path),
            preview_colors={0: [255, 255, 255, 255]},
            slot_names=["Slot 1 (White)"],
            printer_id="bambu-h2d",
            slicer="BambuStudio",
        )

        with zipfile.ZipFile(output_path, "r") as archive:
            assert "Metadata/layer_config_ranges.xml" not in archive.namelist()
    finally:
        _cleanup_temp_paths(piece_path, output_path)


def _write_piece_package(path, *, width: float, height: float) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model", _piece_root_model_bytes())
        archive.writestr("3D/Objects/object_1.model", _piece_object_model_bytes(width=width, height=height))
        archive.writestr("Metadata/model_settings.config", _piece_model_settings_bytes(width=width, height=height))
        archive.writestr("Metadata/project_settings.config", b"{}")
        archive.writestr("Metadata/slice_info.config", b"<config/>")
        archive.writestr("Metadata/filament_sequence.json", b"{}")
        archive.writestr("Metadata/cut_information.xml", _cut_information_bytes())
        archive.writestr("3D/_rels/3dmodel.model.rels", _relationships_bytes())
        archive.writestr("_rels/.rels", _root_relationships_bytes())
        archive.writestr("[Content_Types].xml", b"<Types/>")


def _write_sparse_piece_package(
    path,
    *,
    materials: list[tuple[str, str]],
    filament_colours: list[str],
    project_settings: dict[str, object] | None = None,
) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model", _piece_root_model_bytes())
        archive.writestr("3D/Objects/object_1.model", _sparse_piece_object_model_bytes(materials))
        archive.writestr("Metadata/model_settings.config", _sparse_piece_model_settings_bytes(materials))
        archive.writestr(
            "Metadata/project_settings.config",
            json.dumps(
                project_settings
                or {
                    "filament_colour": filament_colours,
                    "filament_type": ["PLA"] * len(filament_colours),
                },
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        archive.writestr("Metadata/slice_info.config", b"<config/>")
        archive.writestr("Metadata/filament_sequence.json", b"{}")
        archive.writestr("Metadata/cut_information.xml", _cut_information_bytes())
        archive.writestr("3D/_rels/3dmodel.model.rels", _relationships_bytes())
        archive.writestr("_rels/.rels", _root_relationships_bytes())
        archive.writestr("[Content_Types].xml", b"<Types/>")


def _write_machine_registry_fixture(
    registry_root: Path,
    *,
    source_version: str,
    application_metadata: str,
) -> None:
    template_path = (
        registry_root
        / "slicers"
        / "BambuStudio"
        / source_version
        / "metadata_templates"
        / "h2d_0_4.json"
    )
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text(
        json.dumps({"printer_model": "Bambu Lab H2D"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (registry_root / "registry.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-06-09T00:00:00+08:00",
                "slicers": [
                    {
                        "slicer_id": "BambuStudio",
                        "display_name": "Bambu Studio",
                        "source_kind": "local_install",
                        "source_version": source_version,
                        "profile_format": "bambu_orca",
                        "application_metadata": application_metadata,
                        "sidecar_policy": "bambu_studio",
                        "machines": [
                            {
                                "machine_profile_id": "BambuStudio:bbl:bambu-lab-h2d",
                                "display_name": "Bambu Lab H2D",
                                "brand": "Bambu Lab",
                                "vendor_key": "BBL",
                                "bed_width": 350,
                                "bed_depth": 320,
                                "bed_height": 325,
                                "thumbnail": "",
                                "nozzles": [
                                    {
                                        "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
                                        "nozzle_size": "0.4",
                                        "source_profile_name": "Bambu Lab H2D 0.4 nozzle",
                                        "template": template_path.relative_to(registry_root).as_posix(),
                                        "revision": "sha256:abc",
                                        "supported": True,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _piece_root_model_bytes() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        b'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">'
        b"<resources>"
        b'<object id="10" type="model"><components>'
        b'<component p:path="/3D/Objects/object_1.model" objectid="2"/>'
        b'<component p:path="/3D/Objects/object_1.model" objectid="3"/>'
        b"</components></object>"
        b"</resources>"
        b'<build><item objectid="10" printable="1"/></build>'
        b"</model>"
    )


def _reserve_temp_path(suffix: str) -> Path:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return Path(path)


def _cleanup_temp_paths(*paths: Path) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _piece_object_model_bytes(*, width: float, height: float) -> bytes:
    mesh_template = (
        '<object id="{object_id}" name="{name}" type="model">'
        "<mesh>"
        "<vertices>"
        '<vertex x="0" y="0" z="0"/>'
        '<vertex x="{width}" y="0" z="0"/>'
        '<vertex x="0" y="{height}" z="0"/>'
        "</vertices>"
        "<triangles>"
        '<triangle v1="0" v2="1" v3="2"/>'
        "</triangles>"
        "</mesh>"
        "</object>"
    )
    payload = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        "<resources>"
        + mesh_template.format(object_id=2, name="Slot 1 (White)", width=width, height=height)
        + mesh_template.format(object_id=3, name="Slot 2 (Black)", width=width, height=height)
        + "</resources>"
        "</model>"
    )
    return payload.encode("utf-8")


def _sparse_piece_object_model_bytes(materials: list[tuple[str, str]]) -> bytes:
    object_nodes = []
    for index, (material_name, _) in enumerate(materials, start=2):
        object_nodes.append(
            (
                f'<object id="{index}" name="{material_name}" type="model">'
                "<mesh>"
                "<vertices>"
                '<vertex x="0" y="0" z="0"/>'
                '<vertex x="1" y="0" z="0"/>'
                '<vertex x="0" y="1" z="0"/>'
                "</vertices>"
                "<triangles>"
                '<triangle v1="0" v2="1" v3="2"/>'
                "</triangles>"
                "</mesh>"
                "</object>"
            )
        )
    payload = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        "<resources>"
        + "".join(object_nodes)
        + "</resources>"
        "</model>"
    )
    return payload.encode("utf-8")


def _piece_model_settings_bytes(*, width: float, height: float) -> bytes:
    payload = f"""
<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="10">
    <metadata key="extruder" value="1"/>
    <part id="2" subtype="normal_part">
      <metadata key="name" value="Slot 1 (White)"/>
      <metadata key="source_file" value="piece.3mf"/>
      <metadata key="source_object_id" value="0"/>
      <metadata key="source_volume_id" value="0"/>
      <metadata key="matrix" value="1 0 0 {width} 0 1 0 {height} 0 0 1 2 0 0 0 1"/>
      <metadata key="extruder" value="1"/>
      <mesh_stat face_count="12" />
    </part>
    <part id="3" subtype="normal_part">
      <metadata key="name" value="Slot 2 (Black)"/>
      <metadata key="source_file" value="piece.3mf"/>
      <metadata key="source_object_id" value="0"/>
      <metadata key="source_volume_id" value="1"/>
      <metadata key="matrix" value="1 0 0 {width} 0 1 0 {height} 0 0 1 2 0 0 0 1"/>
      <metadata key="extruder" value="2"/>
      <mesh_stat face_count="10" />
    </part>
  </object>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value=""/>
    <metadata key="locked" value="false"/>
    <metadata key="filament_map_mode" value="Auto For Flush"/>
    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>
    <metadata key="thumbnail_no_light_file" value="Metadata/plate_no_light_1.png"/>
    <metadata key="top_file" value="Metadata/top_1.png"/>
    <metadata key="pick_file" value="Metadata/pick_1.png"/>
  </plate>
</config>
"""
    return payload.strip().encode("utf-8")


def _sparse_piece_model_settings_bytes(materials: list[tuple[str, str]]) -> bytes:
    parts = []
    for index, (material_name, extruder) in enumerate(materials, start=2):
        parts.append(
            f"""
    <part id="{index}" subtype="normal_part">
      <metadata key="name" value="{material_name}"/>
      <metadata key="source_file" value="piece_sparse.3mf"/>
      <metadata key="source_object_id" value="0"/>
      <metadata key="source_volume_id" value="{index - 2}"/>
      <metadata key="matrix" value="1 0 0 1 0 1 0 1 0 0 1 2 0 0 0 1"/>
      <metadata key="extruder" value="{extruder}"/>
      <mesh_stat face_count="1" />
    </part>"""
        )

    payload = f"""
<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="10">
    <metadata key="extruder" value="1"/>
{''.join(parts)}
  </object>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value=""/>
    <metadata key="locked" value="false"/>
    <metadata key="filament_map_mode" value="Auto For Flush"/>
    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>
    <metadata key="thumbnail_no_light_file" value="Metadata/plate_no_light_1.png"/>
    <metadata key="top_file" value="Metadata/top_1.png"/>
    <metadata key="pick_file" value="Metadata/pick_1.png"/>
  </plate>
</config>
"""
    return payload.strip().encode("utf-8")


def _cut_information_bytes() -> bytes:
    return (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        b"<objects>"
        b'<object id="1"><cut_id id="0" check_sum="1" connectors_cnt="0"/></object>'
        b"</objects>"
    )


def _relationships_bytes() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Target="/3D/Objects/object_1.model" Id="rel-1" '
        b'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        b"</Relationships>"
    )


def _root_relationships_bytes() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        b'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        b"</Relationships>"
    )


def _bounds_width(nodes: list[ET.Element]) -> float:
    xs: list[float] = []
    for node in nodes:
        for vertex in node.findall("m:mesh/m:vertices/m:vertex", _NS):
            xs.append(float(vertex.get("x", "0")))
    return max(xs) - min(xs)


def _metadata_value(node: ET.Element, key: str) -> str | None:
    for metadata_node in node.findall("metadata"):
        if metadata_node.get("key") == key:
            return metadata_node.get("value")
    return None
