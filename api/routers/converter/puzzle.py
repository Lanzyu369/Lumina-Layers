"""Converter puzzle routes.
图像转换拼图模式路由。

This module implements puzzle-layout overlay preview and puzzle piece export
for the converter workspace.
本模块实现图像转换工作区的拼图叠线预览与拼图导出。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import tempfile
import uuid
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from PIL import Image

from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import (
    get_preview_cache_metadata,
    hydrate_preview_cache,
    is_preview_cache_artifact_ref,
)
from api.schemas.converter import (
    ConvertGenerateRequest,
    ModelingMode,
    PuzzleGenerateRequest,
    PuzzleLayoutPreviewRequest,
)
from api.schemas.responses import PuzzleGenerateResponse, PuzzleLayoutPreviewResponse
from api.session_store import SessionStore
from api.structured_logging import get_logger
from api.worker_pool import WorkerPoolManager
from api.workers.converter_workers import worker_generate_model
from config import ModelingMode as CoreModelingMode
from config import TEMP_DIR
from core.puzzle import (
    PuzzleLayout,
    PuzzleLayoutConfig,
    PuzzlePiece,
    build_puzzle_layout,
    export_piece_boundary_geometry,
    inset_boundary_geometry_payload,
    rasterize_piece_mask,
    render_assembly_overview,
    render_puzzle_overlay,
    resolve_puzzle_mask_geometry,
)
from core.puzzle_3mf import PuzzlePiece3MFSource, assemble_puzzle_3mf

from .common import (
    BATCH_DOWNLOAD_TTL_SECONDS,
    ROUTER_HANDLED_ERRORS,
    _handle_core_error,
    _require_session,
    _resolve_material_backing_index,
    _validate_material_archive_relief_minimum_height,
)

router = APIRouter()
log = get_logger(__name__)
_PUZZLE_WORKER_PIXELS_PER_MM = 10.0
_PUZZLE_TOTAL_CUT_CLEARANCE_MM = 0.1
_PUZZLE_BOUNDARY_INSET_MM = _PUZZLE_TOTAL_CUT_CLEARANCE_MM / 2.0
_PUZZLE_ASSEMBLY_FAILED_DETAIL = (
    "Puzzle 3MF assembly failed. The generated pieces could not be "
    "combined into a downloadable file. Try generating the puzzle again."
)


class _PuzzleLayoutPreviewBody(BaseModel):
    """Wrapper combining session_id with puzzle preview parameters.
    将 ``session_id`` 与拼图预览参数组合在一起的请求模型。
    """

    session_id: str
    params: PuzzleLayoutPreviewRequest


class _PuzzleGenerateBody(BaseModel):
    """Wrapper combining session_id with puzzle generate parameters.
    将 ``session_id`` 与拼图生成参数组合在一起的请求模型。
    """

    session_id: str
    params: PuzzleGenerateRequest


def _require_puzzle_cache(
    session_data: dict[str, Any],
    *,
    fields: set[str],
) -> dict[str, Any]:
    """Load only the preview-cache fields needed by puzzle routes.

    只加载拼图路由实际需要的 preview-cache 字段。
    """
    cache = session_data.get("preview_cache")
    if cache is None:
        raise HTTPException(
            status_code=409,
            detail="No preview cache. Call POST /api/convert/preview first.",
        )
    if not isinstance(cache, dict):
        raise HTTPException(
            status_code=409,
            detail="Invalid preview cache. Call POST /api/convert/preview again.",
        )
    if not is_preview_cache_artifact_ref(cache):
        return cache

    loaded = get_preview_cache_metadata(cache)
    try:
        loaded.update(
            hydrate_preview_cache(
                cache,
                fields=fields,
                mmap_mode="r",
            )
        )
    except (OSError, ValueError, TypeError, KeyError, EOFError) as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Puzzle preview cache is unavailable. "
                "Re-run preview before using puzzle mode."
            ),
        ) from exc
    return loaded


def _piece_boundary_geometry_payload(piece: PuzzlePiece, bbox_px: tuple[int, int, int, int]) -> dict[str, Any]:
    """Build a crop-local boundary payload for one puzzle piece.
    为单个拼图块构建相对裁切区域的边界载荷。

    Args:
        piece: Piece metadata with absolute preview-space coordinates.
            (带有预览绝对坐标的拼图块元数据)
        bbox_px: Inclusive-exclusive crop bbox in preview pixels.
            (预览像素空间中的裁切包围盒)

    Returns:
        dict[str, Any]: JSON-serializable boundary payload.
            (可序列化为 JSON 的边界数据)
    """

    if tuple(int(value) for value in bbox_px) != piece.bbox_px:
        raise ValueError("Puzzle piece crop bbox does not match piece.bbox_px.")
    return export_piece_boundary_geometry(piece)


def _get_source_rgba(cache: dict[str, Any]) -> np.ndarray:
    """Return the canonical raster source for puzzle cropping.
    返回用于拼图裁切的标准栅格源图。

    Args:
        cache: Preview cache stored in session. (Session 中保存的预览缓存)

    Returns:
        np.ndarray: RGBA image in preview pixel space. (预览像素空间中的 RGBA 图像)

    Raises:
        ValueError: If required preview cache keys are missing. (缺少所需预览缓存键时抛出)
    """

    preview_rgba = cache.get("preview_rgba")
    if isinstance(preview_rgba, np.ndarray) and preview_rgba.ndim == 3 and preview_rgba.shape[2] == 4:
        return preview_rgba.astype(np.uint8, copy=False)

    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    if matched_rgb is None or mask_solid is None:
        raise ValueError("Preview cache missing matched_rgb or mask_solid for puzzle mode.")

    h_px, w_px = matched_rgb.shape[:2]
    source_rgba = np.zeros((h_px, w_px, 4), dtype=np.uint8)
    source_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    source_rgba[mask_solid, 3] = 255
    return source_rgba


def _get_layout_dimensions(
    cache: dict[str, Any],
    request: PuzzleLayoutPreviewRequest,
) -> tuple[int, int, float, float]:
    """Resolve preview and physical dimensions for puzzle layout.
    解析拼图布局所需的预览尺寸与物理尺寸。
    """

    matched_rgb = cache.get("matched_rgb")
    if matched_rgb is None or matched_rgb.ndim != 3:
        raise ValueError("Preview cache missing matched_rgb for puzzle layout.")

    height_px, width_px = matched_rgb.shape[:2]
    if height_px <= 0 or width_px <= 0:
        raise ValueError("Preview cache dimensions are invalid for puzzle layout.")

    total_height_mm = float(request.target_height_mm)
    total_width_mm = total_height_mm * (width_px / max(height_px, 1))
    return width_px, height_px, total_width_mm, total_height_mm


def _get_mask_hash(mask_solid: np.ndarray | None) -> str:
    """Build a stable hash for the current solid mask.
    为当前实体蒙版生成稳定哈希。
    """

    if mask_solid is None:
        return "none"
    solid_mask = np.asarray(mask_solid, dtype=bool)
    if solid_mask.size == 0 or np.all(solid_mask):
        return "full-rect"
    packed = np.packbits(solid_mask, axis=None)
    return hashlib.sha1(packed.tobytes()).hexdigest()


def _build_layout_cache_key(
    cache: dict[str, Any],
    request: PuzzleLayoutPreviewRequest,
) -> tuple[Any, ...]:
    """Build a stable cache key for puzzle layout geometry.
    为拼图布局几何生成稳定缓存键。
    """

    width_px, height_px, total_width_mm, total_height_mm = _get_layout_dimensions(cache, request)
    mask_solid = cache.get("mask_solid")
    return (
        width_px,
        height_px,
        round(total_width_mm, 6),
        round(total_height_mm, 6),
        request.puzzle_style.value,
        request.sizing_mode.value,
        round(float(request.piece_width_mm), 6),
        round(float(request.piece_height_mm), 6),
        int(request.rows),
        int(request.cols),
        int(request.target_piece_count),
        int(request.seed),
        request.connector_style.value,
        round(float(request.irregularity_strength), 6),
        round(float(request.min_neck_width_mm), 6),
        _get_mask_hash(mask_solid if isinstance(mask_solid, np.ndarray) else None),
    )


def _build_overlay_cache_key(
    layout_cache_key: tuple[Any, ...],
    request: PuzzleLayoutPreviewRequest,
) -> tuple[Any, ...]:
    """Build a stable cache key for preview overlay images.
    为预览叠线图生成稳定缓存键。
    """

    return layout_cache_key + (bool(request.labels_enabled),)


def _build_boundary_cache_key(
    cache: dict[str, Any],
) -> tuple[Any, ...]:
    """Build a stable cache key for transparent-boundary geometry.
    为透明边界几何生成稳定缓存键。
    """

    matched_rgb = cache.get("matched_rgb")
    if matched_rgb is None or matched_rgb.ndim != 3:
        raise ValueError("Preview cache missing matched_rgb for puzzle layout.")
    height_px, width_px = matched_rgb.shape[:2]
    mask_solid = cache.get("mask_solid")
    return (
        width_px,
        height_px,
        _get_mask_hash(mask_solid if isinstance(mask_solid, np.ndarray) else None),
    )


def _build_layout_config(
    cache: dict[str, Any],
    request: PuzzleLayoutPreviewRequest,
    *,
    mask_geometry: Any = None,
) -> PuzzleLayoutConfig:
    """Build the authoritative core layout configuration.
    构建唯一权威的核心拼图布局配置。
    """

    width_px, height_px, total_width_mm, total_height_mm = _get_layout_dimensions(cache, request)
    mask_solid = cache.get("mask_solid")

    return PuzzleLayoutConfig(
        width_px=width_px,
        height_px=height_px,
        total_width_mm=total_width_mm,
        total_height_mm=total_height_mm,
        style=request.puzzle_style.value,
        sizing_mode=request.sizing_mode.value,
        piece_width_mm=request.piece_width_mm,
        piece_height_mm=request.piece_height_mm,
        rows=request.rows,
        cols=request.cols,
        target_piece_count=request.target_piece_count,
        seed=request.seed,
        connector_style=request.connector_style.value,
        irregularity_strength=request.irregularity_strength,
        min_neck_width_mm=request.min_neck_width_mm,
        solid_mask=mask_solid if isinstance(mask_solid, np.ndarray) else None,
        mask_geometry=mask_geometry,
    )


def _resolve_mask_geometry(
    *,
    session_data: dict[str, Any],
    cache: dict[str, Any],
    request: PuzzleLayoutPreviewRequest,
    store: SessionStore,
    session_id: str,
) -> Any:
    """Resolve and cache transparent-boundary geometry for puzzle layouts.
    解析并缓存拼图布局使用的透明边界几何。
    """

    boundary_key = _build_boundary_cache_key(cache)
    cached_key = session_data.get("puzzle_boundary_geometry_key")
    cached_geometry = session_data.get("puzzle_boundary_geometry")
    if cached_key == boundary_key:
        return cached_geometry

    geometry = resolve_puzzle_mask_geometry(_build_layout_config(cache, request))
    store.put(session_id, "puzzle_boundary_geometry_key", boundary_key)
    store.put(session_id, "puzzle_boundary_geometry", geometry)
    return geometry


def _resolve_layout(
    *,
    session_data: dict[str, Any],
    cache: dict[str, Any],
    request: PuzzleLayoutPreviewRequest,
    store: SessionStore,
    session_id: str,
) -> tuple[PuzzleLayout, tuple[Any, ...]]:
    """Resolve and cache the authoritative puzzle layout.
    解析并缓存权威拼图布局。
    """

    layout_cache_key = _build_layout_cache_key(cache, request)
    cached_key = session_data.get("puzzle_layout_cache_key")
    cached_layout = session_data.get("puzzle_layout_cache")
    if cached_key == layout_cache_key and isinstance(cached_layout, PuzzleLayout):
        return cached_layout, layout_cache_key

    mask_geometry = _resolve_mask_geometry(
        session_data=session_data,
        cache=cache,
        request=request,
        store=store,
        session_id=session_id,
    )
    layout = build_puzzle_layout(
        _build_layout_config(
            cache,
            request,
            mask_geometry=mask_geometry,
        )
    )
    store.put(session_id, "puzzle_layout_cache_key", layout_cache_key)
    store.put(session_id, "puzzle_layout_cache", layout)
    return layout, layout_cache_key


def _crop_piece_arrays(
    source_rgba: np.ndarray,
    matched_rgb: np.ndarray,
    piece: PuzzlePiece,
) -> tuple[tuple[int, int, int, int], np.ndarray, np.ndarray]:
    """Crop puzzle piece raster inputs from full-size arrays.
    从整图数组中裁切单个拼图块所需的栅格输入。

    Args:
        source_rgba: Full RGBA source image. (整图 RGBA 源图)
        matched_rgb: Full matched RGB image. (整图 matched RGB)
        piece: Target puzzle piece metadata. (目标拼图块元数据)

    Returns:
        tuple[tuple[int, int, int, int], np.ndarray, np.ndarray]:
            Bounding box, cropped RGBA, and cropped matched RGB.
            (包围盒、裁切后的 RGBA 与 matched RGB)
    """

    bbox_px, local_mask = rasterize_piece_mask(piece)
    x0, y0, x1, y1 = bbox_px

    rgba_crop = np.array(source_rgba[y0:y1, x0:x1], copy=True)
    matched_crop = np.array(matched_rgb[y0:y1, x0:x1], copy=True)
    alpha_mask = local_mask.astype(np.uint8, copy=False)

    rgba_crop[..., 3] = np.minimum(rgba_crop[..., 3], alpha_mask)
    rgba_crop[alpha_mask == 0] = 0
    matched_crop[alpha_mask == 0] = 0
    return bbox_px, rgba_crop, matched_crop


def _resolve_piece_worker_raster_size(piece: PuzzlePiece) -> tuple[int, int]:
    """Resolve the exact raster size the worker will rebuild for one piece.
    解析 worker 最终会为单个拼图块重建的精确光栅尺寸。

    The downstream worker always rasterizes high-fidelity puzzle pieces at
    ``10 px/mm`` based on the physical bbox dimensions. Puzzle-mode helper
    assets must match that raster grid exactly, otherwise ``matched_rgb`` and
    polygon boundaries drift out of sync for SVG/vector preview caches.
    下游 worker 会基于物理包围盒尺寸按 ``10 px/mm`` 重新光栅化高保真拼图块。
    若辅助资产不与该栅格完全一致，则 ``matched_rgb`` 和 polygon 边界会在
    SVG/矢量预览缓存下发生错位。
    """

    width_mm = max(0.0, float(piece.bbox_mm[2] - piece.bbox_mm[0]))
    height_mm = max(0.0, float(piece.bbox_mm[3] - piece.bbox_mm[1]))
    # Mirror the worker's rounded 10 px/mm rebuild rule so preview-cropped
    # helper assets stay aligned for SVG-derived piece dimensions.
    target_w = max(1, int(round(width_mm * _PUZZLE_WORKER_PIXELS_PER_MM)))
    target_h = max(1, int(round(height_mm * _PUZZLE_WORKER_PIXELS_PER_MM)))
    return target_w, target_h


def _resize_piece_array_nearest(array: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
    """Resize a cropped puzzle asset using nearest-neighbor sampling.
    使用最近邻重采样裁切后的拼图资产。
    """

    target_w, target_h = (max(1, int(target_size[0])), max(1, int(target_size[1])))
    if array.shape[1] == target_w and array.shape[0] == target_h:
        return np.array(array, copy=True)
    resized = Image.fromarray(array).resize((target_w, target_h), Image.Resampling.NEAREST)
    return np.array(resized, copy=True)


def _rescale_piece_boundary_payload(
    payload: dict[str, Any],
    *,
    source_size_px: tuple[int, int],
    target_size_px: tuple[int, int],
) -> dict[str, Any]:
    """Rescale crop-local boundary geometry onto the worker raster grid.
    将局部裁切坐标系中的边界几何缩放到 worker 使用的光栅网格。
    """

    source_w, source_h = (max(1, int(source_size_px[0])), max(1, int(source_size_px[1])))
    target_w, target_h = (max(1, int(target_size_px[0])), max(1, int(target_size_px[1])))
    if (source_w, source_h) == (target_w, target_h):
        return {
            "bbox_px": list(payload.get("bbox_px") or []),
            "polygon_px": [[float(x), float(y)] for x, y in payload.get("polygon_px") or []],
            "holes_px": [
                [[float(x), float(y)] for x, y in hole]
                for hole in payload.get("holes_px") or []
            ],
        }

    scale_x = target_w / float(source_w)
    scale_y = target_h / float(source_h)

    def _scale_ring(points: list[list[float]] | list[tuple[float, float]]) -> list[list[float]]:
        return [[float(x) * scale_x, float(y) * scale_y] for x, y in points]

    return {
        "bbox_px": list(payload.get("bbox_px") or []),
        "polygon_px": _scale_ring(payload.get("polygon_px") or []),
        "holes_px": [_scale_ring(hole) for hole in payload.get("holes_px") or []],
    }


def _prepare_piece_worker_assets(
    source_rgba: np.ndarray,
    matched_rgb: np.ndarray,
    piece: PuzzlePiece,
) -> tuple[tuple[int, int, int, int], np.ndarray, np.ndarray, dict[str, Any]]:
    """Prepare raster and boundary assets aligned to the worker grid.
    准备与 worker 栅格严格对齐的拼图块图像与边界资产。
    """

    bbox_px, piece_rgba, piece_matched = _crop_piece_arrays(source_rgba, matched_rgb, piece)
    source_size = (piece_rgba.shape[1], piece_rgba.shape[0])
    target_size = _resolve_piece_worker_raster_size(piece)
    boundary_payload = _rescale_piece_boundary_payload(
        _piece_boundary_geometry_payload(piece, bbox_px),
        source_size_px=source_size,
        target_size_px=target_size,
    )
    boundary_payload = inset_boundary_geometry_payload(
        boundary_payload,
        inset_px=_PUZZLE_BOUNDARY_INSET_MM * _PUZZLE_WORKER_PIXELS_PER_MM,
    )
    return (
        bbox_px,
        _resize_piece_array_nearest(piece_rgba, target_size),
        _resize_piece_array_nearest(piece_matched, target_size),
        boundary_payload,
    )


def _save_png_array(session_id: str, store: SessionStore, array: np.ndarray, prefix: str) -> str:
    """Persist a numpy image array as a temp PNG registered to the session.
    将 NumPy 图像数组保存为已注册到 Session 的临时 PNG。

    Args:
        session_id: Active session identifier. (当前 Session ID)
        store: Session store used for temp-file cleanup. (用于清理临时文件的 SessionStore)
        array: Image array to save. (待保存的图像数组)
        prefix: Temp-file prefix. (临时文件前缀)

    Returns:
        str: Temp PNG path. (临时 PNG 路径)
    """

    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".png", dir=TEMP_DIR)
    os.close(fd)
    Image.fromarray(array).save(path)
    store.register_temp_file(session_id, path)
    return path


def _save_npy_array(session_id: str, store: SessionStore, array: np.ndarray, prefix: str) -> str:
    """Persist a numpy array as a temp ``.npy`` file registered to the session.
    将 NumPy 数组保存为已注册到 Session 的临时 ``.npy`` 文件。

    Args:
        session_id: Active session identifier. (当前 Session ID)
        store: Session store used for temp-file cleanup. (用于清理临时文件的 SessionStore)
        array: Array to persist. (待保存的数组)
        prefix: Temp-file prefix. (临时文件前缀)

    Returns:
        str: Temp NPY path. (临时 NPY 路径)
    """

    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".npy", dir=TEMP_DIR)
    os.close(fd)
    np.save(path, array)
    store.register_temp_file(session_id, path)
    return path


def _save_json_payload(session_id: str, store: SessionStore, payload: dict[str, Any], prefix: str) -> str:
    """Persist a JSON payload as a temp file registered to the session.
    将 JSON 载荷保存为已注册到 Session 的临时文件。

    Args:
        session_id: Active session identifier. (当前 Session ID)
        store: Session store used for temp-file cleanup. (用于清理临时文件的 SessionStore)
        payload: JSON-serializable payload. (可序列化为 JSON 的载荷)
        prefix: Temp-file prefix. (临时文件前缀)

    Returns:
        str: Temp JSON path. (临时 JSON 路径)
    """

    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".json", dir=TEMP_DIR)
    os.close(fd)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    store.register_temp_file(session_id, path)
    return path


def _remove_temp_path(path: str | None) -> None:
    """Best-effort removal for route-local temp files not owned by a session."""

    if not path:
        return
    try:
        os.remove(path)
    except (FileNotFoundError, OSError):
        return


def _resolve_free_color_set(session_data: dict[str, Any], request: ConvertGenerateRequest) -> set[str] | None:
    free_color_set = session_data.get("free_color_set") or None
    if request.free_color_set is not None:
        free_color_set = set(request.free_color_set)
    return free_color_set


def _resolve_relief_global_max_height(
    session_data: dict[str, Any],
    request: ConvertGenerateRequest,
) -> float | None:
    if not request.enable_relief:
        return None

    height_mode = request.height_mode or "color"
    if height_mode == "color" and request.color_height_map:
        return max(request.color_height_map.values())

    if height_mode == "heightmap":
        heightmap_grayscale = session_data.get("heightmap_grayscale")
        if heightmap_grayscale is None:
            raise HTTPException(status_code=409, detail="Heightmap missing. Upload heightmap before puzzle generation.")
        return float(request.heightmap_max_height or 5.0)

    return None


def _submit_puzzle_worker(
    image_path: str,
    lut_path: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Submit a puzzle piece to the existing model worker with forward-compatible params.
    使用现有模型 worker 提交拼图块，并透传拼图边界参数。
    """
    return worker_generate_model(image_path, lut_path, params)


@router.post("/puzzle-layout-preview", response_model=PuzzleLayoutPreviewResponse)
async def puzzle_layout_preview(
    body: _PuzzleLayoutPreviewBody,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> PuzzleLayoutPreviewResponse:
    """Generate a transparent puzzle overlay aligned to the current preview.
    生成与当前预览对齐的透明拼图叠线。

    Args:
        body: Wrapper containing session ID and puzzle parameters.
            (包含 Session ID 与拼图参数的请求体)
        store: Session store dependency. (SessionStore 依赖)
        registry: File registry dependency. (FileRegistry 依赖)

    Returns:
        PuzzleLayoutPreviewResponse: Overlay resource and resolved layout summary.
            (包含叠线资源和解析结果摘要的响应)
    """

    session_data = _require_session(store, body.session_id)
    cache = _require_puzzle_cache(
        session_data,
        fields={"matched_rgb", "mask_solid"},
    )

    try:
        layout, layout_cache_key = _resolve_layout(
            session_data=session_data,
            cache=cache,
            request=body.params,
            store=store,
            session_id=body.session_id,
        )
        overlay_cache_key = _build_overlay_cache_key(layout_cache_key, body.params)
        cached_overlay_key = session_data.get("puzzle_overlay_cache_key")
        cached_overlay_id = session_data.get("puzzle_overlay_file_id")
        overlay_id: str
        if (
            cached_overlay_key == overlay_cache_key
            and isinstance(cached_overlay_id, str)
            and registry.resolve(cached_overlay_id) is not None
        ):
            overlay_id = cached_overlay_id
        else:
            overlay = render_puzzle_overlay(
                layout,
                labels_enabled=body.params.labels_enabled,
                visibility_mask=cache.get("mask_solid"),
            )
            overlay_buffer = io.BytesIO()
            overlay.save(overlay_buffer, format="PNG")
            overlay_id = registry.register_bytes(body.session_id, overlay_buffer.getvalue(), "puzzle_overlay.png")
            store.put(body.session_id, "puzzle_overlay_cache_key", overlay_cache_key)
            store.put(body.session_id, "puzzle_overlay_file_id", overlay_id)
    except ROUTER_HANDLED_ERRORS as exc:
        _handle_core_error(exc, "Puzzle layout preview")

    warnings = list(layout.warnings)
    log.info(
        "Puzzle layout preview generated",
        extra={
            "event": "converter_puzzle_layout_preview_done",
            "session_id": body.session_id,
            "piece_count": layout.actual_piece_count,
            "grid_cols": layout.cols,
            "grid_rows": layout.rows,
            "derived_piece_width_mm": layout.derived_piece_width_mm,
            "derived_piece_height_mm": layout.derived_piece_height_mm,
            "warning_count": len(warnings),
            "labels_enabled": body.params.labels_enabled,
        },
    )
    return PuzzleLayoutPreviewResponse(
        status="ok",
        message="Puzzle layout preview generated",
        overlay_url=f"/api/files/{overlay_id}",
        piece_count=layout.actual_piece_count,
        grid_cols=layout.cols,
        grid_rows=layout.rows,
        derived_piece_width_mm=layout.derived_piece_width_mm,
        derived_piece_height_mm=layout.derived_piece_height_mm,
        warnings=warnings,
    )


@router.post("/generate-puzzle", response_model=PuzzleGenerateResponse)
async def generate_puzzle(
    body: _PuzzleGenerateBody,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
    pool: WorkerPoolManager = Depends(get_worker_pool),
) -> PuzzleGenerateResponse:
    """Generate per-piece puzzle models and assemble them into one 3MF.
    逐块生成拼图模型，并组装为一个 3MF 文件。

    Args:
        body: Wrapper containing session ID and puzzle generate params.
            (包含 Session ID 与拼图生成参数的请求体)
        store: Session store dependency. (SessionStore 依赖)
        registry: File registry dependency. (FileRegistry 依赖)
        pool: Worker-pool dependency. (WorkerPoolManager 依赖)

    Returns:
        PuzzleGenerateResponse: Download URL and resolved grid summary.
            (包含下载地址与网格摘要的响应)
    """

    session_data = _require_session(store, body.session_id)
    preview_cache_ref = session_data.get("preview_cache")
    cache = _require_puzzle_cache(
        session_data,
        fields={"matched_rgb", "mask_solid", "preview_rgba"},
    )

    request = body.params
    generate_params = request.params
    if generate_params.enable_fridge_magnet:
        raise HTTPException(status_code=422, detail="Puzzle mode does not support fridge magnet cavities.")
    if generate_params.add_loop:
        raise HTTPException(status_code=422, detail="Puzzle mode does not support keychain loop generation.")
    if request.engrave_back_labels:
        raise HTTPException(
            status_code=422,
            detail="Puzzle back-label engraving is not implemented yet. Disable it before generating puzzle pieces.",
        )

    image_path: str | None = session_data.get("image_path")
    lut_path: str | None = session_data.get("lut_path")
    session_material_source = session_data.get("material_source", "lut")
    if not image_path or not os.path.exists(image_path):
        raise HTTPException(status_code=409, detail="Image file missing. Call POST /api/convert/preview first.")
    if session_material_source == "material_archive":
        lut_path = "__material_archive__"
    elif not lut_path or not os.path.exists(lut_path):
        raise HTTPException(status_code=409, detail="LUT file missing. Call POST /api/convert/preview first.")

    try:
        layout, _layout_cache_key = _resolve_layout(
            session_data=session_data,
            cache=cache,
            request=request,
            store=store,
            session_id=body.session_id,
        )
        source_rgba = _get_source_rgba(cache)
        matched_rgb = cache.get("matched_rgb")
        if matched_rgb is None:
            raise ValueError("Preview cache missing matched_rgb for puzzle generation.")
    except ROUTER_HANDLED_ERRORS as exc:
        _handle_core_error(exc, "Puzzle generation setup")

    free_color_set = _resolve_free_color_set(session_data, generate_params)
    relief_global_max_height = _resolve_relief_global_max_height(session_data, generate_params)

    core_modeling_mode = (
        CoreModelingMode.HIGH_FIDELITY
        if generate_params.modeling_mode == ModelingMode.VECTOR
        else CoreModelingMode(generate_params.modeling_mode.value)
    )
    height_mode = generate_params.height_mode or "color"
    _validate_material_archive_relief_minimum_height(
        enable_relief=generate_params.enable_relief,
        material_source=str(session_material_source or "lut"),
        height_mode=height_mode,
        color_height_map=generate_params.color_height_map,
        heightmap_max_height=generate_params.heightmap_max_height,
        session_data=session_data,
        cache=cache,
        cache_ref=preview_cache_ref if isinstance(preview_cache_ref, dict) else None,
    )
    heightmap_grayscale = session_data.get("heightmap_grayscale")

    warnings = list(layout.warnings)

    sid = body.session_id
    base_name = os.path.splitext(os.path.basename(image_path))[0] or "puzzle"
    futures: list[asyncio.Future] = []
    piece_records: list[PuzzlePiece] = []
    skipped_transparent_labels: list[str] = []

    for piece in layout.pieces:
        bbox_px, piece_rgba, piece_matched, piece_boundary_payload = _prepare_piece_worker_assets(
            source_rgba,
            matched_rgb,
            piece,
        )
        if not np.any(piece_rgba[..., 3] >= 10):
            skipped_transparent_labels.append(piece.label)
            continue
        piece_prefix = f"puzzle_{piece.label}_"
        piece_image_path = _save_png_array(sid, store, piece_rgba, piece_prefix)
        piece_matched_path = _save_npy_array(sid, store, piece_matched, piece_prefix)
        piece_boundary_path = _save_json_payload(
            sid,
            store,
            piece_boundary_payload,
            piece_prefix,
        )

        worker_params: dict[str, Any] = {
            "target_width_mm": piece.bbox_mm[2] - piece.bbox_mm[0],
            "spacer_thick": generate_params.spacer_thick,
            "structure_mode": generate_params.structure_mode.value,
            "color_mode": generate_params.color_mode.value,
            "add_loop": False,
            "loop_width": generate_params.loop_width,
            "loop_length": generate_params.loop_length,
            "loop_hole": generate_params.loop_hole,
            "loop_pos": None,
            "enable_fridge_magnet": generate_params.enable_fridge_magnet,
            "fridge_magnets": [item.model_dump(mode="json") for item in generate_params.fridge_magnets],
            "loop_angle": 0.0,
            "loop_offset_x": 0.0,
            "loop_offset_y": 0.0,
            "loop_position_preset": None,
            "modeling_mode": core_modeling_mode,
            "quantize_colors": generate_params.quantize_colors,
            "svg_pixels_per_mm": generate_params.svg_pixels_per_mm,
            "replacement_regions": None,
            "separate_backing": generate_params.separate_backing,
            "enable_relief": generate_params.enable_relief,
            "height_mode": height_mode,
            "color_height_map": generate_params.color_height_map,
            "heightmap_max_height": generate_params.heightmap_max_height,
            "enable_cleanup": generate_params.enable_cleanup,
            "enable_outline": generate_params.enable_outline,
            "outline_width": generate_params.outline_width,
            "enable_cloisonne": generate_params.enable_cloisonne,
            "wire_width_mm": generate_params.wire_width_mm,
            "wire_height_mm": generate_params.wire_height_mm,
            "free_color_set": free_color_set,
            "enable_coating": generate_params.enable_coating,
            "coating_height_mm": generate_params.coating_height_mm,
            "hue_weight": generate_params.hue_weight,
            "chroma_gate": generate_params.chroma_gate,
            "matched_rgb_path": piece_matched_path,
            "piece_boundary_geometry_path": piece_boundary_path,
            "disable_material_dilation": True,
            "center_on_bed": False,
            "printer_id": generate_params.printer_id,
            "slicer": generate_params.slicer,
            "nozzle_size": generate_params.nozzle_size,
            "device_profile_id": generate_params.device_profile_id,
            "relief_global_max_height": relief_global_max_height,
        }
        if session_material_source == "material_archive":
            selected_materials = session_data.get("selected_materials") or []
            worker_params["material_source"] = "material_archive"
            worker_params["selected_materials"] = selected_materials
            worker_params["material_layer_count"] = session_data.get("material_layer_count")
            worker_params["material_layer_height_mm"] = session_data.get("material_layer_height_mm")
            worker_params["material_grid_resolution"] = session_data.get(
                "material_grid_resolution"
            )
            requested_backing_index = (
                generate_params.material_backing_material_index
                if generate_params.material_backing_material_index is not None
                else session_data.get("material_backing_material_index")
            )
            worker_params["material_backing_material_index"] = _resolve_material_backing_index(
                selected_materials,
                requested_backing_index,
            )
        log.info(
            "Puzzle hybrid boundary enabled",
            extra={
                "event": "converter_puzzle_hybrid_boundary_enabled",
                "session_id": sid,
                "piece_label": piece.label,
            },
        )

        if generate_params.enable_relief and height_mode == "heightmap":
            if heightmap_grayscale is None:
                raise HTTPException(status_code=409, detail="Heightmap missing. Upload heightmap before puzzle generation.")
            x0, y0, x1, y1 = bbox_px
            piece_heightmap = np.array(heightmap_grayscale[y0:y1, x0:x1], copy=True)
            piece_heightmap = _resize_piece_array_nearest(
                piece_heightmap,
                _resolve_piece_worker_raster_size(piece),
            )
            piece_heightmap_path = _save_png_array(sid, store, piece_heightmap, piece_prefix)
            worker_params["heightmap_path"] = piece_heightmap_path

        futures.append(pool.submit(_submit_puzzle_worker, piece_image_path, lut_path, worker_params))
        piece_records.append(piece)

    if skipped_transparent_labels:
        warnings.append(
            f"Skipped {len(skipped_transparent_labels)} fully transparent puzzle pieces."
        )

    successful_entries: list[tuple[PuzzlePiece, str]] = []
    errors: list[str] = []
    for piece, future in zip(piece_records, futures):
        try:
            result = await future
            threemf_path = result.get("threemf_path")
            glb_path = result.get("glb_path")
            if threemf_path and os.path.exists(threemf_path):
                store.register_temp_file(sid, threemf_path)
                successful_entries.append((piece, threemf_path))
            else:
                status_msg = result.get("status_msg", "unknown")
                errors.append(f"{piece.label}: {status_msg}")
            if glb_path and os.path.exists(glb_path):
                store.register_temp_file(sid, glb_path)
        except asyncio.TimeoutError:
            errors.append(f"{piece.label}: generation timed out")
        except ROUTER_HANDLED_ERRORS as exc:
            errors.append(f"{piece.label}: {exc}")

    if errors:
        log.error(
            "Puzzle piece generation failed",
            extra={
                "event": "converter_puzzle_generate_failed",
                "session_id": sid,
                "error_type": "puzzle_piece_generation_failed",
                "error_message": "; ".join(errors[:5]),
            },
        )
        raise HTTPException(
            status_code=500,
            detail="Puzzle generation failed for one or more pieces: " + "; ".join(errors[:5]),
        )

    if not successful_entries:
        raise HTTPException(
            status_code=422,
            detail="Puzzle generation produced no non-transparent pieces.",
        )

    piece_sources = [
        PuzzlePiece3MFSource(
            label=piece.label,
            threemf_path=threemf_path,
            offset_x_mm=piece.bbox_mm[0],
            offset_y_mm=layout.total_height_mm - piece.bbox_mm[3],
        )
        for piece, threemf_path in successful_entries
    ]

    fd, combined_3mf_path = tempfile.mkstemp(prefix="puzzle_", suffix=".3mf", dir=TEMP_DIR)
    os.close(fd)
    combined_registered = False

    preview_colors = cache.get("preview_colors")
    slot_names = cache.get("slot_names")
    if preview_colors is None or slot_names is None:
        color_conf = cache.get("color_conf") or {}
        preview_colors = color_conf.get("preview")
        slot_names = color_conf.get("slots")

    overview_buffer = io.BytesIO()
    render_assembly_overview(
        source_rgba,
        layout,
        labels_enabled=request.labels_enabled,
    ).save(overview_buffer, format="PNG")
    overview_png_bytes = overview_buffer.getvalue()

    try:
        assemble_puzzle_3mf(
            piece_sources=piece_sources,
            output_path=combined_3mf_path,
            preview_colors=preview_colors,
            slot_names=slot_names,
            printer_id=generate_params.printer_id,
            slicer=generate_params.slicer,
            nozzle_size=generate_params.nozzle_size,
            device_profile_id=generate_params.device_profile_id,
            overview_png_bytes=overview_png_bytes,
        )
        download_id = registry.register_path(
            str(uuid.uuid4()),
            combined_3mf_path,
            filename=f"{base_name}_puzzle.3mf",
            ttl_seconds=BATCH_DOWNLOAD_TTL_SECONDS,
        )
        combined_registered = True
    except ROUTER_HANDLED_ERRORS as exc:
        log.error(
            "Puzzle 3MF assembly failed",
            extra={
                "event": "converter_puzzle_assembly_failed",
                "session_id": sid,
                "error_type": type(exc).__name__,
                "error_message": _PUZZLE_ASSEMBLY_FAILED_DETAIL,
            },
        )
        raise HTTPException(status_code=500, detail=_PUZZLE_ASSEMBLY_FAILED_DETAIL)
    finally:
        if not combined_registered:
            _remove_temp_path(combined_3mf_path)

    log.info(
        "Puzzle 3MF generated",
        extra={
            "event": "converter_puzzle_generate_done",
            "session_id": sid,
            "piece_count": len(successful_entries),
            "grid_cols": layout.cols,
            "grid_rows": layout.rows,
            "warning_count": len(warnings),
            "skipped_transparent_count": len(skipped_transparent_labels),
            "download_id": download_id,
        },
    )
    return PuzzleGenerateResponse(
        status="ok",
        message=f"Generated {len(successful_entries)} puzzle pieces into a single 3MF",
        download_url=f"/api/files/{download_id}",
        threemf_disk_path=None,
        piece_count=len(successful_entries),
        grid_cols=layout.cols,
        grid_rows=layout.rows,
        warnings=warnings,
    )
