"""Physical-grid contracts for canonical native Vector run groups."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString, Polygon, box

from core.vector_layer_geometry import (
    VectorLayerGeometryPolicy,
    extrude_prepared_vector_run_group,
    prepare_vector_run_group,
)


def _assert_grid_aligned(group) -> None:
    for polygon in group.polygons:
        assert polygon.exterior_units.dtype == np.int64
        assert polygon.exterior_units.flags.c_contiguous
        assert not polygon.exterior_units.flags.writeable
        for hole in polygon.hole_units:
            assert hole.dtype == np.int64
            assert hole.flags.c_contiguous
            assert not hole.flags.writeable


def _edge_incidence_counts(mesh) -> np.ndarray:
    edges = np.asarray(mesh.edges_sorted, dtype=np.int64)
    _unique, counts = np.unique(edges, axis=0, return_counts=True)
    return counts


def test_shared_boundary_is_noded_once_without_an_internal_wall() -> None:
    prepared = prepare_vector_run_group(
        [box(0.0, 0.0, 10.0, 10.0), box(10.0, 0.0, 20.0, 10.0)],
        scale_mm_per_svg_unit=1.0,
    )

    geometry = prepared.to_geometry()
    assert geometry.geom_type == "Polygon"
    assert geometry.area == pytest.approx(200.0, abs=1e-9)
    assert len(prepared.polygons) == 1
    assert prepared.polygons[0].source_indices == (0, 1)
    assert geometry.boundary.intersection(
        LineString([(10.0, 0.0), (10.0, 10.0)])
    ).length == pytest.approx(0.0, abs=1e-12)
    _assert_grid_aligned(prepared)


def test_large_body_keeps_a_printable_independent_five_mm_island() -> None:
    prepared = prepare_vector_run_group(
        [box(0.0, 0.0, 200.0, 200.0), box(210.0, 0.0, 215.0, 5.0)],
        scale_mm_per_svg_unit=1.0,
    )

    assert len(prepared.polygons) == 2
    assert prepared.stats.source_component_count == 2
    assert prepared.stats.output_component_count == 2
    assert prepared.stats.source_area_mm2 == pytest.approx(40_025.0, abs=1e-9)
    assert prepared.stats.output_area_mm2 == pytest.approx(40_025.0, abs=1e-9)
    assert {polygon.source_indices for polygon in prepared.polygons} == {(0,), (1,)}


def test_hole_and_physical_scale_survive_canonicalization() -> None:
    source = Polygon(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        holes=[[(5.0, 5.0), (15.0, 5.0), (15.0, 15.0), (5.0, 15.0)]],
    )

    prepared = prepare_vector_run_group(
        [source],
        scale_mm_per_svg_unit=0.5,
    )

    geometry = prepared.to_geometry()
    assert geometry.area == pytest.approx(75.0, abs=1e-9)
    assert len(prepared.polygons) == 1
    assert len(prepared.polygons[0].hole_units) == 1
    assert prepared.stats.source_hole_count == 1
    assert prepared.stats.output_hole_count == 1
    assert geometry.bounds == pytest.approx((0.0, 0.0, 10.0, 10.0))


def test_near_duplicate_ring_points_collapse_on_the_physical_grid() -> None:
    source = Polygon(
        [
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (0.00000001, 10.0),
            (0.0, 10.0),
        ]
    )

    prepared = prepare_vector_run_group(
        [source],
        scale_mm_per_svg_unit=1.0,
    )

    assert prepared.to_geometry().is_valid
    assert len(prepared.polygons[0].exterior_units) == 4
    assert prepared.stats.output_area_mm2 == pytest.approx(100.0, abs=1e-9)


def test_float32_near_contact_is_separated_instead_of_serialized_as_touching_shells() -> None:
    float32_gap = 9.5367431640625e-7
    source = [
        box(0.0, 0.0, 200.0, 200.0),
        Polygon(
            [
                (200.0 + float32_gap, 100.0),
                (201.0, 99.0),
                (201.0, 101.0),
            ]
        ),
    ]

    prepared = prepare_vector_run_group(
        source,
        scale_mm_per_svg_unit=1.0,
    )

    geometry = prepared.to_geometry()
    assert geometry.geom_type == "MultiPolygon"
    assert geometry.is_valid
    assert prepared.stats.separated_contact_group_count == 1
    assert len(prepared.polygons) == 2
    assert geometry.hausdorff_distance(box(0.0, 0.0, 200.0, 200.0)) < 1.5
    _assert_grid_aligned(prepared)


def test_invalid_scale_and_partial_empty_input_fail_before_geometry_is_returned() -> None:
    with pytest.raises(ValueError, match="positive finite"):
        prepare_vector_run_group([box(0.0, 0.0, 1.0, 1.0)], scale_mm_per_svg_unit=0.0)

    with pytest.raises(ValueError, match="polygonal geometry"):
        prepare_vector_run_group(
            [box(0.0, 0.0, 1.0, 1.0), LineString([(0.0, 0.0), (1.0, 1.0)])],
            scale_mm_per_svg_unit=1.0,
        )


def test_sub_nozzle_zigzag_is_simplified_only_after_physical_grid_noding() -> None:
    source = Polygon(
        [
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (8.0, 10.001),
            (6.0, 9.999),
            (4.0, 10.001),
            (2.0, 9.999),
            (0.0, 10.0),
        ]
    )

    prepared = prepare_vector_run_group(
        [source],
        scale_mm_per_svg_unit=1.0,
    )

    assert prepared.stats.simplified_group_count == 1
    assert prepared.stats.restored_group_count == 0
    assert prepared.stats.output_coordinate_count < prepared.stats.input_coordinate_count
    assert prepared.to_geometry().hausdorff_distance(source) <= 0.0052


def test_source_part_that_collapses_on_physical_grid_is_not_silently_dropped() -> None:
    printable_body = box(0.0, 0.0, 10.0, 10.0)
    sub_grid_triangle = Polygon(
        [
            (10.0, 5.0),
            (10.00001, 5.0),
            (10.0, 5.00001),
        ]
    )

    with pytest.raises(ValueError, match="removed a source polygon"):
        prepare_vector_run_group(
            [printable_body, sub_grid_triangle],
            scale_mm_per_svg_unit=1.0,
            policy=VectorLayerGeometryPolicy(simplify_tolerance_mm=0.0),
        )


def test_prepared_group_extrudes_directly_to_one_closed_indexed_mesh() -> None:
    source = [
        box(0.0, 0.0, 200.0, 200.0),
        box(210.0, 0.0, 215.0, 5.0),
    ]
    prepared = prepare_vector_run_group(
        source,
        scale_mm_per_svg_unit=1.0,
    )

    mesh = extrude_prepared_vector_run_group(
        prepared,
        height_mm=0.2,
        z_offset_mm=0.4,
    )

    assert mesh.is_watertight
    assert mesh.is_winding_consistent
    assert np.all(_edge_incidence_counts(mesh) == 2)
    assert abs(float(mesh.volume)) == pytest.approx(40_025.0 * 0.2, abs=1e-5)
    assert mesh.bounds == pytest.approx(
        np.asarray([[0.0, 0.0, 0.4], [215.0, 200.0, 0.6]]),
        abs=1e-7,
    )
    assert mesh.metadata["_lumina_planar_coverage_mm2"] == pytest.approx(40_025.0)


def test_prepared_group_uses_the_same_ring_indices_for_caps_and_hole_walls() -> None:
    source = Polygon(
        [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        holes=[[(5.0, 5.0), (15.0, 5.0), (15.0, 15.0), (5.0, 15.0)]],
    )
    prepared = prepare_vector_run_group(
        [source],
        scale_mm_per_svg_unit=1.0,
    )

    mesh = extrude_prepared_vector_run_group(
        prepared,
        height_mm=1.0,
        z_offset_mm=0.0,
    )

    assert mesh.is_watertight
    assert mesh.is_winding_consistent
    assert np.all(_edge_incidence_counts(mesh) == 2)
    assert abs(float(mesh.volume)) == pytest.approx(300.0, abs=1e-8)


def test_prepared_extrusion_is_valid_after_the_actual_float32_writer_cast() -> None:
    float32_gap = 9.5367431640625e-7
    prepared = prepare_vector_run_group(
        [
            box(0.0, 0.0, 200.0, 200.0),
            Polygon(
                [
                    (200.0 + float32_gap, 100.0),
                    (201.0, 99.0),
                    (201.0, 101.0),
                ]
            ),
        ],
        scale_mm_per_svg_unit=1.0,
    )
    mesh = extrude_prepared_vector_run_group(
        prepared,
        height_mm=0.08,
        z_offset_mm=0.0,
    )

    writer_vertices = np.asarray(mesh.vertices, dtype=np.float32)
    triangles = writer_vertices[np.asarray(mesh.faces, dtype=np.int64)]
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])

    assert not np.any(np.all(cross == 0.0, axis=1))
    assert mesh.is_watertight
