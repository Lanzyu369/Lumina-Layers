"""
孤立像素清理模块（Isolated Pixel Cleanup）

严格孤立像素（1px）：与所有 8 邻域均不同，用邻域众数替换
"""

import numpy as np
from collections import Counter
from typing import Any

from api.structured_logging import get_logger

_log = get_logger(__name__)


def _encode_stacks(material_matrix, base):
    """将 (H, W, N) 的材料矩阵编码为 (H, W) 整数矩阵。"""
    if material_matrix.ndim != 3:
        raise ValueError(f"material_matrix must be 3D, got shape={material_matrix.shape}")
    n = material_matrix.shape[2]
    weights = np.array([base ** i for i in range(n - 1, -1, -1)], dtype=np.int64)
    return np.sum(material_matrix.astype(np.int64) * weights, axis=2)


def _detect_isolated(encoded):
    """检测孤立像素（与所有 8 邻域均不同），返回布尔掩码。"""
    H, W = encoded.shape
    if H <= 1 and W <= 1:
        return np.zeros((H, W), dtype=bool)
    nc = np.zeros((H, W), dtype=np.int32)
    dc = np.zeros((H, W), dtype=np.int32)
    for dy, dx in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
        cy0, cy1 = max(0, -dy), H - max(0, dy)
        cx0, cx1 = max(0, -dx), W - max(0, dx)
        c = encoded[cy0:cy1, cx0:cx1]
        n = encoded[cy0+dy:cy1+dy, cx0+dx:cx1+dx]
        nc[cy0:cy1, cx0:cx1] += 1
        dc[cy0:cy1, cx0:cx1] += (c != n).astype(np.int32)
    return (dc == nc) & (nc > 0)


def _find_neighbor_mode(encoded, isolated_mask):
    """对每个孤立像素，找 8 邻域众数编码。"""
    H, W = encoded.shape
    mode_map = encoded.copy()
    dirs = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
    for i, j in np.argwhere(isolated_mask):
        nb = []
        for dy, dx in dirs:
            ni, nj = i + dy, j + dx
            if 0 <= ni < H and 0 <= nj < W:
                nb.append(encoded[ni, nj])
        if nb:
            mode_map[i, j] = Counter(nb).most_common(1)[0][0]
    return mode_map


def cleanup_isolated_pixels(
    material_matrix, matched_rgb, lut_rgb, ref_stacks,
    small_blob_threshold=50,
):
    """孤立像素清理：与所有8邻域均不同的像素，用邻域众数替换。"""
    import time

    cleaned_mat = material_matrix.copy()
    cleaned_rgb = matched_rgb.copy()
    H, W = material_matrix.shape[:2]
    total_pixels = H * W

    base = int(material_matrix.max()) + 1 if material_matrix.size > 0 else 1
    encoded = _encode_stacks(material_matrix, base)

    layer_count = ref_stacks.shape[1]
    lut_encoded = _encode_stacks(ref_stacks.reshape(1, -1, layer_count), base).flatten()
    encode_to_lut_idx = {}
    for idx in range(len(lut_encoded)):
        v = int(lut_encoded[idx])
        if v not in encode_to_lut_idx:
            encode_to_lut_idx[v] = idx

    t0 = time.time()
    iso = _detect_isolated(encoded)
    iso_count = int(np.sum(iso))
    rep1 = 0
    if iso_count > 0:
        mm = _find_neighbor_mode(encoded, iso)
        for i, j in np.argwhere(iso):
            ne = int(mm[i, j])
            if ne in encode_to_lut_idx:
                li = encode_to_lut_idx[ne]
                cleaned_mat[i, j] = ref_stacks[li]
                cleaned_rgb[i, j] = lut_rgb[li]
                encoded[i, j] = ne
                rep1 += 1
    p1 = (rep1 / total_pixels * 100) if total_pixels > 0 else 0
    extra: dict[str, Any] = {
        "event": "isolated_pixels_cleaned",
        "isolated_count": iso_count,
        "merge_ratio_percent": round(p1, 3),
        "duration_ms": round((time.time() - t0) * 1000, 3),
    }
    if rep1 != iso_count:
        extra["merged_count"] = rep1
    _log.info("Isolated pixels cleaned", extra=extra)

    return cleaned_rgb, cleaned_mat
