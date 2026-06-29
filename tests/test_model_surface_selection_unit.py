from __future__ import annotations

import pytest
import trimesh

from core.model_surface.footprint import build_surface_footprint
from core.model_surface.selection import select_planar_component


def test_select_planar_component_finds_top_box_face():
    mesh = trimesh.creation.box(extents=(20.0, 10.0, 2.0))
    face_index = int(max(range(len(mesh.faces)), key=lambda i: mesh.face_normals[i][2]))

    selection = select_planar_component(mesh, face_index)

    assert selection.face_count == 2
    assert selection.area_mm2 == pytest.approx(200.0)
    assert selection.normal == pytest.approx((0.0, 0.0, 1.0))


def test_surface_footprint_preserves_rectangular_bounds():
    mesh = trimesh.creation.box(extents=(20.0, 10.0, 2.0))
    face_index = int(max(range(len(mesh.faces)), key=lambda i: mesh.face_normals[i][2]))
    selection = select_planar_component(mesh, face_index)

    footprint = build_surface_footprint(mesh, selection.face_indices)

    assert footprint.bounds_width_mm == pytest.approx(20.0)
    assert footprint.bounds_height_mm == pytest.approx(10.0)
    assert footprint.area_mm2 == pytest.approx(200.0)
    assert footprint.hole_count == 0


def test_surface_footprint_preserves_inner_hole():
    mesh = _flat_square_frame_mesh()

    footprint = build_surface_footprint(mesh, tuple(range(len(mesh.faces))))

    assert footprint.bounds_width_mm == pytest.approx(20.0)
    assert footprint.bounds_height_mm == pytest.approx(20.0)
    assert footprint.area_mm2 == pytest.approx(336.0)
    assert footprint.hole_count == 1


def _flat_square_frame_mesh() -> trimesh.Trimesh:
    rectangles = [
        (-10.0, -10.0, 10.0, -4.0),
        (-10.0, 4.0, 10.0, 10.0),
        (-10.0, -4.0, -4.0, 4.0),
        (4.0, -4.0, 10.0, 4.0),
    ]
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for minx, miny, maxx, maxy in rectangles:
        base = len(vertices)
        vertices.extend(
            [
                (minx, miny, 0.0),
                (maxx, miny, 0.0),
                (maxx, maxy, 0.0),
                (minx, maxy, 0.0),
            ]
        )
        faces.extend([(base, base + 1, base + 2), (base, base + 2, base + 3)])
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
