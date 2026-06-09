"""Policy helpers for material cross-layer fallback guards."""

from __future__ import annotations

DEFAULT_CROSS_N_FALLBACK_MAX_COMBINATIONS = 2_000_000
"""Largest full recipe space allowed to trigger the cross-N fallback."""


def capped_recipe_space_size(
    material_count: int,
    layer_count: int,
    *,
    cap: int = DEFAULT_CROSS_N_FALLBACK_MAX_COMBINATIONS,
) -> int:
    """Return ``material_count ** layer_count`` without overflowing the cap."""
    total = 1
    if material_count <= 0 or layer_count <= 0:
        return 0
    for _ in range(int(layer_count)):
        total *= int(material_count)
        if total > int(cap):
            return int(cap) + 1
    return int(total)


def runtime_covers_full_recipe_space(
    runtime: object | None,
    *,
    material_count: int,
    layer_count: int,
    max_combinations: int = DEFAULT_CROSS_N_FALLBACK_MAX_COMBINATIONS,
) -> bool:
    """Return whether a solver runtime represents every recipe for M materials."""
    if runtime is None:
        return False
    total = capped_recipe_space_size(
        material_count,
        layer_count,
        cap=max_combinations,
    )
    if total <= 0 or total > int(max_combinations):
        return False
    mode = str(getattr(runtime, "mode", "") or "").lower()
    if mode == "exact":
        return True
    if mode != "candidate_hybrid":
        return False
    try:
        candidate_count = int(getattr(runtime, "valid_cell_count", 0))
    except (TypeError, ValueError):
        return False
    return candidate_count >= total


def should_run_cross_n_fallback(
    *,
    solver_path: str,
    runtime: object | None,
    unique_color_count: int,
    material_count: int,
    layer_count: int,
    max_combinations: int = DEFAULT_CROSS_N_FALLBACK_MAX_COMBINATIONS,
) -> bool:
    """Decide whether it is safe and useful to run the not-worse fallback."""
    if unique_color_count <= 0 or layer_count <= 5:
        return False
    if solver_path not in ("cache", "cache_built_on_the_fly"):
        return True
    return runtime_covers_full_recipe_space(
        runtime,
        material_count=material_count,
        layer_count=layer_count,
        max_combinations=max_combinations,
    )
