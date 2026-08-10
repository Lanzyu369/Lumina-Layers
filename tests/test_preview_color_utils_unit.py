# -*- coding: utf-8 -*-
"""Regression tests for ``core.pipeline.preview_color_utils``.

``core.pipeline.preview_color_utils`` 的回归测试：
覆盖 native bundle 调色板在 hex_color 缺省时的颜色解析，
确保不会因 UI ``color_mode`` 陈旧而串色（例如用户从传统 CMYW LUT
切到反推 LUT 时，六色调色板被错误解析成 CMYW 四色导致 3MF
``filament_colour`` 出现重复/错位）。
"""

from __future__ import annotations

from config import ColorSystem, PaletteEntry
from core.pipeline.preview_color_utils import (
    build_palette_preview_colors,
    resolve_material_preview,
)


def _rgba_to_hex(rgba: list[int]) -> str:
    """(r, g, b, a) -> '#RRGGBB' (uppercase)."""
    return "#{:02X}{:02X}{:02X}".format(rgba[0], rgba[1], rgba[2])


def _six_color_rybwgk_palette() -> list[PaletteEntry]:
    """Palette as native ColorDB stores it: canonical names, hex_color=None."""
    return [
        PaletteEntry(color="White", material="PLA", hex_color=None),
        PaletteEntry(color="Blue", material="PLA", hex_color=None),
        PaletteEntry(color="Red", material="PLA", hex_color=None),
        PaletteEntry(color="Green", material="PLA", hex_color=None),
        PaletteEntry(color="Yellow", material="PLA", hex_color=None),
        PaletteEntry(color="Black", material="PLA", hex_color=None),
    ]


def _eight_color_palette() -> list[PaletteEntry]:
    return [
        PaletteEntry(color="White", material="PLA", hex_color=None),
        PaletteEntry(color="Cyan", material="PLA", hex_color=None),
        PaletteEntry(color="Magenta", material="PLA", hex_color=None),
        PaletteEntry(color="Yellow", material="PLA", hex_color=None),
        PaletteEntry(color="Black", material="PLA", hex_color=None),
        PaletteEntry(color="Red", material="PLA", hex_color=None),
        PaletteEntry(color="Blue", material="PLA", hex_color=None),
        PaletteEntry(color="Green", material="PLA", hex_color=None),
    ]


class TestBuildPalettePreviewColors:
    """``build_palette_preview_colors`` 对常见命名调色板的颜色解析。"""

    def test_hex_color_on_entry_is_used_verbatim(self) -> None:
        """If a palette entry carries hex_color, it wins over color_conf lookup.
        调色板自带 hex_color 时应被原样使用。"""
        palette = [
            PaletteEntry(color="Custom Tag", material="PLA", hex_color="#112233"),
        ]
        slot_names, preview = build_palette_preview_colors(palette, ColorSystem.CMYW)

        assert slot_names == ["Custom Tag"]
        assert preview[0] == [0x11, 0x22, 0x33, 255]

    def test_six_color_rybwgk_palette_under_stale_cmyw_color_conf(self) -> None:
        """Native ColorDB palette with canonical names must produce DISTINCT,
        canonical colors even when the caller passes a stale CMYW color_conf
        (reproduces the bug where switching 传统 CMYW LUT → 反推 LUT kept
        ``color_mode='4-Color (CMYW)'`` and polluted the 3MF ``filament_colour``).
        """
        palette = _six_color_rybwgk_palette()
        slot_names, preview = build_palette_preview_colors(palette, ColorSystem.CMYW)

        assert slot_names == ["White", "Blue", "Red", "Green", "Yellow", "Black"]
        # All six colors must be DISTINCT (the bug produced duplicates like
        # Green==Yellow==#F4EE2A and Black==White==#FFFFFF).
        hexes = [_rgba_to_hex(preview[i]) for i in range(len(palette))]
        assert len(set(hexes)) == 6, f"Expected 6 distinct colors, got {hexes}"

        # White and Black must be the canonical extremes.
        assert _rgba_to_hex(preview[0]) == "#FFFFFF"  # White
        assert _rgba_to_hex(preview[5]) == "#000000"  # Black

        # Green must not collapse into Yellow (the pre-fix misbehaviour).
        assert _rgba_to_hex(preview[3]) != _rgba_to_hex(preview[4])

        # Red must not fuzzy-collapse into Magenta (CMYW's preview[2]).
        assert _rgba_to_hex(preview[2]) != "#EC008C"

        # Blue must not fuzzy-collapse into Cyan (CMYW's preview[1]).
        assert _rgba_to_hex(preview[1]) != "#0086D6"

        # Lock canonical mappings: bare "Blue" aliases to 8-Color "Deep Blue"
        # (#0A2989), "Red" to 8-Color Red (#C12E1F), "Green" to 8-Color Green
        # (#00AE42). Prevents silent drift if alias ordering is reshuffled.
        assert _rgba_to_hex(preview[1]) == "#0A2989"  # Blue  → Deep Blue
        assert _rgba_to_hex(preview[2]) == "#C12E1F"  # Red
        assert _rgba_to_hex(preview[3]) == "#00AE42"  # Green
        assert _rgba_to_hex(preview[4]) == "#F4EE2A"  # Yellow

    def test_eight_color_palette_under_stale_cmyw_color_conf(self) -> None:
        """Full 8-color palette must resolve all eight canonical colors
        distinctly, not collapse into the CMYW 4-slot preview dict.
        """
        palette = _eight_color_palette()
        slot_names, preview = build_palette_preview_colors(palette, ColorSystem.CMYW)

        assert slot_names == ["White", "Cyan", "Magenta", "Yellow", "Black", "Red", "Blue", "Green"]
        hexes = [_rgba_to_hex(preview[i]) for i in range(len(palette))]
        assert len(set(hexes)) == 8, f"Expected 8 distinct colors, got {hexes}"

        assert _rgba_to_hex(preview[0]) == "#FFFFFF"  # White
        assert _rgba_to_hex(preview[4]) == "#000000"  # Black
        # Cyan/Magenta/Yellow should match CMYW canonical values regardless.
        assert _rgba_to_hex(preview[1]) == "#0086D6"  # Cyan
        assert _rgba_to_hex(preview[2]) == "#EC008C"  # Magenta
        assert _rgba_to_hex(preview[3]) == "#F4EE2A"  # Yellow

    def test_cmyw_palette_under_matching_cmyw_color_conf(self) -> None:
        """CMYW palette (same as color_conf) stays correct — regression guard.
        调色板刚好等于 CMYW 时保持原有行为。"""
        palette = [
            PaletteEntry(color="White", material="PLA", hex_color=None),
            PaletteEntry(color="Cyan", material="PLA", hex_color=None),
            PaletteEntry(color="Magenta", material="PLA", hex_color=None),
            PaletteEntry(color="Yellow", material="PLA", hex_color=None),
        ]
        _, preview = build_palette_preview_colors(palette, ColorSystem.CMYW)

        assert _rgba_to_hex(preview[0]) == "#FFFFFF"
        assert _rgba_to_hex(preview[1]) == "#0086D6"
        assert _rgba_to_hex(preview[2]) == "#EC008C"
        assert _rgba_to_hex(preview[3]) == "#F4EE2A"

    def test_unknown_color_names_fall_back_to_color_conf(self) -> None:
        """Non-canonical names still fall through to the color_conf fuzzy path
        (preserves existing behavior for bespoke LUT palettes).
        未知颜色名仍走原先的 color_conf 兜底路径。"""
        palette = [
            PaletteEntry(color="Midnight Teal", material="PLA", hex_color=None),
        ]
        # Should not raise and should return some RGBA (the exact value is
        # allowed to come from the color_conf fallback).
        slot_names, preview = build_palette_preview_colors(palette, ColorSystem.CMYW)
        assert slot_names == ["Midnight Teal"]
        assert len(preview[0]) == 4
        assert all(isinstance(channel, int) for channel in preview[0])


class TestResolveMaterialPreview:
    """Material IDs keep one identity across runtime palette key shapes.
    材料 ID 在不同运行时调色板键形态下保持同一材料身份。
    """

    def test_prefers_authoritative_preview_color_over_stale_color_conf(self) -> None:
        result = resolve_material_preview(
            material_id=3,
            slot_names=["White", "Red", "Yellow", "Archive Blue"],
            preview_colors={3: [17, 34, 51, 255]},
            color_conf={
                "slots": ["White", "Red", "Yellow", "Legacy Blue"],
                "preview": {3: [0, 100, 240, 255]},
            },
        )

        assert result.is_resolved is True
        assert result.material_id == 3
        assert result.material_name == "Archive Blue"
        assert result.rgba == (17, 34, 51, 255)
        assert result.source == "preview_int"

    def test_supports_string_id_and_material_name_keys(self) -> None:
        slot_names = ["White", "Red", "Yellow", "自定义夜空紫"]
        by_string = resolve_material_preview(
            material_id=3,
            slot_names=slot_names,
            preview_colors={"3": [21, 31, 41, 255]},
            color_conf={},
        )
        by_name = resolve_material_preview(
            material_id=3,
            slot_names=slot_names,
            preview_colors={slot_names[3]: [51, 61, 71, 255]},
            color_conf={},
        )

        assert by_string.rgba == (21, 31, 41, 255)
        assert by_string.source == "preview_str"
        assert by_name.rgba == (51, 61, 71, 255)
        assert by_name.source == "preview_name"
        assert by_name.material_name == slot_names[3]

    def test_invalid_rgba_does_not_borrow_slot_zero(self) -> None:
        result = resolve_material_preview(
            material_id=1,
            slot_names=["White", "Custom"],
            preview_colors={1: [999], 0: [255, 255, 255, 255]},
            color_conf={"preview": {0: [255, 255, 255, 255]}},
        )

        assert result.is_resolved is False
        assert result.material_name == "Custom"
        assert result.rgba is None
        assert result.source == "unresolved_color"
        assert result.attempts == (
            "preview_int",
            "preview_str",
            "preview_name",
            "color_conf_name",
            "canonical_name",
        )

    def test_out_of_range_id_never_invents_material_identity(self) -> None:
        result = resolve_material_preview(
            material_id=3,
            slot_names=["White", "Red", "Yellow"],
            preview_colors={3: [17, 34, 51, 255]},
            color_conf={
                "slots": ["White", "Red", "Yellow", "Legacy Blue"],
                "preview": {3: [0, 100, 240, 255]},
            },
        )

        assert result.is_resolved is False
        assert result.material_name is None
        assert result.rgba is None
        assert result.source == "invalid_material_id"
        assert result.attempts == ()

    def test_stale_numeric_fallback_cannot_recolor_a_different_material(self) -> None:
        result = resolve_material_preview(
            material_id=1,
            slot_names=["White", "Private Purple"],
            preview_colors={},
            color_conf={
                "slots": ["White", "Legacy Red"],
                "preview": {1: [255, 0, 0, 255]},
            },
        )

        assert result.is_resolved is False
        assert result.material_name == "Private Purple"
        assert result.rgba is None
        assert result.source == "unresolved_color"

    def test_aligned_numeric_color_conf_remains_a_compatible_fallback(self) -> None:
        result = resolve_material_preview(
            material_id=1,
            slot_names=["White", "Archive Red"],
            preview_colors={},
            color_conf={
                "slots": ["White", "Archive Red"],
                "preview": {1: [201, 46, 31, 255]},
            },
        )

        assert result.is_resolved is True
        assert result.material_name == "Archive Red"
        assert result.rgba == (201, 46, 31, 255)
        assert result.source == "color_conf_int"
