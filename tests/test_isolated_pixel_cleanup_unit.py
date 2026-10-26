"""Unit tests for isolated_pixel_cleanup logging contract.

Validates: P2-C - `merged_count` is omitted when it equals `isolated_count`.
"""

from __future__ import annotations

import logging

import numpy as np


def _build_minimal_inputs():
    """Build a 3x3 RGB image with a single isolated pixel surrounded by uniform color."""
    rgb_arr = np.full((3, 3, 3), 200, dtype=np.uint8)
    rgb_arr[1, 1] = (50, 50, 50)
    material_matrix = np.zeros((3, 3, 1), dtype=np.int32)
    material_matrix[1, 1, 0] = 1
    lut_rgb = np.array([[200, 200, 200], [50, 50, 50]], dtype=np.uint8)
    ref_stacks = np.array([[0], [1]], dtype=np.int32)
    return rgb_arr, material_matrix, lut_rgb, ref_stacks


def test_isolated_pixels_cleaned_omits_merged_count_when_all_merged(caplog):
    """When every isolated pixel is merged, merged_count must not be present."""
    from core import isolated_pixel_cleanup

    rgb_arr, material_matrix, lut_rgb, ref_stacks = _build_minimal_inputs()
    target_logger = isolated_pixel_cleanup._log
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=target_logger.name)
    try:
        isolated_pixel_cleanup.cleanup_isolated_pixels(material_matrix, rgb_arr, lut_rgb, ref_stacks)
    finally:
        target_logger.removeHandler(caplog.handler)

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "isolated_pixels_cleaned"
    ]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "isolated_count") >= 1
    assert getattr(record, "isolated_count") == record.__dict__.get(
        "merged_count", getattr(record, "isolated_count")
    )
    assert "merged_count" not in record.__dict__
