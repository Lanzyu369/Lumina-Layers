"""Native-by-default selection and one-shot whole-document fallback."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from shapely.geometry import box

from core import native_svg_adapter
from core.native_svg_adapter import NativeSvgFallback, NativeSvgGeometry
from core.vector_engine import VectorProcessor
import core.vector_engine as vector_engine


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


def _native_geometry() -> NativeSvgGeometry:
    geometry = box(0, 0, 10, 5)
    return NativeSvgGeometry(
        shape_data=[
            {
                "poly": geometry,
                "color": (10, 20, 30),
                "source_kind": "fill",
            }
        ],
        clipped_shapes=[
            {
                "geometry": geometry,
                "color": (10, 20, 30),
                "draw_order": 0,
            }
        ],
        silhouette=geometry,
        scale_factor=2.0,
        bbox=(0.0, 0.0, 10.0, 5.0),
        stage_timings={
            "native_svg_s": 0.03,
            "native_result_conversion_s": 0.01,
            "native_recorder_s": 0.004,
            "native_kernel_s": 0.012,
            "native_binding_conversion_s": 0.002,
            "native_adapter_s": 0.006,
            "geometry_backend": "native",
            "native_fallback_reason": "",
        },
        native_version="0.1.1",
        native_schema_version=1,
    )


def test_supported_document_uses_native_without_legacy_parse(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svg_path = tmp_path / "supported.svg"
    svg_path.write_text("<svg/>", encoding="utf-8")
    processor = _processor()
    monkeypatch.setattr(
        native_svg_adapter,
        "analyze_native_svg",
        lambda *_args, **_kwargs: _native_geometry(),
    )
    processor._parse_svg = lambda *_args: pytest.fail("legacy parser ran")
    processor._clip_occlusion = lambda *_args, **_kwargs: pytest.fail(
        "legacy GEOS clip ran"
    )
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()

    analysis = processor.analyze_svg(str(svg_path), 20.0)

    assert analysis.stage_timings["geometry_backend"] == "native"
    assert analysis.stage_timings["native_svg_s"] > 0
    assert analysis.bbox == (0.0, 0.0, 10.0, 5.0)
    assert len(analysis.clipped_shapes) == 1


def test_native_success_clears_warning_from_previous_legacy_document(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svg_path = tmp_path / "supported-after-warning.svg"
    svg_path.write_text("<svg/>", encoding="utf-8")
    processor = _processor()
    processor.parse_warnings = ["stale warning from another SVG"]
    monkeypatch.setattr(
        native_svg_adapter,
        "analyze_native_svg",
        lambda *_args, **_kwargs: _native_geometry(),
    )
    processor._parse_svg = lambda *_args: pytest.fail("legacy parser ran")
    processor._clip_occlusion = lambda *_args, **_kwargs: pytest.fail(
        "legacy GEOS clip ran"
    )
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()

    processor.analyze_svg(str(svg_path), 20.0)

    assert processor.parse_warnings == []


def test_unsupported_document_runs_one_complete_legacy_path(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svg_path = tmp_path / "unsupported.svg"
    svg_path.write_text("<svg/>", encoding="utf-8")
    processor = _processor()
    monkeypatch.setattr(
        native_svg_adapter,
        "analyze_native_svg",
        lambda *_args, **_kwargs: NativeSvgFallback(
            "unsupported_marker", "0.1.1"
        ),
    )
    geometry = box(0, 0, 1, 1)
    legacy_calls: list[str] = []

    def legacy_parse(path: str, _target_width_mm: float):
        legacy_calls.append(path)
        return [{"poly": geometry, "color": (1, 2, 3)}], 20.0, (0, 0, 1, 1)

    processor._parse_svg = legacy_parse
    processor._clip_occlusion = lambda *_args, **_kwargs: (
        [{"geometry": geometry, "color": (1, 2, 3), "draw_order": 0}],
        geometry,
    )
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
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()

    analysis = processor.analyze_svg(str(svg_path), 20.0)

    assert legacy_calls == [str(svg_path)]
    assert analysis.stage_timings["geometry_backend"] == "legacy"
    assert (
        analysis.stage_timings["native_fallback_reason"]
        == "unsupported_marker"
    )




def test_large_legal_selector_is_processed_without_legacy_retry(
    tmp_path,
) -> None:
    pytest.importorskip("lumina_svg_core")
    svg_path = tmp_path / "selector-amplifier.svg"
    svg_path.write_text(
        "<svg viewBox='0 0 10 10'><style>"
        + "g " * 100_001
        + "{fill:red}</style><rect width='10' height='10'/></svg>",
        encoding="utf-8",
    )
    processor = _processor()
    processor._parse_svg = lambda *_args: pytest.fail("legacy parser ran")
    processor._clip_occlusion = lambda *_args, **_kwargs: pytest.fail(
        "legacy GEOS clip ran"
    )
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()

    analysis = processor.analyze_svg(str(svg_path), 20.0)

    assert analysis.stage_timings["geometry_backend"] == "native"
    assert len(analysis.clipped_shapes) == 1


def test_native_version_is_part_of_parse_clip_cache_identity(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svg_path = tmp_path / "cache.svg"
    svg_path.write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(
        native_svg_adapter,
        "native_runtime_identity",
        lambda: ("native", "0.1.1", 1),
    )
    first = vector_engine._vector_parse_clip_cache_key(
        str(svg_path),
        target_width_mm=20.0,
        sampling_precision=0.02,
        expand_stroke_to_fill=False,
        gradient_color_bands=None,
    )
    monkeypatch.setattr(
        native_svg_adapter,
        "native_runtime_identity",
        lambda: ("native", "0.2.0", 2),
    )
    second = vector_engine._vector_parse_clip_cache_key(
        str(svg_path),
        target_width_mm=20.0,
        sampling_precision=0.02,
        expand_stroke_to_fill=False,
        gradient_color_bands=None,
    )

    assert first != second
    assert ("native", "0.1.1", 1) == first[-3:]
    assert ("native", "0.2.0", 2) == second[-3:]


def test_native_cache_hit_preserves_backend_identity(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svg_path = tmp_path / "cached-native.svg"
    svg_path.write_text("<svg/>", encoding="utf-8")
    processor = _processor()
    calls = 0

    def native_once(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _native_geometry()

    monkeypatch.setattr(native_svg_adapter, "analyze_native_svg", native_once)
    processor._parse_svg = lambda *_args: pytest.fail("legacy parser ran")
    processor._clip_occlusion = lambda *_args, **_kwargs: pytest.fail(
        "legacy GEOS clip ran"
    )
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()

    first = processor.analyze_svg(str(svg_path), 20.0)
    second = processor.analyze_svg(str(svg_path), 20.0)

    assert calls == 1
    assert first.stage_timings["geometry_backend"] == "native"
    assert second.stage_timings["geometry_backend"] == "native"
    assert second.stage_timings["native_cache_hit"] is True
    assert second.stage_timings["native_svg_s"] == 0.0
    assert second.stage_timings["native_result_conversion_s"] == 0.0
    assert second.stage_timings["native_recorder_s"] == 0.0
    assert second.stage_timings["native_kernel_s"] == 0.0
    for stage_name in (
        "native_bounds_s",
        "native_replay_s",
        "native_topology_s",
        "native_normalize_raw_s",
        "native_composite_s",
        "native_normalize_visible_s",
        "native_export_s",
    ):
        assert second.stage_timings[stage_name] == 0.0
    assert second.stage_timings["native_binding_conversion_s"] == 0.0
    assert second.stage_timings["native_adapter_s"] == 0.0
