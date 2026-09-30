"""Perceptual colour-similarity helpers for the colour workspace.

颜色工作台使用的感知色差工具：按 CIEDE2000 色差判断“相近颜色”，并为
目标颜色排序可打印的相似配方。模块只依赖 NumPy/OpenCV，不感知 API 或会话。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import numpy as np

from core.colorchecker.color_metrics import delta_e_2000
from core.material_color_solver import rgb_to_lab

RecipeSource = Literal["lut", "predictive", "image"]

_HEX_PATTERN = re.compile(r"^#?([0-9a-fA-F]{6})$")


@dataclass(frozen=True)
class SimilarRecipeCandidate:
    """One printable recipe ranked by distance to a reference colour.
    按与参考色距离排序的一条可打印配方。

    Attributes:
        rgb: Printed sRGB colour of the recipe. (配方打印后的 sRGB 颜色)
        recipe: Channel indices, ordered top (viewing face) to bottom.
            (通道索引序列，从观察面到底部)
        delta_e00: CIEDE2000 distance to the reference colour. (与参考色的 ΔE00)
        source: ``"lut"`` for measured LUT entries, ``"predictive"`` for
            forward-model candidates, ``"image"`` for colours already printed
            in the image. (lut 为实测条目，predictive 为预测候选，image 为图中已有颜色)
    """

    rgb: tuple[int, int, int]
    recipe: tuple[int, ...]
    delta_e00: float
    source: RecipeSource

    @property
    def hex(self) -> str:
        """Return the ``#rrggbb`` form of :attr:`rgb`. (返回 #rrggbb 形式)"""
        return rgb_to_hex(self.rgb)


def parse_hex_color(value: str) -> tuple[int, int, int]:
    """Parse ``#rrggbb`` / ``rrggbb`` into an RGB tuple.
    将 ``#rrggbb`` 或 ``rrggbb`` 解析为 RGB 三元组。

    Args:
        value: Hex colour string. (十六进制颜色字符串)

    Returns:
        tuple[int, int, int]: RGB channels in ``0..255``. (0..255 的 RGB 通道)

    Raises:
        ValueError: If ``value`` is not a 6-digit hex colour. (格式不是 6 位十六进制时抛出)
    """
    match = _HEX_PATTERN.match(str(value).strip())
    if match is None:
        raise ValueError(f"Invalid hex colour: {value!r}")
    digits = match.group(1)
    return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))


def rgb_to_hex(rgb: tuple[int, int, int] | np.ndarray) -> str:
    """Format an RGB triple as lowercase ``#rrggbb``.
    将 RGB 三元组格式化为小写 ``#rrggbb``。
    """
    r, g, b = (int(np.clip(int(channel), 0, 255)) for channel in list(rgb)[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def _unique_image_colors(
    rgb: np.ndarray,
    mask: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(colors (N, 3) uint8, first_flat_pixel_index (N,))`` of an image."""
    pixels = np.asarray(rgb)[..., :3].reshape(-1, 3)
    flat = np.arange(pixels.shape[0]) if mask is None else np.flatnonzero(np.asarray(mask, dtype=bool))
    channels = pixels[flat].astype(np.uint32)
    packed = (channels[:, 0] << 16) | (channels[:, 1] << 8) | channels[:, 2]
    codes, first = np.unique(packed, return_index=True)
    colors = np.stack([(codes >> 16) & 0xFF, (codes >> 8) & 0xFF, codes & 0xFF], axis=1)
    return colors.astype(np.uint8), flat[first]


def unique_color_hexes(rgb: np.ndarray, mask: np.ndarray | None = None) -> set[str]:
    """Return the distinct ``#rrggbb`` colours of an image, optionally masked.
    返回图像（可选仅掩码内像素）中出现的全部 ``#rrggbb`` 颜色。

    Args:
        rgb: ``(H, W, 3+)`` uint8-compatible image. ((H, W, 3+) 图像)
        mask: Optional ``(H, W)`` boolean mask of pixels to consider. (可选的像素掩码)

    Returns:
        set[str]: Lowercase hex colours. (小写十六进制颜色集合)
    """
    colors, _first = _unique_image_colors(rgb, mask)
    return {rgb_to_hex(color) for color in colors}


def rank_image_colors(
    reference_rgb: tuple[int, int, int],
    rgb: np.ndarray,
    mask: np.ndarray | None,
    stacks: np.ndarray | None,
    *,
    limit: int,
) -> list[SimilarRecipeCandidate]:
    """Rank colours already printed in the image by ΔE00 to a reference.
    按与参考色的 ΔE00 排序图中已有的颜色。

    Each colour carries the layer stack of its first pixel in ``stacks``
    (negative padding entries removed), so the suggestion shows how that
    colour is printed today. Used where only existing colours are suggested,
    such as material-archive sources.
    每个颜色附带其首个像素在 ``stacks`` 中的叠层（去掉负值填充），用于展示
    该颜色当前的打印方式；适用于只推荐已有颜色的场景（如耗材档案来源）。

    Args:
        reference_rgb: Colour to match. (要匹配的颜色)
        rgb: ``(H, W, 3+)`` image colours. (图像颜色)
        mask: Optional ``(H, W)`` mask of printed pixels. (可选的实体像素掩码)
        stacks: Optional ``(H, W, L)`` per-pixel layer stacks, top to bottom.
            (可选的逐像素叠层，自上而下)
        limit: Maximum number of results, ``>= 1``. (最大返回条数)

    Returns:
        list[SimilarRecipeCandidate]: Candidates sorted by ascending ΔE00.
            按 ΔE00 升序排列的候选。

    Raises:
        ValueError: If ``limit`` is below 1. (limit 小于 1 时抛出)
    """
    if int(limit) < 1:
        raise ValueError("limit must be at least 1.")
    colors, first_pixel = _unique_image_colors(rgb, mask)
    distances = delta_e00_to_reference(reference_rgb, colors)
    flat_stacks = None
    if stacks is not None:
        stack_array = np.asarray(stacks)
        flat_stacks = stack_array.reshape(-1, stack_array.shape[-1])
    candidates: list[SimilarRecipeCandidate] = []
    for idx in np.argsort(distances, kind="stable")[: int(limit)]:
        stack = () if flat_stacks is None else flat_stacks[first_pixel[idx]]
        candidates.append(
            SimilarRecipeCandidate(
                rgb=tuple(int(channel) for channel in colors[idx]),
                recipe=tuple(int(channel) for channel in stack if int(channel) >= 0),
                delta_e00=float(distances[idx]),
                source="image",
            )
        )
    return candidates


def delta_e00_to_reference(
    reference_rgb: tuple[int, int, int],
    candidate_rgb: np.ndarray,
) -> np.ndarray:
    """Return CIEDE2000 distances from one reference colour to many candidates.
    计算一个参考色到多个候选色的 CIEDE2000 色差。

    Args:
        reference_rgb: Reference sRGB colour. (参考 sRGB 颜色)
        candidate_rgb: ``(N, 3)`` uint8-compatible sRGB colours. ((N, 3) 候选 sRGB)

    Returns:
        np.ndarray: ``(N,)`` float64 ΔE00 values. ((N,) 的 ΔE00 数组)
    """
    candidates = np.asarray(candidate_rgb).reshape(-1, 3)
    if candidates.shape[0] == 0:
        return np.zeros((0,), dtype=np.float64)
    reference_lab = rgb_to_lab(np.asarray([reference_rgb], dtype=np.uint8))
    candidate_lab = rgb_to_lab(np.clip(candidates, 0, 255).astype(np.uint8))
    return np.asarray(
        delta_e_2000(np.broadcast_to(reference_lab, candidate_lab.shape), candidate_lab),
        dtype=np.float64,
    )


def colors_within_delta_e(
    reference_rgb: tuple[int, int, int],
    candidate_rgb: np.ndarray,
    max_delta_e00: float,
) -> np.ndarray:
    """Return a boolean mask of candidates within ``max_delta_e00`` of the reference.
    返回与参考色 ΔE00 不超过阈值的候选掩码。

    The reference colour itself always matches, so a zero tolerance behaves
    exactly like strict same-colour selection.
    参考色本身总会命中，因此容差为 0 时等价于严格同色选择。

    Args:
        reference_rgb: Reference sRGB colour. (参考 sRGB 颜色)
        candidate_rgb: ``(N, 3)`` sRGB colours. ((N, 3) 候选 sRGB)
        max_delta_e00: Inclusive CIEDE2000 tolerance, must be ``>= 0``.
            (包含边界的 ΔE00 容差，必须 >= 0)

    Returns:
        np.ndarray: ``(N,)`` boolean mask. ((N,) 布尔掩码)

    Raises:
        ValueError: If the tolerance is negative or not finite. (容差为负或非有限值时抛出)
    """
    tolerance = float(max_delta_e00)
    if not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError(f"Colour tolerance must be a non-negative number, got {max_delta_e00!r}.")
    candidates = np.asarray(candidate_rgb).reshape(-1, 3)
    exact = np.all(candidates.astype(np.int32) == np.asarray(reference_rgb, dtype=np.int32), axis=1)
    return exact | (delta_e00_to_reference(reference_rgb, candidates) <= tolerance)


def _rank_source(
    reference_rgb: tuple[int, int, int],
    rgb: np.ndarray,
    stacks: np.ndarray,
    source: RecipeSource,
    limit: int,
) -> list[SimilarRecipeCandidate]:
    """Rank one recipe source; all-Air placeholder rows are skipped and only
    the first row of each printed colour is kept, so a suggested colour maps
    to exactly one recipe.
    对单一来源排序：跳过全 Air 占位行，同一打印色只保留第一条。

    A single ``-1`` is legitimate Air padding (the 1024 base recipes of a
    standard 2468 LUT, short keyed-JSON recipes), so such rows stay ranked
    and only their padding is dropped from the reported recipe.
    单个 ``-1`` 是合法的 Air 填充（标准 2468 LUT 的前 1024 条、keyed JSON
    的短配方），这些行照常参与排序，仅在返回的配方中去掉填充。
    """
    rgb_rows = np.clip(np.asarray(rgb).reshape(-1, 3), 0, 255).astype(np.uint8)
    stack_rows = np.asarray(stacks, dtype=np.int64)
    if stack_rows.ndim != 2 or stack_rows.shape[0] != rgb_rows.shape[0]:
        raise ValueError(f"{source} colours and recipes must have the same length.")
    real = np.any(stack_rows >= 0, axis=1)
    rgb_rows, stack_rows = rgb_rows[real], stack_rows[real]
    first_index = np.sort(np.unique(rgb_rows, axis=0, return_index=True)[1])
    rgb_rows, stack_rows = rgb_rows[first_index], stack_rows[first_index]
    distances = delta_e00_to_reference(reference_rgb, rgb_rows)
    return [
        SimilarRecipeCandidate(
            rgb=tuple(int(channel) for channel in rgb_rows[idx]),
            recipe=tuple(int(channel) for channel in stack_rows[idx] if channel >= 0),
            delta_e00=float(distances[idx]),
            source=source,
        )
        for idx in np.argsort(distances, kind="stable")[:limit]
    ]


def rank_similar_recipes(
    reference_rgb: tuple[int, int, int],
    lut_rgb: np.ndarray,
    lut_stacks: np.ndarray,
    *,
    limit: int,
    predictive_rgb: np.ndarray | None = None,
    predictive_recipes: np.ndarray | None = None,
) -> list[SimilarRecipeCandidate]:
    """Rank printable recipes by CIEDE2000 distance to a reference colour.
    按与参考色的 CIEDE2000 色差排序可打印配方。

    Measured LUT entries and forward-model candidates are ranked separately
    and merged, so the closest ``limit`` of each source can compete. A
    predictive candidate whose printed colour already exists in the LUT is
    dropped because the LUT entry is the measured truth.
    实测 LUT 条目与预测候选分别排序后合并；若预测色与 LUT 某条目同色，
    以实测条目为准并丢弃预测条目。

    Args:
        reference_rgb: Colour to match. (要匹配的颜色)
        lut_rgb: ``(N, 3)`` measured LUT colours. ((N, 3) 实测 LUT 颜色)
        lut_stacks: ``(N, L)`` LUT recipes, top to bottom. ((N, L) LUT 配方，自上而下)
        limit: Maximum number of results, ``>= 1``. (最大返回条数)
        predictive_rgb: Optional ``(M, 3)`` predicted colours. (可选的预测颜色)
        predictive_recipes: Optional ``(M, K)`` predictive recipes. (可选的预测配方)

    Returns:
        list[SimilarRecipeCandidate]: Candidates sorted by ascending ΔE00.
            按 ΔE00 升序排列的候选。

    Raises:
        ValueError: If ``limit`` is below 1 or array lengths disagree.
            limit 小于 1 或数组长度不一致时抛出。
    """
    if int(limit) < 1:
        raise ValueError("limit must be at least 1.")
    candidates = _rank_source(reference_rgb, lut_rgb, lut_stacks, "lut", int(limit))
    if predictive_rgb is not None and predictive_recipes is not None:
        measured = {tuple(int(v) for v in row) for row in np.asarray(lut_rgb).reshape(-1, 3)}
        predicted = _rank_source(
            reference_rgb, predictive_rgb, predictive_recipes, "predictive", int(limit)
        )
        candidates.extend(item for item in predicted if item.rgb not in measured)
    candidates.sort(key=lambda item: (item.delta_e00, item.source != "lut"))
    return candidates[: int(limit)]
