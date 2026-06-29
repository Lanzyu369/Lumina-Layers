from __future__ import annotations

import numpy as np
import trimesh

from core.model_surface.slot_meshing import build_slot_box_scene_from_voxels


def test_slot_box_scene_keeps_adjacent_prisms_topologically_closed():
    full_matrix = np.full((2, 3, 3), -1, dtype=np.int16)
    full_matrix[0, :, :] = 0
    full_matrix[1, :2, :2] = 0

    scene = build_slot_box_scene_from_voxels(
        full_matrix=full_matrix,
        slot_names=["White"],
        preview_colors={0: [255, 255, 255, 255]},
        target_h=3,
        pixel_scale=0.1,
    )

    mesh = scene.geometry["White"]
    assert isinstance(mesh, trimesh.Trimesh)
    open_edges, nonmanifold_edges = _edge_topology_counts(mesh)
    assert open_edges == 0
    assert nonmanifold_edges == 0


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
