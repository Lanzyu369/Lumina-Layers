"""Topology regressions for raster and high-fidelity mesh assembly."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

import core.mesh_generators as mesh_generators
from core.mesh_generators import HighFidelityMesher, VoxelMesher


def _indexed_edge_incidence(mesh: trimesh.Trimesh) -> np.ndarray:
    """Return triangle incidence counts for every indexed mesh edge."""

    faces = np.asarray(mesh.faces, dtype=np.int64)
    edges = np.concatenate(
        [faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]],
        axis=0,
    )
    edges.sort(axis=1)
    _unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    return counts


def _assert_closed_independent_shells(mesh: trimesh.Trimesh) -> None:
    edge_counts = _indexed_edge_incidence(mesh)
    assert np.all(edge_counts == 2)
    assert mesh.is_watertight


@pytest.mark.parametrize(
    "mesher",
    [VoxelMesher(), HighFidelityMesher(disable_material_dilation=True)],
    ids=["voxel", "high_fidelity"],
)
def test_face_adjacent_voxels_become_one_surface_without_internal_faces(
    mesher,
) -> None:
    """Same-material neighbors must form one shell, not two touching boxes."""

    labels = np.array([[[3, 3]]], dtype=np.int16)
    mesh = mesher.generate_mesh(labels, 3, height_px=1)

    assert mesh is not None
    np.testing.assert_allclose(mesh.bounds, [[0.0, 0.0, 0.0], [2.0, 1.0, 1.0]])
    assert float(mesh.volume) == pytest.approx(2.0)
    assert len(mesh.faces) == 12
    _assert_closed_independent_shells(mesh)
    assert len(mesh.split(only_watertight=False)) == 1
    assert mesh.metadata["layered_mesh_stats"]["source_voxel_count"] == 2


@pytest.mark.parametrize(
    "mesher",
    [VoxelMesher(), HighFidelityMesher(disable_material_dilation=True)],
    ids=["voxel", "high_fidelity"],
)
def test_point_touching_components_remain_independently_closed(mesher) -> None:
    """Diagonal pixel contact is not an edge union and must stay two shells."""

    labels = np.array([[[4, -1], [-1, 4]]], dtype=np.int16)
    mesh = mesher.generate_mesh(labels, 4, height_px=2)

    assert mesh is not None
    np.testing.assert_allclose(mesh.bounds, [[0.0, 0.0, 0.0], [2.0, 2.0, 1.0]])
    assert float(mesh.volume) == pytest.approx(2.0)
    _assert_closed_independent_shells(mesh)
    assert len(mesh.split(only_watertight=False)) == 2


@pytest.mark.parametrize(
    "mesher",
    [VoxelMesher(), HighFidelityMesher(disable_material_dilation=True)],
    ids=["voxel", "high_fidelity"],
)
def test_vertically_adjacent_voxels_become_one_stepped_shell(mesher) -> None:
    """Z-adjacent material must not retain an internal slab interface."""

    labels = np.array([[[5, 5]], [[5, -1]]], dtype=np.int16)
    mesh = mesher.generate_mesh(labels, 5, height_px=1)

    assert mesh is not None
    assert float(mesh.volume) == pytest.approx(3.0)
    _assert_closed_independent_shells(mesh)
    assert len(mesh.split(only_watertight=False)) == 1


@pytest.mark.parametrize(
    "mesher",
    [VoxelMesher(), HighFidelityMesher(disable_material_dilation=True)],
    ids=["voxel", "high_fidelity"],
)
def test_backing_label_uses_the_same_exact_closed_surface(mesher) -> None:
    labels = np.array([[[-2, -2], [-1, -2]]], dtype=np.int16)

    mesh = mesher.generate_backing_mesh(labels, height_px=2)

    assert mesh is not None
    assert float(mesh.volume) == pytest.approx(3.0)
    assert mesh.metadata["layered_mesh_stats"]["source_voxel_count"] == 3
    _assert_closed_independent_shells(mesh)


def test_boundary_geometry_uses_only_the_layered_surface_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Puzzle boundaries must not enter any polygon-extrusion implementation."""

    monkeypatch.setattr(
        trimesh.creation,
        "extrude_polygon",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("polygon extrusion called")
        ),
    )
    labels = np.zeros((1, 5, 5), dtype=np.int16)
    boundary = mesh_generators.Polygon(
        [(0.0, 0.0), (3.0, 0.0), (0.0, 5.0)]
    )

    mesh = HighFidelityMesher(
        disable_material_dilation=True,
        boundary_geometry=boundary,
    ).generate_mesh(
        labels,
        0,
        height_px=5,
    )

    assert mesh is not None
    _assert_closed_independent_shells(mesh)
    expected_mask = mesh_generators.rasterize_boundary_geometry(
        boundary,
        height_px=5,
        width_px=5,
    )
    assert float(mesh.volume) == pytest.approx(float(np.count_nonzero(expected_mask)))
    assert mesh.metadata["raster_surface_stats"]["boundary_rasterized"] is True


def test_boundary_lattice_preserves_holes_and_independent_islands(
) -> None:
    """Center-sampled boundary masks keep holes and disconnected printable cells."""

    boundary = mesh_generators.MultiPolygon(
        [
            mesh_generators.Polygon(
                [(0, 0), (4, 0), (4, 4), (0, 4)],
                holes=[[(1, 1), (3, 1), (3, 3), (1, 3)]],
            ),
            mesh_generators.Polygon(
                [(5, 5), (6, 5), (6, 6), (5, 6)]
            ),
        ]
    )
    labels = np.zeros((1, 6, 6), dtype=np.int16)

    mesh = HighFidelityMesher(
        disable_material_dilation=True,
        boundary_geometry=boundary,
    ).generate_mesh(
        labels,
        0,
        height_px=6,
    )

    assert mesh is not None
    expected_mask = mesh_generators.rasterize_boundary_geometry(
        boundary,
        height_px=6,
        width_px=6,
    )
    _assert_closed_independent_shells(mesh)
    assert float(mesh.volume) == pytest.approx(float(np.count_nonzero(expected_mask)))
    assert len(mesh.split(only_watertight=False)) == 2


def test_retired_boundary_extrusion_helpers_are_absent() -> None:
    """The old puzzle polygon adapter must not remain callable by accident."""

    assert not hasattr(mesh_generators, "_extrude_polygon_geometry")
    assert not hasattr(mesh_generators.BaseMesher, "_build_mesh_from_layer_polygons")
