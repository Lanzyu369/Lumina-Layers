"""Regression tests for SVG rasterization edge cases."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


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
