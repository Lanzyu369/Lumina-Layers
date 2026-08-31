"""Thin, fail-closed adapter for the standalone native SVG geometry engine."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import os
import re
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
from core.vector_geometry_contract import (
    LEGACY_MIN_COMPONENT_AREA_SOURCE_UNITS_SQUARED,
)


NATIVE_RESULT_SCHEMA_VERSION = 1
_REFERENCE_SCAN_CHUNK_BYTES = 64 * 1024
_REFERENCE_SCAN_OVERLAP_BYTES = 256
_SOURCE_KIND_FILL = 0
_SOURCE_KIND_STROKE = 1
_LEGACY_CONTOUR_CLOSE_DELTA_SOURCE_UNITS = 0.03
_LEGACY_REFERENCE_TAG_RE = re.compile(
    rb"<(?:[A-Za-z_][A-Za-z0-9_.-]*:)?(?:style|use)(?=[\s/>])"
)


@dataclass(frozen=True)
class NativeSvgFallback:
    """Request one whole-document execution of Lumina's legacy SVG path.

    请求 Lumina 对整份文档执行一次旧 SVG 链路。
    """

    reason_code: str
    native_version: str


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
    geometry_backend: str = field(default="native", init=False)
    image_vectorizer_bounds: Any | None = None


def _load_native_module() -> ModuleType:
    return importlib.import_module("lumina_svg_core")


def _requires_legacy_reference_semantics(svg_path: str) -> bool:
    try:
        with open(svg_path, "rb") as handle:
            file_size = os.fstat(handle.fileno()).st_size
            if file_size <= 0 or file_size > NATIVE_SVG_MAX_BYTES:
                return False
            remaining = file_size
            overlap = b""
            while remaining > 0:
                chunk = handle.read(
                    min(_REFERENCE_SCAN_CHUNK_BYTES, remaining)
                )
                if not chunk:
                    break
                window = overlap + chunk
                if _LEGACY_REFERENCE_TAG_RE.search(window) is not None:
                    return True
                overlap = window[-_REFERENCE_SCAN_OVERLAP_BYTES:]
                remaining -= len(chunk)
            return False
    except (OSError, ValueError):
        return False


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
    return (
        "native",
        str(getattr(module, "__version__", "unknown")),
        NATIVE_RESULT_SCHEMA_VERSION,
    )


def _collection_geometries(collection: Any, grid_to_source_unit: float):
    coordinates = np.multiply(
        np.asarray(collection.coordinates),
        grid_to_source_unit,
        dtype=np.float64,
    )
    if coordinates.ndim != 2 or coordinates.shape[1] != 2:
        raise NativeSvgInternalError(
            "The native SVG result returned an invalid coordinate array.",
            reason_code="invalid_coordinate_schema",
        )
    offsets = (
        np.asarray(collection.ring_offsets),
        np.asarray(collection.polygon_offsets),
        np.asarray(collection.geometry_offsets),
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
    return shapely.from_ragged_array(
        shapely.GeometryType.MULTIPOLYGON,
        coordinates,
        offsets,
    )


def _rgb_at(collection: Any, geometry_index: int) -> tuple[int, int, int]:
    rgba = np.asarray(collection.rgba)
    if rgba.ndim != 2 or rgba.shape != (collection.geometry_count, 4):
        raise NativeSvgInternalError(
            "The native SVG result returned invalid material metadata.",
            reason_code="invalid_material_schema",
        )
    color = rgba[geometry_index]
    return int(color[0]), int(color[1]), int(color[2])


def _shape_data(collection: Any, geometries: np.ndarray) -> list[dict[str, Any]]:
    source_kinds = np.asarray(collection.source_kinds)
    if source_kinds.shape != (collection.geometry_count,):
        raise NativeSvgInternalError(
            "The native SVG result returned invalid source metadata.",
            reason_code="invalid_source_schema",
        )
    items: list[dict[str, Any]] = []
    for geometry_index, geometry in enumerate(geometries):
        if geometry is None or geometry.is_empty:
            continue
        source_kind = int(source_kinds[geometry_index])
        items.append(
            {
                "poly": geometry,
                "color": _rgb_at(collection, geometry_index),
                "source_kind": (
                    "stroke_only"
                    if source_kind == _SOURCE_KIND_STROKE
                    else "fill"
                ),
                "geometry_normalized": True,
            }
        )
    return items


def _visible_shapes(
    collection: Any, geometries: np.ndarray
) -> list[dict[str, Any]]:
    draw_indices = np.asarray(collection.draw_indices)
    source_indices = np.asarray(collection.source_indices)
    if (
        draw_indices.shape != (collection.geometry_count,)
        or source_indices.shape != (collection.geometry_count,)
    ):
        raise NativeSvgInternalError(
            "The native SVG result returned invalid draw-order metadata.",
            reason_code="invalid_draw_schema",
        )
    items: list[dict[str, Any]] = []
    for geometry_index, geometry in enumerate(geometries):
        if geometry is None or geometry.is_empty:
            continue
        components = (
            geometry.geoms
            if geometry.geom_type == "MultiPolygon"
            else (geometry,)
        )
        color = _rgb_at(collection, geometry_index)
        for component in components:
            if (
                component.is_empty
                or float(component.area)
                < LEGACY_MIN_COMPONENT_AREA_SOURCE_UNITS_SQUARED
            ):
                continue
            items.append(
                {
                    "geometry": component,
                    "color": color,
                    "draw_order": len(items),
                    "native_draw_order": int(draw_indices[geometry_index]),
                    "native_source_index": int(source_indices[geometry_index]),
                }
            )
    return items


def _invalid_result(reason_code: str) -> None:
    if reason_code == "empty_geometry":
        raise ValueError("No valid filled shapes found in SVG.")
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
            false, a document containing recorded strokes falls back instead
            of changing legacy behavior. 是否沿用 Lumina 的描边展开策略。

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
        False,
        _LEGACY_CONTOUR_CLOSE_DELTA_SOURCE_UNITS,
        0.25,
    )
    native_call_seconds = time.perf_counter() - call_started

    if result.status == "unsupported":
        reason_code = str(
            result.reason_code or "unsupported_svg_semantics"
        )
        if reason_code == "unsupported_complexity":
            raise NativeSvgResourceLimitError(reason_code=reason_code)
        if reason_code == "unsupported_stroke_policy":
            reason_code = (
                "legacy_stroke_parity"
                if expand_stroke_to_fill
                else "legacy_stroke_policy"
            )
        return NativeSvgFallback(
            reason_code=reason_code,
            native_version=native_version,
        )
    if result.status != "supported":
        reason_code = str(result.reason_code or "unknown_error")
        if reason_code == "empty_geometry":
            return NativeSvgFallback(
                reason_code="legacy_empty_geometry_parity",
                native_version=native_version,
            )
        _invalid_result(reason_code)
    if _requires_legacy_reference_semantics(svg_path):
        return NativeSvgFallback(
            reason_code="legacy_css_use_parity",
            native_version=native_version,
        )
    if int(result.schema_version) != NATIVE_RESULT_SCHEMA_VERSION:
        raise NativeSvgInternalError(
            "The native SVG result schema is incompatible with Lumina.",
            reason_code="native_schema_mismatch",
        )

    if (
        not bool(
            getattr(result, "legacy_contour_normalization_identity", False)
        )
        or not bool(
            getattr(result, "legacy_contour_normalization_compatible", False)
        )
    ):
        return NativeSvgFallback(
            reason_code="legacy_contour_normalization_incompatible",
            native_version=native_version,
        )
    if not bool(
        getattr(result, "legacy_curve_tolerance_compatible", False)
    ):
        return NativeSvgFallback(
            reason_code="legacy_curve_tolerance_parity",
            native_version=native_version,
        )

    source_kinds = np.asarray(result.raw.source_kinds)
    if np.any(source_kinds == _SOURCE_KIND_STROKE):
        return NativeSvgFallback(
            reason_code=(
                "legacy_stroke_parity"
                if expand_stroke_to_fill
                else "legacy_stroke_policy"
            ),
            native_version=native_version,
        )

    adapter_started = time.perf_counter()
    grid_to_source_unit = float(result.grid_to_source_unit)
    raw_geometries = _collection_geometries(
        result.raw, grid_to_source_unit
    )
    visible_geometries = _collection_geometries(
        result.visible, grid_to_source_unit
    )
    silhouette_geometries = _collection_geometries(
        result.silhouette, grid_to_source_unit
    )
    if len(silhouette_geometries) != 1 or silhouette_geometries[0].is_empty:
        raise NativeSvgInternalError(
            "The native SVG result returned an invalid silhouette.",
            reason_code="invalid_silhouette_schema",
        )
    shape_data = _shape_data(result.raw, raw_geometries)
    clipped_shapes = _visible_shapes(result.visible, visible_geometries)
    if not shape_data or not clipped_shapes:
        return NativeSvgFallback(
            reason_code="legacy_empty_geometry_parity",
            native_version=native_version,
        )
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
        scale_factor=float(result.scale_factor),
        bbox=tuple(float(value) for value in result.bbox),
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
            "native_topology_s": float(
                getattr(result, "topology_seconds", 0.0)
            ),
            "native_legacy_raw_s": float(
                getattr(result, "legacy_raw_seconds", 0.0)
            ),
            "native_composite_s": float(
                getattr(result, "composite_seconds", 0.0)
            ),
            "native_legacy_visible_s": float(
                getattr(result, "legacy_visible_seconds", 0.0)
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
            "native_legacy_normalization_identity": bool(
                result.legacy_contour_normalization_identity
            ),
            "native_legacy_area_filter_identity": bool(
                result.legacy_area_filter_identity
            ),
            "native_fallback_reason": "",
        },
        native_version=native_version,
        native_schema_version=int(result.schema_version),
        image_vectorizer_bounds=image_vectorizer_bounds,
    )


__all__ = [
    "NativeSvgFallback",
    "NativeSvgGeometry",
    "analyze_native_svg",
    "native_runtime_identity",
]
