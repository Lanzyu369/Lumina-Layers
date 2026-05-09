import math
from types import SimpleNamespace

import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

import core.vector_engine as vector_engine
from core.vector_engine import VectorProcessor


def _hole_count(geom):
    if geom.geom_type == "Polygon":
        return len(geom.interiors)
    return sum(len(poly.interiors) for poly in geom.geoms)


def _hole_areas(geom):
    if geom.geom_type == "Polygon":
        return sorted(Polygon(ring).area for ring in geom.interiors)
    return sorted(Polygon(ring).area for poly in geom.geoms for ring in poly.interiors)


def test_backing_close_alignment():
    left = box(0, 0, 10, 10)
    right = box(10.2, 0, 20.2, 10)
    split = unary_union([left, right])

    assert (
        VectorProcessor._normalize_contours(split, close_delta_mm=0.05).geom_type
        == "MultiPolygon"
    )
    assert VectorProcessor._normalize_contours(split, close_delta_mm=0.15).geom_type == "Polygon"


def test_backing_hole_alignment():
    outer = box(0, 0, 10, 10).exterior.coords
    small_hole = box(1, 1, 1 + math.sqrt(0.5), 1 + math.sqrt(0.5)).exterior.coords
    large_hole = box(5, 5, 5 + math.sqrt(1.5), 5 + math.sqrt(1.5)).exterior.coords
    filtered = VectorProcessor._filter_backing_holes(
        Polygon(outer, [small_hole, large_hole]),
        min_hole_area_mm2=1.0,
    )

    assert _hole_count(filtered) == 1
    assert _hole_areas(filtered) == pytest.approx([1.5])


def test_slit_filter_closes_narrow_slits():
    narrow_bridge = unary_union(
        [box(0, 0, 4, 4), box(6, 0, 10, 4), box(4, 1.96, 6, 2.04)]
    )

    filtered = VectorProcessor._filter_slits(narrow_bridge, min_slit_width_mm=0.1)

    assert filtered.geom_type == "MultiPolygon"
    assert len(filtered.geoms) == 2


def test_color_layer_hole_filter_removes_small_holes(tmp_path):
    outer = box(0, 0, 10, 10).exterior.coords
    small_hole = box(1, 1, 1 + math.sqrt(0.3), 1 + math.sqrt(0.3)).exterior.coords
    large_hole = box(5, 5, 6, 6).exterior.coords
    geom = Polygon(outer, [small_hole, large_hole])
    svg_path = tmp_path / "direct_geometry.svg"
    svg_path.write_text("<svg/>", encoding="utf-8")

    processor = object.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.sampling_precision = 0.02
    processor.expand_stroke_to_fill = False
    processor.auto_dynamic_range = False
    processor.img_processor = SimpleNamespace(lut_rgb=[(0, 0, 0)], lut_path="direct.npy")
    processor._parse_svg = lambda *_: (
        [{"poly": geom, "color": (0, 128, 255)}],
        1.0,
        (0, 0, 10, 10),
    )
    processor._clip_occlusion = lambda *_args, **_kwargs: (
        [{"geometry": geom, "color": (0, 128, 255)}],
        geom,
    )
    processor._match_colors = lambda clipped, *_args, **_kwargs: [
        {"geometry": item["geometry"], "recipe": [0], "color": item["color"]} for item in clipped
    ]
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()

    analysis = VectorProcessor.analyze_svg(processor, str(svg_path), target_width_mm=10.0)

    assert len(analysis.clipped_shapes) == 1
    assert _hole_count(analysis.clipped_shapes[0]["geometry"]) == 1
    assert _hole_areas(analysis.clipped_shapes[0]["geometry"]) == pytest.approx([1.0])
