"""Topology regressions for raster and high-fidelity mesh assembly."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

import core.mesh_generators as mesh_generators
from core.mesh_generators import HighFidelityMesher, VoxelMesher, _merge_mesh_list


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


def test_boundary_polygon_extrusion_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clipped raster region may not be skipped after extrusion failure."""

    monkeypatch.setattr(
        mesh_generators.VectorProcessor,
        "_extrude_geometry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("broken")),
    )

    with pytest.raises(ValueError, match="refusing partial export"):
        mesh_generators._extrude_polygon_geometry(
            mesh_generators.Polygon(
                [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
            ),
            height=1.0,
            z_offset=0.0,
        )


def test_boundary_polygon_extrusion_is_watertight() -> None:
    mesh = mesh_generators._extrude_polygon_geometry(
        mesh_generators.Polygon(
            [
                (0.0, 0.0),
                (3.0, 0.0),
                (3.0, 1.0),
                (1.0, 1.0),
                (1.0, 3.0),
                (0.0, 3.0),
            ]
        ),
        height=1.0,
        z_offset=0.0,
    )[0]

    _assert_closed_independent_shells(mesh)
    assert float(mesh.volume) == pytest.approx(5.0)


def test_boundary_polygon_extrusion_accepts_bounded_float32_normalization() -> None:
    """Near-duplicate raster vertices may be normalized within the export bound."""

    polygon = mesh_generators.Polygon(
        [
            (2.0, 22.0),
            (2.0, 23.0),
            (1.9999999999999654, 23.0),
            (1.2233571841820776, 22.223357184182078),
            (1.2683026830235615, 22.0),
        ]
    )

    mesh = mesh_generators._extrude_polygon_geometry(
        polygon,
        height=1.0,
        z_offset=0.0,
    )[0]

    _assert_closed_independent_shells(mesh)
    assert abs(float(mesh.volume) - float(polygon.area)) <= 0.01


def test_boundary_polygon_extrusion_rejects_lost_area(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A watertight but undersized triangulation must not pass silently."""

    undersized = trimesh.creation.box(extents=[1.0, 1.0, 1.0])
    undersized.apply_translation([0.5, 0.5, 0.5])
    monkeypatch.setattr(
        mesh_generators.VectorProcessor,
        "_extrude_geometry",
        lambda *_args, **_kwargs: [undersized.copy()],
    )

    with pytest.raises(ValueError, match="coverage incomplete"):
        mesh_generators._extrude_polygon_geometry(
            mesh_generators.Polygon(
                [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
            ),
            height=1.0,
            z_offset=0.0,
        )
