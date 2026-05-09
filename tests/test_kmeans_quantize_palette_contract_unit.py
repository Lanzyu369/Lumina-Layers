"""Regression tests for the K-Means quantizer's palette contract.
K-Means 量化器调色板契约回归测试。

The quantizer must ALWAYS satisfy ``unique RGB count <= n_colors``. A
previous implementation ran ``cv2.medianBlur`` after quantization, which
computes the median independently per channel and therefore synthesised
new RGB triples at neighbourhood boundaries — violating the contract by
10-100x on real-world images. That blur has been removed entirely; this
test locks the contract in so it cannot quietly regress again.

量化器必须始终满足 ``unique RGB 数 <= n_colors``。老实现会在量化之后跑
``cv2.medianBlur``，逐通道取中值会在邻域边界上凭空造出新的 RGB 三元组，
把契约违反 10-100 倍；该步骤已整块删除。本回归测试把契约钉死，防止
日后再次悄悄引入破坏契约的后处理。
"""

from __future__ import annotations

import numpy as np
import pytest

from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors


def _synthetic_noisy_image(n_centers: int, h: int, w: int, seed: int) -> np.ndarray:
    """Build an (H, W, 3) uint8 image whose ground-truth palette has
    exactly ``n_centers`` distinct RGB values arranged randomly.
    生成 (H, W, 3) uint8 合成图，真实调色板恰有 ``n_centers`` 个随机 RGB 值。
    """
    rng = np.random.default_rng(seed)
    centers = rng.integers(0, 256, size=(n_centers, 3), dtype=np.uint8)
    labels = rng.integers(0, n_centers, size=(h, w))
    return centers[labels]


@pytest.mark.parametrize(
    ("n_centers", "n_colors", "seed"),
    [
        (16, 8, 1),
        (16, 16, 2),
        (32, 16, 3),
        (64, 32, 4),
        # High-K unlocked case: mirrors the frontend "unlock quantize colors"
        # flow where users can pick K up to 8192. The palette contract must
        # still hold. (前端解锁模式可选 K 到 8192，契约仍需成立。)
        (256, 256, 5),
    ],
)
def test_quantize_colors_respects_palette_contract(
    n_centers: int, n_colors: int, seed: int
) -> None:
    """量化输出的 unique RGB 数必须 <= n_colors。"""
    img = _synthetic_noisy_image(n_centers=n_centers, h=120, w=120, seed=seed)
    out = quantize_colors(img, n_colors=n_colors, seed=42)
    unique_count = np.unique(out.reshape(-1, 3), axis=0).shape[0]
    assert unique_count <= n_colors, (
        f"palette contract violated: n_colors={n_colors} but "
        f"got {unique_count} unique RGB values"
    )


def test_deprecated_skip_post_blur_kwarg_is_accepted_and_noop() -> None:
    """``skip_post_blur`` is a deprecated no-op kept for backward compat.
    保留的已废弃关键字参数不应影响输出。
    """
    img = _synthetic_noisy_image(n_centers=16, h=64, w=64, seed=6)
    out_default = quantize_colors(img, n_colors=16, seed=42)
    out_legacy_kwarg = quantize_colors(
        img, n_colors=16, seed=42, skip_post_blur=True
    )
    # The cache is keyed without ``skip_post_blur`` so both calls should
    # return byte-identical output; the kwarg is purely cosmetic now.
    # cache key 与 skip_post_blur 无关，两次调用应输出完全相同。
    assert np.array_equal(out_default, out_legacy_kwarg)
