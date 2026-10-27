"""Small native regressions for the desktop resource-policy removal."""

from __future__ import annotations

import lumina_svg_core


def test_recording_accepts_more_than_the_removed_element_count_cap() -> None:
    """The recorder no longer rejects a valid SVG at 250,000 elements."""

    element_count = 250_001
    svg = (
        "<svg viewBox='0 0 1 1'>"
        + "<rect width='1' height='1'/>" * element_count
        + "</svg>"
    )

    result = lumina_svg_core.record_paint_commands_svg(svg)

    assert result.status == "supported"
    assert result.reason_code == ""
    assert len(result.commands) == element_count


def test_recording_accepts_deep_valid_element_nesting() -> None:
    """Nested groups are governed by XML validity, not a fixed depth quota."""

    depth = 300
    svg = (
        "<svg viewBox='0 0 10 10'>"
        + "<g>" * depth
        + "<rect width='10' height='10'/>"
        + "</g>" * depth
        + "</svg>"
    )

    result = lumina_svg_core.record_paint_commands_svg(svg)

    assert result.status == "supported"
    assert result.reason_code == ""
    assert len(result.commands) == 1
