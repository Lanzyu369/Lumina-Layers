"""Regression contracts for SVG geometry classification boundaries."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from shapely.ops import unary_union

import core.vector_engine as vector_engine
from core.vector_engine import VectorProcessor


def _processor() -> VectorProcessor:
    processor = object.__new__(VectorProcessor)
    processor.sampling_precision = 0.02
    processor.parse_warnings = []
    processor._parse_expand_stroke_to_fill = False
    return processor


def _parse(tmp_path: Path, source: str):
    svg_path = tmp_path / "source.svg"
    svg_path.write_text(source, encoding="utf-8")
    return _processor()._parse_svg(str(svg_path), target_width_mm=100.0)


@pytest.mark.parametrize(
    "body",
    [
        "",
        '<rect x="0" y="0" width="10" height="10" display="none"/>',
        '<rect x="0" y="0" width="10" height="10" fill="#f00" opacity="0"/>',
        '<rect x="0" y="0" width="10" height="10" fill="rgba(255,0,0,0)"/>',
        '<path d="M0 0 L10 10" fill="none" stroke="none"/>',
        '<path d="M5 5" fill="#f00"/>',
    ],
)
def test_svg_without_visible_geometry_uses_stable_diagnostic(
    tmp_path: Path,
    body: str,
) -> None:
    source = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f"{body}</svg>"
    )

    with pytest.raises(ValueError, match=r"^No valid shapes found in SVG$"):
        _parse(tmp_path, source)


def test_default_vector_policy_uses_stable_diagnostic_for_stroke_only_svg(
    tmp_path: Path,
) -> None:
    source = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<path d="M10 20 H90" fill="none" stroke="#00f" stroke-width="10"/>'
        "</svg>"
    )

    with pytest.raises(ValueError, match=r"^No valid shapes found in SVG$"):
        _parse(tmp_path, source)


def test_viewbox_without_explicit_dimensions_preserves_geometry(tmp_path: Path) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect x="10" y="20" width="30" height="40" fill="#f00"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((10.0, 20.0, 40.0, 60.0), abs=0.1)
    assert geometry.area == pytest.approx(1200.0, rel=0.01)


def test_nested_transform_and_clip_path_preserve_clipped_bounds(
    tmp_path: Path,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><clipPath id="left-half">'
        '<rect x="0" y="0" width="10" height="10"/>'
        "</clipPath></defs>"
        '<g transform="translate(10 5)">'
        '<g transform="scale(2 1)">'
        '<rect x="0" y="0" width="20" height="10" fill="#0f0" '
        'clip-path="url(#left-half)"/>'
        "</g></g></svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((10.0, 5.0, 30.0, 15.0), abs=0.2)
    assert geometry.area == pytest.approx(200.0, rel=0.03)


@pytest.mark.parametrize(
    ("clip_rect", "target_rect", "expected_bounds", "expected_area"),
    [
        (
            'x="25%" y="25%" width="50%" height="50%"',
            'width="100" height="100"',
            (25.0, 25.0, 75.0, 75.0),
            2500.0,
        ),
        (
            'width="50%" height="100%"',
            'x="20" y="30" width="40" height="20"',
            (20.0, 30.0, 50.0, 50.0),
            600.0,
        ),
    ],
)
def test_user_space_clip_percentages_use_document_viewport(
    tmp_path: Path,
    clip_rect: str,
    target_rect: str,
    expected_bounds: tuple[float, float, float, float],
    expected_area: float,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f'<defs><clipPath id="window"><rect {clip_rect}/></clipPath></defs>'
        f'<rect {target_rect} fill="#f00" clip-path="url(#window)"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx(expected_bounds, abs=0.1)
    assert geometry.area == pytest.approx(expected_area, rel=0.01)


@pytest.mark.parametrize(
    ("preserve_aspect_ratio", "expected_bounds", "expected_area"),
    [
        ("", (75.0, 25.0, 125.0, 75.0), 2500.0),
        (' preserveAspectRatio="none"', (50.0, 25.0, 150.0, 75.0), 5000.0),
    ],
)
def test_user_space_clip_percentages_are_not_double_transformed(
    tmp_path: Path,
    preserve_aspect_ratio: str,
    expected_bounds: tuple[float, float, float, float],
    expected_area: float,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" '
        f'viewBox="0 0 100 100"{preserve_aspect_ratio}>'
        '<defs><clipPath id="window">'
        '<rect x="25%" y="25%" width="50%" height="50%"/>'
        "</clipPath></defs>"
        '<rect width="100" height="100" fill="#f00" '
        'clip-path="url(#window)"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx(expected_bounds, abs=0.1)
    assert geometry.area == pytest.approx(expected_area, rel=0.01)


@pytest.mark.parametrize(
    ("transform", "expected_bounds"),
    [
        (
            "rotate(30 40 40)",
            (17.6795, 21.3397, 45.0, 48.6603),
        ),
        (
            "skewX(30)",
            (37.3205, 30.0, 68.8675, 50.0),
        ),
    ],
)
def test_object_bounding_box_clip_uses_untransformed_source_bounds(
    tmp_path: Path,
    transform: str,
    expected_bounds: tuple[float, float, float, float],
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><clipPath id="left-half" clipPathUnits="objectBoundingBox">'
        '<rect x="0" y="0" width="0.5" height="1"/>'
        "</clipPath></defs>"
        '<rect x="20" y="30" width="40" height="20" fill="#f00" '
        f'clip-path="url(#left-half)" transform="{transform}"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx(expected_bounds, abs=0.2)
    assert geometry.area == pytest.approx(400.0, rel=0.02)


@pytest.mark.parametrize(
    ("clip_transform", "clip_width", "target_transform", "expected_bounds", "expected_area"),
    [
        (
            "scale(.5 1)",
            "1",
            "skewX(30)",
            (37.3205, 30.0, 58.8675, 50.0),
            200.0,
        ),
        (
            "translate(.1 0)",
            ".5",
            "rotate(30 40 40)",
            (17.7661, 21.3897, 45.0866, 48.7103),
            400.0,
        ),
    ],
)
def test_object_bounding_box_clip_applies_definition_transform_in_user_space(
    tmp_path: Path,
    clip_transform: str,
    clip_width: str,
    target_transform: str,
    expected_bounds: tuple[float, float, float, float],
    expected_area: float,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><clipPath id="window" clipPathUnits="objectBoundingBox" '
        f'transform="{clip_transform}"><rect width="{clip_width}" height="1"/>'
        "</clipPath></defs>"
        '<rect x="20" y="30" width="40" height="20" fill="#f00" '
        f'clip-path="url(#window)" transform="{target_transform}"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx(expected_bounds, abs=0.2)
    assert geometry.area == pytest.approx(expected_area, rel=0.02)


@pytest.mark.parametrize(
    ("group_transform", "expected_bounds"),
    [
        ("", (10.0, 20.0, 30.0, 50.0)),
        (' transform="translate(10 5)"', (20.0, 25.0, 40.0, 55.0)),
    ],
)
def test_group_clip_path_applies_to_descendant_geometry(
    tmp_path: Path,
    group_transform: str,
    expected_bounds: tuple[float, float, float, float],
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><clipPath id="window">'
        '<rect x="10" y="20" width="20" height="30"/>'
        "</clipPath></defs>"
        f'<g clip-path="url(#window)"{group_transform}>'
        '<rect width="80" height="80" fill="#f00"/>'
        "</g></svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx(expected_bounds, abs=0.1)
    assert geometry.area == pytest.approx(600.0, rel=0.01)


@pytest.mark.parametrize(
    ("hidden_attribute", "expected_max_x", "expected_area"),
    [
        ('opacity="0"', 20.0, 400.0),
        ('visibility="hidden"', 20.0, 400.0),
        ('display="none"', 10.0, 200.0),
    ],
)
def test_group_object_bbox_uses_geometric_not_painted_child_bounds(
    tmp_path: Path,
    hidden_attribute: str,
    expected_max_x: float,
    expected_area: float,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 150 50">'
        '<defs><clipPath id="left-half" clipPathUnits="objectBoundingBox">'
        '<rect width=".5" height="1"/></clipPath></defs>'
        '<g clip-path="url(#left-half)">'
        '<rect width="20" height="20" fill="#f00"/>'
        f'<rect x="100" width="20" height="20" fill="#00f" {hidden_attribute}/>'
        "</g></svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx(
        (0.0, 0.0, expected_max_x, 20.0),
        abs=0.1,
    )
    assert geometry.area == pytest.approx(expected_area, rel=0.01)


def test_clip_path_inherits_evenodd_rule_from_definition(tmp_path: Path) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><clipPath id="frame" clip-rule="evenodd">'
        '<path d="M10 10 H90 V90 H10 Z M30 30 H70 V70 H30 Z"/>'
        "</clipPath></defs>"
        '<rect width="100" height="100" fill="#f00" '
        'clip-path="url(#frame)"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((10.0, 10.0, 90.0, 90.0), abs=0.1)
    assert geometry.area == pytest.approx(4800.0, rel=0.01)
    assert geometry.geom_type == "Polygon"
    assert len(geometry.interiors) == 1


@pytest.mark.parametrize(
    "definition_attributes",
    [
        'clip-rule="evenodd"',
        'clip-rule="evenodd" style="clip-rule: evenodd"',
        'style="clip-rule: evenodd"',
    ],
)
def test_clip_path_evenodd_rule_is_inherited_and_not_overridden_by_fill_rule(
    tmp_path: Path,
    definition_attributes: str,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f'<defs><clipPath id="frame" {definition_attributes}>'
        '<path fill-rule="nonzero" '
        'd="M10 10 H90 V90 H10 Z M30 30 H70 V70 H30 Z"/>'
        "</clipPath></defs>"
        '<rect width="100" height="100" fill="#f00" '
        'clip-path="url(#frame)"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.area == pytest.approx(4800.0, rel=0.01)
    assert geometry.geom_type == "Polygon"
    assert len(geometry.interiors) == 1


def test_clip_path_fill_rule_does_not_replace_default_clip_rule(tmp_path: Path) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><clipPath id="frame" fill-rule="evenodd">'
        '<path d="M10 10 H90 V90 H10 Z M30 30 H70 V70 H30 Z"/>'
        "</clipPath></defs>"
        '<rect width="100" height="100" fill="#f00" '
        'clip-path="url(#frame)"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.area == pytest.approx(6400.0, rel=0.01)
    assert geometry.geom_type == "Polygon"
    assert len(geometry.interiors) == 0


@pytest.mark.parametrize("transparent_attribute", ['opacity="0"', 'fill-opacity="0"'])
def test_clip_path_geometry_ignores_paint_opacity(
    tmp_path: Path,
    transparent_attribute: str,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><clipPath id="window">'
        f'<rect x="10" y="20" width="20" height="30" {transparent_attribute}/>'
        "</clipPath></defs>"
        '<rect width="80" height="80" fill="#f00" '
        'clip-path="url(#window)"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((10.0, 20.0, 30.0, 50.0), abs=0.1)
    assert geometry.area == pytest.approx(600.0, rel=0.01)


@pytest.mark.parametrize("reference_attribute", ["href", "xlink:href"])
def test_clip_path_resolves_use_references_from_document_defs(
    tmp_path: Path,
    reference_attribute: str,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 100 100">'
        '<defs><rect id="clip-shape" x="10" y="20" width="20" height="30"/>'
        f'<clipPath id="window"><use {reference_attribute}="#clip-shape"/>'
        "</clipPath></defs>"
        '<rect width="80" height="80" fill="#f00" '
        'clip-path="url(#window)"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((10.0, 20.0, 30.0, 50.0), abs=0.1)
    assert geometry.area == pytest.approx(600.0, rel=0.01)


@pytest.mark.parametrize(
    ("referenced_definition", "body"),
    [
        (
            '<rect id="shape" width="80" height="80"/>',
            '<use href="#shape" clip-path="url(#window)"/>',
        ),
        (
            '<rect id="shape" width="80" height="80"/>',
            '<g clip-path="url(#window)"><use href="#shape"/></g>',
        ),
        (
            '<symbol id="shape"><rect width="80" height="40"/>'
            '<rect y="40" width="80" height="40"/></symbol>',
            '<use href="#shape" clip-path="url(#window)"/>',
        ),
    ],
)
def test_clip_path_applies_to_referenced_target_geometry(
    tmp_path: Path,
    referenced_definition: str,
    body: str,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f'<defs>{referenced_definition}<clipPath id="window">'
        '<rect x="10" y="20" width="20" height="30"/>'
        f"</clipPath></defs>{body}</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((10.0, 20.0, 30.0, 50.0), abs=0.1)
    assert geometry.area == pytest.approx(600.0, rel=0.01)


@pytest.mark.parametrize(
    ("preserve_aspect_ratio", "expected_bounds", "expected_area"),
    [
        ("", (30.0, 30.0, 50.0, 50.0), 400.0),
        (' preserveAspectRatio="none"', (20.0, 30.0, 60.0, 50.0), 800.0),
    ],
)
def test_symbol_use_applies_viewbox_viewport_mapping(
    tmp_path: Path,
    preserve_aspect_ratio: str,
    expected_bounds: tuple[float, float, float, float],
    expected_area: float,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f'<defs><symbol id="shape" viewBox="0 0 10 10"{preserve_aspect_ratio}>'
        '<rect width="10" height="10"/></symbol></defs>'
        '<use href="#shape" x="20" y="30" width="40" height="20" fill="#f00"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx(expected_bounds, abs=0.1)
    assert geometry.area == pytest.approx(expected_area, rel=0.01)


@pytest.mark.parametrize(
    "use_aspect_ratio",
    ["xMinYMin meet", "xMidYMid slice"],
)
def test_symbol_viewport_ignores_preserve_aspect_ratio_on_use(
    tmp_path: Path,
    use_aspect_ratio: str,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><symbol id="shape" viewBox="0 0 10 10">'
        '<rect width="10" height="10"/></symbol></defs>'
        '<use href="#shape" x="20" y="30" width="40" height="20" '
        f'preserveAspectRatio="{use_aspect_ratio}" fill="#f00"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((30.0, 30.0, 50.0, 50.0), abs=0.1)
    assert geometry.area == pytest.approx(400.0, rel=0.01)


@pytest.mark.parametrize(
    ("symbol_attributes", "rect_attributes", "use_size", "expected_bounds", "expected_area"),
    [
        (
            'viewBox="0 0 10 10" preserveAspectRatio="xMidYMid slice"',
            'width="10" height="10"',
            'width="40" height="20"',
            (20.0, 30.0, 60.0, 50.0),
            800.0,
        ),
        (
            'viewBox="0 0 10 10"',
            'x="-10" y="-10" width="30" height="30"',
            'width="40" height="20"',
            (20.0, 30.0, 60.0, 50.0),
            800.0,
        ),
        (
            'viewBox="0 0 10 10"',
            'width="10" height="10"',
            "",
            (20.0, 30.0, 100.0, 100.0),
            5600.0,
        ),
    ],
)
def test_symbol_use_clips_content_to_its_viewport(
    tmp_path: Path,
    symbol_attributes: str,
    rect_attributes: str,
    use_size: str,
    expected_bounds: tuple[float, float, float, float],
    expected_area: float,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f'<defs><symbol id="shape" {symbol_attributes}>'
        f'<rect {rect_attributes}/></symbol></defs>'
        f'<use href="#shape" x="20" y="30" {use_size} fill="#f00"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx(expected_bounds, abs=0.1)
    assert geometry.area == pytest.approx(expected_area, rel=0.01)


@pytest.mark.parametrize(
    "overflow_attribute",
    ['overflow="visible"', 'style="overflow: visible"'],
)
def test_symbol_visible_overflow_is_not_clipped_to_use_viewport(
    tmp_path: Path,
    overflow_attribute: str,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f'<defs><symbol id="shape" viewBox="0 0 10 10" {overflow_attribute}>'
        '<rect x="-10" y="-10" width="30" height="30"/>'
        '</symbol></defs>'
        '<use href="#shape" x="20" y="30" width="40" height="20" '
        'fill="#f00"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((10.0, 10.0, 70.0, 70.0), abs=0.1)
    assert geometry.area == pytest.approx(3600.0, rel=0.01)


def test_symbol_use_clip_path_uses_mapped_viewport_geometry(tmp_path: Path) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><symbol id="shape" viewBox="0 0 10 10">'
        '<rect width="10" height="10"/></symbol>'
        '<clipPath id="window"><rect x="25" y="35" width="20" height="15"/>'
        "</clipPath></defs>"
        '<use href="#shape" x="20" y="30" width="40" height="20" '
        'fill="#f00" clip-path="url(#window)"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((30.0, 35.0, 45.0, 50.0), abs=0.1)
    assert geometry.area == pytest.approx(225.0, rel=0.01)


def test_symbol_use_object_bbox_clip_uses_mapped_viewport_bounds(
    tmp_path: Path,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><symbol id="shape" viewBox="0 0 10 10">'
        '<rect width="10" height="10"/></symbol>'
        '<clipPath id="left-half" clipPathUnits="objectBoundingBox">'
        '<rect width=".5" height="1"/></clipPath></defs>'
        '<use href="#shape" x="20" y="30" width="40" height="20" '
        'fill="#f00" clip-path="url(#left-half)"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((30.0, 30.0, 40.0, 50.0), abs=0.1)
    assert geometry.area == pytest.approx(200.0, rel=0.01)


@pytest.mark.parametrize(
    "symbol_body",
    [
        '<rect width="10" height="10" clip-path="url(#window)"/>',
        '<g clip-path="url(#window)"><rect width="10" height="10"/></g>',
    ],
)
def test_symbol_internal_user_space_clip_uses_mapped_viewport(
    tmp_path: Path,
    symbol_body: str,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><clipPath id="window"><rect width="5" height="10"/></clipPath>'
        '<symbol id="shape" viewBox="0 0 10 10">'
        f"{symbol_body}</symbol></defs>"
        '<use href="#shape" x="20" y="30" width="40" height="20" '
        'fill="#f00"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((30.0, 30.0, 40.0, 50.0), abs=0.1)
    assert geometry.area == pytest.approx(200.0, rel=0.01)


@pytest.mark.parametrize(
    ("clip_rect", "expected_bounds", "expected_area"),
    [
        (None, (30.0, 30.0, 50.0, 50.0), 400.0),
        ('width="5" height="10"', (30.0, 30.0, 40.0, 50.0), 200.0),
        ('width="50%" height="100%"', (30.0, 30.0, 40.0, 50.0), 200.0),
    ],
)
def test_nested_svg_viewport_and_clip_use_local_user_space(
    tmp_path: Path,
    clip_rect: str | None,
    expected_bounds: tuple[float, float, float, float],
    expected_area: float,
) -> None:
    clip_definition = (
        f'<defs><clipPath id="window"><rect {clip_rect}/></clipPath></defs>'
        if clip_rect is not None
        else ""
    )
    clip_reference = ' clip-path="url(#window)"' if clip_rect is not None else ""
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<svg x="20" y="30" width="40" height="20" viewBox="0 0 10 10">'
        f'{clip_definition}<rect width="10" height="10" fill="#f00"'
        f"{clip_reference}/></svg></svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx(expected_bounds, abs=0.1)
    assert geometry.area == pytest.approx(expected_area, rel=0.01)


@pytest.mark.parametrize(
    ("clip_definition", "clip_reference", "expected_bounds", "expected_area"),
    [
        ("", "", (53.0, 52.0, 73.0, 72.0), 400.0),
        (
            '<defs><clipPath id="window"><rect width="50%" height="100%"/>'
            "</clipPath></defs>",
            ' clip-path="url(#window)"',
            (53.0, 52.0, 63.0, 72.0),
            200.0,
        ),
    ],
)
def test_nested_svg_offsets_are_resolved_in_the_immediate_viewport(
    tmp_path: Path,
    clip_definition: str,
    clip_reference: str,
    expected_bounds: tuple[float, float, float, float],
    expected_area: float,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" '
        'viewBox="0 0 200 200"><g transform="translate(3 4)">'
        '<svg x="20" y="30" width="80" height="60" viewBox="0 0 20 10">'
        '<svg x="5" y="2" width="10" height="5" viewBox="0 0 10 10">'
        f'{clip_definition}<rect width="10" height="10" fill="#f00"'
        f"{clip_reference}/></svg></svg></g></svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx(expected_bounds, abs=0.1)
    assert geometry.area == pytest.approx(expected_area, rel=0.01)


@pytest.mark.parametrize(
    ("overflow", "expected_bounds", "expected_area"),
    [
        ("", (20.0, 30.0, 60.0, 50.0), 800.0),
        (' overflow="visible"', (10.0, 30.0, 70.0, 50.0), 1200.0),
        (' style="overflow: visible"', (10.0, 30.0, 70.0, 50.0), 1200.0),
    ],
)
def test_nested_svg_explicit_axes_and_overflow_preserve_geometry(
    tmp_path: Path,
    overflow: str,
    expected_bounds: tuple[float, float, float, float],
    expected_area: float,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f'<svg x="20" y="30" width="40" height="20" viewBox="0 0 10 10"'
        f'{overflow}><rect x="-10" width="30" height="10" fill="#f00"/>'
        "</svg></svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx(expected_bounds, abs=0.1)
    assert geometry.area == pytest.approx(expected_area, rel=0.01)


@pytest.mark.parametrize(
    "viewport_lengths",
    [
        'x="20px" y="30px" width="40px" height="20px"',
        'x="10%" y="15%" width="20%" height="10%"',
    ],
)
def test_nested_svg_accepts_length_percentage_viewport_values(
    tmp_path: Path,
    viewport_lengths: str,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" '
        'viewBox="0 0 200 200">'
        f'<svg {viewport_lengths} viewBox="0 0 10 10">'
        '<rect width="10" height="10" fill="#f00"/></svg></svg>',
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((30.0, 30.0, 50.0, 50.0), abs=0.1)
    assert geometry.area == pytest.approx(400.0, rel=0.01)


@pytest.mark.parametrize(
    ("rect_attributes", "overflow", "expected_bounds", "expected_area"),
    [
        ('width="10" height="10"', "", (20.0, 30.0, 30.0, 40.0), 100.0),
        (
            'x="0" y="0" width="10" height="10"',
            "",
            (20.0, 30.0, 30.0, 40.0),
            100.0,
        ),
        (
            'width="100" height="100"',
            ' overflow="visible"',
            (20.0, 30.0, 100.0, 100.0),
            5600.0,
        ),
    ],
)
def test_nested_svg_without_viewbox_applies_its_viewport_translation(
    tmp_path: Path,
    rect_attributes: str,
    overflow: str,
    expected_bounds: tuple[float, float, float, float],
    expected_area: float,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f'<svg x="20" y="30" width="40" height="20"{overflow}>'
        f'<rect {rect_attributes} fill="#f00"/></svg></svg>',
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx(expected_bounds, abs=0.1)
    assert geometry.area == pytest.approx(expected_area, rel=0.01)


def test_nested_svg_without_viewbox_resolves_percentage_axes(
    tmp_path: Path,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" '
        'viewBox="0 0 200 100">'
        '<svg x="10%" y="10%" width="50%" height="50%">'
        '<rect width="10" height="10" fill="#f00"/></svg></svg>',
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((20.0, 10.0, 30.0, 20.0), abs=0.1)
    assert geometry.area == pytest.approx(100.0, rel=0.01)


def test_nested_svg_own_clip_uses_its_local_viewport(tmp_path: Path) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><clipPath id="window"><rect width="50%" height="100%"/>'
        '</clipPath></defs>'
        '<svg x="20" y="30" width="40" height="20" viewBox="0 0 10 10" '
        'clip-path="url(#window)">'
        '<rect width="10" height="10" fill="#f00"/></svg></svg>',
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((30.0, 30.0, 40.0, 50.0), abs=0.1)
    assert geometry.area == pytest.approx(200.0, rel=0.01)


def test_non_square_nested_viewport_resolves_clip_percentage_axes(
    tmp_path: Path,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" '
        'viewBox="0 0 200 200"><defs><clipPath id="window">'
        '<rect width="50%" height="100%"/></clipPath></defs>'
        '<svg x="20" y="30" width="40" height="20" '
        'clip-path="url(#window)">'
        '<rect width="40" height="20" fill="#f00"/></svg></svg>',
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((20.0, 30.0, 40.0, 50.0), abs=0.1)
    assert geometry.area == pytest.approx(400.0, rel=0.01)


def test_nested_svg_preserves_explicit_use_position(tmp_path: Path) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" '
        'viewBox="0 0 200 200"><defs>'
        '<rect id="shape" width="5" height="5"/></defs>'
        '<svg x="20" y="30" width="40" height="20" viewBox="0 0 10 10">'
        '<use href="#shape" x="2" y="3" fill="#f00"/></svg></svg>',
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((34.0, 36.0, 44.0, 46.0), abs=0.1)
    assert geometry.area == pytest.approx(100.0, rel=0.01)


@pytest.mark.parametrize(
    ("definition", "expected_bounds", "expected_area"),
    [
        ('<rect id="shape" width="5" height="5"/>', (34.0, 36.0, 44.0, 46.0), 100.0),
        (
            '<symbol id="shape" viewBox="0 0 10 10">'
            '<rect width="10" height="10"/></symbol>',
            (34.0, 36.0, 44.0, 46.0),
            100.0,
        ),
    ],
)
def test_use_percentages_inside_nested_svg_resolve_in_local_viewport(
    tmp_path: Path,
    definition: str,
    expected_bounds: tuple[float, float, float, float],
    expected_area: float,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" '
        f'viewBox="0 0 200 200"><defs>{definition}</defs>'
        '<svg x="20" y="30" width="40" height="20" viewBox="0 0 10 10">'
        '<use href="#shape" x="20%" y="30%" width="50%" height="50%" '
        'fill="#f00"/></svg></svg>',
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx(expected_bounds, abs=0.1)
    assert geometry.area == pytest.approx(expected_area, rel=0.01)


@pytest.mark.parametrize(
    ("use_attributes", "expected_bounds", "expected_area"),
    [
        ("", (30.0, 30.0, 50.0, 50.0), 400.0),
        ('x="0" y="0" width="5" height="10"', (30.0, 35.0, 40.0, 45.0), 100.0),
        (
            'x="0" y="0" width="50%" height="100%"',
            (30.0, 35.0, 40.0, 45.0),
            100.0,
        ),
    ],
)
def test_symbol_use_inside_nested_svg_uses_local_viewport(
    tmp_path: Path,
    use_attributes: str,
    expected_bounds: tuple[float, float, float, float],
    expected_area: float,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" '
        'viewBox="0 0 200 200"><defs>'
        '<symbol id="shape" viewBox="0 0 10 10">'
        '<rect width="10" height="10"/></symbol></defs>'
        '<svg x="20" y="30" width="40" height="20" viewBox="0 0 10 10">'
        f'<use href="#shape" {use_attributes} fill="#f00"/></svg></svg>',
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx(expected_bounds, abs=0.6)
    assert geometry.area == pytest.approx(expected_area, rel=0.03)


def test_user_space_clip_percentages_follow_each_reference_viewport(
    tmp_path: Path,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" '
        'viewBox="0 0 200 200"><defs><clipPath id="window">'
        '<rect width="50%" height="100%"/></clipPath></defs>'
        '<rect y="100" width="100" height="50" fill="#f00" '
        'clip-path="url(#window)"/>'
        '<svg x="20" y="30" width="40" height="20" viewBox="0 0 10 10">'
        '<rect width="10" height="10" fill="#f00" '
        'clip-path="url(#window)"/></svg></svg>',
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((0.0, 30.0, 100.0, 150.0), abs=0.1)
    assert geometry.area == pytest.approx(5200.0, rel=0.01)


def test_object_bounding_box_clip_percentages_follow_browser_viewport_units(
    tmp_path: Path,
) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><clipPath id="left-half" clipPathUnits="objectBoundingBox">'
        '<rect width="50%" height="100%"/></clipPath></defs>'
        '<rect x="20" y="30" width="40" height="20" fill="#f00" '
        'clip-path="url(#left-half)"/></svg>',
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((20.0, 30.0, 60.0, 50.0), abs=0.1)
    assert geometry.area == pytest.approx(800.0, rel=0.01)


def test_clip_path_fragment_excludes_unrelated_document_defs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fragment_payloads: list[bytes] = []
    original_parse = vector_engine.SVG.parse

    def recording_parse(source, *args, **kwargs):
        if isinstance(source, io.BytesIO):
            fragment_payloads.append(source.getvalue())
        return original_parse(source, *args, **kwargs)

    monkeypatch.setattr(
        vector_engine.SVG,
        "parse",
        staticmethod(recording_parse),
    )
    _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<defs><rect id="unrelated-marker" width="100" height="100"/>'
        '<clipPath id="window"><rect width="20" height="20"/></clipPath></defs>'
        '<rect width="80" height="80" fill="#f00" clip-path="url(#window)"/>'
        "</svg>",
    )

    assert fragment_payloads
    assert all(b"unrelated-marker" not in payload for payload in fragment_payloads)


def test_evenodd_compound_path_preserves_hole(tmp_path: Path) -> None:
    shapes, _scale, _bbox = _parse(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<path fill="#f00" fill-rule="evenodd" '
        'd="M10 10 H90 V90 H10 Z M40 40 H60 V60 H40 Z"/>'
        "</svg>",
    )

    geometry = unary_union([shape["poly"] for shape in shapes])
    assert geometry.bounds == pytest.approx((10.0, 10.0, 90.0, 90.0), abs=0.1)
    assert geometry.area == pytest.approx(6000.0, rel=0.01)
    assert geometry.geom_type == "Polygon"
    assert len(geometry.interiors) == 1
