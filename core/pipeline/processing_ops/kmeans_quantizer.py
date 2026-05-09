"""
K-Means 颜色量化模块（K-Means Color Quantizer）

从 image_processing.py 的 _process_high_fidelity_mode Step 4 搬入。
包含预缩放优化、K-Means++ 初始化、后量化去噪。

K-Means color quantization with pre-scaling optimization.
Extracted from _process_high_fidelity_mode Step 4.
"""

from api.structured_logging import get_logger
import hashlib
import time
import numpy as np
import cv2
from scipy.spatial import KDTree
from scipy.spatial.distance import cdist

_log = get_logger(__name__)


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


KMEANS_PIXEL_THRESHOLD = 500_000


def _lut_constrained_quantize(
    rgb: np.ndarray,
    n_colors: int,
    seed: int,
    *,
    lut_lab: np.ndarray,
    lut_rgb: np.ndarray,
    lut_tree: KDTree,
    skip_post_blur: bool = False,  # Deprecated no-op; post-blur removed.
    lut_fingerprint: str | None = None,
) -> np.ndarray:
    h, w = rgb.shape[:2]
    total_pixels = h * w
    if total_pixels == 0:
        return rgb.copy()

    lut_count = len(lut_lab)
    effective_k = min(n_colors, lut_count)
    if effective_k < n_colors:
        _log.info(
            "LUT-Constrained K-Means: K clamped from %s to %s (LUT has %s entries)",
            n_colors, effective_k, lut_count,
        )

    if effective_k <= 0:
        return rgb.copy()

    _sample = rgb[:: max(1, rgb.shape[0] // 32), :: max(1, rgb.shape[1] // 32)].tobytes()
    _cache_key = (
        f"{rgb.shape}_{len(_sample)}_{hash(_sample)}_"
        f"{effective_k}_{seed}_"
        f"lc1_{lut_fingerprint or ''}"
    )
    if _cache_key in _kmeans_cache:
        _log.debug("LUT-Constrained K-Means cache hit: %s", _cache_key)
        return _kmeans_cache[_cache_key].copy()

    rng = np.random.RandomState(seed)

    if total_pixels > KMEANS_PIXEL_THRESHOLD:
        scale_factor = np.sqrt(total_pixels / KMEANS_PIXEL_THRESHOLD)
        small_h = int(h / scale_factor)
        small_w = int(w / scale_factor)
        _log.debug(
            "LUT-Constrained pre-scaling: %sx%s -> %sx%s",
            w, h, small_w, small_h,
        )
        rgb_small = cv2.resize(rgb, (small_w, small_h), interpolation=cv2.INTER_AREA)
        work_rgb = rgb_small
        full_rgb = rgb
    else:
        work_rgb = rgb
        full_rgb = rgb

    work_pixels_rgb = work_rgb.reshape(-1, 3).astype(np.float32)
    work_pixels_lab = _rgb_to_lab_quantize(work_pixels_rgb)
    n_work = work_pixels_lab.shape[0]

    _, nearest_lut_indices = lut_tree.query(work_pixels_lab)
    lut_pixel_counts = np.bincount(nearest_lut_indices, minlength=lut_count).astype(np.float64)
    lut_pixel_counts[lut_pixel_counts == 0] = 1e-9

    best_centers_lab = None
    best_sse = np.inf

    for _attempt in range(3):
        centers_idx = np.empty(effective_k, dtype=np.intp)
        probs = lut_pixel_counts / lut_pixel_counts.sum()
        centers_idx[0] = rng.choice(lut_count, p=probs)

        cur_centers_lab = lut_lab[centers_idx[:1]].copy()
        for c in range(1, effective_k):
            dist_sq = cdist(lut_lab, cur_centers_lab, 'sqeuclidean').min(axis=1)
            weighted_dist_sq = dist_sq * lut_pixel_counts
            total_weight = weighted_dist_sq.sum()
            if total_weight <= 0:
                centers_idx[c] = rng.choice(lut_count)
            else:
                centers_idx[c] = rng.choice(lut_count, p=weighted_dist_sq / total_weight)
            cur_centers_lab = lut_lab[centers_idx[:c + 1]].copy()

        cur_centers_lab = lut_lab[centers_idx].copy()

        for _iter in range(20):
            dist_sq = cdist(work_pixels_lab, cur_centers_lab, 'sqeuclidean')
            labels = dist_sq.argmin(axis=1)

            new_centers_lab = cur_centers_lab.copy()
            any_changed = False
            for ci in range(effective_k):
                mask = labels == ci
                if mask.sum() == 0:
                    new_idx = rng.choice(lut_count)
                    new_centers_lab[ci] = lut_lab[new_idx]
                    any_changed = True
                else:
                    mean_lab = work_pixels_lab[mask].mean(axis=0)
                    _, nearest_idx = lut_tree.query(mean_lab)
                    new_centers_lab[ci] = lut_lab[nearest_idx]

            if not any_changed and np.allclose(cur_centers_lab, new_centers_lab):
                cur_centers_lab = new_centers_lab
                break
            cur_centers_lab = new_centers_lab

        dist_sq = cdist(work_pixels_lab, cur_centers_lab, 'sqeuclidean')
        labels = dist_sq.argmin(axis=1)
        sse = dist_sq[np.arange(n_work), labels].sum()
        if sse < best_sse:
            best_sse = sse
            best_centers_lab = cur_centers_lab.copy()

    # Map best Lab centers to LUT RGB
    _, best_center_indices = lut_tree.query(best_centers_lab)
    centers_rgb = lut_rgb[best_center_indices]

    if total_pixels > KMEANS_PIXEL_THRESHOLD:
        full_pixels_lab = _rgb_to_lab_quantize(full_rgb.reshape(-1, 3).astype(np.float32))
        dist_sq = cdist(full_pixels_lab, best_centers_lab, 'sqeuclidean')
        labels = dist_sq.argmin(axis=1)
    else:
        dist_sq = cdist(work_pixels_lab, best_centers_lab, 'sqeuclidean')
        labels = dist_sq.argmin(axis=1)

    quantized_image = centers_rgb[labels].reshape(h, w, 3)

    if len(_kmeans_cache) >= _KMEANS_CACHE_MAX:
        oldest = next(iter(_kmeans_cache))
        del _kmeans_cache[oldest]
    _kmeans_cache[_cache_key] = quantized_image.copy()
    return quantized_image


def _rgb_to_lab_quantize(rgb_flat: np.ndarray) -> np.ndarray:
    """Convert (N, 3) float32 RGB to float64 Lab for distance computation.
    将 (N, 3) float32 RGB 转为 float64 Lab，用于距离计算。
    """
    rgb_u8 = np.clip(rgb_flat, 0, 255).astype(np.uint8).reshape(1, -1, 3)
    bgr = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64)
    return lab.reshape(-1, 3)


def quantize_colors(
    rgb: np.ndarray,
    n_colors: int,
    seed: int = 42,
    *,
    skip_post_blur: bool = False,
    lut_lab: np.ndarray | None = None,
    lut_rgb: np.ndarray | None = None,
    lut_tree: KDTree | None = None,
    use_lut_constrained: bool = False,
    lut_fingerprint: str | None = None,
) -> np.ndarray:
    """K-Means 颜色量化（含预缩放优化和 K-Means++ 初始化）。
    K-Means color quantization with pre-scaling optimization and K-Means++ init.

    Args:
        rgb: (H, W, 3) uint8 RGB 图像数组
        n_colors: 量化目标颜色数
        seed: 随机种子，默认 42
        skip_post_blur: **Deprecated no-op**. Historical opt-out for a
            post-quantization ``cv2.medianBlur`` step that violated the
            ``unique RGB count <= n_colors`` contract by per-channel median
            synthesis. The blur has been removed entirely so the contract
            is always honoured; pre-quantization denoising is handled by
            the upstream bilateral filter and isolated-pixel cleanup by
            :func:`core.isolated_pixel_cleanup.cleanup_isolated_pixels`.
            This kwarg is retained for backward compatibility with
            scripts / tests that still pass it and will be removed later.
            (**已废弃的空操作**。原来用于关闭破坏调色板契约的
            后量化 ``cv2.medianBlur``，该步骤已整块删除，契约总能满足。
            空间降噪由上游 bilateral 和下游孤立像素清理共同完成。)
        lut_lab: (N, 3) float64 LUT Lab 颜色表，用于 LUT 约束量化。
        lut_rgb: (N, 3) uint8 LUT RGB 颜色表，用于映射 LUT 索引到 RGB。
        lut_tree: 基于 lut_lab 构建的 KDTree，用于查找最近 LUT 条目。
        use_lut_constrained: 若为 True 且 LUT 数据有效，使用 LUT-Constrained K-Means。
        lut_fingerprint: LUT 指纹，用于缓存隔离。

    Returns:
        (H, W, 3) uint8 量化后的 RGB 图像数组，``unique RGB 数 <= n_colors``。
    """
    h, w = rgb.shape[:2]
    total_pixels = h * w
    if total_pixels == 0:
        return rgb.copy()

    # ``skip_post_blur`` is a deprecated no-op (the post-blur has been
    # removed). It is still accepted so legacy call sites keep working.
    del skip_post_blur  # silence unused-arg warnings; kwarg kept for API parity

    if use_lut_constrained and lut_lab is not None and lut_lab.size > 0 and lut_tree is not None:
        return _lut_constrained_quantize(
            rgb, n_colors, seed,
            lut_lab=lut_lab, lut_rgb=lut_rgb, lut_tree=lut_tree,
            lut_fingerprint=lut_fingerprint,
        )

    effective_n_colors = _resolve_cluster_count(n_colors, total_pixels)
    if effective_n_colors != n_colors:
        _log.debug(
            "Clamping K-Means colors from %s to %s for %s pixels",
            n_colors,
            effective_n_colors,
            total_pixels,
        )

    # 缓存查找：用轻量指纹（shape + 采样像素 + 参数）避免全量 hash。
    _sample = rgb[:: max(1, rgb.shape[0] // 32), :: max(1, rgb.shape[1] // 32)].tobytes()
    _cache_key = (
        f"{rgb.shape}_{len(_sample)}_{hash(_sample)}_"
        f"{effective_n_colors}_{seed}_"
        f"lc{int(use_lut_constrained)}_{lut_fingerprint or ''}"
    )
    if _cache_key in _kmeans_cache:
        _log.debug(f"K-Means cache hit: {_cache_key}")
        return _kmeans_cache[_cache_key].copy()

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

    # Post-quantization ``cv2.medianBlur`` has been removed. It used to run
    # a per-channel median on the quantized RGB image, which synthesised new
    # RGB triples at neighbourhood boundaries and broke the
    # ``unique RGB count <= n_colors`` contract (inflating the palette by up
    # to 10-100x on noisy real-world images). Spatial denoising is handled
    # by the upstream ``apply_bilateral_filter`` + the dedicated
    # ``core.isolated_pixel_cleanup.cleanup_isolated_pixels`` stage that
    # operates on the material matrix without breaking the palette.
    # (后量化 medianBlur 已整块删除，它逐通道取中值会凭空造调色板外的
    # 新 RGB，破坏 ``unique <= n_colors`` 契约。降噪改由上游 bilateral 和
    # 下游 isolated_pixel_cleanup 共同完成，后者在材料矩阵上工作不破坏调色板。)
    _log.debug(f"Quantization complete!")
    # 写入缓存（LRU 简化：超限时清空最旧条目）
    if len(_kmeans_cache) >= _KMEANS_CACHE_MAX:
        oldest = next(iter(_kmeans_cache))
        del _kmeans_cache[oldest]
    _kmeans_cache[_cache_key] = quantized_image.copy()
    return quantized_image
