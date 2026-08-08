"""
S05 — 2D preview image generation with keychain loop drawing.
S05 — 2D 预览图生成与挂件环绘制。

从 converter.py 搬入的预览生成逻辑和挂件环辅助函数：
- _calculate_loop_position: 根据预设计算挂件环位置
- _calculate_loop_info: 计算挂件环完整信息
- _draw_loop_on_preview: 在预览图上绘制挂件环
"""

import time
import numpy as np
from PIL import Image, ImageDraw
from typing import Optional, Dict, Tuple

from api.structured_logging import get_logger
from core.pipeline.preview_color_utils import (
    build_material_preview_warning_extra,
    resolve_material_preview,
)

_log = get_logger(__name__)


def _calculate_loop_position(
    position_preset: str,
    offset_x: float,
    offset_y: float,
    mask_solid: np.ndarray,
    target_w: int,
    target_h: int,
    pixel_scale: float,
) -> tuple:
    """Calculate keychain loop attach position based on preset and offset.
    根据位置预设和偏移量计算钥匙扣挂孔的吸附位置。

    Extracts model bounds from mask_solid, selects an edge snap point based on
    the position preset, then adds the user-specified offset.
    从 mask_solid 提取模型边界，根据预设选择边缘吸附点，叠加偏移量。

    Args:
        position_preset (str): Preset name for snap position.
            (预设位置名称，如 'top-center', 'top-left' 等)
        offset_x (float): X offset in mm to add to the base position.
            (叠加到基准位置的 X 偏移量，单位 mm)
        offset_y (float): Y offset in mm to add to the base position.
            (叠加到基准位置的 Y 偏移量，单位 mm)
        mask_solid (np.ndarray): Boolean 2D array (H, W) indicating solid pixels.
            (布尔二维数组，标识实体像素)
        target_w (int): Image width in pixels. (图像宽度，像素)
        target_h (int): Image height in pixels. (图像高度，像素)
        pixel_scale (float): mm per pixel conversion factor. (像素到 mm 的缩放因子)

    Returns:
        tuple[float, float]: (attach_x_mm, attach_y_mm) position in mm.
            (吸附点坐标，单位 mm)
    """
    # Extract model bounds from mask_solid
    solid_rows = np.any(mask_solid, axis=1)
    solid_cols = np.any(mask_solid, axis=0)

    if not np.any(solid_rows) or not np.any(solid_cols):
        # No solid pixels — return model center as fallback
        center_x_mm = (target_w / 2.0) * pixel_scale
        center_y_mm = (target_h / 2.0) * pixel_scale
        return (center_x_mm + offset_x, center_y_mm + offset_y)

    row_indices = np.where(solid_rows)[0]
    col_indices = np.where(solid_cols)[0]

    min_row = int(row_indices[0])
    max_row = int(row_indices[-1])
    min_col = int(col_indices[0])
    max_col = int(col_indices[-1])

    # Convert pixel bounds to mm coordinates.
    # In the image coordinate system, row 0 is the top.
    # In the mm coordinate system used by the 3D model,
    # Y increases upward: y_mm = (target_h - 1 - row) * pixel_scale
    min_x_mm = min_col * pixel_scale
    max_x_mm = max_col * pixel_scale
    # max_row (bottom in image) -> minY in mm; min_row (top in image) -> maxY in mm
    min_y_mm = (target_h - 1 - max_row) * pixel_scale
    max_y_mm = (target_h - 1 - min_row) * pixel_scale

    center_x_mm = (min_x_mm + max_x_mm) / 2.0
    center_y_mm = (min_y_mm + max_y_mm) / 2.0

    # Select base snap point based on preset
    preset = position_preset if position_preset else "top-center"

    if preset == "top-center":
        base_x = center_x_mm
        base_y = max_y_mm
    elif preset == "top-left":
        base_x = min_x_mm
        base_y = max_y_mm
    elif preset == "top-right":
        base_x = max_x_mm
        base_y = max_y_mm
    elif preset == "left-center":
        base_x = min_x_mm
        base_y = center_y_mm
    elif preset == "right-center":
        base_x = max_x_mm
        base_y = center_y_mm
    elif preset == "bottom-center":
        base_x = center_x_mm
        base_y = min_y_mm
    else:
        # Unknown preset — fall back to top-center
        base_x = center_x_mm
        base_y = max_y_mm

    return (base_x + offset_x, base_y + offset_y)


def _calculate_loop_info(
    loop_pos: Optional[Tuple[float, float]],
    loop_width: float,
    loop_length: float,
    loop_hole: float,
    mask_solid: np.ndarray,
    material_matrix: np.ndarray,
    target_w: int,
    target_h: int,
    pixel_scale: float,
    angle_deg: float = 0.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    position_preset: str = "top-center",
) -> Optional[Dict]:
    """Calculate keychain loop information including position and angle.
    计算钥匙扣挂孔信息，包括位置和旋转角度。

    When loop_pos is provided, snaps to the nearest solid pixel from the
    click point. When loop_pos is None, delegates to _calculate_loop_position()
    to compute a default position based on the preset and offset.
    当 loop_pos 有值时，吸附到点击点最近的实体像素；当 loop_pos 为 None 时，
    委托 _calculate_loop_position() 根据预设和偏移计算默认位置。

    Args:
        loop_pos (Optional[Tuple[float, float]]): Click position (x, y) in pixels,
            or None to use preset-based calculation. (点击位置像素坐标，None 则使用预设计算)
        loop_width (float): Loop width in mm. (环宽度，mm)
        loop_length (float): Loop length in mm. (环长度，mm)
        loop_hole (float): Hole diameter in mm. (孔径，mm)
        mask_solid (np.ndarray): Boolean 2D array (H, W) of solid pixels. (实体像素掩码)
        material_matrix (np.ndarray): Material assignment matrix. (材料分配矩阵)
        target_w (int): Image width in pixels. (图像宽度，像素)
        target_h (int): Image height in pixels. (图像高度，像素)
        pixel_scale (float): mm per pixel. (像素到 mm 缩放因子)
        angle_deg (float): Rotation angle in degrees, default 0. (旋转角度，度，默认 0)
        offset_x (float): X offset in mm, default 0. (X 偏移量，mm，默认 0)
        offset_y (float): Y offset in mm, default 0. (Y 偏移量，mm，默认 0)
        position_preset (str): Position preset name, default "top-center".
            (位置预设名称，默认 "top-center")

    Returns:
        Optional[Dict]: Loop info dict with keys attach_x_mm, attach_y_mm,
            width_mm, length_mm, hole_dia_mm, color_id, angle_deg; or None
            if no solid pixels exist. (挂孔信息字典，或 None)
    """
    solid_rows = np.any(mask_solid, axis=1)
    if not np.any(solid_rows):
        return None

    if loop_pos is not None:
        # Original click-based position logic
        click_x, click_y = loop_pos
        attach_col = int(click_x)
        attach_row = int(click_y)
        attach_col = max(0, min(target_w - 1, attach_col))
        attach_row = max(0, min(target_h - 1, attach_row))

        col_mask = mask_solid[:, attach_col]
        if np.any(col_mask):
            solid_rows_in_col = np.where(col_mask)[0]
            distances = np.abs(solid_rows_in_col - attach_row)
            nearest_idx = np.argmin(distances)
            top_row = solid_rows_in_col[nearest_idx]
        else:
            top_row = np.argmax(solid_rows)
            solid_cols_in_top = np.where(mask_solid[top_row])[0]
            if len(solid_cols_in_top) > 0:
                distances = np.abs(solid_cols_in_top - attach_col)
                nearest_idx = np.argmin(distances)
                attach_col = solid_cols_in_top[nearest_idx]
            else:
                attach_col = target_w // 2

        attach_col = max(0, min(target_w - 1, attach_col))

        attach_x_mm = attach_col * pixel_scale
        attach_y_mm = (target_h - 1 - top_row) * pixel_scale
    else:
        # Preset-based position calculation
        attach_x_mm, attach_y_mm = _calculate_loop_position(
            position_preset=position_preset,
            offset_x=offset_x,
            offset_y=offset_y,
            mask_solid=mask_solid,
            target_w=target_w,
            target_h=target_h,
            pixel_scale=pixel_scale,
        )
        # Convert mm back to pixel coords for color sampling
        attach_col = int(attach_x_mm / pixel_scale) if pixel_scale > 0 else target_w // 2
        attach_col = max(0, min(target_w - 1, attach_col))
        top_row_mm = attach_y_mm / pixel_scale if pixel_scale > 0 else 0
        top_row = int(target_h - 1 - top_row_mm)
        top_row = max(0, min(target_h - 1, top_row))

    # Determine loop color from nearby material
    loop_color_id = 0
    search_area = material_matrix[
        max(0, top_row-2):top_row+3,
        max(0, attach_col-3):attach_col+4
    ]
    search_area = search_area[search_area >= 0]
    if len(search_area) > 0:
        unique, counts = np.unique(search_area, return_counts=True)
        for mat_id in unique[np.argsort(-counts)]:
            if mat_id != 0:
                loop_color_id = int(mat_id)
                break

    return {
        'attach_x_mm': attach_x_mm,
        'attach_y_mm': attach_y_mm,
        'width_mm': loop_width,
        'length_mm': loop_length,
        'hole_dia_mm': loop_hole,
        'color_id': loop_color_id,
        'angle_deg': angle_deg,
    }


def _draw_loop_on_preview(preview_rgba, loop_info, color_conf, pixel_scale):
    """Draw keychain loop on preview image.
    在预览图上绘制挂件环。

    Args:
        preview_rgba (np.ndarray): (H, W, 4) uint8 RGBA 预览图
        loop_info (dict): 挂件环信息字典
        color_conf (dict): 颜色系统配置
        pixel_scale (float): mm/px 缩放因子

    Returns:
        np.ndarray: 绘制挂件环后的 RGBA 预览图
    """
    preview_pil = Image.fromarray(preview_rgba, mode='RGBA')
    draw = ImageDraw.Draw(preview_pil)

    resolved_rgba = loop_info.get("color_rgba")
    if resolved_rgba is None:
        compatibility_resolution = resolve_material_preview(
            material_id=loop_info["color_id"],
            slot_names=color_conf.get("slots"),
            preview_colors=color_conf.get("preview"),
            color_conf=color_conf,
        )
        if not compatibility_resolution.is_resolved:
            raise ValueError(
                "Loop material preview color is unavailable for drawing"
            )
        resolved_rgba = compatibility_resolution.rgba
    loop_color_rgba = tuple(resolved_rgba)

    attach_col = int(loop_info['attach_x_mm'] / pixel_scale)
    attach_row = int((preview_rgba.shape[0] - 1) - loop_info['attach_y_mm'] / pixel_scale)

    loop_w_px = int(loop_info['width_mm'] / pixel_scale)
    loop_h_px = int(loop_info['length_mm'] / pixel_scale)
    hole_r_px = int(loop_info['hole_dia_mm'] / 2 / pixel_scale)
    circle_r_px = loop_w_px // 2

    loop_bottom = attach_row
    loop_left = attach_col - loop_w_px // 2
    loop_right = attach_col + loop_w_px // 2

    rect_h_px = loop_h_px - circle_r_px
    rect_bottom = loop_bottom
    rect_top = loop_bottom - rect_h_px

    circle_center_y = rect_top
    circle_center_x = attach_col

    if rect_h_px > 0:
        draw.rectangle(
            [loop_left, rect_top, loop_right, rect_bottom],
            fill=loop_color_rgba
        )

    draw.ellipse(
        [circle_center_x - circle_r_px, circle_center_y - circle_r_px,
         circle_center_x + circle_r_px, circle_center_y + circle_r_px],
        fill=loop_color_rgba
    )

    draw.ellipse(
        [circle_center_x - hole_r_px, circle_center_y - hole_r_px,
         circle_center_x + hole_r_px, circle_center_y + hole_r_px],
        fill=(0, 0, 0, 0)
    )

    return np.array(preview_pil)


def run(ctx: dict) -> dict:
    """Generate 2D preview image and optionally draw keychain loop.
    生成 2D 预览图，可选绘制挂件环。

    PipelineContext 输入键 / Input keys:
        - matched_rgb (np.ndarray): (H, W, 3) uint8 匹配后的 RGB
        - mask_solid (np.ndarray): (H, W) bool 实体掩码
        - target_w (int): 目标宽度 (像素)
        - target_h (int): 目标高度 (像素)
        - pixel_scale (float): mm/px 缩放因子
        - add_loop (bool): 是否添加挂件环
        - loop_pos (tuple | None): 挂件环点击位置
        - loop_width (float): 环宽度 (mm)
        - loop_length (float): 环长度 (mm)
        - loop_hole (float): 孔径 (mm)
        - loop_angle (float): 旋转角度 (度)
        - loop_offset_x (float): X 偏移 (mm)
        - loop_offset_y (float): Y 偏移 (mm)
        - loop_position_preset (str | None): 位置预设
        - material_matrix (np.ndarray): 材料矩阵
        - color_conf (dict): 颜色系统配置
        - slot_names (list[str]): 与材料 ID 对齐的权威材料名称
        - preview_colors (dict): 与材料 ID 对齐的权威预览颜色

    PipelineContext 输出键 / Output keys:
        - preview_rgba (np.ndarray): (H, W, 4) uint8 RGBA 预览图
        - preview_img (PIL.Image): PIL RGBA 预览图像
        - loop_info (dict | None): 挂件环信息
    """
    _t0 = time.perf_counter()

    matched_rgb = ctx['matched_rgb']
    mask_solid = ctx['mask_solid']
    target_w = ctx['target_w']
    target_h = ctx['target_h']
    pixel_scale = ctx['pixel_scale']
    color_conf = ctx['color_conf']

    # Build preview RGBA
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    preview_rgba[mask_solid, 3] = 255

    # Handle keychain loop
    loop_info = None
    add_loop = ctx.get('add_loop', False)
    if add_loop:
        loop_info = _calculate_loop_info(
            ctx.get('loop_pos'),
            ctx.get('loop_width', 5.0),
            ctx.get('loop_length', 10.0),
            ctx.get('loop_hole', 3.0),
            mask_solid,
            ctx['material_matrix'],
            target_w, target_h, pixel_scale,
            angle_deg=ctx.get('loop_angle', 0.0),
            offset_x=ctx.get('loop_offset_x', 0.0),
            offset_y=ctx.get('loop_offset_y', 0.0),
            position_preset=ctx.get('loop_position_preset') or "top-center",
        )

        if loop_info:
            slot_names = ctx.get("slot_names")
            preview_colors = ctx.get("preview_colors")
            resolution = resolve_material_preview(
                material_id=loop_info["color_id"],
                slot_names=slot_names,
                preview_colors=preview_colors,
                color_conf=color_conf,
            )
            if not resolution.is_resolved:
                _log.warning(
                    "Loop material preview metadata is unresolved",
                    extra=build_material_preview_warning_extra(
                        resolution,
                        slot_names=slot_names,
                        preview_colors=preview_colors,
                        color_conf=color_conf,
                        material_source=ctx.get("material_source", "lut"),
                    ),
                )
                raise ValueError(
                    "Loop material identity or preview color is unavailable"
                )
            loop_info["material_name"] = resolution.material_name
            loop_info["color_rgba"] = list(resolution.rgba)
            loop_info["color_source"] = resolution.source
            preview_rgba = _draw_loop_on_preview(
                preview_rgba, loop_info, color_conf, pixel_scale
            )

    preview_img = Image.fromarray(preview_rgba, mode='RGBA')

    ctx['preview_rgba'] = preview_rgba
    ctx['preview_img'] = preview_img
    ctx['loop_info'] = loop_info

    _elapsed = time.perf_counter() - _t0
    _hifi_timings = ctx.get('_hifi_timings', {})
    _hifi_timings['preview_gen_s'] = _elapsed
    ctx['_hifi_timings'] = _hifi_timings
    _log.debug(
        "preview_gen done: %.3fs",
        _elapsed,
        extra={
            "event": "s05_preview_gen_done",
            "duration_ms": round(_elapsed * 1000, 3),
            "width": int(target_w),
            "height": int(target_h),
            "loop_enabled": bool(add_loop),
            "loop_added": loop_info is not None,
        },
    )
    return ctx
