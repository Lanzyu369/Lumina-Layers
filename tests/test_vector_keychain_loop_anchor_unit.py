"""Regression tests for vector keychain loop placement."""

import numpy as np
import pytest
import trimesh

from core.pipeline.vector_branch import _vector_loop_attach_point


def _irregular_scene() -> trimesh.Scene:
    scene = trimesh.Scene()
    body = trimesh.creation.box(extents=(24.0, 58.0, 1.0))
    body.apply_translation((30.0, 29.0, 0.5))
    spike = trimesh.creation.box(extents=(4.0, 60.0, 1.0))
    spike.apply_translation((2.0, 30.0, 0.5))
    scene.add_geometry(body, geom_name="body")
    scene.add_geometry(spike, geom_name="spike")
    return scene


@pytest.mark.parametrize("captured_offset_y", [-6.5, -10.5])
def test_vector_top_center_clamps_inward_offset_to_local_contact_edge(
    captured_offset_y: float,
) -> None:
    scene = _irregular_scene()
    bounds = np.asarray(scene.bounds, dtype=np.float64)

    attach_x, attach_y = _vector_loop_attach_point(
        {
            "loop_position_preset": "top-center",
            "loop_width": 8.0,
            "loop_offset_x": 0.0,
            "loop_offset_y": captured_offset_y,
        },
        bounds,
        scene,
    )

    assert attach_x == 21.0
    assert attach_y == 58.0
