"""Unit tests for bounded material candidate runtime."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from core.material_candidate_cache import (
    DEFAULT_CANDIDATE_BUILD_MEMORY_BUDGET_BYTES,
    MaterialCandidateCacheConfig,
    build_material_candidate_runtime,
    estimate_candidate_cache_memory,
)
from core.material_candidate_sampling import generate_candidate_recipes
from core.material_color_solver import (
    MaterialParams,
    forward_model,
    linear_to_srgb_uint8,
)


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
    preview_config = MaterialCandidateCacheConfig.preview_safe()

    assert config.candidate_budget == 4_194_304
    assert config.candidate_pool_multiplier == 8
    assert config.batch_recipe_count == 524_288
    assert config.build_memory_budget_bytes == 8 * 1024 * 1024 * 1024
    assert DEFAULT_CANDIDATE_BUILD_MEMORY_BUDGET_BYTES == 8 * 1024 * 1024 * 1024
    assert preview_config.candidate_budget == 1_048_576
    assert preview_config.candidate_pool_multiplier == 1


def test_default_candidate_memory_estimate_fits_8g_budget() -> None:
    config = MaterialCandidateCacheConfig.default_persisted()

    report = estimate_candidate_cache_memory(
        candidate_budget=config.candidate_budget,
        layer_count=10,
        material_count=22,
    )

    assert report.candidate_budget == 4_194_304
    assert report.estimated_peak_bytes < config.build_memory_budget_bytes


def test_candidate_memory_estimate_uses_runtime_uint16_recipe_rows() -> None:
    report = estimate_candidate_cache_memory(
        candidate_budget=1024,
        layer_count=10,
        material_count=22,
    )

    expected_recipe_bytes = 1024 * 10 * np.dtype(np.uint16).itemsize
    assert report.final_runtime_bytes >= expected_recipe_bytes


def test_candidate_runtime_build_rejects_over_budget_configuration() -> None:
    config = MaterialCandidateCacheConfig(
        candidate_budget=1024,
        build_memory_budget_bytes=1,
    )

    with pytest.raises(ValueError, match="candidate runtime build exceeds memory budget"):
        build_material_candidate_runtime(
            materials=SMALL_PALETTE,
            layer_count=5,
            layer_height_mm=0.08,
            substrate="white",
            config=config,
        )


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


def test_candidate_generation_does_not_request_double_sized_sobol_pool(
    monkeypatch,
) -> None:
    import core.material_candidate_sampling as sampling

    requested_counts: list[int] = []
    original = sampling._low_discrepancy_recipes

    def _recording_low_discrepancy(*args, **kwargs):
        requested_counts.append(int(kwargs["count"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(sampling, "_low_discrepancy_recipes", _recording_low_discrepancy)

    generated = sampling.generate_candidate_recipes(
        material_count=12,
        layer_count=8,
        candidate_budget=4096,
        seed=123,
    )

    assert generated.recipes.shape[0] == 4096
    assert requested_counts
    assert max(requested_counts) <= 4096


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
        candidate_budget=10,
        seed=5,
    )

    recipes = {tuple(recipe) for recipe in generated.recipes}
    assert (0, 0, 0, 1) in recipes
    assert (0, 0, 1, 1) in recipes
    assert (0, 1, 0, 1) in recipes
    assert (1, 1, 1, 0) in recipes
    assert (1, 1, 0, 0) in recipes
    assert (1, 0, 1, 0) in recipes


def test_candidate_generation_pins_multiple_top_heavy_depths() -> None:
    generated = generate_candidate_recipes(
        material_count=2,
        layer_count=6,
        candidate_budget=16,
        seed=5,
    )

    recipes = {tuple(recipe) for recipe in generated.recipes}
    assert (0, 0, 0, 0, 0, 1) in recipes
    assert (0, 0, 0, 0, 1, 1) in recipes
    assert (0, 0, 0, 1, 1, 1) in recipes
    assert (1, 1, 1, 1, 1, 0) in recipes
    assert (1, 1, 1, 1, 0, 0) in recipes
    assert (1, 1, 1, 0, 0, 0) in recipes


def test_candidate_runtime_lookup_returns_solver_cache_shaped_values() -> None:
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


def test_candidate_runtime_lookup_honors_hue_reranking(monkeypatch) -> None:
    import core.material_candidate_cache as candidate_cache

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=64, seed=77),
    )
    calls = {"count": 0}

    def _rerank_stub(target_lab, candidate_lab, candidate_delta_e, hue_weight):
        calls["count"] += 1
        return np.zeros(target_lab.shape[0], dtype=np.int64)

    monkeypatch.setattr(
        candidate_cache,
        "_hue_aware_rerank",
        _rerank_stub,
        raising=False,
    )

    runtime.lookup(
        np.asarray([[180, 80, 60], [40, 70, 180]], dtype=np.uint8),
        SMALL_PALETTE,
        hue_weight=0.75,
    )

    assert calls["count"] == 1


def test_candidate_runtime_lookup_honors_neighbor_coherence(monkeypatch) -> None:
    import core.material_candidate_cache as candidate_cache

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=64, seed=77),
    )
    calls = {"count": 0}

    def _coherence_stub(**kwargs):
        calls["count"] += 1
        return kwargs["matched_rgb"], kwargs["recipes_user_order"], kwargs["delta_e"]

    monkeypatch.setattr(
        candidate_cache,
        "_neighbor_coherence_refine",
        _coherence_stub,
        raising=False,
    )

    runtime.lookup(
        np.asarray([[180, 80, 60], [185, 82, 62]], dtype=np.uint8),
        SMALL_PALETTE,
        neighbor_coherence=0.8,
    )

    assert calls["count"] == 1


def test_candidate_runtime_neighbor_coherence_uses_local_candidate_pool(
    monkeypatch,
) -> None:
    import core.material_candidate_cache as candidate_cache

    runtime = build_material_candidate_runtime(
        materials=MEDIUM_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            candidate_budget=256,
            seed=77,
            enable_inverse_refinement=False,
        ),
    )
    observed_pool_sizes: list[int] = []

    def _coherence_stub(**kwargs):
        observed_pool_sizes.append(int(kwargs["all_lab"].shape[0]))
        return kwargs["matched_rgb"], kwargs["recipes_user_order"], kwargs["delta_e"]

    monkeypatch.setattr(
        candidate_cache,
        "_neighbor_coherence_refine",
        _coherence_stub,
        raising=False,
    )

    runtime.lookup(
        np.asarray([[180, 80, 60], [185, 82, 62]], dtype=np.uint8),
        MEDIUM_PALETTE,
        neighbor_coherence=0.8,
    )

    assert observed_pool_sizes
    assert max(observed_pool_sizes) <= 2 * 64
    assert max(observed_pool_sizes) < runtime.valid_cell_count


def test_candidate_runtime_uses_candidate_pool_multiplier_for_coverage_selection(
    monkeypatch,
) -> None:
    import core.material_candidate_cache as candidate_cache

    requested_counts: list[int] = []
    original = candidate_cache._low_discrepancy_recipes

    def _recording_low_discrepancy(*args, **kwargs):
        requested_counts.append(int(kwargs["count"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(
        candidate_cache,
        "_low_discrepancy_recipes",
        _recording_low_discrepancy,
    )

    runtime = build_material_candidate_runtime(
        materials=MEDIUM_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            candidate_budget=128,
            candidate_pool_multiplier=3,
            batch_recipe_count=16,
            seed=77,
        ),
    )

    assert runtime.valid_cell_count == 128
    assert sum(requested_counts) >= 64


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


def test_candidate_cache_file_path_uses_hybrid_budget_stem(tmp_path: Path) -> None:
    from core.material_candidate_cache import candidate_cache_file_path

    path = candidate_cache_file_path(
        SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        candidate_budget=64,
        cache_root=tmp_path,
    )

    assert path.name.endswith("-hybrid-v2-b64.npz")
    assert "-g" not in path.stem


def test_candidate_runtime_save_load_roundtrip(tmp_path: Path) -> None:
    from core.material_candidate_cache import load_material_candidate_runtime, save_material_candidate_runtime

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=32, seed=44),
    )

    npz_path = save_material_candidate_runtime(runtime, cache_root=tmp_path)
    loaded = load_material_candidate_runtime(
        SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        candidate_budget=32,
        cache_root=tmp_path,
    )

    assert npz_path.exists()
    assert loaded is not None
    np.testing.assert_array_equal(loaded.candidate_recipes, runtime.candidate_recipes)
    np.testing.assert_array_equal(loaded.achieved_srgb, runtime.achieved_srgb)
    np.testing.assert_array_equal(loaded.achieved_lab, runtime.achieved_lab)
    np.testing.assert_array_equal(loaded.pinned_mask, runtime.pinned_mask)
    assert loaded.metadata["schema_version"] == "2.0"
    assert loaded.metadata["mode"] == "candidate_hybrid"
    assert loaded.metadata["candidate_budget"] == 32
    assert loaded.metadata["candidate_count"] == runtime.valid_cell_count
    assert loaded.metadata["canonical_material_directory_names"] == [
        "blue",
        "white",
        "red",
    ]
    assert loaded.metadata["candidate_pool_multiplier"] == 8
    assert loaded.metadata["build_memory_budget_bytes"] == (
        DEFAULT_CANDIDATE_BUILD_MEMORY_BUDGET_BYTES
    )
    assert loaded.metadata["batch_recipe_count"] == 524_288


def test_load_candidate_runtime_returns_none_when_absent_or_palette_mismatch(
    tmp_path: Path,
) -> None:
    from core.material_candidate_cache import (
        build_material_candidate_runtime,
        load_material_candidate_runtime,
        save_material_candidate_runtime,
    )

    assert (
        load_material_candidate_runtime(
            SMALL_PALETTE,
            layer_count=5,
            layer_height_mm=0.08,
            substrate="white",
            candidate_budget=32,
            cache_root=tmp_path,
        )
        is None
    )

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=32, seed=44),
    )
    save_material_candidate_runtime(runtime, cache_root=tmp_path)
    red_alt = _mat("RedAlt", E=(0.7, 0.05, 0.05), k=(4.0, 4.0, 4.0))
    mismatched_palette = [red_alt, BLUE, WHITE]

    assert (
        load_material_candidate_runtime(
            mismatched_palette,
            layer_count=5,
            layer_height_mm=0.08,
            substrate="white",
            candidate_budget=32,
            cache_root=tmp_path,
        )
        is None
    )
