"""Canonical Outline mesh regression tests."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import MultiPolygon, Polygon, box

import core.pipeline.vector_branch as vector_branch


def _edge_incidence_counts(mesh) -> np.ndarray:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    edges = np.concatenate(
        (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]),
        axis=0,
    )
    edges.sort(axis=1)
    return np.unique(edges, axis=0, return_counts=True)[1]


def _point_touching_hole_polygon() -> Polygon:
    angles = np.linspace(0.0, 2.0 * np.pi, 20, endpoint=False)
    large_hole = [
        (10.0 + 8.0 * np.cos(theta), 10.0 + 8.0 * np.sin(theta))
        for theta in angles
    ]
    contact = large_hole[0]
    polygon = Polygon(
        [(0.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0)],
        [large_hole, [contact, (25.0, 8.0), (25.0, 12.0), contact]],
    )
    assert polygon.is_valid
    return polygon


def _near_duplicate_boundary_polygon() -> Polygon:
    return Polygon(
        [
            (2509.917435338203, 4623.051929933649),
            (2510.172565883122, 4623.021385042616),
            (2510.883578978562, 4623.157336359613),
            (2556.1858527699997, 4617.512555038293),
            (2509.9174353413346, 4623.05192992644),
            (2509.7519150970775, 4622.940953283469),
        ]
    )


def _outline_analysis() -> SimpleNamespace:
    return SimpleNamespace(
        matched_shapes=[{"geometry": box(-20.0, -20.0, -10.0, -10.0)}],
        scale_factor=1.0,
        bbox=(0.0, 0.0, 30.0, 30.0),
        num_layers=1,
    )


def _outline_context() -> dict[str, object]:
    return {
        "spacer_thick": 1.0,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color RYBW",
        "enable_coating": False,
    }


def _patch_ring(monkeypatch: pytest.MonkeyPatch, ring) -> None:
    source = box(-20.0, -20.0, -10.0, -10.0)
    monkeypatch.setattr(
        vector_branch,
        "_vector_outline_union_geometry",
        lambda _matched_shapes: source,
    )
    monkeypatch.setattr(
        vector_branch,
        "_clip_vector_outline_buffer_to_expected_bounds",
        lambda _expanded, _union, _width_units: ring,
    )


def _build_outline(monkeypatch: pytest.MonkeyPatch, ring):
    _patch_ring(monkeypatch, ring)
    return vector_branch._generate_vector_outline_mesh(
        analysis=_outline_analysis(),
        outline_width_mm=1.0,
        base_aux_color=[255, 255, 255, 255],
        base_aux_material_name="White",
        ctx=_outline_context(),
    )


@pytest.mark.parametrize(
    "ring",
    [_point_touching_hole_polygon(), _near_duplicate_boundary_polygon()],
)
def test_vector_outline_is_closed_for_reported_ring_pathologies(
    monkeypatch: pytest.MonkeyPatch,
    ring: Polygon,
) -> None:
    outline = _build_outline(monkeypatch, ring)

    assert outline is not None
    assert outline.is_watertight
    assert outline.is_winding_consistent
    assert np.all(_edge_incidence_counts(outline) == 2)


def test_vector_outline_uses_the_canonical_layered_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = box(0.0, 0.0, 10.0, 10.0).difference(
        box(2.0, 2.0, 8.0, 8.0)
    )
    _patch_ring(monkeypatch, ring)
    real_prepare = vector_branch.prepare_vector_run_group
    real_extrude = vector_branch.extrude_prepared_vector_run_group
    calls: list[str] = []

    def record_prepare(*args, **kwargs):
        calls.append("prepare")
        return real_prepare(*args, **kwargs)

    def record_extrude(*args, **kwargs):
        calls.append("extrude")
        return real_extrude(*args, **kwargs)

    monkeypatch.setattr(vector_branch, "prepare_vector_run_group", record_prepare)
    monkeypatch.setattr(
        vector_branch,
        "extrude_prepared_vector_run_group",
        record_extrude,
    )

    outline = _build_outline(monkeypatch, ring)

    assert calls == ["prepare", "extrude"]
    assert outline is not None and outline.is_watertight


def test_vector_outline_omits_only_outline_when_canonical_build_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = box(0.0, 0.0, 10.0, 10.0).difference(
        box(2.0, 2.0, 8.0, 8.0)
    )
    _patch_ring(monkeypatch, ring)
    monkeypatch.setattr(
        vector_branch,
        "prepare_vector_run_group",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("synthetic canonical failure")
        ),
    )

    assert _build_outline(monkeypatch, ring) is None


def test_vector_outline_keeps_disconnected_shells_writer_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ring = MultiPolygon(
        [
            box(180.0, 245.0, 181.0, 246.0),
            box(181.0, 245.0, 182.0, 246.0),
        ]
    )
    outline = _build_outline(monkeypatch, ring)

    assert outline is not None
    writer_vertices = np.asarray(outline.vertices, dtype=np.float32)
    writer_faces = np.asarray(outline.faces, dtype=np.int64)
    triangles = writer_vertices[writer_faces]
    cross = np.cross(
        triangles[:, 1] - triangles[:, 0],
        triangles[:, 2] - triangles[:, 0],
    )
    assert not np.any(np.all(cross == 0.0, axis=1))
    writer_mesh = vector_branch.trimesh.Trimesh(
        vertices=writer_vertices,
        faces=writer_faces,
        process=False,
    )
    assert writer_mesh.is_watertight
    assert np.all(_edge_incidence_counts(writer_mesh) == 2)
