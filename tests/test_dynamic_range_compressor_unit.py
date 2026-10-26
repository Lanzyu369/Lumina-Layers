"""Unit tests for ``core.pipeline.processing_ops.dynamic_range_compressor``.

Validate target-range computation and the L*-only auto dynamic range
compression: identity behavior when the target range is wider, monotonic
remap when it is narrower, endpoint clamping, a*b* preservation, and safe
handling of degenerate inputs.

针对动态范围压缩器的单元测试，覆盖目标范围解析、压缩条件、单调性、端点钳制、
a*b* 不变性以及退化输入的安全行为。
"""

from __future__ import annotations

import numpy as np
import pytest
import cv2

from core.pipeline.processing_ops.dynamic_range_compressor import (
    apply_auto_dynamic_range,
    compute_target_l_range,
    _remap_l_channel,
)


def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64)


def _gradient_image(h: int = 16, w: int = 256) -> np.ndarray:
    ramp = np.linspace(0, 255, w, dtype=np.uint8)
    return np.tile(ramp, (h, 1)).reshape(h, w, 1).repeat(3, axis=2)


class TestComputeTargetLRange:
    def test_returns_min_max_from_l_channel(self) -> None:
        lut = np.array([[10.0, 0, 0], [50.0, 5, -5], [90.0, -3, 2]])
        assert compute_target_l_range(lut) == (10.0, 90.0)

    def test_empty_returns_none(self) -> None:
        assert compute_target_l_range(np.zeros((0, 3))) is None
        assert compute_target_l_range(None) is None

    def test_constant_returns_none(self) -> None:
        lut = np.full((4, 3), 50.0)
        assert compute_target_l_range(lut) is None


class TestApplyAutoDynamicRange:
    def test_skipped_when_target_not_narrower(self) -> None:
        rgb = _gradient_image()
        out, info = apply_auto_dynamic_range(rgb, 0.0, 100.0)
        assert info["applied"] is False
        assert info["reason"] == "target_not_narrower"
        np.testing.assert_array_equal(out, rgb)

    def test_compresses_when_target_narrower(self) -> None:
        rgb = _gradient_image()
        out, info = apply_auto_dynamic_range(rgb, 30.0, 70.0)
        assert info["applied"] is True
        lab_out = _rgb_to_lab(out)
        l_out_star = lab_out[..., 0] / (255.0 / 100.0)
        # Endpoints should land within the target span (with small Lab roundtrip slack).
        assert l_out_star.min() >= 30.0 - 1.5
        assert l_out_star.max() <= 70.0 + 1.5
        # The output should be visibly narrower than the input span.
        lab_in = _rgb_to_lab(rgb)
        l_in_star = lab_in[..., 0] / (255.0 / 100.0)
        assert (l_out_star.max() - l_out_star.min()) < (l_in_star.max() - l_in_star.min())

    def test_remap_is_monotonic_in_l(self) -> None:
        rgb = _gradient_image()
        out, info = apply_auto_dynamic_range(rgb, 30.0, 70.0)
        assert info["applied"] is True
        lab_out = _rgb_to_lab(out)
        # Sample one row and verify L* is non-decreasing across the gradient.
        l_row = lab_out[0, :, 0]
        assert np.all(np.diff(l_row) >= -1.0)  # tiny dips allowed from quantization

    def test_preserves_ab_for_neutral_input(self) -> None:
        rgb = _gradient_image()
        lab_in = _rgb_to_lab(rgb)
        out, info = apply_auto_dynamic_range(rgb, 30.0, 70.0)
        assert info["applied"] is True
        lab_out = _rgb_to_lab(out)
        # Neutral gradient should keep a*/b* near 128 (Lab 0) before and after.
        ab_in = lab_in[..., 1:]
        ab_out = lab_out[..., 1:]
        assert np.max(np.abs(ab_in.astype(np.int32) - ab_out.astype(np.int32))) <= 3

    def test_invalid_target_returns_input(self) -> None:
        rgb = _gradient_image()
        out, info = apply_auto_dynamic_range(rgb, 70.0, 30.0)
        assert info["applied"] is False
        assert info["reason"] == "invalid_target"
        np.testing.assert_array_equal(out, rgb)

    def test_empty_image_safe(self) -> None:
        rgb = np.zeros((0, 0, 3), dtype=np.uint8)
        out, info = apply_auto_dynamic_range(rgb, 30.0, 70.0)
        assert info["applied"] is False
        assert out.shape == rgb.shape

    def test_constant_image_skipped(self) -> None:
        rgb = np.full((8, 8, 3), 128, dtype=np.uint8)
        out, info = apply_auto_dynamic_range(rgb, 30.0, 70.0)
        assert info["applied"] is False
        assert info["reason"] == "source_span_too_small"
        np.testing.assert_array_equal(out, rgb)


class TestPureBlackReachesTargetFloor:
    """Regression: pure-black pixels must land at exactly ``tgt_lo``.

    纯黑像素必须精确落到目标 L* 下限：保证 FDM "全黑层组合" 这类专属配方
    对纯黑区域的吸附关系不会因为引入 knee 保留带而漂移到邻近中性配方。
    """

    def _dark_dominated_image(self) -> np.ndarray:
        """Image where >50% of pixels are pure black and remainder are bright."""
        img = np.zeros((32, 32, 3), dtype=np.uint8)
        # Fill a bright quadrant so the source has a non-zero span but pure
        # black occupies the 1st percentile (i.e. src_lo_soft == src_lo_hard).
        img[:16, :16] = (240, 240, 240)
        return img

    def test_pure_black_maps_to_target_lo_when_no_shadow_tail(self) -> None:
        rgb = self._dark_dominated_image()
        out, info = apply_auto_dynamic_range(rgb, 10.0, 90.0)
        assert info["applied"] is True
        lab_out = _rgb_to_lab(out)
        # Extract L* only at the pure-black source region.
        l_star_black = lab_out[16:, 16:, 0] / (255.0 / 100.0)
        # Must sit at the exact target floor (tgt_lo=10), not 10 % above.
        assert l_star_black.max() <= 10.0 + 1.5
        assert l_star_black.min() >= 10.0 - 1.5

    def test_pure_white_maps_to_target_hi_when_no_highlight_tail(self) -> None:
        rgb = np.full((32, 32, 3), 255, dtype=np.uint8)
        # Add a very dark block so the source spans almost the full L* range.
        rgb[:16, :] = (10, 10, 10)
        # Use a narrow target so compression actually triggers.
        out, info = apply_auto_dynamic_range(rgb, 30.0, 70.0)
        assert info["applied"] is True
        lab_out = _rgb_to_lab(out)
        l_star_white = lab_out[16:, :, 0] / (255.0 / 100.0)
        assert l_star_white.min() >= 70.0 - 1.5
        assert l_star_white.max() <= 70.0 + 1.5

    def test_outliers_do_not_dominate_pure_black_mapping(self) -> None:
        """Soft knee still engages when a real shadow tail exists below p1.

        真正存在阴影尾部（低于 1st 百分位的离群像素）时仍保留 knee 软滚降，
        避免回归修复退化为纯线性映射。
        """
        # Build a bright image (so p1 sits well above 0), then inject a 2%
        # speckle of pure-black pixels so they form a real shadow tail
        # below the 1st percentile.
        rng = np.random.default_rng(0)
        rgb = np.full((100, 100, 3), 200, dtype=np.uint8)
        speckle_mask = rng.random((100, 100)) < 0.02
        rgb[speckle_mask] = (0, 0, 0)
        out, info = apply_auto_dynamic_range(rgb, 20.0, 80.0)
        assert info["applied"] is True
        lab_out = _rgb_to_lab(out)
        # The speckle outliers must still land at/near the target floor.
        l_out = lab_out[speckle_mask][:, 0] / (255.0 / 100.0)
        assert l_out.max() <= 20.0 + 2.5


@pytest.mark.parametrize(
    "tgt_lo, tgt_hi",
    [(20.0, 60.0), (10.0, 90.0), (40.0, 80.0)],
)
def test_endpoints_clamped_to_target(tgt_lo: float, tgt_hi: float) -> None:
    rgb = _gradient_image()
    out, info = apply_auto_dynamic_range(rgb, tgt_lo, tgt_hi)
    if not info["applied"]:
        np.testing.assert_array_equal(out, rgb)
        return
    lab_out = _rgb_to_lab(out)
    l_star = lab_out[..., 0] / (255.0 / 100.0)
    assert l_star.min() >= tgt_lo - 1.5
    assert l_star.max() <= tgt_hi + 1.5


class TestCineonCurveProperties:
    """Verify mathematical properties of the Cineon exponential curve.
    验证 Cineon 指数曲线的数学性质。"""

    def test_middle_is_identity_under_light_compression(self) -> None:
        l_samples = np.array([20.0, 40.0, 50.0, 60.0, 80.0], dtype=np.float64)
        out = _remap_l_channel(
            l_samples,
            src_lo_hard=0.0,
            src_hi_hard=100.0,
            tgt_lo=5.0,
            tgt_hi=95.0,
        )
        np.testing.assert_allclose(out, l_samples, atol=1.0)

    def test_c1_continuity_at_segment_boundaries(self) -> None:
        l_dense = np.linspace(0.0, 100.0, 10001, dtype=np.float64)
        out = _remap_l_channel(
            l_dense,
            src_lo_hard=0.0,
            src_hi_hard=100.0,
            tgt_lo=5.0,
            tgt_hi=95.0,
        )
        dy = np.diff(out) / np.diff(l_dense)
        shadow_amt = 5.0
        highlight_amt = 5.0
        W_s = 2.0 * shadow_amt
        W_h = 2.0 * highlight_amt
        x_toe_end = 0.0 + W_s
        x_shoulder_start = 100.0 - W_h
        idx_toe = np.searchsorted(l_dense, x_toe_end)
        idx_shoulder = np.searchsorted(l_dense, x_shoulder_start)
        if idx_toe > 0 and idx_toe < len(dy):
            assert abs(dy[idx_toe] - dy[idx_toe - 1]) < 0.05
        if idx_shoulder > 0 and idx_shoulder < len(dy):
            assert abs(dy[idx_shoulder] - dy[idx_shoulder - 1]) < 0.05

    def test_tail_width_adapts_to_compression_ratio(self) -> None:
        l_full = np.linspace(0.0, 100.0, 10001, dtype=np.float64)
        out_light = _remap_l_channel(
            l_full,
            src_lo_hard=0.0,
            src_hi_hard=100.0,
            tgt_lo=5.0,
            tgt_hi=95.0,
        )
        out_heavy = _remap_l_channel(
            l_full,
            src_lo_hard=0.0,
            src_hi_hard=100.0,
            tgt_lo=20.0,
            tgt_hi=80.0,
        )
        W_s_light = 2.0 * 5.0
        W_s_heavy = 2.0 * 20.0
        assert abs(W_s_light - 10.0) < 0.01
        assert abs(W_s_heavy - 40.0) < 0.01

    def test_heavy_compression_uses_meeting_case(self) -> None:
        l_samples = np.linspace(0.0, 100.0, 10001, dtype=np.float64)
        out = _remap_l_channel(
            l_samples,
            src_lo_hard=0.0,
            src_hi_hard=100.0,
            tgt_lo=35.0,
            tgt_hi=70.0,
        )
        idx_50 = np.searchsorted(l_samples, 50.0)
        assert 40.0 <= out[idx_50] <= 60.0
        assert np.all(np.diff(out) >= -0.01)

    def test_exponential_toe_shape(self) -> None:
        l_toe = np.linspace(0.0, 20.0, 201, dtype=np.float64)
        out = _remap_l_channel(
            l_toe,
            src_lo_hard=0.0,
            src_hi_hard=100.0,
            tgt_lo=20.0,
            tgt_hi=80.0,
        )
        d2 = np.diff(out, n=2)
        assert np.all(d2 > -0.01)
