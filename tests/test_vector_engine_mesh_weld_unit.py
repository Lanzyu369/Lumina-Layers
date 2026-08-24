"""Regression tests for vector mesh topology at shape borders.

Independent extrusions may touch in physical space, but they must keep separate
vertex indices unless their coincident internal walls are removed as part of a
real boolean union.  Blind coordinate welding leaves those walls in place and
creates edges used by four or more faces; Bambu Studio and OrcaSlicer may then
drop large connected regions while reconstructing layer contours.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh
from scipy.spatial import cKDTree
from shapely import wkt
from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.ops import unary_union

import core.vector_engine as vector_engine
from core.errors import VectorTopologyError
from core.vector_engine import (
    VectorAnalysis,
    VectorProcessor,
    _build_atomic_prism_mesh,
    _build_stepped_volume_mesh,
    _cap_planar_area_mm2,
    _concatenate_meshes_fast,
    _finalize_prism_meshes,
)
from core.vector_mesh_topology import (
    VECTOR_COVERAGE_ABS_TOL_MM2,
    VECTOR_COVERAGE_REL_TOL,
    extrude_polygon_for_export,
    mesh_is_float32_safe,
    prepare_geometry_for_float32,
)


def _coincident_pair_count(mesh: trimesh.Trimesh, tol: float = 1e-6) -> int:
    """Count vertex pairs within *tol* mm — i.e. would be welded together."""
    if mesh.vertices.shape[0] < 2:
        return 0
    tree = cKDTree(mesh.vertices)
    pairs = tree.query_pairs(r=tol, output_type="ndarray")
    return int(pairs.shape[0])


def _edge_incidence_counts(mesh: trimesh.Trimesh) -> np.ndarray:
    """Return how many triangle faces use each indexed mesh edge."""

    edges = np.asarray(mesh.edges_sorted, dtype=np.int64)
    if len(edges) == 0:
        return np.empty(0, dtype=np.int64)
    _unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    return counts


class _CoverageMetadataMesh:
    """Mesh sentinel that rejects the triangle-volume fallback."""

    metadata = {"_lumina_planar_coverage_mm2": 12.5}

    @property
    def volume(self):
        raise AssertionError("metadata fast path must not scan mesh volume")


def test_planar_coverage_uses_extrusion_metadata_without_volume_scan() -> None:
    """Known coverage must keep validation independent of triangle count."""

    coverage = vector_engine._extruded_planar_coverage_mm2(
        [_CoverageMetadataMesh()],
        height=0.2,
    )

    assert coverage == pytest.approx(12.5)


def test_cap_planar_area_is_measured_from_generated_triangles() -> None:
    """Coverage metadata must be derived from the actual cap mesh."""

    vertices, faces = vector_engine._direct_convex_extrusion_base(
        box(0.0, 0.0, 3.0, 2.0),
        2.0,
    )

    assert _cap_planar_area_mm2(vertices, faces) == pytest.approx(24.0)


@pytest.mark.parametrize(
    ("polygon", "writer_vertices_stay_distinct"),
    [
        (
            Polygon(
                [
                    (
                        2500.0 + 1000.0 * np.cos(angle),
                        2500.0 + 1000.0 * np.sin(angle),
                    )
                    for angle in (0.0, 1.0, 1.0 + 1e-8, 2.0, 3.0, 4.0, 5.0)
                ]
            ),
            False,
        ),
        (
            Polygon(
                [
                    (1500.0, 2500.0),
                    (2500.0, 2499.99999),
                    (3500.0, 2500.0),
                    (3500.0, 3500.0),
                    (1500.0, 3500.0),
                ]
            ),
            True,
        ),
    ],
    ids=("near_duplicate", "distinct_collinear"),
)
def test_float32_unsafe_direct_convex_candidate_routes_to_shared_service(
    polygon: Polygon,
    writer_vertices_stay_distinct: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct convex output must not bypass writer-domain topology safety."""

    scale = 0.04
    direct = vector_engine._direct_convex_extrusion_base(polygon, scale)
    assert direct is not None
    direct_mesh = trimesh.Trimesh(
        vertices=direct[0],
        faces=direct[1],
        process=False,
    )
    assert not mesh_is_float32_safe(direct_mesh, xy_scale=1.0)
    writer_vertices = np.asarray(direct_mesh.vertices, dtype=np.float32)
    if writer_vertices_stay_distinct:
        assert len(np.unique(writer_vertices, axis=0)) == len(writer_vertices)
        triangles = writer_vertices[direct_mesh.faces].astype(np.float64)
        crosses = np.cross(
            triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 0],
        )
        assert np.any(np.all(crosses == 0.0, axis=1))
    if len(polygon.exterior.coords) == 8:
        assert float(polygon.area) * scale * scale == pytest.approx(
            4133.023362639679
        )

    service_calls = []
    real_service = vector_engine.extrude_polygon_for_export

    def traced_service(poly, *, xy_scale, prefer_fast):
        service_calls.append((poly, xy_scale, prefer_fast))
        return real_service(
            poly,
            xy_scale=xy_scale,
            prefer_fast=prefer_fast,
        )

    monkeypatch.setattr(
        vector_engine,
        "extrude_polygon_for_export",
        traced_service,
    )
    meshes = VectorProcessor._extrude_geometry(
        polygon,
        height=0.2,
        z_offset=0.3,
        scale=scale,
        extrude_cache={},
    )

    assert len(service_calls) == 1
    assert service_calls[0][0].equals(polygon)
    assert service_calls[0][1] == pytest.approx(scale)
    assert service_calls[0][2] is False
    assert len(meshes) == 1
    assert mesh_is_float32_safe(meshes[0], xy_scale=1.0)
    np.testing.assert_allclose(meshes[0].bounds[:, 2], [0.3, 0.5])


def test_extrude_geometry_routes_nonconvex_polygon_through_shared_topology_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The non-convex production path keeps coverage through one service."""

    polygon = Polygon(
        [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (2.0, 2.0), (0.0, 4.0)]
    )
    assert vector_engine._direct_convex_extrusion_base(polygon, 1.0) is None
    calls = []

    def fake_extrude_polygon_for_export(poly, *, xy_scale, prefer_fast):
        calls.append((poly, xy_scale, prefer_fast))
        mesh = trimesh.creation.extrude_polygon(poly, height=1.0)
        mesh.apply_translation((10.0, 20.0, 0.0))
        return [mesh]

    monkeypatch.setattr(
        vector_engine,
        "extrude_polygon_for_export",
        fake_extrude_polygon_for_export,
    )

    meshes = VectorProcessor._extrude_geometry(
        polygon,
        height=0.25,
        z_offset=0.0,
        scale=1.0,
        extrude_cache={},
    )

    assert len(calls) == 1
    assert calls[0][0].equals(polygon)
    assert calls[0][1] == pytest.approx(1.0)
    assert calls[0][2] is False
    assert len(meshes) == 1
    assert meshes[0].is_watertight
    assert np.all(_edge_incidence_counts(meshes[0]) == 2)
    assert abs(float(meshes[0].volume)) == pytest.approx(
        float(polygon.area) * 0.25,
    )
    np.testing.assert_allclose(
        meshes[0].bounds[:, :2],
        np.asarray(polygon.bounds, dtype=np.float64).reshape(2, 2)
        + np.asarray((10.0, 20.0)),
    )


def test_extrude_geometry_fails_closed_when_shared_topology_service_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shared-service error rejects the polygon without legacy fallback."""

    polygon = Polygon(
        [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (2.0, 2.0), (0.0, 4.0)]
    )
    assert vector_engine._direct_convex_extrusion_base(polygon, 1.0) is None
    service_calls = []

    def fail_shared_topology_service(*_args, **_kwargs):
        service_calls.append(True)
        raise ValueError("synthetic topology service failure")

    monkeypatch.setattr(
        vector_engine,
        "extrude_polygon_for_export",
        fail_shared_topology_service,
    )

    with pytest.raises(ValueError, match="refusing partial model export"):
        VectorProcessor._extrude_geometry(
            polygon,
            height=0.25,
            z_offset=0.0,
            scale=1.0,
            extrude_cache={},
        )

    assert service_calls == [True]


def test_lum_20260811_002_ring_contact_extrudes_to_slicer_safe_shell() -> None:
    """A production contour must not create 4- or 6-face vertical edges.

    The source polygon is valid and conserves area/volume, but it contains an
    exterior-ring contact at sub-nanometre distance.  Extruding it verbatim
    produces non-manifold indexed edges that Bambu Studio and OrcaSlicer may
    resolve by dropping a large connected region from the first layers.
    """

    fixture_path = (
        Path(__file__).parent
        / "fixtures"
        / "svg_regression"
        / "lum_20260811_002_ring_contact.wkt"
    )
    polygon = wkt.loads(fixture_path.read_text(encoding="utf-8"))
    scale = 0.2762232707950837
    layer_height = 0.08

    meshes = VectorProcessor._extrude_geometry(
        polygon,
        height=layer_height,
        z_offset=0.0,
        scale=scale,
    )

    assert len(meshes) == 1
    mesh = meshes[0]
    expected_volume = float(polygon.area) * scale * scale * layer_height
    coverage_tolerance_mm2 = max(
        VECTOR_COVERAGE_ABS_TOL_MM2,
        float(polygon.area) * scale * scale * VECTOR_COVERAGE_REL_TOL,
    )
    assert abs(float(mesh.volume)) == pytest.approx(
        expected_volume,
        abs=coverage_tolerance_mm2 * layer_height,
    )
    assert mesh.is_watertight
    assert np.all(_edge_incidence_counts(mesh) == 2)


def _assert_atomic_prism_contract(
    polygon: Polygon,
    *,
    scale: float,
    z_start: float,
    z_end: float,
    expected_component_count: int = 1,
) -> None:
    """Assert cap, side-wall, coverage, and orientation agreement."""

    raw_prism = _build_atomic_prism_mesh(
        polygon,
        z_start=z_start,
        z_end=z_end,
        scale_factor=scale,
    )

    assert raw_prism is not None
    prism = _finalize_prism_meshes([raw_prism])
    assert prism is not None
    assert prism.is_watertight
    assert prism.is_winding_consistent
    np.testing.assert_allclose(prism.bounds[:, 2], [z_start, z_end])

    components = prism.split(only_watertight=False)
    assert len(components) == expected_component_count
    assert all(component.is_watertight for component in components)
    assert all(component.is_winding_consistent for component in components)

    height = z_end - z_start
    cap_area_mm2 = 0.0
    for component in components:
        np.testing.assert_allclose(component.bounds[:, 2], [z_start, z_end])
        vertices = np.asarray(component.vertices, dtype=np.float64)
        faces = np.asarray(component.faces, dtype=np.int64)
        face_vertices = vertices[faces]
        face_z = face_vertices[:, :, 2]
        bottom_mask = np.all(
            np.isclose(face_z, z_start, rtol=0.0, atol=1e-9),
            axis=1,
        )
        bottom_faces = faces[bottom_mask]
        assert len(bottom_faces) > 0
        bottom_triangles = vertices[bottom_faces, :2]
        edge_a = bottom_triangles[:, 1] - bottom_triangles[:, 0]
        edge_b = bottom_triangles[:, 2] - bottom_triangles[:, 0]
        component_cap_area_mm2 = float(
            np.sum(
                np.abs(
                    edge_a[:, 0] * edge_b[:, 1]
                    - edge_a[:, 1] * edge_b[:, 0]
                ),
                dtype=np.float64,
            )
            * 0.5
        )
        cap_area_mm2 += component_cap_area_mm2
        assert abs(float(component.volume)) == pytest.approx(
            component_cap_area_mm2 * height
        )

        cap_edges = np.vstack(
            (
                bottom_faces[:, [0, 1]],
                bottom_faces[:, [1, 2]],
                bottom_faces[:, [2, 0]],
            )
        )
        sorted_cap_edges = np.sort(cap_edges, axis=1)
        unique_cap_edges, cap_edge_counts = np.unique(
            sorted_cap_edges,
            axis=0,
            return_counts=True,
        )

        def xy_edge_key(vertex_indices) -> tuple:
            points = [tuple(vertices[int(index), :2]) for index in vertex_indices]
            return tuple(sorted(points))

        cap_boundary_xy = {
            xy_edge_key(edge)
            for edge in unique_cap_edges[cap_edge_counts == 1]
        }
        assert cap_boundary_xy
        side_bottom_xy = set()
        side_mask = np.ptp(face_z, axis=1) > 1e-9
        for face in faces[side_mask]:
            bottom_indices = [
                int(index)
                for index in face
                if np.isclose(
                    vertices[int(index), 2],
                    z_start,
                    rtol=0.0,
                    atol=1e-9,
                )
            ]
            if len(bottom_indices) == 2:
                side_bottom_xy.add(xy_edge_key(bottom_indices))

        assert side_bottom_xy == cap_boundary_xy

    source_area_mm2 = float(polygon.area) * scale * scale
    coverage_tolerance_mm2 = max(
        VECTOR_COVERAGE_ABS_TOL_MM2,
        source_area_mm2 * VECTOR_COVERAGE_REL_TOL,
    )
    assert abs(float(prism.volume)) == pytest.approx(cap_area_mm2 * height)
    assert abs(cap_area_mm2 - source_area_mm2) <= coverage_tolerance_mm2


def test_precision_snapped_atomic_prism_uses_actual_cap_boundary_for_sides() -> None:
    """A snapped cap and its side walls must describe the same closed prism."""

    fixture_path = (
        Path(__file__).parent
        / "fixtures"
        / "svg_regression"
        / "lum_20260811_002_ring_contact.wkt"
    )
    polygon = wkt.loads(fixture_path.read_text(encoding="utf-8"))

    _assert_atomic_prism_contract(
        polygon,
        scale=0.2762232707950837,
        z_start=0.35,
        z_end=1.15,
    )


def test_atomic_prism_with_hole_uses_actual_cap_boundary_for_sides() -> None:
    """Exterior and hole walls must both follow the generated cap boundary."""

    polygon = Polygon(
        [
            (1500.0, 1500.0),
            (3500.0, 1500.0),
            (3500.0, 3500.0),
            (1500.0, 3500.0),
        ],
        [
            [
                (2200.0, 2200.0),
                (2200.0, 2800.0),
                (2800.0, 2800.0),
                (2800.0, 2200.0),
            ]
        ],
    )

    _assert_atomic_prism_contract(
        polygon,
        scale=0.04,
        z_start=0.2,
        z_end=1.05,
    )


def test_atomic_prism_preserves_every_precision_repair_component() -> None:
    """A sub-grid dumbbell bridge must repair into two complete shells."""

    polygon = unary_union(
        [
            box(0.0, 0.0, 1.0, 1.0),
            # This positive float64 bridge collapses on the 0.0001 mm grid.
            box(1.0, 0.5, 2.0, 0.5 + 1e-13),
            box(2.0, 0.0, 3.0, 1.0),
        ]
    )
    assert isinstance(polygon, Polygon)
    assert polygon.is_valid

    repaired = prepare_geometry_for_float32(polygon, xy_scale=1.0)
    assert repaired is not None
    assert repaired.geom_type == "MultiPolygon"
    assert len(repaired.geoms) == 2
    export_parts = extrude_polygon_for_export(
        polygon,
        xy_scale=1.0,
        prefer_fast=False,
    )
    assert len(export_parts) == len(repaired.geoms)

    _assert_atomic_prism_contract(
        polygon,
        scale=1.0,
        z_start=0.25,
        z_end=1.0,
        expected_component_count=len(repaired.geoms),
    )


@pytest.mark.parametrize(
    ("z_start", "z_end"),
    [(0.5, 0.5), (0.5, 0.4)],
)
def test_atomic_prism_rejects_non_positive_z_span(
    z_start: float,
    z_end: float,
) -> None:
    """Atomic prisms require a positive Z span."""

    with pytest.raises(ValueError, match="positive Z span"):
        _build_atomic_prism_mesh(
            box(0.0, 0.0, 1.0, 1.0),
            z_start=z_start,
            z_end=z_end,
            scale_factor=1.0,
        )


def test_atomic_prism_rejects_mesh_without_bottom_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An extrusion without faces at z_start cannot form an atomic prism."""

    candidate = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    candidate.apply_translation((0.5, 0.5, 2.5))
    monkeypatch.setattr(
        VectorProcessor,
        "_extrude_geometry",
        staticmethod(lambda *_args, **_kwargs: [candidate]),
    )

    with pytest.raises(ValueError, match="bottom cap"):
        _build_atomic_prism_mesh(
            box(0.0, 0.0, 1.0, 1.0),
            z_start=0.0,
            z_end=1.0,
            scale_factor=1.0,
        )


def test_atomic_prism_rejects_bottom_cap_without_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A closed bottom-face set has no boundary from which to build walls."""

    candidate = trimesh.Trimesh(
        vertices=np.asarray(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            dtype=np.float64,
        ),
        faces=np.asarray([(0, 1, 2), (2, 1, 0)], dtype=np.int64),
        process=False,
    )
    monkeypatch.setattr(
        VectorProcessor,
        "_extrude_geometry",
        staticmethod(lambda *_args, **_kwargs: [candidate]),
    )

    with pytest.raises(ValueError, match="boundary edges"):
        _build_atomic_prism_mesh(
            box(0.0, 0.0, 1.0, 1.0),
            z_start=0.0,
            z_end=1.0,
            scale_factor=1.0,
        )


def test_zero_area_polygon_is_not_exported() -> None:
    """A true zero-area GEOS remnant has no printable cross-section."""

    geometry = Polygon(
        [
            (0.0, 0.0),
            (1.0, 1.0),
            (2.0, 2.0),
        ]
    )

    meshes = VectorProcessor._extrude_geometry(
        geometry,
        height=0.08,
        z_offset=0.0,
        scale=1.0,
    )

    assert meshes == []


def test_non_polygon_geometry_is_repaired_before_zero_area_filter() -> None:
    """The topology guard must preserve the existing LineString repair path."""

    meshes = VectorProcessor._extrude_geometry(
        LineString([(0.0, 0.0), (1.0, 0.0)]),
        height=0.08,
        z_offset=0.0,
        scale=1.0,
    )

    assert len(meshes) == 1
    assert meshes[0].is_watertight
    assert np.all(_edge_incidence_counts(meshes[0]) == 2)


def test_indexed_extrusion_preserves_sub_nozzle_speck_topology() -> None:
    """Tiny valid contours stay exact when their ring revisits one XY point."""

    geometry = wkt.loads(
        "POLYGON ((0 0, 0.008 0, 0.01 0.002, 0.008 0.004, "
        "0.004 0.002, 0.008000000000001 0.000000000000001, 0 0))"
    )

    meshes = VectorProcessor._extrude_geometry(
        geometry,
        height=0.08,
        z_offset=0.0,
        scale=1.0,
    )

    assert len(meshes) == 1
    mesh = meshes[0]
    assert mesh.is_watertight
    assert np.all(_edge_incidence_counts(mesh) == 2)
    assert abs(float(mesh.volume)) == pytest.approx(float(geometry.area) * 0.08)


def test_polygon_extrusion_failure_does_not_return_partial_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrepairable polygon must stop export instead of disappearing."""

    geometry = Polygon(
        [(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 3.0)],
        [[(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)]],
    )

    def fail_extrusion(*_args, **_kwargs):
        raise ValueError("synthetic topology failure")

    monkeypatch.setattr(
        vector_engine,
        "extrude_polygon_for_export",
        fail_extrusion,
    )

    with pytest.raises(ValueError, match="refusing partial model export"):
        VectorProcessor._extrude_geometry(
            geometry,
            height=0.08,
            z_offset=0.0,
            scale=1.0,
        )


def test_polygon_topology_failure_preserves_structured_attempt_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Topology diagnostics survive the engine boundary without coordinates."""

    geometry = Polygon(
        [(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 3.0)],
        [[(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)]],
    )
    attempt = {
        "attempt": "repair_0.001_mm",
        "geometry_type": "Polygon",
        "vertex_count": 8,
        "rejected_reason": "float32_duplicate_vertex",
    }
    topology_error = VectorTopologyError(
        "Vector polygon topology could not be repaired for export",
        (attempt,),
    )
    records: list[dict[str, object]] = []

    def fail_extrusion(*_args, **_kwargs):
        raise topology_error

    def capture_warning(_message: str, *, extra: dict[str, object]) -> None:
        records.append(extra)

    monkeypatch.setattr(
        vector_engine,
        "extrude_polygon_for_export",
        fail_extrusion,
    )
    monkeypatch.setattr(vector_engine._log, "warning", capture_warning)

    with pytest.raises(VectorTopologyError) as exc:
        VectorProcessor._extrude_geometry(
            geometry,
            height=0.08,
            z_offset=0.0,
            scale=1.0,
        )

    assert exc.value is topology_error
    record = records[0]
    assert record["event"] == "vector_polygon_extrude_failed"
    assert record["topology_attempts"] == [attempt]
    assert record["topology_rejected_reason"] == "float32_duplicate_vertex"
    assert "coordinates" not in str(record["topology_attempts"]).lower()


def test_polygon_extrusion_rejects_incomplete_closed_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A watertight but undersized triangulation must not self-certify."""

    geometry = Polygon(
        [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    ).buffer(0.1, resolution=3)
    incomplete = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    incomplete.apply_translation((0.5, 0.5, 0.5))
    monkeypatch.setattr(
        vector_engine,
        "extrude_polygon_for_export",
        lambda *_args, **_kwargs: [incomplete],
    )
    monkeypatch.setattr(
        vector_engine,
        "_direct_convex_extrusion_base",
        lambda _geometry, _scale: None,
    )

    with pytest.raises(ValueError, match="refusing partial model export"):
        VectorProcessor._extrude_geometry(
            geometry,
            height=0.08,
            z_offset=0.0,
            scale=1.0,
        )


@pytest.mark.parametrize("touch_offset", [0.0, 1e-13])
def test_extrude_geometry_separates_exterior_from_touching_hole_ring(
    touch_offset: float,
) -> None:
    """Outer/hole point contacts must extrude as a closed shell."""

    geometry = Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        [[(touch_offset, 5.0), (2.0, 4.0), (2.0, 6.0), (touch_offset, 5.0)]],
    )
    meshes = VectorProcessor._extrude_geometry(
        geometry,
        height=1.0,
        z_offset=0.0,
        scale=1.0,
        extrude_cache={},
    )

    assert len(meshes) == 1
    mesh = meshes[0]
    assert mesh.is_watertight
    assert np.all(_edge_incidence_counts(mesh) == 2)
    assert abs(float(mesh.volume)) == pytest.approx(float(geometry.area), abs=0.01)


def test_topology_service_failure_refuses_unsafe_touching_ring_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A topology-service dependency failure must reject the complete shell."""

    geometry = Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        [[(0.0, 5.0), (2.0, 4.0), (2.0, 6.0), (0.0, 5.0)]],
    )
    monkeypatch.setattr(
        vector_engine,
        "extrude_polygon_for_export",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("synthetic missing polygon triangulators")
        ),
    )

    with pytest.raises(ValueError, match="refusing partial model export"):
        VectorProcessor._extrude_geometry(
            geometry,
            height=1.0,
            z_offset=0.0,
            scale=1.0,
            extrude_cache={},
        )


def test_extrude_geometry_preserves_thin_bridge_without_coordinate_repair() -> None:
    """Indexed extrusion retains a positive-area bridge exactly."""

    geometry = unary_union(
        [
            box(0.0, 0.0, 1.0, 1.0),
            box(1.0, 0.5, 2.0, 0.5 + 1e-13),
            box(2.0, 0.0, 3.0, 1.0),
        ]
    )
    meshes = VectorProcessor._extrude_geometry(
        geometry,
        height=1.0,
        z_offset=0.0,
        scale=1.0,
        extrude_cache={},
    )

    assert len(meshes) == 1
    mesh = meshes[0]
    assert mesh.is_watertight
    assert np.all(_edge_incidence_counts(mesh) == 2)
    np.testing.assert_allclose(mesh.bounds, [[0.0, 0.0, 0.0], [3.0, 1.0, 1.0]])
    assert abs(float(mesh.volume)) == pytest.approx(float(geometry.area), abs=0.01)


def test_extrude_geometry_handles_duplicate_vertex_and_thin_bridge() -> None:
    """Writer-safe extrusion preserves area after an unrepresentable bridge."""

    geometry = unary_union(
        [
            box(0.0, 0.0, 1.0, 1.0),
            box(1.0, 0.5, 2.0, 0.5 + 1e-13),
            box(2.0, 0.0, 3.0, 1.0),
        ]
    )
    coordinates = list(geometry.exterior.coords)
    coordinates.insert(2, coordinates[2])
    geometry_with_duplicate = Polygon(coordinates)

    meshes = VectorProcessor._extrude_geometry(
        geometry_with_duplicate,
        height=1.0,
        z_offset=0.0,
        scale=1.0,
        extrude_cache={},
    )

    assert len(meshes) == 1
    mesh = meshes[0]
    assert mesh.is_watertight
    components = mesh.split(only_watertight=False)
    assert len(components) == 2
    assert all(component.is_watertight for component in components)
    assert np.all(_edge_incidence_counts(mesh) == 2)
    assert mesh_is_float32_safe(mesh, xy_scale=1.0)
    assert abs(float(mesh.volume)) == pytest.approx(
        float(geometry_with_duplicate.area),
        abs=0.01,
    )


def test_extrude_geometry_separates_repaired_diagonal_components() -> None:
    """A vanished positive bridge must not reconnect shells in writer space."""

    geometry = unary_union(
        [
            box(0.0, 0.0, 1.0, 1.0),
            box(1.0, 1.0, 2.0, 2.0),
            box(1.0 - 1e-13, 1.0 - 1e-13, 1.0 + 1e-13, 1.0 + 1e-13),
        ]
    )
    assert isinstance(geometry, Polygon)
    assert geometry.is_valid

    meshes = VectorProcessor._extrude_geometry(
        geometry,
        height=1.0,
        z_offset=0.0,
        scale=1.0,
        extrude_cache={},
    )

    assert len(meshes) == 1
    mesh = meshes[0]
    assert mesh_is_float32_safe(mesh, xy_scale=1.0)
    components = mesh.split(only_watertight=False)
    assert len(components) == 2
    assert all(component.is_watertight for component in components)
    assert np.all(_edge_incidence_counts(mesh) == 2)
    assert abs(float(mesh.volume)) == pytest.approx(float(geometry.area), abs=0.01)

    finalized = vector_engine._finalize_prism_meshes(meshes)
    assert finalized is not None
    assert finalized.is_watertight
    assert finalized.is_winding_consistent
    assert mesh_is_float32_safe(finalized, xy_scale=1.0)
    assert np.all(_edge_incidence_counts(finalized) == 2)


def test_extrude_geometry_does_not_revalidate_proven_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Global separation must not rescan every already-certified shell."""

    geometry = MultiPolygon(
        [
            box(0.0, 0.0, 1.0, 1.0),
            box(1.0, 1.0, 2.0, 2.0),
        ]
    )
    original_validator = vector_engine.mesh_is_float32_safe
    validator_calls = 0

    def count_validator_calls(*args, **kwargs):
        nonlocal validator_calls
        validator_calls += 1
        return original_validator(*args, **kwargs)

    monkeypatch.setattr(
        vector_engine,
        "mesh_is_float32_safe",
        count_validator_calls,
    )

    meshes = VectorProcessor._extrude_geometry(
        geometry,
        height=0.2,
        z_offset=0.0,
        scale=1.0,
        extrude_cache={},
    )

    assert validator_calls == 0
    assert original_validator(
        _concatenate_meshes_fast(meshes),
        xy_scale=1.0,
    )


def test_extrude_geometry_separates_point_touching_hole_rings() -> None:
    """Two holes sharing one point must not create a four-face edge."""

    geometry = Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        [
            [(2.0, 4.0), (5.0, 5.0), (2.0, 6.0), (2.0, 4.0)],
            [(8.0, 4.0), (8.0, 6.0), (5.0, 5.0), (8.0, 4.0)],
        ],
    )
    meshes = VectorProcessor._extrude_geometry(
        geometry,
        height=1.0,
        z_offset=0.0,
        scale=1.0,
        extrude_cache={},
    )

    assert len(meshes) == 1
    mesh = meshes[0]
    assert mesh.is_watertight
    assert np.all(_edge_incidence_counts(mesh) == 2)
    assert abs(float(mesh.volume)) == pytest.approx(float(geometry.area), abs=0.01)


def test_extrude_geometry_repairs_complex_point_touching_holes() -> None:
    """A detailed hole and a small hole sharing one point stay slicer-safe."""

    angles = np.linspace(0.0, 2.0 * np.pi, 20, endpoint=False)
    large_hole = [
        (10.0 + 8.0 * np.cos(theta), 10.0 + 8.0 * np.sin(theta))
        for theta in angles
    ]
    contact = large_hole[0]
    small_hole = [contact, (25.0, 8.0), (25.0, 12.0), contact]
    geometry = Polygon(
        [(0.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0)],
        [large_hole, small_hole],
    )

    meshes = VectorProcessor._extrude_geometry(
        geometry,
        height=1.0,
        z_offset=0.0,
        scale=1.0,
        extrude_cache={},
    )

    assert len(meshes) == 1
    mesh = meshes[0]
    assert mesh.is_watertight
    assert np.all(_edge_incidence_counts(mesh) == 2)
    assert abs(float(mesh.volume)) == pytest.approx(float(geometry.area), abs=0.01)


def _build_two_height_relief_board() -> trimesh.Trimesh:
    """Build the minimal adjacent-height board that reproduced broken faces."""

    matched_shapes = [
        {
            "geometry": box(0.0, 0.0, 5.0, 5.0),
            "recipe": [0],
            "matched_rgb": (255, 0, 0),
        },
        {
            "geometry": box(5.0, 0.0, 10.0, 5.0),
            "recipe": [0],
            "matched_rgb": (0, 255, 0),
        },
    ]
    meshes_by_slot = VectorProcessor._build_relief_meshes(
        matched_shapes=matched_shapes,
        num_layers=1,
        layer_h=0.2,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        backing_color_id=0,
        default_height_mm=1.0,
        height_mode="color",
        color_height_map={"#ff0000": 1.0, "#00ff00": 2.0},
        heightmap_path=None,
        heightmap_max_height=None,
        bbox=(0.0, 0.0, 10.0, 5.0),
        extrude_cache={},
    )
    board = _concatenate_meshes_fast(meshes_by_slot["Board"]["meshes"])
    board.merge_vertices()
    return board


def test_relief_backing_welds_adjacent_height_steps() -> None:
    """Different backing heights must form one closed stepped solid."""

    board = _build_two_height_relief_board()

    assert board.is_watertight
    np.testing.assert_allclose(board.bounds, [[0.0, 0.0, 0.0], [10.0, 5.0, 1.8]])
    assert float(board.volume) == pytest.approx(65.0)


def test_relief_backing_volume_preserves_internal_cavity_profile() -> None:
    """A cavity that closes above its opening must remain a closed volume."""

    outer = box(0.0, 0.0, 10.0, 10.0)
    cavity = box(4.0, 4.0, 6.0, 6.0)
    board = _build_stepped_volume_mesh(
        [
            {"geometry": outer, "z_offset": 0.0, "height": 0.4},
            {
                "geometry": outer.difference(cavity),
                "z_offset": 0.4,
                "height": 0.6,
            },
            {"geometry": outer, "z_offset": 1.0, "height": 0.4},
        ],
        scale_factor=1.0,
    )

    assert board is not None
    assert board.is_watertight
    assert float(board.volume) == pytest.approx(137.6)


def test_relief_backing_splits_t_junctions_on_shared_curves() -> None:
    """A tall region edge must align with multiple shorter neighbours."""

    left = Polygon([(0.0, 0.0), (5.0, 0.0), (6.0, 10.0), (0.0, 10.0)])
    shared_midpoint = (5.5 + 1e-12, 5.0)
    right_lower = Polygon([(5.0, 0.0), (10.0, 0.0), (10.0, 5.0), shared_midpoint])
    right_upper = Polygon([shared_midpoint, (10.0, 5.0), (10.0, 10.0), (6.0, 10.0)])
    board = _build_stepped_volume_mesh(
        [
            {"geometry": left, "z_offset": 0.0, "height": 1.8},
            {"geometry": right_lower, "z_offset": 0.0, "height": 0.8},
            {"geometry": right_upper, "z_offset": 0.0, "height": 1.4},
        ],
        scale_factor=1.0,
    )

    assert board is not None
    assert board.is_watertight
    expected_volume = left.area * 1.8 + right_lower.area * 0.8 + right_upper.area * 1.4
    assert float(board.volume) == pytest.approx(expected_volume)


@pytest.mark.parametrize("right_height", [1.0, 1.8])
def test_relief_backing_keeps_corner_touching_shells_separate(
    right_height: float,
) -> None:
    """Point-touching regions must remain independent manifold shells."""

    lower_left = box(0.0, 0.0, 1.0, 1.0)
    upper_right = box(1.0, 1.0, 2.0, 2.0)
    board = _build_stepped_volume_mesh(
        [
            {"geometry": lower_left, "z_offset": 0.0, "height": 1.0},
            {
                "geometry": upper_right,
                "z_offset": 0.0,
                "height": right_height,
            },
        ],
        scale_factor=1.0,
    )

    assert board is not None
    assert board.is_watertight
    assert len(board.split(only_watertight=False)) == 2
    assert float(board.volume) == pytest.approx(1.0 + right_height)


def test_relief_backing_scales_by_connected_component() -> None:
    """Unrelated height levels must not subdivide disconnected regions."""

    region_count = 40
    board = _build_stepped_volume_mesh(
        [
            {
                "geometry": box(index * 2.0, 0.0, index * 2.0 + 1.0, 1.0),
                "z_offset": 0.0,
                "height": 1.0 + index * 0.01,
            }
            for index in range(region_count)
        ],
        scale_factor=1.0,
    )

    assert board is not None
    assert board.is_watertight
    assert len(board.split(only_watertight=False)) == region_count
    assert len(board.faces) <= region_count * 20


def _native_kernel_contract_slabs() -> list[dict]:
    """Return a stepped solid that exercises holes, offsets, and XY scaling."""

    outer = box(-2.0, 3.0, 8.0, 13.0)
    cavity = box(1.0, 6.0, 3.0, 8.0)
    return [
        {"geometry": outer, "z_offset": 0.35, "height": 0.4},
        {
            "geometry": outer.difference(cavity),
            "z_offset": 0.75,
            "height": 0.6,
        },
        {"geometry": outer, "z_offset": 1.35, "height": 0.25},
    ]


@pytest.mark.skipif(
    vector_engine._load_relief_manifold3d() is None,
    reason="optional manifold3d fast kernel is not installed",
)
def test_relief_backing_uses_native_kernel_without_python_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Installed manifold3d must bypass the expensive atomic-prism fallback."""

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Python atomic-prism fallback was unexpectedly used")

    monkeypatch.setattr(
        vector_engine,
        "_build_stepped_volume_mesh_python_prepared",
        fail_if_called,
    )
    board = _build_stepped_volume_mesh(
        _native_kernel_contract_slabs(),
        scale_factor=1.7,
    )

    assert board is not None
    assert board.is_watertight
    np.testing.assert_allclose(
        board.bounds,
        [[-3.4, 5.1, 0.35], [13.6, 22.1, 1.6]],
    )
    assert float(board.volume) == pytest.approx(
        (100.0 * 0.4 + 96.0 * 0.6 + 100.0 * 0.25) * 1.7**2,
        rel=1e-6,
    )


def test_relief_backing_missing_native_dependency_uses_exact_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Base installs and unsupported wheels must retain watertight correctness."""

    fallback_calls = 0
    real_fallback = vector_engine._build_stepped_volume_mesh_python_prepared

    def counted_fallback(*args, **kwargs):
        nonlocal fallback_calls
        fallback_calls += 1
        return real_fallback(*args, **kwargs)

    monkeypatch.setattr(vector_engine, "_load_relief_manifold3d", lambda: None)
    monkeypatch.setattr(
        vector_engine,
        "_build_stepped_volume_mesh_python_prepared",
        counted_fallback,
    )
    board = _build_stepped_volume_mesh(
        _native_kernel_contract_slabs(),
        scale_factor=1.7,
    )

    assert fallback_calls == 1
    assert board is not None
    assert board.is_watertight
    assert float(board.volume) == pytest.approx(
        (100.0 * 0.4 + 96.0 * 0.6 + 100.0 * 0.25) * 1.7**2,
    )


@pytest.mark.skipif(
    vector_engine._load_relief_manifold3d() is None,
    reason="optional manifold3d fast kernel is not installed",
)
def test_relief_backing_native_and_python_kernels_preserve_topology() -> None:
    """Fast and fallback kernels must agree on cavities and point contacts."""

    slabs = _native_kernel_contract_slabs()
    native = vector_engine._build_stepped_volume_mesh_manifold(
        slabs,
        scale_factor=1.7,
    )
    fallback = vector_engine._build_stepped_volume_mesh_python(
        slabs,
        scale_factor=1.7,
    )

    assert native is not None
    assert fallback is not None
    assert native.is_watertight
    assert fallback.is_watertight
    np.testing.assert_allclose(native.bounds, fallback.bounds, atol=1e-8)
    assert float(native.volume) == pytest.approx(
        float(fallback.volume),
        rel=1e-6,
        abs=1e-6,
    )

    point_touching = [
        {"geometry": box(0.0, 0.0, 1.0, 1.0), "z_offset": 0.2, "height": 1.0},
        {"geometry": box(1.0, 1.0, 2.0, 2.0), "z_offset": 0.2, "height": 1.8},
    ]
    native_point_touch = vector_engine._build_stepped_volume_mesh_manifold(
        point_touching,
        scale_factor=1.0,
    )
    fallback_point_touch = vector_engine._build_stepped_volume_mesh_python(
        point_touching,
        scale_factor=1.0,
    )
    assert native_point_touch is not None
    assert fallback_point_touch is not None
    assert len(native_point_touch.split(only_watertight=False)) == 2
    assert len(fallback_point_touch.split(only_watertight=False)) == 2


@pytest.mark.skipif(
    vector_engine._load_relief_manifold3d() is None,
    reason="optional manifold3d fast kernel is not installed",
)
def test_relief_backing_native_groups_same_z_fragments_before_union() -> None:
    """One height slab must not become many independently triangulated solids."""

    base = box(0.0, 0.0, 12.0, 4.0)
    raised_fragments = [
        box(index * 2.0, 0.0, index * 2.0 + 1.0, 4.0)
        for index in range(6)
    ]
    slabs = [
        {"geometry": base, "z_offset": 0.0, "height": 0.5},
        *[
            {"geometry": fragment, "z_offset": 0.5, "height": 0.7}
            for fragment in raised_fragments
        ],
    ]
    native = vector_engine._build_stepped_volume_mesh_manifold(
        slabs,
        scale_factor=1.0,
    )
    fallback = vector_engine._build_stepped_volume_mesh_python(
        slabs,
        scale_factor=1.0,
    )

    assert native is not None
    assert fallback is not None
    assert native.is_watertight
    assert float(native.volume) == pytest.approx(float(fallback.volume))
    assert len(native.faces) < len(fallback.faces)


@pytest.mark.parametrize("native_failure", ["exception", "invalid_mesh"])
def test_relief_backing_native_failure_rebuilds_whole_board_with_fallback(
    monkeypatch: pytest.MonkeyPatch,
    native_failure: str,
) -> None:
    """A failed or invalid native result must never leak a partial Board."""

    fallback_calls = 0
    real_fallback = vector_engine._build_stepped_volume_mesh_python_prepared

    def counted_fallback(*args, **kwargs):
        nonlocal fallback_calls
        fallback_calls += 1
        return real_fallback(*args, **kwargs)

    if native_failure == "exception":
        def broken_native(*_args, **_kwargs):
            raise RuntimeError("simulated manifold3d runtime failure")
    else:
        def broken_native(*_args, **_kwargs):
            return trimesh.creation.box(extents=(1.0, 1.0, 1.0))

    monkeypatch.setattr(
        vector_engine,
        "_build_stepped_volume_mesh_manifold_prepared",
        broken_native,
    )
    monkeypatch.setattr(
        vector_engine,
        "_build_stepped_volume_mesh_python_prepared",
        counted_fallback,
    )
    board = _build_stepped_volume_mesh(
        _native_kernel_contract_slabs(),
        scale_factor=1.7,
    )

    assert fallback_calls == 1
    assert board is not None
    assert board.is_watertight
    np.testing.assert_allclose(
        board.bounds,
        [[-3.4, 5.1, 0.35], [13.6, 22.1, 1.6]],
    )


def test_corner_touching_relief_stays_watertight_through_build_and_glb(
    tmp_path,
) -> None:
    """Scene assembly and preview export must preserve independent shells."""

    from core.pipeline.vector_glb_preview import export_vector_glb_preview

    svg_path = tmp_path / "corner-touch.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" '
        'viewBox="0 0 20 20">'
        '<rect x="0" y="0" width="10" height="10" fill="#ff0000"/>'
        '<rect x="10" y="10" width="10" height="10" fill="#00ff00"/>'
        "</svg>",
        encoding="utf-8",
    )
    repository_root = Path(__file__).resolve().parents[1]
    processor = VectorProcessor(
        str(
            repository_root
            / "lut-preset"
            / "Custom"
            / "Bambulab&PLA&RYBW&红-黄-蓝-白.npy"
        ),
        "4-Color (RYBW)",
    )
    analysis = processor.analyze_svg(str(svg_path), target_width_mm=20.0)
    height_map = {
        f"#{red:02x}{green:02x}{blue:02x}": 1.0 + index * 0.8
        for index, (red, green, blue) in enumerate(
            sorted(
                {
                    tuple(int(value) for value in shape["matched_rgb"][:3])
                    for shape in analysis.matched_shapes
                }
            )
        )
    }
    scene = processor.build_mesh(
        analysis=analysis,
        thickness_mm=1.0,
        structure_mode="Single-sided",
        enable_relief=True,
        height_mode="color",
        color_height_map=height_map,
    )

    assert scene.geometry["Board"].is_watertight
    assert len(scene.geometry["Board"].split(only_watertight=False)) == 2
    glb_path = tmp_path / "corner-touch-preview.glb"
    export_vector_glb_preview(
        scene=scene,
        output_path=str(glb_path),
        structure_mode="Single-sided",
        color_mode="4-Color (RYBW)",
        preview_colors=analysis.preview_colors,
        slot_list=list(analysis.slot_names),
        analysis=analysis,
        ctx={"enable_relief": True},
    )
    loaded = trimesh.load(glb_path, force="scene", process=False)
    assert loaded.geometry["backing_plate"].is_watertight
    assert len(loaded.geometry["backing_plate"].split(only_watertight=False)) == 2


def test_relief_backing_glb_round_trip_stays_watertight(tmp_path) -> None:
    """The indexed topology must survive the actual preview file format."""

    board = _build_two_height_relief_board()
    scene = trimesh.Scene()
    scene.add_geometry(board, geom_name="Board", node_name="Board")
    glb_path = tmp_path / "two-height-relief.glb"
    glb_path.write_bytes(scene.export(file_type="glb"))

    loaded = trimesh.load(glb_path, force="scene", process=False)
    loaded_board = next(iter(loaded.geometry.values()))
    assert loaded_board.is_watertight
    assert float(loaded_board.volume) == pytest.approx(65.0)


def test_real_svg_relief_preview_glb_is_watertight(tmp_path) -> None:
    """The reported illustrated SVG must export without broken mesh faces."""

    from core.pipeline.vector_glb_preview import export_vector_glb_preview

    repository_root = Path(__file__).resolve().parents[1]
    processor = VectorProcessor(
        str(
            repository_root
            / "lut-preset"
            / "Custom"
            / "Bambulab&PLA&RYBW&红-黄-蓝-白.npy"
        ),
        "4-Color (RYBW)",
    )
    analysis = processor.analyze_svg(
        str(repository_root / "test_images" / "1.svg"),
        target_width_mm=100.0,
    )
    matched_colors = sorted(
        {
            tuple(int(value) for value in shape["matched_rgb"][:3])
            for shape in analysis.matched_shapes
        }
    )
    height_map = {
        f"#{red:02x}{green:02x}{blue:02x}": 1.0 + (index % 3) * 0.8
        for index, (red, green, blue) in enumerate(matched_colors)
    }
    scene = processor.build_mesh(
        analysis=analysis,
        thickness_mm=1.0,
        structure_mode="Single-sided",
        enable_relief=True,
        height_mode="color",
        color_height_map=height_map,
    )

    assert scene.geometry["Board"].is_watertight
    glb_path = tmp_path / "illustrated-relief-preview.glb"
    export_vector_glb_preview(
        scene=scene,
        output_path=str(glb_path),
        structure_mode="Single-sided",
        color_mode="4-Color (RYBW)",
        preview_colors=analysis.preview_colors,
        slot_list=list(analysis.slot_names),
        analysis=analysis,
        ctx={"enable_relief": True},
    )
    loaded = trimesh.load(glb_path, force="scene", process=False)
    assert "backing_plate" in loaded.geometry
    assert loaded.geometry["backing_plate"].is_watertight


class TestBuildMeshShellTopology:
    """Validate the slicer topology contract at ``build_mesh`` assembly."""

    @staticmethod
    def _two_adjacent_extrusions() -> tuple[trimesh.Trimesh, trimesh.Trimesh]:
        """Build two boxes that share the edge x=5 (so six vertex pairs coincide
        along the border after extrusion)."""
        left = box(0.0, 0.0, 5.0, 5.0)
        right = box(5.0, 0.0, 10.0, 5.0)
        extrude = VectorProcessor._extrude_geometry
        left_meshes = extrude(left, height=1.0, z_offset=0.0, scale=1.0)
        right_meshes = extrude(right, height=1.0, z_offset=0.0, scale=1.0)
        assert left_meshes and right_meshes, "extrude_polygon returned empty mesh list"
        return left_meshes[0], right_meshes[0]

    def test_adjacent_shapes_produce_coincident_vertices(self):
        """Precondition: two adjacent extruded boxes share coincident border
        vertices that ``trimesh.util.concatenate`` does NOT weld."""
        left_mesh, right_mesh = self._two_adjacent_extrusions()
        combined = trimesh.util.concatenate([left_mesh, right_mesh])
        coincident = _coincident_pair_count(combined, tol=1e-9)
        assert coincident >= 4, (
            "Adjacent shapes should leave at least one coincident vertex pair "
            "per shared border corner; concatenate() must not weld them "
            "implicitly (if this fails, trimesh API semantics changed)."
        )

    def test_merge_vertices_turns_shared_border_non_manifold(self):
        """Blind welding reproduces the slicer's multi-face-edge defect."""
        left_mesh, right_mesh = self._two_adjacent_extrusions()
        combined = trimesh.util.concatenate([left_mesh, right_mesh])
        assert np.all(_edge_incidence_counts(combined) == 2)

        combined.merge_vertices()
        assert np.any(_edge_incidence_counts(combined) > 2)

    def test_build_mesh_call_site_does_not_weld_independent_shells(self):
        """Governance: normal slot assembly must not weld closed prisms."""
        import inspect

        source = inspect.getsource(VectorProcessor.build_mesh)
        concat_idx = source.find("_concatenate_meshes_fast")
        assert concat_idx >= 0, "build_mesh must use the vector fast concat helper"
        merge_idx = source.find("merge_vertices", concat_idx)
        assert merge_idx < 0, (
            "build_mesh must retain independently indexed closed shells; "
            "blind merge_vertices() creates multi-face shared edges"
        )

    def test_build_mesh_fast_concat_does_not_depend_on_trimesh_generic_concatenate(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.delenv("LUMINA_VECTOR_NATIVE_MESH", raising=False)
        left_mesh, right_mesh = self._two_adjacent_extrusions()
        processor = VectorProcessor.__new__(VectorProcessor)

        def fake_run_length_extrude(*_args, **_kwargs):
            return {
                "White": {
                    "meshes": [left_mesh, right_mesh],
                    "mat_id": 0,
                }
            }

        def fail_generic_concatenate(*_args, **_kwargs):
            raise AssertionError("build_mesh should use the vector fast concat helper")

        monkeypatch.setattr(
            VectorProcessor,
            "_run_length_extrude",
            staticmethod(fake_run_length_extrude),
        )
        monkeypatch.setattr(trimesh.util, "concatenate", fail_generic_concatenate)
        processor.color_mode = "4-Color (RYBW)"
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[],
            matched_shapes=[],
            silhouette=None,
            scale_factor=1.0,
            bbox=(0.0, 0.0, 10.0, 5.0),
            color_conf={},
            slot_names=["White"],
            num_channels=1,
            num_layers=1,
            preview_colors={0: [255, 255, 255, 255], "White": [255, 255, 255, 255]},
        )

        scene = processor.build_mesh(
            analysis=analysis,
            thickness_mm=0.0,
            structure_mode="Single-sided",
        )

        combined = scene.geometry["White"]
        assert float(combined.volume) == pytest.approx(
            float(left_mesh.volume + right_mesh.volume),
            rel=1e-6,
            abs=1e-6,
        )
        assert _coincident_pair_count(combined, tol=1e-9) >= 4
        assert np.all(_edge_incidence_counts(combined) == 2)

    def test_build_mesh_fast_concat_accepts_single_array_chunk(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.delenv("LUMINA_VECTOR_NATIVE_MESH", raising=False)
        source_mesh = VectorProcessor._extrude_geometry(
            box(0.0, 0.0, 2.0, 2.0),
            height=1.0,
            z_offset=0.0,
            scale=1.0,
        )[0]
        chunk = (source_mesh.vertices.copy(), source_mesh.faces.copy())
        processor = VectorProcessor.__new__(VectorProcessor)
        processor.color_mode = "4-Color (RYBW)"

        def fake_run_length_extrude(*_args, **_kwargs):
            return {
                "White": {
                    "meshes": [chunk],
                    "mat_id": 0,
                }
            }

        monkeypatch.setattr(
            VectorProcessor,
            "_run_length_extrude",
            staticmethod(fake_run_length_extrude),
        )
        analysis = VectorAnalysis(
            shape_data=[],
            clipped_shapes=[],
            matched_shapes=[],
            silhouette=None,
            scale_factor=1.0,
            bbox=(0.0, 0.0, 2.0, 2.0),
            color_conf={},
            slot_names=["White"],
            num_channels=1,
            num_layers=1,
            preview_colors={0: [255, 255, 255, 255], "White": [255, 255, 255, 255]},
        )

        scene = processor.build_mesh(
            analysis=analysis,
            thickness_mm=0.0,
            structure_mode="Single-sided",
        )

        assert sorted(scene.geometry) == ["White"]
        assert int(len(scene.geometry["White"].faces)) == int(len(source_mesh.faces))


def test_run_length_extrude_preserves_source_area_when_optimized_union_is_lossy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lossy run union must fall back instead of exporting a partial layer."""

    source_geometries = [
        box(0.0, 0.0, 1.0, 1.0),
        box(2.0, 0.0, 3.0, 1.0),
    ]

    def drop_second_geometry(geometries):
        return tuple(geometries)[0]

    monkeypatch.setattr(
        vector_engine,
        "_union_run_group_geometries",
        drop_second_geometry,
    )

    meshes_by_slot = VectorProcessor._run_length_extrude(
        matched_shapes=[
            {"geometry": geometry, "recipe": [0]}
            for geometry in source_geometries
        ],
        num_layers=1,
        layer_h=0.2,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        extrude_cache={},
    )

    meshes = meshes_by_slot["White"]["meshes"]
    actual_volume = sum(abs(float(mesh.volume)) for mesh in meshes)
    expected_volume = sum(float(geometry.area) for geometry in source_geometries) * 0.2
    assert actual_volume == pytest.approx(expected_volume, rel=1e-6, abs=1e-6)


def test_run_length_extrude_rebuilds_lost_5mm_island_beside_200mm_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Coverage tolerance must not hide a complete printable island loss."""

    main_body = box(0.0, 0.0, 200.0, 200.0)
    small_island = box(210.0, 0.0, 215.0, 5.0)
    source_geometries = [main_body, small_island]

    monkeypatch.setattr(
        vector_engine,
        "_union_run_group_geometries",
        lambda geometries: tuple(geometries)[0],
    )

    meshes_by_slot = VectorProcessor._run_length_extrude(
        matched_shapes=[
            {"geometry": geometry, "recipe": [0]}
            for geometry in source_geometries
        ],
        num_layers=1,
        layer_h=0.2,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        extrude_cache={},
    )

    meshes = meshes_by_slot["White"]["meshes"]
    actual_volume = sum(abs(float(mesh.volume)) for mesh in meshes)
    expected_volume = (40000.0 + 25.0) * 0.2
    assert actual_volume == pytest.approx(expected_volume, rel=1e-9, abs=1e-6)


def test_run_length_extrude_separates_point_touching_multipolygon_shells() -> None:
    """Valid MultiPolygon parts stay independent after slot assembly."""

    geometry = MultiPolygon(
        [
            box(0.0, 0.0, 1.0, 1.0),
            box(1.0, 1.0, 2.0, 2.0),
        ]
    )
    assert geometry.is_valid

    meshes_by_slot = VectorProcessor._run_length_extrude(
        matched_shapes=[{"geometry": geometry, "recipe": [0]}],
        num_layers=1,
        layer_h=0.2,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        extrude_cache={},
    )

    meshes = meshes_by_slot["White"]["meshes"]
    combined = _concatenate_meshes_fast(meshes)
    assert mesh_is_float32_safe(combined, xy_scale=1.0)
    components = combined.split(only_watertight=False)
    assert len(components) == 2
    assert all(component.is_watertight for component in components)
    assert np.all(_edge_incidence_counts(combined) == 2)
    assert abs(float(combined.volume)) == pytest.approx(0.4, abs=1e-6)


def test_run_length_extrude_rejects_incomplete_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If primary and fallback extrusion lose area, generation must stop."""

    monkeypatch.setattr(
        VectorProcessor,
        "_extrude_geometry",
        staticmethod(lambda *_args, **_kwargs: []),
    )

    with pytest.raises(ValueError, match="coverage"):
        VectorProcessor._run_length_extrude(
            matched_shapes=[
                {"geometry": box(0.0, 0.0, 2.0, 2.0), "recipe": [0]}
            ],
            num_layers=1,
            layer_h=0.2,
            num_channels=1,
            slot_names=["White"],
            scale_factor=1.0,
            extrude_cache={},
        )


def test_merge_vertices_preserves_volume_of_disjoint_parts():
    """Sanity guard: merging vertices must not collapse geometrically
    disjoint parts (boxes more than 1mm apart)."""
    far_left = box(0.0, 0.0, 1.0, 1.0)
    far_right = box(10.0, 0.0, 11.0, 1.0)
    extrude = VectorProcessor._extrude_geometry
    left = extrude(far_left, height=1.0, z_offset=0.0, scale=1.0)[0]
    right = extrude(far_right, height=1.0, z_offset=0.0, scale=1.0)[0]
    combined = trimesh.util.concatenate([left, right])
    vol_before = float(combined.volume)
    combined.merge_vertices()
    vol_after = float(combined.volume)
    assert vol_after == pytest.approx(vol_before, rel=1e-6, abs=1e-6)
