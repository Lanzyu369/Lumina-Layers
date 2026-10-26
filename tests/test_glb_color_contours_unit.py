"""Regression tests for reusable GLB preview colour contour extraction.

Keeps the analytic Vector preview contour contract aligned with the
segmented GLB renderer so keychain loops and colour highlights use the same
canvas coordinates.
保证解析式矢量预览的轮廓契约与分段 GLB 渲染器一致，使挂环定位和颜色
高亮使用同一套画布坐标。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from core.pipeline.s11_glb_preview import extract_color_contours, generate_segmented_glb


def _irregular_raster() -> tuple[np.ndarray, np.ndarray]:
    matched = np.zeros((30, 30, 3), dtype=np.uint8)
    mask_solid = np.zeros((30, 30), dtype=bool)
    matched[0:30, 1:5] = [214, 40, 40]
    mask_solid[0:30, 1:5] = True
    matched[11:30, 7:29] = [29, 78, 216]
    mask_solid[11:30, 7:29] = True
    return matched, mask_solid


def test_extract_color_contours_matches_segmented_glb_contours(tmp_path: Path) -> None:
    matched, mask_solid = _irregular_raster()
    cache = {
        "matched_rgb": matched.copy(),
        "mask_solid": mask_solid.copy(),
        "target_w": 30,
        "target_width_mm": 60.0,
    }

    glb_path = generate_segmented_glb(cache, output_path=str(tmp_path / "segmented.glb"))

    assert glb_path is not None
    assert extract_color_contours(matched, mask_solid, 60.0) == cache["color_contours"]


def test_extract_color_contours_uses_bottom_left_canvas_millimetres() -> None:
    matched, mask_solid = _irregular_raster()

    contours = extract_color_contours(matched, mask_solid, 60.0)

    body = np.array(contours["1d4ed8"][0])
    spike = np.array(contours["d62828"][0])
    # 2 mm per pixel: the body top sits 11 px below the canvas top edge.
    assert body[:, 1].max() == 38.0
    assert spike[:, 1].max() == 60.0


def test_extract_color_contours_rejects_mismatched_inputs() -> None:
    matched, _mask_solid = _irregular_raster()

    assert extract_color_contours(matched, np.ones((2, 2), dtype=bool), 60.0) == {}
    assert extract_color_contours(None, None, 60.0) == {}
