"""
P05 — Palette extraction.
P05 — 调色板提取。

从 generate_preview_cached 函数搬入的逻辑，包括：
- 从预览缓存中提取颜色调色板
- 将 color_palette 写入 cache 字典
"""

import time

from api.structured_logging import get_logger
from core.pipeline.pipeline_utils import extract_color_palette

_log = get_logger(__name__)


def run(ctx: dict) -> dict:
    """Extract color palette from preview cache.
    从预览缓存中提取颜色调色板。

    PipelineContext 输入键 / Input keys:
        - cache (dict): 预览缓存字典（包含 matched_rgb, mask_solid）

    PipelineContext 输出键 / Output keys:
        - cache (dict): 更新后的缓存字典（添加 color_palette 键）

    Raises:
        KeyError: 缺少必需的输入键时抛出
    """
    # ---- 读取必需输入 ----
    _t0 = time.perf_counter()
    cache = ctx['cache']

    # ---- 提取调色板 ----
    color_palette = extract_color_palette(cache)
    cache['color_palette'] = color_palette

    # ---- 写入输出（cache 已就地更新）----
    ctx['cache'] = cache
    _elapsed = time.perf_counter() - _t0
    ctx.setdefault('_preview_timings', {})['p05_s'] = _elapsed
    _log.debug(
        "palette_extraction done: %.3fs",
        _elapsed,
        extra={
            "event": "p05_palette_extraction_done",
            "duration_ms": round(_elapsed * 1000, 3),
            "count": len(color_palette),
        },
    )
    return ctx
