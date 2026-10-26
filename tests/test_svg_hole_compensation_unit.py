"""Source SVG compensation retains paint identity and uses physical units."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from enum import Enum

import pytest
from shapely.affinity import scale
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
)
from shapely.ops import unary_union


def _compensate(regions, **kwargs):
    module_name = "core.svg_hole_compensation"
    assert importlib.util.find_spec(module_name) is not None, (
        "The source SVG compensation adapter must be implemented"
    )
    return importlib.import_module(module_name).compensate_svg_regions(
        regions, **kwargs
    )


def _frame_regions() -> list[dict]:
    geometries = [
        box(0, 0, 2, 0.8),
        box(0, 1.2, 2, 2),
        box(0, 0.8, 0.8, 1.2),
        box(1.2, 0.8, 2, 1.2),
    ]
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    return [
        {
            "geometry": geometry,
            "color": color,
            "rgba": (*color, 203),
            "rgba_f64": tuple(channel / 255 for channel in (*color, 203)),
            "draw_order": index,
            "native_paint_id": (index + 10, index),
            "source_kind": "fill",
            "recipe": ["must-not-copy"],
        }
        for index, (geometry, color) in enumerate(zip(geometries, colors))
    ]


def _silhouette() -> Polygon:
    return Polygon(box(0, 0, 2, 2).exterior, [box(0.8, 0.8, 1.2, 1.2).exterior])


def test_cross_color_hole_is_filled_with_derived_nearest_color_patch():
    regions = _frame_regions()
    originals = [dict(region) for region in regions]

    result = _compensate(regions, silhouette=_silhouette(), scale_factor=1)

    assert result.filled_holes == 1
    assert result.added_area_mm2 == pytest.approx(0.16)
    assert result.silhouette.equals(box(0, 0, 2, 2))
    assert result.elapsed_seconds >= 0
    for index, region in enumerate(regions):
        assert result.regions[index] is region
        assert region == originals[index]
        assert region["geometry"] is originals[index]["geometry"]
    assert len(result.patches) == 1
    patch = result.patches[0]
    assert result.regions[-1] is patch
    assert patch["geometry"].equals(box(0.8, 0.8, 1.2, 1.2))
    assert patch["color"] is regions[0]["color"]
    assert patch["rgba"] is regions[0]["rgba"]
    assert patch["rgba_f64"] is regions[0]["rgba_f64"]
    assert patch["source_kind"] == "compensation"
    assert patch["compensation_source"]["source_list_index"] == 0
    assert (
        patch["compensation_source"]["native_paint_id"]
        == regions[0]["native_paint_id"]
    )
    assert "native_paint_id" not in patch
    assert "recipe" not in patch
    assert result.unprintable_fragments == []


def test_equal_distance_assignment_uses_draw_order_then_source_index():
    regions = _frame_regions()
    for region in regions:
        region["draw_order"] = 10
    regions[1]["draw_order"] = 3
    regions[2]["draw_order"] = 3

    result = _compensate(regions, silhouette=_silhouette(), scale_factor=1)

    assert result.patches[0]["color"] is regions[1]["color"]
    assert result.patches[0]["compensation_source"]["source_list_index"] == 1


def test_nearest_geometry_wins_over_draw_order():
    regions = _frame_regions()
    regions[0]["geometry"] = box(0, 0, 2, 0.7)
    regions[2]["geometry"] = box(0, 0.7, 0.8, 1.2)
    regions[3]["geometry"] = box(1.2, 0.7, 2, 1.2)
    original_silhouette = Polygon(
        box(0, 0, 2, 2).exterior, [box(0.8, 0.7, 1.2, 1.2).exterior]
    )

    result = _compensate(regions, silhouette=original_silhouette, scale_factor=1)

    assert result.patches[0]["color"] is regions[2]["color"]


@pytest.mark.parametrize("source_units_per_mm", [0.5, 7, 100])
def test_physical_selection_and_patch_area_are_scale_invariant(source_units_per_mm):
    regions = _frame_regions()
    for region in regions:
        region["geometry"] = scale(
            region["geometry"], source_units_per_mm, source_units_per_mm, origin=(0, 0)
        )
    silhouette = scale(
        _silhouette(), source_units_per_mm, source_units_per_mm, origin=(0, 0)
    )

    result = _compensate(
        regions, silhouette=silhouette, scale_factor=1 / source_units_per_mm
    )

    assert result.filled_holes == 1
    assert result.added_area_mm2 == pytest.approx(0.16)
    assert result.patches[0]["geometry"].area == pytest.approx(
        0.16 * source_units_per_mm**2
    )
    assert result.silhouette.equals(
        box(0, 0, 2 * source_units_per_mm, 2 * source_units_per_mm)
    )


def test_large_hole_preserves_original_silhouette_identity():
    silhouette = Polygon(box(0, 0, 5, 5).exterior, [box(1, 1, 3, 3).exterior])
    regions = [{"geometry": silhouette, "color": (123, 45, 6)}]

    result = _compensate(regions, silhouette=silhouette, scale_factor=1)

    assert result.filled_holes == 0
    assert result.patches == []
    assert result.added_area_mm2 == 0
    assert result.regions is regions
    assert result.silhouette is silhouette


def test_zero_thresholds_return_inputs_without_loading_native_extension(monkeypatch):
    regions = _frame_regions()
    silhouette = _silhouette()
    monkeypatch.setitem(sys.modules, "lumina_svg_core._lumina_svg_compensation", None)

    result = _compensate(
        regions,
        silhouette=silhouette,
        scale_factor=1,
        max_hole_area_mm2=0,
        max_hole_width_mm=0,
    )

    assert result.regions is regions
    assert result.silhouette is silhouette
    assert result.patches == []
    assert result.filled_holes == 0


def test_zero_thresholds_report_nonarea_fragments_without_loading_native(monkeypatch):
    painted = {"geometry": box(0, 0, 1, 1), "color": (12, 34, 56)}
    second = box(2, 0, 3, 1)
    collapsed = Polygon([(4, 0), (5, 0), (6, 0)])
    mixed = {
        "geometry": MultiPolygon([second, collapsed]),
        "color": (78, 90, 12),
    }
    regions = [
        painted, mixed,
        {"geometry": LineString([(7, 0), (8, 1)]), "color": (1, 2, 3)},
        {"geometry": Point(9, 0), "color": (4, 5, 6)},
    ]
    original_mixed = mixed["geometry"]
    silhouette = MultiPolygon([painted["geometry"], second])
    monkeypatch.setitem(sys.modules, "lumina_svg_core._lumina_svg_compensation", None)

    result = _compensate(
        regions, silhouette=silhouette, scale_factor=1,
        max_hole_area_mm2=0, max_hole_width_mm=0,
    )

    assert len(result.regions) == 2
    assert result.regions[0] is painted
    assert result.regions[1] is not mixed
    assert result.regions[1]["geometry"].equals(second)
    assert result.regions[1]["color"] is mixed["color"]
    assert mixed["geometry"] is original_mixed
    assert result.silhouette is silhouette
    assert result.patches == []
    assert result.filled_holes == 0
    assert {(item["source_list_index"], item["reason"])
            for item in result.unprintable_fragments} == {
        (1, "collapsed_area"), (2, "non_polygon_geometry"),
        (3, "non_polygon_geometry"),
    }


def test_enabled_compensation_with_missing_extension_is_actionable(monkeypatch):
    monkeypatch.setitem(sys.modules, "lumina_svg_core._lumina_svg_compensation", None)
    with pytest.raises(ImportError, match="lumina-svg-core.*compensation"):
        _compensate(_frame_regions(), silhouette=_silhouette(), scale_factor=1)


def test_nested_painted_island_retains_exact_region_and_color():
    frame = Polygon(box(0, 0, 2, 2).exterior, [box(0.6, 0.6, 1.4, 1.4).exterior])
    island = box(0.8, 0.8, 1.2, 1.2)
    regions = [
        {"geometry": frame, "color": (12, 34, 56)},
        {"geometry": island, "color": (78, 90, 12)},
    ]

    result = _compensate(
        regions, silhouette=MultiPolygon([frame, island]), scale_factor=1
    )

    assert result.regions[1] is regions[1]
    assert result.patches[0]["geometry"].intersection(island).area == 0
    assert result.added_area_mm2 == pytest.approx(0.48)
    assert result.silhouette.equals(box(0, 0, 2, 2))


def test_mixed_geometry_preserves_polygons_and_reports_non_polygon_fragments():
    regions = _frame_regions()
    original = regions[0]
    polygon = original["geometry"]
    original["geometry"] = GeometryCollection([polygon, LineString([(3, 3), (4, 4)])])
    regions.extend([
        {"geometry": Point(10, 10), "color": (9, 9, 9)},
        {"geometry": Polygon(), "color": (8, 8, 8)},
    ])

    result = _compensate(regions, silhouette=_silhouette(), scale_factor=1)

    assert original["geometry"].geom_type == "GeometryCollection"
    assert result.regions[0] is not original
    assert result.regions[0]["geometry"].equals(polygon)
    assert result.regions[0]["color"] is original["color"]
    assert result.filled_holes == 1
    assert all(
        region["geometry"].geom_type in {"Polygon", "MultiPolygon"}
        for region in result.regions
    )
    assert {
        item["source_list_index"] for item in result.unprintable_fragments
    } == {0, 4, 5}
    assert {
        item["geometry_type"] for item in result.unprintable_fragments
    } == {"LineString", "Point", "Polygon"}
    assert all(item["reason"] for item in result.unprintable_fragments)


def test_multipolygon_keeps_every_positive_component_and_reports_collapsed_area():
    regions = _frame_regions()
    original = regions[0]
    painted = original["geometry"]
    separate = box(3, 0, 4, 1)
    collapsed = Polygon([(5, 0), (6, 0), (7, 0), (5, 0)])
    geometry = MultiPolygon([painted, separate, collapsed])
    original["geometry"] = geometry
    original_wkb = geometry.wkb

    result = _compensate(regions, silhouette=_silhouette(), scale_factor=1)

    assert original["geometry"] is geometry
    assert geometry.wkb == original_wkb
    assert result.regions[0] is not original
    assert result.regions[0]["geometry"].equals(MultiPolygon([painted, separate]))
    assert all(part.area > 0 for part in result.regions[0]["geometry"].geoms)
    assert result.regions[0]["color"] is original["color"]
    assert result.filled_holes == 1
    assert len(result.unprintable_fragments) == 1
    fragment = result.unprintable_fragments[0]
    assert fragment["source_list_index"] == 0
    assert fragment["geometry_type"] == "Polygon"
    assert fragment["reason"] == "collapsed_area"
    assert fragment["geometry"].area == 0


def test_standalone_collapsed_polygon_is_reported_as_collapsed_area():
    regions = _frame_regions()
    collapsed = {
        "geometry": Polygon([(3, 0), (4, 0), (5, 0)]),
        "color": (9, 8, 7),
    }
    regions.append(collapsed)

    result = _compensate(regions, silhouette=_silhouette(), scale_factor=1)

    assert all(region is not collapsed for region in result.regions)
    assert result.filled_holes == 1
    assert len(result.unprintable_fragments) == 1
    fragment = result.unprintable_fragments[0]
    assert fragment["source_list_index"] == 4
    assert fragment["geometry_type"] == "Polygon"
    assert fragment["reason"] == "collapsed_area"
    assert fragment["geometry"] is collapsed["geometry"]


def test_positive_multipolygon_preserves_original_object_identity():
    regions = _frame_regions()
    original = regions[0]
    original["geometry"] = MultiPolygon([original["geometry"], box(3, 0, 4, 1)])

    result = _compensate(regions, silhouette=_silhouette(), scale_factor=1)

    assert result.regions[0] is original
    assert result.unprintable_fragments == []


def test_point_touch_holes_produce_valid_patches_and_coverage():
    painted = Polygon(
        [
            (0.4, 1), (0.4, 1.4), (0.6, 1.4), (0.6, 1.2),
            (0.8, 1.2), (0.8, 1.6), (1.4, 1.6), (1.4, 1),
        ],
        [[(1, 1.2), (1.2, 1.2), (1.2, 1.4), (1, 1.4)]],
    )
    regions = [
        {"geometry": painted, "color": (255, 0, 0)},
        {"geometry": box(0.6, 1.4, 0.8, 1.6), "color": (0, 255, 0)},
    ]
    silhouette = unary_union([region["geometry"] for region in regions])
    assert silhouette.is_valid

    result = _compensate(regions, silhouette=silhouette, scale_factor=1)

    assert result.filled_holes == 2
    assert result.added_area_mm2 == pytest.approx(0.08)
    assert all(patch["geometry"].is_valid for patch in result.patches)
    assert result.silhouette.is_valid
    assert result.silhouette.equals(Polygon(silhouette.exterior))
    assert result.regions[0] is regions[0]
    assert result.regions[1] is regions[1]


def test_touching_island_selects_small_component_in_physical_units():
    frame = Polygon(box(-10, -10, 20, 20).exterior, [box(0, 0, 10, 10).exterior])
    island = Polygon([(3, 0), (5, 5), (3, 10), (1, 5)])
    regions = [
        {"geometry": frame, "color": (255, 0, 0)},
        {"geometry": island, "color": (0, 255, 0)},
    ]
    silhouette = MultiPolygon([frame, island])

    result = _compensate(
        regions, silhouette=silhouette, scale_factor=0.1, max_hole_width_mm=0,
    )

    assert result.filled_holes == 1
    assert result.added_area_mm2 == pytest.approx(0.2)
    patch = result.patches[0]
    expected = Polygon([(0, 0), (3, 0), (1, 5), (3, 10), (0, 10)])
    assert patch["geometry"].symmetric_difference(expected).area == pytest.approx(0, abs=1e-12)
    assert patch["geometry"].is_valid
    assert patch["geometry"].intersection(island).area == 0
    source = regions[patch["compensation_source"]["source_list_index"]]
    assert patch["color"] is source["color"]
    assert result.silhouette.is_valid
    assert result.regions[0] is regions[0]
    assert result.regions[1] is regions[1]


@pytest.mark.parametrize(
    "settings",
    [
        {"scale_factor": 0},
        {"scale_factor": float("nan")},
        {"max_hole_area_mm2": -1},
        {"max_hole_width_mm": float("inf")},
    ],
)
def test_invalid_physical_settings_are_rejected(settings):
    parameters = {"scale_factor": 1, **settings}
    with pytest.raises(ValueError, match="finite"):
        _compensate(_frame_regions(), silhouette=_silhouette(), **parameters)


class _ModelingMode(Enum):
    VECTOR = "vector"
    HIGH_FIDELITY = "high-fidelity"


@pytest.mark.parametrize(
    ("enabled", "image_path", "modeling_mode", "accepted"),
    [
        (False, "image.png", "high-fidelity", True),
        (True, "image.svg", "vector", True),
        (True, "image.SVG", _ModelingMode.VECTOR, True),
        (True, "image.png", "vector", False),
        (True, "image.svg", "high-fidelity", False),
        (True, "image.svg", _ModelingMode.HIGH_FIDELITY, False),
    ],
)
def test_scope_requires_svg_vector_only_when_enabled(
    enabled, image_path, modeling_mode, accepted, monkeypatch
):
    module = importlib.import_module("core.svg_hole_compensation")
    validate = getattr(module, "validate_svg_compensation_scope", None)
    assert callable(validate), "SVG compensation must expose an input-scope validator"
    monkeypatch.setitem(sys.modules, "lumina_svg_core._lumina_svg_compensation", None)
    if accepted:
        assert validate(
            enabled=enabled, image_path=image_path, modeling_mode=modeling_mode
        ) is None
    else:
        with pytest.raises(
            ValueError, match="SVG hole compensation requires an SVG in vector mode"
        ):
            validate(
                enabled=enabled, image_path=image_path, modeling_mode=modeling_mode
            )
