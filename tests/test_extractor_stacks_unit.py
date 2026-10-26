"""Regression tests for extractor _generate_recipes stacking order.

Validates that the reversed() convention in 6-Color / 8-Color paths
produces top-to-bottom stacks (stack[0] = viewing surface) consistent
with the calibration board generation and the 4-Color base case.

See PR #18 M7: ensures old extraction results remain reproducible
after the bottom-to-top → top-to-bottom reversal was introduced.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.extractor import (
    EIGHT_COLOR_FULL_TOTAL_PAGES,
    EIGHT_COLOR_FULL_TOTAL_RECIPES,
    EIGHT_COLOR_PAGE_CAPACITY,
    _generate_recipes,
    _get_8color_page_cell_count,
)


# =========================================================================
# 1. 4-Color (base case, no external data dependency)
# =========================================================================


class TestFourColorStacks:
    """4-Color stacks use base-4 decomposition with MSB-first ([::-1])."""

    def test_shape(self) -> None:
        stacks = _generate_recipes("4-Color", 1024)
        assert stacks.shape == (1024, 5)
        assert stacks.dtype == np.int32

    def test_first_stack_all_zeros(self) -> None:
        """Index 0 → digits [0,0,0,0,0]."""
        stacks = _generate_recipes("4-Color", 1024)
        np.testing.assert_array_equal(stacks[0], [0, 0, 0, 0, 0])

    def test_last_stack_all_threes(self) -> None:
        """Index 1023 → digits [3,3,3,3,3]."""
        stacks = _generate_recipes("4-Color", 1024)
        np.testing.assert_array_equal(stacks[1023], [3, 3, 3, 3, 3])

    def test_index_one_lsb(self) -> None:
        """Index 1 → base-4: 00001 → reversed: [0,0,0,0,1]."""
        stacks = _generate_recipes("4-Color", 1024)
        np.testing.assert_array_equal(stacks[1], [0, 0, 0, 0, 1])

    def test_viewing_surface_is_msb(self) -> None:
        """stack[0] should be the most significant digit (viewing surface)."""
        stacks = _generate_recipes("4-Color", 1024)
        # Index 256 = 4^4 → base-4 digits [1,0,0,0,0]
        np.testing.assert_array_equal(stacks[256], [1, 0, 0, 0, 0])

    def test_material_range(self) -> None:
        stacks = _generate_recipes("4-Color", 1024)
        assert stacks.min() == 0
        assert stacks.max() == 3

    def test_rybw_same_as_default(self) -> None:
        """RYBW and CMYW share the same combinatorial recipe."""
        default = _generate_recipes("4-Color", 1024)
        rybw = _generate_recipes("4-Color (RYBW)", 1024)
        cmyw = _generate_recipes("4-Color (CMYW)", 1024)
        np.testing.assert_array_equal(default, rybw)
        np.testing.assert_array_equal(default, cmyw)


# =========================================================================
# 2. BW (simplest mode)
# =========================================================================


class TestBWStacks:
    """BW uses base-2 decomposition, 2^5 = 32 combinations."""

    def test_shape(self) -> None:
        stacks = _generate_recipes("BW", 32)
        assert stacks.shape == (32, 5)

    def test_material_range(self) -> None:
        stacks = _generate_recipes("BW", 32)
        assert stacks.min() == 0
        assert stacks.max() == 1

    def test_first_all_zeros_last_all_ones(self) -> None:
        stacks = _generate_recipes("BW", 32)
        np.testing.assert_array_equal(stacks[0], [0, 0, 0, 0, 0])
        np.testing.assert_array_equal(stacks[31], [1, 1, 1, 1, 1])


# =========================================================================
# 3. 6-Color stacks reversal regression
# =========================================================================


class TestSixColorStacksReversal:
    """6-Color path must reverse get_top_1296_colors() from bottom-to-top
    to top-to-bottom so that stack[0] is the viewing surface."""

    def test_reversed_matches_calibration_convention(self) -> None:
        """Verify _generate_recipes reverses vs raw get_top_1296_colors."""
        try:
            from core.calibration import get_top_1296_colors
        except ImportError:
            pytest.skip("calibration module not available")

        raw = get_top_1296_colors()
        recipes = _generate_recipes("6-Color", len(raw))

        for i, raw_stack in enumerate(raw):
            expected = list(reversed(raw_stack))
            np.testing.assert_array_equal(
                recipes[i],
                expected,
                err_msg=f"Stack {i}: expected reversed {raw_stack} = {expected}, got {list(recipes[i])}",
            )

    def test_generate_recipes_uses_cached_6color_stacks(self, monkeypatch) -> None:
        from core import calibration

        raw = (
            np.arange(1296 * 5, dtype=np.int32).reshape(1296, 5) % 6
        ).astype(np.int32)
        monkeypatch.setattr(
            calibration,
            "_load_smart_6color_stacks_bottom_to_top",
            lambda: raw,
        )

        recipes = _generate_recipes("6-Color", 3)

        np.testing.assert_array_equal(recipes, raw[:3, ::-1])

    def test_shape_and_dtype(self) -> None:
        try:
            from core.calibration import get_top_1296_colors  # noqa: F401
        except ImportError:
            pytest.skip("calibration module not available")

        stacks = _generate_recipes("6-Color", 100)
        assert stacks.shape == (100, 5)
        assert stacks.dtype == np.int32

    def test_material_range(self) -> None:
        try:
            from core.calibration import get_top_1296_colors  # noqa: F401
        except ImportError:
            pytest.skip("calibration module not available")

        stacks = _generate_recipes("6-Color", 1296)
        assert stacks.min() >= 0
        assert stacks.max() <= 5


# =========================================================================
# 4. Cross-mode convention consistency
# =========================================================================


class TestCrossModeConvention:
    """All modes must agree that stack[0] is the viewing surface (top layer)."""

    def test_four_color_surface_layer_varies(self) -> None:
        """Across 1024 stacks, stack[0] should take all 4 values."""
        stacks = _generate_recipes("4-Color", 1024)
        assert set(stacks[:, 0].tolist()) == {0, 1, 2, 3}

    def test_bw_surface_layer_varies(self) -> None:
        stacks = _generate_recipes("BW", 32)
        assert set(stacks[:, 0].tolist()) == {0, 1}

    def test_six_color_surface_layer_varies(self) -> None:
        """6-Color stacks should have multiple distinct viewing-surface colors."""
        try:
            from core.calibration import get_top_1296_colors  # noqa: F401
        except ImportError:
            pytest.skip("calibration module not available")

        stacks = _generate_recipes("6-Color", 1296)
        unique_surface = set(stacks[:, 0].tolist())
        # Should have at least 4 distinct surface colors (all 6 ideally)
        assert len(unique_surface) >= 4, f"Only {len(unique_surface)} surface colors: {unique_surface}"


class TestEightColorFullPages:
    """8-Color full extraction should respect per-page recipe counts."""

    def test_full_mode_first_page_uses_page_capacity(self) -> None:
        assert _get_8color_page_cell_count("Page 1", True) == EIGHT_COLOR_PAGE_CAPACITY

    def test_full_mode_last_page_uses_remaining_recipe_count(self) -> None:
        remaining = EIGHT_COLOR_FULL_TOTAL_RECIPES - (
            (EIGHT_COLOR_FULL_TOTAL_PAGES - 1) * EIGHT_COLOR_PAGE_CAPACITY
        )
        assert remaining > 0
        assert _get_8color_page_cell_count(
            f"Page {EIGHT_COLOR_FULL_TOTAL_PAGES}",
            True,
        ) == remaining

    def test_generate_recipes_full_last_page_matches_remaining_count(self) -> None:
        total_cells = _get_8color_page_cell_count(
            f"Page {EIGHT_COLOR_FULL_TOTAL_PAGES}",
            True,
        )
        stacks = _generate_recipes(
            "8-Color Max",
            total_cells,
            f"Page {EIGHT_COLOR_FULL_TOTAL_PAGES}",
            eight_color_full_export=True,
        )
        assert stacks.shape == (total_cells, 5)
        assert stacks.dtype == np.int32
