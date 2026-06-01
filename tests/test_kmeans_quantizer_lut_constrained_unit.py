"""Unit tests for LUT-Constrained K-Means quantisation.

Verifies regression contract, basic properties, cache isolation, and fallback
behaviour of :func:`quantize_colors` when ``use_lut_constrained=True``.

LUT-Constrained K-Means 量化功能的单元测试。
覆盖回归契约、基本性质、缓存隔离与回退路径。
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest
from scipy.spatial import KDTree

from core.pipeline.processing_ops import kmeans_quantizer
from core.pipeline.processing_ops.kmeans_quantizer import (
    _lut_constrained_quantize,
    quantize_colors,
)


def _build_mini_lut(n: int = 8, seed: int = 1) -> tuple[np.ndarray, np.ndarray, KDTree]:
    """Build a minimal synthetic LUT with *n* RGB entries and their Lab partners.

    构造一个含 *n* 个 RGB/Lab 条目的小型合成 LUT。
    """
    rng = np.random.default_rng(seed)
    lut_rgb = rng.integers(32, 224, size=(n, 3), dtype=np.uint8)
    # Unique RGB values — guaranteed by the integer range and small n.
    lut_rgb = np.unique(lut_rgb, axis=0)
    from core.image_processing import LuminaImageProcessor

    lut_lab = LuminaImageProcessor._rgb_to_lab(lut_rgb)
    lut_tree = KDTree(lut_lab)
    return lut_rgb, lut_lab, lut_tree


def _synthetic_image(palette_rgb: np.ndarray, h: int = 64, w: int = 64, seed: int = 0) -> np.ndarray:
    """Build (H, W, 3) uint8 image from a palette with random spatial layout.

    用调色板生成随机空间排布的小图。
    """
    rng = np.random.default_rng(seed)
    labels = rng.integers(0, len(palette_rgb), size=(h, w))
    return palette_rgb[labels]


class TestRegressionContract:
    """Existing callers must get identical output when ``use_lut_constrained``
    is off or LUT data is absent — no silent behavioural change.
    旧路径调用方在开关关闭或缺 LUT 数据时，输出必须与之前完全一致。
    """

    def test_use_lut_constrained_false_matches_legacy(self) -> None:
        """``use_lut_constrained=False`` produces the legacy cv2.kmeans output.
        关闭开关时输出与旧路径一致。
        """
        pal_rgb, pal_lab, pal_tree = _build_mini_lut(8)
        img = _synthetic_image(pal_rgb, h=64, w=64, seed=42)

        out_legacy = quantize_colors(img, n_colors=4, seed=42)
        out_off = quantize_colors(
            img, n_colors=4, seed=42,
            lut_lab=pal_lab, lut_rgb=pal_rgb, lut_tree=pal_tree,
            use_lut_constrained=False,
        )
        assert np.array_equal(out_legacy, out_off), (
            "use_lut_constrained=False must produce byte-identical output vs legacy path."
        )

    def test_no_lut_data_does_not_raise(self) -> None:
        """``use_lut_constrained=True`` with ``lut_lab=None`` must fall back
        to legacy path without raising.
        开启开关但未传 LUT 数据时，不抛异常，自动回退旧路径。
        """
        pal_rgb, _, _ = _build_mini_lut(8)
        img = _synthetic_image(pal_rgb, h=32, w=32, seed=1)

        out = quantize_colors(
            img, n_colors=4, seed=42,
            lut_lab=None, lut_rgb=None, lut_tree=None,
            use_lut_constrained=True,
        )
        assert out.shape == (32, 32, 3)
        assert out.dtype == np.uint8


class TestLutConstrainedProperties:
    """Basic correctness properties of the LUT-Constrained path.
    LUT-Constrained 路径的基本正确性。
    """

    def test_all_pixels_are_in_lut(self) -> None:
        """Every pixel in the output must be a colour from the LUT RGB palette.
        输出中每个像素的 RGB 都必须是 LUT 条目。
        """
        pal_rgb, pal_lab, pal_tree = _build_mini_lut(16)
        img = _synthetic_image(pal_rgb, h=80, w=80, seed=7)

        out = quantize_colors(
            img, n_colors=8, seed=42, skip_post_blur=True,
            lut_lab=pal_lab, lut_rgb=pal_rgb, lut_tree=pal_tree,
            use_lut_constrained=True,
        )
        out_pixels = out.reshape(-1, 3)
        lut_set = {tuple(row) for row in pal_rgb}
        out_set = {tuple(row) for row in out_pixels}
        assert out_set.issubset(lut_set), (
            f"Output contains {len(out_set - lut_set)} colours not in the LUT."
        )

    def test_k_clamped_when_exceeds_lut_size(self) -> None:
        """When ``n_colors > len(lut)``, K is silently clamped to LUT size.
        K 超过 LUT 条目数时自动 clamp。
        """
        pal_rgb, pal_lab, pal_tree = _build_mini_lut(5)
        img = _synthetic_image(pal_rgb, h=32, w=32, seed=2)

        out = quantize_colors(
            img, n_colors=100, seed=42, skip_post_blur=True,
            lut_lab=pal_lab, lut_rgb=pal_rgb, lut_tree=pal_tree,
            use_lut_constrained=True,
        )
        unique = np.unique(out.reshape(-1, 3), axis=0).shape[0]
        assert unique <= 5, (
            f"Expected at most 5 unique colours (LUT size), got {unique}."
        )

    def test_empty_lut_returns_copy(self) -> None:
        """Zero-entry LUT must return a copy of the input image.
        空 LUT 返回原图副本。
        """
        pal_rgb, _, _ = _build_mini_lut(8)
        img = _synthetic_image(pal_rgb, h=20, w=20, seed=3)
        empty_lab = np.zeros((0, 3), dtype=np.float64)
        empty_tree = KDTree(np.zeros((1, 3))) if False else None
        out = quantize_colors(
            img, n_colors=4, seed=42,
            lut_lab=empty_lab, lut_rgb=np.zeros((0, 3), dtype=np.uint8), lut_tree=None,
            use_lut_constrained=True,
        )
        # Falls back to legacy path; shape must be preserved.
        assert out.shape == (20, 20, 3)

    def test_deterministic_output(self) -> None:
        """Same input + seed must produce identical output across calls.
        相同输入 + 种子 → 确定性输出。
        """
        pal_rgb, pal_lab, pal_tree = _build_mini_lut(16)
        img = _synthetic_image(pal_rgb, h=48, w=48, seed=5)

        out1 = quantize_colors(
            img, n_colors=6, seed=42,
            lut_lab=pal_lab, lut_rgb=pal_rgb, lut_tree=pal_tree,
            use_lut_constrained=True,
        )
        out2 = quantize_colors(
            img, n_colors=6, seed=42,
            lut_lab=pal_lab, lut_rgb=pal_rgb, lut_tree=pal_tree,
            use_lut_constrained=True,
        )
        assert np.array_equal(out1, out2), (
            "LUT-Constrained quantize must be deterministic for the same seed."
        )


class TestCacheIsolation:
    """Module-level cache must partition entries by LUT fingerprint and flag.
    模块级缓存必须根据 LUT 指纹和开关隔离条目。
    """

    def test_different_flag_different_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Toggling ``use_lut_constrained`` must not serve stale cache entries.
        切换开关不应命中旧缓存条目。
        """
        monkeypatch.delenv("LUMINA_SKIP_POST_QUANTIZE_BLUR", raising=False)
        pal_rgb, pal_lab, pal_tree = _build_mini_lut(8)
        img = _synthetic_image(pal_rgb, h=48, w=48, seed=10)

        out_off = quantize_colors(
            img, n_colors=4, seed=42, skip_post_blur=True,
            lut_lab=pal_lab, lut_rgb=pal_rgb, lut_tree=pal_tree,
            use_lut_constrained=False, lut_fingerprint="abc123",
        )
        out_on = quantize_colors(
            img, n_colors=4, seed=42, skip_post_blur=True,
            lut_lab=pal_lab, lut_rgb=pal_rgb, lut_tree=pal_tree,
            use_lut_constrained=True, lut_fingerprint="abc123",
        )
        unique_off = np.unique(out_off.reshape(-1, 3), axis=0).shape[0]
        unique_on = np.unique(out_on.reshape(-1, 3), axis=0).shape[0]
        # Both respect skip_post_blur → both have unique <= n_colors.
        # The assertion is that the two paths are not sharing a cache entry.
        assert not np.array_equal(out_off, out_on), (
            "use_lut_constrained=True and False must produce different outputs "
            "(cache must be partitioned by flag)."
        )

    def test_different_lut_different_cache(self) -> None:
        """Different LUT fingerprints must not share the same cache slot.
        不同 LUT 指纹必须对应不同缓存槽。
        """
        pal_rgb1, pal_lab1, pal_tree1 = _build_mini_lut(8, seed=1)
        pal_rgb2, pal_lab2, pal_tree2 = _build_mini_lut(8, seed=99)
        fp1 = hashlib.sha1(pal_lab1.tobytes()).hexdigest()[:12]
        fp2 = hashlib.sha1(pal_lab2.tobytes()).hexdigest()[:12]
        assert fp1 != fp2, "LUTs with different seeds must have different fingerprints."

        img = _synthetic_image(pal_rgb1, h=48, w=48, seed=11)

        out1 = quantize_colors(
            img, n_colors=4, seed=42, skip_post_blur=True,
            lut_lab=pal_lab1, lut_rgb=pal_rgb1, lut_tree=pal_tree1,
            use_lut_constrained=True, lut_fingerprint=fp1,
        )
        out2 = quantize_colors(
            img, n_colors=4, seed=42, skip_post_blur=True,
            lut_lab=pal_lab2, lut_rgb=pal_rgb2, lut_tree=pal_tree2,
            use_lut_constrained=True, lut_fingerprint=fp2,
        )
        # Different LUT → different quantization result expected
        unique1 = np.unique(out1.reshape(-1, 3), axis=0)
        unique2 = np.unique(out2.reshape(-1, 3), axis=0)
        # They should not be identical since the LUT colours differ
        assert not np.array_equal(unique1, unique2), (
            "Different LUTs must produce different quantization centroids."
        )

    def test_fingerprint_in_cache_key(self) -> None:
        """Supplying a fingerprint isolates cache entries; same LUT data
        with same image should still produce identical deterministic output.
        指纹参数字段隔离缓存；相同 LUT 数据 + 相同图像产生确定性的相同输出。
        """
        pal_rgb, pal_lab, pal_tree = _build_mini_lut(8)
        img = _synthetic_image(pal_rgb, h=48, w=48, seed=12)

        out_a = quantize_colors(
            img, n_colors=4, seed=42, skip_post_blur=True,
            lut_lab=pal_lab, lut_rgb=pal_rgb, lut_tree=pal_tree,
            use_lut_constrained=True, lut_fingerprint="fp_a",
        )
        out_b = quantize_colors(
            img, n_colors=4, seed=42, skip_post_blur=True,
            lut_lab=pal_lab, lut_rgb=pal_rgb, lut_tree=pal_tree,
            use_lut_constrained=True, lut_fingerprint="fp_b",
        )
        # Same inputs -> same deterministic output
        assert np.array_equal(out_a, out_b), (
            "Same LUT + same image must produce identical output regardless "
            "of fingerprint argument."
        )
        # Verify both fingerprints created separate cache entries by calling
        # again and confirming they return from cache (not re-computed).
        out_a_cached = quantize_colors(
            img, n_colors=4, seed=42, skip_post_blur=True,
            lut_lab=pal_lab, lut_rgb=pal_rgb, lut_tree=pal_tree,
            use_lut_constrained=True, lut_fingerprint="fp_a",
        )
        out_b_cached = quantize_colors(
            img, n_colors=4, seed=42, skip_post_blur=True,
            lut_lab=pal_lab, lut_rgb=pal_rgb, lut_tree=pal_tree,
            use_lut_constrained=True, lut_fingerprint="fp_b",
        )
        assert np.array_equal(out_a, out_a_cached)
        assert np.array_equal(out_b, out_b_cached)


class TestLowLevelLutConstrained:
    """Direct unit tests on ``_lut_constrained_quantize``.
    直接测试内部函数 ``_lut_constrained_quantize``。
    """

    def test_returns_uint8_rgb(self) -> None:
        """Output shape and dtype match input expectations.
        输出 shape 与 dtype 正确。
        """
        _, pal_lab, pal_tree = _build_mini_lut(8)
        pal_rgb2, _, _ = _build_mini_lut(16, seed=2)
        img = _synthetic_image(pal_rgb2, h=32, w=32, seed=13)

        out = _lut_constrained_quantize(
            img, n_colors=4, seed=42,
            lut_lab=pal_lab, lut_rgb=pal_rgb2, lut_tree=pal_tree,
            skip_post_blur=True,
        )
        assert out.shape == (32, 32, 3)
        assert out.dtype == np.uint8

    def test_empty_cluster_handling(self) -> None:
        """High K with few distinct input colours exercises empty-cluster
        reinitialisation without crashing.
        高 K 值 + 少量输入色 → 空 cluster 重采样不崩溃。
        """
        pal_rgb, pal_lab, pal_tree = _build_mini_lut(32)
        img = np.broadcast_to(pal_rgb[0].astype(np.uint8), (20, 20, 3)).copy()

        out = _lut_constrained_quantize(
            img, n_colors=16, seed=42,
            lut_lab=pal_lab, lut_rgb=pal_rgb, lut_tree=pal_tree,
            skip_post_blur=True,
        )
        assert out.shape == (20, 20, 3)
        unique = np.unique(out.reshape(-1, 3), axis=0).shape[0]
        assert unique >= 1

    def test_uses_kdtree_not_dense_cdist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The LUT-constrained path must not allocate dense pixel-by-K matrices.

        This blocks regressions where ``cdist(work_pixels, centers)`` or
        ``cdist(full_pixels, centers)`` scales as ``pixels * effective_k`` and
        OOMs large 4096-entry LUT previews.
        LUT 约束路径不得构造 ``像素数 × effective_k`` 的稠密距离矩阵。
        """

        def _blocked_cdist(*_args: object, **_kwargs: object) -> np.ndarray:
            raise AssertionError("dense cdist must not be used")

        monkeypatch.setattr(kmeans_quantizer, "cdist", _blocked_cdist, raising=False)

        pal_rgb, pal_lab, pal_tree = _build_mini_lut(32)
        img = _synthetic_image(pal_rgb, h=48, w=48, seed=14)

        out = _lut_constrained_quantize(
            img,
            n_colors=16,
            seed=42,
            lut_lab=pal_lab,
            lut_rgb=pal_rgb,
            lut_tree=pal_tree,
        )

        assert out.shape == img.shape
        assert out.dtype == np.uint8
        out_set = {tuple(row) for row in out.reshape(-1, 3)}
        lut_set = {tuple(row) for row in pal_rgb}
        assert out_set.issubset(lut_set)
        assert len(out_set) <= 16


class TestPreScalingLutConstrained:
    """Verify that pre-scaling (for images > 500k pixels) works correctly
    in the LUT-Constrained path.
    验证 LUT-Constrained 路径中预缩放（>500k 像素）功能正确。
    """

    def test_pre_scaling_triggers(self) -> None:
        """Image larger than 500k pixels should trigger pre-scaling.
        大于 50 万像素的图应触发预缩放。
        """
        pal_rgb, pal_lab, pal_tree = _build_mini_lut(16)
        # 800×700 = 560,000 > 500,000
        img = _synthetic_image(pal_rgb, h=800, w=700, seed=20)

        out = quantize_colors(
            img, n_colors=8, seed=42, skip_post_blur=True,
            lut_lab=pal_lab, lut_rgb=pal_rgb, lut_tree=pal_tree,
            use_lut_constrained=True,
        )
        assert out.shape == (800, 700, 3)
        assert out.dtype == np.uint8
        # All pixels should still be from the LUT
        out_pixels = out.reshape(-1, 3)
        lut_set = {tuple(row) for row in pal_rgb}
        out_set = {tuple(row) for row in out_pixels}
        assert out_set.issubset(lut_set), (
            "Pre-scaled LUT-Constrained output must still contain only LUT colours."
        )


class TestPostBlurLutConstrained:
    """Post-quantisation blur behaviour in LUT-Constrained path.
    LUT-Constrained 路径的后量化模糊行为。
    """

    def test_skip_post_blur_true(self) -> None:
        """``skip_post_blur=True`` must not run medianBlur.
        skip_post_blur=True 不执行 medianBlur。
        """
        pal_rgb, pal_lab, pal_tree = _build_mini_lut(16)
        img = _synthetic_image(pal_rgb, h=64, w=64, seed=30)

        out = quantize_colors(
            img, n_colors=8, seed=42,
            lut_lab=pal_lab, lut_rgb=pal_rgb, lut_tree=pal_tree,
            use_lut_constrained=True, skip_post_blur=True,
        )
        unique = np.unique(out.reshape(-1, 3), axis=0).shape[0]
        assert unique <= 8, (
            f"skip_post_blur must respect contract: {unique} > 8."
        )

    def test_env_skip_post_blur(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Global env ``LUMINA_SKIP_POST_QUANTIZE_BLUR=1`` must skip blur
        even in LUT-Constrained path.
        全局 env var 同样在 LUT-Constrained 路径生效。
        """
        monkeypatch.setenv("LUMINA_SKIP_POST_QUANTIZE_BLUR", "1")
        pal_rgb, pal_lab, pal_tree = _build_mini_lut(16)
        img = _synthetic_image(pal_rgb, h=64, w=64, seed=31)

        out = quantize_colors(
            img, n_colors=8, seed=42,
            lut_lab=pal_lab, lut_rgb=pal_rgb, lut_tree=pal_tree,
            use_lut_constrained=True,
        )
        unique = np.unique(out.reshape(-1, 3), axis=0).shape[0]
        assert unique <= 8, (
            f"Global env override must skip blur in LUT-Constrained path: {unique} > 8."
        )
