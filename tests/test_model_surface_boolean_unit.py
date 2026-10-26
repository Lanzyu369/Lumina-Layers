from __future__ import annotations

import numpy as np
import pytest
import shapely.geometry as sg
import trimesh
from shapely.ops import unary_union

from core.model_surface.assembly import (
    cut_surface_pocket,
)
from core.model_surface.types import PlaneFrame, SurfaceFootprint


def test_cut_surface_pocket_preserves_tiny_holes():
    polygon = sg.Polygon(
        [(40.10950907447116, -36.6471159409076),
         (40.10950907447116, 36.43138405909241),
         (-31.303589598272552, 36.43138405909241),
         (-31.303589598272552, -36.6471159409076)],
        holes=[
            [(19.87440945055289, -28.323515940907598),
             (19.612209455426054, -28.548615940907595),
             (19.78650945218658, -28.4011159409076)],
            [(-16.839689867093014, -28.260015940907593),
             (-16.66158987040312, -28.25091594090759),
             (-16.211789878762914, -28.2148159409076)],
            [(8.042709670452311, -28.373515940907595),
             (7.869609673669473, -28.38621594090759),
             (7.8991096731212025, -28.386415940907597)],
            [(7.4256096819215, -28.4802159409076),
             (7.425709681919628, -28.4803159409076),
             (8.042709670452311, -28.373515940907595)],
            [(7.817209674643365, -28.385715940907602),
             (7.6940096769331205, -28.3792159409076),
             (7.757209675758503, -28.3852159409076)],
        ],
    )
    base = trimesh.creation.box(extents=(100.0, 100.0, 3.0))
    base.metadata["material_slot"] = 3
    min_x, min_y, max_x, max_y = polygon.bounds
    footprint = SurfaceFootprint(
        frame=PlaneFrame((0, 0, 1.5), (0, 0, 1), (1, 0, 0), (0, 1, 0)),
        outer=tuple(polygon.exterior.coords),
        holes=tuple(tuple(ring.coords) for ring in polygon.interiors),
        bounds_min=(min_x, min_y), bounds_max=(max_x, max_y),
        bounds_width_mm=max_x - min_x, bounds_height_mm=max_y - min_y,
        area_mm2=polygon.area, hole_count=len(polygon.interiors),
    )

    cut = cut_surface_pocket(base, footprint, pocket_depth_mm=0.64)

    assert cut.is_volume
    np.testing.assert_allclose(cut.bounds, base.bounds)
    assert base.volume - cut.volume == pytest.approx(polygon.area * 0.66, abs=1e-5)
    assert cut.metadata["material_slot"] == 3
    top_triangles = cut.triangles[np.all(np.isclose(cut.triangles[:, :, 2], 1.5), axis=1)]
    top = unary_union([sg.Polygon(triangle[:, :2]) for triangle in top_triangles])
    # Every uncut hole retains material at the original top, including tiny holes.
    for ring in polygon.interiors:
        point = sg.Polygon(ring).representative_point()
        assert top.covers(point)


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


def test_cut_surface_pocket_preserves_reversed_inner_cavity() -> None:
    outer = trimesh.creation.box(extents=(20.0, 10.0, 4.0))
    cavity = trimesh.creation.box(extents=(18.0, 8.0, 3.6))
    cavity.invert()
    base = trimesh.util.concatenate((outer, cavity))
    assert base.is_volume
    assert len(base.split(only_watertight=True)) == 2
    footprint = SurfaceFootprint(
        frame=PlaneFrame(
            (0.0, 0.0, 2.0),
            (0.0, 0.0, 1.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ),
        outer=(
            (-1.0, -1.0),
            (1.0, -1.0),
            (1.0, 1.0),
            (-1.0, 1.0),
            (-1.0, -1.0),
        ),
        holes=(),
        bounds_min=(-1.0, -1.0),
        bounds_max=(1.0, 1.0),
        bounds_width_mm=2.0,
        bounds_height_mm=2.0,
        area_mm2=4.0,
        hole_count=0,
    )

    cut = cut_surface_pocket(base, footprint, pocket_depth_mm=0.1)

    assert cut.is_volume
    assert cut.volume < base.volume
    assert cut.volume == pytest.approx(base.volume, abs=1.0)


def test_cut_surface_pocket_handles_nearly_duplicate_boundary_vertices():
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

    base = trimesh.creation.box(extents=(4, 4, 3))
    min_x, min_y, max_x, max_y = polygon.bounds
    footprint = SurfaceFootprint(
        frame=PlaneFrame((0, 0, 1.5), (0, 0, 1), (1, 0, 0), (0, 1, 0)),
        outer=tuple(polygon.exterior.coords), holes=(),
        bounds_min=(min_x, min_y), bounds_max=(max_x, max_y),
        bounds_width_mm=max_x - min_x, bounds_height_mm=max_y - min_y,
        area_mm2=polygon.area, hole_count=0,
    )

    cut = cut_surface_pocket(base, footprint, pocket_depth_mm=0.4)

    assert cut.is_volume
    assert base.volume - cut.volume == pytest.approx(polygon.area * 0.42, rel=1e-6)
