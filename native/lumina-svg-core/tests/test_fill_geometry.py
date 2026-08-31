"""Physical error allocation and fill topology tests."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

import numpy as np
import pytest

import lumina_svg_core


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _normalized_coordinate_bounds(result):
    coordinates = (
        np.asarray(result.raw.coordinates, dtype=np.float64)
        * result.grid_to_source_unit
    )
    return (
        float(coordinates[:, 0].min()),
        float(coordinates[:, 1].min()),
        float(coordinates[:, 0].max()),
        float(coordinates[:, 1].max()),
    )


def test_document_viewport_remains_part_of_lumina_bbox_contract() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "basic_fill_stroke.svg", 20.0, 0.02
    )

    assert result.status == "supported"
    assert result.bbox == pytest.approx((0.0, 0.0, 20.0, 10.0), abs=1e-6)
    assert result.scale_factor == pytest.approx(1.0)


def test_legacy_contour_normalization_identity_is_explicit() -> None:
    rectangle = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path fill='red' d='M10 10H90V90H10Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
        legacy_close_delta_source_units=0.03,
    )
    narrow_hole = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path fill='red' fill-rule='evenodd' "
        "d='M10 10H90V90H10Z M49.98 20H50.02V80H49.98Z'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
        legacy_close_delta_source_units=0.03,
    )
    narrow_notch = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path fill='red' "
        "d='M10 10H90V90H50.02V20H49.98V90H10Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
        legacy_close_delta_source_units=0.03,
    )

    assert rectangle.status == "supported"
    assert rectangle.legacy_contour_normalization_identity is True
    assert rectangle.legacy_contour_normalization_compatible is True
    assert narrow_hole.status == "supported"
    assert narrow_hole.legacy_contour_normalization_identity is False
    assert narrow_hole.legacy_contour_normalization_compatible is True
    assert narrow_hole.raw.hole_count == 0
    assert narrow_notch.status == "supported"
    assert narrow_notch.legacy_contour_normalization_identity is False
    assert narrow_notch.legacy_contour_normalization_compatible is True
    assert narrow_notch.raw.hole_count == 0


def test_legacy_close_keeps_miter_limit_boundary_shapes_on_offset_path() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path d='M0 0L10 0L5 8.660254Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
        legacy_close_delta_source_units=0.03,
    )

    assert result.status == "supported"
    assert result.legacy_contour_normalization_identity is False


def test_spacious_concave_ring_has_provable_miter_round_trip() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path d='M0 0H100V100H60V60H40V100H0Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
        legacy_close_delta_source_units=0.03,
    )

    assert result.status == "supported"
    assert result.legacy_contour_normalization_identity is True


def test_slanted_micro_notch_is_not_claimed_as_identity() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'><path fill='red' d='"
        "M10 10 L90 10 L90 90 L39.83308898930126 90 "
        "L39.79082728731835 82.16007974157606 "
        "L39.69503373258287 90 L10 90 Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
        legacy_close_delta_source_units=0.03,
    )

    assert result.status == "supported"
    assert result.legacy_contour_normalization_identity is False


def test_legacy_contour_normalization_marks_unsafe_multi_component_shape() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'><path fill='red' d='"
        "M55.52831753041504 66.3046688201546 "
        "L55.52831753041504 72.93040052353409 "
        "L47.339743941791944 73.63466187069454 "
        "L53.28877361479757 75.44200987424085 "
        "L53.2656320529904 75.07386941278561 "
        "L73.09976273935555 73.8270823593993 "
        "L73.43087174116687 79.09442869213571 "
        "L75.37109811756244 74.24712851807058 Z "
        "M33.18047101838028 57.359507658012994 "
        "L28.90746374836685 68.03483355590957 "
        "L44.810623640889176 72.86630118368933 "
        "L44.810623640889176 62.01470293567081 Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
        legacy_close_delta_source_units=0.03,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 2
    assert result.legacy_contour_normalization_identity is False
    assert result.legacy_contour_normalization_compatible is False


def test_legacy_close_allows_proven_small_triangular_island_shape() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'><path fill='red' d='"
        "M0 0H50V50H25V10H24.96V50H0Z "
        "M70 70L72 70L71 72Z'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
        legacy_close_delta_source_units=0.03,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 2
    assert result.legacy_contour_normalization_identity is False
    assert result.legacy_contour_normalization_compatible is True


def test_optional_legacy_area_filter_drops_only_subthreshold_paint() -> None:
    svg = (
        "<svg viewBox='0 0 100 100'>"
        "<rect width='50' height='50' fill='red'/>"
        "<rect x='90' y='90' width='.005' height='.005' fill='blue'/>"
        "</svg>"
    )
    standalone = lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )
    compatible = lumina_svg_core.analyze_svg_svg(
        svg,
        target_width_mm=100.0,
        tolerance_mm=0.02,
        legacy_close_delta_source_units=0.03,
        legacy_minimum_paint_area_factor=0.25,
    )

    assert standalone.status == compatible.status == "supported"
    assert standalone.raw.geometry_count == 2
    assert compatible.raw.geometry_count == 1
    assert compatible.legacy_area_filter_identity is False
    assert tuple(compatible.raw.rgba[0]) == (255, 0, 0, 255)


@pytest.mark.parametrize("width", ["0.099999", "0.100001"])
def test_component_area_threshold_uncertainty_is_unsupported(
    width: str,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<rect width='50' height='50' fill='red'/>"
        f"<rect x='90' y='90' width='{width}' height='{width}' "
        "fill='blue'/></svg>",
        target_width_mm=111.0,
        tolerance_mm=0.02,
        legacy_close_delta_source_units=0.03,
        legacy_minimum_paint_area_factor=0.25,
        legacy_component_area_source_units_squared=0.01,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "legacy_area_threshold_ambiguous"
    assert result.raw.geometry_count == 0
    assert result.visible.geometry_count == 0
    assert result.silhouette.geometry_count == 0


def test_legacy_area_filter_preserves_scale_clamp_for_macro_viewbox() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1000000000 1000000000'>"
        "<rect width='500000000' height='500000000' fill='red'/>"
        "<rect x='900000000' y='900000000' width='100000' "
        "height='50000' fill='blue'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
        legacy_close_delta_source_units=0.03,
        legacy_minimum_paint_area_factor=0.25,
    )

    assert result.status == "supported"
    assert result.scale_factor == pytest.approx(1.0e-7)
    assert result.raw.geometry_count == 2
    assert result.legacy_area_filter_identity is True
    assert tuple(result.raw.rgba[1]) == (0, 0, 255, 255)


@pytest.mark.parametrize("width", ["9980", "10020"])
def test_dynamic_area_threshold_uncertainty_is_unsupported(
    width: str,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1000000000 1000000000'>"
        "<rect width='500000000' height='500000000' fill='red'/>"
        f"<rect x='900000000' y='900000000' width='{width}' "
        f"height='{width}' fill='blue'/></svg>",
        target_width_mm=111.0,
        tolerance_mm=0.02,
        legacy_close_delta_source_units=0.03,
        legacy_minimum_paint_area_factor=0.25,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "legacy_area_threshold_ambiguous"


@pytest.mark.parametrize(
    "degenerate_prefix",
    [
        "M1000000 1000000 ",
        "M1000000 1000000L2000000 2000000 ",
        "M1000000 1000000H2000000Z ",
    ],
)
def test_non_painting_subpaths_do_not_expand_bbox_or_reduce_scale(
    degenerate_prefix: str,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg xmlns='http://www.w3.org/2000/svg'>"
        f"<path d='{degenerate_prefix}M0 0H10V10H0Z'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.bbox == pytest.approx((0.0, 0.0, 10.0, 10.0), abs=1e-6)
    assert result.scale_factor == pytest.approx(10.0)
    assert result.raw.component_count == 1


def test_non_uniform_transform_uses_one_model_space_error_budget() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "fill_rules_transforms.svg",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.max_flattening_error_mm == pytest.approx(0.008)
    assert 0 < result.max_quantization_error_mm <= 0.004
    assert result.max_flattening_error_mm + result.max_quantization_error_mm < 0.02
    assert result.scale_factor == pytest.approx(100.0 / result.bbox[2])
    assert result.grid_to_source_unit > 0


@pytest.mark.parametrize(
    "transform",
    [
        "translate(100000000 0) translate(1 0) translate(-100000000 0)",
        "translate(100000000 0) translate(-99999999 0)",
    ],
)
def test_transform_cancellation_fails_closed_before_geometry_replay(
    transform: str,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        f"<path transform='{transform}' d='M0 0H1V1H0Z' fill='red'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_input_precision"
    assert result.raw.geometry_count == 0


def test_relative_path_cancellation_fails_closed_before_geometry_replay() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path d='m100000000 0 m1 0 m-100000000 0 "
        "h1 v1 h-1 z' fill='red'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_input_precision"
    assert result.raw.geometry_count == 0


def test_composed_transform_overflow_fails_closed_without_dropping_paint() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10' overflow='visible'>"
        "<rect width='1' height='1' fill='red' "
        "transform='scale(1e20) scale(1e20)'/>"
        "<rect x='5' width='1' height='1' fill='blue'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_input_precision"
    assert result.raw.geometry_count == 0


def test_percentage_stroke_overflow_fails_closed_without_dropping_stroke() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1e20 1e20'>"
        "<rect width='1e20' height='1e20' fill='red'/>"
        "<path d='M0 5e19H1e20' fill='none' stroke='blue' "
        "stroke-width='1%'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_input_precision"
    assert result.raw.geometry_count == 0


def test_extreme_cubic_precision_is_rejected_before_expensive_flattening() -> None:
    started = perf_counter()
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1 20000000000'>"
        "<path d='M0 0C0 20000000000 1 -20000000000 1 0 "
        "L1 20000000000H0Z' fill='red'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )
    elapsed = perf_counter() - started

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_input_precision"
    assert result.raw.geometry_count == 0
    assert elapsed < 0.5


@pytest.mark.parametrize("unit_scale", [1e-17, 1.0, 1e17])
def test_cubic_extrema_bbox_is_invariant_across_user_unit_scales(
    unit_scale: float,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        f"<svg viewBox='0 0 {unit_scale:g} {unit_scale:g}' "
        "overflow='visible'>"
        f"<path d='M0 0 C {unit_scale:g} 0 {-unit_scale:g} "
        f"{unit_scale:g} 0 {unit_scale:g} L {unit_scale:g} "
        f"{unit_scale:g} L {unit_scale:g} 0 Z' fill='red'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    extrema = np.sqrt(3.0) / 6.0
    expected_min_x = -extrema * unit_scale
    expected_width = (1.0 + extrema) * unit_scale
    assert result.status == "supported"
    source_abs_tolerance = abs(unit_scale) * 1e-8
    assert result.bbox[0] == pytest.approx(
        expected_min_x, rel=2e-6, abs=source_abs_tolerance
    )
    assert result.bbox[2] == pytest.approx(
        expected_width, rel=2e-6, abs=source_abs_tolerance
    )
    assert result.scale_factor == pytest.approx(
        100.0 / expected_width, rel=2e-6
    )

    physical_x = (
        np.asarray(result.raw.coordinates, dtype=np.float64)[:, 0]
        * result.grid_to_source_unit
        * result.scale_factor
    )
    assert physical_x.min() >= -0.02
    assert physical_x.max() <= 100.02
    assert physical_x.max() - physical_x.min() == pytest.approx(
        100.0, abs=0.02
    )


def test_evenodd_hole_and_disconnected_shell_survive() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "fill_rules_transforms.svg",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    visible = result.visible
    assert visible.geometry_count == 1
    assert visible.component_count == 2
    assert visible.hole_count == 1
    assert np.count_nonzero(visible.hole_parent == -1) == 2
    assert np.count_nonzero(visible.hole_parent >= 0) == 1
    assert visible.polygon_offsets.tolist() == [0, 2, 3]


@pytest.mark.parametrize("hole_width", [0.0001, 0.0002, 0.0003])
def test_precision_grid_preserves_a_small_hole(
    hole_width: float,
) -> None:
    half_width = hole_width / 2.0
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path fill-rule='evenodd' "
        f"d='M0 0H10V10H0Z M{5 - half_width:.8f} 4"
        f"H{5 + half_width:.8f}V6H{5 - half_width:.8f}Z'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.hole_count == 1
    assert result.visible.hole_count == 1


def test_precision_grid_preserves_a_thin_material_region() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10' fill='#f00'/>"
        "<rect y='5' width='10' height='0.0001' fill='#00f'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 2
    assert result.visible.component_count == 3


def test_precision_grid_preserves_a_narrow_gap_between_paints() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='4.99995' height='10' fill='#f00'/>"
        "<rect x='5.00005' width='4.99995' height='10' fill='#f00'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.silhouette.component_count == 2


def test_precision_grid_preserves_a_narrow_gap_within_one_paint() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path fill='#f00' d='M0 0H4.9999V10H0Z "
        "M5.0001 0H10V10H5.0001Z'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 2
    assert result.silhouette.component_count == 2


def test_precision_grid_preserves_a_visible_sliver_after_occlusion() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='10' height='10' fill='#f00'/>"
        "<rect x='0.0001' width='9.9999' height='10' fill='#00f'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 2
    assert result.visible.component_count == 2


def test_float_recorder_collapse_fails_closed_before_material_loss() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100000000 10'>"
        "<rect width='100000000' height='10' fill='#f00'/>"
        "<rect x='99999990' width='1' height='10' fill='#00f'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_input_precision"
    assert result.raw.geometry_count == 0


def test_exact_line_gap_in_curved_contours_does_not_spend_curve_budget() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 10'>"
        "<path d='M0 0H9.997V10H0C0 7 0 3 0 0Z' fill='#f00'/>"
        "<path d='M10.003 0H20V10C16 10 14 10 10.003 10Z' fill='#00f'/>"
        "</svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"


def test_sub_tolerance_curve_gap_is_preserved_on_the_integer_grid() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 10'>"
        "<path d='M0 0H9.992C10 3 10 7 9.992 10H0Z' fill='#f00'/>"
        "<path d='M10.008 0C10 3 10 7 10.008 10H20V0Z' fill='#00f'/>"
        "</svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 2


@pytest.mark.parametrize("viewbox_size", [1.0, 0.001])
def test_small_user_unit_cubic_falls_back_for_legacy_tolerance_parity(
    viewbox_size: float,
) -> None:
    result = lumina_svg_core.analyze_svg_svg(
        f"<svg viewBox='0 0 {viewbox_size:g} {viewbox_size:g}'>"
        f"<path d='M0 {viewbox_size:g} C0 0 {viewbox_size / 4:g} 0 "
        f"{viewbox_size / 2:g} 0 C{viewbox_size * 3 / 4:g} 0 "
        f"{viewbox_size:g} 0 {viewbox_size:g} {viewbox_size:g}Z' "
        "fill='red'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.legacy_curve_tolerance_compatible is False
    assert result.raw.geometry_count == 1


def test_robust_non_adjacent_self_intersection_fails_closed() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 20'>"
        "<path d='M0 0L10 10L0 10L10 0L20 20L0 20Z' fill='#f00'/>"
        "</svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_topology_collapse"
    assert result.raw.geometry_count == 0


def test_non_adjacent_shared_endpoint_overlap_fails_closed() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 100 100'>"
        "<path d='M10 10H90V90H10V10H50V50H10Z' "
        "fill='red' fill-rule='evenodd'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_topology_collapse"
    assert result.raw.geometry_count == 0


def test_non_adjacent_collinear_self_overlap_fails_closed() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 10'>"
        "<path d='M0 0H10V1L5 0H15V10H0Z' fill='#f00'/>"
        "</svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_topology_collapse"


def test_intersecting_subpaths_in_one_paint_fail_closed() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 20'>"
        "<path d='M0 0H10V10H0Z M5 -5H6V15H5Z' fill='#f00'/>"
        "</svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_topology_collapse"


def test_relative_path_rounding_chain_is_charged_to_input_budget() -> None:
    relative_steps = "h.03 " * 8000
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1100000 10'>"
        f"<path d='M1000000 0 {relative_steps}v10 h-240 z' fill='#f00'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_input_precision"


def test_transform_rounding_chain_is_charged_to_input_budget() -> None:
    transforms = "translate(.03 0) " * 8000
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1100000 10'>"
        f"<path transform='translate(1000000 0) {transforms}' "
        "d='M0 0H240V10H0Z' fill='#f00'/></svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_input_precision"


def test_shallow_crossing_exceeding_intersection_budget_fails_closed() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 1 2'>"
        "<path d='M0 0H1V1H0Z' fill='#f00'/>"
        "<path d='M0 .9995L1 1.0005V2H0Z' fill='#00f'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_topology_collapse"


def test_exported_grid_stays_in_normalized_svg_analysis_domain() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "fill_rules_transforms.svg",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    source_coordinates = (
        result.visible.coordinates.astype(np.float64)
        * result.grid_to_source_unit
    )
    assert source_coordinates[:, 0].min() == pytest.approx(20.0, abs=0.01)
    assert source_coordinates[:, 1].min() == pytest.approx(14.0, abs=0.01)
    assert source_coordinates[:, 0].max() == pytest.approx(146.0, abs=0.01)
    assert source_coordinates[:, 1].max() == pytest.approx(64.0, abs=0.01)
    assert np.all(source_coordinates[:, 0] >= 0.0)
    assert np.all(source_coordinates[:, 1] >= 0.0)
    assert np.all(source_coordinates[:, 0] <= result.bbox[2] + 0.01)
    assert np.all(source_coordinates[:, 1] <= result.bbox[3] + 0.01)


def test_collinear_cubic_overshoot_is_not_flattened_to_its_short_chord() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10'>"
        "<path d='M0 5C100 5 -100 5 10 5' fill='none' "
        "stroke='#000' stroke-width='1'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.bbox[0] < -15.0
    assert result.bbox[2] > 40.0
    source_coordinates = (
        result.raw.coordinates.astype(np.float64)
        * result.grid_to_source_unit
    )
    assert source_coordinates[:, 0].min() == pytest.approx(0.0, abs=0.02)
    assert source_coordinates[:, 0].max() == pytest.approx(
        result.bbox[2], abs=0.02
    )


def test_close_then_draw_that_overlaps_same_paint_fails_closed() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 30 10'>"
        "<path d='M0 0L10 0L0 10Z L30 0L30 10Z' fill='#f00'/>"
        "</svg>",
        target_width_mm=30.0,
        tolerance_mm=0.02,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "unsupported_topology_collapse"


def test_width_and_height_without_viewbox_do_not_expand_geometry_bbox() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg width='100' height='100'>"
        "<rect x='20' y='20' width='10' height='10' fill='#f00'/>"
        "</svg>",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.bbox == pytest.approx((20.0, 20.0, 10.0, 10.0), abs=0.02)
    assert result.scale_factor == pytest.approx(10.0, abs=0.02)
