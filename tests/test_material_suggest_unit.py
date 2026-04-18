"""Unit tests for the achievable-color suggester (MITM + cache top-K).

Covers:
- ``ColorSuggestion`` and ``suggest_colors_for_target`` contract
- Ranking, deduplication by Lab spacing, and ΔE monotonicity
- ``MaterialSolverCache.lookup_top_k`` contract and palette rebinding
- Parity between cache top-K and direct MITM top-K (within grid tolerance)
- Fallback guard: overflow on very large ``M ** N`` enumerations
"""

from __future__ import annotations

import numpy as np
import pytest

from core.material_cache import build_material_solver_cache
from core.material_color_solver import (
    DEFAULT_SUGGEST_MIN_SPACING,
    ColorSuggestion,
    MaterialParams,
    _greedy_lab_spacing_dedup,
    forward_model,
    linear_to_srgb_uint8,
    rgb_to_lab,
    suggest_colors_for_target,
)


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


RED = _mat("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0))
BLUE = _mat("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0))
WHITE = _mat("White", E=(0.95, 0.95, 0.95), k=(0.5, 0.5, 0.5))
GREEN = _mat("Green", E=(0.1, 0.6, 0.1), k=(4.0, 4.0, 4.0))
BLACK = _mat("Black", E=(0.05, 0.05, 0.05), k=(6.0, 6.0, 6.0))

SMALL_PALETTE = [RED, BLUE, WHITE]
MEDIUM_PALETTE = [RED, BLUE, WHITE, GREEN, BLACK]


# ---------------------------------------------------------------------------
# _greedy_lab_spacing_dedup primitive
# ---------------------------------------------------------------------------


class TestGreedyLabSpacingDedup:
    def test_empty_input_returns_empty(self):
        labs = np.zeros((0, 3), dtype=np.float64)
        out = _greedy_lab_spacing_dedup(labs, 1.0, 5)
        assert out.shape == (0,)

    def test_zero_limit_returns_empty(self):
        labs = np.asarray([[50.0, 0.0, 0.0], [80.0, 10.0, 10.0]])
        out = _greedy_lab_spacing_dedup(labs, 1.0, 0)
        assert out.shape == (0,)

    def test_always_keeps_first(self):
        labs = np.asarray([[50.0, 0.0, 0.0], [50.0, 0.0, 0.0]])
        out = _greedy_lab_spacing_dedup(labs, 5.0, 5)
        # First is always kept; second is duplicate so dropped.
        assert list(out) == [0]

    def test_keeps_spaced_entries(self):
        labs = np.asarray(
            [
                [50.0, 0.0, 0.0],
                [50.5, 0.0, 0.0],   # ΔE=0.5 from first — drop.
                [60.0, 0.0, 0.0],   # ΔE=10 from first — keep.
                [60.1, 0.0, 0.0],   # ΔE=0.1 from second keep — drop.
                [80.0, 0.0, 0.0],   # ΔE=20 from nearest kept — keep.
            ]
        )
        out = _greedy_lab_spacing_dedup(labs, min_spacing=1.0, limit=10)
        assert list(out) == [0, 2, 4]

    def test_respects_limit(self):
        labs = np.asarray([[i * 10.0, 0.0, 0.0] for i in range(10)])
        out = _greedy_lab_spacing_dedup(labs, min_spacing=1.0, limit=3)
        assert out.shape == (3,)


# ---------------------------------------------------------------------------
# suggest_colors_for_target — contract and invariants
# ---------------------------------------------------------------------------


class TestSuggestColorsForTargetContract:
    def test_returns_color_suggestion_list(self):
        target = np.asarray([200, 100, 50], dtype=np.uint8)
        out = suggest_colors_for_target(
            target, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
        )
        assert isinstance(out, list)
        assert all(isinstance(s, ColorSuggestion) for s in out)
        assert 0 < len(out) <= 20

    def test_default_top_k_is_twenty(self):
        target = np.asarray([128, 128, 128], dtype=np.uint8)
        out = suggest_colors_for_target(
            target, MEDIUM_PALETTE, layer_count=5, layer_height_mm=0.08,
            min_spacing=0.0,
        )
        assert len(out) == 20

    def test_top_k_custom(self):
        target = np.asarray([128, 128, 128], dtype=np.uint8)
        out = suggest_colors_for_target(
            target, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            top_k=5, min_spacing=0.0,
        )
        assert len(out) == 5

    def test_rejects_bad_target_shape(self):
        with pytest.raises(ValueError, match="target_srgb"):
            suggest_colors_for_target(
                np.asarray([[100, 100, 100]], dtype=np.uint8),
                SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            )

    def test_rejects_empty_materials(self):
        target = np.asarray([128, 128, 128], dtype=np.uint8)
        with pytest.raises(ValueError, match="materials"):
            suggest_colors_for_target(
                target, [], layer_count=5, layer_height_mm=0.08,
            )

    def test_rejects_invalid_layer_count(self):
        target = np.asarray([128, 128, 128], dtype=np.uint8)
        with pytest.raises(ValueError):
            suggest_colors_for_target(
                target, SMALL_PALETTE, layer_count=1, layer_height_mm=0.08,
            )

    def test_rejects_invalid_layer_height(self):
        target = np.asarray([128, 128, 128], dtype=np.uint8)
        with pytest.raises(ValueError):
            suggest_colors_for_target(
                target, SMALL_PALETTE, layer_count=5, layer_height_mm=0.123,
            )

    def test_rejects_invalid_substrate(self):
        target = np.asarray([128, 128, 128], dtype=np.uint8)
        with pytest.raises(ValueError, match="substrate"):
            suggest_colors_for_target(
                target, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
                substrate="blue",  # type: ignore[arg-type]
            )

    def test_rejects_nonpositive_top_k(self):
        target = np.asarray([128, 128, 128], dtype=np.uint8)
        with pytest.raises(ValueError, match="top_k"):
            suggest_colors_for_target(
                target, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
                top_k=0,
            )

    def test_rejects_negative_min_spacing(self):
        target = np.asarray([128, 128, 128], dtype=np.uint8)
        with pytest.raises(ValueError, match="min_spacing"):
            suggest_colors_for_target(
                target, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
                min_spacing=-0.5,
            )

    def test_overflow_guard_trips_for_large_combinations(self):
        target = np.asarray([128, 128, 128], dtype=np.uint8)
        # 5 materials × 10 layers = 9.7M combinations > 10k cap.
        with pytest.raises(OverflowError, match="combinations"):
            suggest_colors_for_target(
                target, MEDIUM_PALETTE, layer_count=10, layer_height_mm=0.08,
                max_combinations=10_000,
            )


class TestSuggestColorsForTargetRanking:
    def test_delta_e_is_ascending(self):
        target = np.asarray([150, 70, 40], dtype=np.uint8)
        out = suggest_colors_for_target(
            target, MEDIUM_PALETTE, layer_count=5, layer_height_mm=0.08,
            top_k=15, min_spacing=0.0,
        )
        de_values = [s.delta_e for s in out]
        assert de_values == sorted(de_values)

    def test_best_suggestion_matches_optimal_solver(self):
        """Best suggestion should match :func:`solve_image_colors_optimal` output."""
        from core.material_color_solver import solve_image_colors_optimal

        target = np.asarray([180, 60, 40], dtype=np.uint8)
        suggestions = suggest_colors_for_target(
            target, MEDIUM_PALETTE, layer_count=5, layer_height_mm=0.08,
            top_k=5, min_spacing=0.0,
        )
        assert len(suggestions) >= 1
        optimal_matched, optimal_recipes, optimal_de = solve_image_colors_optimal(
            target.reshape(1, 3), MEDIUM_PALETTE, layer_count=5,
            layer_height_mm=0.08,
        )
        best = suggestions[0]
        # ΔE should match within a tiny numerical slack.
        assert abs(best.delta_e - float(optimal_de[0])) < 1e-3

    def test_predicted_rgb_consistent_with_recipe(self):
        target = np.asarray([200, 200, 80], dtype=np.uint8)
        out = suggest_colors_for_target(
            target, MEDIUM_PALETTE, layer_count=5, layer_height_mm=0.08,
            top_k=5, min_spacing=0.0,
        )
        substrate_linear = np.ones(3, dtype=np.float64)
        for suggestion in out:
            predicted_linear = forward_model(
                suggestion.recipe, MEDIUM_PALETTE, 0.08, substrate_linear
            )
            predicted_srgb = linear_to_srgb_uint8(predicted_linear.reshape(1, 3))[0]
            np.testing.assert_array_equal(
                suggestion.matched_rgb, predicted_srgb,
                err_msg=(
                    f"suggestion matched={suggestion.matched_rgb} but "
                    f"forward_model(recipe)={predicted_srgb} for "
                    f"recipe={suggestion.recipe}"
                ),
            )

    def test_recipe_length_equals_layer_count(self):
        target = np.asarray([100, 200, 150], dtype=np.uint8)
        out = suggest_colors_for_target(
            target, SMALL_PALETTE, layer_count=6, layer_height_mm=0.08,
            top_k=5,
        )
        for suggestion in out:
            assert suggestion.recipe.shape == (6,)
            assert suggestion.recipe.dtype == np.int32
            assert int(suggestion.recipe.min()) >= 0
            assert int(suggestion.recipe.max()) < len(SMALL_PALETTE)

    def test_min_spacing_enforces_distinctness(self):
        target = np.asarray([128, 128, 128], dtype=np.uint8)
        out = suggest_colors_for_target(
            target, MEDIUM_PALETTE, layer_count=5, layer_height_mm=0.08,
            top_k=20, min_spacing=5.0,
        )
        # Every kept pair must be ΔE >= 5 apart in Lab.
        labs = rgb_to_lab(
            np.stack([s.matched_rgb for s in out], axis=0)
        ).astype(np.float64)
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                de = float(np.linalg.norm(labs[i] - labs[j]))
                assert de >= 5.0 - 1e-6, (
                    f"Suggestion #{i} and #{j} are {de:.3f} apart (< 5.0)"
                )

    def test_substrate_black_differs_from_white(self):
        target = np.asarray([50, 50, 50], dtype=np.uint8)
        white = suggest_colors_for_target(
            target, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white", top_k=3, min_spacing=0.0,
        )
        black = suggest_colors_for_target(
            target, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="black", top_k=3, min_spacing=0.0,
        )
        # Best recipe should differ (dark target on black needs no base coat).
        assert not np.array_equal(white[0].recipe, black[0].recipe)


class TestSuggestColorsForTargetDefaults:
    def test_default_min_spacing_constant(self):
        assert DEFAULT_SUGGEST_MIN_SPACING > 0.0


# ---------------------------------------------------------------------------
# MaterialSolverCache.lookup_top_k — contract and parity with direct MITM
# ---------------------------------------------------------------------------


class TestCacheLookupTopK:
    @pytest.fixture
    def built_cache(self):
        return build_material_solver_cache(
            SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            substrate="white", grid_resolution=32,
        )

    def test_returns_color_suggestion_list(self, built_cache):
        target = np.asarray([200, 100, 50], dtype=np.uint8)
        out = built_cache.lookup_top_k(target, SMALL_PALETTE, top_k=10)
        assert isinstance(out, list)
        assert 0 < len(out) <= 10
        assert all(isinstance(s, ColorSuggestion) for s in out)

    def test_default_top_k_is_twenty(self, built_cache):
        target = np.asarray([128, 128, 128], dtype=np.uint8)
        out = built_cache.lookup_top_k(
            target, SMALL_PALETTE, min_spacing=0.0
        )
        # May be < 20 for a small palette if the cell grid has fewer reached
        # buckets, but with 3 materials × 5 layers × 32 grid we easily clear.
        assert len(out) == 20

    def test_rejects_bad_target_shape(self, built_cache):
        with pytest.raises(ValueError, match="target_srgb"):
            built_cache.lookup_top_k(
                np.asarray([[200, 100, 50]], dtype=np.uint8), SMALL_PALETTE,
            )

    def test_rejects_nonpositive_top_k(self, built_cache):
        target = np.asarray([128, 128, 128], dtype=np.uint8)
        with pytest.raises(ValueError, match="top_k"):
            built_cache.lookup_top_k(target, SMALL_PALETTE, top_k=0)

    def test_rejects_negative_spacing(self, built_cache):
        target = np.asarray([128, 128, 128], dtype=np.uint8)
        with pytest.raises(ValueError, match="min_spacing"):
            built_cache.lookup_top_k(
                target, SMALL_PALETTE, min_spacing=-0.1
            )

    def test_rejects_palette_mismatch(self, built_cache):
        target = np.asarray([128, 128, 128], dtype=np.uint8)
        with pytest.raises(ValueError, match="palette"):
            built_cache.lookup_top_k(target, MEDIUM_PALETTE)

    def test_delta_e_is_ascending(self, built_cache):
        target = np.asarray([180, 60, 60], dtype=np.uint8)
        out = built_cache.lookup_top_k(
            target, SMALL_PALETTE, top_k=10, min_spacing=0.0
        )
        de_values = [s.delta_e for s in out]
        assert de_values == sorted(de_values)

    def test_recipe_indexed_into_user_palette(self, built_cache):
        target = np.asarray([180, 60, 60], dtype=np.uint8)
        shuffled = [SMALL_PALETTE[2], SMALL_PALETTE[0], SMALL_PALETTE[1]]
        out_original = built_cache.lookup_top_k(
            target, SMALL_PALETTE, top_k=1, min_spacing=0.0
        )
        out_shuffled = built_cache.lookup_top_k(
            target, shuffled, top_k=1, min_spacing=0.0
        )
        original_mats = [SMALL_PALETTE[i] for i in out_original[0].recipe]
        shuffled_mats = [shuffled[i] for i in out_shuffled[0].recipe]
        # The actual material per layer must match even though the indices differ.
        assert [m.name for m in original_mats] == [m.name for m in shuffled_mats]

    def test_parity_with_direct_mitm_within_grid_slack(self, built_cache):
        """Cache and direct MITM top-1 ΔE should agree within grid half-diagonal."""
        target = np.asarray([170, 50, 30], dtype=np.uint8)
        mitm_suggestions = suggest_colors_for_target(
            target, SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
            top_k=1, min_spacing=0.0,
        )
        cache_suggestions = built_cache.lookup_top_k(
            target, SMALL_PALETTE, top_k=1, min_spacing=0.0
        )
        # Cache has coarser grid so its ΔE may be larger; bound it by the cell
        # half-diagonal. For grid=32 the half-diagonal ≈ 5.9 — allow 12 slack.
        assert (
            cache_suggestions[0].delta_e - mitm_suggestions[0].delta_e
        ) <= 12.0

    def test_respects_min_spacing(self, built_cache):
        target = np.asarray([128, 128, 128], dtype=np.uint8)
        out = built_cache.lookup_top_k(
            target, SMALL_PALETTE, top_k=20, min_spacing=4.0
        )
        labs = rgb_to_lab(
            np.stack([s.matched_rgb for s in out], axis=0)
        ).astype(np.float64)
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                de = float(np.linalg.norm(labs[i] - labs[j]))
                assert de >= 4.0 - 1e-6
