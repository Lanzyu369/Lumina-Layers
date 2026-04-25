"""Converter router replace module."""

from __future__ import annotations

import os
import uuid

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.schemas.converter import (
    ColorHighlightRequest,
    ColorHighlightResponse,
    ColorMergePreviewRequest,
    ColorReplaceBatchRequest,
    ColorReplaceRequest,
    RecipeOverrideApplyRequest,
    RecipePredictRequest,
    RegionDetectRequest,
    RegionDetectResponse,
    RegionRecipeRequest,
    RegionReplaceBatchItem,
    RegionReplaceBatchRequest,
    RegionReplaceRequest,
    RegionReplaceResponse,
    RegionRequantizeRequest,
    ResetReplacementsRequest,
    SourceColorPickRequest,
    SourceColorPickResponse,
    VirtualMaterial,
)
from api.schemas.responses import (
    ColorReplaceResponse,
    MergePreviewResponse,
    RecipeOverrideApplyResponse,
    RecipePredictResponse,
    RegionRecipeEntry,
    RegionRecipeResponse,
    ResetReplacementsResponse,
)
from api.session_store import SessionStore
from config import LUTMetadata, PaletteEntry
from core.color_merger import ColorMerger
from core.color_replacement import ColorReplacementManager
from core.gradient_group_analyzer import REGION_ID_ENCODING_MULTIPLIER
from core.gradient_region_requantize import requantize_gradient_regions
from core.converter import (
    extract_color_palette,
    _compute_connected_region_mask_4n,
)
from core.material_cache import DEFAULT_GRID_RESOLUTION, load_material_solver_cache_with_fallback
from core.material_lut_synthesis import load_multiple_materials, solve_image_colors_optimal
from core.pipeline.processing_ops.lut_loader import load_lut
from core.predictive_lut import predict_recipe_color
from core.recipe_order import (
    convert_recipe_between_orders,
    normalize_layer_order,
    pad_recipe_to_layer_count,
)
from utils.lut_manager import LUTManager
from api.structured_logging import get_logger

from .common import (
    ROUTER_HANDLED_ERRORS,
    _handle_core_error,
    _image_to_png_bytes,
    _require_preview_cache,
    _require_session,
    recompute_gradient_groups_into_session,
)
from .async_glb import schedule_glb_build

router = APIRouter()
log = get_logger(__name__)


def _render_styled_preview_bytes(replaced_rgb: np.ndarray, cache: dict) -> bytes:
    """Render a raw RGBA preview from replaced_rgb with transparency.
    从替换后的 matched_rgb 生成带透明通道的原始 RGBA 预览。

    Returns raw RGBA so that pixel coordinates match previewPixelWidth ×
    previewPixelHeight exactly, keeping SVG contour overlays and
    click-to-pixel mapping correctly aligned in ColorPreview2D.

    Args:
        replaced_rgb: Updated matched_rgb array (H, W, 3) after color replacement.
        cache: Preview cache dict containing mask_solid, etc.

    Returns:
        PNG bytes of the raw RGBA preview image.
    """
    mask_solid: np.ndarray | None = cache.get("mask_solid")
    h, w = replaced_rgb.shape[:2]

    # Reconstruct RGBA from replaced_rgb + mask_solid
    preview_rgba = np.zeros((h, w, 4), dtype=np.uint8)
    if mask_solid is not None:
        preview_rgba[mask_solid, :3] = replaced_rgb[mask_solid]
        preview_rgba[mask_solid, 3] = 255
    else:
        preview_rgba[..., :3] = replaced_rgb
        preview_rgba[..., 3] = 255

    # Update cache's preview_rgba for consistency
    cache["preview_rgba"] = preview_rgba.copy()

    return _image_to_png_bytes(preview_rgba)


def _get_region_mask_items_for_ids(
    session_data: dict,
    region_ids: list[str],
) -> list[tuple[str, np.ndarray]]:
    region_masks = session_data.get("selected_region_masks") or {}
    if not isinstance(region_masks, dict):
        region_masks = {}

    masks: list[tuple[str, np.ndarray]] = []
    seen_region_ids: set[str] = set()
    for region_id in region_ids:
        mask = region_masks.get(region_id)
        if isinstance(region_id, str) and isinstance(mask, np.ndarray) and region_id not in seen_region_ids:
            masks.append((region_id, mask))
            seen_region_ids.add(region_id)

    if not masks:
        fallback_mask = session_data.get("selected_region_mask")
        fallback_id = session_data.get("selected_region_id")
        if isinstance(fallback_id, str) and isinstance(fallback_mask, np.ndarray) and (
            not region_ids or fallback_id in region_ids
        ):
            masks.append((fallback_id, fallback_mask))
    return masks


def _upgrade_material_matrix_layers(
    material_matrix: np.ndarray,
    target_layers: int,
) -> np.ndarray:
    if material_matrix.shape[2] >= target_layers:
        return material_matrix.copy()
    pad = np.zeros(
        (*material_matrix.shape[:2], target_layers - material_matrix.shape[2]),
        dtype=material_matrix.dtype,
    )
    return np.concatenate([material_matrix.copy(), pad], axis=2)


def _sync_lut_material_matrix_for_diff(
    session_data: dict,
    cache: dict,
    diff_mask: np.ndarray,
    updated_rgb: np.ndarray,
) -> None:
    material_matrix = cache.get("material_matrix")
    if material_matrix is None:
        return
    lut_path = session_data.get("lut_path")
    color_mode = session_data.get("color_mode")
    if not isinstance(lut_path, str) or not lut_path or not os.path.exists(lut_path):
        return
    if not isinstance(color_mode, str) or not color_mode:
        return
    target_layers = int(
        cache.get("color_layers")
        or session_data.get("color_layers")
        or material_matrix.shape[2]
    )
    layer_height_mm = float(
        cache.get("layer_height_mm")
        or session_data.get("layer_height_mm")
        or 0.08
    )
    try:
        lut_data = load_lut(
            lut_path,
            color_mode,
            color_layers=target_layers,
            layer_height_mm=layer_height_mm,
            model_enable=bool(session_data.get("model_enable", False)),
            model_only=bool(session_data.get("model_only", False)),
            model_threshold=(
                float(session_data["model_threshold"])
                if session_data.get("model_threshold") is not None
                else None
            ),
            model_margin=(
                float(session_data["model_margin"])
                if session_data.get("model_margin") is not None
                else None
            ),
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        log.warning(
            "LUT replacement stack sync failed",
            extra={
                "event": "converter_replace_lut_stack_sync_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return

    ref_stacks = np.asarray(lut_data.get("ref_stacks"))
    kdtree = lut_data.get("kdtree")
    if ref_stacks.ndim != 2 or ref_stacks.shape[0] == 0 or kdtree is None:
        return

    new_material_matrix = _upgrade_material_matrix_layers(
        np.asarray(material_matrix),
        int(ref_stacks.shape[1]),
    )
    unique_colors = np.unique(updated_rgb[diff_mask], axis=0)
    for color in unique_colors:
        color_mask = np.all(updated_rgb == color, axis=-1) & diff_mask
        _, lut_idx = kdtree.query(
            _rgb_to_lab(np.asarray(color, dtype=np.uint8).reshape(1, 3))
        )
        stack = ref_stacks[int(np.asarray(lut_idx).reshape(-1)[0])]
        new_material_matrix[color_mask] = np.asarray(
            stack,
            dtype=new_material_matrix.dtype,
        )
    cache["material_matrix"] = new_material_matrix
    cache["color_layers"] = int(new_material_matrix.shape[2])


def _sync_material_archive_matrix_for_diff(
    session_data: dict,
    cache: dict,
    diff_mask: np.ndarray,
    updated_rgb: np.ndarray,
) -> None:
    material_matrix = cache.get("material_matrix")
    if material_matrix is None:
        return
    selected_materials = session_data.get("selected_materials") or []
    if not isinstance(selected_materials, list) or len(selected_materials) == 0:
        return

    try:
        materials = load_multiple_materials(selected_materials)
    except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
        log.warning(
            "Material-archive replacement stack sync failed during material load",
            extra={
                "event": "converter_replace_material_stack_load_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return

    layer_count = int(
        session_data.get("material_layer_count")
        or cache.get("color_layers")
        or material_matrix.shape[2]
    )
    layer_height_mm = float(
        session_data.get("material_layer_height_mm")
        or cache.get("layer_height_mm")
        or session_data.get("layer_height_mm")
        or 0.08
    )
    substrate = str(
        cache.get("material_substrate")
        or session_data.get("material_substrate")
        or "white"
    )
    target_rgbs = np.unique(updated_rgb[diff_mask], axis=0).astype(np.uint8, copy=False)

    grid_resolution = int(
        session_data.get("material_grid_resolution")
        or DEFAULT_GRID_RESOLUTION
    )
    log.info(
        "material-archive matrix sync: solving",
        extra={
            "event": "converter_replace_material_sync_solve",
            "target_rgb_count": int(target_rgbs.shape[0]),
            "target_rgbs_sample": target_rgbs[:3].tolist(),
            "grid_resolution": grid_resolution,
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "material_count": len(materials),
        },
    )
    try:
        solver_cache, _actual_grid = load_material_solver_cache_with_fallback(
            materials=materials,
            layer_count=layer_count,
            layer_height_mm=layer_height_mm,
            substrate=substrate,
            grid_resolution=grid_resolution,
        )
        _solve_path = "cache" if solver_cache is not None else "mitm"
        if solver_cache is not None:
            resolved_rgb, recipes, _delta_e = solver_cache.lookup(target_rgbs, materials)
        else:
            resolved_rgb, recipes, _delta_e = solve_image_colors_optimal(
                target_rgbs,
                materials,
                layer_count=layer_count,
                layer_height_mm=layer_height_mm,
                substrate=substrate,
            )
        log.info(
            "material-archive matrix sync: solved",
            extra={
                "event": "converter_replace_material_sync_solved",
                "solve_path": _solve_path,
                "actual_grid": _actual_grid,
                "target_rgbs_sample": target_rgbs[:3].tolist(),
                "resolved_rgbs_sample": resolved_rgb[:3].tolist() if resolved_rgb is not None else None,
            },
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        log.warning(
            "Material-archive replacement stack sync solve failed",
            extra={
                "event": "converter_replace_material_stack_solve_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return

    if recipes.shape[1] > 1:
        recipes = np.ascontiguousarray(recipes[:, ::-1])

    new_material_matrix = _upgrade_material_matrix_layers(
        np.asarray(material_matrix),
        int(recipes.shape[1]),
    )
    color_masks = [
        np.all(updated_rgb == color, axis=-1) & diff_mask for color in target_rgbs
    ]
    for idx, color_mask in enumerate(color_masks):
        if not np.any(color_mask):
            continue
        updated_rgb[color_mask] = resolved_rgb[idx].astype(np.uint8, copy=False)
        new_material_matrix[color_mask] = recipes[idx].astype(
            new_material_matrix.dtype,
            copy=False,
        )
    cache["material_matrix"] = new_material_matrix
    cache["color_layers"] = int(new_material_matrix.shape[2])
    cache["layer_height_mm"] = float(layer_height_mm)


def _sync_material_matrix_after_rgb_change(
    session_data: dict,
    cache: dict,
    previous_rgb: np.ndarray,
    updated_rgb: np.ndarray,
) -> None:
    material_matrix = cache.get("material_matrix")
    mask_solid = cache.get("mask_solid")
    if material_matrix is None or mask_solid is None:
        return

    diff_mask = np.any(previous_rgb != updated_rgb, axis=-1) & np.asarray(
        mask_solid,
        dtype=bool,
    )
    if not np.any(diff_mask):
        return

    if str(session_data.get("material_source") or "lut") == "material_archive":
        _sync_material_archive_matrix_for_diff(session_data, cache, diff_mask, updated_rgb)
    else:
        _sync_lut_material_matrix_for_diff(session_data, cache, diff_mask, updated_rgb)

    cache["color_palette"] = extract_color_palette(cache)

# Extend base tuple with IndexError for array-index operations
# in region-detect / region-replace endpoints.
REPLACE_HANDLED_ERRORS = ROUTER_HANDLED_ERRORS + (IndexError,)


def _rgb_pixel_to_hex(pixel: np.ndarray) -> str:
    rgb = np.asarray(pixel).reshape(-1)
    if rgb.size < 3:
        raise ValueError("RGB pixel must contain at least three channels.")
    r, g, b = (int(np.clip(value, 0, 255)) for value in rgb[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


@router.post("/replace-color")
def replace_color(
    request: ColorReplaceRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ColorReplaceResponse:
    """Replace a single color in the current session preview (synchronous).
    替换当前 session 预览中的单个颜色（同步执行）。

    This endpoint is intentionally kept synchronous (no process pool offload)
    because the computation is lightweight: it operates on the cached
    matched_rgb array (small preview image) with simple NumPy mask operations
    over a small number of user-driven color replacements (typically 1-10).
    The heavy image processing was already completed in the /preview step.
    此端点有意保持同步执行（不卸载到进程池），因为计算量很小：
    仅对缓存的 matched_rgb 数组（小尺寸预览图）执行简单的 NumPy 掩码操作，
    颜色替换数量由用户驱动（通常 1-10 个）。
    繁重的图像处理已在 /preview 步骤中完成。

    Args:
        request (ColorReplaceRequest): Color replacement parameters. (颜色替换参数)
        store (SessionStore): Session store dependency. (会话存储依赖)
        registry (FileRegistry): File registry dependency. (文件注册表依赖)

    Returns:
        ColorReplaceResponse: Replacement result with preview URL. (替换结果及预览 URL)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache available. (无预览缓存)
        HTTPException(500): Internal processing error. (内部处理错误)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    try:
        # Parse hex colors to RGB tuples
        selected_rgb = ColorReplacementManager._hex_to_color(request.selected_color)
        replacement_rgb = ColorReplacementManager._hex_to_color(request.replacement_color)

        # Build manager from all existing replacement_regions
        manager = ColorReplacementManager()
        for record in session_data.get("replacement_regions", []):
            orig = ColorReplacementManager._hex_to_color(record["selected_color"])
            repl = ColorReplacementManager._hex_to_color(record["replacement_color"])
            manager.add_replacement(orig, repl)

        # Add the new replacement
        manager.add_replacement(selected_rgb, replacement_rgb)

        # Apply all replacements to the original matched_rgb
        matched_rgb: np.ndarray = cache["matched_rgb"]
        previous_rgb = matched_rgb.copy()
        replaced_rgb = manager.apply_to_image(matched_rgb)

        # --- diagnostic logging ---
        diff_pixels = int(np.any(previous_rgb != replaced_rgb, axis=-1).sum())
        log.info(
            "replace-color diag",
            extra={
                "event": "converter_replace_color_diag",
                "selected_color": request.selected_color,
                "replacement_color": request.replacement_color,
                "material_source": session_data.get("material_source"),
                "matched_rgb_shape": list(matched_rgb.shape),
                "diff_pixel_count": diff_pixels,
                "replacement_region_count": len(session_data.get("replacement_regions", [])),
                "has_material_matrix": cache.get("material_matrix") is not None,
                "has_mask_solid": cache.get("mask_solid") is not None,
            },
        )
        # --- end diagnostic logging ---

        # Update cache so 3D preview reflects replacements
        cache["matched_rgb"] = replaced_rgb
        _sync_material_matrix_after_rgb_change(
            session_data,
            cache,
            previous_rgb,
            replaced_rgb,
        )
        store.put(request.session_id, "preview_cache", cache)

        # Generate styled preview PNG (with bed grid and transparency)
        preview_bytes = _render_styled_preview_bytes(replaced_rgb, cache)
        preview_id = registry.register_bytes(request.session_id, preview_bytes, "preview_replaced.png")

        # Schedule async segmented-GLB rebuild so this response returns
        # immediately after the PNG is ready. Frontend polls
        # /api/convert/glb-status/{session_id} to pick up the new GLB URL.
        # 异步重建分段 GLB：响应在 PNG 就绪后立即返回，前端轮询 glb-status。
        schedule_glb_build(request.session_id, store, registry, cache)
        glb_url: str | None = None

        # Save history snapshot (deep copy of regions before this change) for undo
        current_regions = session_data.get("replacement_regions", [])
        snapshot = [dict(r) for r in current_regions]
        history = list(session_data.get("replacement_history", []))
        history.append(snapshot)
        store.put(request.session_id, "replacement_history", history)

        # Append new replacement record
        current_regions.append(
            {
                "selected_color": request.selected_color,
                "replacement_color": request.replacement_color,
            }
        )
        store.put(request.session_id, "replacement_regions", current_regions)

    except HTTPException:
        raise
    except REPLACE_HANDLED_ERRORS as e:
        _handle_core_error(e, "Color replacement")

    return ColorReplaceResponse(
        status="ok",
        message="Color replaced successfully",
        preview_url=f"/api/files/{preview_id}",
        preview_3d_url=glb_url,
        replacement_count=len(current_regions),
    )


@router.post("/reset-replacements", response_model=ResetReplacementsResponse)
def reset_replacements(
    request: ResetReplacementsRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ResetReplacementsResponse:
    """Reset all color replacements and restore original preview.
    重置所有颜色替换并恢复原始预览。

    Clears replacement_regions and replacement_history from the session,
    then regenerates the preview from the original matched_rgb cache.
    清空 session 中的 replacement_regions 和 replacement_history，
    然后从原始 matched_rgb 缓存重新生成预览。

    Args:
        request (ResetReplacementsRequest): Reset request with session_id. (重置请求)
        store (SessionStore): Session store dependency. (会话存储依赖)
        registry (FileRegistry): File registry dependency. (文件注册表依赖)

    Returns:
        ResetReplacementsResponse: Reset result with original preview URL. (重置结果及原始预览 URL)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache available. (无预览缓存)
        HTTPException(500): Internal processing error. (内部处理错误)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    try:
        # Clear replacement state
        store.put(request.session_id, "replacement_regions", [])
        store.put(request.session_id, "replacement_history", [])
        previous_rgb = np.asarray(cache.get("matched_rgb")).copy()

        # Restore matched_rgb from the pristine original saved at preview time.
        # region-replace mutates cache["matched_rgb"] in-place, so we must
        # use the untouched copy to truly reset.
        original_rgb: np.ndarray | None = session_data.get("original_matched_rgb")
        if original_rgb is not None:
            # Restore cache to original state
            cache["matched_rgb"] = original_rgb.copy()
            source_rgb = original_rgb
        else:
            # Fallback: no original saved (legacy session), use current cache
            source_rgb = cache["matched_rgb"]

        original_material_matrix: np.ndarray | None = session_data.get(
            "original_material_matrix"
        )
        if original_material_matrix is not None:
            cache["material_matrix"] = original_material_matrix.copy()
        elif original_rgb is not None:
            _sync_material_matrix_after_rgb_change(
                session_data,
                cache,
                previous_rgb,
                cache["matched_rgb"],
            )
        cache["color_palette"] = extract_color_palette(cache)
        store.put(request.session_id, "preview_cache", cache)

        # Regenerate preview from original matched_rgb (no replacements applied)
        preview_bytes = _image_to_png_bytes(source_rgb)
        preview_id = registry.register_bytes(request.session_id, preview_bytes, "preview_reset.png")

        # Async GLB rebuild from restored matched_rgb. Same rationale as
        # /replace-color: keep HTTP response snappy, let the frontend poll.
        # 异步 GLB 重建，理由同 /replace-color。
        schedule_glb_build(request.session_id, store, registry, cache)
        glb_url: str | None = None
    except HTTPException:
        raise
    except REPLACE_HANDLED_ERRORS as e:
        _handle_core_error(e, "Reset replacements")

    return ResetReplacementsResponse(
        status="ok",
        message="All replacements cleared",
        preview_url=f"/api/files/{preview_id}",
        preview_glb_url=glb_url,
    )


@router.post("/source-color-pick", response_model=SourceColorPickResponse)
def source_color_pick(
    request: SourceColorPickRequest,
    store: SessionStore = Depends(get_session_store),
) -> SourceColorPickResponse:
    """Resolve the original source colour at a preview pixel.
    解析预览像素位置的原始源色。

    Select all clicks must be based on the original matched colour, not the
    currently displayed recoloured preview. ``original_matched_rgb`` is the
    preferred source; legacy sessions fall back to the current
    ``preview_cache["matched_rgb"]`` so old previews can still be clicked.
    全选点图必须按原始匹配色选中，而不是按已经换色后的展示图。优先读取
    ``original_matched_rgb``；旧 session 没有它时回退到当前
    ``preview_cache["matched_rgb"]``，避免旧预览完全不可点。

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): Preview cache is incomplete or inconsistent.
            (预览缓存缺失或尺寸不一致)
        HTTPException(400): Coordinates are out of bounds or background.
            (坐标越界或点在背景上)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    try:
        source_rgb = session_data.get("original_matched_rgb")
        if source_rgb is None:
            source_rgb = cache.get("matched_rgb")

        quantized_image = cache.get("quantized_image")
        mask_solid = cache.get("mask_solid")
        if source_rgb is None or quantized_image is None or mask_solid is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Preview cache missing original_matched_rgb/matched_rgb, "
                    "quantized_image, or mask_solid."
                ),
            )

        source_arr = np.asarray(source_rgb)
        quantized_arr = np.asarray(quantized_image)
        mask_arr = np.asarray(mask_solid, dtype=bool)
        if source_arr.ndim != 3 or source_arr.shape[2] < 3:
            raise HTTPException(
                status_code=409,
                detail="Preview source matched RGB cache has invalid shape.",
            )
        if quantized_arr.ndim != 3 or quantized_arr.shape[2] < 3:
            raise HTTPException(
                status_code=409,
                detail="Preview quantized image cache has invalid shape.",
            )

        height, width = source_arr.shape[:2]
        if quantized_arr.shape[:2] != (height, width) or mask_arr.shape != (
            height,
            width,
        ):
            raise HTTPException(
                status_code=409,
                detail="Preview cache dimensions are inconsistent.",
            )

        x, y = request.x, request.y
        if not (0 <= x < width and 0 <= y < height):
            raise HTTPException(
                status_code=400,
                detail=f"Coordinates ({x}, {y}) out of bounds for image {width}x{height}.",
            )
        if not bool(mask_arr[y, x]):
            raise HTTPException(
                status_code=400,
                detail="Clicked on background area.",
            )

        return SourceColorPickResponse(
            source_matched_hex=_rgb_pixel_to_hex(source_arr[y, x]),
            quantized_hex=_rgb_pixel_to_hex(quantized_arr[y, x]),
        )
    except HTTPException:
        raise
    except REPLACE_HANDLED_ERRORS as exc:
        _handle_core_error(exc, "Source color pick")


@router.post("/color-highlight", response_model=ColorHighlightResponse)
def color_highlight(
    request: ColorHighlightRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ColorHighlightResponse:
    """Highlight all pixels matching any of the given colors in the preview.
    在预览图中高亮所有匹配给定颜色的像素。

    Generates a preview image with semi-transparent cyan overlay on every
    pixel whose color matches any entry in ``color_hexes``.  Uses the same
    highlight style as ``region-detect`` (cyan ``[0, 200, 255]``, alpha 0.45).
    生成预览图，对颜色匹配 ``color_hexes`` 中任意条目的所有像素施加
    半透明青色叠加，样式与 ``region-detect`` 一致。

    Args:
        request: Color highlight parameters. (颜色高亮参数)
        store: Session store dependency. (会话存储依赖)
        registry: File registry dependency. (文件注册表依赖)

    Returns:
        ColorHighlightResponse: Highlighted preview URL. (高亮预览图 URL)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    try:
        matched_rgb: np.ndarray | None = cache.get("matched_rgb")
        mask_solid: np.ndarray | None = cache.get("mask_solid")

        if matched_rgb is None or mask_solid is None:
            raise HTTPException(
                status_code=409,
                detail="Preview cache missing matched_rgb or mask_solid.",
            )

        # Parse color hex strings → RGB tuples
        target_rgbs: list[np.ndarray] = []
        for hex_str in request.color_hexes:
            h = hex_str.lstrip("#")
            if len(h) != 6:
                continue
            target_rgbs.append(np.array([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)], dtype=np.uint8))

        if not target_rgbs:
            raise HTTPException(status_code=400, detail="No valid color hex values provided.")

        # Optional region-scope constraint. When the Gradient Groups panel
        # asks us to highlight the colours inside one specific sub-region,
        # we clip the scan to the *exact* pixel mask of that sub-region so
        # unrelated same-colour pixels elsewhere on the canvas stay dark —
        # fixes the "clicking a sub-region lights up the whole group" UX
        # bug. Preferred path: ``gradient_group_index`` + ``gradient_region_index``
        # pair (uses the cached per-pixel region_id_map). Legacy fallback:
        # ``region_bbox`` rectangular scope.
        # 可选区域裁剪：最优先使用渐变分组/子区域编号精确裁剪，回退到
        # 矩形 bbox。修复"点小分组把整组都点亮"的 UX 问题。
        img_h, img_w = matched_rgb.shape[:2]
        region_scope_mask: np.ndarray | None = None

        group_idx = request.gradient_group_index
        region_idx = request.gradient_region_index
        # Diagnostic: capture which scope path the endpoint actually takes
        # given the request payload it actually received. This is the most
        # reliable way to tell apart "frontend forgot to send identifiers"
        # from "backend silently dropped them because the process wasn't
        # restarted after the schema change".
        # 诊断日志：明确记录 endpoint 真正收到的 scope 字段与分支走向，
        # 便于区分"前端未传"与"后端未重启（静默丢弃字段）"。
        log.info(
            "color_highlight_invoked",
            extra={
                "event": "color_highlight_invoked",
                "session_id": request.session_id,
                "color_hex_count": len(request.color_hexes),
                "received_gradient_group_index": group_idx,
                "received_gradient_region_index": region_idx,
                "received_region_bbox": request.region_bbox,
                "image_shape": [img_h, img_w],
            },
        )
        if (group_idx is None) != (region_idx is None):
            raise HTTPException(
                status_code=400,
                detail=(
                    "gradient_group_index and gradient_region_index must be "
                    "provided together."
                ),
            )
        if group_idx is not None and region_idx is not None:
            # region_id_map is stored alongside ``gradient_groups`` at the
            # session-data top level (not inside ``preview_cache``) because
            # it's derived metadata computed *after* the preview cache is
            # finalised. Mirror that layout here for consistency.
            # region_id_map 与 gradient_groups 并列存于 session_data 顶层，
            # 与 preview_cache 分离。
            region_id_map = session_data.get("gradient_region_id_map")
            if region_id_map is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Preview cache has no gradient_region_id_map; "
                        "re-run /preview to refresh gradient-region metadata."
                    ),
                )
            region_id_arr = np.asarray(region_id_map)
            if region_id_arr.shape != (img_h, img_w):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Cached gradient_region_id_map shape "
                        f"{region_id_arr.shape} does not match preview "
                        f"{img_h}x{img_w}; re-run /preview."
                    ),
                )
            encoded_id = (
                int(group_idx) * REGION_ID_ENCODING_MULTIPLIER + int(region_idx)
            )
            region_scope_mask = region_id_arr == np.uint32(encoded_id)
            region_pixel_count = int(region_scope_mask.sum())
            log.info(
                "color_highlight_using_region_mask",
                extra={
                    "event": "color_highlight_scope_region_mask",
                    "group_index": int(group_idx),
                    "region_index": int(region_idx),
                    "encoded_id": int(encoded_id),
                    "region_pixel_count": region_pixel_count,
                    "region_id_map_nonzero_count": int(
                        (region_id_arr != 0).sum()
                    ),
                },
            )
            if region_pixel_count == 0:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"No pixels found for gradient group "
                        f"{group_idx}, region {region_idx}."
                    ),
                )
        elif request.region_bbox is not None:
            x0, y0, x1, y1 = request.region_bbox
            if not (0 <= x0 < x1 <= img_w and 0 <= y0 < y1 <= img_h):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"region_bbox {request.region_bbox} out of bounds for "
                        f"image {img_w}x{img_h}."
                    ),
                )
            region_scope_mask = np.zeros((img_h, img_w), dtype=bool)
            region_scope_mask[y0:y1, x0:x1] = True

        # Build combined mask: pixels matching ANY of the given colors
        combined_mask = np.zeros((img_h, img_w), dtype=bool)
        for rgb in target_rgbs:
            combined_mask |= np.all(matched_rgb == rgb, axis=-1) & mask_solid
        if region_scope_mask is not None:
            combined_mask &= region_scope_mask

        # Apply cyan highlight (same style as region-detect)
        highlight_color = np.array([0, 200, 255], dtype=np.uint8)
        alpha = 0.45
        preview_img: np.ndarray = matched_rgb.copy()
        preview_img[combined_mask] = (
            preview_img[combined_mask].astype(np.float32) * (1 - alpha)
            + highlight_color.astype(np.float32) * alpha
        ).astype(np.uint8)

        preview_bytes: bytes = _image_to_png_bytes(preview_img)
        preview_id: str = registry.register_bytes(
            request.session_id, preview_bytes, "color_highlight.png",
        )

    except HTTPException:
        raise
    except REPLACE_HANDLED_ERRORS as e:
        _handle_core_error(e, "Color highlight")

    return ColorHighlightResponse(preview_url=f"/api/files/{preview_id}")


@router.post("/region-detect", response_model=RegionDetectResponse)
def region_detect(
    request: RegionDetectRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> RegionDetectResponse:
    """Detect a connected region of same-colored pixels at the click position.
    检测点击位置处同色像素的连通区域。

    This endpoint is synchronous because the BFS flood-fill on a small
    quantized preview image is lightweight. The heavy image processing
    was already completed in the /preview step.
    此端点同步执行，因为在小尺寸量化预览图上的 BFS 洪水填充计算量很小。
    繁重的图像处理已在 /preview 步骤中完成。

    Args:
        request (RegionDetectRequest): Region detection parameters. (区域检测参数)
        store (SessionStore): Session store dependency. (会话存储依赖)
        registry (FileRegistry): File registry dependency. (文件注册表依赖)

    Returns:
        RegionDetectResponse: Detected region metadata with preview URL. (检测到的区域元数据及预览 URL)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache available. (无预览缓存)
        HTTPException(400): Click coordinates out of bounds or on background. (点击坐标越界或在背景上)
        HTTPException(500): Internal processing error. (内部处理错误)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    try:
        quantized_image: np.ndarray | None = cache.get("quantized_image")
        mask_solid: np.ndarray | None = cache.get("mask_solid")
        matched_rgb: np.ndarray | None = cache.get("matched_rgb")

        if quantized_image is None or mask_solid is None or matched_rgb is None:
            raise HTTPException(
                status_code=409,
                detail="Preview cache missing quantized_image, mask_solid, or matched_rgb.",
            )

        h, w = quantized_image.shape[:2]
        x, y = request.x, request.y

        if not (0 <= x < w and 0 <= y < h):
            raise HTTPException(
                status_code=400,
                detail=f"Coordinates ({x}, {y}) out of bounds for image {w}x{h}.",
            )

        if not mask_solid[y, x]:
            raise HTTPException(
                status_code=400,
                detail="Clicked on background area.",
            )

        # Compute connected region mask via 4-neighbor BFS
        region_mask: np.ndarray = _compute_connected_region_mask_4n(quantized_image, mask_solid, x, y)

        pixel_count: int = int(np.count_nonzero(region_mask))
        if pixel_count == 0:
            raise HTTPException(
                status_code=400,
                detail="No connected region found at the click position.",
            )

        # Extract region color from matched_rgb at click position
        r, g, b = int(matched_rgb[y, x, 0]), int(matched_rgb[y, x, 1]), int(matched_rgb[y, x, 2])
        color_hex: str = f"#{r:02x}{g:02x}{b:02x}"

        # Store region_mask in session for subsequent region-replace
        region_id: str = str(uuid.uuid4())
        store.put(request.session_id, "selected_region_mask", region_mask)
        store.put(request.session_id, "selected_region_id", region_id)
        existing_masks = session_data.get("selected_region_masks") or {}
        if not isinstance(existing_masks, dict):
            existing_masks = {}
        existing_masks[region_id] = region_mask
        store.put(request.session_id, "selected_region_masks", existing_masks)
        region_masks = dict(session_data.get("region_masks") or {})
        region_masks[region_id] = region_mask
        store.put(request.session_id, "region_masks", region_masks)
        region_masks = session_data.get("selected_region_masks") or {}
        if not isinstance(region_masks, dict):
            region_masks = {}
        region_masks = dict(region_masks)
        region_masks[region_id] = region_mask
        store.put(request.session_id, "selected_region_masks", region_masks)

        # Generate highlighted preview: overlay region with semi-transparent highlight
        highlight_color = np.array([0, 200, 255], dtype=np.uint8)  # cyan highlight
        alpha = 0.45
        preview_img: np.ndarray = matched_rgb.copy()
        preview_img[region_mask] = (
            preview_img[region_mask].astype(np.float32) * (1 - alpha) + highlight_color.astype(np.float32) * alpha
        ).astype(np.uint8)

        preview_bytes: bytes = _image_to_png_bytes(preview_img)
        preview_id: str = registry.register_bytes(request.session_id, preview_bytes, "region_highlight.png")

        # Extract 2D contours from region_mask for frontend RGB outline rendering
        region_contours: list[list[list[float]]] | None = None
        target_w = cache.get("target_w")
        target_width_mm = cache.get("target_width_mm")
        if target_w and target_width_mm and target_w > 0:
            pixel_scale = target_width_mm / target_w
            mask_u8 = region_mask.astype(np.uint8) * 255
            cv_contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            region_contours = []
            for cnt in cv_contours:
                if len(cnt) < 3:
                    continue
                pts = cnt.squeeze(1).astype(float)
                world_pts: list[list[float]] = []
                for px, py in pts:
                    x_mm = float(px * pixel_scale)
                    y_mm = float((h - py) * pixel_scale)
                    world_pts.append([x_mm, y_mm])
                region_contours.append(world_pts)

    except HTTPException:
        raise
    except REPLACE_HANDLED_ERRORS as e:
        _handle_core_error(e, "Region detection")

    return RegionDetectResponse(
        region_id=region_id,
        color_hex=color_hex,
        pixel_count=pixel_count,
        preview_url=f"/api/files/{preview_id}",
        contours=region_contours,
    )


@router.post("/region-replace", response_model=RegionReplaceResponse)
def region_replace(
    request: RegionReplaceRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> RegionReplaceResponse:
    """Replace color only within the previously detected connected region.
    仅替换先前检测到的连通区域内的颜色。

    This endpoint is synchronous because it performs a simple masked
    pixel assignment on the cached matched_rgb array (small preview image).
    此端点同步执行，因为仅对缓存的 matched_rgb 数组执行简单的掩码像素赋值。

    Args:
        request (RegionReplaceRequest): Region replacement parameters. (区域替换参数)
        store (SessionStore): Session store dependency. (会话存储依赖)
        registry (FileRegistry): File registry dependency. (文件注册表依赖)

    Returns:
        RegionReplaceResponse: Replacement result with preview URL. (替换结果及预览 URL)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache or no region selected. (无预览缓存或未选中区域)
        HTTPException(500): Internal processing error. (内部处理错误)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    try:
        matched_rgb: np.ndarray | None = cache.get("matched_rgb")
        if matched_rgb is None:
            raise HTTPException(
                status_code=409,
                detail="Preview cache missing matched_rgb.",
            )

        # Two mask sources are supported. When the Gradient Groups panel
        # routes a "replace inside this banded region only" click, the
        # payload carries ``gradient_group_index`` + ``gradient_region_index``
        # and we rebuild the mask from the cached per-pixel region_id_map.
        # Otherwise we fall back to the legacy click-detected flood-fill mask
        # that ``region_detect`` stashed under ``selected_region_mask``.
        # Rebuilding from region_id_map lets one gradient sub-region be
        # edited without touching other regions that happen to share the
        # same quantised hex — that was the "replace cyan band → whole body
        # turns red" bug we are fixing.
        # 支持两种 mask 来源：渐变区域（优先，使用缓存 region_id_map）和
        # 点击检测区域（legacy）。渐变区域路径让单个子区域换色不会污染
        # 共用同一量化 hex 的其它区域——修复"换一条 cyan 带 → 全身皮肤
        # 变色"的 bug。
        img_h, img_w = matched_rgb.shape[:2]
        region_mask: np.ndarray | None = None
        mask_source: str = "click"
        gradient_group_idx = request.gradient_group_index
        gradient_region_idx = request.gradient_region_index
        if gradient_group_idx is not None:
            region_id_map = session_data.get("gradient_region_id_map")
            if region_id_map is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Preview cache has no gradient_region_id_map; "
                        "re-run /preview to refresh gradient-region metadata."
                    ),
                )
            region_id_arr = np.asarray(region_id_map)
            if region_id_arr.shape != (img_h, img_w):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Cached gradient_region_id_map shape "
                        f"{region_id_arr.shape} does not match preview "
                        f"{img_h}x{img_w}; re-run /preview."
                    ),
                )
            if gradient_region_idx is not None:
                # Single region within the group
                mask_source = "gradient_region"
                encoded_id = (
                    int(gradient_group_idx) * REGION_ID_ENCODING_MULTIPLIER
                    + int(gradient_region_idx)
                )
                region_mask = region_id_arr == np.uint32(encoded_id)
                if not np.any(region_mask):
                    raise HTTPException(
                        status_code=404,
                        detail=(
                            f"No pixels found for gradient group "
                            f"{gradient_group_idx}, region "
                            f"{gradient_region_idx}."
                        ),
                    )
            else:
                # Whole group: mask all pixels whose encoded group matches
                # 整组去海带纹：mask 覆盖该组所有像素
                mask_source = "gradient_group"
                group_of_pixel = region_id_arr // np.uint32(
                    REGION_ID_ENCODING_MULTIPLIER
                )
                region_mask = group_of_pixel == np.uint32(
                    int(gradient_group_idx)
                )
                if not np.any(region_mask):
                    raise HTTPException(
                        status_code=404,
                        detail=(
                            f"No pixels found for gradient group "
                            f"{gradient_group_idx}."
                        ),
                    )
        else:
            region_mask = session_data.get("selected_region_mask")
            if region_mask is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "No region selected. Call POST /api/convert/region-detect first, "
                        "or supply gradient_group_index + gradient_region_index."
                    ),
                )

        # Parse replacement hex to RGB tuple
        replacement_rgb = np.array(
            ColorReplacementManager._hex_to_color(request.replacement_color),
            dtype=np.uint8,
        )

        # Apply region replacement: only modify pixels within the mask
        replaced_rgb: np.ndarray = matched_rgb.copy()
        replaced_rgb[region_mask] = replacement_rgb

        import time as _time
        _region_pixels = int(region_mask.sum())
        _diff_before_sync = int(np.any(matched_rgb != replaced_rgb, axis=-1).sum())
        log.info(
            "region-replace diag: before sync",
            extra={
                "event": "converter_region_replace_diag_pre",
                "replacement_color": request.replacement_color,
                "material_source": session_data.get("material_source"),
                "region_mask_pixels": _region_pixels,
                "diff_pixel_count": _diff_before_sync,
                "has_material_matrix": cache.get("material_matrix") is not None,
                "has_mask_solid": cache.get("mask_solid") is not None,
                "matched_rgb_shape": list(matched_rgb.shape),
            },
        )

        # Update matched_rgb in session cache
        cache["matched_rgb"] = replaced_rgb
        _t_sync = _time.perf_counter()
        _sync_material_matrix_after_rgb_change(
            session_data,
            cache,
            matched_rgb,
            replaced_rgb,
        )
        _sync_ms = (_time.perf_counter() - _t_sync) * 1000

        _diff_after_sync = int(np.any(matched_rgb != replaced_rgb, axis=-1).sum())
        log.info(
            "region-replace diag: after sync",
            extra={
                "event": "converter_region_replace_diag_post",
                "sync_ms": round(_sync_ms, 1),
                "diff_pixel_count_after_sync": _diff_after_sync,
                "replaced_rgb_sample": replaced_rgb[region_mask][0].tolist() if _region_pixels > 0 else None,
                "original_rgb_sample": matched_rgb[region_mask][0].tolist() if _region_pixels > 0 else None,
            },
        )
        store.put(request.session_id, "preview_cache", cache)

        # Generate styled preview PNG (with bed grid and transparency)
        _t_png = _time.perf_counter()
        preview_bytes: bytes = _render_styled_preview_bytes(replaced_rgb, cache)
        preview_id: str = registry.register_bytes(request.session_id, preview_bytes, "preview_region_replaced.png")
        _png_ms = (_time.perf_counter() - _t_png) * 1000

        # Async GLB rebuild: /region-replace previously spent ~77% of its
        # wall time here; now the HTTP response returns in ~10s (sync +
        # PNG) and the GLB arrives via /glb-status polling afterwards.
        # 异步 GLB 重建：以往 /region-replace 77% 的耗时在这里；现在只
        # 等 sync + PNG 即可响应，GLB 通过 glb-status 轮询取回。
        schedule_glb_build(request.session_id, store, registry, cache)
        glb_url: str | None = None

        # Per-step timing so the frontend-perceived latency can be attributed
        # to mask building / material sync / PNG render. The heavy GLB step
        # no longer blocks this response — see converter_glb_completed in
        # async_glb.py for its separate timing log.
        # 每步耗时日志；GLB 现已脱离本响应，改为 async_glb 中单独打点。
        log.info(
            "region-replace timing",
            extra={
                "event": "converter_region_replace_timing",
                "sync_ms": round(_sync_ms, 1),
                "png_ms": round(_png_ms, 1),
                "mask_source": mask_source,
                "region_mask_pixels": _region_pixels,
                "matched_rgb_shape": list(matched_rgb.shape),
            },
        )

        # Extract updated color_contours from cache
        contours_data: dict | None = cache.get("color_contours")

        # Only clear the one-shot click-detected region mask, and only when
        # that was the actual source we consumed. The cached
        # ``gradient_region_id_map`` is derived reusable metadata and must
        # survive so the user can replace several banded regions in a row
        # without re-running ``/preview`` between each one.
        # 仅在 click 模式下清理一次性 mask；gradient region 路径复用缓存
        # 的 region_id_map，保留以便连续替换多个区域。
        if mask_source == "click":
            store.put(request.session_id, "selected_region_mask", None)
            store.put(request.session_id, "selected_region_id", None)

    except HTTPException:
        raise
    except REPLACE_HANDLED_ERRORS as e:
        _handle_core_error(e, "Region replacement")

    return RegionReplaceResponse(
        preview_url=f"/api/files/{preview_id}",
        preview_glb_url=glb_url,
        color_contours=contours_data,
        message="Region color replaced successfully",
    )


# ---------------------------------------------------------------------------
# Per-region secondary re-quantisation (material-archive mode only)
# ---------------------------------------------------------------------------


@router.post("/region-requantize", response_model=RegionReplaceResponse)
def region_requantize(
    request: RegionRequantizeRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> RegionReplaceResponse:
    """Per-region secondary re-quantisation for the gradient-groups panel.
    渐变分组面板的区域级二次量化接口。

    For every ``(gradient_group_index, gradient_region_index)`` in
    ``request.targets``, the endpoint extracts the ORIGINAL source pixels
    inside the region's mask, runs a local K-Means with the user-chosen
    ``local_quantize_colors`` budget, and re-matches those locally
    quantised colours through the same :class:`MaterialSolverCache` the
    preview pipeline used. The resulting per-pixel material colours
    overwrite those regions in ``matched_rgb`` while leaving the rest of
    the canvas untouched.

    对每个选中的渐变 region，取原图像素独立做一次 K-Means 量化，再经
    管线同款材料求解器重匹配，只写回这些区域的 ``matched_rgb``。其它
    像素保持不变。

    Material-archive mode only — LUT mode has a completely different
    matching path that does not use :class:`MaterialSolverCache`. Callers
    get HTTP 409 if they attempt this on an LUT session.
    仅支持耗材档案模式；LUT 模式走另一套匹配逻辑，此端点不适用。

    Raises:
        HTTPException(404): Session not found.
        HTTPException(409): Preview cache missing, ``material_source`` is
            not ``"material_archive"``, ``gradient_region_id_map`` is
            absent/stale, or the material solver cache cannot be loaded.
        HTTPException(422): Validation failure on ``local_quantize_colors``
            or ``targets`` (handled by Pydantic before reaching here).
        HTTPException(500): Unexpected processing error.
    """
    import time as _time
    from PIL import Image

    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    try:
        matched_rgb: np.ndarray | None = cache.get("matched_rgb")
        if matched_rgb is None:
            raise HTTPException(
                status_code=409,
                detail="Preview cache missing matched_rgb; re-run /preview first.",
            )

        material_source = str(session_data.get("material_source") or "lut")
        if material_source != "material_archive":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Region re-quantisation is only available in material-archive "
                    "mode; current material_source is "
                    f"'{material_source}'."
                ),
            )

        region_id_map = session_data.get("gradient_region_id_map")
        if region_id_map is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Preview cache has no gradient_region_id_map; "
                    "re-run /preview to refresh gradient-region metadata."
                ),
            )
        region_id_arr = np.asarray(region_id_map)
        img_h, img_w = matched_rgb.shape[:2]
        if region_id_arr.shape != (img_h, img_w):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cached gradient_region_id_map shape "
                    f"{region_id_arr.shape} does not match preview "
                    f"{img_h}x{img_w}; re-run /preview."
                ),
            )

        # Materials list → MaterialParams → solver cache.
        selected_materials = session_data.get("selected_materials") or []
        if not isinstance(selected_materials, list) or not selected_materials:
            raise HTTPException(
                status_code=409,
                detail="Session has no selected materials for material-archive mode.",
            )
        try:
            materials = load_multiple_materials(list(selected_materials))
        except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Failed to load materials: {exc}",
            ) from exc

        layer_count = int(
            session_data.get("material_layer_count")
            or cache.get("color_layers")
            or 10
        )
        layer_height_mm = float(
            session_data.get("material_layer_height_mm")
            or cache.get("layer_height_mm")
            or session_data.get("layer_height_mm")
            or 0.08
        )
        substrate = str(
            cache.get("material_substrate")
            or session_data.get("material_substrate")
            or "white"
        )
        grid_resolution = int(
            session_data.get("material_grid_resolution")
            or DEFAULT_GRID_RESOLUTION
        )
        solver_cache, _grid = load_material_solver_cache_with_fallback(
            materials=materials,
            layer_count=layer_count,
            layer_height_mm=layer_height_mm,
            substrate=substrate,
            grid_resolution=grid_resolution,
        )
        if solver_cache is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "No material solver cache on disk for the current palette; "
                    "run a normal /preview first so the cache is built."
                ),
            )

        # Load the ORIGINAL source image and resize to preview resolution so
        # the region_mask indexes the right pixels. The preview pipeline
        # performs the same resize; resampling with LANCZOS is acceptable
        # here because k-means is robust to sub-pixel smoothing.
        # 原图加载并缩放至预览分辨率，mask 索引才能对齐。
        image_path = session_data.get("image_path")
        if not image_path or not os.path.exists(image_path):
            raise HTTPException(
                status_code=409,
                detail="Session has no original image_path on disk; re-upload.",
            )
        try:
            original_pil = Image.open(image_path).convert("RGB")
            if original_pil.size != (img_w, img_h):
                original_pil = original_pil.resize(
                    (img_w, img_h), Image.LANCZOS
                )
            original_source_rgb = np.asarray(original_pil, dtype=np.uint8)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to load / resize source image: {exc}",
            ) from exc

        # Convert Pydantic targets to plain tuples for the core function.
        target_pairs = [
            (t.gradient_group_index, t.gradient_region_index)
            for t in request.targets
        ]

        _t_core = _time.perf_counter()
        try:
            new_matched_rgb, rewritten_px = requantize_gradient_regions(
                matched_rgb=np.asarray(matched_rgb, dtype=np.uint8),
                original_source_rgb=original_source_rgb,
                region_id_map=region_id_arr.astype(np.uint32, copy=False),
                targets=target_pairs,
                materials=materials,
                material_solver_cache=solver_cache,
                local_quantize_colors=request.local_quantize_colors,
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Invalid re-quantisation request: {exc}",
            ) from exc
        _core_ms = (_time.perf_counter() - _t_core) * 1000

        # Sync material matrix for the changed pixels, then commit to cache.
        cache["matched_rgb"] = new_matched_rgb
        _t_sync = _time.perf_counter()
        _sync_material_matrix_after_rgb_change(
            session_data,
            cache,
            np.asarray(matched_rgb),
            new_matched_rgb,
        )
        _sync_ms = (_time.perf_counter() - _t_sync) * 1000

        # Refresh the palette derived from matched_rgb so downstream
        # consumers (``/layer-images`` iterates over it; Palette Panel
        # surfaces it in the UI) see every new material colour the local
        # k-means produced. Without this the palette still reflects the
        # pre-quantise colours and ``/layer-images`` would only generate
        # slices for the old set.
        # 重算从 matched_rgb 派生的调色板，保证 /layer-images 与面板
        # 能看到二次量化新增的材料色；不补会导致分层图缺色。
        _t_palette = _time.perf_counter()
        cache["color_palette"] = extract_color_palette(cache)
        _palette_ms = (_time.perf_counter() - _t_palette) * 1000

        # The default segmented-GLB merge cap is 64 unique colours. Local
        # re-quantisation deliberately introduces low-frequency colours
        # inside small regions; if those exceed the cap they get merged
        # into the dominant palette, which makes the 3D preview look
        # identical to the pre-quantise state even though the 2D PNG
        # already shows the new colours. Track the actual unique-colour
        # count in the (post-sync) matched_rgb solid mask and bump the
        # GLB cap so every new colour survives into the segmented mesh.
        # 默认 GLB 合并上限 64 会把二次量化引入的低频新色合并掉，导致 3D
        # 看起来没变化。这里按 sync 之后真实的唯一色数把上限抬高，确保
        # 二次量化后 3D 预览能显现 2D 同步可见的新色。
        mask_solid_arr = cache.get("mask_solid")
        if mask_solid_arr is not None:
            mask_bool = np.asarray(mask_solid_arr, dtype=bool)
            solid_pixels = new_matched_rgb[mask_bool] if mask_bool.shape == new_matched_rgb.shape[:2] else new_matched_rgb.reshape(-1, 3)
        else:
            solid_pixels = new_matched_rgb.reshape(-1, 3)
        unique_color_count = int(np.unique(solid_pixels.reshape(-1, 3), axis=0).shape[0])
        previous_cap = int(cache.get("glb_max_meshes") or 0)
        new_cap = max(previous_cap, unique_color_count)
        if new_cap > previous_cap:
            cache["glb_max_meshes"] = new_cap

        store.put(request.session_id, "preview_cache", cache)

        # Re-run gradient-group analysis so the Gradient Groups panel and
        # the cached ``gradient_region_id_map`` both reflect the new
        # ``matched_rgb``. Without this the panel still shows the pre-
        # quantize groups and subsequent /region-requantize or /region-
        # replace calls would address stale region ids. Best-effort: a
        # failure here is logged inside the helper and we ship an empty
        # ``gradient_groups`` so the client can keep going.
        # 二次量化后 matched_rgb 分布变了，必须重跑 gradient-group 分析
        # 让面板与 region_id_map 同步刷新，否则面板显示旧分组，后续再量化
        # 会按旧 region 定位，造成点不中的错觉。
        _t_groups = _time.perf_counter()
        refreshed_groups = recompute_gradient_groups_into_session(
            cache, request.session_id, store
        )
        _groups_ms = (_time.perf_counter() - _t_groups) * 1000

        # Re-render styled preview PNG and schedule GLB rebuild.
        _t_png = _time.perf_counter()
        preview_bytes: bytes = _render_styled_preview_bytes(new_matched_rgb, cache)
        preview_id: str = registry.register_bytes(
            request.session_id,
            preview_bytes,
            "preview_region_requantized.png",
        )
        _png_ms = (_time.perf_counter() - _t_png) * 1000
        schedule_glb_build(request.session_id, store, registry, cache)

        log.info(
            "region-requantize done",
            extra={
                "event": "converter_region_requantize_done",
                "target_count": len(target_pairs),
                "local_quantize_colors": int(request.local_quantize_colors),
                "rewritten_pixels": int(rewritten_px),
                "unique_color_count_after": unique_color_count,
                "glb_max_meshes_previous": previous_cap,
                "glb_max_meshes_new": new_cap,
                "core_ms": round(_core_ms, 1),
                "sync_ms": round(_sync_ms, 1),
                "palette_ms": round(_palette_ms, 1),
                "palette_entry_count": len(cache.get("color_palette") or []),
                "groups_ms": round(_groups_ms, 1),
                "png_ms": round(_png_ms, 1),
                "refreshed_group_count": (
                    len(refreshed_groups) if refreshed_groups is not None else None
                ),
                "matched_rgb_shape": list(matched_rgb.shape),
            },
        )

        contours_data: dict | None = cache.get("color_contours")
    except HTTPException:
        raise
    except REPLACE_HANDLED_ERRORS as exc:
        _handle_core_error(exc, "Region re-quantisation")

    return RegionReplaceResponse(
        preview_url=f"/api/files/{preview_id}",
        preview_glb_url=None,
        color_contours=contours_data,
        message=(
            f"Re-quantised {len(request.targets)} region(s) with "
            f"{request.local_quantize_colors} colours; rewrote {rewritten_px} pixels."
        ),
        gradient_groups=refreshed_groups,
    )


# ---------------------------------------------------------------------------
# Batch endpoints
# ---------------------------------------------------------------------------
#
# Why these exist: the legacy per-colour / per-region endpoints regenerate
# the styled preview PNG, the segmented GLB, and run the material-matrix
# sync on *every* request. When the frontend loops over N replacements
# (multi-colour swap, colour-remap preview rebuild, multi-region click,
# whole-group gradient flatten) that's N * (GLB + PNG + sync) — and GLB
# is expensive. These batch endpoints apply all N changes cumulatively to
# the cached ``matched_rgb``, then do PNG + GLB + sync exactly once at
# the end. Semantically equivalent to the loop, but O(N) faster on the
# heavy steps.
# 批量端点存在的原因：老的单色/单区域端点每次都会重渲染 PNG、重建 GLB、
# 做一次物料矩阵 sync。前端循环 N 次就等于 N × (GLB + PNG + sync)，GLB
# 又最贵。这里把 N 次改动累积到 matched_rgb，最后统一做一次 PNG+GLB+sync。
# 语义上等价于循环，重活只做一次。


def _build_mask_for_region_batch_item(
    session_data: dict,
    item: RegionReplaceBatchItem,
    img_h: int,
    img_w: int,
    cache: dict,
) -> tuple[np.ndarray, str]:
    """Build a boolean mask for one batch region-replace item.
    为单条批量 region-replace 条目构建 mask。

    Mirrors :func:`region_replace` mask-selection logic: gradient group/region
    indices take precedence (re-derived from the cached region_id_map); else
    ``click_x`` / ``click_y`` trigger a fresh flood-fill on the quantised
    preview.
    与 :func:`region_replace` 的 mask 选择逻辑一致：优先渐变索引（现场从
    缓存的 region_id_map 重建），否则使用 click_x/click_y 做泛洪填充。

    Raises:
        HTTPException(400/404/409): Same error codes and messages as the
            single-item /region-replace endpoint.
    """
    gradient_group_idx = item.gradient_group_index
    gradient_region_idx = item.gradient_region_index

    if gradient_group_idx is not None:
        region_id_map = session_data.get("gradient_region_id_map")
        if region_id_map is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Preview cache has no gradient_region_id_map; "
                    "re-run /preview to refresh gradient-region metadata."
                ),
            )
        region_id_arr = np.asarray(region_id_map)
        if region_id_arr.shape != (img_h, img_w):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cached gradient_region_id_map shape "
                    f"{region_id_arr.shape} does not match preview "
                    f"{img_h}x{img_w}; re-run /preview."
                ),
            )
        if gradient_region_idx is not None:
            encoded_id = (
                int(gradient_group_idx) * REGION_ID_ENCODING_MULTIPLIER
                + int(gradient_region_idx)
            )
            mask = region_id_arr == np.uint32(encoded_id)
            if not np.any(mask):
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"No pixels found for gradient group "
                        f"{gradient_group_idx}, region "
                        f"{gradient_region_idx}."
                    ),
                )
            return mask, "gradient_region"
        group_of_pixel = region_id_arr // np.uint32(REGION_ID_ENCODING_MULTIPLIER)
        mask = group_of_pixel == np.uint32(int(gradient_group_idx))
        if not np.any(mask):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No pixels found for gradient group {gradient_group_idx}."
                ),
            )
        return mask, "gradient_group"

    # Click-detected path: flood-fill from (click_x, click_y) on the
    # quantised preview, same kernel as /region-detect.
    if item.click_x is None or item.click_y is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Each batch item must supply either gradient_group_index "
                "(+ optional gradient_region_index) or click_x + click_y."
            ),
        )

    quantized_image = cache.get("quantized_image")
    mask_solid = cache.get("mask_solid")
    if quantized_image is None or mask_solid is None:
        raise HTTPException(
            status_code=409,
            detail="Preview cache missing quantized_image or mask_solid.",
        )

    x, y = int(item.click_x), int(item.click_y)
    if not (0 <= x < img_w and 0 <= y < img_h):
        raise HTTPException(
            status_code=400,
            detail=f"Coordinates ({x}, {y}) out of bounds for image {img_w}x{img_h}.",
        )
    if not mask_solid[y, x]:
        raise HTTPException(
            status_code=400,
            detail=f"Click ({x}, {y}) fell on background.",
        )
    mask = _compute_connected_region_mask_4n(quantized_image, mask_solid, x, y)
    if not np.any(mask):
        raise HTTPException(
            status_code=400,
            detail=f"No connected region at ({x}, {y}).",
        )
    return mask, "click"


@router.post("/replace-colors-batch", response_model=ColorReplaceResponse)
def replace_colors_batch(
    request: ColorReplaceBatchRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ColorReplaceResponse:
    """Batch-replace multiple colours in one round-trip.
    一次调用批量替换多个颜色。

    Semantically equivalent to calling /replace-color for each pair in
    ``request.replacements`` in order, but the heavy per-call work (styled
    PNG render, segmented GLB rebuild, material-matrix sync) runs exactly
    once at the end, making batch colour swaps O(N) cheaper on those
    dominant cost centres.
    语义等价于顺序调用 N 次 /replace-color，但重活（PNG 渲染、GLB 重建、
    物料矩阵 sync）只跑 1 次，批量颜色替换 N× 提速。

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache. (无预览缓存)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    try:
        matched_rgb: np.ndarray = cache["matched_rgb"]
        previous_rgb = matched_rgb.copy()

        # Build manager from existing replacement_regions + every new pair.
        # 把历史 replacement_regions 和本次新 pair 一起塞进 manager，
        # 一次性 apply 到 matched_rgb。
        manager = ColorReplacementManager()
        for record in session_data.get("replacement_regions", []):
            orig = ColorReplacementManager._hex_to_color(record["selected_color"])
            repl = ColorReplacementManager._hex_to_color(record["replacement_color"])
            manager.add_replacement(orig, repl)
        for pair in request.replacements:
            manager.add_replacement(
                ColorReplacementManager._hex_to_color(pair.selected_color),
                ColorReplacementManager._hex_to_color(pair.replacement_color),
            )

        replaced_rgb = manager.apply_to_image(matched_rgb)

        log.info(
            "replace-colors-batch diag",
            extra={
                "event": "converter_replace_colors_batch_diag",
                "pair_count": len(request.replacements),
                "diff_pixel_count": int(
                    np.any(previous_rgb != replaced_rgb, axis=-1).sum()
                ),
                "material_source": session_data.get("material_source"),
            },
        )

        cache["matched_rgb"] = replaced_rgb
        _sync_material_matrix_after_rgb_change(
            session_data, cache, previous_rgb, replaced_rgb
        )
        store.put(request.session_id, "preview_cache", cache)

        # One PNG render + one GLB rebuild for the whole batch.
        # 整个批次只渲染一次 PNG、重建一次 GLB。
        preview_bytes = _render_styled_preview_bytes(replaced_rgb, cache)
        preview_id = registry.register_bytes(
            request.session_id, preview_bytes, "preview_batch_replaced.png"
        )

        # Async GLB rebuild for the entire batch. Matches the single-pair
        # behaviour and keeps batch-swap responses as snappy as PNG render.
        # 批量颜色替换的 GLB 重建也改为异步，响应只等 PNG。
        schedule_glb_build(request.session_id, store, registry, cache)
        glb_url: str | None = None

        # One snapshot to history, append all new pairs to replacement_regions.
        # 批次开始前快照入 history 一次，末尾一次性 append 所有新 pair。
        current_regions = list(session_data.get("replacement_regions", []))
        snapshot = [dict(r) for r in current_regions]
        history = list(session_data.get("replacement_history", []))
        history.append(snapshot)
        store.put(request.session_id, "replacement_history", history)

        for pair in request.replacements:
            current_regions.append(
                {
                    "selected_color": pair.selected_color,
                    "replacement_color": pair.replacement_color,
                }
            )
        store.put(request.session_id, "replacement_regions", current_regions)

    except HTTPException:
        raise
    except REPLACE_HANDLED_ERRORS as e:
        _handle_core_error(e, "Batch color replacement")

    return ColorReplaceResponse(
        status="ok",
        message=f"Replaced {len(request.replacements)} colors in batch",
        preview_url=f"/api/files/{preview_id}",
        preview_3d_url=glb_url,
        replacement_count=len(request.replacements),
    )


@router.post("/region-replace-batch", response_model=RegionReplaceResponse)
def region_replace_batch(
    request: RegionReplaceBatchRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> RegionReplaceResponse:
    """Batch region-replacement: multiple masks + target colours in one call.
    批量区域替换：一次调用里处理多个区域（混合 click 和 gradient 来源）。

    Each item independently resolves its mask (gradient indices or click
    coordinates), then the target colour is applied on top of the running
    ``matched_rgb``. Material-matrix sync, styled PNG render and segmented
    GLB rebuild all run exactly once at the end — the expensive steps are
    amortised across the whole batch.
    每条 item 独立解析 mask（渐变索引或点击坐标），目标色逐条累加应用到
    ``matched_rgb``。物料矩阵 sync、PNG、GLB 各只跑 1 次，重活在整个批次
    内摊薄。
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    try:
        matched_rgb: np.ndarray | None = cache.get("matched_rgb")
        if matched_rgb is None:
            raise HTTPException(
                status_code=409,
                detail="Preview cache missing matched_rgb.",
            )

        img_h, img_w = matched_rgb.shape[:2]
        previous_rgb = matched_rgb.copy()
        working_rgb = matched_rgb.copy()

        any_click_mask_used = False
        for item in request.items:
            mask, mask_source = _build_mask_for_region_batch_item(
                session_data, item, img_h, img_w, cache
            )
            replacement_rgb = np.array(
                ColorReplacementManager._hex_to_color(item.replacement_color),
                dtype=np.uint8,
            )
            working_rgb[mask] = replacement_rgb
            if mask_source == "click":
                any_click_mask_used = True

        # Commit + single sync + single PNG + single GLB.
        # 一次性提交到 cache，sync/PNG/GLB 各跑一次。
        cache["matched_rgb"] = working_rgb
        _sync_material_matrix_after_rgb_change(
            session_data, cache, previous_rgb, working_rgb
        )
        store.put(request.session_id, "preview_cache", cache)

        preview_bytes = _render_styled_preview_bytes(working_rgb, cache)
        preview_id = registry.register_bytes(
            request.session_id, preview_bytes, "preview_region_batch_replaced.png"
        )

        # Async GLB rebuild for the whole batch of region edits. See
        # schedule_glb_build for job-token semantics when a newer replace
        # arrives before the background thread finishes.
        # 批量区域替换的 GLB 重建改为异步；重入竞争由 job_token 守护。
        schedule_glb_build(request.session_id, store, registry, cache)
        glb_url: str | None = None

        contours_data: dict | None = cache.get("color_contours")

        # Legacy one-shot click mask gets cleared just like the per-item
        # endpoint does, but only if at least one click-sourced item was
        # consumed. Gradient masks are reusable metadata and survive.
        # 批次里消费过 click mask 的话清理一次性 mask；gradient 元数据保留。
        if any_click_mask_used:
            store.put(request.session_id, "selected_region_mask", None)
            store.put(request.session_id, "selected_region_id", None)

        log.info(
            "region-replace-batch diag",
            extra={
                "event": "converter_region_replace_batch_diag",
                "item_count": len(request.items),
                "diff_pixel_count": int(
                    np.any(previous_rgb != working_rgb, axis=-1).sum()
                ),
                "material_source": session_data.get("material_source"),
            },
        )

    except HTTPException:
        raise
    except REPLACE_HANDLED_ERRORS as e:
        _handle_core_error(e, "Batch region replacement")

    return RegionReplaceResponse(
        preview_url=f"/api/files/{preview_id}",
        preview_glb_url=glb_url,
        color_contours=contours_data,
        message=f"Batch replaced {len(request.items)} regions successfully",
    )


def _resolve_recipe_source_metadata(
    session_data: dict,
    cache: dict,
) -> tuple[LUTMetadata, np.ndarray | None, np.ndarray | None]:
    """Return ``(metadata, lut_rgb, lut_stacks)`` for a recipe endpoint.

    Bridges ``/predict-recipe`` and ``/apply-recipe-override`` over two source
    kinds:

    - **LUT-backed sessions** — ``session_data["lut_path"]`` points to a real
      calibration file. We resolve it via
      :meth:`LUTManager.load_lut_with_metadata` and return the real
      palette + pure-stack arrays so downstream forward-model prediction and
      pure-stack fallbacks work as they always have.
    - **Material-archive sessions** — ``session_data["material_source"] ==
      "material_archive"`` and ``lut_path`` is the sentinel literal
      ``"__material_archive__"`` (no file on disk). We synthesise a stub
      :class:`LUTMetadata` from ``selected_materials`` /
      ``material_layer_count`` / ``material_layer_height_mm`` so the
      apply / predict endpoints still get a palette length, layer order, and
      ``base_channel_idx`` to drive virtual-material validation, top-layer
      selection, and pad-slab growth. ``lut_rgb`` / ``lut_stacks`` are
      returned as ``None`` — callers must derive display RGB from
      ``cache["preview_colors"]`` (see :func:`_cache_preview_rgb`) because
      material archives have no LUT pure-stack mapping.

    耗材档案模式下 ``session_data["lut_path"]`` 是
    ``"__material_archive__"`` 这种 sentinel 字符串，没法 open，所以两种
    来源统一到这里：LUT 会话照旧走 ``LUTManager.load_lut_with_metadata``；
    耗材档案会话按 ``selected_materials`` / ``material_layer_count`` 拼出
    stub :class:`LUTMetadata`，``lut_rgb`` / ``lut_stacks`` 返回 ``None``，
    让上游自然退化到 cache preview colors 兜底。

    Raises:
        HTTPException(409): LUT session has no LUT file, or material-archive
            session is missing ``selected_materials``. Surfaces the same
            "Preview again first." hint the legacy code used.
    """
    material_source = str(session_data.get("material_source") or "lut")

    if material_source == "material_archive":
        selected_materials = session_data.get("selected_materials") or []
        if not isinstance(selected_materials, list) or not selected_materials:
            raise HTTPException(
                status_code=409,
                detail="Material-archive session missing selected_materials. Preview again first.",
            )
        # Stub palette: one ``PaletteEntry`` per selected material. The
        # ``color`` attribute is only consumed by
        # ``_canonical_apply_rgb(palette[idx].color)`` in the existing apply
        # fallback chain and by palette-length checks; use the slot name when
        # cache already has one (keeps downstream logs readable), otherwise
        # fall back to the material directory name.
        # stub 调色板：每个选中的耗材给一个 PaletteEntry。color 字段仅用于
        # ``_canonical_apply_rgb`` 的通道名兜底和长度校验；尽量用 cache 里
        # 已有的 slot_name，退而用目录名，保持日志/错误信息可读。
        slot_names_raw = cache.get("slot_names")
        slot_names = list(slot_names_raw) if isinstance(slot_names_raw, (list, tuple)) else []
        palette_entries: list[PaletteEntry] = []
        for idx, dir_name in enumerate(selected_materials):
            raw_slot = slot_names[idx] if idx < len(slot_names) else None
            label = str(raw_slot) if raw_slot else str(dir_name)
            palette_entries.append(
                PaletteEntry(color=label, material=str(dir_name))
            )
        try:
            layer_count = int(
                session_data.get("material_layer_count") or len(palette_entries) or 1
            )
            layer_height_mm = float(
                session_data.get("material_layer_height_mm") or 0.08
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Material-archive layer metadata invalid: {exc}",
            ) from exc
        metadata = LUTMetadata(
            palette=palette_entries,
            max_color_layers=layer_count,
            layer_height_mm=layer_height_mm,
            base_channel_idx=0,
            layer_order="Top2Bottom",
        )
        return metadata, None, None

    # LUT-backed session: the path must be a real file on disk.
    # LUT 会话：lut_path 必须是真实存在的文件。
    lut_path = session_data.get("lut_path")
    if not isinstance(lut_path, str) or not lut_path or not os.path.exists(lut_path):
        raise HTTPException(
            status_code=409,
            detail="LUT/source file missing. Preview again first.",
        )
    lut_rgb, lut_stacks, metadata = LUTManager.load_lut_with_metadata(lut_path)
    return metadata, lut_rgb, lut_stacks


def _cache_preview_rgb(cache: dict, channel_idx: int) -> np.ndarray | None:
    """Return the cached preview RGB for ``channel_idx`` or ``None``.

    Reads ``cache["preview_colors"]`` first (populated for merged LUTs and
    after ``_extend_cache_palette_with_virtuals``), then falls back to
    ``cache["color_conf"]["preview"]`` (the standard-color-mode canonical
    source). Used by the recipe endpoints as the material-archive fallback
    when ``_pure_stack_rgb`` cannot resolve a colour — material archives
    have no LUT pure-stack table but always publish a ``preview_colors``
    entry per selected material in ``p04_cache_building`` / P01.

    从 cache 读通道预览色，优先 ``preview_colors``，再回退
    ``color_conf.preview``。耗材档案模式没有 LUT 纯堆叠表，但 cache 里每
    个选中耗材一定有 ``preview_colors`` 条目，所以这是它的兜底色源。
    """
    if channel_idx < 0:
        return None
    for source in (
        cache.get("preview_colors"),
        (cache.get("color_conf") or {}).get("preview"),
    ):
        if not isinstance(source, dict):
            continue
        rgba = source.get(channel_idx)
        if rgba is None:
            continue
        arr = np.asarray(rgba, dtype=np.uint8)
        if arr.ndim == 1 and arr.shape[0] >= 3:
            return arr[:3].copy()
    return None


@router.post("/predict-recipe", response_model=RecipePredictResponse)
def predict_recipe(
    request: RecipePredictRequest,
    store: SessionStore = Depends(get_session_store),
) -> RecipePredictResponse:
    """Predict the display color of a custom recipe for the active source."""
    session_data = _require_session(store, request.session_id)
    cache = session_data.get("preview_cache") or {}
    is_material_archive = (
        str(session_data.get("material_source") or "lut") == "material_archive"
    )
    metadata, _lut_rgb, _lut_stacks = _resolve_recipe_source_metadata(
        session_data, cache
    )

    try:
        if not is_material_archive:
            # LUT-backed session: keep the predictive forward model path.
            # LUT 会话：走前向模型预测。
            prediction = predict_recipe_color(
                metadata,
                recipe=request.recipe,
                layer_height_mm=request.layer_height_mm,
                color_layers=request.color_layers,
                layer_order=request.layer_order,
            )
        else:
            # Material-archive session: no forward model exists, so derive
            # the display colour from the topmost layer's preview RGB in the
            # shared cache (populated by P01 from the material archive). If
            # that misses (e.g. malformed cache), degrade to neutral grey
            # rather than hard-failing — the dialog's "predict" button is a
            # preview, not a gate.
            # 耗材档案没有前向模型，直接用最顶层通道的 preview 色做预测。
            # 兜底是中性灰，避免因 cache 异常让 predict 按钮直接报错。
            top_channel = _top_layer_channel(list(request.recipe), request.layer_order)
            preview_rgb = (
                _cache_preview_rgb(cache, top_channel)
                if top_channel is not None
                else None
            )
            if preview_rgb is None:
                preview_rgb = np.asarray((128, 128, 128), dtype=np.uint8)
            prediction = {
                "rgb": [int(v) for v in preview_rgb.tolist()],
                "lab": [
                    float(v)
                    for v in _rgb_to_lab(preview_rgb.reshape(1, 1, 3))
                    .reshape(3)
                    .tolist()
                ],
                "source": "material_archive_preview",
                "runtime_mode_key": None,
            }
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return RecipePredictResponse(
        status="ok",
        message="Recipe color predicted",
        rgb=[int(v) for v in prediction.get("rgb", [])],
        lab=[float(v) for v in prediction.get("lab", [])],
        source=str(prediction.get("source", "unknown")),
        runtime_mode_key=(
            str(prediction["runtime_mode_key"])
            if prediction.get("runtime_mode_key") is not None
            else None
        ),
    )


# Canonical primary-name -> RGB fallback for apply's preview colour when the
# LUT has neither a forward model nor a pure-channel stack to sample. Keeping
# the dict in sync with the one in ``api/routers/lut.py`` is deliberate: both
# locations need the same visual shorthand so users never see "apply failed"
# just because a particular bundle happens to be sparse.
# 当 LUT 既没前向模型也没纯通道堆叠时，应用自定义配方的预览色走此兜底：
# 按通道名映射到 CMYK / RGB 经典原色，和 ``api/routers/lut.py`` 保持同步，
# 避免"某个 bundle 太稀疏"就让应用失败。
_APPLY_CANONICAL_RGB: dict[str, tuple[int, int, int]] = {
    "cyan": (0, 183, 235),
    "magenta": (230, 0, 126),
    "yellow": (255, 212, 0),
    "black": (17, 17, 17),
    "white": (245, 245, 245),
    "red": (229, 57, 53),
    "green": (67, 160, 71),
    "blue": (30, 136, 229),
    "orange": (251, 140, 0),
    "purple": (142, 36, 170),
    "pink": (236, 64, 122),
    "gray": (158, 158, 158),
    "grey": (158, 158, 158),
    "brown": (121, 85, 72),
}


def _canonical_apply_rgb(color_name: str | None) -> np.ndarray | None:
    """Map a channel name to a canonical primary RGB triplet.

    按通道名返回经典原色 RGB 三元组；找不到返回 ``None``。
    """
    if not color_name:
        return None
    hit = _APPLY_CANONICAL_RGB.get(color_name.strip().lower())
    if hit is None:
        return None
    return np.asarray(hit, dtype=np.uint8)


def _hex_to_rgb_triple(hex_value: str) -> tuple[int, int, int]:
    """Parse ``#RRGGBB`` into an ``(r, g, b)`` uint8 triple.

    将 ``#RRGGBB`` 解析为 ``(r, g, b)`` uint8 三元组；非法输入抛 ``ValueError``。
    """
    raw = hex_value.strip().lstrip("#")
    if len(raw) != 6:
        raise ValueError(f"Invalid virtual material hex: {hex_value!r}")
    value = int(raw, 16)
    return (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF


def _extend_cache_palette_with_virtuals(
    cache: dict,
    lut_palette_length: int,
    virtual_materials: list[VirtualMaterial] | None,
) -> list[tuple[int, tuple[int, int, int], str]]:
    """Append user-declared virtual materials into the preview cache palette.

    把用户声明的虚拟耗材追加到预览缓存的调色板，保证 material_matrix 里
    ``>= LUT.N`` 的索引能被 preview/3MF 正确解析。Returns the list of
    ``(cache_index, rgb, name)`` triples that were written so callers can
    honour the user's per-layer intent when computing the overall preview
    colour.

    Virtual materials are indexed strictly above the LUT palette so LUT-native
    channels stay at their canonical positions; the ``cache_index`` returned
    is ``lut_palette_length + virtual_position``.
    """
    if not virtual_materials:
        return []
    # CRITICAL: ``cache["color_conf"]`` / ``cache["preview_colors"]`` /
    # ``cache["slot_names"]`` may be direct references into the process-wide
    # ``ColorSystem.get(color_mode)`` dict (populated by ``p01`` +
    # ``p04_cache_building``). Appending to them in place permanently pollutes
    # every subsequent request handled by this worker: 透明通道被额外槽位顶掉、
    # s07 按错误的 ``num_materials`` 生成方块、非 override 区域丢配方。
    # 所以必须先做 copy-on-write，把 cache 里的引用换成独立副本，再追加。
    color_conf_src = cache.get("color_conf")
    color_conf = (
        dict(color_conf_src) if isinstance(color_conf_src, dict) else {}
    )
    cache["color_conf"] = color_conf
    conf_preview_src = color_conf.get("preview")
    conf_preview = (
        dict(conf_preview_src) if isinstance(conf_preview_src, dict) else {}
    )
    color_conf["preview"] = conf_preview
    conf_slots_src = color_conf.get("slots")
    conf_slots = (
        list(conf_slots_src)
        if isinstance(conf_slots_src, (list, tuple))
        else []
    )
    color_conf["slots"] = conf_slots

    # Standard color modes (CMYW / RYBW / BW) don't pre-populate
    # ``cache["preview_colors"]`` or ``cache["slot_names"]`` — those keys are
    # only populated for Merged LUTs. The ``/layer-images`` endpoint reads
    # ``preview_colors`` with priority and only falls back to
    # ``color_conf.preview`` when it's missing. If we seeded ``preview_colors``
    # with a fresh empty dict here and only wrote virtuals into it, the
    # endpoint would switch from the complete ``color_conf`` fallback to an
    # incomplete virtuals-only ``preview_colors`` mid-session, and every
    # native layer would render as background grey — exactly the "分层预览
    # 只显示改过配方的那几层，原预览变灰" regression. Seed both keys from the
    # already-copied ``conf_preview`` / ``conf_slots`` so the cache always
    # reflects the FULL palette (natives + upcoming virtuals) after apply.
    # 标准色模式（CMYW / RYBW / BW）下 cache 没有 preview_colors / slot_names，
    # 只有 Merged LUT 才会预置这两个键。/layer-images 端点优先读 preview_colors，
    # 缺失时才回退到 color_conf.preview。如果这里新建空字典只塞虚拟耗材，
    # 端点就会从完整的 color_conf 兜底切换到只有虚拟耗材的残缺字典，native
    # 层全部变灰（就是分层预览只剩配方层的现象）。用已复制的 conf_preview /
    # conf_slots 做种子，保证 apply 后 cache 里的调色板始终是 native + 虚拟
    # 的完整集合。
    preview_colors_src = cache.get("preview_colors")
    if isinstance(preview_colors_src, dict):
        preview_colors = dict(preview_colors_src)
    else:
        preview_colors = dict(conf_preview)
    cache["preview_colors"] = preview_colors
    slot_names_src = cache.get("slot_names")
    if isinstance(slot_names_src, (list, tuple)):
        slot_names = list(slot_names_src)
    else:
        slot_names = list(conf_slots)
    cache["slot_names"] = slot_names

    written: list[tuple[int, tuple[int, int, int], str]] = []
    for offset, material in enumerate(virtual_materials):
        cache_index = lut_palette_length + offset
        r, g, b = _hex_to_rgb_triple(material.hex)
        rgba = [int(r), int(g), int(b), 255]
        preview_colors[cache_index] = rgba
        # slot_names is addressed by int index; pad with None placeholders if
        # the current list is shorter (shouldn't happen in practice but keeps
        # behaviour deterministic for sparse caches).
        while len(slot_names) < cache_index:
            slot_names.append(f"Slot_{len(slot_names)}")
        if len(slot_names) == cache_index:
            slot_names.append(material.name)
        else:
            slot_names[cache_index] = material.name
        # color_conf mirrors preview_colors/slot_names for downstream helpers
        # (e.g. pipeline color configuration). Keep them in lockstep so any
        # path that reads color_conf[*] sees the virtual entry.
        conf_preview[cache_index] = rgba
        while len(conf_slots) < cache_index:
            conf_slots.append(f"Slot_{len(conf_slots)}")
        if len(conf_slots) == cache_index:
            conf_slots.append(material.name)
        else:
            conf_slots[cache_index] = material.name
        written.append((cache_index, (int(r), int(g), int(b)), material.name))
    return written


def _top_layer_channel(recipe: list[int], layer_order: str) -> int | None:
    """Return the channel index of the visually topmost layer in ``recipe``.

    返回 ``recipe`` 中视觉上最顶层那一层的通道索引；空配方返回 ``None``。
    """
    if not recipe:
        return None
    return int(recipe[0] if layer_order == "Top2Bottom" else recipe[-1])


def _pure_stack_rgb(
    rgb: np.ndarray | None,
    stacks: np.ndarray | None,
    channel_idx: int,
) -> np.ndarray | None:
    """Return the LUT's RGB for the pure-channel stack ``[c, c, ..., c]``.

    查找 LUT 中纯通道堆叠配方（每层都是同一通道）对应的 RGB，
    用作缺少前向模型时自定义配方应用的兜底颜色。

    Args:
        rgb: ``(N, 3)`` uint8 array of per-recipe RGB, or ``None``.
        stacks: ``(N, layers)`` int array of per-recipe channel indices, or ``None``.
        channel_idx: Palette channel index to resolve. 调色板通道索引。

    Returns:
        ``(3,)`` uint8 array when a matching pure stack exists, else ``None``.
    """
    if rgb is None or stacks is None:
        return None
    rgb_arr = np.asarray(rgb)
    stacks_arr = np.asarray(stacks)
    if rgb_arr.ndim != 2 or stacks_arr.ndim != 2:
        return None
    if stacks_arr.shape[0] != rgb_arr.shape[0] or stacks_arr.shape[1] == 0:
        return None
    target = np.full(stacks_arr.shape[1], channel_idx, dtype=stacks_arr.dtype)
    matches = np.where(np.all(stacks_arr == target, axis=1))[0]
    if matches.size == 0:
        return None
    row = rgb_arr[int(matches[0])]
    if row.shape[-1] < 3:
        return None
    return np.asarray(row[:3], dtype=np.uint8)


@router.post("/apply-recipe-override", response_model=RecipeOverrideApplyResponse)
def apply_recipe_override(
    request: RecipeOverrideApplyRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> RecipeOverrideApplyResponse:
    """Apply a custom recipe override to the selected regions and update preview cache."""
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    matched_rgb: np.ndarray | None = cache.get("matched_rgb")
    material_matrix: np.ndarray | None = cache.get("material_matrix")
    if matched_rgb is None or material_matrix is None:
        raise HTTPException(status_code=409, detail="Preview cache missing matched_rgb or material_matrix.")

    region_mask_items = _get_region_mask_items_for_ids(session_data, request.region_ids)
    if not region_mask_items:
        raise HTTPException(status_code=409, detail="No selected regions available for recipe override.")

    # Resolve source metadata: real LUT for LUT-backed sessions, stub
    # metadata + ``(None, None)`` arrays for material-archive sessions
    # (whose ``lut_path`` is the ``"__material_archive__"`` sentinel and
    # cannot be opened). The fallback chain below reads
    # ``cache["preview_colors"]`` via :func:`_cache_preview_rgb` when the
    # LUT pure-stack arrays are unavailable.
    # 解析来源元数据：LUT 会话走真实 LUT；耗材档案会话返回 stub metadata
    # 和 (None, None) 数组，下面的兜底链用 cache preview_colors 取色。
    is_material_archive = (
        str(session_data.get("material_source") or "lut") == "material_archive"
    )
    metadata, _rgb, _stacks = _resolve_recipe_source_metadata(session_data, cache)

    try:
        lut_palette_length = len(metadata.palette)
        virtual_materials = list(request.virtual_materials or [])
        allowed_upper = lut_palette_length + len(virtual_materials)

        # Validate recipe indices only when the caller opts into the new
        # virtual-material path: legacy callers (tests, older clients) may
        # pass ``metadata.palette`` == empty + raw LUT channel indices that
        # downstream code still resolves correctly, so we leave their contract
        # untouched. When ``virtual_materials`` is supplied we do enforce that
        # the provided virtual-tail count is sufficient so the user's intent
        # round-trips cleanly into the cache's extended palette.
        # 仅在调用方使用新的虚拟耗材功能时校验 recipe 索引：旧调用方
        # （测试 / 老前端）传空 palette + 原始 LUT 通道索引的路径依然走老逻辑，
        # 保持契约不变；一旦带上 virtual_materials，就严格保证索引落在
        # LUT.N + 虚拟耗材数 的范围内。
        if virtual_materials:
            for idx, channel in enumerate(request.recipe):
                if channel < 0 or channel >= allowed_upper:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"recipe[{idx}]={channel} out of range; LUT has "
                            f"{lut_palette_length} channel(s) and "
                            f"{len(virtual_materials)} virtual material(s) "
                            f"were supplied."
                        ),
                    )

        top_channel_idx = _top_layer_channel(
            list(request.recipe), request.layer_order
        )

        # Custom recipes must still apply when the bundle has no forward model
        # (e.g. material archives / native LUTs). In that case we synthesise a
        # deterministic preview color from the LUT's pure-stack recipe of the
        # topmost visible layer so the material_matrix update still produces
        # visible feedback instead of hard-failing the whole request.
        # 自定义配方在缺少前向模型（例如材料包 / 原生 LUT）时也必须能应用。
        # 此时用 LUT 里"最顶层通道"对应的纯堆叠配方颜色作为兜底预测色，
        # 保证 material_matrix 更新依旧能给用户可见的反馈，而不是整单报错。
        used_virtual_preview = False
        # When the topmost layer is a user-declared virtual material, trust the
        # user's intent colour directly — this is the whole point of the
        # virtual-material feature and keeps the 2D preview honest instead of
        # rendering the LUT substitute channel.
        # 顶层若是用户声明的虚拟耗材，直接用该耗材的 hex 作为 2D 预览色，
        # 保证所见即所得，而不是 LUT 里代用通道的色。
        if (
            top_channel_idx is not None
            and top_channel_idx >= lut_palette_length
            and virtual_materials
        ):
            offset = top_channel_idx - lut_palette_length
            if 0 <= offset < len(virtual_materials):
                material = virtual_materials[offset]
                predicted_rgb = np.asarray(
                    _hex_to_rgb_triple(material.hex), dtype=np.uint8
                )
                predicted_lab = [
                    float(v)
                    for v in _rgb_to_lab(
                        predicted_rgb.reshape(1, 1, 3)
                    ).reshape(3).tolist()
                ]
                prediction_source = "virtual_material"
                runtime_mode_key = None
                match_mode = "virtual_material"
                used_virtual_preview = True

        if not used_virtual_preview:
            # For predictive runtimes we can only call in when every recipe
            # index actually lives in the LUT's palette; virtual indices have
            # no forward-model representation yet, so we fall through to the
            # user-intent / pure-stack fallback instead of erroring out.
            # 前向模型只认识真实 LUT 通道；recipe 含虚拟索引时直接走兜底。
            # Only treat an index as "virtual" when the caller explicitly
            # supplied a virtual materials list; otherwise legacy callers with
            # empty ``metadata.palette`` but valid channel indices keep their
            # old predictive path (empty palette makes ``>= lut_palette_length``
            # match every index, which would wrongly bypass the forward model).
            # 仅当调用方显式提供 virtual_materials 时才把索引当作"虚拟"；
            # 否则保持老调用方的兼容性（空 palette 下每个索引都会大于等于 0，
            # 若不加这层判断会错把所有普通请求甩到兜底路径）。
            recipe_has_virtual = bool(virtual_materials) and any(
                ch >= lut_palette_length for ch in request.recipe
            )
            # Material-archive sessions have no LUT file and therefore no
            # forward-model runtime. Skipping ``predict_recipe_color`` for
            # these sessions avoids a stub-metadata round-trip that would
            # ValueError inside the predictive runtime loader and lets the
            # fallback chain pick a deterministic preview colour from
            # ``preview_colors``. ``is_material_archive`` is the source-of-
            # truth here (driven by ``session_data["material_source"]``);
            # we cannot infer the source from ``_rgb`` / ``_stacks`` being
            # ``None`` because legacy tests legitimately monkeypatch the
            # LUT loader to return ``stacks=None`` while still wiring the
            # predictive path.
            # 耗材档案会话没有 LUT 文件也没有前向模型 runtime，此处跳过
            # ``predict_recipe_color``，避免对 stub metadata 做无意义尝试，
            # 直接走兜底链用 preview_colors 取色。用 session 的
            # material_source 作为唯一信号——不能靠 _rgb/_stacks 是否为
            # None 来推断，老 LUT 测试会合法地 mock stacks=None 但仍然
            # 走预测路径。
            try:
                if recipe_has_virtual or is_material_archive:
                    raise ValueError(
                        "No predictive runtime is available for virtual materials"
                    )
                prediction = predict_recipe_color(
                    metadata,
                    recipe=request.recipe,
                    layer_height_mm=request.layer_height_mm,
                    color_layers=request.color_layers,
                    layer_order=request.layer_order,
                )
                predicted_rgb = np.asarray(prediction.get("rgb", []), dtype=np.uint8)
                if predicted_rgb.shape != (3,):
                    raise ValueError("Predicted RGB payload is invalid")
                predicted_lab = [float(v) for v in prediction.get("lab", [])]
                prediction_source = prediction.get("source")
                runtime_mode_key = prediction.get("runtime_mode_key")
                match_mode = "predictive"
            except ValueError as predict_exc:
                if "No predictive runtime" not in str(predict_exc):
                    raise
                top_channel = top_channel_idx if top_channel_idx is not None else 0
                # Multi-tier fallback so apply never 422s for lack of colour data:
                # (1) LUT pure-stack, (2) cached preview_colors entry for the
                # top channel (covers material-archive sessions whose selected
                # materials publish preview RGB into the cache during preview),
                # (3) canonical primary by channel name (LUT-side sparse
                # palettes like BW without explicit RGB), (4) neutral grey.
                # The material_matrix update is the real work here; the
                # preview colour is only for painting the cached region.
                # 多级兜底：LUT 纯堆叠 → cache preview_colors 的通道预览色
                # （覆盖耗材档案模式）→ 通道名对应的原色 → 中性灰。真正的
                # 工作是 material_matrix 更新，预览色只是给缓存区域着色。
                fallback_rgb = _pure_stack_rgb(_rgb, _stacks, top_channel)
                if fallback_rgb is None:
                    fallback_rgb = _cache_preview_rgb(cache, top_channel)
                if (
                    fallback_rgb is None
                    and 0 <= top_channel < lut_palette_length
                ):
                    fallback_rgb = _canonical_apply_rgb(
                        metadata.palette[top_channel].color
                    )
                if fallback_rgb is None:
                    fallback_rgb = np.asarray((128, 128, 128), dtype=np.uint8)
                predicted_rgb = fallback_rgb
                predicted_lab = [
                    float(v)
                    for v in _rgb_to_lab(
                        predicted_rgb.reshape(1, 1, 3)
                    ).reshape(3).tolist()
                ]
                # Distinguish the material-archive cache-backed fallback from
                # the LUT pure-stack fallback so downstream logs and the UI
                # can differentiate "no forward model, used archive preview"
                # from "LUT exists but the recipe was outside the predictive
                # grid". 区分耗材档案兜底与 LUT 纯堆叠兜底，方便日志/前端
                # 分辨"没前向模型走档案"和"LUT 不在预测格"两种来源。
                prediction_source = (
                    "material_archive_preview"
                    if is_material_archive
                    else "pure_stack_fallback"
                )
                runtime_mode_key = None
                match_mode = prediction_source

        # Extend the preview cache with any user-declared virtual materials so
        # downstream GLB rendering / 3MF export (which index preview_colors and
        # slot_names by material id) can resolve indices beyond LUT.N.
        # 扩展预览缓存里的 preview_colors / slot_names / color_conf，让下游
        # GLB 渲染和 3MF 导出按索引读 preview_colors 时能解析到虚拟耗材。
        _extend_cache_palette_with_virtuals(
            cache,
            lut_palette_length,
            virtual_materials or None,
        )

        current_layers = int(material_matrix.shape[2])
        target_layers = int(request.color_layers)
        if target_layers > current_layers:
            pad_count = target_layers - current_layers
            # Growing ``material_matrix`` beyond its current depth has two
            # conflicting constraints that must be satisfied at the same time:
            #
            #   (a) Pixels OUTSIDE the object silhouette (``~mask_solid``,
            #       i.e., the transparent background p03 has already marked
            #       with ``-1``) must NOT gain any material at the new
            #       layers. Otherwise S06 copies them into ``full_matrix``
            #       and S07 emits a White mesh ringing the model at the
            #       extended Z — the "整块白矩形包裹 / 透明通道失效" bug.
            #
            #   (b) Pixels INSIDE the object silhouette (``mask_solid``) that
            #       the user did not override must keep a real material at
            #       the new layers so the extended region stays continuous
            #       with the backing slab. If we pad them with ``-1`` too
            #       they become "air" and the user sees their 6th layer
            #       collapse into an empty silhouette outside the override
            #       — the "第 6 层空层" bug.
            #
            # Both constraints collapse into a single rule: the pad slab is
            # ``-1`` everywhere except the ``mask_solid`` interior, which
            # gets the LUT's base channel (normally White on CMYW). The
            # override region is then overwritten by the user's recipe a
            # few lines down, so this pad only affects non-override pixels.
            # 扩展 material_matrix 必须同时满足两条约束：(a) 物体轮廓外
            # (~mask_solid，p03 已经标记为 -1 的透明背景) 新增的层上绝不能
            # 产生材料，否则 S07 会围着模型生成一圈白色 mesh（"整块白矩形
            # / 透明通道失效"）；(b) 物体轮廓内但未被 override 的像素在新
            # 增层上要保留实体材料，跟下方背板连续，否则用户的第 6 层会
            # 塌成空层（"第 6 层空层"）。所以 pad slab 整体置 -1，再只在
            # mask_solid 位置写 LUT base channel（CMYW 下就是白色）；接下
            # 来几行再把 override 区域覆盖成用户配方。
            mask_solid: np.ndarray | None = cache.get("mask_solid")
            if mask_solid is None:
                raise HTTPException(
                    status_code=409,
                    detail="Preview cache missing mask_solid; re-run preview before applying recipe override.",
                )
            mask_solid_arr = np.asarray(mask_solid, dtype=bool)
            if mask_solid_arr.shape != material_matrix.shape[:2]:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "mask_solid shape does not match material_matrix; "
                        "re-run preview before applying recipe override."
                    ),
                )
            # uint dtypes would wrap ``-1`` into ``255`` and resurrect the
            # exact same mesh-explosion bug, so promote to a signed dtype
            # before padding.
            # uint 类型会把 ``-1`` 绕回 255，把同一个 bug 换个编号再来一遍，
            # 所以先升到 signed 类型再 pad。
            if np.issubdtype(material_matrix.dtype, np.unsignedinteger):
                material_matrix = material_matrix.astype(np.int32)
            pad_slab = np.full(
                (material_matrix.shape[0], material_matrix.shape[1], pad_count),
                -1,
                dtype=material_matrix.dtype,
            )
            pad_slab[mask_solid_arr] = int(metadata.base_channel_idx)
            if metadata.layer_order == "Bottom2Top":
                material_matrix = np.concatenate([pad_slab, material_matrix], axis=2)
            else:
                material_matrix = np.concatenate([material_matrix, pad_slab], axis=2)

        recipe_full = np.asarray(
            pad_recipe_to_layer_count(
                request.recipe,
                int(material_matrix.shape[2]),
                int(metadata.base_channel_idx),
                request.layer_order,
            ),
            dtype=np.int32,
        )

        updated_rgb = matched_rgb.copy()
        for _region_id, region_mask in region_mask_items:
            effective_mask = np.asarray(region_mask, dtype=bool)
            updated_rgb[effective_mask] = predicted_rgb
            material_matrix[effective_mask] = recipe_full

        cache["matched_rgb"] = updated_rgb
        cache["material_matrix"] = material_matrix
        cache["color_layers"] = int(material_matrix.shape[2])
        cache["layer_height_mm"] = float(request.layer_height_mm)
        cache["lut_match_info"] = {
            "match_mode": match_mode,
            "runtime_mode_key": runtime_mode_key,
            "override": True,
            "source": prediction_source,
        }
        store.put(request.session_id, "preview_cache", cache)

        existing_overrides = list(session_data.get("recipe_overrides") or [])
        # Persist the per-region virtual materials alongside the recipe so the
        # generate endpoint can rebuild the extended palette for the 3MF
        # pipeline even in a fresh worker process. Use plain dicts (not
        # pydantic models) so the session store stays JSON-serialisable.
        # 把 per-region 的虚拟耗材和 recipe 一并持久化到会话里，让 generate
        # 端点在新 worker 进程里也能重建扩展调色板；存 dict 保证 JSON 可序列化。
        virtual_materials_payload = (
            [
                {"name": material.name, "hex": material.hex}
                for material in virtual_materials
            ]
            if virtual_materials
            else None
        )
        existing_overrides.extend(
            {
                "region_id": region_id,
                "recipe": list(request.recipe),
                "layer_order": request.layer_order,
                "color_layers": int(material_matrix.shape[2]),
                "layer_height_mm": float(request.layer_height_mm),
                **(
                    {"virtual_materials": virtual_materials_payload}
                    if virtual_materials_payload
                    else {}
                ),
            }
            for region_id, _region_mask in region_mask_items
        )
        store.put(request.session_id, "recipe_overrides", existing_overrides)
        store.put(request.session_id, "recipe_override_count", len(existing_overrides))

        preview_bytes = _render_styled_preview_bytes(updated_rgb, cache)
        preview_id = registry.register_bytes(
            request.session_id,
            preview_bytes,
            "preview_recipe_override.png",
        )

        # Async GLB rebuild for the newly applied recipe override. Keeps
        # the override response fast; GLB arrives via /glb-status polling.
        # 配方覆盖也走异步 GLB 重建，保持响应延迟与其他 replace 端点一致。
        schedule_glb_build(request.session_id, store, registry, cache)
        glb_url: str | None = None
    except HTTPException:
        raise
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return RecipeOverrideApplyResponse(
        status="ok",
        message="Recipe override applied",
        preview_url=f"/api/files/{preview_id}",
        preview_glb_url=glb_url,
        rgb=[int(v) for v in predicted_rgb.tolist()],
        lab=predicted_lab,
        source=str(prediction_source or "unknown"),
        runtime_mode_key=(
            str(runtime_mode_key) if runtime_mode_key is not None else None
        ),
        override_count=len(existing_overrides),
    )


def _sample_region_recipe_top2bottom(
    material_matrix: np.ndarray,
    region_mask: np.ndarray,
) -> list[int] | None:
    """Sample the current per-layer material stack for a region mask.

    Reads the first solid pixel inside ``region_mask`` and returns its
    ``material_matrix`` stack in the pipeline's native ``Top2Bottom``
    convention (index 0 = viewing surface). Regions are connected components
    of a single ``matched_hex`` so every pixel in the mask shares the same
    stack; picking any one pixel is therefore correct and O(H·W) cheap.
    ``-1`` air sentinels (present in layers grown past the original depth
    outside ``mask_solid``) are stripped so the returned recipe contains
    only valid material indices — callers can use its length as the "real"
    solid-layer count.

    从区域掩码里采样一个实体像素，返回该像素在 ``material_matrix`` 中的
    堆叠（Top2Bottom，索引 0 = 观察面）。区域内每个像素共享同一个 matched_hex
    → 同一个堆叠，所以取任意一个即可。过滤 -1（空气哨兵，发生在 grown
    后不在 mask_solid 内的层），返回的 recipe 里只含合法材料索引，其长度
    就是该区域的真实实体层数。

    Returns:
        Recipe list or ``None`` when the mask is empty / shape mismatched /
        stack contains no solid layers.
    """
    if material_matrix.ndim != 3:
        return None
    mask_arr = np.asarray(region_mask, dtype=bool)
    if mask_arr.shape != material_matrix.shape[:2]:
        return None
    ys, xs = np.where(mask_arr)
    if ys.size == 0:
        return None
    stack = material_matrix[int(ys[0]), int(xs[0]), :]
    recipe = [int(v) for v in stack.tolist() if int(v) >= 0]
    if not recipe:
        return None
    return recipe


@router.post("/region-recipe", response_model=RegionRecipeResponse)
def region_recipe(
    request: RegionRecipeRequest,
    store: SessionStore = Depends(get_session_store),
) -> RegionRecipeResponse:
    """Return each requested region's current per-layer material stack.

    The Custom Recipe dialog calls this on open so the per-layer dropdowns
    pre-populate with the region's *actual* matched recipe instead of the
    all-White default. Without this the dialog silently overwrites the
    user's current stack on "Apply" if they only wanted to tweak a single
    layer — the user-reported "永远默认全白" bug.

    自定义配方对话框打开时调用，让逐层下拉预设为该区域的真实配方，而不
    是默认的全白。否则用户只想改一层也会把整个配方覆盖成白色，正是用户
    报告的 "永远默认全白" bug。

    ``material_matrix`` is stored in ``Top2Bottom`` convention (layer 0 =
    viewing surface) everywhere in the pipeline; we sample directly and
    reorder only when the caller asks for ``Bottom2Top``.

    Raises:
        HTTPException(404): Session not found.
        HTTPException(409): Missing preview cache, missing material_matrix,
            or no regions to sample.
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    material_matrix: np.ndarray | None = cache.get("material_matrix")
    if material_matrix is None:
        raise HTTPException(
            status_code=409,
            detail="Preview cache missing material_matrix. Preview again first.",
        )

    region_mask_items = _get_region_mask_items_for_ids(
        session_data, list(request.region_ids)
    )
    if not region_mask_items:
        raise HTTPException(
            status_code=409,
            detail="No selected regions available for recipe sampling.",
        )

    target_order = normalize_layer_order(request.layer_order)
    layer_height_mm = float(
        cache.get("layer_height_mm") or session_data.get("material_layer_height_mm") or 0.08
    )

    entries: list[RegionRecipeEntry] = []
    for region_id, region_mask in region_mask_items:
        # ``material_matrix`` storage is always Top2Bottom (s03 docstring is
        # the canonical reference). Convert only when the caller asks for
        # the reversed view; empty samples degrade to an empty recipe so
        # the frontend can still fall back to its built-in default without
        # crashing on ``recipe[0]``.
        # material_matrix 恒为 Top2Bottom 存储，调用方要 Bottom2Top 时才反
        # 序；空样本退化为空 recipe，让前端能安全回退到默认配方。
        recipe_t2b = _sample_region_recipe_top2bottom(material_matrix, region_mask)
        if recipe_t2b is None:
            entries.append(
                RegionRecipeEntry(
                    region_id=region_id,
                    recipe=[],
                    color_layers=int(material_matrix.shape[2]),
                    layer_height_mm=layer_height_mm,
                    layer_order=target_order,
                )
            )
            continue
        recipe_out = convert_recipe_between_orders(recipe_t2b, "Top2Bottom", target_order)
        entries.append(
            RegionRecipeEntry(
                region_id=region_id,
                recipe=recipe_out,
                color_layers=len(recipe_out),
                layer_height_mm=layer_height_mm,
                layer_order=target_order,
            )
        )

    return RegionRecipeResponse(
        status="ok",
        message="Region recipes resolved",
        recipes=entries,
    )


def _rgb_to_lab(rgb_array: np.ndarray) -> np.ndarray:
    """Convert RGB array to CIELAB color space via OpenCV.
    通过 OpenCV 将 RGB 数组转换为 CIELAB 色彩空间。

    Args:
        rgb_array (np.ndarray): RGB values of shape (N, 3), dtype uint8. (RGB 值，形状 (N, 3))

    Returns:
        np.ndarray: LAB values of shape (N, 3), dtype float64. (LAB 值，形状 (N, 3))
    """
    rgb_2d = rgb_array.reshape(1, -1, 3).astype(np.uint8)
    lab_2d = cv2.cvtColor(rgb_2d, cv2.COLOR_RGB2LAB)
    return lab_2d.reshape(-1, 3).astype(np.float64)


@router.post("/merge-colors")
def merge_colors(
    request: ColorMergePreviewRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> MergePreviewResponse:
    """Preview the effect of merging similar colors (synchronous).
    预览合并相似颜色的效果（同步执行）。

    This endpoint is intentionally kept synchronous (no process pool offload)
    because the computation is lightweight: it operates on the cached palette
    (typically 3-64 colors) and the cached matched_rgb array from the /preview
    step. Delta-E calculations involve small NumPy arrays (palette-sized, not
    image-sized), and pixel replacement uses simple mask operations.
    The heavy image processing was already completed in the /preview step.
    此端点有意保持同步执行（不卸载到进程池），因为计算量很小：
    仅对缓存的调色板（通常 3-64 色）和 /preview 步骤缓存的 matched_rgb 数组操作。
    Delta-E 计算涉及小型 NumPy 数组（调色板级别，非图像级别），
    像素替换使用简单的掩码操作。
    繁重的图像处理已在 /preview 步骤中完成。

    Args:
        request (ColorMergePreviewRequest): Merge parameters. (合并参数)
        store (SessionStore): Session store dependency. (会话存储依赖)
        registry (FileRegistry): File registry dependency. (文件注册表依赖)

    Returns:
        MergePreviewResponse: Merge result with preview URL and quality metric.
                              (合并结果及预览 URL 和质量指标)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache available. (无预览缓存)
        HTTPException(500): Internal processing error. (内部处理错误)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    try:
        # Extract palette from preview cache
        palette = extract_color_palette(cache)
        colors_before = len(palette)

        # If merge disabled, return empty merge with perfect quality
        if not request.merge_enable:
            preview_bytes = _image_to_png_bytes(cache["matched_rgb"])
            preview_id = registry.register_bytes(request.session_id, preview_bytes, "preview_merged.png")
            store.put(request.session_id, "merge_map", {})
            return MergePreviewResponse(
                status="ok",
                message="Color merging disabled",
                preview_url=f"/api/files/{preview_id}",
                merge_map={},
                quality_metric=100.0,
                colors_before=colors_before,
                colors_after=colors_before,
            )

        # Build merge map using ColorMerger
        merger = ColorMerger(rgb_to_lab_func=_rgb_to_lab)
        merge_map = merger.build_merge_map(
            palette,
            threshold_percent=request.merge_threshold,
            max_distance=float(request.merge_max_distance),
        )

        # Apply merging to matched_rgb
        matched_rgb: np.ndarray = cache["matched_rgb"]
        merged_rgb = merger.apply_color_merging(matched_rgb, merge_map)

        # Calculate quality metric
        merged_palette = extract_color_palette(
            {
                "matched_rgb": merged_rgb,
                "mask_solid": cache["mask_solid"],
            }
        )
        quality = merger.calculate_quality_metric(palette, merged_palette, merge_map)
        colors_after = len(merged_palette)

        # Generate preview PNG
        preview_bytes = _image_to_png_bytes(merged_rgb)
        preview_id = registry.register_bytes(request.session_id, preview_bytes, "preview_merged.png")

        # Store merge_map in session
        store.put(request.session_id, "merge_map", merge_map)

    except HTTPException:
        raise
    except REPLACE_HANDLED_ERRORS as e:
        _handle_core_error(e, "Color merging")

    return MergePreviewResponse(
        status="ok",
        message=f"Merged {len(merge_map)} colors",
        preview_url=f"/api/files/{preview_id}",
        merge_map=merge_map,
        quality_metric=round(quality, 2),
        colors_before=colors_before,
        colors_after=colors_after,
    )


# ---------------------------------------------------------------------------
# Cleanup intermediate files after download
# ---------------------------------------------------------------------------
