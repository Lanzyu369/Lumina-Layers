"""Per-region secondary re-quantisation against the material-archive solver.

针对渐变 region 的"二次量化"：对每个被选中的连通区域，独立跑一次 K-Means
色彩量化（只基于该 region 的**原图像**像素，不与全图共用 256 色预算），
然后用管线本来就在使用的只读材料颜色目录 ``lookup()`` 把本地调色板
重新匹配成材料配方，再把结果写回 ``matched_rgb`` 的对应像素。Stage A
传入传统缓存，Lumina Box 则传入候选运行时适配器。

Why this module
===============
The global material-archive preview pipeline quantises the entire source
image to N (default 256) colours and matches each to a material recipe.
When a region has smooth source gradients (e.g. skin shading), the global
quantiser may split those smooth gradients across multiple material hexes,
producing visible "kelp" banding (海带纹).

The gradient-group analyser already identifies the banded regions; the
existing one-click flatten replaces every non-representative hex inside
the group with the group's representative — which kills the banding but
also kills the low-frequency gradient, producing a flat patch.

Secondary re-quantisation takes a different approach: it runs a fresh
K-Means with a dedicated colour budget on **only that region's original
source pixels**, then re-matches those locally-quantised colours through
the same solver. Because the budget is no longer shared with the rest of
the canvas, the local palette concentrates on the region's own colour
range, and the final material matching produces far fewer distinct recipes
inside the region — banding collapses without flattening the gradient.

Public API
----------
:func:`requantize_gradient_regions` is the single public entry point.
All arguments are plain NumPy arrays / typed objects so the function is
worker-safe (picklable) and has no UI or HTTP dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Sequence

import numpy as np

from core.gradient_group_analyzer import REGION_ID_ENCODING_MULTIPLIER
from core.material_color_solver import MaterialParams
from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors

if TYPE_CHECKING:
    from core.material_candidate_cache import MaterialCandidateRuntime


class MaterialColorCatalog(Protocol):
    """Read-only color-to-recipe catalog used by region re-quantisation."""

    def lookup(
        self,
        target_srgb: np.ndarray,
        user_materials: list[MaterialParams],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return matched RGB, recipes, and color differences.

        返回匹配 RGB、配方索引与色差。
        """


@dataclass(frozen=True)
class MaterialCandidateRuntimeCatalog:
    """Explicit adapter from a KM candidate runtime to the region catalog.

    将 KM 候选运行时显式适配为区域重算只读目录，避免把它伪装成仿射缓存。
    """

    runtime: "MaterialCandidateRuntime"

    def lookup(
        self,
        target_srgb: np.ndarray,
        user_materials: list[MaterialParams],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return self.runtime.lookup(target_srgb, user_materials)


# Hard bounds on the user-facing colour budget. The lower bound keeps the
# palette expressive enough to retain obvious gradient steps (and matches
# the UI minimum); the upper bound matches the pipeline's default global
# quantiser ceiling so the local budget never exceeds what the solver
# cache was built for.
# 量化色数的硬性上下界：下限保证调色板能表达基本渐变层级（与 UI 最小值
# 一致）；上限对齐管线全局量化上限，避免超出求解器缓存覆盖范围。
MIN_LOCAL_QUANTIZE_COLORS: int = 12
MAX_LOCAL_QUANTIZE_COLORS: int = 256


def _validate_local_quantize_colors(local_quantize_colors: int) -> int:
    """Return a validated colour-budget integer, raising on out-of-range values.
    校验本地量化色数，超出范围抛 ``ValueError``。
    """
    if not isinstance(local_quantize_colors, (int, np.integer)):
        raise TypeError(
            f"local_quantize_colors must be int, got {type(local_quantize_colors).__name__}"
        )
    value = int(local_quantize_colors)
    if value < MIN_LOCAL_QUANTIZE_COLORS or value > MAX_LOCAL_QUANTIZE_COLORS:
        raise ValueError(
            f"local_quantize_colors must be in "
            f"[{MIN_LOCAL_QUANTIZE_COLORS}, {MAX_LOCAL_QUANTIZE_COLORS}], "
            f"got {value}"
        )
    return value


def _mask_for_target(
    region_id_map: np.ndarray,
    group_index: int,
    region_index: int,
) -> np.ndarray:
    """Build the boolean mask for a single (group, region) target.
    根据 ``(group_index, region_index)`` 从 region_id_map 中取出对应 mask。
    """
    if group_index < 1 or region_index < 1:
        raise ValueError(
            f"group_index and region_index must be >= 1, got "
            f"group={group_index}, region={region_index}"
        )
    encoded = int(group_index) * REGION_ID_ENCODING_MULTIPLIER + int(region_index)
    return region_id_map == np.uint32(encoded)


def requantize_gradient_regions(
    *,
    matched_rgb: np.ndarray,
    original_source_rgb: np.ndarray,
    region_id_map: np.ndarray,
    targets: Sequence[tuple[int, int]],
    materials: Sequence[MaterialParams],
    material_solver_cache: MaterialColorCatalog,
    local_quantize_colors: int,
) -> tuple[np.ndarray, int]:
    """Re-quantise the listed gradient regions in-place-style.
    对选中的渐变区域做二次量化并返回更新后的 ``matched_rgb``。

    For each ``(group_index, region_index)`` in ``targets``:

    1. Extract the original source pixels under the region's mask.
    2. Run K-Means (via :func:`quantize_colors`) with ``local_quantize_colors``
       clusters — this is the "dedicated colour budget" for this region.
    3. Unique-colour-dedup the new quantised palette and push those unique
       colours through the supplied catalog's ``lookup`` to obtain per-colour
       matched-RGB values (the same path the preview pipeline uses).
    4. Write the per-pixel matched-RGB back into the output array at the
       region's coordinates.

    对每个目标 region：取原图该 region 的像素 → 局部 K-Means 量化 →
    lookup 到材料配方的 matched RGB → 写回 ``matched_rgb`` 同坐标。

    Args:
        matched_rgb: ``(H, W, 3)`` uint8 current preview — **not mutated**.
            A copy is returned even when no region was eligible, so callers
            can treat the return value as the new preview unconditionally.
            调用方拿到的返回值总是一份新的 ``matched_rgb``；原数组不会被
            修改，便于 ``_sync_material_matrix_after_rgb_change`` 比较前后。
        original_source_rgb: ``(H, W, 3)`` uint8 pre-quantization source
            RGB at preview resolution. The caller is responsible for loading
            and resizing the source image to match ``matched_rgb``'s shape.
            预览分辨率下的原图 RGB（调用方负责加载 + 缩放匹配）。
        region_id_map: ``(H, W)`` uint32 encoding
            ``group_index * REGION_ID_ENCODING_MULTIPLIER + region_index``
            for every pixel inside a gradient region (0 outside).
        targets: List of ``(group_index, region_index)`` pairs (1-based).
            Duplicate entries are tolerated but processed only once.
        materials: Selected material palette (same list the solver cache
            was loaded against).
        material_solver_cache: Read-only color catalog for the same materials,
            layer count, layer height, and substrate as the preview. Stage A
            supplies ``MaterialSolverCache``; Lumina Box supplies
            ``MaterialCandidateRuntimeCatalog``.
        local_quantize_colors: Per-region k-means cluster count, validated
            against ``[MIN_LOCAL_QUANTIZE_COLORS, MAX_LOCAL_QUANTIZE_COLORS]``.
            If a region has fewer unique source colours than requested, the
            underlying ``quantize_colors`` helper already clamps the cluster
            count.

    Returns:
        ``(new_matched_rgb, rewritten_pixel_count)``. ``new_matched_rgb`` is
        a fresh ``(H, W, 3)`` uint8 array; ``rewritten_pixel_count`` is the
        total number of pixels whose value actually changed after all
        target regions were processed (handy for diagnostic logs and for
        distinguishing "no-op because colours happened to round-trip" from
        "target region was empty").

    Raises:
        TypeError: When array dtypes or shapes are inconsistent.
        ValueError: When ``local_quantize_colors`` is out of range, a
            target index is non-positive, array shapes mismatch, or
            ``targets`` is empty.
    """
    # ---- Basic input validation ----
    local_quantize_colors = _validate_local_quantize_colors(local_quantize_colors)
    if not targets:
        raise ValueError("targets must contain at least one (group, region) pair")

    matched_rgb_arr = np.asarray(matched_rgb)
    original_arr = np.asarray(original_source_rgb)
    region_id_arr = np.asarray(region_id_map)

    if matched_rgb_arr.ndim != 3 or matched_rgb_arr.shape[-1] != 3:
        raise ValueError(
            f"matched_rgb must have shape (H, W, 3); got {matched_rgb_arr.shape}"
        )
    h, w = matched_rgb_arr.shape[:2]
    if original_arr.shape[:2] != (h, w) or original_arr.shape[-1] != 3:
        raise ValueError(
            f"original_source_rgb shape {original_arr.shape} must match "
            f"matched_rgb at (H, W, 3) = ({h}, {w}, 3)"
        )
    if region_id_arr.shape != (h, w):
        raise ValueError(
            f"region_id_map shape {region_id_arr.shape} must match matched_rgb "
            f"(H, W) = ({h}, {w})"
        )
    if matched_rgb_arr.dtype != np.uint8 or original_arr.dtype != np.uint8:
        raise TypeError(
            "matched_rgb and original_source_rgb must be uint8"
        )

    # Deduplicate targets (the caller may re-send the same region under
    # multi-select + single-select mixing) while preserving order so log
    # output stays stable for diagnostics.
    # 去重保持顺序，日志/调试输出稳定。
    seen: set[tuple[int, int]] = set()
    unique_targets: list[tuple[int, int]] = []
    for entry in targets:
        key = (int(entry[0]), int(entry[1]))
        if key in seen:
            continue
        seen.add(key)
        unique_targets.append(key)

    out = matched_rgb_arr.copy()

    for group_idx, region_idx in unique_targets:
        region_mask = _mask_for_target(region_id_arr, group_idx, region_idx)
        if not np.any(region_mask):
            # Silently skip empty targets so a stale multi-selection that
            # references a region which has since been edited away does
            # not fail the whole batch. Callers can cross-check
            # ``rewritten_pixel_count`` if they need to detect this.
            # 目标已失效时跳过，不影响批量里其它 region。
            continue

        ys, xs = np.nonzero(region_mask)
        region_pixels = original_arr[ys, xs]  # (N, 3) uint8

        # Local K-Means on the region's source pixels. We reshape to
        # ``(N, 1, 3)`` because ``quantize_colors`` expects an image-shaped
        # array; k-means itself only cares about the unordered pixel set.
        # 把像素排成 (N, 1, 3) 的"伪图像"给到 quantize_colors；k-means 仅依赖
        # 像素集合，不依赖空间顺序。
        patch = region_pixels.reshape(-1, 1, 3)
        locally_quantised = quantize_colors(
            patch, local_quantize_colors
        ).reshape(-1, 3)

        # Unique-colour dedup → solver lookup → broadcast per pixel.
        unique_colours, inverse = np.unique(
            locally_quantised, axis=0, return_inverse=True
        )
        matched_unique, _recipes, _delta = material_solver_cache.lookup(
            unique_colours, list(materials)
        )
        matched_pixels = np.asarray(matched_unique, dtype=np.uint8)[inverse]

        out[ys, xs] = matched_pixels

    rewritten_pixel_count = int(np.any(out != matched_rgb_arr, axis=-1).sum())
    return out, rewritten_pixel_count
