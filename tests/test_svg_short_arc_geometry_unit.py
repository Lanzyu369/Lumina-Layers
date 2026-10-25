"""Synthetic regressions for endpoint arcs with very large radii."""

from pathlib import Path
import io
import math
from decimal import Decimal, localcontext

import pytest
from shapely.geometry import box
from svgelements import Arc, CubicBezier, Image, Path as SvgPath, Shape, SVG, Text

from core.svg_arc_geometry import parse_svg_document, parse_svg_path
from core.vector_engine import VectorProcessor


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("sweep", [0, 1])
def test_short_arc_keeps_its_shape_and_unrelated_square(
    tmp_path: Path, direct: bool, sweep: int,
) -> None:
    source = tmp_path / "short-arc.svg"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">'
        f'<path fill="#ff0000" fill-rule="evenodd" '
        f'd="M10 10 A1e13 1e13 0 0 {sweep} 12 10 L12 12 L10 12 Z"/>'
        '<path fill="#0000ff" fill-rule="evenodd" '
        'd="M20 20 H24 V24 H20 Z"/></svg>',
        encoding="utf-8",
    )
    processor = object.__new__(VectorProcessor)
    processor.sampling_precision = 0.02
    processor._parse_expand_stroke_to_fill = False
    processor._parse_direct_top_level_paths_fast_path = direct

    shapes, scale, bounds = processor._parse_svg(str(source), 40.0)

    assert bounds == pytest.approx((0.0, 0.0, 40.0, 40.0))
    assert scale == pytest.approx(1.0)
    by_color = {shape["color"]: shape["poly"] for shape in shapes}
    assert set(by_color) == {(255, 0, 0), (0, 0, 255)}
    assert by_color[(255, 0, 0)].symmetric_difference(box(10, 10, 12, 12)).area < 1e-6
    assert by_color[(0, 0, 255)].equals(box(20, 20, 24, 24))


@pytest.mark.parametrize("large_arc", [0, 1])
@pytest.mark.parametrize("sweep", [0, 1])
@pytest.mark.parametrize("radii", [(1e13, 1e13), (1e13, 1.0)])
def test_original_arc_flags_preserve_minor_and_major_ellipses(
    large_arc: int, sweep: int, radii: tuple[float, float],
) -> None:
    rx, ry = radii
    path = parse_svg_path(
        f"M-1 0 A{rx} {ry} 0 {large_arc} {sweep} 1 0", 0.02,
    )
    curves = [segment for segment in path if isinstance(segment, CubicBezier)]
    assert curves
    middle_index = len(curves) // 2
    middle = curves[middle_index].point(0.0 if len(curves) % 2 == 0 else 0.5)
    expected_sign = 1 if sweep == 0 else -1
    assert math.copysign(1.0, middle.y) == expected_sign
    if large_arc:
        assert abs(middle.y) == pytest.approx(2.0 * ry, rel=1e-12)
    else:
        assert abs(middle.y) <= ry / rx**2
    assert tuple(curves[0].start) == (-1.0, 0.0)
    assert tuple(curves[-1].end) == (1.0, 0.0)


@pytest.mark.parametrize("following", ["S4 2 5 1", "T5 1"])
def test_smooth_command_after_arc_keeps_original_control_semantics(following: str) -> None:
    data = f"M0 0 A1e13 1e13 0 0 0 2 0 {following}"
    original = SvgPath(data)
    conditioned = parse_svg_path(data, 0.0001)
    assert conditioned[-1] == original[-1]


def test_relative_repeated_arcs_and_compact_flags_share_the_same_parser() -> None:
    path = parse_svg_path("m1 1 a1e13 1e13 0 002 0 1e13 1e13 0 01 2 0", 0.0001)
    assert tuple(path[-1].end) == (5.0, 1.0)
    assert len([segment for segment in path if isinstance(segment, CubicBezier)]) == 2


@pytest.mark.parametrize("large_arc", [0, 1])
@pytest.mark.parametrize("sweep", [0, 1])
def test_angle_rounding_cannot_swap_small_and_large_arc_at_any_coordinate_scale(
    large_arc: int, sweep: int,
) -> None:
    path = parse_svg_path(f"M-1e-13 0 A1 1 0 {large_arc} {sweep} 1e-13 0", 0.02)
    points = [segment.point(t) for segment in list(path)[1:] for t in (0, 0.5, 1)]
    maximum_y = max(abs(point.y) for point in points)
    assert (maximum_y > 1.0) == bool(large_arc)


@pytest.mark.parametrize("sweep", [0, 1])
@pytest.mark.parametrize("rotation", [0, 37])
def test_eccentric_short_arc_retains_visible_curvature(sweep: int, rotation: int) -> None:
    angle = math.radians(rotation)
    sin_angle, cos_angle = math.sin(angle), math.cos(angle)
    data = (
        f"M{sin_angle:.17g} {-cos_angle:.17g} "
        f"A1e13 1e6 {rotation} 0 {sweep} {-sin_angle:.17g} {cos_angle:.17g}"
    )
    path = parse_svg_path(data, 0.0001)
    assert len(path) == 2
    midpoint = path[-1].point(0.5)
    # Independent ellipse sagitta using high-precision arithmetic. The chord
    # is only 2 units long but its visible bulge is 5 units, not a straight line.
    with localcontext() as context:
        context.prec = 60
        sagitta = float(Decimal("1e13") * (1 - (1 - Decimal("1e-12")).sqrt()))
    expected_x = sagitta * (1 if sweep == 1 else -1)
    assert midpoint.x == pytest.approx(expected_x * cos_angle, abs=1e-10)
    assert midpoint.y == pytest.approx(expected_x * sin_angle, abs=1e-10)


def test_major_arc_cubic_error_stays_within_source_budget() -> None:
    radius, tolerance = 1e6, 0.0001
    path = parse_svg_path(f"M-1 0 A{radius} {radius} 0 1 1 1 0", tolerance)
    curves = [segment for segment in path if isinstance(segment, CubicBezier)]
    assert len(curves) > 4
    with localcontext() as context:
        context.prec = 60
        r = Decimal(str(radius))
        center_y = -(r * r - 1).sqrt()
        for curve in curves:
            for t in (0.1, 0.25, 0.5, 0.75, 0.9):
                point = curve.point(t)
                x = Decimal.from_float(float(point.x))
                y = Decimal.from_float(float(point.y)) - center_y
                radial_error = abs((x * x + y * y).sqrt() - r)
                assert radial_error <= Decimal(str(tolerance))


@pytest.mark.parametrize("matrix", ["matrix(2 .5 .75 3 4 -7)", "matrix(-2 .5 .75 3 4 -7)"])
def test_conditioned_cubic_keeps_original_affine_transform(matrix: str) -> None:
    source = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">'
        f'<g transform="{matrix}"><path d="M0 -1 A1e13 1e6 0 0 1 0 1"/></g></svg>'
    )
    original = SVG.parse(io.StringIO(source), reify=False)
    transform = next(element for element in original.elements() if isinstance(element, SvgPath)).transform
    conditioned = parse_svg_document(io.StringIO(source), 0.0001)
    path = next(element for element in conditioned.elements() if isinstance(element, SvgPath))
    expected = parse_svg_path("M0 -1 A1e13 1e6 0 0 1 0 1", 0.00001)
    expected *= transform
    expected.reify()
    assert list(path) == list(expected)


def test_document_keeps_legacy_partial_path_error_semantics() -> None:
    source = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
        '<path fill="red" d="M0 0A1e13 1e13 0 0 0 2 0L2 2Z L"/>'
        '<path fill="blue" d="M10 10H14V14H10Z"/></svg>'
    )
    document = parse_svg_document(io.StringIO(source), 0.0001)
    paths = [element for element in document.elements() if isinstance(element, SvgPath)]
    assert len(paths) == 2
    assert isinstance(paths[0][1], CubicBezier)
    assert paths[0].bbox() == pytest.approx((0, 0, 2, 2), abs=1e-10)


@pytest.mark.parametrize("reference", ["clip", "use"])
def test_short_arc_in_referenced_geometry_keeps_paint_and_square(
    tmp_path: Path, reference: str,
) -> None:
    short_path = 'd="M10 10A1e13 1e13 0 0 0 12 10L12 12L10 12Z"'
    if reference == "clip":
        artwork = (
            f'<defs><clipPath id="clip"><path {short_path}/></clipPath></defs>'
            '<rect width="30" height="30" fill="red" clip-path="url(#clip)"/>'
        )
    else:
        artwork = (
            f'<defs><path id="arc" {short_path}/></defs>'
            '<use href="#arc" fill="red"/>'
        )
    source = tmp_path / f"short-arc-{reference}.svg"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">'
        f'{artwork}<rect x="20" y="20" width="4" height="4" fill="blue"/></svg>',
        encoding="utf-8",
    )
    processor = object.__new__(VectorProcessor)
    processor.sampling_precision = 0.02
    processor._parse_expand_stroke_to_fill = False
    shapes, scale, bounds = processor._parse_svg(str(source), 40.0)
    by_color = {shape["color"]: shape["poly"] for shape in shapes}
    assert scale == pytest.approx(1.0)
    assert bounds == pytest.approx((0, 0, 40, 40))
    assert set(by_color) == {(255, 0, 0), (0, 0, 255)}
    assert by_color[(255, 0, 0)].symmetric_difference(box(10, 10, 12, 12)).area < 1e-6
    assert by_color[(0, 0, 255)].equals(box(20, 20, 24, 24))


def test_unrepresentable_major_arc_reports_precision_failure() -> None:
    with pytest.raises(ValueError, match="requires too many segments"):
        parse_svg_path("M-1 0 A1e100 1e100 0 1 1 1 0", 0.0001)


@pytest.mark.parametrize("data", [
    "M0 0 A10 10 0 0 1 10 10",
    "M0 0 A1 1 0 0 1 10 10",  # mandatory radii correction
    "M0 0 A0 10 0 0 1 10 10",
    "M0 0 A10 0 0 0 1 10 10",
    "M0 0 A10 10 0 1 1 0 0",
    "M0 0 A-10 -10 0 0 1 10 10",
])
def test_well_conditioned_and_degenerate_arc_semantics_are_preserved(data: str) -> None:
    expected = SvgPath(data)
    actual = parse_svg_path(data, 0.0001)
    assert list(actual) == list(expected)
    assert isinstance(actual[-1], Arc)


def test_deferred_reify_preserves_definition_and_visible_shape_geometry() -> None:
    source = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">'
        '<defs><path id="shape" transform="translate(3 4)" '
        'd="M1 1H4V5H1Z"/></defs>'
        '<use href="#shape" x="2" transform="scale(2 3)"/>'
        '<g transform="rotate(20)"><ellipse id="ellipse" cx="4" cy="4" '
        'rx="2" ry="1" stroke="red" stroke-width="2"/></g></svg>'
    )
    expected = SVG.parse(io.StringIO(source))
    actual = parse_svg_document(io.StringIO(source), 0.0001)
    for identifier in ["shape", "ellipse"]:
        assert actual.objects[identifier].bbox() == pytest.approx(expected.objects[identifier].bbox())
        assert actual.objects[identifier].transform == expected.objects[identifier].transform
    expected_shapes = [element for element in expected.elements() if isinstance(element, (Shape, Image, Text))]
    actual_shapes = [element for element in actual.elements() if isinstance(element, (Shape, Image, Text))]
    assert [element.bbox() for element in actual_shapes] == [element.bbox() for element in expected_shapes]
