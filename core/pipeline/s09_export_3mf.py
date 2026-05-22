"""
S09 — Coordinate transform and 3MF export.
S09 — 坐标变换与 3MF 导出。

从 converter.py 搬入的导出逻辑：
- 单面模式 X 镜像
- BambuStudio 3MF 导出（含嵌入打印设置）
"""

from api.structured_logging import get_logger
import os
import time

import numpy as np

from config import MODELS_DIR, PrinterConfig, get_printer_profile
from core.naming import generate_model_filename
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata

_log = get_logger(__name__)


def _center_scene_on_printer_bed(scene, printer_id: str) -> None:
    """Translate the export scene to the selected printer's bed center."""
    bounds = np.asarray(scene.bounds, dtype=np.float64)
    if bounds.shape != (2, 3) or not np.all(np.isfinite(bounds)):
        return

    min_bounds, max_bounds = bounds
    if np.any(max_bounds[:2] <= min_bounds[:2]):
        return

    profile = get_printer_profile(printer_id)
    current_center = (min_bounds[:2] + max_bounds[:2]) / 2.0
    bed_center = np.array([profile.bed_width / 2.0, profile.bed_depth / 2.0], dtype=np.float64)
    delta_xy = bed_center - current_center
    if np.allclose(delta_xy, 0.0):
        return

    transform = np.eye(4)
    transform[0, 3] = float(delta_xy[0])
    transform[1, 3] = float(delta_xy[1])
    for geom_name in list(scene.geometry.keys()):
        scene.geometry[geom_name].apply_transform(transform)

    _log.debug(
        "Centered export scene on printer bed",
        extra={
            "event": "s09_scene_centered_on_bed",
            "printer_id": profile.id,
            "bed_width_mm": int(profile.bed_width),
            "bed_depth_mm": int(profile.bed_depth),
            "delta_x_mm": round(float(delta_xy[0]), 6),
            "delta_y_mm": round(float(delta_xy[1]), 6),
        },
    )


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
        - bambu_base_height_mm (float): Bambu 底板高度，缺省为 0.0
        - bambu_color_height_mm (float): Bambu 彩色层高度，缺省为 0.0
        - bambu_face_orientation (str): Bambu 朝向，缺省为 "down"
        - enable_base_layer_height_modifier (bool): 是否启用底板粗层高覆盖，缺省为 True

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

    # Single-sided: X mirror correction only. The transform does not change Z,
    # so Bambu layer_config_ranges Z intervals remain valid without adjustment.
    if is_single_sided:
        model_width_mm = target_w * pixel_scale
        mirror_transform = np.array([[-1, 0, 0, model_width_mm], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        for geom_name in list(scene.geometry.keys()):
            scene.geometry[geom_name].apply_transform(mirror_transform)

    if bool(ctx.get("center_on_bed", True)):
        _center_scene_on_printer_bed(scene, ctx.get("printer_id", "bambu-h2d"))

    _prog = ctx.get("progress")
    if _prog is not None:
        _prog(0.50, "导出 3MF 中... | Exporting 3MF...")

    _log.debug(f"export_3mf start")
    _export_t0 = time.perf_counter() if _bench_enabled else None

    base_name = os.path.splitext(os.path.basename(image_path))[0]
    out_path = os.path.join(MODELS_DIR, generate_model_filename(base_name, modeling_mode, color_mode))

    # Check if scene has any geometry before exporting
    if len(scene.geometry) == 0:
        _log.error("No meshes generated, cannot export 3MF")
        ctx["error"] = "[ERROR] Mesh generation failed: No valid meshes generated"
        return ctx

    # BambuStudio print settings
    print_settings = {
        "layer_height": "0.08",
        "initial_layer_height": "0.08",
        "wall_loops": "1",
        "top_shell_layers": "0",
        "bottom_shell_layers": "1",
        "bottom_surface_pattern": "monotonicline",
        "elefant_foot_compensation": "0",
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
        _log.debug(f"Exporting with BambuStudio metadata...")
        _log.debug(
            "Base-layer modifier: enabled=%s base_height_mm=%s color_height_mm=%s face_orientation=%s",
            bool(ctx.get("enable_base_layer_height_modifier", True)),
            float(ctx.get("bambu_base_height_mm", 0.0)),
            float(ctx.get("bambu_color_height_mm", 0.0)),
            str(ctx.get("bambu_face_orientation", "down")),
        )

        # Cover-thumbnail diagnostics: log which image is forwarded as
        # cover_source for this export, plus structure_mode / face_orientation
        # to help correlate single-sided vs double-sided behaviour.
        # 封面缩略图诊断日志：记录本次导出实际使用的 cover_source 路径，
        # 以及 structure_mode / face_orientation，帮助定位单面/双面差异。
        _cover_path = ctx.get("cover_source_path") or ctx.get("image_path")
        _cover_exists = bool(_cover_path) and os.path.exists(str(_cover_path))
        try:
            _cover_size = os.path.getsize(str(_cover_path)) if _cover_exists else 0
        except OSError:
            _cover_size = -1
        _log.debug(
            "Cover thumbnail source resolved",
            extra={
                "event": "s09_cover_source_resolved",
                "structure_mode": str(ctx.get("structure_mode", "")),
                "face_orientation": str(ctx.get("bambu_face_orientation", "down")),
                "color_mode": str(color_mode),
                "cover_source_path_param": str(ctx.get("cover_source_path") or ""),
                "image_path": str(ctx.get("image_path") or ""),
                "resolved_cover_path": str(_cover_path or ""),
                "resolved_cover_exists": bool(_cover_exists),
                "resolved_cover_size_bytes": int(_cover_size),
                "out_path": str(out_path),
            },
        )

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
            enable_base_layer_height_modifier=bool(ctx.get("enable_base_layer_height_modifier", True)),
            base_height_mm=float(ctx.get("bambu_base_height_mm", 0.0)),
            color_height_mm=float(ctx.get("bambu_color_height_mm", 0.0)),
            face_orientation=str(ctx.get("bambu_face_orientation", "down")),
            cover_source=ctx.get("cover_source_path") or ctx.get("image_path"),
        )
        if _bench_enabled and _export_t0 is not None:
            _export_elapsed = time.perf_counter() - _export_t0
            _hifi_timings["export_3mf_s"] = _export_elapsed
            ctx["_hifi_timings"] = _hifi_timings
            _log.debug(f"export_3mf done: {_export_elapsed:.3f}s")
        _log.debug(f"3MF exported with embedded settings: {out_path}")
    except (ValueError, TypeError, RuntimeError, OSError) as e:
        _log.exception(f"Error exporting 3MF: {e}")
        ctx["error"] = f"[ERROR] 3MF export failed: {e}"
        return ctx

    ctx["out_path"] = out_path

    return ctx
