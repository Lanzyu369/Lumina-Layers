from __future__ import annotations

import pytest
import trimesh

from core.pipeline.vector_branch import _make_vector_glb_preview_scene


def _box_between(z_min: float, z_max: float) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=(10.0, 10.0, z_max - z_min))
    mesh.apply_translation((0.0, 0.0, (z_min + z_max) / 2.0))
    return mesh


def _make_single_sided_scene() -> trimesh.Scene:
    scene = trimesh.Scene()
    scene.add_geometry(_box_between(0.0, 0.48), geom_name="Red")
    scene.add_geometry(_box_between(0.485, 1.685), geom_name="Board")
    return scene


def test_single_sided_vector_glb_preview_mirrors_front_face_up() -> None:
    scene = _make_single_sided_scene()
    preview = _make_vector_glb_preview_scene(
        scene,
        structure_mode="Single-sided",
        color_mode="4-Color (RYBW)",
    )

    assert preview is not scene
    assert scene.geometry["Board"].bounds[0][2] > scene.geometry["Red"].bounds[1][2]
    assert preview.geometry["Board"].bounds[1][2] == pytest.approx(1.2)
    assert preview.geometry["Red"].bounds[0][2] == pytest.approx(1.205)
    assert preview.geometry["Board"].bounds[1][2] < preview.geometry["Red"].bounds[0][2]


def test_double_sided_vector_glb_preview_keeps_export_scene() -> None:
    scene = _make_single_sided_scene()
    preview = _make_vector_glb_preview_scene(
        scene,
        structure_mode="Double-sided",
        color_mode="4-Color (RYBW)",
    )

    assert preview is scene


def test_five_color_vector_glb_preview_keeps_face_up_scene() -> None:
    scene = _make_single_sided_scene()
    preview = _make_vector_glb_preview_scene(
        scene,
        structure_mode="Single-sided",
        color_mode="5-Color Extended",
    )

    assert preview is scene
