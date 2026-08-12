"""Topology regressions for raster and high-fidelity mesh assembly."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

from core.mesh_generators import HighFidelityMesher, _merge_mesh_list


def _indexed_edge_incidence(mesh: trimesh.Trimesh) -> np.ndarray:
    """Return triangle incidence counts for every indexed mesh edge."""

    faces = np.asarray(mesh.faces, dtype=np.int64)
    edges = np.concatenate(
        [faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]],
        axis=0,
    )
    edges.sort(axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return counts


def _assert_closed_independent_shells(mesh: trimesh.Trimesh) -> None:
    edge_counts = _indexed_edge_incidence(mesh)
    assert not np.any(edge_counts == 1), "closed prisms must not expose open edges"
    assert not np.any(edge_counts > 2), "no indexed edge may belong to more than two faces"
    assert np.all(edge_counts == 2)
    assert mesh.is_watertight


def test_layer_rect_builder_keeps_adjacent_prisms_as_closed_shells() -> None:
    """Greedy rectangles may touch but must not share vertex indices."""

    mesher = HighFidelityMesher(disable_material_dilation=True)
    rectangles = np.array(
        [
            [0.0, 0.0, 1.0, 1.0],
            [1.0, 0.0, 2.0, 1.0],
        ],
        dtype=np.float64,
    )

    mesh = mesher._build_mesh_from_layer_rects([(0, 1, rectangles)], height_px=1)

    assert mesh is not None
    np.testing.assert_allclose(mesh.bounds, [[0.0, 0.0, 0.0], [2.0, 1.0, 1.0]])
    assert float(mesh.volume) == pytest.approx(2.0)
    _assert_closed_independent_shells(mesh)


def test_merge_mesh_list_keeps_adjacent_prisms_as_closed_shells() -> None:
    """Fallback concatenation must not weld touching watertight inputs."""

    left = trimesh.creation.box(extents=[1.0, 1.0, 1.0])
    right = trimesh.creation.box(extents=[1.0, 1.0, 1.0])
    left.apply_translation([0.5, 0.5, 0.5])
    right.apply_translation([1.5, 0.5, 0.5])

    mesh = _merge_mesh_list([left, right])

    assert mesh is not None
    np.testing.assert_allclose(mesh.bounds, [[0.0, 0.0, 0.0], [2.0, 1.0, 1.0]])
    assert float(mesh.volume) == pytest.approx(2.0)
    _assert_closed_independent_shells(mesh)
