"""
core.pipeline.pipeline_utils — 管道共享工具函数
Pipeline shared utility functions.

从 converter.py 原封不动搬入的工具函数集合，包括：
- 颜色工具函数（RGB/Hex 转换、亮度计算、调色板提取、自动高度图生成）
- LUT 工具函数（颜色提取、下拉菜单生成、颜色模式检测）
- 检测工具函数（图像类型检测）
- 缓存辅助函数（量化图像缓存回填）
- LUT HTML 网格生成函数
"""

from api.structured_logging import get_logger
import os
import math
import numpy as np
from typing import Any, List, Dict, Tuple, Optional

from config import PrinterConfig, ColorSystem, ModelingMode

log = get_logger(__name__)

# ========== 颜色工具函数 (Color Utility Functions) ==========


def _rgb_to_hex(rgb):
    """将 RGB 三元组转换为 #RRGGBB。
    Convert RGB tuple to #RRGGBB hex string.

    Args:
        rgb: (R, G, B) 三元组，每个值 0-255

    Returns:
        str: '#rrggbb' 格式的十六进制颜色字符串
    """
    r, g, b = [int(x) for x in rgb]
    return f"#{r:02x}{g:02x}{b:02x}"


def _hex_to_rgb_tuple(hex_color):
    """将 #RRGGBB 转换为 (R, G, B)。
    Convert #RRGGBB hex string to (R, G, B) tuple.

    Args:
        hex_color (str): '#rrggbb' 格式的十六进制颜色字符串

    Returns:
        tuple: (R, G, B) 三元组，每个值 0-255

    Raises:
        ValueError: 如果输入不是有效的 hex 颜色字符串
    """
    if not isinstance(hex_color, str):
        raise ValueError("hex_color must be a string")

    h = hex_color.strip().lower()
    if h.startswith("#"):
        h = h[1:]
    if len(h) != 6:
        raise ValueError(f"invalid hex color: {hex_color}")

    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def calculate_luminance(hex_color):
    """
    Calculate relative luminance of a color using standard formula.
    使用标准公式计算颜色的相对亮度。

    Formula: Y = 0.299*R + 0.587*G + 0.114*B

    Args:
        hex_color: Color in hex format (e.g., '#ff0000')

    Returns:
        float: Luminance value (0-255)
    """
    # Remove '#' if present
    hex_color = hex_color.lstrip("#")

    # Convert hex to RGB
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    # Calculate luminance using standard formula
    luminance = 0.299 * r + 0.587 * g + 0.114 * b

    return luminance


def extract_color_palette(preview_cache: dict) -> List[dict]:
    """
    Extract unique colors from preview cache.
    从预览缓存中提取唯一颜色调色板。

    Args:
        preview_cache: Cache data from generate_preview_cached containing:
            - matched_rgb: (H, W, 3) uint8 array of matched colors
            - mask_solid: (H, W) bool array indicating solid pixels

    Returns:
        List of dicts sorted by pixel count (descending), each containing:
        - 'color': (R, G, B) tuple
        - 'hex': '#RRGGBB' string
        - 'count': pixel count
        - 'percentage': percentage of total solid pixels (0.0-100.0)
    """
    if preview_cache is None:
        return []

    matched_rgb = preview_cache.get("matched_rgb")
    mask_solid = preview_cache.get("mask_solid")

    if matched_rgb is None or mask_solid is None:
        return []

    # Get only solid pixels
    solid_pixels = matched_rgb[mask_solid]

    if len(solid_pixels) == 0:
        return []

    total_solid = len(solid_pixels)

    # Find unique colors and their counts
    # Reshape to (N, 3) and find unique rows
    unique_colors, counts = np.unique(solid_pixels, axis=0, return_counts=True)

    # Build palette entries
    palette = []
    for color, count in zip(unique_colors, counts):
        r, g, b = int(color[0]), int(color[1]), int(color[2])
        palette.append(
            {
                "color": (r, g, b),
                "hex": f"#{r:02x}{g:02x}{b:02x}",
                "count": int(count),
                "percentage": round(count / total_solid * 100, 2),
            }
        )

    # Sort by count descending
    palette.sort(key=lambda x: x["count"], reverse=True)

    return palette


def generate_auto_height_map(color_list, mode, base_thickness, max_relief_height):
    """
    Generate automatic height mapping based on color luminance using Min-Max normalization.
    基于颜色亮度使用 Min-Max 归一化生成自动高度映射。

    This function calculates the luminance of each color and assigns heights
    using normalization, ensuring all heights fall within [base_thickness, max_relief_height].
    This prevents height explosion when dealing with many colors.

    Algorithm:
    1. Calculate luminance Y = 0.299*R + 0.587*G + 0.114*B for each color
    2. Find Y_min and Y_max across all colors
    3. Calculate available height range: Delta_Z = max_relief_height - base_thickness
    4. For each color, calculate normalized ratio:
       - If "浅色凸起": Ratio = (Y - Y_min) / (Y_max - Y_min)
       - If "深色凸起": Ratio = 1.0 - (Y - Y_min) / (Y_max - Y_min)
    5. Final height = base_thickness + Ratio * Delta_Z
    6. Round to 0.1mm precision

    Args:
        color_list: List of hex color strings (e.g., ['#ff0000', '#00ff00'])
        mode: Sorting mode - "深色凸起" (darker higher) or "浅色凸起" (lighter higher)
        base_thickness: Base thickness in mm (minimum height)
        max_relief_height: Maximum relief height in mm (maximum height)

    Returns:
        dict: Color-to-height mapping {hex_color: height_mm}

    Example:
        >>> colors = ['#ff0000', '#00ff00', '#0000ff']
        >>> generate_auto_height_map(colors, "深色凸起", 1.2, 5.0)
        {'#00ff00': 1.2, '#ff0000': 3.1, '#0000ff': 5.0}
    """
    if not color_list:
        return {}

    # Step 1: Calculate luminance for each color
    color_luminance = []
    for color in color_list:
        luminance = calculate_luminance(color)
        color_luminance.append((color, luminance))

    # Step 2: Find min and max luminance
    luminances = [lum for _, lum in color_luminance]
    y_min = min(luminances)
    y_max = max(luminances)

    # Handle edge case: all colors have same luminance
    if y_max == y_min:
        # All colors get the same height (average of base and max)
        avg_height = (base_thickness + max_relief_height) / 2.0
        color_height_map = {color: round(avg_height, 1) for color, _ in color_luminance}
        log.info(
            "Auto height map used average height",
            extra={
                "event": "auto_height_map_average_used",
                "color_count": len(color_list),
                "average_height_mm": round(avg_height, 3),
            },
        )
        return color_height_map

    # Step 3: Calculate available height range
    delta_z = max_relief_height - base_thickness

    # Step 4 & 5: Calculate normalized heights
    color_height_map = {}
    for color, luminance in color_luminance:
        # Normalize luminance to [0, 1]
        normalized = (luminance - y_min) / (y_max - y_min)

        # Apply mode: darker higher or lighter higher
        if "深色凸起" in mode or "Darker Higher" in mode:
            # Darker colors (lower luminance) should be higher
            # Invert the ratio: 0 -> 1, 1 -> 0
            ratio = 1.0 - normalized
        else:
            # Lighter colors (higher luminance) should be higher
            # Keep the ratio as is: 0 -> 0, 1 -> 1
            ratio = normalized

        # Calculate final height (minimum 0.08mm = 1 layer height)
        height = max(0.08, base_thickness + ratio * delta_z)

        # Round to 0.1mm precision
        color_height_map[color] = round(height, 1)

    log.info(
        "Auto height map generated",
        extra={
            "event": "auto_height_map_generated",
            "color_count": len(color_list),
            "mode": mode,
            "luminance_min": round(float(y_min), 3),
            "luminance_max": round(float(y_max), 3),
            "height_min_mm": round(float(min(color_height_map.values())), 3),
            "height_max_mm": round(float(max(color_height_map.values())), 3),
            "height_span_mm": round(float(max(color_height_map.values()) - min(color_height_map.values())), 3),
        },
    )

    return color_height_map


# ========== LUT 工具函数 (LUT Utility Functions) ==========

# Try to import LUTManager for metadata loading
try:
    from utils.lut_manager import LUTManager
except ImportError:
    LUTManager = None


def extract_lut_available_colors(lut_path: str) -> List[dict]:
    """
    Extract all available colors from a LUT file.
    从 LUT 文件中提取所有可用颜色。

    This function loads a LUT file (.npy/.npz/.json) and extracts all unique
    colors that the printer can produce. These colors can be used as
    replacement options in the color replacement feature.

    Uses LUTManager.load_lut_with_metadata() as the unified loading entry
    point to support all LUT formats consistently.

    Args:
        lut_path: Path to the LUT file (.npy/.npz/.json)

    Returns:
        List of dicts, each containing:
        - 'color': (R, G, B) tuple
        - 'hex': '#RRGGBB' string

        Returns empty list if LUT cannot be loaded.
    """
    if not lut_path:
        return []

    try:
        # 统一通过 LUTManager 加载，支持 .npy/.npz/.json 三种格式
        if LUTManager is not None:
            rgb, _stacks, _metadata = LUTManager.load_lut_with_metadata(lut_path)
            measured_colors = rgb.reshape(-1, 3)
        elif lut_path.endswith(".npz"):
            data = np.load(lut_path, allow_pickle=False)
            measured_colors = data["rgb"]
        else:
            lut_grid = np.load(lut_path)
            measured_colors = lut_grid.reshape(-1, 3)
        log.debug(
            "Loading LUT colors",
            extra={
                "event": "lut_colors_loading",
                "lut_path": lut_path,
                "color_count": int(len(measured_colors)),
            },
        )

        # Get unique colors
        unique_colors = np.unique(measured_colors, axis=0)

        # Build color list
        colors = []
        for color in unique_colors:
            r, g, b = int(color[0]), int(color[1]), int(color[2])
            colors.append({"color": (r, g, b), "hex": f"#{r:02x}{g:02x}{b:02x}"})

        # Sort by brightness (dark to light) for better UX
        colors.sort(key=lambda x: sum(x["color"]))

        measured_count = int(len(measured_colors))
        unique_count = int(len(unique_colors))
        extra: dict[str, Any] = {
            "event": "lut_colors_loaded",
            "lut_path": lut_path,
            "color_count": measured_count,
        }
        if unique_count != measured_count:
            extra["unique_count"] = unique_count
        log.info("LUT colors loaded", extra=extra)
        return colors

    except (OSError, ValueError, TypeError, KeyError) as e:
        log.warning(
            "Failed to extract LUT colors",
            extra={
                "event": "lut_colors_extraction_failed",
                "lut_path": lut_path,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        return []


def get_lut_color_choices(lut_path: str) -> List[tuple]:
    """
    Get LUT colors formatted for dropdown selection.
    获取格式化为下拉菜单的 LUT 颜色列表。

    Args:
        lut_path: Path to the LUT .npy file

    Returns:
        List of (display_label, hex_value) tuples for Dropdown choices.
        Display label includes a colored square emoji approximation.
    """
    colors = extract_lut_available_colors(lut_path)

    if not colors:
        return []

    choices = []
    for entry in colors:
        hex_color = entry["hex"]
        r, g, b = entry["color"]
        # Create a display label with RGB values
        label = f"■ {hex_color} (R:{r} G:{g} B:{b})"
        choices.append((label, hex_color))

    return choices


# generate_lut_color_dropdown_html relocated to api/lut_html.py — see
# the deferred re-export block at the bottom of this file.


def detect_lut_color_mode(lut_path):
    """
    自动检测LUT文件的颜色模式。
    Auto-detect the color mode of a LUT file.

    Args:
        lut_path: LUT文件路径

    Returns:
        str: 颜色模式 ("BW (Black & White)", "Merged", "6-Color (CMYWGK 1296)", "8-Color Max", etc.)
             Returns None if detection fails.
    """
    if not lut_path or not os.path.exists(lut_path):
        return None

    try:
        if lut_path.endswith(".npz"):
            data = np.load(lut_path)
            if "rgb" in data:
                rgb = data["rgb"]
                total_colors = int(rgb.reshape(-1, 3).shape[0])
                stacks = data["stacks"] if "stacks" in data else None
                layer_count = int(stacks.shape[1]) if isinstance(stacks, np.ndarray) and stacks.ndim == 2 else None
                max_mat = int(np.max(stacks)) if isinstance(stacks, np.ndarray) and stacks.size > 0 else None
                if (
                    total_colors >= 2400
                    and total_colors < 2600
                    and layer_count == 6
                    and (max_mat is None or max_mat <= 4)
                ):
                    log.info(
                        "Detected LUT color mode",
                        extra={"event": "lut_color_mode_detected", "source": "npz", "color_count": int(total_colors), "color_mode": "5-Color Extended"},
                    )
                    return "5-Color Extended"
                if total_colors >= 2600 and total_colors <= 2800:
                    log.info(
                        "Detected LUT color mode",
                        extra={"event": "lut_color_mode_detected", "source": "npz", "color_count": int(total_colors), "color_mode": "8-Color Max"},
                    )
                    return "8-Color Max"
                if total_colors >= 1200 and total_colors < 1400:
                    log.info(
                        "Detected LUT color mode",
                        extra={"event": "lut_color_mode_detected", "source": "npz", "color_count": int(total_colors), "color_mode": "6-Color (CMYWGK 1296)"},
                    )
                    return "6-Color (CMYWGK 1296)"
                if total_colors >= 900 and total_colors < 1200:
                    log.info(
                        "Detected LUT color mode",
                        extra={"event": "lut_color_mode_detected", "source": "npz", "color_count": int(total_colors), "color_mode": "4-Color"},
                    )
                    return "4-Color"
                if total_colors >= 30 and total_colors <= 35:
                    log.info(
                        "Detected LUT color mode",
                        extra={"event": "lut_color_mode_detected", "source": "npz", "color_count": int(total_colors), "color_mode": "BW (Black & White)"},
                    )
                    return "BW (Black & White)"
            log.info(
                "Detected merged LUT color mode",
                extra={"event": "lut_color_mode_detected", "source": "npz", "color_mode": "Merged"},
            )
            return "Merged"

        # .json (Keyed JSON) format
        if lut_path.endswith(".json"):
            from utils.lut_manager import LUTManager

            rgb, stacks, _meta = LUTManager.load_lut_with_metadata(lut_path)
            # 优先使用存储的 color_mode
            if _meta and _meta.color_mode:
                log.info(
                    "Using LUT color mode metadata",
                    extra={"event": "lut_color_mode_metadata_used", "source": "json", "color_mode": _meta.color_mode},
                )
                return _meta.color_mode
            # 回退到基于数量的推断
            total_colors = len(rgb) if rgb is not None else 0
            layer_count = int(stacks.shape[1]) if isinstance(stacks, np.ndarray) and stacks.ndim == 2 else None
            max_mat = int(np.max(stacks)) if isinstance(stacks, np.ndarray) and stacks.size > 0 else None
            log.debug(
                "JSON LUT mode inputs resolved",
                extra={
                    "event": "json_lut_mode_inputs_resolved",
                    "color_count": int(total_colors),
                    "layer_count": layer_count,
                    "max_material": max_mat,
                },
            )
            if total_colors >= 2400 and total_colors < 2600 and layer_count == 6 and (max_mat is None or max_mat <= 4):
                log.info(
                    "Detected LUT color mode",
                    extra={"event": "lut_color_mode_detected", "source": "json", "color_count": int(total_colors), "color_mode": "5-Color Extended"},
                )
                return "5-Color Extended"
            if total_colors >= 2600 and total_colors <= 2800:
                log.info(
                    "Detected LUT color mode",
                    extra={"event": "lut_color_mode_detected", "source": "json", "color_count": int(total_colors), "color_mode": "8-Color Max"},
                )
                return "8-Color Max"
            if total_colors >= 1200 and total_colors < 1400:
                log.info(
                    "Detected LUT color mode",
                    extra={"event": "lut_color_mode_detected", "source": "json", "color_count": int(total_colors), "color_mode": "6-Color (CMYWGK 1296)"},
                )
                return "6-Color (CMYWGK 1296)"
            if total_colors >= 900 and total_colors < 1200:
                log.info(
                    "Detected LUT color mode",
                    extra={"event": "lut_color_mode_detected", "source": "json", "color_count": int(total_colors), "color_mode": "4-Color"},
                )
                return "4-Color"
            if total_colors >= 30 and total_colors <= 35:
                log.info(
                    "Detected LUT color mode",
                    extra={"event": "lut_color_mode_detected", "source": "json", "color_count": int(total_colors), "color_mode": "BW (Black & White)"},
                )
                return "BW (Black & White)"
            log.info(
                "Detected merged LUT color mode",
                extra={"event": "lut_color_mode_detected", "source": "json", "color_count": int(total_colors), "color_mode": "Merged"},
            )
            return "Merged"

        # Standard .npy format
        lut_data = np.load(lut_path)

        # 确保是2D数组
        if lut_data.ndim == 1:
            # 如果是1D数组，假设是 (N*3,) 格式，重塑为 (N, 3)
            if len(lut_data) % 3 == 0:
                lut_data = lut_data.reshape(-1, 3)
            else:
                log.info(
                    "Invalid LUT shape for mode detection",
                    extra={"event": "lut_color_mode_detection_invalid_shape", "lut_path": lut_path},
                )
                return None

        # 计算颜色数量
        if lut_data.ndim == 2:
            total_colors = lut_data.shape[0]
        else:
            total_colors = lut_data.shape[0] * lut_data.shape[1]

        log.debug(
            "LUT mode inputs resolved",
            extra={"event": "lut_mode_inputs_resolved", "lut_shape": list(lut_data.shape), "color_count": int(total_colors)},
        )

        # 2色模式：32色 (2^5 = 32)
        if total_colors >= 30 and total_colors <= 35:
            log.info(
                "Detected LUT color mode",
                extra={"event": "lut_color_mode_detected", "source": "npy", "color_count": int(total_colors), "color_mode": "BW (Black & White)"},
            )
            return "BW (Black & White)"

        # 5-Color Extended模式：~2468色 (1024 base + 1444 extended)
        elif total_colors >= 2400 and total_colors < 2600:
            log.info(
                "Detected LUT color mode",
                extra={"event": "lut_color_mode_detected", "source": "npy", "color_count": int(total_colors), "color_mode": "5-Color Extended"},
            )
            return "5-Color Extended"

        # 8色模式：2600-2800色
        elif total_colors >= 2600 and total_colors <= 2800:
            log.info(
                "Detected LUT color mode",
                extra={"event": "lut_color_mode_detected", "source": "npy", "color_count": int(total_colors), "color_mode": "8-Color Max"},
            )
            return "8-Color Max"

        # 6色模式：1200-1400色
        elif total_colors >= 1200 and total_colors < 1400:
            log.info(
                "Detected LUT color mode",
                extra={"event": "lut_color_mode_detected", "source": "npy", "color_count": int(total_colors), "color_mode": "6-Color (CMYWGK 1296)"},
            )
            return "6-Color (CMYWGK 1296)"

        # 4色模式：900-1200色
        elif total_colors >= 900 and total_colors < 1200:
            log.info(
                "Detected LUT color mode",
                extra={"event": "lut_color_mode_detected", "source": "npy", "color_count": int(total_colors), "color_mode": "4-Color"},
            )
            return "4-Color"

        else:
            # 非标准尺寸：识别为合并色卡
            log.info(
                "Detected merged LUT color mode",
                extra={"event": "lut_color_mode_detected", "source": "npy", "color_count": int(total_colors), "color_mode": "Merged"},
            )
            return "Merged"

    except (OSError, ValueError, TypeError, KeyError) as e:
        log.exception(
            "Failed to detect LUT color mode",
            extra={
                "event": "lut_color_mode_detection_failed",
                "lut_path": lut_path,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        return None


# ========== 检测工具函数 (Detection Utility Functions) ==========


def detect_image_type(image_path: str | None) -> str | None:
    """Detect image type and return recommended modeling mode.
    自动检测图像类型并返回推荐的建模模式。

    Args:
        image_path (str | None): Image file path. (图像文件路径)

    Returns:
        str | None: Modeling mode string if change recommended, None otherwise.
            (推荐的建模模式字符串，无需变更时返回 None)
    """
    if not image_path:
        return None

    try:
        ext = os.path.splitext(image_path)[1].lower()

        if ext == ".svg":
            log.info(
                "Detected SVG image type",
                extra={"event": "image_type_detected", "image_path": image_path, "extension": ext, "recommended_mode": str(ModelingMode.VECTOR)},
            )
            return ModelingMode.VECTOR
        else:
            log.info(
                "Detected raster image type",
                extra={"event": "image_type_detected", "image_path": image_path, "extension": ext, "recommended_mode": None},
            )
            return None

    except (OSError, ValueError, TypeError) as e:
        log.warning(
            "Failed to detect image type",
            extra={
                "event": "image_type_detection_failed",
                "image_path": image_path,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        return None


# ========== 缓存辅助函数 (Cache Helper Functions) ==========


def _ensure_quantized_image_in_cache(cache):
    """保证预览缓存中存在 quantized_image，缺失时自动回填。
    Ensure quantized_image exists in preview cache, auto-backfill if missing.

    Args:
        cache (dict): 预览缓存字典，包含 matched_rgb 和可选的 debug_data

    Returns:
        dict: 更新后的缓存字典，保证包含 quantized_image 键
    """
    if cache.get("quantized_image") is not None:
        return cache

    dbg = cache.get("debug_data") or {}
    q = dbg.get("quantized_image")
    if q is None:
        q = cache["matched_rgb"].copy()

    cache["quantized_image"] = q
    return cache


# ---------------------------------------------------------------------------
# Phase 0 Sub-PR B: HTML grid + click-selection helpers relocated to api/.
# 这两块原先位于本模块，违反 ``core/ -> api/ -> UI`` 层次约束（``AGENTS.md`` L72）。
# 现已迁移到 ``api/lut_html.py`` 与 ``api/color_workstation_helpers.py``。下面的
# 再导出仅作过渡兼容（``core.converter`` 链上的旧调用与
# ``tests/test_backward_compat_properties.py`` 仍依赖此处可见同名符号）；Phase 4
# 完成消费方迁移后将一并删除。
# ---------------------------------------------------------------------------
from api.lut_html import (  # noqa: E402  -- transitional layer-violation, Phase 0 Sub-PR B
    generate_lut_card_grid_html,
    generate_lut_color_dropdown_html,
    generate_lut_grid_html,
)
from api.color_workstation_helpers import (  # noqa: E402  -- transitional layer-violation
    _build_dual_recommendations,
    _build_selection_meta,
    _recommend_lut_colors_by_rgb,
    _resolve_click_selection_hexes,
    _resolve_highlight_mask,
)
