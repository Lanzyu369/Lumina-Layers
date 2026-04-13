"""Reusable printable-feature optimization for polygonal shape records.

可复用的多边形形状记录可打印性优化模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Iterable, Mapping, Optional

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid

from config import PrinterConfig, VectorConfig


_MIN_AREA_EPSILON = 1e-9
_SHARED_BOUNDARY_EPSILON = 1e-7
_ISOLATED_MAX_DIMENSION_MULTIPLIER = 1.6
_ISOLATED_MIN_COMPACTNESS = 0.42
_THIN_MIN_ASPECT_RATIO = 2.4
_THIN_MAX_COMPACTNESS = 0.32
_MITRE_LIMIT = 2.0
_WIDEN_ATTEMPTS = 4
_WIDEN_STEP_RATIO = 0.12


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_polygonal_geometry(geometry):
    """Return a polygonal geometry or ``None`` if nothing valid remains.

    返回可用的多边形几何；若无法保留有效多边形则返回 ``None``。
    """
    if geometry is None or getattr(geometry, "is_empty", True):
        return None

    candidate = geometry
    if not getattr(candidate, "is_valid", True):
        try:
            candidate = make_valid(candidate)
        except Exception:
            candidate = candidate.buffer(0)

    if candidate is None or getattr(candidate, "is_empty", True):
        return None

    if isinstance(candidate, Polygon):
        return candidate

    if isinstance(candidate, MultiPolygon):
        polygons = [poly for poly in candidate.geoms if not poly.is_empty and poly.area > _MIN_AREA_EPSILON]
        if not polygons:
            return None
        return MultiPolygon(polygons) if len(polygons) > 1 else polygons[0]

    if isinstance(candidate, GeometryCollection):
        polygon_parts = []
        for part in candidate.geoms:
            normalized = _normalize_polygonal_geometry(part)
            if normalized is None:
                continue
            if isinstance(normalized, Polygon):
                polygon_parts.append(normalized)
            elif isinstance(normalized, MultiPolygon):
                polygon_parts.extend([poly for poly in normalized.geoms if not poly.is_empty])
        if not polygon_parts:
            return None
        merged = unary_union(polygon_parts)
        return _normalize_polygonal_geometry(merged)

    return None


def _compactness(geometry) -> float:
    """Compute a bounded compactness score in the range 0..1.

    计算限定在 0..1 之间的紧凑度分数。
    """
    if geometry is None or getattr(geometry, "is_empty", True):
        return 0.0

    perimeter = float(getattr(geometry, "length", 0.0))
    area = float(getattr(geometry, "area", 0.0))
    if perimeter <= _MIN_AREA_EPSILON or area <= _MIN_AREA_EPSILON:
        return 0.0
    return max(0.0, min(1.0, (4.0 * 3.141592653589793 * area) / (perimeter * perimeter)))


def _geometry_dimensions_mm(geometry, scale_factor: float) -> tuple[float, float]:
    """Return geometry width/height in millimeters.

    以毫米为单位返回几何宽高。
    """
    min_x, min_y, max_x, max_y = geometry.bounds
    return (max(0.0, (max_x - min_x) * scale_factor), max(0.0, (max_y - min_y) * scale_factor))


def _geometry_area_mm2(geometry, scale_factor: float) -> float:
    """Return geometry area converted to mm^2.

    将几何面积换算为 mm²。
    """
    if geometry is None or getattr(geometry, "is_empty", True):
        return 0.0
    return float(getattr(geometry, "area", 0.0)) * (scale_factor * scale_factor)


def _shared_boundary_length(a, b) -> float:
    """Return shared boundary length between two geometries.

    返回两个几何之间共享边界的长度。
    """
    try:
        boundary = a.boundary.intersection(b.boundary)
        return float(getattr(boundary, "length", 0.0))
    except Exception:
        return 0.0


def _same_recipe(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return left.get("recipe") == right.get("recipe")


@dataclass
class PrintableFeatureOptimizationItem:
    """Per-shape optimization outcome.

    单个形状记录的优化结果。
    """

    index: int
    draw_order: int
    classification: str
    action: str
    merged_into_index: Optional[int] = None
    merge_source_index: Optional[int] = None
    merge_source_recipe: Optional[list] = None
    merge_target_index: Optional[int] = None
    merge_target_recipe: Optional[list] = None
    merge_recipe_changed: bool = False
    received_merge_source_indices: tuple[int, ...] = ()
    received_merge_source_recipes: tuple[tuple, ...] = ()
    widened_to_normal: bool = False
    source_area_mm2: float = 0.0
    output_area_mm2: float = 0.0
    skip_reason: str = ""
    reason: str = ""


@dataclass
class PrintableFeatureOptimizationResult:
    """Structured optimization result for downstream logging.

    面向下游日志记录的结构化优化结果。
    """

    records: list[dict]
    items: list[PrintableFeatureOptimizationItem]
    classification_counts: dict[str, int]
    action_counts: dict[str, int]
    timings_ms: dict[str, float]


class PrintableFeatureOptimizer:
    """Optimize polygon shape records for printable-core constraints.

    对多边形形状记录执行可打印核心约束优化。
    """

    def __init__(
        self,
        shape_records: Iterable[Mapping[str, Any]],
        scale_factor: float,
        printable_core_nozzle_multiplier: float | None = None,
        nozzle_width_mm: float | None = None,
    ) -> None:
        self._scale_factor = _as_float(scale_factor, 0.0)
        if self._scale_factor <= 0.0:
            raise ValueError("scale_factor must be positive")

        self._printable_core_nozzle_multiplier = _as_float(
            printable_core_nozzle_multiplier,
            VectorConfig.PRINTABLE_CORE_NOZZLE_MULTIPLIER,
        )
        self._nozzle_width_mm = _as_float(nozzle_width_mm, PrinterConfig.NOZZLE_WIDTH)
        if self._nozzle_width_mm <= 0.0:
            raise ValueError("nozzle_width_mm must be positive")
        if self._printable_core_nozzle_multiplier <= 0.0:
            raise ValueError("printable_core_nozzle_multiplier must be positive")

        self._source_records: list[dict[str, Any]] = []
        for index, record in enumerate(shape_records):
            copied = dict(record)
            copied["_input_index"] = index
            copied["_original_geometry"] = copied.get("geometry")
            copied["geometry"] = _normalize_polygonal_geometry(copied.get("geometry"))
            self._source_records.append(copied)

    @property
    def printable_core_width_mm(self) -> float:
        """Return the target printable-core width in millimeters.

        返回目标可打印核心宽度（毫米）。
        """
        return self._nozzle_width_mm * self._printable_core_nozzle_multiplier

    @property
    def printable_core_erosion_mm(self) -> float:
        """Return the core erosion radius in millimeters.

        返回可打印核心腐蚀半径（毫米）。
        """
        return self.printable_core_width_mm * 0.5

    def optimize(self) -> PrintableFeatureOptimizationResult:
        """Optimize shape records and return structured results.

        优化形状记录并返回结构化结果。
        """
        t0 = perf_counter()
        sorted_records = sorted(
            self._source_records,
            key=lambda item: (int(item.get("draw_order", item["_input_index"])), item["_input_index"]),
        )
        live_records = {record["_input_index"]: record for record in sorted_records if record.get("geometry") is not None}
        active_records: list[dict[str, Any]] = []

        items_by_input_index: dict[int, PrintableFeatureOptimizationItem] = {}
        classification_counts = {"normal": 0, "isolated": 0, "thin": 0, "skip": 0}
        action_counts = {"keep": 0, "widen": 0, "merge": 0, "skip": 0}
        classify_ms = 0.0
        action_ms = 0.0

        for record in sorted_records:
            original_geometry = record.get("_original_geometry")
            normalized_geometry = record.get("geometry")
            source_area_mm2 = _geometry_area_mm2(original_geometry or normalized_geometry, self._scale_factor)

            if normalized_geometry is None:
                skip_reason = self._skip_reason(record)
                items_by_input_index[record["_input_index"]] = PrintableFeatureOptimizationItem(
                    index=int(record["_input_index"]),
                    draw_order=int(record.get("draw_order", record["_input_index"])),
                    classification="skip",
                    action="skip",
                    source_area_mm2=source_area_mm2,
                    output_area_mm2=0.0,
                    skip_reason=skip_reason,
                    reason=skip_reason,
                )
                classification_counts["skip"] += 1
                action_counts["skip"] += 1
                continue

            item_start = perf_counter()
            classification = self.classify(normalized_geometry)
            classify_ms += (perf_counter() - item_start) * 1000.0
            classification_counts[classification] += 1

            action_start = perf_counter()
            output_area = source_area_mm2
            merged_into_index: Optional[int] = None
            action = "keep"
            reason = ""
            widened_to_normal = False
            merge_info = None

            if classification == "normal":
                active_records.append(record)
            elif classification == "isolated":
                target = self._select_best_neighbor(record, live_records.values())
                if target is not None:
                    merge_info = self._merge_record_into_target(record, target)
                    merged_into_index = int(target["_input_index"])
                    action = "merge"
                    reason = "isolated"
                    output_area = 0.0
                    live_records.pop(int(record["_input_index"]), None)
                    self._update_target_receipt(target, record, merge_info)
                else:
                    active_records.append(record)
                    reason = "no-neighbor"
            elif classification == "thin":
                widened = self._widen_to_printable_core(record["geometry"])
                if widened is not None and self.classify(widened) == "normal":
                    record["geometry"] = widened
                    output_area = _geometry_area_mm2(widened, self._scale_factor)
                    action = "widen"
                    reason = "widened-to-core"
                    widened_to_normal = True
                    active_records.append(record)
                else:
                    target = self._select_best_neighbor(record, live_records.values())
                    if target is not None:
                        merge_info = self._merge_record_into_target(record, target)
                        merged_into_index = int(target["_input_index"])
                        action = "merge"
                        reason = "thin-fallback-merge"
                        output_area = 0.0
                        live_records.pop(int(record["_input_index"]), None)
                        self._update_target_receipt(target, record, merge_info)
                    else:
                        active_records.append(record)
                        reason = "thin-no-neighbor"
            else:
                reason = "unknown"

            action_ms += (perf_counter() - action_start) * 1000.0
            action_counts[action] += 1

            items_by_input_index[record["_input_index"]] = self._build_item(
                record=record,
                classification=classification,
                action=action,
                source_area_mm2=source_area_mm2,
                output_area_mm2=output_area,
                merged_into_index=merged_into_index,
                reason=reason,
                widened_to_normal=widened_to_normal,
                merge_info=merge_info if action == "merge" else None,
            )

        ordered_survivors = sorted(
            active_records,
            key=lambda item: (int(item.get("draw_order", item["_input_index"])), int(item["_input_index"])),
        )
        final_records = [self._public_record(record) for record in ordered_survivors]

        timings_ms = {
            "classify": classify_ms,
            "action": action_ms,
            "total": (perf_counter() - t0) * 1000.0,
        }

        for record in active_records:
            item = items_by_input_index.get(int(record["_input_index"]))
            if item is None:
                continue
            item.received_merge_source_indices = tuple(record.get("_received_merge_source_indices", ()))
            item.received_merge_source_recipes = tuple(record.get("_received_merge_source_recipes", ()))
            if item.action in {"keep", "widen"}:
                item.output_area_mm2 = _geometry_area_mm2(record.get("geometry"), self._scale_factor)

        items = [items_by_input_index[index] for index in sorted(items_by_input_index)]
        return PrintableFeatureOptimizationResult(
            records=final_records,
            items=items,
            classification_counts=classification_counts,
            action_counts=action_counts,
            timings_ms=timings_ms,
        )

    def classify(self, geometry) -> str:
        """Classify a polygonal geometry as normal, isolated, or thin.

        将多边形几何分类为 normal、isolated 或 thin。
        """
        normalized = _normalize_polygonal_geometry(geometry)
        if normalized is None or normalized.area <= _MIN_AREA_EPSILON:
            return "isolated"

        erosion_svg = self.printable_core_erosion_mm / self._scale_factor
        core = normalized.buffer(-erosion_svg, join_style="mitre", mitre_limit=_MITRE_LIMIT)
        core = _normalize_polygonal_geometry(core)
        if core is not None and getattr(core, "area", 0.0) > _MIN_AREA_EPSILON:
            return "normal"

        max_dim_mm, min_dim_mm = self._geometry_span_mm(normalized)
        compactness = _compactness(normalized)
        if (
            max_dim_mm <= self.printable_core_width_mm * _ISOLATED_MAX_DIMENSION_MULTIPLIER
            and min_dim_mm <= self.printable_core_width_mm * _ISOLATED_MAX_DIMENSION_MULTIPLIER
            and compactness >= _ISOLATED_MIN_COMPACTNESS
        ):
            return "isolated"

        aspect_ratio = max_dim_mm / max(min_dim_mm, 1e-9)
        if aspect_ratio >= _THIN_MIN_ASPECT_RATIO or compactness <= _THIN_MAX_COMPACTNESS:
            return "thin"

        return "isolated"

    def _geometry_span_mm(self, geometry) -> tuple[float, float]:
        width_mm, height_mm = _geometry_dimensions_mm(geometry, self._scale_factor)
        max_dim = max(width_mm, height_mm)
        min_dim = min(width_mm, height_mm)
        return max_dim, min_dim

    def _widen_to_printable_core(self, geometry):
        """Expand a thin geometry to the printable-core target when possible.

        尝试将细长几何扩展到可打印核心目标宽度。
        """
        normalized = _normalize_polygonal_geometry(geometry)
        if normalized is None:
            return None

        _, min_dim_mm = self._geometry_span_mm(normalized)
        if min_dim_mm <= 0.0:
            return None

        base_delta_mm = max(0.0, (self.printable_core_width_mm - min_dim_mm) * 0.5)
        if base_delta_mm <= _MIN_AREA_EPSILON:
            return _normalize_polygonal_geometry(normalized)

        step_mm = max(0.01, self.printable_core_width_mm * _WIDEN_STEP_RATIO)
        best_candidate = None
        for attempt in range(_WIDEN_ATTEMPTS + 1):
            delta_mm = base_delta_mm + (step_mm * attempt)
            delta_svg = delta_mm / self._scale_factor
            widened = normalized.buffer(delta_svg, join_style="mitre", mitre_limit=_MITRE_LIMIT)
            widened = _normalize_polygonal_geometry(widened)
            if widened is None or widened.area <= _MIN_AREA_EPSILON:
                continue
            best_candidate = widened
            if self.classify(widened) == "normal":
                return widened

        return None if best_candidate is None else best_candidate

    def _select_best_neighbor(self, record: Mapping[str, Any], records: list[dict[str, Any]]):
        """Pick the best merge target using shared boundary, distance, and recipe ties.

        按共享边界、距离和 recipe 兼容性选择最佳合并目标。
        """
        candidates = []
        source_geometry = record.get("geometry")
        if source_geometry is None:
            return None

        for candidate in records:
            if candidate["_input_index"] == record["_input_index"]:
                continue
            target_geometry = candidate.get("geometry")
            if target_geometry is None:
                continue

            shared_boundary = _shared_boundary_length(source_geometry, target_geometry)
            try:
                distance = float(source_geometry.distance(target_geometry))
            except Exception:
                distance = float("inf")
            same_recipe = _same_recipe(record, candidate)
            candidates.append(
                (
                    0 if shared_boundary > _SHARED_BOUNDARY_EPSILON else 1,
                    distance,
                    0 if same_recipe else 1,
                    int(candidate.get("draw_order", candidate["_input_index"])),
                    int(candidate["_input_index"]),
                    candidate,
                )
            )

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[:-1])
        return candidates[0][-1]

    def _merge_record_into_target(self, source: Mapping[str, Any], target: dict[str, Any]) -> dict[str, Any]:
        """Merge source geometry into an existing target record in place.

        将源几何原地合并到目标记录中。
        """
        source_geometry = source.get("geometry")
        target_geometry = target.get("geometry")
        if source_geometry is None or target_geometry is None:
            return

        merged = unary_union([target_geometry, source_geometry])
        merged = _normalize_polygonal_geometry(merged)
        if merged is not None:
            target["geometry"] = merged
        return {
            "source_index": int(source["_input_index"]),
            "source_recipe": self._recipe_copy(source.get("recipe")),
            "target_index": int(target["_input_index"]),
            "target_recipe": self._recipe_copy(target.get("recipe")),
            "recipe_changed": source.get("recipe") != target.get("recipe"),
        }

    def _update_target_receipt(self, target: Mapping[str, Any], source: Mapping[str, Any], merge_info: Mapping[str, Any]) -> None:
        """Record inbound merge provenance on the target record.

        在目标记录上登记入站合并来源。
        """
        source_index = int(merge_info["source_index"])
        source_recipe = tuple(merge_info["source_recipe"] or ())
        target.setdefault("_received_merge_source_indices", [])
        target.setdefault("_received_merge_source_recipes", [])
        target["_received_merge_source_indices"].append(source_index)
        target["_received_merge_source_recipes"].append(source_recipe)

    def _recipe_copy(self, recipe):
        """Return a stable copy of a recipe list for result metadata.

        为结果元数据返回稳定的 recipe 拷贝。
        """
        if recipe is None:
            return None
        if isinstance(recipe, list):
            return list(recipe)
        if isinstance(recipe, tuple):
            return list(recipe)
        try:
            return list(recipe)
        except TypeError:
            return [recipe]

    def _build_item(
        self,
        record: Mapping[str, Any],
        classification: str,
        action: str,
        source_area_mm2: float,
        output_area_mm2: float,
        merged_into_index: Optional[int] = None,
        reason: str = "",
        widened_to_normal: bool = False,
        merge_info: Optional[Mapping[str, Any]] = None,
    ) -> PrintableFeatureOptimizationItem:
        """Build a structured optimization item with explicit provenance."""

        item = PrintableFeatureOptimizationItem(
            index=int(record["_input_index"]),
            draw_order=int(record.get("draw_order", record["_input_index"])),
            classification=classification,
            action=action,
            merged_into_index=merged_into_index,
            source_area_mm2=source_area_mm2,
            output_area_mm2=output_area_mm2,
            skip_reason=reason if action == "skip" else "",
            reason=reason,
            widened_to_normal=widened_to_normal,
        )

        if merge_info is not None:
            item.merge_source_index = int(merge_info["source_index"])
            item.merge_source_recipe = self._recipe_copy(merge_info.get("source_recipe"))
            item.merge_target_index = int(merge_info["target_index"])
            item.merge_target_recipe = self._recipe_copy(merge_info.get("target_recipe"))
            item.merge_recipe_changed = bool(merge_info.get("recipe_changed", False))

        return item

    def _skip_reason(self, record: Mapping[str, Any]) -> str:
        """Derive a stable skip reason for normalized-away inputs.

        为归一化后消失的输入推导稳定的跳过原因。
        """
        original_geometry = record.get("_original_geometry")
        if original_geometry is None:
            return "missing-geometry"
        if getattr(original_geometry, "is_empty", False) or getattr(original_geometry, "area", 0.0) <= _MIN_AREA_EPSILON:
            return "empty-geometry"
        return "normalized-away"

    def _public_record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Strip internal bookkeeping keys before returning the result.

        返回结果前去除内部 bookkeeping 字段。
        """
        public = dict(record)
        public.pop("_input_index", None)
        public.pop("_original_geometry", None)
        public.pop("_received_merge_source_indices", None)
        public.pop("_received_merge_source_recipes", None)
        return public
