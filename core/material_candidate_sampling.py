"""Bounded recipe sampling for material candidate runtimes.

This module only generates finite recipe candidates. It deliberately avoids
the exhaustive affine enumerators used by the legacy solver-cache builder.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CandidateRecipeBatch:
    """Bounded recipe candidates plus must-keep row markers.
    有上限的候选配方集合，以及必须保留的行标记。

    Attributes:
        recipes: ``(K, N)`` bottom-to-top material indices. (自底向上的配方)
        pinned_mask: ``(K,)`` rows that came from deterministic anchors.
            (来自确定性锚点、后续选择时应优先保留的行)
    """

    recipes: np.ndarray
    pinned_mask: np.ndarray


def _uniform_recipes(material_count: int, layer_count: int) -> np.ndarray:
    indices = np.arange(material_count, dtype=np.uint16)
    return np.repeat(indices[:, None], layer_count, axis=1)


def _safe_total_count(
    *,
    material_count: int,
    layer_count: int,
    limit: int,
) -> int:
    total = 1
    for _ in range(layer_count):
        total *= material_count
        if total >= limit:
            return limit
    return total


def _all_recipe_space(material_count: int, layer_count: int, total: int) -> np.ndarray:
    values = np.arange(int(total), dtype=np.uint64)
    work = values.copy()
    recipes = np.empty((int(total), int(layer_count)), dtype=np.uint16)
    for layer_index in range(int(layer_count)):
        recipes[:, layer_index] = (work % int(material_count)).astype(np.uint16)
        work //= int(material_count)
    return recipes


def _pair_ramp_recipes(
    *,
    material_count: int,
    layer_count: int,
    limit: int,
) -> np.ndarray:
    if limit <= 0 or material_count < 2:
        return np.zeros((0, int(layer_count)), dtype=np.uint16)

    recipes: list[np.ndarray] = []
    for bottom in range(int(material_count)):
        for top in range(int(material_count)):
            if bottom == top:
                continue

            top_one = np.full(int(layer_count), bottom, dtype=np.uint16)
            top_one[-1] = top
            recipes.append(top_one)
            if len(recipes) >= limit:
                return np.asarray(recipes, dtype=np.uint16)

            top_half = np.full(int(layer_count), bottom, dtype=np.uint16)
            split = max(1, int(layer_count) // 2)
            top_half[-split:] = top
            recipes.append(top_half)
            if len(recipes) >= limit:
                return np.asarray(recipes, dtype=np.uint16)

            alternating = np.empty(int(layer_count), dtype=np.uint16)
            alternating[0::2] = bottom
            alternating[1::2] = top
            recipes.append(alternating)
            if len(recipes) >= limit:
                return np.asarray(recipes, dtype=np.uint16)

    if not recipes:
        return np.zeros((0, int(layer_count)), dtype=np.uint16)
    return np.asarray(recipes, dtype=np.uint16)


def _sobol_points(count: int, layer_count: int, seed: int) -> np.ndarray:
    from scipy.stats import qmc

    power = int(np.ceil(np.log2(max(1, count))))
    sampler = qmc.Sobol(d=int(layer_count), scramble=True, seed=int(seed))
    return sampler.random_base2(power)[:count]


def _rng_points(count: int, layer_count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(int(seed))
    return rng.random((int(count), int(layer_count)), dtype=np.float64)


def _low_discrepancy_recipes(
    *,
    material_count: int,
    layer_count: int,
    count: int,
    seed: int,
) -> np.ndarray:
    try:
        points = _sobol_points(count, layer_count, seed)
    except Exception:
        points = _rng_points(count, layer_count, seed)
    recipes = np.floor(points * int(material_count)).astype(np.uint16)
    return np.clip(recipes, 0, int(material_count) - 1)


def _unique_rows_preserve_order(rows: np.ndarray) -> np.ndarray:
    if rows.size == 0:
        return rows.reshape(0, rows.shape[-1])
    _, unique_indices = np.unique(rows, axis=0, return_index=True)
    return rows[np.sort(unique_indices)]


def generate_candidate_recipes(
    *,
    material_count: int,
    layer_count: int,
    candidate_budget: int,
    seed: int = 0,
) -> CandidateRecipeBatch:
    """Generate deterministic bounded recipes for a material palette.
    为一个耗材调色板生成确定性、有数量上限的候选配方。

    Args:
        material_count: Number of available materials. (可用耗材数量)
        layer_count: Number of layers in each recipe. (每条配方的层数)
        candidate_budget: Maximum number of recipes to return. (最多返回配方数)
        seed: Deterministic seed for Sobol scrambling. (Sobol 扰动种子)

    Returns:
        CandidateRecipeBatch: Candidate recipes and pinned-row mask.
            (候选配方及其锚点标记)
    """
    if material_count <= 0:
        raise ValueError("material_count must be positive")
    if layer_count <= 0:
        raise ValueError("layer_count must be positive")
    if candidate_budget <= 0:
        raise ValueError("candidate_budget must be positive")
    if material_count > np.iinfo(np.uint16).max + 1:
        raise ValueError("material_count exceeds uint16 recipe capacity")

    total_count = _safe_total_count(
        material_count=int(material_count),
        layer_count=int(layer_count),
        limit=int(candidate_budget) + 1,
    )
    budget = min(int(candidate_budget), total_count)
    pinned = _uniform_recipes(int(material_count), int(layer_count))[:budget]

    if total_count <= budget:
        all_recipes = _all_recipe_space(
            int(material_count),
            int(layer_count),
            int(total_count),
        )
        combined = _unique_rows_preserve_order(np.vstack([pinned, all_recipes]))
        pinned_mask = np.zeros(combined.shape[0], dtype=bool)
        pinned_mask[: min(int(material_count), combined.shape[0])] = True
        return CandidateRecipeBatch(
            recipes=combined.astype(np.uint16, copy=False),
            pinned_mask=pinned_mask,
        )

    ramps = _pair_ramp_recipes(
        material_count=int(material_count),
        layer_count=int(layer_count),
        limit=max(0, budget - pinned.shape[0]),
    )
    anchors = _unique_rows_preserve_order(np.vstack([pinned, ramps]))[:budget]
    remaining = max(0, budget - anchors.shape[0])
    sample_count = max(remaining * 2, remaining)
    sampled = _low_discrepancy_recipes(
        material_count=int(material_count),
        layer_count=int(layer_count),
        count=sample_count,
        seed=int(seed),
    )
    combined = _unique_rows_preserve_order(np.vstack([anchors, sampled]))[:budget]

    while combined.shape[0] < budget:
        missing = budget - combined.shape[0]
        extra = _low_discrepancy_recipes(
            material_count=int(material_count),
            layer_count=int(layer_count),
            count=max(missing * 4, 1),
            seed=int(seed) + combined.shape[0] + 1,
        )
        next_combined = _unique_rows_preserve_order(
            np.vstack([combined, extra])
        )[:budget]
        if next_combined.shape[0] == combined.shape[0]:
            break
        combined = next_combined

    pinned_mask = np.zeros(combined.shape[0], dtype=bool)
    pinned_mask[: min(anchors.shape[0], combined.shape[0])] = True
    return CandidateRecipeBatch(
        recipes=combined.astype(np.uint16, copy=False),
        pinned_mask=pinned_mask,
    )
