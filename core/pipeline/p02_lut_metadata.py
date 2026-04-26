"""
P02 — LUT metadata loading and color system configuration.
P02 — LUT 元数据加载与颜色系统配置。

从 generate_preview_cached 函数搬入的逻辑，包括：
- 颜色系统配置（ColorSystem.get）
- LUT 元数据加载（通过 LUTManager.load_lut_with_metadata）
"""

import time

from api.structured_logging import get_logger
from config import ColorSystem

_log = get_logger(__name__)

# Try to import LUTManager for metadata loading
try:
    from utils.lut_manager import LUTManager
except ImportError:
    LUTManager = None


def run(ctx: dict) -> dict:
    """Load LUT metadata and configure color system.
    加载 LUT 元数据并配置颜色系统。

    PipelineContext 输入键 / Input keys:
        - actual_lut_path (str): 解析后的实际 LUT 文件路径
        - color_mode (str): 颜色模式字符串

    PipelineContext 输出键 / Output keys:
        - color_conf (dict): 颜色系统配置
        - lut_metadata (object | None): LUT 元数据对象

    Raises:
        KeyError: 缺少必需的输入键时抛出
    """
    # ---- 读取必需输入 ----
    _t0 = time.perf_counter()
    actual_lut_path = ctx['actual_lut_path']
    color_mode = ctx['color_mode']

    # ---- Material-archive branch: skip LUT metadata ----
    if ctx.get("material_source") == "material_archive":
        if "color_conf" not in ctx:
            ctx["color_conf"] = ColorSystem.get(color_mode)
        ctx["lut_metadata"] = None
        _elapsed = time.perf_counter() - _t0
        ctx.setdefault('_preview_timings', {})['p02_s'] = _elapsed
        _log.info(
            "material_archive mode, skipping LUT metadata: %.3fs",
            _elapsed,
            extra={
                "event": "p02_material_archive_lut_metadata_skipped",
                "duration_ms": round(_elapsed * 1000, 3),
                "mode": str(color_mode),
            },
        )
        return ctx

    # ---- 颜色系统配置 ----
    color_conf = ColorSystem.get(color_mode)

    # ---- LUT 元数据加载 ----
    lut_metadata = None
    if LUTManager is not None:
        try:
            _, _, lut_metadata = LUTManager.load_lut_with_metadata(actual_lut_path)
        except Exception as e:
            _log.warning(
                "Warning: Failed to load LUT metadata: %s",
                e,
                extra={
                    "event": "p02_lut_metadata_load_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "path": str(actual_lut_path),
                },
            )

    # ---- 写入输出 ----
    ctx['color_conf'] = color_conf
    ctx['lut_metadata'] = lut_metadata
    _elapsed = time.perf_counter() - _t0
    ctx.setdefault('_preview_timings', {})['p02_s'] = _elapsed
    _log.info(
        "lut_metadata done: %.3fs",
        _elapsed,
        extra={
            "event": "p02_lut_metadata_done",
            "duration_ms": round(_elapsed * 1000, 3),
            "mode": str(color_mode),
            "has_metadata": lut_metadata is not None,
        },
    )
    return ctx
