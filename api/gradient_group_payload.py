"""Shared gradient-group payload computation."""

from __future__ import annotations

from typing import Any

import numpy as np

from core.gradient_group_analyzer import (
    GradientGroupAnalysisParams,
    analyze_gradient_groups_with_region_id_map,
    gradient_groups_to_json,
)


def compute_gradient_group_payload(
    cache_data: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], np.ndarray] | None:
    """Compute gradient groups and the matching per-pixel region map.

    根据 preview cache 计算渐变分组，以及对应的每像素 region id 图。
    """
    if cache_data is None:
        return None

    matched_rgb = cache_data.get("matched_rgb")
    quantized_image = cache_data.get("quantized_image")
    mask_solid = cache_data.get("mask_solid")
    if matched_rgb is None or quantized_image is None or mask_solid is None:
        return None

    analysis = analyze_gradient_groups_with_region_id_map(
        matched_rgb=np.asarray(matched_rgb, dtype=np.uint8),
        quantized_rgb=np.asarray(quantized_image, dtype=np.uint8),
        mask_solid=np.asarray(mask_solid, dtype=bool),
        params=GradientGroupAnalysisParams(),
    )
    payload = gradient_groups_to_json(analysis.groups)
    region_id_map = np.ascontiguousarray(analysis.region_id_map, dtype=np.uint32)
    return payload, region_id_map
