"""Unit tests for colour-workspace similarity helpers (core.color_similarity)."""

from __future__ import annotations

import numpy as np
import pytest

from core.color_similarity import (
    colors_within_delta_e,
    delta_e00_to_reference,
    parse_hex_color,
    rank_image_colors,
    rank_similar_recipes,
    rgb_to_hex,
    unique_color_hexes,
)


def test_parse_hex_color_accepts_optional_hash() -> None:
    assert parse_hex_color("#FF8000") == (255, 128, 0)
    assert parse_hex_color("00ff7f") == (0, 255, 127)
    assert rgb_to_hex((255, 128, 0)) == "#ff8000"


@pytest.mark.parametrize("value", ["", "#fff", "gg0000", "#12345678"])
def test_parse_hex_color_rejects_malformed_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_hex_color(value)


def test_delta_e00_is_zero_for_identical_colour() -> None:
    distances = delta_e00_to_reference((10, 120, 200), np.array([[10, 120, 200], [200, 10, 10]]))
    assert distances[0] == pytest.approx(0.0, abs=1e-6)
    assert distances[1] > 30


def test_colors_within_delta_e_zero_tolerance_is_strict_same_colour() -> None:
    candidates = np.array([[200, 0, 0], [201, 0, 0], [0, 0, 200]], dtype=np.uint8)
    assert colors_within_delta_e((200, 0, 0), candidates, 0).tolist() == [True, False, False]


def test_colors_within_delta_e_tolerance_includes_near_shades_only() -> None:
    candidates = np.array([[200, 0, 0], [204, 4, 2], [0, 0, 200]], dtype=np.uint8)
    assert colors_within_delta_e((200, 0, 0), candidates, 5).tolist() == [True, True, False]


def test_colors_within_delta_e_rejects_negative_tolerance() -> None:
    with pytest.raises(ValueError):
        colors_within_delta_e((0, 0, 0), np.zeros((1, 3), dtype=np.uint8), -1)


def _lut() -> tuple[np.ndarray, np.ndarray]:
    rgb = np.array(
        [
            [250, 250, 250],  # white
            [220, 30, 30],  # red
            [205, 40, 40],  # darker red
            [220, 30, 30],  # duplicate red, different stack
            [30, 30, 220],  # blue
            [100, 100, 100],  # placeholder row
        ],
        dtype=np.uint8,
    )
    stacks = np.array(
        [
            [0, 0, 0],
            [1, 1, 0],
            [1, 1, 1],
            [1, 0, 0],
            [2, 2, 0],
            [-1, -1, -1],
        ],
        dtype=np.int64,
    )
    return rgb, stacks


def test_rank_similar_recipes_sorts_by_delta_e_and_keeps_first_duplicate() -> None:
    rgb, stacks = _lut()
    ranked = rank_similar_recipes((218, 32, 32), rgb, stacks, limit=3)
    assert [item.hex for item in ranked[:2]] == ["#dc1e1e", "#cd2828"]
    # The first of two identical LUT colours wins so apply stays deterministic.
    assert ranked[0].recipe == (1, 1, 0)
    assert all(item.source == "lut" for item in ranked)
    distances = [item.delta_e00 for item in ranked]
    assert distances == sorted(distances)
    assert len({item.hex for item in ranked}) == len(ranked)


def test_rank_similar_recipes_skips_placeholder_stacks() -> None:
    rgb, stacks = _lut()
    ranked = rank_similar_recipes((100, 100, 100), rgb, stacks, limit=10)
    assert "#646464" not in {item.hex for item in ranked}
    assert len(ranked) == 4


def test_rank_similar_recipes_merges_predictive_and_drops_lut_duplicates() -> None:
    rgb, stacks = _lut()
    predictive_rgb = np.array([[219, 31, 31], [220, 30, 30]], dtype=np.uint8)
    predictive_recipes = np.array([[1, 2, 1], [1, 1, 2]], dtype=np.int64)
    ranked = rank_similar_recipes(
        (219, 31, 31),
        rgb,
        stacks,
        limit=4,
        predictive_rgb=predictive_rgb,
        predictive_recipes=predictive_recipes,
    )
    assert ranked[0].source == "predictive"
    assert ranked[0].recipe == (1, 2, 1)
    predictive_hexes = [item.hex for item in ranked if item.source == "predictive"]
    assert "#dc1e1e" not in predictive_hexes


def test_rank_similar_recipes_validates_inputs() -> None:
    rgb, stacks = _lut()
    with pytest.raises(ValueError):
        rank_similar_recipes((0, 0, 0), rgb, stacks, limit=0)
    with pytest.raises(ValueError):
        rank_similar_recipes((0, 0, 0), rgb, stacks[:2], limit=3)


def test_unique_color_hexes_respects_mask() -> None:
    rgb = np.array([[[255, 0, 0], [0, 0, 255]], [[255, 0, 0], [0, 255, 0]]], dtype=np.uint8)
    assert unique_color_hexes(rgb) == {"#ff0000", "#0000ff", "#00ff00"}
    mask = np.array([[True, False], [True, False]])
    assert unique_color_hexes(rgb, mask) == {"#ff0000"}


def test_rank_image_colors_uses_masked_pixels_and_strips_padding() -> None:
    rgb = np.array([[[200, 0, 0], [0, 0, 200]], [[210, 10, 10], [0, 200, 0]]], dtype=np.uint8)
    mask = np.array([[True, True], [True, False]])
    stacks = np.array([[[1, 1], [2, 2]], [[1, -1], [3, 3]]], dtype=np.int64)
    ranked = rank_image_colors((200, 0, 0), rgb, mask, stacks, limit=5)
    assert [item.hex for item in ranked] == ["#c80000", "#d20a0a", "#0000c8"]
    assert [item.recipe for item in ranked] == [(1, 1), (1,), (2, 2)]
    assert all(item.source == "image" for item in ranked)
    assert rank_image_colors((0, 0, 0), rgb, mask, None, limit=1)[0].recipe == ()
