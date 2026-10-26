"""Downstream consumers preserve physical Z and independent optical layers."""

from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

from core.mesh_generators import HighFidelityMesher
from core.model_surface.pipeline import _build_pattern_scene
from core.model_surface.types import ModelSurfaceError
from core.pipeline import s06_voxel_building, s08_auxiliary_meshes


def test_auxiliary_materials_use_volume_intervals_without_stretching_coating() -> None:
    compact = np.array([[[0, -2], [-3, -1]], [[1, -2], [-3, -1]]], dtype=np.int16)
    edges = np.array([0, 1, 126])

    def build(matrix: np.ndarray, z_edges: np.ndarray | None) -> trimesh.Scene:
        return s08_auxiliary_meshes.run({
            "scene": trimesh.Scene(), "valid_slot_names": [], "full_matrix": matrix,
            "voxel_z_edges": z_edges, "mask_solid": np.ones((2, 2), dtype=bool),
            "matched_rgb": np.full((2, 2, 3), [255, 0, 0], dtype=np.uint8),
            "target_h": 2, "pixel_scale": 1.0, "total_layers": 126,
            "preview_colors": {0: [255, 255, 255, 255]}, "transform": np.eye(4),
            "mesher": HighFidelityMesher(disable_material_dilation=True), "separate_backing": True,
            "enable_cloisonne": True, "backing_metadata": {"is_cloisonne": True},
            "free_color_set": {"#ff0000"}, "enable_coating": True,
            "coating_height_mm": 0.16,
            "resolved_coating_material": SimpleNamespace(name="Clear", rgb=(200, 200, 200)),
        })["scene"]

    actual = build(compact, edges)
    expected = build(np.repeat(compact, np.diff(edges), axis=0), None)
    assert set(actual.geometry) == {"Backing", "Wire", "Free_ff0000", "Coating"}
    for name, mesh in actual.geometry.items():
        assert mesh.is_watertight
        assert mesh.volume == pytest.approx(expected.geometry[name].volume)
        np.testing.assert_allclose(mesh.bounds, expected.geometry[name].bounds)
    assert actual.geometry["Free_ff0000"].volume == pytest.approx(126)
    assert actual.geometry["Backing"].volume == pytest.approx(126)
    assert actual.geometry["Coating"].volume == pytest.approx(4 * 0.16)
    assert actual.geometry["Coating"].metadata["bambu_material_name"] == "Clear"


@pytest.mark.parametrize("color_mode", ["4-Color", "5-Color Extended"])
def test_surface_pattern_resets_backing_intervals_to_optical_stack(color_mode: str) -> None:
    material = np.array([[[0, 1], [1, 0]]], dtype=np.int16)
    ctx = s06_voxel_building.run({
        "material_matrix": material, "mask_solid": np.ones((1, 2), dtype=bool),
        "matched_rgb": np.zeros((1, 2, 3), dtype=np.uint8), "spacer_thick": 10,
        "structure_mode": "Single-sided", "color_mode": color_mode,
        "backing_color_id": 1, "pixel_scale": 1.0,
    })
    ctx.update(target_h=1, slot_names=["White", "Red"], preview_colors={
        0: [255, 255, 255, 255], 1: [255, 0, 0, 255],
    }, layer_height_mm=0.08)
    actual = _build_pattern_scene(ctx)
    dense_ctx = dict(ctx, full_matrix=np.repeat(ctx["full_matrix"], np.diff(ctx["voxel_z_edges"]), axis=0))
    dense_ctx.pop("voxel_z_edges")
    expected = _build_pattern_scene(dense_ctx)
    for name, mesh in actual.geometry.items():
        assert mesh.volume == pytest.approx(expected.geometry[name].volume)
        np.testing.assert_allclose(mesh.bounds, expected.geometry[name].bounds)
        assert mesh.bounds[1, 2] == pytest.approx(0.16)


@pytest.mark.parametrize("orientation,edges,error", [
    ("double", [0, 1, 126, 127], "single display face"),
    ("down", [0, 125, 126, 127], "individual Z intervals"),
    ("up", [0, 1, 2, 127], "individual Z intervals"),
])
def test_surface_pattern_rejects_invalid_display_intervals(orientation, edges, error) -> None:
    with pytest.raises(ModelSurfaceError, match=error):
        _build_pattern_scene({
            "full_matrix": np.zeros((3, 1, 1), dtype=np.int16),
            "voxel_z_edges": edges, "color_layers": 1,
            "bambu_face_orientation": orientation, "slot_names": ["White"],
            "preview_colors": {0: [255, 255, 255, 255]},
            "target_h": 1, "pixel_scale": 1.0,
        })
