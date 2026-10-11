"""Compatibility imports for color selection helpers now owned by core."""

from core.pipeline.pipeline_utils import (
    _recommend_lut_colors_by_rgb,
    _build_selection_meta,
    _resolve_highlight_mask,
    _build_dual_recommendations,
    _resolve_click_selection_hexes,
)

__all__ = [
    "_recommend_lut_colors_by_rgb",
    "_build_selection_meta",
    "_resolve_highlight_mask",
    "_build_dual_recommendations",
    "_resolve_click_selection_hexes",
]
