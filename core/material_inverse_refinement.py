"""Target-aware inverse refinement for bounded material candidates.

This module improves candidate-cache matches by using the affine structure of
the Beer-Lambert model. It searches only a bounded material subset and bounded
prefix/suffix tables; it never scans the full ``M ** N`` recipe space.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from core.material_candidate_sampling import generate_candidate_recipes
from core.material_color_solver import (
    MaterialParams,
    _compute_material_affines,
    linear_to_srgb_uint8,
    rgb_to_lab,
    srgb_to_linear,
)
from core.task_parallelism import task_parallelism_worker_scope


@dataclass(frozen=True)
class MaterialInverseRefinementConfig:
    """Bounded inverse-refinement settings.
    有预算约束的反向精修配置。

    Attributes:
        enabled: Whether refinement is enabled. (是否启用精修)
        max_refine_materials: Maximum material subset size. (材料子集上限)
        max_refine_bottom_prefixes: Bottom-prefix candidate cap. (底部前缀上限)
        max_refine_top_suffixes: Top-suffix candidate cap. (顶部后缀上限)
        refine_bottom_neighbors: Bottom prefixes to test per required color.
            (每个反推底色测试的底部前缀数量)
        required_color_tolerance: Allowed linear-RGB overshoot tolerance.
            (反推底色的线性 RGB 越界容差)
        seed: Deterministic seed for capped recipe generation. (确定性种子)
    """

    enabled: bool = True
    max_refine_materials: int = 8
    max_refine_bottom_prefixes: int = 65_536
    max_refine_top_suffixes: int = 32_768
    refine_bottom_neighbors: int = 2
    required_color_tolerance: float = 0.03
    seed: int = 0


@dataclass(frozen=True)
class MaterialInverseRefinementResult:
    """Refined material matches.
    反向精修后的耗材匹配结果。

    Attributes:
        matched_srgb: ``(C, 3)`` verified predicted sRGB. (验证后的预测色)
        recipes: ``(C, N)`` bottom-to-top recipes in canonical order.
            (规范顺序、自底向上的配方)
        delta_e: ``(C,)`` CIE76 Delta-E to targets. (相对目标色的 Delta-E)
        improved_mask: ``(C,)`` rows improved over baseline. (相对 baseline 改善的行)
    """

    matched_srgb: np.ndarray
    recipes: np.ndarray
    delta_e: np.ndarray
    improved_mask: np.ndarray


@dataclass(frozen=True)
class _InverseRefinementWorkspaceKey:
    """Stable identity for one deterministic inverse-refinement workspace."""

    subset: tuple[int, ...]
    bottom_depth: int
    top_depth: int
    bottom_budget: int
    top_budget: int
    bottom_seed: int
    top_seed: int


@dataclass(frozen=True)
class _InverseRefinementWorkspace:
    """Read-only candidate arrays shared by target rows in one subset group."""

    bottom_recipes: np.ndarray
    top_recipes: np.ndarray
    bottom_linear: np.ndarray
    top_alpha: np.ndarray
    top_beta: np.ndarray
    bottom_tree: cKDTree


def compute_required_bottom_colors(
    target_linear: np.ndarray,
    top_alpha: np.ndarray,
    top_beta: np.ndarray,
) -> np.ndarray:
    """Invert top suffix affine maps for one target linear RGB.
    对一个目标线性 RGB 反推顶部后缀需要的底部颜色。

    Args:
        target_linear: ``(3,)`` target linear RGB. (目标线性 RGB)
        top_alpha: ``(K, 3)`` top-suffix transmittance. (顶部后缀 alpha)
        top_beta: ``(K, 3)`` top-suffix emission term. (顶部后缀 beta)

    Returns:
        np.ndarray: ``(K, 3)`` required bottom colors. (所需底部颜色)
    """
    target = np.asarray(target_linear, dtype=np.float64).reshape(1, 3)
    alpha = np.asarray(top_alpha, dtype=np.float64)
    beta = np.asarray(top_beta, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (target - beta) / alpha


def required_bottom_color_mask(
    required_bottom: np.ndarray,
    *,
    tolerance: float,
) -> np.ndarray:
    """Return rows whose required bottom color is finite and near gamut.
    返回反推底色有限且没有明显越界的行。
    """
    required = np.asarray(required_bottom, dtype=np.float64)
    finite = np.isfinite(required).all(axis=1)
    lower_ok = (required >= -float(tolerance)).all(axis=1)
    upper_ok = (required <= 1.0 + float(tolerance)).all(axis=1)
    return finite & lower_ok & upper_ok


def _substrate_linear(substrate: str) -> np.ndarray:
    normalized = str(substrate).lower()
    if normalized == "white":
        return np.ones(3, dtype=np.float64)
    if normalized == "black":
        return np.zeros(3, dtype=np.float64)
    raise ValueError("substrate must be 'white' or 'black'")


def _cumulative_affines_for_recipes(
    *,
    recipes: np.ndarray,
    materials: list[MaterialParams],
    layer_height_mm: float,
) -> tuple[np.ndarray, np.ndarray]:
    affines = _compute_material_affines(materials, float(layer_height_mm))
    alpha = np.ones((recipes.shape[0], 3), dtype=np.float64)
    beta = np.zeros((recipes.shape[0], 3), dtype=np.float64)
    batch = recipes.astype(np.int64, copy=False)
    for layer_index in range(batch.shape[1]):
        material_indices = batch[:, layer_index]
        alpha = affines.a[material_indices] * alpha
        beta = affines.a[material_indices] * beta + affines.b[material_indices]
    return alpha, beta


def _predict_linear_for_recipes(
    *,
    recipes: np.ndarray,
    materials: list[MaterialParams],
    layer_height_mm: float,
    substrate: str,
) -> np.ndarray:
    alpha, beta = _cumulative_affines_for_recipes(
        recipes=recipes,
        materials=materials,
        layer_height_mm=layer_height_mm,
    )
    return np.clip(alpha * _substrate_linear(substrate).reshape(1, 3) + beta, 0.0, 1.0)


def _select_material_subset(
    *,
    target_srgb: np.ndarray,
    baseline_recipe: np.ndarray,
    materials: list[MaterialParams],
    max_materials: int,
) -> np.ndarray:
    material_count = len(materials)
    if material_count <= max_materials:
        return np.arange(material_count, dtype=np.int32)

    selected: list[int] = []
    for material_index in np.unique(baseline_recipe.astype(np.int32, copy=False)):
        if 0 <= int(material_index) < material_count:
            selected.append(int(material_index))

    estimated = np.vstack([m.estimated_rgb for m in materials]).astype(np.uint8)
    material_lab = rgb_to_lab(estimated).astype(np.float64)
    target_lab = rgb_to_lab(target_srgb.reshape(1, 3).astype(np.uint8))[0]
    nearest = np.argsort(np.linalg.norm(material_lab - target_lab.reshape(1, 3), axis=1))
    for material_index in nearest:
        if int(material_index) not in selected:
            selected.append(int(material_index))
        if len(selected) >= max_materials:
            break
    return np.asarray(selected[:max_materials], dtype=np.int32)


def _bounded_subset_recipes(
    *,
    subset: np.ndarray,
    depth: int,
    budget: int,
    seed: int,
) -> np.ndarray:
    if depth <= 0:
        return np.zeros((1, 0), dtype=np.int32)
    generated = generate_candidate_recipes(
        material_count=int(subset.shape[0]),
        layer_count=int(depth),
        candidate_budget=max(1, int(budget)),
        seed=int(seed),
    )
    return subset[generated.recipes.astype(np.int64)].astype(np.int32, copy=False)


def _workspace_key(
    *,
    subset: np.ndarray,
    layer_count: int,
    config: MaterialInverseRefinementConfig,
) -> _InverseRefinementWorkspaceKey:
    """Return the deterministic key for a row's candidate workspace."""

    bottom_depth = int(layer_count) // 2
    top_depth = int(layer_count) - bottom_depth
    return _InverseRefinementWorkspaceKey(
        subset=tuple(int(value) for value in subset),
        bottom_depth=bottom_depth,
        top_depth=top_depth,
        bottom_budget=int(config.max_refine_bottom_prefixes),
        top_budget=int(config.max_refine_top_suffixes),
        bottom_seed=int(config.seed),
        top_seed=int(config.seed) + 17,
    )


def _build_workspace(
    *,
    key: _InverseRefinementWorkspaceKey,
    materials: list[MaterialParams],
    layer_height_mm: float,
    substrate: str,
) -> _InverseRefinementWorkspace:
    """Build one immutable candidate workspace for a material subset."""

    subset = np.asarray(key.subset, dtype=np.int32)
    bottom_recipes = _bounded_subset_recipes(
        subset=subset,
        depth=key.bottom_depth,
        budget=key.bottom_budget,
        seed=key.bottom_seed,
    )
    top_recipes = _bounded_subset_recipes(
        subset=subset,
        depth=key.top_depth,
        budget=key.top_budget,
        seed=key.top_seed,
    )
    bottom_linear = _predict_linear_for_recipes(
        recipes=bottom_recipes,
        materials=materials,
        layer_height_mm=float(layer_height_mm),
        substrate=substrate,
    )
    top_alpha, top_beta = _cumulative_affines_for_recipes(
        recipes=top_recipes,
        materials=materials,
        layer_height_mm=float(layer_height_mm),
    )
    return _InverseRefinementWorkspace(
        bottom_recipes=bottom_recipes,
        top_recipes=top_recipes,
        bottom_linear=bottom_linear,
        top_alpha=top_alpha,
        top_beta=top_beta,
        bottom_tree=cKDTree(bottom_linear.astype(np.float64, copy=False)),
    )


def _best_refined_row_with_workspace(
    *,
    target_srgb: np.ndarray,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    baseline_recipe: np.ndarray,
    baseline_delta_e: float,
    config: MaterialInverseRefinementConfig,
    workspace: _InverseRefinementWorkspace,
) -> tuple[np.ndarray, np.ndarray, float, bool]:
    bottom_recipes = workspace.bottom_recipes
    top_recipes = workspace.top_recipes
    bottom_linear = workspace.bottom_linear
    top_alpha = workspace.top_alpha
    top_beta = workspace.top_beta

    required = compute_required_bottom_colors(
        srgb_to_linear(target_srgb.reshape(1, 3))[0],
        top_alpha,
        top_beta,
    )
    valid_top_mask = required_bottom_color_mask(
        required,
        tolerance=float(config.required_color_tolerance),
    )
    if not np.any(valid_top_mask):
        baseline_srgb = linear_to_srgb_uint8(
            _predict_linear_for_recipes(
                recipes=baseline_recipe.reshape(1, -1),
                materials=materials,
                layer_height_mm=float(layer_height_mm),
                substrate=substrate,
            )
        )[0]
        return baseline_srgb, baseline_recipe.copy(), float(baseline_delta_e), False

    valid_required = required[valid_top_mask]
    valid_top_alpha = top_alpha[valid_top_mask]
    valid_top_beta = top_beta[valid_top_mask]
    valid_top_recipes = top_recipes[valid_top_mask]

    neighbor_count = min(
        max(1, int(config.refine_bottom_neighbors)),
        bottom_linear.shape[0],
    )
    _distances, bottom_indices = workspace.bottom_tree.query(
        valid_required,
        k=neighbor_count,
    )
    if neighbor_count == 1:
        bottom_indices = bottom_indices[:, None]

    final_linear = (
        valid_top_alpha[:, None, :] * bottom_linear[bottom_indices]
        + valid_top_beta[:, None, :]
    )
    flat_linear = final_linear.reshape(-1, 3)
    flat_srgb = linear_to_srgb_uint8(flat_linear)
    flat_lab = rgb_to_lab(flat_srgb).astype(np.float64)
    target_lab = rgb_to_lab(target_srgb.reshape(1, 3).astype(np.uint8))[0]
    delta = np.linalg.norm(flat_lab - target_lab.reshape(1, 3), axis=1)
    best_flat = int(np.argmin(delta))
    best_delta = float(delta[best_flat])

    if best_delta >= float(baseline_delta_e) - 1e-12:
        baseline_srgb = linear_to_srgb_uint8(
            _predict_linear_for_recipes(
                recipes=baseline_recipe.reshape(1, -1),
                materials=materials,
                layer_height_mm=float(layer_height_mm),
                substrate=substrate,
            )
        )[0]
        return baseline_srgb, baseline_recipe.copy(), float(baseline_delta_e), False

    top_index = best_flat // neighbor_count
    neighbor_index = best_flat % neighbor_count
    bottom_index = int(bottom_indices[top_index, neighbor_index])
    recipe = np.concatenate(
        [bottom_recipes[bottom_index], valid_top_recipes[top_index]]
    ).astype(np.int32, copy=False)
    verified_linear = _predict_linear_for_recipes(
        recipes=recipe.reshape(1, -1),
        materials=materials,
        layer_height_mm=float(layer_height_mm),
        substrate=substrate,
    )
    verified_srgb = linear_to_srgb_uint8(verified_linear)[0]
    verified_lab = rgb_to_lab(verified_srgb.reshape(1, 3)).astype(np.float64)[0]
    verified_delta = float(np.linalg.norm(verified_lab - target_lab))
    if verified_delta >= float(baseline_delta_e) - 1e-12:
        baseline_srgb = linear_to_srgb_uint8(
            _predict_linear_for_recipes(
                recipes=baseline_recipe.reshape(1, -1),
                materials=materials,
                layer_height_mm=float(layer_height_mm),
                substrate=substrate,
            )
        )[0]
        return baseline_srgb, baseline_recipe.copy(), float(baseline_delta_e), False

    return verified_srgb, recipe, verified_delta, True


def _best_refined_row(
    *,
    target_srgb: np.ndarray,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    baseline_recipe: np.ndarray,
    baseline_delta_e: float,
    config: MaterialInverseRefinementConfig,
) -> tuple[np.ndarray, np.ndarray, float, bool]:
    """Refine one row with a freshly built workspace.

    This compatibility helper intentionally retains the old one-row behavior;
    batched callers use grouped workspaces through :func:`refine_material_matches`.
    """

    subset = _select_material_subset(
        target_srgb=target_srgb,
        baseline_recipe=baseline_recipe,
        materials=materials,
        max_materials=min(int(config.max_refine_materials), len(materials)),
    )
    key = _workspace_key(
        subset=subset,
        layer_count=int(layer_count),
        config=config,
    )
    workspace = _build_workspace(
        key=key,
        materials=materials,
        layer_height_mm=float(layer_height_mm),
        substrate=substrate,
    )
    return _best_refined_row_with_workspace(
        target_srgb=target_srgb,
        materials=materials,
        layer_count=int(layer_count),
        layer_height_mm=float(layer_height_mm),
        substrate=substrate,
        baseline_recipe=baseline_recipe,
        baseline_delta_e=float(baseline_delta_e),
        config=config,
        workspace=workspace,
    )


def _query_bottom_neighbors(
    *,
    workspace: _InverseRefinementWorkspace,
    required_bottom: np.ndarray,
    neighbor_count: int,
    workers: int,
) -> np.ndarray:
    """Query exact bottom neighbours, tolerating older SciPy releases."""

    query_kwargs = {
        "k": int(neighbor_count),
        "eps": 0.0,
        "workers": max(1, int(workers)),
    }
    try:
        _distances, indices = workspace.bottom_tree.query(
            required_bottom,
            **query_kwargs,
        )
    except TypeError:
        query_kwargs.pop("workers")
        _distances, indices = workspace.bottom_tree.query(
            required_bottom,
            **query_kwargs,
        )
    result = np.asarray(indices, dtype=np.int64)
    if int(neighbor_count) == 1:
        result = result[:, None]
    return result


def _refine_workspace_row_block(
    *,
    row_indices: tuple[int, ...],
    targets: np.ndarray,
    baseline_recipes: np.ndarray,
    baseline_delta_e: np.ndarray,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    config: MaterialInverseRefinementConfig,
    workspace: _InverseRefinementWorkspace,
    query_workers: int,
) -> list[tuple[int, np.ndarray, np.ndarray, float, bool]]:
    """Refine one memory-bounded block without changing row semantics."""

    if not row_indices:
        return []

    block_indices = np.asarray(row_indices, dtype=np.intp)
    block_targets = targets[block_indices]
    block_baseline_recipes = baseline_recipes[block_indices]
    block_baseline_delta = baseline_delta_e[block_indices]
    baseline_linear = _predict_linear_for_recipes(
        recipes=block_baseline_recipes,
        materials=materials,
        layer_height_mm=float(layer_height_mm),
        substrate=substrate,
    )
    baseline_srgb = linear_to_srgb_uint8(baseline_linear)
    results = [
        (
            int(row_index),
            baseline_srgb[position],
            block_baseline_recipes[position].copy(),
            float(block_baseline_delta[position]),
            False,
        )
        for position, row_index in enumerate(row_indices)
    ]

    target_linear = srgb_to_linear(block_targets)
    target_lab = rgb_to_lab(block_targets).astype(np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        required = (
            target_linear[:, None, :] - workspace.top_beta[None, :, :]
        ) / workspace.top_alpha[None, :, :]
    tolerance = float(config.required_color_tolerance)
    valid_mask = (
        np.isfinite(required).all(axis=2)
        & (required >= -tolerance).all(axis=2)
        & (required <= 1.0 + tolerance).all(axis=2)
    )
    valid_rows, valid_top_indices = np.nonzero(valid_mask)
    if valid_rows.size == 0:
        return results

    neighbor_count = min(
        max(1, int(config.refine_bottom_neighbors)),
        workspace.bottom_linear.shape[0],
    )
    bottom_indices = _query_bottom_neighbors(
        workspace=workspace,
        required_bottom=required[valid_rows, valid_top_indices],
        neighbor_count=neighbor_count,
        workers=query_workers,
    )
    final_linear = (
        workspace.top_alpha[valid_top_indices, None, :]
        * workspace.bottom_linear[bottom_indices]
        + workspace.top_beta[valid_top_indices, None, :]
    )
    flat_srgb = linear_to_srgb_uint8(final_linear.reshape(-1, 3))
    flat_lab = rgb_to_lab(flat_srgb).astype(np.float64)
    candidate_targets = np.repeat(
        target_lab[valid_rows],
        neighbor_count,
        axis=0,
    )
    candidate_delta = np.linalg.norm(
        flat_lab - candidate_targets,
        axis=1,
    )
    valid_counts = np.bincount(
        valid_rows,
        minlength=len(row_indices),
    )
    candidate_offsets = np.concatenate(
        [
            np.zeros((1,), dtype=np.int64),
            np.cumsum(valid_counts * neighbor_count, dtype=np.int64),
        ],
    )

    provisional_positions: list[int] = []
    provisional_recipes: list[np.ndarray] = []
    for position in range(len(row_indices)):
        start = int(candidate_offsets[position])
        stop = int(candidate_offsets[position + 1])
        if start == stop:
            continue
        best_flat = start + int(np.argmin(candidate_delta[start:stop]))
        if (
            float(candidate_delta[best_flat])
            >= float(block_baseline_delta[position]) - 1e-12
        ):
            continue
        query_index, neighbor_index = divmod(best_flat, neighbor_count)
        bottom_index = int(bottom_indices[query_index, neighbor_index])
        top_index = int(valid_top_indices[query_index])
        provisional_positions.append(position)
        provisional_recipes.append(
            np.concatenate(
                [
                    workspace.bottom_recipes[bottom_index],
                    workspace.top_recipes[top_index],
                ],
            ).astype(np.int32, copy=False),
        )

    if not provisional_recipes:
        return results

    recipe_batch = np.stack(provisional_recipes).astype(
        np.int32,
        copy=False,
    )
    verified_linear = _predict_linear_for_recipes(
        recipes=recipe_batch,
        materials=materials,
        layer_height_mm=float(layer_height_mm),
        substrate=substrate,
    )
    verified_srgb = linear_to_srgb_uint8(verified_linear)
    verified_lab = rgb_to_lab(verified_srgb).astype(np.float64)
    verified_delta = np.linalg.norm(
        verified_lab - target_lab[provisional_positions],
        axis=1,
    )
    for candidate_index, position in enumerate(provisional_positions):
        row_delta = float(verified_delta[candidate_index])
        if row_delta >= float(block_baseline_delta[position]) - 1e-12:
            continue
        results[position] = (
            int(row_indices[position]),
            verified_srgb[candidate_index],
            recipe_batch[candidate_index],
            row_delta,
            True,
        )
    return results


def _refine_workspace_group(
    *,
    key: _InverseRefinementWorkspaceKey,
    row_indices: tuple[int, ...],
    targets: np.ndarray,
    baseline_recipes: np.ndarray,
    baseline_delta_e: np.ndarray,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    config: MaterialInverseRefinementConfig,
) -> list[tuple[int, np.ndarray, np.ndarray, float, bool]]:
    """Build one workspace and refine its rows without mutating shared output."""

    workspace = _build_workspace(
        key=key,
        materials=materials,
        layer_height_mm=float(layer_height_mm),
        substrate=substrate,
    )
    results: list[tuple[int, np.ndarray, np.ndarray, float, bool]] = []
    for row_index in row_indices:
        row_srgb, row_recipe, row_delta, did_improve = (
            _best_refined_row_with_workspace(
                target_srgb=targets[row_index],
                materials=materials,
                layer_count=int(layer_count),
                layer_height_mm=float(layer_height_mm),
                substrate=substrate,
                baseline_recipe=baseline_recipes[row_index],
                baseline_delta_e=float(baseline_delta_e[row_index]),
                config=config,
                workspace=workspace,
            )
        )
        results.append(
            (
                row_index,
                row_srgb,
                row_recipe,
                row_delta,
                did_improve,
            ),
        )
    return results


def _refine_workspace_group_in_worker(
    **kwargs,
) -> list[tuple[int, np.ndarray, np.ndarray, float, bool]]:
    """Run one refinement group inside the nested-parallelism guard."""

    with task_parallelism_worker_scope():
        return _refine_workspace_group(**kwargs)


def refine_material_matches(
    *,
    target_srgb: np.ndarray,
    baseline_matched_srgb: np.ndarray,
    baseline_recipes: np.ndarray,
    baseline_delta_e: np.ndarray,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    config: MaterialInverseRefinementConfig | None = None,
    parallelism: int = 1,
) -> MaterialInverseRefinementResult:
    """Improve material matches with bounded affine inverse search.
    使用有预算的 affine 反向搜索改善耗材匹配。

    Args:
        target_srgb: ``(C, 3)`` target colors. (目标色)
        baseline_matched_srgb: ``(C, 3)`` baseline matched colors. (基线匹配色)
        baseline_recipes: ``(C, N)`` baseline recipes. (基线配方)
        baseline_delta_e: ``(C,)`` baseline Delta-E. (基线 Delta-E)
        materials: Canonical material parameters. (规范顺序耗材参数)
        layer_count: Recipe layer count. (配方层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"`` substrate. (基底)
        config: Optional refinement config. (可选精修配置)
        parallelism: Maximum independent subset groups to process at once.
            (同时处理的独立耗材子集组上限)

    Returns:
        MaterialInverseRefinementResult: Baseline-or-better matches.
            (不差于基线的匹配结果)
    """
    cfg = config or MaterialInverseRefinementConfig()
    targets = np.asarray(target_srgb, dtype=np.uint8)
    matched = np.asarray(baseline_matched_srgb, dtype=np.uint8).copy()
    recipes = np.asarray(baseline_recipes, dtype=np.int32).copy()
    delta_e = np.asarray(baseline_delta_e, dtype=np.float64).copy()
    improved = np.zeros((targets.shape[0],), dtype=bool)

    if not cfg.enabled or targets.shape[0] == 0:
        return MaterialInverseRefinementResult(matched, recipes, delta_e, improved)
    if targets.ndim != 2 or targets.shape[1] != 3:
        raise ValueError("target_srgb must have shape (C, 3)")
    if recipes.shape != (targets.shape[0], int(layer_count)):
        raise ValueError("baseline_recipes shape does not match targets/layer_count")

    grouped_rows: dict[_InverseRefinementWorkspaceKey, list[int]] = {}
    max_materials = min(int(cfg.max_refine_materials), len(materials))
    for row_index in range(targets.shape[0]):
        subset = _select_material_subset(
            target_srgb=targets[row_index],
            baseline_recipe=recipes[row_index],
            materials=materials,
            max_materials=max_materials,
        )
        key = _workspace_key(
            subset=subset,
            layer_count=int(layer_count),
            config=cfg,
        )
        grouped_rows.setdefault(key, []).append(row_index)

    group_items = [
        (key, tuple(row_indices))
        for key, row_indices in grouped_rows.items()
    ]
    worker_count = min(
        max(1, int(parallelism)),
        len(group_items),
    )
    if worker_count > 1:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(
                    _refine_workspace_group_in_worker,
                    key=key,
                    row_indices=row_indices,
                    targets=targets,
                    baseline_recipes=recipes,
                    baseline_delta_e=delta_e,
                    materials=materials,
                    layer_count=int(layer_count),
                    layer_height_mm=float(layer_height_mm),
                    substrate=substrate,
                    config=cfg,
                )
                for key, row_indices in group_items
            ]
            grouped_results = [future.result() for future in futures]
    else:
        grouped_results = [
            _refine_workspace_group(
                key=key,
                row_indices=row_indices,
                targets=targets,
                baseline_recipes=recipes,
                baseline_delta_e=delta_e,
                materials=materials,
                layer_count=int(layer_count),
                layer_height_mm=float(layer_height_mm),
                substrate=substrate,
                config=cfg,
            )
            for key, row_indices in group_items
        ]

    for group_results in grouped_results:
        for (
            row_index,
            row_srgb,
            row_recipe,
            row_delta,
            did_improve,
        ) in group_results:
            if did_improve:
                matched[row_index] = row_srgb
                recipes[row_index] = row_recipe
                delta_e[row_index] = row_delta
                improved[row_index] = True

    return MaterialInverseRefinementResult(matched, recipes, delta_e, improved)
