from __future__ import annotations

import math
from dataclasses import replace

import pytest

from core.wipe_tower_placement import (
    Rect,
    WipeTowerPlacementRequest,
    estimate_wipe_tower_depth,
    solve_wipe_tower_placement,
)


def _request(
    *,
    model_size: tuple[float, float] = (100.0, 100.0),
    bed_size: tuple[float, float] = (180.0, 180.0),
    tower_x: float = 5.0,
    tower_y: float = 145.0,
    tower_width: float = 170.0,
    tower_rotation: float = 0.0,
    material_count: int = 4,
    purge_volume: float = 140.0,
    model_height: float = 2.0,
    model_brim: float = 5.0,
    tower_brim: float = 3.0,
    edge_clearance: float = 2.0,
    minimum_tower_footprint_width: float = 0.0,
    minimum_tower_depth: float = 0.0,
    model_tower_clearance: float = 8.0,
    exclusions: tuple[tuple[tuple[float, float], ...], ...] = (),
    extruder_areas: tuple[tuple[tuple[float, float], ...], ...] = (),
) -> WipeTowerPlacementRequest:
    width, height = model_size
    bed_width, bed_height = bed_size
    return WipeTowerPlacementRequest(
        printable_area=((0.0, 0.0), (bed_width, 0.0), (bed_width, bed_height), (0.0, bed_height)),
        bed_exclusions=exclusions,
        extruder_printable_areas=extruder_areas,
        model_bounds=Rect(0.0, 0.0, width, height),
        model_height=model_height,
        model_brim=model_brim,
        material_count=material_count,
        layer_height=0.08,
        nozzle_diameter=0.4,
        purge_volume=purge_volume,
        tower_x=tower_x,
        tower_y=tower_y,
        tower_width=tower_width,
        tower_rotation=tower_rotation,
        tower_brim=tower_brim,
        edge_clearance=edge_clearance,
        minimum_tower_footprint_width=minimum_tower_footprint_width,
        minimum_tower_depth=minimum_tower_depth,
        model_tower_clearance=model_tower_clearance,
    )


def _assert_safe(result) -> None:
    assert result.requires_manual_adjustment is False
    assert result.model_outer_bounds.intersection_area(result.tower_outer_bounds) == pytest.approx(0.0)
    assert result.model_outer_bounds.width > 0
    assert result.model_outer_bounds.height > 0


def test_estimated_depth_decreases_when_long_strip_grows() -> None:
    short = estimate_wipe_tower_depth(
        width=35.0,
        model_height=2.0,
        material_count=4,
        layer_height=0.08,
        nozzle_diameter=0.4,
        purge_volume=140.0,
    )
    long = estimate_wipe_tower_depth(
        width=200.0,
        model_height=2.0,
        material_count=4,
        layer_height=0.08,
        nozzle_diameter=0.4,
        purge_volume=140.0,
    )

    assert short > long
    assert long >= 5.0


def test_estimated_depth_reserves_native_discrete_paths_and_block_walls() -> None:
    depth = estimate_wipe_tower_depth(
        width=22.0,
        model_height=1.2,
        material_count=4,
        layer_height=0.08,
        nozzle_diameter=0.4,
        purge_volume=45.0,
        tower_infill_spacing_ratio=1.5,
    )

    # Native Bambu/Orca generation discretises each transition into 0.5 mm
    # paths and adds two structural lines per material block.  A continuous
    # volume estimate gives only 115.06 mm here, while the sliced tower is
    # 126.5 mm deep before its brim.
    assert depth == pytest.approx(126.5)


def test_keeps_original_tower_and_centered_model_when_layout_is_safe() -> None:
    request = _request(
        bed_size=(256.0, 256.0),
        model_size=(100.0, 100.0),
        tower_x=18.5216,
        tower_y=214.154,
        tower_width=220.0,
    )

    result = solve_wipe_tower_placement(request)

    assert result.adapted is False
    assert result.tower_x == pytest.approx(request.tower_x)
    assert result.tower_y == pytest.approx(request.tower_y)
    assert result.tower_width == pytest.approx(request.tower_width)
    assert result.tower_rotation == pytest.approx(request.tower_rotation)
    assert result.model_translation == pytest.approx((78.0, 78.0))
    _assert_safe(result)


def test_locked_model_translation_preserves_batch_coordinates() -> None:
    request = replace(
        _request(
            bed_size=(350.0, 320.0),
            model_size=(10.0, 8.0),
            tower_x=80.0,
            tower_y=250.0,
            tower_width=230.0,
        ),
        model_bounds=Rect(100.0, 50.0, 110.0, 58.0),
        model_translation_locked=True,
    )

    result = solve_wipe_tower_placement(request)

    assert result.model_translation == pytest.approx((0.0, 0.0))
    assert result.model_bounds == request.model_bounds
    _assert_safe(result)


def test_a1_mini_caps_orca_tower_that_is_longer_than_the_bed() -> None:
    request = _request(
        model_size=(120.0, 100.0),
        tower_x=7.45573,
        tower_y=219.877,
        tower_width=240.0,
    )

    result = solve_wipe_tower_placement(request)

    assert result.adapted is True
    assert result.tower_width <= 174.0
    assert result.tower_rotation == pytest.approx(0.0)
    _assert_safe(result)


def test_tall_model_selects_vertical_strip() -> None:
    result = solve_wipe_tower_placement(
        _request(
            model_size=(100.0, 155.0),
            tower_x=7.45573,
            tower_y=219.877,
            tower_width=240.0,
            purge_volume=30.0,
        )
    )

    assert result.adapted is True
    assert result.tower_rotation == pytest.approx(0.0)
    assert result.tower_bounds.height > result.tower_bounds.width
    assert result.tower_width == pytest.approx(30.0)
    assert result.reason in {"adapted_right", "adapted_left"}
    # Native slicers can generate tower/brim paths slightly beyond the visual
    # footprint. Keep a real 2 mm path margin inside the printable boundary.
    assert result.tower_bounds.right + 3.0 <= 178.0 + 1e-6
    _assert_safe(result)


def test_vertical_strip_reserves_a_native_minimum_footprint() -> None:
    result = solve_wipe_tower_placement(
        _request(
            bed_size=(256.0, 256.0),
            model_size=(180.0, 203.0),
            tower_x=26.7243,
            tower_y=220.0,
            tower_width=35.0,
            purge_volume=30.0,
            tower_brim=0.0,
            edge_clearance=0.0,
            minimum_tower_footprint_width=58.5,
            minimum_tower_depth=61.0,
            model_tower_clearance=7.5,
        )
    )

    assert result.requires_manual_adjustment is False
    assert result.reason in {"adapted_right", "adapted_left"}
    assert result.tower_width == pytest.approx(30.0)
    assert result.tower_bounds.width == pytest.approx(58.5)
    assert result.tower_bounds.height >= 61.0
    assert result.model_bounds.width == pytest.approx(180.0)
    assert result.model_bounds.left == pytest.approx(5.0)
    assert result.model_bounds.right == pytest.approx(185.0)
    assert result.tower_bounds.left - result.model_outer_bounds.right >= 7.5 - 1e-6
    _assert_safe(result)


def test_wide_model_selects_horizontal_strip() -> None:
    result = solve_wipe_tower_placement(
        _request(
            model_size=(155.0, 100.0),
            tower_x=7.45573,
            tower_y=219.877,
            tower_width=240.0,
        )
    )

    assert result.adapted is True
    assert result.tower_rotation == pytest.approx(0.0)
    _assert_safe(result)


def test_model_is_translated_without_changing_its_size() -> None:
    request = _request(
        bed_size=(256.0, 256.0),
        model_size=(200.0, 200.0),
        tower_x=18.5216,
        tower_y=214.154,
        tower_width=220.0,
    )

    result = solve_wipe_tower_placement(request)

    assert result.adapted is True
    assert result.model_bounds.width == pytest.approx(request.model_bounds.width)
    assert result.model_bounds.height == pytest.approx(request.model_bounds.height)
    assert math.isclose(result.model_translation[0], 28.0, abs_tol=30.0)
    assert result.model_translation != pytest.approx((28.0, 28.0))
    _assert_safe(result)


def test_common_extruder_area_is_respected_for_edge_limited_machine() -> None:
    request = _request(
        bed_size=(350.0, 320.0),
        model_size=(280.0, 120.0),
        tower_x=80.0,
        tower_y=250.0,
        tower_width=230.0,
        extruder_areas=(
            ((0.0, 0.0), (325.0, 0.0), (325.0, 320.0), (0.0, 320.0)),
            ((25.0, 0.0), (350.0, 0.0), (350.0, 320.0), (25.0, 320.0)),
        ),
    )

    result = solve_wipe_tower_placement(request)

    assert result.model_outer_bounds.left >= 25.0
    assert result.model_outer_bounds.right <= 325.0
    _assert_safe(result)


def test_bed_exclusion_forces_relayout() -> None:
    exclusion = (((0.0, 140.0), (180.0, 140.0), (180.0, 180.0), (0.0, 180.0)),)
    request = _request(
        model_size=(80.0, 80.0),
        tower_x=5.0,
        tower_y=145.0,
        tower_width=170.0,
        exclusions=exclusion,
    )

    result = solve_wipe_tower_placement(request)

    assert result.adapted is True
    assert result.tower_outer_bounds.bottom < 140.0
    _assert_safe(result)


def test_impossible_layout_keeps_model_scale_and_requires_manual_adjustment() -> None:
    request = _request(
        model_size=(179.0, 179.0),
        tower_x=7.45573,
        tower_y=219.877,
        tower_width=240.0,
    )

    result = solve_wipe_tower_placement(request)

    assert result.requires_manual_adjustment is True
    assert result.warning_code == "wipe_tower_manual_adjustment_required"
    assert result.model_bounds.width == pytest.approx(179.0)
    assert result.model_bounds.height == pytest.approx(179.0)
    assert result.tower_width > 0.0
