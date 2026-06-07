"""Unit tests for bounded material candidate runtime."""

from __future__ import annotations

import numpy as np

from core.material_candidate_cache import (
    DEFAULT_CANDIDATE_BUILD_MEMORY_BUDGET_BYTES,
    MaterialCandidateCacheConfig,
    estimate_candidate_cache_memory,
)
from core.material_candidate_sampling import generate_candidate_recipes
from core.material_color_solver import MaterialParams, forward_model, linear_to_srgb_uint8


def _mat(
    name: str,
    E: tuple[float, float, float],
    k: tuple[float, float, float],
) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(E, dtype=np.float64),
        k=np.asarray(k, dtype=np.float64),
        C0_white=np.asarray((1.0, 1.0, 1.0), dtype=np.float64),
        estimated_rgb=np.asarray([int(round(255 * c)) for c in E], dtype=np.uint8),
    )


RED = _mat("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0))
BLUE = _mat("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0))
WHITE = _mat("White", E=(0.95, 0.95, 0.95), k=(0.5, 0.5, 0.5))
GREEN = _mat("Green", E=(0.1, 0.6, 0.1), k=(4.0, 4.0, 4.0))
BLACK = _mat("Black", E=(0.05, 0.05, 0.05), k=(6.0, 6.0, 6.0))
SMALL_PALETTE = [RED, BLUE, WHITE]
MEDIUM_PALETTE = [RED, BLUE, WHITE, GREEN, BLACK]


def test_default_candidate_config_uses_8g_build_budget() -> None:
    config = MaterialCandidateCacheConfig.default_persisted()

    assert config.candidate_budget == 4_194_304
    assert config.candidate_pool_multiplier == 8
    assert config.batch_recipe_count == 524_288
    assert config.build_memory_budget_bytes == 8 * 1024 * 1024 * 1024
    assert DEFAULT_CANDIDATE_BUILD_MEMORY_BUDGET_BYTES == 8 * 1024 * 1024 * 1024


def test_default_candidate_memory_estimate_fits_8g_budget() -> None:
    config = MaterialCandidateCacheConfig.default_persisted()

    report = estimate_candidate_cache_memory(
        candidate_budget=config.candidate_budget,
        layer_count=10,
        material_count=22,
    )

    assert report.candidate_budget == 4_194_304
    assert report.estimated_peak_bytes < config.build_memory_budget_bytes


def test_sobol_candidate_generation_is_deterministic_and_bounded() -> None:
    first = generate_candidate_recipes(
        material_count=5,
        layer_count=8,
        candidate_budget=128,
        seed=1234,
    )
    second = generate_candidate_recipes(
        material_count=5,
        layer_count=8,
        candidate_budget=128,
        seed=1234,
    )

    np.testing.assert_array_equal(first.recipes, second.recipes)
    assert first.recipes.shape == (128, 8)
    assert first.recipes.dtype == np.uint16
    assert int(first.recipes.min()) >= 0
    assert int(first.recipes.max()) < 5
    assert first.pinned_mask.shape == (128,)


def test_uniform_recipes_are_pinned_before_sobol_candidates() -> None:
    generated = generate_candidate_recipes(
        material_count=5,
        layer_count=6,
        candidate_budget=32,
        seed=9,
    )

    expected_uniforms = np.asarray([[i] * 6 for i in range(5)], dtype=np.uint16)
    np.testing.assert_array_equal(generated.recipes[:5], expected_uniforms)
    np.testing.assert_array_equal(generated.pinned_mask[:5], np.ones(5, dtype=bool))


def test_candidate_generation_covers_entire_space_when_budget_allows() -> None:
    generated = generate_candidate_recipes(
        material_count=3,
        layer_count=3,
        candidate_budget=27,
        seed=42,
    )

    all_expected = {
        tuple(recipe)
        for recipe in np.asarray(
            np.meshgrid(
                np.arange(3, dtype=np.uint16),
                np.arange(3, dtype=np.uint16),
                np.arange(3, dtype=np.uint16),
                indexing="ij",
            )
        )
        .reshape(3, -1)
        .T
    }

    assert generated.recipes.shape == (27, 3)
    assert {tuple(recipe) for recipe in generated.recipes} == all_expected


def test_candidate_generation_pins_pair_ramp_and_top_heavy_recipes() -> None:
    generated = generate_candidate_recipes(
        material_count=2,
        layer_count=4,
        candidate_budget=8,
        seed=5,
    )

    recipes = {tuple(recipe) for recipe in generated.recipes}
    assert (0, 0, 0, 1) in recipes
    assert (0, 0, 1, 1) in recipes
    assert (0, 1, 0, 1) in recipes
    assert (1, 1, 1, 0) in recipes
    assert (1, 1, 0, 0) in recipes
    assert (1, 0, 1, 0) in recipes


def test_candidate_runtime_lookup_returns_solver_cache_shaped_values() -> None:
    from core.material_candidate_cache import build_material_candidate_runtime

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=64, seed=77),
    )

    targets = np.asarray([[180, 80, 60], [40, 70, 180]], dtype=np.uint8)
    matched_rgb, recipes, delta_e = runtime.lookup(targets, SMALL_PALETTE)

    assert runtime.mode == "candidate_hybrid"
    assert runtime.layer_count == 5
    assert runtime.valid_cell_count == 64
    assert matched_rgb.shape == (2, 3)
    assert matched_rgb.dtype == np.uint8
    assert recipes.shape == (2, 5)
    assert recipes.dtype == np.int32
    assert delta_e.shape == (2,)
    assert delta_e.dtype == np.float64


def test_candidate_runtime_rebinds_recipes_to_user_material_order() -> None:
    from core.material_candidate_cache import build_material_candidate_runtime

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=64, seed=88),
    )

    target = np.asarray([[180, 80, 60]], dtype=np.uint8)
    _, original_recipes, _ = runtime.lookup(target, SMALL_PALETTE)
    original_names = [SMALL_PALETTE[index].name for index in original_recipes[0]]

    shuffled = [SMALL_PALETTE[2], SMALL_PALETTE[0], SMALL_PALETTE[1]]
    _, shuffled_recipes, _ = runtime.lookup(target, shuffled)
    shuffled_names = [shuffled[index].name for index in shuffled_recipes[0]]

    assert original_names == shuffled_names


def test_candidate_runtime_inverse_refinement_improves_sparse_baseline() -> None:
    from core.material_candidate_cache import build_material_candidate_runtime

    target_recipe = np.asarray([0, 1, 1, 2], dtype=np.int32)
    target_linear = forward_model(
        target_recipe,
        MEDIUM_PALETTE,
        0.08,
        substrate_linear=np.ones(3, dtype=np.float64),
    )
    target_srgb = linear_to_srgb_uint8(target_linear.reshape(1, 3))

    baseline_runtime = build_material_candidate_runtime(
        materials=MEDIUM_PALETTE,
        layer_count=4,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            candidate_budget=5,
            seed=11,
            enable_inverse_refinement=False,
        ),
    )
    refined_runtime = build_material_candidate_runtime(
        materials=MEDIUM_PALETTE,
        layer_count=4,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            candidate_budget=5,
            seed=11,
            enable_inverse_refinement=True,
            max_refine_materials=5,
            max_refine_bottom_prefixes=25,
            max_refine_top_suffixes=25,
            refine_bottom_neighbors=2,
        ),
    )

    _, _baseline_recipe, baseline_delta = baseline_runtime.lookup(
        target_srgb,
        MEDIUM_PALETTE,
    )
    refined_rgb, refined_recipe, refined_delta = refined_runtime.lookup(
        target_srgb,
        MEDIUM_PALETTE,
    )

    assert refined_delta[0] < baseline_delta[0]
    np.testing.assert_array_equal(refined_rgb, target_srgb)
    assert refined_recipe.shape == (1, 4)
