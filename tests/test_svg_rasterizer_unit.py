"""Regression tests for SVG rasterization edge cases."""

from __future__ import annotations

from pathlib import Path

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
