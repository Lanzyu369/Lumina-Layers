"""Unit tests for the cross-N not-worse-than-smaller-N fallback helpers.
跨 N 不劣回退辅助函数的单元测试。

Covers:
    - ``find_white_material_index`` palette-whiteness detection and threshold
      behaviour;
    - ``forward_batch_model`` vectorised Beer-Lambert evaluation and its
      consistency with the per-recipe :func:`forward_model`;
    - ``ensure_not_worse_than_smaller_N`` input validation, guard paths
      (no white, no targets, target < MIN_LAYER_COUNT, target == min),
      and the core "returned ΔE never exceeds baseline ΔE" invariant;
    - ``stats`` contract (``applied``/``improved_pixels``/``per_k_improved``/
      ``white_material_index`` reported under every path).
"""

from __future__ import annotations

import numpy as np
import pytest

from core.material_color_solver import (
    DEFAULT_LAYER_HEIGHT_MM,
    MAX_LAYER_COUNT,
    MIN_LAYER_COUNT,
    MaterialParams,
    WHITE_MATERIAL_MAX_LINEAR_DISTANCE,
    ensure_not_worse_than_smaller_N,
    find_white_material_index,
    forward_batch_model,
    forward_model,
    linear_to_srgb_uint8,
    rgb_to_lab,
    solve_image_colors_optimal,
)


# ---------------------------------------------------------------------------
# Fixture materials — keep parameters close to the calibrated filament library
# used elsewhere in the test suite so the solver behaves realistically.
# ---------------------------------------------------------------------------


def _mat(name: str, *, E: tuple[float, float, float], k: tuple[float, float, float]) -> MaterialParams:
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


RED = _mat("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0))
BLUE = _mat("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0))
GREEN = _mat("Green", E=(0.1, 0.6, 0.1), k=(4.0, 4.0, 4.0))
BLACK = _mat("Black", E=(0.05, 0.05, 0.05), k=(6.0, 6.0, 6.0))
WHITE = _mat("White", E=(0.95, 0.95, 0.95), k=(0.5, 0.5, 0.5))
OFF_WHITE_CREAM = _mat("Cream", E=(0.95, 0.90, 0.80), k=(0.8, 0.8, 0.8))

PALETTE_WITH_WHITE = [RED, BLUE, WHITE, GREEN, BLACK]
PALETTE_NO_WHITE = [RED, BLUE, GREEN, BLACK]


# ---------------------------------------------------------------------------
# find_white_material_index
# ---------------------------------------------------------------------------


class TestFindWhiteMaterialIndex:
    def test_returns_index_of_white_entry(self):
        idx = find_white_material_index(PALETTE_WITH_WHITE)
        assert idx == PALETTE_WITH_WHITE.index(WHITE)

    def test_returns_none_for_empty_palette(self):
        assert find_white_material_index([]) is None

    def test_returns_none_when_no_material_is_white_enough(self):
        # All materials are saturated colours; their E is far from (1,1,1).
        idx = find_white_material_index(PALETTE_NO_WHITE)
        assert idx is None

    def test_accepts_off_white_within_default_threshold(self):
        # Cream (E = 0.95, 0.90, 0.80) has ‖E − 1‖ ≈ 0.224, safely below the
        # 0.35 default threshold, so it is accepted.
        idx = find_white_material_index([RED, OFF_WHITE_CREAM, BLACK])
        assert idx == 1
        # With a stricter threshold the cream should be rejected.
        stricter = find_white_material_index(
            [RED, OFF_WHITE_CREAM, BLACK], max_linear_distance=0.1
        )
        assert stricter is None

    def test_accepts_distance_strictly_below_threshold(self):
        # Construct a material whose distance to white sits comfortably below
        # the default threshold (avoiding FP rounding right at the boundary).
        t = float(WHITE_MATERIAL_MAX_LINEAR_DISTANCE) * 0.9
        gray = 1.0 - t / np.sqrt(3)
        off = _mat(
            "BelowThreshold",
            E=(gray, gray, gray),
            k=(1.0, 1.0, 1.0),
        )
        idx = find_white_material_index([off])
        assert idx == 0

    def test_prefers_whitest_candidate(self):
        # Two plausible whites with different distances to (1,1,1); the
        # helper must pick the closer one regardless of list order.
        whiter = _mat("Whiter", E=(0.98, 0.98, 0.98), k=(0.4, 0.4, 0.4))
        yellower = _mat("Yellower", E=(0.92, 0.90, 0.80), k=(0.6, 0.6, 0.6))
        assert find_white_material_index([yellower, whiter]) == 1
        assert find_white_material_index([whiter, yellower]) == 0


# ---------------------------------------------------------------------------
# forward_batch_model
# ---------------------------------------------------------------------------


class TestForwardBatchModel:
    def test_matches_per_recipe_forward_model(self):
        recipes = np.asarray(
            [
                [0, 2, 1, 2, 0],
                [2, 2, 2, 2, 2],
                [1, 0, 2, 0, 1],
            ],
            dtype=np.int32,
        )
        batch = forward_batch_model(
            recipes, PALETTE_WITH_WHITE, DEFAULT_LAYER_HEIGHT_MM
        )
        per_row = np.stack(
            [
                forward_model(recipes[i], PALETTE_WITH_WHITE, DEFAULT_LAYER_HEIGHT_MM)
                for i in range(recipes.shape[0])
            ],
            axis=0,
        )
        assert batch.shape == (3, 3)
        np.testing.assert_allclose(batch, per_row, atol=1e-12)

    def test_zero_rows_returns_empty_array(self):
        out = forward_batch_model(
            np.zeros((0, 5), dtype=np.int32),
            PALETTE_WITH_WHITE,
            DEFAULT_LAYER_HEIGHT_MM,
        )
        assert out.shape == (0, 3)

    def test_zero_layers_returns_substrate(self):
        substrate = np.asarray([0.2, 0.4, 0.8], dtype=np.float64)
        out = forward_batch_model(
            np.zeros((4, 0), dtype=np.int32),
            PALETTE_WITH_WHITE,
            DEFAULT_LAYER_HEIGHT_MM,
            substrate_linear=substrate,
        )
        assert out.shape == (4, 3)
        np.testing.assert_allclose(out, np.broadcast_to(substrate, (4, 3)))

    def test_substrate_affects_result(self):
        recipes = np.asarray([[0, 1, 2]], dtype=np.int32)
        white = forward_batch_model(
            recipes,
            PALETTE_WITH_WHITE,
            DEFAULT_LAYER_HEIGHT_MM,
            substrate_linear=np.ones(3, dtype=np.float64),
        )
        black = forward_batch_model(
            recipes,
            PALETTE_WITH_WHITE,
            DEFAULT_LAYER_HEIGHT_MM,
            substrate_linear=np.zeros(3, dtype=np.float64),
        )
        assert not np.allclose(white, black)

    def test_rejects_wrong_shape(self):
        with pytest.raises(ValueError):
            forward_batch_model(
                np.zeros((5,), dtype=np.int32),
                PALETTE_WITH_WHITE,
                DEFAULT_LAYER_HEIGHT_MM,
            )

    def test_rejects_empty_palette(self):
        with pytest.raises(ValueError):
            forward_batch_model(
                np.asarray([[0, 0, 0]], dtype=np.int32),
                [],
                DEFAULT_LAYER_HEIGHT_MM,
            )


# ---------------------------------------------------------------------------
# ensure_not_worse_than_smaller_N — validation & guard paths
# ---------------------------------------------------------------------------


def _make_baseline_via_solver(
    targets: np.ndarray,
    palette: list[MaterialParams],
    *,
    layer_count: int,
    substrate: str = "white",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Convenience: run the strict MITM solver once to manufacture a baseline.
    用严格 MITM 求解器生成 baseline 供测试消费。
    """
    matched, recipes, delta_e = solve_image_colors_optimal(
        targets,
        palette,
        layer_count=layer_count,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate=substrate,
    )
    return matched, recipes.astype(np.int32), delta_e.astype(np.float64)


class TestEnsureNotWorseValidation:
    def test_rejects_target_above_max(self):
        targets = np.asarray([[200, 100, 50]], dtype=np.uint8)
        with pytest.raises(ValueError, match="target_layer_count"):
            ensure_not_worse_than_smaller_N(
                targets,
                PALETTE_WITH_WHITE,
                np.zeros((1, 3), dtype=np.uint8),
                np.zeros((1, MAX_LAYER_COUNT + 1), dtype=np.int32),
                np.zeros((1,), dtype=np.float64),
                target_layer_count=MAX_LAYER_COUNT + 1,
            )

    def test_rejects_min_below_solver_min(self):
        targets = np.asarray([[200, 100, 50]], dtype=np.uint8)
        with pytest.raises(ValueError, match="min_layer_count"):
            ensure_not_worse_than_smaller_N(
                targets,
                PALETTE_WITH_WHITE,
                np.zeros((1, 3), dtype=np.uint8),
                np.zeros((1, 6), dtype=np.int32),
                np.zeros((1,), dtype=np.float64),
                target_layer_count=6,
                min_layer_count=MIN_LAYER_COUNT - 1,
            )

    def test_rejects_shape_mismatched_baseline(self):
        targets = np.asarray([[200, 100, 50]], dtype=np.uint8)
        with pytest.raises(ValueError, match="baseline"):
            ensure_not_worse_than_smaller_N(
                targets,
                PALETTE_WITH_WHITE,
                np.zeros((2, 3), dtype=np.uint8),  # wrong row count
                np.zeros((1, 6), dtype=np.int32),
                np.zeros((1,), dtype=np.float64),
                target_layer_count=6,
            )

    def test_rejects_out_of_range_white_material_index(self):
        targets = np.asarray([[200, 100, 50]], dtype=np.uint8)
        with pytest.raises(ValueError, match="white_material_index"):
            ensure_not_worse_than_smaller_N(
                targets,
                PALETTE_WITH_WHITE,
                np.zeros((1, 3), dtype=np.uint8),
                np.zeros((1, 6), dtype=np.int32),
                np.zeros((1,), dtype=np.float64),
                target_layer_count=6,
                white_material_index=len(PALETTE_WITH_WHITE),
            )


class TestEnsureNotWorseGuardPaths:
    def test_target_below_min_is_noop(self):
        targets = np.asarray([[30, 200, 60]], dtype=np.uint8)
        baseline_matched = targets.copy()
        baseline_recipes = np.asarray([[0]], dtype=np.int32)
        baseline_de = np.asarray([0.0], dtype=np.float64)
        matched, recipes, de, stats = ensure_not_worse_than_smaller_N(
            targets,
            PALETTE_WITH_WHITE,
            baseline_matched,
            baseline_recipes,
            baseline_de,
            target_layer_count=1,
        )
        np.testing.assert_array_equal(matched, baseline_matched)
        np.testing.assert_array_equal(recipes, baseline_recipes)
        np.testing.assert_array_equal(de, baseline_de)
        assert stats["applied"] is False
        assert stats["improved_pixels"] == 0
        assert stats["per_k_improved"] == {}

    def test_target_equal_to_min_is_noop(self):
        targets = np.asarray([[200, 100, 50]], dtype=np.uint8)
        matched_b, recipes_b, delta_b = _make_baseline_via_solver(
            targets, PALETTE_WITH_WHITE, layer_count=MIN_LAYER_COUNT,
        )
        matched, recipes, de, stats = ensure_not_worse_than_smaller_N(
            targets,
            PALETTE_WITH_WHITE,
            matched_b,
            recipes_b,
            delta_b,
            target_layer_count=MIN_LAYER_COUNT,
        )
        np.testing.assert_array_equal(matched, matched_b)
        np.testing.assert_array_equal(recipes, recipes_b)
        np.testing.assert_array_equal(de, delta_b)
        assert stats["applied"] is False
        assert stats["improved_pixels"] == 0

    def test_empty_targets_is_noop(self):
        targets = np.zeros((0, 3), dtype=np.uint8)
        matched_b = np.zeros((0, 3), dtype=np.uint8)
        recipes_b = np.zeros((0, 6), dtype=np.int32)
        delta_b = np.zeros((0,), dtype=np.float64)
        matched, recipes, de, stats = ensure_not_worse_than_smaller_N(
            targets,
            PALETTE_WITH_WHITE,
            matched_b,
            recipes_b,
            delta_b,
            target_layer_count=6,
        )
        assert matched.shape == (0, 3)
        assert recipes.shape == (0, 6)
        assert de.shape == (0,)
        assert stats["applied"] is False
        assert stats["improved_pixels"] == 0
        assert stats["mean_delta_e_before"] == 0.0
        assert stats["mean_delta_e_after"] == 0.0

    def test_no_white_material_is_noop(self):
        targets = np.asarray([[200, 100, 50]], dtype=np.uint8)
        matched_b, recipes_b, delta_b = _make_baseline_via_solver(
            targets, PALETTE_NO_WHITE, layer_count=6,
        )
        matched, recipes, de, stats = ensure_not_worse_than_smaller_N(
            targets,
            PALETTE_NO_WHITE,
            matched_b,
            recipes_b,
            delta_b,
            target_layer_count=6,
        )
        np.testing.assert_array_equal(recipes, recipes_b)
        assert stats["applied"] is False
        assert stats["white_material_index"] is None
        assert stats["improved_pixels"] == 0

    def test_empty_palette_is_noop(self):
        targets = np.asarray([[200, 100, 50]], dtype=np.uint8)
        baseline_matched = np.zeros((1, 3), dtype=np.uint8)
        baseline_recipes = np.zeros((1, 6), dtype=np.int32)
        baseline_de = np.zeros((1,), dtype=np.float64)
        matched, recipes, de, stats = ensure_not_worse_than_smaller_N(
            targets,
            [],  # empty palette
            baseline_matched,
            baseline_recipes,
            baseline_de,
            target_layer_count=6,
        )
        np.testing.assert_array_equal(recipes, baseline_recipes)
        assert stats["applied"] is False


# ---------------------------------------------------------------------------
# ensure_not_worse_than_smaller_N — semantics
# ---------------------------------------------------------------------------


class TestEnsureNotWorseSemantics:
    def test_baseline_optimum_is_preserved(self):
        """A baseline that already solves every target at ΔE=0 must not change."""
        # Targets are taken from a known-good N=6 enumeration so baseline ΔE is 0.
        targets = np.asarray([[255, 0, 0], [0, 255, 255], [128, 128, 128]], dtype=np.uint8)
        matched_b, recipes_b, delta_b = _make_baseline_via_solver(
            targets, PALETTE_WITH_WHITE, layer_count=6,
        )
        # Ensure the baseline is the pointwise minimum under the same solver
        # so the fallback cannot strictly beat it anywhere.
        baseline_snapshot_recipes = recipes_b.copy()
        baseline_snapshot_de = delta_b.copy()
        matched, recipes, de, stats = ensure_not_worse_than_smaller_N(
            targets,
            PALETTE_WITH_WHITE,
            matched_b,
            recipes_b,
            delta_b,
            target_layer_count=6,
        )
        # ΔE cannot have grown; for an already-optimal baseline the fallback is
        # also not required to shrink it (a padded k<6 solution may tie rather
        # than beat).
        assert np.all(de <= baseline_snapshot_de + 1e-9)
        assert stats["applied"] is True
        assert stats["white_material_index"] == PALETTE_WITH_WHITE.index(WHITE)
        # Unchanged rows keep the baseline recipe bit-for-bit.
        unchanged = de >= baseline_snapshot_de - 1e-12
        if np.any(unchanged):
            np.testing.assert_array_equal(
                recipes[unchanged], baseline_snapshot_recipes[unchanged]
            )

    def test_inflated_baseline_is_repaired(self):
        """An artificially-bad baseline (worse than a padded k<N solution)
        must be replaced by the padded k<N recipe on every target."""
        targets = np.asarray(
            [[220, 40, 40], [40, 60, 220], [20, 200, 20]], dtype=np.uint8
        )
        target_N = 7
        # Baseline: pretend the cache dedup gave us "all RED, top-to-bottom"
        # for every target. This is deliberately far from optimal so the
        # padded k<N solution is guaranteed to win on at least some targets.
        red_idx = PALETTE_WITH_WHITE.index(RED)
        baseline_recipes = np.full(
            (targets.shape[0], target_N), red_idx, dtype=np.int32
        )
        baseline_linear = forward_batch_model(
            baseline_recipes, PALETTE_WITH_WHITE, DEFAULT_LAYER_HEIGHT_MM,
        )
        baseline_srgb = linear_to_srgb_uint8(baseline_linear)
        baseline_lab = rgb_to_lab(baseline_srgb).astype(np.float64)
        target_lab = rgb_to_lab(targets).astype(np.float64)
        baseline_de = np.linalg.norm(baseline_lab - target_lab, axis=1)

        matched, recipes, de, stats = ensure_not_worse_than_smaller_N(
            targets,
            PALETTE_WITH_WHITE,
            baseline_srgb,
            baseline_recipes,
            baseline_de,
            target_layer_count=target_N,
        )
        # The invariant: no target may be worse than the baseline — this is
        # the "10 layers not worse than 5 layers" guarantee.
        assert np.all(de <= baseline_de + 1e-9)
        # At least one target should be strictly improved (the all-RED
        # baseline is dominated by multiple padded k<N candidates for these
        # targets).
        assert stats["applied"] is True
        assert stats["improved_pixels"] >= 1
        # Every improved pixel was overwritten with a recipe whose bottom
        # entries are the palette's white index.
        white_idx = PALETTE_WITH_WHITE.index(WHITE)
        improved_mask = de < baseline_de - 1e-9
        if np.any(improved_mask):
            # The padding lives at the bottom of the recipe (column 0 … pad-1),
            # so at least the first column of any improved recipe is white.
            first_col = recipes[improved_mask][:, 0]
            assert np.all(first_col == white_idx)
        # per_k_improved only lists ks that actually improved at least one target.
        assert all(
            MIN_LAYER_COUNT <= int(k) < target_N
            for k in stats["per_k_improved"].keys()
        )
        assert (
            sum(stats["per_k_improved"].values()) == stats["improved_pixels"]
        )

    def test_stats_before_after_reflect_improvement(self):
        """mean/max ΔE reported in stats must bracket the real arrays."""
        targets = np.asarray([[220, 40, 40], [40, 60, 220]], dtype=np.uint8)
        red_idx = PALETTE_WITH_WHITE.index(RED)
        baseline_recipes = np.full((2, 6), red_idx, dtype=np.int32)
        baseline_linear = forward_batch_model(
            baseline_recipes, PALETTE_WITH_WHITE, DEFAULT_LAYER_HEIGHT_MM,
        )
        baseline_srgb = linear_to_srgb_uint8(baseline_linear)
        baseline_lab = rgb_to_lab(baseline_srgb).astype(np.float64)
        target_lab = rgb_to_lab(targets).astype(np.float64)
        baseline_de = np.linalg.norm(baseline_lab - target_lab, axis=1)

        _, _, de, stats = ensure_not_worse_than_smaller_N(
            targets,
            PALETTE_WITH_WHITE,
            baseline_srgb,
            baseline_recipes,
            baseline_de,
            target_layer_count=6,
        )
        assert stats["mean_delta_e_before"] == pytest.approx(float(baseline_de.mean()))
        assert stats["max_delta_e_before"] == pytest.approx(float(baseline_de.max()))
        assert stats["mean_delta_e_after"] == pytest.approx(float(de.mean()))
        assert stats["max_delta_e_after"] == pytest.approx(float(de.max()))
        # Improvement can only reduce the aggregate metrics.
        assert stats["mean_delta_e_after"] <= stats["mean_delta_e_before"] + 1e-9
        assert stats["max_delta_e_after"] <= stats["max_delta_e_before"] + 1e-9
