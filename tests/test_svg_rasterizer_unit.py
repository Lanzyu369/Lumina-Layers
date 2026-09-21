"""Regression tests for SVG rasterization edge cases."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("10", 10.0),
        ("10px", 10.0),
        ("1in", 96.0),
        ("1cm", 96.0 / 2.54),
        ("1mm", 96.0 / 25.4),
        ("1q", 96.0 / 101.6),
        ("1pt", 96.0 / 72.0),
        ("1pc", 16.0),
        ("1e2mm", 100.0 * 96.0 / 25.4),
    ),
)
def test_svg_absolute_length_parser_matches_resvg_css_pixels(
    raw: str,
    expected: float,
) -> None:
    from core.pipeline.processing_ops.svg_rasterizer import _parse_svg_length_to_px

    assert _parse_svg_length_to_px(raw) == pytest.approx(expected)


def test_svg_absolute_length_parser_rejects_percentages_and_unknown_units() -> None:
    from core.pipeline.processing_ops.svg_rasterizer import _parse_svg_length_to_px

    assert _parse_svg_length_to_px("100%") is None
    assert _parse_svg_length_to_px("10em") is None


def test_rasterize_svg_full_canvas_accepts_physical_units(tmp_path: Path) -> None:
    """SVG cover rasterization must handle mm-sized source artwork."""
    pytest.importorskip("resvg_py")

    from core.pipeline.processing_ops.svg_rasterizer import rasterize_svg

    svg_path = tmp_path / "physical-units.svg"
    svg_path.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">
  <rect x="10" y="10" width="40" height="40" fill="#ff0000"/>
  <circle cx="70" cy="30" r="15" fill="#0000ff"/>
</svg>
""",
        encoding="utf-8",
    )

    rendered = rasterize_svg(
        str(svg_path),
        target_width_mm=20.0,
        pixels_per_mm=2.0,
        crop_to_content=False,
    )

    assert rendered.ndim == 3
    assert rendered.shape[2] == 4
    assert rendered.shape[0] > 0
    assert rendered.shape[1] > 0
    assert rendered[:, :, 3].max() == 255


def test_rasterize_svg_thumbnail_caps_extreme_tall_canvas(tmp_path: Path) -> None:
    """A physical model width must not become an unbounded cover bitmap."""

    pytest.importorskip("resvg_py")
    from core.pipeline.processing_ops.svg_rasterizer import rasterize_svg

    svg_path = tmp_path / "tall.svg"
    svg_path.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 1000">
  <rect width="100" height="1000" fill="#336699"/>
</svg>
""",
        encoding="utf-8",
    )

    rendered = rasterize_svg(
        str(svg_path),
        target_width_mm=9999.0,
        pixels_per_mm=2.0,
        crop_to_content=False,
        _min_quality_px=1,
        _max_longest_px=512,
        _cache_result=False,
    )

    assert max(rendered.shape[:2]) <= 512
    assert rendered.shape[0] > rendered.shape[1]


def test_thumbnail_cap_uses_outer_viewport_before_mismatched_viewbox(
    tmp_path: Path,
) -> None:
    """The pre-render cap must match the viewport aspect resvg actually uses."""

    pytest.importorskip("resvg_py")
    from core.pipeline.processing_ops import svg_rasterizer

    svg_path = tmp_path / "viewport-mismatch.svg"
    svg_path.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" width="10" height="100"
viewBox="0 0 10 10"><rect width="10" height="10" fill="#336699"/></svg>
""",
        encoding="utf-8",
    )
    original_render = svg_rasterizer.resvg_py.svg_to_bytes
    with patch.object(
        svg_rasterizer.resvg_py,
        "svg_to_bytes",
        wraps=original_render,
    ) as render_mock:
        rendered = svg_rasterizer.rasterize_svg(
            str(svg_path),
            target_width_mm=9999.0,
            pixels_per_mm=2.0,
            crop_to_content=False,
            _min_quality_px=1,
            _max_longest_px=64,
            _cache_result=False,
        )

    assert render_mock.call_args.kwargs["width"] == 6
    assert max(rendered.shape[:2]) <= 64


def test_thumbnail_cap_parses_exponent_viewport_lengths(tmp_path: Path) -> None:
    """Scientific-notation viewport lengths cannot bypass pre-render bounds."""

    pytest.importorskip("resvg_py")
    from core.pipeline.processing_ops import svg_rasterizer

    svg_path = tmp_path / "exponent-viewport.svg"
    svg_path.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" width="10" height="1e3"
viewBox="0 0 10 10"><rect width="10" height="10" fill="#336699"/></svg>
""",
        encoding="utf-8",
    )
    original_render = svg_rasterizer.resvg_py.svg_to_bytes
    with patch.object(
        svg_rasterizer.resvg_py,
        "svg_to_bytes",
        wraps=original_render,
    ) as render_mock:
        rendered = svg_rasterizer.rasterize_svg(
            str(svg_path),
            target_width_mm=9999.0,
            pixels_per_mm=2.0,
            crop_to_content=False,
            _min_quality_px=1,
            _max_longest_px=200,
            _cache_result=False,
        )

    assert render_mock.call_args.kwargs["width"] == 2
    assert max(rendered.shape[:2]) <= 200


def test_total_pixel_cap_uses_resvg_viewport_for_large_format_fallback(
    tmp_path: Path,
) -> None:
    """A mismatched viewBox cannot multiply the fallback render budget."""

    pytest.importorskip("resvg_py")
    from core.pipeline.processing_ops import svg_rasterizer
    from core.vector_large_format import inspect_svg_large_format_support

    svg_path = tmp_path / "unsupported-viewport-mismatch.svg"
    svg_path.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" width="10" height="1000"
viewBox="0 0 10 10" preserveAspectRatio="xMinYMin meet">
  <defs><clipPath id="clip"><rect width="10" height="10"/></clipPath></defs>
  <rect width="10" height="10" clip-path="url(#clip)" fill="#336699"/>
</svg>
""",
        encoding="utf-8",
    )
    assert not inspect_svg_large_format_support(str(svg_path))[
        "native_tiling_supported"
    ]

    original_render = svg_rasterizer.resvg_py.svg_to_bytes
    with patch.object(
        svg_rasterizer.resvg_py,
        "svg_to_bytes",
        wraps=original_render,
    ) as render_mock:
        rendered = svg_rasterizer.rasterize_svg(
            str(svg_path),
            target_width_mm=100.0,
            pixels_per_mm=100.0,
            crop_to_content=False,
            _min_quality_px=1,
            _max_total_pixels=4_096,
            _cache_result=False,
        )

    render_width = render_mock.call_args.kwargs["width"]
    assert render_width <= 6
    assert rendered.shape[0] * rendered.shape[1] <= 4_096


def test_bounded_raster_accepts_percentage_canvas_with_finite_viewbox(
    tmp_path: Path,
) -> None:
    """A 100% canvas inherits its bounded aspect ratio from the viewBox."""

    pytest.importorskip("resvg_py")
    from core.pipeline.processing_ops import svg_rasterizer
    from core.vector_large_format import inspect_svg_large_format_support

    svg_path = tmp_path / "percentage-canvas-clip.svg"
    svg_path.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%"
viewBox="0 0 400 200">
  <defs><clipPath id="clip"><rect width="400" height="200"/></clipPath></defs>
  <rect width="400" height="200" clip-path="url(#clip)" fill="#336699"/>
</svg>
""",
        encoding="utf-8",
    )
    assert not inspect_svg_large_format_support(str(svg_path))[
        "native_tiling_supported"
    ]

    rendered = svg_rasterizer.rasterize_svg(
        str(svg_path),
        target_width_mm=4.0,
        pixels_per_mm=20.0,
        crop_to_content=False,
        _min_quality_px=1,
        _max_total_pixels=4_096,
        _cache_result=False,
    )

    assert rendered.shape == (40, 80, 4)
    assert rendered.shape[0] * rendered.shape[1] <= 4_096


@pytest.mark.parametrize(
    "canvas_attributes",
    [
        'width="99%" height="100%" viewBox="0 0 400 200"',
        'width="100%" height="99%" viewBox="0 0 400 200"',
        'width="100%" viewBox="0 0 400 200"',
        'width="100%" height="100%" viewBox="0 0 nan 200"',
        'width="100%" height="100%" viewBox="0 0 inf 200"',
        'width="100%" height="100%" viewBox="0 0 400"',
    ],
)
def test_percentage_canvas_ratio_fails_closed_without_exact_finite_contract(
    tmp_path: Path,
    canvas_attributes: str,
) -> None:
    """Only the exact 100%/100% plus finite viewBox contract is inferred."""

    from core.pipeline.processing_ops.svg_rasterizer import (
        _svg_canvas_height_width_ratio,
    )

    svg_path = tmp_path / "ambiguous-percentage-canvas.svg"
    svg_path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" {canvas_attributes}/>',
        encoding="utf-8",
    )
    assert _svg_canvas_height_width_ratio(str(svg_path)) is None
