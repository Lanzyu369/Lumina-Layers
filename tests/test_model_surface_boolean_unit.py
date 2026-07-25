from __future__ import annotations

import pytest
import shapely.geometry as sg
import trimesh

from core.model_surface.assembly import (
    _build_polygon_prism_mesh,
    cut_surface_pocket,
)
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


def test_polygon_prism_is_volume_with_nearly_duplicate_boundary_vertices():
    polygon = sg.Polygon(
        (
            (0.9710505662045676, 0.0),
            (0.8344205663964743, 0.07093299990037849),
            (0.7548535665082312, 0.13188499981478685),
            (0.585797566745569, 0.38525299945894176),
            (0.5857975656029311, 0.38525299917040456),
            (0.41420243325443096, 0.5091319805808041),
            (0.16201956734080625, 0.4738609993344767),
            (0.0, 0.49546373292163537),
            (0.0, 0.9471924900198729),
            (1.0, 0.9471924900198729),
            (1.0, 0.001856922367423408),
        )
    )

    prism = _build_polygon_prism_mesh(polygon, height_mm=0.44)

    assert prism.is_volume
    assert prism.volume == pytest.approx(polygon.area * 0.44, rel=1e-6)
