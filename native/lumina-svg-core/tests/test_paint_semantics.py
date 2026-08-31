"""Stroke, clip, source-order occlusion, and silhouette semantics."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Polygon, box

import lumina_svg_core


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def geometry_rings(result, collection, geometry_index: int):
    polygon_start = collection.geometry_offsets[geometry_index]
    polygon_end = collection.geometry_offsets[geometry_index + 1]
    for polygon_index in range(polygon_start, polygon_end):
        ring_start = collection.polygon_offsets[polygon_index]
        ring_end = collection.polygon_offsets[polygon_index + 1]
        for ring_index in range(ring_start, ring_end):
            point_start = collection.ring_offsets[ring_index]
            point_end = collection.ring_offsets[ring_index + 1]
            yield (
                collection.coordinates[point_start:point_end].astype(np.float64)
                * result.grid_to_source_unit
            )


def geometry_area(result, collection, geometry_index: int) -> float:
    area = 0.0
    for ring in geometry_rings(result, collection, geometry_index):
        signed = 0.5 * np.sum(
            ring[:-1, 0] * ring[1:, 1]
            - ring[1:, 0] * ring[:-1, 1]
        )
        area += signed
    return abs(area)


def geometry_bounds(result, collection, geometry_index: int):
    points = np.concatenate(
        list(geometry_rings(result, collection, geometry_index)), axis=0
    )
    return (
        points[:, 0].min(),
        points[:, 1].min(),
        points[:, 0].max(),
        points[:, 1].max(),
    )


def geometry_shape(result, collection, geometry_index: int):
    geometries = shapely.from_ragged_array(
        shapely.GeometryType.MULTIPOLYGON,
        collection.coordinates.astype(np.float64)
        * result.grid_to_source_unit,
        (
            collection.ring_offsets,
            collection.polygon_offsets,
            collection.geometry_offsets,
        ),
    )
    return geometries[geometry_index]


def _cubic_point(
    start: np.ndarray,
    control1: np.ndarray,
    control2: np.ndarray,
    end: np.ndarray,
    parameter: np.ndarray,
) -> np.ndarray:
    complement = 1.0 - parameter
    return (
        complement**3 * start
        + 3.0 * complement**2 * parameter * control1
        + 3.0 * complement * parameter**2 * control2
        + parameter**3 * end
    )


def test_stroke_expands_before_full_affine_transform() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "stroke_only_affine.svg", 60.0, 0.02
    )

    assert result.status == "supported"
    assert result.bbox == pytest.approx((0.0, 0.0, 100.0, 60.0), abs=0.01)
    assert result.raw.source_kinds.tolist() == [1]
    assert geometry_bounds(result, result.raw, 0) == pytest.approx(
        (20.0, 35.0, 80.0, 45.0), abs=0.03
    )


def test_clip_and_later_paint_define_visible_geometry() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "strokes_clips_occlusion.svg", 100.0, 0.02
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 4
    assert result.visible.geometry_count == 4
    assert result.raw.rgba.tolist() == [
        [239, 83, 80, 255],
        [30, 136, 229, 255],
        [67, 160, 71, 255],
        [142, 36, 170, 255],
    ]
    assert geometry_area(result, result.raw, 1) == pytest.approx(900.0, abs=0.1)
    assert geometry_area(result, result.visible, 1) == pytest.approx(550.0, abs=0.1)
    assert geometry_bounds(result, result.raw, 3) == pytest.approx(
        (20.0, 35.0, 80.0, 45.0), abs=0.03
    )
    assert result.silhouette.component_count == 1
    assert result.silhouette.hole_count == 0


def test_dash_array_is_applied_in_local_arclength() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "dashed_stroke.svg", 40.0, 0.02
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1
    assert result.raw.component_count == 2
    assert geometry_area(result, result.raw, 0) == pytest.approx(80.0, abs=0.1)


@pytest.mark.parametrize("unit_scale", [1e-17, 1.0, 1e17])
def test_dashed_stroke_is_invariant_across_user_unit_scales(
    unit_scale: float,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        f"<svg viewBox='0 0 {unit_scale:g} {unit_scale:g}'>"
        f"<path d='M0 {0.5 * unit_scale:g}H{unit_scale:g}' fill='none' "
        f"stroke='#000' stroke-width='{0.1 * unit_scale:g}' "
        f"stroke-linecap='butt' stroke-dasharray="
        f"'{0.2 * unit_scale:g} {0.2 * unit_scale:g}'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 3
    physical_area = (
        geometry_area(result, result.raw, 0) * result.scale_factor**2
    )
    assert physical_area == pytest.approx(600.0, abs=0.2)


@pytest.mark.parametrize("unit_scale", [1.0, 1e-2, 1e-4, 1e-6, 1e-17])
def test_round_stroke_bbox_contains_geometry_at_any_user_unit_scale(
    unit_scale: float,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg>"
        f"<path d='M0 0L{unit_scale:g} 0' fill='none' stroke='red' "
        f"stroke-width='{0.2 * unit_scale:g}' stroke-linecap='round'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    min_x, min_y, max_x, max_y = geometry_bounds(result, result.raw, 0)
    source_budget = 0.02 / result.scale_factor
    assert min_x >= -source_budget
    assert min_y >= -source_budget
    assert max_x <= result.bbox[2] + source_budget
    assert max_y <= result.bbox[3] + source_budget
    assert (max_x - min_x) * result.scale_factor == pytest.approx(
        100.0, abs=0.02
    )


def test_microscopic_dash_period_fails_closed_without_expanding_billions() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 10'>"
        "<path d='M0 5H100' fill='none' stroke='red' stroke-width='1' "
        "stroke-dasharray='0.00000001 0.00000001'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_complexity"
    assert result.raw.geometry_count == 0


def test_closed_stroke_remains_a_band_with_an_independent_hole() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 40 40'>"
        "<path d='M10 10H30V30H10Z' fill='none' stroke='#000' "
        "stroke-width='4' stroke-linejoin='miter'/>"
        "</svg>",
        target_width_mm=24.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.bbox == pytest.approx((0.0, 0.0, 40.0, 40.0), abs=0.01)
    assert result.raw.component_count == 1
    assert result.raw.hole_count == 1
    assert geometry_area(result, result.raw, 0) == pytest.approx(320.0, abs=0.3)


@pytest.mark.parametrize(
    ("linecap", "expected_area"),
    [("round", np.pi), ("square", 4.0)],
)
def test_zero_length_solid_stroke_preserves_visible_cap(
    linecap: str,
    expected_area: float,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<path d='M5 5L5 5' fill='none' stroke='#000' "
        f"stroke-width='2' stroke-linecap='{linecap}'/>"
        "</svg>",
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 1
    assert geometry_bounds(result, result.raw, 0) == pytest.approx(
        (4.0, 4.0, 6.0, 6.0), abs=0.03
    )
    assert geometry_area(result, result.raw, 0) == pytest.approx(
        expected_area, abs=0.08
    )


@pytest.mark.parametrize("linecap", ["butt", "round", "square"])
def test_single_moveto_does_not_create_a_stroke_cap(linecap: str) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<path d='M5 5' fill='none' stroke='#000' stroke-width='2' "
        f"stroke-linecap='{linecap}'/>"
        "<rect width='1' height='1' fill='red'/></svg>",
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 1
    assert tuple(result.raw.source_kinds) == (0,)
    assert tuple(result.raw.rgba[0]) == (255, 0, 0, 255)


@pytest.mark.parametrize(
    "path_data",
    ["M5 5L5 5", "M5 5Z", "M5 5C5 5 5 5 5 5"],
    ids=["line", "close", "cubic"],
)
def test_zero_length_draw_verbs_keep_their_round_cap(
    path_data: str,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<path d='{path_data}' fill='none' stroke='#000' "
        "stroke-width='2' stroke-linecap='round'/></svg>",
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 1
    assert geometry_area(result, result.raw, 0) == pytest.approx(
        np.pi, abs=0.08
    )


@pytest.mark.parametrize(
    "path_data",
    ["M5 5L5 5", "M5 5Z"],
    ids=["line", "close"],
)
@pytest.mark.parametrize(
    ("linecap", "dash_offset", "expected_area"),
    [
        ("round", 0, np.pi),
        ("square", 0, 4.0),
        ("butt", 0, 0.0),
        ("round", 5, np.pi),
        ("square", 5, 4.0),
        ("butt", 5, 0.0),
        ("round", -5, np.pi),
        ("square", 15, 4.0),
        ("round", 4.999, np.pi),
        ("round", 5.001, 0.0),
    ],
    ids=[
        "round-painted",
        "square-painted",
        "butt-painted",
        "round-painted-endpoint",
        "square-painted-endpoint",
        "butt-painted-endpoint",
        "round-negative-painted-endpoint",
        "square-wrapped-painted-endpoint",
        "round-before-painted-endpoint",
        "round-after-painted-endpoint",
    ],
)
def test_zero_length_dashed_subpath_respects_dash_phase_and_cap(
    path_data: str,
    linecap: str,
    dash_offset: float,
    expected_area: float,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<path d='{path_data}' fill='none' stroke='#000' "
        f"stroke-width='2' stroke-linecap='{linecap}' "
        f"stroke-dasharray='5 5' stroke-dashoffset='{dash_offset}'/>"
        "<rect width='1' height='1' fill='red'/></svg>",
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert tuple(result.raw.source_kinds) == (1, 0)
    assert geometry_area(result, result.raw, 0) == pytest.approx(
        expected_area, abs=0.08
    )
    assert result.raw.component_count == (2 if expected_area else 1)


@pytest.mark.parametrize("linecap", ["round", "square"])
@pytest.mark.parametrize("dash_offset", [-5, 5, 15])
def test_nonzero_dash_keeps_cap_at_exact_painted_interval_endpoint(
    linecap: str,
    dash_offset: int,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 30 10'>"
        "<path d='M5 5H25' fill='none' stroke='#000' stroke-width='2' "
        f"stroke-linecap='{linecap}' stroke-dasharray='5 5' "
        f"stroke-dashoffset='{dash_offset}'/></svg>",
        target_width_mm=30.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert geometry_bounds(result, result.raw, 0)[0] == pytest.approx(
        4.0, abs=0.03
    )


def test_pure_moveto_is_dropped_without_hiding_a_later_zero_length_line() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path d='M1 1 M5 5L5 5' fill='none' stroke='#000' "
        "stroke-width='2' stroke-linecap='round'/></svg>",
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 1
    assert geometry_bounds(result, result.raw, 0) == pytest.approx(
        (4.0, 4.0, 6.0, 6.0), abs=0.03
    )


@pytest.mark.parametrize("unit_scale", [1e-17, 1.0, 1e17])
def test_closed_dash_caps_are_invariant_across_user_unit_scales(
    unit_scale: float,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        f"<svg viewBox='0 0 {14 * unit_scale:g} {14 * unit_scale:g}'>"
        f"<path d='M{2 * unit_scale:g} {2 * unit_scale:g}"
        f"H{12 * unit_scale:g}V{12 * unit_scale:g}"
        f"H{2 * unit_scale:g}Z' "
        "fill='none' stroke='#000' "
        f"stroke-width='{2 * unit_scale:g}' stroke-linecap='butt' "
        "stroke-linejoin='miter' "
        f"stroke-dasharray='{10 * unit_scale:g} {10 * unit_scale:g}' "
        f"stroke-dashoffset='{5 * unit_scale:g}'/>"
        "</svg>",
        target_width_mm=14.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 2
    physical_area = (
        geometry_area(result, result.raw, 0) * result.scale_factor**2
    )
    # Two butt-capped dash pairs meet without replacing their caps by a join.
    # The zero-origin root viewport is 14 mm wide after public normalization.
    assert physical_area == pytest.approx(39.0, abs=0.1)


@pytest.mark.parametrize("linecap", ["butt", "round", "square"])
@pytest.mark.parametrize(
    ("dash_array", "dash_offset"),
    [("50 10", 0), ("40 10", 0), ("10 10", 5)],
    ids=["covers-perimeter", "equals-perimeter", "two-pairs-across-seam"],
)
def test_closed_dashed_path_keeps_caps_at_seam_like_equivalent_open_path(
    linecap: str,
    dash_array: str,
    dash_offset: int,
) -> None:
    common_style = (
        "fill='none' stroke='#000' stroke-width='2' "
        f"stroke-linecap='{linecap}' stroke-linejoin='bevel' "
        f"stroke-dasharray='{dash_array}' stroke-dashoffset='{dash_offset}'"
    )
    closed = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 20'>"
        f"<path d='M5 5H15V15H5Z' {common_style}/></svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )
    equivalent_open = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 20'>"
        f"<path d='M5 5H15V15H5L5 5' {common_style}/></svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert closed.status == equivalent_open.status == "supported"
    closed_geometry = geometry_shape(closed, closed.raw, 0)
    open_geometry = geometry_shape(equivalent_open, equivalent_open.raw, 0)
    assert closed_geometry.symmetric_difference(open_geometry).area < 0.02


def test_zero_length_dash_entry_fails_closed_before_expansion() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 10'>"
        "<path d='M0 5H20' fill='none' stroke='#000' stroke-width='2' "
        "stroke-linecap='round' stroke-dasharray='0 5' "
        "stroke-dashoffset='2'/>"
        "</svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_zero_length_dash"
    assert result.raw.geometry_count == 0


def test_dash_offset_float_rounding_exceeding_error_budget_fails_closed() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 10'>"
        "<path d='M0 5H100' fill='none' stroke='#000' stroke-width='2' "
        "stroke-dasharray='3 3' stroke-dashoffset='16777217'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_input_precision"
    assert result.raw.geometry_count == 0


def test_dash_pattern_rounding_accumulated_by_large_offset_fails_closed() -> None:
    dash_array = " ".join(["0.100000001"] * 32)
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 10'>"
        "<path d='M0 5H100' fill='none' stroke='#000' stroke-width='2' "
        f"stroke-dasharray='{dash_array}' stroke-dashoffset='10000000'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_input_precision"
    assert result.raw.geometry_count == 0


@pytest.mark.parametrize("limit_delta", [-0.05, 0.05])
def test_svg_miter_limit_uses_bevel_fallback_below_threshold(
    limit_delta: float,
) -> None:
    points = [(10.0, 10.0), (20.0, 10.0), (10.603, 13.42)]
    incoming_outgoing_cosine = -9.397 / np.hypot(9.397, 3.42)
    miter_ratio = np.sqrt(2.0 / (incoming_outgoing_cosine + 1.0))
    miter_limit = miter_ratio + limit_delta
    expected_join = "bevel" if limit_delta < 0 else "mitre"
    expected = LineString(points).buffer(
        1.0,
        cap_style="flat",
        join_style=expected_join,
        mitre_limit=miter_limit,
    )
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 40 25'>"
        "<path d='M10 10L20 10L10.603 13.42' fill='none' stroke='#000' "
        "stroke-width='2' stroke-linecap='butt' stroke-linejoin='miter' "
        f"stroke-miterlimit='{miter_limit:.9f}'/></svg>",
        target_width_mm=40.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert geometry_area(result, result.raw, 0) == pytest.approx(
        expected.area, abs=0.08
    )
    assert geometry_bounds(result, result.raw, 0)[2] == pytest.approx(
        expected.bounds[2], abs=0.03
    )


def test_closed_miter_limit_uses_bevel_instead_of_square_fallback() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 30 20'>"
        "<path d='M10 10L20 10L10.603 13.42Z' fill='none' stroke='#000' "
        "stroke-width='2' stroke-linejoin='miter' stroke-miterlimit='4'/>"
        "</svg>",
        target_width_mm=30.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert geometry_bounds(result, result.raw, 0)[2] == pytest.approx(
        20.342, abs=0.03
    )


def test_miter_bevel_fallback_is_expanded_before_affine_transform() -> None:
    local_bevel = LineString(
        [(0.0, 0.0), (10.0, 0.0), (0.603, 3.42)]
    ).buffer(1.0, cap_style="flat", join_style="bevel")
    affine_determinant = abs(1.2 * 0.8 - 0.4 * 0.3)
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 60 50'>"
        "<path d='M0 0L10 0L0.603 3.42' fill='none' stroke='#000' "
        "stroke-width='2' stroke-linecap='butt' stroke-linejoin='miter' "
        "stroke-miterlimit='4' transform='matrix(1.2 0.3 0.4 0.8 20 20)'/>"
        "</svg>",
        target_width_mm=60.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert geometry_area(result, result.raw, 0) == pytest.approx(
        local_bevel.area * affine_determinant, abs=0.1
    )


def test_miter_limit_rounding_at_join_threshold_fails_closed() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 14 8'>"
        "<path d='M2 2L10 2L3 5.872983346207417' fill='none' "
        "stroke='#000' "
        "stroke-width='2' stroke-linejoin='miter' stroke-miterlimit='4'/>"
        "</svg>",
        target_width_mm=14.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_input_precision"
    assert result.raw.geometry_count == 0


def test_dashed_cubic_uses_total_arclength_error_budget() -> None:
    cubic_commands = " ".join(
        f"C{index + 0.25} 2 {index + 0.75} 0 {index + 1} 1"
        for index in range(5)
    )
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 5 2'>"
        f"<path d='M0 1 {cubic_commands}' fill='none' stroke='#000' "
        "stroke-width='.2' stroke-linecap='butt' "
        "stroke-dasharray='7 1000'/></svg>",
        target_width_mm=5.0,
        tolerance_mm=0.02,
    )

    if result.status == "unsupported":
        assert result.reason_code in {
            "unsupported_complexity",
            "unsupported_input_precision",
            "unsupported_topology_collapse",
        }
        assert result.raw.geometry_count == 0
        return
    assert result.status == "supported", result.reason_code
    samples: list[np.ndarray] = [np.array([0.0, 1.0])]
    start = samples[0]
    parameters = np.linspace(0.0, 1.0, 4001)[1:, None]
    for index in range(5):
        control1 = np.array([index + 0.25, 2.0])
        control2 = np.array([index + 0.75, 0.0])
        end = np.array([index + 1.0, 1.0])
        samples.extend(
            _cubic_point(
                start, control1, control2, end, parameters
            )
        )
        start = end
    centerline = np.asarray(samples)
    segment_lengths = np.linalg.norm(
        np.diff(centerline, axis=0), axis=1
    )
    cumulative = np.concatenate(([0.0], np.cumsum(segment_lengths)))
    endpoint_index = int(np.searchsorted(cumulative, 7.0))
    endpoint_fraction = (
        (7.0 - cumulative[endpoint_index - 1])
        / (cumulative[endpoint_index] - cumulative[endpoint_index - 1])
    )
    endpoint = centerline[endpoint_index - 1] + endpoint_fraction * (
        centerline[endpoint_index] - centerline[endpoint_index - 1]
    )
    reference_centerline = np.vstack(
        (centerline[:endpoint_index], endpoint)
    )
    reference = LineString(reference_centerline).buffer(
        0.1,
        cap_style="flat",
        join_style="round",
        quad_segs=16,
    )
    actual = geometry_shape(result, result.raw, 0)
    physical_boundary_error = (
        actual.boundary.hausdorff_distance(reference.boundary)
        * result.scale_factor
    )

    assert physical_boundary_error <= 0.02


def test_nested_svg_coordinate_semantics_fail_closed_to_legacy() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 40 20'>"
        "<svg x='10' y='5' width='10' height='10' viewBox='0 0 10 10'>"
        "<path d='M-10 0H20V10H-10Z' fill='#f00'/>"
        "</svg></svg>",
        target_width_mm=40.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_nested_svg"
    assert result.raw.geometry_count == 0


def test_explicit_root_overflow_hidden_falls_back_to_legacy() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10' overflow='hidden'>"
        "<path d='M-10 0H20V10H-10Z' fill='#f00'/>"
        "</svg>",
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_root_overflow"
    assert result.raw.geometry_count == 0


@pytest.mark.parametrize("outlier", [1_000.0, 1_000_000_000.0])
def test_clip_outlier_does_not_expand_bbox_or_change_physical_scale(
    outlier: float,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<defs><clipPath id='small'>"
        "<rect x='0' y='0' width='10' height='10'/>"
        "</clipPath></defs>"
        f"<rect x='-{outlier:g}' y='0' width='{2 * outlier:g}' height='10' "
        "clip-path='url(#small)' fill='#f00'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.bbox == pytest.approx((0.0, 0.0, 100.0, 100.0), abs=0.001)
    assert result.scale_factor == pytest.approx(1.0, abs=0.00001)
    assert geometry_bounds(result, result.raw, 0) == pytest.approx(
        (0.0, 0.0, 10.0, 10.0), abs=0.02
    )


def test_clip_bounds_prepass_respects_end_to_end_boundary_budget() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg xmlns='http://www.w3.org/2000/svg'>"
        "<defs><clipPath id='small'>"
        "<rect x='0' y='0' width='10' height='10'/>"
        "</clipPath></defs>"
        "<rect x='-1000000000' y='0' width='2000000000' height='10' "
        "clip-path='url(#small)' fill='#f00'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.bbox == pytest.approx((0.0, 0.0, 10.0, 10.0), abs=0.001)
    ring = next(geometry_rings(result, result.raw, 0))
    physical = Polygon(ring * result.scale_factor)
    expected = box(0.0, 0.0, 100.0, 100.0)
    assert physical.boundary.hausdorff_distance(expected.boundary) <= 0.02


def test_stroke_policy_can_fail_before_geometry_kernel_expansion() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 40 20'>"
        "<path d='M0 10H40' fill='none' stroke='#000' stroke-width='4'/>"
        "</svg>",
        target_width_mm=40.0,
        tolerance_mm=0.02,
        allow_strokes=False,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_stroke_policy"
    assert result.raw.geometry_count == 0
    assert result.visible.geometry_count == 0
    assert result.silhouette.geometry_count == 0
