"""
SVG 光栅化模块（SVG Rasterizer）

使用 resvg (Rust) 进行高质量 SVG → RGBA 光栅化。
原生支持透明度，无需双通道差分 hack。

High-quality SVG rasterization via resvg (Rust).
Native RGBA transparency support — no dual-pass hack needed.
"""

from api.structured_logging import get_logger
import os
import io
import time
import numpy as np
import cv2

_log = get_logger(__name__)

try:
    import resvg_py

    HAS_SVG = True
except ImportError:
    HAS_SVG = False

_SVG_RASTER_CACHE = {}
_SVG_RASTER_CACHE_MAX = 4


def rasterize_svg(
    svg_path: str,
    target_width_mm: float,
    pixels_per_mm: float = 20.0,
    *,
    crop_to_content: bool = True,
) -> np.ndarray:
    """Rasterize an SVG file to an RGBA numpy array via resvg.
    通过 resvg 将 SVG 文件光栅化为 RGBA numpy 数组。

    Args:
        svg_path: SVG 文件路径
        target_width_mm: 目标宽度（毫米）
        pixels_per_mm: 光栅化密度，20.0 用于最终输出，10.0 用于预览
        crop_to_content: 是否按 alpha 通道做内容感知裁切。默认 ``True``，
            返回紧贴非透明像素的最小外接矩形（保留旧行为）；置为 ``False``
            时跳过裁切与 ``target_width_px`` 缩回，直接返回 resvg 渲染出的
            完整画布。这种模式下 ``(0, 0)`` 像素严格对应 SVG viewBox 的左上
            角，``pixel_x ≈ x_mm * (img.shape[1] / target_width_mm)`` 与 y
            轴同理，便于按 mm 范围在像素空间做精确按比例采样。

            Whether to alpha-crop the rasterized canvas to its non-
            transparent bounding box. Default ``True`` preserves the
            historical behavior. When ``False`` the function skips both the
            content-aware crop and the post-render scale-back, returning
            the full canvas so pixel coordinates map deterministically to
            mm: ``pixel_x ≈ x_mm * (img.shape[1] / target_width_mm)``.

    Returns:
        (H, W, 4) uint8 RGBA numpy 数组
    """
    if not HAS_SVG:
        raise ImportError("Please install 'resvg-py' for SVG support.")

    cache_key = None
    try:
        svg_abs = os.path.abspath(svg_path)
        svg_mtime = os.path.getmtime(svg_abs)
        cache_key = (
            svg_abs,
            round(float(target_width_mm), 4),
            round(float(pixels_per_mm), 2),
            svg_mtime,
            bool(crop_to_content),
        )
        cached = _SVG_RASTER_CACHE.get(cache_key)
        if cached is not None:
            _log.debug("Cache hit: %s @ %spx/mm", os.path.basename(svg_abs), pixels_per_mm)
            return cached.copy()
    except (OSError, ValueError, TypeError):
        cache_key = None

    _log.debug("Rasterizing (resvg): %s", svg_path)
    _t0_total = time.perf_counter()

    target_width_px = max(1, int(target_width_mm * pixels_per_mm))
    MIN_QUALITY_PX = 800
    render_width_px = max(target_width_px, MIN_QUALITY_PX)

    _t0 = time.perf_counter()
    png_bytes = resvg_py.svg_to_bytes(svg_path=svg_path, width=render_width_px)
    _t_render = time.perf_counter() - _t0

    from PIL import Image

    img_pil = Image.open(io.BytesIO(bytes(png_bytes)))
    img_final = np.array(img_pil.convert("RGBA"))
    _log.debug("Rendered: %sx%s px", img_final.shape[1], img_final.shape[0])

    if crop_to_content:
        _t0 = time.perf_counter()
        alpha_channel = img_final[:, :, 3]

        BORDER = 2
        h_arr, w_arr = img_final.shape[:2]
        content_rows = np.any(alpha_channel > 0, axis=1)
        content_cols = np.any(alpha_channel > 0, axis=0)
        if np.any(content_rows) and np.any(content_cols):
            row_idx = np.where(content_rows)[0]
            col_idx = np.where(content_cols)[0]
            y_min = max(0, row_idx[0] - BORDER)
            x_min = max(0, col_idx[0] - BORDER)
            y_max = min(h_arr - 1, row_idx[-1] + BORDER)
            x_max = min(w_arr - 1, col_idx[-1] + BORDER)
            img_final = img_final[y_min : y_max + 1, x_min : x_max + 1]
        _log.debug("Content-aware crop: %sx%s px", img_final.shape[1], img_final.shape[0])

        if render_width_px > target_width_px and target_width_px > 0:
            scale_back = target_width_px / render_width_px
            out_w = max(1, round(img_final.shape[1] * scale_back))
            out_h = max(1, round(img_final.shape[0] * scale_back))
            img_final = cv2.resize(img_final, (out_w, out_h), interpolation=cv2.INTER_AREA)
            _log.debug("Scaled to target: %sx%s px", out_w, out_h)
        _t_postprocess = time.perf_counter() - _t0
    else:
        # Skip alpha-crop and scale-back: callers that need stable
        # pixel→mm mapping (e.g. tile cover thumbnails on a large-format
        # canvas) cannot tolerate the bounding-box shift.
        # 跳过 alpha 裁切与缩回；需要稳定 像素↔毫米 映射的调用方（如大画幅
        # tile 封面）拿到的就是 resvg 渲染出的完整画布。
        _t_postprocess = 0.0
        _log.debug(
            "crop_to_content=False; returning full canvas %sx%s px",
            img_final.shape[1],
            img_final.shape[0],
        )

    _t_total = time.perf_counter() - _t0_total
    _log.debug(
        "Timing: render=%.2fs, postprocess=%.2fs, total=%.2fs",
        _t_render,
        _t_postprocess,
        _t_total,
    )
    _log.debug("Final resolution: %sx%s px", img_final.shape[1], img_final.shape[0])

    if cache_key is not None:
        _SVG_RASTER_CACHE[cache_key] = img_final.copy()
        while len(_SVG_RASTER_CACHE) > _SVG_RASTER_CACHE_MAX:
            _SVG_RASTER_CACHE.pop(next(iter(_SVG_RASTER_CACHE)))

    return img_final
