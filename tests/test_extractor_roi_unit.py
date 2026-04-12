"""Unit tests for adaptive ROI sizing in color extraction.

Validates:
- Per-cell ROI bounded by local corrected center-to-center spacing (no overlap)
- Minimum half-ROI floor under extreme compression
- Boundary-clamped ROI produces valid (positive-area) regions for in-bounds cells
- Vectorised center coordinates match the original scalar transform
"""

from __future__ import annotations

import numpy as np
import pytest

from config import DST_SIZE
from core.extractor import _compute_sampling_geometry, _MIN_HALF_ROI

# All (grid_size, physical_grid) combos used in production
_MODE_GRIDS: list[tuple[int, int]] = [
    (6, 8),     # BW
    (32, 34),   # 4-Color (default)
    (36, 38),   # 6-Color
    (37, 39),   # 8-Color
    (32, 34),   # 5-Color Ext P1
    (38, 40),   # 5-Color Ext P2
]


class TestNoOverlap:
    """Adjacent ROI regions must never overlap."""

    @staticmethod
    def _assert_no_horizontal_overlap(
        centers_x: np.ndarray, half_roi_map: np.ndarray
    ) -> None:
        gs = centers_x.shape[0]
        for r in range(gs):
            for c in range(gs - 1):
                right_edge = centers_x[r, c] + half_roi_map[r, c]
                left_edge = centers_x[r, c + 1] - half_roi_map[r, c + 1]
                assert right_edge <= left_edge + 1, (
                    f"H-overlap at ({r},{c})->({r},{c+1}): "
                    f"right_edge={right_edge:.1f}, left_edge={left_edge:.1f}"
                )

    @staticmethod
    def _assert_no_vertical_overlap(
        centers_y: np.ndarray, half_roi_map: np.ndarray
    ) -> None:
        gs = centers_y.shape[0]
        for r in range(gs - 1):
            for c in range(gs):
                bottom_edge = centers_y[r, c] + half_roi_map[r, c]
                top_edge = centers_y[r + 1, c] - half_roi_map[r + 1, c]
                assert bottom_edge <= top_edge + 1, (
                    f"V-overlap at ({r},{c})->({r+1},{c}): "
                    f"bottom_edge={bottom_edge:.1f}, top_edge={top_edge:.1f}"
                )

    @pytest.mark.parametrize("grid_size,physical_grid", _MODE_GRIDS)
    def test_nominal_params(self, grid_size: int, physical_grid: int) -> None:
        """No overlap with default zoom=1, barrel=0."""
        cx, cy, hr = _compute_sampling_geometry(
            grid_size, physical_grid, zoom=1.0, barrel=0.0,
            offset_x=0, offset_y=0,
        )
        self._assert_no_horizontal_overlap(cx, hr)
        self._assert_no_vertical_overlap(cy, hr)

    @pytest.mark.parametrize(
        "zoom,barrel",
        [
            (0.8, 0.0),
            (1.0, -0.2),
            (0.8, -0.2),
            (0.7, -0.15),
            (1.2, 0.1),
        ],
    )
    @pytest.mark.parametrize("grid_size,physical_grid", _MODE_GRIDS)
    def test_extreme_params(
        self, grid_size: int, physical_grid: int, zoom: float, barrel: float
    ) -> None:
        """No overlap under supported zoom/distortion extremes."""
        cx, cy, hr = _compute_sampling_geometry(
            grid_size, physical_grid, zoom=zoom, barrel=barrel,
            offset_x=0, offset_y=0,
        )
        self._assert_no_horizontal_overlap(cx, hr)
        self._assert_no_vertical_overlap(cy, hr)


class TestMinimumFloor:
    """half_roi absolute floor and desired floor semantics."""

    @pytest.mark.parametrize(
        "zoom,barrel",
        [(0.5, -0.5), (0.3, -0.3), (0.7, -0.3)],
    )
    def test_absolute_floor_under_extreme_compression(
        self, zoom: float, barrel: float
    ) -> None:
        """Absolute floor of 1px holds even when spacing is tiny."""
        for grid_size, physical_grid in _MODE_GRIDS:
            _cx, _cy, hr = _compute_sampling_geometry(
                grid_size, physical_grid, zoom=zoom, barrel=barrel,
                offset_x=0, offset_y=0,
            )
            assert hr.min() >= 1

    @pytest.mark.parametrize("grid_size,physical_grid", _MODE_GRIDS)
    def test_desired_floor_under_nominal_params(
        self, grid_size: int, physical_grid: int
    ) -> None:
        """Under default zoom/barrel, half_roi >= _MIN_HALF_ROI."""
        _cx, _cy, hr = _compute_sampling_geometry(
            grid_size, physical_grid, zoom=1.0, barrel=0.0,
            offset_x=0, offset_y=0,
        )
        assert hr.min() >= _MIN_HALF_ROI


class TestBoundaryClamp:
    """Clamped ROI coordinates must produce positive-area regions."""

    @pytest.mark.parametrize(
        "offset_x,offset_y",
        [(50, -50), (-30, 40), (0, 0)],
    )
    @pytest.mark.parametrize("grid_size,physical_grid", _MODE_GRIDS[:3])
    def test_clamped_roi_positive_area(
        self,
        grid_size: int,
        physical_grid: int,
        offset_x: float,
        offset_y: float,
    ) -> None:
        cx, cy, hr = _compute_sampling_geometry(
            grid_size, physical_grid, zoom=1.0, barrel=0.0,
            offset_x=offset_x, offset_y=offset_y,
        )
        for r in range(grid_size):
            for c in range(grid_size):
                cxv, cyv = float(cx[r, c]), float(cy[r, c])
                if not (0 <= cxv < DST_SIZE and 0 <= cyv < DST_SIZE):
                    continue
                hrv = int(hr[r, c])
                x0 = int(max(0, cxv - hrv))
                y0 = int(max(0, cyv - hrv))
                x1 = int(min(DST_SIZE, cxv + hrv))
                y1 = int(min(DST_SIZE, cyv + hrv))
                assert x1 > x0 and y1 > y0, (
                    f"Zero-area ROI at ({r},{c}): "
                    f"[{x0}:{x1}, {y0}:{y1}]"
                )

    @pytest.mark.parametrize(
        "zoom,barrel",
        [(1.2, 0.2), (1.3, 0.1)],
    )
    def test_out_of_bounds_center_still_sampled_when_roi_overlaps(
        self, zoom: float, barrel: float
    ) -> None:
        """Cells whose center is outside DST_SIZE but whose clamped ROI
        still overlaps the image must be counted as sampleable, not dropped."""
        grid_size, physical_grid = 32, 34
        cx, cy, hr = _compute_sampling_geometry(
            grid_size, physical_grid, zoom=zoom, barrel=barrel,
            offset_x=0, offset_y=0,
        )
        recovered = 0
        for r in range(grid_size):
            for c in range(grid_size):
                cxv, cyv = float(cx[r, c]), float(cy[r, c])
                hrv = int(hr[r, c])
                center_in = 0 <= cxv < DST_SIZE and 0 <= cyv < DST_SIZE
                x0 = int(max(0, cxv - hrv))
                y0 = int(max(0, cyv - hrv))
                x1 = int(min(DST_SIZE, cxv + hrv))
                y1 = int(min(DST_SIZE, cyv + hrv))
                roi_valid = x1 > x0 and y1 > y0
                if not center_in and roi_valid:
                    recovered += 1
        # Under zoom=1.2 + barrel=0.2 several corner/edge cells have
        # out-of-bounds centers but ROIs that still overlap the image.
        # With the old strict center check these would all be black;
        # now they must be recovered.
        assert recovered > 0, (
            f"Expected some recovered out-of-bounds cells for "
            f"zoom={zoom}, barrel={barrel}, got 0"
        )

    @pytest.mark.parametrize(
        "zoom,barrel",
        [(1.2, 0.2), (1.0, -0.2)],
    )
    @pytest.mark.parametrize("grid_size,physical_grid", _MODE_GRIDS[:3])
    def test_all_sampleable_cells_have_positive_area(
        self,
        grid_size: int,
        physical_grid: int,
        zoom: float,
        barrel: float,
    ) -> None:
        """Every cell whose clamped ROI has positive area is sampleable."""
        cx, cy, hr = _compute_sampling_geometry(
            grid_size, physical_grid, zoom=zoom, barrel=barrel,
            offset_x=0, offset_y=0,
        )
        for r in range(grid_size):
            for c in range(grid_size):
                cxv, cyv = float(cx[r, c]), float(cy[r, c])
                hrv = int(hr[r, c])
                x0 = int(max(0, cxv - hrv))
                y0 = int(max(0, cyv - hrv))
                x1 = int(min(DST_SIZE, cxv + hrv))
                y1 = int(min(DST_SIZE, cyv + hrv))
                if x1 > x0 and y1 > y0:
                    assert x0 >= 0 and y0 >= 0
                    assert x1 <= DST_SIZE and y1 <= DST_SIZE


class TestCenterConsistency:
    """Vectorised centers must match the original scalar computation."""

    def test_centers_match_scalar_loop(self) -> None:
        grid_size, physical_grid = 32, 34
        zoom, barrel = 0.9, -0.1
        ox, oy = 5.0, -3.0

        cx, cy, _hr = _compute_sampling_geometry(
            grid_size, physical_grid, zoom=zoom, barrel=barrel,
            offset_x=ox, offset_y=oy,
        )

        for r in range(grid_size):
            for c in range(grid_size):
                phys_r, phys_c = r + 1, c + 1
                nx = (phys_c + 0.5) / physical_grid * 2 - 1
                ny = (phys_r + 0.5) / physical_grid * 2 - 1
                rad = np.sqrt(nx**2 + ny**2)
                k = 1 + barrel * (rad**2)
                dx_s, dy_s = nx * k * zoom, ny * k * zoom
                expected_cx = (dx_s + 1) / 2 * DST_SIZE + ox
                expected_cy = (dy_s + 1) / 2 * DST_SIZE + oy
                assert abs(cx[r, c] - expected_cx) < 1e-10, (
                    f"cx mismatch at ({r},{c})"
                )
                assert abs(cy[r, c] - expected_cy) < 1e-10, (
                    f"cy mismatch at ({r},{c})"
                )
