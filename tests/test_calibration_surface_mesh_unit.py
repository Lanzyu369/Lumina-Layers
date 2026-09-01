"""Calibration voxel-surface regression tests."""

from __future__ import annotations

import numpy as np
import pytest

from config import PrinterConfig
from core.calibration import _generate_voxel_mesh
from core.mesh_export_parts import get_mesh_export_part_ranges


def test_calibration_voxels_build_closed_independent_shells() -> None:
    """Face neighbors merge while an edge-only contact stays independent."""

    labels = np.full((2, 2, 2), -1, dtype=np.int16)
    labels[0, 0, :2] = 1
    labels[1, 1, 0] = 1

    mesh = _generate_voxel_mesh(labels, 1, grid_h=2, grid_w=2)

    assert mesh is not None
    assert mesh.is_watertight
    assert mesh.is_winding_consistent
    expected_volume = (
        3
        * PrinterConfig.NOZZLE_WIDTH
        * PrinterConfig.NOZZLE_WIDTH
        * PrinterConfig.LAYER_HEIGHT
    )
    assert abs(float(mesh.volume)) == pytest.approx(expected_volume)
    assert len(get_mesh_export_part_ranges(mesh)) == 2


def test_calibration_voxel_rows_keep_legacy_physical_y_direction() -> None:
    """Row zero remains at low physical Y instead of being mirrored."""

    labels = np.full((1, 3, 2), -1, dtype=np.int16)
    labels[0, 0, 0] = 1

    mesh = _generate_voxel_mesh(labels, 1, grid_h=3, grid_w=2)

    assert mesh is not None
    assert mesh.bounds[:, 1] == pytest.approx(
        [0.0, float(PrinterConfig.NOZZLE_WIDTH)]
    )
