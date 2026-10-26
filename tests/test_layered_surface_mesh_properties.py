"""Property contracts for raster mesher adoption of labeled surfaces."""

from __future__ import annotations

import numpy as np
from hypothesis import given, settings, strategies as st

from core.mesh_generators import HighFidelityMesher, VoxelMesher


@st.composite
def _small_label_volumes(draw):
    z_size = draw(st.integers(min_value=1, max_value=3))
    y_size = draw(st.integers(min_value=1, max_value=4))
    x_size = draw(st.integers(min_value=1, max_value=4))
    values = draw(
        st.lists(
            st.integers(min_value=-1, max_value=2),
            min_size=z_size * y_size * x_size,
            max_size=z_size * y_size * x_size,
        )
    )
    labels = np.asarray(values, dtype=np.int16).reshape((z_size, y_size, x_size))
    material_id = draw(st.integers(min_value=0, max_value=2))
    return labels, material_id


def _horizontal_section_occupancy(mesh, shape: tuple[int, int, int]) -> np.ndarray:
    """Recover cell occupancy from independent horizontal mesh sections."""

    z_size, y_size, x_size = shape
    occupied = np.zeros(shape, dtype=bool)
    for z_index in range(z_size):
        section = mesh.section(
            plane_origin=(0.0, 0.0, z_index + 0.5),
            plane_normal=(0.0, 0.0, 1.0),
        )
        if section is None:
            continue
        segment_chunks = []
        for entity in section.entities:
            points = section.vertices[np.asarray(entity.points), :2]
            if len(points) >= 2:
                segment_chunks.append(
                    np.stack((points[:-1], points[1:]), axis=1)
                )
        segments = np.concatenate(segment_chunks, axis=0)
        first = segments[:, 0]
        second = segments[:, 1]
        for y_index in range(y_size):
            for x_index in range(x_size):
                probe_x = x_index + 0.413
                probe_y = y_size - y_index - 0.371
                crosses_y = (first[:, 1] > probe_y) != (
                    second[:, 1] > probe_y
                )
                crossing_x = first[:, 0] + (
                    (probe_y - first[:, 1])
                    * (second[:, 0] - first[:, 0])
                    / np.where(
                        second[:, 1] == first[:, 1],
                        1.0,
                        second[:, 1] - first[:, 1],
                    )
                )
                occupied[z_index, y_index, x_index] = bool(
                    np.count_nonzero(crosses_y & (crossing_x > probe_x)) % 2
                )
    return occupied


@settings(max_examples=60, deadline=None)
@given(case=_small_label_volumes())
def test_no_dilation_raster_meshers_preserve_independent_section_occupancy(
    case,
) -> None:
    labels, material_id = case
    expected_occupancy = labels == material_id

    for mesher in (
        VoxelMesher(),
        HighFidelityMesher(disable_material_dilation=True),
    ):
        actual = mesher.generate_mesh(
            labels,
            material_id,
            height_px=labels.shape[1],
        )
        if not bool(np.any(expected_occupancy)):
            assert actual is None
            continue
        assert actual is not None
        assert actual.is_watertight
        np.testing.assert_array_equal(
            _horizontal_section_occupancy(actual, labels.shape),
            expected_occupancy,
        )
        assert float(actual.volume) == float(np.count_nonzero(expected_occupancy))
