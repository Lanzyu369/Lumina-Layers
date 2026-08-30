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


_MAX_EXACT_SIMPLIFICATION_COORDINATES = 128
_MAX_CONTACT_TRANSLATION_GRID_UNITS = 4


@dataclass(frozen=True)
class VectorLayerGeometryPolicy:
    """Physical-grid and fidelity policy for one Vector run group.
    单个 Vector 走层组的物理网格与保真策略。
    """

    grid_mm: float = 0.0001
    simplify_tolerance_mm: float = 0.005
    coverage_relative_tolerance: float = 1e-6
    coverage_absolute_tolerance_mm2: float = 0.01


def resolve_vector_writer_grid_mm(
    maximum_abs_coordinate_mm: float,
    *,
    minimum_mm: float = VectorLayerGeometryPolicy().grid_mm,
) -> float:
    """Resolve the physical grid that remains distinct in float32 output.
    计算在 float32 写出域中仍能保持坐标可区分的物理网格。

    Args:
        maximum_abs_coordinate_mm: Largest absolute XY coordinate in mm.
            XY 坐标绝对值的毫米上限。
        minimum_mm: Minimum canonical grid size in mm.
            规范网格的最小毫米尺寸。

    Returns:
        Writer-safe canonical grid size in mm.
        写出安全的规范网格尺寸（毫米）。
    """

    maximum_coordinate = float(maximum_abs_coordinate_mm)
    minimum_grid = float(minimum_mm)
    if (
        not math.isfinite(maximum_coordinate)
        or maximum_coordinate < 0.0
        or not math.isfinite(minimum_grid)
        or minimum_grid <= 0.0
    ):
        raise ValueError("Vector writer grid inputs must be finite and positive")
    writer_value = np.float32(maximum_coordinate)
    writer_ulp = abs(float(np.spacing(writer_value)))
    if not math.isfinite(writer_ulp):
        raise ValueError("Vector physical coordinates exceed float32 writer range")
    return max(minimum_grid, writer_ulp * 4.0)


def snap_vector_writer_coordinate_mm(
    coordinate_mm: float,
    *,
    grid_mm: float,
) -> float:
    """Snap one coordinate with the same half-grid rule as GEOS.
    使用与 GEOS 相同的半网格规则对单个坐标取整。

    Args:
        coordinate_mm: Coordinate in physical millimetres.
            物理毫米坐标。
        grid_mm: Canonical writer grid size in millimetres.
            规范写出网格尺寸（毫米）。

    Returns:
        Coordinate snapped to the canonical writer grid.
        吸附到规范写出网格后的坐标。
    """

    coordinate = float(coordinate_mm)
    grid = float(grid_mm)
    if (
        not math.isfinite(coordinate)
        or not math.isfinite(grid)
        or grid <= 0.0
    ):
        raise ValueError("Vector writer coordinate inputs must be finite")
    scaled_coordinate = coordinate / grid
    if not math.isfinite(scaled_coordinate):
        raise ValueError("Vector writer coordinate exceeds canonical grid range")
    return float(math.floor(scaled_coordinate + 0.5) * grid)


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
class PreparedVectorSpatialGroups:
    """Best-effort canonical groups separated in writer-safe XY space.

    在写入安全的 XY 空间中彼此分离的尽力规范组。
    """

    groups: tuple[PreparedVectorRunGroup, ...]
    source_geometry_count: int
    source_part_count: int
    prepared_part_count: int
    failed_group_count: int
    failed_part_count: int
    failure_types: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class _PhysicalPart:
    source_index: int
    geometry: Polygon


@dataclass(frozen=True)
class _SteppedPhysicalSlab:
    geometry: Polygon
    z_start_mm: float
    z_end_mm: float


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
    if not geometry.is_valid:
        return _polygon_parts(make_valid(geometry))
    if isinstance(geometry, Polygon):
        parts = (geometry,)
    else:
        parts = tuple(geometry.geoms)
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


def _resnap_noded_group(geometry: BaseGeometry, *, grid_mm: float) -> BaseGeometry:
    """Snap rational segment intersections back onto the physical grid."""

    snapped = set_precision(
        geometry,
        grid_size=float(grid_mm),
        mode="valid_output",
    )
    if snapped is None or snapped.is_empty or not snapped.is_valid:
        raise ValueError("Vector noded geometry could not be closed on the physical grid")
    return snapped


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


def _polygon_has_ring_contact(polygon: Polygon) -> bool:
    """Return whether distinct boundary rings touch in physical space."""

    if not polygon.interiors:
        return False
    shell_boundary = Polygon(polygon.exterior).boundary
    holes = [Polygon(ring) for ring in polygon.interiors]
    tree = STRtree(holes)
    if len(tree.query(shell_boundary, predicate="intersects")) > 0:
        return True
    pairs = np.asarray(tree.query(holes, predicate="intersects"), dtype=np.int64)
    return bool(pairs.size and np.any(pairs[0] < pairs[1]))


def _ring_translation_candidates(*, grid_mm: float) -> list[tuple[float, float]]:
    """Return deterministic sub-nozzle translations for touching holes."""

    directions = (
        (1, 0),
        (-1, 0),
        (0, 1),
        (0, -1),
        (1, 1),
        (1, -1),
        (-1, 1),
        (-1, -1),
    )
    return [
        (float(dx * radius) * grid_mm, float(dy * radius) * grid_mm)
        for radius in range(1, _MAX_CONTACT_TRANSLATION_GRID_UNITS + 1)
        for dx, dy in directions
    ]


def _translate_on_physical_grid(
    polygon: Polygon,
    *,
    x_offset: float,
    y_offset: float,
    grid_mm: float,
) -> Polygon | None:
    """Translate and immediately restore exact physical-grid coordinates."""

    translated = affinity.translate(
        polygon,
        xoff=float(x_offset),
        yoff=float(y_offset),
    )
    snapped = set_precision(
        translated,
        grid_size=float(grid_mm),
        mode="pointwise",
    )
    if not isinstance(snapped, Polygon) or snapped.is_empty or not snapped.is_valid:
        return None
    return snapped


def _separate_polygon_ring_contacts(
    polygon: Polygon,
    *,
    grid_mm: float,
) -> tuple[Polygon, bool]:
    """Separate point-touching holes without changing their area.

    OGC-valid polygons may let a hole touch the shell or another hole at one
    point.  A closed indexed prism cannot represent that weakly-simple contact:
    the cap and the two wall rings need different indices at the same writer
    coordinate.  Translate only the touching hole by a few writer-safe grid
    units before triangulation.  The hole area is unchanged and the bounded
    displacement is orders of magnitude below supported nozzle widths.
    """

    if not _polygon_has_ring_contact(polygon):
        return polygon, False

    shell = Polygon(polygon.exterior)
    shell_boundary = shell.boundary
    holes = [Polygon(ring) for ring in polygon.interiors]
    translated = False
    candidates = _ring_translation_candidates(grid_mm=float(grid_mm))
    hole_tree = STRtree(holes)
    shell_contacts = {
        int(index)
        for index in np.asarray(
            hole_tree.query(shell_boundary, predicate="intersects")
        ).reshape(-1)
    }
    touching_neighbors: dict[int, set[int]] = {}
    pairs = np.asarray(
        hole_tree.query(holes, predicate="intersects"),
        dtype=np.int64,
    )
    if pairs.size:
        for first_index, second_index in pairs.T:
            first = int(first_index)
            second = int(second_index)
            if first >= second:
                continue
            touching_neighbors.setdefault(first, set()).add(second)
            touching_neighbors.setdefault(second, set()).add(first)

    touching_indices = sorted(shell_contacts | set(touching_neighbors))
    maximum_relative_motion = float(grid_mm) * 12.0
    for hole_index in touching_indices:
        hole = holes[hole_index]
        neighbor_indices = {
            int(index)
            for index in np.asarray(
                hole_tree.query(
                    hole,
                    predicate="dwithin",
                    distance=maximum_relative_motion,
                )
            ).reshape(-1)
            if int(index) != hole_index
        }
        neighbor_indices.update(touching_neighbors.get(hole_index, ()))
        requires_separation = (
            shell_boundary.intersects(hole.boundary)
            or any(hole.intersects(holes[index]) for index in neighbor_indices)
        )
        if not requires_separation:
            continue

        separated = None
        for x_offset, y_offset in candidates:
            candidate = _translate_on_physical_grid(
                hole,
                x_offset=x_offset,
                y_offset=y_offset,
                grid_mm=float(grid_mm),
            )
            if candidate is None:
                continue
            if (
                shell.contains(candidate)
                and shell_boundary.disjoint(candidate)
                and all(
                    candidate.disjoint(holes[index])
                    for index in neighbor_indices
                )
            ):
                separated = candidate
                break
        if separated is None:
            raise ValueError(
                "Vector point-touching rings could not remain independent"
            )
        holes[hole_index] = separated
        translated = True

    result = Polygon(
        polygon.exterior.coords,
        [hole.exterior.coords for hole in holes],
    )
    if result.is_empty or not result.is_valid or _polygon_has_ring_contact(result):
        raise ValueError("Vector physical-grid output retains touching rings")
    area_tolerance = max(1e-12, float(polygon.area) * 1e-12)
    if abs(float(result.area) - float(polygon.area)) > area_tolerance:
        raise ValueError("Vector ring separation changed printable coverage")
    return result, translated


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
        for radius in range(1, _MAX_CONTACT_TRANSLATION_GRID_UNITS + 1)
        for dx, dy in unique_directions
    ]


def _separate_unrepresentable_contacts(
    geometry: BaseGeometry,
    *,
    grid_mm: float,
) -> tuple[BaseGeometry, bool]:
    """Move all unrepresentable boundary contacts apart on one physical grid."""

    source_parts = _polygon_parts(geometry)
    separated_any = False
    ring_safe_parts: list[Polygon] = []
    for part in source_parts:
        ring_safe_part, ring_separated = _separate_polygon_ring_contacts(
            part,
            grid_mm=float(grid_mm),
        )
        ring_safe_parts.append(ring_safe_part)
        separated_any = separated_any or ring_separated

    ring_safe_geometry: BaseGeometry = (
        ring_safe_parts[0]
        if len(ring_safe_parts) == 1
        else MultiPolygon(ring_safe_parts)
    )
    has_cross_polygon_contact = _has_cross_polygon_contact(ring_safe_geometry)
    if has_cross_polygon_contact:
        ordered_parts = sorted(
            ring_safe_parts,
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
                candidate = _translate_on_physical_grid(
                    part,
                    x_offset=x_offset,
                    y_offset=y_offset,
                    grid_mm=float(grid_mm),
                )
                if candidate is None:
                    continue
                if not any(candidate.intersects(other) for other in accepted):
                    separated = candidate
                    break
            if separated is None:
                raise ValueError(
                    "Vector float32-near contacts could not remain independent"
                )
            accepted.append(separated)
            separated_any = True
        result: BaseGeometry = (
            accepted[0] if len(accepted) == 1 else MultiPolygon(accepted)
        )
    else:
        result = ring_safe_geometry
    if (
        result.is_empty
        or not result.is_valid
        or _has_cross_polygon_contact(result)
    ):
        raise ValueError("Vector physical-grid output retains touching boundaries")
    result_parts = _polygon_parts(result)
    if any(_polygon_has_ring_contact(part) for part in result_parts):
        raise ValueError("Vector physical-grid output retains touching boundaries")
    source_area = math.fsum(float(part.area) for part in source_parts)
    result_area = math.fsum(float(part.area) for part in result_parts)
    area_tolerance = max(1e-12, abs(source_area) * 1e-12)
    if abs(result_area - source_area) > area_tolerance:
        raise ValueError("Vector contact separation changed printable coverage")
    return result, separated_any


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
    if original_coordinates > _MAX_EXACT_SIMPLIFICATION_COORDINATES:
        return geometry, False, False
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
    return resolve_vector_writer_grid_mm(
        maximum_abs_coordinate,
        minimum_mm=float(minimum_mm),
    )


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
            # A printable micro-island can be narrower than the bounded
            # contact-separation shift, leaving no positive-area overlap with
            # its original position.  Recover only the nearest source within
            # that same constructive movement bound; anything farther away is
            # still rejected as lost ownership.
            source_distances = [
                float(polygon.distance(source_geometry))
                for source_geometry in source_geometries
            ]
            nearest_distance = min(source_distances, default=math.inf)
            ownership_distance_limit = (
                float(grid_mm)
                * (_MAX_CONTACT_TRANSLATION_GRID_UNITS + 1)
                * math.sqrt(2.0)
            )
            distance_equality_tolerance = max(1e-12, float(grid_mm) * 1e-9)
            if nearest_distance <= ownership_distance_limit:
                owners = sorted(
                    {
                        source_index
                        for source_index, distance in zip(
                            source_indices,
                            source_distances,
                        )
                        if distance
                        <= nearest_distance + distance_equality_tolerance
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
        canonical = _resnap_noded_group(
            _node_group_once(snapped),
            grid_mm=grid_mm,
        )
        # The physical grid is the export representation, not a repair
        # candidate that must reproduce arbitrary input floats byte-for-byte.
        # Every source polygon has already been checked for survival by
        # ``_snapped_parts``.  Measure all later fidelity decisions against
        # this representable geometry so harmless grid rounding cannot reject
        # a complete Outline or native Vector group.
        representable_area = float(canonical.area)
        canonical, separated = _separate_unrepresentable_contacts(
            canonical,
            grid_mm=grid_mm,
        )
        if separated:
            separated_contact_group_count += 1

        canonical, simplified, restored = _simplify_or_restore(
            canonical,
            expected_area_mm2=representable_area,
            policy=effective_policy,
        )
        simplified_group_count += int(simplified)
        restored_group_count += int(restored)
        prepared_group = _prepared_polygons(
            canonical,
            grid_mm=grid_mm,
            source_parts=physical_parts,
            group_indices=group_indices,
        )
        if not prepared_group:
            raise ValueError("Vector integer-grid conversion removed a source group")
        prepared_geometries = [
            polygon.to_geometry(grid_mm) for polygon in prepared_group
        ]
        if any(not geometry.is_valid for geometry in prepared_geometries):
            raise ValueError("Vector integer-grid conversion produced invalid rings")
        prepared_geometry: BaseGeometry = (
            prepared_geometries[0]
            if len(prepared_geometries) == 1
            else MultiPolygon(prepared_geometries)
        )
        if (
            not prepared_geometry.is_valid
            or not _coverage_is_complete(
                representable_area,
                float(prepared_geometry.area),
                effective_policy,
            )
        ):
            raise ValueError("Vector integer-grid conversion lost printable coverage")
        output.extend(prepared_group)

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
    if not output_geometry.is_valid:
        raise ValueError("Vector canonical preparation produced invalid aggregate geometry")
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
    return PreparedVectorRunGroup(
        polygons=tuple(output),
        grid_mm=grid_mm,
        stats=stats,
    )


def prepare_vector_spatial_groups_best_effort(
    geometries: Sequence[BaseGeometry],
    *,
    scale_mm_per_svg_unit: float,
    policy: VectorLayerGeometryPolicy | None = None,
) -> PreparedVectorSpatialGroups:
    """Prepare independent nearby groups without reviving a legacy fallback.

    使用同一规范算法独立准备邻近组，不再回到旧拓扑修复链。

    Touching or writer-grid-near source parts are always prepared together.
    A failed remote group is omitted while successful groups remain available;
    memory exhaustion is never swallowed. This keeps local availability without
    combining independently prepared touching shells in one 3MF object.

    Args:
        geometries: Source polygonal geometries in SVG units.
            （SVG 单位中的源多边形几何）
        scale_mm_per_svg_unit: Physical XY scale.（物理 XY 比例）
        policy: Optional canonical geometry policy.（可选规范几何策略）

    Returns:
        Prepared groups plus deterministic failure counters.
        （已准备组及确定性的失败计数）
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
    for source_index, geometry in enumerate(geometries):
        if geometry is None:
            continue
        for part in _polygon_parts(geometry):
            physical_parts.append(
                _PhysicalPart(
                    source_index=source_index,
                    geometry=affinity.scale(
                        part,
                        xfact=scale,
                        yfact=scale,
                        origin=(0.0, 0.0),
                    ),
                )
            )
    if not physical_parts:
        raise ValueError("Vector run group requires polygonal geometry")

    shared_grid_mm = _writer_safe_grid_mm(physical_parts, minimum_grid_mm)
    group_policy = replace(effective_policy, grid_mm=shared_grid_mm)
    spatial_groups = _nearby_groups(
        physical_parts,
        distance_mm=shared_grid_mm,
    )
    prepared_groups: list[PreparedVectorRunGroup] = []
    prepared_part_count = 0
    failed_group_count = 0
    failed_part_count = 0
    failure_types: dict[str, int] = {}
    handled_errors = (
        ValueError,
        TypeError,
        RuntimeError,
        AttributeError,
        OSError,
        OverflowError,
    )

    for group_indices in spatial_groups:
        group_geometries_mm = tuple(
            physical_parts[index].geometry for index in group_indices
        )
        try:
            prepared = prepare_vector_run_group(
                group_geometries_mm,
                scale_mm_per_svg_unit=1.0,
                policy=group_policy,
            )
        except MemoryError:
            raise
        except handled_errors as exc:
            failed_group_count += 1
            failed_part_count += len(group_indices)
            error_name = type(exc).__name__
            failure_types[error_name] = failure_types.get(error_name, 0) + 1
            continue
        prepared_groups.append(prepared)
        prepared_part_count += len(group_indices)

    return PreparedVectorSpatialGroups(
        groups=tuple(prepared_groups),
        source_geometry_count=len(geometries),
        source_part_count=len(physical_parts),
        prepared_part_count=prepared_part_count,
        failed_group_count=failed_group_count,
        failed_part_count=failed_part_count,
        failure_types=tuple(sorted(failure_types.items())),
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


def _cap_expected_boundary_edges(ring_ends: np.ndarray) -> np.ndarray:
    ring_starts = np.concatenate((np.asarray([0]), ring_ends[:-1])).astype(np.int64)
    boundary_chunks = []
    for ring_start, ring_end in zip(ring_starts, ring_ends.astype(np.int64)):
        indices = np.arange(int(ring_start), int(ring_end), dtype=np.int64)
        boundary_chunks.append(
            np.sort(np.column_stack((indices, np.roll(indices, -1))), axis=1)
        )
    return np.vstack(boundary_chunks)


def _straight_ring_chain(
    vertices_2d: np.ndarray,
    ring_ends: np.ndarray,
    start_index: int,
    end_index: int,
) -> np.ndarray | None:
    """Return the noded ring arc represented by one triangulator edge."""

    ring_starts = np.concatenate((np.asarray([0]), ring_ends[:-1])).astype(np.int64)
    for ring_start, ring_end in zip(ring_starts, ring_ends.astype(np.int64)):
        if not (
            int(ring_start) <= start_index < int(ring_end)
            and int(ring_start) <= end_index < int(ring_end)
        ):
            continue
        ring = np.arange(int(ring_start), int(ring_end), dtype=np.int64)
        start_position = int(np.flatnonzero(ring == start_index)[0])
        end_position = int(np.flatnonzero(ring == end_index)[0])
        forward = np.concatenate(
            (
                ring[start_position:],
                ring[: end_position + 1],
            )
        )
        if start_position <= end_position:
            forward = ring[start_position : end_position + 1]
        backward = np.concatenate(
            (
                ring[: start_position + 1][::-1],
                ring[end_position:][::-1],
            )
        )
        if start_position >= end_position:
            backward = ring[end_position : start_position + 1][::-1]

        start = vertices_2d[start_index]
        end = vertices_2d[end_index]
        delta = end - start
        squared_length = float(np.dot(delta, delta))
        for candidate in (forward, backward):
            if len(candidate) <= 2:
                continue
            coordinates = vertices_2d[candidate]
            relative = coordinates - start
            cross = relative[:, 0] * delta[1] - relative[:, 1] * delta[0]
            projection = relative @ delta
            if (
                np.all(cross == 0.0)
                and np.all(projection >= 0.0)
                and np.all(projection <= squared_length)
                and np.all(projection[1:] > projection[:-1])
            ):
                return candidate
    return None


def _restore_noded_cap_boundary(
    vertices_2d: np.ndarray,
    cap_faces: np.ndarray,
    ring_ends: np.ndarray,
) -> np.ndarray:
    """Split cap triangles at collinear ring nodes omitted by triangulators."""

    faces = np.asarray(cap_faces, dtype=np.int64).reshape((-1, 3))
    expected_boundary = _cap_expected_boundary_edges(ring_ends)
    expected_keys = {
        (int(edge[0]), int(edge[1])) for edge in expected_boundary
    }
    for _split_index in range(len(vertices_2d)):
        cap_edges = np.sort(
            faces[:, [[0, 1], [1, 2], [2, 0]]].reshape((-1, 2)),
            axis=1,
        )
        unique_edges, counts = np.unique(cap_edges, axis=0, return_counts=True)
        boundary_edges = unique_edges[counts == 1]
        unexpected = next(
            (
                edge
                for edge in boundary_edges
                if (int(edge[0]), int(edge[1])) not in expected_keys
            ),
            None,
        )
        if unexpected is None:
            return faces

        first = int(unexpected[0])
        second = int(unexpected[1])
        chain = _straight_ring_chain(
            vertices_2d,
            ring_ends,
            first,
            second,
        )
        if chain is None:
            raise ValueError(
                "Vector canonical cap introduced a non-ring boundary edge"
            )
        owning_faces = np.flatnonzero(
            np.sum(np.isin(faces, [first, second]), axis=1) == 2
        )
        if len(owning_faces) != 1:
            raise ValueError(
                "Vector canonical cap boundary edge has ambiguous ownership"
            )
        face_index = int(owning_faces[0])
        opposite = next(
            int(index)
            for index in faces[face_index]
            if int(index) not in {first, second}
        )
        replacement = np.column_stack(
            (
                chain[:-1],
                chain[1:],
                np.full(len(chain) - 1, opposite, dtype=np.int64),
            )
        )
        faces = np.concatenate(
            (faces[:face_index], replacement, faces[face_index + 1 :]),
            axis=0,
        )
    raise ValueError("Vector canonical cap could not restore all ring nodes")


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

    expected_boundary = _cap_expected_boundary_edges(ring_ends)
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
        earcut_faces = np.asarray(
            triangulate_float64(vertices_2d, ring_ends),
            dtype=np.int64,
        ).reshape((-1, 3))
        if (
            len(earcut_faces) > 0
            and np.all(earcut_faces >= 0)
            and np.all(earcut_faces < len(vertices_2d))
        ):
            triangles = vertices_2d[earcut_faces]
            signed_twice_area = (
                (triangles[:, 1, 0] - triangles[:, 0, 0])
                * (triangles[:, 2, 1] - triangles[:, 0, 1])
                - (triangles[:, 1, 1] - triangles[:, 0, 1])
                * (triangles[:, 2, 0] - triangles[:, 0, 0])
            )
            if not bool(np.any(signed_twice_area == 0.0)):
                return earcut_faces

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


def _validate_float32_triangle_domain(
    vertices: np.ndarray,
    faces: np.ndarray,
    *,
    mesh_label: str,
) -> None:
    """Certify locally generated triangles in the actual 3MF writer domain."""

    source_vertices = np.asarray(vertices)
    source_faces = np.asarray(faces, dtype=np.int64)
    for start in range(0, len(source_vertices), 65_536):
        writer_block = np.asarray(
            source_vertices[start : start + 65_536],
            dtype=np.float32,
        )
        if not np.all(np.isfinite(writer_block)):
            raise ValueError(f"{mesh_label} exceeds float32 writer space")

    for start in range(0, len(source_faces), 65_536):
        triangles = np.asarray(
            source_vertices[source_faces[start : start + 65_536]],
            dtype=np.float32,
        )
        cross = np.cross(
            triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 0],
        )
        if np.any(np.all(cross == 0.0, axis=1)):
            raise ValueError(
                f"{mesh_label} contains a float32-degenerate triangle"
            )


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
            _restore_noded_cap_boundary(
                vertices_2d,
                raw_cap_faces,
                ring_ends,
            ),
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

    _validate_float32_triangle_domain(
        vertices,
        faces,
        mesh_label="Vector canonical mesh",
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


def _stepped_ring_units(coordinates, *, grid_mm: float) -> np.ndarray:
    """Keep every globally noded ring vertex on the physical integer grid."""

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
    if len(units) < 3:
        raise ValueError("Vector stepped-volume ring collapsed below three points")
    return np.ascontiguousarray(units)


def _stepped_prepared_polygon(
    polygon: Polygon,
    *,
    grid_mm: float,
) -> tuple[PreparedVectorPolygon, list[np.ndarray]]:
    """Convert one arrangement cell without discarding shared line nodes."""

    oriented = orient(polygon, sign=1.0)
    prepared = PreparedVectorPolygon(
        exterior_units=_stepped_ring_units(
            oriented.exterior.coords,
            grid_mm=grid_mm,
        ),
        hole_units=tuple(
            _stepped_ring_units(ring.coords, grid_mm=grid_mm)
            for ring in oriented.interiors
        ),
        source_indices=(0,),
    )
    return prepared, _oriented_polygon_rings(prepared)


def _extrude_single_stepped_slab(
    slab: _SteppedPhysicalSlab,
    *,
    grid_mm: float,
) -> trimesh.Trimesh:
    """Extrude an isolated slab without building a multi-level arrangement."""

    prepared_polygon, rings = _stepped_prepared_polygon(
        slab.geometry,
        grid_mm=grid_mm,
    )
    coordinate_count = sum(len(ring) for ring in rings)
    integer_coordinate_bytes = sum(ring.nbytes for ring in rings)
    area_mm2 = float(slab.geometry.area)
    prepared = PreparedVectorRunGroup(
        polygons=(prepared_polygon,),
        grid_mm=float(grid_mm),
        stats=VectorLayerGeometryStats(
            source_geometry_count=1,
            source_polygon_count=1,
            source_component_count=1,
            source_hole_count=len(prepared_polygon.hole_units),
            source_area_mm2=area_mm2,
            output_component_count=1,
            output_hole_count=len(prepared_polygon.hole_units),
            output_area_mm2=area_mm2,
            input_coordinate_count=coordinate_count,
            output_coordinate_count=coordinate_count,
            integer_coordinate_bytes=integer_coordinate_bytes,
            spatial_group_count=1,
            simplified_group_count=0,
            restored_group_count=0,
            separated_contact_group_count=0,
        ),
    )
    return extrude_prepared_vector_run_group(
        prepared,
        height_mm=slab.z_end_mm - slab.z_start_mm,
        z_offset_mm=slab.z_start_mm,
    )


def _stepped_slab_parts(
    slabs: Sequence[dict],
    *,
    scale_mm_per_svg_unit: float,
    policy: VectorLayerGeometryPolicy,
) -> tuple[list[_SteppedPhysicalSlab], float]:
    """Validate, scale, and snap all stepped slabs on one writer-safe grid."""

    scale = float(scale_mm_per_svg_unit)
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("Vector stepped-volume scale must be positive finite")

    physical_parts: list[_PhysicalPart] = []
    raw_slabs: list[_SteppedPhysicalSlab] = []
    for slab_index, slab in enumerate(slabs):
        if not isinstance(slab, dict):
            raise ValueError("Vector stepped-volume slabs must be mappings")
        geometry = slab.get("geometry")
        try:
            z_start = float(slab.get("z_offset", 0.0))
            height = float(slab.get("height", 0.0))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Vector stepped-volume slab has invalid height") from exc
        if geometry is None or getattr(geometry, "is_empty", True) or height <= 1e-9:
            continue
        z_end = z_start + height
        if not all(math.isfinite(value) for value in (z_start, z_end)):
            raise ValueError("Vector stepped-volume Z range must be finite")
        for polygon in _polygon_parts(geometry):
            physical_geometry = affinity.scale(
                polygon,
                xfact=scale,
                yfact=scale,
                origin=(0.0, 0.0),
            )
            for physical in _polygon_parts(physical_geometry):
                physical_parts.append(
                    _PhysicalPart(source_index=slab_index, geometry=physical)
                )
                raw_slabs.append(
                    _SteppedPhysicalSlab(
                        geometry=physical,
                        z_start_mm=round(z_start, 9),
                        z_end_mm=round(z_end, 9),
                    )
                )
    if not raw_slabs:
        return [], float(policy.grid_mm)

    grid_mm = _writer_safe_grid_mm(physical_parts, float(policy.grid_mm))
    snapped_slabs: list[_SteppedPhysicalSlab] = []
    for slab in raw_slabs:
        snapped = set_precision(
            slab.geometry,
            grid_size=grid_mm,
            mode="valid_output",
        )
        if snapped is None or snapped.is_empty:
            continue
        for polygon in _polygon_parts(snapped):
            snapped_slabs.append(
                _SteppedPhysicalSlab(
                    geometry=polygon,
                    z_start_mm=slab.z_start_mm,
                    z_end_mm=slab.z_end_mm,
                )
            )
    return snapped_slabs, grid_mm


def _stepped_component_groups(
    slabs: Sequence[_SteppedPhysicalSlab],
    *,
    grid_mm: float,
) -> list[list[_SteppedPhysicalSlab]]:
    """Keep point-only XY islands separate in writer coordinates."""

    footprint = unary_union([slab.geometry for slab in slabs])
    components = list(_polygon_parts(footprint))
    grouped: list[list[_SteppedPhysicalSlab]] = [[] for _ in components]
    component_tree = STRtree(components)
    orphan_components: list[Polygon] = []
    orphan_groups: list[list[_SteppedPhysicalSlab]] = []
    for slab in slabs:
        representative = slab.geometry.representative_point()
        matches = np.asarray(
            component_tree.query(representative, predicate="covered_by"),
            dtype=np.int64,
        ).reshape(-1)
        if len(matches) == 0:
            nearby = np.asarray(
                component_tree.query(slab.geometry, predicate="intersects"),
                dtype=np.int64,
            ).reshape(-1)
            if len(nearby) > 0:
                matches = np.asarray(
                    [
                        max(
                            (int(index) for index in nearby),
                            key=lambda index: float(
                                components[index].intersection(slab.geometry).area
                            ),
                        )
                    ],
                    dtype=np.int64,
                )
        if len(matches) > 0:
            grouped[int(np.min(matches))].append(slab)
            continue
        orphan_components.append(slab.geometry)
        orphan_groups.append([slab])
    components.extend(orphan_components)
    grouped.extend(orphan_groups)

    accepted_footprints: list[Polygon] = []
    separated_groups: list[list[_SteppedPhysicalSlab]] = []
    ordered = sorted(
        zip(components, grouped),
        key=lambda item: (-float(item[0].area), *item[0].bounds),
    )
    for component, group in ordered:
        if not group:
            continue
        contacts = [
            other
            for other in accepted_footprints
            if component.intersects(other)
        ]
        if not contacts:
            accepted_footprints.append(component)
            separated_groups.append(group)
            continue

        translated_component = None
        translated_group = None
        for x_offset, y_offset in _contact_free_translation_candidates(
            component,
            contacts,
            grid_mm=grid_mm,
        ):
            candidate = _translate_on_physical_grid(
                component,
                x_offset=x_offset,
                y_offset=y_offset,
                grid_mm=grid_mm,
            )
            if candidate is None or any(
                candidate.intersects(other) for other in accepted_footprints
            ):
                continue
            translated_component = candidate
            translated_group = [
                _SteppedPhysicalSlab(
                    geometry=set_precision(
                        affinity.translate(
                            slab.geometry,
                            xoff=x_offset,
                            yoff=y_offset,
                        ),
                        grid_size=grid_mm,
                        mode="pointwise",
                    ),
                    z_start_mm=slab.z_start_mm,
                    z_end_mm=slab.z_end_mm,
                )
                for slab in group
            ]
            break
        if translated_component is None or translated_group is None:
            raise ValueError(
                "Vector stepped-volume point contact could not remain independent"
            )
        accepted_footprints.append(translated_component)
        separated_groups.append(translated_group)
    return separated_groups


def _stepped_interval_footprints(
    slabs: Sequence[_SteppedPhysicalSlab],
    *,
    grid_mm: float,
) -> tuple[list[float], list[BaseGeometry | None]]:
    """Resolve the occupied planar footprint for every consecutive Z band."""

    z_levels = sorted(
        {
            value
            for slab in slabs
            for value in (slab.z_start_mm, slab.z_end_mm)
        }
    )
    if len(z_levels) < 2:
        raise ValueError("Vector stepped-volume requires a positive Z interval")
    writer_z = np.asarray(z_levels, dtype=np.float32)
    if np.any(writer_z[1:] <= writer_z[:-1]):
        raise ValueError("Vector stepped-volume Z interval collapses in writer space")

    footprints: list[BaseGeometry | None] = []
    for z_start, z_end in zip(z_levels, z_levels[1:]):
        z_mid = (z_start + z_end) * 0.5
        active = [
            slab.geometry
            for slab in slabs
            if slab.z_start_mm < z_mid < slab.z_end_mm
        ]
        if not active:
            footprints.append(None)
            continue
        footprint = set_precision(
            unary_union(active),
            grid_size=grid_mm,
            mode="valid_output",
        )
        if footprint is None or footprint.is_empty:
            raise ValueError("Vector stepped-volume lost an occupied Z band")
        footprints.append(footprint)
    return z_levels, footprints


def _stepped_arrangement_cells(
    footprints: Sequence[BaseGeometry | None],
    *,
    grid_mm: float,
) -> tuple[list[Polygon], np.ndarray]:
    """Node all Z-band boundaries once and label their atomic XY cells."""

    occupied_footprints = [
        footprint
        for footprint in footprints
        if footprint is not None and not footprint.is_empty
    ]
    if not occupied_footprints:
        return [], np.empty((0, len(footprints)), dtype=bool)
    # Snap-round and node the complete line arrangement in one fixed-precision
    # operation.  This keeps every resulting cell on the writer-safe physical
    # grid and lets only genuinely sub-grid residue collapse there.
    linework = shapely.unary_union(
        [footprint.boundary for footprint in occupied_footprints],
        grid_size=grid_mm,
    )
    cells = [
        cell
        for cell in polygonize(linework)
        if not cell.is_empty and float(cell.area) > 0.0
    ]
    cells = [
        cell
        for cell in cells
        if isinstance(cell, Polygon) and not cell.is_empty
    ]
    refined_cells: list[Polygon] = []
    for cell in cells:
        if not _polygon_has_ring_contact(cell):
            refined_cells.append(cell)
            continue
        raw_triangles = list(
            shapely.get_parts(shapely.constrained_delaunay_triangles(cell))
        )
        parts = []
        for triangle in raw_triangles:
            if not cell.covers(triangle.representative_point()):
                continue
            part = set_precision(
                triangle,
                grid_size=grid_mm,
                mode="pointwise",
            )
            if (
                not isinstance(part, Polygon)
                or part.is_empty
                or not part.is_valid
                or float(part.area) <= 0.0
                or _polygon_has_ring_contact(part)
            ):
                continue
            parts.append(part)
        if not parts:
            raise ValueError(
                "Vector stepped-volume could not split a local ring contact"
            )
        refined_area = math.fsum(float(part.area) for part in parts)
        area_tolerance = max(1e-12, float(cell.area) * 1e-12)
        if (
            not parts
            or abs(refined_area - float(cell.area)) > area_tolerance
        ):
            raise ValueError(
                "Vector stepped-volume ring-contact split changed coverage"
            )
        refined_cells.extend(parts)
    cells = refined_cells
    cells.sort(key=lambda cell: (*cell.bounds, float(cell.area)))
    occupancy = np.zeros((len(cells), len(footprints)), dtype=bool)
    for cell_index, cell in enumerate(cells):
        point = cell.representative_point()
        for interval_index, footprint in enumerate(footprints):
            occupancy[cell_index, interval_index] = bool(
                footprint is not None and footprint.covers(point)
            )
    keep = np.any(occupancy, axis=1)
    return (
        [cell for cell, retained in zip(cells, keep) if bool(retained)],
        occupancy[keep],
    )


def _materialize_stepped_contact_vertices(
    vertices: np.ndarray,
    faces: np.ndarray,
    contact_groups: Sequence[Sequence[int]],
    *,
    grid_mm: float,
) -> np.ndarray:
    """Give known local volume domains distinct float32 writer coordinates."""

    groups = [tuple(int(index) for index in group) for group in contact_groups]
    groups = [group for group in groups if len(group) > 1]
    if not groups:
        return vertices

    contact_indices = np.asarray(
        [index for group in groups for index in group],
        dtype=np.int64,
    )
    contact_lookup = np.full(len(vertices), -1, dtype=np.int64)
    contact_lookup[contact_indices] = np.arange(len(contact_indices), dtype=np.int64)
    inward_sums = np.zeros((len(contact_indices), 3), dtype=np.float64)
    for block_start in range(0, len(faces), 65_536):
        face_block = faces[block_start : block_start + 65_536]
        selected_faces = face_block[
            np.any(contact_lookup[face_block] >= 0, axis=1)
        ]
        if len(selected_faces) == 0:
            continue
        triangles = vertices[selected_faces]
        normals = np.cross(
            triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 0],
        )
        normal_lengths = np.linalg.norm(normals, axis=1)
        valid = normal_lengths > 0.0
        normals[valid] /= normal_lengths[valid, None]
        normals[~valid] = 0.0
        for corner in range(3):
            local_indices = contact_lookup[selected_faces[:, corner]]
            selected = local_indices >= 0
            np.add.at(
                inward_sums,
                local_indices[selected],
                -normals[selected],
            )

    maximum_abs_coordinate = float(np.max(np.abs(vertices)))
    writer_ulp = abs(float(np.spacing(np.float32(maximum_abs_coordinate))))
    coordinate_quantum = min(
        float(grid_mm) * 0.25,
        max(writer_ulp, 1e-7),
    )
    output = vertices.copy()
    contact_cursor = 0
    for group in groups:
        group_directions = inward_sums[
            contact_cursor : contact_cursor + len(group)
        ]
        contact_cursor += len(group)
        lengths = np.linalg.norm(group_directions, axis=1)
        nonzero = lengths > 1e-12
        group_directions[nonzero] /= lengths[nonzero, None]

        radius = 1
        while (2 * radius + 1) ** 3 - 1 < len(group):
            radius += 1
        codes = np.asarray(
            [
                (x_step, y_step, z_step)
                for x_step in range(-radius, radius + 1)
                for y_step in range(-radius, radius + 1)
                for z_step in range(-radius, radius + 1)
                if (x_step, y_step, z_step) != (0, 0, 0)
            ],
            dtype=np.float64,
        )
        code_lengths = np.linalg.norm(codes, axis=1)
        unit_codes = codes / code_lengths[:, None]
        unused = set(range(len(codes)))
        for local_index, vertex_index in enumerate(group):
            direction = group_directions[local_index]
            scores = unit_codes @ direction
            chosen = min(
                unused,
                key=lambda code_index: (
                    -float(scores[code_index]),
                    float(code_lengths[code_index]),
                    tuple(float(value) for value in codes[code_index]),
                ),
            )
            unused.remove(chosen)
            output[vertex_index] += codes[chosen] * coordinate_quantum

    return output.astype(np.float32).astype(np.float64)


def _build_stepped_component_mesh(
    slabs: Sequence[_SteppedPhysicalSlab],
    *,
    grid_mm: float,
) -> trimesh.Trimesh | None:
    """Build one stepped solid directly from noded caps and exposed walls."""

    z_levels, footprints = _stepped_interval_footprints(slabs, grid_mm=grid_mm)
    cells, occupancy = _stepped_arrangement_cells(footprints, grid_mm=grid_mm)
    if not cells:
        component_footprint = unary_union([slab.geometry for slab in slabs])
        if float(component_footprint.area) <= (
            VectorLayerGeometryPolicy().coverage_absolute_tolerance_mm2
        ):
            return None
        raise ValueError("Vector stepped-volume arrangement produced no cells")

    prepared_cells: list[PreparedVectorPolygon] = []
    cell_rings: list[list[np.ndarray]] = []
    edge_owners: dict[
        tuple[tuple[int, int], tuple[int, int]],
        list[tuple[int, tuple[int, int], tuple[int, int]]],
    ] = {}
    for cell_index, cell in enumerate(cells):
        prepared, rings = _stepped_prepared_polygon(cell, grid_mm=grid_mm)
        prepared_cells.append(prepared)
        cell_rings.append(rings)
        for ring in rings:
            for start, end in zip(ring, np.roll(ring, -1, axis=0)):
                start_key = (int(start[0]), int(start[1]))
                end_key = (int(end[0]), int(end[1]))
                if start_key == end_key:
                    raise ValueError("Vector stepped-volume contains a zero-length edge")
                edge_key = tuple(sorted((start_key, end_key)))
                edge_owners.setdefault(edge_key, []).append(
                    (cell_index, start_key, end_key)
                )
    if any(len(owners) not in {1, 2} for owners in edge_owners.values()):
        raise ValueError("Vector stepped-volume arrangement has ambiguous edge ownership")

    coordinate_cells: dict[tuple[int, int], set[int]] = {}
    coordinate_neighbors: dict[
        tuple[int, int],
        set[tuple[int, int]],
    ] = {}
    for edge, owners in edge_owners.items():
        owner_cells = {int(owner[0]) for owner in owners}
        for coordinate in edge:
            coordinate_cells.setdefault(coordinate, set()).update(owner_cells)
            if len(owner_cells) == 2:
                coordinate_neighbors.setdefault(coordinate, set()).add(
                    tuple(sorted(owner_cells))
                )

    interval_count = occupancy.shape[1]
    local_domain_cache: dict[
        tuple[int, int, int],
        dict[tuple[int, int], int],
    ] = {}

    def local_vertex_domain(
        cell_index: int,
        interval_index: int,
        coordinate: tuple[int, int] | np.ndarray,
        z_index: int,
    ) -> int:
        """Identify only volume regions that meet through a local face."""

        x_unit = int(coordinate[0])
        y_unit = int(coordinate[1])
        cache_key = (x_unit, y_unit, int(z_index))
        cached = local_domain_cache.get(cache_key)
        if cached is None:
            adjacent_intervals = []
            if z_index > 0:
                adjacent_intervals.append(z_index - 1)
            if z_index < interval_count:
                adjacent_intervals.append(z_index)
            incident_cells = coordinate_cells.get((x_unit, y_unit), set())
            nodes = sorted(
                (incident_cell, adjacent_interval)
                for incident_cell in incident_cells
                for adjacent_interval in adjacent_intervals
                if occupancy[incident_cell, adjacent_interval]
            )
            parents = {node: node for node in nodes}

            def find(node: tuple[int, int]) -> tuple[int, int]:
                parent = parents[node]
                while parent != parents[parent]:
                    parents[parent] = parents[parents[parent]]
                    parent = parents[parent]
                while node != parent:
                    next_node = parents[node]
                    parents[node] = parent
                    node = next_node
                return parent

            def union(first: tuple[int, int], second: tuple[int, int]) -> None:
                first_root = find(first)
                second_root = find(second)
                if first_root != second_root:
                    parents[second_root] = first_root

            if len(adjacent_intervals) == 2:
                lower_interval, upper_interval = adjacent_intervals
                for incident_cell in incident_cells:
                    lower = (incident_cell, lower_interval)
                    upper = (incident_cell, upper_interval)
                    if lower in parents and upper in parents:
                        union(lower, upper)

            for first_cell, second_cell in coordinate_neighbors.get(
                (x_unit, y_unit),
                set(),
            ):
                for adjacent_interval in adjacent_intervals:
                    first = (first_cell, adjacent_interval)
                    second = (second_cell, adjacent_interval)
                    if first in parents and second in parents:
                        union(first, second)

            roots: dict[tuple[int, int], int] = {}
            cached = {
                node: roots.setdefault(find(node), len(roots))
                for node in nodes
            }
            local_domain_cache[cache_key] = cached

        owner = (int(cell_index), int(interval_index))
        if owner not in cached:
            raise ValueError(
                "Vector stepped-volume vertex has no occupied local domain"
            )
        return cached[owner]

    vertex_indices: dict[tuple[int, int, int, int], int] = {}
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []

    def vertex_index(
        cell_index: int,
        interval_index: int,
        coordinate: tuple[int, int] | np.ndarray,
        z_index: int,
    ) -> int:
        x_unit = int(coordinate[0])
        y_unit = int(coordinate[1])
        domain = local_vertex_domain(
            cell_index,
            interval_index,
            coordinate,
            z_index,
        )
        key = (domain, x_unit, y_unit, int(z_index))
        existing = vertex_indices.get(key)
        if existing is not None:
            return existing
        index = len(vertices)
        vertex_indices[key] = index
        vertices.append(
            (
                x_unit * grid_mm,
                y_unit * grid_mm,
                float(z_levels[z_index]),
            )
        )
        return index

    for cell_index, (prepared, rings) in enumerate(
        zip(prepared_cells, cell_rings)
    ):
        vertices_2d = np.vstack(rings).astype(np.float64) * grid_mm
        ring_ends = np.cumsum([len(ring) for ring in rings], dtype=np.uint32)
        raw_cap_faces = _canonical_cap_faces(
            prepared,
            vertices_2d,
            ring_ends,
            grid_mm=grid_mm,
        )
        restored_cap_faces = _restore_noded_cap_boundary(
            vertices_2d,
            raw_cap_faces,
            ring_ends,
        )
        cap_faces = _validate_cap_indices(
            vertices_2d,
            restored_cap_faces,
            ring_ends,
            expected_area_mm2=float(cells[cell_index].area),
        )
        flattened_units = np.vstack(rings)
        for z_index in range(interval_count + 1):
            below = z_index > 0 and bool(occupancy[cell_index, z_index - 1])
            above = z_index < interval_count and bool(
                occupancy[cell_index, z_index]
            )
            if below == above:
                continue
            occupied_interval = z_index - 1 if below else z_index
            local_indices = np.asarray(
                [
                    vertex_index(
                        cell_index,
                        occupied_interval,
                        coordinate,
                        z_index,
                    )
                    for coordinate in flattened_units
                ],
                dtype=np.int64,
            )
            oriented_faces = cap_faces if below else cap_faces[:, ::-1]
            faces.extend(
                tuple(int(value) for value in local_indices[face])
                for face in oriented_faces
            )

    for interval_index in range(interval_count):
        for owners in edge_owners.values():
            occupied = [
                owner
                for owner in owners
                if occupancy[owner[0], interval_index]
            ]
            if len(occupied) != 1:
                continue
            cell_index, start, end = occupied[0]
            start_bottom = vertex_index(
                cell_index,
                interval_index,
                start,
                interval_index,
            )
            end_bottom = vertex_index(
                cell_index,
                interval_index,
                end,
                interval_index,
            )
            start_top = vertex_index(
                cell_index,
                interval_index,
                start,
                interval_index + 1,
            )
            end_top = vertex_index(
                cell_index,
                interval_index,
                end,
                interval_index + 1,
            )
            faces.extend(
                (
                    (start_bottom, end_bottom, end_top),
                    (start_bottom, end_top, start_top),
                )
            )

    if not vertices or not faces:
        raise ValueError("Vector stepped-volume construction produced no surface")
    vertex_array = np.asarray(vertices, dtype=np.float64)
    face_array = np.asarray(faces, dtype=np.int64)
    contact_groups: list[list[int]] = []
    for (x_unit, y_unit, z_index), domains in local_domain_cache.items():
        indices = [
            vertex_indices[(domain, x_unit, y_unit, z_index)]
            for domain in sorted(set(domains.values()))
            if (domain, x_unit, y_unit, z_index) in vertex_indices
        ]
        if len(indices) > 1:
            contact_groups.append(indices)
    vertex_array = _materialize_stepped_contact_vertices(
        vertex_array,
        face_array,
        contact_groups,
        grid_mm=grid_mm,
    )
    _validate_float32_triangle_domain(
        vertex_array,
        face_array,
        mesh_label="Vector stepped-volume mesh",
    )
    mesh = trimesh.Trimesh(
        vertices=vertex_array,
        faces=face_array,
        process=False,
    )
    mesh.metadata["vector_stepped_geometry"] = {
        "grid_mm": float(grid_mm),
        "z_interval_count": int(interval_count),
        "arrangement_cell_count": int(len(cells)),
        "mesh_vertex_count": int(len(vertex_array)),
        "mesh_face_count": int(len(face_array)),
    }
    return mesh


def _concatenate_stepped_components(
    meshes: Sequence[trimesh.Trimesh],
) -> trimesh.Trimesh:
    """Concatenate independent stepped components without welding indices."""

    if not meshes:
        raise ValueError("Vector stepped-volume has no component meshes")
    if len(meshes) == 1:
        return meshes[0]
    vertex_count = sum(len(mesh.vertices) for mesh in meshes)
    face_count = sum(len(mesh.faces) for mesh in meshes)
    vertices = np.empty((vertex_count, 3), dtype=np.float64)
    faces = np.empty((face_count, 3), dtype=np.int64)
    vertex_cursor = 0
    face_cursor = 0
    for mesh in meshes:
        next_vertex = vertex_cursor + len(mesh.vertices)
        next_face = face_cursor + len(mesh.faces)
        vertices[vertex_cursor:next_vertex] = np.asarray(
            mesh.vertices,
            dtype=np.float64,
        )
        np.add(
            np.asarray(mesh.faces, dtype=np.int64),
            vertex_cursor,
            out=faces[face_cursor:next_face],
        )
        vertex_cursor = next_vertex
        face_cursor = next_face
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def build_vector_stepped_volume(
    slabs: Sequence[dict],
    *,
    scale_mm_per_svg_unit: float,
    policy: VectorLayerGeometryPolicy | None = None,
) -> trimesh.Trimesh | None:
    """Build a native Vector stepped solid directly from canonical surfaces.
    从规范表面直接构建原生 Vector 阶梯实体。

    Every XY boundary is snapped and noded once before triangle allocation.
    Caps and exposed walls then share the same indexed vertices; no boolean
    mesh union, vertex welding, topology repair, or alternate 3D fallback is
    involved. / 所有 XY 边界在分配三角面前只做一次网格化与节点化；顶面和
    外露侧壁直接共享索引，不再执行网格布尔、合点、拓扑修补或备用三维路径。
    """

    effective_policy = policy or VectorLayerGeometryPolicy()
    snapped_slabs, grid_mm = _stepped_slab_parts(
        slabs,
        scale_mm_per_svg_unit=scale_mm_per_svg_unit,
        policy=effective_policy,
    )
    if not snapped_slabs:
        return None
    component_meshes = []
    component_groups = _stepped_component_groups(
        snapped_slabs,
        grid_mm=grid_mm,
    )
    for group in component_groups:
        component_mesh = None
        if len(group) == 1:
            try:
                component_mesh = _extrude_single_stepped_slab(
                    group[0],
                    grid_mm=grid_mm,
                )
            except ValueError:
                # Writer-domain edge cases still use the complete arrangement;
                # the shortcut must never change coverage or topology policy.
                component_mesh = None
        if component_mesh is None:
            component_mesh = _build_stepped_component_mesh(
                group,
                grid_mm=grid_mm,
            )
        if component_mesh is not None:
            component_meshes.append(component_mesh)
    if not component_meshes:
        return None
    component_groups.clear()
    snapped_slabs.clear()
    mesh = _concatenate_stepped_components(component_meshes)
    mesh.metadata["vector_stepped_geometry"] = {
        "grid_mm": float(grid_mm),
        "component_count": int(len(component_meshes)),
        "mesh_vertex_count": int(len(mesh.vertices)),
        "mesh_face_count": int(len(mesh.faces)),
    }
    return mesh


__all__ = [
    "PreparedVectorPolygon",
    "PreparedVectorRunGroup",
    "resolve_vector_writer_grid_mm",
    "snap_vector_writer_coordinate_mm",
    "PreparedVectorSpatialGroups",
    "VectorLayerGeometryPolicy",
    "VectorLayerGeometryStats",
    "build_vector_stepped_volume",
    "extrude_prepared_vector_run_group",
    "prepare_vector_run_group",
    "prepare_vector_spatial_groups_best_effort",
]
