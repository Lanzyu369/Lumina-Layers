"""Processing helper properties and real image result contracts.
图像处理辅助函数属性与真实处理结果契约测试。
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays


# ---------------------------------------------------------------------------
# Hypothesis 策略：生成小尺寸 uint8 RGB 图像数组
# ---------------------------------------------------------------------------

def _rgb_image_strategy(min_side=4, max_side=16):
    """生成 (H, W, 3) uint8 随机 RGB 图像数组。"""
    return st.tuples(
        st.integers(min_value=min_side, max_value=max_side),
        st.integers(min_value=min_side, max_value=max_side),
    ).flatmap(
        lambda hw: arrays(
            dtype=np.uint8,
            shape=(hw[0], hw[1], 3),
        )
    )


# ===========================================================================
# Property 9: processing_ops 模块独立性
# Feature: image-pipeline-modularization, Property 9: processing_ops 模块独立性
# **Validates: Requirements 10.2, 10.6**
# ===========================================================================

class TestProperty9ProcessingOpsIndependence:
    """验证 processing_ops 子模块可直接调用，无需实例化 LuminaImageProcessor。

    使用 Hypothesis 生成随机 numpy 数组（小尺寸），验证各函数可独立调用
    且输入输出 shape 一致。
    """

    # ── bilateral_filter ──────────────────────────────────────────────

    @given(rgb=_rgb_image_strategy(), sigma=st.floats(min_value=0.0, max_value=50.0))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_bilateral_filter_shape_preserved(self, rgb: np.ndarray, sigma: float):
        """bilateral_filter.apply_bilateral_filter 输入输出 shape 一致。"""
        from core.pipeline.processing_ops.bilateral_filter import apply_bilateral_filter

        result = apply_bilateral_filter(rgb, sigma)
        assert result.shape == rgb.shape, (
            f"bilateral_filter 输出 shape {result.shape} != 输入 shape {rgb.shape}"
        )
        assert result.dtype == np.uint8

    # ── median_filter ─────────────────────────────────────────────────

    @given(
        rgb=_rgb_image_strategy(),
        kernel_size=st.sampled_from([0, 1, 3, 5]),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_median_filter_shape_preserved(self, rgb: np.ndarray, kernel_size: int):
        """median_filter.apply_median_filter 输入输出 shape 一致。"""
        from core.pipeline.processing_ops.median_filter import apply_median_filter

        result = apply_median_filter(rgb, kernel_size)
        assert result.shape == rgb.shape, (
            f"median_filter 输出 shape {result.shape} != 输入 shape {rgb.shape}"
        )
        assert result.dtype == np.uint8

    # ── kmeans_quantizer ──────────────────────────────────────────────

    @given(data=st.data())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    def test_kmeans_quantizer_shape_preserved(self, data):
        """kmeans_quantizer.quantize_colors 输入输出 shape 一致。"""
        from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors

        h = data.draw(st.integers(min_value=4, max_value=12))
        w = data.draw(st.integers(min_value=4, max_value=12))
        rgb = data.draw(arrays(dtype=np.uint8, shape=(h, w, 3)))
        total_pixels = h * w
        # n_colors 必须 >= 2 且 <= 像素数
        max_colors = min(total_pixels, 8)
        n_colors = data.draw(st.integers(min_value=2, max_value=max_colors))

        result = quantize_colors(rgb, n_colors)
        assert result.shape == rgb.shape, (
            f"kmeans_quantizer 输出 shape {result.shape} != 输入 shape {rgb.shape}"
        )
        assert result.dtype == np.uint8

    # ── wireframe_extractor ───────────────────────────────────────────

    @given(
        rgb=_rgb_image_strategy(),
        pixel_scale=st.floats(min_value=0.01, max_value=1.0),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_wireframe_extractor_returns_bool_array(self, rgb: np.ndarray, pixel_scale: float):
        """wireframe_extractor.extract_wireframe_mask 返回 bool 数组。"""
        from core.pipeline.processing_ops.wireframe_extractor import extract_wireframe_mask

        h, w = rgb.shape[:2]
        result = extract_wireframe_mask(rgb, pixel_scale)
        assert result.shape == (h, w), (
            f"extract_wireframe_mask 输出 shape {result.shape} != 期望 ({h}, {w})"
        )
        assert result.dtype == np.bool_

@pytest.mark.parametrize("modeling_mode", ["HIGH_FIDELITY", "PIXEL"])
def test_process_image_result_contract(tmp_path: Path, modeling_mode: str) -> None:
    """Process an RGBA image with a real LUT and verify usable output arrays.
    使用真实 LUT 处理 RGBA 图片，验证返回数据可用于后续建模。
    """
    from config import ModelingMode
    from core.image_processing import LuminaImageProcessor

    lut = np.zeros((32, 3), dtype=np.uint8)
    lut[16:] = 255
    lut_path = tmp_path / "bw.npy"
    np.save(lut_path, lut)

    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[:, :2, 3] = 255
    rgba[:, 2:, :3] = 255
    image_path = tmp_path / "source.png"
    Image.fromarray(rgba).save(image_path)

    result = LuminaImageProcessor(str(lut_path), "BW").process_image(
        str(image_path),
        target_width_mm=1.0,
        modeling_mode=ModelingMode[modeling_mode],
        quantize_colors=2,
        blur_kernel=0,
        smooth_sigma=0,
    )

    required_keys = {
        "matched_rgb", "material_matrix", "mask_solid", "dimensions",
        "pixel_scale", "mode_info", "quantized_image",
    }
    assert required_keys <= result.keys()
    width, height = result["dimensions"]
    assert width > 0 and height > 0
    assert result["pixel_scale"] > 0
    assert result["matched_rgb"].shape == (height, width, 3)
    assert result["matched_rgb"].dtype == np.uint8
    assert result["quantized_image"].shape == (height, width, 3)
    assert result["quantized_image"].dtype == np.uint8
    assert result["material_matrix"].shape == (height, width, 5)
    assert np.issubdtype(result["material_matrix"].dtype, np.integer)
    mask = result["mask_solid"]
    assert mask.shape == (height, width)
    assert mask.dtype == np.bool_
    assert np.any(mask) and np.any(~mask)
    assert np.all(result["material_matrix"][~mask] == -1)
    assert np.any((result["matched_rgb"] == 0).all(axis=2) & mask)
