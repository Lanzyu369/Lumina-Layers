from __future__ import annotations

import pytest
import trimesh

from core.model_surface.assembly import cut_surface_pocket
from core.model_surface.types import PlaneFrame, SurfaceFootprint


def test_cut_surface_pocket_preserves_outer_extents():
    base = trimesh.creation.box(extents=(20.0, 10.0, 3.0))
    footprint = SurfaceFootprint(
        frame=PlaneFrame(
            (0.0, 0.0, 1.5),
            (0.0, 0.0, 1.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ),
        outer=((-8.0, -3.0), (8.0, -3.0), (8.0, 3.0), (-8.0, 3.0), (-8.0, -3.0)),
        holes=(),
        bounds_min=(-8.0, -3.0),
        bounds_max=(8.0, 3.0),
        bounds_width_mm=16.0,
        bounds_height_mm=6.0,
        area_mm2=96.0,
        hole_count=0,
    )

    cut = cut_surface_pocket(base, footprint, pocket_depth_mm=0.4)

    assert cut.extents[0] == pytest.approx(base.extents[0])
    assert cut.extents[1] == pytest.approx(base.extents[1])
    assert cut.extents[2] == pytest.approx(base.extents[2])
    assert len(cut.faces) > 0
