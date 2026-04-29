"""
K-Means 颜色量化模块（K-Means Color Quantizer）

从 image_processing.py 的 _process_high_fidelity_mode Step 4 搬入。
包含预缩放优化、K-Means++ 初始化、后量化去噪。

K-Means color quantization with pre-scaling optimization.
Extracted from _process_high_fidelity_mode Step 4.
"""

from api.structured_logging import get_logger
import os
import time
import numpy as np
import cv2
from scipy.spatial import KDTree

_log = get_logger(__name__)


def _skip_post_quantize_blur() -> bool:
    """Return True when the ``LUMINA_SKIP_POST_QUANTIZE_BLUR`` env var
    globally forces the post-quantization medianBlur to be skipped.
    返回 True 时，``LUMINA_SKIP_POST_QUANTIZE_BLUR`` 环境变量在全局层面
    强制跳过量化后的 medianBlur 步骤。

    The blur was originally intended to remove "salt-and-pepper" noise, but
    ``cv2.medianBlur`` on a 3-channel uint8 image takes the median per
    channel independently, which violates the quantization contract and can
    explode the distinct-color count far beyond ``n_colors``. Individual
    callers should prefer the ``skip_post_blur=True`` keyword argument on
    :func:`quantize_colors` to opt out locally; this env var is a global
    override primarily used by diagnostics and by callers that want to
    verify behaviour without modifying the call site.
    (单个调用方应优先使用 ``skip_post_blur=True`` 关键字参数进行本地选择性
    关闭；该 env var 则是全局覆盖，主要用于诊断或不便改调用点的场景。)
    """
    raw = os.environ.get("LUMINA_SKIP_POST_QUANTIZE_BLUR", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}

# 模块级 K-Means 缓存：key = md5(rgb)[:16]_{n_colors}_{seed}
_kmeans_cache: dict = {}
_KMEANS_CACHE_MAX = 4


def _resolve_cluster_count(requested_colors: int, sample_count: int) -> int:
    """Clamp the cluster count to the available sample count.

    OpenCV ``cv2.kmeans`` requires ``K <= N`` where ``N`` is the number of
    samples. Tiny SVG puzzle pieces can easily rasterize to fewer pixels than
    the requested quantization count, so we degrade gracefully instead of
    raising inside OpenCV.
    """
    if sample_count <= 0:
        return 0
    return max(1, min(requested_colors, sample_count))


def quantize_colors(
    rgb: np.ndarray,
    n_colors: int,
    seed: int = 42,
    *,
    skip_post_blur: bool = False,
) -> np.ndarray:
    """K-Means 颜色量化（含预缩放优化、K-Means++ 初始化、后量化去噪）。
    K-Means color quantization with pre-scaling optimization and post-quantization cleanup.

    Args:
        rgb: (H, W, 3) uint8 RGB 图像数组
        n_colors: 量化目标颜色数
        seed: 随机种子，默认 42
        skip_post_blur: If True, skip the ``cv2.medianBlur`` post-processing
            step. The blur computes the median independently per channel and
            therefore can synthesise new RGB triples at neighbourhood
            boundaries, inflating the distinct-color count far beyond
            ``n_colors`` (breaking the quantization contract). Callers whose
            downstream consumers rely on that contract — notably the
            material-archive solver branch in
            :mod:`core.pipeline.p03_core_processing` — should pass ``True``.
            The global ``LUMINA_SKIP_POST_QUANTIZE_BLUR`` env var also forces
            the skip regardless of this argument.
            (若为 True 则跳过 ``cv2.medianBlur``；该步骤会逐通道取中值、
            凭空造出新的 RGB 组合，破坏 ``unique RGB 数 <= n_colors`` 契约。
            依赖该契约的调用方应显式传 True；全局 env var 仍可强制开启。)

    Returns:
        (H, W, 3) uint8 量化后的 RGB 图像数组
    """
    h, w = rgb.shape[:2]
    total_pixels = h * w
    if total_pixels == 0:
        return rgb.copy()

    effective_n_colors = _resolve_cluster_count(n_colors, total_pixels)
    if effective_n_colors != n_colors:
        _log.debug(
            "Clamping K-Means colors from %s to %s for %s pixels",
            n_colors,
            effective_n_colors,
            total_pixels,
        )

    # 缓存查找：用轻量指纹（shape + 采样像素 + 参数）避免全量 hash。
    # ``effective_skip`` 必须参与 key，否则参数或 env var 变化时会命中
    # 旧的相反分支结果。
    # (``effective_skip`` must be part of the key so a change in either the
    # argument or the env var does not serve a stale entry of the opposite
    # branch.)
    env_skip_blur = _skip_post_quantize_blur()
    effective_skip = bool(skip_post_blur) or env_skip_blur
    _sample = rgb[:: max(1, rgb.shape[0] // 32), :: max(1, rgb.shape[1] // 32)].tobytes()
    _cache_key = (
        f"{rgb.shape}_{len(_sample)}_{hash(_sample)}_"
        f"{effective_n_colors}_{seed}_blur{int(not effective_skip)}"
    )
    if _cache_key in _kmeans_cache:
        _log.debug(f"K-Means cache hit: {_cache_key}")
        return _kmeans_cache[_cache_key].copy()

    # 方案 3：预缩放优化
    # 如果像素数超过 50 万，先缩小做 K-Means，再映射回原图
    KMEANS_PIXEL_THRESHOLD = 500_000

    t0 = time.time()
    if total_pixels > KMEANS_PIXEL_THRESHOLD:
        # 计算缩放比例，目标 50 万像素
        scale_factor = np.sqrt(total_pixels / KMEANS_PIXEL_THRESHOLD)
        small_h = int(h / scale_factor)
        small_w = int(w / scale_factor)

        _log.debug(
            f"🚀 Pre-scaling optimization: {w}×{h} → {small_w}×{small_h} ({total_pixels:,} → {small_w*small_h:,} pixels)"
        )

        # 缩小图片
        rgb_small = cv2.resize(rgb, (small_w, small_h), interpolation=cv2.INTER_AREA)

        # 在小图上做 K-Means（使用 K-Means++ 初始化）
        pixels_small = rgb_small.reshape(-1, 3).astype(np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5)
        flags = cv2.KMEANS_PP_CENTERS  # K-Means++ 初始化

        t_kmeans = time.time()
        _log.debug(f"K-Means++ on downscaled image ({effective_n_colors} colors)...")
        cv2.setRNGSeed(seed)  # 固定随机种子，确保 K-Means 结果可复现
        _, _, centers = cv2.kmeans(pixels_small, effective_n_colors, None, criteria, 5, flags)
        _log.debug(f"⏱️ K-Means: {time.time() - t_kmeans:.2f}s")

        # 用得到的 centers 直接映射原图（不再迭代，只做最近邻查找）
        t_map = time.time()
        _log.debug(f"Mapping centers to full image...")
        centers = centers.astype(np.float32)
        pixels_full = rgb.reshape(-1, 3).astype(np.float32)

        # 批量计算每个像素到所有 centers 的距离，找最近的
        # 使用 KDTree 加速
        centers_tree = KDTree(centers)
        _, labels = centers_tree.query(pixels_full)
        _log.debug(f"⏱️ KDTree query: {time.time() - t_map:.2f}s")

        centers = centers.astype(np.uint8)
        quantized_pixels = centers[labels]
        quantized_image = quantized_pixels.reshape(h, w, 3)

        _log.debug(f"✅ Pre-scaling optimization complete!")
    else:
        # 小图直接做 K-Means
        _log.debug(f"K-Means++ quantization to {effective_n_colors} colors...")
        pixels = rgb.reshape(-1, 3).astype(np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
        flags = cv2.KMEANS_PP_CENTERS

        cv2.setRNGSeed(seed)  # 固定随机种子，确保 K-Means 结果可复现
        _, labels, centers = cv2.kmeans(pixels, effective_n_colors, None, criteria, 10, flags)

        centers = centers.astype(np.uint8)
        quantized_pixels = centers[labels.flatten()]
        quantized_image = quantized_pixels.reshape(h, w, 3)
    _log.debug(f"⏱️ Total quantization: {time.time() - t0:.2f}s")

    # [CRITICAL FIX] Post-Quantization Cleanup
    # Removes isolated "salt-and-pepper" noise pixels that survive quantization.
    # WARNING: ``cv2.medianBlur`` on a 3-channel uint8 image takes the median
    # independently per channel, which breaks the "at most ``n_colors``
    # distinct RGB values" contract and can inflate the unique-color count by
    # 10-100x on real-world images. Callers that depend on the contract opt
    # out via ``skip_post_blur=True``; ``LUMINA_SKIP_POST_QUANTIZE_BLUR`` is
    # the global override.
    # (注：cv2.medianBlur 按通道独立取中值，会凭空造出新的 RGB 组合，从而
    # 破坏量化契约。依赖契约的调用方用 ``skip_post_blur=True`` 显式关闭；
    # env var ``LUMINA_SKIP_POST_QUANTIZE_BLUR=1`` 作为全局覆盖。)
    if effective_skip:
        trigger = "env=LUMINA_SKIP_POST_QUANTIZE_BLUR" if env_skip_blur else "param=skip_post_blur"
        _log.debug("Post-quantization blur skipped (%s)", trigger)
    else:
        t0 = time.time()
        _log.debug("Applying post-quantization cleanup (Denoising)...")
        quantized_image = cv2.medianBlur(quantized_image, 3)
        _log.debug(f"⏱️ Post-quantization cleanup: {time.time() - t0:.2f}s")

    _log.debug(f"Quantization complete!")
    # 写入缓存（LRU 简化：超限时清空最旧条目）
    if len(_kmeans_cache) >= _KMEANS_CACHE_MAX:
        oldest = next(iter(_kmeans_cache))
        del _kmeans_cache[oldest]
    _kmeans_cache[_cache_key] = quantized_image.copy()
    return quantized_image
