"""Uniform backing thickness must not allocate repeated raster planes."""

import numpy as np
import pytest

from core.pipeline import s06_voxel_building as s06


@pytest.mark.parametrize("structure,color_mode", [
    ("Single-sided", "4-Color"), ("Double-sided", "4-Color"),
    ("Single-sided", "5-Color Extended"),
])
def test_uniform_backing_preserves_dense_geometry_with_one_backing_plane(structure, color_mode) -> None:
    material = np.array([[[0, 1], [-1, -1]], [[1, 0], [0, 0]]], dtype=np.int16)
    solid = np.any(material >= 0, axis=2)
    ctx = {
        "material_matrix": material, "mask_solid": solid, "spacer_thick": 10,
        "structure_mode": structure, "color_mode": color_mode, "backing_color_id": 1,
        "matched_rgb": np.zeros((2, 2, 3), dtype=np.uint8), "pixel_scale": .1,
    }
    actual = s06.run(ctx)
    assert "error" not in actual
    expected, expected_meta = (
        s06._build_voxel_matrix_faceup(material, solid, 10, 1)
        if "Extended" in color_mode else s06._build_voxel_matrix(material, solid, 10, structure, 1)
    )
    edges = actual["voxel_z_edges"]
    assert actual["full_matrix"].shape[0] == (5 if "Double" in structure else 3)
    np.testing.assert_array_equal(np.repeat(actual["full_matrix"], np.diff(edges), axis=0), expected)
    assert actual["total_layers"] == len(expected)
    assert actual["backing_metadata"]["backing_z_range"] == expected_meta["backing_z_range"]
    np.testing.assert_array_equal(actual["backing_metadata"]["backing_z_min_map"], expected_meta["backing_z_min_map"])
    np.testing.assert_array_equal(actual["backing_metadata"]["backing_z_max_map"], expected_meta["backing_z_max_map"])
