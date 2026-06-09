"""Unit tests for target-aware material inverse refinement."""

from __future__ import annotations

import numpy as np

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
