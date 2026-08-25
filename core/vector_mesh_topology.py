"""Bounded topology preparation for vector mesh exports.

为矢量网格导出提供有界的拓扑准备与校验。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import math

import numpy as np
import trimesh
from mapbox_earcut import triangulate_float64 as _triangulate_float64
from shapely import affinity as _affinity
from shapely import box as _vectorized_box
from shapely import covered_by as _covered_by
from shapely import linestrings as _linestrings
from shapely import STRtree as _STRtree
from shapely import set_precision as _set_precision
from shapely.errors import ShapelyError as _ShapelyError
from shapely.geometry import MultiPolygon as _MultiPolygon
from shapely.geometry import Polygon as _Polygon
from shapely.geometry.polygon import LinearRing as _LinearRing
from shapely.ops import unary_union as _unary_union
from shapely.validation import make_valid as _make_valid

from core.errors import VectorTopologyError

VECTOR_COVERAGE_REL_TOL = 1e-6
VECTOR_COVERAGE_ABS_TOL_MM2 = 0.01
VECTOR_RING_SEPARATION_RETRY_MM = (0.0001, 0.001)

__all__ = [
    "VECTOR_COVERAGE_REL_TOL",
    "VECTOR_COVERAGE_ABS_TOL_MM2",
    "VECTOR_RING_SEPARATION_RETRY_MM",
    "mesh_is_float32_safe",
    "prepare_geometry_for_float32",
    "separate_component_coordinates",
    "extrude_polygon_for_export",
]

_FLOAT32_GRID_MM = 0.0001
_FLOAT32_MAX = float(np.finfo(np.float32).max)
_SMALL_MESH_FACE_LIMIT = 64
_CAP_UNION_CHUNK_SIZE = 1024
_WRITER_FACE_CHUNK_SIZE = 65_536
_GENERIC_COMPONENT_FACE_LIMIT = 2048
_GENERIC_COMPONENT_PAIR_LIMIT = 250_000
_COMPONENT_AABB_PAIR_LIMIT = 250_000
_WRITER_VOLUME_REL_TOL = 1e-6
_WRITER_VOLUME_ABS_TOL_MM3 = 1e-9
_COMPONENT_MAX_STEPS = 8
_COMPONENT_DIRECTIONS = (
    (1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0),
    (1.0, 1.0), (-1.0, 1.0), (1.0, -1.0), (-1.0, -1.0),
)
_GEOMETRY_ERRORS = (ValueError, TypeError, _ShapelyError)
_RECOVERABLE_EXPORT_ERRORS = (
    ArithmeticError,
    AttributeError,
    ImportError,
    IndexError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    _ShapelyError,
)
_Polygonal = _Polygon | _MultiPolygon


class _ComponentPairBudgetExceeded(RuntimeError):
    """The bounded component broad phase exhausted its inspection budget."""


@dataclass(frozen=True)
class _WriterBoundaryProfile:
    """Filled writer-domain footprint and its closed Z range."""

    footprint: _Polygonal
    bounds: tuple[float, float, float, float]
    z_min: float
    z_max: float


def _positive_scale(value: float) -> float | None:
    """Return a finite positive scale, or ``None``."""
    try:
        scale = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return scale if math.isfinite(scale) and scale > 0.0 else None


def _mesh_arrays(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray] | None:
    """Return non-empty triangular mesh arrays without copying them."""
    try:
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int64)
    except (AttributeError, TypeError, ValueError):
        return None
    if (
        vertices.ndim != 2 or vertices.shape[1:] != (3,) or len(vertices) == 0
        or faces.ndim != 2 or faces.shape[1:] != (3,) or len(faces) == 0
    ):
        return None
    return vertices, faces


def _writer_vertices_for_offset(
    vertices: np.ndarray,
    scale: float,
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> np.ndarray | None:
    """Quantize one candidate exactly as the 3MF float32 writer will."""

    writer_vertices = np.empty(vertices.shape, dtype=np.float32)
    offset_array = np.asarray(offset, dtype=np.float64)
    with np.errstate(over="ignore", invalid="ignore"):
        writer_vertices[:, :2] = (
            vertices[:, :2] + offset_array[:2]
        ) * scale
        writer_vertices[:, 2] = vertices[:, 2] + offset_array[2]
    if not np.all(np.isfinite(writer_vertices)):
        return None
    return writer_vertices


def _writer_mesh_metrics(
    writer_vertices: np.ndarray,
    faces: np.ndarray,
    *,
    measure_coverage: bool = True,
) -> tuple[bool, float | None]:
    """Validate indexed triangles in chunks and return absolute volume."""

    if (
        faces.ndim != 2
        or faces.shape[1:] != (3,)
        or len(faces) == 0
        or np.any(faces < 0)
        or np.any(faces >= len(writer_vertices))
        or np.any(
            (faces[:, 0] == faces[:, 1])
            | (faces[:, 1] == faces[:, 2])
            | (faces[:, 2] == faces[:, 0])
        )
    ):
        return False, 0.0
    signed_volume_six = 0.0
    for start in range(0, len(faces), _WRITER_FACE_CHUNK_SIZE):
        chunk = faces[start : start + _WRITER_FACE_CHUNK_SIZE]
        triangles = writer_vertices[chunk].astype(np.float64)
        crosses = np.cross(
            triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 0],
        )
        if np.any(np.all(crosses == 0.0, axis=1)):
            return False, 0.0
        if measure_coverage:
            signed_volume_six += float(
                np.einsum("ij,ij->i", triangles[:, 0], crosses).sum(
                    dtype=np.float64
                )
            )
    coverage = abs(signed_volume_six) / 6.0 if measure_coverage else None
    return True, coverage


def _cap_faces_at_z(
    writer_vertices: np.ndarray,
    faces: np.ndarray,
    z_value: np.float32,
) -> np.ndarray | None:
    """Collect cap faces without one unbounded ``vertices[faces]`` gather."""

    chunks: list[np.ndarray] = []
    for start in range(0, len(faces), _WRITER_FACE_CHUNK_SIZE):
        chunk = faces[start : start + _WRITER_FACE_CHUNK_SIZE]
        face_z = writer_vertices[chunk, 2]
        selected = chunk[np.all(face_z == z_value, axis=1)]
        if len(selected):
            chunks.append(selected)
    return np.concatenate(chunks, axis=0) if chunks else None


def _filled_cap_footprint(
    writer_vertices: np.ndarray,
    faces: np.ndarray,
    z_value: np.float32,
) -> _Polygonal | None:
    """Return the actual filled cap after writer-domain quantization."""

    cap_faces = _cap_faces_at_z(writer_vertices, faces, z_value)
    if cap_faces is None:
        return None
    partials: list[_Polygonal] = []
    triangle_area = 0.0
    coordinate_magnitude = 1.0
    for start in range(0, len(cap_faces), _CAP_UNION_CHUNK_SIZE):
        chunk = cap_faces[start : start + _CAP_UNION_CHUNK_SIZE]
        points = writer_vertices[chunk, :2].astype(np.float64)
        coordinate_magnitude = max(
            coordinate_magnitude,
            float(np.max(np.abs(points))),
        )
        first_edges = points[:, 1] - points[:, 0]
        second_edges = points[:, 2] - points[:, 0]
        twice_area = np.abs(
            first_edges[:, 0] * second_edges[:, 1]
            - first_edges[:, 1] * second_edges[:, 0]
        )
        if np.any(twice_area == 0.0):
            return None
        triangle_area += float(twice_area.sum(dtype=np.float64)) * 0.5
        polygons = [_Polygon(points[index]) for index in range(len(points))]
        if any(polygon.is_empty or not polygon.is_valid for polygon in polygons):
            return None
        try:
            chunk_union = _unary_union(polygons)
        except _GEOMETRY_ERRORS:
            return None
        partials.append(chunk_union)
    if not partials:
        return None
    try:
        filled = _unary_union(partials)
    except _GEOMETRY_ERRORS:
        return None
    parts = _polygon_parts(filled)
    numeric_area_error = (
        np.finfo(np.float64).eps
        * coordinate_magnitude
        * coordinate_magnitude
        * max(64, len(cap_faces) * 64)
    )
    if (
        not parts
        or not filled.is_valid
        or not math.isclose(
            float(filled.area),
            triangle_area,
            rel_tol=0.0,
            abs_tol=max(1e-12, numeric_area_error),
        )
    ):
        return None

    return filled


def _side_faces_match_vertical_prism(
    writer_vertices: np.ndarray,
    faces: np.ndarray,
    *,
    z_min: np.float32,
    z_max: np.float32,
    footprint: _Polygonal,
) -> bool:
    """Prove that all non-cap triangles form vertical footprint walls."""

    if footprint.is_empty:
        return False
    for start in range(0, len(faces), _WRITER_FACE_CHUNK_SIZE):
        chunk = faces[start : start + _WRITER_FACE_CHUNK_SIZE]
        triangle_vertices = writer_vertices[chunk]
        triangle_z = triangle_vertices[:, :, 2]
        cap_mask = np.all(triangle_z == z_min, axis=1) | np.all(
            triangle_z == z_max,
            axis=1,
        )
        side_triangles = triangle_vertices[~cap_mask, :, :2].astype(np.float64)
        if not len(side_triangles):
            continue
        first_edges = side_triangles[:, 1] - side_triangles[:, 0]
        second_edges = side_triangles[:, 2] - side_triangles[:, 0]
        twice_area = (
            first_edges[:, 0] * second_edges[:, 1]
            - first_edges[:, 1] * second_edges[:, 0]
        )
        if np.any(twice_area != 0.0):
            return False
        pair_indexes = np.asarray(((0, 1), (1, 2), (2, 0)), dtype=np.int64)
        paired = side_triangles[:, pair_indexes]
        squared_lengths = np.sum(
            (paired[:, :, 1] - paired[:, :, 0]) ** 2,
            axis=2,
        )
        longest = np.argmax(squared_lengths, axis=1)
        if np.any(squared_lengths[np.arange(len(longest)), longest] == 0.0):
            return False
        endpoints = paired[np.arange(len(longest)), longest]
        if not np.all(_covered_by(_linestrings(endpoints), footprint)):
            return False
    return True


def _writer_boundary_profile(
    writer_vertices: np.ndarray,
    faces: np.ndarray,
) -> _WriterBoundaryProfile | None:
    """Build a filled writer-domain profile for a vertical prism mesh."""

    if len(writer_vertices) == 0 or len(faces) == 0:
        return None
    bounds = _component_writer_bounds(writer_vertices, faces)
    if bounds is None:
        return None
    z_min = np.float32(bounds[2])
    z_max = np.float32(bounds[5])
    if not np.isfinite(z_min) or not np.isfinite(z_max) or z_min >= z_max:
        return None
    footprint = _filled_cap_footprint(writer_vertices, faces, z_min)
    top_footprint = _filled_cap_footprint(writer_vertices, faces, z_max)
    if footprint is None or top_footprint is None:
        return None
    if (
        not footprint.equals(top_footprint)
        or not _side_faces_match_vertical_prism(
            writer_vertices,
            faces,
            z_min=z_min,
            z_max=z_max,
            footprint=footprint,
        )
    ):
        return None
    return _WriterBoundaryProfile(
        footprint=footprint,
        bounds=tuple(float(value) for value in footprint.bounds),
        z_min=float(z_min),
        z_max=float(z_max),
    )


def _profiles_may_touch(
    first: _WriterBoundaryProfile,
    second: _WriterBoundaryProfile,
) -> bool:
    """Return whether closed 3D ranges overlap before exact line testing."""

    first_min_x, first_min_y, first_max_x, first_max_y = first.bounds
    second_min_x, second_min_y, second_max_x, second_max_y = second.bounds
    return (
        first.z_min <= second.z_max
        and second.z_min <= first.z_max
        and first_min_x <= second_max_x
        and second_min_x <= first_max_x
        and first_min_y <= second_max_y
        and second_min_y <= first_max_y
    )


def _profiles_touch(
    first: _WriterBoundaryProfile,
    second: _WriterBoundaryProfile,
) -> bool:
    """Check exact float32 boundary contact after a cheap 3D AABB test."""

    return _profiles_may_touch(first, second) and bool(
        first.footprint.intersects(second.footprint)
    )


def _component_writer_bounds(
    writer_vertices: np.ndarray,
    faces: np.ndarray,
) -> tuple[float, float, float, float, float, float] | None:
    """Return one component's closed writer AABB."""

    if (
        len(faces) == 0
        or np.any(faces < 0)
        or np.any(faces >= len(writer_vertices))
    ):
        return None
    if len(faces) <= _SMALL_MESH_FACE_LIMIT:
        points = writer_vertices[faces]
        minimum = np.min(points, axis=(0, 1))
        maximum = np.max(points, axis=(0, 1))
    else:
        minimum = np.full(3, np.inf, dtype=np.float64)
        maximum = np.full(3, -np.inf, dtype=np.float64)
        for start in range(0, len(faces), _WRITER_FACE_CHUNK_SIZE):
            used = faces[
                start : start + _WRITER_FACE_CHUNK_SIZE
            ].reshape(-1)
            points = writer_vertices[used]
            minimum = np.minimum(minimum, np.min(points, axis=0))
            maximum = np.maximum(maximum, np.max(points, axis=0))
    return (
        float(minimum[0]),
        float(minimum[1]),
        float(minimum[2]),
        float(maximum[0]),
        float(maximum[1]),
        float(maximum[2]),
    )


def _candidate_component_pairs(
    bounds: np.ndarray,
) -> Iterator[tuple[int, int]]:
    """Yield closed XY/Z AABB candidates without an N-squared pair array."""

    if len(bounds) < 2:
        return
    boxes = _vectorized_box(
        bounds[:, 0],
        bounds[:, 1],
        bounds[:, 3],
        bounds[:, 4],
    )
    tree = _STRtree(boxes)
    inspected_pairs = 0
    for first, first_box in enumerate(boxes):
        for second_raw in tree.query(first_box, predicate="intersects"):
            second = int(second_raw)
            if second <= first:
                continue
            inspected_pairs += 1
            if inspected_pairs > _COMPONENT_AABB_PAIR_LIMIT:
                raise _ComponentPairBudgetExceeded
            if (
                bounds[first, 2] <= bounds[second, 5]
                and bounds[second, 2] <= bounds[first, 5]
            ):
                yield first, second


def _triangles_touch(
    first: np.ndarray,
    second: np.ndarray,
) -> bool:
    """Conservatively test two closed float32-domain triangles for contact."""

    first_edges = np.roll(first, -1, axis=0) - first
    second_edges = np.roll(second, -1, axis=0) - second
    first_normal = np.cross(first_edges[0], first_edges[1])
    second_normal = np.cross(second_edges[0], second_edges[1])
    axes = [first_normal, second_normal]
    axes.extend(
        np.cross(first_edge, second_edge)
        for first_edge in first_edges
        for second_edge in second_edges
    )
    # Triangle surfaces are zero-thickness convex sets.  The usual 3D
    # triangle axes collapse to the shared normal for coplanar faces, so add
    # in-plane edge normals to distinguish disjoint coplanar triangles.
    axes.extend(np.cross(first_normal, edge) for edge in first_edges)
    axes.extend(np.cross(second_normal, edge) for edge in second_edges)
    for axis in axes:
        norm = float(np.linalg.norm(axis))
        if not math.isfinite(norm) or norm <= np.finfo(np.float64).tiny:
            continue
        first_projection = first @ axis
        second_projection = second @ axis
        magnitude = max(
            1.0,
            float(np.max(np.abs(first_projection))),
            float(np.max(np.abs(second_projection))),
        )
        tolerance = np.finfo(np.float64).eps * 64.0 * magnitude
        if (
            float(np.max(first_projection))
            < float(np.min(second_projection)) - tolerance
            or float(np.max(second_projection))
            < float(np.min(first_projection)) - tolerance
        ):
            return False
    return True


def _point_inside_closed_surface(
    point: np.ndarray,
    triangles: np.ndarray,
) -> bool | None:
    """Classify a point by the oriented solid angle of a closed triangle shell."""

    relative = triangles - np.asarray(point, dtype=np.float64)
    lengths = np.linalg.norm(relative, axis=2)
    if not np.all(np.isfinite(lengths)) or np.any(
        lengths <= np.finfo(np.float64).tiny
    ):
        return None
    first = relative[:, 0]
    second = relative[:, 1]
    third = relative[:, 2]
    numerator = np.einsum(
        "ij,ij->i",
        first,
        np.cross(second, third),
    )
    denominator = (
        lengths[:, 0] * lengths[:, 1] * lengths[:, 2]
        + np.einsum("ij,ij->i", first, second) * lengths[:, 2]
        + np.einsum("ij,ij->i", second, third) * lengths[:, 0]
        + np.einsum("ij,ij->i", third, first) * lengths[:, 1]
    )
    angles = 2.0 * np.arctan2(numerator, denominator)
    if not np.all(np.isfinite(angles)):
        return None
    magnitude = abs(float(angles.sum(dtype=np.float64)))
    if magnitude >= 2.0 * math.pi:
        return True
    if magnitude <= 1e-6:
        return False
    return None


def _component_surfaces_touch(
    first_vertices: np.ndarray,
    first_faces: np.ndarray,
    second_vertices: np.ndarray,
    second_faces: np.ndarray,
) -> bool | None:
    """Check small non-prismatic components, returning ``None`` if unbounded."""

    if (
        len(first_faces) > _GENERIC_COMPONENT_FACE_LIMIT
        or len(second_faces) > _GENERIC_COMPONENT_FACE_LIMIT
        or np.any(first_faces < 0)
        or np.any(first_faces >= len(first_vertices))
        or np.any(second_faces < 0)
        or np.any(second_faces >= len(second_vertices))
    ):
        return None
    first_triangles = first_vertices[first_faces].astype(np.float64)
    second_triangles = second_vertices[second_faces].astype(np.float64)
    second_minimum = np.min(second_triangles, axis=1)
    second_maximum = np.max(second_triangles, axis=1)
    candidate_count = 0
    for triangle in first_triangles:
        first_minimum = np.min(triangle, axis=0)
        first_maximum = np.max(triangle, axis=0)
        candidates = np.flatnonzero(
            np.all(first_minimum <= second_maximum, axis=1)
            & np.all(second_minimum <= first_maximum, axis=1)
        )
        candidate_count += len(candidates)
        if candidate_count > _GENERIC_COMPONENT_PAIR_LIMIT:
            return None
        for index in candidates:
            if _triangles_touch(triangle, second_triangles[int(index)]):
                return True
    first_point = first_vertices[int(first_faces[0, 0])].astype(np.float64)
    second_point = second_vertices[int(second_faces[0, 0])].astype(np.float64)
    first_inside_second = _point_inside_closed_surface(
        first_point,
        second_triangles,
    )
    second_inside_first = _point_inside_closed_surface(
        second_point,
        first_triangles,
    )
    if first_inside_second is None or second_inside_first is None:
        return None
    return first_inside_second or second_inside_first


def _small_writer_topology_is_safe(
    vertices: np.ndarray,
    faces: np.ndarray,
    scale: float,
    *,
    require_unit_height: bool,
    measure_coverage: bool,
) -> tuple[bool, float | None, str | None]:
    """Validate a small mesh and optionally measure physical coverage."""
    writer_vertices: list[tuple[float, float, float]] = []
    seen: set[tuple[float, float, float]] = set()
    z_min, z_max = math.inf, -math.inf
    for x, y, z in vertices:
        scaled_x, scaled_y, z_value = float(x) * scale, float(y) * scale, float(z)
        if (
            not math.isfinite(scaled_x)
            or not math.isfinite(scaled_y)
            or not math.isfinite(z_value)
            or abs(scaled_x) > _FLOAT32_MAX
            or abs(scaled_y) > _FLOAT32_MAX
            or abs(z_value) > _FLOAT32_MAX
        ):
            return False, None, "writer_coordinate_non_finite"
        key = (float(np.float32(scaled_x)), float(np.float32(scaled_y)),
               float(np.float32(z_value)))
        if key in seen:
            return False, None, "float32_duplicate_vertex"
        seen.add(key)
        writer_vertices.append(key)
        z_min, z_max = min(z_min, z_value), max(z_max, z_value)
    if require_unit_height and (z_min != 0.0 or z_max != 1.0):
        return False, None, "non_unit_height"

    vertex_count = len(writer_vertices)
    signed_volume_six = 0.0
    for raw_start, raw_middle, raw_end in faces:
        start, middle, end = int(raw_start), int(raw_middle), int(raw_end)
        if (
            min(start, middle, end) < 0
            or max(start, middle, end) >= vertex_count
        ):
            return False, None, "face_index_out_of_range"
        if start == middle or middle == end or end == start:
            return False, None, "index_degenerate_triangle"
        point_a = writer_vertices[start]
        point_b, point_c = writer_vertices[middle], writer_vertices[end]
        ax, ay, az = (point_b[index] - point_a[index] for index in range(3))
        bx, by, bz = (point_c[index] - point_a[index] for index in range(3))
        cross_x = ay * bz - az * by
        cross_y = az * bx - ax * bz
        cross_z = ax * by - ay * bx
        if cross_x == 0.0 and cross_y == 0.0 and cross_z == 0.0:
            return False, None, "float32_degenerate_triangle"
        if measure_coverage:
            signed_volume_six += (
                point_a[0] * cross_x
                + point_a[1] * cross_y
                + point_a[2] * cross_z
            )
    coverage = abs(signed_volume_six) / 6.0 if measure_coverage else None
    return True, coverage, None


def _analyse_export_mesh(
    mesh: trimesh.Trimesh,
    scale: float,
    *,
    require_unit_height: bool,
    measure_coverage: bool,
) -> tuple[bool, float | None, str | None, bool | None]:
    """Validate one candidate and optionally return physical coverage."""
    arrays = _mesh_arrays(mesh)
    if arrays is None:
        return False, None, "invalid_mesh_arrays", None
    vertices, faces = arrays
    if len(faces) <= _SMALL_MESH_FACE_LIMIT:
        safe, coverage, reason = _small_writer_topology_is_safe(
            vertices,
            faces,
            scale,
            require_unit_height=require_unit_height,
            measure_coverage=measure_coverage,
        )
    else:
        if not np.all(np.isfinite(vertices)):
            return False, None, "source_coordinate_non_finite", None
        if np.any(faces < 0) or np.any(faces >= len(vertices)):
            return False, None, "face_index_out_of_range", None
        if np.any(
            (faces[:, 0] == faces[:, 1])
            | (faces[:, 1] == faces[:, 2])
            | (faces[:, 2] == faces[:, 0])
        ):
            return False, None, "index_degenerate_triangle", None
        if require_unit_height and (
            float(np.min(vertices[:, 2])) != 0.0
            or float(np.max(vertices[:, 2])) != 1.0
        ):
            return False, None, "non_unit_height", None
        writer_vertices = np.empty(vertices.shape, dtype=np.float32)
        with np.errstate(over="ignore", invalid="ignore"):
            np.multiply(vertices[:, :2], scale, out=writer_vertices[:, :2])
            writer_vertices[:, 2] = vertices[:, 2]
        if not np.all(np.isfinite(writer_vertices)):
            return False, None, "writer_coordinate_non_finite", None
        if len(np.unique(writer_vertices, axis=0)) != len(writer_vertices):
            return False, None, "float32_duplicate_vertex", None
        safe, measured = _writer_mesh_metrics(
            writer_vertices,
            faces,
            measure_coverage=measure_coverage,
        )
        reason = None if safe else "float32_degenerate_triangle"
        coverage = measured if safe else None
    if not safe:
        return False, None, reason, None
    try:
        if not bool(mesh.is_watertight):
            return False, None, "mesh_not_watertight", False
        if not bool(mesh.is_winding_consistent):
            return False, None, "mesh_winding_inconsistent", True
        face_components = trimesh.graph.connected_components(
            np.asarray(mesh.face_adjacency, dtype=np.int64),
            nodes=np.arange(len(faces), dtype=np.int64),
            min_len=1,
        )
        if len(face_components) > 1:
            writer_boundary_vertices = _writer_vertices_for_offset(
                vertices,
                scale,
            )
            if writer_boundary_vertices is None:
                return False, None, "writer_coordinate_non_finite", None
            component_faces_list = [
                faces[np.asarray(component, dtype=np.int64)]
                for component in face_components
            ]
            component_bounds = []
            for component_faces in component_faces_list:
                bounds = _component_writer_bounds(
                    writer_boundary_vertices,
                    component_faces,
                )
                if bounds is None:
                    return False, None, "writer_component_bounds_invalid", True
                component_bounds.append(bounds)
            candidate_pairs = _candidate_component_pairs(
                np.asarray(component_bounds, dtype=np.float64)
            )
            component_profiles: dict[int, _WriterBoundaryProfile] = {}

            def profile_for(index: int) -> _WriterBoundaryProfile | None:
                profile = component_profiles.get(index)
                if profile is None:
                    profile = _writer_boundary_profile(
                        writer_boundary_vertices,
                        component_faces_list[index],
                    )
                    if profile is not None:
                        component_profiles[index] = profile
                return profile

            for first_index, second_index in candidate_pairs:
                first_profile = profile_for(first_index)
                second_profile = profile_for(second_index)
                if first_profile is not None and second_profile is not None:
                    components_touch: bool | None = _profiles_touch(
                        first_profile,
                        second_profile,
                    )
                else:
                    components_touch = _component_surfaces_touch(
                        writer_boundary_vertices,
                        component_faces_list[first_index],
                        writer_boundary_vertices,
                        component_faces_list[second_index],
                    )
                if components_touch is None:
                    return (
                        False,
                        None,
                        "writer_component_boundary_invalid",
                        True,
                    )
                if components_touch:
                    return (
                        False,
                        None,
                        "writer_component_boundary_contact",
                        True,
                    )
        return True, coverage, None, True
    except _ComponentPairBudgetExceeded:
        return False, None, "writer_component_pair_budget_exceeded", True
    except (IndexError, TypeError, ValueError, RuntimeError):
        return False, None, "watertight_check_failed", None


def mesh_is_float32_safe(mesh: trimesh.Trimesh, *, xy_scale: float = 1.0) -> bool:
    """Check writer-domain float32 topology. / 校验写出域 float32 拓扑。

    Args:
        mesh: Triangle mesh to validate. / 要校验的三角网格。
        xy_scale: XY scale applied before serialization. / 序列化前的 XY 缩放。

    Returns:
        Whether the converted mesh is closed and manifold. / 转换后网格是否
        闭合且为流形。
    """

    scale = _positive_scale(xy_scale)
    if scale is None:
        return False
    safe, _coverage, _reason, _watertight = _analyse_export_mesh(
        mesh, scale, require_unit_height=False, measure_coverage=False
    )
    return safe


def _polygon_parts(geometry: object) -> list[_Polygon] | None:
    """Return non-empty polygon parts, rejecting other geometry types."""
    if isinstance(geometry, _Polygon):
        return [geometry] if not geometry.is_empty else None
    if isinstance(geometry, _MultiPolygon):
        parts = [part for part in geometry.geoms if not part.is_empty]
        return parts or None
    return None


def _ring_vertices(ring: _LinearRing) -> set[tuple[float, float]]:
    """Return the non-closing XY vertices of a polygon ring."""
    return {
        tuple(float(value) for value in point[:2]) for point in ring.coords[:-1]
    }


def _float32_unsafe_ring_count(geometry: _Polygonal, scale: float) -> int:
    """Count rings that cannot retain their vertices in writer space."""
    parts = _polygon_parts(geometry)
    if not parts:
        return 1
    unsafe_count = 0
    for polygon in parts:
        for ring in (polygon.exterior, *polygon.interiors):
            try:
                coordinates = np.asarray(ring.coords, dtype=np.float64)[:-1, :2]
            except (AttributeError, TypeError, ValueError):
                unsafe_count += 1
                continue
            if len(coordinates) < 3 or not np.all(np.isfinite(coordinates)):
                unsafe_count += 1
                continue
            with np.errstate(over="ignore", invalid="ignore"):
                scaled = coordinates * scale
            if (
                not np.all(np.isfinite(scaled))
                or np.any(np.abs(scaled) > _FLOAT32_MAX)
            ):
                unsafe_count += 1
                continue
            if len(np.unique(scaled.astype(np.float32), axis=0)) != len(coordinates):
                unsafe_count += 1
    return unsafe_count


def _geometry_has_float32_ring_collapse(geometry: _Polygonal, scale: float) -> bool:
    """Return whether any ring collapses in the float32 writer domain."""

    return _float32_unsafe_ring_count(geometry, scale) > 0


def _physical_area(geometry: _Polygonal, scale: float) -> float | None:
    """Return polygonal area in square millimetres."""
    try:
        area = abs(float(geometry.area)) * scale * scale
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    return area if math.isfinite(area) else None


def _coverage_is_safe(expected_mm2: float, actual_mm2: float) -> bool:
    """Return whether two physical areas meet the export coverage bound."""
    if not math.isfinite(expected_mm2) or not math.isfinite(actual_mm2):
        return False
    tolerance = max(
        VECTOR_COVERAGE_ABS_TOL_MM2, expected_mm2 * VECTOR_COVERAGE_REL_TOL
    )
    return abs(actual_mm2 - expected_mm2) <= tolerance


def _writer_volume_is_safe(expected_mm3: float, actual_mm3: float) -> bool:
    """Compare generic-solid writer volumes with an explicit mm3 bound."""

    if not math.isfinite(expected_mm3) or not math.isfinite(actual_mm3):
        return False
    tolerance = max(
        _WRITER_VOLUME_ABS_TOL_MM3,
        expected_mm3 * _WRITER_VOLUME_REL_TOL,
    )
    return abs(actual_mm3 - expected_mm3) <= tolerance


def _attempt_geometry_metrics(
    attempt: str,
    geometry: _Polygonal | None,
    scale: float,
    original_area_mm2: float,
) -> dict[str, object]:
    """Build coordinate-free metrics for one bounded ladder attempt."""
    parts = _polygon_parts(geometry) if geometry is not None else None
    polygons = parts or []
    hole_count = sum(len(part.interiors) for part in polygons)
    vertex_count = 0
    for part in polygons:
        vertex_count += max(0, len(part.exterior.coords) - 1)
        vertex_count += sum(
            max(0, len(ring.coords) - 1) for ring in part.interiors
        )
    candidate_area = (
        _physical_area(geometry, scale) if geometry is not None else None
    )
    area_delta = (
        abs(candidate_area - original_area_mm2)
        if candidate_area is not None else None
    )
    return {
        "attempt": attempt,
        "geometry_type": (
            getattr(geometry, "geom_type", None)
            if geometry is not None else None
        ),
        "polygon_part_count": len(polygons),
        "ring_count": len(polygons) + hole_count,
        "hole_count": hole_count,
        "vertex_count": vertex_count,
        "original_area_mm2": original_area_mm2,
        "candidate_area_mm2": candidate_area,
        "area_delta_mm2": area_delta,
        "float32_ring_collapse_count": (
            _float32_unsafe_ring_count(geometry, scale)
            if geometry is not None else None
        ),
        "candidate_mesh_count": 0,
        "watertight": None,
        "non_manifold_edge_count": None,
        "expected_coverage_mm2": original_area_mm2,
        "actual_coverage_mm2": None,
        "rejected_reason": None,
        "error_type": None,
    }


def _normalise_polygonal(
    geometry: object,
    *,
    grid_size: float | None = None,
    union_first: bool = False,
) -> _Polygonal | None:
    """Apply optional precision and return one valid polygonal result."""
    try:
        candidate = _unary_union(geometry) if union_first else geometry
        if grid_size is not None:
            candidate = _set_precision(candidate, grid_size=grid_size)
        if candidate is None or getattr(candidate, "is_empty", True):
            return None
        if not getattr(candidate, "is_valid", False):
            candidate = _make_valid(candidate)
        if isinstance(candidate, (_Polygon, _MultiPolygon)):
            return candidate if candidate.is_valid and not candidate.is_empty else None
        parts = [part for part in getattr(candidate, "geoms", ())
                 if isinstance(part, _Polygon) and not part.is_empty]
        merged = _unary_union(parts) if parts else None
    except _GEOMETRY_ERRORS:
        return None
    if isinstance(merged, (_Polygon, _MultiPolygon)):
        return merged if merged.is_valid and not merged.is_empty else None
    return None


def prepare_geometry_for_float32(
    geometry: _Polygonal,
    *,
    xy_scale: float,
) -> _Polygonal | None:
    """Prepare whole geometry for float32 IO. / 为 float32 写出准备整个几何。

    Args:
        geometry: Polygon or multipolygon to prepare. / 待准备的多边形几何。
        xy_scale: XY scale applied before serialization. / 序列化前的 XY 缩放。

    Returns:
        Original geometry, an area-safe 0.0001 mm-grid repair, or ``None``. /
        原几何、面积安全的 0.0001 mm 网格修复结果，或 ``None``。
    """

    scale = _positive_scale(xy_scale)
    if scale is None or not _polygon_parts(geometry):
        return None
    if not _geometry_has_float32_ring_collapse(geometry, scale):
        return geometry
    original_area = _physical_area(geometry, scale)
    if original_area is None:
        return None
    prepared = _normalise_polygonal(
        geometry, grid_size=_FLOAT32_GRID_MM / scale, union_first=True
    )
    repaired_area = _physical_area(prepared, scale) if prepared is not None else None
    if (
        repaired_area is None
        or not _coverage_is_safe(original_area, repaired_area)
        or _geometry_has_float32_ring_collapse(prepared, scale)
    ):
        return None
    return prepared


def separate_component_coordinates(
    meshes: list[trimesh.Trimesh],
    *,
    separation_mm: float = 1e-4,
    xy_scale: float = 1.0,
) -> bool:
    """Separate shells with bounded translations. / 有界平移独立壳体。

    Args:
        meshes: Independent meshes to separate. / 需要分离的独立网格。
        separation_mm: Physical offset per step in millimetres. / 每步物理偏移
            （毫米）。
        xy_scale: XY scale from mesh coordinates to millimetres. /
            网格坐标到毫米的 XY 缩放。

    Returns:
        Whether every component has collision-free float32 coordinates. /
        所有组件的 float32 坐标是否均无碰撞。
    """

    separation = _positive_scale(separation_mm)
    scale = _positive_scale(xy_scale)
    if separation is None or scale is None:
        return False
    geometry_separation = separation / scale
    vertices_by_mesh: list[np.ndarray] = []
    faces_by_mesh: list[np.ndarray] = []
    writer_by_mesh: list[np.ndarray] = []
    initial_volume_by_mesh: list[float] = []
    bounds_by_mesh: list[tuple[float, float, float, float, float, float]] = []
    for mesh in meshes:
        arrays = _mesh_arrays(mesh)
        if arrays is None:
            return False
        vertices, faces = arrays
        if not np.all(np.isfinite(vertices)):
            return False
        writer = _writer_vertices_for_offset(vertices, scale)
        if (
            writer is None
            or np.any(faces < 0)
            or np.any(faces >= len(writer))
            or np.any(
                (faces[:, 0] == faces[:, 1])
                | (faces[:, 1] == faces[:, 2])
                | (faces[:, 2] == faces[:, 0])
            )
        ):
            return False
        if len(np.unique(writer, axis=0)) != len(writer):
            return False
        valid, initial_volume = _writer_mesh_metrics(
            writer,
            faces,
            measure_coverage=True,
        )
        if (
            not valid
            or initial_volume is None
            or not math.isfinite(initial_volume)
        ):
            return False
        bounds = _component_writer_bounds(writer, faces)
        if bounds is None:
            return False
        vertices_by_mesh.append(vertices)
        faces_by_mesh.append(faces)
        writer_by_mesh.append(writer)
        initial_volume_by_mesh.append(initial_volume)
        bounds_by_mesh.append(bounds)
    if not meshes:
        return True

    bounds_array = np.asarray(bounds_by_mesh, dtype=np.float64)
    profiles: list[_WriterBoundaryProfile | None] = [None] * len(meshes)
    profiles_ready = [False] * len(meshes)

    def profile_for(index: int) -> _WriterBoundaryProfile | None:
        if not profiles_ready[index]:
            profiles[index] = _writer_boundary_profile(
                writer_by_mesh[index],
                faces_by_mesh[index],
            )
            profiles_ready[index] = True
        return profiles[index]

    def components_touch(first_index: int, second_index: int) -> bool | None:
        first_profile = profile_for(first_index)
        second_profile = profile_for(second_index)
        if first_profile is not None and second_profile is not None:
            return _profiles_touch(first_profile, second_profile)
        return _component_surfaces_touch(
            writer_by_mesh[first_index],
            faces_by_mesh[first_index],
            writer_by_mesh[second_index],
            faces_by_mesh[second_index],
        )

    colliding_indexes: set[int] = set()
    try:
        for first_index, second_index in _candidate_component_pairs(bounds_array):
            touches = components_touch(first_index, second_index)
            if touches is None:
                return False
            if touches:
                colliding_indexes.update((first_index, second_index))
    except _ComponentPairBudgetExceeded:
        return False
    if not colliding_indexes:
        return True

    offsets = (
        (0.0, 0.0, 0.0),
        *((dx * geometry_separation * step,
           dy * geometry_separation * step, 0.0)
          for step in range(1, _COMPONENT_MAX_STEPS + 1)
          for dx, dy in _COMPONENT_DIRECTIONS),
    )
    selected = [(0.0, 0.0, 0.0) for _mesh in meshes]
    anchored_index = min(colliding_indexes)
    for index in sorted(colliding_indexes - {anchored_index}):
        vertices = vertices_by_mesh[index]
        faces = faces_by_mesh[index]
        initial_volume = initial_volume_by_mesh[index]
        original_profile = profile_for(index)
        accepted: tuple[float, float, float] | None = None
        accepted_writer: np.ndarray | None = None
        accepted_profile: _WriterBoundaryProfile | None = None
        accepted_bounds: tuple[float, float, float, float, float, float] | None = None
        for offset in offsets:
            writer_candidate = _writer_vertices_for_offset(
                vertices,
                scale,
                offset,
            )
            if (
                writer_candidate is None
                or len(np.unique(writer_candidate, axis=0))
                != len(writer_candidate)
            ):
                continue
            valid, candidate_volume = _writer_mesh_metrics(
                writer_candidate,
                faces,
                measure_coverage=True,
            )
            if (
                not valid
                or candidate_volume is None
            ):
                continue
            candidate_profile = _writer_boundary_profile(
                writer_candidate,
                faces,
            )
            if original_profile is not None:
                if (
                    candidate_profile is None
                    or not _coverage_is_safe(
                        float(original_profile.footprint.area),
                        float(candidate_profile.footprint.area),
                    )
                ):
                    continue
            elif not _writer_volume_is_safe(
                initial_volume,
                candidate_volume,
            ):
                continue
            candidate_bounds = _component_writer_bounds(
                writer_candidate,
                faces,
            )
            if candidate_bounds is None:
                continue
            row = np.asarray(candidate_bounds, dtype=np.float64)
            nearby = np.flatnonzero(
                (row[0] <= bounds_array[:, 3])
                & (bounds_array[:, 0] <= row[3])
                & (row[1] <= bounds_array[:, 4])
                & (bounds_array[:, 1] <= row[4])
                & (row[2] <= bounds_array[:, 5])
                & (bounds_array[:, 2] <= row[5])
            )
            touches_other = False
            for other_index_raw in nearby:
                other_index = int(other_index_raw)
                if other_index == index:
                    continue
                other_profile = profile_for(other_index)
                if candidate_profile is not None and other_profile is not None:
                    touches = _profiles_touch(
                        candidate_profile,
                        other_profile,
                    )
                else:
                    touches = _component_surfaces_touch(
                        writer_candidate,
                        faces,
                        writer_by_mesh[other_index],
                        faces_by_mesh[other_index],
                    )
                if touches is None or touches:
                    touches_other = True
                    break
            if not touches_other:
                accepted = offset
                accepted_writer = writer_candidate
                accepted_profile = candidate_profile
                accepted_bounds = candidate_bounds
                break
        if accepted is None or accepted_writer is None or accepted_bounds is None:
            return False
        selected[index] = accepted
        writer_by_mesh[index] = accepted_writer
        profiles[index] = accepted_profile
        profiles_ready[index] = True
        bounds_by_mesh[index] = accepted_bounds
        bounds_array[index] = accepted_bounds

    try:
        for first_index, second_index in _candidate_component_pairs(bounds_array):
            touches = components_touch(first_index, second_index)
            if touches is None or touches:
                return False
    except _ComponentPairBudgetExceeded:
        return False

    moved: list[tuple[trimesh.Trimesh, np.ndarray]] = []
    try:
        for mesh, vertices, offset in zip(meshes, vertices_by_mesh, selected):
            if offset != (0.0, 0.0, 0.0):
                moved.append((mesh, vertices.copy()))
                mesh.apply_translation(offset)
    except (TypeError, ValueError, RuntimeError):
        for mesh, original in moved:
            mesh.vertices = original
        return False
    return True


def _contact_component_anchors(
    rings: list[tuple[_LinearRing, set[tuple[float, float]]]],
    contacts: list[set[tuple[float, float]]],
    neighbours: list[set[int]],
    touches_exterior: list[bool],
) -> set[int]:
    """Choose one stationary ring for each hole-only contact component."""
    anchors: set[int] = set()
    unvisited = {index for index, points in enumerate(contacts) if points}
    while unvisited:
        start = min(unvisited)
        component: set[int] = set()
        pending = [start]
        while pending:
            index = pending.pop()
            if index in component:
                continue
            component.add(index)
            pending.extend(neighbours[index] - component)
        unvisited.difference_update(component)
        if any(touches_exterior[index] for index in component):
            continue

        def anchor_rank(index: int) -> tuple[int, float, int]:
            try:
                area = abs(float(_Polygon(rings[index][0]).area))
            except _GEOMETRY_ERRORS:
                area = 0.0
            return len(neighbours[index]), area, -index

        anchors.add(max(component, key=anchor_rank))
    return anchors


def _separate_polygon_ring_contacts(
    poly: _Polygon,
    geometry_gap: float,
) -> _Polygon | None:
    """Move touching holes inward by one bounded geometry-space offset."""
    exterior = _ring_vertices(poly.exterior)
    rings = [(ring, _ring_vertices(ring)) for ring in poly.interiors]
    owners: dict[tuple[float, float], list[int]] = {}
    for index, (_ring, vertices) in enumerate(rings):
        for vertex in vertices:
            owners.setdefault(vertex, []).append(index)
    contacts: list[set[tuple[float, float]]] = [set() for _ring in rings]
    neighbours: list[set[int]] = [set() for _ring in rings]
    touches_exterior = [False for _ring in rings]
    for vertex, ring_indexes in owners.items():
        if vertex not in exterior and len(ring_indexes) == 1:
            continue
        for index in ring_indexes:
            contacts[index].add(vertex)
            if vertex in exterior:
                touches_exterior[index] = True
            neighbours[index].update(
                other for other in ring_indexes if other != index
            )
    if not any(contacts):
        return poly
    anchors = _contact_component_anchors(
        rings,
        contacts,
        neighbours,
        touches_exterior,
    )

    translated_holes = []
    for index, (ring, _vertices) in enumerate(rings):
        if not contacts[index] or index in anchors:
            translated_holes.append(ring.coords)
            continue
        hole = _Polygon(ring)
        center = np.asarray(tuple(contacts[index]), dtype=np.float64).mean(axis=0)
        point = hole.representative_point()
        direction = np.asarray((point.x, point.y), dtype=np.float64) - center
        length = float(np.linalg.norm(direction))
        if not math.isfinite(length) or length <= 0.0:
            return None
        offset = direction * (geometry_gap / length)
        try:
            moved = _affinity.translate(
                hole, xoff=float(offset[0]), yoff=float(offset[1])
            )
        except _GEOMETRY_ERRORS:
            return None
        if moved.is_empty or not isinstance(moved, _Polygon):
            return None
        translated_holes.append(moved.exterior.coords)

    repaired = _Polygon(poly.exterior.coords, translated_holes)
    if repaired.is_empty or not repaired.is_valid:
        return None
    seen = set(exterior)
    for ring in repaired.interiors:
        vertices = _ring_vertices(ring)
        if not seen.isdisjoint(vertices):
            return None
        seen.update(vertices)
    return repaired


def _repair_polygon_ring_contacts(
    poly: _Polygon,
    scale: float,
    separation_mm: float,
) -> _Polygonal | None:
    """Snap and separate ring contacts on one finite physical grid."""
    geometry_gap = separation_mm / scale
    if not math.isfinite(geometry_gap) or geometry_gap <= 0.0:
        return None
    snapped = _normalise_polygonal(poly, grid_size=geometry_gap)
    if isinstance(snapped, _Polygon):
        return _separate_polygon_ring_contacts(snapped, geometry_gap)
    if not isinstance(snapped, _MultiPolygon):
        return None
    parts = [
        _separate_polygon_ring_contacts(part, geometry_gap)
        for part in snapped.geoms
        if not part.is_empty
    ]
    if not parts or any(part is None for part in parts):
        return None
    repaired = parts[0] if len(parts) == 1 else _MultiPolygon(parts)
    return _normalise_polygonal(repaired)


def _extrude_polygon_unit_height_indexed(poly: _Polygon) -> trimesh.Trimesh:
    """Build a unit-height prism from triangulation boundary indices."""
    try:
        vertices_2d, cap_faces = trimesh.creation.triangulate_polygon(
            poly, engine="manifold"
        )
    except _RECOVERABLE_EXPORT_ERRORS:
        rings = [
            np.asarray(poly.exterior.coords, dtype=np.float64)[:-1, :2],
            *[
                np.asarray(ring.coords, dtype=np.float64)[:-1, :2]
                for ring in poly.interiors
            ],
        ]
        if any(len(ring) < 3 for ring in rings):
            raise ValueError("Vector polygon contains a degenerate ring")
        vertices_2d = np.vstack(rings)
        ring_ends = np.cumsum([len(ring) for ring in rings], dtype=np.uint32)
        cap_faces = _triangulate_float64(vertices_2d, ring_ends).reshape((-1, 3))

    vertices_2d = np.asarray(vertices_2d, dtype=np.float64)
    cap_faces = np.asarray(cap_faces, dtype=np.int64)
    if (
        vertices_2d.ndim != 2 or vertices_2d.shape[1:] != (2,)
        or cap_faces.ndim != 2 or cap_faces.shape[1:] != (3,)
        or len(cap_faces) == 0 or np.any(cap_faces < 0)
        or np.any(cap_faces >= len(vertices_2d))
    ):
        raise ValueError("Vector polygon triangulation produced no cap faces")
    cap_a = vertices_2d[cap_faces[:, 1]] - vertices_2d[cap_faces[:, 0]]
    cap_b = vertices_2d[cap_faces[:, 2]] - vertices_2d[cap_faces[:, 0]]
    signed_area = cap_a[:, 0] * cap_b[:, 1] - cap_a[:, 1] * cap_b[:, 0]
    if np.any(signed_area == 0.0):
        raise ValueError("Vector polygon triangulation has degenerate cap faces")
    if float(np.mean(signed_area)) < 0.0:
        cap_faces = cap_faces[:, ::-1]

    oriented_edges = np.vstack(
        (cap_faces[:, [0, 1]], cap_faces[:, [1, 2]], cap_faces[:, [2, 0]])
    )
    sorted_edges = np.sort(oriented_edges, axis=1)
    _edges, inverse, counts = np.unique(
        sorted_edges, axis=0, return_inverse=True, return_counts=True
    )
    if np.any(counts > 2):
        raise ValueError("Vector cap triangulation produced non-manifold edges")
    boundary = oriented_edges[counts[inverse] == 1]
    if len(boundary) == 0:
        raise ValueError("Vector polygon triangulation produced no boundary")

    count = len(vertices_2d)
    bottom = np.column_stack((vertices_2d, np.zeros(count, dtype=np.float64)))
    top = np.column_stack((vertices_2d, np.ones(count, dtype=np.float64)))
    start, end = boundary[:, 0], boundary[:, 1]
    sides = np.vstack((
        np.column_stack((start, end, count + end)),
        np.column_stack((start, count + end, count + start)),
    ))
    faces = np.vstack((cap_faces[:, ::-1], cap_faces + count, sides))
    return trimesh.Trimesh(
        vertices=np.vstack((bottom, top)), faces=faces, process=False
    )


def _extrude_indexed_parts(geometry: _Polygonal) -> list[trimesh.Trimesh]:
    """Extrude every polygon part as an independently indexed shell."""
    parts = _polygon_parts(geometry)
    if not parts:
        raise ValueError("Vector polygon repair produced no extrudable parts")
    return [_extrude_polygon_unit_height_indexed(part) for part in parts]


def _meshes_are_export_safe(
    meshes: list[trimesh.Trimesh],
    scale: float,
    *,
    expected_area_mm2: float | None,
    rejection_metrics: dict[str, object] | None = None,
) -> bool:
    """Analyze each mesh once and optionally enforce physical coverage."""
    if not meshes:
        if rejection_metrics is not None:
            rejection_metrics.update(
                candidate_mesh_count=0,
                rejected_reason="no_meshes",
            )
        return False
    if len(meshes) > 1 and not separate_component_coordinates(
        meshes,
        separation_mm=_FLOAT32_GRID_MM,
        xy_scale=scale,
    ):
        if rejection_metrics is not None:
            rejection_metrics.update(
                candidate_mesh_count=len(meshes),
                watertight=None,
                non_manifold_edge_count=None,
                rejected_reason="component_coordinate_collision",
            )
        return False
    coverage_mm2 = 0.0
    for mesh in meshes:
        safe, measured, reason, watertight = _analyse_export_mesh(
            mesh,
            scale,
            require_unit_height=True,
            measure_coverage=expected_area_mm2 is not None,
        )
        if not safe:
            if rejection_metrics is not None:
                rejection_metrics.update(
                    candidate_mesh_count=len(meshes),
                    watertight=watertight,
                    non_manifold_edge_count=(0 if watertight else None),
                    rejected_reason=reason or "mesh_validation_failed",
                )
            return False
        if measured is not None:
            coverage_mm2 += measured
    coverage_safe = expected_area_mm2 is None or _coverage_is_safe(
        expected_area_mm2, coverage_mm2
    )
    if not coverage_safe and rejection_metrics is not None:
        rejection_metrics.update(
            candidate_mesh_count=len(meshes),
            watertight=True,
            non_manifold_edge_count=0,
            actual_coverage_mm2=coverage_mm2,
            rejected_reason="coverage_mismatch",
        )
    return coverage_safe


def extrude_polygon_for_export(
    poly: _Polygon,
    *,
    xy_scale: float,
    prefer_fast: bool,
) -> list[trimesh.Trimesh]:
    """Run the bounded export ladder. / 执行有界的多边形导出阶梯。

    Order: optional fast, original indexed, 0.0001 mm repair, 0.001 mm repair. /
    顺序：可选快速路径、原几何 indexed 路径、两档固定物理修复。

    Args:
        poly: Source polygon to extrude. / 待挤出的源多边形。
        xy_scale: XY scale applied before serialization. / 序列化前的 XY 缩放。
        prefer_fast: Whether to try ordinary extrusion first. / 是否先尝试普通
            挤出。

    Returns:
        Safe independently indexed unit-height meshes. / 安全、独立索引的单位
        高度网格。

    Raises:
        ValueError: If inputs are invalid. / 输入无效。
        VectorTopologyError: If every bounded attempt fails. /
            所有有界尝试均失败。
    """

    scale = _positive_scale(xy_scale)
    if scale is None or not isinstance(poly, _Polygon) or poly.is_empty:
        raise ValueError("Vector polygon export requires a non-empty Polygon")
    original_area = _physical_area(poly, scale)
    if original_area is None:
        raise ValueError("Vector polygon export requires a finite physical area")

    failed_attempts: list[dict[str, object]] = []
    fast_allowed = (
        prefer_fast and poly.is_valid and not poly.interiors
        and not _geometry_has_float32_ring_collapse(poly, scale)
    )
    if fast_allowed:
        try:
            fast_mesh = trimesh.creation.extrude_polygon(poly, height=1.0)
            mesh_diagnostics: dict[str, object] = {}
            if _meshes_are_export_safe(
                [fast_mesh],
                scale,
                expected_area_mm2=original_area,
                rejection_metrics=mesh_diagnostics,
            ):
                return [fast_mesh]
            diagnostics = _attempt_geometry_metrics(
                "fast", poly, scale, original_area
            )
            diagnostics.update(mesh_diagnostics)
            failed_attempts.append(diagnostics)
        except _RECOVERABLE_EXPORT_ERRORS as exc:
            diagnostics = _attempt_geometry_metrics(
                "fast", poly, scale, original_area
            )
            diagnostics.update(
                rejected_reason="extrusion_error",
                error_type=type(exc).__name__,
            )
            failed_attempts.append(diagnostics)

    candidate: _Polygonal | None = poly
    for attempt in range(1 + len(VECTOR_RING_SEPARATION_RETRY_MM)):
        attempt_name = "original"
        if attempt:
            separation = VECTOR_RING_SEPARATION_RETRY_MM[attempt - 1]
            attempt_name = f"repair_{separation:g}_mm"
            try:
                candidate = _repair_polygon_ring_contacts(
                    poly, scale, separation
                )
                repaired_area = (
                    _physical_area(candidate, scale)
                    if candidate is not None else None
                )
            except _RECOVERABLE_EXPORT_ERRORS as exc:
                diagnostics = _attempt_geometry_metrics(
                    attempt_name, poly, scale, original_area
                )
                diagnostics.update(
                    rejected_reason="repair_error",
                    error_type=type(exc).__name__,
                )
                failed_attempts.append(diagnostics)
                continue
            if (
                candidate is None or not candidate.is_valid or candidate.is_empty
                or repaired_area is None
                or not _coverage_is_safe(original_area, repaired_area)
            ):
                diagnostics = _attempt_geometry_metrics(
                    attempt_name,
                    candidate if candidate is not None else poly,
                    scale,
                    original_area,
                )
                if candidate is None:
                    rejected_reason = "repair_failed"
                elif candidate.is_empty:
                    rejected_reason = "repair_empty"
                elif not candidate.is_valid:
                    rejected_reason = "repair_invalid"
                elif repaired_area is None:
                    rejected_reason = "repair_area_unavailable"
                else:
                    rejected_reason = "repair_coverage_mismatch"
                diagnostics["candidate_area_mm2"] = repaired_area
                diagnostics["area_delta_mm2"] = (
                    abs(repaired_area - original_area)
                    if repaired_area is not None else None
                )
                diagnostics["rejected_reason"] = rejected_reason
                failed_attempts.append(diagnostics)
                continue
        try:
            meshes = _extrude_indexed_parts(candidate)
            mesh_diagnostics = {}
            if _meshes_are_export_safe(
                meshes,
                scale,
                expected_area_mm2=original_area,
                rejection_metrics=mesh_diagnostics,
            ):
                return meshes
            diagnostics = _attempt_geometry_metrics(
                attempt_name, candidate, scale, original_area
            )
            diagnostics.update(mesh_diagnostics)
            failed_attempts.append(diagnostics)
        except _RECOVERABLE_EXPORT_ERRORS as exc:
            diagnostics = _attempt_geometry_metrics(
                attempt_name, candidate, scale, original_area
            )
            diagnostics.update(
                rejected_reason="extrusion_error",
                error_type=type(exc).__name__,
            )
            failed_attempts.append(diagnostics)
            continue

    message = "Vector polygon topology could not be repaired for export"
    error = VectorTopologyError(message, tuple(failed_attempts))
    raise error from None
