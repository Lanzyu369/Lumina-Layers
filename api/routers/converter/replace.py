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
    ColorReplaceRequest,
    RecipeOverrideApplyRequest,
    RecipePredictRequest,
    RegionDetectRequest,
    RegionDetectResponse,
    RegionReplaceRequest,
    RegionReplaceResponse,
    ResetReplacementsRequest,
)
from api.schemas.responses import (
    ColorReplaceResponse,
    MergePreviewResponse,
    RecipeOverrideApplyResponse,
    RecipePredictResponse,
    ResetReplacementsResponse,
)
from api.session_store import SessionStore
from core.color_merger import ColorMerger
from core.color_replacement import ColorReplacementManager
from core.converter import (
    extract_color_palette,
    generate_segmented_glb,
    _compute_connected_region_mask_4n,
)
from core.material_cache import load_material_solver_cache
from core.material_lut_synthesis import load_multiple_materials, solve_image_colors_optimal
from core.pipeline.processing_ops.lut_loader import load_lut
from core.predictive_lut import predict_recipe_color
from core.recipe_order import pad_recipe_to_layer_count
from utils.lut_manager import LUTManager
from api.structured_logging import get_logger

from .common import (
    NON_FATAL_GLB_ERRORS,
    ROUTER_HANDLED_ERRORS,
    _handle_core_error,
    _image_to_png_bytes,
    _require_preview_cache,
    _require_session,
)

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

    try:
        solver_cache = load_material_solver_cache(
            materials=materials,
            layer_count=layer_count,
            layer_height_mm=layer_height_mm,
            substrate=substrate,
        )
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

        # Regenerate segmented GLB from updated matched_rgb
        glb_url: str | None = None
        try:
            glb_path = generate_segmented_glb(cache)
            if glb_path and os.path.exists(glb_path):
                glb_id = registry.register_path(request.session_id, glb_path)
                glb_url = f"/api/files/{glb_id}"
        except NON_FATAL_GLB_ERRORS as glb_err:
            log.warning(
                "Color-replace GLB regeneration failed",
                extra={
                    "event": "converter_color_replace_glb_failed",
                    "error_type": type(glb_err).__name__,
                    "error_message": str(glb_err),
                },
            )

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

        # Regenerate segmented GLB from restored matched_rgb
        glb_url: str | None = None
        try:
            glb_path = generate_segmented_glb(cache)
            if glb_path and os.path.exists(glb_path):
                glb_id = registry.register_path(request.session_id, glb_path)
                glb_url = f"/api/files/{glb_id}"
        except NON_FATAL_GLB_ERRORS as glb_err:
            log.warning(
                "Reset-replacements GLB regeneration failed",
                extra={
                    "event": "converter_reset_glb_failed",
                    "error_type": type(glb_err).__name__,
                    "error_message": str(glb_err),
                },
            )
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

        # Build combined mask: pixels matching ANY of the given colors
        combined_mask = np.zeros(matched_rgb.shape[:2], dtype=bool)
        for rgb in target_rgbs:
            combined_mask |= np.all(matched_rgb == rgb, axis=-1) & mask_solid

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

        region_mask: np.ndarray | None = session_data.get("selected_region_mask")
        if region_mask is None:
            raise HTTPException(
                status_code=409,
                detail="No region selected. Call POST /api/convert/region-detect first.",
            )

        # Parse replacement hex to RGB tuple
        replacement_rgb = np.array(
            ColorReplacementManager._hex_to_color(request.replacement_color),
            dtype=np.uint8,
        )

        # Apply region replacement: only modify pixels within the mask
        replaced_rgb: np.ndarray = matched_rgb.copy()
        replaced_rgb[region_mask] = replacement_rgb

        # Update matched_rgb in session cache
        cache["matched_rgb"] = replaced_rgb
        _sync_material_matrix_after_rgb_change(
            session_data,
            cache,
            matched_rgb,
            replaced_rgb,
        )
        store.put(request.session_id, "preview_cache", cache)

        # Generate styled preview PNG (with bed grid and transparency)
        preview_bytes: bytes = _render_styled_preview_bytes(replaced_rgb, cache)
        preview_id: str = registry.register_bytes(request.session_id, preview_bytes, "preview_region_replaced.png")

        # Regenerate segmented GLB from updated matched_rgb
        glb_url: str | None = None
        try:
            glb_path = generate_segmented_glb(cache)
            if glb_path and os.path.exists(glb_path):
                glb_id = registry.register_path(request.session_id, glb_path)
                glb_url = f"/api/files/{glb_id}"
        except NON_FATAL_GLB_ERRORS as glb_err:
            log.warning(
                "Region-replace GLB regeneration failed",
                extra={
                    "event": "converter_region_replace_glb_failed",
                    "error_type": type(glb_err).__name__,
                    "error_message": str(glb_err),
                },
            )

        # Extract updated color_contours from cache
        contours_data: dict | None = cache.get("color_contours")

        # Clear region mask after replacement
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


@router.post("/predict-recipe", response_model=RecipePredictResponse)
def predict_recipe(
    request: RecipePredictRequest,
    store: SessionStore = Depends(get_session_store),
) -> RecipePredictResponse:
    """Predict the display color of a custom recipe for the active source."""
    session_data = _require_session(store, request.session_id)
    lut_path: str | None = session_data.get("lut_path")
    if not lut_path or not os.path.exists(lut_path):
        raise HTTPException(status_code=409, detail="LUT/source file missing. Preview again first.")

    try:
        _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(lut_path)
        prediction = predict_recipe_color(
            metadata,
            recipe=request.recipe,
            layer_height_mm=request.layer_height_mm,
            color_layers=request.color_layers,
            layer_order=request.layer_order,
        )
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


@router.post("/apply-recipe-override", response_model=RecipeOverrideApplyResponse)
def apply_recipe_override(
    request: RecipeOverrideApplyRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> RecipeOverrideApplyResponse:
    """Apply a custom recipe override to the selected regions and update preview cache."""
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)
    lut_path: str | None = session_data.get("lut_path")
    if not lut_path or not os.path.exists(lut_path):
        raise HTTPException(status_code=409, detail="LUT/source file missing. Preview again first.")

    matched_rgb: np.ndarray | None = cache.get("matched_rgb")
    material_matrix: np.ndarray | None = cache.get("material_matrix")
    if matched_rgb is None or material_matrix is None:
        raise HTTPException(status_code=409, detail="Preview cache missing matched_rgb or material_matrix.")

    region_mask_items = _get_region_mask_items_for_ids(session_data, request.region_ids)
    if not region_mask_items:
        raise HTTPException(status_code=409, detail="No selected regions available for recipe override.")

    try:
        _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(lut_path)
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

        current_layers = int(material_matrix.shape[2])
        target_layers = int(request.color_layers)
        if target_layers > current_layers:
            pad_count = target_layers - current_layers
            base_fill = int(metadata.base_channel_idx)
            if metadata.layer_order == "Bottom2Top":
                pad_shape = ((0, 0), (0, 0), (pad_count, 0))
            else:
                pad_shape = ((0, 0), (0, 0), (0, pad_count))
            material_matrix = np.pad(
                material_matrix,
                pad_shape,
                mode="constant",
                constant_values=base_fill,
            )

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
            "match_mode": "predictive",
            "runtime_mode_key": prediction.get("runtime_mode_key"),
            "override": True,
            "source": prediction.get("source"),
        }
        store.put(request.session_id, "preview_cache", cache)

        existing_overrides = list(session_data.get("recipe_overrides") or [])
        existing_overrides.extend(
            {
                "region_id": region_id,
                "recipe": list(request.recipe),
                "layer_order": request.layer_order,
                "color_layers": int(material_matrix.shape[2]),
                "layer_height_mm": float(request.layer_height_mm),
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

        glb_url: str | None = None
        try:
            glb_path = generate_segmented_glb(cache)
            if glb_path and os.path.exists(glb_path):
                glb_id = registry.register_path(request.session_id, glb_path)
                glb_url = f"/api/files/{glb_id}"
        except NON_FATAL_GLB_ERRORS as glb_err:
            log.warning(
                "Recipe-override GLB regeneration failed",
                extra={
                    "event": "converter_recipe_override_glb_failed",
                    "error_type": type(glb_err).__name__,
                    "error_message": str(glb_err),
                },
            )
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
        lab=[float(v) for v in prediction.get("lab", [])],
        source=str(prediction.get("source", "unknown")),
        runtime_mode_key=(
            str(prediction["runtime_mode_key"])
            if prediction.get("runtime_mode_key") is not None
            else None
        ),
        override_count=len(existing_overrides),
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
