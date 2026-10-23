"""Regression: full-path SVG exports must keep the preview's physical scale.

SVG rasterization alpha-crops transparent canvas margins. The 3D preview
(``s11_glb_preview._resolve_glb_pixel_scale``) and the preview-analysis reuse
paths map the cropped raster with ``target_width_mm / cropped_width``. The full
material-archive and LUT SVG branches used a fixed ``1 / svg_pixels_per_mm``,
so a margined SVG exported smaller than previewed (LUM-202610-1ed2c73a: 79.4 mm
preview vs 53.6 mm 3MF once fridge magnets forced the full path).

SVG 光栅化会裁掉透明画布边距。3D 预览与预览分析复用路径按
``target_width_mm / 裁后宽度`` 换算；完整耗材/LUT SVG 分支却固定使用
``1 / svg_pixels_per_mm``，导致带边距 SVG 导出比预览小。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from config import ModelingMode

pytest.importorskip("resvg_py")

TARGET_WIDTH_MM = 20.0

# Content occupies the middle half of the canvas, so the alpha crop removes
# about half of the rendered width.
# 内容只占画布中间一半，alpha 裁切会去掉约一半渲染宽度。
_MARGINED_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80" viewBox="0 0 100 80">'
    '<rect x="25" y="20" width="50" height="40" fill="#cc0000"/></svg>'
)
_FULL_BLEED_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80" viewBox="0 0 100 80">'
    '<rect x="0" y="0" width="100" height="80" fill="#cc0000"/></svg>'
)


def _write(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _preview_scale(width_px: int) -> float:
    from core.pipeline.s11_glb_preview import _resolve_glb_pixel_scale

    return _resolve_glb_pixel_scale(TARGET_WIDTH_MM, width_px)


class _FakeCache:
    """Pass-through ``MaterialSolverCache`` stand-in."""

    palette_hash = "fake"
    grid_resolution = 1
    valid_cell_count = 1
    metadata: dict = {"built_at": "t", "mean_delta_e": 0.0, "max_delta_e": 0.0}

    def lookup(self, unique_colors: np.ndarray, materials):
        n = int(unique_colors.shape[0])
        return (
            unique_colors.astype(np.uint8, copy=True),
            np.zeros((n, 5), dtype=np.int32),
            np.zeros((n,), dtype=np.float32),
        )


def _fake_map_pixels_to_materials(
    quantized_image, unique_colors, matched_rgb_unique, recipes_unique, target_h, target_w
):
    matched_rgb = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    material_matrix = np.zeros((target_h, target_w, 5), dtype=np.int32)
    return matched_rgb, material_matrix


def _run_material_branch(image_path: str) -> dict:
    from core.pipeline import p03_core_processing as p03_mod

    ctx = {
        "image_path": image_path,
        "target_width_mm": TARGET_WIDTH_MM,
        "modeling_mode": ModelingMode.HIGH_FIDELITY,
        "svg_pixels_per_mm": 10,
        "quantize_colors": 16,
        "auto_bg": False,
        "bg_tol": 0,
        "_material_params": [object()],
        "color_layers": 5,
        "layer_height_mm": 0.08,
        "material_substrate": "white",
        "material_source": "material_archive",
    }
    with patch(
        "core.material_cache.load_material_solver_cache_with_fallback",
        return_value=(_FakeCache(), 1),
    ), patch(
        "core.material_lut_synthesis.map_pixels_to_materials",
        side_effect=_fake_map_pixels_to_materials,
    ):
        result = p03_mod._run_material_archive_branch(ctx)
    assert result.get("error") is None, result.get("error")
    return result


def _run_lut_processor(tmp_path: Path, image_path: str) -> dict:
    from core.image_processing import LuminaImageProcessor

    lut = np.zeros((32, 3), dtype=np.uint8)
    lut[16:] = 255
    lut_path = tmp_path / "bw.npy"
    np.save(lut_path, lut)
    return LuminaImageProcessor(str(lut_path), "BW", svg_pixels_per_mm=10).process_image(
        image_path,
        target_width_mm=TARGET_WIDTH_MM,
        modeling_mode=ModelingMode.HIGH_FIDELITY,
        quantize_colors=2,
        blur_kernel=0,
        smooth_sigma=0,
    )


def test_material_margined_svg_matches_preview_scale(tmp_path: Path) -> None:
    result = _run_material_branch(_write(tmp_path, "margined.svg", _MARGINED_SVG))

    target_w = int(result["target_w"])
    assert target_w < 150  # alpha crop removed the margin
    assert result["pixel_scale"] == pytest.approx(_preview_scale(target_w))
    assert result["pixel_scale"] * target_w == pytest.approx(TARGET_WIDTH_MM)


def test_lut_margined_svg_matches_preview_scale(tmp_path: Path) -> None:
    result = _run_lut_processor(tmp_path, _write(tmp_path, "margined.svg", _MARGINED_SVG))

    target_w = int(result["dimensions"][0])
    assert target_w < 150  # alpha crop removed the margin
    assert result["pixel_scale"] == pytest.approx(_preview_scale(target_w))
    assert result["pixel_scale"] * target_w == pytest.approx(TARGET_WIDTH_MM)


def test_material_full_bleed_svg_keeps_sampling_scale(tmp_path: Path) -> None:
    result = _run_material_branch(_write(tmp_path, "full.svg", _FULL_BLEED_SVG))

    assert int(result["target_w"]) == 200
    assert result["pixel_scale"] == pytest.approx(0.1)


def test_lut_full_bleed_svg_keeps_sampling_scale(tmp_path: Path) -> None:
    result = _run_lut_processor(tmp_path, _write(tmp_path, "full.svg", _FULL_BLEED_SVG))

    assert int(result["dimensions"][0]) == 200
    assert result["pixel_scale"] == pytest.approx(0.1)


def test_raster_input_keeps_fixed_high_fidelity_scale(tmp_path: Path) -> None:
    rgba = np.zeros((40, 50, 4), dtype=np.uint8)
    rgba[10:30, 12:38] = (204, 0, 0, 255)
    image_path = tmp_path / "margined.png"
    Image.fromarray(rgba).save(image_path)

    lut_result = _run_lut_processor(tmp_path, str(image_path))
    material_result = _run_material_branch(str(image_path))

    assert int(lut_result["dimensions"][0]) == 200
    assert lut_result["pixel_scale"] == pytest.approx(0.1)
    assert int(material_result["target_w"]) == 200
    assert material_result["pixel_scale"] == pytest.approx(0.1)
