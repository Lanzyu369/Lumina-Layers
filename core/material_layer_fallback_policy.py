"""Helpers for deciding when the cross-layer fallback has full coverage."""

from __future__ import annotations

def recipe_space_size(material_count: int, layer_count: int) -> int:
    """Return the complete ``material_count ** layer_count`` recipe space."""
    total = 1
    if material_count <= 0 or layer_count <= 0:
        return 0
    for _ in range(int(layer_count)):
        total *= int(material_count)
    return int(total)


def runtime_covers_full_recipe_space(
    runtime: object | None,
    *,
    material_count: int,
    layer_count: int,
) -> bool:
    """Return whether a solver runtime represents every recipe for M materials."""
    if runtime is None:
        return False
    total = recipe_space_size(material_count, layer_count)
    if total <= 0:
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
    )
