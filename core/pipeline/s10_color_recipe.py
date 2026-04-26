"""
S10 — Color recipe report generation (optional step).
S10 — 颜色配方报告生成（可选步骤）。

从 converter.py 搬入的颜色配方逻辑：
- 环境变量策略控制（LUMINA_COLOR_RECIPE_POLICY）
- 自动像素阈值判断
- ColorRecipeLogger 调用
"""

import os
import time

import numpy as np

from api.structured_logging import get_logger
from config import OUTPUT_DIR

_log = get_logger(__name__)


def run(ctx: dict) -> dict:
    """Generate color recipe report (optional, failure does not stop pipeline).
    生成颜色配方报告（可选步骤，失败不终止管道）。

    PipelineContext 输入键 / Input keys:
        - processor (LuminaImageProcessor): 处理器实例
        - matched_rgb (np.ndarray): (H, W, 3) 匹配后的 RGB
        - material_matrix (np.ndarray): (H, W, N) 材料矩阵
        - mask_solid (np.ndarray): (H, W) bool 实体掩码
        - out_path (str): 3MF 文件路径
        - lut_metadata (dict | None): LUT 元数据

    PipelineContext 输出键 / Output keys:
        - color_recipe_path (str | None): 颜色配方报告路径
    """
    _t0 = time.perf_counter()

    # processor is only available in LUT mode; material-archive mode produces
    # recipes via the beam-search solver and exposes them through
    # material_matrix + slot_names instead of a ColorRecipeLogger.
    processor = ctx.get('processor')
    if processor is None:
        ctx['color_recipe_path'] = None
        _log.info("color recipe report skipped (no LUT processor; material-archive mode)")
        return ctx

    matched_rgb = ctx['matched_rgb']
    material_matrix = ctx['material_matrix']
    mask_solid = ctx['mask_solid']
    out_path = ctx['out_path']
    lut_metadata = ctx.get('lut_metadata')

    color_recipe_path = None
    recipe_policy = os.getenv("LUMINA_COLOR_RECIPE_POLICY", "auto").strip().lower()
    try:
        recipe_auto_max_pixels = int(os.getenv("LUMINA_COLOR_RECIPE_AUTO_MAX_PIXELS", "1200000"))
    except Exception:
        recipe_auto_max_pixels = 1200000
    solid_pixels = int(np.count_nonzero(mask_solid))
    enable_recipe = recipe_policy == "on" or (
        recipe_policy == "auto" and solid_pixels <= recipe_auto_max_pixels
    )
    if enable_recipe:
        try:
            from utils.color_recipe_logger import ColorRecipeLogger

            model_filename = os.path.basename(out_path)
            color_recipe_path = ColorRecipeLogger.create_from_processor(
                processor=processor,
                output_dir=OUTPUT_DIR,
                model_filename=model_filename,
                matched_rgb=matched_rgb,
                material_matrix=material_matrix,
                mask_solid=mask_solid,
                metadata=lut_metadata,
            )
        except Exception as e:
            _log.warning(
                "Warning: Failed to generate color recipe report: %s",
                e,
                extra={
                    "event": "s10_color_recipe_report_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
    else:
        _log.info(
            "Skipping color recipe report: policy=%s, solid_pixels=%s, auto_max=%s",
            recipe_policy,
            solid_pixels,
            recipe_auto_max_pixels,
            extra={
                "event": "s10_color_recipe_report_skipped",
                "policy": recipe_policy,
                "solid_pixels": solid_pixels,
                "auto_max_pixels": recipe_auto_max_pixels,
            },
        )

    ctx['color_recipe_path'] = color_recipe_path

    _elapsed = time.perf_counter() - _t0
    _hifi_timings = ctx.get('_hifi_timings', {})
    _hifi_timings['color_recipe_s'] = _elapsed
    ctx['_hifi_timings'] = _hifi_timings
    _log.info(
        "color_recipe done: %.3fs",
        _elapsed,
        extra={
            "event": "s10_color_recipe_done",
            "duration_ms": round(_elapsed * 1000, 3),
            "recipe_enabled": bool(enable_recipe),
            "has_recipe_path": color_recipe_path is not None,
        },
    )
    return ctx
