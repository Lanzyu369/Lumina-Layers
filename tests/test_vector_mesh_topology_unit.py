"""Contract tests for the shared vector topology export service."""

from __future__ import annotations

import pickle
import traceback
import weakref

import numpy as np
import pytest
import trimesh
from shapely.geometry import Point, Polygon, box

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


def test_component_separation_rolls_back_after_translation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later translation failure restores an earlier nonzero translation."""

    prototype = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
    meshes = [prototype.copy() for _ in range(3)]
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
