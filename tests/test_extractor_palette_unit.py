# -*- coding: utf-8 -*-
"""Extractor default-palette regression tests.
Extractor 默认调色板回归测试。

These tests pin the contract between ``color_mode`` and the slot names in the
``default_palette`` returned by ``api.routers.extractor._build_default_palette``.

历史 bug：``/api/extractor/extract`` 会先把 6 色变体统一归一为 CMYWGK
（`effective_color_mode`），再用归一后的值去构建 ``default_palette``。结果选择
RYBWGK 模式时，前端面板显示的槽位名仍然是 CMYW 的「Cyan / Magenta / ...」。
正确行为：提取管线归一化仍保留，但面向用户的调色板必须用原始 ``color_mode``，
RYBWGK → 白/红/黄/蓝/绿/黑，CMYWGK → 白/青/品红/绿/黄/黑。
"""

from __future__ import annotations

import numpy as np

from api.routers.extractor import _build_default_palette
from utils.lut_manager import LUTManager


class TestBuildDefaultPaletteColorMode:
    """``_build_default_palette`` must honor the exact color-mode subtype."""

    def test_rybwgk_6_color_returns_rybw_slot_names(self):
        """6-Color (RYBWGK 1296) → White/Red/Yellow/Blue/Green/Black."""
        palette = _build_default_palette("6-Color (RYBWGK 1296)")
        colors = [entry["color"] for entry in palette]
        assert colors == ["White", "Red", "Yellow", "Blue", "Green", "Black"]
        # And specifically must NOT contain CMYW-family names.
        assert "Cyan" not in colors
        assert "Magenta" not in colors

    def test_cmywgk_6_color_returns_cmyw_slot_names(self):
        """6-Color (CMYWGK 1296) → White/Cyan/Magenta/Green/Yellow/Black."""
        palette = _build_default_palette("6-Color (CMYWGK 1296)")
        colors = [entry["color"] for entry in palette]
        assert colors == ["White", "Cyan", "Magenta", "Green", "Yellow", "Black"]

    def test_4_color_rybw_returns_rybw_slot_names(self):
        """4-Color (RYBW) → White/Red/Yellow/Blue (baseline, unchanged)."""
        palette = _build_default_palette("4-Color (RYBW)")
        colors = [entry["color"] for entry in palette]
        assert "Cyan" not in colors
        assert "Magenta" not in colors
        assert "White" in colors

    def test_4_color_cmyw_returns_cmyw_slot_names(self):
        """4-Color (CMYW) → White/Cyan/Magenta/Yellow (baseline, unchanged)."""
        palette = _build_default_palette("4-Color (CMYW)")
        colors = [entry["color"] for entry in palette]
        assert "Cyan" in colors
        assert "Magenta" in colors

    def test_palette_entries_have_required_fields(self):
        """Every palette entry must carry color/material/hex_color/color_name."""
        palette = _build_default_palette("6-Color (RYBWGK 1296)")
        assert palette  # non-empty
        for entry in palette:
            assert set(entry.keys()) == {"color", "material", "hex_color", "color_name"}
            assert isinstance(entry["color"], str) and entry["color"]
            # hex_color should be a lowercase #rrggbb string when preview exists
            assert entry["hex_color"] is not None
            assert entry["hex_color"].startswith("#")
            assert len(entry["hex_color"]) == 7

    def test_run_extraction_preserves_rybwgk_metadata(self, tmp_path, monkeypatch):
        from core import extractor as extractor_core

        lut_path = tmp_path / "lumina_lut.json"
        monkeypatch.setattr(extractor_core, "LUT_FILE_PATH", str(lut_path))
        monkeypatch.setattr(extractor_core.Stats, "increment", lambda _name: None)

        img = np.full((1000, 1000, 3), 180, dtype=np.uint8)
        _vis, _preview, saved_path, _status = extractor_core.run_extraction(
            img=img,
            points=[[0, 0], [999, 0], [999, 999], [0, 999]],
            offset_x=0,
            offset_y=0,
            zoom=1.0,
            barrel=0.0,
            bright=False,
            color_mode="6-Color (RYBWGK 1296)",
            page_choice="Page 1",
            auto_wb=False,
            eight_color_full_export=False,
        )

        assert saved_path == str(lut_path)
        _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(str(lut_path))
        assert metadata.color_mode == "6-Color (RYBWGK 1296)"
        assert [entry.color for entry in metadata.palette] == [
            "White",
            "Red",
            "Yellow",
            "Blue",
            "Green",
            "Black",
        ]
