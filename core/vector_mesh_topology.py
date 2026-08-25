"""Bounded topology preparation for vector mesh exports.

为矢量网格导出提供有界的拓扑准备与校验。
"""

from __future__ import annotations

import math

import numpy as np
import trimesh
from mapbox_earcut import triangulate_float64 as _triangulate_float64
from shapely import affinity as _affinity
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
    "prepare_component_footprints_for_float32",
    "separate_component_coordinates",
    "extrude_polygon_for_export",
]

_FLOAT32_GRID_MM = 0.0001
_FLOAT32_MAX = float(np.finfo(np.float32).max)
_SMALL_MESH_FACE_LIMIT = 64
_COMPONENT_PAIR_LIMIT = 250_000
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


def _writer_mesh_vertices(
    vertices: np.ndarray,
    scale: float,
) -> np.ndarray | None:
    """Map mesh vertices exactly into the float32 coordinates written to 3MF."""

    writer_vertices = np.empty(vertices.shape, dtype=np.float32)
    with np.errstate(over="ignore", invalid="ignore"):
        writer_vertices[:, :2] = vertices[:, :2] * scale
        writer_vertices[:, 2] = vertices[:, 2]
    if not np.all(np.isfinite(writer_vertices)):
        return None
    return writer_vertices


def _trace_boundary_loops(boundary: np.ndarray) -> list[list[int]] | None:
    """Trace consistently oriented cap boundary edges into closed loops."""

    outgoing: dict[int, int] = {}
    incoming: set[int] = set()
    for raw_start, raw_end in boundary:
        start, end = int(raw_start), int(raw_end)
        if start == end or start in outgoing or end in incoming:
            return None
        outgoing[start] = end
        incoming.add(end)
    if set(outgoing) != incoming:
        return None

    loops: list[list[int]] = []
    remaining = set(outgoing)
    while remaining:
        start = min(remaining)
        loop = [start]
        current = start
        while True:
            next_index = outgoing.get(current)
            if next_index is None:
                return None
            if next_index == start:
                break
            if next_index not in remaining:
                return None
            loop.append(next_index)
            current = next_index
        if len(loop) < 3:
            return None
        remaining.difference_update(loop)
        loops.append(loop)
    return loops


def _vertical_prism_profile(
    mapped_vertices: np.ndarray,
    faces: np.ndarray,
) -> tuple[_Polygon, float, float] | None:
    """Recover one vertical prism's footprint from indexed cap boundaries."""

    if (
        faces.ndim != 2
        or faces.shape[1:] != (3,)
        or len(faces) == 0
        or np.any(faces < 0)
        or np.any(faces >= len(mapped_vertices))
    ):
        return None
    used = np.unique(faces.reshape(-1))
    component_vertices = mapped_vertices[used]
    z_values = np.unique(component_vertices[:, 2])
    if len(z_values) != 2:
        return None
    z_min, z_max = float(z_values[0]), float(z_values[1])
    if not z_min < z_max:
        return None

    bottom_xy = {
        tuple(row)
        for row in component_vertices[component_vertices[:, 2] == z_values[0], :2]
    }
    top_xy = {
        tuple(row)
        for row in component_vertices[component_vertices[:, 2] == z_values[1], :2]
    }
    if not bottom_xy or bottom_xy != top_xy:
        return None

    face_z = mapped_vertices[faces, 2]
    bottom_faces = faces[np.all(face_z == z_values[0], axis=1)]
    top_faces = faces[np.all(face_z == z_values[1], axis=1)]
    if len(bottom_faces) == 0 or len(top_faces) == 0:
        return None
    oriented_edges = np.vstack(
        (
            bottom_faces[:, [0, 1]],
            bottom_faces[:, [1, 2]],
            bottom_faces[:, [2, 0]],
        )
    )
    sorted_edges = np.sort(oriented_edges, axis=1)
    _edges, inverse, counts = np.unique(
        sorted_edges,
        axis=0,
        return_inverse=True,
        return_counts=True,
    )
    if np.any(counts > 2):
        return None
    boundary = oriented_edges[counts[inverse] == 1]
    loops = _trace_boundary_loops(boundary)
    if not loops:
        return None

    loop_coordinates = [
        mapped_vertices[np.asarray(loop, dtype=np.int64), :2].astype(np.float64)
        for loop in loops
    ]
    twice_areas = [
        float(
            np.sum(
                coordinates[:, 0] * np.roll(coordinates[:, 1], -1)
                - coordinates[:, 1] * np.roll(coordinates[:, 0], -1)
            )
        )
        for coordinates in loop_coordinates
    ]
    if any(area == 0.0 or not math.isfinite(area) for area in twice_areas):
        return None
    exterior_index = int(np.argmax(np.abs(twice_areas)))
    exterior = loop_coordinates[exterior_index]
    holes = [
        coordinates
        for index, coordinates in enumerate(loop_coordinates)
        if index != exterior_index
    ]
    try:
        footprint = _Polygon(exterior, holes)
    except _GEOMETRY_ERRORS:
        return None
    if (
        footprint.is_empty
        or not footprint.is_valid
        or not math.isfinite(float(footprint.area))
        or float(footprint.area) <= 0.0
    ):
        return None
    return footprint, z_min, z_max


def _prism_profiles_are_disjoint(
    profiles: list[tuple[_Polygon, float, float]],
) -> bool:
    """Check XY contact only for prism pairs whose closed Z ranges overlap."""

    if len(profiles) < 2:
        return True
    footprints = [profile[0] for profile in profiles]
    try:
        tree = _STRtree(footprints)
    except _GEOMETRY_ERRORS:
        return False
    inspected_pairs = 0
    for first_index, footprint in enumerate(footprints):
        try:
            nearby = tree.query(footprint, predicate="intersects")
        except _GEOMETRY_ERRORS:
            return False
        first_z_min, first_z_max = profiles[first_index][1:]
        for raw_second_index in np.asarray(nearby).reshape(-1):
            second_index = int(raw_second_index)
            if second_index <= first_index:
                continue
            inspected_pairs += 1
            if inspected_pairs > _COMPONENT_PAIR_LIMIT:
                return False
            second_z_min, second_z_max = profiles[second_index][1:]
            if max(first_z_min, second_z_min) <= min(first_z_max, second_z_max):
                return False
    return True


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
        triangles = writer_vertices[faces].astype(np.float64)
        edge_a = triangles[:, 1] - triangles[:, 0]
        edge_b = triangles[:, 2] - triangles[:, 0]
        crosses = np.cross(edge_a, edge_b)
        safe = not np.any(np.all(crosses == 0.0, axis=1))
        reason = None if safe else "float32_degenerate_triangle"
        coverage = None
        if safe and measure_coverage:
            signed_volume_six = np.einsum(
                "ij,ij->i", triangles[:, 0], crosses
            ).sum(dtype=np.float64)
            coverage = abs(float(signed_volume_six)) / 6.0
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
            writer_vertices = _writer_mesh_vertices(vertices, scale)
            if writer_vertices is None:
                return False, None, "writer_coordinate_non_finite", None
            profiles: list[tuple[_Polygon, float, float]] = []
            for component in face_components:
                profile = _vertical_prism_profile(
                    writer_vertices,
                    faces[np.asarray(component, dtype=np.int64)],
                )
                if profile is None:
                    return False, None, "writer_component_not_vertical_prism", True
                profiles.append(profile)
            if not _prism_profiles_are_disjoint(profiles):
                return False, None, "writer_component_boundary_contact", True
        return True, coverage, None, True
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


def _writer_footprint(poly: _Polygon, scale: float) -> _Polygonal | None:
    """Map one source polygon through the exact float32 XY writer domain."""

    def writer_ring(ring: _LinearRing) -> np.ndarray | None:
        try:
            coordinates = np.asarray(ring.coords, dtype=np.float64)[:, :2]
        except (AttributeError, TypeError, ValueError):
            return None
        if len(coordinates) < 4 or not np.all(np.isfinite(coordinates)):
            return None
        with np.errstate(over="ignore", invalid="ignore"):
            writer_coordinates = (coordinates * scale).astype(np.float32)
        if not np.all(np.isfinite(writer_coordinates)):
            return None
        return writer_coordinates.astype(np.float64)

    exterior = writer_ring(poly.exterior)
    if exterior is None:
        return None
    holes: list[np.ndarray] = []
    for ring in poly.interiors:
        coordinates = writer_ring(ring)
        if coordinates is None:
            return None
        holes.append(coordinates)
    try:
        footprint = _Polygon(exterior, holes)
    except _GEOMETRY_ERRORS:
        return None
    if not footprint.is_valid:
        footprint = _normalise_polygonal(footprint)
        if footprint is None:
            return None
    if (
        footprint.is_empty
        or not math.isfinite(float(footprint.area))
        or float(footprint.area) <= 0.0
    ):
        return None
    return footprint


def _component_intersects_earlier(
    candidate: _Polygonal,
    *,
    index: int,
    original_tree: _STRtree,
    current_writer: list[_Polygonal],
    search_margin_mm: float,
    inspected_pairs: list[int],
) -> bool | None:
    """Check one candidate against accepted predecessors with bounded work."""

    try:
        search_geometry = candidate.buffer(
            search_margin_mm,
            cap_style="square",
            join_style="mitre",
        )
        nearby = original_tree.query(search_geometry)
    except _GEOMETRY_ERRORS:
        return None
    for raw_other_index in np.asarray(nearby).reshape(-1):
        other_index = int(raw_other_index)
        if other_index >= index:
            continue
        inspected_pairs[0] += 1
        if inspected_pairs[0] > _COMPONENT_PAIR_LIMIT:
            return None
        try:
            if candidate.intersects(current_writer[other_index]):
                return True
        except _GEOMETRY_ERRORS:
            return None
    return False


def _writer_footprints_are_disjoint(
    footprints: list[_Polygonal],
) -> bool:
    """Verify all final writer footprints without materialising all pairs."""

    if len(footprints) < 2:
        return True
    try:
        tree = _STRtree(footprints)
    except _GEOMETRY_ERRORS:
        return False
    inspected_pairs = 0
    for index, footprint in enumerate(footprints):
        try:
            nearby = tree.query(footprint, predicate="intersects")
        except _GEOMETRY_ERRORS:
            return False
        for raw_other_index in np.asarray(nearby).reshape(-1):
            other_index = int(raw_other_index)
            if other_index <= index:
                continue
            inspected_pairs += 1
            if inspected_pairs > _COMPONENT_PAIR_LIMIT:
                return False
            return False
    return True


def _prepare_component_footprints(
    polygons: list[_Polygon],
    *,
    scale: float,
    separation_mm: float,
) -> tuple[list[_Polygon], list[tuple[float, float]]] | None:
    """Return source polygons and source-space offsets safe for float32 IO."""

    if not polygons:
        return [], []
    if any(
        not isinstance(poly, _Polygon)
        or poly.is_empty
        or not poly.is_valid
        for poly in polygons
    ):
        return None
    if len(polygons) == 1:
        return [polygons[0]], [(0.0, 0.0)]

    original_writer: list[_Polygonal] = []
    expected_areas: list[float] = []
    for poly in polygons:
        expected_area = _physical_area(poly, scale)
        footprint = _writer_footprint(poly, scale)
        if (
            expected_area is None
            or footprint is None
            or not _coverage_is_safe(expected_area, float(footprint.area))
        ):
            return None
        expected_areas.append(expected_area)
        original_writer.append(footprint)
    try:
        original_tree = _STRtree(original_writer)
    except _GEOMETRY_ERRORS:
        return None

    geometry_step = separation_mm / scale
    offsets = (
        (0.0, 0.0),
        *((
            dx * geometry_step * step,
            dy * geometry_step * step,
        )
          for step in range(1, _COMPONENT_MAX_STEPS + 1)
          for dx, dy in _COMPONENT_DIRECTIONS),
    )
    max_writer_shift = (
        separation_mm * _COMPONENT_MAX_STEPS * math.sqrt(2.0)
    )
    prepared: list[_Polygon] = []
    current_writer: list[_Polygonal] = []
    selected_offsets: list[tuple[float, float]] = []
    inspected_pairs = [0]

    for index, poly in enumerate(polygons):
        accepted: tuple[_Polygon, _Polygonal, tuple[float, float]] | None = None
        for x_offset, y_offset in offsets:
            try:
                candidate = (
                    poly
                    if x_offset == 0.0 and y_offset == 0.0
                    else _affinity.translate(
                        poly,
                        xoff=float(x_offset),
                        yoff=float(y_offset),
                    )
                )
            except _GEOMETRY_ERRORS:
                continue
            writer_candidate = _writer_footprint(candidate, scale)
            if (
                writer_candidate is None
                or not _coverage_is_safe(
                    expected_areas[index],
                    float(writer_candidate.area),
                )
            ):
                continue
            intersects = _component_intersects_earlier(
                writer_candidate,
                index=index,
                original_tree=original_tree,
                current_writer=current_writer,
                search_margin_mm=max_writer_shift,
                inspected_pairs=inspected_pairs,
            )
            if intersects is None:
                return None
            if not intersects:
                accepted = (
                    candidate,
                    writer_candidate,
                    (float(x_offset), float(y_offset)),
                )
                break
        if accepted is None:
            return None
        candidate, writer_candidate, offset = accepted
        prepared.append(candidate)
        current_writer.append(writer_candidate)
        selected_offsets.append(offset)

    if not _writer_footprints_are_disjoint(current_writer):
        return None
    return prepared, selected_offsets


def prepare_component_footprints_for_float32(
    polygons: list[_Polygon],
    *,
    xy_scale: float,
    separation_mm: float = _FLOAT32_GRID_MM,
) -> list[_Polygon] | None:
    """Prepare independent prism footprints before extrusion.

    在挤出前把独立轮廓映射到 3MF 实际使用的 float32 坐标域；若两个
    壳体会因舍入而接触，则仅对后一个轮廓做有界的 0.0001 mm 级平移。

    Args:
        polygons: Independent source-space polygon footprints. /
            源坐标中的独立多边形轮廓。
        xy_scale: Source-coordinate to millimetre scale. /
            源坐标到毫米的缩放。
        separation_mm: Physical offset per bounded retry. /
            每次有界重试的物理偏移量。

    Returns:
        Prepared polygons, or ``None`` when they cannot be represented safely. /
        可安全写出的轮廓；无法安全表示时返回 ``None``。
    """

    scale = _positive_scale(xy_scale)
    separation = _positive_scale(separation_mm)
    if scale is None or separation is None:
        return None
    result = _prepare_component_footprints(
        list(polygons),
        scale=scale,
        separation_mm=separation,
    )
    return result[0] if result is not None else None


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
    if not meshes:
        return True

    vertices_by_mesh: list[np.ndarray] = []
    footprints: list[_Polygon] = []
    for mesh in meshes:
        arrays = _mesh_arrays(mesh)
        if arrays is None:
            return False
        vertices, faces = arrays
        if not np.all(np.isfinite(vertices)):
            return False
        profile = _vertical_prism_profile(vertices, faces)
        if profile is None:
            return False
        vertices_by_mesh.append(vertices)
        footprints.append(profile[0])

    prepared = _prepare_component_footprints(
        footprints,
        scale=scale,
        separation_mm=separation,
    )
    if prepared is None:
        return False
    _prepared_footprints, selected = prepared

    moved: list[tuple[trimesh.Trimesh, np.ndarray]] = []
    try:
        for mesh, vertices, offset in zip(meshes, vertices_by_mesh, selected):
            if offset != (0.0, 0.0):
                moved.append((mesh, vertices.copy()))
                mesh.apply_translation((offset[0], offset[1], 0.0))
        if not all(
            mesh_is_float32_safe(mesh, xy_scale=scale) for mesh in meshes
        ):
            raise ValueError("writer-domain component validation failed")
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
            candidate_parts = _polygon_parts(candidate)
            if not candidate_parts:
                raise ValueError(
                    "Vector polygon repair produced no extrudable parts"
                )
            prepared_parts = prepare_component_footprints_for_float32(
                candidate_parts,
                xy_scale=scale,
            )
            if prepared_parts is None:
                raise ValueError(
                    "Vector polygon components cannot remain separate in float32"
                )
            prepared_candidate: _Polygonal = (
                prepared_parts[0]
                if len(prepared_parts) == 1
                else _MultiPolygon(prepared_parts)
            )
            meshes = _extrude_indexed_parts(prepared_candidate)
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
