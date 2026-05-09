"""
P01 — Preview input validation and parameter normalization.
P01 — 预览输入验证与参数规范化。

从 generate_preview_cached 函数开头搬入的逻辑，包括：
- 输入参数校验（image_path, lut_path）
- LUT 路径解析（支持字符串路径和 file-like 对象）
- modeling_mode 规范化（None -> HIGH_FIDELITY）
- quantize_colors 范围 clamp（8-256）
- Merged LUT palette 提取和 preview_colors 构建
"""

from api.structured_logging import get_logger
import time

from config import ModelingMode, ColorSystem
from core.pipeline._input_validation_common import (
    _apply_material_archive_branch,
    _clamp_quantize_colors,
    _resolve_lut_path_or_error,
)
from core.pipeline.preview_color_utils import build_palette_preview_colors
from utils.lut_manager import LUTManager

_log = get_logger(__name__)


def run(ctx: dict) -> dict:
    """Validate preview inputs and normalize parameters.
    验证预览输入参数并规范化。

    PipelineContext 输入键 / Input keys:
        - image_path (str): 输入图像路径
        - lut_path (str | object): LUT 文件路径或 file-like 对象
        - modeling_mode (ModelingMode | str | None): 建模模式
        - quantize_colors (int): K-Means 量化颜色数
        - color_mode (str): 颜色模式字符串

    PipelineContext 输出键 / Output keys:
        - actual_lut_path (str): 解析后的实际 LUT 文件路径
        - modeling_mode (ModelingMode): 规范化后的建模模式
        - quantize_colors (int): clamp 到 [8, 8192] 范围后的量化颜色数
        - preview_colors (dict): 材料ID到RGBA颜色的映射
        - slot_names (list): 材料槽位名称列表

    Raises:
        KeyError: 缺少必需的输入键时抛出
    """
    # ---- 读取必需输入 ----
    _t0 = time.perf_counter()
    image_path = ctx["image_path"]
    lut_path = ctx["lut_path"]
    modeling_mode = ctx.get("modeling_mode")
    quantize_colors = ctx.get("quantize_colors", 64)
    color_mode = ctx.get("color_mode", "4-Color")

    material_source = ctx.get("material_source", "lut")

    # ---- 输入校验 ----
    if image_path is None:
        ctx["error"] = "[ERROR] Please upload an image"
        return ctx

    # ---- modeling_mode 规范化 ----
    if modeling_mode is None or modeling_mode == "none":
        modeling_mode = ModelingMode.HIGH_FIDELITY
        _log.warning("modeling_mode was None, using default HIGH_FIDELITY")
    else:
        modeling_mode = ModelingMode(modeling_mode)

    # ---- quantize_colors clamp ----
    quantize_colors = _clamp_quantize_colors(quantize_colors)

    # ---- Material-archive branch ----
    if material_source == "material_archive":
        outcome = _apply_material_archive_branch(
            ctx,
            log=_log,
            event_prefix="p01",
        )
        if outcome == "error":
            return ctx
        # P01 finalises modeling_mode + quantize_colors that were normalised
        # above the material-archive branch (helper does not see them).
        ctx["modeling_mode"] = modeling_mode
        ctx["quantize_colors"] = quantize_colors
        _elapsed = time.perf_counter() - _t0
        ctx.setdefault("_preview_timings", {})["p01_s"] = _elapsed
        return ctx

    # ---- LUT branch (existing logic) ----
    actual_lut_path, lut_err = _resolve_lut_path_or_error(
        ctx,
        error_prefix="[WARNING] Please select or upload calibration file",
    )
    if lut_err is not None:
        ctx["error"] = lut_err
        return ctx

    # ---- 颜色系统配置 ----
    color_conf = ColorSystem.get(color_mode)

    # For Merged LUTs, extract slot_names and preview_colors from LUT palette
    # Use material names as keys (not indices) for direct lookup
    preview_colors = None
    slot_names = None
    if "color_layers" not in ctx:
        ctx["color_layers"] = None
    if "layer_height_mm" not in ctx:
        ctx["layer_height_mm"] = None

    if actual_lut_path.endswith((".json", ".msgpack", ".npy")):
        try:
            _, _, lut_metadata = LUTManager.load_lut_with_metadata(actual_lut_path)
            if ctx.get("color_layers") is None:
                ctx["color_layers"] = getattr(lut_metadata, "max_color_layers", None)
            if ctx.get("layer_height_mm") is None:
                ctx["layer_height_mm"] = getattr(lut_metadata, "layer_height_mm", None)
            if lut_metadata.palette:
                slot_names, preview_colors = build_palette_preview_colors(lut_metadata.palette, color_conf)
                _log.debug(
                    "LUT/source: Using palette order: %s",
                    slot_names,
                    extra={
                        "event": "p01_lut_palette_order_loaded",
                        "count": len(slot_names),
                    },
                )
                for idx, entry in enumerate(lut_metadata.palette):
                    rgba = preview_colors[idx]
                    if entry.hex_color:
                        _log.debug(
                            "Material '%s' -> RGB%s (%s)",
                            entry.color,
                            rgba[:3],
                            entry.hex_color,
                            extra={
                                "event": "p01_lut_palette_entry_loaded",
                                "material": entry.color,
                                "rgb": list(rgba[:3]),
                                "hex_color": entry.hex_color,
                            },
                        )
                    else:
                        _log.debug(
                            "Material '%s' -> RGB%s (derived from color_conf)",
                            entry.color,
                            rgba[:3],
                            extra={
                                "event": "p01_lut_palette_entry_loaded",
                                "material": entry.color,
                                "rgb": list(rgba[:3]),
                            },
                        )
            else:
                _log.warning("Merged LUT has no palette, using default color_conf")
        except (OSError, ValueError, TypeError, KeyError) as e:
            _log.warning(f"Failed to extract palette from Merged LUT: {e}")

    # ---- 写入输出 ----
    ctx["actual_lut_path"] = actual_lut_path
    ctx["modeling_mode"] = modeling_mode
    ctx["quantize_colors"] = quantize_colors
    ctx["preview_colors"] = preview_colors
    ctx["slot_names"] = slot_names
    _elapsed = time.perf_counter() - _t0
    ctx.setdefault("_preview_timings", {})["p01_s"] = _elapsed
    _log.debug(
        "validation done: %.3fs",
        _elapsed,
        extra={
            "event": "p01_validation_done",
            "duration_ms": round(_elapsed * 1000, 3),
            "mode": str(color_mode),
            "quantize_colors": int(quantize_colors),
        },
    )
    return ctx
