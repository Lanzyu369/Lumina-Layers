"""Optional hole compensation after SVG parsing and before material mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from math import isfinite
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from shapely import STRtree
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from core.svg_coordinate_domain import SvgCoordinateDomain

Region = dict[str, Any]
_COLOR_KEYS = ("color", "rgba", "rgba_f64")
_SOURCE_KEYS = (
    "native_paint_id", "native_paint_index", "native_source_index",
    "native_draw_order", "native_paint_contributors",
    "native_component_index", "draw_order", "source_kind", "source", "source_id",
)


@dataclass(frozen=True)
class SvgHoleCompensationResult:
    """Return original paint regions plus optional derived compensation patches.
    返回原始着色区域和可选派生孔洞补片。

    Attributes:
        regions: Polygon regions followed by compensation patches.
            面区域及追加的孔洞补片。
        silhouette: Filled polygon coverage in the original coordinate space.
            原始坐标系中的补偿后覆盖轮廓。
        patches: Derived polygons with exact source color and provenance.
            保留精确来源颜色和身份记录的派生面补片。
        filled_holes: Number of selected enclosed empty components.
            被选中填充的封闭空白连通区域数量。
        added_area_mm2: Filled empty area, excluding painted islands, in mm².
            新增填充面积，单位平方毫米，不包含原有着色色岛。
        elapsed_seconds: Time spent computing compensation.
            补偿计算耗时，单位秒。
        unprintable_fragments: Original non-polygon or empty geometry diagnostics.
            原始非面或空几何的诊断记录。
    """

    regions: list[Region]
    silhouette: BaseGeometry
    patches: list[Region] = field(default_factory=list)
    filled_holes: int = 0
    added_area_mm2: float = 0.0
    elapsed_seconds: float = 0.0
    unprintable_fragments: list[Region] = field(default_factory=list)


def validate_svg_compensation_scope(
    *, enabled: bool, image_path: str, modeling_mode: object
) -> None:
    """Require an SVG input in vector mode only when compensation is enabled.
    仅在启用补偿时要求输入为矢量模式的 SVG。

    Args:
        enabled: Whether source-SVG hole compensation is requested.
            是否请求原始 SVG 孔洞补偿。
        image_path: Input image path, with a case-insensitive SVG suffix.
            输入图片路径，SVG 扩展名不区分大小写。
        modeling_mode: Modeling mode string or enum with a value property.
            建模模式字符串或包含 value 属性的枚举。

    Raises:
        ValueError: Enabled compensation is requested for an unsupported input.
            启用补偿但输入不属于 SVG 矢量模式。
    """
    if not enabled:
        return
    if (
        Path(image_path).suffix.lower() != ".svg"
        or getattr(modeling_mode, "value", modeling_mode) != "vector"
    ):
        raise ValueError(
            "SVG hole compensation requires an SVG in vector mode / "
            "SVG 孔洞补偿需要矢量模式的 SVG 输入"
        )


def _validate_settings(scale_factor: float, area: float, width: float) -> None:
    if not isfinite(scale_factor) or scale_factor <= 0:
        raise ValueError("scale_factor must be finite and positive")
    for name, value in (("max_hole_area_mm2", area), ("max_hole_width_mm", width)):
        if not isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative")


def _polygon_subset(
    geometry: BaseGeometry, source_index: int, fragments: list[Region]
) -> list[Polygon]:
    if isinstance(geometry, Polygon) and not geometry.is_empty and geometry.area > 0:
        return [geometry]
    if (
        isinstance(geometry, (MultiPolygon, GeometryCollection))
        and not geometry.is_empty
    ):
        return [
            polygon
            for part in geometry.geoms
            for polygon in _polygon_subset(part, source_index, fragments)
        ]
    reason = "non_polygon_geometry"
    if geometry.is_empty:
        reason = "empty_geometry"
    elif isinstance(geometry, Polygon):
        reason = "collapsed_area"
    fragments.append({
        "source_list_index": source_index,
        "geometry_type": geometry.geom_type,
        "reason": reason,
        "geometry": geometry,
    })
    return []


def _polygon_regions(
    regions: list[Region],
) -> tuple[list[Region], list[int], list[Region]]:
    retained: list[Region] = []
    source_indices: list[int] = []
    fragments: list[Region] = []
    for source_index, region in enumerate(regions):
        geometry = region["geometry"]
        if (
            isinstance(geometry, (Polygon, MultiPolygon))
            and not geometry.is_empty
            and geometry.area > 0
            and (
                not isinstance(geometry, MultiPolygon)
                or all(part.area > 0 for part in geometry.geoms)
            )
        ):
            retained.append(region)
            source_indices.append(source_index)
            continue
        polygons = _polygon_subset(geometry, source_index, fragments)
        if polygons:
            geometry = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
            retained.append({**region, "geometry": geometry})
            source_indices.append(source_index)
    if len(retained) == len(regions) and all(a is b for a, b in zip(retained, regions)):
        retained = regions
    return retained, source_indices, fragments


def _ring_mm(coordinates: Any, scale_factor: float, *, positive: bool) -> np.ndarray:
    ring = np.asarray(coordinates, dtype=np.float64)[:, :2] * scale_factor
    edges = ring[1:] - ring[0]
    signed_area = np.sum(edges[:-1, 0] * edges[1:, 1] - edges[:-1, 1] * edges[1:, 0])
    if (signed_area > 0) != positive:
        ring = ring[::-1].copy()
    return ring


def _rings_mm(regions: list[Region], scale_factor: float) -> list[np.ndarray]:
    rings: list[np.ndarray] = []
    for region in regions:
        geometry = region["geometry"]
        polygons = geometry.geoms if isinstance(geometry, MultiPolygon) else (geometry,)
        for polygon in polygons:
            rings.append(_ring_mm(polygon.exterior.coords, scale_factor, positive=True))
            rings.extend(
                _ring_mm(interior.coords, scale_factor, positive=False)
                for interior in polygon.interiors
            )
    return rings


def _polygons_in_source_space(parts: Any, scale_factor: float) -> list[Polygon]:
    return [
        Polygon(
            shell / scale_factor,
            [interior / scale_factor for interior in interiors],
        )
        for shell, interiors in parts
    ]


def _polygons_in_working_space(parts: Any, domain: SvgCoordinateDomain) -> list[Polygon]:
    from lumina_svg_core import project_regions_to_grid

    regions = [[shell, *holes] for shell, holes in parts]
    projected = project_regions_to_grid(
        regions, 1.0 / (domain.mm_per_unit * domain.grid_size),
    )
    return [
        domain.restore_precision(Polygon(
            shell * domain.grid_size,
            [hole * domain.grid_size for hole in holes],
        ))
        for region in projected for shell, holes in region
    ]


def _nearest_sources(
    holes: list[Polygon], regions: list[Region], source_indices: list[int]
) -> list[int]:
    tree = STRtree([region["geometry"] for region in regions])
    matches = tree.query_nearest(
        [hole.representative_point() for hole in holes], all_matches=True
    )
    draw_orders = np.asarray([
        region.get("draw_order", region.get("native_paint_index", source_index))
        for region, source_index in zip(regions, source_indices)
    ])
    hole_indices, region_indices = matches
    ordering = np.lexsort((
        np.asarray(source_indices)[region_indices],
        draw_orders[region_indices],
        hole_indices,
    ))
    sorted_holes = hole_indices[ordering]
    first_per_hole = np.r_[True, sorted_holes[1:] != sorted_holes[:-1]]
    return region_indices[ordering[first_per_hole]].tolist()


def _patch(polygon: Polygon, source: Region, source_index: int) -> Region:
    provenance = {key: source[key] for key in _SOURCE_KEYS if key in source}
    provenance["source_list_index"] = source_index
    return {
        "geometry": polygon,
        **{key: source[key] for key in _COLOR_KEYS if key in source},
        "source_kind": "compensation",
        "geometry_normalized": True,
        "compensation_source": provenance,
    }


def compensate_svg_regions(
    regions: list[Region],
    *,
    silhouette: BaseGeometry,
    scale_factor: float,
    max_hole_area_mm2: float = 0.5,
    max_hole_width_mm: float = 0.1,
) -> SvgHoleCompensationResult:
    """Fill globally enclosed SVG voids without changing original paint objects.
    填充由所有 SVG 颜色共同围成的孔洞，保留原始着色对象。

    Args:
        regions: Parsed polygon regions carrying RGB and optional paint metadata.
            已解析的面区域，带 RGB 和可选着色身份信息。
        silhouette: Original SVG silhouette in source coordinates.
            原始 SVG 坐标系中的轮廓。
        scale_factor: Positive millimetres per source coordinate unit.
            每个原始坐标单位对应的正毫米数。
        max_hole_area_mm2: Fill voids at or below this area; zero disables it.
            填充面积不大于此值的孔洞；零关闭面积判断。
        max_hole_width_mm: Fill voids whose 2*area/perimeter meets this threshold.
            填充 2*面积/周长不大于此值的孔洞；零关闭宽度判断。

    Returns:
        Original regions plus patches and filled coverage. Equal-distance colors
        use ascending draw order, then source list index. Non-polygon fragments
        are reported separately; original input dictionaries are never mutated.
        原区域、补片和补偿后轮廓。等距颜色按绘制顺序、来源列表位置升序选择；
        非面片段单独记录，输入字典始终保持不变。

    Raises:
        ImportError: Enabled compensation requires its optional native extension.
            启用补偿时缺少所需原生扩展。
        ValueError: A physical setting or native coordinate is invalid.
            物理参数或原生坐标无效。
    """
    return _compensate_regions(
        regions, silhouette=silhouette, scale_factor=scale_factor,
        max_hole_area_mm2=max_hole_area_mm2, max_hole_width_mm=max_hole_width_mm,
        domain=None,
    )


def compensate_svg_regions_in_domain(
    regions: list[Region], *, silhouette: BaseGeometry, domain: SvgCoordinateDomain,
    max_hole_area_mm2: float = 0.5, max_hole_width_mm: float = 0.1,
) -> SvgHoleCompensationResult:
    """Keep optional source edits in the explicit SVG topology domain.

    将可选补洞产生的新区域交回显式 SVG 拓扑域，保留原始区域对象。
    """
    return _compensate_regions(
        regions, silhouette=silhouette, scale_factor=domain.mm_per_unit,
        max_hole_area_mm2=max_hole_area_mm2, max_hole_width_mm=max_hole_width_mm,
        domain=domain,
    )


def _compensate_regions(
    regions: list[Region], *, silhouette: BaseGeometry, scale_factor: float,
    max_hole_area_mm2: float, max_hole_width_mm: float,
    domain: SvgCoordinateDomain | None,
) -> SvgHoleCompensationResult:
    started = perf_counter()
    _validate_settings(scale_factor, max_hole_area_mm2, max_hole_width_mm)
    polygon_regions, source_indices, fragments = _polygon_regions(regions)
    if max_hole_area_mm2 == 0 and max_hole_width_mm == 0:
        return SvgHoleCompensationResult(
            polygon_regions, silhouette, elapsed_seconds=perf_counter() - started,
            unprintable_fragments=fragments,
        )
    try:
        native = import_module("lumina_svg_core._lumina_svg_compensation")
    except ImportError as exc:
        raise ImportError(
            "Install or rebuild lumina-svg-core with its SVG compensation extension "
            "(_lumina_svg_compensation) before enabling source-SVG hole compensation."
        ) from exc
    holes_mm, coverage_mm = native.find_holes_mm(
        _rings_mm(polygon_regions, scale_factor), max_hole_area_mm2, max_hole_width_mm
    )
    if not holes_mm:
        return SvgHoleCompensationResult(
            polygon_regions, silhouette, elapsed_seconds=perf_counter() - started,
            unprintable_fragments=fragments,
        )
    holes = (_polygons_in_working_space(holes_mm, domain) if domain is not None
             else _polygons_in_source_space(holes_mm, scale_factor))
    owners = _nearest_sources(holes, polygon_regions, source_indices)
    patches = [
        _patch(hole, polygon_regions[owner], source_indices[owner])
        for hole, owner in zip(holes, owners)
    ]
    coverage = (_polygons_in_working_space(coverage_mm, domain) if domain is not None
                else _polygons_in_source_space(coverage_mm, scale_factor))
    filled_silhouette = coverage[0] if len(coverage) == 1 else MultiPolygon(coverage)
    if domain is not None:
        filled_silhouette = domain.restore_precision(filled_silhouette)
    return SvgHoleCompensationResult(
        regions=[*polygon_regions, *patches],
        silhouette=filled_silhouette,
        patches=patches,
        filled_holes=len(holes),
        added_area_mm2=sum(hole.area for hole in holes) * scale_factor**2,
        elapsed_seconds=perf_counter() - started,
        unprintable_fragments=fragments,
    )
