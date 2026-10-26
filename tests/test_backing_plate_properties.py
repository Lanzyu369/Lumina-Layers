"""
Lumina Studio - Backing Plate 形状属性测试 (Property-Based Tests)

使用 Hypothesis 验证 _build_color_extruded_mesh 生成 mesh 的正确性属性。
每个属性测试至少运行 100 次迭代。
"""

import os
import sys

import numpy as np
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.pipeline.s11_glb_preview import _build_color_extruded_mesh

BACKING_PLATE_RGBA = np.array([245, 245, 245, 255], dtype=np.uint8)


# ---------------------------------------------------------------------------
# Hypothesis strategy: generate random mask_solid boolean arrays
# ---------------------------------------------------------------------------
@st.composite
def mask_solid_strategy(draw: st.DrawFn):
    """Generate a random boolean mask_solid array with at least one True pixel.
    生成至少包含一个 True 像素的随机布尔 mask_solid 数组。

    Returns:
        tuple: (mask_solid, height, width)
    """
    h = draw(st.integers(min_value=1, max_value=20))
    w = draw(st.integers(min_value=1, max_value=20))
    flat = draw(st.lists(st.booleans(), min_size=h * w, max_size=h * w))
    mask_solid = np.array(flat, dtype=bool).reshape(h, w)
    assume(np.any(mask_solid))
    return mask_solid, h, w


# ============================================================================
# Property 1: 非空 mask 总是返回非 None mesh
# **Validates: Requirements 1.1**
# ============================================================================

@settings(max_examples=100)
@given(data=mask_solid_strategy())
def test_non_empty_mask_returns_mesh(data):
    """Property 1: 非空 mask 总是返回有效 mesh

    For any mask_solid with at least one True pixel,
    _build_color_extruded_mesh should return a non-None Trimesh.

    **Validates: Requirements 1.1**
    """
    mask_solid, height, width = data

    mesh = _build_color_extruded_mesh(
        mask=mask_solid,
        height=height,
        total_layers=1,
        rgba=BACKING_PLATE_RGBA,
    )

    assert mesh is not None, "mesh should not be None for mask with True pixels"
    assert len(mesh.vertices) > 0
    assert len(mesh.faces) > 0


# ============================================================================
# Property 2: 空 mask 返回 None
# **Validates: Requirements 1.2**
# ============================================================================

@settings(max_examples=50)
@given(
    h=st.integers(min_value=1, max_value=20),
    w=st.integers(min_value=1, max_value=20),
)
def test_empty_mask_returns_none(h, w):
    """Property 2: 全 False mask 返回 None

    For any all-False mask_solid, _build_color_extruded_mesh should return None.

    **Validates: Requirements 1.2**
    """
    mask_solid = np.zeros((h, w), dtype=bool)

    mesh = _build_color_extruded_mesh(
        mask=mask_solid,
        height=h,
        total_layers=1,
        rgba=BACKING_PLATE_RGBA,
    )

    assert mesh is None, "mesh should be None for all-False mask"


# ============================================================================
# Property 3: Z 跨度匹配 total_layers
# **Validates: Requirements 1.4**
# ============================================================================

@settings(max_examples=100)
@given(
    data=mask_solid_strategy(),
    total_layers=st.integers(min_value=1, max_value=50),
)
def test_z_span_matches_total_layers(data, total_layers):
    """Property 3: Z 跨度匹配 total_layers

    The generated mesh Z range should be [0, total_layers].

    **Validates: Requirements 1.4**
    """
    mask_solid, height, width = data

    mesh = _build_color_extruded_mesh(
        mask=mask_solid,
        height=height,
        total_layers=total_layers,
        rgba=BACKING_PLATE_RGBA,
    )

    assert mesh is not None
    z_min = mesh.vertices[:, 2].min()
    z_max = mesh.vertices[:, 2].max()
    assert z_min == pytest.approx(0.0, abs=1e-9), f"Z min should be 0, got {z_min}"
    assert z_max == pytest.approx(float(total_layers), abs=1e-9), (
        f"Z max should be {total_layers}, got {z_max}"
    )


# ============================================================================
# Property 4: 面颜色与输入 RGBA 一致
# **Validates: Requirements 1.6**
# ============================================================================

@settings(max_examples=100)
@given(data=mask_solid_strategy())
def test_face_colors_match_rgba(data):
    """Property 4: 面颜色与输入 RGBA 一致

    For any non-empty mask_solid, all face colors should match the given RGBA.

    **Validates: Requirements 1.6**
    """
    mask_solid, height, width = data

    mesh = _build_color_extruded_mesh(
        mask=mask_solid,
        height=height,
        total_layers=1,
        rgba=BACKING_PLATE_RGBA,
    )

    assert mesh is not None, "mesh should not be None for mask with True pixels"
    colors = mesh.visual.face_colors
    assert np.all(colors == BACKING_PLATE_RGBA), (
        f"Face colors mismatch: expected {BACKING_PLATE_RGBA}, got unique={np.unique(colors, axis=0)}"
    )
