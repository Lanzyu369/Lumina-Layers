"""
景泰蓝掐丝描边提取模块（Wireframe Extractor）

从 image_processing.py 的 _extract_wireframe_mask 搬入。
使用 Canny 边缘检测 + 膨胀提取掐丝描边掩码。

Cloisonné wireframe mask extraction using Canny edge detection + dilation.
Extracted from _extract_wireframe_mask.
"""

import time
import numpy as np
import cv2

from api.structured_logging import get_logger

_log = get_logger(__name__)


def extract_wireframe_mask(rgb_arr: np.ndarray, pixel_scale: float,
                           wire_width_mm: float = 0.6) -> np.ndarray:
    """景泰蓝掐丝描边提取。
    Extract cloisonné wireframe mask using edge detection + dilation.

    The mask marks pixels that should become raised "gold wire" in the
    final 3D model. The dilation kernel is sized so that the wire is
    physically printable (≥ nozzle width).

    Args:
        rgb_arr: (H, W, 3) uint8 – colour-matched or quantised image.
        pixel_scale: float – mm per pixel.
        wire_width_mm: float – desired physical wire width in mm (default 0.6).

    Returns:
        mask_wireframe: (H, W) bool ndarray – True where wire should be.
    """
    t0 = time.time()

    # 1. Greyscale + light blur to suppress quantisation noise
    gray = cv2.cvtColor(rgb_arr.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    # 2. Adaptive Canny thresholds (Otsu-based)
    otsu_thresh, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    low = max(10, int(otsu_thresh * 0.4))
    high = max(30, int(otsu_thresh * 0.8))
    edges = cv2.Canny(gray, low, high)

    # 3. Dilate to physical wire width
    wire_px = max(1, int(round(wire_width_mm / pixel_scale)))
    if wire_px % 2 == 0:
        wire_px += 1  # kernel must be odd
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (wire_px, wire_px))
    dilated = cv2.dilate(edges, kernel, iterations=1)

    mask_wireframe = dilated > 0

    dt = time.time() - t0
    wire_pixels = int(np.sum(mask_wireframe))
    _log.debug(
        "Wireframe extracted: Canny(%s,%s), dilate %spx (%smm), %s wire pixels, %.2fs",
        low,
        high,
        wire_px,
        wire_width_mm,
        wire_pixels,
        dt,
        extra={
            "event": "cloisonne_wireframe_extracted",
            "duration_ms": round(dt * 1000, 3),
            "low_threshold": int(low),
            "high_threshold": int(high),
            "wire_width_px": int(wire_px),
            "wire_width_mm": float(wire_width_mm),
            "count": wire_pixels,
        },
    )

    return mask_wireframe
