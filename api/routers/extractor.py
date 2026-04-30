"""Extractor domain API router.
Extractor 领域 API 路由模块。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import List, Tuple

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image

from api.dependencies import get_file_registry, get_session_store
from api.errors import to_http_exception
from api.file_bridge import (
    ndarray_to_png_bytes,
    pil_to_png_bytes,
    upload_to_ndarray,
    upload_to_tempfile,
)
from api.file_registry import FileRegistry
from api.schemas.extractor import (
    ConfirmPaletteRequest,
    ExtractorManualFixRequest,
    ExtractorMergeEightColorRequest,
    ExtractorResolveCellRequest,
)
from api.schemas.responses import ExtractResponse, LutPreviewResolvedCell, ManualFixResponse
from api.session_store import SessionStore
from api.structured_logging import bind_session_id, get_logger
from config import ColorSystem, LUTMetadata, PaletteEntry
from core.extractor import (
    EIGHT_COLOR_FULL_TOTAL_PAGES,
    apply_auto_white_balance,
    manual_fix_cell,
    rotate_image,
    run_extraction,
)
from core.lut_card_layout import (
    LutCardLayout,
    LutCardPage,
    cell_from_normalized_point,
    localize_page_layout,
    overlay_bbox_for_cell,
    resolve_extraction_page_layout,
    resolve_lut_layout,
    rgb_to_hex,
)
from utils.lut_manager import LUTManager

router = APIRouter(prefix="/api/extractor", tags=["Extractor"])
EPHEMERAL_PREVIEW_TTL_SECONDS = 600
log = get_logger(__name__)

EXTRACTOR_HANDLED_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    AttributeError,
    OSError,
    RuntimeError,
    json.JSONDecodeError,
)
LUT_PERSIST_WARNING_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    OSError,
    RuntimeError,
    json.JSONDecodeError,
)


def _handle_core_error(e: Exception, context: str) -> None:
    """Translate core exceptions to HTTP 500 errors."""
    log.exception(
        "Extractor operation failed",
        extra={
            "event": "extractor_error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "context": context,
        },
    )
    raise to_http_exception(e, context)


def _image_to_png_bytes(img: object) -> bytes:
    """Convert ndarray/PIL image to PNG bytes."""
    if isinstance(img, np.ndarray):
        return ndarray_to_png_bytes(img)
    if isinstance(img, Image.Image):
        return pil_to_png_bytes(img)
    raise TypeError(f"Unsupported image type: {type(img)}")


def _normalize_6color_mode(color_mode: str) -> str:
    """Normalize six-color variants to the unified CMYW mode.
    将 6 色变体统一归一到 CMYW 模式。

    Args:
        color_mode (str): Raw color mode from request. (请求中的原始颜色模式)

    Returns:
        str: Normalized color mode. (归一化后的颜色模式)
    """
    if "6-Color" in str(color_mode):
        return "6-Color (CMYWGK 1296)"
    return color_mode


def _build_default_palette(color_mode: str) -> list[dict]:
    """Build default palette array based on color mode.
    根据颜色模式构建默认调色板数组。

    The raw ``color_mode`` (not the CMYW-normalized variant used by the
    extraction pipeline) must be used here so each 6-Color subtype keeps its
    own slot names — RYBWGK resolves to White/Red/Yellow/Blue/Green/Black,
    CMYWGK resolves to White/Cyan/Magenta/Green/Yellow/Black. Normalizing
    first would silently collapse RYBWGK into CMYW names in the UI.

    这里必须使用原始 ``color_mode``，而不是提取管线为共享处理路径使用的
    CMYW 归一模式。这样每个 6 色子类型都能保留自己的槽位名：RYBWGK →
    白/红/黄/蓝/绿/黑，CMYWGK → 白/青/品红/绿/黄/黑。若先归一会让 RYBWGK 在
    UI 上被静默展示成 CMYW 名字。

    Args:
        color_mode (str): Raw color mode string from the request. (请求中的
            原始颜色模式字符串，不做 6 色归一化)

    Returns:
        list[dict]: Default palette entries. (默认调色板条目列表)
    """
    color_conf = ColorSystem.get(color_mode)
    slots = color_conf.get("slots", [])
    preview = color_conf.get("preview", {})
    palette = []
    for i, slot_name in enumerate(slots):
        hex_color = None
        if i in preview:
            r, g, b = preview[i][:3]
            hex_color = f"#{r:02x}{g:02x}{b:02x}"
        palette.append(
            {
                "color": slot_name,
                "material": "PLA Basic",
                "hex_color": hex_color,
                "color_name": slot_name,
            }
        )
    return palette


def _build_merged_metadata(
    primary: LUTMetadata,
    secondary: LUTMetadata,
    color_mode: str,
    output_path: str,
    color_count: int,
) -> LUTMetadata:
    """Build merged metadata while preserving user-entered fields when available.
    构建合并后的元数据，尽量保留用户填写过的字段。
    """
    source = primary if primary.palette else secondary
    manufacturer = primary.manufacturer or secondary.manufacturer
    lut_type = primary.type or secondary.type

    if source.palette:
        return LUTMetadata(
            palette=[
                PaletteEntry(
                    color=entry.color,
                    material=entry.material,
                    hex_color=entry.hex_color,
                    color_name=entry.color_name,
                )
                for entry in source.palette
            ],
            manufacturer=manufacturer,
            type=lut_type,
            color_mode=color_mode,
            max_color_layers=source.max_color_layers,
            layer_height_mm=source.layer_height_mm,
            line_width_mm=source.line_width_mm,
            base_layers=source.base_layers,
            base_channel_idx=source.base_channel_idx,
            layer_order=source.layer_order,
        )

    metadata = LUTManager.infer_default_metadata("lumina_lut", output_path, color_count, color_mode=color_mode)
    metadata.manufacturer = manufacturer
    metadata.type = lut_type
    return metadata


def _get_assets_dir() -> str:
    import sys

    if getattr(sys, "frozen", False):
        return os.path.join(os.getcwd(), "assets")
    return "assets"


def _resolve_session_lut_layout(
    *,
    color_mode: str,
    total_count: int,
    page: str = "Page 1",
    eight_color_full_export: bool = False,
    current_page: bool = False,
) -> LutCardLayout:
    if current_page:
        page_layout = resolve_extraction_page_layout(
            color_mode,
            page=page,
            eight_color_full_export=eight_color_full_export,
        )
        if total_count <= page_layout.capacity:
            return localize_page_layout(page_layout, item_count=total_count)
    return resolve_lut_layout(color_mode, total_count)


def _resolve_session_page_layout(session_data: dict | None, rgb_count: int) -> LutCardPage | None:
    if not session_data:
        return None
    color_mode = str(session_data.get("color_mode") or "")
    if not color_mode:
        return None
    layout = _resolve_session_lut_layout(
        color_mode=color_mode,
        total_count=rgb_count,
        page=str(session_data.get("page") or "Page 1"),
        eight_color_full_export=bool(session_data.get("eight_color_full_export")),
        current_page=True,
    )
    return layout.pages[0] if layout.pages else None


def _parse_page_number(page: str, default: int = 1) -> int:
    digits = "".join(ch for ch in str(page) if ch.isdigit())
    if not digits:
        return default
    page_number = int(digits)
    return page_number if page_number >= 1 else default


def _get_8color_temp_path(assets_dir: str, page_number: int, eight_color_full_export: bool) -> str:
    if eight_color_full_export:
        return os.path.join(assets_dir, f"temp_8c_full_page_{page_number}.json")
    return os.path.join(assets_dir, f"temp_8c_page_{page_number}.json")


_ROTATE_DIRECTION_TO_LABEL: dict[str, str] = {
    "ccw": "Rotate Left 90°",
    "cw": "Rotate Right 90°",
}


@router.post("/rotate")
async def extractor_rotate(
    image: UploadFile = File(..., description="待旋转的图片"),
    direction: str = "ccw",
    registry: FileRegistry = Depends(get_file_registry),
):
    """Rotate an image 90 degrees and return the rotated PNG.
    将图像旋转 90 度并返回旋转后的 PNG。

    Args:
        image: Uploaded image to rotate. (待旋转图片)
        direction: ``"ccw"`` for counter-clockwise (default, backwards
            compatible) or ``"cw"`` for clockwise. (``"ccw"`` 逆时针，默认；
            ``"cw"`` 顺时针)
    """
    direction_key = direction.strip().lower()
    rotation_label = _ROTATE_DIRECTION_TO_LABEL.get(direction_key)
    if rotation_label is None:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid rotation direction {direction!r}; expected 'cw' or 'ccw'.",
        )
    try:
        img_arr = await upload_to_ndarray(image)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    rotate_start = time.perf_counter()
    rotated = rotate_image(img_arr, rotation_label)
    if rotated is None:
        raise HTTPException(status_code=500, detail="Image rotation failed")

    rotated_bytes = ndarray_to_png_bytes(rotated)
    # Release intermediate arrays early
    # 尽早释放中间数组
    del img_arr
    h, w = rotated.shape[:2]
    file_id = registry.register_bytes(
        str(uuid.uuid4()),
        rotated_bytes,
        "rotated.png",
        ttl_seconds=EPHEMERAL_PREVIEW_TTL_SECONDS,
    )
    rotate_ms = (time.perf_counter() - rotate_start) * 1000.0
    del rotated, rotated_bytes

    log.info(
        "Extractor rotate completed",
        extra={
            "event": "extractor_rotate_done",
            "direction": str(direction_key),
            "output_width": int(w),
            "output_height": int(h),
            "rotate_ms": round(rotate_ms, 2),
        },
    )

    return {
        "preview_url": f"/api/files/{file_id}",
        "width": w,
        "height": h,
    }


@router.post("/preview-wb")
async def extractor_preview_wb(
    image: UploadFile = File(..., description="待处理的图片"),
    registry: FileRegistry = Depends(get_file_registry),
):
    """Apply auto white balance to an image and return the preview PNG.
    对图像应用自动白平衡并返回预览 PNG。
    """
    try:
        img_arr = await upload_to_ndarray(image)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    wb_start = time.perf_counter()
    balanced = apply_auto_white_balance(img_arr)
    del img_arr
    balanced_bytes = ndarray_to_png_bytes(balanced)
    h, w = balanced.shape[:2]
    file_id = registry.register_bytes(
        str(uuid.uuid4()),
        balanced_bytes,
        "wb_preview.png",
        ttl_seconds=EPHEMERAL_PREVIEW_TTL_SECONDS,
    )
    wb_ms = (time.perf_counter() - wb_start) * 1000.0
    del balanced, balanced_bytes

    log.info(
        "Extractor white-balance preview completed",
        extra={
            "event": "extractor_preview_wb_done",
            "output_width": int(w),
            "output_height": int(h),
            "wb_ms": round(wb_ms, 2),
        },
    )

    return {
        "preview_url": f"/api/files/{file_id}",
        "width": w,
        "height": h,
    }


@router.post("/extract")
async def extractor_extract(
    image: UploadFile = File(..., description="Calibration board image"),
    corner_points: str = Form(..., description="4 个角点坐标 JSON 数组 [[x,y],...]"),
    color_mode: str = Form("4-Color (RYBW)", description="标准颜色模式"),
    page: str = Form("Page 1", description="8-Color 页码"),
    eight_color_full_export: bool = Form(False, description="8 色是否来自全量分页导出"),
    offset_x: int = Form(0, description="水平采样偏移"),
    offset_y: int = Form(0, description="垂直采样偏移"),
    zoom: float = Form(1.0, description="透视校正缩放"),
    distortion: float = Form(0.0, description="畸变校正"),
    vignette_correction: bool = Form(False, description="暗角校正"),
    auto_wb: bool = Form(False, description="Enable auto white balance"),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ExtractResponse:
    """Extract colors from a photographed calibration board.
    从拍摄的标定板图像中提取颜色。
    """
    # Parse corner_points from JSON string
    try:
        points: List[List[int]] = json.loads(corner_points)
    except (json.JSONDecodeError, TypeError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid corner_points JSON: {e}")

    if len(points) != 4:
        raise HTTPException(
            status_code=422,
            detail=f"corner_points must contain exactly 4 points, got {len(points)}",
        )

    effective_color_mode = _normalize_6color_mode(color_mode)

    # Convert UploadFile to ndarray
    try:
        img_arr = await upload_to_ndarray(image)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Call core extraction (field name mapping: distortion->barrel, vignette_correction->bright)
    extract_start = time.perf_counter()
    try:
        vis_img, preview_img, lut_path, status_msg = run_extraction(
            img=img_arr,
            points=points,
            offset_x=offset_x,
            offset_y=offset_y,
            zoom=zoom,
            barrel=distortion,
            bright=vignette_correction,
            color_mode=effective_color_mode,
            page_choice=page,
            auto_wb=auto_wb,
            eight_color_full_export=eight_color_full_export,
        )
        extract_ms = (time.perf_counter() - extract_start) * 1000.0
    except EXTRACTOR_HANDLED_ERRORS as e:
        _handle_core_error(e, "Color extraction")

    if lut_path is None:
        raise HTTPException(status_code=500, detail=status_msg or "Extraction failed")

    # Create session and store state
    session_id = store.create()
    store.put(session_id, "lut_path", lut_path)
    store.put(session_id, "color_mode", effective_color_mode)
    store.put(session_id, "page", page)
    store.put(session_id, "eight_color_full_export", bool(eight_color_full_export))

    # For 8-Color mode: save page-specific temp file
    if "8-Color" in effective_color_mode and lut_path:
        assets_dir = _get_assets_dir()
        os.makedirs(assets_dir, exist_ok=True)
        max_page = EIGHT_COLOR_FULL_TOTAL_PAGES if eight_color_full_export else 2
        page_idx = min(max(_parse_page_number(page), 1), max_page)
        temp_path = _get_8color_temp_path(assets_dir, page_idx, eight_color_full_export)
        try:
            rgb, stacks, metadata = LUTManager.load_lut_with_metadata(lut_path)
            if stacks is None:
                stacks = np.zeros((len(rgb), 0), dtype=np.int32)
            LUTManager.save_keyed_json(temp_path, rgb, stacks, metadata)
            store.put(session_id, "lut_path", temp_path)
            lut_path = temp_path
        except LUT_PERSIST_WARNING_ERRORS as e:
            log.warning(
                "Failed to save 8-color temp LUT page",
                extra={
                    "event": "extractor_temp_lut_save_failed",
                    "page_idx": page_idx,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )

    # For 5-Color Extended mode: save page-specific temp file
    if "5-Color" in effective_color_mode and lut_path:
        import sys

        if getattr(sys, "frozen", False):
            assets_dir = os.path.join(os.getcwd(), "assets")
        else:
            assets_dir = "assets"
        os.makedirs(assets_dir, exist_ok=True)
        page_idx: int = 1 if "1" in str(page) else 2
        temp_path = os.path.join(assets_dir, f"temp_5c_ext_page_{page_idx}.json")
        try:
            rgb, stacks, metadata = LUTManager.load_lut_with_metadata(lut_path)
            if stacks is None:
                stacks = np.zeros((len(rgb), 0), dtype=np.int32)
            LUTManager.save_keyed_json(temp_path, rgb, stacks, metadata)
            store.put(session_id, "lut_path", temp_path)
            lut_path = temp_path
        except LUT_PERSIST_WARNING_ERRORS as e:
            log.warning(
                "Failed to save 5-color-ext temp LUT page",
                extra={
                    "event": "extractor_temp_lut_save_failed",
                    "page_idx": page_idx,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )

    # Register LUT file (already in Keyed JSON format from run_extraction)
    lut_download_id = registry.register_path(session_id, lut_path)
    try:
        layout_rgb, _layout_stacks, _layout_metadata = LUTManager.load_lut_with_metadata(lut_path)
        lut_layout = _resolve_session_lut_layout(
            color_mode=effective_color_mode,
            total_count=len(layout_rgb),
            page=page,
            eight_color_full_export=bool(eight_color_full_export),
            current_page=True,
        )
    except LUT_PERSIST_WARNING_ERRORS:
        lut_layout = None

    # Register warp view (visualization)
    warp_view_id = ""
    if vis_img is not None:
        vis_bytes = _image_to_png_bytes(vis_img)
        warp_view_id = registry.register_bytes(session_id, vis_bytes, "warp_view.png")

    # Register LUT preview
    lut_preview_id = ""
    if preview_img is not None:
        preview_bytes = _image_to_png_bytes(preview_img)
        lut_preview_id = registry.register_bytes(session_id, preview_bytes, "lut_preview.png")

    log.info(
        "Extractor extract completed",
        extra={
            "event": "extractor_extract_done",
            "color_mode": effective_color_mode,
            "page": page,
            "eight_color_full_export": bool(eight_color_full_export),
            "lut_path": str(lut_path),
            "extract_ms": round(extract_ms, 1),
        },
    )

    return ExtractResponse(
        session_id=session_id,
        status="ok",
        message=status_msg or "Extraction complete",
        lut_download_url=f"/api/files/{lut_download_id}",
        warp_view_url=f"/api/files/{warp_view_id}" if warp_view_id else "",
        lut_preview_url=f"/api/files/{lut_preview_id}" if lut_preview_id else "",
        # The extraction pipeline uses ``effective_color_mode`` (CMYW-normalized
        # for 6-Color variants to share the same processing path). The
        # user-facing default palette must use the *raw* ``color_mode`` so
        # RYBWGK keeps its RYBW slot names (White/Red/Yellow/Blue/Green/Black)
        # instead of being displayed as CMYW (White/Cyan/Magenta/...).
        # 提取管线使用 ``effective_color_mode``（6 色变体统一归一为 CMYW 共享处理
        # 路径）。但面向用户的默认调色板必须使用原始 ``color_mode``，这样 RYBWGK
        # 保持自己的 RYBW 槽位名（白/红/黄/蓝/绿/黑），不会被显示成 CMYW
        # （白/青/品红/...）。
        default_palette=_build_default_palette(color_mode),
        lut_layout=lut_layout.to_dict() if lut_layout is not None else None,
    )


@router.post("/manual-fix")
def extractor_manual_fix(
    request: ExtractorManualFixRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ManualFixResponse:
    """Manually override a single LUT cell color value.
    手动覆盖单个 LUT 格点的颜色值。
    """
    # Resolve lut_path: prefer session lookup, fallback to direct path
    lut_path = request.lut_path
    session_data = None
    if request.session_id:
        bind_session_id(request.session_id)
        session_data = store.get(request.session_id)
        if session_data and "lut_path" in session_data:
            lut_path = session_data["lut_path"]

    manual_fix_start = time.perf_counter()
    try:
        page_layout = None
        if lut_path:
            rgb_for_layout, _stacks_for_layout, _metadata_for_layout = LUTManager.load_lut_with_metadata(lut_path)
            page_layout = _resolve_session_page_layout(session_data, len(rgb_for_layout))
        preview_result, status_msg = manual_fix_cell(
            coord=request.cell_coord,
            row_index=request.row_index,
            color_input=request.override_color,
            lut_path=lut_path,
            page_layout=page_layout,
        )
    except EXTRACTOR_HANDLED_ERRORS as e:
        _handle_core_error(e, "Manual fix")
    manual_fix_ms = (time.perf_counter() - manual_fix_start) * 1000.0

    if preview_result is None:
        raise HTTPException(status_code=500, detail=status_msg or "Manual fix failed")

    # Register updated preview
    preview_bytes = _image_to_png_bytes(preview_result)
    has_valid_session = bool(request.session_id and store.exists(request.session_id))
    sid_for_registry = request.session_id if has_valid_session else str(uuid.uuid4())
    preview_id = registry.register_bytes(
        sid_for_registry,
        preview_bytes,
        "lut_preview.png",
        ttl_seconds=None if has_valid_session else EPHEMERAL_PREVIEW_TTL_SECONDS,
    )

    log.info(
        "Extractor manual fix completed",
        extra={
            "event": "extractor_manual_fix_done",
            "cell_coord_row": int(request.cell_coord[0]),
            "cell_coord_col": int(request.cell_coord[1]),
            "override_color": str(request.override_color),
            "has_session": bool(has_valid_session),
            "manual_fix_ms": round(manual_fix_ms, 2),
        },
    )

    return ManualFixResponse(
        status="ok",
        message=status_msg or "Cell updated",
        lut_preview_url=f"/api/files/{preview_id}",
        lut_layout=(
            localize_page_layout(page_layout, len(rgb_for_layout)).to_dict()
            if page_layout is not None
            else None
        ),
    )


@router.post("/resolve-cell", response_model=LutPreviewResolvedCell)
def extractor_resolve_cell(
    request: ExtractorResolveCellRequest,
    store: SessionStore = Depends(get_session_store),
) -> LutPreviewResolvedCell:
    """Resolve a LUT preview click using the backend LUT card layout."""
    bind_session_id(request.session_id)
    session_data = store.get(request.session_id)
    if not session_data or "lut_path" not in session_data:
        raise HTTPException(status_code=404, detail="Session LUT not found")

    lut_path = session_data["lut_path"]
    try:
        rgb, _stacks, _metadata = LUTManager.load_lut_with_metadata(lut_path)
    except EXTRACTOR_HANDLED_ERRORS as e:
        _handle_core_error(e, "Resolve LUT preview cell")

    color_mode = str(session_data.get("color_mode") or "")
    layout = _resolve_session_lut_layout(
        color_mode=color_mode,
        total_count=len(rgb),
        page=str(session_data.get("page") or "Page 1"),
        eight_color_full_export=bool(session_data.get("eight_color_full_export")),
        current_page=True,
    )
    try:
        cell = cell_from_normalized_point(
            layout,
            card_index=request.card_index,
            x=request.x,
            y=request.y,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid card_index: {exc}") from exc
    if cell is None:
        raise HTTPException(status_code=404, detail="Clicked cell is outside the valid LUT area")

    cell_rgb = tuple(int(v) for v in rgb[cell.row_index])
    return LutPreviewResolvedCell(
        cell=cell.to_dict(),
        rgb=cell_rgb,
        hex=rgb_to_hex(cell_rgb),
        overlay_bbox=overlay_bbox_for_cell(cell),
    )


@router.post("/merge-5color-extended")
def extractor_merge_5color_extended(
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ExtractResponse:
    """Merge two 5-Color Extended pages into a single LUT.
    将两页 5-Color Extended 合并为单个 LUT。
    """
    import sys
    from config import LUT_FILE_PATH

    if getattr(sys, "frozen", False):
        assets_dir = os.path.join(os.getcwd(), "assets")
    else:
        assets_dir = "assets"

    path1 = os.path.join(assets_dir, "temp_5c_ext_page_1.json")
    path2 = os.path.join(assets_dir, "temp_5c_ext_page_2.json")

    if not os.path.exists(path1) or not os.path.exists(path2):
        raise HTTPException(
            status_code=400,
            detail="Missing temp pages. Please extract Page 1 and Page 2 first.",
        )

    merge_start = time.perf_counter()
    try:
        rgb1, stacks1, meta1 = LUTManager.load_lut_with_metadata(path1)
        rgb2, stacks2, meta2 = LUTManager.load_lut_with_metadata(path2)
        rgb1 = rgb1.reshape(-1, 3)
        rgb2 = rgb2.reshape(-1, 3)
        merged_rgb = np.vstack([rgb1, rgb2])

        # Merge stacks if available
        stacks_compatible = (
            stacks1 is not None
            and stacks2 is not None
            and stacks1.shape[1] == stacks2.shape[1]
        )
        if stacks_compatible:
            merged_stacks = np.vstack([stacks1, stacks2])
        else:
            merged_stacks = np.zeros((len(merged_rgb), 0), dtype=np.int32)

        metadata = _build_merged_metadata(meta1, meta2, "5-Color Extended", LUT_FILE_PATH, len(merged_rgb))
        LUTManager.save_keyed_json(LUT_FILE_PATH, merged_rgb, merged_stacks, metadata)
    except EXTRACTOR_HANDLED_ERRORS as e:
        _handle_core_error(e, "5-Color Extended merge")
    merge_ms = (time.perf_counter() - merge_start) * 1000.0

    # Create session for merged result
    session_id = store.create()
    store.put(session_id, "lut_path", LUT_FILE_PATH)
    store.put(session_id, "color_mode", "5-Color Extended")

    lut_download_id = registry.register_path(session_id, LUT_FILE_PATH)

    log.info(
        "Extractor 5-Color Extended merge completed",
        extra={
            "event": "extractor_merge_5color_extended_done",
            "merged_rgb_count": int(merged_rgb.shape[0]),
            "stacks_compatible": bool(stacks_compatible),
            "merge_ms": round(merge_ms, 2),
        },
    )

    return ExtractResponse(
        session_id=session_id,
        status="ok",
        message=f"5-Color Extended LUT merged ({merged_rgb.shape[0]}x{merged_rgb.shape[1]})",
        lut_download_url=f"/api/files/{lut_download_id}",
        warp_view_url="",
        lut_preview_url="",
        default_palette=_build_default_palette("5-Color Extended"),
    )


@router.post("/merge-8color")
def extractor_merge_8color(
    request: ExtractorMergeEightColorRequest | None = None,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ExtractResponse:
    """Merge extracted 8-Color pages into a single LUT.
    将提取得到的 8 色分页结果合并为单个 LUT。
    """
    from config import LUT_FILE_PATH

    eight_color_full_export = bool(request.eight_color_full_export) if request is not None else False
    assets_dir = _get_assets_dir()
    total_pages = EIGHT_COLOR_FULL_TOTAL_PAGES if eight_color_full_export else 2
    page_paths = [
        _get_8color_temp_path(assets_dir, page_number, eight_color_full_export)
        for page_number in range(1, total_pages + 1)
    ]
    missing_pages = [
        str(page_number)
        for page_number, page_path in enumerate(page_paths, start=1)
        if not os.path.exists(page_path)
    ]

    if missing_pages:
        missing_hint = ", ".join(missing_pages[:8])
        if len(missing_pages) > 8:
            missing_hint += ", ..."
        raise HTTPException(
            status_code=400,
            detail=(
                f"Missing temp pages. Please extract all required pages first. Missing: {missing_hint}"
            ),
        )

    merge_start = time.perf_counter()
    try:
        rgb_parts = []
        stack_parts = []
        metadata_parts = []
        stacks_compatible = True
        expected_stack_width = None

        for page_path in page_paths:
            rgb, stacks, metadata = LUTManager.load_lut_with_metadata(page_path)
            rgb_parts.append(rgb.reshape(-1, 3))
            metadata_parts.append(metadata)
            if stacks is None:
                stacks_compatible = False
                continue
            stacks = stacks.reshape(stacks.shape[0], -1)
            if expected_stack_width is None:
                expected_stack_width = stacks.shape[1]
            elif stacks.shape[1] != expected_stack_width:
                stacks_compatible = False
            stack_parts.append(stacks)

        merged_rgb = np.vstack(rgb_parts)

        if stacks_compatible and stack_parts and len(stack_parts) == len(page_paths):
            merged_stacks = np.vstack(stack_parts)
        else:
            merged_stacks = np.zeros((len(merged_rgb), 0), dtype=np.int32)

        metadata = _build_merged_metadata(
            metadata_parts[0],
            metadata_parts[-1],
            "8-Color Max",
            LUT_FILE_PATH,
            len(merged_rgb),
        )
        LUTManager.save_keyed_json(LUT_FILE_PATH, merged_rgb, merged_stacks, metadata)
    except EXTRACTOR_HANDLED_ERRORS as e:
        _handle_core_error(e, "8-Color merge")
    merge_ms = (time.perf_counter() - merge_start) * 1000.0

    # Create session for merged result
    session_id = store.create()
    store.put(session_id, "lut_path", LUT_FILE_PATH)
    store.put(session_id, "color_mode", "8-Color Max")

    lut_download_id = registry.register_path(session_id, LUT_FILE_PATH)

    log.info(
        "Extractor 8-Color merge completed",
        extra={
            "event": "extractor_merge_8color_done",
            "eight_color_full_export": bool(eight_color_full_export),
            "total_pages": int(total_pages),
            "merged_rgb_count": int(merged_rgb.shape[0]),
            "stacks_compatible": bool(stacks_compatible),
            "merge_ms": round(merge_ms, 2),
        },
    )

    return ExtractResponse(
        session_id=session_id,
        status="ok",
        message=(
            f"8-Color{' Full' if eight_color_full_export else ''} LUT merged "
            f"({merged_rgb.shape[0]}x{merged_rgb.shape[1]})"
        ),
        lut_download_url=f"/api/files/{lut_download_id}",
        warp_view_url="",
        lut_preview_url="",
        default_palette=_build_default_palette("8-Color Max"),
    )


@router.post("/confirm-palette")
def confirm_palette(
    request: ConfirmPaletteRequest,
    store: SessionStore = Depends(get_session_store),
) -> dict:
    """Accept user-confirmed palette and save to session.
    接受用户确认的调色板并写入会话。

    Args:
        request (ConfirmPaletteRequest): Palette confirmation request. (调色板确认请求)
        store (SessionStore): Session store dependency. (会话存储)

    Returns:
        dict: Confirmation status. (确认状态)

    Raises:
        HTTPException: 422 if color name is blank, 404 if session not found.
            (颜色名称为空返回 422，session 不存在返回 404)
    """
    for entry in request.palette:
        if not entry.color or not entry.color.strip():
            raise HTTPException(status_code=422, detail="Color name cannot be blank")

    confirm_start = time.perf_counter()
    bind_session_id(request.session_id)
    session_data = store.get(request.session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session {request.session_id} not found")

    manufacturer = request.manufacturer.strip()
    lut_type = request.type.strip()
    palette_entries = [
        PaletteEntry(
            color=e.color.strip(),
            material=e.material.strip() if e.material else "PLA Basic",
            hex_color=e.hex_color,
            color_name=e.color_name.strip() if e.color_name and e.color_name.strip() else None,
        )
        for e in request.palette
    ]

    metadata = LUTMetadata(
        palette=palette_entries,
        manufacturer=manufacturer,
        type=lut_type,
        color_mode=session_data.get("color_mode"),
    )

    # Persist palette to the LUT JSON file on disk
    lut_path = session_data.get("lut_path")
    persist_warning = None
    if lut_path and os.path.exists(lut_path):
        try:
            rgb, stacks, existing_metadata = LUTManager.load_lut_with_metadata(lut_path)
            existing_metadata.palette = palette_entries
            existing_metadata.manufacturer = manufacturer
            existing_metadata.type = lut_type
            if not existing_metadata.color_mode and session_data.get("color_mode"):
                existing_metadata.color_mode = session_data["color_mode"]
            if stacks is None:
                stacks = np.zeros((len(rgb), 0), dtype=np.int32)
            LUTManager.save_keyed_json(lut_path, rgb, stacks, existing_metadata)
            metadata = existing_metadata
        except LUT_PERSIST_WARNING_ERRORS as e:
            persist_warning = f"调色板已确认，但持久化到磁盘失败: {e}"
            log.warning(
                "Failed to persist confirmed palette",
                extra={
                    "event": "extractor_persist_palette_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )

    store.put(request.session_id, "lut_metadata", metadata)
    confirm_ms = (time.perf_counter() - confirm_start) * 1000.0

    log.info(
        "Extractor palette confirmation completed",
        extra={
            "event": "extractor_confirm_palette_done",
            "palette_size": int(len(request.palette)),
            "manufacturer": str(manufacturer),
            "lut_type": str(lut_type),
            "persisted_to_disk": bool(
                lut_path is not None and os.path.exists(lut_path) and persist_warning is None
            ),
            "confirm_ms": round(confirm_ms, 2),
        },
    )

    if persist_warning:
        return {"status": "warning", "message": persist_warning}
    return {"status": "ok", "message": "调色板已确认"}
