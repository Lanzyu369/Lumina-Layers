from __future__ import annotations

import numpy as np
import pytest
import trimesh

from core.model_surface.pipeline import _build_pattern_scene
from core.model_surface.slot_meshing import (
    build_printable_footprint_from_voxels,
    build_slot_surface_scene_from_voxels,
)
from core.model_surface.types import ModelSurfaceError


def test_slot_surface_scene_keeps_adjacent_voxels_topologically_closed():
    full_matrix = np.full((2, 3, 3), -1, dtype=np.int16)
    full_matrix[0, :, :] = 0
    full_matrix[1, :2, :2] = 0

    scene = build_slot_surface_scene_from_voxels(
        full_matrix=full_matrix,
        slot_names=["White"],
        preview_colors={0: [255, 255, 255, 255]},
        target_h=3,
        pixel_scale=0.1,
        layer_heights_mm=[0.08, 0.08],
    )

    mesh = scene.geometry["White"]
    assert isinstance(mesh, trimesh.Trimesh)
    open_edges, nonmanifold_edges = _edge_topology_counts(mesh)
    assert open_edges == 0
    assert nonmanifold_edges == 0
    assert mesh.metadata["layered_mesh_stats"]["source_voxel_count"] == 13


def test_printable_footprint_uses_valid_voxels_and_preserves_single_pixel_width():
    full_matrix = np.full((2, 3, 5), -1, dtype=np.int16)
    full_matrix[0, 0, 1:4] = 0
    full_matrix[1, 2, 4] = 1
    full_matrix[:, 1, 0] = 2

    footprint = build_printable_footprint_from_voxels(
        full_matrix=full_matrix,
        material_count=2,
        target_h=3,
        pixel_scale=0.5,
    )

    assert footprint.area == pytest.approx(1.0)
    assert footprint.bounds == pytest.approx((0.5, 0.0, 2.5, 1.5))


def test_model_surface_pattern_turns_face_down_single_side_outward():
    full_matrix = np.zeros((3, 1, 1), dtype=np.int16)
    full_matrix[0, 0, 0] = 1

    scene = _build_pattern_scene(
        {
            "full_matrix": full_matrix,
            "slot_names": ["White", "Red"],
            "preview_colors": {
                0: [255, 255, 255, 255],
                1: [255, 0, 0, 255],
            },
            "target_h": 1,
            "pixel_scale": 1.0,
            "color_layers": 3,
            "layer_height_mm": 0.08,
            "bambu_face_orientation": "down",
        }
    )

    assert scene.geometry["Red"].bounds[1, 2] > scene.geometry["White"].bounds[1, 2]


def test_model_surface_face_down_pattern_defers_print_mirror_to_final_orientation():
    full_matrix = np.full((1, 1, 4), -1, dtype=np.int16)
    full_matrix[0, 0, 0] = 0

    scene = _build_pattern_scene(
        {
            "full_matrix": full_matrix,
            "slot_names": ["Artwork"],
            "preview_colors": {0: [255, 0, 0, 255]},
            "target_h": 1,
            "pixel_scale": 1.0,
            "color_layers": 1,
            "layer_height_mm": 0.08,
            "bambu_face_orientation": "down",
        }
    )

    assert scene.geometry["Artwork"].bounds[:, 0] == pytest.approx([0.0, 1.0])


def test_model_surface_face_up_pattern_does_not_add_print_mirror():
    full_matrix = np.full((1, 1, 4), -1, dtype=np.int16)
    full_matrix[0, 0, 0] = 0

    scene = _build_pattern_scene(
        {
            "full_matrix": full_matrix,
            "slot_names": ["Artwork"],
            "preview_colors": {0: [255, 0, 0, 255]},
            "target_h": 1,
            "pixel_scale": 1.0,
            "color_layers": 1,
            "layer_height_mm": 0.08,
            "bambu_face_orientation": "up",
        }
    )

    assert scene.geometry["Artwork"].bounds[:, 0] == pytest.approx([0.0, 1.0])


@pytest.mark.parametrize("layer_count", [7, 10])
@pytest.mark.parametrize("layer_height_mm", [0.04, 0.08, 0.10])
def test_model_surface_pattern_uses_only_display_stack_height(
    layer_count: int,
    layer_height_mm: float,
):
    backing_layers = 15
    full_matrix = np.zeros((layer_count + backing_layers, 1, 1), dtype=np.int16)
    full_matrix[:layer_count, 0, 0] = 1

    scene = _build_pattern_scene(
        {
            "full_matrix": full_matrix,
            "slot_names": ["Backing", "Artwork"],
            "preview_colors": {
                0: [255, 255, 255, 255],
                1: [255, 0, 0, 255],
            },
            "target_h": 1,
            "pixel_scale": 1.0,
            "color_layers": layer_count,
            "layer_height_mm": layer_height_mm,
            "bambu_face_orientation": "down",
        }
    )

    assert "Backing" not in scene.geometry
    assert scene.bounds[0, 2] == pytest.approx(0.0)
    assert scene.bounds[1, 2] == pytest.approx(layer_count * layer_height_mm)


@pytest.mark.parametrize("layer_height_mm", [0.04, 0.08, 0.10])
def test_model_surface_face_up_pattern_discards_leading_backing(
    layer_height_mm: float,
):
    layer_count = 7
    backing_layers = 15
    full_matrix = np.zeros((backing_layers + layer_count, 1, 1), dtype=np.int16)
    full_matrix[backing_layers:, 0, 0] = 1

    scene = _build_pattern_scene(
        {
            "full_matrix": full_matrix,
            "slot_names": ["Backing", "Artwork"],
            "preview_colors": {
                0: [255, 255, 255, 255],
                1: [255, 0, 0, 255],
            },
            "target_h": 1,
            "pixel_scale": 1.0,
            "color_layers": layer_count,
            "layer_height_mm": layer_height_mm,
            "bambu_face_orientation": "up",
        }
    )

    assert "Backing" not in scene.geometry
    assert scene.bounds[0, 2] == pytest.approx(0.0)
    assert scene.bounds[1, 2] == pytest.approx(layer_count * layer_height_mm)


def test_model_surface_face_up_pattern_preserves_nonuniform_layer_order():
    full_matrix = np.zeros((6, 1, 1), dtype=np.int16)
    full_matrix[3:, 0, 0] = [3, 2, 1]

    scene = _build_pattern_scene(
        {
            "full_matrix": full_matrix,
            "slot_names": ["Backing", "Outer", "Middle", "Inner"],
            "preview_colors": {
                0: [255, 255, 255, 255],
                1: [255, 0, 0, 255],
                2: [0, 255, 0, 255],
                3: [0, 0, 255, 255],
            },
            "target_h": 1,
            "pixel_scale": 1.0,
            "color_layers": 3,
            "display_layer_heights_mm": [0.04, 0.08, 0.10],
            "bambu_face_orientation": "up",
        }
    )

    assert scene.geometry["Inner"].bounds[:, 2] == pytest.approx([0.0, 0.10])
    assert scene.geometry["Middle"].bounds[:, 2] == pytest.approx([0.10, 0.18])
    assert scene.geometry["Outer"].bounds[:, 2] == pytest.approx([0.18, 0.22])


def test_model_surface_pattern_supports_per_layer_physical_heights():
    full_matrix = np.zeros((6, 1, 1), dtype=np.int16)
    full_matrix[:3, 0, 0] = [1, 2, 3]

    scene = _build_pattern_scene(
        {
            "full_matrix": full_matrix,
            "slot_names": ["Backing", "Outer", "Middle", "Inner"],
            "preview_colors": {
                0: [255, 255, 255, 255],
                1: [255, 0, 0, 255],
                2: [0, 255, 0, 255],
                3: [0, 0, 255, 255],
            },
            "target_h": 1,
            "pixel_scale": 1.0,
            "color_layers": 3,
            "layer_height_mm": 0.08,
            "display_layer_heights_mm": [0.04, 0.08, 0.10],
            "bambu_face_orientation": "down",
        }
    )

    assert "Backing" not in scene.geometry
    assert scene.geometry["Inner"].bounds[:, 2] == pytest.approx([0.0, 0.10])
    assert scene.geometry["Middle"].bounds[:, 2] == pytest.approx([0.10, 0.18])
    assert scene.geometry["Outer"].bounds[:, 2] == pytest.approx([0.18, 0.22])


def test_model_surface_pattern_rejects_mismatched_layer_height_schedule():
    with pytest.raises(ModelSurfaceError, match="display layer heights"):
        _build_pattern_scene(
            {
                "full_matrix": np.ones((4, 1, 1), dtype=np.int16),
                "slot_names": ["Artwork", "Other"],
                "preview_colors": {
                    0: [255, 255, 255, 255],
                    1: [255, 0, 0, 255],
                },
                "target_h": 1,
                "pixel_scale": 1.0,
                "color_layers": 3,
                "layer_height_mm": 0.08,
                "display_layer_heights_mm": [0.04, 0.08],
                "bambu_face_orientation": "down",
            }
        )


def test_model_surface_pattern_rejects_invalid_uniform_layer_height():
    with pytest.raises(ModelSurfaceError, match="positive and finite"):
        _build_pattern_scene(
            {
                "full_matrix": np.ones((3, 1, 1), dtype=np.int16),
                "slot_names": ["Artwork"],
                "preview_colors": {0: [255, 0, 0, 255]},
                "target_h": 1,
                "pixel_scale": 1.0,
                "color_layers": 3,
                "layer_height_mm": 0.0,
                "bambu_face_orientation": "down",
            }
        )


def test_model_surface_pattern_preserves_short_per_pixel_display_stacks():
    full_matrix = np.zeros((5, 1, 2), dtype=np.int16)
    full_matrix[:3] = -1
    full_matrix[0, 0, :] = 1
    full_matrix[1:3, 0, 0] = 1

    scene = _build_pattern_scene(
        {
            "full_matrix": full_matrix,
            "slot_names": ["Backing", "Artwork"],
            "preview_colors": {
                0: [255, 255, 255, 255],
                1: [255, 0, 0, 255],
            },
            "target_h": 1,
            "pixel_scale": 1.0,
            "color_layers": 3,
            "display_layer_heights_mm": [0.04, 0.08, 0.10],
            "bambu_face_orientation": "down",
        }
    )

    artwork = scene.geometry["Artwork"]
    short_stack_vertices = artwork.vertices[artwork.vertices[:, 0] > 1.0]
    assert short_stack_vertices[:, 2].min() == pytest.approx(0.18)
    assert short_stack_vertices[:, 2].max() == pytest.approx(0.22)


def test_model_surface_pattern_preserves_all_air_inner_layer_depth():
    full_matrix = np.zeros((5, 1, 1), dtype=np.int16)
    full_matrix[:3] = -1
    full_matrix[0, 0, 0] = 1

    scene = _build_pattern_scene(
        {
            "full_matrix": full_matrix,
            "slot_names": ["Backing", "Artwork"],
            "preview_colors": {
                0: [255, 255, 255, 255],
                1: [255, 0, 0, 255],
            },
            "target_h": 1,
            "pixel_scale": 1.0,
            "color_layers": 3,
            "display_layer_heights_mm": [0.04, 0.08, 0.10],
            "bambu_face_orientation": "down",
        }
    )

    assert scene.bounds[:, 2] == pytest.approx([0.18, 0.22])
    assert scene.metadata["model_surface_display_z_bounds_mm"] == pytest.approx(
        [0.0, 0.22]
    )


def test_model_surface_pattern_rejects_full_scene_fallback():
    scene = trimesh.Scene(
        {"possibly_backed": trimesh.creation.box(extents=(1.0, 1.0, 1.0))}
    )

    with pytest.raises(ModelSurfaceError, match="display voxel stack"):
        _build_pattern_scene({"scene": scene})


def _edge_topology_counts(mesh: trimesh.Trimesh) -> tuple[int, int]:
    edges = np.empty((len(mesh.faces) * 3, 2), dtype=np.int64)
    edges[0::3] = mesh.faces[:, [0, 1]]
    edges[1::3] = mesh.faces[:, [1, 2]]
    edges[2::3] = mesh.faces[:, [2, 0]]
    edges.sort(axis=1)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    edges = edges[order]
    same_as_previous = np.all(edges[1:] == edges[:-1], axis=1)
    starts = np.concatenate(([0], np.nonzero(~same_as_previous)[0] + 1))
    counts = np.diff(np.concatenate((starts, [len(edges)])))
    return int((counts == 1).sum()), int((counts > 2).sum())
