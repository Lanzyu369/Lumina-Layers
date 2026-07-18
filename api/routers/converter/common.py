"""Common helpers for converter router modules."""

from __future__ import annotations

import pickle
import time
from typing import NoReturn

import cv2
import numpy as np
from fastapi import HTTPException
from PIL import Image

from api.errors import to_http_exception
from api.file_bridge import ndarray_to_png_bytes, pil_to_png_bytes
from api.gradient_group_payload import compute_gradient_group_payload
from api.preview_cache_artifacts import (
    hydrate_preview_cache,
    is_preview_cache_artifact_ref,
)
from api.session_store import SessionStore
from api.structured_logging import bind_session_id, get_logger
from config import PrinterConfig
from core.material_lut_synthesis import infer_material_archive_base_channel_idx
from core.pipeline._input_validation_common import (
    VECTOR_NATIVE_REQUIRES_SVG_DETAIL,
)

EPHEMERAL_PREVIEW_TTL_SECONDS = 600
BATCH_DOWNLOAD_TTL_SECONDS = 3600
VECTOR_NATIVE_REQUIRES_SVG_ERROR = "vector_native_requires_svg"
PREVIEW_CACHE_UNAVAILABLE_DETAIL = (
    "Preview data is unavailable. Re-run preview and try again."
)
PREVIEW_CACHE_INVALID_DETAIL = (
    "Preview data is unavailable. Re-run preview before trying again."
)
SOURCE_IMAGE_UNAVAILABLE_DETAIL = (
    "Source image is unavailable. Re-upload the image, run preview, and try again."
)
LUT_DATA_UNAVAILABLE_DETAIL = (
    "Color lookup data is unavailable. Re-select the LUT or materials, run preview, "
    "and try again."
)
LUT_SOURCE_SELECTION_INVALID_DETAIL = (
    "Choose a valid LUT or complete native material source, then try again."
)
PREVIEW_COLOR_PALETTE_UNAVAILABLE_DETAIL = (
    "Preview color palette is unavailable. Re-run preview and try again."
)
REGION_SELECTION_REQUIRED_DETAIL = (
    "No replacement region is selected. Select a region or choose a gradient group, "
    "then try again."
)
GRADIENT_REGION_METADATA_UNAVAILABLE_DETAIL = (
    "Gradient region data is unavailable. Re-run preview and try again."
)
GRADIENT_REGION_METADATA_STALE_DETAIL = (
    "Gradient region data no longer matches the preview. Re-run preview and try again."
)
MATCHED_COLORS_UNAVAILABLE_DETAIL = (
    "Preview matched colors are unavailable. Re-run preview and try again."
)
MATERIAL_SOLVER_CACHE_UNAVAILABLE_DETAIL = (
    "Material solver data is unavailable. Re-run preview and try again."
)
log = get_logger(__name__)
_VALID_MATERIAL_SOURCES = {"lut", "material_archive"}
_RELIEF_HEIGHT_EPSILON_MM = 1e-9

# Shared error tuples for except clauses across converter router modules.
# replace.py extends ROUTER_HANDLED_ERRORS with IndexError for array-index
# operations in region-detect / region-replace endpoints.
ROUTER_HANDLED_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    OSError,
    RuntimeError,
    pickle.UnpicklingError,
    cv2.error,
)
NON_FATAL_GLB_ERRORS = (
    ValueError,
    TypeError,
    OSError,
    RuntimeError,
    cv2.error,
)


def _public_pipeline_validation_detail(status_msg: object) -> dict[str, str] | None:
    """Return a public detail for known pipeline validation failures.
    为已知管线校验错误返回可公开的错误详情。
    """
    raw_status = str(status_msg or "").strip()
    if "Vector Native mode requires SVG files" in raw_status:
        return {
            "error": VECTOR_NATIVE_REQUIRES_SVG_ERROR,
            "message": VECTOR_NATIVE_REQUIRES_SVG_DETAIL,
        }
    return None


def _integer_value_bounds(value: object) -> tuple[int, int] | None:
    if value is None:
        return None
    try:
        array = np.asarray(value)
    except (TypeError, ValueError):
        return None
    if array.size == 0:
        return None
    if not np.issubdtype(array.dtype, np.integer):
        try:
            array = array.astype(np.int64)
        except (TypeError, ValueError, OverflowError):
            return None
    return int(array.min()), int(array.max())


def _material_matrix_dtype_for_bounds(min_value: int, max_value: int) -> np.dtype:
    for dtype in (np.int8, np.int16, np.int32, np.int64):
        info = np.iinfo(dtype)
        if min_value >= info.min and max_value <= info.max:
            return np.dtype(dtype)
    return np.dtype(np.int64)


def _ensure_material_matrix_signed_capacity(
    material_matrix: np.ndarray,
    *candidate_values: object,
) -> np.ndarray:
    """Return a signed matrix dtype wide enough for pending material ids."""

    if material_matrix.size:
        min_value = int(material_matrix.min())
        max_value = int(material_matrix.max())
    else:
        min_value = 0
        max_value = 0
    for value in candidate_values:
        bounds = _integer_value_bounds(value)
        if bounds is None:
            continue
        min_value = min(min_value, bounds[0])
        max_value = max(max_value, bounds[1])

    target_dtype = _material_matrix_dtype_for_bounds(min_value, max_value)
    if (
        np.issubdtype(material_matrix.dtype, np.signedinteger)
        and material_matrix.dtype == target_dtype
    ):
        return material_matrix
    if (
        np.issubdtype(material_matrix.dtype, np.signedinteger)
        and material_matrix.dtype.itemsize > target_dtype.itemsize
    ):
        return material_matrix
    return material_matrix.astype(target_dtype, copy=False)


def _validate_material_source(material_source: str) -> str:
    """Validate converter color-source selector from API form inputs."""

    if material_source not in _VALID_MATERIAL_SOURCES:
        expected = ", ".join(sorted(_VALID_MATERIAL_SOURCES))
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid material_source: {material_source}. "
                f"Expected one of: {expected}."
            ),
        )
    return material_source


def _material_matrix_depth_from_shape(shape: object | None) -> int | None:
    if shape is None:
        return None
    try:
        shape_values = list(shape)
    except TypeError:
        return None
    if len(shape_values) < 3:
        return None
    try:
        depth = int(shape_values[2])
    except (TypeError, ValueError):
        return None
    return depth if depth > 0 else None


def _material_matrix_depth_from_value(material_matrix: object | None) -> int | None:
    shape = getattr(material_matrix, "shape", None)
    if shape is None and isinstance(material_matrix, dict):
        shape = material_matrix.get("shape")
    return _material_matrix_depth_from_shape(shape)


def _cache_material_matrix_depth(cache: dict | None) -> int | None:
    if not cache:
        return None
    depth = _material_matrix_depth_from_value(cache.get("material_matrix"))
    if depth is not None:
        return depth

    fields = cache.get("fields")
    if isinstance(fields, dict):
        material_matrix_ref = fields.get("material_matrix")
        if isinstance(material_matrix_ref, dict):
            return _material_matrix_depth_from_shape(material_matrix_ref.get("shape"))
    return None


def _positive_int(value: object | None) -> int | None:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count > 0 else None


def _recipe_override_layer_count(recipe_overrides: list[dict[str, object]] | None) -> int | None:
    if not recipe_overrides:
        return None

    counts: list[int] = []
    for item in recipe_overrides:
        if not isinstance(item, dict):
            continue
        recipe = item.get("recipe")
        try:
            count = len(recipe)  # type: ignore[arg-type]
        except TypeError:
            continue
        if count > 0:
            counts.append(count)
    return max(counts) if counts else None


def _resolve_material_archive_optical_layer_count(
    *,
    session_data: dict | None = None,
    cache: dict | None = None,
    cache_ref: dict | None = None,
    material_layer_count: object | None = None,
    requested_color_layers: object | None = None,
    recipe_overrides: list[dict[str, object]] | None = None,
) -> int | None:
    candidates: list[int] = []

    cache_ref_depth = _cache_material_matrix_depth(cache_ref)
    if cache_ref_depth is not None:
        candidates.append(cache_ref_depth)

    cache_depth = _cache_material_matrix_depth(cache)
    if cache_depth is not None:
        candidates.append(cache_depth)

    raw_count = material_layer_count
    if raw_count is None and session_data is not None:
        raw_count = session_data.get("material_layer_count")
    session_count = _positive_int(raw_count)
    if session_count is not None:
        candidates.append(session_count)

    request_count = _positive_int(requested_color_layers)
    if request_count is not None:
        candidates.append(request_count)

    override_count = _recipe_override_layer_count(recipe_overrides)
    if override_count is not None:
        candidates.append(override_count)

    return max(candidates) if candidates else None


def _format_mm(value: float) -> str:
    return f"{value:.2f} mm"


def _validate_material_archive_relief_minimum_height(
    *,
    enable_relief: bool,
    material_source: str,
    height_mode: str | None,
    color_height_map: dict[str, float] | None,
    heightmap_max_height: float | None,
    session_data: dict | None = None,
    cache: dict | None = None,
    cache_ref: dict | None = None,
    material_layer_count: object | None = None,
    requested_color_layers: object | None = None,
    recipe_overrides: list[dict[str, object]] | None = None,
) -> None:
    """Reject material-archive relief heights below the optical stack depth."""

    if not enable_relief or material_source != "material_archive":
        return

    optical_layers = _resolve_material_archive_optical_layer_count(
        session_data=session_data,
        cache=cache,
        cache_ref=cache_ref,
        material_layer_count=material_layer_count,
        requested_color_layers=requested_color_layers,
        recipe_overrides=recipe_overrides,
    )
    if optical_layers is None:
        return

    min_height_mm = optical_layers * float(PrinterConfig.LAYER_HEIGHT)
    mode = height_mode or "color"
    if mode == "heightmap":
        requested = float(heightmap_max_height or 0.0)
        if requested + _RELIEF_HEIGHT_EPSILON_MM < min_height_mm:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Material-archive relief heightmap_max_height must be at least "
                    f"{_format_mm(min_height_mm)} for {optical_layers} optical layers; "
                    f"received {_format_mm(requested)}."
                ),
            )
        return

    if mode != "color" or not color_height_map:
        return

    try:
        min_color_height = min(float(value) for value in color_height_map.values())
    except (TypeError, ValueError):
        return
    if min_color_height + _RELIEF_HEIGHT_EPSILON_MM < min_height_mm:
        raise HTTPException(
            status_code=422,
            detail=(
                "Material-archive relief color heights must be at least "
                f"{_format_mm(min_height_mm)} for {optical_layers} optical layers; "
                f"received minimum {_format_mm(min_color_height)}."
            ),
        )


def _handle_core_error(e: Exception, context: str) -> NoReturn:
    log.exception(
        "Converter operation failed",
        extra={
            "event": "converter_error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "context": context,
        },
    )
    raise to_http_exception(e, context)


def _require_session(store: SessionStore, session_id: str) -> dict:
    bind_session_id(session_id)
    data = store.get(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return data


def _require_preview_cache(session_data: dict) -> dict:
    cache = session_data.get("preview_cache")
    if cache is None:
        raise HTTPException(status_code=409, detail=PREVIEW_CACHE_UNAVAILABLE_DETAIL)
    if is_preview_cache_artifact_ref(cache):
        return hydrate_preview_cache(cache)
    return cache


def _resolve_material_backing_index(
    selected_materials: object,
    requested_index: object | None,
) -> int:
    materials = list(selected_materials) if isinstance(selected_materials, (list, tuple)) else []
    if requested_index is None:
        index = infer_material_archive_base_channel_idx(materials, [], {})
    else:
        try:
            index = int(requested_index)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail="material_backing_material_index must be an integer.",
            ) from exc
    if index < 0:
        raise HTTPException(
            status_code=422,
            detail="material_backing_material_index must be greater than or equal to 0.",
        )
    if materials and index >= len(materials):
        raise HTTPException(
            status_code=422,
            detail=(
                "material_backing_material_index is outside the selected_materials "
                f"range: {index} >= {len(materials)}."
            ),
        )
    if not materials and index != 0:
        raise HTTPException(
            status_code=422,
            detail="material_backing_material_index requires selected_materials.",
        )
    return index


def _image_to_png_bytes(img: object) -> bytes:
    if isinstance(img, np.ndarray):
        return ndarray_to_png_bytes(img)
    if isinstance(img, Image.Image):
        return pil_to_png_bytes(img)
    raise TypeError(f"Unsupported image type: {type(img)}")


def recompute_gradient_groups_into_session(
    cache_data: dict | None,
    session_id: str,
    store: SessionStore,
) -> list[dict] | None:
    """Analyse preview cache for gradient-banding groups and cache the result.
    分析预览缓存中的渐变海带纹分组，结果写入 session。

    Runs synchronously. The analyser is pure NumPy / OpenCV and typically
    finishes within 1-2s even on 2k x 3k images. Failures are non-fatal —
    we log a warning and leave the session without gradient-group metadata
    so the UI can degrade gracefully.

    Shared by ``/preview`` (first-time analysis on a fresh cache) and
    ``/region-requantize`` (re-analysis after ``matched_rgb`` changes so
    the Gradient Groups panel reflects the new segmentation). Keeping the
    analysis in ``common.py`` avoids duplicating the failure-handling /
    logging contract between call sites.
    同时被 ``/preview``（首次分析）和 ``/region-requantize``（二次量化后
    重跑）使用。放在 ``common.py`` 统一失败处理与日志规范，避免多处重复。

    Returns:
        The JSON-serialisable group payload on success, or ``None`` when
        the cache is missing inputs or the analyser degrades. Callers that
        want to ship groups back to the frontend in their response payload
        can use this return value directly without re-reading from the
        session store.
        成功时返回可 JSON 序列化的分组负载；缓存缺输入或分析失败时返回
        ``None``。调用方若要直接把新分组塞进响应，可用返回值避免再读一次
        session。
    """
    if cache_data is None:
        return None
    matched_rgb = cache_data.get("matched_rgb")
    quantized_image = cache_data.get("quantized_image")
    mask_solid = cache_data.get("mask_solid")
    if matched_rgb is None or quantized_image is None or mask_solid is None:
        log.debug(
            "Skipping gradient-group analysis: preview cache is missing inputs",
            extra={"event": "gradient_groups_skipped_missing_inputs"},
        )
        return None
    _t = time.perf_counter()
    try:
        computed = compute_gradient_group_payload(cache_data)
    except (ValueError, RuntimeError) as exc:
        log.warning(
            "Gradient-group analysis failed",
            extra={
                "event": "gradient_groups_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return None
    if computed is None:
        return None
    payload, region_id_map = computed
    store.put(session_id, "gradient_groups", payload)
    # Cache the per-pixel region_id_map so the color-highlight / replace /
    # requantize endpoints can clip by the exact pixel mask of a selected
    # sub-region instead of a bbox approximation.
    # 缓存每像素 (group, region) 编码图，后续 highlight / replace /
    # requantize 可做像素级精确裁剪。
    store.put(
        session_id,
        "gradient_region_id_map",
        region_id_map,
    )
    log.debug(
        "Gradient groups computed",
        extra={
            "event": "gradient_groups_computed",
            "duration_ms": round((time.perf_counter() - _t) * 1000, 3),
            "group_count": len(payload),
            "total_regions": sum(len(g.get("regions", [])) for g in payload),
        },
    )
    return payload
