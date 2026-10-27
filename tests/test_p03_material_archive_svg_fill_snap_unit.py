"""Regression test for the SVG fill-palette snapping branch in
``_run_material_archive_branch``.

When an SVG is processed in material-archive mode, the rasterizer (resvg)
produces anti-aliased edges where neighbouring fills linearly blend. The
historical K-Means path with a large ``quantize_colors`` budget (e.g. 256)
allocated clusters to those transition bands, which then resolved to
unrelated material recipes and produced visible "noise pixels not following
the SVG strokes" in previews/exports.

This test locks in the fix: SVG inputs MUST go through fill-palette
snapping, producing ``unique_colors`` bounded by the SVG's actual fill set
regardless of how large ``quantize_colors`` is.

SVG 输入在耗材档案模式下必须走填充色板吸附，量化预算再大也不能让 unique
颜色数超过 SVG 真实填充色数。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest


_SVG_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
  <rect x="0" y="0" width="100" height="100" fill="#ffffff"/>
  <circle cx="30" cy="30" r="20" fill="#ff0000"/>
  <circle cx="70" cy="70" r="20" fill="#0000ff"/>
  <rect x="10" y="60" width="30" height="30" fill="#00aa00"/>
</svg>
"""


class _FakeCache:
    """Stand-in for ``MaterialSolverCache`` with a pass-through ``lookup``.
    透明替身：把 unique_colors 原样作为 matched_rgb 返回，不影响测试断言。
    """

    palette_hash = "fake"
    grid_resolution = 1
    valid_cell_count = 1
    metadata: dict = {"built_at": "t", "mean_delta_e": 0.0, "max_delta_e": 0.0}

    def lookup(self, unique_colors: np.ndarray, materials):
        n = int(unique_colors.shape[0])
        matched_rgb = unique_colors.astype(np.uint8, copy=True)
        recipes = np.zeros((n, 5), dtype=np.int32)
        delta_e = np.zeros((n,), dtype=np.float32)
        return matched_rgb, recipes, delta_e


def _fake_map_pixels_to_materials(
    quantized_image,
    unique_colors,
    matched_rgb_unique,
    recipes_unique,
    target_h,
    target_w,
):
    """Shape-correct stand-in; details unrelated to this test.
    形状正确即可，本测试只关心 unique_colors 数量。
    """
    matched_rgb = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    if matched_rgb_unique.shape[0]:
        matched_rgb[:] = matched_rgb_unique[0]
    layer_count = recipes_unique.shape[1] if recipes_unique.size else 5
    material_matrix = np.zeros((target_h, target_w, layer_count), dtype=np.int32)
    return matched_rgb, material_matrix


@pytest.fixture
def tiny_svg(tmp_path: Path) -> str:
    """Write a small multi-fill SVG that resvg can rasterize.
    写一个多填充色 SVG 给 resvg 栅格化。
    """
    path = tmp_path / "fills.svg"
    path.write_text(_SVG_TEMPLATE, encoding="utf-8")
    return str(path)


def _material_archive_ctx(image_path: str, quantize_colors: int) -> dict:
    """Build a minimal ctx dict for ``_run_material_archive_branch``.
    构造耗材档案分支所需的最小 ctx。
    """
    return {
        "image_path": image_path,
        "target_width_mm": 50.0,
        "modeling_mode": None,
        "quantize_colors": quantize_colors,
        "auto_bg": False,
        "bg_tol": 0,
        "_material_params": [object()],
        "color_layers": 5,
        "layer_height_mm": 0.08,
        "material_substrate": "white",
        "material_source": "material_archive",
    }


def _run_branch(svg_path: str, quantize_colors: int) -> dict:
    """Run the material-archive branch with collaborators stubbed.
    带桩运行耗材档案分支。
    """
    pytest.importorskip("resvg_py")

    from core.pipeline import p03_core_processing as p03_mod

    with patch(
        "core.material_cache.load_material_solver_cache_with_fallback",
        return_value=(_FakeCache(), 1),
    ), patch(
        "core.material_lut_synthesis.map_pixels_to_materials",
        side_effect=_fake_map_pixels_to_materials,
    ):
        ctx = _material_archive_ctx(svg_path, quantize_colors)
        return p03_mod._run_material_archive_branch(ctx)


def test_svg_fill_snap_caps_unique_colors_at_fill_palette(tiny_svg: str) -> None:
    """SVG with 4 fills must produce <=4 unique opaque colors even at q=256.

    Without the fill-palette snap, K-Means at quantize=256 would allocate
    cluster centers to anti-aliased edge pixels, yielding tens to hundreds
    of unique RGB triples and producing the "noise not following the strokes"
    symptom downstream.

    SVG 仅 4 种填充色，量化预算给到 256 也必须保证可见区域 unique 颜色 <=4，
    否则就是抗锯齿过渡带又被聚成独立簇，杂色 bug 复发。
    """
    result = _run_branch(tiny_svg, quantize_colors=256)

    assert result.get("error") is None, result.get("error")
    quantized = result["quantized_image"]
    mask_solid = result["mask_solid"]
    assert quantized is not None and mask_solid is not None

    visible_pixels = quantized[mask_solid].reshape(-1, 3)
    unique_visible = np.unique(visible_pixels, axis=0)
    # SVG has 4 fills (white bg, red, blue, green). Allow exact match; any
    # extra entry indicates the snap regressed and edge blends leaked
    # through.
    assert unique_visible.shape[0] <= 4, (
        f"SVG fill-palette snap produced {unique_visible.shape[0]} unique "
        "opaque colors, expected <=4. Anti-aliased edge pixels are "
        "leaking past the snap; this is the 'noise not following SVG "
        "strokes' regression."
    )

    # Reverse-direction guard: ensure all four real fills survive. Without
    # this we'd silently pass a degenerate "snap everything to one color"
    # bug (unique_visible.shape[0] == 1 satisfies the upper bound too).
    # 反向哨兵：防止「全图被吸到同一种色」这类反向回归 (unique=1 也满足上界)。
    expected_fills = {
        (255, 255, 255),  # white bg
        (255, 0, 0),      # red circle
        (0, 0, 255),      # blue circle
        (0, 170, 0),      # green rect
    }
    got_fills = {tuple(int(x) for x in row) for row in unique_visible}
    missing = expected_fills - got_fills
    assert not missing, (
        f"Expected SVG fills {expected_fills} all present in output, "
        f"but missing {missing}. The snap collapsed real fills together; "
        f"got_fills={got_fills}."
    )


def test_svg_fill_snap_respects_quantize_budget_below_palette(
    tiny_svg: str,
) -> None:
    """When quantize budget < SVG fill count, palette must be reduced.
    量化预算 < 真实填充色数时，色板必须按预算收紧。
    """
    result = _run_branch(tiny_svg, quantize_colors=2)
    assert result.get("error") is None, result.get("error")
    quantized = result["quantized_image"]
    mask_solid = result["mask_solid"]
    assert quantized is not None and mask_solid is not None

    visible_pixels = quantized[mask_solid].reshape(-1, 3)
    unique_visible = np.unique(visible_pixels, axis=0)
    assert unique_visible.shape[0] <= 2, (
        f"Quantize budget=2 must cap unique opaque colors at 2, got "
        f"{unique_visible.shape[0]}."
    )
