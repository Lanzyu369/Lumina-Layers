"""LUT HTML grid renderers (api layer).
LUT 网格 HTML 渲染器（API 层）。

This module owns the HTML-string generators that used to live in
``core/pipeline/pipeline_utils.py``. They are presentation-layer helpers
producing raw HTML for legacy gradio surfaces; per ``AGENTS.md`` L72 layering
rule (``core/`` -> API/workers -> UI), UI/presentation belongs in ``api/``,
not in ``core/``.

历史上这些函数被放在 ``core/pipeline/pipeline_utils.py``，违反了
``core/`` 不混入 UI 表现层的层次约定。Phase 0 Sub-PR B 将其迁移到本模块
``api/lut_html.py``。``core/pipeline/pipeline_utils.py`` 保留同名再导出
作为过渡期向后兼容层，待 Phase 4 删除。

The functions here have **no active call sites** in the Python code (the
React frontend renders LUT grids via API data, not server-rendered HTML),
but the symbols remain reachable through the ``core.converter`` chain for
backward compatibility — see ``tests/test_backward_compat_properties.py``.
"""

from __future__ import annotations

import colorsys
import math
import os

import numpy as np

# NOTE: ``extract_lut_available_colors`` is imported lazily inside the
# functions below (instead of at module-top) so this module can be loaded
# before ``core.pipeline.pipeline_utils`` finishes initialising — the latter
# re-exports our public symbols, which would otherwise create a module-load
# cycle on cold imports.
# 延迟导入避免与 ``core.pipeline.pipeline_utils`` 的循环导入。

__all__ = [
    "generate_lut_color_dropdown_html",
    "generate_lut_grid_html",
    "generate_lut_card_grid_html",
]


def generate_lut_color_dropdown_html(lut_path: str, selected_color: str = None, used_colors: set = None) -> str:
    """
    Generate HTML for displaying LUT available colors as a clickable visual grid.
    生成 LUT 可用颜色的可点击视觉网格 HTML。

    Colors are grouped into two sections:
    1. Colors used in current image (if any)
    2. Other available colors

    This provides a visual preview of all available colors from the LUT,
    allowing users to click directly to select a replacement color.

    Args:
        lut_path: Path to the LUT .npy file
        selected_color: Currently selected replacement color hex
        used_colors: Set of hex colors currently used in the image (for grouping)

    Returns:
        HTML string showing available colors as a clickable grid
    """
    # NOTE: HTML generation was previously delegated to legacy UI extension
    # modules. The web frontend now renders color grid UI via API data.
    from core.pipeline.pipeline_utils import extract_lut_available_colors

    colors = extract_lut_available_colors(lut_path)
    if not colors:
        return ""
    return ""


def _classify_hue(r: int, g: int, b: int) -> str:
    """色相分类辅助 / Classify a colour into one of nine hue buckets.

    Args:
        r, g, b: 0-255 RGB components.

    Returns:
        One of ``"red", "orange", "yellow", "green", "cyan", "blue",
        "purple", "neutral"``.
    """
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    h, s, v = colorsys.rgb_to_hsv(rf, gf, bf)
    h360 = h * 360
    if s < 0.15 or v < 0.10:
        return "neutral"
    if h360 < 15 or h360 >= 345:
        return "red"
    elif h360 < 40:
        return "orange"
    elif h360 < 70:
        return "yellow"
    elif h360 < 160:
        return "green"
    elif h360 < 195:
        return "cyan"
    elif h360 < 260:
        return "blue"
    elif h360 < 345:
        return "purple"
    return "neutral"


def generate_lut_grid_html(lut_path, lang: str = "zh"):
    """
    生成 LUT 可用颜色的 HTML 网格 (with hue filter + smart search)。
    Generate LUT available colors HTML grid with hue filter and smart search.

    Args:
        lut_path: LUT 文件路径
        lang (str): 语言代码，默认 "zh"

    Returns:
        str: HTML 字符串
    """
    from core.i18n import I18n
    from core.pipeline.pipeline_utils import extract_lut_available_colors

    colors = extract_lut_available_colors(lut_path)

    if not colors:
        return f"<div style='color:orange'>LUT 文件无效或为空</div>"

    count = len(colors)

    # NOTE: Search/hue-filter UI is rendered by the web frontend via API data.
    _search_bar_html = ""
    _hue_filter_html = ""

    # Derive LUT key for favorites persistence
    _lut_key = os.path.splitext(os.path.basename(lut_path))[0] if lut_path else ""

    html = f"""
    <div class="lut-grid-container">
        <div style="margin-bottom: 8px; font-size: 12px; color: #666;">
            {I18n.get('lut_grid_count', lang).format(count=count)}: <span id="lut-color-visible-count">{count}</span>
        </div>
        {_search_bar_html}
        {_hue_filter_html}
        <div id="lut-color-grid-container" data-lut-key="{_lut_key}" style="
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            max-height: 300px;
            overflow-y: auto;
            padding: 5px;
            border: 1px solid #eee;
            border-radius: 8px;
            background: #f9f9f9;">
    """

    for entry in colors:
        hex_val = entry["hex"]
        r, g, b = entry["color"]
        rgb_val = f"R:{r} G:{g} B:{b}"
        hue_cat = _classify_hue(r, g, b)

        html += f"""
        <div class="lut-color-swatch-container" data-hue="{hue_cat}" style="display:flex;">
        <div class="lut-swatch lut-color-swatch"
             data-color="{hex_val}"
             style="background-color: {hex_val}; width:24px; height:24px; cursor:pointer; border:1px solid #ddd; border-radius:3px;"
             title="{hex_val} ({rgb_val})">
        </div>
        </div>
        """

    html += "</div></div>"
    return html


def generate_lut_card_grid_html(lut_path, lang: str = "zh"):
    """
    Generate a calibration-card-style (色卡) HTML grid for the LUT.
    生成校准卡风格的 LUT HTML 网格。

    Colors are displayed in their original LUT order arranged in a square grid,
    matching the physical calibration board layout.  For 8-color LUTs the two
    halves are shown side-by-side horizontally.

    Includes search bar (highlight-in-place, no hiding) and hue filter
    (dims non-matching swatches instead of hiding to preserve grid layout).

    Each swatch is clickable (same data-color / class as the swatch grid) so
    the existing event-delegation click handler picks it up automatically.

    Args:
        lut_path: LUT 文件路径
        lang (str): 语言代码，默认 "zh"

    Returns:
        str: HTML 字符串
    """
    if not lut_path:
        return "<div style='color:orange'>LUT 文件无效或为空</div>"

    try:
        lut_grid = np.load(lut_path)
        measured_colors = lut_grid.reshape(-1, 3)
    except (OSError, ValueError, TypeError) as e:
        return f"<div style='color:orange'>LUT 加载失败: {e}</div>"

    total = len(measured_colors)

    from core.i18n import I18n

    if total == 2738:
        half = total // 2
        remainder = total - half
        dim1 = int(math.ceil(math.sqrt(half)))
        dim2 = int(math.ceil(math.sqrt(remainder)))
        grids = [
            (measured_colors[:half], dim1, "色卡 A" if lang == "zh" else "Card A"),
            (measured_colors[half:], dim2, "色卡 B" if lang == "zh" else "Card B"),
        ]
    else:
        dim = int(math.ceil(math.sqrt(total)))
        label = f"{total} 色色卡" if lang == "zh" else f"{total}-color Card"
        grids = [(measured_colors, dim, label)]

    cell = 18
    gap = 1

    # NOTE: Search/hue-filter UI is rendered by the web frontend via API data.
    html_parts = [
        f'<div style="margin-bottom:8px; font-size:12px; color:#666;">{I18n.get("lut_grid_count", lang).format(count=total)}: <span id="lut-color-visible-count">{total}</span></div>',
    ]

    # Derive LUT key for favorites persistence
    _lut_key = os.path.splitext(os.path.basename(lut_path))[0] if lut_path else ""

    # Grid
    html_parts.append(
        f"<div id='lut-color-grid-container' data-lut-key='{_lut_key}' style='display:flex; gap:12px; align-items:flex-start; "
        "overflow-x:auto; padding:4px;'>"
    )

    for colors_arr, dim, title in grids:
        html_parts.append(
            f"<div style='flex-shrink:0;'>"
            f"<div style='font-size:11px; color:#666; margin-bottom:4px;'>{title} ({len(colors_arr)})</div>"
            f"<div style='display:grid; grid-template-columns:repeat({dim}, {cell}px); gap:{gap}px; "
            f"border:1px solid #eee; border-radius:6px; padding:4px; background:#f9f9f9;'>"
        )
        for c in colors_arr:
            r, g, b = int(c[0]), int(c[1]), int(c[2])
            hex_val = f"#{r:02x}{g:02x}{b:02x}"
            hue_cat = _classify_hue(r, g, b)
            html_parts.append(
                f"<div class='lut-swatch lut-color-swatch' data-color='{hex_val}' data-hue='{hue_cat}' "
                f"style='width:{cell}px;height:{cell}px;background:{hex_val};"
                f"cursor:pointer;border-radius:2px;' "
                f"title='{hex_val} (R:{r} G:{g} B:{b})'></div>"
            )
        html_parts.append("</div></div>")

    html_parts.append("</div>")
    return "".join(html_parts)
