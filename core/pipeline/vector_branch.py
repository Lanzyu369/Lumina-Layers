"""
Pipeline vector branch — SVG \u539f\u751f\u77e2\u91cf\u8f6c\u6362\u5206\u652f\u3002
SVG-native vector conversion branch for the staged pipeline.

\u672c\u6a21\u5757\u4ece ``core/pipeline/coordinator.py`` \u4e2d\u62bd\u51fa\u539f\u6709\u7684\u77e2\u91cf\u5206\u652f\u5b9e\u73b0\uff0c\u4f7f
``coordinator.py`` \u91cd\u65b0\u62e5\u6709\u5355\u4e00\u804c\u8d23\uff08\u53ea\u5145\u5f53raster/preview \u8868\u9a71\u52a8
\u8c03\u5ea6\u5668\uff09\u3002\u51fd\u6570\u4e0e\u4e8b\u4ef6\u540d\u7167\u539f\u6837\u4fdd\u7559\uff0c\u91cd\u6784\u4e3a\u7eaf\u6587\u4ef6\u643c\u8fc1\u3002

This module hosts the SVG-native conversion branch that used to live inline
inside ``core.pipeline.coordinator``. The extraction restores
``coordinator.py``'s single responsibility (table-driven raster + preview
orchestration) without changing any public behavior, function signatures, or
structured-logging event names.

Public callables (re-exported by ``coordinator`` for backward compatibility):
\u516c\u5171\u8c03\u7528\u70b9\uff08``coordinator`` \u91cd\u5bfc\u51fa\u4ee5\u4fdd\u8bc1\u5411\u540e\u517c\u5bb9\uff09\uff1a

- ``_run_vector_branch(ctx) -> dict``: SVG \u2192 3MF/GLB/2D \u9884\u89c8 \u5b8c\u6574\u8f6c\u6362\u5206\u652f\u3002
- ``_run_vector_preview_branch(ctx) -> dict``: SVG \u9884\u89c8\u7f13\u5b58\u6784\u5efa\u3002
- ``_update_bambu_base_layer_ctx_for_vector(...)``: Bambu \u5e95\u677f\u53ec\u552e\u5c01\u88c5\u3002
- ``_log_vector_timings(...)``: \u8ba1\u65f6\u660e\u7ec6\u8f93\u51fa\u3002
"""

from __future__ import annotations

import inspect
import os
import time

import cv2  # noqa: F401  -- imported for side-effect parity with coordinator
import numpy as np

from api.structured_logging import get_logger
from config import BedManager
from core.pipeline import p06_bed_rendering, s09_export_3mf
from core.pipeline.pipeline_utils import extract_color_palette
from core.pipeline.s03_color_replacement import _normalize_color_replacements_input

# ---------------------------------------------------------------------------
# Cycle-safe re-import of small helpers that originate in coordinator.
# Defined ABOVE the ``coordinator -> vector_branch`` import in coordinator.py
# so this lookup succeeds during partial module initialisation.
#
# coordinator.py \u5728\u5bfc\u5165\u672c\u6a21\u5757\u4e4b\u524d\u5148\u5b9a\u4e49\u4e86 ``COORDINATOR_HANDLED_ERRORS``
# \u4e0e ``_report_progress``\uff0c\u56e0\u6b64\u4e0b\u9762\u8fd9\u6b65\u5728\u5faa\u73af\u5bfc\u5165\u4e0a\u4e0b\u6587\u4e2d\u4ecd\u80fd\u62ff\u5230\u5b8c\u6574\u5b9a\u4e49\u3002
# ---------------------------------------------------------------------------
from core.pipeline.coordinator import (  # noqa: E402  -- intentional cycle break
    COORDINATOR_HANDLED_ERRORS,
    _report_progress,
)

# Logger namespace is intentionally pinned to the coordinator's name so the
# extraction does not change observable log records (pre-existing tests +
# log audits attach handlers to ``lumina.core.pipeline.coordinator``).
# 日志命名空间故意继续沿用 coordinator，保证抽离后日志可观察性零变更。
log = get_logger("core.pipeline.coordinator")


def _update_bambu_base_layer_ctx_for_vector(
    ctx: dict,
    *,
    color_mode: str,
    structure_mode: str,
    num_layers: int,
    thickness_mm: float,
) -> None:
    """Populate Bambu base-layer modifier values for the vector export branch.
    \u4e3a\u77e2\u91cf\u5bfc\u51fa\u5206\u652f\u586b\u5145 Bambu \u5e95\u677f\u7c97\u5c42\u9ad8\u76f8\u5173\u4e0a\u4e0b\u6587\u503c\u3002

    Args:
        ctx (dict): Pipeline context updated in place.
            \uff08\u5c31\u5730\u66f4\u65b0\u7684\u6d41\u6c34\u7ebf\u4e0a\u4e0b\u6587\u5b57\u5178\uff09
        color_mode (str): Effective color mode resolved by the vector branch.
            \uff08\u77e2\u91cf\u5206\u652f\u89e3\u6790\u540e\u7684\u989c\u8272\u6a21\u5f0f\uff09
        structure_mode (str): Effective structure mode used for mesh extrusion.
            \uff08\u7528\u4e8e\u7f51\u683c\u62c9\u4f38\u7684\u5b9e\u9645\u7ed3\u6784\u6a21\u5f0f\uff09
        num_layers (int): Optical color-layer count reported by vector analysis.
            \uff08\u77e2\u91cf\u5206\u6790\u5f97\u5230\u7684\u5f69\u8272\u5149\u5b66\u5c42\u5c42\u6570\uff09
        thickness_mm (float): Requested backing thickness in millimetres.
            \uff08\u8bf7\u6c42\u7684\u5e95\u677f\u539a\u5ea6\uff0c\u5355\u4f4d\u6beb\u7c73\uff09
    """
    from config import PrinterConfig

    layer_h = PrinterConfig.LAYER_HEIGHT
    backing_layer_count = max(1, int(round(float(thickness_mm) / layer_h)))
    base_height_mm = backing_layer_count * layer_h
    color_height_mm = max(0, int(num_layers)) * layer_h

    structure_mode_text = str(structure_mode or "")
    color_mode_text = str(color_mode or "")
    is_double = "\u53cc\u9762" in structure_mode_text or "Double" in structure_mode_text
    is_5color = "5-Color Extended" in color_mode_text

    if is_double:
        face_orientation = "double"
    elif is_5color:
        face_orientation = "up"
    else:
        face_orientation = "down"

    ctx["bambu_base_height_mm"] = float(base_height_mm)
    ctx["bambu_color_height_mm"] = float(color_height_mm)
    ctx["bambu_face_orientation"] = face_orientation
    ctx["enable_base_layer_height_modifier"] = bool(ctx.get("enable_base_layer_height_modifier", True))


# ===================================================================
# Vector preview branch (SVG native preview processing)
# ===================================================================


def _run_vector_preview_branch(ctx: dict) -> dict:
    """Execute SVG native preview processing for vector mode.
    \u4e3a SVG + vector \u6a21\u5f0f\u6784\u5efa\u4e0e native vector \u751f\u6210\u4e00\u81f4\u7684\u9884\u89c8\u7f13\u5b58\u3002
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
        log.exception("Vector preview branch failed: %s", exc)
        return ctx


# ===================================================================
# Vector branch (SVG native processing)
# ===================================================================


def _run_vector_branch(ctx: dict) -> dict:
    """Execute SVG native vector processing branch.
    \u6267\u884c SVG \u539f\u751f\u77e2\u91cf\u5904\u7406\u5206\u652f\u3002

    \u5f53 S01 \u68c0\u6d4b\u5230 ``is_svg_vector=True`` \u65f6\u7531 ``run_raster_pipeline``
    \u8c03\u7528\u3002\u4f7f\u7528 ``core.vector_engine.VectorProcessor`` \u5b8c\u6210 SVG \u2192 3D
    \u8f6c\u6362\uff0c\u5305\u62ec 3MF \u5bfc\u51fa\u3001GLB \u9884\u89c8\u548c 2D \u9884\u89c8\u751f\u6210\u3002

    Args:
        ctx: \u7ecf\u8fc7 S01 \u9a8c\u8bc1\u540e\u7684 PipelineContext \u5b57\u5178

    Returns:
        \u66f4\u65b0\u540e\u7684 PipelineContext \u5b57\u5178\uff08\u5305\u542b result_tuple\uff09
    """
    from config import ColorSystem, MODELS_DIR, OUTPUT_DIR  # noqa: F401  -- ColorSystem kept for parity
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
    recipe_overrides = ctx.get("recipe_overrides") or []
    recipe_override_masks_path = ctx.get("recipe_override_masks_path")
    requested_color_layers = ctx.get("color_layers")
    lut_metadata = ctx.get("lut_metadata")
    matched_rgb_path = ctx.get("matched_rgb_path")
    mask_solid_path = ctx.get("mask_solid_path")

    vector_timing = {}
    vector_total_t0 = time.perf_counter()
    log.info(
        "Vector branch started",
        extra={
            "event": "vector_branch_init",
            "image_name": os.path.basename(str(image_path)),
            "color_mode": str(color_mode),
            "modeling_mode": str(modeling_mode),
            "target_width_mm": float(target_width_mm),
            "structure_mode": str(structure_mode),
            "has_replacement_regions": bool(replacement_regions),
            "has_color_replacements": bool(color_replacements),
            "has_recipe_overrides": bool(recipe_overrides),
        },
    )

    # ---- Normalize color replacements ----
    vector_replacements = _normalize_color_replacements_input(replacement_regions)
    if not vector_replacements:
        vector_replacements = _normalize_color_replacements_input(color_replacements)

    try:
        from core.vector_engine import (
            VectorProcessor,
            apply_matched_rgb_overrides_to_analysis,
            apply_recipe_overrides_to_analysis,
        )

        vec_processor = VectorProcessor(actual_lut_path, color_mode)
        vec_processor.enable_fridge_magnet = bool(enable_fridge_magnet)
        vec_processor.fridge_magnets = list(fridge_magnets)

        # 1. Unified analysis: parse \u2192 clip \u2192 match (shared by preview + mesh)
        _report_progress(ctx, 0.05, "SVG \u89e3\u6790\u4e0e\u51e0\u4f55\u5904\u7406\u4e2d... | Parsing & extruding SVG...")
        mesh_t0 = time.perf_counter()
        analysis = vec_processor.analyze_svg(
            svg_path=image_path,
            target_width_mm=target_width_mm,
            color_replacements=vector_replacements,
        )

        # 1.1 Project ColorWorkstation region edits (``/region-replace``,
        # ``/region-replace-batch``) back into ``analysis.matched_shapes``.
        # The 2D preview / GLB previews route through ``cache.matched_rgb``,
        # so without this step the SVG-native 3MF would silently drop every
        # spatial colour edit the user made.
        # \u628a ColorWorkstation \u7684\u533a\u57df\u6539\u8272\uff08/region-replace \u7b49\u7aef\u70b9\uff09\u56de\u5199\u5230
        # analysis.matched_shapes\uff0c\u5426\u5219\u77e2\u91cf 3MF \u4f1a\u4e22\u5931\u6240\u6709\u7a7a\u95f4\u66ff\u6362\uff0c\u9020\u6210
        # "2D \u9884\u89c8\u53d8\u4e86\u3001\u6700\u7ec8\u6a21\u578b\u6ca1\u53d8" \u7684\u73b0\u8c61\u3002
        if matched_rgb_path and mask_solid_path:
            try:
                cached_matched_rgb = np.load(matched_rgb_path)
                cached_mask_solid = np.load(mask_solid_path).astype(bool)
                rewritten = apply_matched_rgb_overrides_to_analysis(
                    analysis,
                    matched_rgb=cached_matched_rgb,
                    mask_solid=cached_mask_solid,
                    img_processor=vec_processor.img_processor,
                )
                if rewritten:
                    log.info(
                        "Vector matched RGB overrides applied",
                        extra={
                            "event": "vector_matched_rgb_overrides_applied",
                            "shapes_rewritten": int(rewritten),
                            "matched_rgb_path": str(matched_rgb_path),
                            "mask_solid_path": str(mask_solid_path),
                        },
                    )
            except COORDINATOR_HANDLED_ERRORS as exc:
                log.warning(
                    "Failed to apply vector matched RGB overrides",
                    extra={
                        "event": "vector_matched_rgb_overrides_failed",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "matched_rgb_path": str(matched_rgb_path),
                        "mask_solid_path": str(mask_solid_path),
                    },
                )

        # 1a. Apply per-region recipe overrides (custom recipe dialog +
        # appended layers) before meshing. Without this the 3MF is built
        # from the LUT's default match and silently ignores every edit
        # the user made in the "\u81ea\u5b9a\u4e49\u914d\u65b9" dialog \u2014 the 2D preview +
        # segmented GLB would reflect the override (they read the
        # material_matrix updated by ``/convert/apply-recipe-override``)
        # but the vector 3MF would not.
        # \u751f\u6210\u7f51\u683c\u524d\u5148\u628a\u81ea\u5b9a\u4e49\u914d\u65b9\u5bf9\u8bdd\u6846\u91cc\u7684 per-region \u914d\u65b9 / \u8ffd\u52a0\u7684\u5c42
        # \u56de\u5199\u5230 ``matched_shapes``\uff1b\u5426\u5219 3MF \u4ec5\u57fa\u4e8e LUT \u9ed8\u8ba4\u5339\u914d\uff0c\u7528\u6237
        # \u5728 "\u81ea\u5b9a\u4e49\u914d\u65b9" \u91cc\u505a\u7684\u7f16\u8f91\uff08\u5305\u62ec\u52a0\u5c42\uff09\u4f1a\u88ab\u6084\u6084\u4e22\u5f03\uff0c\u53ea\u6709 2D
        # \u9884\u89c8\u548c\u5206\u6bb5 GLB \u80fd\u770b\u5230\u3002
        if recipe_overrides and recipe_override_masks_path:
            import pickle as _pickle

            try:
                with open(recipe_override_masks_path, "rb") as f:
                    vector_region_masks = _pickle.load(f)
            except (OSError, EOFError, ValueError, TypeError, _pickle.PickleError) as exc:
                log.warning(
                    "Failed to load vector recipe override masks",
                    extra={
                        "event": "vector_recipe_overrides_load_failed",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "path": str(recipe_override_masks_path),
                    },
                )
                vector_region_masks = None

            if isinstance(vector_region_masks, dict) and vector_region_masks:
                base_channel_idx = int(getattr(lut_metadata, "base_channel_idx", 0) or 0)
                try:
                    apply_recipe_overrides_to_analysis(
                        analysis,
                        recipe_overrides=recipe_overrides,
                        region_masks=vector_region_masks,
                        target_layers=requested_color_layers,
                        base_channel_idx=base_channel_idx,
                    )
                except COORDINATOR_HANDLED_ERRORS as exc:
                    log.warning(
                        "Vector recipe override application failed",
                        extra={
                            "event": "vector_recipe_overrides_apply_failed",
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            "region_count": len(vector_region_masks),
                            "override_count": len(recipe_overrides),
                        },
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

        _update_bambu_base_layer_ctx_for_vector(
            ctx,
            color_mode=vec_processor.color_mode,
            structure_mode=structure_mode,
            num_layers=analysis.num_layers,
            thickness_mm=spacer_thick,
        )

        if len(scene.geometry) == 0:
            ctx["error"] = "[ERROR] Vector mesh generation failed: no valid geometry generated"
            log.error(
                "Vector branch failed",
                extra={
                    "event": "vector_branch_failed",
                    "error_type": "ValueError",
                    "error_message": ctx["error"],
                    "stage": "build_mesh",
                },
            )
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
                log.debug(
                    "Vector board merged into first material slot",
                    extra={
                        "event": "vector_board_merged",
                        "slot_name": str(first_slot),
                        "separate_backing": False,
                    },
                )
            else:
                log.debug(
                    "Vector board kept because first material slot was not found",
                    extra={
                        "event": "vector_board_kept",
                        "separate_backing": False,
                    },
                )
        elif board_geom is not None and separate_backing:
            vec_preview_colors["Board"] = vec_preview_colors.get(0, [255, 255, 255, 255])
            log.debug(
                "Vector board kept as separate backing",
                extra={
                    "event": "vector_board_separate",
                    "separate_backing": True,
                },
            )

        # 2. Export 3MF
        _report_progress(ctx, 0.72, "\u5bfc\u51fa 3MF \u4e2d... | Exporting 3MF...")
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        out_path = os.path.join(MODELS_DIR, generate_model_filename(base_name, modeling_mode, color_mode))

        vec_slot_names = []
        for geom_name, geom in scene.geometry.items():
            vertices = getattr(geom, "vertices", None)
            faces = getattr(geom, "faces", None)
            v_count = len(vertices) if vertices is not None else 0
            f_count = len(faces) if faces is not None else 0
            if v_count == 0 or f_count == 0:
                log.debug(
                    "Skipping empty vector geometry",
                    extra={
                        "event": "vector_geometry_skipped",
                        "geometry_name": str(geom_name),
                        "vertex_count": int(v_count),
                        "face_count": int(f_count),
                    },
                )
                continue
            vec_slot_names.append(geom_name)

        if not vec_slot_names:
            ctx["error"] = "[ERROR] Vector export aborted: all generated geometries are empty"
            log.error(
                "Vector branch failed",
                extra={
                    "event": "vector_branch_failed",
                    "error_type": "ValueError",
                    "error_message": ctx["error"],
                    "stage": "export_3mf",
                    "geometry_count": len(scene.geometry),
                },
            )
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

        if bool(ctx.get("center_on_bed", True)):
            s09_export_3mf._center_scene_on_printer_bed(scene, ctx.get("printer_id", "bambu-h2d"))

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
            nozzle_size=ctx.get("nozzle_size", "0.4"),
            enable_base_layer_height_modifier=bool(ctx.get("enable_base_layer_height_modifier", True)),
            base_height_mm=float(ctx.get("bambu_base_height_mm", 0.0)),
            color_height_mm=float(ctx.get("bambu_color_height_mm", 0.0)),
            face_orientation=str(ctx.get("bambu_face_orientation", "down")),
        )
        vector_timing["export_3mf_s"] = time.perf_counter() - export_t0
        log.info(
            "Vector 3MF exported with Bambu metadata",
            extra={
                "event": "vector_3mf_exported",
                "path": str(out_path),
                "slot_count": len(vec_slot_names),
                "geometry_count": len(scene.geometry),
                "duration_ms": round(vector_timing["export_3mf_s"] * 1000, 3),
            },
        )

        # 3. GLB preview
        _report_progress(ctx, 0.82, "\u751f\u6210 3D \u9884\u89c8\u4e2d... | Generating 3D preview...")
        glb_path = None
        glb_t0 = time.perf_counter()
        try:
            glb_path = os.path.join(OUTPUT_DIR, generate_preview_filename(base_name))
            scene.export(glb_path)
            log.debug(
                "Vector preview GLB exported",
                extra={
                    "event": "vector_glb_exported",
                    "path": str(glb_path),
                },
            )
        except COORDINATOR_HANDLED_ERRORS as e:
            log.debug(
                "Vector preview GLB export skipped",
                extra={
                    "event": "vector_glb_exported_skipped",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
        vector_timing["export_glb_s"] = time.perf_counter() - glb_t0

        # 4. 2D preview from analyzed geometry (same data as 3MF)
        _report_progress(ctx, 0.90, "\u751f\u6210 2D \u9884\u89c8\u4e2d... | Generating 2D preview...")
        preview_img = None
        preview_t0 = time.perf_counter()
        need_2d_preview = ctx.get("need_2d_preview", True)
        skip_heavy_preview = os.getenv("LUMINA_VECTOR_SKIP_2D_PREVIEW", "0") == "1"
        if skip_heavy_preview or not need_2d_preview:
            reason = "env flag" if skip_heavy_preview else "caller does not need it"
            log.debug(
                "Skipping SVG 2D preview",
                extra={
                    "event": "vector_2d_preview_skipped",
                    "reason": reason,
                },
            )
        else:
            try:
                preview_img = VectorProcessor.render_preview(analysis, pixels_per_mm=10.0)
                log.debug(
                    "Generated 2D vector preview from analyzed geometry",
                    extra={"event": "vector_2d_preview_done"},
                )
            except COORDINATOR_HANDLED_ERRORS as e:
                log.warning(
                    "Failed to render vector preview",
                    extra={
                        "event": "vector_2d_preview_failed",
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                )
        vector_timing["preview_2d_s"] = time.perf_counter() - preview_t0

        # 5. Stats & timing
        Stats.increment("conversions")
        vector_timing["vector_branch_total_s"] = time.perf_counter() - vector_total_t0
        _log_vector_timings(vector_timing)

        msg = "Vector conversion complete! Objects merged by material."
        if getattr(vec_processor, "parse_warnings", None):
            msg += " \u26a0 " + "; ".join(vec_processor.parse_warnings)
        ctx["result_tuple"] = (out_path, glb_path, preview_img, msg, None)
        log.info(
            "Vector branch completed",
            extra={
                "event": "vector_branch_done",
                "duration_ms": round(vector_timing["vector_branch_total_s"] * 1000, 3),
                "path": str(out_path),
                "glb_path": str(glb_path) if glb_path else None,
                "slot_count": len(vec_slot_names),
                "geometry_count": len(scene.geometry),
                "preview_2d_generated": preview_img is not None,
                "parse_warning_count": len(getattr(vec_processor, "parse_warnings", None) or []),
            },
        )
        return ctx

    except ModuleNotFoundError as e:
        error_msg = f"Vector processing failed: {e}"
        log.exception(
            "Vector branch failed",
            extra={
                "event": "vector_branch_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
                "dependency": getattr(e, "name", None),
            },
        )
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
        log.exception(
            "Vector branch failed",
            extra={
                "event": "vector_branch_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
                "stage": "vector_processing",
            },
        )
        ctx["error"] = error_msg
        return ctx


def _log_vector_timings(timings: dict) -> None:
    """Log vector branch timing breakdown.
    \u8f93\u51fa\u77e2\u91cf\u5206\u652f\u8ba1\u65f6\u660e\u7ec6\u3002

    Args:
        timings: \u8ba1\u65f6\u5b57\u5178
    """
    if not timings:
        return
    log.debug(
        "Vector timings (s): "
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
        f"total={timings.get('vector_branch_total_s', 0.0):.3f}",
        extra={
            "event": "vector_timings",
            "timings": {str(key): float(value) for key, value in timings.items()},
        },
    )
