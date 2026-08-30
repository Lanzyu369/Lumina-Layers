"""Test-only differential audit for the supported Lumina native subset."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import GeometryCollection
from shapely.ops import unary_union

from core import native_svg_adapter
from core.native_svg_adapter import NativeSvgFallback
from core.vector_engine import VectorProcessor
import core.vector_engine as vector_engine


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "native_svg"
MANIFEST = json.loads(
    (FIXTURES / "golden_manifest.json").read_text(encoding="utf-8")
)


def _processor() -> VectorProcessor:
    processor = object.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.sampling_precision = 0.02
    processor.expand_stroke_to_fill = False
    processor.auto_dynamic_range = False
    processor.img_processor = SimpleNamespace(
        lut_rgb=[(0, 0, 0)],
        lut_path="direct.npy",
    )
    processor._match_colors = lambda clipped, *_args, **_kwargs: [
        {
            "geometry": item["geometry"],
            "recipe": [0],
            "color": item["color"],
        }
        for item in clipped
    ]
    return processor


def _run(processor: VectorProcessor, path: Path, *, backend: str, monkeypatch):
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()
    if backend == "native":
        return processor.analyze_svg(
            str(path), MANIFEST["target_width_mm"]
        )
    with monkeypatch.context() as context:
        context.setattr(
            native_svg_adapter,
            "analyze_native_svg",
            lambda *_args, **_kwargs: NativeSvgFallback(
                "differential_reference", "test"
            ),
        )
        return processor.analyze_svg(
            str(path), MANIFEST["target_width_mm"]
        )


def _by_color(analysis):
    grouped = defaultdict(list)
    for item in analysis.clipped_shapes:
        grouped[tuple(item["color"])].append(item["geometry"])
    return {color: unary_union(geometries) for color, geometries in grouped.items()}


def _component_hole_counts(analysis) -> tuple[int, int]:
    component_count = 0
    hole_count = 0
    for geometry in _by_color(analysis).values():
        polygons = geometry.geoms if geometry.geom_type == "MultiPolygon" else (geometry,)
        component_count += len(polygons)
        hole_count += sum(len(polygon.interiors) for polygon in polygons)
    return component_count, hole_count


def _ordered_unique_colors(analysis) -> list[tuple[int, int, int]]:
    return list(
        dict.fromkeys(tuple(item["color"]) for item in analysis.clipped_shapes)
    )


@pytest.mark.parametrize("case", MANIFEST["cases"], ids=lambda case: case["file"])
def test_native_matches_legacy_reference_within_physical_budget(
    case: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = FIXTURES / str(case["file"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == case["sha256"]
    processor = _processor()

    native = _run(processor, path, backend="native", monkeypatch=monkeypatch)
    legacy = _run(processor, path, backend="legacy", monkeypatch=monkeypatch)

    assert native.stage_timings["geometry_backend"] == "native"
    assert legacy.stage_timings["geometry_backend"] == "legacy"
    assert native.bbox == pytest.approx(legacy.bbox, abs=0.001)
    assert native.scale_factor == pytest.approx(legacy.scale_factor, rel=1e-6)
    assert _ordered_unique_colors(native) == _ordered_unique_colors(legacy)
    assert _component_hole_counts(native) == _component_hole_counts(legacy)

    native_by_color = _by_color(native)
    legacy_by_color = _by_color(legacy)
    assert native_by_color.keys() == legacy_by_color.keys()
    total_difference_mm2 = 0.0
    for color in native_by_color:
        native_geometry = native_by_color[color]
        legacy_geometry = legacy_by_color[color]
        physical_scale_squared = legacy.scale_factor**2
        area_difference_mm2 = abs(
            native_geometry.area - legacy_geometry.area
        ) * physical_scale_squared
        symmetric_difference_mm2 = native_geometry.symmetric_difference(
            legacy_geometry
        ).area * physical_scale_squared
        assert area_difference_mm2 <= case["max_area_difference_mm2"]
        total_difference_mm2 += symmetric_difference_mm2
    assert total_difference_mm2 <= case["max_symmetric_difference_mm2"]


def test_native_differential_output_is_stable_across_uncached_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("lumina_svg_core")
    case = MANIFEST["cases"][0]
    path = FIXTURES / str(case["file"])
    processor = _processor()
    fingerprints = []
    for _ in range(3):
        analysis = _run(
            processor, path, backend="native", monkeypatch=monkeypatch
        )
        digest = hashlib.sha256()
        for item in analysis.clipped_shapes:
            digest.update(bytes(item["color"]))
            digest.update(item["geometry"].wkb)
        fingerprints.append(digest.hexdigest())
    assert len(set(fingerprints)) == 1
