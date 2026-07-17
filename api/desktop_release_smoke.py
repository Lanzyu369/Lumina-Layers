"""Frozen desktop-backend smoke checks for required native mesh kernels."""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from core import vector_engine


class _SmokeColorTree:
    """Minimal deterministic color matcher for the self-contained SVG fixture."""

    n = 2

    @staticmethod
    def query(query: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        palette = np.asarray([[255, 0, 0], [0, 255, 0]], dtype=np.float64)
        distances = np.linalg.norm(palette - np.asarray(query)[0], axis=1)
        index = int(np.argmin(distances))
        return np.asarray([distances[index]]), np.asarray([index])


class _SmokeColorMatcher:
    """LUT-matcher surface required by ``VectorProcessor.analyze_svg``."""

    hue_matcher = None
    lut_path = "desktop-release-smoke.npy"
    lut_metadata = None
    lut_rgb = np.asarray([[255, 0, 0], [0, 255, 0]], dtype=np.uint8)
    ref_stacks = np.asarray([[0], [0]], dtype=np.int32)
    kdtree = _SmokeColorTree()

    @staticmethod
    def _rgb_to_lab(colors: np.ndarray) -> np.ndarray:
        return np.asarray(colors, dtype=np.float64).reshape(-1, 3)


def run_native_relief_smoke() -> dict[str, Any]:
    """Verify packaged native imports and a watertight SVG relief fast path.

    验证桌面打包产物能导入原生依赖，并真实走 SVG 浮雕快速路径生成水密底板。

    Returns:
        dict[str, Any]: JSON-safe smoke evidence.（可序列化的 smoke 证据。）

    Raises:
        RuntimeError: If imports, fast-path dispatch, or geometry checks fail.
            （导入、快速路径调度或几何检查失败。）
    """

    importlib.import_module("rasterio.features")
    importlib.import_module("manifold3d")

    fallback_called = False
    original_fallback = vector_engine._build_stepped_volume_mesh_python_prepared

    def reject_fallback(*_args, **_kwargs):
        nonlocal fallback_called
        fallback_called = True
        raise RuntimeError("desktop release smoke reached Python relief fallback")

    vector_engine._build_stepped_volume_mesh_python_prepared = reject_fallback
    try:
        with tempfile.TemporaryDirectory(prefix="lumina-desktop-smoke-") as temp_dir:
            svg_path = Path(temp_dir) / "two-height-relief.svg"
            svg_path.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="5" '
                'viewBox="0 0 10 5">'
                '<rect x="0" y="0" width="5" height="5" fill="#ff0000"/>'
                '<rect x="5" y="0" width="5" height="5" fill="#00ff00"/>'
                "</svg>",
                encoding="utf-8",
            )
            processor = vector_engine.VectorProcessor.from_img_processor(
                _SmokeColorMatcher(),
                "4-Color (RYBW)",
            )
            analysis = processor.analyze_svg(str(svg_path), target_width_mm=10.0)
        meshes_by_slot = vector_engine.VectorProcessor._build_relief_meshes(
            matched_shapes=analysis.matched_shapes,
            num_layers=1,
            layer_h=0.2,
            num_channels=1,
            slot_names=["White"],
            scale_factor=1.0,
            backing_color_id=0,
            default_height_mm=1.0,
            height_mode="color",
            color_height_map={"#ff0000": 1.0, "#00ff00": 2.0},
            heightmap_path=None,
            heightmap_max_height=None,
            bbox=(0.0, 0.0, 10.0, 5.0),
            extrude_cache={},
        )
        board = vector_engine._concatenate_meshes_fast(
            meshes_by_slot["Board"]["meshes"],
        )
    finally:
        vector_engine._build_stepped_volume_mesh_python_prepared = original_fallback

    expected_bounds = np.asarray([[0.0, 0.0, 0.0], [10.0, 5.0, 1.8]])
    if fallback_called:
        raise RuntimeError("desktop release smoke used Python relief fallback")
    if not board.is_watertight:
        raise RuntimeError("desktop release smoke produced a non-watertight Board")
    if not np.allclose(board.bounds, expected_bounds, atol=1e-6):
        raise RuntimeError(f"desktop release smoke bounds mismatch: {board.bounds!r}")
    if not np.isclose(float(board.volume), 65.0, rtol=1e-6, atol=1e-6):
        raise RuntimeError(
            f"desktop release smoke volume mismatch: {float(board.volume)!r}",
        )

    return {
        "status": "ok",
        "native_kernel": "manifold3d",
        "fixture": "two-rectangle-svg-relief",
        "rasterio_features_imported": True,
        "fallback_called": False,
        "board_watertight": True,
        "board_faces": int(len(board.faces)),
        "board_vertices": int(len(board.vertices)),
        "board_volume": float(board.volume),
    }
