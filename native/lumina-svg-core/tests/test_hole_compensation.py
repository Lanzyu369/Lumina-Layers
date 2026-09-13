"""Physical-mm contracts for the optional source-SVG hole utility."""

from __future__ import annotations

import gc
import importlib
import importlib.util

import numpy as np
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union


def _find_holes(rings, area=0.5, width=0.0):
    module_name = "lumina_svg_core._lumina_svg_compensation"
    assert importlib.util.find_spec(module_name) is not None, (
        "The separate SVG compensation extension must be built"
    )
    return importlib.import_module(module_name).find_holes_mm(rings, area, width)


def _rings(*polygons: Polygon) -> list[np.ndarray]:
    rings = []
    for polygon in polygons:
        normalized = orient(polygon, sign=1.0)
        rings.append(np.asarray(normalized.exterior.coords, dtype=np.float64))
        rings.extend(
            np.asarray(interior.coords, dtype=np.float64)
            for interior in normalized.interiors
        )
    return rings


def _geometry(parts) -> MultiPolygon:
    return MultiPolygon([Polygon(shell, holes) for shell, holes in parts])


def test_global_union_fills_hole_enclosed_by_four_independent_regions():
    sides = [
        box(0, 0, 2, 0.8),
        box(0, 1.2, 2, 2),
        box(0, 0.8, 0.8, 1.2),
        box(1.2, 0.8, 2, 1.2),
    ]

    holes, coverage = _find_holes(_rings(*sides))

    assert len(holes) == 1
    assert _geometry(holes).equals(box(0.8, 0.8, 1.2, 1.2))
    assert _geometry(coverage).equals(box(0, 0, 2, 2))


def test_large_hole_and_separate_outer_shell_remain_unchanged():
    frame = Polygon(box(0, 0, 5, 5).exterior, [box(1, 1, 3, 3).exterior])
    separate = box(7, 0, 9, 2)

    holes, coverage = _find_holes(_rings(frame, separate))

    assert holes == []
    assert _geometry(coverage).equals(MultiPolygon([frame, separate]))


def test_selected_void_excludes_nested_painted_island():
    frame = Polygon(box(0, 0, 2, 2).exterior, [box(0.6, 0.6, 1.4, 1.4).exterior])
    island = box(0.8, 0.8, 1.2, 1.2)

    holes, coverage = _find_holes(_rings(frame, island))

    assert len(holes) == 1
    assert len(holes[0][1]) == 1
    assert _geometry(holes).area == pytest.approx(0.48)
    assert not _geometry(holes).covers(Point(1, 1))
    assert _geometry(coverage).equals(box(0, 0, 2, 2))
    assert _geometry(coverage).is_valid


def test_filled_ancestor_preserves_large_hole_inside_nested_island():
    frame = Polygon(box(0, 0, 6, 6).exterior, [box(1, 1, 5, 5).exterior])
    island = Polygon(box(1.1, 1.1, 4.9, 4.9).exterior, [box(2, 2, 4, 4).exterior])
    expected = Polygon(box(0, 0, 6, 6).exterior, [box(2, 2, 4, 4).exterior])

    holes, coverage = _find_holes(_rings(frame, island), area=0.5, width=0.11)

    assert len(holes) == 1
    assert _geometry(holes).area == pytest.approx(1.56)
    assert _geometry(coverage).equals(expected)
    assert _geometry(coverage).is_valid


@pytest.mark.parametrize(
    ("area", "width", "filled"),
    [(0.5, 0.0, True), (0.0, 0.1, True), (0.49, 0.0, False), (0.0, 0.0, False)],
)
def test_area_and_narrow_slit_criteria_are_independent(area, width, filled):
    frame = Polygon(box(0, 0, 7, 2).exterior, [box(1, 0.95, 6, 1.05).exterior])

    holes, coverage = _find_holes(_rings(frame), area=area, width=width)

    assert bool(holes) is filled
    assert _geometry(coverage).equals(box(0, 0, 7, 2) if filled else frame)


def test_compensation_does_not_close_gap_connected_to_exterior():
    sides = [box(0, 0, 2, 0.8), box(0, 1.2, 2, 2), box(0, 0.8, 0.8, 1.2)]

    holes, coverage = _find_holes(_rings(*sides), area=10, width=10)

    assert holes == []
    assert not _geometry(coverage).covers(Point(1, 1))
    assert _geometry(coverage).area == pytest.approx(sum(side.area for side in sides))


def test_result_arrays_own_memory_after_inputs_and_other_results_are_released():
    frame = Polygon(box(0, 0, 2, 2).exterior, [box(0.8, 0.8, 1.2, 1.2).exterior])
    inputs = _rings(frame)
    holes, coverage = _find_holes(inputs)
    expected_hole = np.array(holes[0][0], copy=True)
    for ring in inputs:
        ring[:] = 999
    del inputs, frame
    gc.collect()

    for shell, interiors in holes + coverage:
        for coordinates in [shell, *interiors]:
            assert coordinates.dtype == np.float64
            assert coordinates.flags.owndata
    np.testing.assert_array_equal(holes[0][0], expected_hole)
    assert _geometry(coverage).equals(box(0, 0, 2, 2))


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -0.1])
def test_invalid_settings_rejected_before_geometry_work(invalid):
    with pytest.raises(ValueError, match="finite.*nonnegative"):
        _find_holes([], area=invalid)
    with pytest.raises(ValueError, match="finite.*nonnegative"):
        _find_holes([], width=invalid)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), 1e20])
def test_unrepresentable_coordinates_rejected(invalid):
    coordinates = np.array([[0, 0], [1, 0], [invalid, 1]], dtype=np.float64)
    with pytest.raises(ValueError, match="coordinate"):
        _find_holes([coordinates])


def test_empty_inputs_have_no_holes_or_coverage():
    assert _find_holes([]) == ([], [])


def _point_touch_regions() -> list[Polygon]:
    return [
        Polygon(
            [
                (0.4, 1), (0.4, 1.4), (0.6, 1.4), (0.6, 1.2),
                (0.8, 1.2), (0.8, 1.6), (1.4, 1.6), (1.4, 1),
            ],
            [[(1, 1.2), (1.2, 1.2), (1.2, 1.4), (1, 1.4)]],
        ),
        box(0.6, 1.4, 0.8, 1.6),
    ]


@pytest.mark.parametrize("area_threshold", [0, 0.5])
def test_point_touch_hole_is_simple_and_selected_after_global_union(area_threshold):
    sources = _point_touch_regions()
    original = unary_union(sources)
    assert all(source.is_valid for source in sources)
    assert original.is_valid

    holes, coverage = _find_holes(_rings(*sources), area=area_threshold)

    assert _geometry(coverage).is_valid
    assert all(Polygon(shell, interiors).is_valid for shell, interiors in holes)
    if area_threshold:
        expected_holes = MultiPolygon([
            box(0.6, 1.2, 0.8, 1.4), box(1, 1.2, 1.2, 1.4),
        ])
        assert len(holes) == 2
        assert _geometry(holes).equals(expected_holes)
        assert _geometry(coverage).equals(Polygon(original.exterior))
    else:
        assert holes == []
        assert _geometry(coverage).equals(original)


def test_point_touch_shells_remain_separate_valid_polygons():
    sources = [box(0, 0, 1, 1), box(1, 1, 2, 2)]

    holes, coverage = _find_holes(_rings(*sources))

    assert holes == []
    assert len(coverage) == 2
    assert _geometry(coverage).is_valid
    assert _geometry(coverage).equals(MultiPolygon(sources))


def test_point_touch_void_preserves_painted_islands_when_filled():
    void = unary_union(_point_touch_regions())
    frame = Polygon(box(0, 0, 2, 2).exterior, [void.exterior])
    islands = [Polygon(interior) for interior in void.interiors]
    sources = [frame, *islands]
    assert MultiPolygon(sources).is_valid

    holes, coverage = _find_holes(_rings(*sources))

    assert len(holes) == 1
    assert _geometry(holes).is_valid
    assert _geometry(holes).equals(void)
    assert _geometry(holes).intersection(MultiPolygon(islands)).area == 0
    assert _geometry(coverage).is_valid
    assert _geometry(coverage).equals(box(0, 0, 2, 2))


def test_near_contacts_created_by_integer_union_keep_valid_coverage():
    # A small crop from the real vectorized fixture; all four source faces are
    # valid, while integer union can create nested or crossing boundary cycles.
    sources = [
        Polygon([
            (79.50120368987571, 1.0420379019068513),
            (79.45988820785882, 1.0134042251026996),
            (79.45988820785882, 0.9937005643098067),
            (79.55522943428667, 0.9937005643098067),
            (79.55522943428667, 0.9937645244652271),
            (79.50756634158309, 1.0413668877908178),
        ]),
        Polygon([
            (79.45988820785882, 1.0889842729727417),
            (79.55522943428667, 0.9937645244652265),
            (79.55522943428667, 1.0890417907376466),
            (79.45988820785882, 1.0890417907376466),
        ]),
        Polygon([
            (79.4706805568747, 1.0782056749034838),
            (79.45988820785882, 1.0889842729727408),
            (79.45988820785882, 1.0134042251026996),
            (79.50120368987571, 1.0420379019068513),
            (79.50120368987571, 1.0420379019068515),
            (79.50120368987571, 1.042037901906852),
            (79.47795097550575, 1.0444901655692187),
        ]),
        Polygon([
            (79.4706805568747, 1.0782056749034838),
            (79.47795097550575, 1.0444901655692187),
            (79.50756634158309, 1.0413668877908178),
            (79.50756634158309, 1.041366887790818),
            (79.50473784465875, 1.0441917808185337),
        ]),
    ]
    assert all(source.is_valid for source in sources)
    expected = unary_union(sources)
    assert expected.is_valid

    holes, coverage = _find_holes(_rings(*sources), area=0, width=0)

    assert holes == []
    assert _geometry(coverage).is_valid
    assert _geometry(coverage).area == pytest.approx(expected.area, abs=1e-6)


@pytest.mark.parametrize("area_threshold", [0, 0.5, 1])
def test_touching_island_splits_void_before_each_component_is_selected(area_threshold):
    frame = Polygon(box(-1, -1, 2, 2).exterior, [box(0, 0, 1, 1).exterior])
    island = Polygon([(0.3, 0), (0.5, 0.5), (0.3, 1), (0.1, 0.5)])
    left_void = Polygon([(0, 0), (0.3, 0), (0.1, 0.5), (0.3, 1), (0, 1)])
    right_void = Polygon([(0.3, 0), (1, 0), (1, 1), (0.3, 1), (0.5, 0.5)])
    original = MultiPolygon([frame, island])
    assert original.is_valid

    holes, coverage = _find_holes(_rings(frame, island), area=area_threshold)

    patches = _geometry(holes)
    filled = _geometry(coverage)
    assert patches.is_valid
    assert filled.is_valid
    assert patches.intersection(island).area == 0
    if area_threshold == 0:
        assert holes == []
        assert filled.equals(original)
    elif area_threshold == 0.5:
        assert len(holes) == 1
        assert patches.equals(left_void)
        assert patches.area == pytest.approx(0.2)
        assert filled.equals(Polygon(box(-1, -1, 2, 2).exterior, [right_void.exterior]))
    else:
        assert len(holes) == 2
        assert patches.area == pytest.approx(0.8)
        assert patches.equals(MultiPolygon([left_void, right_void]))
        assert filled.equals(box(-1, -1, 2, 2))


@pytest.mark.parametrize("area_threshold", [0, 1e-12])
def test_retained_near_contacts_form_closed_coverage_at_tiny_thresholds(area_threshold):
    # Three triangles minimized from a real SVG union's near-contact failure.
    sources = [
        Polygon([
            (141.9368570948912, 133.35523),
            (141.87892356611994, 132.88371161494777),
            (141.85372595422868, 132.8228791985805),
        ]),
        Polygon([
            (141.86712760623115, 132.85523364860308),
            (141.86994138560345, 132.8620267129252),
            (141.8689705949958, 132.85537456742856),
        ]),
        Polygon([
            (141.88216612634926, 132.99737283580393),
            (142.02091304522338, 133.15428622046218),
            (142.17001770221452, 133.26941295110834),
        ]),
    ]
    assert all(source.is_valid for source in sources)
    expected = unary_union(sources)
    assert expected.is_valid

    holes, coverage = _find_holes(_rings(*sources), area=area_threshold)

    assert _geometry(coverage).is_valid
    assert _geometry(coverage).area == pytest.approx(expected.area, abs=2e-6)
    assert all(Polygon(shell, interiors).is_valid for shell, interiors in holes)
