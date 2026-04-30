"""ColorWorkstation click-selection helpers (api layer).
ColorWorkstation 点击选择辅助函数（API 层）。

This module owns the click-selection meta builders + recommendation helpers
that used to live in ``core/pipeline/pipeline_utils.py``. They serve the
``/region-replace`` / ``/region-replace-batch`` ColorWorkstation flow and
the legacy preview-click pipeline; per ``AGENTS.md`` L72 layering rule
(``core/`` -> API/workers -> UI), helpers driven by UI events belong in
``api/``.

Phase 0 Sub-PR B 把这些点击选区辅助函数从 ``core/pipeline/pipeline_utils.py``
迁移到本模块。``core/pipeline/pipeline_utils.py`` 保留同名再导出作为过渡
向后兼容层，待 Phase 4 删除。
"""

from __future__ import annotations

import numpy as np

from core.pipeline.pipeline_utils import _rgb_to_hex

__all__ = [
    "_recommend_lut_colors_by_rgb",
    "_build_selection_meta",
    "_resolve_highlight_mask",
    "_build_dual_recommendations",
    "_resolve_click_selection_hexes",
]


def _recommend_lut_colors_by_rgb(base_rgb, lut_colors, top_k=10):
    """Recommend LUT colors by RGB Euclidean distance, return top_k items.
    按 RGB 欧氏距离推荐 LUT 颜色，返回前 top_k 项。

    Args:
        base_rgb: (R, G, B) 基准颜色
        lut_colors: LUT 颜色列表（dict 或 tuple 格式）
        top_k (int): 返回前 k 项

    Returns:
        list[dict]: 推荐颜色列表，每项包含 'color' 和 'hex'
    """
    if not lut_colors:
        return []

    normalized = []
    for c in lut_colors:
        if isinstance(c, dict):
            color = c.get("color")
            hex_color = c.get("hex")
            if color is None and isinstance(hex_color, str) and len(hex_color.strip().lstrip("#")) == 6:
                h = hex_color.strip().lstrip("#")
                color = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            if color is not None and isinstance(hex_color, str):
                normalized.append({"color": tuple(int(v) for v in color), "hex": hex_color.lower()})
            continue

        if isinstance(c, (tuple, list)) and len(c) >= 2 and isinstance(c[1], str):
            h = c[1].strip().lstrip("#")
            if len(h) != 6:
                continue
            normalized.append({"color": (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)), "hex": f"#{h.lower()}"})

    if not normalized:
        return []

    arr = np.array([c["color"] for c in normalized], dtype=np.float64)
    b = np.array(base_rgb, dtype=np.float64)
    dist = np.sqrt(np.sum((arr - b) ** 2, axis=1))
    idx = np.argsort(dist)[:top_k]
    return [normalized[i] for i in idx]


def _build_selection_meta(q_rgb, m_rgb, scope="region"):
    """Build click selection metadata (quantized color + matched color).
    构建点击选区元数据（量化色 + 原配准色）。

    Args:
        q_rgb: 量化色 RGB 三元组
        m_rgb: 原配准色 RGB 三元组
        scope (str): 选择范围 ("region" 或 "global")

    Returns:
        dict: 包含 selected_quantized_hex、selected_matched_hex、selection_scope
    """
    return {
        "selected_quantized_hex": _rgb_to_hex(q_rgb),
        "selected_matched_hex": _rgb_to_hex(m_rgb),
        "selection_scope": scope,
    }


def _resolve_highlight_mask(color_match, mask_solid, region_mask=None, scope="global"):
    """Determine highlight mask based on selection scope: region first, otherwise global same-color.
    根据选择范围决定高亮掩码：区域优先，否则全图同色。

    Args:
        color_match (np.ndarray): (H, W) bool 颜色匹配掩码
        mask_solid (np.ndarray): (H, W) bool 实体掩码
        region_mask (np.ndarray | None): (H, W) bool 区域掩码
        scope (str): "region" 或 "global"

    Returns:
        np.ndarray: (H, W) bool 高亮掩码
    """
    if scope == "region" and region_mask is not None:
        return region_mask & mask_solid
    return color_match & mask_solid


def _build_dual_recommendations(q_rgb, m_rgb, lut_colors, top_k=10):
    """Build dual-basis recommendations: by quantized color and by matched color.
    构建双基准推荐：按量化色与按原配准色。

    Args:
        q_rgb: 量化色 RGB 三元组
        m_rgb: 原配准色 RGB 三元组
        lut_colors: LUT 颜色列表
        top_k (int): 每组返回前 k 项

    Returns:
        dict: 包含 'by_quantized' 和 'by_matched' 两组推荐列表
    """
    return {
        "by_quantized": _recommend_lut_colors_by_rgb(q_rgb, lut_colors, top_k=top_k),
        "by_matched": _recommend_lut_colors_by_rgb(m_rgb, lut_colors, top_k=top_k),
    }


def _resolve_click_selection_hexes(cache, default_hex):
    """Resolve display color and internal state color after click.
    解析点击后的显示色与内部状态色。

    显示色优先使用原配准色，内部状态色保持量化色，
    以兼容"显示原图色、替换按量化色作用连通域"的设计。

    Args:
        cache (dict | None): 预览缓存
        default_hex: 默认 hex 颜色值

    Returns:
        tuple: (display_hex, internal_hex)
    """
    cached_q_hex = (cache or {}).get("selected_quantized_hex")
    cached_m_hex = (cache or {}).get("selected_matched_hex")

    # Non-string values (e.g. None) must not propagate into hex state.
    fallback_hex = default_hex if isinstance(default_hex, str) else None
    q_hex = cached_q_hex if isinstance(cached_q_hex, str) else fallback_hex
    m_hex = cached_m_hex if isinstance(cached_m_hex, str) else q_hex
    return m_hex, q_hex
