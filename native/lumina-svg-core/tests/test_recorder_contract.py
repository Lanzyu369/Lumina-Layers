"""Contract tests for the narrow LunaSVG paint recorder fork."""

from __future__ import annotations

from pathlib import Path

import pytest

import lumina_svg_core


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_file_apis_accept_unicode_path_components(tmp_path: Path) -> None:
    svg_path = tmp_path / "中文-🐉" / "图像-😀.svg"
    svg_path.parent.mkdir()
    svg_path.write_text(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10' fill='#123456'/>"
        "</svg>",
        encoding="utf-8",
    )

    recording = lumina_svg_core.record_paint_commands(str(svg_path))
    analysis = lumina_svg_core.analyze_svg(svg_path, 10.0, 0.02)

    assert recording.status == "supported"
    assert tuple(recording.commands[0].rgba) == (18, 52, 86, 255)
    assert analysis.status == "supported"
    assert analysis.raw.geometry_count == 1


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


def test_recorder_returns_decoded_image_vectorizer_root_metadata() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<?xml version='1.0'?><!-- leading comment -->"
        "<svg viewBox='0 0 10 10' aria-label='1 > 0' "
        "data-lumina-origin='image&#45;vectorizer'>"
        "<rect width='10' height='10'/></svg>"
    )

    assert result.status == "supported"
    assert result.image_vectorizer_origin is True


def test_recorder_ignores_image_vectorizer_metadata_on_nested_svg() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<svg data-lumina-origin='image-vectorizer' width='10' height='10'>"
        "<rect width='10' height='10'/></svg></svg>"
    )

    assert result.status == "supported"
    assert result.image_vectorizer_origin is False


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
        ("<image href='#internal-image'/>", "unsupported_image"),
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


@pytest.mark.parametrize(
    "body",
    [
        "<path d='M1 5A4 4 0 0 1 9 5L1 5Z'/>",
        "<circle cx='5' cy='5' r='4'/>",
        "<ellipse cx='5' cy='5' rx='4' ry='2'/>",
        "<rect x='1' y='1' width='8' height='8' rx='2'/>",
    ],
)
def test_recorder_fails_closed_for_fixed_segment_arc_sources(
    body: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>"
        f"{body}</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_arc"
    assert result.commands == ()


@pytest.mark.parametrize(
    "svg",
    [
        "<svg><path d='M0 0H10V10Z'></svg",
        "<svg><path d='M0 0H10V10Z'>",
        "<svg><path d='M0 0H10V10Z' fill='red&bogus;'/></svg>",
        "<svg><path d='M0 0H10V10Z&bogus;' fill='red'/></svg>",
        "<svg><path d='M0 0H10V10Z' fill='red' fill='blue'/></svg>",
        "<svg><style>path { fill: red&bogus;; }</style>"
        "<path d='M0 0H10V10Z'/></svg>",
    ],
)
def test_recorder_reports_invalid_svg_without_partial_commands(
    svg: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(svg)

    assert result.status == "invalid"
    assert result.reason_code == "invalid_svg"
    assert result.commands == ()


@pytest.mark.parametrize(
    "svg",
    [
        "<svg viewBox='0 0 10 10'><g>&undefined;"
        "<rect width='10' height='10'/></g></svg>",
        "<svg viewBox='0 0 10 10'><g>bad ]]> text"
        "<rect width='10' height='10'/></g></svg>",
        "<svg viewBox='0 0 10 10' data-x='<'>"
        "<rect width='10' height='10'/></svg>",
        "<svg viewBox='0 0 10 10'><!-- bad--comment -->"
        "<rect width='10' height='10'/></svg>",
        "<svg viewBox='0 0 10 10'><?xml version='1.0'?>"
        "<rect width='10' height='10'/></svg>",
        "<?xml version='1.0' encoding='UTF-16'?>"
        "<svg viewBox='0 0 10 10'><rect width='10' height='10'/></svg>",
    ],
)
def test_recorder_rejects_additional_xml_well_formedness_violations(
    svg: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(svg)

    assert result.status == "invalid"
    assert result.reason_code == "invalid_svg"
    assert result.commands == ()


@pytest.mark.parametrize(
    "svg",
    [
        "<svg viewBox='0 0 10 10' aria-label='&#0;'>"
        "<rect width='10' height='10'/></svg>",
        "<svg viewBox='0 0 10 10' aria-label='&#x110000;'>"
        "<rect width='10' height='10'/></svg>",
        "<svg viewBox='0 0 10 10' aria-label='\x01'>"
        "<rect width='10' height='10'/></svg>",
        "<svg viewBox='0 0 10 10'><style>&#xD800;</style>"
        "<rect width='10' height='10'/></svg>",
        "<svg viewBox='0 0 10 10'><style>&#x1FFFFF;</style>"
        "<rect width='10' height='10'/></svg>",
        "<svg viewBox='0 0 10 10'><style>\x08</style>"
        "<rect width='10' height='10'/></svg>",
    ],
)
def test_recorder_rejects_non_xml_characters(svg: str) -> None:
    result = lumina_svg_core.record_paint_commands_svg(svg)

    assert result.status == "invalid"
    assert result.reason_code == "invalid_svg"
    assert result.commands == ()


@pytest.mark.parametrize(
    "invalid_fragment",
    [
        b"<svg viewBox='0 0 10 10' aria-label='\xff'>",
        b"<svg viewBox='0 0 10 10'><style>\xc0\x80</style>",
    ],
)
def test_file_recorder_rejects_invalid_utf8(
    tmp_path: Path,
    invalid_fragment: bytes,
) -> None:
    svg_path = tmp_path / "invalid-utf8.svg"
    svg_path.write_bytes(
        invalid_fragment
        + b"<rect width='10' height='10'/></svg>"
    )

    result = lumina_svg_core.record_paint_commands(svg_path)

    assert result.status == "invalid"
    assert result.reason_code == "invalid_svg"
    assert result.commands == ()


def test_recorder_accepts_valid_supplementary_xml_character_reference() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10' aria-label='&#x1F600;'>"
        "<rect width='10' height='10'/></svg>"
    )

    assert result.status == "supported"


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


@pytest.mark.parametrize("style", ["bogus; fill:red", "1:x; fill:red"])
def test_recorder_rejects_unrecovered_inline_css_syntax(style: str) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><g fill='blue'>"
        f"<path style='{style}' d='M0 0H10V10Z'/>"
        "</g></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_css_rule"
    assert result.commands == ()


def test_recorder_routes_internal_doctype_to_whole_document_fallback() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<!DOCTYPE svg [<!ENTITY c '#f00'>]>"
        "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10' fill='&c;'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_doctype"
    assert result.commands == ()


@pytest.mark.parametrize(
    "prefix",
    [
        "<!DOCTYPE svg SYSTEM 'https://example.invalid/shape.dtd'>",
        "<?xml-stylesheet href='https://example.invalid/style.css'?>",
    ],
)
def test_recorder_rejects_external_xml_resources(prefix: str) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        prefix
        + "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_external_resource"
    assert result.commands == ()


def test_recorder_rejects_external_use_resource() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><use href='external.svg#shape'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_external_resource"
    assert result.commands == ()


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (
            "<rect width='10' height='10' clip-path='url(#missing)'/>",
            "unresolved_clip_path",
        ),
        ("<use href='#missing'/>", "unresolved_reference"),
    ],
)
def test_recorder_rejects_unresolved_local_references(
    body: str,
    reason: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg viewBox='0 0 10 10'>{body}</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == reason
    assert result.commands == ()


def test_recorder_rejects_xml_base_that_changes_fragment_resolution() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10' xml:base='external.svg'>"
        "<defs><clipPath id='c'><rect width='5' height='5'/></clipPath></defs>"
        "<rect width='10' height='10' clip-path='url(#c)'/>"
        "</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_external_resource"
    assert result.commands == ()


@pytest.mark.parametrize("url_function", ["URL", "Url", "uRl"])
def test_recorder_rejects_case_insensitive_external_url_function(
    url_function: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<rect width='10' height='10' "
        f"fill='{url_function}(https://example.invalid/paint.svg#p)'/>"
        "</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_external_resource"
    assert result.commands == ()


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (
            "<path d='M1 5&#65;4 4 0 0 1 9 5L1 5Z'/>",
            "unsupported_arc",
        ),
        (
            "<rect width='10' height='10' "
            "fill='u&#114;l(https://example.invalid/paint.svg#p)'/>",
            "unsupported_external_resource",
        ),
    ],
)
def test_recorder_checks_capabilities_after_xml_entity_decode(
    body: str,
    reason: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>" f"{body}</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == reason
    assert result.commands == ()


def test_recorder_fails_closed_for_unsupported_css4_color_syntax() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10' fill='rgb(255 0 0)'/>"
        "</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_color_syntax"
    assert result.commands == ()


@pytest.mark.parametrize(
    ("paint", "reason"),
    [
        ("fill='bogus'", "unsupported_color_syntax"),
        ("stroke='context-stroke'", "unsupported_color_syntax"),
        ("color='context-fill' fill='currentColor'", "unsupported_color_syntax"),
        ("fill='#12'", "unsupported_color_syntax"),
        ("fill='rgb(1, 2)'", "unsupported_color_syntax"),
        ("fill='currentColor'", "unsupported_color_reference"),
        ("fill='rgba(0, 0, 0, 0.5)'", "unsupported_partial_alpha"),
        ("fill='#00000080'", "unsupported_partial_alpha"),
        ("fill='url(#missing)'", "unsupported_paint_server"),
        ("style='fill: bogus'", "unsupported_color_syntax"),
    ],
)
def test_recorder_fails_closed_for_invalid_or_ambiguous_paint_tokens(
    paint: str,
    reason: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><g fill='red'>"
        f"<rect width='10' height='10' {paint}/>"
        "</g></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == reason
    assert result.commands == ()


def test_recorder_fails_closed_for_invalid_stylesheet_paint_token() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<style>rect { fill: bogus; }</style>"
        "<rect width='10' height='10'/>"
        "</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_color_syntax"
    assert result.commands == ()


@pytest.mark.parametrize(
    ("paint", "expected_rgba"),
    [
        ("fill='red'", (255, 0, 0, 255)),
        ("fill='#0f0'", (0, 255, 0, 255)),
        ("fill='rgb(0, 0, 255)'", (0, 0, 255, 255)),
    ],
)
def test_recorder_accepts_colors_supported_by_the_fixed_plutovg_parser(
    paint: str,
    expected_rgba: tuple[int, int, int, int],
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<rect width='10' height='10' {paint}/>"
        "</svg>"
    )

    assert result.status == "supported"
    assert [tuple(command.rgba) for command in result.commands] == [expected_rgba]


@pytest.mark.parametrize(
    ("attribute", "value", "reason"),
    [
        ("fill-rule", "bogus", "unsupported_property_value"),
        ("clip-rule", "bogus", "unsupported_property_value"),
        ("visibility", "bogus", "unsupported_property_value"),
        ("overflow", "bogus", "unsupported_property_value"),
        ("display", "block", "unsupported_property_value"),
        ("clip-path", "bogus", "unsupported_clip_path"),
        ("mask", "none", "unsupported_mask"),
        ("stroke-linecap", "triangle", "unsupported_property_value"),
        ("stroke-linejoin", "arcs", "unsupported_property_value"),
        ("stroke-width", "-1", "unsupported_property_value"),
        ("stroke-dasharray", "2 bogus", "unsupported_property_value"),
        ("stroke-dashoffset", "bogus", "unsupported_property_value"),
        ("stroke-miterlimit", "0", "unsupported_property_value"),
        ("fill-opacity", "nan", "unsupported_property_value"),
    ],
)
def test_recorder_fails_closed_for_invalid_known_paint_property_values(
    attribute: str,
    value: str,
    reason: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><g fill-rule='evenodd' visibility='hidden'>"
        f"<path d='M0 0H10V10Z' {attribute}='{value}'/>"
        "</g></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == reason
    assert result.commands == ()


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("d", "M0 0L"),
        ("transform", "translate(bogus)"),
        ("points", "0,0 10,bogus"),
        ("viewBox", "0 0 bogus 10"),
        ("preserveAspectRatio", "sideways"),
    ],
)
def test_recorder_fails_closed_when_lunasvg_rejects_a_known_attribute_value(
    attribute: str,
    value: str,
) -> None:
    element = "path" if attribute in {"d", "transform"} else "polygon"
    if attribute in {"viewBox", "preserveAspectRatio"}:
        svg_attribute = f"{attribute}='{value}'"
        body = "<path d='M0 0H10V10Z'/>"
    else:
        svg_attribute = "viewBox='0 0 10 10'"
        body = f"<{element} {attribute}='{value}'/>"
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg {svg_attribute}>{body}</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_attribute_value"
    assert result.commands == ()


def test_valid_inherited_fill_rule_remains_supported() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><g fill-rule='evenodd'>"
        "<path fill-rule='inherit' d='M0 0H10V10H0Z M2 2H8V8H2Z'/>"
        "</g></svg>"
    )

    assert result.status == "supported"
    assert [command.fill_rule for command in result.commands] == ["evenodd"]


def test_empty_clip_path_fails_closed_without_an_unbalanced_clip_stack() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<defs><clipPath id='empty'/></defs>"
        "<rect width='10' height='10' clip-path='url(#empty)'/>"
        "</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_empty_clip"
    assert result.commands == ()


def test_unsupported_image_is_rejected_before_large_viewport_rendering() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg width='30000' height='30000' viewBox='0 0 30000 30000'>"
        "<image width='30000' height='30000' href='missing.png'/>"
        "</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_image"
    assert result.commands == ()
