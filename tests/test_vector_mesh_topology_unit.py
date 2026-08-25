"""Contract tests for the shared vector topology export service."""

from __future__ import annotations

import pickle
import traceback
import weakref

import numpy as np
import pytest
import trimesh
from shapely.geometry import MultiPoint, Point, Polygon, box

import core.vector_mesh_topology as vector_mesh_topology
from core.errors import VectorTopologyError
from core.vector_mesh_topology import (
    extrude_polygon_for_export,
    mesh_is_float32_safe,
    prepare_geometry_for_float32,
    separate_component_coordinates,
)

# The public separation policy tries at most eight fixed offset steps.
MAX_COMPONENT_SEPARATION_MM = 8 * 1e-4
# Zero offset plus eight directions at each of the eight fixed retry steps.
MAX_COMPONENT_OFFSET_CANDIDATES = 1 + 8 * 8


def _edge_incidence_counts(mesh) -> np.ndarray:
    """Return indexed face incidence counts for every mesh edge."""

    faces = np.asarray(mesh.faces, dtype=np.int64)
    edges = np.concatenate(
        [faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]],
        axis=0,
    )
    edges.sort(axis=1)
    _unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    return counts


def _near_duplicate_boundary_polygon() -> Polygon:
    """Return a valid ring whose distinct vertices collapse at float32 scale."""

    polygon = Polygon(
        [
            (2509.917435338203, 4623.051929933649),
            (2510.172565883122, 4623.021385042616),
            (2510.883578978562, 4623.157336359613),
            (2556.1858527699997, 4617.512555038293),
            (2509.9174353413346, 4623.05192992644),
            (2509.7519150970775, 4622.940953283469),
        ]
    )
    assert polygon.is_valid
    return polygon


def _point_touching_holes_polygon() -> Polygon:
    """Return a valid polygon with two holes that share one vertex."""

    polygon = Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        [
            [(2.0, 4.0), (5.0, 5.0), (2.0, 6.0), (2.0, 4.0)],
            [(8.0, 4.0), (8.0, 6.0), (5.0, 5.0), (8.0, 4.0)],
        ],
    )
    assert polygon.is_valid
    return polygon


def _multi_point_touching_holes_polygon() -> Polygon:
    """Return four valid holes that share exactly one central vertex."""

    polygon = Polygon(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        [
            [(10.0, 10.0), (8.0, 12.0), (9.0, 13.0)],
            [(10.0, 10.0), (11.0, 13.0), (12.0, 12.0)],
            [(10.0, 10.0), (12.0, 8.0), (11.0, 7.0)],
            [(10.0, 10.0), (9.0, 7.0), (8.0, 8.0)],
        ],
    )
    assert polygon.is_valid
    return polygon


def _separate_holes_polygon() -> Polygon:
    """Return a polygon whose holes share no ring coordinates."""

    polygon = Polygon(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        [
            [(2.0, 2.0), (4.0, 2.0), (3.0, 4.0)],
            [(8.0, 2.0), (10.0, 2.0), (9.0, 4.0)],
            [(2.0, 9.0), (4.0, 9.0), (3.0, 11.0)],
            [(8.0, 9.0), (10.0, 9.0), (9.0, 11.0)],
        ],
    )
    assert polygon.is_valid
    return polygon


def _hub_touching_holes_polygon(*, contact_gap: float = 0.0) -> Polygon:
    """Return a valid central hole with four point-touching satellites."""

    polygon = Polygon(
        [(0.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0)],
        [
            [(12.0, 12.0), (18.0, 12.0), (18.0, 18.0), (12.0, 18.0)],
            [(12.0 - contact_gap, 15.0), (8.0, 13.0), (8.0, 17.0)],
            [(18.0 + contact_gap, 15.0), (22.0, 17.0), (22.0, 13.0)],
            [(15.0, 18.0 + contact_gap), (13.0, 22.0), (17.0, 22.0)],
            [(15.0, 12.0 - contact_gap), (17.0, 8.0), (13.0, 8.0)],
        ],
    )
    assert polygon.is_valid
    return polygon


def _float32_combined_mesh(meshes):
    """Build a writer-domain mesh from independently indexed components."""

    vertices = np.vstack(
        [np.asarray(mesh.vertices, dtype=np.float64) for mesh in meshes]
    )
    faces = []
    vertex_offset = 0
    for mesh in meshes:
        faces.append(np.asarray(mesh.faces, dtype=np.int64) + vertex_offset)
        vertex_offset += len(mesh.vertices)
    all_faces = np.vstack(faces)
    writer_vertices = vertices.astype(np.float32).astype(np.float64)
    unique_vertices, inverse = np.unique(
        writer_vertices,
        axis=0,
        return_inverse=True,
    )
    return unique_vertices, inverse[all_faces]


def _three_level_hourglass() -> trimesh.Trimesh:
    """Return a closed solid whose middle section is wider than both caps."""

    vertices = []
    for z_value, radius in ((0.0, 1.0), (0.5, 2.0), (1.0, 1.0)):
        vertices.extend(
            [
                (-radius, -radius, z_value),
                (radius, -radius, z_value),
                (radius, radius, z_value),
                (-radius, radius, z_value),
            ]
        )
    faces = [(0, 2, 1), (0, 3, 2), (8, 9, 10), (8, 10, 11)]
    for lower in (0, 4):
        upper = lower + 4
        for index in range(4):
            next_index = (index + 1) % 4
            faces.extend(
                [
                    (lower + index, lower + next_index, upper + next_index),
                    (lower + index, upper + next_index, upper + index),
                ]
            )
    mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
    )
    assert mesh.is_watertight
    assert mesh.is_winding_consistent
    return mesh


def _rectangular_frustum(
    *,
    left_x: float,
    bottom_right_x: float,
    top_right_x: float,
) -> trimesh.Trimesh:
    """Return a closed box-like frustum with independently placed right edges."""

    vertices = np.asarray(
        [
            (left_x, 0.0, 0.0),
            (bottom_right_x, 0.0, 0.0),
            (bottom_right_x, 1.0, 0.0),
            (left_x, 1.0, 0.0),
            (left_x, 0.0, 1.0),
            (top_right_x, 0.0, 1.0),
            (top_right_x, 1.0, 1.0),
            (left_x, 1.0, 1.0),
        ],
        dtype=np.float64,
    )
    faces = np.asarray(
        [
            (0, 2, 1), (0, 3, 2),
            (4, 5, 6), (4, 6, 7),
            (0, 1, 5), (0, 5, 4),
            (1, 2, 6), (1, 6, 5),
            (2, 3, 7), (2, 7, 6),
            (3, 0, 4), (3, 4, 7),
        ],
        dtype=np.int64,
    )
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    assert mesh.is_watertight
    assert mesh.is_winding_consistent
    return mesh


def _total_unit_height_volume(meshes) -> float:
    """Return the total physical volume of unit-height component meshes."""

    return sum(abs(float(mesh.volume)) for mesh in meshes)


def test_export_extrusion_handles_plain_rectangle() -> None:
    """Ordinary polygons retain the fast printable-prism contract."""

    xy_scale = 1.0
    polygon = box(0.0, 0.0, 4.0, 3.0)
    prepared = prepare_geometry_for_float32(polygon, xy_scale=xy_scale)

    meshes = extrude_polygon_for_export(
        polygon,
        xy_scale=xy_scale,
        prefer_fast=True,
    )

    assert prepared is polygon
    assert len(meshes) == 1
    assert meshes[0].is_watertight
    assert mesh_is_float32_safe(meshes[0], xy_scale=xy_scale)
    assert np.all(_edge_incidence_counts(meshes[0]) == 2)
    expected_physical_area = float(polygon.area) * xy_scale * xy_scale
    physical_volume = _total_unit_height_volume(meshes) * xy_scale * xy_scale
    physical_area_tolerance = max(0.01, expected_physical_area * 1e-6)
    assert physical_volume == pytest.approx(
        expected_physical_area,
        abs=physical_area_tolerance,
    )


def test_export_extrusion_repairs_near_duplicate_boundary() -> None:
    """Float32-unsafe but valid exterior rings are repaired within the service."""

    xy_scale = 0.043424072501499274
    polygon = _near_duplicate_boundary_polygon()

    prepared = prepare_geometry_for_float32(polygon, xy_scale=xy_scale)
    meshes = extrude_polygon_for_export(
        polygon,
        xy_scale=xy_scale,
        prefer_fast=True,
    )

    assert prepared is not None
    assert prepared is not polygon
    assert prepared.is_valid
    prepared_coordinates = np.asarray(prepared.exterior.coords, dtype=np.float64)[:-1]
    export_coordinates = (prepared_coordinates * xy_scale).astype(np.float32)
    assert len(np.unique(export_coordinates, axis=0)) == len(export_coordinates)
    assert abs(float(prepared.area - polygon.area) * xy_scale * xy_scale) <= 0.01
    assert meshes
    assert all(mesh.is_watertight for mesh in meshes)
    assert all(
        mesh_is_float32_safe(mesh, xy_scale=xy_scale)
        for mesh in meshes
    )
    expected_physical_area = float(polygon.area) * xy_scale * xy_scale
    physical_volume = _total_unit_height_volume(meshes) * xy_scale * xy_scale
    physical_area_tolerance = max(0.01, expected_physical_area * 1e-6)
    assert physical_volume == pytest.approx(
        expected_physical_area,
        abs=physical_area_tolerance,
    )


def test_export_extrusion_is_scale_invariant_for_tiny_geometry() -> None:
    """Physical 100 mm geometry must not lose 0.1 mm details before export."""

    large_coordinate = 1e-7
    detail_coordinate = 1e-10
    xy_scale = 1e9
    polygon = Polygon(
        [
            (0.0, 0.0),
            (detail_coordinate, 0.0),
            (detail_coordinate, detail_coordinate),
            (large_coordinate, 0.0),
            (large_coordinate, large_coordinate),
            (0.0, large_coordinate),
        ]
    )
    assert polygon.is_valid
    assert (polygon.bounds[2] - polygon.bounds[0]) * xy_scale == pytest.approx(
        100.0
    )
    assert detail_coordinate * xy_scale == pytest.approx(0.1)

    meshes = extrude_polygon_for_export(
        polygon,
        xy_scale=xy_scale,
        prefer_fast=False,
    )

    expected_physical_area = float(polygon.area) * xy_scale * xy_scale
    physical_volume = _total_unit_height_volume(meshes) * xy_scale * xy_scale
    physical_area_tolerance = max(0.01, expected_physical_area * 1e-6)
    assert meshes
    assert all(mesh.is_watertight for mesh in meshes)
    assert all(mesh_is_float32_safe(mesh, xy_scale=xy_scale) for mesh in meshes)
    assert physical_volume == pytest.approx(
        expected_physical_area,
        abs=physical_area_tolerance,
    )


def test_export_extrusion_uses_only_bounded_repair_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public fallback ladder tries the original and exactly two repairs."""

    polygon = box(0.0, 0.0, 3.0, 2.0)
    repaired_candidates = [
        Polygon(polygon.exterior.coords),
        Polygon(polygon.exterior.coords),
    ]
    repair_calls = []
    indexed_attempts = []

    def fail_indexed_extrusion(geometry):
        indexed_attempts.append(geometry)
        raise ValueError("synthetic indexed extrusion failure")

    def return_repaired_candidate(_poly, _scale, separation_mm):
        candidate = repaired_candidates[len(repair_calls)]
        repair_calls.append(separation_mm)
        return candidate

    monkeypatch.setattr(
        vector_mesh_topology,
        "_extrude_indexed_parts",
        fail_indexed_extrusion,
    )
    monkeypatch.setattr(
        vector_mesh_topology,
        "_repair_polygon_ring_contacts",
        return_repaired_candidate,
    )

    with pytest.raises(VectorTopologyError, match="topology could not be repaired"):
        extrude_polygon_for_export(
            polygon,
            xy_scale=1.0,
            prefer_fast=False,
        )

    assert repair_calls == [0.0001, 0.001]
    assert indexed_attempts[0] is polygon
    assert indexed_attempts[1] is repaired_candidates[0]
    assert indexed_attempts[2] is repaired_candidates[1]


def test_export_failure_reports_structured_bounded_attempt_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every failed ladder stage exposes safe geometry and mesh metrics."""

    polygon = box(0.0, 0.0, 3.0, 2.0)
    wrong_coverage_mesh = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    wrong_coverage_mesh.apply_translation((0.0, 0.0, 0.5))

    def return_wrong_fast_extrusion(*_args, **_kwargs):
        return wrong_coverage_mesh

    def return_wrong_indexed_extrusion(_geometry):
        return [wrong_coverage_mesh]

    monkeypatch.setattr(
        vector_mesh_topology.trimesh.creation,
        "extrude_polygon",
        return_wrong_fast_extrusion,
    )
    monkeypatch.setattr(
        vector_mesh_topology,
        "_extrude_indexed_parts",
        return_wrong_indexed_extrusion,
    )

    with pytest.raises(VectorTopologyError) as exc:
        extrude_polygon_for_export(
            polygon,
            xy_scale=1.0,
            prefer_fast=True,
        )

    attempts = exc.value.attempts
    assert [attempt["attempt"] for attempt in attempts] == [
        "fast",
        "original",
        "repair_0.0001_mm",
        "repair_0.001_mm",
    ]
    required_fields = {
        "attempt",
        "geometry_type",
        "polygon_part_count",
        "ring_count",
        "hole_count",
        "vertex_count",
        "original_area_mm2",
        "candidate_area_mm2",
        "area_delta_mm2",
        "float32_ring_collapse_count",
        "candidate_mesh_count",
        "watertight",
        "non_manifold_edge_count",
        "expected_coverage_mm2",
        "actual_coverage_mm2",
        "rejected_reason",
        "error_type",
    }
    for attempt in attempts:
        assert required_fields <= attempt.keys()
        assert attempt["geometry_type"] == "Polygon"
        assert attempt["polygon_part_count"] == 1
        assert attempt["ring_count"] == 1
        assert attempt["hole_count"] == 0
        assert attempt["vertex_count"] == 4
        assert attempt["original_area_mm2"] == pytest.approx(6.0)
        assert attempt["candidate_area_mm2"] == pytest.approx(6.0)
        assert attempt["area_delta_mm2"] == pytest.approx(0.0)
        assert attempt["float32_ring_collapse_count"] == 0
        assert attempt["candidate_mesh_count"] == 1
        assert attempt["watertight"] is True
        assert attempt["non_manifold_edge_count"] == 0
        assert attempt["expected_coverage_mm2"] == pytest.approx(6.0)
        assert attempt["actual_coverage_mm2"] == pytest.approx(1.0)
        assert attempt["rejected_reason"] == "coverage_mismatch"
        assert attempt["error_type"] is None
    restored = pickle.loads(pickle.dumps(exc.value))
    assert isinstance(restored, VectorTopologyError)
    assert restored.error_type == "vector_topology_unrepairable"
    assert str(restored) == str(exc.value)
    assert restored.attempts == attempts


def test_export_extrusion_recovers_from_fast_index_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fast-path operation error must yield to canonical extrusion."""

    polygon = box(0.0, 0.0, 3.0, 2.0)
    original_indexed = vector_mesh_topology._extrude_indexed_parts
    indexed_calls = []

    def fail_fast_extrusion(*_args, **_kwargs):
        raise IndexError("synthetic fast-path indexing failure")

    def record_indexed_extrusion(geometry):
        indexed_calls.append(geometry)
        return original_indexed(geometry)

    monkeypatch.setattr(
        vector_mesh_topology.trimesh.creation,
        "extrude_polygon",
        fail_fast_extrusion,
    )
    monkeypatch.setattr(
        vector_mesh_topology,
        "_extrude_indexed_parts",
        record_indexed_extrusion,
    )

    meshes = extrude_polygon_for_export(
        polygon,
        xy_scale=1.0,
        prefer_fast=True,
    )

    assert indexed_calls == [polygon]
    assert meshes
    assert all(mesh_is_float32_safe(mesh, xy_scale=1.0) for mesh in meshes)


@pytest.mark.parametrize(
    "error_type",
    [RuntimeError, IndexError, AttributeError, OSError, ArithmeticError],
)
def test_export_extrusion_recovers_from_manifold_operation_error(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    """Reasonable manifold failures must fall back to Earcut."""

    polygon = box(0.0, 0.0, 3.0, 2.0)

    def fail_manifold(*_args, **_kwargs):
        raise error_type("synthetic manifold operation failure")

    monkeypatch.setattr(
        vector_mesh_topology.trimesh.creation,
        "triangulate_polygon",
        fail_manifold,
    )

    meshes = extrude_polygon_for_export(
        polygon,
        xy_scale=1.0,
        prefer_fast=False,
    )

    assert meshes
    assert all(mesh_is_float32_safe(mesh, xy_scale=1.0) for mesh in meshes)
    assert _total_unit_height_volume(meshes) == pytest.approx(float(polygon.area))


def test_export_extrusion_bounds_earcut_operation_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Earcut operation failures exhaust the fixed ladder as one typed error."""

    polygon = box(0.0, 0.0, 3.0, 2.0)
    original_repair = vector_mesh_topology._repair_polygon_ring_contacts
    repair_calls = []
    earcut_calls = []

    def fail_manifold(*_args, **_kwargs):
        raise RuntimeError("synthetic manifold failure")

    def fail_earcut(*args, **_kwargs):
        earcut_calls.append(args)
        raise OSError("synthetic Earcut failure near 12.345 67.890")

    def record_repair(poly, scale, separation_mm):
        repair_calls.append(separation_mm)
        return original_repair(poly, scale, separation_mm)

    monkeypatch.setattr(
        vector_mesh_topology.trimesh.creation,
        "triangulate_polygon",
        fail_manifold,
    )
    monkeypatch.setattr(vector_mesh_topology, "_triangulate_float64", fail_earcut)
    monkeypatch.setattr(
        vector_mesh_topology,
        "_repair_polygon_ring_contacts",
        record_repair,
    )

    with pytest.raises(
        VectorTopologyError,
        match="topology could not be repaired",
    ) as exc:
        extrude_polygon_for_export(
            polygon,
            xy_scale=1.0,
            prefer_fast=False,
        )

    assert exc.value.__cause__ is None
    assert exc.value.attempts[-1]["error_type"] == "OSError"
    formatted = "".join(
        traceback.format_exception(type(exc.value), exc.value, exc.value.__traceback__)
    )
    assert "12.345" not in formatted
    assert "67.890" not in formatted
    assert len(earcut_calls) == 3
    assert repair_calls == [0.0001, 0.001]


def test_failed_attempt_payload_is_released_before_next_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed extrusion traceback must not overlap the next attempt."""

    polygon = box(0.0, 0.0, 3.0, 2.0)
    payload_ref: weakref.ReferenceType[np.ndarray] | None = None
    calls = 0

    def fail_with_large_local(_geometry):
        nonlocal calls, payload_ref
        if calls == 0:
            payload = np.empty(2_000_000, dtype=np.float64)
            payload_ref = weakref.ref(payload)
        else:
            assert payload_ref is not None
            assert payload_ref() is None
        calls += 1
        raise OSError("synthetic bounded extrusion failure")

    monkeypatch.setattr(
        vector_mesh_topology,
        "_extrude_indexed_parts",
        fail_with_large_local,
    )

    with pytest.raises(VectorTopologyError):
        extrude_polygon_for_export(
            polygon,
            xy_scale=1.0,
            prefer_fast=False,
        )

    assert calls == 3


@pytest.mark.parametrize(
    "fatal_type",
    [MemoryError, KeyboardInterrupt, SystemExit, GeneratorExit],
)
def test_export_extrusion_does_not_swallow_process_control_errors(
    monkeypatch: pytest.MonkeyPatch,
    fatal_type: type[BaseException],
) -> None:
    """Fatal and process-control exceptions must escape the export ladder."""

    polygon = box(0.0, 0.0, 3.0, 2.0)

    def abort_fast_extrusion(*_args, **_kwargs):
        raise fatal_type("synthetic fatal failure")

    monkeypatch.setattr(
        vector_mesh_topology.trimesh.creation,
        "extrude_polygon",
        abort_fast_extrusion,
    )

    with pytest.raises(fatal_type):
        extrude_polygon_for_export(
            polygon,
            xy_scale=1.0,
            prefer_fast=True,
        )


def test_export_extrusion_rejects_unsafe_fast_mesh_for_canonical_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unsafe generic mesh must not bypass the canonical indexed result."""

    polygon = box(0.0, 0.0, 3.0, 2.0)
    original_fast_extrusion = vector_mesh_topology.trimesh.creation.extrude_polygon
    canonical_mesh = original_fast_extrusion(polygon, height=1.0)
    canonical_mesh.metadata["topology_service_marker"] = "canonical"
    fast_calls = []
    indexed_calls = []

    def return_unsafe_fast_mesh(*args, **kwargs):
        fast_calls.append((args, kwargs))
        mesh = original_fast_extrusion(*args, **kwargs)
        vertices = np.asarray(mesh.vertices, dtype=np.float64).copy()
        vertices[0] = vertices[1]
        mesh.vertices = vertices
        assert not mesh_is_float32_safe(mesh, xy_scale=1.0)
        return mesh

    def return_canonical_mesh(geometry):
        indexed_calls.append(geometry)
        return [canonical_mesh]

    monkeypatch.setattr(
        vector_mesh_topology.trimesh.creation,
        "extrude_polygon",
        return_unsafe_fast_mesh,
    )
    monkeypatch.setattr(
        vector_mesh_topology,
        "_extrude_indexed_parts",
        return_canonical_mesh,
    )

    meshes = extrude_polygon_for_export(
        polygon,
        xy_scale=1.0,
        prefer_fast=True,
    )

    assert len(fast_calls) == 1
    assert indexed_calls == [polygon]
    assert meshes == [canonical_mesh]
    assert meshes[0].metadata["topology_service_marker"] == "canonical"


def test_export_extrusion_rejects_wrong_coverage_fast_mesh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A safe fast mesh with one-sixth coverage must yield to canonical output."""

    polygon = box(0.0, 0.0, 3.0, 2.0)
    original_fast_extrusion = vector_mesh_topology.trimesh.creation.extrude_polygon
    wrong_coverage_mesh = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    wrong_coverage_mesh.apply_translation((0.0, 0.0, 0.5))
    wrong_coverage_mesh.metadata["topology_service_marker"] = "wrong_coverage"
    canonical_mesh = original_fast_extrusion(polygon, height=1.0)
    canonical_mesh.metadata["topology_service_marker"] = "canonical"
    indexed_calls = []

    def return_wrong_coverage_fast_mesh(*_args, **_kwargs):
        return wrong_coverage_mesh

    def return_canonical_mesh(geometry):
        indexed_calls.append(geometry)
        return [canonical_mesh]

    assert float(polygon.area) == pytest.approx(6.0)
    assert abs(float(wrong_coverage_mesh.volume)) == pytest.approx(1.0)
    assert wrong_coverage_mesh.is_watertight
    assert mesh_is_float32_safe(wrong_coverage_mesh, xy_scale=1.0)
    monkeypatch.setattr(
        vector_mesh_topology.trimesh.creation,
        "extrude_polygon",
        return_wrong_coverage_fast_mesh,
    )
    monkeypatch.setattr(
        vector_mesh_topology,
        "_extrude_indexed_parts",
        return_canonical_mesh,
    )

    meshes = extrude_polygon_for_export(
        polygon,
        xy_scale=1.0,
        prefer_fast=True,
    )

    assert meshes[0] is canonical_mesh
    assert indexed_calls == [polygon]
    assert meshes[0].metadata["topology_service_marker"] == "canonical"


def test_export_extrusion_repairs_point_touching_holes() -> None:
    """Hole contacts must produce only closed, two-face-per-edge shells."""

    polygon = _point_touching_holes_polygon()

    meshes = extrude_polygon_for_export(
        polygon,
        xy_scale=1.0,
        prefer_fast=False,
    )

    assert meshes
    assert all(mesh.is_watertight for mesh in meshes)
    assert all(np.all(_edge_incidence_counts(mesh) == 2) for mesh in meshes)
    assert all(mesh_is_float32_safe(mesh, xy_scale=1.0) for mesh in meshes)
    assert _total_unit_height_volume(meshes) == pytest.approx(
        float(polygon.area),
        abs=0.01,
    )


def test_export_extrusion_repairs_multiple_holes_sharing_one_point() -> None:
    """Every ring sharing one point must be separated within the area bound."""

    polygon = _multi_point_touching_holes_polygon()

    meshes = extrude_polygon_for_export(
        polygon,
        xy_scale=1.0,
        prefer_fast=False,
    )

    assert meshes
    assert all(mesh.is_watertight for mesh in meshes)
    assert all(mesh_is_float32_safe(mesh, xy_scale=1.0) for mesh in meshes)
    assert _total_unit_height_volume(meshes) == pytest.approx(
        float(polygon.area),
        abs=0.01,
    )


def test_export_extrusion_repairs_hub_with_four_point_touching_holes() -> None:
    """A symmetric contact hub is repaired as independent hole components."""

    polygon = _hub_touching_holes_polygon()

    meshes = extrude_polygon_for_export(
        polygon,
        xy_scale=1.0,
        prefer_fast=False,
    )

    assert meshes
    assert all(mesh.is_watertight for mesh in meshes)
    assert all(mesh_is_float32_safe(mesh, xy_scale=1.0) for mesh in meshes)
    assert _total_unit_height_volume(meshes) == pytest.approx(
        float(polygon.area),
        abs=0.01,
    )


def test_export_extrusion_keeps_equivalent_separated_holes_working() -> None:
    """The non-contacting control for the symmetric hub remains exportable."""

    polygon = _hub_touching_holes_polygon(contact_gap=0.01)

    meshes = extrude_polygon_for_export(
        polygon,
        xy_scale=1.0,
        prefer_fast=False,
    )

    assert meshes
    assert all(mesh.is_watertight for mesh in meshes)
    assert all(mesh_is_float32_safe(mesh, xy_scale=1.0) for mesh in meshes)
    assert _total_unit_height_volume(meshes) == pytest.approx(
        float(polygon.area),
        abs=0.01,
    )


def test_export_extrusion_preserves_non_contacting_holes_during_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A forced repair keeps already separate holes exportable and area-safe."""

    polygon = _separate_holes_polygon()
    original_indexed = vector_mesh_topology._extrude_indexed_parts
    indexed_calls = []

    def fail_original_then_extrude(geometry):
        indexed_calls.append(geometry)
        if len(indexed_calls) == 1:
            raise RuntimeError("synthetic original extrusion failure")
        return original_indexed(geometry)

    monkeypatch.setattr(
        vector_mesh_topology,
        "_extrude_indexed_parts",
        fail_original_then_extrude,
    )

    meshes = extrude_polygon_for_export(
        polygon,
        xy_scale=1.0,
        prefer_fast=False,
    )

    assert len(indexed_calls) == 2
    assert meshes
    assert all(mesh_is_float32_safe(mesh, xy_scale=1.0) for mesh in meshes)
    assert _total_unit_height_volume(meshes) == pytest.approx(
        float(polygon.area),
        abs=0.01,
    )


def test_mesh_float32_safety_rejects_scaled_vertex_collapse() -> None:
    """A float64-valid shell is unsafe when scaled XY vertices collapse."""

    mesh = trimesh.creation.box(extents=(1e-6, 2.0, 1.0))
    mesh.apply_translation((2500.0, 10.0, 0.5))
    source_vertices = np.asarray(mesh.vertices, dtype=np.float64)
    scaled_vertices = source_vertices.copy()
    scaled_vertices[:, :2] *= 0.04
    writer_vertices = scaled_vertices.astype(np.float32)
    _unique_vertices, inverse = np.unique(
        writer_vertices,
        axis=0,
        return_inverse=True,
    )
    writer_faces = inverse[np.asarray(mesh.faces, dtype=np.int64)]

    assert len(np.unique(source_vertices, axis=0)) == len(source_vertices)
    assert len(_unique_vertices) < len(scaled_vertices)
    assert np.any(
        (writer_faces[:, 0] == writer_faces[:, 1])
        | (writer_faces[:, 1] == writer_faces[:, 2])
        | (writer_faces[:, 2] == writer_faces[:, 0])
    )
    assert not mesh_is_float32_safe(mesh, xy_scale=0.04)


def test_mesh_float32_safety_validates_large_meshes_and_open_negative() -> None:
    """The vectorized validator accepts closed meshes above 64 faces."""

    polygon = Point(0.0, 0.0).buffer(1.0, resolution=20)
    mesh = trimesh.creation.extrude_polygon(polygon, height=1.0)
    open_mesh = trimesh.Trimesh(
        vertices=np.asarray(mesh.vertices, dtype=np.float64).copy(),
        faces=np.asarray(mesh.faces, dtype=np.int64)[:-1].copy(),
        process=False,
    )
    reversed_faces = np.asarray(mesh.faces, dtype=np.int64).copy()
    reversed_faces[0] = reversed_faces[0, ::-1]
    inconsistent_mesh = trimesh.Trimesh(
        vertices=np.asarray(mesh.vertices, dtype=np.float64).copy(),
        faces=reversed_faces,
        process=False,
    )

    assert len(mesh.faces) > 64
    assert mesh.is_watertight
    assert mesh_is_float32_safe(mesh, xy_scale=1.0)
    assert len(open_mesh.faces) > 64
    assert not open_mesh.is_watertight
    assert not mesh_is_float32_safe(open_mesh, xy_scale=1.0)
    assert inconsistent_mesh.is_watertight
    assert not inconsistent_mesh.is_winding_consistent
    assert not mesh_is_float32_safe(inconsistent_mesh, xy_scale=1.0)


def test_mesh_float32_safety_rejects_inconsistent_winding() -> None:
    """A closed mesh with one reversed face is not safe for slicer export."""

    mesh = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    faces = np.asarray(mesh.faces, dtype=np.int64).copy()
    faces[0] = faces[0, ::-1]
    reversed_face_mesh = trimesh.Trimesh(
        vertices=np.asarray(mesh.vertices, dtype=np.float64).copy(),
        faces=faces,
        process=False,
    )

    assert reversed_face_mesh.is_watertight
    assert not reversed_face_mesh.is_winding_consistent
    assert not mesh_is_float32_safe(reversed_face_mesh, xy_scale=1.0)


def test_writer_cap_profile_excludes_triangulation_diagonals_and_bridges() -> None:
    """Only the filled cap outline participates in component contact checks."""

    rectangle = trimesh.creation.extrude_polygon(
        box(0.0, 0.0, 2.0, 1.0),
        height=1.0,
    )
    rectangle_arrays = vector_mesh_topology._mesh_arrays(rectangle)
    assert rectangle_arrays is not None
    rectangle_vertices, rectangle_faces = rectangle_arrays
    rectangle_writer = vector_mesh_topology._writer_vertices_for_offset(
        rectangle_vertices,
        1.0,
    )
    rectangle_profile = vector_mesh_topology._writer_boundary_profile(
        rectangle_writer,
        rectangle_faces,
    )
    assert rectangle_profile is not None
    assert rectangle_profile.footprint.boundary.length == pytest.approx(6.0)

    hole_mesh = vector_mesh_topology._extrude_indexed_parts(
        _separate_holes_polygon()
    )[0]
    hole_arrays = vector_mesh_topology._mesh_arrays(hole_mesh)
    assert hole_arrays is not None
    hole_vertices, hole_faces = hole_arrays
    hole_writer = vector_mesh_topology._writer_vertices_for_offset(
        hole_vertices,
        1.0,
    )
    hole_profile = vector_mesh_topology._writer_boundary_profile(
        hole_writer,
        hole_faces,
    )
    assert hole_profile is not None
    assert hole_profile.footprint.boundary.is_simple
    assert len(hole_profile.footprint.boundary.geoms) == 5


def test_writer_component_contact_uses_closed_z_intervals() -> None:
    """Separated Z ranges are safe, while a shared Z boundary is contact."""

    float32_gap = 9.5367431640625e-7
    component_a = trimesh.creation.extrude_polygon(
        box(199.0, 0.0, 200.0, 2.0),
        height=1.0,
    )
    component_b = trimesh.creation.extrude_polygon(
        Polygon(
            [
                (200.0 + float32_gap, 0.7),
                (201.0, 0.2),
                (201.0, 1.4),
            ]
        ),
        height=1.0,
    )

    z_separated = component_b.copy()
    z_separated.apply_translation((0.0, 0.0, 1.01))
    assert mesh_is_float32_safe(
        trimesh.util.concatenate([component_a, z_separated]),
        xy_scale=1.0,
    )

    z_touching = component_b.copy()
    z_touching.apply_translation((0.0, 0.0, 1.0))
    assert not mesh_is_float32_safe(
        trimesh.util.concatenate([component_a, z_touching]),
        xy_scale=1.0,
    )


def test_writer_component_contact_detects_nested_footprint_after_z_rounding() -> None:
    """A contained cap touching only after float32 Z conversion is unsafe."""

    lower = trimesh.creation.extrude_polygon(
        box(0.0, 0.0, 10.0, 10.0),
        height=1.0,
    )
    upper = trimesh.creation.extrude_polygon(
        box(4.0, 4.0, 6.0, 6.0),
        height=1.0,
    )
    upper.apply_translation((0.0, 0.0, 1.0 + 2.98e-8))
    assert float(np.min(upper.vertices[:, 2])) > 1.0
    assert np.float32(np.min(upper.vertices[:, 2])) == np.float32(1.0)

    combined = trimesh.util.concatenate([lower, upper])
    assert combined.is_watertight
    assert not mesh_is_float32_safe(combined, xy_scale=1.0)


def test_disjoint_non_prismatic_components_with_overlapping_aabbs_are_safe() -> None:
    """The prism fast path must not make nearby generic solids false-negative."""

    first = trimesh.creation.icosphere(subdivisions=1, radius=1.0)
    second = trimesh.creation.icosphere(subdivisions=1, radius=1.0)
    second.apply_translation((1.45, 1.45, 0.0))
    assert np.linalg.norm([1.45, 1.45]) > 2.0
    assert np.all(first.bounds[0] <= second.bounds[1])
    assert np.all(second.bounds[0] <= first.bounds[1])

    combined = trimesh.util.concatenate([first, second])
    assert combined.is_watertight
    assert mesh_is_float32_safe(combined, xy_scale=1.0)


def test_non_prismatic_middle_section_contact_is_not_hidden_by_equal_caps() -> None:
    """Equal end caps cannot certify a solid that bulges at an intermediate Z."""

    hourglass = _three_level_hourglass()
    gap = float(np.spacing(np.float32(2.0))) / 4.0
    neighbour = trimesh.creation.box(extents=(0.2, 0.2, 0.2))
    neighbour.apply_translation((2.1 + gap, 0.0, 0.5))
    assert float(hourglass.bounds[1, 0]) < float(neighbour.bounds[0, 0])
    assert np.float32(hourglass.bounds[1, 0]) == np.float32(
        neighbour.bounds[0, 0]
    )

    combined = trimesh.util.concatenate([hourglass, neighbour])
    assert combined.is_watertight
    assert not mesh_is_float32_safe(combined, xy_scale=1.0)


def test_generic_component_contact_detects_full_volume_containment() -> None:
    """Disjoint triangle surfaces are still unsafe when one shell contains another."""

    outer = trimesh.creation.icosphere(subdivisions=1, radius=2.0)
    inner = trimesh.creation.icosphere(subdivisions=1, radius=1.0)
    combined = trimesh.util.concatenate([outer, inner])

    assert combined.is_watertight
    assert not mesh_is_float32_safe(combined, xy_scale=1.0)


def test_component_separation_rejects_internal_float32_collapse_without_pairs() -> None:
    """Every component is validated even when broad phase finds no neighbour."""

    collapsing = trimesh.creation.box(extents=(1e-6, 1.0, 1.0))
    collapsing.apply_translation((200.0, 0.0, 0.0))
    assert not mesh_is_float32_safe(collapsing, xy_scale=1.0)
    assert not separate_component_coordinates([collapsing], xy_scale=1.0)


def test_cap_union_rejects_overlapping_triangle_area() -> None:
    """A union cannot normalize overlapping cap triangles into valid coverage."""

    writer_vertices = np.asarray(
        [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ],
        dtype=np.float32,
    )
    duplicate_faces = np.asarray([(0, 1, 2), (0, 1, 2)], dtype=np.int64)
    assert (
        vector_mesh_topology._filled_cap_footprint(
            writer_vertices,
            duplicate_faces,
            np.float32(0.0),
        )
        is None
    )


def test_writer_contact_uses_face_edge_components_not_body_count() -> None:
    """Vertex-connected shells remain separate face-edge components."""

    first = trimesh.creation.extrude_polygon(
        box(0.0, 0.0, 1.0, 1.0),
        height=1.0,
    )
    second = trimesh.creation.extrude_polygon(
        box(1.0, 1.0, 2.0, 2.0),
        height=1.0,
    )
    second.apply_translation((0.0, 0.0, 1.0))
    combined = trimesh.util.concatenate([first, second])
    combined.merge_vertices()

    assert combined.is_watertight
    assert combined.body_count == 1
    assert not mesh_is_float32_safe(combined, xy_scale=1.0)


def test_component_coordinate_separation_survives_float32_writer_mapping() -> None:
    """Touching independent components keep closed topology after float32 IO."""

    meshes = extrude_polygon_for_export(
        box(0.0, 0.0, 1.0, 1.0),
        xy_scale=1.0,
        prefer_fast=True,
    ) + extrude_polygon_for_export(
        box(1.0, 0.0, 2.0, 1.0),
        xy_scale=1.0,
        prefer_fast=True,
    )

    original_vertices = [
        np.asarray(mesh.vertices, dtype=np.float64).copy() for mesh in meshes
    ]
    assert separate_component_coordinates(meshes)
    translations = []
    for mesh, vertices_before in zip(meshes, original_vertices):
        translation = np.asarray(mesh.vertices, dtype=np.float64) - vertices_before
        np.testing.assert_allclose(
            translation,
            np.broadcast_to(translation[0], translation.shape),
        )
        translations.append(translation[0])
    assert any(np.any(np.abs(translation[:2]) > 0.0) for translation in translations)
    assert all(
        np.max(np.abs(translation[:2])) <= MAX_COMPONENT_SEPARATION_MM
        for translation in translations
    )
    assert all(translation[2] == pytest.approx(0.0) for translation in translations)
    writer_vertices, writer_faces = _float32_combined_mesh(meshes)
    assert not np.any(
        (writer_faces[:, 0] == writer_faces[:, 1])
        | (writer_faces[:, 1] == writer_faces[:, 2])
        | (writer_faces[:, 2] == writer_faces[:, 0])
    )
    writer_mesh = trimesh.Trimesh(
        vertices=writer_vertices,
        faces=writer_faces,
        process=False,
    )
    assert np.all(_edge_incidence_counts(writer_mesh) == 2)


def test_component_separation_rejects_out_of_range_face_indexes() -> None:
    """Malformed component indexes fail closed before any translation."""

    mesh = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    faces = np.asarray(mesh.faces, dtype=np.int64).copy()
    faces[0, 0] = len(mesh.vertices) + 5
    malformed = trimesh.Trimesh(
        vertices=np.asarray(mesh.vertices, dtype=np.float64).copy(),
        faces=faces,
        process=False,
    )
    assert not separate_component_coordinates([malformed])


def test_disjoint_component_broad_phase_skips_cap_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Many separated shells take the indexed broad phase, not all-pairs work."""

    meshes = []
    for index in range(512):
        mesh = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
        mesh.apply_translation((float(index * 3), 0.0, 0.0))
        meshes.append(mesh)
    profile_calls = 0
    original_profile = vector_mesh_topology._writer_boundary_profile

    def count_profile_calls(*args, **kwargs):
        nonlocal profile_calls
        profile_calls += 1
        return original_profile(*args, **kwargs)

    monkeypatch.setattr(
        vector_mesh_topology,
        "_writer_boundary_profile",
        count_profile_calls,
    )
    assert separate_component_coordinates(meshes)
    assert profile_calls == 0


def test_dense_component_broad_phase_fails_with_bounded_pair_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dense component set is rejected before materialising all N-squared pairs."""

    monkeypatch.setattr(
        vector_mesh_topology,
        "_COMPONENT_AABB_PAIR_LIMIT",
        16,
    )
    prototype = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    meshes = [prototype.copy() for _ in range(64)]
    assert not separate_component_coordinates(meshes)


def test_dense_xy_broad_phase_counts_candidates_before_z_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Equal XY boxes at disjoint Z cannot bypass the broad-phase budget."""

    monkeypatch.setattr(
        vector_mesh_topology,
        "_COMPONENT_AABB_PAIR_LIMIT",
        16,
    )
    bounds = np.asarray(
        [(0.0, 0.0, float(index * 2), 1.0, 1.0, float(index * 2 + 1))
         for index in range(64)],
        dtype=np.float64,
    )
    with pytest.raises(vector_mesh_topology._ComponentPairBudgetExceeded):
        list(vector_mesh_topology._candidate_component_pairs(bounds))


def test_template_retry_never_reports_success_with_writer_contact() -> None:
    """A retry must revalidate both caps after float32 bins split them apart."""

    midpoint_low = 199.99999237060547
    midpoint_high = 200.00000762939453
    bottom_right = midpoint_low + 0.1 * (midpoint_high - midpoint_low)
    top_right = midpoint_low + 0.9 * (midpoint_high - midpoint_low)
    anchor = trimesh.creation.extrude_polygon(
        box(198.0, 0.0, 199.0, 1.0),
        height=1.0,
    )
    mover = _rectangular_frustum(
        left_x=199.0,
        bottom_right_x=bottom_right,
        top_right_x=top_right,
    )
    blocker_left = float(np.float32(top_right + 0.0001))
    blocker = trimesh.creation.extrude_polygon(
        box(blocker_left, 0.0, 201.0, 1.0),
        height=1.0,
    )
    meshes = [anchor, mover, blocker]
    original_vertices = [mesh.vertices.copy() for mesh in meshes]

    separated = separate_component_coordinates(meshes, xy_scale=1.0)
    if separated:
        assert mesh_is_float32_safe(
            trimesh.util.concatenate(meshes),
            xy_scale=1.0,
        )
    else:
        assert all(
            np.array_equal(mesh.vertices, original)
            for mesh, original in zip(meshes, original_vertices)
        )


def test_retry_uses_retriangulated_cap_union_not_stale_boundary_indexes() -> None:
    """Float32 can move an internal diagonal beyond a cached concave boundary."""

    anchor = box(99.0, 195.0, 99.9999999, 205.0)
    mover = Polygon(
        [
            (200.00087036433843, 200.0006904831091),
            (200.0002785, 210.0),
            (100.0, 210.0),
            (100.0, 190.0),
            (200.00011049400032, 199.99891889649209),
            (200.00039372344105, 199.9995510250455),
        ]
    )
    contact = (200.00059509277344, 199.9998016357422)
    blocker = Polygon(
        [
            contact,
            (contact[0] + 1.0, contact[1] - 1.0),
            (contact[0] + 1.0, contact[1] - 2.0),
        ]
    )
    assert anchor.distance(mover) > 0.0
    assert mover.distance(blocker) > 0.0
    meshes = [
        trimesh.creation.extrude_polygon(footprint, height=1.0)
        for footprint in (anchor, mover, blocker)
    ]
    assert all(mesh_is_float32_safe(mesh, xy_scale=1.0) for mesh in meshes)

    separated = separate_component_coordinates(meshes, xy_scale=1.0)
    assert separated
    assert mesh_is_float32_safe(
        trimesh.util.concatenate(meshes),
        xy_scale=1.0,
    )


@pytest.mark.parametrize("subdivision_rounds", [0, 2], ids=["small", "large"])
def test_writer_domain_rejects_vertex_on_other_component_edge(
    subdivision_rounds: int,
) -> None:
    """Float32 mapping must keep disjoint shells strictly disjoint."""

    float32_gap = 9.5367431640625e-7
    component_a = box(199.0, 0.0, 200.0, 2.0)
    component_b = Polygon(
        [
            (200.0 + float32_gap, 0.7),
            (201.0, 0.2),
            (201.0, 1.4),
        ]
    )
    assert component_a.is_valid
    assert component_b.is_valid
    assert component_a.distance(component_b) > 0.0

    meshes = extrude_polygon_for_export(
        component_a,
        xy_scale=1.0,
        prefer_fast=True,
    ) + extrude_polygon_for_export(
        component_b,
        xy_scale=1.0,
        prefer_fast=True,
    )
    for _ in range(subdivision_rounds):
        meshes = [mesh.subdivide() for mesh in meshes]
    if subdivision_rounds:
        assert sum(len(mesh.faces) for mesh in meshes) > 64

    combined_before = trimesh.util.concatenate(meshes)
    assert not mesh_is_float32_safe(combined_before, xy_scale=1.0)

    original_vertices = [
        np.asarray(mesh.vertices, dtype=np.float64).copy() for mesh in meshes
    ]
    original_volumes = [abs(float(mesh.volume)) for mesh in meshes]
    assert separate_component_coordinates(meshes, xy_scale=1.0)

    translations = []
    writer_footprints = []
    for mesh, vertices_before in zip(meshes, original_vertices):
        vertices_after = np.asarray(mesh.vertices, dtype=np.float64)
        translation = vertices_after - vertices_before
        np.testing.assert_allclose(
            translation,
            np.broadcast_to(translation[0], translation.shape),
        )
        translations.append(translation[0])
        writer_vertices = vertices_after.astype(np.float32).astype(np.float64)
        writer_footprints.append(MultiPoint(writer_vertices[:, :2]).convex_hull)

    assert any(np.any(np.abs(offset[:2]) > 0.0) for offset in translations)
    assert all(
        np.max(np.abs(offset[:2])) <= MAX_COMPONENT_SEPARATION_MM
        for offset in translations
    )
    assert writer_footprints[0].distance(writer_footprints[1]) > 0.0
    assert not writer_footprints[0].intersects(writer_footprints[1])

    combined_after = trimesh.util.concatenate(meshes)
    assert mesh_is_float32_safe(combined_after, xy_scale=1.0)
    assert [abs(float(mesh.volume)) for mesh in meshes] == pytest.approx(
        original_volumes,
    )


def test_component_separation_failure_preserves_every_vertex() -> None:
    """Exhausting all 65 fixed offsets leaves every component unchanged."""

    prototype = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
    meshes = [
        prototype.copy() for _ in range(MAX_COMPONENT_OFFSET_CANDIDATES + 1)
    ]
    original_vertices = [
        np.asarray(mesh.vertices, dtype=np.float64).copy() for mesh in meshes
    ]

    assert not separate_component_coordinates(meshes)
    for mesh, vertices_before in zip(meshes, original_vertices):
        assert np.array_equal(np.asarray(mesh.vertices), vertices_before)


def test_component_separation_rejects_writer_coverage_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A collision-free offset is still rejected if float32 volume drifts."""

    meshes = [
        trimesh.creation.extrude_polygon(footprint, height=1.0)
        for footprint in (
            box(0.0, 0.0, 1.0, 1.0),
            box(1.0, 0.0, 2.0, 1.0),
        )
    ]
    original_vertices = [np.asarray(mesh.vertices).copy() for mesh in meshes]
    original_metrics = vector_mesh_topology._writer_mesh_metrics
    call_count = 0

    def drift_after_initial_measurements(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        valid, coverage = original_metrics(*args, **kwargs)
        if call_count > len(meshes) and coverage is not None:
            coverage += 1.0
        return valid, coverage

    monkeypatch.setattr(
        vector_mesh_topology,
        "_writer_mesh_metrics",
        drift_after_initial_measurements,
    )
    monkeypatch.setattr(
        vector_mesh_topology,
        "_writer_boundary_profile",
        lambda *_args, **_kwargs: None,
    )
    assert not separate_component_coordinates(meshes)
    assert call_count > len(meshes)
    for mesh, before in zip(meshes, original_vertices):
        assert np.array_equal(np.asarray(mesh.vertices), before)


def test_prism_retry_uses_footprint_area_not_height_scaled_volume() -> None:
    """The public mm2 coverage tolerance stays independent of extrusion height."""

    low_200 = 199.99999237060547
    high_200 = 200.00000762939453
    left = low_200 + 0.1 * (high_200 - low_200)
    target_201 = float(np.float32(201.0))
    previous_201 = float(
        np.nextafter(np.float32(201.0), np.float32(-np.inf))
    )
    next_201 = float(np.nextafter(np.float32(201.0), np.float32(np.inf)))
    low_201 = (previous_201 + target_201) / 2.0
    high_201 = (target_201 + next_201) / 2.0
    right = low_201 + 0.9 * (high_201 - low_201)
    footprint = box(left, 0.0, right, 1000.0)
    mover = trimesh.creation.extrude_polygon(footprint, height=0.1)
    arrays = vector_mesh_topology._mesh_arrays(mover)
    assert arrays is not None
    vertices, faces = arrays
    initial_writer = vector_mesh_topology._writer_vertices_for_offset(
        vertices,
        1.0,
    )
    moved_writer = vector_mesh_topology._writer_vertices_for_offset(
        vertices,
        1.0,
        (0.0001, 0.0, 0.0),
    )
    assert initial_writer is not None and moved_writer is not None
    initial_profile = vector_mesh_topology._writer_boundary_profile(
        initial_writer,
        faces,
    )
    moved_profile = vector_mesh_topology._writer_boundary_profile(
        moved_writer,
        faces,
    )
    assert initial_profile is not None and moved_profile is not None
    assert not vector_mesh_topology._coverage_is_safe(
        float(initial_profile.footprint.area),
        float(moved_profile.footprint.area),
    )


def test_component_separation_rolls_back_after_translation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later translation failure restores an earlier nonzero translation."""

    meshes = [
        trimesh.creation.extrude_polygon(
            footprint,
            height=0.1,
        )
        for footprint in (
            box(0.0, 0.0, 1.0, 1.0),
            box(1.0, 1.0, 2.0, 2.0),
            box(-1.0, 1.0, 0.0, 2.0),
        )
    ]
    original_vertices = [
        np.asarray(mesh.vertices, dtype=np.float64).copy() for mesh in meshes
    ]
    successful_translations = []
    failed_translations = []
    original_apply_translation = meshes[1].apply_translation

    def record_nonzero_translation(offset):
        successful_translations.append(np.asarray(offset, dtype=np.float64))
        return original_apply_translation(offset)

    def fail_later_translation(offset):
        failed_translations.append(np.asarray(offset, dtype=np.float64))
        raise RuntimeError("synthetic translation failure")

    monkeypatch.setattr(
        meshes[1],
        "apply_translation",
        record_nonzero_translation,
        raising=False,
    )
    monkeypatch.setattr(
        meshes[2],
        "apply_translation",
        fail_later_translation,
        raising=False,
    )

    assert not separate_component_coordinates(meshes)
    assert successful_translations
    assert np.any(np.abs(successful_translations[0][:2]) > 0.0)
    assert failed_translations
    for mesh, vertices_before in zip(meshes, original_vertices):
        assert np.array_equal(np.asarray(mesh.vertices), vertices_before)
