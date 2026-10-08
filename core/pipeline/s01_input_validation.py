"""
S01 — Input validation, LUT path resolution, and color system configuration.
S01 — 输入验证、LUT 路径解析与颜色系统配置。

从 convert_image_to_3d 函数开头搬入的逻辑，包括：
- 输入参数校验（image_path, lut_path）
- LUT 路径解析（支持字符串路径和 file-like 对象）
- 颜色系统配置（ColorSystem.get）
- SVG 矢量模式检测（is_svg_vector 标志）
- backing_color_id 校验
- separate_backing 处理
"""

from api.structured_logging import get_logger
import time

from config import ColorSystem, ModelingMode
from core.pipeline._input_validation_common import (
    _apply_material_archive_branch,
    _resolve_lut_path_or_error,
    _validate_vector_svg_input,
)
from core.pipeline.preview_color_utils import (
    build_lut_material_types,
    build_palette_preview_colors,
)
from core.pipeline.svg_opacity import should_use_opacity_safe_svg_raster_fallback
from utils.lut_manager import LUTManager

_log = get_logger(__name__)
S01_HANDLED_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    OSError,
    RuntimeError,
)


def run(ctx: dict) -> dict:
    """Validate inputs, resolve LUT path, configure color system, detect SVG vector mode.
    验证输入参数，解析 LUT 路径，配置颜色系统，检测 SVG 矢量模式。

    PipelineContext 输入键 / Input keys:
        - image_path (str): 输入图像路径
        - lut_path (str | object): LUT 文件路径或 file-like 对象
        - color_mode (str): 颜色模式字符串
        - modeling_mode (ModelingMode): 建模模式枚举
        - backing_color_id (int): 底板材料 ID
        - separate_backing (bool): 是否分离底板

    PipelineContext 输出键 / Output keys:
        - actual_lut_path (str): 解析后的实际 LUT 文件路径
        - color_conf (dict): 颜色系统配置
        - slot_names (list): 材料槽名称列表
        - preview_colors (dict): 预览颜色映射
        - is_svg_vector (bool): 是否为 SVG 矢量模式
        - backing_color_id (int): 校验/更新后的底板材料 ID
        - separate_backing (bool): 校验后的底板分离标志

    Raises:
        KeyError: 缺少必需的输入键时抛出
    """
    _t0 = time.perf_counter()

    # ---- 读取必需输入 ----
    image_path = ctx["image_path"]
    lut_path = ctx["lut_path"]
    color_mode = ctx["color_mode"]
    modeling_mode = ctx["modeling_mode"]

    material_source = ctx.get("material_source", "lut")

    if should_use_opacity_safe_svg_raster_fallback(
        image_path=image_path,
        color_mode=color_mode,
        modeling_mode=modeling_mode,
    ):
        modeling_mode = ModelingMode.HIGH_FIDELITY
        ctx["modeling_mode"] = modeling_mode
        ctx["svg_vector_opacity_fallback"] = True
        _log.debug(
            "5-Color Extended SVG vector input uses opacity; routing through raster compositing",
            extra={
                "event": "svg_vector_opacity_fallback",
                "stage": "s01",
                "color_mode": str(color_mode),
            },
        )

    # ---- 输入校验 ----
    if image_path is None:
        ctx["error"] = "[ERROR] Please upload an image"
        return ctx

    # ---- SVG 矢量模式检测 ----
    # ``material_archive`` previously bailed out of the SVG-native
    # branch and forced its SVG inputs through the raster ``P03``
    # path, which rasterised to pixels and snapped each pixel to the
    # fill palette before the material solver ran. The downside was
    # hard pixel edges with occasional 1-px misclassified colours
    # along strokes — visually distinct from the LUT-vector preview.
    # Material vector mode now reuses the same parse → clip → mesh /
    # preview pipeline and only swaps the per-fill matcher, so the
    # gate is widened to cover both ``lut`` and ``material_archive``.
    # 耗材档案 + 矢量模式过去走的是栅格 P03，2D 预览硬边像素 +
    # 偶发杂色；现在改为复用同一条矢量管线，只替换颜色匹配器。
    _validate_vector_svg_input(
        ctx,
        image_path=image_path,
        modeling_mode=modeling_mode,
    )
    if ctx.get("error"):
        return ctx

    # ---- Material-archive branch ----
    if material_source == "material_archive":
        outcome = _apply_material_archive_branch(
            ctx,
            log=_log,
            event_prefix="s01",
        )
        if outcome == "error":
            return ctx
        # Fall through to common backing/vector checks below.
    else:
        # ---- LUT branch ----
        actual_lut_path, lut_err = _resolve_lut_path_or_error(
            ctx,
            error_prefix="[WARNING] Please select or upload a .npy calibration file!",
        )
        if lut_err is not None:
            ctx["error"] = lut_err
            return ctx

        ctx["actual_lut_path"] = actual_lut_path
        if "color_layers" not in ctx:
            ctx["color_layers"] = None
        if "layer_height_mm" not in ctx:
            ctx["layer_height_mm"] = None

    # ---- separate_backing 处理 ----
    separate_backing = ctx.get("separate_backing", False)
    try:
        separate_backing = bool(separate_backing) if separate_backing is not None else False
    except S01_HANDLED_ERRORS as e:
        _log.warning(f"Error reading separate_backing checkbox state: {e}, using default (False)")
        separate_backing = False

    backing_color_id = ctx.get("backing_color_id", 0)
    if (
        material_source == "material_archive"
        and ctx.get("material_backing_material_index") is None
    ):
        backing_color_id = ctx.get("material_base_channel_idx", backing_color_id)
    separate_backing_color_id = ctx.get("separate_backing_color_id", backing_color_id)
    if separate_backing_color_id is None:
        separate_backing_color_id = backing_color_id
    if separate_backing:
        backing_color_id = -2
        _log.debug(
            "Backing separation enabled: backing will be a separate object",
            extra={
                "event": "s01_backing_separation_resolved",
                "separate_backing": True,
                "separate_backing_color_id": separate_backing_color_id,
            },
        )
    else:
        _log.debug(
            "Backing separation disabled: backing merged with first layer (backing_color_id=%s)",
            backing_color_id,
            extra={
                "event": "s01_backing_separation_resolved",
                "separate_backing": False,
                "backing_color_id": backing_color_id,
            },
        )

    ctx["separate_backing"] = separate_backing
    ctx["backing_color_id"] = backing_color_id
    ctx["separate_backing_color_id"] = separate_backing_color_id

    _log.debug(
        "conversion parameters resolved",
        extra={
            "event": "s01_conversion_parameters_resolved",
            "mode": modeling_mode.get_display_name(),
            "quantize_colors": int(ctx.get("quantize_colors", 32)),
            "blur_kernel": int(ctx.get("blur_kernel", 0)),
            "smooth_sigma": int(ctx.get("smooth_sigma", 10)),
        },
    )

    # ---- 颜色系统配置 (LUT branch only) ----
    if material_source != "material_archive":
        actual_lut_path = ctx["actual_lut_path"]
        _log.debug(
            "LUT: %s",
            actual_lut_path,
            extra={"event": "s01_lut_path_resolved", "path": str(actual_lut_path)},
        )
        color_conf = ColorSystem.get(color_mode)
        lut_metadata = None

        # For Merged LUTs, extract slot_names and preview_colors from LUT metadata.
        # Use metadata.palette order (same as LUTManager.name_to_idx) so that
        # integer material IDs in ref_stacks match slot_names and preview_colors.
        if actual_lut_path.endswith((".json", ".msgpack", ".npy", ".npz")):
            try:
                _, _, lut_metadata = LUTManager.load_lut_with_metadata(actual_lut_path)
                if ctx.get("color_layers") is None:
                    ctx["color_layers"] = getattr(lut_metadata, "max_color_layers", None)
                if ctx.get("layer_height_mm") is None:
                    ctx["layer_height_mm"] = getattr(lut_metadata, "layer_height_mm", None)
                if lut_metadata.palette:
                    slot_names, preview_colors = build_palette_preview_colors(lut_metadata.palette, color_conf)
                    _log.debug(
                        "Source palette order: %s",
                        slot_names,
                        extra={"event": "s01_lut_palette_order_loaded", "count": len(slot_names)},
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
                                    "event": "s01_lut_palette_entry_loaded",
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
                                    "event": "s01_lut_palette_entry_loaded",
                                    "material": entry.color,
                                    "rgb": list(rgba[:3]),
                                },
                            )
                else:
                    slot_names = color_conf["slots"]
                    preview_colors = color_conf["preview"]
            except S01_HANDLED_ERRORS as e:
                _log.warning(f"Failed to extract palette from Merged LUT: {e}")
                slot_names = color_conf["slots"]
                preview_colors = color_conf["preview"]
        else:
            slot_names = color_conf["slots"]
            preview_colors = color_conf["preview"]

        ctx["color_conf"] = color_conf
        ctx["slot_names"] = slot_names
        ctx["preview_colors"] = preview_colors
        ctx["material_types"] = build_lut_material_types(lut_metadata, slot_names)

    slot_names = ctx["slot_names"]
    preview_colors = ctx["preview_colors"]
    _log.debug(
        "final palette resolved",
        extra={
            "event": "s01_palette_resolved",
            "slot_count": len(slot_names),
            "preview_color_count": len(preview_colors),
        },
    )

    # ---- backing_color_id 范围校验 ----
    num_materials = len(slot_names)
    if backing_color_id != -2 and (backing_color_id < 0 or backing_color_id >= num_materials):
        _log.warning(f"Invalid backing_color_id={backing_color_id}, using default (0)")
        ctx["backing_color_id"] = 0

    _elapsed = time.perf_counter() - _t0
    _hifi_timings = ctx.get("_hifi_timings", {})
    _hifi_timings["input_val_s"] = _elapsed
    ctx["_hifi_timings"] = _hifi_timings
    _log.debug(
        "done: %.3fs",
        _elapsed,
        extra={
            "event": "s01_done",
            "duration_ms": round(_elapsed * 1000, 3),
            "mode": modeling_mode.get_display_name(),
            "slot_count": len(slot_names),
        },
    )
    return ctx
