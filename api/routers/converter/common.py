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
from api.session_store import SessionStore
from api.structured_logging import bind_session_id, get_logger
from core.material_lut_synthesis import infer_material_archive_base_channel_idx
from core.gradient_group_analyzer import (
    GradientGroupAnalysisParams,
    analyze_gradient_groups_with_region_id_map,
    gradient_groups_to_json,
)

EPHEMERAL_PREVIEW_TTL_SECONDS = 600
BATCH_DOWNLOAD_TTL_SECONDS = 3600
log = get_logger(__name__)

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
        raise HTTPException(status_code=409, detail="No preview cache. Call POST /api/convert/preview first.")
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
        analysis = analyze_gradient_groups_with_region_id_map(
            matched_rgb=np.asarray(matched_rgb, dtype=np.uint8),
            quantized_rgb=np.asarray(quantized_image, dtype=np.uint8),
            mask_solid=np.asarray(mask_solid, dtype=bool),
            params=GradientGroupAnalysisParams(),
        )
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
    payload = gradient_groups_to_json(analysis.groups)
    store.put(session_id, "gradient_groups", payload)
    # Cache the per-pixel region_id_map so the color-highlight / replace /
    # requantize endpoints can clip by the exact pixel mask of a selected
    # sub-region instead of a bbox approximation.
    # 缓存每像素 (group, region) 编码图，后续 highlight / replace /
    # requantize 可做像素级精确裁剪。
    store.put(
        session_id,
        "gradient_region_id_map",
        np.ascontiguousarray(analysis.region_id_map, dtype=np.uint32),
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
