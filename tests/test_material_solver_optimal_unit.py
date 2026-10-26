"""Unit tests for the optimal (MITM + transmittance-cutoff B&B) material color solver.

Covers:
- Affine decomposition helpers: ``_compute_material_affines``, ``_enumerate_cumulative_affines``
- High-level solver: ``solve_image_colors_optimal`` (guaranteed-optimal variant)
- Equivalence properties (vs. brute-force on small cases, vs. beam-search on all cases)
- Transmittance cutoff / buffer-layer semantics

The beam search in ``solve_image_colors`` is a non-admissible heuristic that may
miss globally better recipes. The optimal solver must be at least as good as
beam search on every target color.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from core.material_color_solver import (
    DEFAULT_LAYER_HEIGHT_MM,
    MaterialParams,
    _compute_material_affines,
    _enumerate_cumulative_affines,
    forward_model,
    rgb_to_lab,
    solve_image_colors,
    solve_image_colors_optimal,
)


# ---------------------------------------------------------------------------
# Test fixtures — synthetic 3-material palette and larger 6-material palette
# ---------------------------------------------------------------------------


def _mat(name: str, E: tuple, k: tuple) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(E, dtype=np.float64),
        k=np.asarray(k, dtype=np.float64),
        C0_white=np.asarray((1.0, 1.0, 1.0), dtype=np.float64),
        estimated_rgb=np.asarray(
            [int(round(255 * c)) for c in E], dtype=np.uint8
        ),
    )


# Small 3-material palette — tractable for brute force up to N=6
RED = _mat("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0))
BLUE = _mat("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0))
WHITE = _mat("White", E=(0.95, 0.95, 0.95), k=(0.5, 0.5, 0.5))

# Larger 6-material palette — used for beam-vs-optimal comparison
GREEN = _mat("Green", E=(0.1, 0.6, 0.1), k=(4.0, 4.0, 4.0))
YELLOW = _mat("Yellow", E=(0.7, 0.6, 0.05), k=(4.0, 4.0, 4.0))
BLACK = _mat("Black", E=(0.05, 0.05, 0.05), k=(6.0, 6.0, 6.0))

SMALL_PALETTE = [RED, BLUE, WHITE]
MEDIUM_PALETTE = [RED, BLUE, WHITE, GREEN, YELLOW, BLACK]


def _brute_force_optimal(
    target_srgb: np.ndarray,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
) -> tuple[np.ndarray, float]:
    """Naive brute-force optimal solver for small N, used as ground truth.

    Enumerates all ``M ** layer_count`` ordered recipes and returns the one
    with minimum CIE76 ΔE to the target color.
    """
    substrate_linear = (
        np.ones(3, dtype=np.float64)
        if substrate == "white"
        else np.zeros(3, dtype=np.float64)
    )
    target_lab = rgb_to_lab(target_srgb.reshape(1, 3))[0]
    best_de = np.inf
    best_recipe = np.zeros(layer_count, dtype=np.int32)
    M = len(materials)
    for combo in itertools.product(range(M), repeat=layer_count):
        recipe = np.asarray(combo, dtype=np.int32)
        pred_linear = forward_model(recipe, materials, layer_height_mm, substrate_linear)
        pred_srgb = np.clip(
            np.round(
                (
                    np.where(
                        pred_linear <= 0.0031308,
                        12.92 * pred_linear,
                        1.055 * np.power(np.clip(pred_linear, 0.0, 1.0), 1.0 / 2.4) - 0.055,
                    )
                )
                * 255.0
            ),
            0,
            255,
        ).astype(np.uint8)
        pred_lab = rgb_to_lab(pred_srgb.reshape(1, 3))[0]
        de = float(np.linalg.norm(pred_lab - target_lab))
        if de < best_de:
            best_de = de
            best_recipe = recipe.copy()
    return best_recipe, best_de


# ---------------------------------------------------------------------------
# Affine decomposition primitive tests
# ---------------------------------------------------------------------------


class TestComputeMaterialAffines:
    def test_a_and_b_shapes(self):
        affines = _compute_material_affines(SMALL_PALETTE, 0.08)
        assert affines.a.shape == (3, 3)
        assert affines.b.shape == (3, 3)

    def test_a_equals_exp_minus_kt(self):
        affines = _compute_material_affines(SMALL_PALETTE, 0.08)
        for i, mat in enumerate(SMALL_PALETTE):
            np.testing.assert_allclose(affines.a[i], np.exp(-mat.k * 0.08))

    def test_b_equals_E_times_one_minus_a(self):
        affines = _compute_material_affines(SMALL_PALETTE, 0.08)
        for i, mat in enumerate(SMALL_PALETTE):
            a = np.exp(-mat.k * 0.08)
            expected_b = mat.E * (1 - a)
            np.testing.assert_allclose(affines.b[i], expected_b)

    def test_single_layer_affine_reproduces_forward_model(self):
        """T(C) = a*C + b should equal beer_lambert_layer output."""
        affines = _compute_material_affines(SMALL_PALETTE, 0.08)
        substrate = np.asarray([1.0, 0.5, 0.3], dtype=np.float64)
        for i, mat in enumerate(SMALL_PALETTE):
            predicted = affines.a[i] * substrate + affines.b[i]
            expected = forward_model(
                np.asarray([i], dtype=np.int32), SMALL_PALETTE, 0.08, substrate
            )
            np.testing.assert_allclose(predicted, expected, atol=1e-10)


class TestEnumerateCumulativeAffines:
    def test_depth_zero_gives_identity(self):
        affines = _compute_material_affines(SMALL_PALETTE, 0.08)
        alpha, beta, recipes = _enumerate_cumulative_affines(affines, 0)
        assert alpha.shape == (1, 3)
        assert beta.shape == (1, 3)
        assert recipes.shape == (1, 0)
        np.testing.assert_allclose(alpha[0], 1.0)
        np.testing.assert_allclose(beta[0], 0.0)

    def test_depth_one_matches_single_affine(self):
        affines = _compute_material_affines(SMALL_PALETTE, 0.08)
        alpha, beta, recipes = _enumerate_cumulative_affines(affines, 1)
        M = len(SMALL_PALETTE)
        assert alpha.shape == (M, 3)
        assert recipes.shape == (M, 1)
        for i in range(M):
            np.testing.assert_allclose(alpha[i], affines.a[i])
            np.testing.assert_allclose(beta[i], affines.b[i])

    def test_output_count_matches_m_power_depth(self):
        affines = _compute_material_affines(SMALL_PALETTE, 0.08)
        for depth in range(0, 5):
            alpha, beta, recipes = _enumerate_cumulative_affines(affines, depth)
            assert alpha.shape[0] == len(SMALL_PALETTE) ** depth
            assert recipes.shape == (len(SMALL_PALETTE) ** depth, depth)

    def test_applied_to_substrate_matches_forward_model(self):
        """Cumulative affine applied to substrate must equal forward_model output."""
        affines = _compute_material_affines(SMALL_PALETTE, 0.08)
        depth = 4
        substrate = np.asarray([1.0, 1.0, 1.0], dtype=np.float64)
        alpha, beta, recipes = _enumerate_cumulative_affines(affines, depth)
        for i in range(recipes.shape[0]):
            predicted = alpha[i] * substrate + beta[i]
            expected = forward_model(
                recipes[i].astype(np.int32), SMALL_PALETTE, 0.08, substrate
            )
            np.testing.assert_allclose(predicted, expected, atol=1e-10)

    def test_recipe_order_is_bottom_first(self):
        """recipes[i, 0] is the bottom (first applied) layer; recipes[i, -1] is top."""
        affines = _compute_material_affines([RED, BLUE], 0.08)
        _, _, recipes = _enumerate_cumulative_affines(affines, 2)
        # Expect the 4 combos: (R,R) (R,B) (B,R) (B,B) in some order.
        combos = {tuple(r) for r in recipes.tolist()}
        assert combos == {(0, 0), (0, 1), (1, 0), (1, 1)}


# ---------------------------------------------------------------------------
# solve_image_colors_optimal — contract and invariants
# ---------------------------------------------------------------------------


class TestSolveImageColorsOptimalContract:
    def test_returns_three_arrays_with_correct_shapes(self):
        targets = np.asarray([[200, 100, 50]], dtype=np.uint8)
        matched, recipes, de = solve_image_colors_optimal(
            targets, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08
        )
        assert matched.shape == (1, 3)
        assert matched.dtype == np.uint8
        assert recipes.shape == (1, 5)
        assert de.shape == (1,)
        assert de.dtype in (np.float32, np.float64)

    def test_empty_targets_returns_empty_arrays(self):
        targets = np.zeros((0, 3), dtype=np.uint8)
        matched, recipes, de = solve_image_colors_optimal(
            targets, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08
        )
        assert matched.shape == (0, 3)
        assert recipes.shape == (0, 5)
        assert de.shape == (0,)

    def test_empty_materials_raises(self):
        targets = np.asarray([[200, 100, 50]], dtype=np.uint8)
        with pytest.raises(ValueError, match="materials"):
            solve_image_colors_optimal(
                targets, [], layer_count=5, layer_height_mm=0.08
            )

    def test_rejects_out_of_range_layer_count(self):
        targets = np.asarray([[200, 100, 50]], dtype=np.uint8)
        with pytest.raises(ValueError):
            solve_image_colors_optimal(
                targets, SMALL_PALETTE, layer_count=1, layer_height_mm=0.08
            )
        with pytest.raises(ValueError):
            solve_image_colors_optimal(
                targets, SMALL_PALETTE, layer_count=99, layer_height_mm=0.08
            )

    def test_rejects_unknown_layer_height(self):
        targets = np.asarray([[200, 100, 50]], dtype=np.uint8)
        with pytest.raises(ValueError):
            solve_image_colors_optimal(
                targets, SMALL_PALETTE, layer_count=5, layer_height_mm=0.123
            )

    def test_deterministic(self):
        """Same inputs must produce identical outputs on repeated calls."""
        targets = np.asarray(
            [[200, 100, 50], [10, 20, 30], [128, 128, 128]], dtype=np.uint8
        )
        r1 = solve_image_colors_optimal(
            targets, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08
        )
        r2 = solve_image_colors_optimal(
            targets, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08
        )
        np.testing.assert_array_equal(r1[0], r2[0])
        np.testing.assert_array_equal(r1[1], r2[1])
        np.testing.assert_allclose(r1[2], r2[2])

    def test_substrate_black_gives_different_result_than_white(self):
        targets = np.asarray([[50, 50, 50]], dtype=np.uint8)
        white_result = solve_image_colors_optimal(
            targets, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white",
        )
        black_result = solve_image_colors_optimal(
            targets, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="black",
        )
        # Recipes and/or ΔE should differ
        assert (
            not np.array_equal(white_result[1], black_result[1])
            or not np.allclose(white_result[2], black_result[2])
        )


# ---------------------------------------------------------------------------
# Optimality properties
# ---------------------------------------------------------------------------


class TestOptimalityVsBruteForce:
    """For small N × M the optimal solver must match exhaustive enumeration."""

    @pytest.mark.parametrize(
        "target_srgb",
        [
            np.asarray([200, 100, 50], dtype=np.uint8),
            np.asarray([10, 20, 200], dtype=np.uint8),
            np.asarray([240, 240, 240], dtype=np.uint8),
            np.asarray([40, 160, 80], dtype=np.uint8),
        ],
    )
    def test_matches_brute_force_N5_M3(self, target_srgb):
        targets = target_srgb.reshape(1, 3)
        bf_recipe, bf_de = _brute_force_optimal(
            target_srgb, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white",
        )
        matched, recipes, de = solve_image_colors_optimal(
            targets, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
        )
        # ΔE should match brute force within a tiny numerical tolerance
        assert de[0] <= bf_de + 1e-3, (
            f"Optimal solver found worse ΔE than brute force: "
            f"optimal={de[0]:.4f} vs brute={bf_de:.4f}"
        )


class TestOptimalityVsBeamSearch:
    """Optimal solver must be at least as good as beam search on every target."""

    def test_optimal_le_beam_on_medium_palette_N6(self):
        rng = np.random.default_rng(42)
        targets = rng.integers(0, 256, size=(24, 3), dtype=np.uint8)
        _, _, beam_de = solve_image_colors(
            targets, MEDIUM_PALETTE, layer_count=6, layer_height_mm=0.08,
        )
        _, _, optimal_de = solve_image_colors_optimal(
            targets, MEDIUM_PALETTE, layer_count=6, layer_height_mm=0.08,
        )
        # Optimal should be <= beam for every target (within tiny numerical slack)
        diffs = optimal_de - beam_de
        worst = float(diffs.max())
        assert worst <= 1e-3, (
            f"Optimal found at least one worse target than beam: worst diff = {worst:.4f}"
        )

    def test_optimal_strictly_better_on_hard_targets(self):
        """On at least one hard target, optimal should beat beam search.

        This targets the leading-white-layer regression the solver was built
        to fix. We pick a target that requires several white base layers.
        """
        rng = np.random.default_rng(123)
        # Generate 50 random targets to find a case where beam is suboptimal
        targets = rng.integers(0, 256, size=(50, 3), dtype=np.uint8)
        _, _, beam_de = solve_image_colors(
            targets, MEDIUM_PALETTE, layer_count=7, layer_height_mm=0.08,
        )
        _, _, optimal_de = solve_image_colors_optimal(
            targets, MEDIUM_PALETTE, layer_count=7, layer_height_mm=0.08,
        )
        # Count cases where optimal improved over beam
        improved_count = int(np.sum(optimal_de < beam_de - 0.01))
        assert improved_count >= 1, (
            "Expected optimal to strictly beat beam on at least one target; "
            f"got zero improvements across 50 random targets (beam mean={beam_de.mean():.3f}, "
            f"optimal mean={optimal_de.mean():.3f})"
        )


class TestTransmittanceCutoff:
    """Buffer-layer slack must not regress ΔE below noise floor."""

    def test_buffer_layers_zero_matches_brute_force(self):
        """With ``buffer_layers=0`` the cutoff is disabled — must be strictly optimal."""
        target_srgb = np.asarray([180, 120, 80], dtype=np.uint8)
        targets = target_srgb.reshape(1, 3)
        bf_recipe, bf_de = _brute_force_optimal(
            target_srgb, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white",
        )
        _, _, de = solve_image_colors_optimal(
            targets, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            buffer_layers=0,
        )
        assert de[0] <= bf_de + 1e-3

    def test_buffer_layers_one_within_noise_of_brute_force(self):
        """Buffer-layer slack may cost ≤ a small ΔE tolerance vs. brute force."""
        target_srgb = np.asarray([180, 120, 80], dtype=np.uint8)
        targets = target_srgb.reshape(1, 3)
        _, bf_de = _brute_force_optimal(
            target_srgb, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white",
        )
        _, _, de = solve_image_colors_optimal(
            targets, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            buffer_layers=1,
        )
        # Allow up to 1 ΔE slack for 1 buffer layer
        assert de[0] <= bf_de + 1.0

    def test_explicit_alpha_cutoff_overrides_buffer_layers(self):
        """When ``alpha_cutoff`` is explicitly set, it takes precedence."""
        target_srgb = np.asarray([180, 120, 80], dtype=np.uint8)
        targets = target_srgb.reshape(1, 3)
        # With alpha_cutoff=0, the cutoff is fully disabled and the result must
        # match brute force regardless of buffer_layers
        _, _, de = solve_image_colors_optimal(
            targets, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            alpha_cutoff=0.0, buffer_layers=5,  # conflicting; explicit 0 wins
        )
        _, bf_de = _brute_force_optimal(
            target_srgb, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white",
        )
        assert de[0] <= bf_de + 1e-3


class TestForwardModelConsistency:
    """Predicted linear color must match ``forward_model(recipe)`` exactly."""

    def test_matched_rgb_consistent_with_recipe_forward_model(self):
        rng = np.random.default_rng(7)
        targets = rng.integers(0, 256, size=(6, 3), dtype=np.uint8)
        matched, recipes, de = solve_image_colors_optimal(
            targets, MEDIUM_PALETTE, layer_count=5, layer_height_mm=0.08,
        )
        substrate = np.ones(3, dtype=np.float64)
        for i in range(targets.shape[0]):
            predicted_linear = forward_model(
                recipes[i].astype(np.int32), MEDIUM_PALETTE, 0.08, substrate
            )
            # Convert predicted linear to sRGB uint8 and compare to matched
            from core.material_color_solver import linear_to_srgb_uint8
            predicted_srgb = linear_to_srgb_uint8(predicted_linear.reshape(1, 3))[0]
            np.testing.assert_array_equal(
                matched[i], predicted_srgb,
                err_msg=(
                    f"matched[{i}]={matched[i]} but forward_model(recipe)="
                    f"{predicted_srgb} for recipe={recipes[i]}"
                ),
            )
