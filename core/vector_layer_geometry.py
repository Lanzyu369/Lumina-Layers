"""Canonical physical-grid geometry for native Vector layer runs.

Native SVG coordinates are converted to millimetres and noded on one shared
integer grid before any 3D allocation.  This makes shared boundaries identical
by construction and keeps independent printable islands explicit.

原生 SVG 坐标在分配三维网格前统一转换为毫米，并在共享整数网格上节点化；
因此共享边天然一致，独立可打印小岛也不会被静默丢弃。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Sequence

import numpy as np
import shapely
import trimesh
from mapbox_earcut import triangulate_float64
from shapely import STRtree, affinity, set_precision
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union
from shapely.validation import make_valid


@dataclass(frozen=True)
class VectorLayerGeometryPolicy:
    """Physical-grid and fidelity policy for one Vector run group.
    单个 Vector 走层组的物理网格与保真策略。
    """

    grid_mm: float = 0.0001
    simplify_tolerance_mm: float = 0.005
    coverage_relative_tolerance: float = 1e-6
    coverage_absolute_tolerance_mm2: float = 0.01


@dataclass(frozen=True)
class PreparedVectorPolygon:
    """One canonical polygon stored only as compact integer rings.
    仅用紧凑整数环保存的单个规范多边形。
    """

    exterior_units: np.ndarray
    hole_units: tuple[np.ndarray, ...]
    source_indices: tuple[int, ...]

    def to_geometry(self, grid_mm: float) -> Polygon:
        """Materialize a Shapely polygon in millimetres on demand.
        按需还原毫米单位的 Shapely 多边形。
        """

        exterior = self.exterior_units.astype(np.float64) * float(grid_mm)
        holes = [
            ring.astype(np.float64) * float(grid_mm)
            for ring in self.hole_units
        ]
        return Polygon(exterior, holes)


@dataclass(frozen=True)
class VectorLayerGeometryStats:
    """Structural and coverage counters for canonical preparation.
    规范化准备的结构与覆盖统计。
    """

    source_geometry_count: int
    source_polygon_count: int
    source_component_count: int
    source_hole_count: int
    source_area_mm2: float
    output_component_count: int
    output_hole_count: int
    output_area_mm2: float
    input_coordinate_count: int
    output_coordinate_count: int
    integer_coordinate_bytes: int
    spatial_group_count: int
    simplified_group_count: int
    restored_group_count: int
    separated_contact_group_count: int


@dataclass(frozen=True)
class PreparedVectorRunGroup:
    """Canonical printable polygons for one material/layer run.
    单个材料走层的规范可打印多边形集合。
    """

    polygons: tuple[PreparedVectorPolygon, ...]
    grid_mm: float
    stats: VectorLayerGeometryStats

    def to_geometry(self) -> Polygon | MultiPolygon:
        """Materialize the full millimetre geometry for compatibility checks.
        为兼容性检查按需还原完整毫米几何。
        """

        geometries = [polygon.to_geometry(self.grid_mm) for polygon in self.polygons]
        if len(geometries) == 1:
            return geometries[0]
        return MultiPolygon(geometries)


@dataclass(frozen=True)
class _PhysicalPart:
    source_index: int
    geometry: Polygon


def _polygon_parts(geometry: BaseGeometry) -> tuple[Polygon, ...]:
    """Return printable polygon parts, ignoring zero-area collection residue."""

    if isinstance(geometry, GeometryCollection):
        parts = tuple(
            polygon
            for item in geometry.geoms
            if isinstance(item, (Polygon, MultiPolygon))
            for polygon in _polygon_parts(item)
        )
        if not parts:
            raise ValueError("Vector run group requires polygonal geometry")
        return parts
    if not isinstance(geometry, (Polygon, MultiPolygon)):
        raise ValueError("Vector run group requires polygonal geometry")
    candidate = make_valid(geometry) if not geometry.is_valid else geometry
    if isinstance(candidate, Polygon):
        parts = (candidate,)
    elif isinstance(candidate, MultiPolygon):
        parts = tuple(candidate.geoms)
    else:
        raise ValueError("Vector run group requires repairable polygonal geometry")
    if not parts or any(part.is_empty or float(part.area) <= 0.0 for part in parts):
        raise ValueError("Vector run group contains empty polygonal geometry")
    return parts


def _coordinate_count(geometry: Polygon) -> int:
    return len(geometry.exterior.coords) - 1 + sum(
        len(ring.coords) - 1 for ring in geometry.interiors
    )


def _topology_signature(geometry: BaseGeometry) -> tuple[int, int]:
    parts = _polygon_parts(geometry)
    return len(parts), sum(len(part.interiors) for part in parts)


def _coverage_is_complete(
    expected_area_mm2: float,
    actual_area_mm2: float,
    policy: VectorLayerGeometryPolicy,
) -> bool:
    tolerance = max(
        float(policy.coverage_absolute_tolerance_mm2),
        expected_area_mm2 * float(policy.coverage_relative_tolerance),
    )
    return actual_area_mm2 + tolerance >= expected_area_mm2


def _nearby_groups(
    parts: list[_PhysicalPart],
    *,
    distance_mm: float,
) -> list[list[int]]:
    """Partition source parts by overlap/touch/sub-grid proximity."""

    geometries = [part.geometry for part in parts]
    tree = STRtree(geometries)
    parents = np.arange(len(parts), dtype=np.int64)
    ranks = np.zeros(len(parts), dtype=np.uint8)

    def find(index: int) -> int:
        while int(parents[index]) != index:
            parents[index] = parents[int(parents[index])]
            index = int(parents[index])
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        if ranks[first_root] < ranks[second_root]:
            parents[first_root] = second_root
        elif ranks[first_root] > ranks[second_root]:
            parents[second_root] = first_root
        else:
            parents[second_root] = first_root
            ranks[first_root] += 1

    for first_index, geometry in enumerate(geometries):
        nearby = tree.query(
            geometry,
            predicate="dwithin",
            distance=float(distance_mm),
        )
        for raw_second_index in np.asarray(nearby).reshape(-1):
            second_index = int(raw_second_index)
            if second_index > first_index:
                union(first_index, second_index)

    grouped: dict[int, list[int]] = {}
    for index in range(len(parts)):
        grouped.setdefault(find(index), []).append(index)
    return sorted(grouped.values(), key=lambda group: group[0])


def _snapped_parts(
    parts: list[_PhysicalPart],
    indices: list[int],
    *,
    grid_mm: float,
) -> list[tuple[int, Polygon]]:
    result: list[tuple[int, Polygon]] = []
    for part_index in indices:
        part = parts[part_index]
        snapped = set_precision(
            part.geometry,
            grid_size=float(grid_mm),
            mode="valid_output",
        )
        if snapped is None or snapped.is_empty:
            raise ValueError(
                "Vector physical-grid conversion removed a source polygon"
            )
        for polygon in _polygon_parts(snapped):
            result.append((part.source_index, polygon))
    return result


def _node_group_once(snapped: list[tuple[int, Polygon]]) -> BaseGeometry:
    """Node all shared boundaries once and select occupied arrangement cells."""

    boundaries = [polygon.boundary for _source_index, polygon in snapped]
    noded = unary_union(boundaries)
    cells = list(polygonize(noded))
    accepted = []
    source_polygons = [polygon for _source_index, polygon in snapped]
    source_tree = STRtree(source_polygons)
    for cell in cells:
        point = cell.representative_point()
        nearby = source_tree.query(point, predicate="covered_by")
        if len(nearby) > 0:
            accepted.append(cell)
    if not accepted:
        raise ValueError("Vector physical-grid noding produced no printable cells")
    return unary_union(accepted)


def _has_cross_polygon_contact(geometry: BaseGeometry) -> bool:
    if not isinstance(geometry, MultiPolygon):
        return False
    parts = list(geometry.geoms)
    tree = STRtree(parts)
    for first_index, part in enumerate(parts):
        nearby = tree.query(part, predicate="intersects")
        if any(int(index) > first_index for index in np.asarray(nearby).reshape(-1)):
            return True
    return False


def _contact_free_translation_candidates(
    geometry: Polygon,
    contacts: Sequence[Polygon],
    *,
    grid_mm: float,
) -> list[tuple[float, float]]:
    """Order small grid translations away from already accepted contacts."""

    contact_x = math.fsum(float(item.centroid.x) for item in contacts) / len(contacts)
    contact_y = math.fsum(float(item.centroid.y) for item in contacts) / len(contacts)
    delta_x = float(geometry.centroid.x) - contact_x
    delta_y = float(geometry.centroid.y) - contact_y
    sign_x = 1 if delta_x >= 0.0 else -1
    sign_y = 1 if delta_y >= 0.0 else -1
    preferred = [
        (sign_x, sign_y),
        (sign_x, 0),
        (0, sign_y),
    ]
    all_directions = preferred + [
        (1, 0),
        (-1, 0),
        (0, 1),
        (0, -1),
        (1, 1),
        (1, -1),
        (-1, 1),
        (-1, -1),
    ]
    unique_directions = list(dict.fromkeys(all_directions))
    return [
        (float(dx * radius) * grid_mm, float(dy * radius) * grid_mm)
        for radius in range(1, 5)
        for dx, dy in unique_directions
    ]


def _separate_unrepresentable_contacts(
    geometry: BaseGeometry,
    *,
    grid_mm: float,
) -> tuple[BaseGeometry, bool]:
    """Move touching independent shells apart on the same physical grid."""

    if not _has_cross_polygon_contact(geometry):
        return geometry, False

    ordered_parts = sorted(
        geometry.geoms,
        key=lambda part: (-float(part.area), *part.bounds),
    )
    accepted: list[Polygon] = []
    for part in ordered_parts:
        contacts = [other for other in accepted if part.intersects(other)]
        if not contacts:
            accepted.append(part)
            continue
        separated = None
        for x_offset, y_offset in _contact_free_translation_candidates(
            part,
            contacts,
            grid_mm=float(grid_mm),
        ):
            candidate = affinity.translate(part, xoff=x_offset, yoff=y_offset)
            if not any(candidate.intersects(other) for other in accepted):
                separated = candidate
                break
        if separated is None:
            raise ValueError(
                "Vector float32-near contacts could not remain independent"
            )
        accepted.append(separated)

    result: BaseGeometry = (
        accepted[0] if len(accepted) == 1 else MultiPolygon(accepted)
    )
    if result.is_empty or not result.is_valid or _has_cross_polygon_contact(result):
        raise ValueError("Vector physical-grid output retains touching shells")
    if geometry.hausdorff_distance(result) > float(grid_mm) * 6.0:
        raise ValueError("Vector contact separation exceeded the physical-grid bound")
    return result, True


def _simplify_or_restore(
    geometry: BaseGeometry,
    *,
    expected_area_mm2: float,
    policy: VectorLayerGeometryPolicy,
) -> tuple[BaseGeometry, bool, bool]:
    tolerance = float(policy.simplify_tolerance_mm)
    if tolerance <= 0.0:
        return geometry, False, False
    original_signature = _topology_signature(geometry)
    original_coordinates = sum(_coordinate_count(part) for part in _polygon_parts(geometry))
    simplified = geometry.simplify(tolerance, preserve_topology=True)
    simplified = set_precision(
        simplified,
        grid_size=float(policy.grid_mm),
        mode="valid_output",
    )
    if simplified is None or simplified.is_empty or not simplified.is_valid:
        return geometry, False, True
    simplified, _separated = _separate_unrepresentable_contacts(
        simplified,
        grid_mm=float(policy.grid_mm),
    )
    simplified_coordinates = sum(
        _coordinate_count(part) for part in _polygon_parts(simplified)
    )
    accepted = (
        _topology_signature(simplified) == original_signature
        and _coverage_is_complete(
            expected_area_mm2,
            float(simplified.area),
            policy,
        )
        and geometry.hausdorff_distance(simplified)
        <= tolerance + float(policy.grid_mm) * math.sqrt(2.0)
    )
    if not accepted:
        return geometry, False, True
    return simplified, simplified_coordinates < original_coordinates, False


def _ring_units(coordinates, *, grid_mm: float) -> np.ndarray:
    values = np.asarray(coordinates, dtype=np.float64)
    if len(values) > 1 and np.array_equal(values[0], values[-1]):
        values = values[:-1]
    units = np.rint(values / float(grid_mm)).astype(np.int64)
    if len(units) > 1:
        keep = np.ones(len(units), dtype=bool)
        keep[1:] = np.any(units[1:] != units[:-1], axis=1)
        units = units[keep]
    if len(units) > 1 and np.array_equal(units[0], units[-1]):
        units = units[:-1]
    while len(units) > 3:
        previous = np.roll(units, 1, axis=0)
        following = np.roll(units, -1, axis=0)
        incoming = units - previous
        outgoing = following - units
        collinear = (
            incoming[:, 0] * outgoing[:, 1]
            - incoming[:, 1] * outgoing[:, 0]
        ) == 0
        forward = np.einsum("ij,ij->i", incoming, outgoing) >= 0
        removable = collinear & forward
        if not bool(np.any(removable)) or bool(np.all(removable)):
            break
        units = units[~removable]
    if len(units) < 3:
        raise ValueError("Vector physical-grid ring collapsed below three points")
    units = np.ascontiguousarray(units)
    units.setflags(write=False)
    return units


def _writer_safe_grid_mm(parts: Sequence[_PhysicalPart], minimum_mm: float) -> float:
    """Choose a grid whose adjacent coordinates remain distinct in float32."""

    maximum_abs_coordinate = max(
        max(abs(float(value)) for value in part.geometry.bounds)
        for part in parts
    )
    writer_value = np.float32(maximum_abs_coordinate)
    writer_ulp = abs(float(np.spacing(writer_value)))
    if not math.isfinite(writer_ulp):
        raise ValueError("Vector physical coordinates exceed float32 writer range")
    return max(float(minimum_mm), writer_ulp * 4.0)


def _prepared_polygons(
    geometry: BaseGeometry,
    *,
    grid_mm: float,
    source_parts: list[_PhysicalPart],
    group_indices: list[int],
) -> list[PreparedVectorPolygon]:
    prepared = []
    source_geometries = [source_parts[index].geometry for index in group_indices]
    source_indices = [source_parts[index].source_index for index in group_indices]
    for raw_polygon in _polygon_parts(geometry):
        polygon = orient(raw_polygon, sign=1.0)
        owners = sorted(
            {
                source_index
                for source_index, source_geometry in zip(
                    source_indices,
                    source_geometries,
                )
                if float(polygon.intersection(source_geometry).area) > 0.0
            }
        )
        if not owners:
            raise ValueError("Vector canonical polygon lost its source ownership")
        prepared.append(
            PreparedVectorPolygon(
                exterior_units=_ring_units(
                    polygon.exterior.coords,
                    grid_mm=grid_mm,
                ),
                hole_units=tuple(
                    _ring_units(ring.coords, grid_mm=grid_mm)
                    for ring in polygon.interiors
                ),
                source_indices=tuple(owners),
            )
        )
    return prepared


def prepare_vector_run_group(
    geometries: Sequence[BaseGeometry],
    *,
    scale_mm_per_svg_unit: float,
    policy: VectorLayerGeometryPolicy | None = None,
) -> PreparedVectorRunGroup:
    """Prepare edge-matched printable coverage in physical millimetres.
    在物理毫米坐标中准备共享边完全一致的可打印覆盖。

    The function is all-or-nothing: every supplied polygon participates in a
    canonical spatial group, or a ``ValueError`` is raised before any 3D mesh
    is returned. / 本函数采用全有或全无语义：所有输入多边形都必须进入规范
    空间组，否则在返回任何三维网格前抛出 ``ValueError``。
    """

    effective_policy = policy or VectorLayerGeometryPolicy()
    scale = float(scale_mm_per_svg_unit)
    minimum_grid_mm = float(effective_policy.grid_mm)
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("Vector physical scale must be positive finite")
    if not math.isfinite(minimum_grid_mm) or minimum_grid_mm <= 0.0:
        raise ValueError("Vector physical grid must be positive finite")
    if not geometries:
        raise ValueError("Vector run group requires polygonal geometry")

    physical_parts: list[_PhysicalPart] = []
    input_coordinate_count = 0
    for source_index, geometry in enumerate(geometries):
        if geometry is None:
            raise ValueError("Vector run group requires polygonal geometry")
        for part in _polygon_parts(geometry):
            physical = affinity.scale(
                part,
                xfact=scale,
                yfact=scale,
                origin=(0.0, 0.0),
            )
            physical_parts.append(
                _PhysicalPart(source_index=source_index, geometry=physical)
            )
            input_coordinate_count += _coordinate_count(part)

    grid_mm = _writer_safe_grid_mm(physical_parts, minimum_grid_mm)
    effective_policy = replace(effective_policy, grid_mm=grid_mm)

    spatial_groups = _nearby_groups(
        physical_parts,
        distance_mm=grid_mm,
    )
    output: list[PreparedVectorPolygon] = []
    source_area_mm2 = 0.0
    source_component_count = 0
    source_hole_count = 0
    simplified_group_count = 0
    restored_group_count = 0
    separated_contact_group_count = 0

    for group_indices in spatial_groups:
        source_union = unary_union(
            [physical_parts[index].geometry for index in group_indices]
        )
        source_signature = _topology_signature(source_union)
        source_area = float(source_union.area)
        source_area_mm2 += source_area
        source_component_count += source_signature[0]
        source_hole_count += source_signature[1]

        snapped = _snapped_parts(
            physical_parts,
            group_indices,
            grid_mm=grid_mm,
        )
        if not snapped:
            raise ValueError("Vector physical-grid conversion removed a source group")
        canonical = _node_group_once(snapped)
        canonical, separated = _separate_unrepresentable_contacts(
            canonical,
            grid_mm=grid_mm,
        )
        if separated:
            separated_contact_group_count += 1
        if not _coverage_is_complete(source_area, float(canonical.area), effective_policy):
            raise ValueError("Vector physical-grid conversion lost printable coverage")

        canonical, simplified, restored = _simplify_or_restore(
            canonical,
            expected_area_mm2=source_area,
            policy=effective_policy,
        )
        simplified_group_count += int(simplified)
        restored_group_count += int(restored)
        output.extend(
            _prepared_polygons(
                canonical,
                grid_mm=grid_mm,
                source_parts=physical_parts,
                group_indices=group_indices,
            )
        )

    if not output:
        raise ValueError("Vector canonical preparation produced no polygons")
    output.sort(
        key=lambda polygon: (
            int(polygon.exterior_units[:, 0].min()),
            int(polygon.exterior_units[:, 1].min()),
            int(polygon.exterior_units[:, 0].max()),
            int(polygon.exterior_units[:, 1].max()),
        )
    )
    output_geometry = (
        output[0].to_geometry(grid_mm)
        if len(output) == 1
        else MultiPolygon([polygon.to_geometry(grid_mm) for polygon in output])
    )
    output_coordinate_count = sum(
        len(polygon.exterior_units)
        + sum(len(hole) for hole in polygon.hole_units)
        for polygon in output
    )
    integer_coordinate_bytes = sum(
        polygon.exterior_units.nbytes
        + sum(hole.nbytes for hole in polygon.hole_units)
        for polygon in output
    )
    stats = VectorLayerGeometryStats(
        source_geometry_count=len(geometries),
        source_polygon_count=len(physical_parts),
        source_component_count=source_component_count,
        source_hole_count=source_hole_count,
        source_area_mm2=source_area_mm2,
        output_component_count=len(output),
        output_hole_count=sum(len(polygon.hole_units) for polygon in output),
        output_area_mm2=float(output_geometry.area),
        input_coordinate_count=input_coordinate_count,
        output_coordinate_count=output_coordinate_count,
        integer_coordinate_bytes=integer_coordinate_bytes,
        spatial_group_count=len(spatial_groups),
        simplified_group_count=simplified_group_count,
        restored_group_count=restored_group_count,
        separated_contact_group_count=separated_contact_group_count,
    )
    if not _coverage_is_complete(
        source_area_mm2,
        stats.output_area_mm2,
        effective_policy,
    ):
        raise ValueError("Vector canonical preparation lost aggregate printable coverage")
    return PreparedVectorRunGroup(
        polygons=tuple(output),
        grid_mm=grid_mm,
        stats=stats,
    )


def _signed_twice_ring_area(coordinates: np.ndarray) -> float:
    values = np.asarray(coordinates, dtype=np.float64)
    return float(
        np.sum(
            values[:, 0] * np.roll(values[:, 1], -1)
            - values[:, 1] * np.roll(values[:, 0], -1),
            dtype=np.float64,
        )
    )


def _oriented_polygon_rings(polygon: PreparedVectorPolygon) -> list[np.ndarray]:
    rings = [polygon.exterior_units, *polygon.hole_units]
    oriented_rings: list[np.ndarray] = []
    for index, ring in enumerate(rings):
        signed_area = _signed_twice_ring_area(ring)
        if signed_area == 0.0 or not math.isfinite(signed_area):
            raise ValueError("Vector canonical ring has zero signed area")
        should_be_positive = index == 0
        if (signed_area > 0.0) != should_be_positive:
            oriented_rings.append(np.ascontiguousarray(ring[::-1]))
        else:
            oriented_rings.append(ring)
    return oriented_rings


def _validate_cap_indices(
    vertices_2d: np.ndarray,
    cap_faces: np.ndarray,
    ring_ends: np.ndarray,
    *,
    expected_area_mm2: float,
) -> np.ndarray:
    """Orient and validate one Earcut cap without building a 3D fallback."""

    faces = np.asarray(cap_faces, dtype=np.int64).reshape((-1, 3))
    if len(faces) == 0 or np.any(faces < 0) or np.any(faces >= len(vertices_2d)):
        raise ValueError("Vector canonical cap triangulation has invalid indices")
    if np.any(
        (faces[:, 0] == faces[:, 1])
        | (faces[:, 1] == faces[:, 2])
        | (faces[:, 2] == faces[:, 0])
    ):
        raise ValueError("Vector canonical cap triangulation is index-degenerate")

    triangles = vertices_2d[faces]
    signed_twice_area = (
        (triangles[:, 1, 0] - triangles[:, 0, 0])
        * (triangles[:, 2, 1] - triangles[:, 0, 1])
        - (triangles[:, 1, 1] - triangles[:, 0, 1])
        * (triangles[:, 2, 0] - triangles[:, 0, 0])
    )
    if np.any(signed_twice_area == 0.0):
        raise ValueError("Vector canonical cap triangulation is coordinate-degenerate")
    reversed_faces = signed_twice_area < 0.0
    if bool(np.any(reversed_faces)):
        faces[reversed_faces] = faces[reversed_faces][:, [0, 2, 1]]
        signed_twice_area[reversed_faces] *= -1.0

    cap_area = math.fsum(float(value) for value in signed_twice_area) * 0.5
    area_tolerance = max(1e-9, expected_area_mm2 * 1e-9)
    if abs(cap_area - expected_area_mm2) > area_tolerance:
        raise ValueError("Vector canonical cap triangulation changed coverage")

    cap_edges = np.sort(
        faces[:, [[0, 1], [1, 2], [2, 0]]].reshape((-1, 2)),
        axis=1,
    )
    unique_edges, counts = np.unique(cap_edges, axis=0, return_counts=True)
    if np.any((counts != 1) & (counts != 2)):
        raise ValueError("Vector canonical cap has non-manifold edge incidence")
    cap_boundary = unique_edges[counts == 1]

    ring_starts = np.concatenate((np.asarray([0]), ring_ends[:-1])).astype(np.int64)
    boundary_chunks = []
    for ring_start, ring_end in zip(ring_starts, ring_ends.astype(np.int64)):
        indices = np.arange(int(ring_start), int(ring_end), dtype=np.int64)
        boundary_chunks.append(
            np.sort(np.column_stack((indices, np.roll(indices, -1))), axis=1)
        )
    expected_boundary = np.vstack(boundary_chunks)
    if not np.array_equal(
        cap_boundary[np.lexsort((cap_boundary[:, 1], cap_boundary[:, 0]))],
        expected_boundary[
            np.lexsort((expected_boundary[:, 1], expected_boundary[:, 0]))
        ],
    ):
        raise ValueError("Vector canonical cap boundary differs from its rings")
    return faces


def _canonical_cap_faces(
    polygon: PreparedVectorPolygon,
    vertices_2d: np.ndarray,
    ring_ends: np.ndarray,
    *,
    grid_mm: float,
) -> np.ndarray:
    """Triangulate canonical rings with a topology-appropriate kernel."""

    if not polygon.hole_units:
        return triangulate_float64(vertices_2d, ring_ends)

    polygon_geometry = polygon.to_geometry(grid_mm)
    triangles = shapely.constrained_delaunay_triangles(polygon_geometry)
    triangle_parts = shapely.get_parts(triangles)
    coordinate_counts = np.asarray(
        shapely.get_num_coordinates(triangle_parts),
        dtype=np.int64,
    )
    if len(coordinate_counts) == 0 or np.any(coordinate_counts != 4):
        raise ValueError("Vector constrained cap did not produce triangles")
    triangle_coordinates = np.asarray(
        shapely.get_coordinates(triangle_parts),
        dtype=np.float64,
    ).reshape((-1, 4, 2))[:, :3, :]

    canonical_units = np.rint(vertices_2d / float(grid_mm)).astype(np.int64)
    triangle_units = np.rint(
        triangle_coordinates.reshape((-1, 2)) / float(grid_mm)
    ).astype(np.int64)
    key_dtype = np.dtype([("x", np.int64), ("y", np.int64)])
    canonical_keys = np.ascontiguousarray(canonical_units).view(key_dtype).reshape(-1)
    triangle_keys = np.ascontiguousarray(triangle_units).view(key_dtype).reshape(-1)
    order = np.argsort(canonical_keys, kind="quicksort")
    sorted_keys = canonical_keys[order]
    positions = np.searchsorted(sorted_keys, triangle_keys)
    if (
        np.any(positions >= len(sorted_keys))
        or not np.array_equal(sorted_keys[positions], triangle_keys)
    ):
        raise ValueError("Vector constrained cap introduced a non-ring vertex")
    return order[positions].reshape((-1, 3))


def extrude_prepared_vector_run_group(
    prepared: PreparedVectorRunGroup,
    *,
    height_mm: float,
    z_offset_mm: float,
) -> trimesh.Trimesh:
    """Build one closed indexed prism mesh from canonical physical rings.
    从规范物理坐标环直接构建一个闭合索引棱柱网格。

    Caps and walls share the exact same ring indices. No geometric repair or
    alternate 3D fallback is attempted after this point. / 顶底面与侧壁复用
    完全相同的环索引；进入本步骤后不再尝试几何修补或备用三维路径。
    """

    height = float(height_mm)
    z_offset = float(z_offset_mm)
    if not math.isfinite(height) or height <= 0.0:
        raise ValueError("Vector prism height must be positive finite")
    if not math.isfinite(z_offset):
        raise ValueError("Vector prism Z offset must be finite")
    if not prepared.polygons:
        raise ValueError("Vector prism requires canonical polygons")
    if np.float32(z_offset) == np.float32(z_offset + height):
        raise ValueError("Vector prism height collapses in float32 writer space")

    polygon_rings = [_oriented_polygon_rings(polygon) for polygon in prepared.polygons]
    ring_vertex_counts = [
        sum(len(ring) for ring in rings) for rings in polygon_rings
    ]
    cap_face_counts = [
        vertex_count + 2 * (len(rings) - 1) - 2
        for vertex_count, rings in zip(ring_vertex_counts, polygon_rings)
    ]
    vertex_count = 2 * sum(ring_vertex_counts)
    face_count = sum(
        2 * cap_face_count + 2 * ring_vertex_count
        for cap_face_count, ring_vertex_count in zip(
            cap_face_counts,
            ring_vertex_counts,
        )
    )
    if vertex_count > np.iinfo(np.uint32).max:
        raise ValueError("Vector canonical mesh exceeds uint32 vertex indices")

    vertices = np.empty((vertex_count, 3), dtype=np.float64)
    faces = np.empty((face_count, 3), dtype=np.int64)
    vertex_cursor = 0
    face_cursor = 0

    for polygon, rings, local_vertex_count, expected_cap_face_count in zip(
        prepared.polygons,
        polygon_rings,
        ring_vertex_counts,
        cap_face_counts,
    ):
        vertices_2d = np.vstack(rings).astype(np.float64)
        vertices_2d *= float(prepared.grid_mm)
        ring_ends = np.cumsum([len(ring) for ring in rings], dtype=np.uint32)
        raw_cap_faces = _canonical_cap_faces(
            polygon,
            vertices_2d,
            ring_ends,
            grid_mm=float(prepared.grid_mm),
        )
        expected_area = float(polygon.to_geometry(prepared.grid_mm).area)
        cap_faces = _validate_cap_indices(
            vertices_2d,
            raw_cap_faces,
            ring_ends,
            expected_area_mm2=expected_area,
        )
        if len(cap_faces) != expected_cap_face_count:
            raise ValueError("Vector canonical cap triangle count is inconsistent")

        bottom_start = vertex_cursor
        top_start = vertex_cursor + local_vertex_count
        vertices[bottom_start:top_start, :2] = vertices_2d
        vertices[bottom_start:top_start, 2] = z_offset
        vertices[top_start : top_start + local_vertex_count, :2] = vertices_2d
        vertices[top_start : top_start + local_vertex_count, 2] = z_offset + height

        cap_count = len(cap_faces)
        faces[face_cursor : face_cursor + cap_count] = (
            cap_faces[:, ::-1] + bottom_start
        )
        face_cursor += cap_count
        faces[face_cursor : face_cursor + cap_count] = cap_faces + top_start
        face_cursor += cap_count

        local_ring_start = 0
        for ring in rings:
            ring_indices = np.arange(
                local_ring_start,
                local_ring_start + len(ring),
                dtype=np.int64,
            )
            next_indices = np.roll(ring_indices, -1)
            side_count = len(ring) * 2
            faces[face_cursor : face_cursor + side_count : 2] = np.column_stack(
                (
                    bottom_start + ring_indices,
                    bottom_start + next_indices,
                    top_start + next_indices,
                )
            )
            faces[face_cursor + 1 : face_cursor + side_count : 2] = np.column_stack(
                (
                    bottom_start + ring_indices,
                    top_start + next_indices,
                    top_start + ring_indices,
                )
            )
            face_cursor += side_count
            local_ring_start += len(ring)
        vertex_cursor += local_vertex_count * 2

    if vertex_cursor != vertex_count or face_cursor != face_count:
        raise ValueError("Vector canonical mesh allocation count mismatch")

    writer_vertices = vertices.astype(np.float32)
    if not np.all(np.isfinite(writer_vertices)):
        raise ValueError("Vector canonical mesh exceeds float32 writer space")
    for start in range(0, len(faces), 65_536):
        triangles = writer_vertices[faces[start : start + 65_536]]
        cross = np.cross(
            triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 0],
        )
        if np.any(np.all(cross == 0.0, axis=1)):
            raise ValueError(
                "Vector canonical mesh contains a float32-degenerate triangle"
            )

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.metadata["_lumina_planar_coverage_mm2"] = float(
        prepared.stats.output_area_mm2
    )
    mesh.metadata["vector_layer_geometry"] = {
        **asdict(prepared.stats),
        "grid_mm": float(prepared.grid_mm),
        "mesh_vertex_count": int(vertex_count),
        "mesh_face_count": int(face_count),
        "mesh_array_bytes": int(vertices.nbytes + faces.nbytes),
    }
    return mesh


__all__ = [
    "PreparedVectorPolygon",
    "PreparedVectorRunGroup",
    "VectorLayerGeometryPolicy",
    "VectorLayerGeometryStats",
    "extrude_prepared_vector_run_group",
    "prepare_vector_run_group",
]
