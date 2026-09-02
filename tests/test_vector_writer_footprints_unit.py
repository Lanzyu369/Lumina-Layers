"""Writer-domain footprint regressions for vector prism export."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import MultiPolygon, Polygon, box
import trimesh

from core import vector_engine
from core.vector_mesh_topology import (
    mesh_is_float32_safe,
    prepare_component_footprints_for_float32,
    separate_component_coordinates,
)


def _writer_polygon(poly: Polygon, scale: float = 1.0) -> Polygon:
    """Map a polygon through the float32 coordinate domain used by 3MF."""

    def writer_ring(ring) -> np.ndarray:
        coordinates = np.asarray(ring.coords, dtype=np.float64)[:, :2]
        return (coordinates * scale).astype(np.float32).astype(np.float64)

    return Polygon(
        writer_ring(poly.exterior),
        [writer_ring(ring) for ring in poly.interiors],
    )


def test_preflight_separates_vertex_collapsing_onto_other_component_edge() -> None:
    """A source-space gap must survive the actual float32 writer mapping."""

    float32_gap = 9.5367431640625e-7
    components = [
        box(199.0, 0.0, 200.0, 2.0),
        Polygon(
            [
                (200.0 + float32_gap, 0.7),
                (201.0, 0.2),
                (201.0, 1.4),
            ]
        ),
    ]
    assert components[0].distance(components[1]) > 0.0
    assert _writer_polygon(components[0]).intersects(
        _writer_polygon(components[1])
    )

    prepared = prepare_component_footprints_for_float32(
        components,
        xy_scale=1.0,
    )

    assert prepared is not None
    assert [poly.area for poly in prepared] == pytest.approx(
        [poly.area for poly in components]
    )
    writer_components = [_writer_polygon(poly) for poly in prepared]
    assert writer_components[0].disjoint(writer_components[1])
    assert prepared[0].equals_exact(components[0], tolerance=0.0)
    assert prepared[1].hausdorff_distance(components[1]) <= 8e-4


def test_preflight_scales_physical_separation_back_to_source_coordinates() -> None:
    """The bounded adjustment remains 0.0001 mm at non-unit SVG scales."""

    scale = 0.04
    components = [
        box(0.0, 0.0, 25.0, 25.0),
        box(25.0, 25.0, 50.0, 50.0),
    ]

    prepared = prepare_component_footprints_for_float32(
        components,
        xy_scale=scale,
    )

    assert prepared is not None
    writer_components = [_writer_polygon(poly, scale) for poly in prepared]
    assert writer_components[0].disjoint(writer_components[1])
    physical_shift = prepared[1].hausdorff_distance(components[1]) * scale
    assert 0.0 < physical_shift <= 8e-4


def test_mesh_compatibility_guard_detects_and_separates_edge_contact() -> None:
    """The legacy mesh API must enforce the same prism-footprint contract."""

    float32_gap = 9.5367431640625e-7
    footprints = [
        box(199.0, 0.0, 200.0, 2.0),
        Polygon(
            [
                (200.0 + float32_gap, 0.7),
                (201.0, 0.2),
                (201.0, 1.4),
            ]
        ),
    ]
    meshes = [
        trimesh.creation.extrude_polygon(footprint, height=1.0)
        for footprint in footprints
    ]

    assert not mesh_is_float32_safe(
        trimesh.util.concatenate(meshes),
        xy_scale=1.0,
    )
    assert separate_component_coordinates(meshes, xy_scale=1.0)
    assert mesh_is_float32_safe(
        trimesh.util.concatenate(meshes),
        xy_scale=1.0,
    )


def test_vector_engine_resolves_component_contacts_before_extrusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production must consume the 2D preflight, not a post-mesh repair pass."""

    float32_gap = 9.5367431640625e-7
    geometry = MultiPolygon(
        [
            box(199.0, 0.0, 200.0, 2.0),
            Polygon(
                [
                    (200.0 + float32_gap, 0.7),
                    (201.0, 0.2),
                    (201.0, 1.4),
                ]
            ),
        ]
    )
    assert geometry.is_valid

    def reject_post_mesh_repair(*_args, **_kwargs):
        raise AssertionError("post-mesh component repair should not run")

    monkeypatch.setattr(
        vector_engine,
        "separate_component_coordinates",
        reject_post_mesh_repair,
    )
    meshes = vector_engine.VectorProcessor._extrude_geometry(
        geometry,
        height=0.2,
        z_offset=0.0,
        scale=1.0,
        extrude_cache={},
    )

    assert len(meshes) == 2
    assert mesh_is_float32_safe(trimesh.util.concatenate(meshes))
