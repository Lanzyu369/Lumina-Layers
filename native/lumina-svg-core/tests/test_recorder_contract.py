"""Contract tests for the narrow LunaSVG paint recorder fork."""

from __future__ import annotations

from pathlib import Path

import pytest

import lumina_svg_core


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_recorder_preserves_resolved_fill_then_stroke_order() -> None:
    result = lumina_svg_core.record_paint_commands(
        FIXTURES / "basic_fill_stroke.svg"
    )

    assert result.status == "supported"
    assert result.reason_code == ""
    assert result.schema_version == 1
    assert result.viewport == pytest.approx((0.0, 0.0, 20.0, 10.0))
    assert [command.kind for command in result.commands] == ["fill", "stroke"]
    assert tuple(result.commands[0].rgba) == (255, 0, 0, 255)
    assert tuple(result.commands[1].rgba) == (0, 0, 255, 255)
    assert tuple(result.commands[0].matrix) == pytest.approx(
        (2.0, 0.0, 0.0, 1.0, 2.0, 1.0)
    )
    assert result.commands[0].source_index == result.commands[1].source_index
    assert result.commands[0].path_verbs[0] == "move_to"
    assert result.commands[0].path_verbs[-1] == "close"


@pytest.mark.parametrize(
    ("attribute", "value", "reason"),
    [
        ("vector-effect", "non-scaling-stroke", "unsupported_vector_effect"),
        ("marker-start", "url(#marker)", "unsupported_marker"),
        ("paint-order", "stroke fill", "unsupported_paint_order"),
        ("filter", "url(#blur)", "unsupported_filter"),
        ("opacity", "0.5", "unsupported_partial_alpha"),
    ],
)
def test_recorder_fails_closed_for_unsupported_attributes(
    attribute: str,
    value: str,
    reason: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>"
        f"<path d='M0 0H10V10Z' fill='#ff0000' {attribute}='{value}'/>"
        "</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == reason
    assert result.commands == ()


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("<mask id='m'><rect width='1' height='1'/></mask>", "unsupported_mask"),
        ("<marker id='m'/>", "unsupported_marker"),
        ("<linearGradient id='g'/>", "unsupported_paint_server"),
        ("<radialGradient id='g'/>", "unsupported_paint_server"),
        ("<pattern id='p'/>", "unsupported_paint_server"),
        ("<foreignObject width='1' height='1'/>", "unsupported_element"),
        ("<script>1</script>", "unsupported_script"),
        ("<image href='data:image/png;base64,AA=='/>", "unsupported_image"),
        ("<text x='0' y='1'>x</text>", "unsupported_text"),
    ],
)
def test_recorder_fails_closed_for_unsupported_elements(
    body: str,
    reason: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>"
        f"{body}</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == reason
    assert result.commands == ()


def test_recorder_reports_invalid_svg_without_partial_commands() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg><path d='M0 0H10V10Z'></svg"
    )

    assert result.status == "invalid"
    assert result.reason_code == "invalid_svg"
    assert result.commands == ()


def test_recorder_ignores_non_semantic_data_attributes() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>"
        "<path data-source='fixture' d='M0 0H10V10Z' fill='#00ff00'/>"
        "</svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1


@pytest.mark.parametrize(
    ("style", "reason"),
    [
        ("path { vector-effect: non-scaling-stroke; }", "unsupported_vector_effect"),
        ("path { made-up-paint: 1; }", "unsupported_property"),
        ("path:hover { fill: red; }", "unsupported_css_selector"),
        ("@import url('external.css');", "unsupported_css_at_rule"),
    ],
)
def test_recorder_fails_closed_for_ignored_css(
    style: str,
    reason: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><style>"
        f"{style}"
        "</style><path d='M0 0H10V10Z'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == reason
    assert result.commands == ()


def test_recorder_rejects_external_use_resource() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><use href='external.svg#shape'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_external_resource"
    assert result.commands == ()
