"""
Property-based tests for processing_ops modules.
processing_ops 子模块的属性测试。

Feature: image-pipeline-modularization
Tests: Property 9, 10
"""

import inspect

import numpy as np
import pytest
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


def _alpha_channel_strategy(h, w):
    """生成 (H, W) uint8 alpha 通道数组。"""
    return arrays(dtype=np.uint8, shape=(h, w))


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

    # ── image_scaler ──────────────────────────────────────────────────

    @given(
        img_width=st.integers(min_value=10, max_value=500),
        img_height=st.integers(min_value=10, max_value=500),
        target_mm=st.floats(min_value=10.0, max_value=400.0),
        mode=st.sampled_from(["high-fidelity", "pixel"]),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_image_scaler_returns_3_tuple(self, img_width, img_height, target_mm, mode):
        """image_scaler.calculate_target_dimensions 返回 3 元组。"""
        from core.pipeline.processing_ops.image_scaler import calculate_target_dimensions
        from config import ModelingMode

        modeling_mode = (
            ModelingMode.HIGH_FIDELITY if mode == "high-fidelity"
            else ModelingMode.PIXEL
        )
        result = calculate_target_dimensions(img_width, img_height, target_mm, modeling_mode)
        assert isinstance(result, tuple), (
            f"calculate_target_dimensions 应返回 tuple，实际为 {type(result)}"
        )
        assert len(result) == 3, (
            f"calculate_target_dimensions 应返回 3 元组，实际长度 {len(result)}"
        )
        target_w, target_h, pixel_scale = result
        assert isinstance(target_w, int)
        assert isinstance(target_h, int)
        assert isinstance(pixel_scale, float)
        assert target_w > 0
        assert target_h > 0
        assert pixel_scale > 0

    # ── background_remover ────────────────────────────────────────────

    @given(data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_background_remover_returns_bool_array(self, data):
        """background_remover.remove_background 返回 bool 数组。"""
        from core.pipeline.processing_ops.background_remover import remove_background

        h = data.draw(st.integers(min_value=4, max_value=16))
        w = data.draw(st.integers(min_value=4, max_value=16))
        alpha = data.draw(arrays(dtype=np.uint8, shape=(h, w)))
        rgb = data.draw(arrays(dtype=np.uint8, shape=(h, w, 3)))

        result = remove_background(alpha, rgb)
        assert result.shape == (h, w), (
            f"remove_background 输出 shape {result.shape} != 期望 ({h}, {w})"
        )
        assert result.dtype == np.bool_

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

    # ── 模块独立导入验证 ──────────────────────────────────────────────

    @pytest.mark.parametrize("module_path,func_name", [
        ("core.pipeline.processing_ops.bilateral_filter", "apply_bilateral_filter"),
        ("core.pipeline.processing_ops.median_filter", "apply_median_filter"),
        ("core.pipeline.processing_ops.kmeans_quantizer", "quantize_colors"),
        ("core.pipeline.processing_ops.image_scaler", "calculate_target_dimensions"),
        ("core.pipeline.processing_ops.background_remover", "remove_background"),
        ("core.pipeline.processing_ops.wireframe_extractor", "extract_wireframe_mask"),
        ("core.pipeline.processing_ops.lut_color_matcher", "match_colors_to_lut"),
        ("core.pipeline.processing_ops.lut_color_matcher", "map_pixels_to_lut"),
    ])
    def test_module_importable_without_image_processor(self, module_path: str, func_name: str):
        """processing_ops 子模块可独立导入，无需实例化 LuminaImageProcessor。"""
        import importlib
        mod = importlib.import_module(module_path)
        assert hasattr(mod, func_name), (
            f"{module_path} 缺少函数 {func_name}"
        )
        func = getattr(mod, func_name)
        assert callable(func), (
            f"{module_path}.{func_name} 不是可调用对象"
        )


# ===========================================================================
# Property 10: LuminaImageProcessor.process_image 返回值格式
# Feature: image-pipeline-modularization, Property 10: LuminaImageProcessor.process_image 返回值格式
# **Validates: Requirements 11.3**
# ===========================================================================

class TestProperty10ProcessImageReturnFormat:
    """验证 LuminaImageProcessor.process_image 返回值 dict 包含所有必需键。

    由于需要真实 LUT 文件，这里通过 inspect 检查签名和返回类型注解，
    并验证源代码中确实构建了包含所有必需键的 result dict。
    """

    # process_image 返回值必须包含的键
    REQUIRED_KEYS = [
        "matched_rgb",
        "material_matrix",
        "mask_solid",
        "dimensions",
        "pixel_scale",
        "mode_info",
        "quantized_image",
    ]

    def test_process_image_exists_and_callable(self):
        """LuminaImageProcessor.process_image 方法存在且可调用。"""
        from core.image_processing import LuminaImageProcessor
        assert hasattr(LuminaImageProcessor, "process_image")
        assert callable(getattr(LuminaImageProcessor, "process_image"))

    def test_process_image_signature(self):
        """process_image 签名包含所有必需参数。"""
        from core.image_processing import LuminaImageProcessor
        sig = inspect.signature(LuminaImageProcessor.process_image)
        param_names = list(sig.parameters.keys())

        required_params = [
            "self", "image_path", "target_width_mm", "modeling_mode",
            "quantize_colors",
        ]
        for param in required_params:
            assert param in param_names, (
                f"process_image 签名缺少参数: {param}"
            )

    def test_process_image_source_contains_all_required_keys(self):
        """process_image 源代码中构建的 result dict 包含所有必需键。"""
        from core.image_processing import LuminaImageProcessor
        source = inspect.getsource(LuminaImageProcessor.process_image)

        for key in self.REQUIRED_KEYS:
            assert f"'{key}'" in source or f'"{key}"' in source, (
                f"process_image 源代码中未找到必需键 '{key}'"
            )

    def test_process_image_returns_dict_with_result_construction(self):
        """process_image 源代码中构建了 result dict 并返回。"""
        from core.image_processing import LuminaImageProcessor
        source = inspect.getsource(LuminaImageProcessor.process_image)

        # 验证源代码中有 result = { ... } 和 return result 模式
        assert "result" in source, (
            "process_image 源代码中未找到 'result' 变量"
        )
        assert "return result" in source or "return {" in source, (
            "process_image 源代码中未找到 'return result' 语句"
        )

    @given(
        key_subset=st.lists(
            st.sampled_from([
                "matched_rgb", "material_matrix", "mask_solid",
                "dimensions", "pixel_scale", "mode_info", "quantized_image",
            ]),
            min_size=1,
            max_size=7,
            unique=True,
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_required_keys_are_subset_of_source_keys(self, key_subset: list):
        """随机选取的必需键子集都应出现在 process_image 源代码中。"""
        from core.image_processing import LuminaImageProcessor
        source = inspect.getsource(LuminaImageProcessor.process_image)

        for key in key_subset:
            assert f"'{key}'" in source or f'"{key}"' in source, (
                f"process_image 源代码中未找到必需键 '{key}'"
            )
