import math
import pickle
from types import SimpleNamespace

import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

import core.vector_engine as vector_engine
from core.native_svg_adapter import NativeSvgFallback
from core.vector_engine import VectorProcessor


def _hole_count(geom):
    if geom.geom_type == "Polygon":
        return len(geom.interiors)
    return sum(len(poly.interiors) for poly in geom.geoms)


def _hole_areas(geom):
    if geom.geom_type == "Polygon":
        return sorted(Polygon(ring).area for ring in geom.interiors)
    return sorted(Polygon(ring).area for poly in geom.geoms for ring in poly.interiors)


def _force_legacy_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep legacy-internal unit tests isolated from an installed native wheel."""

    monkeypatch.setattr(
        vector_engine.native_svg_adapter,
        "analyze_native_svg",
        lambda *_args, **_kwargs: NativeSvgFallback(
            reason_code="test_legacy_parser",
            native_version="test",
        ),
    )


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


def test_evenodd_two_subpath_containment_uses_difference_fast_path(monkeypatch):
    outer = box(0, 0, 10, 10)
    inner = box(2, 2, 4, 4)

    def fail_symmetric_difference_all(_items):
        raise AssertionError("contained two-subpath evenodd should avoid full symmetric_difference_all")

    monkeypatch.setattr(vector_engine, "symmetric_difference_all", fail_symmetric_difference_all)

    result = vector_engine._combine_evenodd_polygons([outer, inner])

    expected = outer.difference(inner)
    assert result.symmetric_difference(expected).area == pytest.approx(0.0)


def test_slit_filter_closes_narrow_slits():
    narrow_bridge = unary_union(
        [box(0, 0, 4, 4), box(6, 0, 10, 4), box(4, 1.96, 6, 2.04)]
    )

    filtered = VectorProcessor._filter_slits(narrow_bridge, min_slit_width_mm=0.1)

    assert filtered.geom_type == "MultiPolygon"
    assert len(filtered.geoms) == 2


def test_color_layer_hole_filter_removes_small_holes(tmp_path, monkeypatch):
    _force_legacy_parser(monkeypatch)
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
    processor.img_processor = SimpleNamespace(
        lut_rgb=[(0, 0, 0)],
        lut_path="direct.npy",
    )
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


def test_vector_parse_clip_cache_capacity_is_interaction_sized():
    assert vector_engine._VECTOR_PARSE_CLIP_CACHE_MAX >= 8


def test_vector_parse_clip_cache_refreshes_hit_before_eviction(tmp_path, monkeypatch):
    _force_legacy_parser(monkeypatch)
    monkeypatch.setattr(vector_engine, "_VECTOR_PARSE_CLIP_CACHE_MAX", 2)
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()

    paths = []
    for name in ("a.svg", "b.svg", "c.svg"):
        path = tmp_path / name
        path.write_text("<svg/>", encoding="utf-8")
        paths.append(path)

    geom = box(0, 0, 1, 1)
    parse_calls = []
    processor = object.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.sampling_precision = 0.02
    processor.expand_stroke_to_fill = False
    processor.auto_dynamic_range = False
    processor.img_processor = SimpleNamespace(lut_rgb=[(0, 0, 0)], lut_path="direct.npy")

    def fake_parse(svg_path, _target_width_mm):
        parse_calls.append(svg_path)
        return [{"poly": geom, "color": (0, 128, 255)}], 1.0, (0, 0, 1, 1)

    processor._parse_svg = fake_parse
    processor._clip_occlusion = lambda *_args, **_kwargs: (
        [{"geometry": geom, "color": (0, 128, 255)}],
        geom,
    )
    processor._match_colors = lambda clipped, *_args, **_kwargs: [
        {"geometry": item["geometry"], "recipe": [0], "color": item["color"]} for item in clipped
    ]

    for path in (paths[0], paths[1], paths[0], paths[2]):
        VectorProcessor.analyze_svg(processor, str(path), target_width_mm=10.0)

    cache_paths = [key[0] for key in vector_engine._VECTOR_PARSE_CLIP_CACHE]
    assert str(paths[0].resolve()) in cache_paths
    assert str(paths[1].resolve()) not in cache_paths
    assert str(paths[2].resolve()) in cache_paths
    assert parse_calls == [str(paths[0]), str(paths[1]), str(paths[2])]


def test_vector_parse_clip_artifact_skips_parse_and_clip(tmp_path):
    svg_path = tmp_path / "cached.svg"
    svg_path.write_text("<svg/>", encoding="utf-8")
    artifact_path = tmp_path / "parse_clip_cache.pkl"
    geom = box(0, 0, 1, 1)
    cache_key = vector_engine._vector_parse_clip_cache_key(
        str(svg_path),
        target_width_mm=10.0,
        sampling_precision=0.02,
        expand_stroke_to_fill=False,
        gradient_color_bands=None,
    )
    cache_entry = {
        "shape_data": [{"poly": geom, "color": (0, 128, 255)}],
        "clipped_shapes": [{"geometry": geom, "color": (0, 128, 255)}],
        "silhouette": geom,
        "image_vectorizer_bounds": None,
        "scale_factor": 1.0,
        "bbox": (0, 0, 1, 1),
        "parse_warnings": ["cached legacy parse warning"],
    }
    artifact_path.write_bytes(
        vector_engine._serialize_vector_parse_clip_cache(cache_key, cache_entry)
    )

    processor = object.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.sampling_precision = 0.02
    processor.expand_stroke_to_fill = False
    processor.auto_dynamic_range = False
    processor.parse_warnings = ["stale warning from another SVG"]
    processor._parse_clip_cache_path = str(artifact_path)
    solve_calls = []
    processor.img_processor = SimpleNamespace(
        lut_rgb=[(0, 0, 0)],
        lut_path="direct.npy",
        solve_for_fills=lambda fills: solve_calls.append(tuple(fills)),
    )
    processor._parse_svg = lambda *_args, **_kwargs: pytest.fail("parse should be skipped")
    processor._clip_occlusion = lambda *_args, **_kwargs: pytest.fail("clip should be skipped")
    processor._match_colors = lambda clipped, *_args, **_kwargs: [
        {"geometry": item["geometry"], "recipe": [0], "color": item["color"]} for item in clipped
    ]
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()

    analysis = VectorProcessor.analyze_svg(processor, str(svg_path), target_width_mm=10.0)

    assert analysis.stage_timings["parse_s"] == 0.0
    assert analysis.stage_timings["occlusion_s"] == 0.0
    assert analysis.stage_timings["fill_dedup_s"] >= 0.0
    assert analysis.stage_timings["material_solve_s"] >= 0.0
    assert solve_calls == [((0, 128, 255),)]
    assert len(analysis.matched_shapes) == 1
    assert processor.parse_warnings == ["cached legacy parse warning"]


def test_v3_artifact_without_paint_identity_is_ignored(
    tmp_path,
    monkeypatch,
):
    _force_legacy_parser(monkeypatch)
    svg_path = tmp_path / "self-cross.svg"
    svg_path.write_text("<svg/>", encoding="utf-8")
    artifact_path = tmp_path / "old-v3-parse-clip-cache.pkl"
    cache_key = vector_engine._vector_parse_clip_cache_key(
        str(svg_path),
        target_width_mm=10.0,
        sampling_precision=0.02,
        expand_stroke_to_fill=False,
        gradient_color_bands=None,
    )
    stale_geom = box(0, 0, 2, 2)
    stale_entry = {
        "shape_data": [{"poly": stale_geom, "color": (255, 0, 0)}],
        "clipped_shapes": [
            {"geometry": stale_geom, "color": (255, 0, 0)}
        ],
        "silhouette": stale_geom,
        "image_vectorizer_bounds": None,
        "scale_factor": 1.0,
        "bbox": (0, 0, 2, 2),
        "parse_warnings": ["stale-v3-result-without-paint-identity"],
    }
    artifact_path.write_bytes(
        pickle.dumps(
            {
                "schema": "lumina_vector_parse_clip_cache_v3",
                "cache_key": cache_key,
                "entry": stale_entry,
            },
            protocol=pickle.HIGHEST_PROTOCOL,
        )
    )

    fresh_geom = box(0, 0, 1, 1)
    parse_calls = []
    processor = object.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.sampling_precision = 0.02
    processor.expand_stroke_to_fill = False
    processor.auto_dynamic_range = False
    processor.parse_warnings = []
    processor._parse_clip_cache_path = str(artifact_path)
    processor.img_processor = SimpleNamespace(
        lut_rgb=[(0, 0, 0)],
        lut_path="direct.npy",
        solve_for_fills=lambda _fills: None,
    )

    def fresh_parse(path, _target_width_mm):
        parse_calls.append(path)
        return [
            {"poly": fresh_geom, "color": (0, 128, 255)}
        ], 1.0, (0, 0, 1, 1)

    processor._parse_svg = fresh_parse
    processor._clip_occlusion = lambda *_args, **_kwargs: (
        [{"geometry": fresh_geom, "color": (0, 128, 255)}],
        fresh_geom,
    )
    processor._match_colors = lambda clipped, *_args, **_kwargs: [
        {
            "geometry": item["geometry"],
            "recipe": [0],
            "color": item["color"],
        }
        for item in clipped
    ]
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()

    analysis = VectorProcessor.analyze_svg(
        processor, str(svg_path), target_width_mm=10.0
    )

    assert parse_calls == [str(svg_path)]
    assert analysis.bbox == (0, 0, 1, 1)
    assert processor.parse_warnings == []


def test_vector_parse_clip_cache_entry_is_not_mutated_by_later_filters(
    tmp_path,
    monkeypatch,
):
    _force_legacy_parser(monkeypatch)
    svg_path = tmp_path / "cache_source.svg"
    svg_path.write_text("<svg/>", encoding="utf-8")
    original_geom = box(0, 0, 10, 10)
    filtered_geom = box(0, 0, 9, 9)

    processor = object.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.sampling_precision = 0.02
    processor.expand_stroke_to_fill = False
    processor.auto_dynamic_range = False
    processor.img_processor = SimpleNamespace(lut_rgb=[(0, 0, 0)], lut_path="direct.npy")
    processor._parse_svg = lambda *_args, **_kwargs: (
        [{"poly": original_geom, "color": (0, 128, 255)}],
        1.0,
        (0, 0, 10, 10),
    )
    processor._clip_occlusion = lambda *_args, **_kwargs: (
        [{"geometry": original_geom, "color": (0, 128, 255), "draw_order": 0}],
        original_geom,
    )
    processor._match_colors = lambda clipped, *_args, **_kwargs: [
        {"geometry": item["geometry"], "recipe": [0], "color": item["color"]} for item in clipped
    ]
    monkeypatch.setattr(
        VectorProcessor,
        "_postprocess_clipped_shapes",
        staticmethod(lambda clipped: clipped),
    )
    monkeypatch.setattr(
        VectorProcessor,
        "_split_disconnected_shapes",
        staticmethod(lambda shapes: shapes),
    )
    monkeypatch.setattr(
        VectorProcessor,
        "_filter_backing_holes",
        staticmethod(lambda _geom, **_kwargs: filtered_geom),
    )
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()

    analysis = VectorProcessor.analyze_svg(processor, str(svg_path), target_width_mm=10.0)
    cache_key = vector_engine._vector_parse_clip_cache_key(
        str(svg_path),
        target_width_mm=10.0,
        sampling_precision=0.02,
        expand_stroke_to_fill=False,
        gradient_color_bands=None,
    )

    assert analysis.clipped_shapes[0]["geometry"] is filtered_geom
    cached_entry = vector_engine._VECTOR_PARSE_CLIP_CACHE[cache_key]
    assert cached_entry["clipped_shapes"][0]["geometry"] is original_geom
