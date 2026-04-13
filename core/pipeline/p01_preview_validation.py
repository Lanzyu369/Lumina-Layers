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

import time
import logging

from config import ModelingMode, ColorSystem
from core.pipeline.preview_color_utils import build_palette_preview_colors
from utils.lut_manager import LUTManager

_log = logging.getLogger(__name__)


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
        - quantize_colors (int): clamp 到 [8, 256] 范围后的量化颜色数
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

    # ---- 输入校验 ----
    if image_path is None:
        ctx["error"] = "[ERROR] Please upload an image"
        return ctx
    if lut_path is None:
        ctx["error"] = "[WARNING] Please select or upload calibration file"
        return ctx

    # ---- LUT 路径解析 ----
    if isinstance(lut_path, str):
        actual_lut_path = lut_path
    elif hasattr(lut_path, "name"):
        actual_lut_path = lut_path.name
    else:
        ctx["error"] = "[ERROR] Invalid LUT file format"
        return ctx

    # ---- modeling_mode 规范化 ----
    if modeling_mode is None or modeling_mode == "none":
        modeling_mode = ModelingMode.HIGH_FIDELITY
        _log.warning("[CONVERTER] modeling_mode was None, using default HIGH_FIDELITY")
    else:
        modeling_mode = ModelingMode(modeling_mode)

    # ---- quantize_colors clamp ----
    quantize_colors = max(8, min(256, quantize_colors))

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

    if actual_lut_path.endswith((".json", ".msgpack")):
        try:
            _, _, lut_metadata = LUTManager.load_lut_with_metadata(actual_lut_path)
            if ctx.get("color_layers") is None:
                ctx["color_layers"] = getattr(lut_metadata, "max_color_layers", None)
            if ctx.get("layer_height_mm") is None:
                ctx["layer_height_mm"] = getattr(lut_metadata, "layer_height_mm", None)
            if lut_metadata.palette:
                slot_names, preview_colors = build_palette_preview_colors(lut_metadata.palette, color_conf)
                _log.info(f"[P01] LUT/source: Using palette order: {slot_names}")
                for idx, entry in enumerate(lut_metadata.palette):
                    rgba = preview_colors[idx]
                    if entry.hex_color:
                        _log.info(f"[P01] Material '{entry.color}' -> RGB{rgba[:3]} ({entry.hex_color})")
                    else:
                        _log.info(f"[P01] Material '{entry.color}' -> RGB{rgba[:3]} (derived from color_conf)")
            else:
                _log.warning("[P01] Merged LUT has no palette, using default color_conf")
        except (OSError, ValueError, TypeError, KeyError) as e:
            _log.warning(f"[P01] Failed to extract palette from Merged LUT: {e}")

    # ---- 写入输出 ----
    ctx["actual_lut_path"] = actual_lut_path
    ctx["modeling_mode"] = modeling_mode
    ctx["quantize_colors"] = quantize_colors
    ctx["preview_colors"] = preview_colors
    ctx["slot_names"] = slot_names
    _elapsed = time.perf_counter() - _t0
    ctx.setdefault("_preview_timings", {})["p01_s"] = _elapsed
    _log.info(f"[P01] validation done: {_elapsed:.3f}s")
    return ctx
