"""Canonical physical-grid geometry for native Vector layer runs.

Native SVG coordinates are converted to millimetres and noded on one shared
integer grid before any 3D allocation.  This makes shared boundaries identical
by construction and keeps independent printable islands explicit.

原生 SVG 坐标在分配三维网格前统一转换为毫米，并在共享整数网格上节点化；
因此共享边天然一致，独立可打印小岛也不会被静默丢弃。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from shapely import STRtree, affinity, set_precision
from shapely.geometry import MultiPolygon, Polygon
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
    coalesced_contact_group_count: int


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
    """Return all non-empty polygon parts without accepting mixed dimensions."""

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


def _coalesce_unrepresentable_contacts(
    geometry: BaseGeometry,
    *,
    grid_mm: float,
) -> tuple[BaseGeometry, bool]:
    """Turn grid-collapsed shell contacts into one tiny connected footprint."""

    if not _has_cross_polygon_contact(geometry):
        return geometry, False
    expanded = set_precision(
        geometry.buffer(float(grid_mm), join_style="mitre"),
        grid_size=float(grid_mm),
        mode="valid_output",
    )
    if expanded is None or expanded.is_empty or not expanded.is_valid:
        raise ValueError("Vector float32-near contacts could not be coalesced safely")
    if _has_cross_polygon_contact(expanded):
        raise ValueError("Vector physical-grid output retains touching shells")
    if geometry.hausdorff_distance(expanded) > float(grid_mm) * 3.0:
        raise ValueError("Vector contact coalescing exceeded the physical-grid bound")
    return expanded, True


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
    simplified, _coalesced = _coalesce_unrepresentable_contacts(
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
    if len(units) < 3:
        raise ValueError("Vector physical-grid ring collapsed below three points")
    units = np.ascontiguousarray(units)
    units.setflags(write=False)
    return units


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
    geometries: list[BaseGeometry] | tuple[BaseGeometry, ...],
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
    grid_mm = float(effective_policy.grid_mm)
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("Vector physical scale must be positive finite")
    if not math.isfinite(grid_mm) or grid_mm <= 0.0:
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
    coalesced_contact_group_count = 0

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
        canonical, coalesced = _coalesce_unrepresentable_contacts(
            canonical,
            grid_mm=grid_mm,
        )
        if coalesced:
            coalesced_contact_group_count += 1
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
        coalesced_contact_group_count=coalesced_contact_group_count,
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


__all__ = [
    "PreparedVectorPolygon",
    "PreparedVectorRunGroup",
    "VectorLayerGeometryPolicy",
    "VectorLayerGeometryStats",
    "prepare_vector_run_group",
]
