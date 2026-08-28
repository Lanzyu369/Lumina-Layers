"""Raster Outline must use the canonical layered surface builder."""

from __future__ import annotations

import numpy as np
import pytest

from core.pipeline.s08_auxiliary_meshes import _generate_outline_mesh


@pytest.mark.parametrize(
    "mask",
    [
        np.pad(np.ones((1, 1), dtype=bool), 2),
        np.pad(np.ones((3, 3), dtype=bool), 1),
    ],
)
def test_raster_outline_has_exactly_two_faces_per_edge(mask: np.ndarray) -> None:
    outline = _generate_outline_mesh(
        mask_solid=mask,
        pixel_scale=0.1,
        outline_width_mm=0.1,
        outline_thickness_mm=0.32,
        target_h=int(mask.shape[0]),
    )

    assert outline is not None
    edge_counts = np.unique(
        np.asarray(outline.edges_sorted, dtype=np.int64),
        axis=0,
        return_counts=True,
    )[1]
    assert outline.is_watertight
    assert np.all(edge_counts == 2)
    assert outline.metadata["integer_topology_scale"] == 2
