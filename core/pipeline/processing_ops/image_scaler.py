"""
图像缩放与分辨率计算模块 (Image Scaler)

从 image_processing.py 的 process_image 抽取缩放与分辨率计算逻辑。
包含目标尺寸计算和 NEAREST 插值缩放。

Image scaling and resolution calculation.
Extracted from process_image.
"""


from api.structured_logging import get_logger
import numpy as np
import cv2
from PIL import Image

from config import PrinterConfig, ModelingMode

_log = get_logger(__name__)


def calculate_target_dimensions(
    img_width: int, img_height: int, target_width_mm: float, modeling_mode: "ModelingMode"
) -> tuple:
    """计算目标尺寸和像素比例。
    Calculate target dimensions and pixel scale.

    Args:
        img_width: 原始图像宽度（像素）
        img_height: 原始图像高度（像素）
        target_width_mm: 目标宽度（毫米）
        modeling_mode: 建模模式（HIGH_FIDELITY / PIXEL）

    Returns:
        tuple: (target_w, target_h, pixel_scale)
            - target_w: 目标宽度（像素）
            - target_h: 目标高度（像素）
            - pixel_scale: mm/pixel 比例
    """
    if modeling_mode == ModelingMode.HIGH_FIDELITY:
        # High-precision mode: 10 pixels/mm
        PIXELS_PER_MM = 10
        target_w = int(round(target_width_mm * PIXELS_PER_MM))
        pixel_scale = 1.0 / PIXELS_PER_MM  # 0.1 mm per pixel
        _log.debug(f"High-res mode: {PIXELS_PER_MM} px/mm")
    else:
        # Pixel mode: Based on nozzle width
        target_w = int(round(target_width_mm / PrinterConfig.NOZZLE_WIDTH))
        pixel_scale = PrinterConfig.NOZZLE_WIDTH
        _log.debug(f"Pixel mode: {1.0/pixel_scale:.2f} px/mm")

    target_w = max(1, target_w)
    target_h = max(1, int(round(target_w * img_height / img_width)))
    _log.debug(
        f"Target: {target_w}×{target_h}px ({target_w*pixel_scale:.1f}×{target_h*pixel_scale:.1f}mm)"
    )

    return target_w, target_h, pixel_scale


def resize_image(img: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
    """NEAREST 插值缩放。
    Resize image with NEAREST interpolation to preserve hard edges.

    Args:
        img: 输入图像数组（PIL Image 或 numpy array），如果是 PIL Image 会自动转换
        target_w: 目标宽度（像素）
        target_h: 目标高度（像素）

    Returns:
        (target_h, target_w, C) uint8 缩放后的图像数组
    """
    _log.debug(f"Using NEAREST interpolation (no anti-aliasing)")
    if isinstance(img, Image.Image):
        img = img.resize((target_w, target_h), Image.Resampling.NEAREST)
        return np.array(img)
    else:
        return cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_NEAREST)
