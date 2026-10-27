"""Unit tests for preview-click selection safety and HTML rendering."""

import sys
import os

# Add project root to path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core.converter import _resolve_click_selection_hexes, on_preview_click_select_color


def test_invalid_click_returns_none_hex():
    """Invalid click events should not return dict-like hex values."""
    cache = {"bed_label": "256x256 mm"}
    _img, _text, hex_val, msg = on_preview_click_select_color(cache, None)
    assert hex_val is None
    assert "无效点击" in msg


def test_resolve_click_selection_hexes_rejects_non_string_default():
    """dict default_hex payload should be normalized away."""
    display_hex, state_hex = _resolve_click_selection_hexes({}, {"value": "bad"})
    assert display_hex is None
    assert state_hex is None


def test_resolve_click_selection_hexes_prefers_cached_strings():
    cache = {"selected_quantized_hex": "#112233", "selected_matched_hex": "#445566"}
    display_hex, state_hex = _resolve_click_selection_hexes(cache, {"value": "bad"})
    assert display_hex == "#445566"
    assert state_hex == "#112233"
