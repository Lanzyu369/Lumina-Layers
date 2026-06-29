from __future__ import annotations

import numpy as np
import trimesh

from core.model_surface.assembly import build_embedded_overlay_scene
from core.model_surface.types import PlaneFrame, SurfaceFootprint


def test_build_embedded_overlay_scene_keeps_bounds_and_adds_base_slot():
    base = trimesh.creation.box(extents=(20.0, 10.0, 3.0))
    color = trimesh.creation.box(extents=(20.0, 10.0, 0.4))
    color.apply_translation((0.0, 0.0, 0.2))
    pattern = trimesh.Scene({"color_ff0000": color})
    footprint = SurfaceFootprint(
        frame=PlaneFrame(
            origin=(0.0, 0.0, 1.5),
            normal=(0.0, 0.0, 1.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
        ),
        outer=((-10.0, -5.0), (10.0, -5.0), (10.0, 5.0), (-10.0, 5.0), (-10.0, -5.0)),
        holes=(),
        bounds_min=(-10.0, -5.0),
        bounds_max=(10.0, 5.0),
        bounds_width_mm=20.0,
        bounds_height_mm=10.0,
        area_mm2=200.0,
        hole_count=0,
    )

    result = build_embedded_overlay_scene(
        base_mesh=base,
        pattern_scene=pattern,
        footprint=footprint,
        pocket_depth_mm=0.4,
        base_slot_name="surface_base",
        base_color=(245, 245, 245),
        allow_uncut_base=True,
    )

    assert "surface_base" in result.scene.geometry
    assert "color_ff0000" in result.scene.geometry
    assert result.slot_names == ["surface_base", "color_ff0000"]
    np.testing.assert_allclose(
        np.asarray(result.scene.bounds)[:, :2],
        np.asarray(base.bounds)[:, :2],
    )
