"""
S09 — Coordinate transform and 3MF export.
S09 — 坐标变换与 3MF 导出。

从 converter.py 搬入的导出逻辑：
- 单面模式 X 镜像
- BambuStudio 3MF 导出（含嵌入打印设置）
"""

import os
import time
import logging

import numpy as np

from config import MODELS_DIR, PrinterConfig
from core.naming import generate_model_filename
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata

_log = logging.getLogger(__name__)


def run(ctx: dict) -> dict:
    """Apply coordinate transforms and export scene to 3MF file.
    应用坐标变换并导出场景为 3MF 文件。

    PipelineContext 输入键 / Input keys:
        - scene (trimesh.Scene): 包含所有网格的 3D 场景
        - valid_slot_names (list[str]): 有效槽位名称
        - preview_colors (dict): 材料预览颜色
        - color_mode (str): 颜色模式
        - image_path (str): 原始图像路径
        - modeling_mode (ModelingMode): 建模模式
        - target_w (int): 图像宽度（像素）
        - pixel_scale (float): mm/px 缩放因子
        - structure_mode (str): 结构模式（双面/单面）
        - total_layers (int): 总层数

    PipelineContext 输出键 / Output keys:
        - out_path (str): 导出的 3MF 文件路径
    """
    scene = ctx["scene"]
    valid_slot_names = ctx["valid_slot_names"]
    slot_names = ctx.get("slot_names", valid_slot_names)
    preview_colors = ctx["preview_colors"]
    color_mode = ctx["color_mode"]
    image_path = ctx["image_path"]
    modeling_mode = ctx["modeling_mode"]
    target_w = ctx["target_w"]
    pixel_scale = ctx["pixel_scale"]
    structure_mode = ctx.get("structure_mode", "单面")

    _bench_enabled = ctx.get("_bench_enabled", True)
    _hifi_timings = ctx.get("_hifi_timings", {})

    is_single_sided = "单面" in structure_mode or "Single" in structure_mode

    # Single-sided: X mirror correction (needed by BambuStudio writer)
    if is_single_sided:
        model_width_mm = target_w * pixel_scale
        mirror_transform = np.array([[-1, 0, 0, model_width_mm], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        for geom_name in list(scene.geometry.keys()):
            scene.geometry[geom_name].apply_transform(mirror_transform)

    _prog = ctx.get("progress")
    if _prog is not None:
        _prog(0.50, "导出 3MF 中... | Exporting 3MF...")

    _log.info(f"[S09] export_3mf start")
    _export_t0 = time.perf_counter() if _bench_enabled else None

    base_name = os.path.splitext(os.path.basename(image_path))[0]
    out_path = os.path.join(MODELS_DIR, generate_model_filename(base_name, modeling_mode, color_mode))

    # Check if scene has any geometry before exporting
    if len(scene.geometry) == 0:
        _log.error("[S09] No meshes generated, cannot export 3MF")
        ctx["error"] = "[ERROR] Mesh generation failed: No valid meshes generated"
        return ctx

    # BambuStudio print settings
    print_settings = {
        "layer_height": "0.08",
        "initial_layer_height": "0.08",
        "wall_loops": "1",
        "top_shell_layers": "0",
        "bottom_shell_layers": "0",
        "sparse_infill_density": "100%",
        "sparse_infill_pattern": "zig-zag",
        "nozzle_temperature": ["220"] * 8,
        "bed_temperature": ["60"] * 8,
        "filament_type": ["PLA"] * 8,
        "print_speed": "100",
        "travel_speed": "150",
        "enable_support": "0",
        "brim_width": "5",
        "brim_type": "auto_brim",
    }

    try:
        _log.info(f"[S09] Exporting with BambuStudio metadata...")
        export_scene_with_bambu_metadata(
            scene=scene,
            output_path=out_path,
            slot_names=valid_slot_names,
            preview_colors=preview_colors,
            project_slot_names=slot_names,
            settings=print_settings,
            color_mode=color_mode,
            printer_id=ctx.get("printer_id", "bambu-h2d"),
            slicer=ctx.get("slicer", "BambuStudio"),
            nozzle_size=ctx.get("nozzle_size", "0.4"),
        )
        if _bench_enabled and _export_t0 is not None:
            _export_elapsed = time.perf_counter() - _export_t0
            _hifi_timings["export_3mf_s"] = _export_elapsed
            ctx["_hifi_timings"] = _hifi_timings
            _log.info(f"[S09] export_3mf done: {_export_elapsed:.3f}s")
        _log.info(f"[S09] 3MF exported with embedded settings: {out_path}")
    except (ValueError, TypeError, RuntimeError, OSError) as e:
        _log.exception(f"[S09] Error exporting 3MF: {e}")
        ctx["error"] = f"[ERROR] 3MF export failed: {e}"
        return ctx

    ctx["out_path"] = out_path

    return ctx
