"""Material color solver — Beer-Lambert beam-search for per-pixel layer recipes.
耗材颜色求解器 — 基于 Beer-Lambert 模型的波束搜索，求解每像素叠层配方。

Given a set of materials (each with fitted E, k, C0 parameters) and a target
layer count, this module solves for the optimal per-pixel layer recipe that
best reproduces a target color.

The solver uses a beam-search strategy: for each unique quantized color, it
explores layer-by-layer expansions of partial recipes, pruning to the top-B
candidates at each step.  This avoids the M^N combinatorial explosion of
exhaustive enumeration while still finding near-optimal solutions.

Public API
----------
- ``MaterialParams``   — dataclass holding Beer-Lambert parameters for one material
- ``forward_model``    — predict linear RGB for a full N-layer recipe
- ``solve_image_colors`` — solve optimal recipes for a batch of unique colors
- ``map_pixels_to_materials`` — map every image pixel to its solved recipe
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_LAYER_HEIGHTS_MM: tuple[float, ...] = (0.04, 0.08, 0.1)
DEFAULT_LAYER_HEIGHT_MM: float = 0.08
DEFAULT_LAYER_COUNT: int = 5
MIN_LAYER_COUNT: int = 5
MAX_LAYER_COUNT: int = 10
DEFAULT_BEAM_WIDTH: int = 32


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MaterialParams:
    """Loaded Beer-Lambert parameters for one material.
    单种耗材的 Beer-Lambert 参数。

    Attributes:
        name: Human-readable material name (e.g. "PLA Red"). (耗材名称)
        directory_name: On-disk directory name under ``materials/``. (目录名)
        E: (3,) equilibrium color in linear RGB. (平衡色 linear RGB)
        k: (3,) absorption coefficient per channel. (吸收系数)
        C0_white: (3,) zero-thickness color on white substrate in linear RGB.
            (白底零厚度颜色 linear RGB)
        estimated_rgb: (3,) sRGB uint8 estimated material color for preview.
            (预览用 sRGB uint8 预估耗材颜色)
    """

    name: str
    directory_name: str
    E: np.ndarray       # (3,) float64, linear
    k: np.ndarray       # (3,) float64
    C0_white: np.ndarray  # (3,) float64, linear
    estimated_rgb: np.ndarray  # (3,) uint8


# ---------------------------------------------------------------------------
# sRGB ↔ linear helpers
# ---------------------------------------------------------------------------


def srgb_to_linear(arr: np.ndarray) -> np.ndarray:
    """Convert sRGB uint8 to linear float64 in [0, 1].
    将 sRGB uint8 转换为 [0, 1] 范围的线性 float64。
    """
    c = arr.astype(np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb_float(arr: np.ndarray) -> np.ndarray:
    """Convert linear float64 to sRGB float64 in [0, 1].
    将线性 float64 转换为 [0, 1] 范围的 sRGB float64。
    """
    c = np.clip(arr.astype(np.float64), 0.0, 1.0)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


def linear_to_srgb_uint8(arr: np.ndarray) -> np.ndarray:
    """Convert linear float64 to sRGB uint8.
    将线性 float64 转换为 sRGB uint8。
    """
    srgb = linear_to_srgb_float(arr)
    return np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)


def rgb_to_lab(srgb_uint8: np.ndarray) -> np.ndarray:
    """Convert sRGB uint8 array (N, 3) to CIE Lab float64 (N, 3).
    将 sRGB uint8 (N, 3) 转换为 CIE Lab float64 (N, 3)。
    """
    srgb_f32 = srgb_uint8.astype(np.float32) / 255.0
    lab = cv2.cvtColor(srgb_f32.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB)
    return lab.reshape(-1, 3).astype(np.float64)


# ---------------------------------------------------------------------------
# Beer-Lambert forward model
# ---------------------------------------------------------------------------


def beer_lambert_layer(
    C_prev: np.ndarray,
    E: np.ndarray,
    k: np.ndarray,
    thickness_mm: float,
) -> np.ndarray:
    """Apply one Beer-Lambert layer on top of the current color.
    在当前颜色上叠加一层 Beer-Lambert 耗材。

    C(t) = E + (C_prev − E) × exp(−k × t)

    Args:
        C_prev: (..., 3) current color in linear RGB. (当前线性 RGB 颜色)
        E: (3,) equilibrium color. (平衡色)
        k: (3,) absorption coefficient. (吸收系数)
        thickness_mm: Layer thickness in mm. (层厚度 mm)

    Returns:
        (..., 3) new color after the layer. (叠层后的新颜色)
    """
    return E + (C_prev - E) * np.exp(-k * thickness_mm)


def forward_model(
    recipe: np.ndarray,
    materials: list[MaterialParams],
    layer_height_mm: float,
    substrate_linear: np.ndarray | None = None,
) -> np.ndarray:
    """Compute the predicted linear RGB for a full N-layer recipe.
    正向计算 N 层配方的预测线性 RGB。

    Args:
        recipe: (N,) int array of material indices (0-based). (材料索引数组)
        materials: List of available materials. (耗材列表)
        layer_height_mm: Thickness of each layer in mm. (每层厚度 mm)
        substrate_linear: (3,) substrate color in linear RGB; defaults to white.
            (基底颜色 linear RGB，默认白)

    Returns:
        (3,) predicted color in linear RGB. (预测颜色 linear RGB)
    """
    if substrate_linear is None:
        substrate_linear = np.ones(3, dtype=np.float64)
    C = substrate_linear.copy()
    for layer_idx in range(len(recipe)):
        mat_id = int(recipe[layer_idx])
        mat = materials[mat_id]
        C = beer_lambert_layer(C, mat.E, mat.k, layer_height_mm)
    return C


# ---------------------------------------------------------------------------
# Beam-search solver
# ---------------------------------------------------------------------------


def _solve_single_color_beam(
    target_lab: np.ndarray,
    target_linear: np.ndarray,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate_linear: np.ndarray,
    beam_width: int,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Beam-search solver for one target color.
    单色波束搜索求解器。

    对一个目标颜色，逐层展开候选配方，每步保留 ΔE 最小的 beam_width 个候选。

    Args:
        target_lab: (3,) target color in CIE Lab. (目标 Lab 颜色)
        target_linear: (3,) target color in linear RGB. (目标线性 RGB)
        materials: Available materials. (可用耗材列表)
        layer_count: Number of layers. (层数)
        layer_height_mm: Thickness per layer in mm. (每层厚度 mm)
        substrate_linear: (3,) substrate color in linear RGB. (基底颜色)
        beam_width: Max candidates to keep per step. (每步最大候选数)

    Returns:
        (recipe, predicted_linear, delta_e): Best recipe found.
            recipe: (N,) int32 material indices.
            predicted_linear: (3,) predicted linear RGB.
            delta_e: float ΔE (CIE76) between target and prediction.
    """
    M = len(materials)

    # Pre-extract E and k arrays for vectorized computation: (M, 3) each
    all_E = np.stack([m.E for m in materials], axis=0)     # (M, 3)
    all_k = np.stack([m.k for m in materials], axis=0)     # (M, 3)

    # Initialize beam: one candidate starting from substrate
    # Each candidate: (current_linear (3,), partial_recipe list[int])
    beam_colors = substrate_linear.reshape(1, 3).copy()  # (B, 3)
    beam_recipes: list[list[int]] = [[]]

    for _layer in range(layer_count):
        B = beam_colors.shape[0]
        # Expand: each of B candidates × M materials → B*M candidates
        # beam_colors: (B, 3) → repeat for M → (B*M, 3)
        expanded_colors = np.repeat(beam_colors, M, axis=0)  # (B*M, 3)

        # Tile E and k for each beam entry
        tiled_E = np.tile(all_E, (B, 1))  # (B*M, 3)
        tiled_k = np.tile(all_k, (B, 1))  # (B*M, 3)

        # Vectorized Beer-Lambert
        new_colors = tiled_E + (expanded_colors - tiled_E) * np.exp(-tiled_k * layer_height_mm)

        # Compute ΔE in Lab space for scoring
        new_srgb = linear_to_srgb_uint8(new_colors)
        new_lab = rgb_to_lab(new_srgb)
        delta_e = np.linalg.norm(new_lab - target_lab.reshape(1, 3), axis=1)  # (B*M,)

        # Build expanded recipe lists
        mat_ids = np.tile(np.arange(M), B)  # (B*M,)
        expanded_recipes = []
        for b_idx in range(B):
            for m_idx in range(M):
                expanded_recipes.append(beam_recipes[b_idx] + [m_idx])

        # Prune to top beam_width
        if len(delta_e) <= beam_width:
            keep = np.arange(len(delta_e))
        else:
            keep = np.argpartition(delta_e, beam_width)[:beam_width]
            # Sort the kept indices for deterministic ordering
            keep = keep[np.argsort(delta_e[keep])]

        beam_colors = new_colors[keep]
        beam_recipes = [expanded_recipes[i] for i in keep]

    # Final selection: best ΔE
    final_srgb = linear_to_srgb_uint8(beam_colors)
    final_lab = rgb_to_lab(final_srgb)
    final_delta_e = np.linalg.norm(final_lab - target_lab.reshape(1, 3), axis=1)
    best_idx = int(np.argmin(final_delta_e))

    best_recipe = np.asarray(beam_recipes[best_idx], dtype=np.int32)
    best_color = beam_colors[best_idx]
    best_de = float(final_delta_e[best_idx])
    return best_recipe, best_color, best_de


def solve_image_colors(
    unique_colors_srgb: np.ndarray,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float = DEFAULT_LAYER_HEIGHT_MM,
    substrate: str = "white",
    beam_width: int = DEFAULT_BEAM_WIDTH,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Solve optimal recipes for a set of unique quantized colors.
    对一组量化后的唯一颜色求解最优配方。

    For each unique color, runs a beam-search through the space of possible
    N-layer recipes and returns the best match (lowest CIE76 ΔE).

    Args:
        unique_colors_srgb: (C, 3) uint8 unique colors. (唯一颜色 sRGB)
        materials: List of selected materials. (已选耗材列表)
        layer_count: Number of layers per pixel (5-10). (每像素层数)
        layer_height_mm: Thickness of each layer in mm. (每层厚度 mm)
        substrate: Substrate type, "white" or "black". (基底类型)
        beam_width: Beam search width. (波束宽度)

    Returns:
        matched_rgb: (C, 3) uint8 — predicted sRGB for each unique color.
            (每个唯一色的预测 sRGB)
        recipes: (C, N) int32 — material index per layer for each color.
            (每个唯一色的配方)
        delta_e: (C,) float64 — ΔE for each color. (每个唯一色的 ΔE)
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

    C_count = unique_colors_srgb.shape[0]
    if C_count == 0:
        return (
            np.zeros((0, 3), dtype=np.uint8),
            np.zeros((0, layer_count), dtype=np.int32),
            np.zeros((0,), dtype=np.float64),
        )

    # Substrate color in linear RGB
    if substrate == "white":
        substrate_linear = np.ones(3, dtype=np.float64)
    elif substrate == "black":
        substrate_linear = np.zeros(3, dtype=np.float64)
    else:
        substrate_linear = np.ones(3, dtype=np.float64)

    # Pre-compute Lab for all target colors
    target_labs = rgb_to_lab(unique_colors_srgb)
    target_linears = srgb_to_linear(unique_colors_srgb)

    matched_rgb = np.zeros((C_count, 3), dtype=np.uint8)
    recipes = np.zeros((C_count, layer_count), dtype=np.int32)
    delta_e_arr = np.zeros(C_count, dtype=np.float64)

    _log.info(
        "[MaterialSolver] Solving %d unique colors with %d materials, %d layers, "
        "%.2f mm/layer, beam=%d",
        C_count,
        len(materials),
        layer_count,
        layer_height_mm,
        beam_width,
    )

    for i in range(C_count):
        recipe, pred_linear, de = _solve_single_color_beam(
            target_lab=target_labs[i],
            target_linear=target_linears[i],
            materials=materials,
            layer_count=layer_count,
            layer_height_mm=layer_height_mm,
            substrate_linear=substrate_linear,
            beam_width=beam_width,
        )
        matched_rgb[i] = linear_to_srgb_uint8(pred_linear.reshape(1, 3))[0]
        recipes[i] = recipe
        delta_e_arr[i] = de

    mean_de = float(np.mean(delta_e_arr)) if C_count > 0 else 0.0
    max_de = float(np.max(delta_e_arr)) if C_count > 0 else 0.0
    _log.info(
        "[MaterialSolver] Done: mean_ΔE=%.2f, max_ΔE=%.2f",
        mean_de,
        max_de,
    )
    return matched_rgb, recipes, delta_e_arr


# ---------------------------------------------------------------------------
# Pixel mapping (replicates the role of map_pixels_to_lut for material mode)
# ---------------------------------------------------------------------------


def map_pixels_to_materials(
    quantized_image: np.ndarray,
    unique_colors: np.ndarray,
    matched_rgb_unique: np.ndarray,
    recipes_unique: np.ndarray,
    target_h: int,
    target_w: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Map all image pixels to their solved recipes.
    将图像所有像素映射到求解的配方。

    Uses integer-code lookup (R*65536 + G*256 + B) for fast matching between
    the quantized image and the unique-color solution table.

    Args:
        quantized_image: (H, W, 3) uint8 quantized image. (量化图像)
        unique_colors: (C, 3) uint8 unique colors. (唯一颜色)
        matched_rgb_unique: (C, 3) uint8 matched colors from solver. (求解匹配色)
        recipes_unique: (C, N) int32 recipes from solver. (求解配方)
        target_h: Image height. (图像高度)
        target_w: Image width. (图像宽度)

    Returns:
        matched_rgb: (H, W, 3) uint8 matched RGB image. (匹配 RGB 图像)
        material_matrix: (H, W, N) int32 material matrix. (材料矩阵)
    """
    layer_count = recipes_unique.shape[1]

    unique_codes = (
        unique_colors[:, 0].astype(np.int32) * 65536
        + unique_colors[:, 1].astype(np.int32) * 256
        + unique_colors[:, 2].astype(np.int32)
    )
    sort_idx = np.argsort(unique_codes)
    sorted_codes = unique_codes[sort_idx]
    sorted_matched = matched_rgb_unique[sort_idx]
    sorted_recipes = recipes_unique[sort_idx]

    flat_quantized = quantized_image.reshape(-1, 3)
    pixel_codes = (
        flat_quantized[:, 0].astype(np.int32) * 65536
        + flat_quantized[:, 1].astype(np.int32) * 256
        + flat_quantized[:, 2].astype(np.int32)
    )
    insert_positions = np.searchsorted(sorted_codes, pixel_codes)
    matched_rgb = sorted_matched[insert_positions].reshape(target_h, target_w, 3)
    material_matrix = sorted_recipes[insert_positions].reshape(target_h, target_w, layer_count)

    return matched_rgb, material_matrix
