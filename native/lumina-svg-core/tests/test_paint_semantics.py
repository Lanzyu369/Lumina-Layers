"""Stroke, clip, source-order occlusion, and silhouette semantics."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Polygon, box

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


def test_closed_dash_merges_painted_segments_across_path_seam() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='-2 -2 14 14'>"
        "<path d='M0 0H10V10H0Z' fill='none' stroke='#000' "
        "stroke-width='2' stroke-linecap='butt' stroke-linejoin='miter' "
        "stroke-dasharray='10 10' stroke-dashoffset='5'/>"
        "</svg>",
        target_width_mm=14.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert result.raw.component_count == 2
    assert geometry_area(result, result.raw, 0) == pytest.approx(40.0, abs=0.1)


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


def test_nested_svg_default_viewport_clip_is_recorded() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 40 20'>"
        "<svg x='10' y='5' width='10' height='10' viewBox='0 0 10 10'>"
        "<path d='M-10 0H20V10H-10Z' fill='#f00'/>"
        "</svg></svg>",
        target_width_mm=40.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert geometry_bounds(result, result.raw, 0) == pytest.approx(
        (10.0, 5.0, 20.0, 15.0), abs=0.02
    )


def test_explicit_root_overflow_hidden_viewport_clip_is_recorded() -> None:
    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 10 10' overflow='hidden'>"
        "<path d='M-10 0H20V10H-10Z' fill='#f00'/>"
        "</svg>",
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert result.status == "supported"
    assert geometry_bounds(result, result.raw, 0) == pytest.approx(
        (0.0, 0.0, 10.0, 10.0), abs=0.02
    )


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
