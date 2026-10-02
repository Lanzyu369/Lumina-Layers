from __future__ import annotations

import gc
import json
import sys
from types import SimpleNamespace
import weakref
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pytest
import shapely.geometry as sg
import trimesh

from core.layered_coordinate_domain import (
    LAYERED_COORDINATE_DOMAIN_CERTIFIED_KEY,
    read_layered_coordinate_domain,
)
from core.vector_layer_geometry import (
    VectorLayerGeometryPolicy,
    build_vector_layered_volume,
)
from core.vector_engine import VectorAnalysis, VectorProcessor
from core.model_surface.assembly import (
    MODEL_SURFACE_DISPLAY_LAYER_HEIGHTS_KEY,
    MODEL_SURFACE_DISPLAY_Z_BOUNDS_KEY,
    MODEL_SURFACE_LOGICAL_XY_BOUNDS_KEY,
    OverlaySceneResult,
    PreparedSurfacePattern,
    _pattern_layer_heights_mm,
    _pattern_xy_bounds_mm,
    _pattern_z_bounds_mm,
    apply_model_transform_to_overlay_scene,
    build_embedded_overlay_scene,
    cut_surface_pocket,
    orient_overlay_scene_for_print,
)
from core.model_surface.pipeline import (
    _build_pattern_scene,
    _build_scene_printable_footprint,
    build_surface_overlay_scene,
)
from core.model_surface.types import ModelSurfaceError, PlaneFrame, SurfaceFootprint
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata


def _upward_horizontal_area_at_z(
    mesh: trimesh.Trimesh,
    z_mm: float,
) -> float:
    triangle_z = np.asarray(mesh.vertices)[np.asarray(mesh.faces), 2]
    on_plane = np.all(np.isclose(triangle_z, z_mm, atol=1e-6), axis=1)
    upward = np.asarray(mesh.face_normals)[:, 2] > 1.0 - 1e-6
    return float(np.asarray(mesh.area_faces)[on_plane & upward].sum())


def _edge_incidence_counts(mesh: trimesh.Trimesh) -> np.ndarray:
    edges = np.asarray(mesh.edges_sorted, dtype=np.int64)
    _unique, counts = np.unique(edges, axis=0, return_counts=True)
    return counts


def _rotation_y(degrees: float) -> np.ndarray:
    return trimesh.transformations.rotation_matrix(
        np.deg2rad(float(degrees)),
        [0.0, 1.0, 0.0],
    )


def _contact_pattern_overlay(
    *,
    surface_tilt_y_deg: float,
) -> OverlaySceneResult:
    full_matrix = np.array([[[0, -1], [-1, 0]]], dtype=np.int16)
    pattern = _build_pattern_scene(
        {
            "full_matrix": full_matrix,
            "slot_names": ["Artwork"],
            "preview_colors": {0: [255, 0, 0, 255]},
            "target_h": 2,
            "pixel_scale": 1.0,
            "color_layers": 1,
            "layer_height_mm": 0.08,
            "bambu_face_orientation": "down",
        }
    )
    surface_rotation = _rotation_y(surface_tilt_y_deg)
    base = trimesh.creation.box(extents=(2.0, 2.0, 3.0))
    base.apply_transform(surface_rotation)

    def rotated(vector: tuple[float, float, float]) -> tuple[float, float, float]:
        homogeneous = np.asarray([*vector, 0.0], dtype=np.float64)
        return tuple((surface_rotation @ homogeneous)[:3])

    surface_origin = tuple(
        (surface_rotation @ np.asarray([0.0, 0.0, 1.5, 1.0]))[:3]
    )
    footprint = SurfaceFootprint(
        frame=PlaneFrame(
            origin=surface_origin,
            normal=rotated((0.0, 0.0, 1.0)),
            u_axis=rotated((1.0, 0.0, 0.0)),
            v_axis=rotated((0.0, 1.0, 0.0)),
        ),
        outer=((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)),
        holes=(),
        bounds_min=(-1.0, -1.0),
        bounds_max=(1.0, 1.0),
        bounds_width_mm=2.0,
        bounds_height_mm=2.0,
        area_mm2=4.0,
        hole_count=0,
    )
    return build_embedded_overlay_scene(
        base_mesh=base,
        pattern_scene=pattern,
        footprint=footprint,
        pocket_depth_mm=0.08,
        base_slot_name="surface_base",
        base_color=(245, 245, 245),
        allow_uncut_base=True,
        _take_pattern_ownership=True,
    )


def _object_mesh_from_3mf(
    output_path,
    *,
    object_name: str,
) -> tuple[ET.Element, trimesh.Trimesh]:
    namespace = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    with zipfile.ZipFile(output_path) as package:
        root = ET.fromstring(package.read("3D/Objects/object_1.model"))
    objects = root.findall("./m:resources/m:object", namespace)
    exported = next(item for item in objects if item.attrib.get("name") == object_name)
    vertices = np.asarray(
        [
            [float(vertex.attrib[axis]) for axis in ("x", "y", "z")]
            for vertex in exported.findall("./m:mesh/m:vertices/m:vertex", namespace)
        ],
        dtype=np.float64,
    )
    faces = np.asarray(
        [
            [int(face.attrib[index]) for index in ("v1", "v2", "v3")]
            for face in exported.findall("./m:mesh/m:triangles/m:triangle", namespace)
        ],
        dtype=np.int64,
    )
    return exported, trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def test_build_embedded_overlay_scene_keeps_bounds_and_adds_base_slot():
    base = trimesh.creation.box(extents=(20.0, 10.0, 3.0))
    color = trimesh.creation.box(extents=(20.0, 10.0, 0.4))
    color.apply_translation((0.0, 0.0, 0.2))
    pattern = trimesh.Scene({"color_ff0000": color})
    footprint = SurfaceFootprint(
        frame=PlaneFrame(
            origin=(0.0, 0.0, 1.5),
            normal=(0.0, 0.0, 1.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
        ),
        outer=((-10.0, -5.0), (10.0, -5.0), (10.0, 5.0), (-10.0, 5.0), (-10.0, -5.0)),
        holes=(),
        bounds_min=(-10.0, -5.0),
        bounds_max=(10.0, 5.0),
        bounds_width_mm=20.0,
        bounds_height_mm=10.0,
        area_mm2=200.0,
        hole_count=0,
    )

    result = build_embedded_overlay_scene(
        base_mesh=base,
        pattern_scene=pattern,
        footprint=footprint,
        pocket_depth_mm=0.4,
        base_slot_name="surface_base",
        base_color=(245, 245, 245),
        allow_uncut_base=True,
    )

    assert "surface_base" in result.scene.geometry
    assert "color_ff0000" in result.scene.geometry
    assert result.slot_names == ["surface_base", "color_ff0000"]
    np.testing.assert_allclose(
        np.asarray(result.scene.bounds)[:, :2],
        np.asarray(base.bounds)[:, :2],
    )
    assert result.scene.bounds[0][2] == pytest.approx(base.bounds[0][2])
    assert result.scene.bounds[1][2] == pytest.approx(base.bounds[1][2])


def test_build_embedded_overlay_scene_preserves_transparent_canvas_surface():
    full_matrix = np.full((1, 10, 20), -1, dtype=np.int16)
    full_matrix[0, 1:3, 2:6] = 0
    pattern = _build_pattern_scene(
        {
            "full_matrix": full_matrix,
            "slot_names": ["Artwork"],
            "preview_colors": {0: [255, 0, 0, 255]},
            "target_h": 10,
            "pixel_scale": 1.0,
            "color_layers": 1,
            "layer_height_mm": 0.08,
            "bambu_face_orientation": "down",
        }
    )
    base = trimesh.creation.box(extents=(20.0, 10.0, 3.0))
    footprint = SurfaceFootprint(
        frame=PlaneFrame(
            origin=(0.0, 0.0, 1.5),
            normal=(0.0, 0.0, 1.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
        ),
        outer=((-10.0, -5.0), (10.0, -5.0), (10.0, 5.0), (-10.0, 5.0)),
        holes=(),
        bounds_min=(-10.0, -5.0),
        bounds_max=(10.0, 5.0),
        bounds_width_mm=20.0,
        bounds_height_mm=10.0,
        area_mm2=200.0,
        hole_count=0,
    )

    result = build_embedded_overlay_scene(
        base_mesh=base,
        pattern_scene=pattern,
        footprint=footprint,
        pocket_depth_mm=0.08,
        base_slot_name="surface_base",
        base_color=(245, 245, 245),
    )

    cut_base = result.scene.geometry["surface_base"]
    assert _upward_horizontal_area_at_z(cut_base, 1.5) == pytest.approx(
        192.0,
        abs=1e-5,
    )


def test_build_embedded_overlay_scene_preserves_source_orientation_and_canvas_margins():
    full_matrix = np.full((1, 10, 20), -1, dtype=np.int16)
    full_matrix[0, 1:3, 2:6] = 0
    pattern = _build_pattern_scene(
        {
            "full_matrix": full_matrix,
            "slot_names": ["Artwork"],
            "preview_colors": {0: [255, 0, 0, 255]},
            "target_h": 10,
            "pixel_scale": 1.0,
            "color_layers": 1,
            "layer_height_mm": 0.08,
            "bambu_face_orientation": "down",
        }
    )
    assert pattern.metadata[MODEL_SURFACE_LOGICAL_XY_BOUNDS_KEY] == pytest.approx(
        (0.0, 0.0, 20.0, 10.0)
    )
    base = trimesh.creation.box(extents=(20.0, 10.0, 3.0))
    footprint = SurfaceFootprint(
        frame=PlaneFrame(
            origin=(0.0, 0.0, 1.5),
            normal=(0.0, 0.0, 1.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
        ),
        outer=((-10.0, -5.0), (10.0, -5.0), (10.0, 5.0), (-10.0, 5.0)),
        holes=(),
        bounds_min=(-10.0, -5.0),
        bounds_max=(10.0, 5.0),
        bounds_width_mm=20.0,
        bounds_height_mm=10.0,
        area_mm2=200.0,
        hole_count=0,
    )

    result = build_embedded_overlay_scene(
        base_mesh=base,
        pattern_scene=pattern,
        footprint=footprint,
        pocket_depth_mm=0.08,
        base_slot_name="surface_base",
        base_color=(245, 245, 245),
        allow_uncut_base=True,
    )

    artwork_bounds = np.asarray(result.scene.geometry["Artwork"].bounds)
    np.testing.assert_allclose(artwork_bounds[:, 0], [-8.0, -4.0], atol=1e-6)
    np.testing.assert_allclose(artwork_bounds[:, 1], [2.0, 4.0], atol=1e-6)
    np.testing.assert_allclose(
        artwork_bounds[1, :2] - artwork_bounds[0, :2],
        [4.0, 2.0],
        atol=1e-6,
    )


def test_raster_pattern_publishes_one_certified_coordinate_domain() -> None:
    full_matrix = np.zeros((2, 3, 5), dtype=np.int16)
    pattern = _build_pattern_scene(
        {
            "full_matrix": full_matrix,
            "slot_names": ["Artwork"],
            "preview_colors": {0: [255, 0, 0, 255]},
            "target_h": 3,
            "pixel_scale": 0.2,
            "color_layers": 2,
            "layer_height_mm": 0.08,
            "bambu_face_orientation": "down",
        }
    )

    domain = read_layered_coordinate_domain(
        pattern.scene,
        require_certified=True,
    )
    assert domain is not None
    assert domain.xy_grid_mm == 0.2
    assert domain.canvas_max_units == (5, 3)
    assert domain.layer_heights_mm == (0.08, 0.08)
    assert _pattern_xy_bounds_mm(pattern) == domain.writer_canvas_bounds_mm
    assert _pattern_z_bounds_mm(pattern) == domain.writer_z_bounds_mm


def test_pattern_bounds_reject_malformed_certification_marker() -> None:
    pattern = trimesh.Scene({"Artwork": trimesh.creation.box(extents=(1, 1, 1))})
    pattern.metadata[LAYERED_COORDINATE_DOMAIN_CERTIFIED_KEY] = True

    with pytest.raises(ModelSurfaceError, match="coordinate-domain"):
        _pattern_xy_bounds_mm(pattern)


def test_native_vector_pattern_is_normalized_before_surface_assembly():
    artwork = trimesh.creation.box(extents=(2.0, 6.0, 0.08))
    artwork.apply_translation((3.0, 5.0, 0.04))
    export_mirror = np.asarray(
        [
            [-1.0, 0.0, 0.0, 0.0],
            [0.0, -1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    artwork.apply_transform(export_mirror)
    source_scene = trimesh.Scene({"Black": artwork})

    pattern = _build_pattern_scene(
        {
            "is_svg_vector": True,
            "scene": source_scene,
            "vector_analysis": SimpleNamespace(
                slot_names=("Black",),
                num_channels=1,
                bbox=(0.0, 0.0, 20.0, 10.0),
                scale_factor=1.0,
                num_layers=1,
                matched_shapes=(
                    {
                        "geometry": sg.box(2.0, 2.0, 4.0, 8.0),
                        "recipe": (0,),
                    },
                ),
            ),
            "layer_height_mm": 0.08,
        }
    )

    np.testing.assert_allclose(
        source_scene.geometry["Black"].bounds[:, 0],
        [-4.0, -2.0],
        atol=1e-6,
    )
    np.testing.assert_allclose(
        pattern.geometry["Black"].bounds[:, 0],
        [2.0, 4.0],
        atol=1e-6,
    )


@pytest.mark.parametrize(
    ("canvas_width", "canvas_height", "target_width_mm"),
    [
        pytest.param(1156.0, 819.0, 60.0, id="reported-svg"),
        pytest.param(40000.0, 1.0, 10.0, id="positive-half-grid"),
    ],
)
def test_native_vector_pattern_uses_canonical_grid_canvas_bounds(
    canvas_width,
    canvas_height,
    target_width_mm,
):
    scale_factor = target_width_mm / canvas_width
    artwork = build_vector_layered_volume(
        [
            {
                "geometry": sg.box(0.0, 0.0, canvas_width, canvas_height),
                "height": 0.08,
                "z_offset": 0.0,
            }
        ],
        scale_mm_per_svg_unit=scale_factor,
    )
    assert artwork is not None
    artwork.apply_transform(
        np.asarray(
            [
                [-1.0, 0.0, 0.0, 0.0],
                [0.0, -1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
    )
    source_scene = trimesh.Scene({"Black": artwork})

    pattern = _build_pattern_scene(
        {
            "is_svg_vector": True,
            "scene": source_scene,
            "vector_analysis": SimpleNamespace(
                slot_names=("Black",),
                num_channels=1,
                bbox=(0.0, 0.0, canvas_width, canvas_height),
                scale_factor=scale_factor,
                num_layers=1,
                matched_shapes=(),
            ),
            "layer_height_mm": 0.08,
            "bambu_face_orientation": "down",
        }
    )

    grid_mm = VectorLayerGeometryPolicy().grid_mm
    expected_width_mm = (
        np.floor(canvas_width * scale_factor / grid_mm + 0.5) * grid_mm
    )
    expected_height_mm = (
        np.floor(canvas_height * scale_factor / grid_mm + 0.5) * grid_mm
    )
    domain = read_layered_coordinate_domain(
        pattern.scene,
        require_certified=True,
    )
    assert domain is not None
    expected_bounds = domain.writer_canvas_bounds_mm
    assert pattern.metadata[MODEL_SURFACE_LOGICAL_XY_BOUNDS_KEY] == expected_bounds
    assert _pattern_xy_bounds_mm(pattern.scene) == expected_bounds
    actual_bounds = np.asarray(pattern.bounds, dtype=np.float32).astype(np.float64)
    assert actual_bounds[0, 0] >= expected_bounds[0]
    assert actual_bounds[0, 1] >= expected_bounds[1]
    assert actual_bounds[1, 0] <= expected_bounds[2]
    assert actual_bounds[1, 1] <= expected_bounds[3]


def test_native_vector_pattern_ownership_transfer_reuses_mesh_and_releases_scene():
    artwork = trimesh.creation.box(extents=(2.0, 2.0, 0.08))
    artwork.apply_translation((2.0, -2.0, 0.04))
    ctx = {
        "is_svg_vector": True,
        "scene": trimesh.Scene({"Black": artwork}),
        "vector_analysis": SimpleNamespace(
            slot_names=("Black",),
            num_channels=1,
            bbox=(0.0, 0.0, 10.0, 10.0),
            scale_factor=1.0,
            num_layers=1,
        ),
        "layer_height_mm": 0.08,
        "bambu_face_orientation": "up",
    }
    source_scene_ref = weakref.ref(ctx["scene"])

    pattern = _build_pattern_scene(ctx, _take_vector_scene_ownership=True)
    gc.collect()

    assert source_scene_ref() is None
    assert "scene" not in ctx
    assert "vector_analysis" not in ctx
    assert pattern.geometry["Black"] is artwork
    np.testing.assert_allclose(
        pattern.geometry["Black"].bounds[:, 1],
        [7.0, 9.0],
        atol=1e-6,
    )


def test_owned_model_surface_pipeline_does_not_copy_complete_scenes():
    base = trimesh.creation.box(extents=(20.0, 10.0, 3.0))
    color = trimesh.creation.box(extents=(2.0, 2.0, 0.08))
    color.apply_translation((0.0, 0.0, 0.04))
    pattern = trimesh.Scene({"Artwork": color})
    footprint = SurfaceFootprint(
        frame=PlaneFrame(
            origin=(0.0, 0.0, 1.5),
            normal=(0.0, 0.0, 1.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
        ),
        outer=((-10.0, -5.0), (10.0, -5.0), (10.0, 5.0), (-10.0, 5.0)),
        holes=(),
        bounds_min=(-10.0, -5.0),
        bounds_max=(10.0, 5.0),
        bounds_width_mm=20.0,
        bounds_height_mm=10.0,
        area_mm2=200.0,
        hole_count=0,
    )

    assembled = build_embedded_overlay_scene(
        base_mesh=base,
        pattern_scene=pattern,
        footprint=footprint,
        pocket_depth_mm=0.08,
        base_slot_name="surface_base",
        base_color=(245, 245, 245),
        allow_uncut_base=True,
        _take_pattern_ownership=True,
    )
    assert assembled.scene.geometry["Artwork"] is color

    transformed = apply_model_transform_to_overlay_scene(
        assembled,
        {"rotation_deg": {"x": 0, "y": 0, "z": 90}},
        _copy_scene=False,
    )
    assert transformed.scene is assembled.scene

    oriented = orient_overlay_scene_for_print(
        transformed,
        "down",
        _copy_scene=False,
    )
    assert oriented.scene is assembled.scene


@pytest.mark.parametrize(
    ("surface_tilt_y_deg", "user_rotation_y_deg"),
    [
        pytest.param(0.0, 0.0, id="axis-aligned-control"),
        pytest.param(0.0, 90.0, id="quarter-turn-control"),
        pytest.param(0.0, 15.0, id="user-rotation"),
        pytest.param(15.0, 0.0, id="tilted-surface-frame"),
    ],
)
def test_contacting_surface_pattern_exports_after_rigid_rotation(
    tmp_path,
    surface_tilt_y_deg: float,
    user_rotation_y_deg: float,
) -> None:
    """Contact shells remain printable through the complete surface workflow."""

    assembled = _contact_pattern_overlay(
        surface_tilt_y_deg=surface_tilt_y_deg,
    )
    transformed = apply_model_transform_to_overlay_scene(
        assembled,
        {
            "rotation_deg": {
                "x": 0.0,
                "y": user_rotation_y_deg,
                "z": 0.0,
            }
        },
        _copy_scene=False,
    )
    oriented = orient_overlay_scene_for_print(
        transformed,
        "down",
        _copy_scene=False,
    )
    output_path = tmp_path / (
        f"surface-contact-{surface_tilt_y_deg:g}-{user_rotation_y_deg:g}.3mf"
    )

    export_scene_with_bambu_metadata(
        scene=oriented.scene,
        output_path=str(output_path),
        slot_names=oriented.slot_names,
        preview_colors=oriented.preview_colors,
        settings={},
        color_mode="BW",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
        enable_wipe_tower_auto_placement=False,
    )

    surface_object, _surface_mesh = _object_mesh_from_3mf(
        output_path,
        object_name="surface_base",
    )
    artwork_object, artwork_mesh = _object_mesh_from_3mf(
        output_path,
        object_name="Artwork",
    )
    assert surface_object.attrib["pid"] == artwork_object.attrib["pid"]
    assert surface_object.attrib["pindex"] != artwork_object.attrib["pindex"]
    assert len(artwork_mesh.vertices) == 16
    assert len(artwork_mesh.faces) == 24
    assert abs(float(artwork_mesh.volume)) == pytest.approx(0.16, abs=0.0001)
    for vertex_start, face_start in ((0, 0), (8, 12)):
        leaf = trimesh.Trimesh(
            vertices=np.asarray(artwork_mesh.vertices)[
                vertex_start : vertex_start + 8
            ],
            faces=np.asarray(artwork_mesh.faces)[face_start : face_start + 12]
            - vertex_start,
            process=False,
        )
        assert leaf.is_watertight
        assert leaf.is_winding_consistent
        assert np.all(_edge_incidence_counts(leaf) == 2)










def test_native_vector_pattern_footprint_excludes_transparent_and_air_shapes():
    artwork = trimesh.creation.box(extents=(2.25, 2.0, 0.08))
    artwork.apply_translation((-3.125, -2.0, 0.04))
    source_scene = trimesh.Scene({"Black": artwork})

    pattern = _build_pattern_scene(
        {
            "is_svg_vector": True,
            "scene": source_scene,
            "vector_analysis": SimpleNamespace(
                slot_names=("Black",),
                num_channels=1,
                num_layers=1,
                bbox=(0.0, 0.0, 20.0, 10.0),
                scale_factor=1.0,
                matched_shapes=(
                    {"geometry": sg.box(2.0, 1.0, 4.0, 3.0), "recipe": (0,)},
                    {"geometry": sg.box(10.0, 1.0, 12.0, 3.0), "recipe": (-1,)},
                ),
            ),
            "layer_height_mm": 0.08,
            "bambu_face_orientation": "down",
        }
    )

    assert pattern.printable_footprint.area == pytest.approx(4.5)
    assert pattern.printable_footprint.bounds == pytest.approx(
        (2.0, 7.0, 4.25, 9.0)
    )


def test_build_surface_overlay_scene_orients_selected_face_toward_build_plate(
    monkeypatch,
):
    base = trimesh.creation.box(extents=(20.0, 10.0, 2.0))
    base.apply_translation((0.0, 0.0, 1.0))
    artwork = trimesh.creation.box(extents=(2.0, 2.0, 0.4))
    artwork.apply_translation((-8.0, 0.0, 1.8))
    assembled = OverlaySceneResult(
        scene=trimesh.Scene({"surface_base": base, "Artwork": artwork}),
        slot_names=["surface_base", "Artwork"],
        preview_colors={
            "surface_base": (245, 245, 245),
            "Artwork": (255, 0, 0),
        },
    )
    footprint = SurfaceFootprint(
        frame=PlaneFrame(
            origin=(0.0, 0.0, 2.0),
            normal=(0.0, 0.0, 1.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
        ),
        outer=((-10.0, -5.0), (10.0, -5.0), (10.0, 5.0), (-10.0, 5.0)),
        holes=(),
        bounds_min=(-10.0, -5.0),
        bounds_max=(10.0, 5.0),
        bounds_width_mm=20.0,
        bounds_height_mm=10.0,
        area_mm2=200.0,
        hole_count=0,
    )
    monkeypatch.setattr(
        "core.model_surface.pipeline.load_model_surface_mesh",
        lambda _path: SimpleNamespace(mesh=base),
    )
    monkeypatch.setattr(
        "core.model_surface.pipeline.build_image_model_context",
        lambda **_kwargs: {
            "full_matrix": np.zeros((1, 1, 1), dtype=np.int16),
            "slot_names": ["Artwork"],
            "preview_colors": {0: [255, 0, 0, 255]},
            "target_h": 1,
            "pixel_scale": 1.0,
            "color_layers": 1,
            "layer_height_mm": 0.4,
            "bambu_face_orientation": "down",
        },
    )
    monkeypatch.setattr(
        "core.model_surface.pipeline.build_embedded_overlay_scene",
        lambda **_kwargs: assembled,
    )

    result = build_surface_overlay_scene(
        model_path="plate.stl",
        artwork_image_path="art.png",
        lut_path="colors.npy",
        converter_params={},
        footprint=footprint,
        pocket_depth_mm=0.4,
    )

    artwork_bounds = np.asarray(result.scene.geometry["Artwork"].bounds)
    np.testing.assert_allclose(artwork_bounds[:, 0], [7.0, 9.0], atol=1e-6)
    np.testing.assert_allclose(artwork_bounds[:, 2], [0.0, 0.4], atol=1e-6)
    np.testing.assert_allclose(result.scene.bounds[:, 2], [0.0, 2.0], atol=1e-6)


@pytest.mark.parametrize("backing_index, expected_index", [(0, 0), (3, 3), (None, 2)])
def test_surface_base_reuses_selected_material_and_preserves_unused_palette(
    monkeypatch, tmp_path, backing_index, expected_index,
):
    base = trimesh.creation.box(extents=(20, 10, 3))
    names = ["PETG Red", "PETG Yellow", "PETG White", "PETG Blue"]
    colors = {0: (230, 10, 20), 1: (230, 220, 10), 2: (240, 240, 235), 3: (10, 20, 230)}
    ctx = {
        "material_source": "material_archive", "material_backing_material_index": backing_index,
        "material_base_channel_idx": 2, "slot_names": names, "preview_colors": colors,
        "bambu_face_orientation": "down",
    }
    pattern_mesh = trimesh.creation.box(extents=(2, 2, .08))
    pattern_mesh.apply_translation((1, 1, .04))
    pattern = PreparedSurfacePattern(trimesh.Scene({names[0]: pattern_mesh}), sg.box(0, 0, 2, 2))
    footprint = SurfaceFootprint(
        frame=PlaneFrame((0, 0, 1.5), (0, 0, 1), (1, 0, 0), (0, 1, 0)),
        outer=((-10, -5), (10, -5), (10, 5), (-10, 5)), holes=(),
        bounds_min=(-10, -5), bounds_max=(10, 5),
        bounds_width_mm=20, bounds_height_mm=10, area_mm2=200, hole_count=0,
    )
    monkeypatch.setattr("core.model_surface.pipeline.load_model_surface_mesh", lambda _: SimpleNamespace(mesh=base))
    monkeypatch.setattr("core.model_surface.pipeline.build_image_model_context", lambda **_: ctx)
    monkeypatch.setattr("core.model_surface.pipeline._build_pattern_scene", lambda *_, **__: pattern)

    overlay = build_surface_overlay_scene(model_path="model.stl", artwork_image_path="art.png",
        lut_path="unused.npy", converter_params={}, footprint=footprint, pocket_depth_mm=.08)

    assert overlay.scene.geometry["surface_base"].metadata["bambu_material_name"] == names[expected_index]
    assert overlay.preview_colors["surface_base"] == colors[expected_index]
    assert overlay.project_slot_names == names
    output = tmp_path / "surface-material.3mf"
    export_scene_with_bambu_metadata(scene=overlay.scene, output_path=str(output),
        slot_names=overlay.slot_names, preview_colors=overlay.preview_colors,
        project_slot_names=overlay.project_slot_names, settings={}, printer_id="bambu-p2s",
        enable_wipe_tower_auto_placement=False)
    with zipfile.ZipFile(output) as archive:
        project = json.loads(archive.read("Metadata/project_settings.config"))
        model_settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
    assert project["filament_type"] == ["PETG"] * 4
    assert len(project["filament_colour"]) == 4
    parts = model_settings.findall("./object/part")
    base_part = next(p for p in parts if p.find("./metadata[@key='name']").get("value") == "surface_base")
    assert base_part.find("./metadata[@key='extruder']").get("value") == str(expected_index + 1)


def test_pattern_logical_xy_bounds_reject_geometry_outside_canvas():
    color = trimesh.creation.box(extents=(4.0, 2.0, 0.08))
    color.apply_translation((3.0, 2.0, 0.04))
    pattern = trimesh.Scene({"Artwork": color})
    pattern.metadata[MODEL_SURFACE_LOGICAL_XY_BOUNDS_KEY] = (0.0, 0.0, 4.0, 4.0)

    with pytest.raises(ModelSurfaceError, match="exceeds its logical XY bounds"):
        _pattern_xy_bounds_mm(pattern)


def test_pattern_logical_xy_bounds_accept_float32_writer_rounding():
    canvas_width = 814.0
    canvas_height = 947.0
    target_width_mm = 115.59999084472656
    scale_factor = target_width_mm / canvas_width
    logical_width_mm = 115.6
    logical_height_mm = 134.488
    writer_width_mm = max(
        logical_width_mm,
        float(np.float32(logical_width_mm)),
    )
    writer_height_mm = float(np.float32(logical_height_mm))
    color = trimesh.creation.box(
        extents=(writer_width_mm, writer_height_mm, 0.08)
    )
    color.apply_translation(
        (-writer_width_mm / 2.0, -writer_height_mm / 2.0, 0.04)
    )
    pattern = _build_pattern_scene(
        {
            "is_svg_vector": True,
            "scene": trimesh.Scene({"Artwork": color}),
            "vector_analysis": SimpleNamespace(
                slot_names=("Artwork",),
                bbox=(0.0, 0.0, canvas_width, canvas_height),
                scale_factor=scale_factor,
                num_layers=1,
            ),
            "layer_height_mm": 0.08,
            "bambu_face_orientation": "down",
        }
    )
    domain = read_layered_coordinate_domain(
        pattern.scene,
        require_certified=True,
    )
    assert domain is not None
    logical_bounds = domain.writer_canvas_bounds_mm

    assert pattern.metadata[MODEL_SURFACE_LOGICAL_XY_BOUNDS_KEY] == logical_bounds
    assert _pattern_xy_bounds_mm(pattern) == logical_bounds


def test_pattern_display_bounds_accept_float32_writer_rounding():
    logical_height_mm = 0.4
    writer_height_mm = float(np.float32(logical_height_mm))
    color = trimesh.creation.box(extents=(4.0, 4.0, writer_height_mm))
    color.apply_translation((-2.0, -2.0, writer_height_mm / 2.0))
    layer_heights_mm = (0.08,) * 5
    pattern = _build_pattern_scene(
        {
            "is_svg_vector": True,
            "scene": trimesh.Scene({"Artwork": color}),
            "vector_analysis": SimpleNamespace(
                slot_names=("Artwork",),
                bbox=(0.0, 0.0, 4.0, 4.0),
                scale_factor=1.0,
                num_layers=5,
            ),
            "layer_height_mm": 0.08,
            "bambu_face_orientation": "down",
        }
    )

    assert pattern.metadata[MODEL_SURFACE_DISPLAY_Z_BOUNDS_KEY] == (
        0.0,
        writer_height_mm,
    )
    assert _pattern_z_bounds_mm(pattern) == (0.0, writer_height_mm)
    assert _pattern_layer_heights_mm(pattern) == layer_heights_mm


def _build_real_gray_vector_pattern(
    layer_count: int,
) -> tuple[PreparedSurfacePattern, VectorAnalysis, list[str]]:
    canvas_width = 814.0
    canvas_height = 947.0
    target_width_mm = 115.59999084472656
    scale_factor = target_width_mm / canvas_width
    geometries = [
        sg.Polygon(
            [(50, 50), (220, 50), (220, 300), (50, 300)],
            holes=[[(90, 90), (160, 90), (160, 180), (90, 180)]],
        ),
        sg.MultiPolygon(
            [
                sg.box(260, 60, 340, 150),
                sg.box(350, 180, 450, 280),
            ]
        ),
        sg.box(450, 280, 540, 370),
        sg.Polygon([(700, 900), (760, 850), (814, 900), (780, 947)]),
    ]
    slot_names = ["White", "Red", "Yellow", "Blue"]
    processor = VectorProcessor.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.enable_fridge_magnet = False
    processor.enable_coating = False
    processor.enable_outline = False
    processor.layer_height_mm = 0.08
    processor._merge_backing_into_material = False
    analysis = VectorAnalysis(
        shape_data=[None] * 167,
        clipped_shapes=[None] * 294,
        matched_shapes=[
            {
                "geometry": geometry,
                "recipe": [material_index] * layer_count,
            }
            for material_index, geometry in enumerate(geometries)
        ],
        silhouette=sg.GeometryCollection(geometries).buffer(0),
        scale_factor=scale_factor,
        bbox=(17.0, 23.0, canvas_width, canvas_height),
        color_conf={},
        slot_names=slot_names,
        num_channels=4,
        num_layers=layer_count,
        preview_colors={
            index: [index * 60, index * 40, index * 20, 255]
            for index in range(4)
        },
    )
    source_scene = processor.build_mesh(
        analysis=analysis,
        thickness_mm=0.0,
        structure_mode="Single-sided",
    )

    pattern = _build_pattern_scene(
        {
            "is_svg_vector": True,
            "scene": source_scene,
            "vector_analysis": analysis,
            "layer_height_mm": 0.08,
            "bambu_face_orientation": "down",
        }
    )
    return pattern, analysis, slot_names


@pytest.mark.parametrize("layer_count", [5, 10])
def test_real_gray_parameters_share_one_domain_across_four_materials(
    layer_count: int,
) -> None:
    """The reported canvas survives margins, holes, islands, and contacts."""

    pattern, analysis, slot_names = _build_real_gray_vector_pattern(layer_count)

    domain = read_layered_coordinate_domain(
        pattern.scene,
        require_certified=True,
    )
    assert domain == analysis.coordinate_domain
    assert tuple(pattern.geometry) == tuple(slot_names)
    assert domain.layer_heights_mm == (0.08,) * layer_count
    assert _pattern_xy_bounds_mm(pattern) == domain.writer_canvas_bounds_mm
    assert _pattern_z_bounds_mm(pattern) == domain.writer_z_bounds_mm


def test_real_gray_backface_survives_y180_model_transform() -> None:
    """The reported back face remains printable after its model rotation."""

    layer_count = 5
    pattern, _analysis, slot_names = _build_real_gray_vector_pattern(layer_count)
    footprint_width_mm = 115.59999084472656
    footprint_height_mm = 81.89998626708984
    half_width = footprint_width_mm / 2.0
    half_height = footprint_height_mm / 2.0
    footprint = SurfaceFootprint(
        frame=PlaneFrame(
            origin=(0.0, 0.0, -1.9),
            normal=(0.0, 0.0, -1.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, -1.0, 0.0),
        ),
        outer=(
            (-half_width, -half_height),
            (half_width, -half_height),
            (half_width, half_height),
            (-half_width, half_height),
            (-half_width, -half_height),
        ),
        holes=(),
        bounds_min=(-half_width, -half_height),
        bounds_max=(half_width, half_height),
        bounds_width_mm=footprint_width_mm,
        bounds_height_mm=footprint_height_mm,
        area_mm2=footprint_width_mm * footprint_height_mm,
        hole_count=0,
    )
    base = trimesh.creation.box(
        extents=(footprint_width_mm, footprint_height_mm, 3.8)
    )
    assembled = build_embedded_overlay_scene(
        base_mesh=base,
        pattern_scene=pattern,
        footprint=footprint,
        pocket_depth_mm=0.08 * layer_count,
        base_slot_name="surface_base",
        base_color=(245, 245, 245),
        allow_uncut_base=True,
    )
    transformed = apply_model_transform_to_overlay_scene(
        assembled,
        {"rotation_deg": {"x": 0.0, "y": 180.0, "z": 0.0}},
    )
    oriented = orient_overlay_scene_for_print(transformed, "down")

    assert oriented.slot_names == ["surface_base", *slot_names]
    assert np.all(np.isfinite(np.asarray(oriented.scene.bounds)))
    for slot_name in slot_names:
        mesh = oriented.scene.geometry[slot_name]
        assert isinstance(mesh, trimesh.Trimesh)
        assert mesh.is_watertight


def test_build_embedded_overlay_scene_embeds_full_pattern_depth():
    base = trimesh.creation.box(extents=(20.0, 10.0, 3.0))
    color = trimesh.creation.box(extents=(20.0, 10.0, 1.2))
    color.apply_translation((0.0, 0.0, 0.6))
    pattern = trimesh.Scene({"color_ff0000": color})
    footprint = SurfaceFootprint(
        frame=PlaneFrame(
            origin=(0.0, 0.0, 1.5),
            normal=(0.0, 0.0, 1.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
        ),
        outer=((-10.0, -5.0), (10.0, -5.0), (10.0, 5.0), (-10.0, 5.0), (-10.0, -5.0)),
        holes=(),
        bounds_min=(-10.0, -5.0),
        bounds_max=(10.0, 5.0),
        bounds_width_mm=20.0,
        bounds_height_mm=10.0,
        area_mm2=200.0,
        hole_count=0,
    )

    result = build_embedded_overlay_scene(
        base_mesh=base,
        pattern_scene=pattern,
        footprint=footprint,
        pocket_depth_mm=0.4,
        base_slot_name="surface_base",
        base_color=(245, 245, 245),
        allow_uncut_base=True,
    )

    assert result.scene.bounds[0][2] == pytest.approx(base.bounds[0][2])
    assert result.scene.bounds[1][2] == pytest.approx(base.bounds[1][2])


def test_build_embedded_overlay_scene_rejects_pattern_deeper_than_model():
    base = trimesh.creation.box(extents=(20.0, 10.0, 0.3))
    color = trimesh.creation.box(extents=(20.0, 10.0, 0.4))
    color.apply_translation((0.0, 0.0, 0.2))
    pattern = trimesh.Scene({"color_ff0000": color})
    footprint = SurfaceFootprint(
        frame=PlaneFrame(
            origin=(0.0, 0.0, 0.15),
            normal=(0.0, 0.0, 1.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
        ),
        outer=((-10.0, -5.0), (10.0, -5.0), (10.0, 5.0), (-10.0, 5.0)),
        holes=(),
        bounds_min=(-10.0, -5.0),
        bounds_max=(10.0, 5.0),
        bounds_width_mm=20.0,
        bounds_height_mm=10.0,
        area_mm2=200.0,
        hole_count=0,
    )

    with pytest.raises(
        ModelSurfaceError,
        match=r"^model_surface_insufficient_thickness:",
    ):
        build_embedded_overlay_scene(
            base_mesh=base,
            pattern_scene=pattern,
            footprint=footprint,
            pocket_depth_mm=0.4,
            base_slot_name="surface_base",
            base_color=(245, 245, 245),
        )


def test_build_embedded_overlay_scene_uses_local_wall_thickness_for_hollow_model():
    outer = trimesh.creation.box(extents=(20.0, 10.0, 4.0))
    cavity = trimesh.creation.box(extents=(18.0, 8.0, 3.6))
    cavity.invert()
    base = trimesh.util.concatenate([outer, cavity])
    color = trimesh.creation.box(extents=(20.0, 10.0, 0.3))
    color.apply_translation((0.0, 0.0, 0.15))
    pattern = trimesh.Scene({"color_ff0000": color})
    footprint = SurfaceFootprint(
        frame=PlaneFrame(
            origin=(0.0, 0.0, 2.0),
            normal=(0.0, 0.0, 1.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
        ),
        outer=((-9.0, -4.0), (9.0, -4.0), (9.0, 4.0), (-9.0, 4.0)),
        holes=(),
        bounds_min=(-9.0, -4.0),
        bounds_max=(9.0, 4.0),
        bounds_width_mm=18.0,
        bounds_height_mm=8.0,
        area_mm2=144.0,
        hole_count=0,
    )

    with pytest.raises(
        ModelSurfaceError,
        match=r"^model_surface_insufficient_thickness:",
    ):
        build_embedded_overlay_scene(
            base_mesh=base,
            pattern_scene=pattern,
            footprint=footprint,
            pocket_depth_mm=0.3,
            base_slot_name="surface_base",
            base_color=(245, 245, 245),
        )


def test_build_embedded_overlay_scene_uses_logical_display_depth_for_air_layers(
    monkeypatch: pytest.MonkeyPatch,
):
    base = trimesh.creation.box(extents=(20.0, 10.0, 3.0))
    color = trimesh.creation.box(extents=(20.0, 10.0, 0.04))
    color.apply_translation((0.0, 0.0, 0.20))
    pattern = trimesh.Scene({"color_ff0000": color})
    pattern.metadata["model_surface_display_z_bounds_mm"] = (0.0, 0.22)
    pattern.metadata["model_surface_display_layer_heights_mm"] = (0.10, 0.08, 0.04)
    footprint = SurfaceFootprint(
        frame=PlaneFrame(
            origin=(0.0, 0.0, 1.5),
            normal=(0.0, 0.0, 1.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
        ),
        outer=((-10.0, -5.0), (10.0, -5.0), (10.0, 5.0), (-10.0, 5.0)),
        holes=(),
        bounds_min=(-10.0, -5.0),
        bounds_max=(10.0, 5.0),
        bounds_width_mm=20.0,
        bounds_height_mm=10.0,
        area_mm2=200.0,
        hole_count=0,
    )
    captured: dict[str, float] = {}

    def fake_cut_surface_pocket(
        base_mesh,
        _footprint,
        _pattern,
        *,
        pocket_depth_mm,
    ):
        captured["pocket_depth_mm"] = pocket_depth_mm
        return base_mesh.copy()

    monkeypatch.setattr(
        "core.model_surface.assembly.cut_pattern_surface_pocket",
        fake_cut_surface_pocket,
    )

    result = build_embedded_overlay_scene(
        base_mesh=base,
        pattern_scene=pattern,
        footprint=footprint,
        pocket_depth_mm=0.04,
        base_slot_name="surface_base",
        base_color=(245, 245, 245),
    )

    assert captured["pocket_depth_mm"] == pytest.approx(0.22)
    assert result.scene.metadata["model_surface_display_layer_heights_mm"] == (
        0.10,
        0.08,
        0.04,
    )


def test_apply_model_transform_rotates_entire_overlay_scene_without_losing_slots():
    base = trimesh.creation.box(extents=(20.0, 10.0, 2.0))
    color = trimesh.creation.box(extents=(20.0, 10.0, 0.4))
    color.apply_translation((0.0, 0.0, 1.2))
    scene = trimesh.Scene({"surface_base": base, "color_ff0000": color})
    scene.metadata["model_surface_display_layer_heights_mm"] = (0.04,) * 10
    result = OverlaySceneResult(
        scene=scene,
        slot_names=["surface_base", "color_ff0000"],
        preview_colors={"surface_base": (245, 245, 245), "color_ff0000": (255, 0, 0)},
    )

    transformed = apply_model_transform_to_overlay_scene(
        result,
        {"rotation_deg": {"x": 0, "y": 0, "z": 90}},
    )

    np.testing.assert_allclose(
        np.asarray(transformed.scene.extents)[:2],
        np.array([10.0, 20.0]),
        atol=1e-6,
    )
    assert transformed.slot_names == result.slot_names
    assert transformed.preview_colors == result.preview_colors
    assert transformed.scene.metadata["model_surface_display_layer_heights_mm"] == (
        0.04,
    ) * 10
    np.testing.assert_allclose(
        np.asarray(result.scene.extents)[:2],
        np.array([20.0, 10.0]),
        atol=1e-6,
    )
