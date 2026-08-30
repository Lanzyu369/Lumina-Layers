"""Physical error allocation and fill topology tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import lumina_svg_core


FIXTURES = Path(__file__).resolve().parent / "fixtures"


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
    assert source_coordinates[:, 0].min() == pytest.approx(0.0, abs=0.01)
    assert source_coordinates[:, 1].min() == pytest.approx(0.0, abs=0.01)
    assert source_coordinates[:, 0].max() == pytest.approx(
        result.bbox[2], abs=0.01
    )
    assert source_coordinates[:, 1].max() == pytest.approx(
        result.bbox[3], abs=0.01
    )
