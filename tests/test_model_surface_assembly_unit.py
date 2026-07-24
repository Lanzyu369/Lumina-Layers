from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

from core.model_surface.assembly import (
    MODEL_SURFACE_LOGICAL_XY_BOUNDS_KEY,
    OverlaySceneResult,
    _pattern_xy_bounds_mm,
    apply_model_transform_to_overlay_scene,
    build_embedded_overlay_scene,
)
from core.model_surface.pipeline import (
    _build_pattern_scene,
    build_surface_overlay_scene,
)
from core.model_surface.types import ModelSurfaceError, PlaneFrame, SurfaceFootprint


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
                bbox=(0.0, 0.0, 20.0, 10.0),
                scale_factor=1.0,
                num_layers=1,
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

    with pytest.raises(ModelSurfaceError, match="available model thickness"):
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

    with pytest.raises(ModelSurfaceError, match="available model thickness"):
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

    def fake_cut_surface_pocket(base_mesh, _footprint, *, pocket_depth_mm):
        captured["pocket_depth_mm"] = pocket_depth_mm
        return base_mesh.copy()

    monkeypatch.setattr(
        "core.model_surface.assembly.cut_surface_pocket",
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
