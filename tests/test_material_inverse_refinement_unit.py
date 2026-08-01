"""Unit tests for target-aware material inverse refinement."""

from __future__ import annotations

import numpy as np
import pytest

import core.material_inverse_refinement as inverse_refinement
from core.material_color_solver import (
    DEFAULT_LAYER_HEIGHT_MM,
    MaterialParams,
    forward_model,
    linear_to_srgb_uint8,
    rgb_to_lab,
)
from core.material_inverse_refinement import (
    MaterialInverseRefinementConfig,
    compute_required_bottom_colors,
    refine_material_matches,
    required_bottom_color_mask,
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


RED = _mat("Red", E=(0.65, 0.04, 0.04), k=(3.5, 3.5, 3.5))
BLUE = _mat("Blue", E=(0.04, 0.08, 0.65), k=(3.5, 3.5, 3.5))
WHITE = _mat("White", E=(0.95, 0.95, 0.95), k=(0.4, 0.4, 0.4))
GREEN = _mat("Green", E=(0.08, 0.65, 0.08), k=(3.5, 3.5, 3.5))
PALETTE = [RED, BLUE, WHITE, GREEN]


def _srgb_for_recipe(recipe: np.ndarray) -> np.ndarray:
    linear = forward_model(
        recipe,
        PALETTE,
        DEFAULT_LAYER_HEIGHT_MM,
        substrate_linear=np.ones(3, dtype=np.float64),
    )
    return linear_to_srgb_uint8(linear.reshape(1, 3))[0]


def _delta_e(target_srgb: np.ndarray, matched_srgb: np.ndarray) -> float:
    labs = rgb_to_lab(np.vstack([target_srgb, matched_srgb]).astype(np.uint8))
    return float(np.linalg.norm(labs[0] - labs[1]))


def test_required_bottom_color_reconstructs_target_for_valid_suffix() -> None:
    target_linear = np.asarray([[0.45, 0.25, 0.2]], dtype=np.float64)
    top_alpha = np.asarray([[0.8, 0.7, 0.6]], dtype=np.float64)
    top_beta = np.asarray([[0.05, 0.04, 0.03]], dtype=np.float64)

    required = compute_required_bottom_colors(target_linear[0], top_alpha, top_beta)

    assert np.isfinite(required).all()
    reconstructed = top_alpha * required + top_beta
    np.testing.assert_allclose(reconstructed, target_linear, atol=1e-12)


def test_out_of_bounds_required_bottom_colors_are_rejected() -> None:
    target_linear = np.asarray([0.02, 0.02, 0.02], dtype=np.float64)
    top_alpha = np.asarray(
        [
            [0.7, 0.7, 0.7],
            [0.9, 0.9, 0.9],
        ],
        dtype=np.float64,
    )
    top_beta = np.asarray(
        [
            [0.9, 0.9, 0.9],
            [0.01, 0.01, 0.01],
        ],
        dtype=np.float64,
    )

    required = compute_required_bottom_colors(target_linear, top_alpha, top_beta)
    mask = required_bottom_color_mask(required, tolerance=0.0)

    np.testing.assert_array_equal(mask, np.asarray([False, True]))


def test_refinement_candidate_is_forward_verified() -> None:
    target_recipe = np.asarray([0, 1, 1, 2], dtype=np.int32)
    target_srgb = _srgb_for_recipe(target_recipe).reshape(1, 3)
    baseline_recipe = np.asarray([[0, 0, 0, 0]], dtype=np.int32)
    baseline_srgb = _srgb_for_recipe(baseline_recipe[0]).reshape(1, 3)
    baseline_delta = np.asarray(
        [_delta_e(target_srgb[0], baseline_srgb[0])],
        dtype=np.float64,
    )

    result = refine_material_matches(
        target_srgb=target_srgb,
        baseline_matched_srgb=baseline_srgb,
        baseline_recipes=baseline_recipe,
        baseline_delta_e=baseline_delta,
        materials=PALETTE,
        layer_count=4,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
        config=MaterialInverseRefinementConfig(
            max_refine_materials=4,
            max_refine_bottom_prefixes=16,
            max_refine_top_suffixes=16,
            refine_bottom_neighbors=2,
        ),
    )

    verified_srgb = _srgb_for_recipe(result.recipes[0])
    np.testing.assert_array_equal(result.matched_srgb[0], verified_srgb)
    assert result.delta_e[0] <= baseline_delta[0]
    assert result.improved_mask[0]


def test_refinement_never_worsens_baseline_match() -> None:
    baseline_recipe = np.asarray([[2, 2, 2, 2]], dtype=np.int32)
    baseline_srgb = _srgb_for_recipe(baseline_recipe[0]).reshape(1, 3)
    target_srgb = baseline_srgb.copy()
    baseline_delta = np.asarray([0.0], dtype=np.float64)

    result = refine_material_matches(
        target_srgb=target_srgb,
        baseline_matched_srgb=baseline_srgb,
        baseline_recipes=baseline_recipe,
        baseline_delta_e=baseline_delta,
        materials=PALETTE,
        layer_count=4,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
        config=MaterialInverseRefinementConfig(
            max_refine_materials=4,
            max_refine_bottom_prefixes=16,
            max_refine_top_suffixes=16,
            refine_bottom_neighbors=2,
        ),
    )

    np.testing.assert_array_equal(result.matched_srgb, baseline_srgb)
    np.testing.assert_array_equal(result.recipes, baseline_recipe)
    np.testing.assert_allclose(result.delta_e, baseline_delta)
    np.testing.assert_array_equal(result.improved_mask, np.asarray([False]))


def test_refinement_reuses_one_workspace_for_shared_subset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two target rows sharing a subset build only bottom and top candidates."""

    target_recipes = np.asarray(
        [
            [0, 1, 1, 2],
            [3, 1, 0, 2],
        ],
        dtype=np.int32,
    )
    target_srgb = np.vstack([_srgb_for_recipe(row) for row in target_recipes])
    baseline_recipes = np.zeros((2, 4), dtype=np.int32)
    baseline_matched = np.vstack(
        [_srgb_for_recipe(row) for row in baseline_recipes],
    )
    baseline_delta = np.asarray(
        [
            _delta_e(target_srgb[index], baseline_matched[index])
            for index in range(2)
        ],
        dtype=np.float64,
    )
    config = MaterialInverseRefinementConfig(
        max_refine_materials=4,
        max_refine_bottom_prefixes=16,
        max_refine_top_suffixes=16,
        refine_bottom_neighbors=2,
    )
    independent = [
        refine_material_matches(
            target_srgb=target_srgb[index : index + 1],
            baseline_matched_srgb=baseline_matched[index : index + 1],
            baseline_recipes=baseline_recipes[index : index + 1],
            baseline_delta_e=baseline_delta[index : index + 1],
            materials=PALETTE,
            layer_count=4,
            layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
            substrate="white",
            config=config,
        )
        for index in range(2)
    ]

    original_generate = inverse_refinement.generate_candidate_recipes
    generation_calls: list[tuple[int, int, int, int]] = []

    def _record_generation(
        *,
        material_count: int,
        layer_count: int,
        candidate_budget: int,
        seed: int,
    ):
        generation_calls.append(
            (material_count, layer_count, candidate_budget, seed),
        )
        return original_generate(
            material_count=material_count,
            layer_count=layer_count,
            candidate_budget=candidate_budget,
            seed=seed,
        )

    monkeypatch.setattr(
        inverse_refinement,
        "generate_candidate_recipes",
        _record_generation,
    )

    batched = refine_material_matches(
        target_srgb=target_srgb,
        baseline_matched_srgb=baseline_matched,
        baseline_recipes=baseline_recipes,
        baseline_delta_e=baseline_delta,
        materials=PALETTE,
        layer_count=4,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
        config=config,
    )

    assert len(generation_calls) == 2
    for index, expected in enumerate(independent):
        np.testing.assert_array_equal(
            batched.matched_srgb[index],
            expected.matched_srgb[0],
        )
        np.testing.assert_array_equal(
            batched.recipes[index],
            expected.recipes[0],
        )
        assert batched.delta_e[index] == expected.delta_e[0]
        assert batched.improved_mask[index] == expected.improved_mask[0]


def test_refinement_builds_each_subset_once_and_parallel_results_stay_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Independent subset groups may run concurrently without reordering rows."""

    baseline_recipes = np.asarray(
        [
            [0, 1, 0, 1],
            [0, 1, 0, 1],
            [2, 3, 2, 3],
            [2, 3, 2, 3],
        ],
        dtype=np.int32,
    )
    target_recipes = np.asarray(
        [
            [1, 0, 1, 0],
            [0, 0, 1, 1],
            [3, 2, 3, 2],
            [2, 2, 3, 3],
        ],
        dtype=np.int32,
    )
    target_srgb = np.vstack([_srgb_for_recipe(row) for row in target_recipes])
    baseline_matched = np.vstack(
        [_srgb_for_recipe(row) for row in baseline_recipes],
    )
    baseline_delta = np.asarray(
        [
            _delta_e(target_srgb[index], baseline_matched[index])
            for index in range(4)
        ],
        dtype=np.float64,
    )
    config = MaterialInverseRefinementConfig(
        max_refine_materials=2,
        max_refine_bottom_prefixes=4,
        max_refine_top_suffixes=4,
        refine_bottom_neighbors=2,
    )
    serial = refine_material_matches(
        target_srgb=target_srgb,
        baseline_matched_srgb=baseline_matched,
        baseline_recipes=baseline_recipes,
        baseline_delta_e=baseline_delta,
        materials=PALETTE,
        layer_count=4,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
        config=config,
    )

    original_generate = inverse_refinement.generate_candidate_recipes
    generation_calls = 0

    def _record_generation(**kwargs):
        nonlocal generation_calls
        generation_calls += 1
        return original_generate(**kwargs)

    monkeypatch.setattr(
        inverse_refinement,
        "generate_candidate_recipes",
        _record_generation,
    )

    parallel = refine_material_matches(
        target_srgb=target_srgb,
        baseline_matched_srgb=baseline_matched,
        baseline_recipes=baseline_recipes,
        baseline_delta_e=baseline_delta,
        materials=PALETTE,
        layer_count=4,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
        config=config,
        parallelism=2,
    )

    assert generation_calls == 4
    np.testing.assert_array_equal(parallel.matched_srgb, serial.matched_srgb)
    np.testing.assert_array_equal(parallel.recipes, serial.recipes)
    np.testing.assert_array_equal(parallel.delta_e, serial.delta_e)
    np.testing.assert_array_equal(parallel.improved_mask, serial.improved_mask)


def _shared_workspace_fixture():
    target_recipes = np.asarray(
        [
            [0, 1, 1, 2],
            [3, 1, 0, 2],
            [1, 3, 2, 0],
            [2, 2, 2, 2],
            [0, 0, 0, 0],
        ],
        dtype=np.int32,
    )
    targets = np.vstack([_srgb_for_recipe(row) for row in target_recipes])
    baseline_recipes = np.zeros((len(targets), 4), dtype=np.int32)
    baseline_matched = np.vstack(
        [_srgb_for_recipe(row) for row in baseline_recipes],
    )
    baseline_delta = np.asarray(
        [
            _delta_e(targets[index], baseline_matched[index])
            for index in range(len(targets))
        ],
        dtype=np.float64,
    )
    config = MaterialInverseRefinementConfig(
        max_refine_materials=4,
        max_refine_bottom_prefixes=16,
        max_refine_top_suffixes=16,
        refine_bottom_neighbors=2,
    )
    key = inverse_refinement._workspace_key(
        subset=np.arange(4, dtype=np.int32),
        layer_count=4,
        config=config,
    )
    workspace = inverse_refinement._build_workspace(
        key=key,
        materials=PALETTE,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
    )
    return (
        targets,
        baseline_recipes,
        baseline_matched,
        baseline_delta,
        config,
        workspace,
    )


def test_workspace_row_block_matches_one_row_reference_exactly() -> None:
    (
        targets,
        baseline_recipes,
        _baseline_matched,
        baseline_delta,
        config,
        workspace,
    ) = _shared_workspace_fixture()
    expected = [
        inverse_refinement._best_refined_row_with_workspace(
            target_srgb=targets[index],
            materials=PALETTE,
            layer_count=4,
            layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
            substrate="white",
            baseline_recipe=baseline_recipes[index],
            baseline_delta_e=float(baseline_delta[index]),
            config=config,
            workspace=workspace,
        )
        for index in range(len(targets))
    ]

    actual = inverse_refinement._refine_workspace_row_block(
        row_indices=tuple(range(len(targets))),
        targets=targets,
        baseline_recipes=baseline_recipes,
        baseline_delta_e=baseline_delta,
        materials=PALETTE,
        layer_count=4,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
        config=config,
        workspace=workspace,
        query_workers=1,
    )

    assert len(actual) == len(expected)
    for row_index, expected_row in enumerate(expected):
        (
            actual_index,
            actual_rgb,
            actual_recipe,
            actual_delta,
            actual_improved,
        ) = actual[row_index]
        assert actual_index == row_index
        np.testing.assert_array_equal(actual_rgb, expected_row[0])
        np.testing.assert_array_equal(actual_recipe, expected_row[1])
        assert actual_delta == expected_row[2]
        assert actual_improved == expected_row[3]


def test_workspace_row_block_retains_baseline_when_no_suffix_is_valid() -> None:
    (
        targets,
        baseline_recipes,
        baseline_matched,
        baseline_delta,
        config,
        workspace,
    ) = _shared_workspace_fixture()
    invalid_workspace = inverse_refinement._InverseRefinementWorkspace(
        bottom_recipes=workspace.bottom_recipes,
        top_recipes=workspace.top_recipes,
        bottom_linear=workspace.bottom_linear,
        top_alpha=np.zeros_like(workspace.top_alpha),
        top_beta=np.full_like(workspace.top_beta, 2.0),
        bottom_tree=workspace.bottom_tree,
    )

    actual = inverse_refinement._refine_workspace_row_block(
        row_indices=(0, 1),
        targets=targets,
        baseline_recipes=baseline_recipes,
        baseline_delta_e=baseline_delta,
        materials=PALETTE,
        layer_count=4,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
        config=config,
        workspace=invalid_workspace,
        query_workers=1,
    )

    for position, (_row_index, rgb, recipe, delta, improved) in enumerate(actual):
        np.testing.assert_array_equal(rgb, baseline_matched[position])
        np.testing.assert_array_equal(recipe, baseline_recipes[position])
        assert delta == baseline_delta[position]
        assert not improved


def test_workspace_group_preserves_exact_rows_across_partial_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        targets,
        baseline_recipes,
        _baseline_matched,
        baseline_delta,
        config,
        _workspace,
    ) = _shared_workspace_fixture()
    observed_blocks: list[tuple[int, ...]] = []
    original = inverse_refinement._refine_workspace_row_block

    def _record_block(**kwargs):
        observed_blocks.append(tuple(kwargs["row_indices"]))
        return original(**kwargs)

    monkeypatch.setattr(
        inverse_refinement,
        "_refinement_row_block_size",
        lambda **_kwargs: 2,
    )
    monkeypatch.setattr(
        inverse_refinement,
        "_refine_workspace_row_block",
        _record_block,
    )

    result = inverse_refinement._refine_workspace_group(
        key=inverse_refinement._workspace_key(
            subset=np.arange(4, dtype=np.int32),
            layer_count=4,
            config=config,
        ),
        row_indices=tuple(range(len(targets))),
        targets=targets,
        baseline_recipes=baseline_recipes,
        baseline_delta_e=baseline_delta,
        materials=PALETTE,
        layer_count=4,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
        config=config,
        query_workers=1,
    )

    assert observed_blocks == [(0, 1), (2, 3), (4,)]
    assert [row[0] for row in result] == [0, 1, 2, 3, 4]


@pytest.mark.parametrize(
    ("parallelism", "group_count", "expected"),
    [
        (1, 1, (1, 1)),
        (8, 1, (1, 8)),
        (8, 2, (2, 4)),
        (8, 3, (3, 2)),
        (4, 8, (4, 1)),
    ],
)
def test_refinement_worker_allocation_stays_within_budget(
    parallelism: int,
    group_count: int,
    expected: tuple[int, int],
) -> None:
    allocation = inverse_refinement._refinement_worker_allocation(
        parallelism=parallelism,
        group_count=group_count,
    )

    assert allocation == expected
    assert allocation[0] * allocation[1] <= max(1, parallelism)


def test_single_workspace_query_workers_preserve_serial_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        targets,
        baseline_recipes,
        baseline_matched,
        baseline_delta,
        config,
        _workspace,
    ) = _shared_workspace_fixture()
    serial = refine_material_matches(
        target_srgb=targets,
        baseline_matched_srgb=baseline_matched,
        baseline_recipes=baseline_recipes,
        baseline_delta_e=baseline_delta,
        materials=PALETTE,
        layer_count=4,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
        config=config,
        parallelism=1,
    )
    observed_workers: list[int] = []
    original_query = inverse_refinement._query_bottom_neighbors

    def _record_query_workers(**kwargs):
        observed_workers.append(int(kwargs["workers"]))
        return original_query(**kwargs)

    monkeypatch.setattr(
        inverse_refinement,
        "_query_bottom_neighbors",
        _record_query_workers,
    )
    parallel = refine_material_matches(
        target_srgb=targets,
        baseline_matched_srgb=baseline_matched,
        baseline_recipes=baseline_recipes,
        baseline_delta_e=baseline_delta,
        materials=PALETTE,
        layer_count=4,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
        config=config,
        parallelism=4,
    )

    assert observed_workers and set(observed_workers) == {4}
    np.testing.assert_array_equal(parallel.matched_srgb, serial.matched_srgb)
    np.testing.assert_array_equal(parallel.recipes, serial.recipes)
    np.testing.assert_array_equal(parallel.delta_e, serial.delta_e)
    np.testing.assert_array_equal(parallel.improved_mask, serial.improved_mask)
