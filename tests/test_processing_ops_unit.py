"""
Unit tests for processing_ops submodules.
processing_ops 子模块的单元测试。

覆盖范围：bilateral_filter, median_filter, kmeans_quantizer
测试边界情况：空数组、单像素图像、极端参数值

_需求: 10.2, 10.6_
"""

from types import SimpleNamespace

import numpy as np
import pytest



# ===========================================================================
# bilateral_filter 单元测试
# ===========================================================================

class TestBilateralFilter:
    """bilateral_filter.apply_bilateral_filter 的单元测试。"""

    def test_sigma_zero_returns_original(self):
        """sigma=0 时返回原始数组（无滤波）。"""
        from core.pipeline.processing_ops.bilateral_filter import apply_bilateral_filter

        rgb = np.array([[[100, 150, 200], [50, 60, 70]],
                        [[10, 20, 30], [255, 255, 255]]], dtype=np.uint8)
        result = apply_bilateral_filter(rgb, sigma=0.0)
        np.testing.assert_array_equal(result, rgb)

    def test_sigma_positive_returns_uint8_same_shape(self):
        """sigma>0 时返回 uint8 数组且 shape 不变。"""
        from core.pipeline.processing_ops.bilateral_filter import apply_bilateral_filter

        rgb = np.random.randint(0, 256, (10, 10, 3), dtype=np.uint8)
        result = apply_bilateral_filter(rgb, sigma=25.0)
        assert result.shape == rgb.shape
        assert result.dtype == np.uint8

    def test_single_pixel_image(self):
        """单像素图像（1x1x3）不崩溃。"""
        from core.pipeline.processing_ops.bilateral_filter import apply_bilateral_filter

        rgb = np.array([[[128, 64, 32]]], dtype=np.uint8)
        result = apply_bilateral_filter(rgb, sigma=10.0)
        assert result.shape == (1, 1, 3)
        assert result.dtype == np.uint8

    def test_all_black_image(self):
        """全黑图像滤波后仍为全黑。"""
        from core.pipeline.processing_ops.bilateral_filter import apply_bilateral_filter

        rgb = np.zeros((8, 8, 3), dtype=np.uint8)
        result = apply_bilateral_filter(rgb, sigma=30.0)
        np.testing.assert_array_equal(result, rgb)

    def test_all_white_image(self):
        """全白图像滤波后仍为全白。"""
        from core.pipeline.processing_ops.bilateral_filter import apply_bilateral_filter

        rgb = np.full((8, 8, 3), 255, dtype=np.uint8)
        result = apply_bilateral_filter(rgb, sigma=30.0)
        np.testing.assert_array_equal(result, rgb)


# ===========================================================================
# median_filter 单元测试
# ===========================================================================

class TestMedianFilter:
    """median_filter.apply_median_filter 的单元测试。"""

    def test_kernel_zero_returns_original(self):
        """kernel_size=0 时返回原始数组（无滤波）。"""
        from core.pipeline.processing_ops.median_filter import apply_median_filter

        rgb = np.array([[[100, 150, 200], [50, 60, 70]],
                        [[10, 20, 30], [255, 255, 255]]], dtype=np.uint8)
        result = apply_median_filter(rgb, kernel_size=0)
        np.testing.assert_array_equal(result, rgb)

    def test_kernel_3_returns_uint8_same_shape(self):
        """kernel_size=3 时返回 uint8 数组且 shape 不变。"""
        from core.pipeline.processing_ops.median_filter import apply_median_filter

        rgb = np.random.randint(0, 256, (10, 10, 3), dtype=np.uint8)
        result = apply_median_filter(rgb, kernel_size=3)
        assert result.shape == rgb.shape
        assert result.dtype == np.uint8

    def test_even_kernel_adjusted_to_odd(self):
        """偶数 kernel_size 自动调整为奇数，不崩溃。"""
        from core.pipeline.processing_ops.median_filter import apply_median_filter

        rgb = np.random.randint(0, 256, (8, 8, 3), dtype=np.uint8)
        # kernel_size=4 应被调整为 5
        result = apply_median_filter(rgb, kernel_size=4)
        assert result.shape == rgb.shape
        assert result.dtype == np.uint8

    def test_single_pixel_image(self):
        """单像素图像（1x1x3）不崩溃。"""
        from core.pipeline.processing_ops.median_filter import apply_median_filter

        rgb = np.array([[[128, 64, 32]]], dtype=np.uint8)
        result = apply_median_filter(rgb, kernel_size=3)
        assert result.shape == (1, 1, 3)
        assert result.dtype == np.uint8

    def test_all_black_image(self):
        """全黑图像滤波后仍为全黑。"""
        from core.pipeline.processing_ops.median_filter import apply_median_filter

        rgb = np.zeros((8, 8, 3), dtype=np.uint8)
        result = apply_median_filter(rgb, kernel_size=5)
        np.testing.assert_array_equal(result, rgb)

    def test_all_white_image(self):
        """全白图像滤波后仍为全白。"""
        from core.pipeline.processing_ops.median_filter import apply_median_filter

        rgb = np.full((8, 8, 3), 255, dtype=np.uint8)
        result = apply_median_filter(rgb, kernel_size=5)
        np.testing.assert_array_equal(result, rgb)



# ===========================================================================
# kmeans_quantizer 单元测试
# ===========================================================================

class TestKmeansQuantizer:
    """kmeans_quantizer.quantize_colors 的单元测试。"""

    def test_n_colors_2_outputs_at_most_2_unique(self):
        """n_colors=2 时输出最多 2 种唯一颜色。"""
        from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors

        rgb = np.random.randint(0, 256, (8, 8, 3), dtype=np.uint8)
        result = quantize_colors(rgb, n_colors=2)
        unique = np.unique(result.reshape(-1, 3), axis=0)
        assert len(unique) <= 2

    def test_uniform_color_stays_uniform(self):
        """全同色图像量化后仍为同色（允许 medianBlur 后处理的 ±1 偏差）。"""
        from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors

        rgb = np.full((8, 8, 3), [100, 150, 200], dtype=np.uint8)
        result = quantize_colors(rgb, n_colors=4)
        # medianBlur 后处理可能引入 ±1 的微小偏差，验证所有像素接近原色
        diff = np.abs(result.astype(int) - rgb.astype(int))
        assert diff.max() <= 1, f"全同色图像量化偏差过大: max_diff={diff.max()}"

    def test_output_shape_matches_input(self):
        """输出 shape 与输入一致。"""
        from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors

        rgb = np.random.randint(0, 256, (12, 10, 3), dtype=np.uint8)
        result = quantize_colors(rgb, n_colors=4)
        assert result.shape == rgb.shape

    def test_output_dtype_uint8(self):
        """输出 dtype 为 uint8。"""
        from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors

        rgb = np.random.randint(0, 256, (8, 8, 3), dtype=np.uint8)
        result = quantize_colors(rgb, n_colors=3)
        assert result.dtype == np.uint8

    def test_single_pixel_image(self):
        """单像素图像（1x1x3）不崩溃。"""
        from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors

        rgb = np.array([[[128, 64, 32]]], dtype=np.uint8)
        # n_colors=1 时 cv2.kmeans 需要至少 1 个 center
        # 但 n_colors 不能超过像素数，这里 1 像素只能 n_colors=1
        # 实际上 cv2.kmeans 要求 n_colors >= 1
        # 但设计中 n_colors >= 2，单像素时 n_colors 不能超过 1
        # 这里测试 n_colors=1 的边界
        result = quantize_colors(rgb, n_colors=1)
        assert result.shape == (1, 1, 3)
        assert result.dtype == np.uint8

    def test_n_colors_larger_than_pixel_count_is_clamped(self):
        """Requested colors above pixel count should not crash OpenCV kmeans."""
        from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors

        rgb = np.array(
            [
                [[255, 0, 0], [0, 255, 0]],
                [[0, 0, 255], [255, 255, 0]],
            ],
            dtype=np.uint8,
        )

        result = quantize_colors(rgb, n_colors=48)

        assert result.shape == rgb.shape
        assert result.dtype == np.uint8
        unique = np.unique(result.reshape(-1, 3), axis=0)
        assert len(unique) <= rgb.shape[0] * rgb.shape[1]

    def test_unique_colors_within_budget_skip_opencv_kmeans(self, monkeypatch):
        """Images already within the palette budget should pass through exactly."""
        from core.pipeline.processing_ops import kmeans_quantizer

        colors = np.array(
            [
                [255, 0, 0],
                [0, 255, 0],
                [0, 0, 255],
                [255, 255, 0],
            ],
            dtype=np.uint8,
        )
        idx = np.indices((32, 32)).sum(axis=0) % len(colors)
        rgb = colors[idx]

        def _fail_kmeans(*_args, **_kwargs):
            raise AssertionError("cv2.kmeans should be skipped")

        monkeypatch.setattr(kmeans_quantizer.cv2, "kmeans", _fail_kmeans)

        result = kmeans_quantizer.quantize_colors(rgb, n_colors=8)

        np.testing.assert_array_equal(result, rgb)

    def test_all_black_image(self):
        """全黑图像量化后仍为全黑。"""
        from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors

        rgb = np.zeros((8, 8, 3), dtype=np.uint8)
        result = quantize_colors(rgb, n_colors=2)
        unique = np.unique(result.reshape(-1, 3), axis=0)
        assert len(unique) == 1
        np.testing.assert_array_equal(unique[0], [0, 0, 0])

    def test_all_white_image(self):
        """全白图像量化后仍为全白。"""
        from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors

        rgb = np.full((8, 8, 3), 255, dtype=np.uint8)
        result = quantize_colors(rgb, n_colors=2)
        unique = np.unique(result.reshape(-1, 3), axis=0)
        assert len(unique) == 1
        np.testing.assert_array_equal(unique[0], [255, 255, 255])


class TestHighFidelityImageProcessing:
    """LuminaImageProcessor high-fidelity hot-path tests."""

    def test_unique_color_extraction_avoids_axis_row_unique(self, monkeypatch):
        """High-fidelity unique extraction should use packed RGB, not axis=0 rows."""
        from core import image_processing
        from core.image_processing import LuminaImageProcessor

        original_unique = image_processing.np.unique

        def unique_spy(*args, **kwargs):
            if kwargs.get("axis") == 0:
                raise AssertionError("row-wise np.unique is too slow for high-fidelity colors")
            return original_unique(*args, **kwargs)

        monkeypatch.setattr(image_processing.np, "unique", unique_spy)
        monkeypatch.setattr(image_processing, "apply_bilateral_filter", lambda rgb, _sigma: rgb)
        monkeypatch.setattr(image_processing, "apply_median_filter", lambda rgb, _kernel: rgb)
        monkeypatch.setattr(image_processing, "kmeans_quantize", lambda rgb, *_args, **_kwargs: rgb.copy())

        colors = np.array(
            [
                [255, 0, 0],
                [0, 0, 255],
                [255, 255, 0],
            ],
            dtype=np.uint8,
        )
        idx = np.indices((12, 12)).sum(axis=0) % len(colors)
        rgb = colors[idx]
        processor = SimpleNamespace(use_lut_constrained=False, _last_unique_colors=0)

        quantized, unique_colors, processed = LuminaImageProcessor._prepare_high_fidelity_images(
            processor,
            rgb,
            8,
            0,
            10,
        )

        np.testing.assert_array_equal(quantized, rgb)
        np.testing.assert_array_equal(processed, rgb)
        assert processor._last_unique_colors == 3
        assert {tuple(color) for color in unique_colors.tolist()} == {
            (255, 0, 0),
            (0, 0, 255),
            (255, 255, 0),
        }
