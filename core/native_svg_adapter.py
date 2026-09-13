"""Thin, fail-closed adapter for the standalone native SVG geometry engine."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import os
import time
from types import ModuleType
from typing import Any

import numpy as np
import shapely

from core.errors import (
    NativeSvgInternalError,
    NativeSvgInvalidError,
    NativeSvgResourceLimitError,
)
from core.native_svg_limits import NATIVE_SVG_MAX_BYTES


NATIVE_RESULT_SCHEMA_VERSION = 4
_SOURCE_KIND_FILL = 0
_SOURCE_KIND_STROKE = 1
_SOURCE_KIND_COMPOSITE = 3


@dataclass(frozen=True)
class NativeSvgFallback:
    """Request one whole-document execution of Lumina's legacy SVG path.

    请求 Lumina 对整份文档执行一次旧 SVG 链路。
    """

    reason_code: str
    native_version: str


@dataclass(frozen=True)
class NativeSvgPaintContributor:
    """One exact SVG paint contribution to a visible composite region.

    一个可见复合区域中来自 SVG paint op 的精确贡献。
    """

    native_draw_order: int
    native_source_index: int
    source_kind: str
    weight: float

    @property
    def native_paint_id(self) -> tuple[int, int]:
        """Return the stable source/draw identity for this paint operation.

        返回该 paint 操作稳定的 source/draw 身份。
        """

        return (self.native_source_index, self.native_draw_order)


@dataclass(frozen=True)
class NativeSvgUnprintableFragment:
    """One non-area SVG fragment excluded from polygon collections.

    一段因不具备二维面积而未进入 Polygon 集合的 SVG 片段。

    A composite-only diagnostic has no single paint owner and therefore uses
    ``native_paint_id=None``. 复合区域诊断没有单一 paint 归属，因此其
    ``native_paint_id`` 为 ``None``。
    """

    reason_code: str
    rgba: tuple[int, int, int, int]
    rgba_f64: tuple[float, float, float, float]
    source_kind: str
    native_draw_order: int
    native_source_index: int
    native_paint_id: tuple[int, int] | None
    subpath_index: int


@dataclass
class NativeSvgGeometry:
    """Lumina-compatible parse/clip payload built from immutable native arrays.

    从不可变原生数组构建、兼容 Lumina 的解析与裁剪结果。
    """

    shape_data: list[dict[str, Any]]
    clipped_shapes: list[dict[str, Any]]
    silhouette: Any
    scale_factor: float
    bbox: tuple[float, float, float, float]
    stage_timings: dict[str, Any]
    native_version: str
    native_schema_version: int
    unprintable_fragments: tuple[NativeSvgUnprintableFragment, ...] = field(
        default_factory=tuple
    )
    geometry_backend: str = field(default="native", init=False)
    image_vectorizer_bounds: Any | None = None


def _load_native_module() -> ModuleType:
    return importlib.import_module("lumina_svg_core")


def native_runtime_identity() -> tuple[str, str, int]:
    """Return the cache identity for the available native runtime.

    返回当前可用原生运行时的缓存身份；不可用时返回稳定的 legacy 身份。

    Returns:
        ``("native", version, schema)`` when import succeeds, otherwise a
        stable dependency-unavailable tuple used only to isolate cache keys.
        导入成功时返回原生版本身份，否则返回稳定的依赖缺失身份。
    """

    try:
        module = _load_native_module()
    except (ImportError, OSError):
        return ("legacy", "native_dependency_unavailable", 0)
    try:
        runtime_schema = int(getattr(module, "RESULT_SCHEMA_VERSION"))
    except (AttributeError, TypeError, ValueError, OverflowError):
        runtime_schema = 0
    return (
        "native",
        str(getattr(module, "__version__", "unknown")),
        runtime_schema,
    )


def _native_array(
    value: Any,
    *,
    dtype: np.dtype[Any],
    ndim: int,
    reason_code: str,
) -> np.ndarray:
    """Validate one immutable C-contiguous native ABI array.

    验证一个只读、C 连续的原生 ABI 数组。
    """

    if (
        not isinstance(value, np.ndarray)
        or value.dtype != dtype
        or value.ndim != ndim
        or not value.flags.c_contiguous
        or value.flags.writeable
    ):
        raise NativeSvgInternalError(
            "The native SVG result returned an incompatible NumPy array.",
            reason_code=reason_code,
        )
    return value


def _collection_geometries(collection: Any, grid_to_source_unit: float):
    integer_coordinates = _native_array(
        collection.coordinates,
        dtype=np.dtype(np.int64),
        ndim=2,
        reason_code="invalid_coordinate_schema",
    )
    if integer_coordinates.shape[1:] != (2,):
        raise NativeSvgInternalError(
            "The native SVG result returned an invalid coordinate array.",
            reason_code="invalid_coordinate_schema",
        )
    coordinates = np.multiply(
        integer_coordinates,
        grid_to_source_unit,
        dtype=np.float64,
    )
    offsets = (
        _native_array(
            collection.ring_offsets,
            dtype=np.dtype(np.uint64),
            ndim=1,
            reason_code="invalid_offset_schema",
        ),
        _native_array(
            collection.polygon_offsets,
            dtype=np.dtype(np.uint64),
            ndim=1,
            reason_code="invalid_offset_schema",
        ),
        _native_array(
            collection.geometry_offsets,
            dtype=np.dtype(np.uint64),
            ndim=1,
            reason_code="invalid_offset_schema",
        ),
    )
    expected_endpoints = (
        len(coordinates),
        max(0, len(offsets[0]) - 1),
        max(0, len(offsets[1]) - 1),
    )
    for offset, expected_endpoint in zip(
        offsets, expected_endpoints, strict=True
    ):
        if (
            offset.ndim != 1
            or len(offset) == 0
            or int(offset[0]) != 0
            or int(offset[-1]) != expected_endpoint
            or np.any(offset[1:] < offset[:-1])
        ):
            raise NativeSvgInternalError(
                "The native SVG result returned invalid ragged offsets.",
                reason_code="invalid_offset_schema",
            )
    ring_count = len(offsets[0]) - 1
    geometry_count = len(offsets[2]) - 1
    if int(collection.geometry_count) != geometry_count:
        raise NativeSvgInternalError(
            "The native SVG result returned an inconsistent geometry count.",
            reason_code="invalid_offset_schema",
        )
    hole_parent = _native_array(
        collection.hole_parent,
        dtype=np.dtype(np.int64),
        ndim=1,
        reason_code="invalid_hole_schema",
    )
    if hole_parent.shape != (ring_count,):
        raise NativeSvgInternalError(
            "The native SVG result returned invalid hole metadata.",
            reason_code="invalid_hole_schema",
        )
    ring_starts = offsets[0][:-1]
    ring_ends = offsets[0][1:]
    ring_starts_index = ring_starts.astype(np.intp, copy=False)
    ring_ends_index = ring_ends.astype(np.intp, copy=False)
    if ring_count and (
        np.any(ring_ends - ring_starts < 4)
        or not np.array_equal(
            integer_coordinates[ring_starts_index],
            integer_coordinates[ring_ends_index - 1],
        )
    ):
        raise NativeSvgInternalError(
            "The native SVG result returned an invalid closed ring.",
            reason_code="invalid_ring_schema",
        )
    if ring_count and np.any(
        (hole_parent < -1)
        | (hole_parent >= np.arange(ring_count, dtype=np.int64))
    ):
        raise NativeSvgInternalError(
            "The native SVG result returned invalid hole metadata.",
            reason_code="invalid_hole_schema",
        )
    polygon_starts = offsets[1][:-1]
    polygon_ends = offsets[1][1:]
    if len(polygon_starts):
        if np.any(polygon_starts >= polygon_ends):
            raise NativeSvgInternalError(
                "The native SVG result returned invalid component hierarchy.",
                reason_code="invalid_hole_schema",
            )
        expected_parents = np.repeat(
            polygon_starts.astype(np.int64, copy=False),
            (polygon_ends - polygon_starts).astype(np.intp, copy=False),
        )
        expected_parents[polygon_starts.astype(np.intp, copy=False)] = -1
        if not np.array_equal(hole_parent, expected_parents):
            raise NativeSvgInternalError(
                "The native SVG result returned invalid component hierarchy.",
                reason_code="invalid_hole_schema",
            )
    return shapely.from_ragged_array(
        shapely.GeometryType.MULTIPOLYGON,
        coordinates,
        offsets,
    )


@dataclass(frozen=True)
class _CollectionPaintMetadata:
    rgba: np.ndarray
    rgba_f64: np.ndarray
    draw_indices: np.ndarray
    source_indices: np.ndarray
    source_kinds: np.ndarray
    contributor_offsets: np.ndarray
    contributor_draw_indices: np.ndarray
    contributor_source_indices: np.ndarray
    contributor_source_kinds: np.ndarray
    contributor_weights: np.ndarray


def _collection_paint_metadata(
    collection: Any,
    *,
    allow_composite: bool,
) -> _CollectionPaintMetadata:
    """Validate and return the native per-paint metadata arrays.

    验证并返回原生结果中逐 paint 的元数据数组。
    """

    rgba = _native_array(
        collection.rgba,
        dtype=np.dtype(np.uint8),
        ndim=2,
        reason_code="invalid_material_schema",
    )
    rgba_f64 = _native_array(
        collection.rgba_f64,
        dtype=np.dtype(np.float64),
        ndim=2,
        reason_code="invalid_material_schema",
    )
    draw_indices = _native_array(
        collection.draw_indices,
        dtype=np.dtype(np.int32),
        ndim=1,
        reason_code="invalid_draw_schema",
    )
    source_indices = _native_array(
        collection.source_indices,
        dtype=np.dtype(np.int32),
        ndim=1,
        reason_code="invalid_draw_schema",
    )
    source_kinds = _native_array(
        collection.source_kinds,
        dtype=np.dtype(np.int32),
        ndim=1,
        reason_code="invalid_source_schema",
    )
    contributor_offsets = _native_array(
        collection.contributor_offsets,
        dtype=np.dtype(np.uint64),
        ndim=1,
        reason_code="invalid_provenance_schema",
    )
    contributor_draw_indices = _native_array(
        collection.contributor_draw_indices,
        dtype=np.dtype(np.int32),
        ndim=1,
        reason_code="invalid_provenance_schema",
    )
    contributor_source_indices = _native_array(
        collection.contributor_source_indices,
        dtype=np.dtype(np.int32),
        ndim=1,
        reason_code="invalid_provenance_schema",
    )
    contributor_source_kinds = _native_array(
        collection.contributor_source_kinds,
        dtype=np.dtype(np.int32),
        ndim=1,
        reason_code="invalid_provenance_schema",
    )
    contributor_weights = _native_array(
        collection.contributor_weights,
        dtype=np.dtype(np.float64),
        ndim=1,
        reason_code="invalid_provenance_schema",
    )
    geometry_count = int(collection.geometry_count)
    geometry_shape = (geometry_count,)
    if (
        rgba.ndim != 2
        or rgba.shape != (geometry_count, 4)
        or rgba_f64.shape != (geometry_count, 4)
        or not np.all(np.isfinite(rgba_f64))
        or np.any((rgba_f64 < 0.0) | (rgba_f64 > 1.0))
    ):
        raise NativeSvgInternalError(
            "The native SVG result returned invalid material metadata.",
            reason_code="invalid_material_schema",
        )
    if (
        draw_indices.shape != geometry_shape
        or source_indices.shape != geometry_shape
    ):
        raise NativeSvgInternalError(
            "The native SVG result returned invalid draw-order metadata.",
            reason_code="invalid_draw_schema",
        )
    allowed_source_kind = (
        (source_kinds == _SOURCE_KIND_FILL)
        | (source_kinds == _SOURCE_KIND_STROKE)
    )
    if allow_composite:
        allowed_source_kind |= source_kinds == _SOURCE_KIND_COMPOSITE
    if source_kinds.shape != geometry_shape or np.any(~allowed_source_kind):
        raise NativeSvgInternalError(
            "The native SVG result returned invalid source metadata.",
            reason_code="invalid_source_schema",
        )
    expected_rgba = np.floor(rgba_f64 * 255.0 + 0.5).astype(np.uint8)
    if not np.array_equal(rgba, expected_rgba):
        raise NativeSvgInternalError(
            "The native SVG result returned inconsistent color metadata.",
            reason_code="invalid_material_schema",
        )

    contributor_count = len(contributor_draw_indices)
    if (
        contributor_offsets.shape != (geometry_count + 1,)
        or len(contributor_offsets) == 0
        or int(contributor_offsets[0]) != 0
        or int(contributor_offsets[-1]) != contributor_count
        or np.any(contributor_offsets[1:] <= contributor_offsets[:-1])
        or contributor_source_indices.shape != (contributor_count,)
        or contributor_source_kinds.shape != (contributor_count,)
        or contributor_weights.shape != (contributor_count,)
        or np.any(contributor_draw_indices < 0)
        or np.any(contributor_source_indices < 0)
        or np.any(
            (contributor_source_kinds != _SOURCE_KIND_FILL)
            & (contributor_source_kinds != _SOURCE_KIND_STROKE)
        )
        or not np.all(np.isfinite(contributor_weights))
        or np.any((contributor_weights <= 0.0) | (contributor_weights > 1.0))
    ):
        raise NativeSvgInternalError(
            "The native SVG result returned invalid paint provenance.",
            reason_code="invalid_provenance_schema",
        )
    for geometry_index in range(geometry_count):
        start = int(contributor_offsets[geometry_index])
        end = int(contributor_offsets[geometry_index + 1])
        kind = int(source_kinds[geometry_index])
        draw_index = int(draw_indices[geometry_index])
        source_index = int(source_indices[geometry_index])
        contributor_draws = contributor_draw_indices[start:end]
        if len(contributor_draws) > 1 and np.any(
            contributor_draws[1:] <= contributor_draws[:-1]
        ):
            raise NativeSvgInternalError(
                "The native SVG result returned unordered paint provenance.",
                reason_code="invalid_provenance_schema",
            )
        if kind == _SOURCE_KIND_COMPOSITE:
            identity_is_valid = (
                allow_composite
                and draw_index == -1
                and source_index == -1
                and end - start >= 2
            )
        else:
            identity_is_valid = (
                end - start == 1
                and draw_index == int(contributor_draw_indices[start])
                and source_index == int(contributor_source_indices[start])
                and kind == int(contributor_source_kinds[start])
            )
        weight_sum = float(np.sum(contributor_weights[start:end]))
        weight_tolerance = 1e-12 * max(1, end - start)
        if not identity_is_valid or not np.isclose(
            weight_sum,
            float(rgba_f64[geometry_index, 3]),
            rtol=0.0,
            atol=weight_tolerance,
        ):
            raise NativeSvgInternalError(
                "The native SVG result returned inconsistent paint provenance.",
                reason_code="invalid_provenance_schema",
            )
    return _CollectionPaintMetadata(
        rgba=rgba,
        rgba_f64=rgba_f64,
        draw_indices=draw_indices,
        source_indices=source_indices,
        source_kinds=source_kinds,
        contributor_offsets=contributor_offsets,
        contributor_draw_indices=contributor_draw_indices,
        contributor_source_indices=contributor_source_indices,
        contributor_source_kinds=contributor_source_kinds,
        contributor_weights=contributor_weights,
    )


def _paint_metadata_at(
    metadata: _CollectionPaintMetadata,
    geometry_index: int,
) -> dict[str, Any]:
    """Return one stable exact-paint identity record.

    返回一条稳定、精确的 paint 身份记录。
    """

    rgba = tuple(int(value) for value in metadata.rgba[geometry_index])
    rgba_f64 = tuple(
        float(value) for value in metadata.rgba_f64[geometry_index]
    )
    native_paint_index = int(metadata.draw_indices[geometry_index])
    native_source_index = int(metadata.source_indices[geometry_index])
    source_kind_index = int(metadata.source_kinds[geometry_index])
    contributor_start = int(metadata.contributor_offsets[geometry_index])
    contributor_end = int(metadata.contributor_offsets[geometry_index + 1])
    contributors = tuple(
        NativeSvgPaintContributor(
            native_draw_order=int(metadata.contributor_draw_indices[index]),
            native_source_index=int(
                metadata.contributor_source_indices[index]
            ),
            source_kind=(
                "stroke_only"
                if int(metadata.contributor_source_kinds[index])
                == _SOURCE_KIND_STROKE
                else "fill"
            ),
            weight=float(metadata.contributor_weights[index]),
        )
        for index in range(contributor_start, contributor_end)
    )
    source_kind = (
        "composite"
        if source_kind_index == _SOURCE_KIND_COMPOSITE
        else (
            "stroke_only"
            if source_kind_index == _SOURCE_KIND_STROKE
            else "fill"
        )
    )
    return {
        "color": rgba[:3],
        "rgba": rgba,
        "rgba_f64": rgba_f64,
        "source_kind": source_kind,
        "native_draw_order": native_paint_index,
        "native_paint_index": native_paint_index,
        "native_source_index": native_source_index,
        "native_paint_id": (
            None
            if source_kind_index == _SOURCE_KIND_COMPOSITE
            else (native_source_index, native_paint_index)
        ),
        "native_paint_contributors": contributors,
    }


def _validate_visible_provenance(
    raw: _CollectionPaintMetadata,
    visible: _CollectionPaintMetadata,
) -> None:
    """Confirm visible contributions exactly reference raw SVG paints.

    确认可见复合区域精确引用原始 SVG paint，并重建其预乘 RGB。
    """

    if len(visible.draw_indices) == 0:
        return
    if len(raw.draw_indices) == 0 or np.any(
        raw.draw_indices[1:] <= raw.draw_indices[:-1]
    ):
        raise NativeSvgInternalError(
            "The native SVG result returned inconsistent paint provenance.",
            reason_code="invalid_provenance_schema",
        )

    positions = np.searchsorted(
        raw.draw_indices, visible.contributor_draw_indices
    )
    if np.any(positions >= len(raw.draw_indices)):
        raise NativeSvgInternalError(
            "The native SVG result referenced a missing source paint.",
            reason_code="invalid_provenance_schema",
        )
    if (
        not np.array_equal(
            raw.draw_indices[positions],
            visible.contributor_draw_indices,
        )
        or not np.array_equal(
            raw.source_indices[positions],
            visible.contributor_source_indices,
        )
        or not np.array_equal(
            raw.source_kinds[positions],
            visible.contributor_source_kinds,
        )
    ):
        raise NativeSvgInternalError(
            "The native SVG result referenced a mismatched source paint.",
            reason_code="invalid_provenance_schema",
        )

    weighted_rgb = (
        raw.rgba_f64[positions, :3]
        * visible.contributor_weights[:, np.newaxis]
    )
    geometry_starts = visible.contributor_offsets[:-1].astype(
        np.intp, copy=False
    )
    reconstructed_rgb = np.add.reduceat(weighted_rgb, geometry_starts, axis=0)
    expected_rgb = (
        visible.rgba_f64[:, :3] * visible.rgba_f64[:, 3, np.newaxis]
    )
    contributor_counts = np.diff(visible.contributor_offsets).astype(
        np.float64, copy=False
    )
    tolerance = 1e-12 * np.maximum(1.0, contributor_counts)
    if not np.all(
        np.isclose(
            reconstructed_rgb,
            expected_rgb,
            rtol=0.0,
            atol=tolerance[:, np.newaxis],
        )
    ):
        raise NativeSvgInternalError(
            "The native SVG result returned inconsistent composite color.",
            reason_code="invalid_provenance_schema",
        )


def _unprintable_fragments(
    collection: Any,
) -> tuple[NativeSvgUnprintableFragment, ...]:
    """Validate and convert non-area fragment diagnostics.

    验证并转换不具备二维面积的片段诊断。
    """

    count = int(collection.count)
    if count < 0:
        raise NativeSvgInternalError(
            "The native SVG result returned an invalid fragment count.",
            reason_code="invalid_fragment_schema",
        )
    reason_codes = tuple(str(value) for value in collection.reason_codes)
    reason_ids = _native_array(
        collection.reason_ids,
        dtype=np.dtype(np.int32),
        ndim=1,
        reason_code="invalid_fragment_schema",
    )
    rgba = _native_array(
        collection.rgba,
        dtype=np.dtype(np.uint8),
        ndim=2,
        reason_code="invalid_fragment_schema",
    )
    rgba_f64 = _native_array(
        collection.rgba_f64,
        dtype=np.dtype(np.float64),
        ndim=2,
        reason_code="invalid_fragment_schema",
    )
    draw_indices = _native_array(
        collection.draw_indices,
        dtype=np.dtype(np.int32),
        ndim=1,
        reason_code="invalid_fragment_schema",
    )
    source_indices = _native_array(
        collection.source_indices,
        dtype=np.dtype(np.int32),
        ndim=1,
        reason_code="invalid_fragment_schema",
    )
    source_kinds = _native_array(
        collection.source_kinds,
        dtype=np.dtype(np.int32),
        ndim=1,
        reason_code="invalid_fragment_schema",
    )
    subpath_indices = _native_array(
        collection.subpath_indices,
        dtype=np.dtype(np.int32),
        ndim=1,
        reason_code="invalid_fragment_schema",
    )
    if (
        len(reason_codes) != count
        or reason_ids.shape != (count,)
        or rgba.shape != (count, 4)
        or rgba_f64.shape != (count, 4)
        or not np.all(np.isfinite(rgba_f64))
        or np.any((rgba_f64 < 0.0) | (rgba_f64 > 1.0))
        or draw_indices.shape != (count,)
        or source_indices.shape != (count,)
        or source_kinds.shape != (count,)
        or subpath_indices.shape != (count,)
        or np.any(
            (source_kinds != _SOURCE_KIND_FILL)
            & (source_kinds != _SOURCE_KIND_STROKE)
            & (source_kinds != _SOURCE_KIND_COMPOSITE)
        )
    ):
        raise NativeSvgInternalError(
            "The native SVG result returned invalid fragment metadata.",
            reason_code="invalid_fragment_schema",
        )
    allowed_reasons = {
        "empty_path",
        "point_only",
        "line_only",
        "area_collapse",
        "fill_rule_cancelled",
        "clipped_out",
        "stroke_collapse",
    }
    if any(reason not in allowed_reasons for reason in reason_codes):
        raise NativeSvgInternalError(
            "The native SVG result returned an unknown fragment reason.",
            reason_code="invalid_fragment_schema",
        )
    expected_rgba = np.floor(rgba_f64 * 255.0 + 0.5).astype(np.uint8)
    if not np.array_equal(rgba, expected_rgba):
        raise NativeSvgInternalError(
            "The native SVG result returned inconsistent fragment colors.",
            reason_code="invalid_fragment_schema",
        )

    fragments: list[NativeSvgUnprintableFragment] = []
    for index, reason_code in enumerate(reason_codes):
        exact_rgba = tuple(int(value) for value in rgba[index])
        exact_rgba_f64 = tuple(float(value) for value in rgba_f64[index])
        draw_index = int(draw_indices[index])
        source_index = int(source_indices[index])
        source_kind_index = int(source_kinds[index])
        is_composite = source_kind_index == _SOURCE_KIND_COMPOSITE
        fragments.append(
            NativeSvgUnprintableFragment(
                reason_code=reason_code,
                rgba=exact_rgba,
                rgba_f64=exact_rgba_f64,
                source_kind=(
                    "composite"
                    if is_composite
                    else (
                        "stroke_only"
                        if source_kind_index == _SOURCE_KIND_STROKE
                        else "fill"
                    )
                ),
                native_draw_order=draw_index,
                native_source_index=source_index,
                native_paint_id=(
                    None
                    if is_composite
                    else (source_index, draw_index)
                ),
                subpath_index=int(subpath_indices[index]),
            )
        )
    return tuple(fragments)


def _shape_data(
    metadata: _CollectionPaintMetadata,
    geometries: np.ndarray,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for geometry_index, geometry in enumerate(geometries):
        if geometry is None or geometry.is_empty:
            continue
        item = _paint_metadata_at(metadata, geometry_index)
        item.update(
            {
                "poly": geometry,
                "geometry_normalized": True,
            }
        )
        items.append(item)
    return items


def _visible_shapes(
    metadata: _CollectionPaintMetadata,
    geometries: np.ndarray,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for geometry_index, geometry in enumerate(geometries):
        if geometry is None or geometry.is_empty:
            continue
        components = (
            geometry.geoms
            if geometry.geom_type == "MultiPolygon"
            else (geometry,)
        )
        paint_metadata = _paint_metadata_at(metadata, geometry_index)
        for component_index, component in enumerate(components):
            if component.is_empty:
                continue
            item = dict(paint_metadata)
            item.update(
                {
                    "geometry": component,
                    "draw_order": len(items),
                    "native_component_index": component_index,
                    "geometry_normalized": True,
                }
            )
            items.append(item)
    return items


def _invalid_result(reason_code: str) -> None:
    if reason_code == "empty_geometry":
        # Preserve VectorProcessor's established public error contract even
        # when the native fill-only policy removes every recorded stroke.
        raise ValueError("No valid shapes found in SVG")
    if reason_code == "invalid_svg":
        raise ValueError("Invalid SVG document.")
    if reason_code in {"invalid_physical_parameters", "numeric_range_error"}:
        detail = (
            "Native SVG geometry exceeds the supported numeric range."
            if reason_code == "numeric_range_error"
            else "Native SVG physical parameters must be positive and finite."
        )
        raise NativeSvgInvalidError(detail, reason_code=reason_code)
    raise NativeSvgInternalError(
        f"The native SVG engine failed ({reason_code or 'unknown_error'}).",
        reason_code=reason_code or "unknown_error",
    )


def analyze_native_svg(
    svg_path: str,
    target_width_mm: float,
    tolerance_mm: float,
    *,
    expand_stroke_to_fill: bool = False,
) -> NativeSvgGeometry | NativeSvgFallback:
    """Analyze one SVG with the native engine or request whole-file fallback.

    使用原生引擎分析一份 SVG；遇到不支持的明确语义时，请求整份文档回退。

    Args:
        svg_path: SVG filesystem path. SVG 文件系统路径。
        target_width_mm: Requested physical model width. 目标模型物理宽度。
        tolerance_mm: One total physical error budget. 统一物理误差预算。
        expand_stroke_to_fill: Preserve Lumina's existing stroke policy. If
            false, stroke paint operations are ignored just as in the legacy
            fill-only path; if true, unsupported stroke semantics fail closed.
            是否沿用 Lumina 的描边展开策略；关闭时与旧填充链一致忽略描边，
            开启时遇到不支持的描边语义会整份文档回退。

    Returns:
        Native-compatible geometry on success, or a whole-document fallback
        request for explicitly unsupported semantics. 成功时返回原生几何，
        明确不支持时返回整份文档回退请求。

    Raises:
        ValueError: The SVG is invalid or has no printable fill geometry.
        NativeSvgInvalidError: Physical input exceeds the numeric contract.
        NativeSvgResourceLimitError: Input exceeds a deterministic resource
            budget and must not be retried through the legacy parser.
        NativeSvgInternalError: ABI/schema/native processing failed.
    """

    try:
        if os.path.getsize(svg_path) > NATIVE_SVG_MAX_BYTES:
            raise NativeSvgResourceLimitError()
    except OSError:
        # Preserve the native boundary's existing invalid-path behavior.
        pass

    try:
        module = _load_native_module()
    except (ImportError, OSError):
        return NativeSvgFallback(
            reason_code="native_dependency_unavailable",
            native_version="unavailable",
        )
    native_version = str(getattr(module, "__version__", "unknown"))
    call_started = time.perf_counter()
    result = module.analyze_svg(
        svg_path,
        target_width_mm,
        tolerance_mm,
        bool(expand_stroke_to_fill),
    )
    native_call_seconds = time.perf_counter() - call_started

    if result.status == "unsupported":
        reason_code = str(
            result.reason_code or "unsupported_svg_semantics"
        )
        if reason_code in {
            "unsupported_complexity",
            "unsupported_input_complexity",
        }:
            raise NativeSvgResourceLimitError(reason_code=reason_code)
        return NativeSvgFallback(
            reason_code=reason_code,
            native_version=native_version,
        )
    if result.status != "supported":
        reason_code = str(result.reason_code or "unknown_error")
        _invalid_result(reason_code)
    if int(result.schema_version) != NATIVE_RESULT_SCHEMA_VERSION:
        raise NativeSvgInternalError(
            "The native SVG result schema is incompatible with Lumina.",
            reason_code="native_schema_mismatch",
        )

    adapter_started = time.perf_counter()
    grid_to_source_unit = float(result.grid_to_source_unit)
    scale_factor = float(result.scale_factor)
    bbox = tuple(float(value) for value in result.bbox)
    if (
        not np.isfinite(grid_to_source_unit)
        or grid_to_source_unit <= 0.0
        or not np.isfinite(scale_factor)
        or scale_factor <= 0.0
        or len(bbox) != 4
        or not np.all(np.isfinite(bbox))
        or bbox[2] <= 0.0
        or bbox[3] <= 0.0
    ):
        raise NativeSvgInternalError(
            "The native SVG result returned an invalid coordinate domain.",
            reason_code="invalid_coordinate_domain",
        )
    raw_geometries = _collection_geometries(
        result.raw, grid_to_source_unit
    )
    visible_geometries = _collection_geometries(
        result.visible, grid_to_source_unit
    )
    silhouette_geometries = _collection_geometries(
        result.silhouette, grid_to_source_unit
    )
    input_paint_count = int(result.input_paint_count)
    if (
        input_paint_count < 0
        or input_paint_count < int(result.raw.geometry_count)
    ):
        raise NativeSvgInternalError(
            "The native SVG result returned an invalid paint count.",
            reason_code="invalid_fragment_schema",
        )
    unprintable_fragments = _unprintable_fragments(
        result.unprintable_fragments
    )
    unprintable_reason_counts: dict[str, int] = {}
    for fragment in unprintable_fragments:
        unprintable_reason_counts[fragment.reason_code] = (
            unprintable_reason_counts.get(fragment.reason_code, 0) + 1
        )
    if (
        int(result.raw.geometry_count) == 0
        and int(result.visible.geometry_count) == 0
        and int(result.silhouette.geometry_count) == 0
    ):
        # The native parser successfully classified the document, but Lumina's
        # product pipeline still has no area-bearing shape to analyze.
        _invalid_result("empty_geometry")
    if len(silhouette_geometries) != 1 or silhouette_geometries[0].is_empty:
        raise NativeSvgInternalError(
            "The native SVG result returned an invalid silhouette.",
            reason_code="invalid_silhouette_schema",
        )
    raw_metadata = _collection_paint_metadata(
        result.raw, allow_composite=False
    )
    visible_metadata = _collection_paint_metadata(
        result.visible, allow_composite=True
    )
    _validate_visible_provenance(raw_metadata, visible_metadata)
    shape_data = _shape_data(raw_metadata, raw_geometries)
    clipped_shapes = _visible_shapes(visible_metadata, visible_geometries)
    if not shape_data or not clipped_shapes:
        _invalid_result("empty_geometry")
    adapter_seconds = time.perf_counter() - adapter_started

    image_vectorizer_bounds = None
    if bool(getattr(result, "image_vectorizer_origin", False)):
        viewport_bounds = tuple(
            float(value) for value in result.viewport_bounds
        )
        viewport_x, viewport_y, viewport_width, viewport_height = (
            viewport_bounds
        )
        if (
            np.all(np.isfinite(viewport_bounds))
            and viewport_width > 0
            and viewport_height > 0
        ):
            image_vectorizer_bounds = shapely.box(
                viewport_x,
                viewport_y,
                viewport_x + viewport_width,
                viewport_y + viewport_height,
            )

    native_result_conversion_seconds = float(
        getattr(result, "result_conversion_seconds", 0.0)
    )
    return NativeSvgGeometry(
        shape_data=shape_data,
        clipped_shapes=clipped_shapes,
        silhouette=silhouette_geometries[0],
        scale_factor=scale_factor,
        bbox=bbox,
        stage_timings={
            "native_svg_s": native_call_seconds,
            "native_recorder_s": float(
                getattr(result, "recorder_seconds", 0.0)
            ),
            "native_kernel_s": float(
                getattr(result, "kernel_seconds", 0.0)
            ),
            "native_bounds_s": float(
                getattr(result, "bounds_seconds", 0.0)
            ),
            "native_replay_s": float(
                getattr(result, "replay_seconds", 0.0)
            ),
            "native_replay_worker_count": int(
                getattr(result, "replay_worker_count", 1)
            ),
            "native_topology_s": float(
                getattr(result, "topology_seconds", 0.0)
            ),
            "native_normalize_raw_s": float(
                getattr(result, "normalization_raw_seconds", 0.0)
            ),
            "native_composite_s": float(
                getattr(result, "composite_seconds", 0.0)
            ),
            "native_normalize_visible_s": float(
                getattr(result, "normalization_visible_seconds", 0.0)
            ),
            "native_export_s": float(
                getattr(result, "export_seconds", 0.0)
            ),
            "native_result_conversion_s": (
                native_result_conversion_seconds + adapter_seconds
            ),
            "native_binding_conversion_s": native_result_conversion_seconds,
            "native_adapter_s": adapter_seconds,
            "geometry_backend": "native",
            "native_version": native_version,
            "native_schema_version": int(result.schema_version),
            "native_fallback_reason": "",
            "native_input_paint_count": input_paint_count,
            "native_raw_paint_count": int(result.raw.geometry_count),
            "native_output_paint_count": int(result.visible.geometry_count),
            "native_component_count": int(result.visible.component_count),
            "native_hole_count": int(result.visible.hole_count),
            "native_unprintable_fragment_count": len(
                unprintable_fragments
            ),
            "native_unprintable_reasons": unprintable_reason_counts,
        },
        native_version=native_version,
        native_schema_version=int(result.schema_version),
        unprintable_fragments=unprintable_fragments,
        image_vectorizer_bounds=image_vectorizer_bounds,
    )


__all__ = [
    "NativeSvgFallback",
    "NativeSvgGeometry",
    "NativeSvgPaintContributor",
    "NativeSvgUnprintableFragment",
    "analyze_native_svg",
    "native_runtime_identity",
]
