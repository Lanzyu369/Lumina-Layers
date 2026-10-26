r"""
动态范围压缩模块（Auto Dynamic Range）
Auto dynamic range compressor.

把输入图像的 CIELAB 亮度通道 L\* 重映射到 LUT/耗材档案可达的 L\* 范围：
采用 **Cineon 指数三段曲线**——轻度压缩时中段保持严格斜率 1（恒等映射，
完全保留中灰对比度），仅用两段指数曲线（toe / shoulder）柔化端点；
重度压缩时两段指数直接相接、中段斜率均匀降为 ``2·tgt_span / src_span``，
曲线始终 C1 连续（无斜率突变）。仅作用于 L\* 通道，a\*b\* 保持不变以避免
色相/饱和度漂移。

Map source image L* into the L* range achievable by the selected LUT or
material archive using a **Cineon exponential three-segment curve**: under
light compression the middle keeps slope = 1 exactly (identity — midtone
contrast is fully preserved) and two exponential toes soften only the
endpoints; under heavy compression the two exponentials meet directly, the
central slope smoothly drops to ``2·tgt_span / src_span``, and the curve
stays C1 continuous everywhere. Only L* is modified; a*b* are kept intact
to avoid hue/saturation shifts.
"""

from __future__ import annotations

import math
import numpy as np
import cv2

from api.structured_logging import get_logger

_log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# 内部常量 / Internal constants
# --------------------------------------------------------------------------- #

# OpenCV CIELAB 编码：L 在 [0, 255]，对应真实 L\* 的 [0, 100]。
# OpenCV CIELAB encoding: L is stored in [0, 255], representing L* [0, 100].
_OPENCV_L_SCALE = 255.0 / 100.0

# Cineon 形状常数 k：方程 k·e^k = 2·(e^k − 1) 的数值解，
# 保证指数 toe/shoulder 在内边界处斜率 = 1（C1 连续）。
# Cineon shape constant k: numerical solution of k·e^k = 2·(e^k − 1),
# ensuring the exponential toe/shoulder has slope = 1 at the inner boundary (C1).
_CINEON_K = 1.593624260040
_CINEON_E = math.exp(_CINEON_K) - 1  # ≈ 3.9215

# 触发压缩所需的最小宽度（L* 单位），避免对接近常量的图像做无意义映射。
# Minimum source L* span (L* units) before compression kicks in.
_MIN_SOURCE_SPAN = 1.0

# 触发压缩所需的最小目标收窄量（L* 单位），避免噪声级别的微调。
# Skip compression unless the target span is at least this much narrower.
_MIN_COMPRESSION_DELTA = 1.0


def compute_target_l_range(lut_lab: np.ndarray) -> tuple[float, float] | None:
    r"""Compute L* min/max from a LUT/material palette in CIELAB.
    从 LUT 或耗材调色板的 CIELAB 数组中取 L\* 的最小/最大值。

    Args:
        lut_lab: (N, 3) float array of CIELAB samples (L in [0, 100]).

    Returns:
        (l_min, l_max) tuple, or ``None`` if the input is empty/invalid.
    """
    if lut_lab is None:
        return None
    arr = np.asarray(lut_lab)
    if arr.size == 0 or arr.ndim != 2 or arr.shape[1] < 1:
        return None
    l_channel = arr[:, 0].astype(np.float64, copy=False)
    if not np.isfinite(l_channel).any():
        return None
    l_min = float(np.nanmin(l_channel))
    l_max = float(np.nanmax(l_channel))
    if not np.isfinite(l_min) or not np.isfinite(l_max):
        return None
    if l_max <= l_min:
        return None
    return l_min, l_max


def _remap_l_channel(
    l_star: np.ndarray,
    *,
    src_lo_hard: float,
    src_hi_hard: float,
    tgt_lo: float,
    tgt_hi: float,
) -> np.ndarray:
    r"""Cineon exponential L* remap: toe + identity middle + shoulder.
    Cineon 指数三段 L\* 重映射：阴影 toe + 恒等中段 + 高光 shoulder。

    轻度压缩（W_s + W_h ≤ src_span）时中段严格恒等（斜率 1），
    两端用指数曲线柔化；重度压缩时两段指数直接相接。
    曲线在所有接合点 C1 连续，端点精确映射。

    Under light compression (W_s + W_h ≤ src_span) the middle is strict
    identity (slope 1) with exponential toes at both ends; under heavy
    compression the two exponentials meet directly. The curve is C1
    continuous everywhere and endpoints map exactly.

    Args:
        l_star: Input L* array (true L* units, [0, 100]).
        src_lo_hard: Source hard minimum L*.
        src_hi_hard: Source hard maximum L*.
        tgt_lo: Target minimum L*.
        tgt_hi: Target maximum L*.

    Returns:
        Remapped L* array clipped to [tgt_lo, tgt_hi].
    """
    src_lo_hard = float(src_lo_hard)
    src_hi_hard = float(src_hi_hard)
    tgt_lo = float(tgt_lo)
    tgt_hi = float(tgt_hi)

    src_span = src_hi_hard - src_lo_hard
    tgt_span = tgt_hi - tgt_lo

    if src_span <= 1e-6:
        return np.full_like(l_star, 0.5 * (tgt_lo + tgt_hi), dtype=np.float64)

    shadow_amt = max(0.0, tgt_lo - src_lo_hard)
    highlight_amt = max(0.0, src_hi_hard - tgt_hi)
    W_s = 2.0 * shadow_amt
    W_h = 2.0 * highlight_amt

    out = np.empty_like(l_star, dtype=np.float64)

    if W_s + W_h <= src_span:
        x_toe_end = src_lo_hard + W_s
        x_shoulder_start = src_hi_hard - W_h

        has_toe = W_s > 1e-9
        has_shoulder = W_h > 1e-9
        toe_mask = (l_star <= x_toe_end) if has_toe else np.zeros_like(l_star, dtype=bool)
        shoulder_mask = (
            (l_star >= x_shoulder_start)
            if has_shoulder
            else np.zeros_like(l_star, dtype=bool)
        )
        mid_mask = ~(toe_mask | shoulder_mask)

        if toe_mask.any():
            u = (l_star[toe_mask] - src_lo_hard) / W_s
            out[toe_mask] = tgt_lo + shadow_amt * (np.exp(_CINEON_K * u) - 1.0) / _CINEON_E

        if mid_mask.any():
            out[mid_mask] = l_star[mid_mask]

        if shoulder_mask.any():
            u = (src_hi_hard - l_star[shoulder_mask]) / W_h
            out[shoulder_mask] = tgt_hi - highlight_amt * (np.exp(_CINEON_K * u) - 1.0) / _CINEON_E
    else:
        total_amt = shadow_amt + highlight_amt
        if total_amt <= 1e-6:
            return np.full_like(l_star, 0.5 * (tgt_lo + tgt_hi), dtype=np.float64)

        ratio_s = shadow_amt / total_amt
        ratio_h = 1.0 - ratio_s
        if ratio_s <= 1e-9:
            u = (src_hi_hard - l_star) / src_span
            out = tgt_hi - tgt_span * (np.exp(_CINEON_K * u) - 1.0) / _CINEON_E
            return np.clip(out, tgt_lo, tgt_hi)
        if ratio_h <= 1e-9:
            u = (l_star - src_lo_hard) / src_span
            out = tgt_lo + tgt_span * (np.exp(_CINEON_K * u) - 1.0) / _CINEON_E
            return np.clip(out, tgt_lo, tgt_hi)
        x_meet = src_lo_hard + src_span * ratio_s

        toe_mask = l_star <= x_meet
        shoulder_mask = l_star > x_meet

        if toe_mask.any():
            u = (l_star[toe_mask] - src_lo_hard) / (src_span * ratio_s)
            out[toe_mask] = tgt_lo + (tgt_span * ratio_s) * (np.exp(_CINEON_K * u) - 1.0) / _CINEON_E

        if shoulder_mask.any():
            u = (src_hi_hard - l_star[shoulder_mask]) / (src_span * ratio_h)
            out[shoulder_mask] = tgt_hi - (tgt_span * ratio_h) * (np.exp(_CINEON_K * u) - 1.0) / _CINEON_E

    return np.clip(out, tgt_lo, tgt_hi)


def apply_auto_dynamic_range(
    rgb: np.ndarray,
    target_l_min: float,
    target_l_max: float,
) -> tuple[np.ndarray, dict]:
    r"""Compress source RGB image to fit the target L* range.
    将输入 RGB 图像的 L\* 范围压缩到目标 L\* 区间。

    Args:
        rgb: (H, W, 3) uint8 RGB image.
        target_l_min: Target minimum L* (in [0, 100]).
        target_l_max: Target maximum L* (in [0, 100]).

    Returns:
        ``(rgb_out, info)`` where ``rgb_out`` is the same shape/dtype as
        ``rgb`` and ``info`` reports whether compression was applied along
        with the source/target L* spans (true L* units).
    """
    info: dict = {
        "applied": False,
        "reason": None,
        "src_l_range": None,
        "tgt_l_range": (float(target_l_min), float(target_l_max)),
    }

    if rgb is None:
        info["reason"] = "no_image"
        return rgb, info
    if rgb.size == 0:
        info["reason"] = "empty_image"
        return rgb, info
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        info["reason"] = "invalid_shape"
        return rgb, info
    if not np.isfinite(target_l_min) or not np.isfinite(target_l_max):
        info["reason"] = "invalid_target"
        return rgb, info
    if target_l_max <= target_l_min:
        info["reason"] = "invalid_target"
        return rgb, info

    rgb_u8 = rgb if rgb.dtype == np.uint8 else np.clip(rgb, 0, 255).astype(np.uint8)
    bgr = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64)
    l_opencv = lab[..., 0]
    # 转换为真实 L\* 单位以便用统一的百分位/端点参数。
    l_star = l_opencv / _OPENCV_L_SCALE

    src_lo_hard = float(np.min(l_star))
    src_hi_hard = float(np.max(l_star))
    info["src_l_range"] = (src_lo_hard, src_hi_hard)

    src_span = src_hi_hard - src_lo_hard
    tgt_span = float(target_l_max - target_l_min)

    if src_span < _MIN_SOURCE_SPAN:
        info["reason"] = "source_span_too_small"
        return rgb_u8, info
    if tgt_span >= src_span - _MIN_COMPRESSION_DELTA:
        info["reason"] = "target_not_narrower"
        return rgb_u8, info

    l_star_new = _remap_l_channel(
        l_star,
        src_lo_hard=src_lo_hard,
        src_hi_hard=src_hi_hard,
        tgt_lo=float(target_l_min),
        tgt_hi=float(target_l_max),
    )

    lab[..., 0] = np.clip(l_star_new * _OPENCV_L_SCALE, 0.0, 255.0)
    lab_u8 = np.clip(lab, 0.0, 255.0).astype(np.uint8)
    bgr_out = cv2.cvtColor(lab_u8, cv2.COLOR_Lab2BGR)
    rgb_out = cv2.cvtColor(bgr_out, cv2.COLOR_BGR2RGB)

    info["applied"] = True
    info["reason"] = "compressed"
    return rgb_out, info


def apply_auto_dynamic_range_to_colors(
    colors: list[tuple[int, int, int]],
    target_l_min: float,
    target_l_max: float,
) -> tuple[list[tuple[int, int, int]], dict]:
    r"""Compress a list of discrete RGB colors to fit the target L\* range.
    将一组离散 RGB 颜色的 L\* 范围压缩到目标 L\* 区间。

    Internally stacks the colors into a ``(1, N, 3)`` uint8 image and
    delegates to :func:`apply_auto_dynamic_range`, then extracts the
    compressed per-color results.

    Args:
        colors: List of ``(R, G, B)`` tuples (each 0–255).
        target_l_min: Target minimum L* (in [0, 100]).
        target_l_max: Target maximum L* (in [0, 100]).

    Returns:
        ``(compressed_colors, info)`` where *compressed_colors* is a list
        of ``(R, G, B)`` tuples and *info* is the same dict returned by
        :func:`apply_auto_dynamic_range`.
    """
    if not colors:
        return list(colors), {"applied": False, "reason": "no_colors"}
    n = len(colors)
    img = np.array([list(colors)], dtype=np.uint8)
    compressed, info = apply_auto_dynamic_range(img, target_l_min, target_l_max)
    if info.get("applied"):
        return [tuple(int(c) for c in compressed[0, i]) for i in range(n)], info
    return list(colors), info
