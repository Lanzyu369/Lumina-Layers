from __future__ import annotations

import gc
from types import SimpleNamespace
import weakref

import numpy as np
import pytest
import shapely.geometry as sg
import trimesh

from core.errors import VectorMeshMemoryBudgetError
from core.model_surface.assembly import (
    MODEL_SURFACE_LOGICAL_XY_BOUNDS_KEY,
    OverlaySceneResult,
    _pattern_xy_bounds_mm,
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


def _upward_horizontal_area_at_z(
    mesh: trimesh.Trimesh,
    z_mm: float,
) -> float:
    triangle_z = np.asarray(mesh.vertices)[np.asarray(mesh.faces), 2]
    on_plane = np.all(np.isclose(triangle_z, z_mm, atol=1e-6), axis=1)
    upward = np.asarray(mesh.face_normals)[:, 2] > 1.0 - 1e-6
    return float(np.asarray(mesh.area_faces)[on_plane & upward].sum())


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


def test_native_vector_pattern_is_normalized_before_surface_assembly():
    artwork = trimesh.creation.box(extents=(2.0, 6.0, 0.08))
    artwork.apply_translation((3.0, 5.0, 0.04))
    export_mirror = np.asarray(
        [
            [-1.0, 0.0, 0.0, 20.0],
            [0.0, 1.0, 0.0, 0.0],
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
        [16.0, 18.0],
        atol=1e-6,
    )
    np.testing.assert_allclose(
        pattern.geometry["Black"].bounds[:, 0],
        [2.0, 4.0],
        atol=1e-6,
    )


def test_native_vector_pattern_ownership_transfer_reuses_mesh_and_releases_scene():
    artwork = trimesh.creation.box(extents=(2.0, 2.0, 0.08))
    artwork.apply_translation((2.0, 2.0, 0.04))
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


def test_model_surface_footprint_memory_error_is_fatal(monkeypatch):
    scene = trimesh.Scene(
        {"Artwork": trimesh.creation.box(extents=(2.0, 2.0, 0.08))}
    )
    monkeypatch.setattr(
        "core.model_surface.pipeline.shapely.union_all",
        lambda _items: (_ for _ in ()).throw(MemoryError("footprint allocation")),
    )

    with pytest.raises(MemoryError, match="footprint allocation"):
        _build_scene_printable_footprint(scene)


def test_owned_vector_footprint_guard_uses_bounded_workspace_before_projection(
    monkeypatch,
):
    artwork = trimesh.creation.box(extents=(2.0, 2.0, 0.08))
    artwork.apply_translation((2.0, 2.0, 0.04))
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
    rejected = VectorMeshMemoryBudgetError(
        "model_surface_vector_footprint",
        9 * 1024**3,
        8 * 1024**3,
        1 * 1024**3,
        1,
        len(artwork.vertices),
    )
    calls = []

    def reject(_scene, **kwargs):
        calls.append(kwargs)
        raise rejected

    monkeypatch.setattr(
        "core.vector_engine._enforce_vector_scene_export_headroom",
        reject,
    )
    monkeypatch.setattr(
        "core.model_surface.pipeline._build_scene_printable_footprint",
        lambda _scene: (_ for _ in ()).throw(
            AssertionError("projection started before memory admission")
        ),
    )

    with pytest.raises(VectorMeshMemoryBudgetError) as raised:
        _build_pattern_scene(ctx, _take_vector_scene_ownership=True)

    assert raised.value is rejected
    assert calls == [
        {
            "stage": "model_surface_vector_footprint",
            "workspace_multiplier": 32.0,
        }
    ]


def test_model_surface_boolean_guard_runs_before_split_copy_or_difference(
    monkeypatch,
):
    base = trimesh.creation.box(extents=(20.0, 10.0, 3.0))
    cutter = trimesh.creation.box(extents=(1.0, 1.0, 0.09))
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
    rejected = VectorMeshMemoryBudgetError(
        "model_surface_boolean",
        9 * 1024**3,
        8 * 1024**3,
        1 * 1024**3,
        2,
        len(base.vertices) + len(cutter.vertices),
    )
    monkeypatch.setattr(
        "core.model_surface.assembly._build_polygon_prism_mesh",
        lambda _polygon, *, height_mm: cutter,
    )
    guard_calls = []

    def reject(_scene, **kwargs):
        guard_calls.append(kwargs)
        raise rejected

    monkeypatch.setattr(
        "core.vector_engine._enforce_vector_scene_export_headroom",
        reject,
    )
    monkeypatch.setattr(
        trimesh.Trimesh,
        "split",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("split started before memory admission")
        ),
    )
    monkeypatch.setattr(
        trimesh.Trimesh,
        "copy",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("copy started before memory admission")
        ),
    )
    monkeypatch.setattr(
        "core.model_surface.assembly.trimesh.boolean.difference",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("boolean started before memory admission")
        ),
    )

    with pytest.raises(VectorMeshMemoryBudgetError) as raised:
        cut_surface_pocket(base, footprint, pocket_depth_mm=0.08)

    assert raised.value is rejected
    assert guard_calls == [
        {
            "stage": "model_surface_boolean",
            "workspace_multiplier": 32.0,
        }
    ]


def test_model_surface_boolean_memory_error_is_fatal(monkeypatch):
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
    monkeypatch.setattr(
        "core.model_surface.assembly._build_polygon_prism_mesh",
        lambda _polygon, *, height_mm: trimesh.creation.box(
            extents=(1.0, 1.0, height_mm)
        ),
    )
    monkeypatch.setattr(
        "core.model_surface.assembly.prepare_model_surface_mesh_for_boolean",
        lambda mesh, **_kwargs: mesh,
    )
    monkeypatch.setattr(
        "core.model_surface.assembly.trimesh.boolean.difference",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            MemoryError("boolean allocation")
        ),
    )

    with pytest.raises(MemoryError, match="boolean allocation"):
        cut_surface_pocket(base, footprint, pocket_depth_mm=0.08)


def test_native_vector_pattern_footprint_excludes_transparent_and_air_shapes():
    artwork = trimesh.creation.box(extents=(2.25, 2.0, 0.08))
    artwork.apply_translation((16.875, 8.0, 0.04))
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


def test_pattern_logical_xy_bounds_reject_geometry_outside_canvas():
    color = trimesh.creation.box(extents=(4.0, 2.0, 0.08))
    color.apply_translation((3.0, 2.0, 0.04))
    pattern = trimesh.Scene({"Artwork": color})
    pattern.metadata[MODEL_SURFACE_LOGICAL_XY_BOUNDS_KEY] = (0.0, 0.0, 4.0, 4.0)

    with pytest.raises(ModelSurfaceError, match="exceeds its logical XY bounds"):
        _pattern_xy_bounds_mm(pattern)


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
