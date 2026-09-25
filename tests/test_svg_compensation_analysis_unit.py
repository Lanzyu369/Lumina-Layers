"""The shared analysis consumes compensated SVG regions before colour matching."""

from types import SimpleNamespace

import pytest
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from core import native_svg_adapter, vector_engine
from core.native_svg_adapter import NativeSvgGeometry
from core.vector_engine import VectorProcessor


@pytest.fixture
def source_analysis(tmp_path, monkeypatch):
    path = tmp_path / "two-colour-hole.svg"
    path.write_text("<svg viewBox='0 0 10 10'/>", encoding="utf-8")
    left = Polygon([(0, 0), (5, 0), (5, 4.8), (4.8, 4.8),
                    (4.8, 5.2), (5, 5.2), (5, 10), (0, 10)])
    right = box(0, 0, 10, 10).difference(left).difference(box(4.8, 4.8, 5.2, 5.2))
    regions = [
        {"geometry": left, "color": (255, 0, 0), "draw_order": 0},
        {"geometry": right, "color": (0, 0, 255), "draw_order": 1},
    ]
    source_coverage = unary_union([left, right])

    def parse(_path, width, *_args, **_kwargs):
        return NativeSvgGeometry(
            shape_data=[{"poly": item["geometry"], "color": item["color"]} for item in regions],
            clipped_shapes=regions,
            silhouette=source_coverage,
            scale_factor=width / 10.0,
            bbox=(0, 0, 10, 10),
            stage_timings={"geometry_backend": "native"},
            native_version="test-boundary",
            native_schema_version=3,
        )

    monkeypatch.setattr(native_svg_adapter, "analyze_native_svg", parse)
    processor = VectorProcessor.from_img_processor(
        SimpleNamespace(lut_rgb=[(0, 0, 0)], lut_path="compensation-direct.npy"),
        "4-Color (RYBW)",
    )
    processor._match_colors = lambda clipped, *a, **kw: [
        {**item, "recipe": [0] * 5, "matched_rgb": item["color"]} for item in clipped
    ]
    processor.svg_hole_max_width_mm = 0.0
    processor.svg_hole_max_area_mm2 = 0.5
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()
    yield processor, path, regions
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()


def test_compensation_reaches_both_matched_regions_and_silhouette(source_analysis):
    processor, path, regions = source_analysis
    processor.svg_hole_compensation_enabled = True
    result = processor.analyze_svg(str(path), 10.0)
    assert result.silhouette.covers(Point(5, 5))
    assert any(item["geometry"].covers(Point(5, 5)) for item in result.matched_shapes)
    assert result.stage_timings["svg_holes_filled"] == 1
    assert result.stage_timings["svg_hole_added_area_mm2"] == pytest.approx(0.16)
    assert all(not item["geometry"].covers(Point(5, 5)) for item in regions)


def test_toggle_does_not_contaminate_pure_parse_cache(source_analysis):
    processor, path, _ = source_analysis
    processor.svg_hole_compensation_enabled = False
    before = processor.analyze_svg(str(path), 10.0)
    processor.svg_hole_compensation_enabled = True
    filled = processor.analyze_svg(str(path), 10.0)
    processor.svg_hole_compensation_enabled = False
    after = processor.analyze_svg(str(path), 10.0)
    assert filled.silhouette.covers(Point(5, 5))
    assert not before.silhouette.covers(Point(5, 5))
    assert not after.silhouette.covers(Point(5, 5))
    assert after.silhouette.equals(before.silhouette)


def test_strength_and_size_are_recomputed_from_original_svg(source_analysis):
    processor, path, _ = source_analysis
    processor.svg_hole_compensation_enabled = True
    small = processor.analyze_svg(str(path), 10.0)
    large = processor.analyze_svg(str(path), 20.0)
    processor.svg_hole_max_area_mm2 = 0.01
    reduced = processor.analyze_svg(str(path), 10.0)
    assert small.silhouette.covers(Point(5, 5))
    assert not large.silhouette.covers(Point(5, 5))
    assert not reduced.silhouette.covers(Point(5, 5))


def test_compensated_legacy_cache_does_not_run_another_per_color_hole_filter(source_analysis, monkeypatch):
    processor, path, _ = source_analysis
    processor.analyze_svg(str(path), 10.0)
    for entry in vector_engine._VECTOR_PARSE_CLIP_CACHE.values():
        entry["geometry_stage_timings"]["geometry_backend"] = "legacy"

    def unexpected_filter(*args, **kwargs):
        raise AssertionError("Compensated geometry must not be filled a second time")

    monkeypatch.setattr(VectorProcessor, "_filter_backing_holes", unexpected_filter)
    processor.svg_hole_compensation_enabled = True
    result = processor.analyze_svg(str(path), 10.0)
    assert result.silhouette.covers(Point(5, 5))


def test_missing_compensation_binary_explains_how_to_recover(source_analysis, monkeypatch):
    from api.errors import to_http_exception
    from core import svg_hole_compensation
    from core.errors import CoreDependencyError

    def missing(*args):
        raise ImportError("missing extension")

    monkeypatch.setattr(svg_hole_compensation, "import_module", missing)
    processor, path, _ = source_analysis
    processor.svg_hole_compensation_enabled = True
    with pytest.raises(CoreDependencyError) as failure:
        processor.analyze_svg(str(path), 10.0)
    response = to_http_exception(failure.value, context="SVG preview")
    assert response.status_code == 502
    assert "Install or rebuild lumina-svg-core" in response.detail
