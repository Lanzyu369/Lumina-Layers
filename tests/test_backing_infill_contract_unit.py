"""Regression tests for backing thickness and viewing-surface infill rules."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
import zipfile

import pytest
import trimesh
from pydantic import ValidationError

from api.schemas.converter import ConvertGenerateRequest, PuzzleGenerateRequest
from config import PrinterConfig
from core.backing_infill import (
    get_viewing_surface_solid_z_ranges,
    resolve_effective_backing_infill_density_percent,
)
from utils.bambu_3mf_writer import (
    build_layer_config_ranges_xml,
    export_scene_with_bambu_metadata,
)


def _options_by_range(xml_bytes: bytes) -> list[tuple[float, float, dict[str, str]]]:
    root = ET.fromstring(xml_bytes)
    result: list[tuple[float, float, dict[str, str]]] = []
    for range_element in root.findall("./object/range"):
        options = {
            option.attrib["opt_key"]: option.text or ""
            for option in range_element.findall("option")
        }
        result.append(
            (
                float(range_element.attrib["min_z"]),
                float(range_element.attrib["max_z"]),
                options,
            )
        )
    return result


def test_generate_schema_accepts_10_mm_and_rejects_above_boundary() -> None:
    request = ConvertGenerateRequest(lut_name="test_lut", spacer_thick=10.0)

    assert request.spacer_thick == 10.0
    assert request.backing_infill_density_percent == 100

    with pytest.raises(ValidationError):
        ConvertGenerateRequest(lut_name="test_lut", spacer_thick=10.001)


@pytest.mark.parametrize("density", [4, 101])
def test_generate_schema_rejects_unsafe_backing_infill_density(
    density: int,
) -> None:
    with pytest.raises(ValidationError):
        ConvertGenerateRequest(
            lut_name="test_lut",
            backing_infill_density_percent=density,
        )


def test_generate_schema_rejects_sparse_relief_and_sparse_puzzle() -> None:
    with pytest.raises(ValidationError, match="relief mode"):
        ConvertGenerateRequest(
            lut_name="test_lut",
            enable_relief=True,
            backing_infill_density_percent=20,
        )

    with pytest.raises(ValidationError, match="puzzle generation"):
        PuzzleGenerateRequest(
            target_height_mm=100.0,
            params=ConvertGenerateRequest(
                lut_name="test_lut",
                backing_infill_density_percent=20,
            )
        )


def test_canonical_solid_depth_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    assert PrinterConfig.VIEWING_SURFACE_SOLID_DEPTH_MM == 3.0
    monkeypatch.setattr(
        PrinterConfig,
        "VIEWING_SURFACE_SOLID_DEPTH_MM",
        4.0,
    )

    ranges = get_viewing_surface_solid_z_ranges(
        base_height_mm=10.0,
        color_height_mm=0.4,
        face="down",
    )

    assert ranges == pytest.approx([(0.0, 4.4)])


@pytest.mark.parametrize(
    ("face", "expected"),
    [
        ("down", [(0.0, 3.4)]),
        ("up", [(7.0, 10.4)]),
        ("double", [(0.0, 3.4), (7.4, 10.8)]),
    ],
)
def test_viewing_surface_solid_ranges_follow_orientation(
    face: str,
    expected: list[tuple[float, float]],
) -> None:
    ranges = get_viewing_surface_solid_z_ranges(
        base_height_mm=10.0,
        color_height_mm=0.4,
        face=face,
    )

    assert ranges == pytest.approx(expected)


@pytest.mark.parametrize(
    ("face", "base_height"),
    [("down", 3.0), ("up", 3.0), ("double", 6.0)],
)
def test_fully_protected_backing_promotes_global_density_to_solid(
    face: str,
    base_height: float,
) -> None:
    assert (
        resolve_effective_backing_infill_density_percent(
            20,
            base_height_mm=base_height,
            face=face,
        )
        == 100
    )


def test_layer_config_splits_coarse_and_solid_overrides_without_overlap() -> None:
    xml_bytes = build_layer_config_ranges_xml(
        base_height_mm=10.0,
        color_height_mm=0.4,
        nozzle_mm=0.4,
        face="down",
        backing_infill_density_percent=20,
    )

    assert xml_bytes is not None
    ranges = _options_by_range(xml_bytes)
    assert [(start, end) for start, end, _options in ranges] == pytest.approx(
        [(0.0, 0.4), (0.4, 3.4), (3.4, 10.4)]
    )
    assert ranges[0][2] == {
        "layer_height": "0.080000000000000002",
        "sparse_infill_density": "100%",
    }
    assert ranges[1][2]["sparse_infill_density"] == "100%"
    assert ranges[1][2]["layer_height"] == ranges[2][2]["layer_height"]
    assert all("layer_height" in options for _start, _end, options in ranges)
    assert "sparse_infill_density" not in ranges[2][2]


def test_exported_3mf_contains_sparse_global_and_solid_surface_metadata(
    tmp_path,
) -> None:
    output_path = tmp_path / "backing-infill.3mf"
    scene = trimesh.Scene()
    mesh = trimesh.creation.box(extents=(20.0, 20.0, 10.4))
    mesh.apply_translation((0.0, 0.0, 5.2))
    scene.add_geometry(mesh, geom_name="White")

    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=str(output_path),
        slot_names=["White"],
        preview_colors={"White": [255, 255, 255, 255]},
        settings={"sparse_infill_density": "100%"},
        enable_base_layer_height_modifier=False,
        base_height_mm=10.0,
        color_height_mm=0.4,
        face_orientation="down",
        backing_infill_density_percent=20,
    )

    with zipfile.ZipFile(output_path, "r") as archive:
        project_settings = json.loads(
            archive.read("Metadata/project_settings.config").decode("utf-8")
        )
        layer_ranges = _options_by_range(
            archive.read("Metadata/layer_config_ranges.xml")
        )
        model_settings = archive.read("Metadata/model_settings.config").decode(
            "utf-8"
        )

    assert project_settings["sparse_infill_density"] == "20%"
    assert project_settings["top_shell_layers"] == "1"
    assert layer_ranges == [
        (
            0.0,
            3.4,
            {
                "layer_height": "0.080000000000000002",
                "sparse_infill_density": "100%",
            },
        )
    ]
    assert "White" in model_settings


def test_exported_thin_backing_stays_globally_solid(tmp_path) -> None:
    output_path = tmp_path / "thin-backing.3mf"
    scene = trimesh.Scene()
    scene.add_geometry(
        trimesh.creation.box(extents=(10.0, 10.0, 3.4)),
        geom_name="White",
    )

    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=str(output_path),
        slot_names=["White"],
        preview_colors={"White": [255, 255, 255, 255]},
        enable_base_layer_height_modifier=False,
        base_height_mm=3.0,
        color_height_mm=0.4,
        face_orientation="down",
        backing_infill_density_percent=20,
    )

    with zipfile.ZipFile(output_path, "r") as archive:
        project_settings = json.loads(
            archive.read("Metadata/project_settings.config").decode("utf-8")
        )
        names = set(archive.namelist())

    assert project_settings["sparse_infill_density"] == "100%"
    assert project_settings["top_shell_layers"] == "0"
    assert "Metadata/layer_config_ranges.xml" not in names
