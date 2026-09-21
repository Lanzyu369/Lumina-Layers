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
    assert result.schema_version == 4
    assert lumina_svg_core.RECORDER_SCHEMA_VERSION == 4
    assert lumina_svg_core.RESULT_SCHEMA_VERSION == 4
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


def test_nested_svg_does_not_override_root_metadata() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<svg data-lumina-origin='image-vectorizer' width='10' height='10'>"
        "<rect width='10' height='10'/></svg></svg>"
    )

    assert result.status == "supported"
    assert result.image_vectorizer_origin is False
    assert any(command.kind == "fill" for command in result.commands)


@pytest.mark.parametrize("origin", ["10 20", "-10 -20", "1000000 0"])
def test_recorder_applies_nonzero_root_viewbox_origin(
    origin: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg viewBox='{origin} 10 10'>"
        "<rect x='1' y='1' width='8' height='8'/></svg>"
    )

    assert result.status == "supported"
    x, y = (float(value) for value in origin.split())
    assert result.viewport == (0.0, 0.0, 10.0, 10.0)
    assert result.commands[0].matrix == (1.0, 0.0, 0.0, 1.0, -x, -y)


@pytest.mark.parametrize(
    ("root_attributes", "body"),
    [
        (
            "width='100' height='50'",
            "<rect x='10%' y='20%' width='50%' height='40%'/>",
        ),
        (
            "viewBox='0 0 100 100' overflow='hidden'",
            "<rect x='-10' y='-10' width='120' height='120'/>",
        ),
        (
            "viewBox='0 0 100 100' transform='translate(50 20)'",
            "<rect x='10' y='10' width='20' height='20'/>",
        ),
        (
            "viewBox='0 0 100 100' x='50' y='20'",
            "<rect x='10' y='10' width='20' height='20'/>",
        ),
    ],
)
def test_recorder_supports_root_layout_semantics(
    root_attributes: str,
    body: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg {root_attributes}>{body}</svg>"
    )

    assert result.status == "supported"
    assert any(command.kind == "fill" for command in result.commands)


def test_recorder_applies_root_transform_to_paint_commands() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 100 100' transform='translate(50 20)'>"
        "<rect x='10' y='10' width='20' height='20'/></svg>"
    )

    assert result.status == "supported"
    assert result.commands[0].matrix == (
        1.0,
        0.0,
        0.0,
        1.0,
        50.0,
        20.0,
    )


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
def test_recorder_supports_clip_rule_inheritance(
    document: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(document)

    assert result.status == "supported"
    clip_commands = [
        command for command in result.commands if command.kind == "clip_begin"
    ]
    assert len(clip_commands) == 1
    assert clip_commands[0].fill_rule == "evenodd"


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


def test_clip_path_transform_precision_is_preserved_in_recorded_command() -> None:
    svg = (
        "<svg viewBox='0 0 100 100'><defs>"
        "<clipPath id='c' transform='translate(1000000025 0) "
        "translate(-1000000000 0)'>"
        "<rect width='50' height='100'/></clipPath></defs>"
        "<rect width='100' height='100' fill='red' "
        "clip-path='url(#c)'/></svg>"
    )
    recording = lumina_svg_core.record_paint_commands_svg(svg)

    assert recording.status == "supported"
    clip = next(
        command
        for command in recording.commands
        if command.kind == "clip_begin"
    )
    assert clip.transform_operation_count >= 2
    assert clip.transform_coordinates_exact is True
    assert clip.transform_translation_precision_error == 0.0
    assert clip.matrix == pytest.approx((1, 0, 0, 1, 25, 0))

    result = lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )
    assert result.status == "supported"
    assert result.reason_code == ""
    assert result.raw.geometry_count == 1


def test_recorder_preserves_exact_source_path_coordinates() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path d='M0 499.99999 L100 500.00009 L100 550 L0 550 Z'/>"
        "</svg>"
    )

    assert result.status == "supported"
    command = result.commands[0]
    assert command.path_input_precision_error_x == 0.0
    assert command.path_input_precision_error_y == 0.0
    assert command.path_input_precision_error == 0.0
    expected = (
        (0.0, 499.99999),
        (100.0, 500.00009),
        (100.0, 550.0),
        (0.0, 550.0),
    )
    assert len(command.path_points) == len(expected)
    for actual, wanted in zip(command.path_points, expected, strict=True):
        assert actual == pytest.approx(wanted, abs=1e-12)


def test_object_bounding_box_clip_fails_closed_until_precision_is_proven(
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 100 100'><defs>"
        "<clipPath id='c' clipPathUnits='objectBoundingBox'>"
        "<rect width='.5' height='1'/></clipPath></defs>"
        "<rect width='100' height='100' fill='red' "
        "clip-path='url(#c)'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_clip_path_units"
    assert result.commands == ()


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
def test_recorder_supports_nested_svg_coordinate_semantics(
    nested: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg viewBox='0 0 100 100'>{nested}</svg>"
    )

    assert result.status == "supported"
    assert any(command.kind == "fill" for command in result.commands)


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


def test_recorder_decodes_character_references_in_namespace_uris() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg xmlns='http://www.w3.org/2000/sv&#103;' "
        "xmlns:xlink='http://www.w3.org/1999/xlin&#107;' "
        "viewBox='0 0 10 10'><defs>"
        "<rect id='shape' width='5' height='5'/></defs>"
        "<use xlink:href='#shape'/></svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1


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
    ("binding", "expected_status", "expected_reason"),
    [
        ("urn:not-xlink", "unsupported", "unsupported_namespace"),
        ("", "invalid", "invalid_svg"),
    ],
    ids=["shadowed", "unbound"],
)
def test_recorder_rejects_shadowed_or_unbound_xlink_binding(
    binding: str,
    expected_status: str,
    expected_reason: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg xmlns:xlink='http://www.w3.org/1999/xlink' "
        "viewBox='0 0 10 10'><defs>"
        "<rect id='shape' width='5' height='5'/></defs>"
        f"<g xmlns:xlink='{binding}'><use xlink:href='#shape'/></g></svg>"
    )

    assert result.status == expected_status
    assert result.reason_code == expected_reason
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
    ],
    ids=["prefixed_root", "prefixed_child"],
)
def test_recorder_supports_prefixed_svg_namespaces(svg: str) -> None:
    result = lumina_svg_core.record_paint_commands_svg(svg)

    assert result.status == "supported"
    assert len(result.commands) == 1


def test_recorder_rejects_prefixed_svg_with_wrong_binding() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg:svg xmlns:svg='urn:not-svg' viewBox='0 0 10 10'>"
        "<svg:rect width='10' height='10'/></svg:svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_namespace"
    assert result.commands == ()


def test_recorder_ignores_bound_foreign_metadata_attributes() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg xmlns='http://www.w3.org/2000/svg' "
        "xmlns:inkscape='http://www.inkscape.org/namespaces/inkscape' "
        "inkscape:version='1.4' viewBox='0 0 10 10'>"
        "<rect inkscape:label='paint' width='10' height='10'/></svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1


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
def test_svg2_href_wins_over_xlink_href_regardless_of_attribute_order(
    use_attributes: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg xmlns:xlink='http://www.w3.org/1999/xlink' "
        "viewBox='0 0 10 10'><defs>"
        "<rect id='good' width='4' height='4' fill='red'/>"
        "<rect id='bad' x='5' width='4' height='4' fill='blue'/>"
        f"</defs><use {use_attributes}/></svg>"
    )

    assert result.status == "supported"
    assert [tuple(command.rgba) for command in result.commands] == [
        (255, 0, 0, 255)
    ]


@pytest.mark.parametrize(
    ("attribute", "value", "reason"),
    [
        ("paint-order", "stroke fill", "unsupported_paint_order"),
        ("filter", "url(#blur)", "unsupported_filter"),
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
    "svg",
    [
        "<svg viewBox='0 0 10 10'><path fill='red' stroke='blue' "
        "vector-effect='non-scaling-stroke' d='M0 0H10V10H0Z'/></svg>",
        "<svg viewBox='0 0 10 10'><style>"
        "path { vector-effect: non-scaling-stroke; }</style>"
        "<path fill='red' stroke='blue' d='M0 0H10V10H0Z'/></svg>",
        "<svg viewBox='0 0 10 10'><path fill='red' stroke='blue' "
        "vector-effect='non-scaling&#45;stroke' "
        "d='M0 0H10V10H0Z'/></svg>",
    ],
    ids=["attribute", "stylesheet", "decoded-attribute"],
)
def test_recorder_preserves_non_scaling_stroke_for_policy_boundary(
    svg: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(svg)

    assert result.status == "supported"
    assert [command.kind for command in result.commands] == ["fill", "stroke"]
    assert result.has_non_scaling_stroke is True
    assert [command.non_scaling_stroke for command in result.commands] == [
        False,
        True,
    ]


def test_unused_non_scaling_stroke_rule_does_not_trigger_policy_boundary() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><style>"
        ".unused { vector-effect: non-scaling-stroke; }</style>"
        "<path fill='red' stroke='blue' d='M0 0H10V10H0Z'/></svg>"
    )

    assert result.status == "supported"
    assert result.has_non_scaling_stroke is False
    assert [command.non_scaling_stroke for command in result.commands] == [
        False,
        False,
    ]


@pytest.mark.parametrize(
    "value",
    ["0.99999999", "1e-50", "50%"],
)
def test_recorder_preserves_exact_group_opacity_boundaries(
    value: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<rect width='10' height='10' opacity='{value}'/>"
        "</svg>"
    )

    expected = float(value.removesuffix("%")) / (100 if value.endswith("%") else 1)
    assert result.status == "supported"
    assert [command.kind for command in result.commands] == [
        "group_begin",
        "fill",
        "group_end",
    ]
    assert result.commands[0].group_opacity == pytest.approx(
        expected, rel=0, abs=1e-15
    )
    assert result.commands[2].group_opacity == pytest.approx(
        expected, rel=0, abs=1e-15
    )


def test_recorder_groups_leaf_fill_and_stroke_as_one_object() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<rect x='1' y='1' width='8' height='8' fill='red' stroke='blue' "
        "stroke-width='2' opacity='.5'/>"
        "</svg>"
    )

    assert result.status == "supported"
    assert [command.kind for command in result.commands] == [
        "group_begin",
        "fill",
        "stroke",
        "group_end",
    ]
    assert result.commands[0].group_opacity == pytest.approx(0.5)
    assert result.commands[-1].group_opacity == pytest.approx(0.5)


def test_recorder_preserves_nested_group_and_clip_order() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><defs>"
        "<clipPath id='c'><rect width='8' height='8'/></clipPath>"
        "</defs><g opacity='.5' clip-path='url(#c)'>"
        "<g opacity='.25'><rect width='10' height='10' fill='red'/></g>"
        "</g></svg>"
    )

    assert result.status == "supported"
    assert [command.kind for command in result.commands] == [
        "group_begin",
        "clip_begin",
        "group_begin",
        "fill",
        "group_end",
        "clip_end",
        "group_end",
    ]
    assert [
        command.group_opacity
        for command in result.commands
        if command.kind in {"group_begin", "group_end"}
    ] == pytest.approx([0.5, 0.25, 0.25, 0.5])


def test_recorder_omits_identity_group_and_suppresses_zero_group() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 20 10'>"
        "<g opacity='1'><rect width='10' height='10' fill='red'/></g>"
        "<g opacity='0'><rect x='10' width='10' height='10' fill='blue'/></g>"
        "</svg>"
    )

    assert result.status == "supported"
    assert [command.kind for command in result.commands] == ["fill"]
    assert result.commands[0].rgba == (255, 0, 0, 255)


def test_recorder_preserves_use_instance_opacity_group() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 20 10'><defs>"
        "<path id='tile' d='M0 0H10V10H0Z' fill='red'/>"
        "</defs><use href='#tile' x='5' opacity='.3'/></svg>"
    )

    assert result.status == "supported"
    assert [command.kind for command in result.commands] == [
        "group_begin",
        "fill",
        "group_end",
    ]
    assert result.commands[0].group_opacity == pytest.approx(0.3)
    assert result.commands[-1].group_opacity == pytest.approx(0.3)


@pytest.mark.parametrize(
    ("attribute", "expected_alpha"),
    [("fill-opacity", 127), ("stroke-opacity", 127)],
)
def test_recorder_folds_paint_opacity_into_exact_rgba(
    attribute: str,
    expected_alpha: int,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path d='M1 5H9' fill='red' stroke='blue' "
        f"{attribute}='50%'/></svg>"
    )

    assert result.status == "supported"
    command = next(
        command
        for command in result.commands
        if command.kind == ("fill" if attribute == "fill-opacity" else "stroke")
    )
    assert command.rgba[3] == expected_alpha


@pytest.mark.parametrize(
    ("paint", "expected_rgba"),
    [
        ("fill='rgba(255,0,0,0.5)'", (255, 0, 0, 128)),
        ("fill='#00ff0080'", (0, 255, 0, 128)),
        ("fill='rgba(40,40,39,0.996)'", (40, 40, 39, 254)),
    ],
)
def test_recorder_preserves_partial_paint_alpha(
    paint: str,
    expected_rgba: tuple[int, int, int, int],
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<rect width='10' height='10' {paint}/>"
        "</svg>"
    )

    assert result.status == "supported"
    assert [tuple(command.rgba) for command in result.commands] == [
        expected_rgba
    ]


@pytest.mark.parametrize(
    "paint",
    [
        "fill='red' fill-opacity='0.99999999'",
        "fill='red' fill-opacity='1e-50'",
        "fill='rgba(1,2,3,0.99999999)'",
        "fill='rgba(1,2,3,1e-50)'",
        "fill='RGBA(1,2,3,0.99999999)'",
        "fill='rGbA(1,2,3,1e-50)'",
        "color='rgba(1,2,3,0.99999999)' fill='currentColor'",
    ],
)
def test_recorder_marks_source_partial_alpha_before_byte_quantization(
    paint: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<rect width='10' height='10' {paint}/>"
        "</svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1
    assert result.commands[0].has_partial_alpha is True


@pytest.mark.parametrize(
    ("paint", "expected_opacity"),
    [
        ("fill='red' fill-opacity='0.99999999'", 0.99999999),
        ("fill='red' fill-opacity='1e-50'", 1e-50),
        ("fill='rgba(1,2,3,0.99999999)'", 0.99999999),
        ("fill='rgba(1,2,3,1e-50)'", 1e-50),
        ("fill='RGBA(1,2,3,0.99999999)'", 0.99999999),
        ("fill='rGbA(1,2,3,1e-50)'", 1e-50),
        (
            "color='rgba(1,2,3,0.99999999)' fill='currentColor'",
            0.99999999,
        ),
        ("fill='rgba(1,2,3,.5)' fill-opacity='50%'", 0.25),
        ("fill='#12345680'", 128 / 255),
        ("fill='#1238'", 136 / 255),
        (
            "fill='none' stroke='rgba(4,5,6,.25)' stroke-opacity='40%'",
            0.1,
        ),
    ],
)
def test_recorder_preserves_effective_paint_opacity_before_byte_quantization(
    paint: str,
    expected_opacity: float,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<rect width='10' height='10' {paint}/></svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1
    assert result.commands[0].paint_opacity == pytest.approx(
        expected_opacity, rel=0, abs=1e-15
    )


@pytest.mark.parametrize("value", ["linearRGB", "auto"])
def test_non_srgb_color_interpolation_remains_fail_closed(value: str) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<rect width='10' height='10' fill='rgba(255,0,0,.5)' "
        f"color-interpolation='{value}'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_color_interpolation"
    assert result.commands == ()


def test_explicit_srgb_color_interpolation_is_supported() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10' fill='rgba(255,0,0,.5)' "
        "color-interpolation='sRGB'/></svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1
    assert result.commands[0].paint_opacity == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("opacity", "0"),
        ("opacity", "1"),
        ("opacity", "100%"),
        ("opacity", "-0.5"),
        ("opacity", "1.5"),
        ("fill", "rgba(255,0,0,0.000)"),
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


def test_recorder_omits_exact_zero_alpha_rgba_paint() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 20 10'>"
        "<rect width='10' height='10' fill='rgba(0,0,0,0.000)'/>"
        "<rect x='10' width='10' height='10' fill='#ff0000'/>"
        "</svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1
    assert result.commands[0].rgba == (255, 0, 0, 255)


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("<mask id='m'><rect width='1' height='1'/></mask>", "unsupported_mask"),
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


def test_recorder_emits_marker_paint_operations() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 20 10'><defs>"
        "<marker id='m' markerWidth='2' markerHeight='2' refX='1' refY='1'>"
        "<rect width='2' height='2' fill='blue'/></marker></defs>"
        "<path d='M2 5H18' fill='none' stroke='red' "
        "marker-start='url(#m)' marker-end='url(#m)'/></svg>"
    )

    assert result.status == "supported"
    assert [command.kind for command in result.commands] == [
        "stroke",
        "clip_begin",
        "fill",
        "clip_end",
        "clip_begin",
        "fill",
        "clip_end",
    ]
    assert [
        tuple(command.rgba)
        for command in result.commands
        if command.kind in {"fill", "stroke"}
    ] == [
        (255, 0, 0, 255),
        (0, 0, 255, 255),
        (0, 0, 255, 255),
    ]


def test_auto_oriented_marker_rejects_collapsed_source_direction() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 100 100'><defs>"
        "<marker id='m' markerUnits='userSpaceOnUse' markerWidth='30' "
        "markerHeight='10' refX='0' refY='5' orient='auto' "
        "overflow='visible'>"
        "<path d='M0 0 L30 5 L0 10 Z' fill='blue'/>"
        "</marker></defs>"
        "<path d='M500.00013 50.00013 L500.000131 50.000131' "
        "transform='translate(-450 0)' fill='none' stroke='none' "
        "marker-start='url(#m)'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_input_precision"
    assert result.commands == ()


def test_recorder_renders_symbol_through_use() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><defs>"
        "<symbol id='shape' viewBox='0 0 5 5'>"
        "<path d='M0 0H5V5H0Z' fill='green'/></symbol></defs>"
        "<use href='#shape' width='10' height='10'/></svg>"
    )

    assert result.status == "supported"
    assert [
        tuple(command.rgba)
        for command in result.commands
        if command.kind == "fill"
    ] == [
        (0, 128, 0, 255)
    ]


@pytest.mark.parametrize(
    "value",
    [
        " xMidYMid meet",
        "xMidYMid  meet",
        "\txMidYMid meet",
        "none",
        "xMidYMid meet",
        "xMidYMid slice",
    ],
)
def test_root_explicit_preserve_aspect_ratio_is_recorded(
    value: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg width='20' height='10' viewBox='0 0 10 10' "
        f"preserveAspectRatio='{value}'>"
        "<path d='M0 0H10V10H0Z'/></svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1


@pytest.mark.parametrize(
    "path_data",
    [
        "M1 5A4 4 0 0 1 9 5L1 5Z",
        "M1 5a4 4 0 0 1 8 0L1 5Z",
    ],
)
def test_recorder_accepts_path_arc_sources(path_data: str) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>"
        f"<path d='{path_data}'/></svg>"
    )

    assert result.status == "supported"
    assert result.reason_code == ""
    assert len(result.commands) == 1
    assert "cubic_to" in result.commands[0].path_verbs


def test_exact_arc_reduces_full_turns_before_trigonometry() -> None:
    def record(rotation_degrees: str):
        result = lumina_svg_core.record_paint_commands_svg(
            "<svg viewBox='0 0 10 10'>"
            "<path d='M0 0A1000000000 1 "
            f"{rotation_degrees} 0 1 1 0L1 1H0Z'/></svg>"
        )
        assert result.status == "supported"
        return result.commands[0]

    huge_rotation = record("1000000000")
    reduced_rotation = record("280")

    assert huge_rotation.path_verbs == reduced_rotation.path_verbs
    assert len(huge_rotation.path_points) == len(
        reduced_rotation.path_points
    )
    for actual, expected in zip(
        huge_rotation.path_points,
        reduced_rotation.path_points,
        strict=True,
    ):
        assert actual == pytest.approx(expected, rel=0.0, abs=1e-9)
    assert huge_rotation.path_lowering_precision_error == pytest.approx(
        reduced_rotation.path_lowering_precision_error,
        abs=1e-12,
    )


@pytest.mark.parametrize(
    "body",
    [
        "<circle cx='5' cy='5' r='4'/>",
        "<ellipse cx='5' cy='5' rx='4' ry='2'/>",
        "<rect x='1' y='1' width='8' height='8' rx='2'/>",
    ],
)
def test_recorder_converts_shape_arc_sources_to_cubics(body: str) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>"
        f"{body}</svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1
    assert "cubic_to" in result.commands[0].path_verbs


@pytest.mark.parametrize(
    "path_data",
    [
        "M0 0Q3 6 6 0Z",
        "M10 10q3 6 6 0Z",
    ],
)
def test_recorder_accepts_original_quadratic_sources(
    path_data: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<path d='{path_data}'/></svg>"
    )

    assert result.status == "supported"
    assert result.reason_code == ""
    assert len(result.commands) == 1
    assert "cubic_to" in result.commands[0].path_verbs


@pytest.mark.parametrize(
    ("path_data", "expected"),
    [
        ("M1 1L2 2L3 3Z", [False]),
        ("M1 1L2 2L3 2Z", [True]),
        ("M0 0L1e-17 0L0 1e-17Z", [True]),
        ("M1 1L2 2L3 3Z M0 0H10V10H0Z", [False, True]),
    ],
)
def test_recorder_preserves_source_subpath_area_potential(
    path_data: str,
    expected: list[bool],
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<path d='{path_data}' fill='red'/></svg>"
    )

    assert result.status == "supported"
    assert result.commands[0].source_subpath_area_potential == expected


def test_relative_precision_tracks_longest_chain_not_document_token_count() -> None:
    rectangles = " ".join(
        f"M{index * 2} 0h1v1h-1z" for index in range(1_000)
    )
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 2000 1'>"
        f"<path d='{rectangles}' fill='red'/></svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1
    assert result.commands[0].relative_path_operation_count == 3


@pytest.mark.parametrize(
    "path_data",
    [
        "M0 0Q2 5 4 0T10 0Z",
        "M0 0q2 5 4 0t6 0Z",
    ],
)
def test_recorder_converts_smooth_quadratic_sources_to_cubics(
    path_data: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<path d='{path_data}'/></svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1
    assert "cubic_to" in result.commands[0].path_verbs




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
    expected_reason = "unsupported_input_precision"

    assert recording.status == "unsupported"
    assert recording.reason_code == expected_reason
    assert recording.commands == ()
    assert analysis.status == "unsupported"
    assert analysis.reason_code == expected_reason
    assert analysis.raw.geometry_count == 0


def test_non_inherited_property_with_explicit_inherit_is_supported() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 40 20' overflow='visible'>"
        "<svg x='10' y='5' width='10' height='10' viewBox='0 0 10 10' "
        "overflow='inherit'>"
        "<rect x='-5' width='20' height='10' fill='red'/>"
        "</svg></svg>",
        target_width_mm=40.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1


def test_inherited_paint_property_preserves_exact_color() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<g fill='red'><rect fill='inherit' width='10' height='10'/></g>"
        "</svg>",
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1
    assert result.raw.rgba.tolist() == [[255, 0, 0, 255]]


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
        ("path:hover { fill: red; }", "unsupported_css_selector"),
        ("path:is(.a,.b) { fill: red; }", "unsupported_css_selector"),
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


@pytest.mark.parametrize(
    "selector",
    [
        "path:not(:hover)",
        "path:not(g path)",
    ],
)
def test_recorder_fails_closed_for_unsupported_selector_inside_not(
    selector: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><style>"
        f"{selector}{{fill:red}}"
        "</style><path d='M0 0H10V10Z'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_css_selector"
    assert result.commands == ()


def test_recorder_supports_simple_selector_list_inside_not() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 20 10'><style>"
        "path:not(.skip,.hidden){fill:red}"
        "</style>"
        "<path d='M0 0H10V10H0Z'/>"
        "<path class='skip' d='M10 0H20V10H10Z'/>"
        "</svg>"
    )

    assert result.status == "supported"
    assert [tuple(command.rgba) for command in result.commands] == [
        (255, 0, 0, 255),
        (0, 0, 0, 255),
    ]


def test_css_attribute_presence_distinguishes_empty_and_absent_values() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 30 10'><style>"
        "[class]{fill:red}"
        "</style>"
        "<rect class='' width='10' height='10'/>"
        "<rect class='x' x='10' width='10' height='10'/>"
        "<rect x='20' width='10' height='10'/>"
        "</svg>"
    )

    assert result.status == "supported"
    assert [tuple(command.rgba) for command in result.commands] == [
        (255, 0, 0, 255),
        (255, 0, 0, 255),
        (0, 0, 0, 255),
    ]


def test_css_empty_selector_counts_whitespace_and_character_data_nodes() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 30 10'><style>"
        "rect:empty{fill:red}"
        "</style>"
        "<rect width='10' height='10'/>"
        "<rect x='10' width='10' height='10'> </rect>"
        "<rect x='20' width='10' height='10'>x</rect>"
        "</svg>"
    )

    assert result.status == "supported"
    assert [tuple(command.rgba) for command in result.commands] == [
        (255, 0, 0, 255),
        (0, 0, 0, 255),
        (0, 0, 0, 255),
    ]


@pytest.mark.parametrize("value", ["initial", "unset", "revert"])
def test_css_all_shorthand_fails_closed_until_it_is_implemented(
    value: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><style>"
        f"rect{{all:{value}}}"
        "</style><g fill='red'><rect width='10' height='10'/></g></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_css_property"
    assert result.commands == ()


def test_recorder_applies_only_of_type_selector() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 20 10'><style>"
        "rect:only-of-type{fill:red}"
        "</style><g><rect width='10' height='10'/>"
        "<circle cx='15' cy='5' r='5'/></g></svg>"
    )

    assert result.status == "supported"
    assert [tuple(command.rgba) for command in result.commands] == [
        (255, 0, 0, 255),
        (0, 0, 0, 255),
    ]


@pytest.mark.parametrize(
    "body",
    [
        (
            "<style>path{transform:translate(10px,0)}</style>"
            "<path d='M0 0H1V1H0Z'/>"
        ),
        (
            "<style>rect{x:10px}</style>"
            "<rect width='1' height='1'/>"
        ),
        "<path style='transform:translate(10px,0)' d='M0 0H1V1H0Z'/>",
        "<path style='d:path(\"M0 0H1V1H0Z\")' d='M0 0H2V2H0Z'/>",
    ],
)
def test_recorder_fails_closed_for_unimplemented_geometry_css(
    body: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg viewBox='0 0 20 10'>{body}</svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_css_property"
    assert result.commands == ()


@pytest.mark.parametrize(
    "declaration",
    [
        "opacity:.5",
        "filter:url(#missing)",
        "transform:translate(10px,0)",
        "paint-order:stroke fill",
    ],
)
def test_unmatched_unsupported_css_declaration_does_not_reject_document(
    declaration: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><style>"
        f".unused{{{declaration}}}"
        "</style><rect width='10' height='10' fill='red'/></svg>"
    )

    assert result.status == "supported"
    assert result.reason_code == ""
    assert [tuple(command.rgba) for command in result.commands] == [
        (255, 0, 0, 255)
    ]


def test_higher_priority_css_can_override_unsupported_declaration() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><style>"
        ".shape{opacity:.5}#target{opacity:1}"
        "</style><rect id='target' class='shape' width='10' height='10' "
        "fill='red'/></svg>"
    )

    assert result.status == "supported"
    assert result.reason_code == ""
    assert [tuple(command.rgba) for command in result.commands] == [
        (255, 0, 0, 255)
    ]


def test_stylesheet_important_can_override_unsupported_inline_style() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><style>"
        "#target{opacity:1!important}"
        "</style><rect id='target' style='opacity:.5' width='10' height='10' "
        "fill='red'/></svg>"
    )

    assert result.status == "supported"
    assert result.reason_code == ""
    assert [tuple(command.rgba) for command in result.commands] == [
        (255, 0, 0, 255)
    ]


@pytest.mark.parametrize(
    "body",
    [
        (
            "<defs><rect id='unused' width='10' height='10' "
            "style='opacity:.5'/></defs>"
        ),
        "<rect width='10' height='10' style='display:none;opacity:.5'/>",
        (
            "<g visibility='hidden'><rect width='10' height='10' "
            "style='opacity:.5'/></g>"
        ),
        (
            "<g visibility='hidden' style='opacity:.5'>"
            "<rect width='10' height='10'/></g>"
        ),
        (
            "<style>#unused{opacity:.5}</style><defs>"
            "<rect id='unused' width='10' height='10'/></defs>"
        ),
    ],
)
def test_unsupported_css_on_unrendered_element_does_not_reject_document(
    body: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"{body}<rect width='10' height='10' fill='red'/></svg>"
    )

    assert result.status == "supported"
    assert result.reason_code == ""
    assert [tuple(command.rgba) for command in result.commands] == [
        (255, 0, 0, 255)
    ]


def test_css_opacity_on_use_target_records_isolated_group() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><defs>"
        "<rect id='target' width='10' height='10' style='opacity:.5'/>"
        "</defs><use href='#target'/></svg>"
    )

    assert result.status == "supported"
    assert [command.kind for command in result.commands] == [
        "group_begin",
        "fill",
        "group_end",
    ]
    assert result.commands[0].group_opacity == pytest.approx(0.5)


def test_group_css_opacity_wraps_descendant_that_restores_visibility(
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<g visibility='hidden' style='opacity:.5'>"
        "<rect visibility='visible' width='10' height='10'/></g></svg>"
    )

    assert result.status == "supported"
    assert [command.kind for command in result.commands] == [
        "group_begin",
        "fill",
        "group_end",
    ]
    assert result.commands[0].group_opacity == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("stylesheet", "element", "expected_rgba"),
    [
        (
            ".x:not(#other){fill:red} #target{fill:blue}",
            "<path id='target' class='x' d='M0 0H1V1H0Z'/>",
            (255, 0, 0, 255),
        ),
        (
            "#target{fill:blue} [id=target]{fill:red}",
            "<path id='target' d='M0 0H1V1H0Z'/>",
            (0, 0, 255, 255),
        ),
        (
            "path:not(rect){fill:red} .x{fill:blue}",
            "<path class='x' d='M0 0H1V1H0Z'/>",
            (0, 0, 255, 255),
        ),
    ],
)
def test_recorder_uses_css_specificity_for_attribute_and_not_selectors(
    stylesheet: str,
    element: str,
    expected_rgba: tuple[int, int, int, int],
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 1 1'><style>"
        f"{stylesheet}</style>{element}</svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1
    assert tuple(result.commands[0].rgba) == expected_rgba


def test_css_specificity_components_do_not_carry_into_id_weight() -> None:
    repeated_classes = ".a" * 256
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 1 1'><style>"
        f"#target{{fill:blue}}{repeated_classes}{{fill:red}}"
        "</style><path id='target' class='a' d='M0 0H1V1H0Z'/></svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1
    assert tuple(result.commands[0].rgba) == (0, 0, 255, 255)


@pytest.mark.parametrize(
    "body",
    [
        "<style>rect{FILL:red}</style><rect width='1' height='1'/>",
        "<rect style='FiLl:red' width='1' height='1'/>",
    ],
)
def test_css_property_names_are_ascii_case_insensitive(body: str) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg viewBox='0 0 1 1'>{body}</svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1
    assert tuple(result.commands[0].rgba) == (255, 0, 0, 255)


def test_uppercase_geometry_css_cannot_bypass_capability_check() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><style>"
        "rect{TRANSFORM:translate(1px,0)}"
        "</style><rect width='1' height='1'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_css_property"
    assert result.commands == ()


def test_css_important_keyword_is_ascii_case_insensitive() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 1 1'><style>"
        "#target{fill:red!IMPORTANT}.shape{fill:blue}"
        "</style><rect id='target' class='shape' width='1' height='1'/></svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1
    assert tuple(result.commands[0].rgba) == (255, 0, 0, 255)


@pytest.mark.parametrize(
    ("attributes", "reason"),
    [
        ("media='not all'", "unsupported_css_media"),
        ("media='print'", "unsupported_css_media"),
        ("type='text/less'", "unsupported_css_type"),
        ("scoped=''", "unsupported_css_scope"),
    ],
)
def test_style_metadata_is_not_silently_applied_globally(
    attributes: str,
    reason: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 1 1'>"
        f"<style {attributes}>rect{{fill:red}}</style>"
        "<rect width='1' height='1'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == reason
    assert result.commands == ()


@pytest.mark.parametrize(
    "attribute",
    [
        "requiredExtensions='urn:missing'",
        "requiredFeatures='urn:missing'",
        "systemLanguage='zz-ZZ'",
    ],
)
def test_visible_conditional_processing_attribute_fails_closed(
    attribute: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 1 1'>"
        f"<rect {attribute} width='1' height='1' fill='red'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_conditional_processing"
    assert result.commands == ()


def test_unrendered_conditional_processing_attribute_is_inert() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 1 1'><defs>"
        "<rect requiredExtensions='urn:missing' width='1' height='1'/>"
        "</defs><rect width='1' height='1' fill='red'/></svg>"
    )

    assert result.status == "supported"
    assert [tuple(command.rgba) for command in result.commands] == [
        (255, 0, 0, 255)
    ]


def test_path_length_is_not_silently_ignored_for_rendered_geometry() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 100 10'><path d='M0 5H100' pathLength='10' "
        "fill='none' stroke='red' stroke-width='1' "
        "stroke-dasharray='5 5'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_path_length"
    assert result.commands == ()


def test_recorder_ignores_unknown_css_declarations() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><style>"
        "path { made-up-paint: 1; fill: red; }"
        "</style><path d='M0 0H10V10Z'/></svg>"
    )

    assert result.status == "supported"
    assert result.commands[0].rgba == (255, 0, 0, 255)


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


@pytest.mark.parametrize(
    "style",
    [
        "fill:/*comment*/red",
        "fi/*comment*/ll:red",
        "fill:red/*comment*/",
    ],
)
def test_recorder_supports_inline_css_comments(style: str) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<path style='{style}' d='M0 0H10V10H0Z'/>"
        "</svg>"
    )

    assert result.status == "supported"
    assert result.commands[0].rgba == (255, 0, 0, 255)


def test_recorder_rejects_unterminated_inline_css_comment() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path style='fill:/*unterminated' d='M0 0H10V10H0Z'/>"
        "</svg>"
    )

    assert result.status == "unsupported"
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


def test_recorder_converts_entity_decoded_smooth_quadratic() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path d='M0 0Q2 5 4 0&#84;10 0Z'/></svg>"
    )

    assert result.status == "supported"
    assert "cubic_to" in result.commands[0].path_verbs


def test_recorder_checks_external_url_after_xml_entity_decode() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10' "
        "fill='u&#114;l(https://example.invalid/paint.svg#p)'/></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_external_resource"
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
        ("fill='rebeccapurple'", (102, 51, 153, 255)),
        ("fill='aliceblue'", (240, 248, 255, 255)),
        ("fill='rgb(50%, 0%, 0%)'", (128, 0, 0, 255)),
        ("fill='rgba(1, 2, 3, 100%)'", (1, 2, 3, 255)),
        ("fill='hsl(0, 100%, 50%)'", (255, 0, 0, 255)),
        ("fill='hsla(0, 100%, 50%, 1)'", (255, 0, 0, 255)),
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


def test_recorder_omits_fully_transparent_color_paint() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10' fill='rgba(1, 2, 3, 0%)'/>"
        "</svg>"
    )

    assert result.status == "supported"
    assert result.commands == ()


@pytest.mark.parametrize(
    "attributes",
    ["color='blue' fill='currentColor'", "fill='currentColor' color='blue'"],
)
def test_recorder_resolves_current_color_independent_of_attribute_order(
    attributes: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<rect width='10' height='10' {attributes}/></svg>"
    )

    assert result.status == "supported"
    assert [tuple(command.rgba) for command in result.commands] == [
        (0, 0, 255, 255)
    ]


@pytest.mark.parametrize(
    ("attribute", "kind"),
    [("fill-opacity", "fill"), ("stroke-opacity", "stroke")],
)
@pytest.mark.parametrize("value", ["0%", "100%"])
def test_recorder_supports_paint_opacity_percent(
    attribute: str,
    kind: str,
    value: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path d='M1 5H9V9H1Z' fill='red' stroke='blue' "
        f"{attribute}='{value}'/>"
        "</svg>"
    )

    assert result.status == "supported"
    matching = [command for command in result.commands if command.kind == kind]
    if value == "0%":
        assert matching == []
    else:
        assert len(matching) == 1
        assert matching[0].rgba[3] == 255


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
def test_recorder_supports_font_relative_lengths(
    body: str,
) -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        f"<svg viewBox='0 0 20 20'>{body}</svg>"
    )

    assert result.status == "supported"
    assert len(result.commands) == 1


@pytest.mark.parametrize(
    ("attribute", "value", "reason"),
    [
        ("fill-rule", "bogus", "unsupported_property_value"),
        ("clip-rule", "bogus", "unsupported_property_value"),
        ("visibility", "bogus", "unsupported_property_value"),
        ("overflow", "bogus", "unsupported_property_value"),
        ("display", "block", "unsupported_property_value"),
        ("clip-path", "bogus", "unsupported_clip_path"),
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
        "<svg viewBox='0 0 10 10'><g fill-rule='evenodd'>"
        f"<path d='M0 0H10V10Z' {attribute}='{value}'/>"
        "</g></svg>"
    )

    assert result.status == "unsupported"
    assert result.reason_code == reason
    assert result.commands == ()


def test_mask_none_is_a_supported_noop() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10' mask='none' fill='red'/></svg>"
    )

    assert result.status == "supported"
    assert [tuple(command.rgba) for command in result.commands] == [
        (255, 0, 0, 255)
    ]


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


def test_valid_inherited_fill_rule_is_recorded() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><g fill-rule='evenodd'>"
        "<path fill-rule='inherit' d='M0 0H10V10H0Z M2 2H8V8H2Z'/>"
        "</g></svg>"
    )

    assert result.status == "supported"
    assert result.commands[0].fill_rule == "evenodd"


def test_inline_explicit_inherit_is_recorded() -> None:
    result = lumina_svg_core.record_paint_commands_svg(
        "<svg viewBox='0 0 10 10'><g fill='green'>"
        "<path style='fill:inherit' d='M0 0H10V10H0Z'/>"
        "</g></svg>"
    )

    assert result.status == "supported"
    assert result.commands[0].rgba == (0, 128, 0, 255)


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
