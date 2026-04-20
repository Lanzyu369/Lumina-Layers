"""Material-solver disk cache — 64³ Lab-grid bucketed recipe lookup.
耗材求解器磁盘缓存 —— 64³ Lab 网格分桶的配方查询。

This module provides a persistent, per-palette cache of optimal Beer-Lambert
recipes, built by enumerating every ``M**N`` ordered layer sequence, bucketing
each combination's output color into a 3-D Lab grid, and keeping the
bucket-center-closest recipe per occupied cell.

Runtime lookup: given target sRGB colors, a KD-Tree over occupied bucket
centers finds the nearest stored recipe. Worst-case ΔE(target, achieved) is
bounded by a cell's half-diagonal; typical error is ~1-3 ΔE for the 64³ default.

On-disk layout (one ``.npz`` + one ``.meta.json`` sidecar per cache entry):

    <cache_root>/
        <palette_hash>-N<count>-t<height_str>-<substrate>.npz
        <palette_hash>-N<count>-t<height_str>-<substrate>.meta.json

Filename components:
    palette_hash       — 16-char sha256 prefix of the canonically-ordered palette
    N<count>           — zero-padded layer count (e.g. ``N10``)
    t<height_str>      — layer height with dots replaced by underscores (e.g. ``t0_08``)
    <substrate>        — ``"white"`` or ``"black"``

Public API:
    - ``MaterialSolverCache``          — loaded cache with ``lookup()``
    - ``build_material_solver_cache``  — enumerate + bucket + return in-memory cache
    - ``save_material_solver_cache``   — persist to disk
    - ``load_material_solver_cache``   — load from disk
    - ``cache_file_path``              — canonical on-disk path for parameters
    - ``default_cache_directory``      — where caches live (``MATERIALS_DIR/_solver_cache``)
    - ``fingerprint_palette``          — stable hash of material parameters
    - ``list_cached_entries``          — enumerate cached combinations
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy.spatial import cKDTree

from config import MATERIALS_DIR
from core.material_color_solver import (
    ALLOWED_LAYER_HEIGHTS_MM,
    DEFAULT_SUGGEST_MIN_SPACING,
    DEFAULT_SUGGEST_TOP_K,
    MAX_LAYER_COUNT,
    MIN_LAYER_COUNT,
    ColorSuggestion,
    MaterialParams,
    _compute_material_affines,
    _enumerate_cumulative_affines,
    _greedy_lab_spacing_dedup,
    linear_to_srgb_uint8,
    rgb_to_lab,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants & schema
# ---------------------------------------------------------------------------

DEFAULT_GRID_RESOLUTION: int = 64
"""Lab grid cells per axis. Total cell count is ``grid_resolution ** 3``.
Default 64 gives ~4 MB raw cache with worst-case lookup ΔE ≤ cell half-diagonal
(~4 ΔE). Higher resolutions trade disk/build cost for lower ΔE."""

CACHE_SCHEMA_VERSION: str = "1.0"
CACHE_SUBDIR: str = "_solver_cache"

_FINGERPRINT_DECIMALS: int = 6
_HASH_PREFIX_LEN: int = 16

_CHUNK_TARGET_BYTES: int = 64 * 1024 * 1024
"""Per-chunk memory budget for the build pass (final linear RGB block).
64 MiB chunks keep peak memory comfortable on 8 GB-class machines."""


# ---------------------------------------------------------------------------
# Palette fingerprinting
# ---------------------------------------------------------------------------


def _material_fingerprint(mat: MaterialParams) -> str:
    """Stable content hash of a material's Beer-Lambert parameters.
    耗材 Beer-Lambert 参数的稳定内容哈希。

    Rounds each float to :data:`_FINGERPRINT_DECIMALS` decimals so tiny
    floating-point jitter across fit runs does not invalidate caches.
    """
    payload = {
        "E": [round(float(v), _FINGERPRINT_DECIMALS) for v in mat.E.tolist()],
        "k": [round(float(v), _FINGERPRINT_DECIMALS) for v in mat.k.tolist()],
        "C0_white": [
            round(float(v), _FINGERPRINT_DECIMALS) for v in mat.C0_white.tolist()
        ],
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def fingerprint_palette(materials: list[MaterialParams]) -> str:
    """Compute a canonical 16-char fingerprint for a palette.
    计算调色板的 16 字符规范指纹。

    The fingerprint is independent of the caller's material ordering: materials
    are sorted by their individual fingerprint before the palette hash is
    computed. Callers who rebind recipe columns must use the canonical order
    returned by :func:`canonical_palette_order`.
    """
    if not materials:
        raise ValueError("Cannot fingerprint an empty palette")
    per_material = sorted(_material_fingerprint(m) for m in materials)
    palette_blob = "|".join(per_material)
    return hashlib.sha256(palette_blob.encode("utf-8")).hexdigest()[:_HASH_PREFIX_LEN]


def canonical_palette_order(materials: list[MaterialParams]) -> list[int]:
    """Return indices such that ``[materials[i] for i in order]`` is canonical.
    返回将耗材列表重排为规范顺序的索引列表。
    """
    fingerprints = [_material_fingerprint(m) for m in materials]
    return sorted(range(len(materials)), key=lambda i: fingerprints[i])


# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------


def default_cache_directory(cache_root: str | Path | None = None) -> Path:
    """Return the default cache directory.
    返回默认缓存目录。

    When ``cache_root`` is ``None`` the cache lives under
    ``<MATERIALS_DIR>/_solver_cache/``. Callers (e.g. tests) can override by
    passing an explicit path.
    """
    root = Path(cache_root) if cache_root is not None else Path(MATERIALS_DIR)
    return root / CACHE_SUBDIR


def _height_to_str(layer_height_mm: float) -> str:
    return f"{float(layer_height_mm):g}".replace(".", "_")


def _cache_file_stem(
    palette_hash: str,
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
) -> str:
    return (
        f"{palette_hash}-N{int(layer_count):02d}"
        f"-t{_height_to_str(layer_height_mm)}-{substrate}"
    )


def cache_file_path(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    *,
    cache_root: str | Path | None = None,
) -> Path:
    """Resolve the canonical ``.npz`` path for the given cache parameters.
    返回指定缓存参数对应的规范 ``.npz`` 路径。
    """
    palette_hash = fingerprint_palette(materials)
    stem = _cache_file_stem(palette_hash, layer_count, layer_height_mm, substrate)
    return default_cache_directory(cache_root) / f"{stem}.npz"


def _cache_meta_path_for(npz_path: Path) -> Path:
    """Return the ``.meta.json`` sidecar path next to ``npz_path``."""
    return npz_path.with_name(npz_path.stem + ".meta.json")


# ---------------------------------------------------------------------------
# Cache data class
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MaterialSolverCache:
    """Loaded 64³ Lab-grid material-recipe cache.
    已加载的 64³ Lab 网格耗材配方缓存。

    Attributes:
        lab_centers: (K, 3) float32 Lab bucket centers that were reached by
            at least one enumerated recipe. (被枚举触达的 Lab 网格中心)
        recipes: (K, N) uint8 best recipe per reached bucket, with column 0
            as the bottom layer. Indices refer to the canonically-ordered
            palette; callers must rebind to their own order via
            :meth:`reindex_to_user_order`. (每桶最优配方)
        achieved_srgb: (K, 3) uint8 predicted sRGB when the stored recipe is
            applied, used to compute ΔE to targets at lookup time.
            (配方实际达成的 sRGB)
        center_delta_e: (K,) float32 ΔE between bucket center and the stored
            recipe's achieved Lab. Diagnostic only — lookup ΔE is recomputed
            against the caller's target. (配方与桶心的 ΔE，仅诊断用)
        metadata: JSON-serialisable dictionary with palette fingerprint,
            parameters, build stats, and timestamps. (元数据)
    """

    lab_centers: np.ndarray
    recipes: np.ndarray
    achieved_srgb: np.ndarray
    center_delta_e: np.ndarray
    metadata: dict[str, Any]

    @property
    def layer_count(self) -> int:
        return int(self.metadata["layer_count"])

    @property
    def layer_height_mm(self) -> float:
        return float(self.metadata["layer_height_mm"])

    @property
    def substrate(self) -> str:
        return str(self.metadata["substrate"])

    @property
    def palette_hash(self) -> str:
        return str(self.metadata["palette_hash"])

    @property
    def grid_resolution(self) -> int:
        return int(self.metadata.get("grid_resolution", DEFAULT_GRID_RESOLUTION))

    @property
    def valid_cell_count(self) -> int:
        return int(self.lab_centers.shape[0])

    def reindex_to_user_order(self, user_order: list[int]) -> np.ndarray:
        """Remap ``recipes`` (in canonical order) back to the caller's order.
        将规范顺序的 ``recipes`` 重映射回调用方的顺序。

        ``user_order`` is the list produced by
        :func:`canonical_palette_order(user_materials)`: for each canonical
        position ``c``, ``user_order[c]`` is the index into the caller's
        material list whose material equals the cache's canonical material
        at position ``c``.  The rebinding is therefore
        ``user_recipe = user_order[stored_canonical_recipe]``.
        """
        mapping = np.asarray(user_order, dtype=np.int32)
        return mapping[self.recipes]

    def lookup(
        self,
        target_srgb: np.ndarray,
        user_materials: list[MaterialParams],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Find the best stored recipe for each target color.
        为每个目标颜色查找最优存档配方。

        The cache quantizes the exhaustive solver output onto a fixed Lab grid
        and keeps one representative recipe per occupied bucket. A naive
        nearest-bucket-center lookup can be suboptimal because a bucket's
        representative may not be the closest achievable colour to a specific
        target inside that bucket. To mitigate this, the lookup queries up to
        ``min(64, grid_resolution, valid_cell_count)`` nearest buckets per
        target, rehydrates their stored ``achieved_srgb``, converts those back
        to Lab, and selects the candidate with the smallest actual CIE76 ΔE to
        the target. This keeps the O(1)-style query cost while greatly reducing
        bucket-collision error when many recipes land in the same cell.

        缓存在构建时将穷举求解结果压缩到固定 Lab 网格，每个被占用的分桶只保留
        一条代表配方。直接取最近桶中心可能并不最优，因为该桶的代表色与桶内某
        个目标色之间仍可能有较大偏差。为缓解这种近似误差，本方法一次性查询
        ``min(64, grid_resolution, valid_cell_count)`` 个最近分桶，对各自存档
        的 ``achieved_srgb`` 重新计算相对目标色的 CIE76 ΔE，并选择 ΔE 最小的
        候选，在保持近常数级查询成本的同时明显降低桶内碰撞误差。

        Args:
            target_srgb (np.ndarray): ``(C, 3)`` uint8 unique target colours in
                sRGB. (目标 sRGB 唯一色)
            user_materials (list[MaterialParams]): The caller's ordered material
                list. Used to re-bind recipe indices from canonical storage
                order to the caller's order. (调用方耗材顺序)

        Returns:
            tuple[np.ndarray, np.ndarray, np.ndarray]: A triple of
                ``(matched_rgb, recipes_user_order, delta_e)``.

                - ``matched_rgb`` (``(C, 3)`` uint8): predicted sRGB for each
                  target, taken from the re-ranked best candidate bucket.
                - ``recipes_user_order`` (``(C, N)`` int32): recipes rewritten
                  in the caller's material order.
                - ``delta_e`` (``(C,)`` float64): CIE76 ΔE between target and
                  the selected achieved colour (not the bucket centre).

        Raises:
            ValueError: If ``target_srgb`` is not shaped ``(C, 3)``, the
                caller's palette fingerprint does not match the cache, or the
                cache contains no populated cells.
        """
        if target_srgb.ndim != 2 or target_srgb.shape[1] != 3:
            raise ValueError("target_srgb must be shaped (C, 3)")
        if target_srgb.shape[0] == 0:
            N = self.layer_count
            return (
                np.zeros((0, 3), dtype=np.uint8),
                np.zeros((0, N), dtype=np.int32),
                np.zeros((0,), dtype=np.float64),
            )
        if int(self.valid_cell_count) == 0:
            raise ValueError(
                "MaterialSolverCache has no populated cells; rebuild the cache "
                "before lookup. (缓存不含任何有效分桶，请先重建缓存)"
            )
        # Validate user palette fingerprint matches the cache.
        user_fp = fingerprint_palette(user_materials)
        if user_fp != self.palette_hash:
            raise ValueError(
                f"User palette fingerprint {user_fp} does not match cached "
                f"palette {self.palette_hash}"
            )
        # Build KDTree over bucket centers (lazily; expected small cost).
        tree = cKDTree(self.lab_centers.astype(np.float64))
        target_lab = rgb_to_lab(target_srgb).astype(np.float64)
        query_k = min(64, int(self.grid_resolution), int(self.valid_cell_count))
        _, nearest_idx = tree.query(target_lab, k=query_k)
        nearest_idx = np.asarray(nearest_idx)
        if nearest_idx.ndim == 1:
            # cKDTree squeezes the last dim when k == 1.
            nearest_idx = nearest_idx.reshape(-1, 1)
        candidate_rgb = self.achieved_srgb[nearest_idx]
        candidate_lab = rgb_to_lab(candidate_rgb.reshape(-1, 3)).astype(np.float64)
        candidate_lab = candidate_lab.reshape(target_lab.shape[0], nearest_idx.shape[1], 3)
        candidate_delta_e = np.linalg.norm(
            candidate_lab - target_lab[:, None, :], axis=2
        )
        best_pos = np.argmin(candidate_delta_e, axis=1)
        row_index = np.arange(target_lab.shape[0], dtype=np.int64)
        best_rows = nearest_idx[row_index, best_pos]
        matched_rgb = self.achieved_srgb[best_rows]
        # Re-bind recipe material indices from canonical to caller order.
        user_order = canonical_palette_order(user_materials)
        canonical_recipes = self.recipes[best_rows]
        mapping = np.asarray(user_order, dtype=np.int32)
        recipes_user_order = mapping[canonical_recipes].astype(np.int32)
        # ΔE already measured against the actual achieved colour (not the bucket centre).
        delta_e = candidate_delta_e[row_index, best_pos]
        return matched_rgb, recipes_user_order, delta_e

    def lookup_top_k(
        self,
        target_srgb: np.ndarray,
        user_materials: list[MaterialParams],
        *,
        top_k: int = DEFAULT_SUGGEST_TOP_K,
        min_spacing: float = DEFAULT_SUGGEST_MIN_SPACING,
    ) -> list[ColorSuggestion]:
        """Return the ``top_k`` cached recipes closest in Lab to one target.
        返回 Lab 空间中最接近单一目标色的 ``top_k`` 条缓存配方。

        The cache stores one recipe per reached bucket centre, so the entire
        enumerated gamut is already deduplicated at the grid resolution. A
        ``cKDTree`` query picks the nearest-cell neighbours, then a greedy
        ``min_spacing`` filter enforces perceptually distinct suggestions.

        Args:
            target_srgb: (3,) uint8 target colour in sRGB. (目标 sRGB)
            user_materials: Caller's ordered material list (for recipe
                rebinding). (调用方耗材顺序)
            top_k: Maximum number of suggestions to return. (返回候选数上限)
            min_spacing: Minimum Lab ΔE between returned candidates.
                (候选间最小 Lab ΔE)

        Returns:
            List of :class:`ColorSuggestion` ordered by ΔE ascending. Recipe
            indices refer to ``user_materials`` (not the canonical cache order).
            (按 ΔE 升序的候选列表；``recipe`` 使用调用方耗材索引)

        Raises:
            ValueError: ``target_srgb`` shape is wrong or ``top_k <= 0`` or
                the caller's palette fingerprint does not match the cache.
        """
        target_srgb = np.asarray(target_srgb, dtype=np.uint8)
        if target_srgb.shape != (3,):
            raise ValueError(
                f"target_srgb must be shaped (3,), got {target_srgb.shape}"
            )
        if top_k <= 0:
            raise ValueError(f"top_k must be positive, got {top_k}")
        if min_spacing < 0.0:
            raise ValueError(f"min_spacing must be non-negative, got {min_spacing}")
        user_fp = fingerprint_palette(user_materials)
        if user_fp != self.palette_hash:
            raise ValueError(
                f"User palette fingerprint {user_fp} does not match cached "
                f"palette {self.palette_hash}"
            )
        if self.lab_centers.shape[0] == 0:
            return []

        target_lab = rgb_to_lab(target_srgb.reshape(1, 3))[0].astype(np.float64)
        oversample = max(1, int(top_k) * 4)
        query_k = min(oversample, int(self.lab_centers.shape[0]))
        tree = cKDTree(self.lab_centers.astype(np.float64))
        # ``cKDTree.query`` returns ``distances, indices``; when ``k == 1`` the
        # arrays are 0-D scalars so we always normalise to 1-D.
        # k=1 时返回标量，这里统一成一维数组便于下游处理。
        _, nearest_idx = tree.query(target_lab, k=query_k)
        nearest_idx = np.atleast_1d(nearest_idx).astype(np.int64)

        nearest_lab = self.lab_centers[nearest_idx].astype(np.float64)
        nearest_srgb = self.achieved_srgb[nearest_idx]
        # Recompute ΔE against the achieved (not the bucket centre) for an
        # accurate target-to-prediction error.
        matched_lab = rgb_to_lab(nearest_srgb).astype(np.float64)
        delta_e = np.linalg.norm(matched_lab - target_lab, axis=1)

        # Sort ascending by ΔE before the greedy spacing filter.
        sort_order = np.argsort(delta_e, kind="stable")
        sorted_lab = matched_lab[sort_order]
        sorted_srgb = nearest_srgb[sort_order]
        sorted_de = delta_e[sort_order]
        sorted_cache_rows = nearest_idx[sort_order]

        kept_idx = _greedy_lab_spacing_dedup(
            sorted_lab, min_spacing=min_spacing, limit=int(top_k)
        )
        if kept_idx.size == 0:
            return []

        user_order = canonical_palette_order(user_materials)
        mapping = np.asarray(user_order, dtype=np.int32)
        return [
            ColorSuggestion(
                matched_rgb=sorted_srgb[i].copy(),
                recipe=mapping[self.recipes[sorted_cache_rows[i]]].astype(
                    np.int32, copy=True
                ),
                delta_e=float(sorted_de[i]),
            )
            for i in kept_idx
        ]


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def _lab_to_bucket_index(
    lab: np.ndarray,
    grid_resolution: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Map an ``(N, 3)`` Lab array to (flat_bucket_idx, bucket_center).
    将 ``(N, 3)`` 的 Lab 数组映射为 (桶索引, 桶心 Lab)。
    """
    # L in [0, 100], a/b in [-128, 127]. Clip to valid range before binning.
    L = np.clip(lab[:, 0], 0.0, 100.0)
    a = np.clip(lab[:, 1], -128.0, 127.0)
    b = np.clip(lab[:, 2], -128.0, 127.0)
    # Quantize each axis into [0, grid_resolution - 1].
    L_step = 100.0 / grid_resolution
    ab_step = 256.0 / grid_resolution
    L_idx = np.clip((L / L_step).astype(np.int32), 0, grid_resolution - 1)
    a_idx = np.clip(((a + 128.0) / ab_step).astype(np.int32), 0, grid_resolution - 1)
    b_idx = np.clip(((b + 128.0) / ab_step).astype(np.int32), 0, grid_resolution - 1)
    flat_idx = (
        L_idx * (grid_resolution * grid_resolution)
        + a_idx * grid_resolution
        + b_idx
    )
    # Bucket center = lower bound + half-step (so the bucket's representative
    # point is at the cell's geometric centre).
    center = np.empty_like(lab, dtype=np.float64)
    center[:, 0] = L_idx * L_step + L_step * 0.5
    center[:, 1] = a_idx * ab_step + ab_step * 0.5 - 128.0
    center[:, 2] = b_idx * ab_step + ab_step * 0.5 - 128.0
    return flat_idx, center


def _groupby_argmin(
    bucket_idx: np.ndarray,
    delta: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-bucket argmin over (bucket_idx, delta) without pandas.
    不依赖 pandas 的分桶 argmin。

    Returns (unique_buckets, row_indices_into_original_arrays) where
    ``row_indices[i]`` is the index of the minimum-delta row for
    ``unique_buckets[i]``.
    """
    # Lexsort: primary bucket (ascending), secondary delta (ascending).
    # The first occurrence of each bucket in the sorted order has the min delta.
    order = np.lexsort((delta, bucket_idx))
    sorted_buckets = bucket_idx[order]
    # First-occurrence mask: True where bucket differs from previous.
    if sorted_buckets.size == 0:
        return (
            np.zeros(0, dtype=bucket_idx.dtype),
            np.zeros(0, dtype=np.int64),
        )
    first_mask = np.empty(sorted_buckets.shape, dtype=bool)
    first_mask[0] = True
    np.not_equal(sorted_buckets[1:], sorted_buckets[:-1], out=first_mask[1:])
    unique_buckets = sorted_buckets[first_mask]
    row_indices = order[first_mask]
    return unique_buckets, row_indices


def build_material_solver_cache(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    grid_resolution: int = DEFAULT_GRID_RESOLUTION,
    progress_callback: Callable[[float, dict[str, Any]], None] | None = None,
) -> MaterialSolverCache:
    """Exhaustively enumerate every recipe and build a bucketed lookup cache.
    穷举所有配方并构建分桶查询缓存。

    The build pass uses the MITM decomposition from
    :mod:`core.material_color_solver`: the top and bottom halves are
    enumerated into cumulative-affine tables once, then combined chunk-by-chunk
    to produce every ``M**N`` final color. Each chunk bucketizes outputs into a
    ``grid_resolution ** 3`` Lab grid and keeps the recipe whose output Lab is
    closest to its cell centre.

    Args:
        materials: Palette used for enumeration. The solver internally reorders
            to canonical (fingerprint-sorted) order and stores recipes in that
            order; :meth:`MaterialSolverCache.lookup` rebinds indices to the
            caller's order at query time. (枚举用耗材列表)
        layer_count: Number of layers (5-10). (层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底)
        grid_resolution: Lab grid cells per axis. Default 64.
            (Lab 网格分辨率)
        progress_callback: Optional callback invoked as
            ``cb(progress_fraction, info)`` where ``progress_fraction`` is in
            ``[0, 1]`` and ``info`` carries build stats. (进度回调)

    Returns:
        MaterialSolverCache with populated arrays and metadata.
    """
    if layer_count < MIN_LAYER_COUNT or layer_count > MAX_LAYER_COUNT:
        raise ValueError(
            f"layer_count must be {MIN_LAYER_COUNT}-{MAX_LAYER_COUNT}, got {layer_count}"
        )
    if not materials:
        raise ValueError("At least one material must be provided")
    if layer_height_mm not in ALLOWED_LAYER_HEIGHTS_MM:
        raise ValueError(
            f"layer_height_mm must be one of {ALLOWED_LAYER_HEIGHTS_MM}, got {layer_height_mm}"
        )
    if substrate not in ("white", "black"):
        raise ValueError(f"substrate must be 'white' or 'black', got {substrate!r}")
    if grid_resolution < 8 or grid_resolution > 256:
        raise ValueError(
            f"grid_resolution must be in [8, 256], got {grid_resolution}"
        )

    start_time = time.time()

    # Re-order materials to canonical order for storage.
    canonical_order = canonical_palette_order(materials)
    canonical_materials = [materials[i] for i in canonical_order]
    palette_hash = fingerprint_palette(canonical_materials)

    affines = _compute_material_affines(canonical_materials, layer_height_mm)
    substrate_linear = (
        np.zeros(3, dtype=np.float64)
        if substrate == "black"
        else np.ones(3, dtype=np.float64)
    )

    top_depth = (layer_count + 1) // 2
    bottom_depth = layer_count - top_depth

    # Enumerate halves.
    bot_alpha, bot_beta, bot_recipes = _enumerate_cumulative_affines(
        affines, bottom_depth
    )
    bot_colors = bot_alpha * substrate_linear + bot_beta          # (K_bot, 3)
    top_alpha, top_beta, top_recipes = _enumerate_cumulative_affines(
        affines, top_depth
    )
    K_bot = bot_colors.shape[0]
    K_top = top_alpha.shape[0]
    total_combinations = int(K_top) * int(K_bot)

    # Sparse per-bucket state. Use dict mapping flat_bucket_idx -> (delta, rec_row).
    total_buckets = grid_resolution ** 3
    # Dense arrays for fastest updates — 262K * (few bytes) is tiny at 64³.
    best_delta = np.full(total_buckets, np.inf, dtype=np.float64)
    best_recipes = np.zeros((total_buckets, layer_count), dtype=np.int8)
    best_achieved_lab = np.zeros((total_buckets, 3), dtype=np.float64)
    best_achieved_srgb = np.zeros((total_buckets, 3), dtype=np.uint8)
    best_center_lab = np.zeros((total_buckets, 3), dtype=np.float64)

    # Chunk tops so each (chunk × K_bot × 24B) fits the memory budget.
    per_row_bytes = K_bot * 24
    chunk_size = max(1, min(K_top, _CHUNK_TARGET_BYTES // max(per_row_bytes, 1)))
    num_chunks = (K_top + chunk_size - 1) // chunk_size

    for chunk_idx, chunk_start in enumerate(range(0, K_top, chunk_size)):
        chunk_end = min(chunk_start + chunk_size, K_top)
        sub = chunk_end - chunk_start
        chunk_alpha = top_alpha[chunk_start:chunk_end]             # (sub, 3)
        chunk_beta = top_beta[chunk_start:chunk_end]               # (sub, 3)
        chunk_recipes_top = top_recipes[chunk_start:chunk_end]     # (sub, top_depth)

        # final_linear: (sub, K_bot, 3).
        final_linear = (
            chunk_alpha[:, None, :] * bot_colors[None, :, :]
            + chunk_beta[:, None, :]
        )
        flat_linear = final_linear.reshape(-1, 3)                  # (sub*K_bot, 3)
        flat_srgb = linear_to_srgb_uint8(flat_linear)
        flat_lab = rgb_to_lab(flat_srgb)                           # (sub*K_bot, 3)

        bucket_idx, bucket_center = _lab_to_bucket_index(flat_lab, grid_resolution)
        delta_to_center = np.linalg.norm(flat_lab - bucket_center, axis=1)

        # Find min-delta row per bucket within this chunk.
        unique_buckets, row_indices = _groupby_argmin(bucket_idx, delta_to_center)
        if unique_buckets.size == 0:
            continue

        chunk_best_deltas = delta_to_center[row_indices]
        chunk_best_lab = flat_lab[row_indices]
        chunk_best_srgb = flat_srgb[row_indices]
        chunk_best_centers = bucket_center[row_indices]

        # Rebuild recipes for these rows. Each row index is a flat index into
        # (sub, K_bot): top_i = row // K_bot, bot_i = row % K_bot.
        top_idx_in_chunk = row_indices // K_bot
        bot_idx_in_chunk = row_indices % K_bot
        chunk_bot_recipes = bot_recipes[bot_idx_in_chunk]          # (K_hit, bottom_depth)
        chunk_top_recipes = chunk_recipes_top[top_idx_in_chunk]    # (K_hit, top_depth)

        # Compare to global best, update where improved.
        improved = chunk_best_deltas < best_delta[unique_buckets]
        if not np.any(improved):
            continue
        idx_improved = unique_buckets[improved]
        best_delta[idx_improved] = chunk_best_deltas[improved]
        best_achieved_lab[idx_improved] = chunk_best_lab[improved]
        best_achieved_srgb[idx_improved] = chunk_best_srgb[improved]
        best_center_lab[idx_improved] = chunk_best_centers[improved]
        if bottom_depth > 0:
            best_recipes[idx_improved, :bottom_depth] = chunk_bot_recipes[improved]
        if top_depth > 0:
            best_recipes[idx_improved, bottom_depth:] = chunk_top_recipes[improved]

        if progress_callback is not None:
            fraction = (chunk_idx + 1) / max(num_chunks, 1)
            progress_callback(
                fraction,
                {
                    "chunk_index": chunk_idx + 1,
                    "total_chunks": num_chunks,
                    "valid_bucket_count": int(np.sum(np.isfinite(best_delta))),
                    "elapsed_seconds": time.time() - start_time,
                },
            )

    # Materialize sparse output: only valid (reached) buckets.
    valid_mask = np.isfinite(best_delta)
    lab_centers = best_center_lab[valid_mask].astype(np.float32)
    recipes = best_recipes[valid_mask]
    achieved_srgb = best_achieved_srgb[valid_mask]
    center_delta_e = best_delta[valid_mask].astype(np.float32)

    valid_count = int(lab_centers.shape[0])
    build_time = time.time() - start_time

    metadata = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "palette_hash": palette_hash,
        "canonical_materials": [
            {
                "name": m.name,
                "directory_name": m.directory_name,
                "fingerprint": _material_fingerprint(m),
                "E": [round(float(v), _FINGERPRINT_DECIMALS) for v in m.E.tolist()],
                "k": [round(float(v), _FINGERPRINT_DECIMALS) for v in m.k.tolist()],
                "C0_white": [
                    round(float(v), _FINGERPRINT_DECIMALS) for v in m.C0_white.tolist()
                ],
            }
            for m in canonical_materials
        ],
        "layer_count": int(layer_count),
        "layer_height_mm": float(layer_height_mm),
        "substrate": substrate,
        "grid_resolution": int(grid_resolution),
        "total_combinations": total_combinations,
        "valid_cell_count": valid_count,
        "total_cell_count": total_buckets,
        "mean_delta_e": float(center_delta_e.mean()) if valid_count > 0 else 0.0,
        "max_delta_e": float(center_delta_e.max()) if valid_count > 0 else 0.0,
        "build_time_seconds": build_time,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    _log.info(
        "[MaterialCache] Built cache: palette=%s N=%d t=%.2f substrate=%s "
        "valid_cells=%d/%d mean_ΔE=%.2f build=%.1fs",
        palette_hash,
        layer_count,
        layer_height_mm,
        substrate,
        valid_count,
        total_buckets,
        metadata["mean_delta_e"],
        build_time,
    )

    return MaterialSolverCache(
        lab_centers=lab_centers,
        recipes=recipes,
        achieved_srgb=achieved_srgb,
        center_delta_e=center_delta_e,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_material_solver_cache(
    cache: MaterialSolverCache,
    *,
    cache_root: str | Path | None = None,
) -> Path:
    """Write ``cache`` to disk at its canonical path.
    将 ``cache`` 写入其规范磁盘路径。
    """
    directory = default_cache_directory(cache_root)
    directory.mkdir(parents=True, exist_ok=True)
    stem = _cache_file_stem(
        cache.palette_hash,
        cache.layer_count,
        cache.layer_height_mm,
        cache.substrate,
    )
    npz_path = directory / f"{stem}.npz"
    meta_path = _cache_meta_path_for(npz_path)

    # Write arrays atomically. np.savez_compressed appends ``.npz`` when the
    # path lacks one, so we hand it a binary file handle to keep the tmp name
    # predictable; then an atomic rename promotes it to the final path.
    tmp_npz = npz_path.with_name(npz_path.name + ".tmp")
    with tmp_npz.open("wb") as handle:
        np.savez_compressed(
            handle,
            lab_centers=cache.lab_centers,
            recipes=cache.recipes,
            achieved_srgb=cache.achieved_srgb,
            center_delta_e=cache.center_delta_e,
        )
    tmp_npz.replace(npz_path)

    meta_path.write_text(
        json.dumps(cache.metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _log.info("[MaterialCache] Saved cache %s (%.2f MB)",
              npz_path.name, npz_path.stat().st_size / (1024 * 1024))
    return npz_path


def load_material_solver_cache(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    cache_root: str | Path | None = None,
) -> MaterialSolverCache | None:
    """Load a cached solver from disk, or ``None`` if absent/corrupt.
    从磁盘加载缓存；不存在或损坏时返回 ``None``。
    """
    npz_path = cache_file_path(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        cache_root=cache_root,
    )
    meta_path = _cache_meta_path_for(npz_path)
    if not npz_path.exists() or not meta_path.exists():
        return None
    try:
        with np.load(npz_path) as loaded:
            lab_centers = loaded["lab_centers"].astype(np.float32)
            recipes = loaded["recipes"].astype(np.uint8)
            achieved_srgb = loaded["achieved_srgb"].astype(np.uint8)
            center_delta_e = loaded["center_delta_e"].astype(np.float32)
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        _log.warning(
            "[MaterialCache] Failed to load cache %s: %s",
            npz_path.name, exc,
        )
        return None

    # Sanity checks: shapes consistent, fingerprint matches caller's palette.
    if (
        recipes.shape[0] != lab_centers.shape[0]
        or recipes.shape[1] != int(metadata.get("layer_count", -1))
    ):
        _log.warning("[MaterialCache] Cache %s has inconsistent shapes", npz_path.name)
        return None
    expected_hash = fingerprint_palette(materials)
    if metadata.get("palette_hash") != expected_hash:
        _log.warning(
            "[MaterialCache] Cache %s palette_hash mismatch (expected %s got %s)",
            npz_path.name, expected_hash, metadata.get("palette_hash"),
        )
        return None

    return MaterialSolverCache(
        lab_centers=lab_centers,
        recipes=recipes,
        achieved_srgb=achieved_srgb,
        center_delta_e=center_delta_e,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Listing & introspection
# ---------------------------------------------------------------------------


def list_cached_entries(
    cache_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """List every cached palette combination with its metadata.
    列出所有已缓存的调色板组合及其元数据。
    """
    directory = default_cache_directory(cache_root)
    if not directory.exists():
        return []
    entries: list[dict[str, Any]] = []
    for npz_path in sorted(directory.glob("*.npz")):
        meta_path = _cache_meta_path_for(npz_path)
        if not meta_path.exists():
            continue
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        try:
            file_size = npz_path.stat().st_size
        except OSError:
            file_size = 0
        entries.append(
            {
                **metadata,
                "cache_file_path": str(npz_path),
                "cache_meta_path": str(meta_path),
                "cache_file_size_bytes": int(file_size),
            }
        )
    return entries


def delete_cached_entry(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    cache_root: str | Path | None = None,
) -> bool:
    """Remove the cache entry for the given parameters. Returns ``True`` on hit.
    删除指定参数的缓存条目；命中返回 ``True``。
    """
    npz_path = cache_file_path(
        materials, layer_count, layer_height_mm, substrate,
        cache_root=cache_root,
    )
    meta_path = _cache_meta_path_for(npz_path)
    removed_any = False
    for path in (npz_path, meta_path):
        if path.exists():
            try:
                path.unlink()
                removed_any = True
            except OSError as exc:
                _log.warning(
                    "[MaterialCache] Failed to remove %s: %s", path, exc
                )
    return removed_any
