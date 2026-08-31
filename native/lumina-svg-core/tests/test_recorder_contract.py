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


def test_file_entry_accepts_utf8_bom(tmp_path: Path) -> None:
    svg_path = tmp_path / "utf8-bom.svg"
    svg_path.write_bytes(
        b"\xef\xbb\xbf<?xml version='1.0' encoding='UTF-8'?>"
        b"<svg viewBox='0 0 10 10'><rect width='10' height='10'/></svg>"
    )

    recording = lumina_svg_core.record_paint_commands(svg_path)
    analysis = lumina_svg_core.analyze_svg(svg_path, 10.0, 0.02)

    assert recording.status == "supported"
    assert analysis.status == "supported"


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


def test_recorder_preserves_draw_verbs_after_close() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 30 10'>"
        "<path d='M0 0L10 0L0 10Z L30 0L30 10Z' fill='#f00'/>"
        "</svg>"
    )

    assert result.status == "supported"
    assert result.commands[0].path_verbs == (
        "move_to",
        "line_to",
        "line_to",
        "close",
        "line_to",
        "line_to",
        "close",
    )


@pytest.mark.parametrize(
    ("line_cap", "line_join"),
    [
        ("butt", "miter"),
        ("round", "round"),
        ("square", "bevel"),
    ],
)
def test_recorder_exposes_stable_stroke_cap_and_join_names(
    line_cap: str,
    line_join: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path d='M1 5H9' fill='none' stroke='#000' "
        f"stroke-linecap='{line_cap}' stroke-linejoin='{line_join}'/>"
        "</svg>"
    )

    assert result.status == "supported"
    assert result.commands[0].stroke.line_cap == line_cap
    assert result.commands[0].stroke.line_join == line_join


def test_recorder_returns_decoded_image_vectorizer_root_metadata() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<?xml version='1.0'?><!-- leading comment -->"
        "<svg viewBox='0 0 10 10' aria-label='1 > 0' "
        "data-lumina-origin='image&#45;vectorizer'>"
        "<rect width='10' height='10'/></svg>"
    )

    assert result.status == "supported"
    assert result.image_vectorizer_origin is True


def test_recorder_falls_back_before_using_nested_svg_metadata() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<svg data-lumina-origin='image-vectorizer' width='10' height='10'>"
        "<rect width='10' height='10'/></svg></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_nested_svg"
    assert result.image_vectorizer_origin is False


@pytest.mark.parametrize("origin", ["10 20", "-10 -20"])
def test_recorder_falls_back_for_nonzero_root_viewbox_origin(
    origin: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg viewBox='{origin} 10 10'>"
        "<rect x='1' y='1' width='8' height='8'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_viewbox_origin"
    assert result.commands == ()


@pytest.mark.parametrize(
    ("root_attributes", "body", "reason"),
    [
        (
            "width='100' height='50'",
            "<rect x='10%' y='20%' width='50%' height='40%'/>",
            "unsupported_percentage_without_viewbox",
        ),
        (
            "viewBox='0 0 100 100' overflow='hidden'",
            "<rect x='-10' y='-10' width='120' height='120'/>",
            "unsupported_root_overflow",
        ),
        (
            "viewBox='0 0 100 100' transform='translate(50 20)'",
            "<rect x='10' y='10' width='20' height='20'/>",
            "unsupported_root_transform",
        ),
        (
            "viewBox='0 0 100 100' x='50' y='20'",
            "<rect x='10' y='10' width='20' height='20'/>",
            "unsupported_root_position",
        ),
    ],
)
def test_recorder_falls_back_for_root_layout_contract_differences(
    root_attributes: str,
    body: str,
    reason: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg {root_attributes}>{body}</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == reason
    assert result.commands == ()


def test_zero_root_position_remains_supported() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10' x='0px' y='0%'>"
        "<rect width='10' height='10'/></svg>"
    )

    assert result.status == "supported"


@pytest.mark.parametrize(
    "document",
    [
        (
            "<svg viewBox='0 0 100 100' clip-rule='evenodd'>"
            "<defs><clipPath id='c'><path d='M10 10H90V90H10Z "
            "M30 30H70V70H30Z'/></clipPath></defs>"
            "<rect width='100' height='100' clip-path='url(#c)'/>"
            "</svg>"
        ),
        (
            "<svg viewBox='0 0 100 100'><g clip-rule='evenodd'>"
            "<defs><clipPath id='c'><path d='M10 10H90V90H10Z "
            "M30 30H70V70H30Z'/></clipPath></defs>"
            "<rect width='100' height='100' clip-path='url(#c)'/>"
            "</g></svg>"
        ),
        (
            "<svg viewBox='0 0 100 100'>"
            "<defs clip-rule='evenodd'><clipPath id='c'>"
            "<path d='M10 10H90V90H10Z M30 30H70V70H30Z'/>"
            "</clipPath></defs>"
            "<rect width='100' height='100' clip-path='url(#c)'/>"
            "</svg>"
        ),
    ],
    ids=["root", "group", "defs"],
)
def test_recorder_rejects_legacy_incompatible_clip_rule_inheritance(
    document: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(document)

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_clip_rule_inheritance"
    assert result.commands == ()


def test_direct_clip_path_rule_remains_supported() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'><defs>"
        "<clipPath id='c' clip-rule='evenodd'>"
        "<path d='M10 10H90V90H10Z M30 30H70V70H30Z'/>"
        "</clipPath></defs>"
        "<rect width='100' height='100' fill='red' "
        "clip-path='url(#c)'/></svg>",
        100.0,
        0.02,
    )

    assert result.status == "supported", result.reason_code
    assert result.raw.hole_count == 1


@pytest.mark.parametrize(
    "nested",
    [
        (
            "<svg x='10' y='5' width='10' height='10' viewBox='0 0 10 10'>"
            "<rect width='10' height='10'/></svg>"
        ),
        (
            "<svg x='2' y='3' width='10' height='10' viewBox='0 0 10 10' "
            "overflow='visible'><rect x='-5' width='20' height='10'/></svg>"
        ),
        (
            "<svg x='10' y='20' width='40' height='20'>"
            "<rect x='10%' y='20%' width='50%' height='40%'/></svg>"
        ),
        (
            "<svg x='1em' y='1' width='4' height='4' viewBox='0 0 4 4'>"
            "<rect width='4' height='4'/></svg>"
        ),
    ],
)
def test_recorder_falls_back_for_nested_svg_coordinate_semantics(
    nested: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg viewBox='0 0 100 100'>{nested}</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_nested_svg"
    assert result.commands == ()


@pytest.mark.parametrize(
    "svg",
    [
        "<svg xmlns='urn:not-svg' viewBox='0 0 10 10'>"
        "<rect width='10' height='10'/></svg>",
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>"
        "<g xmlns='urn:not-svg'><rect width='10' height='10'/></g></svg>",
        "<svg xmlns:xlink='urn:not-xlink' viewBox='0 0 10 10'>"
        "<rect width='10' height='10'/></svg>",
    ],
)
def test_recorder_fails_closed_for_wrong_namespace_bindings(svg: str) -> None:
    result = lumina_svg_core.record_paint_commands_svg(svg)

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_namespace"
    assert result.commands == ()


def test_recorder_accepts_canonical_svg_and_xlink_namespace_bindings() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg xmlns='http://www.w3.org/2000/svg' "
        "xmlns:xlink='http://www.w3.org/1999/xlink' viewBox='0 0 10 10'>"
        "<rect width='10' height='10'/></svg>"
    )

    assert result.status == "supported"


@pytest.mark.parametrize(
    "attribute",
    [
        "inkscape:label='shape'",
        "sodipodi:nodetypes='cccc'",
        "xlink:href='#shape'",
    ],
)
def test_recorder_rejects_unbound_attribute_prefixes(attribute: str) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<rect {attribute} width='10' height='10'/></svg>"
    )

    assert result.status == "invalid"
    assert result.reason_code == "invalid_svg"
    assert result.commands == ()


def test_recorder_resolves_inherited_xlink_binding() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg xmlns:xlink='http://www.w3.org/1999/xlink' "
        "viewBox='0 0 10 10'><defs>"
        "<rect id='shape' width='5' height='5'/></defs>"
        "<g><use xlink:href='#shape'/></g></svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1


def test_recorder_resolves_binding_declared_later_on_same_element() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><defs>"
        "<rect id='shape' width='5' height='5'/></defs>"
        "<use xlink:href='#shape' "
        "xmlns:xlink='http://www.w3.org/1999/xlink'/></svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1


@pytest.mark.parametrize(
    "binding",
    ["urn:not-xlink", ""],
    ids=["shadowed", "unbound"],
)
def test_recorder_rejects_shadowed_or_unbound_xlink_binding(
    binding: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg xmlns:xlink='http://www.w3.org/1999/xlink' "
        "viewBox='0 0 10 10'><defs>"
        "<rect id='shape' width='5' height='5'/></defs>"
        f"<g xmlns:xlink='{binding}'><use xlink:href='#shape'/></g></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_namespace"
    assert result.commands == ()


def test_recorder_keeps_predefined_xml_prefix_available() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10' xml:lang='en'>"
        "<rect width='10' height='10'/></svg>"
    )

    assert result.status == "supported"


@pytest.mark.parametrize(
    "svg",
    [
        (
            "<svg:svg xmlns:svg='http://www.w3.org/2000/svg' "
            "viewBox='0 0 10 10'>"
            "<svg:rect width='10' height='10'/></svg:svg>"
        ),
        (
            "<svg xmlns='http://www.w3.org/2000/svg' "
            "xmlns:svg='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>"
            "<svg:rect width='10' height='10'/></svg>"
        ),
        (
            "<svg:svg xmlns:svg='urn:not-svg' viewBox='0 0 10 10'>"
            "<svg:rect width='10' height='10'/></svg:svg>"
        ),
    ],
    ids=["prefixed_root", "prefixed_child", "wrong_prefix_binding"],
)
def test_recorder_falls_back_for_prefixed_svg_namespaces(svg: str) -> None:
    result = lumina_svg_core.record_paint_commands_svg(svg)

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_namespace"
    assert result.commands == ()


@pytest.mark.parametrize(
    "svg",
    [
        (
            "<svg viewBox='0 0 10 10'>"
            "<备注/><rect width='10' height='10'/></svg>"
        ),
        (
            "<svg viewBox='0 0 10 10'>"
            "<rect 名称='x' width='10' height='10'/></svg>"
        ),
        (
            "<前:svg xmlns:前='http://www.w3.org/2000/svg' "
            "viewBox='0 0 10 10'>"
            "<前:rect width='10' height='10'/></前:svg>"
        ),
        (
            "<svg xmlns:前='http://www.w3.org/2000/svg' "
            "viewBox='0 0 10 10'>"
            "<前:备注/><rect width='10' height='10'/></svg>"
        ),
    ],
    ids=["element", "attribute", "prefix", "local_name"],
)
def test_recorder_falls_back_for_non_ascii_xml_names(svg: str) -> None:
    result = lumina_svg_core.record_paint_commands_svg(svg)

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_xml_name"
    assert result.commands == ()


def test_non_ascii_xml_values_and_text_remain_supported() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>中文"
        "<rect id='中文' aria-label='图形' width='10' height='10'/></svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1


def test_non_name_unicode_codepoint_stays_invalid_xml() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><\u00a0rect width='10' height='10'/></svg>"
    )

    assert result.status == "invalid"
    assert result.reason_code == "invalid_svg"
    assert result.commands == ()


@pytest.mark.parametrize(
    "svg",
    [
        "<svg viewBox='0 0 10 10'><g><rect width='1' height='1'/></a>"
        "</svg>",
        "<svg viewBox='0 0 10 10'><a><rect width='1' height='1'/></g>"
        "</svg>",
        (
            "<svg:svg xmlns:svg='http://www.w3.org/2000/svg' "
            "xmlns:other='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>"
            "<svg:rect width='1' height='1'/></other:svg>"
        ),
    ],
    ids=["g_closed_by_a", "a_closed_by_g", "different_prefix"],
)
def test_recorder_rejects_mismatched_exact_element_names(svg: str) -> None:
    result = lumina_svg_core.record_paint_commands_svg(svg)

    assert result.status == "invalid"
    assert result.reason_code == "invalid_svg"
    assert result.commands == ()


@pytest.mark.parametrize(
    "use_attributes",
    [
        "href='#good' xlink:href='#bad'",
        "xlink:href='#bad' href='#good'",
    ],
    ids=["href_then_xlink", "xlink_then_href"],
)
def test_recorder_fails_closed_for_competing_href_forms(
    use_attributes: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg xmlns:xlink='http://www.w3.org/1999/xlink' "
        "viewBox='0 0 10 10'><defs>"
        "<rect id='good' width='4' height='4' fill='red'/>"
        "<rect id='bad' x='5' width='4' height='4' fill='blue'/>"
        f"</defs><use {use_attributes}/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_href_precedence"
    assert result.commands == ()


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
    ("attribute", "value"),
    [
        ("opacity", "0.99999999"),
        ("opacity", "1e-50"),
        ("fill-opacity", "0.99999999"),
        ("fill-opacity", "1e-50"),
        ("fill", "rgba(255,0,0,0.99999999)"),
        ("fill", "rgba(255,0,0,1e-50)"),
    ],
)
def test_recorder_fails_closed_before_partial_alpha_rounds_to_endpoint(
    attribute: str,
    value: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<rect width='10' height='10' {attribute}='{value}'/>"
        "</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_partial_alpha"
    assert result.commands == ()


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("opacity", "0"),
        ("opacity", "1"),
        ("opacity", "100%"),
        ("opacity", "-0.5"),
        ("opacity", "1.5"),
        ("fill", "rgba(255,0,0,1)"),
    ],
)
def test_recorder_keeps_exact_or_clamped_alpha_endpoints_supported(
    attribute: str,
    value: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<rect width='10' height='10' {attribute}='{value}'/>"
        "</svg>"
    )

    assert result.status == "supported"


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
    "path_data",
    [
        "M0 0Q5 10 10 0Z",
        "M0 0q5 10 10 0Z",
        "M0 0Q2 5 4 0T10 0Z",
        "M0 0q2 5 4 0t6 0Z",
    ],
)
def test_recorder_fails_closed_for_original_quadratic_sources(
    path_data: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<path d='{path_data}'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_quadratic"
    assert result.commands == ()


def test_recorder_rejects_long_absolute_smooth_quadratic_chain() -> None:
    # PlutoVG reflects the previous control point while lowering each T to a
    # cubic. Repeating that float operation can exceed the physical budget,
    # so v0.1 must reject the original source before geometry replay.
    chain = " ".join(
        f"T{10 + index % 81} {10 + (index * 37) % 81}"
        for index in range(6000)
    )
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path d='M0 0Q0 30 0 50 " + chain + " L100 0Z'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.015,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_quadratic"
    assert result.raw.geometry_count == 0


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
    "body",
    [
        (
            "<defs>"
            "<clipPath id='c'><rect width='5' height='10'/></clipPath>"
            "<clipPath id='&#x63;'><rect x='5' width='5' height='10'/>"
            "</clipPath></defs>"
            "<rect width='10' height='10' clip-path='url(#c)'/>"
        ),
        (
            "<defs><path id='shape' d='M0 0H4V4H0Z'/>"
            "<path id='shape' d='M6 6H10V10H6Z'/></defs>"
            "<use href='#shape'/>"
        ),
        (
            "<style>#paint { fill: red; }</style>"
            "<rect id='paint' width='4' height='4'/>"
            "<rect id='paint' x='6' y='6' width='4' height='4'/>"
        ),
    ],
)
def test_recorder_rejects_duplicate_nonempty_ids_after_entity_decode(
    body: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg viewBox='0 0 10 10'>{body}</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_duplicate_id"
    assert result.commands == ()


@pytest.mark.parametrize(
    "svg",
    [
        (
            "<svg viewBox='0 0 10 10'>"
            "<rect width='1e-46' height='1' fill='red'/>"
            "<rect x='5' width='1' height='1' fill='blue'/>"
            "</svg>"
        ),
        (
            "<svg viewBox='0 0 10 10'>"
            "<path d='M0 0H1e-46V1H0Z' fill='red'/>"
            "<rect x='5' width='1' height='1' fill='blue'/>"
            "</svg>"
        ),
        (
            "<svg viewBox='0 0 10 10'>"
            "<polygon points='0,0 1e-46,0 0,1' fill='red'/>"
            "<rect x='5' width='1' height='1' fill='blue'/>"
            "</svg>"
        ),
        (
            "<svg viewBox='0 0 10 10'>"
            "<line x1='0' y1='0' x2='1e-46' y2='0' stroke='red' "
            "stroke-width='1' stroke-linecap='round'/>"
            "<rect x='5' width='1' height='1' fill='blue'/>"
            "</svg>"
        ),
        (
            "<svg viewBox='0 0 10 10'>"
            "<rect width='1' height='1' transform='scale(1e-46 1)' "
            "fill='red'/>"
            "<rect x='5' width='1' height='1' fill='blue'/>"
            "</svg>"
        ),
        (
            "<svg viewBox='0 0 10 10' overflow='visible'>"
            "<svg width='10' height='10' viewBox='0 0 1e-45 1' "
            "preserveAspectRatio='none' overflow='visible'>"
            "<rect width='1e-46' height='1' fill='red'/></svg>"
            "<rect x='5' width='1' height='1' fill='blue'/></svg>"
        ),
    ],
    ids=["rect", "path", "polygon", "line", "transform", "nested_viewport"],
)
def test_nonzero_geometry_that_underflows_float_fails_closed(svg: str) -> None:
    recording = lumina_svg_core.record_paint_commands_svg(svg)
    analysis = lumina_svg_core.analyze_svg_svg(svg, 100.0, 0.02)
    expected_reason = (
        "unsupported_nested_svg"
        if "<svg width='10'" in svg
        else "unsupported_input_precision"
    )

    assert recording.status == "unsupported"
    assert recording.reason_code == expected_reason
    assert recording.commands == ()
    assert analysis.status == "unsupported"
    assert analysis.reason_code == expected_reason
    assert analysis.raw.geometry_count == 0


def test_non_inherited_property_with_explicit_inherit_fails_closed() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 40 20' overflow='visible'>"
        "<svg x='10' y='5' width='10' height='10' viewBox='0 0 10 10' "
        "overflow='inherit'>"
        "<rect x='-5' width='20' height='10' fill='red'/>"
        "</svg></svg>",
        target_width_mm=40.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_nested_svg"
    assert result.raw.geometry_count == 0


def test_inherited_paint_property_falls_back_for_legacy_parity() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<g fill='red'><rect fill='inherit' width='10' height='10'/></g>"
        "</svg>",
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_legacy_explicit_inherit"
    assert result.raw.geometry_count == 0


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
        "<![CDATA[junk]]><svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10'/></svg>",
        "<svg viewBox='0 0 10 10'><rect width='10' height='10'/>"
        "</svg><![CDATA[junk]]>",
    ],
)
def test_recorder_rejects_additional_xml_well_formedness_violations(
    svg: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(svg)

    assert result.status == "invalid"
    assert result.reason_code == "invalid_svg"
    assert result.commands == ()


def test_declared_non_utf8_in_memory_routes_to_whole_document_fallback() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<?xml version='1.0' encoding='UTF-16'?>"
        "<svg viewBox='0 0 10 10'><rect width='10' height='10'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_xml_encoding"
    assert result.commands == ()


@pytest.mark.parametrize(
    ("declared_encoding", "python_encoding", "bom"),
    [
        ("ISO-8859-1", "iso-8859-1", b""),
        ("UTF-16LE", "utf-16-le", b"\xff\xfe"),
        ("UTF-16BE", "utf-16-be", b"\xfe\xff"),
    ],
)
def test_file_entry_routes_valid_non_utf8_xml_to_whole_document_fallback(
    tmp_path: Path,
    declared_encoding: str,
    python_encoding: str,
    bom: bytes,
) -> None:
    svg_path = tmp_path / f"valid-{declared_encoding}.svg"
    document = (
        f"<?xml version='1.0' encoding='{declared_encoding}'?>"
        "<svg viewBox='0 0 10 10' aria-label='café'>"
        "<rect width='10' height='10'/></svg>"
    )
    svg_path.write_bytes(bom + document.encode(python_encoding))

    recording = lumina_svg_core.record_paint_commands(svg_path)
    analysis = lumina_svg_core.analyze_svg(svg_path, 10.0, 0.02)

    assert recording.status == "unsupported"
    assert recording.reason_code == "unsupported_xml_encoding"
    assert recording.commands == ()
    assert analysis.status == "unsupported"
    assert analysis.reason_code == "unsupported_xml_encoding"


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
    ("prefix", "reason"),
    [
        (
            "<!DOCTYPE svg SYSTEM 'https://example.invalid/shape.dtd'>",
            "unsupported_doctype",
        ),
        (
            "<?xml-stylesheet href='https://example.invalid/style.css'?>",
            "unsupported_external_resource",
        ),
    ],
)
def test_recorder_rejects_external_xml_resources(
    prefix: str,
    reason: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        prefix
        + "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10'/></svg>"
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
        ("fill='rebeccapurple'", "unsupported_color_syntax"),
        ("fill='aliceblue'", "unsupported_color_syntax"),
        ("fill='rgb(50%, 0%, 0%)'", "unsupported_color_syntax"),
        ("fill='rgba(1, 2, 3, 100%)'", "unsupported_color_syntax"),
        ("fill='rgba(1, 2, 3, 0%)'", "unsupported_color_syntax"),
        ("fill='hsl(0, 100%, 50%)'", "unsupported_color_syntax"),
        ("fill='hsla(0, 100%, 50%, 1)'", "unsupported_color_syntax"),
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


@pytest.mark.parametrize("attribute", ["fill-opacity", "stroke-opacity"])
@pytest.mark.parametrize("value", ["0%", "100%"])
def test_recorder_falls_back_for_legacy_incompatible_paint_opacity_percent(
    attribute: str,
    value: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<rect width='10' height='10' fill='red' {attribute}='{value}'/>"
        "</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_opacity_syntax"
    assert result.commands == ()


@pytest.mark.parametrize(
    "body",
    [
        "<rect x='1em' y='1' width='4' height='4'/>",
        "<rect x='1ex' y='1' width='4' height='4'/>",
        "<rect x='1' y='1em' width='4' height='4'/>",
        "<rect x='1' y='1' width='1em' height='4'/>",
        "<rect x='1' y='1' width='4' height='1ex'/>",
        (
            "<path d='M1 5H9' fill='none' stroke='red' "
            "stroke-width='1em'/>"
        ),
        (
            "<path d='M1 5H9' fill='none' stroke='red' stroke-width='1' "
            "stroke-dasharray='1em 2'/>"
        ),
        (
            "<g font-size='20'><rect x='1em' y='1' width='4' "
            "height='4'/></g>"
        ),
    ],
)
def test_recorder_falls_back_for_legacy_incompatible_font_relative_lengths(
    body: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg viewBox='0 0 20 20'>{body}</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_font_relative_length"
    assert result.commands == ()


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


def test_valid_inherited_fill_rule_falls_back_for_legacy_parity() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><g fill-rule='evenodd'>"
        "<path fill-rule='inherit' d='M0 0H10V10H0Z M2 2H8V8H2Z'/>"
        "</g></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_legacy_explicit_inherit"
    assert result.commands == ()


def test_inline_explicit_inherit_falls_back_for_legacy_parity() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><g fill='green'>"
        "<path style='fill:inherit' d='M0 0H10V10H0Z'/>"
        "</g></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_legacy_explicit_inherit"
    assert result.commands == ()


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
