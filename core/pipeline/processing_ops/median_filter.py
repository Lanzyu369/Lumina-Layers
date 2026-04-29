"""
中值滤波模块（Median Filter）

从 image_processing.py 的 _process_high_fidelity_mode Step 2 搬入。
椒盐噪声去除。

Median filter for salt-and-pepper noise removal.
Extracted from _process_high_fidelity_mode Step 2.
"""

from api.structured_logging import get_logger
import time
import numpy as np
import cv2

_log = get_logger(__name__)


def apply_median_filter(rgb: np.ndarray, kernel_size: int) -> np.ndarray:
    """中值滤波（椒盐噪声去除）。
    Median filter for salt-and-pepper noise removal.

    Args:
        rgb: (H, W, 3) uint8 RGB 图像数组
        kernel_size: 中值滤波核大小，0 表示禁用，必须为正奇数

    Returns:
        (H, W, 3) uint8 滤波后的 RGB 图像数组
    """
    t0 = time.time()
    if kernel_size > 0:
        kernel_size = kernel_size if kernel_size % 2 == 1 else kernel_size + 1
        _log.debug(f"Applying median blur (kernel={kernel_size})...")
        rgb_processed = cv2.medianBlur(rgb, kernel_size)
    else:
        _log.debug(f"Median blur disabled (kernel=0)")
        rgb_processed = rgb
    _log.debug(f"⏱️ Median blur: {time.time() - t0:.2f}s")
    return rgb_processed
