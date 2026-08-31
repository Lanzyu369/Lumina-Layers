"""Physical error allocation and fill topology tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import lumina_svg_core


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_document_viewport_remains_part_of_lumina_bbox_contract() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "basic_fill_stroke.svg", 20.0, 0.02
    )

    assert result.status == "supported"
    assert result.bbox == pytest.approx((0.0, 0.0, 20.0, 10.0), abs=1e-6)
    assert result.scale_factor == pytest.approx(1.0)


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


def test_robust_non_adjacent_self_intersection_is_supported() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 20'>"
        "<path d='M0 0L10 10L0 10L10 0L20 20L0 20Z' fill='#f00'/>"
        "</svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count > 0


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


def test_close_path_restores_subpath_start_for_following_draw_verbs() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 30 10'>"
        "<path d='M0 0L10 0L0 10Z L30 0L30 10Z' fill='#f00'/>"
        "</svg>",
        target_width_mm=30.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    source_coordinates = (
        result.raw.coordinates.astype(np.float64)
        * result.grid_to_source_unit
    )
    assert source_coordinates[:, 0].max() == pytest.approx(30.0, abs=0.02)


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
