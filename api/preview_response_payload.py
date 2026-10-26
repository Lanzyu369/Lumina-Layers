"""Preview response payload builders."""

from __future__ import annotations

from typing import Any

import numpy as np


def build_preview_response_palette(
    cache_data: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build the preview API palette from a preview cache.

    从预览缓存构造 preview API 返回给前端的调色板列表。
    """
    raw_palette: list[dict[str, Any]] = (
        cache_data.get("color_palette", []) if cache_data else []
    )
    quantized_image = cache_data.get("quantized_image") if cache_data else None
    matched_rgb_arr = cache_data.get("matched_rgb") if cache_data else None
    mask_solid_arr = cache_data.get("mask_solid") if cache_data else None

    palette: list[dict[str, Any]] = []
    if not raw_palette or matched_rgb_arr is None or mask_solid_arr is None:
        return palette

    matched_to_quantized: dict[str, str] = {}
    if quantized_image is not None:
        solid_mask = mask_solid_arr
        q_pixels = quantized_image[solid_mask]
        m_pixels = matched_rgb_arr[solid_mask]

        # Encode RGB triplets as scalars so the dominant source colour per
        # matched colour can be found with one np.unique pass.
        m_enc = (
            (m_pixels[:, 0].astype(np.uint32) << 16)
            | (m_pixels[:, 1].astype(np.uint32) << 8)
            | m_pixels[:, 2].astype(np.uint32)
        )
        q_enc = (
            (q_pixels[:, 0].astype(np.uint32) << 16)
            | (q_pixels[:, 1].astype(np.uint32) << 8)
            | q_pixels[:, 2].astype(np.uint32)
        )

        pair_key = m_enc.astype(np.uint64) * (1 << 24) + q_enc.astype(np.uint64)
        unique_keys, counts = np.unique(pair_key, return_counts=True)

        u_m = (unique_keys >> 24).astype(np.uint32)
        u_q = (unique_keys & 0xFFFFFF).astype(np.uint32)

        order = np.lexsort((-counts, u_m))
        sorted_m = u_m[order]
        sorted_q = u_q[order]
        _, first_idx = np.unique(sorted_m, return_index=True)

        for mk, qk in zip(sorted_m[first_idx], sorted_q[first_idx]):
            m_hex = f"#{(mk >> 16) & 0xFF:02x}{(mk >> 8) & 0xFF:02x}{mk & 0xFF:02x}"
            q_hex = f"#{(qk >> 16) & 0xFF:02x}{(qk >> 8) & 0xFF:02x}{qk & 0xFF:02x}"
            matched_to_quantized[m_hex] = q_hex

    for entry in raw_palette:
        m_hex = entry["hex"]
        q_hex = matched_to_quantized.get(m_hex, m_hex)
        palette.append(
            {
                "quantized_hex": q_hex,
                "matched_hex": m_hex,
                "pixel_count": entry["count"],
                "percentage": entry["percentage"],
            }
        )

    return palette
