"""Physical-grid contracts for canonical native Vector run groups."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

import core.vector_layer_geometry as vector_layer_geometry
from core.vector_layer_geometry import (
    VectorLayerGeometryPolicy,
    build_vector_stepped_volume,
    extrude_prepared_vector_run_group,
    prepare_vector_run_group,
    prepare_vector_spatial_groups_best_effort,
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


def _assert_closed_volume(mesh, expected_volume: float) -> None:
    assert mesh is not None
    assert mesh.is_watertight
    assert mesh.is_winding_consistent
    assert np.all(_edge_incidence_counts(mesh) == 2)
    assert abs(float(mesh.volume)) == pytest.approx(expected_volume, abs=1e-5)


def test_stepped_volume_builds_cavity_and_height_transitions_directly() -> None:
    outer = box(0.0, 0.0, 10.0, 10.0)
    cavity = box(4.0, 4.0, 6.0, 6.0)

    mesh = build_vector_stepped_volume(
        [
            {"geometry": outer, "z_offset": 0.0, "height": 0.4},
            {
                "geometry": outer.difference(cavity),
                "z_offset": 0.4,
                "height": 0.6,
            },
            {"geometry": outer, "z_offset": 1.0, "height": 0.4},
        ],
        scale_mm_per_svg_unit=1.0,
    )

    _assert_closed_volume(mesh, 137.6)


def test_stepped_volume_nodes_shared_curve_once_without_repair() -> None:
    left = Polygon([(0.0, 0.0), (5.0, 0.0), (6.0, 10.0), (0.0, 10.0)])
    shared_midpoint = (5.5 + 1e-12, 5.0)
    right_lower = Polygon(
        [(5.0, 0.0), (10.0, 0.0), (10.0, 5.0), shared_midpoint]
    )
    right_upper = Polygon(
        [shared_midpoint, (10.0, 5.0), (10.0, 10.0), (6.0, 10.0)]
    )

    mesh = build_vector_stepped_volume(
        [
            {"geometry": left, "z_offset": 0.0, "height": 1.8},
            {"geometry": right_lower, "z_offset": 0.0, "height": 0.8},
            {"geometry": right_upper, "z_offset": 0.0, "height": 1.4},
        ],
        scale_mm_per_svg_unit=1.0,
    )

    expected = left.area * 1.8 + right_lower.area * 0.8 + right_upper.area * 1.4
    _assert_closed_volume(mesh, expected)


def test_stepped_volume_keeps_corner_touching_shells_independent() -> None:
    mesh = build_vector_stepped_volume(
        [
            {
                "geometry": box(0.0, 0.0, 1.0, 1.0),
                "z_offset": 0.0,
                "height": 1.0,
            },
            {
                "geometry": box(1.0, 1.0, 2.0, 2.0),
                "z_offset": 0.0,
                "height": 1.8,
            },
        ],
        scale_mm_per_svg_unit=1.0,
    )

    _assert_closed_volume(mesh, 2.8)
    assert len(mesh.split(only_watertight=False)) == 2
    writer_vertices = np.asarray(mesh.vertices, dtype=np.float32)
    assert len(np.unique(writer_vertices, axis=0)) == len(writer_vertices)


def test_stepped_volume_splits_local_edge_pinch_inside_connected_volume() -> None:
    mesh = build_vector_stepped_volume(
        [
            {
                "geometry": box(0.0, 0.0, 1.0, 1.0),
                "z_offset": 0.0,
                "height": 0.3,
            },
            {
                "geometry": box(-1.0, -1.0, 0.0, 0.5),
                "z_offset": 0.1,
                "height": 0.1,
            },
            {
                "geometry": box(0.0, -0.5, 2.0, 1.0),
                "z_offset": 0.2,
                "height": 0.1,
            },
        ],
        scale_mm_per_svg_unit=1.0,
    )

    _assert_closed_volume(mesh, 0.65)
    writer_vertices = np.asarray(mesh.vertices, dtype=np.float32)
    assert len(np.unique(writer_vertices, axis=0)) == len(writer_vertices)


def test_stepped_volume_keeps_noded_collinear_cap_boundaries() -> None:
    continuing = Polygon(
        [(6.0, 9.0), (9.0, 9.0), (9.25, 10.5), (6.0, 10.5)]
    )
    lower_left = box(5.0, 9.0, 8.0, 12.0)
    lower_right = box(6.0, 8.5, 10.0, 13.0)

    mesh = build_vector_stepped_volume(
        [
            {
                "geometry": continuing,
                "z_offset": 0.24,
                "height": 0.40,
            },
            {
                "geometry": lower_right,
                "z_offset": 0.24,
                "height": 0.32,
            },
            {
                "geometry": lower_left,
                "z_offset": 0.24,
                "height": 0.32,
            },
        ],
        scale_mm_per_svg_unit=1.0,
    )

    lower_footprint = unary_union([continuing, lower_left, lower_right])
    expected_volume = lower_footprint.area * 0.32 + continuing.area * 0.08
    _assert_closed_volume(mesh, expected_volume)


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


def test_independently_checked_grid_groups_do_not_false_fail_in_aggregate() -> None:
    source = [
        Polygon(
            [
                (float(index * 3), 0.0),
                (float(index * 3 + 1), 0.0),
                (float(index * 3), 1.0049),
            ]
        )
        for index in range(5)
    ]

    prepared = prepare_vector_run_group(
        source,
        scale_mm_per_svg_unit=1.0,
        policy=VectorLayerGeometryPolicy(
            grid_mm=0.01,
            simplify_tolerance_mm=0.0,
        ),
    )

    assert prepared.stats.spatial_group_count == 5
    assert prepared.stats.source_area_mm2 - prepared.stats.output_area_mm2 > 0.01
    assert prepared.stats.output_area_mm2 == pytest.approx(2.5, abs=1e-12)
    assert len(prepared.polygons) == 5


def test_grid_quantization_drift_does_not_drop_a_valid_outline_ring() -> None:
    """Coverage is measured from the representable grid, not raw float input."""

    rectangle = box(10.0, 10.0, 50.0, 50.0)
    circle = Polygon(
        [
            (
                70.0 + 15.0 * np.cos(theta),
                30.0 + 15.0 * np.sin(theta),
            )
            for theta in np.linspace(0.0, 2.0 * np.pi, 64, endpoint=False)
        ]
    )
    body = unary_union([rectangle, circle])
    outline = body.buffer(
        2.5998495286426193,
        join_style="mitre",
        mitre_limit=2.0,
    ).difference(body)

    prepared = prepare_vector_run_group(
        [outline],
        scale_mm_per_svg_unit=1.0,
    )

    assert prepared.to_geometry().is_valid
    assert prepared.stats.output_component_count == 1
    assert prepared.stats.output_hole_count == 2
    assert prepared.stats.source_area_mm2 - prepared.stats.output_area_mm2 > 0.01


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


def test_contact_regularization_uses_constructive_bounds_not_global_hausdorff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_global_hausdorff(*_args, **_kwargs):
        raise AssertionError("contact regularization must stay linear")

    monkeypatch.setattr(
        BaseGeometry,
        "hausdorff_distance",
        fail_global_hausdorff,
    )

    prepared = prepare_vector_run_group(
        [box(0.0, 0.0, 10.0, 10.0)],
        scale_mm_per_svg_unit=1.0,
        policy=VectorLayerGeometryPolicy(simplify_tolerance_mm=0.0),
    )
    assert prepared.to_geometry().area == pytest.approx(100.0, abs=1e-9)

    point_contact = Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        holes=[[(5.0, 0.0), (6.0, 1.0), (4.0, 1.0)]],
    )
    separated = prepare_vector_run_group(
        [point_contact],
        scale_mm_per_svg_unit=1.0,
        policy=VectorLayerGeometryPolicy(simplify_tolerance_mm=0.0),
    )
    assert separated.stats.separated_contact_group_count == 1
    assert separated.to_geometry().area == pytest.approx(
        point_contact.area,
        abs=1e-9,
    )


def test_invalid_scale_and_partial_empty_input_fail_before_geometry_is_returned() -> None:
    with pytest.raises(ValueError, match="positive finite"):
        prepare_vector_run_group([box(0.0, 0.0, 1.0, 1.0)], scale_mm_per_svg_unit=0.0)

    with pytest.raises(ValueError, match="polygonal geometry"):
        prepare_vector_run_group(
            [box(0.0, 0.0, 1.0, 1.0), LineString([(0.0, 0.0), (1.0, 1.0)])],
            scale_mm_per_svg_unit=1.0,
        )


def test_zero_area_repair_residue_does_not_hide_the_printable_polygon() -> None:
    source = Polygon(
        [
            (0.0, 0.0),
            (2.0, 0.0),
            (2.0, 2.0),
            (1.0, 2.0),
            (1.0, 3.0),
            (1.0, 2.0),
            (0.0, 2.0),
            (0.0, 0.0),
        ]
    )
    assert not source.is_valid

    prepared = prepare_vector_run_group(
        [source],
        scale_mm_per_svg_unit=1.0,
        policy=VectorLayerGeometryPolicy(simplify_tolerance_mm=0.0),
    )
    mesh = extrude_prepared_vector_run_group(
        prepared,
        height_mm=0.2,
        z_offset_mm=0.0,
    )

    assert prepared.stats.output_component_count == 1
    assert prepared.stats.output_area_mm2 == pytest.approx(4.0, abs=1e-9)
    assert mesh.is_watertight
    assert np.all(_edge_incidence_counts(mesh) == 2)


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


def test_large_group_preserves_original_instead_of_running_quadratic_fidelity_check() -> None:
    source = Point(0.0, 0.0).buffer(10.0, quad_segs=600)

    prepared = prepare_vector_run_group(
        [source],
        scale_mm_per_svg_unit=1.0,
    )

    assert prepared.stats.input_coordinate_count == 2400
    assert prepared.stats.simplified_group_count == 0
    assert prepared.stats.restored_group_count == 0
    assert prepared.stats.output_coordinate_count > 1000


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


def test_simple_cap_rejects_overlapping_triangles_with_matching_area() -> None:
    vertices = np.asarray(
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        dtype=np.float64,
    )
    overlapping_faces = np.asarray(
        [(0, 1, 2), (0, 1, 3)],
        dtype=np.int64,
    )

    with pytest.raises(ValueError, match="boundary differs from its ring"):
        vector_layer_geometry._validate_cap_indices(
            vertices,
            overlapping_faces,
            np.asarray([4], dtype=np.int64),
            expected_area_mm2=1.0,
        )


@pytest.mark.parametrize(
    "source",
    [
        Polygon(
            [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
            holes=[[(5.0, 0.0), (6.0, 1.0), (4.0, 1.0)]],
        ),
        Polygon(
            [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
            holes=[
                [(2.0, 2.0), (5.0, 5.0), (2.0, 8.0)],
                [(8.0, 2.0), (8.0, 8.0), (5.0, 5.0)],
            ],
        ),
    ],
    ids=("hole_touches_shell", "holes_touch_each_other"),
)
def test_point_touching_rings_are_separated_before_cap_triangulation(source) -> None:
    """Valid OGC point contacts must remain printable in writer coordinates."""

    prepared = prepare_vector_run_group(
        [source],
        scale_mm_per_svg_unit=1.0,
        policy=VectorLayerGeometryPolicy(simplify_tolerance_mm=0.0),
    )
    mesh = extrude_prepared_vector_run_group(
        prepared,
        height_mm=0.2,
        z_offset_mm=0.0,
    )

    polygon = prepared.polygons[0]
    ring_coordinate_sets = [
        {tuple(point) for point in polygon.exterior_units.tolist()},
        *(
            {tuple(point) for point in hole.tolist()}
            for hole in polygon.hole_units
        ),
    ]
    assert all(
        first.isdisjoint(second)
        for first_index, first in enumerate(ring_coordinate_sets)
        for second in ring_coordinate_sets[first_index + 1 :]
    )
    assert prepared.stats.separated_contact_group_count == 1
    assert prepared.stats.output_area_mm2 == pytest.approx(source.area, abs=1e-9)
    assert mesh.is_watertight
    assert mesh.is_winding_consistent
    assert np.all(_edge_incidence_counts(mesh) == 2)
    assert abs(float(mesh.volume)) == pytest.approx(source.area * 0.2, abs=1e-8)


def test_ring_separation_cannot_reintroduce_contact_with_an_independent_island() -> None:
    """Finalize touching rings before moving an island inside the affected hole."""

    body = Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        holes=[
            [(2.0, 2.0), (6.0, 2.0), (6.0, 6.0), (2.0, 6.0)],
            [(2.0, 4.0), (1.5, 3.8), (1.5, 4.2)],
        ],
    )
    island = Polygon([(2.0, 3.0), (2.5, 2.9), (2.5, 3.1)])

    prepared = prepare_vector_run_group(
        [body, island],
        scale_mm_per_svg_unit=1.0,
        policy=VectorLayerGeometryPolicy(simplify_tolerance_mm=0.0),
    )
    geometry = prepared.to_geometry()
    mesh = extrude_prepared_vector_run_group(
        prepared,
        height_mm=0.2,
        z_offset_mm=0.0,
    )

    assert geometry.is_valid
    assert not vector_layer_geometry._has_cross_polygon_contact(geometry)
    assert all(
        not vector_layer_geometry._polygon_has_ring_contact(part)
        for part in vector_layer_geometry._polygon_parts(geometry)
    )
    assert prepared.stats.output_area_mm2 == pytest.approx(
        body.area + island.area,
        abs=1e-9,
    )
    assert mesh.is_watertight
    assert mesh.is_winding_consistent
    assert np.all(_edge_incidence_counts(mesh) == 2)


def test_contact_shifted_micro_island_keeps_its_source_owner() -> None:
    body = Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        holes=[
            [(2.0, 2.0), (6.0, 2.0), (6.0, 6.0), (2.0, 6.0)],
            [(2.0, 4.0), (1.5, 3.8), (1.5, 4.2)],
        ],
    )
    island = Polygon(
        [(2.0, 3.0), (2.0001, 2.998), (2.0001, 3.002)]
    )

    prepared = prepare_vector_run_group(
        [body, island],
        scale_mm_per_svg_unit=1.0,
        policy=VectorLayerGeometryPolicy(simplify_tolerance_mm=0.0),
    )
    prepared_by_area = sorted(
        prepared.polygons,
        key=lambda polygon: polygon.to_geometry(prepared.grid_mm).area,
    )

    assert prepared_by_area[0].source_indices == (1,)
    assert prepared.stats.output_component_count == 2
    assert prepared.stats.output_hole_count == 2


def test_ring_contact_separation_queries_only_spatial_neighbors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holes = [[(50.0, 0.0), (50.1, 0.2), (49.9, 0.2)]]
    holes.extend(
        [
            (x, y),
            (x + 0.1, y),
            (x + 0.1, y + 0.1),
            (x, y + 0.1),
        ]
        for x in range(5, 95, 9)
        for y in range(5, 95, 9)
    )
    source = Polygon(
        [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        holes=holes,
    )
    real_intersects = BaseGeometry.intersects
    intersects_calls = 0

    def counted_intersects(self, other):
        nonlocal intersects_calls
        intersects_calls += 1
        return real_intersects(self, other)

    monkeypatch.setattr(BaseGeometry, "intersects", counted_intersects)

    separated, changed = vector_layer_geometry._separate_polygon_ring_contacts(
        source,
        grid_mm=0.0001,
    )

    assert changed is True
    assert separated.is_valid
    assert not vector_layer_geometry._polygon_has_ring_contact(separated)
    assert intersects_calls < 1000


def test_ring_contact_candidates_are_rejected_in_integer_writer_grid() -> None:
    epsilon = 1e-15
    moved_hole = [
        (-0.0001 - epsilon, -epsilon),
        (0.0217 - epsilon, 0.0331 - epsilon),
        (0.0218 - epsilon, 0.0331 - epsilon),
    ]
    touching_hole = [
        (-0.0001 - epsilon, -epsilon),
        (-0.0004 - epsilon, -0.0002 - epsilon),
        (-0.0004 - epsilon, 0.0002 - epsilon),
    ]
    near_hole = [
        (0.0224, 0.0335),
        (0.0218, 0.0331),
        (0.0220, 0.0333),
    ]
    source = Polygon(
        [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)],
        holes=[moved_hole, touching_hole, near_hole],
    )

    separated, changed = vector_layer_geometry._separate_polygon_ring_contacts(
        source,
        grid_mm=0.0001,
    )
    writer_rings = [
        vector_layer_geometry._ring_units(
            separated.exterior.coords,
            grid_mm=0.0001,
        ),
        *(
            vector_layer_geometry._ring_units(ring.coords, grid_mm=0.0001)
            for ring in separated.interiors
        ),
    ]
    writer_polygon = Polygon(
        writer_rings[0].astype(np.float64) * 0.0001,
        [ring.astype(np.float64) * 0.0001 for ring in writer_rings[1:]],
    )

    assert changed is True
    assert writer_polygon.is_valid
    assert not vector_layer_geometry._polygon_has_ring_contact(writer_polygon)


def test_off_grid_noding_intersection_is_resnapped_before_integer_rings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rational intersections from grid-aligned edges must be snapped once more."""

    source = Polygon(
        [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)],
        holes=[
            [
                (0.0, 0.0),
                (0.0147, 0.0567),
                (0.0297, 0.0979),
                (-0.02851931530323, -0.0620071524363),
            ]
        ],
    )
    assert source.is_valid
    monkeypatch.setattr(
        vector_layer_geometry,
        "_node_group_once",
        lambda _snapped: source,
    )

    prepared = prepare_vector_run_group(
        [source],
        scale_mm_per_svg_unit=1.0,
        policy=VectorLayerGeometryPolicy(simplify_tolerance_mm=0.0),
    )
    mesh = extrude_prepared_vector_run_group(
        prepared,
        height_mm=0.2,
        z_offset_mm=0.0,
    )

    assert prepared.to_geometry().is_valid
    assert prepared.stats.output_area_mm2 == pytest.approx(
        source.area,
        abs=VectorLayerGeometryPolicy().coverage_absolute_tolerance_mm2,
    )
    assert mesh.is_watertight
    assert np.all(_edge_incidence_counts(mesh) == 2)


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


def test_best_effort_spatial_groups_keep_touching_sources_together() -> None:
    result = prepare_vector_spatial_groups_best_effort(
        [
            box(0.0, 0.0, 10.0, 10.0),
            box(10.0, 0.0, 20.0, 10.0),
            box(100.0, 0.0, 105.0, 5.0),
        ],
        scale_mm_per_svg_unit=1.0,
    )

    assert len(result.groups) == 2
    assert sorted(group.stats.source_polygon_count for group in result.groups) == [1, 2]
    assert result.failed_group_count == 0
    assert result.failed_part_count == 0


def test_best_effort_spatial_groups_skip_only_one_remote_failed_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_prepare = vector_layer_geometry.prepare_vector_run_group

    def prepare_or_fail(geometries, **kwargs):
        if min(float(geometry.bounds[0]) for geometry in geometries) > 50.0:
            raise ValueError("remote bad island")
        return real_prepare(geometries, **kwargs)

    monkeypatch.setattr(
        vector_layer_geometry,
        "prepare_vector_run_group",
        prepare_or_fail,
    )
    result = prepare_vector_spatial_groups_best_effort(
        [
            box(0.0, 0.0, 10.0, 10.0),
            box(100.0, 0.0, 105.0, 5.0),
        ],
        scale_mm_per_svg_unit=1.0,
    )

    assert len(result.groups) == 1
    assert result.prepared_part_count == 1
    assert result.failed_group_count == 1
    assert result.failed_part_count == 1
    assert result.failure_types == (("ValueError", 1),)


def test_best_effort_spatial_groups_do_not_swallow_memory_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        vector_layer_geometry,
        "prepare_vector_run_group",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MemoryError()),
    )

    with pytest.raises(MemoryError):
        prepare_vector_spatial_groups_best_effort(
            [box(0.0, 0.0, 1.0, 1.0)],
            scale_mm_per_svg_unit=1.0,
        )
