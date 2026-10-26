"""
Lumina Studio - 颜色选择模式属性测试 (Property-Based Tests)

使用 Hypothesis 验证区域替换的像素隔离性。
每个属性测试至少运行 100 次迭代。
"""

import os
import sys

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.converter import _apply_region_replacement


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

@st.composite
def rgb_image_and_mask(draw: st.DrawFn):
    """Generate a random RGB image and a boolean mask of the same spatial shape.
    生成随机 RGB 图像和相同空间形状的布尔掩码。

    Returns:
        tuple: (image_rgb, region_mask, replacement_rgb)
    """
    h = draw(st.integers(min_value=3, max_value=50))
    w = draw(st.integers(min_value=3, max_value=50))

    image = draw(arrays(
        dtype=np.uint8,
        shape=(h, w, 3),
        elements=st.integers(min_value=0, max_value=255),
    ))

    mask = draw(arrays(
        dtype=bool,
        shape=(h, w),
        elements=st.booleans(),
    ))

    replacement_rgb = draw(st.tuples(
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
    ))

    return image, mask, replacement_rgb


# ============================================================================
# Property 6: 区域替换仅修改掩码内像素
# Feature: color-selection-modes, Property 6: 区域替换仅修改掩码内像素
# **Validates: Requirements 6.3**
# ============================================================================

@settings(max_examples=100)
@given(data=rgb_image_and_mask())
def test_region_replacement_only_modifies_masked_pixels(data):
    """Property 6: 区域替换仅修改掩码内像素

    For any RGB image array and connected region mask (region_mask),
    after calling _apply_region_replacement, all pixels outside the mask
    should be identical to the original image, and all pixels inside the
    mask should be set to the replacement color.

    **Validates: Requirements 6.3**
    """
    image_rgb, region_mask, replacement_rgb = data

    result = _apply_region_replacement(image_rgb, region_mask, replacement_rgb)

    # Pixels outside the mask must be unchanged
    outside_mask = ~region_mask
    np.testing.assert_array_equal(
        result[outside_mask],
        image_rgb[outside_mask],
        err_msg="Pixels outside the mask were modified",
    )

    # Pixels inside the mask must equal the replacement color
    if np.any(region_mask):
        expected_color = np.array(replacement_rgb, dtype=np.uint8)
        masked_pixels = result[region_mask]
        assert np.all(masked_pixels == expected_color), (
            f"Not all masked pixels were set to {replacement_rgb}. "
            f"Found unique values: {np.unique(masked_pixels, axis=0).tolist()}"
        )

    # Result must not alias the original array
    assert result is not image_rgb, "Result should be a copy, not the original array"
