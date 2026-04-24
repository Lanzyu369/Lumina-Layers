"""Regression test locking the material-archive branch of P03 to always
pass ``skip_post_blur=True`` into :func:`kmeans_quantize`.

The material-archive solver (and its persisted cache) consumes the
``unique_colors`` array downstream. ``cv2.medianBlur`` would inflate that
array by 10-100x on real images (per-channel median creates RGB triples
that are not in the K-Means palette), producing visible color banding at
higher layer counts because neighbouring pixels get routed to different
recipes. This test guards against accidental regressions of the fix made
in :mod:`core.pipeline.p03_core_processing`.

P03 耗材档案分支必须在调用 ``kmeans_quantize`` 时显式传
``skip_post_blur=True``。本回归测试防止未来改动误把这个关键参数丢掉。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image


class _FakeCache:
    """Minimal stand-in for ``MaterialSolverCache`` used in this test.

    We only need ``lookup`` to succeed so the branch reaches the write-back
    phase; downstream steps are exercised elsewhere.
    仅作为 ``MaterialSolverCache`` 的最小替身，使材料分支能跑完写回阶段。
    """

    palette_hash = "fake"
    grid_resolution = 1
    valid_cell_count = 1
    metadata: dict = {"built_at": "t", "mean_delta_e": 0.0, "max_delta_e": 0.0}

    def lookup(self, unique_colors: np.ndarray, materials):
        n = int(unique_colors.shape[0])
        matched_rgb = unique_colors.astype(np.uint8, copy=True)
        # 5 layers to match the default ``color_layers`` in our ctx builder.
        recipes = np.zeros((n, 5), dtype=np.int32)
        delta_e = np.zeros((n,), dtype=np.float32)
        return matched_rgb, recipes, delta_e


@pytest.fixture
def tiny_png(tmp_path: Path) -> str:
    """Write a 4x4 RGBA PNG the branch can load.
    生成 4x4 RGBA PNG，给耗材分支做输入。
    """
    arr = np.zeros((4, 4, 4), dtype=np.uint8)
    arr[..., :3] = [120, 60, 200]
    arr[..., 3] = 255
    path = tmp_path / "tiny.png"
    Image.fromarray(arr).save(path)
    return str(path)


def _material_archive_ctx(image_path: str) -> dict:
    """Build a minimal ctx dict for ``_run_material_archive_branch``.
    构造耗材档案分支所需的最小 ctx。
    """
    return {
        "image_path": image_path,
        "target_width_mm": 10.0,
        "modeling_mode": None,
        "quantize_colors": 8,
        "auto_bg": False,
        "bg_tol": 0,
        "_material_params": [object()],  # opaque; only used by cache/solver stubs
        "color_layers": 5,
        "layer_height_mm": 0.08,
        "material_substrate": "white",
        "material_source": "material_archive",
    }


def _fake_map_pixels_to_materials(
    quantized_image,
    unique_colors,
    matched_rgb_unique,
    recipes_unique,
    target_h,
    target_w,
):
    """Degenerate pixel-mapping stand-in: we only need shape-correct outputs.
    形状正确即可；本测试只关心 kmeans 调用参数。
    """
    matched_rgb = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    matched_rgb[:] = matched_rgb_unique[0] if matched_rgb_unique.shape[0] else 0
    layer_count = recipes_unique.shape[1] if recipes_unique.size else 5
    material_matrix = np.zeros((target_h, target_w, layer_count), dtype=np.int32)
    return matched_rgb, material_matrix


def test_material_archive_passes_skip_post_blur_true(tiny_png: str) -> None:
    """Material-archive branch must call ``kmeans_quantize`` with
    ``skip_post_blur=True`` to keep the quantization contract intact for
    the solver / cache lookup.
    耗材分支必须显式传 ``skip_post_blur=True``，保证给到 solver 的
    ``unique_colors`` 不被 medianBlur 膨胀。
    """
    from core.pipeline import p03_core_processing as p03_mod

    captured: dict = {}

    def fake_kmeans_quantize(rgb, n_colors, seed=42, *, skip_post_blur=False):
        captured["skip_post_blur"] = bool(skip_post_blur)
        captured["n_colors"] = int(n_colors)
        # Return a single-color output so unique_colors has exactly 1 entry.
        out = np.zeros_like(rgb)
        out[..., 0] = 10
        out[..., 1] = 20
        out[..., 2] = 30
        return out

    # Patch collaborators imported *inside* ``_run_material_archive_branch``.
    # We cannot patch the function-local alias ``kmeans_quantize`` directly;
    # instead we patch the underlying module attribute so the ``from X import
    # Y as kmeans_quantize`` resolves to our fake on each call.
    # (不能直接替换函数内的 local alias，必须替换源模块上的属性。)
    with patch(
        "core.pipeline.processing_ops.kmeans_quantizer.quantize_colors",
        side_effect=fake_kmeans_quantize,
    ), patch(
        "core.material_cache.load_material_solver_cache",
        return_value=_FakeCache(),
    ), patch(
        "core.material_lut_synthesis.map_pixels_to_materials",
        side_effect=_fake_map_pixels_to_materials,
    ):
        ctx = _material_archive_ctx(tiny_png)
        result = p03_mod._run_material_archive_branch(ctx)

    assert "skip_post_blur" in captured, (
        "kmeans_quantize was not invoked by the material-archive branch; "
        "patching target may be wrong."
    )
    assert captured["skip_post_blur"] is True, (
        "Material-archive branch must pass ``skip_post_blur=True`` to "
        "``kmeans_quantize``. Without this, ``cv2.medianBlur`` inflates the "
        "palette past ``quantize_colors`` and causes visible banding."
    )
    # Sanity: the branch actually wrote its outputs.
    assert result.get("matched_rgb") is not None
    assert result.get("material_matrix") is not None
    assert result.get("material_solver_info", {}).get("path") == "cache"
