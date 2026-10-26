# -*- coding: utf-8 -*-
"""5-color extractor recipe generation regression tests."""

from __future__ import annotations

import numpy as np

from config import LUTMetadata, PaletteEntry
from core.extractor import _generate_recipes
from utils.lut_manager import LUTManager


def test_generate_5color_page2_recipes_match_calibration_board_order() -> None:
    """Page 2 extraction recipes must be real 6-layer stacks, not white fallback."""
    stacks = _generate_recipes("5-Color Extended", 1444, "Page 2")

    assert stacks.shape == (1444, 6)
    assert stacks.dtype == np.int32
    assert stacks[0].tolist() == [4, 0, 0, 0, 0, 0]
    assert np.any(stacks == 4)
    assert not np.all(stacks == 0)


def test_5color_page2_keyed_json_save_writes_black_recipe(tmp_path) -> None:
    """Saved JSON should contain the material recipe that produced black."""
    rgb = np.zeros((1444, 3), dtype=np.uint8)
    stacks = _generate_recipes("5-Color Extended", 1444, "Page 2")
    metadata = LUTMetadata(
        palette=[
            PaletteEntry("White", "PETG"),
            PaletteEntry("Red", "PETG"),
            PaletteEntry("Yellow", "PETG"),
            PaletteEntry("Blue", "PETG"),
            PaletteEntry("Black", "PETG"),
        ],
        color_mode="5-Color Extended",
        max_color_layers=6,
    )
    lut_path = tmp_path / "page2.json"

    LUTManager.save_keyed_json(str(lut_path), rgb, stacks, metadata)
    _loaded_rgb, loaded_stacks, _loaded_metadata = LUTManager.load_lut_with_metadata(str(lut_path))

    assert loaded_stacks is not None
    assert loaded_stacks.shape == (1444, 6)
    assert loaded_stacks[0].tolist() == [4, 0, 0, 0, 0, 0]
