"""Topology regressions for raster and high-fidelity mesh assembly."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

import core.mesh_generators as mesh_generators
from core.mesh_generators import HighFidelityMesher, _merge_mesh_list


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


def test_layer_rect_builder_keeps_edge_adjacent_prisms_independently_closed() -> None:
    """Touching raster boxes must stay closed instead of sharing bad indices."""

    mesher = HighFidelityMesher(disable_material_dilation=True)
    rectangles = np.array(
        [
            [0.0, 0.0, 1.0, 1.0],
            [1.0, 0.0, 2.0, 1.0],
        ],
        dtype=np.float64,
    )

    mesh = mesher._build_mesh_from_layer_rects(
        [(0.0, 1.0, rectangles)],
        height_px=1,
    )

    assert mesh is not None
    np.testing.assert_allclose(mesh.bounds, [[0.0, 0.0, 0.0], [2.0, 1.0, 1.0]])
    assert float(mesh.volume) == pytest.approx(2.0)
    _assert_closed_independent_shells(mesh)
    assert len(mesh.split(only_watertight=False)) == 2


def test_layer_rect_builder_keeps_point_touching_components_independently_closed() -> None:
    """Diagonal pixel contact is not an edge union and must stay two shells."""

    mesher = HighFidelityMesher(disable_material_dilation=True)
    rectangles = np.array(
        [
            [0.0, 0.0, 1.0, 1.0],
            [1.0, 1.0, 2.0, 2.0],
        ],
        dtype=np.float64,
    )

    mesh = mesher._build_mesh_from_layer_rects(
        [(0.0, 1.0, rectangles)],
        height_px=2,
    )

    assert mesh is not None
    np.testing.assert_allclose(mesh.bounds, [[0.0, 0.0, 0.0], [2.0, 2.0, 1.0]])
    assert float(mesh.volume) == pytest.approx(2.0)
    _assert_closed_independent_shells(mesh)
    assert len(mesh.split(only_watertight=False)) == 2


def test_layer_rect_builder_keeps_vertically_adjacent_slabs_closed() -> None:
    """Touching Z slabs retain two valid shells without global vertex welding."""

    mesher = HighFidelityMesher(disable_material_dilation=True)
    mesh = mesher._build_mesh_from_layer_rects(
        [
            (
                0.0,
                1.0,
                np.array([[0.0, 0.0, 2.0, 1.0]], dtype=np.float64),
            ),
            (
                1.0,
                2.0,
                np.array([[0.0, 0.0, 1.0, 1.0]], dtype=np.float64),
            ),
        ],
        height_px=1,
    )

    assert mesh is not None
    assert float(mesh.volume) == pytest.approx(3.0)
    _assert_closed_independent_shells(mesh)
    assert len(mesh.split(only_watertight=False)) == 2


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
