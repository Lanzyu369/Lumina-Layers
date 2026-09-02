"""Fail-closed integration properties for ambiguous SVG semantics."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
import pytest
from shapely.geometry import box

from core import native_svg_adapter
from core.native_svg_adapter import NativeSvgFallback, NativeSvgGeometry
from core.vector_engine import VectorProcessor
import core.vector_engine as vector_engine


UNSUPPORTED_DOCUMENT_PARTS = [
    "<rect x='1' y='1' width='4' height='4' opacity='0.5'/>",
    "<g opacity='0.5'><rect x='1' y='1' width='4' height='4'/></g>",
    "<path d='M1 1H5' paint-order='stroke fill'/>",
    "<mask id='m'><rect width='5' height='5'/></mask>",
    "<pattern id='p' width='1' height='1'/><rect width='5' height='5' "
    "fill='url(#p)'/>",
    "<linearGradient id='g'><stop offset='0' stop-color='red'/></linearGradient>"
    "<rect width='5' height='5' fill='url(#g)'/>",
    "<text x='1' y='2'>x</text>",
    "<image href='data:image/png;base64,AA=='/>",
    "<rect width='5' height='5' filter='url(#f)'/>",
    "<script>1</script>",
    "<animate attributeName='x' from='0' to='1'/>",
    "<use href='external.svg#shape'/>",
    "<foreignObject width='1' height='1'/>",
]

SUPPORTED_DOCUMENT_PARTS = [
    "<path d='M1 1H5' marker-start='url(#missing)'/>",
    "<rect width='5' height='5' made-up-paint='1'/>",
    "<style>rect { made-up-paint: 1; }</style>",
    "<circle cx='5' cy='5' r='4'/>",
    "<ellipse cx='5' cy='5' rx='4' ry='2'/>",
    "<rect x='1' y='1' width='8' height='8' rx='2'/>",
]


def test_arc_path_is_native_and_preserves_exact_paint_identity(
    tmp_path: Path,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "arc.svg"
    path.write_text(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>"
        "<path d='M1 5A4 4 0 0 1 9 5L1 5Z' fill='#123456'/></svg>",
        encoding="utf-8",
    )

    outcome = native_svg_adapter.analyze_native_svg(str(path), 20.0, 0.02)

    assert isinstance(outcome, NativeSvgGeometry)
    assert len(outcome.shape_data) == 1
    assert len(outcome.clipped_shapes) == 1
    assert outcome.clipped_shapes[0]["rgba"] == (18, 52, 86, 255)
    assert outcome.clipped_shapes[0]["native_paint_id"] == (1, 0)
    assert outcome.clipped_shapes[0]["geometry"].area > 0.0


def _document(part: str) -> str:
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>"
        f"{part}<rect x='0' y='0' width='10' height='10' fill='#123456'/>"
        "</svg>"
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


@pytest.mark.parametrize("part", UNSUPPORTED_DOCUMENT_PARTS)
def test_unsupported_semantics_return_no_native_geometry_and_fallback_once(
    part: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "unsupported.svg"
    path.write_text(_document(part), encoding="utf-8")
    outcome = native_svg_adapter.analyze_native_svg(
        str(path), 20.0, 0.02
    )
    assert isinstance(outcome, NativeSvgFallback)

    geometry = box(0, 0, 10, 10)
    processor = _processor()
    parse_calls = 0

    def legacy_parse(*_args, **_kwargs):
        nonlocal parse_calls
        parse_calls += 1
        return [{"poly": geometry, "color": (18, 52, 86)}], 2.0, (
            0,
            0,
            10,
            10,
        )

    processor._parse_svg = legacy_parse
    processor._clip_occlusion = lambda *_args, **_kwargs: (
        [{"geometry": geometry, "color": (18, 52, 86), "draw_order": 0}],
        geometry,
    )
    monkeypatch.setattr(
        native_svg_adapter,
        "analyze_native_svg",
        lambda *_args, **_kwargs: outcome,
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

    analysis = processor.analyze_svg(str(path), 20.0)

    assert parse_calls == 1
    assert analysis.stage_timings["geometry_backend"] == "legacy"
    assert analysis.stage_timings["native_fallback_reason"] == outcome.reason_code


@pytest.mark.parametrize("part", SUPPORTED_DOCUMENT_PARTS)
def test_supported_shapes_and_ignored_metadata_stay_native(
    part: str,
    tmp_path: Path,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "supported.svg"
    path.write_text(_document(part), encoding="utf-8")

    outcome = native_svg_adapter.analyze_native_svg(str(path), 20.0, 0.02)

    assert isinstance(outcome, NativeSvgGeometry)
    assert outcome.clipped_shapes


def test_non_scaling_stroke_follows_the_requested_stroke_policy(
    tmp_path: Path,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "non-scaling-stroke.svg"
    path.write_text(
        _document(
            "<path d='M1 1H5' fill='none' stroke='red' "
            "vector-effect='non-scaling-stroke'/>"
        ),
        encoding="utf-8",
    )

    fill_only = native_svg_adapter.analyze_native_svg(
        str(path), 20.0, 0.02, expand_stroke_to_fill=False
    )
    expanded = native_svg_adapter.analyze_native_svg(
        str(path), 20.0, 0.02, expand_stroke_to_fill=True
    )

    assert isinstance(fill_only, NativeSvgGeometry)
    assert isinstance(expanded, NativeSvgGeometry)
    assert [item["source_kind"] for item in fill_only.shape_data] == [
        "fill"
    ]
    assert [item["source_kind"] for item in expanded.shape_data] == [
        "stroke_only",
        "fill",
    ]
    assert expanded.shape_data[0]["rgba"] == (255, 0, 0, 255)


@settings(
    max_examples=20,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(alpha=st.floats(min_value=0.01, max_value=0.99, allow_nan=False))
def test_every_partial_paint_alpha_requests_whole_document_fallback(
    alpha: float,
    tmp_path: Path,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "partial-alpha.svg"
    path.write_text(
        _document(
            "<rect x='1' y='1' width='4' height='4' "
            f"fill='rgba(12,34,56,{alpha:.9f})'/>"
        ),
        encoding="utf-8",
    )

    outcome = native_svg_adapter.analyze_native_svg(str(path), 20.0, 0.02)

    assert outcome == NativeSvgFallback(
        reason_code="unsupported_partial_alpha",
        native_version="0.2.0",
    )


@settings(
    max_examples=20,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    attribute=st.from_regex(r"x-[a-z]{1,12}", fullmatch=True),
    value=st.integers(min_value=0, max_value=10_000),
)
def test_every_unknown_attribute_is_ignored(
    attribute: str,
    value: int,
    tmp_path: Path,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "unknown-property.svg"
    path.write_text(
        _document(
            f"<rect x='1' y='1' width='4' height='4' {attribute}='{value}'/>"
        ),
        encoding="utf-8",
    )

    outcome = native_svg_adapter.analyze_native_svg(str(path), 20.0, 0.02)

    assert isinstance(outcome, NativeSvgGeometry)
    assert outcome.clipped_shapes


def test_internal_doctype_entity_falls_back_to_legacy_red_geometry(
    tmp_path: Path,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "internal-entity.svg"
    path.write_text(
        "<!DOCTYPE svg [<!ENTITY c '#f00'>]>"
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>"
        "<rect width='10' height='10' fill='&c;'/></svg>",
        encoding="utf-8",
    )
    vector_engine._VECTOR_PARSE_CLIP_CACHE.clear()

    analysis = _processor().analyze_svg(str(path), 20.0)

    assert analysis.stage_timings["geometry_backend"] == "legacy"
    assert analysis.stage_timings["native_fallback_reason"] == (
        "unsupported_doctype"
    )
    assert [shape["color"] for shape in analysis.shape_data] == [
        (255, 0, 0)
    ]
