"""Exact CIEDE2000 scalar scoring shared by fixed and dynamic material search."""

from __future__ import annotations

import math

import numpy as np

try:
    from numba import njit, prange
    from numba.core.errors import NumbaError

    _NUMBA_AVAILABLE = True
except ImportError:
    _NUMBA_AVAILABLE = False

    def njit(*args, **kwargs):
        return lambda function: function

    prange = range


def _delta_e00_scalar_components(
    lightness1: float,
    a1: float,
    b1: float,
    lightness2: float,
    a2: float,
    b2: float,
) -> float:
    chroma1 = math.sqrt(a1 * a1 + b1 * b1)
    chroma2 = math.sqrt(a2 * a2 + b2 * b2)
    mean_chroma = (chroma1 + chroma2) / 2.0
    mean_chroma_seventh = mean_chroma**7
    compensation = 0.5 * (
        1.0
        - math.sqrt(
            mean_chroma_seventh / (mean_chroma_seventh + 25.0**7)
        )
    )

    adjusted_a1 = a1 * (1.0 + compensation)
    adjusted_a2 = a2 * (1.0 + compensation)
    adjusted_chroma1 = math.sqrt(adjusted_a1**2 + b1**2)
    adjusted_chroma2 = math.sqrt(adjusted_a2**2 + b2**2)
    hue1 = math.degrees(math.atan2(b1, adjusted_a1)) % 360.0
    hue2 = math.degrees(math.atan2(b2, adjusted_a2)) % 360.0

    delta_lightness = lightness2 - lightness1
    delta_chroma = adjusted_chroma2 - adjusted_chroma1
    if adjusted_chroma1 * adjusted_chroma2 == 0.0:
        delta_hue_degrees = 0.0
    elif abs(hue2 - hue1) <= 180.0:
        delta_hue_degrees = hue2 - hue1
    elif hue2 - hue1 > 180.0:
        delta_hue_degrees = hue2 - hue1 - 360.0
    else:
        delta_hue_degrees = hue2 - hue1 + 360.0
    delta_hue = (
        2.0
        * math.sqrt(adjusted_chroma1 * adjusted_chroma2)
        * math.sin(math.radians(delta_hue_degrees / 2.0))
    )

    mean_lightness = (lightness1 + lightness2) / 2.0
    mean_adjusted_chroma = (adjusted_chroma1 + adjusted_chroma2) / 2.0
    if adjusted_chroma1 * adjusted_chroma2 == 0.0:
        mean_hue = hue1 + hue2
    elif abs(hue1 - hue2) <= 180.0:
        mean_hue = (hue1 + hue2) / 2.0
    elif hue1 + hue2 < 360.0:
        mean_hue = (hue1 + hue2 + 360.0) / 2.0
    else:
        mean_hue = (hue1 + hue2 - 360.0) / 2.0

    hue_rotation = (
        1.0
        - 0.17 * math.cos(math.radians(mean_hue - 30.0))
        + 0.24 * math.cos(math.radians(2.0 * mean_hue))
        + 0.32 * math.cos(math.radians(3.0 * mean_hue + 6.0))
        - 0.20 * math.cos(math.radians(4.0 * mean_hue - 63.0))
    )
    lightness_scale = 1.0 + (
        0.015 * (mean_lightness - 50.0) ** 2
        / math.sqrt(20.0 + (mean_lightness - 50.0) ** 2)
    )
    chroma_scale = 1.0 + 0.045 * mean_adjusted_chroma
    hue_scale = 1.0 + 0.015 * mean_adjusted_chroma * hue_rotation

    mean_adjusted_chroma_seventh = mean_adjusted_chroma**7
    rotation_chroma = 2.0 * math.sqrt(
        mean_adjusted_chroma_seventh
        / (mean_adjusted_chroma_seventh + 25.0**7)
    )
    rotation_angle = 30.0 * math.exp(-((mean_hue - 275.0) / 25.0) ** 2)
    rotation_term = -math.sin(math.radians(2.0 * rotation_angle)) * rotation_chroma

    lightness_term = delta_lightness / lightness_scale
    chroma_term = delta_chroma / chroma_scale
    hue_term = delta_hue / hue_scale
    return math.sqrt(
        lightness_term**2
        + chroma_term**2
        + hue_term**2
        + rotation_term * chroma_term * hue_term
    )


_delta_e00_numba_components = njit(cache=True, fastmath=False)(
    _delta_e00_scalar_components
)


def _search_fixed_kernel(
    targets: np.ndarray, candidates: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    indices = np.full(len(targets), -1, dtype=np.int64)
    values = np.full(len(targets), np.inf, dtype=np.float64)
    for row in prange(len(targets)):
        lightness, a, b = targets[row, 0], targets[row, 1], targets[row, 2]
        best_index, best_value = -1, np.inf
        for index in range(len(candidates)):
            candidate_l = candidates[index, 0]
            mean_l = (lightness + candidate_l) / 2.
            offset_squared = (mean_l - 50.) ** 2
            lightness_scale = 1. + .015 * offset_squared / math.sqrt(20. + offset_squared)
            # The chroma/hue quadratic is nonnegative, so this is a safe
            # lower bound on CIEDE2000. Preserve roundoff-close candidates.
            if abs(candidate_l - lightness) / lightness_scale > best_value + 1e-12:
                continue
            value = _delta_e00_numba_components(
                lightness, a, b, candidate_l, candidates[index, 1], candidates[index, 2],
            )
            if value < best_value:
                best_index, best_value = index, value
                if value == 0.:
                    break
        indices[row], values[row] = best_index, best_value
    return indices, values


_search_fixed_kernel = njit(cache=True, parallel=True, fastmath=False)(_search_fixed_kernel)


def try_exact_ciede2000_minima(
    targets: np.ndarray, candidates: np.ndarray,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Try compiled exact scoring with bounded task-aware CPU parallelism.
    尝试使用受任务并行预算约束的编译计算进行精确色差匹配。

    Args:
        targets: Float64 target Lab rows. Float64 目标 Lab 行。
        candidates: Float64 candidate Lab rows. Float64 候选 Lab 行。

    Returns:
        First minimum indices and distances, or None for NumPy fallback.
        最小色差首次出现的索引与距离；无法使用时返回 None，交由 NumPy 计算。
    """
    if not _NUMBA_AVAILABLE:
        return None
    from numba import config, get_num_threads, set_num_threads
    from core.task_parallelism import resolve_task_parallelism

    previous_threads = get_num_threads()
    workers = resolve_task_parallelism(
        "raster", work_items=len(targets), hard_max_workers=16,
        work_units=len(targets) * len(candidates),
        work_units_per_worker=100_000,
    )
    try:
        set_num_threads(min(workers, config.NUMBA_NUM_THREADS))
        return _search_fixed_kernel(targets, candidates)
    except (NumbaError, RuntimeError, ValueError):
        return None
    finally:
        set_num_threads(previous_threads)
