"""Fail-closed integration properties for ambiguous SVG semantics."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
import pytest
from shapely.geometry import box

from core import native_svg_adapter
from core.native_svg_adapter import NativeSvgFallback
from core.vector_engine import VectorProcessor
import core.vector_engine as vector_engine


UNSUPPORTED_DOCUMENT_PARTS = [
    "<rect x='1' y='1' width='4' height='4' opacity='0.5'/>",
    "<g opacity='0.5'><rect x='1' y='1' width='4' height='4'/></g>",
    "<path d='M1 1H5' fill='none' stroke='red' "
    "vector-effect='non-scaling-stroke'/>",
    "<path d='M1 1H5' marker-start='url(#m)'/>",
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
    "<rect width='5' height='5' made-up-paint='1'/>",
    "<style>rect { made-up-paint: 1; }</style>",
]


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


@settings(
    max_examples=20,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(alpha=st.floats(min_value=0.001, max_value=0.999, allow_nan=False))
def test_every_partial_alpha_fails_closed(
    alpha: float,
    tmp_path: Path,
) -> None:
    pytest.importorskip("lumina_svg_core")
    path = tmp_path / "partial-alpha.svg"
    path.write_text(
        _document(
            "<rect x='1' y='1' width='4' height='4' "
            f"opacity='{alpha:.9f}'/>"
        ),
        encoding="utf-8",
    )

    outcome = native_svg_adapter.analyze_native_svg(str(path), 20.0, 0.02)

    assert isinstance(outcome, NativeSvgFallback)
    assert outcome.reason_code == "unsupported_partial_alpha"


@settings(
    max_examples=20,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    attribute=st.from_regex(r"x-[a-z]{1,12}", fullmatch=True),
    value=st.integers(min_value=0, max_value=10_000),
)
def test_every_unknown_presentation_attribute_fails_closed(
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

    assert isinstance(outcome, NativeSvgFallback)
    assert outcome.reason_code == "unsupported_property"
