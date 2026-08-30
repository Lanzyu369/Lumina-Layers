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


def test_non_uniform_transform_uses_one_model_space_error_budget() -> None:
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "fill_rules_transforms.svg",
        target_width_mm=100.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.max_flattening_error_mm == pytest.approx(0.008)
    assert result.max_quantization_error_mm == pytest.approx(0.004)
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
