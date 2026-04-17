"""
Pipeline coordinator — orchestrates raster (S01-S12) and preview (P01-P06) pipelines.
管道协调器 — 编排光栅管道（S01-S12）和预览管道（P01-P06）。

Provides:
    - run_raster_pipeline(ctx) -> ctx: 光栅转换管道
    - run_preview_pipeline(ctx) -> ctx: 预览管道
    - _run_vector_branch(ctx) -> ctx: SVG 矢量分支（内部使用）
"""

import os
import time
import logging
import inspect

import cv2
import numpy as np

from config import BedManager
from core.pipeline import (
    s01_input_validation,
    s02_image_processing,
    s03_color_replacement,
    s04_debug_preview,
    s05_preview_generation,
    s06_voxel_building,
    s07_mesh_generation,
    s08_auxiliary_meshes,
    s09_export_3mf,
    s10_color_recipe,
    s11_glb_preview,
    s12_result_assembly,
    p01_preview_validation,
    p02_lut_metadata,
    p03_core_processing,
    p04_cache_building,
    p05_palette_extraction,
    p06_bed_rendering,
)
from core.pipeline.s03_color_replacement import _normalize_color_replacements_input
from core.pipeline.pipeline_utils import extract_color_palette

log = logging.getLogger(__name__)
COORDINATOR_HANDLED_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    AttributeError,
    OSError,
    RuntimeError,
    ModuleNotFoundError,
    cv2.error,
)

# ---------------------------------------------------------------------------
# Raster pipeline step definitions
# ---------------------------------------------------------------------------

# Each entry: (module, step_label, progress_before, progress_after, optional)
_RASTER_STEPS = [
    # S01 is called separately (before vector branch check)
    (s02_image_processing, "S02", 0.05, 0.20, False),
    (s03_color_replacement, "S03", 0.20, 0.25, False),
    (s04_debug_preview, "S04", 0.25, 0.28, True),
    (s05_preview_generation, "S05", 0.28, 0.35, False),
    (s06_voxel_building, "S06", 0.35, 0.45, False),
    (s07_mesh_generation, "S07", 0.45, 0.60, False),
    (s08_auxiliary_meshes, "S08", 0.60, 0.68, False),
    (s09_export_3mf, "S09", 0.68, 0.75, False),
    (s10_color_recipe, "S10", 0.75, 0.80, True),
    (s11_glb_preview, "S11", 0.80, 0.90, False),
    (s12_result_assembly, "S12", 0.90, 1.00, False),
]

_PREVIEW_STEPS = [
    # P01 is called separately (for early error check)
    (p02_lut_metadata, "P02", 0.10, 0.20, False),
    (p03_core_processing, "P03", 0.20, 0.55, False),
    (p04_cache_building, "P04", 0.55, 0.70, False),
    (p05_palette_extraction, "P05", 0.70, 0.80, False),
    (p06_bed_rendering, "P06", 0.80, 1.00, False),
]


def _report_progress(ctx: dict, value: float, desc: str = "") -> None:
    """Call progress callback if present in ctx.
    如果 ctx 中存在 progress 回调则调用。

    Args:
        ctx: 管道上下文
        value: 进度值 (0.0 - 1.0)
        desc: 进度描述文本
    """
    progress = ctx.get("progress")
    if progress is not None:
        progress(value, desc=desc)


# ===================================================================
# Raster pipeline
# ===================================================================


def run_raster_pipeline(ctx: dict) -> dict:
    """Execute raster conversion pipeline S01-S12 in order.
    按顺序执行光栅转换管道 S01-S12。

    S01 执行后检查 ``is_svg_vector`` 标志，若为 True 则走矢量分支
    ``_run_vector_branch``，不再执行 S02-S12。

    S04（调试预览）和 S10（颜色配方）标记为 optional，失败仅打印
    警告，不终止管道。其余步骤抛出异常时捕获并写入 ``ctx['error']``，
    提前终止管道。

    Args:
        ctx: 已初始化的 PipelineContext 字典

    Returns:
        更新后的 PipelineContext 字典
    """
    pipeline_t0 = time.perf_counter()
    step_timings = {}

    # ---- S01: Input validation ----
    _report_progress(ctx, 0.0, "输入验证中... | Validating inputs...")
    t0 = time.perf_counter()
    try:
        ctx = s01_input_validation.run(ctx)
    except COORDINATOR_HANDLED_ERRORS as exc:
        ctx["error"] = f"[S01] {exc}"
        return ctx
    step_timings["S01"] = time.perf_counter() - t0

    if ctx.get("error"):
        return ctx

    # ---- Vector branch check ----
    if ctx.get("is_svg_vector"):
        return _run_vector_branch(ctx)

    # ---- S02-S12: Raster steps ----
    for module, label, prog_before, prog_after, optional in _RASTER_STEPS:
        _report_progress(ctx, prog_before, f"{label} 执行中...")
        t0 = time.perf_counter()
        try:
            ctx = module.run(ctx)
        except COORDINATOR_HANDLED_ERRORS as exc:
            if optional:
                log.warning(f"[COORDINATOR] Optional step {label} failed: {exc}")
            else:
                ctx["error"] = f"[{label}] {exc}"
                log.error(f"[COORDINATOR] Pipeline aborted at {label}: {exc}")
                return ctx
        step_timings[label] = time.perf_counter() - t0
        if ctx.get("error"):
            return ctx
        _report_progress(ctx, prog_after)

    total_s = time.perf_counter() - pipeline_t0
    log.info(f"\n{'=' * 60}")
    log.info(f"[PIPELINE] S01-S12 completed in {total_s:.2f}s")
    for label, elapsed in step_timings.items():
        pct = elapsed / total_s * 100 if total_s > 0 else 0
        log.info(f"  {label}: {elapsed:.2f}s ({pct:.1f}%)")
    log.info(f"{'=' * 60}")
    ctx["_pipeline_total_s"] = total_s
    ctx["_step_timings"] = step_timings

    return ctx


# ===================================================================
# Preview pipeline
# ===================================================================


def run_preview_pipeline(ctx: dict) -> dict:
    """Execute preview pipeline P01-P06 in order.
    按顺序执行预览管道 P01-P06。

    任意步骤抛出异常时捕获并写入 ``ctx['error']``，提前终止管道。

    Args:
        ctx: 已初始化的 PipelineContext 字典

    Returns:
        更新后的 PipelineContext 字典
    """
    pipeline_t0 = time.perf_counter()
    step_timings = {}

    # ---- P01: Preview validation ----
    _report_progress(ctx, 0.0, "预览验证中... | Validating preview inputs...")
    t0 = time.perf_counter()
    try:
        ctx = p01_preview_validation.run(ctx)
    except COORDINATOR_HANDLED_ERRORS as exc:
        ctx["error"] = f"[P01] {exc}"
        return ctx
    step_timings["P01"] = time.perf_counter() - t0

    if ctx.get("error"):
        return ctx

    modeling_mode = ctx.get("modeling_mode")
    modeling_mode_value = getattr(modeling_mode, "value", modeling_mode)
    image_path = str(ctx.get("image_path", "") or "")
    is_svg_vector = modeling_mode_value == "vector" and image_path.lower().endswith(".svg")
    if is_svg_vector:
        _report_progress(ctx, 0.10, "SVG 矢量预览分析中... | Building vector preview...")
        t0 = time.perf_counter()
        ctx = _run_vector_preview_branch(ctx)
        step_timings["P_VECTOR"] = time.perf_counter() - t0
        if ctx.get("error"):
            return ctx
        total_s = time.perf_counter() - pipeline_t0
        log.info("\n%s", "=" * 60)
        log.info("[PREVIEW] P01 + VectorPreview completed in %.2fs", total_s)
        for label, elapsed in step_timings.items():
            pct = elapsed / total_s * 100 if total_s > 0 else 0
            log.info("  %s: %.2fs (%.1f%%)", label, elapsed, pct)
        log.info("%s", "=" * 60)
        ctx["_preview_total_s"] = total_s
        ctx["_preview_step_timings"] = step_timings
        return ctx

    # ---- P02-P06 ----
    for module, label, prog_before, prog_after, optional in _PREVIEW_STEPS:
        _report_progress(ctx, prog_before, f"{label} 执行中...")
        t0 = time.perf_counter()
        try:
            ctx = module.run(ctx)
        except COORDINATOR_HANDLED_ERRORS as exc:
            if optional:
                log.warning(f"[COORDINATOR] Optional step {label} failed: {exc}")
            else:
                ctx["error"] = f"[{label}] {exc}"
                log.error(f"[COORDINATOR] Preview pipeline aborted at {label}: {exc}")
                return ctx
        step_timings[label] = time.perf_counter() - t0
        if ctx.get("error"):
            return ctx
        _report_progress(ctx, prog_after)

    total_s = time.perf_counter() - pipeline_t0
    log.info(f"\n{'=' * 60}")
    log.info(f"[PREVIEW] P01-P06 completed in {total_s:.2f}s")
    for label, elapsed in step_timings.items():
        pct = elapsed / total_s * 100 if total_s > 0 else 0
        log.info(f"  {label}: {elapsed:.2f}s ({pct:.1f}%)")
    log.info(f"{'=' * 60}")
    ctx["_preview_total_s"] = total_s
    ctx["_preview_step_timings"] = step_timings

    return ctx


# ===================================================================
# Vector preview branch (SVG native preview processing)
# ===================================================================


def _run_vector_preview_branch(ctx: dict) -> dict:
    """Execute SVG native preview processing for vector mode.
    为 SVG + vector 模式构建与 native vector 生成一致的预览缓存。
    """
    image_path = ctx["image_path"]
    actual_lut_path = ctx["actual_lut_path"]
    color_mode = ctx["color_mode"]
    target_width_mm = ctx["target_width_mm"]
    is_dark = ctx.get("is_dark", True)
    quantize_colors = ctx.get("quantize_colors", 64)
    backing_color_id = ctx.get("backing_color_id", 0)
    lut_metadata = ctx.get("lut_metadata")

    try:
        from core.vector_engine import VectorProcessor

        vec_processor = VectorProcessor(actual_lut_path, color_mode)
        analysis = vec_processor.analyze_svg(
            svg_path=image_path,
            target_width_mm=target_width_mm,
            color_replacements=None,
        )

        raster_cache = VectorProcessor.build_preview_cache(
            analysis,
            pixels_per_mm=10.0,
        )

        cache = {
            "target_w": raster_cache["target_w"],
            "target_h": raster_cache["target_h"],
            "target_width_mm": target_width_mm,
            "pixel_scale": raster_cache["pixel_scale"],
            "mask_solid": raster_cache["mask_solid"],
            "material_matrix": raster_cache["material_matrix"],
            "matched_rgb": raster_cache["matched_rgb"],
            "preview_rgba": raster_cache["preview_rgba"].copy(),
            "color_conf": analysis.color_conf,
            "color_mode": color_mode,
            "quantize_colors": quantize_colors,
            "backing_color_id": backing_color_id,
            "is_dark": is_dark,
            "bed_label": BedManager.DEFAULT_BED,
            "lut_metadata": lut_metadata,
            "preview_colors": dict(analysis.preview_colors),
            "slot_names": list(analysis.slot_names),
            "debug_data": None,
            "quantized_image": raster_cache["quantized_image"],
        }
        cache["color_palette"] = extract_color_palette(cache)

        ctx["matched_rgb"] = raster_cache["matched_rgb"]
        ctx["material_matrix"] = raster_cache["material_matrix"]
        ctx["mask_solid"] = raster_cache["mask_solid"]
        ctx["target_w"] = raster_cache["target_w"]
        ctx["target_h"] = raster_cache["target_h"]
        ctx["quantized_image"] = raster_cache["quantized_image"]
        ctx["preview_rgba"] = raster_cache["preview_rgba"]
        ctx["cache"] = cache
        ctx["color_conf"] = analysis.color_conf
        ctx["preview_colors"] = dict(analysis.preview_colors)
        ctx["slot_names"] = list(analysis.slot_names)

        ctx = p06_bed_rendering.run(ctx)
        return ctx
    except Exception as exc:
        ctx["error"] = f"[VECTOR_PREVIEW] {exc}"
        log.exception("[COORDINATOR] Vector preview branch failed: %s", exc)
        return ctx


# ===================================================================
# Vector branch (SVG native processing)
# ===================================================================


def _run_vector_branch(ctx: dict) -> dict:
    """Execute SVG native vector processing branch.
    执行 SVG 原生矢量处理分支。

    当 S01 检测到 ``is_svg_vector=True`` 时由 ``run_raster_pipeline``
    调用。使用 ``core.vector_engine.VectorProcessor`` 完成 SVG → 3D
    转换，包括 3MF 导出、GLB 预览和 2D 预览生成。

    Args:
        ctx: 经过 S01 验证后的 PipelineContext 字典

    Returns:
        更新后的 PipelineContext 字典（包含 result_tuple）
    """
    from config import ColorSystem, MODELS_DIR, OUTPUT_DIR
    from core.naming import generate_model_filename, generate_preview_filename
    from utils.bambu_3mf_writer import export_scene_with_bambu_metadata
    from utils import Stats

    image_path = ctx["image_path"]
    actual_lut_path = ctx["actual_lut_path"]
    color_mode = ctx["color_mode"]
    modeling_mode = ctx["modeling_mode"]
    target_width_mm = ctx["target_width_mm"]
    spacer_thick = ctx["spacer_thick"]
    structure_mode = ctx["structure_mode"]
    color_replacements = ctx.get("color_replacements")
    replacement_regions = ctx.get("replacement_regions")
    enable_fridge_magnet = ctx.get("enable_fridge_magnet", False)
    fridge_magnets = ctx.get("fridge_magnets") or []

    log.info("[COORDINATOR] Using Native Vector Engine (Shapely/Clipper)...")
    vector_timing = {}
    vector_total_t0 = time.perf_counter()

    # ---- Normalize color replacements ----
    vector_replacements = _normalize_color_replacements_input(replacement_regions)
    if not vector_replacements:
        vector_replacements = _normalize_color_replacements_input(color_replacements)

    try:
        from core.vector_engine import VectorProcessor

        vec_processor = VectorProcessor(actual_lut_path, color_mode)
        vec_processor.enable_fridge_magnet = bool(enable_fridge_magnet)
        vec_processor.fridge_magnets = list(fridge_magnets)

        # 1. Unified analysis: parse → clip → match (shared by preview + mesh)
        _report_progress(ctx, 0.05, "SVG 解析与几何处理中... | Parsing & extruding SVG...")
        mesh_t0 = time.perf_counter()
        analysis = vec_processor.analyze_svg(
            svg_path=image_path,
            target_width_mm=target_width_mm,
            color_replacements=vector_replacements,
        )

        # 1b. Build 3D mesh from analysis
        build_mesh_kwargs = {
            "analysis": analysis,
            "thickness_mm": spacer_thick,
            "structure_mode": structure_mode,
        }
        try:
            build_mesh_signature = inspect.signature(vec_processor.build_mesh)
        except (TypeError, ValueError):
            build_mesh_signature = None
        if build_mesh_signature is not None:
            parameters = build_mesh_signature.parameters
            accepts_var_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values())
            if accepts_var_kwargs or "enable_fridge_magnet" in parameters:
                build_mesh_kwargs["enable_fridge_magnet"] = enable_fridge_magnet
            if accepts_var_kwargs or "fridge_magnets" in parameters:
                build_mesh_kwargs["fridge_magnets"] = fridge_magnets

        scene = vec_processor.build_mesh(**build_mesh_kwargs)
        vector_timing["mesh_total_s"] = time.perf_counter() - mesh_t0
        if isinstance(getattr(vec_processor, "last_stage_timings", None), dict):
            vector_timing.update(vec_processor.last_stage_timings)

        if len(scene.geometry) == 0:
            ctx["error"] = "[ERROR] Vector mesh generation failed: no valid geometry generated"
            return ctx

        # 1.5a Use color config from analysis (already resolved)
        vec_color_mode = vec_processor.color_mode
        vec_preview_colors = dict(analysis.preview_colors)
        vec_slot_list = analysis.slot_names

        for _mid, _rgba in list(vec_preview_colors.items()):
            if isinstance(_mid, int) and _mid < len(vec_slot_list):
                vec_preview_colors[vec_slot_list[_mid]] = _rgba

        # 1.5b separate_backing handling
        separate_backing = ctx.get("separate_backing", False)
        board_geom = scene.geometry.get("Board")
        if board_geom is not None and not separate_backing:
            first_slot = vec_slot_list[0] if vec_slot_list else None
            first_geom = scene.geometry.get(first_slot) if first_slot else None
            if first_geom is not None:
                import trimesh as _trimesh

                merged = _trimesh.util.concatenate([first_geom, board_geom])
                merged.visual.face_colors = first_geom.visual.face_colors
                merged.metadata["name"] = first_slot
                scene.geometry[first_slot] = merged
                del scene.geometry["Board"]
                log.info(f"[COORDINATOR] Vector: merged Board into '{first_slot}' (separate_backing=false)")
            else:
                log.info("[COORDINATOR] Vector: Board exists but first slot not found, keeping Board as-is")
        elif board_geom is not None and separate_backing:
            vec_preview_colors["Board"] = vec_preview_colors.get(0, [255, 255, 255, 255])
            log.info("[COORDINATOR] Vector: keeping Board as separate backing (separate_backing=true)")

        # 2. Export 3MF
        _report_progress(ctx, 0.72, "导出 3MF 中... | Exporting 3MF...")
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        out_path = os.path.join(MODELS_DIR, generate_model_filename(base_name, modeling_mode, color_mode))

        vec_slot_names = []
        for geom_name, geom in scene.geometry.items():
            vertices = getattr(geom, "vertices", None)
            faces = getattr(geom, "faces", None)
            v_count = len(vertices) if vertices is not None else 0
            f_count = len(faces) if faces is not None else 0
            if v_count == 0 or f_count == 0:
                log.info(f"[COORDINATOR] Skipping empty vector geometry '{geom_name}' (v={v_count}, f={f_count})")
                continue
            vec_slot_names.append(geom_name)

        if not vec_slot_names:
            ctx["error"] = "[ERROR] Vector export aborted: all generated geometries are empty"
            return ctx

        vec_print_settings = {
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

        export_t0 = time.perf_counter()
        export_scene_with_bambu_metadata(
            scene=scene,
            output_path=out_path,
            slot_names=vec_slot_names,
            preview_colors=vec_preview_colors,
            settings=vec_print_settings,
            color_mode=vec_color_mode,
            printer_id=ctx.get("printer_id", "bambu-h2d"),
            slicer=ctx.get("slicer", "BambuStudio"),
        )
        log.info(f"[COORDINATOR] Vector 3MF exported with Bambu metadata: {out_path}")
        vector_timing["export_3mf_s"] = time.perf_counter() - export_t0

        # 3. GLB preview
        _report_progress(ctx, 0.82, "生成 3D 预览中... | Generating 3D preview...")
        glb_path = None
        glb_t0 = time.perf_counter()
        try:
            glb_path = os.path.join(OUTPUT_DIR, generate_preview_filename(base_name))
            scene.export(glb_path)
            log.info(f"[COORDINATOR] Preview GLB exported: {glb_path}")
        except COORDINATOR_HANDLED_ERRORS as e:
            log.warning(f"[COORDINATOR] Preview generation skipped: {e}")
        vector_timing["export_glb_s"] = time.perf_counter() - glb_t0

        # 4. 2D preview from analyzed geometry (same data as 3MF)
        _report_progress(ctx, 0.90, "生成 2D 预览中... | Generating 2D preview...")
        preview_img = None
        preview_t0 = time.perf_counter()
        need_2d_preview = ctx.get("need_2d_preview", True)
        skip_heavy_preview = os.getenv("LUMINA_VECTOR_SKIP_2D_PREVIEW", "0") == "1"
        if skip_heavy_preview or not need_2d_preview:
            reason = "env flag" if skip_heavy_preview else "caller does not need it"
            log.info("[COORDINATOR] Skipping SVG 2D preview (%s)", reason)
        else:
            try:
                preview_img = VectorProcessor.render_preview(analysis, pixels_per_mm=10.0)
                log.info("[COORDINATOR] Generated 2D vector preview from analyzed geometry")
            except COORDINATOR_HANDLED_ERRORS as e:
                log.warning("[COORDINATOR] Failed to render vector preview: %s", e)
        vector_timing["preview_2d_s"] = time.perf_counter() - preview_t0

        # 5. Stats & timing
        Stats.increment("conversions")
        vector_timing["vector_branch_total_s"] = time.perf_counter() - vector_total_t0
        _log_vector_timings(vector_timing)

        msg = "Vector conversion complete! Objects merged by material."
        if getattr(vec_processor, "parse_warnings", None):
            msg += " ⚠ " + "; ".join(vec_processor.parse_warnings)
        ctx["result_tuple"] = (out_path, glb_path, preview_img, msg, None)
        return ctx

    except ModuleNotFoundError as e:
        error_msg = f"Vector processing failed: {e}"
        log.error(f"[COORDINATOR] {error_msg}")
        ctx["error"] = error_msg
        return ctx

    except COORDINATOR_HANDLED_ERRORS as e:
        error_msg = (
            f"Vector processing failed: {e}\n\n"
            "Suggestions:\n"
            "- Ensure SVG has filled paths (not just strokes)\n"
            "- Try opening in Inkscape and re-saving as 'Plain SVG'\n"
            "- Convert text to paths (Path -> Object to Path)\n"
            "- Or switch to 'High-Fidelity' mode for rasterization"
        )
        log.exception(f"[COORDINATOR] {error_msg}")
        ctx["error"] = error_msg
        return ctx


def _log_vector_timings(timings: dict) -> None:
    """Log vector branch timing breakdown.
    输出矢量分支计时明细。

    Args:
        timings: 计时字典
    """
    if not timings:
        return
    log.info(
        "[COORDINATOR] Vector timings (s): "
        f"parse={timings.get('parse_s', 0.0):.3f}, "
        f"clip={timings.get('occlusion_s', 0.0):.3f}, "
        f"match={timings.get('color_match_s', 0.0):.3f}, "
        f"extrude_bottom={timings.get('extrude_bottom_s', 0.0):.3f}, "
        f"backing={timings.get('backing_s', 0.0):.3f}, "
        f"extrude_top={timings.get('extrude_top_s', 0.0):.3f}, "
        f"assemble={timings.get('assemble_s', 0.0):.3f}, "
        f"mesh_total={timings.get('mesh_total_s', 0.0):.3f}, "
        f"export_3mf={timings.get('export_3mf_s', 0.0):.3f}, "
        f"export_glb={timings.get('export_glb_s', 0.0):.3f}, "
        f"preview_2d={timings.get('preview_2d_s', 0.0):.3f}, "
        f"total={timings.get('vector_branch_total_s', 0.0):.3f}"
    )
