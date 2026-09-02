"""
Lumina Studio - Image Converter Coordinator (Refactored)

Thin wrapper layer + re-exports for backward compatibility.
薄包装层 + re-export，保持向后兼容。

converter.py 从 4500+ 行的巨型文件重构为：
1. convert_image_to_3d / generate_preview_cached 薄包装（委托给 coordinator）
2. re-export 所有被外部引用的函数（保持 from core.converter import XXX 兼容）
"""

import os
import time
import logging
from collections import deque
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
from typing import List, Dict, Tuple, Optional

from config import (
    SVG_PIXELS_PER_MM_DEFAULT,
    PrinterConfig,
    ColorSystem,
    ModelingMode,
    PREVIEW_SCALE,
    PREVIEW_MARGIN,
    OUTPUT_DIR,
    BedManager,
)
from utils import Stats
from core.material_lut_synthesis import infer_material_archive_base_channel_idx

# ========== Re-exports from pipeline modules ==========
# 保持 `from core.converter import XXX` 对所有现有调用方仍然有效

# --- pipeline_utils ---
from core.pipeline.pipeline_utils import (
    extract_color_palette,
    _rgb_to_hex,
    _hex_to_rgb_tuple,
    calculate_luminance,
    extract_lut_available_colors,
    get_lut_color_choices,
    generate_lut_color_dropdown_html,
    detect_lut_color_mode,
    detect_image_type,
    _ensure_quantized_image_in_cache,
    generate_auto_height_map,
    _recommend_lut_colors_by_rgb,
    _build_selection_meta,
    _resolve_highlight_mask,
    _build_dual_recommendations,
    _resolve_click_selection_hexes,
    generate_lut_grid_html,
    generate_lut_card_grid_html,
)

# --- s03_color_replacement ---
from core.pipeline.s03_color_replacement import (
    _normalize_color_replacements_input,
    _apply_region_replacement,
    _apply_regions_to_raster_outputs,
    _compute_connected_region_mask_4n,
)

# --- s11_glb_preview ---
from core.pipeline.s11_glb_preview import (
    generate_segmented_glb,
    generate_realtime_glb,
    generate_empty_bed_glb,
    _create_preview_mesh,
    _merge_low_frequency_colors,
)

# --- s06_voxel_building ---
from core.pipeline.s06_voxel_building import (
    _build_voxel_matrix,
    _build_voxel_matrix_faceup,
    _build_relief_voxel_matrix,
    _build_cloisonne_voxel_matrix,
    _normalize_color_height_map,
)

# --- s05_preview_generation ---
from core.pipeline.s05_preview_generation import (
    _calculate_loop_position,
    _calculate_loop_info,
    _draw_loop_on_preview,
)

# --- s08_auxiliary_meshes ---
from core.pipeline.s08_auxiliary_meshes import (
    _generate_outline_mesh,
    _parse_outline_slot,
)

# --- s04_debug_preview ---
from core.pipeline.s04_debug_preview import _save_debug_preview

# --- p06_bed_rendering ---
from core.pipeline.p06_bed_rendering import (
    render_preview,
    _draw_loop_on_canvas,
    _create_bed_mesh,
)

# --- coordinator ---
from core.pipeline.coordinator import run_raster_pipeline, run_preview_pipeline

# Try to import LUTManager for metadata loading
try:
    from utils.lut_manager import LUTManager
except ImportError:
    LUTManager = None

log = logging.getLogger(__name__)


def _raise_dynamic_material_pipeline_error(ctx: dict) -> None:
    """Re-raise a typed dynamic failure retained by a pipeline coordinator.

    重新抛出管线协调器保留的动态类型化失败。

    Args:
        ctx: Completed or failed pipeline context. 已完成或失败的管线上下文。

    Raises:
        DynamicMaterialCandidateError: When candidate construction or lookup
            failed. 候选构建或查找失败时抛出。
        DynamicMaterialSolverError: When both exact engines failed. 两个精确
            引擎均失败时抛出。
    """
    envelope = ctx.get("material_dynamic_layer_error")
    if not isinstance(envelope, dict):
        return
    failure = envelope.get("exception")
    if failure is None:
        return
    from core.material_dynamic_solver import (
        DynamicMaterialCandidateError,
        DynamicMaterialSolverError,
    )

    if isinstance(
        failure,
        (DynamicMaterialCandidateError, DynamicMaterialSolverError),
    ):
        raise failure


def _resolve_material_archive_backing_color_id(
    selected_materials: Optional[List[str]],
    material_backing_material_index: Optional[int],
) -> int:
    if material_backing_material_index is None:
        materials = (
            list(selected_materials)
            if isinstance(selected_materials, (list, tuple))
            else []
        )
        return infer_material_archive_base_channel_idx(materials, [], {})
    try:
        backing_color_id = int(material_backing_material_index)
    except (TypeError, ValueError) as exc:
        raise ValueError("material_backing_material_index must be an integer") from exc
    if backing_color_id < 0:
        raise ValueError("material_backing_material_index must be >= 0")
    if selected_materials and backing_color_id >= len(selected_materials):
        raise ValueError(
            "material_backing_material_index is outside selected_materials range"
        )
    if not selected_materials and backing_color_id != 0:
        raise ValueError(
            "material_backing_material_index requires selected_materials"
        )
    return backing_color_id


def _resolve_converter_separate_backing_color_id(
    material_source: str,
    selected_materials: Optional[List[str]],
    material_backing_material_index: Optional[int],
    separate_backing_color_id: Optional[int],
) -> Optional[int]:
    if material_source != "material_archive" or separate_backing_color_id is not None:
        return separate_backing_color_id
    return _resolve_material_archive_backing_color_id(
        selected_materials,
        material_backing_material_index,
    )


def _build_color_contour_mesh(mask, height, total_layers, rgba):
    """Build a simple extruded mesh for a boolean mask.
    构建布尔掩码的简化挤出网格（兼容旧导出符号）。
    This compatibility helper is kept in ``core.converter`` because legacy tests
    and callers import it from here. Implementation is intentionally minimal:
    each True pixel is extruded to a box and concatenated into one mesh.
    该兼容函数保留在 ``core.converter``，用于维持历史导入契约。
    实现保持最小化：每个 True 像素挤出为盒体并合并为单个 mesh。"""
    import trimesh

    mask_arr = np.asarray(mask, dtype=bool)
    if mask_arr.ndim != 2 or not np.any(mask_arr):
        return None

    h, w = mask_arr.shape
    z_extent = float(total_layers)
    boxes = []

    for y, x in np.argwhere(mask_arr):
        # Keep a deterministic XY mapping while ensuring Z span is [0, total_layers].
        center_x = float(x) + 0.5
        center_y = float(h - 1 - y) + 0.5
        center_z = z_extent / 2.0

        box = trimesh.creation.box(extents=(1.0, 1.0, z_extent))
        box.apply_translation((center_x, center_y, center_z))
        box.visual.face_colors = np.array(rgba, dtype=np.uint8)
        boxes.append(box)

    if not boxes:
        return None

    merged = trimesh.util.concatenate(boxes)
    merged.visual.face_colors = np.array(rgba, dtype=np.uint8)
    return merged


def build_image_model_context(
    *,
    stop_after_step: str | None = None,
    progress=None,
    **kwargs,
) -> dict:
    """Build a converter pipeline context for callers that need the scene.

    为需要复用 scene 的调用方构建转换管线上下文。

    Args:
        stop_after_step: Optional staged pipeline label such as ``"S08"``.
            可选的分阶段管线停止点，例如 ``"S08"``。
        progress: Optional progress callback forwarded to the pipeline.
            可选的进度回调，会透传给管线。
        **kwargs: Standard converter arguments accepted by ``convert_image_to_3d``.
            ``convert_image_to_3d`` 接受的标准转换参数。

    Returns:
        Pipeline context, possibly stopped before final export.
        管线上下文，可能已在最终导出前停止。
    """

    ctx = dict(kwargs)
    ctx["progress"] = progress
    # Intentional: the API layer produces its own GLB preview, so skip the
    # heavy SVG->raster 2D preview inside the vector branch coordinator.
    ctx["need_2d_preview"] = False
    # Mirror cover source onto a stable ctx key; fall back to image_path so
    # downstream pipeline stages can pick a sane default without the caller
    # opting in. 大画幅光栅模式下 image_path 已经是 tile PNG，所以无需 worker
    # 侧改动即能让每片 3MF 拿到自己的封面图源。
    ctx["cover_source_path"] = ctx.get("cover_source_path") or ctx.get("image_path")
    if stop_after_step:
        ctx["stop_after_step"] = stop_after_step
    return run_raster_pipeline(ctx)


# ========== Main Conversion Function (Thin Wrapper) ==========


def convert_image_to_3d(
    image_path,
    lut_path,
    target_width_mm,
    spacer_thick,
    structure_mode,
    color_mode,
    add_loop,
    loop_width,
    loop_length,
    loop_hole,
    loop_pos,
    modeling_mode=ModelingMode.VECTOR,
    color_layers: Optional[int] = None,
    layer_height_mm: Optional[float] = None,
    model_enable: bool = False,
    model_only: bool = False,
    model_threshold: Optional[float] = None,
    model_margin: Optional[float] = None,
    quantize_colors=32,
    blur_kernel=0,
    smooth_sigma=10,
    color_replacements=None,
    replacement_regions=None,
    recipe_overrides=None,
    recipe_override_masks_path: Optional[str] = None,
    backing_color_id=0,
    separate_backing_color_id: Optional[int] = None,
    separate_backing=False,
    enable_relief=False,
    color_height_map=None,
    height_mode: str = "color",
    heightmap_path=None,
    heightmap_max_height=None,
    enable_cleanup=True,
    enable_outline=False,
    outline_width=2.0,
    enable_cloisonne=False,
    wire_width_mm=0.4,
    wire_height_mm=0.4,
    free_color_set=None,
    enable_coating=False,
    coating_height_mm=0.08,
    hue_weight: float = 0.0,
    chroma_gate: float = 15.0,
    matched_rgb_path: Optional[str] = None,
    mask_solid_path: Optional[str] = None,
    quantized_image_path: Optional[str] = None,
    material_matrix_path: Optional[str] = None,
    reuse_preview_analysis: bool = False,
    preview_glb_path: Optional[str] = None,
    vector_parse_clip_cache_path: Optional[str] = None,
    piece_boundary_geometry_path: Optional[str] = None,
    disable_material_dilation: bool = True,
    loop_angle: float = 0.0,
    loop_offset_x: float = 0.0,
    loop_offset_y: float = 0.0,
    loop_position_preset: Optional[str] = "top-center",
    printer_id: str = "bambu-h2d",
    slicer: str = "BambuStudio",
    nozzle_size: str = "0.4",
    device_profile_id: Optional[str] = None,
    build_plate_id: Optional[str] = None,
    enable_base_layer_height_modifier: bool = True,
    center_on_bed: bool = True,
    relief_global_max_height: Optional[float] = None,
    progress=None,
    enable_fridge_magnet: bool = False,
    fridge_magnets: Optional[List[Dict]] = None,
    material_source: str = "lut",
    selected_materials: Optional[List[str]] = None,
    material_layer_count: Optional[int] = None,
    material_layer_height_mm: Optional[float] = None,
    material_grid_resolution: Optional[int] = None,
    material_backing_material_index: Optional[int] = None,
    use_lut_constrained: bool = False,
    auto_dynamic_range: bool = False,
    high_precision_3d_preview: bool = False,
    svg_pixels_per_mm: float = SVG_PIXELS_PER_MM_DEFAULT,
    *,
    backing_infill_density_percent: int = 100,
    height_identity_rgb_path: Optional[str] = None,
    original_matched_rgb_path: Optional[str] = None,
    original_material_matrix_path: Optional[str] = None,
    edit_projection: Optional[Dict[str, object]] = None,
    final_material_matrix_is_authoritative: bool = False,
    final_material_matrix_authority_mask_path: Optional[str] = None,
    cover_source_path: Optional[str] = None,
    export_transform_metadata: Optional[Dict[str, object]] = None,
    material_dynamic_layer_count_enabled: bool = False,
    material_min_layer_count: int = 5,
    material_max_layer_count: int = 10,
    material_delta_e00_tolerance: float = 0.5,
):
    """Main conversion function: Convert image to 3D model.
    主要转换函数：将图像转换为 3D 模型。

    Args:
        enable_fridge_magnet: Whether to enable opt-in fridge-magnet cavity
            handling in downstream raster/vector geometry stages.
            (是否在下游光栅/矢量几何阶段启用可选的冰箱贴磁铁槽处理)
        fridge_magnets: Serialized fridge-magnet item list forwarded through
            the backend contract. (通过后端契约向下游透传的冰箱贴磁铁槽列表)
        cover_source_path: Optional explicit cover thumbnail source path.
            Defaults to ``image_path`` so普通模式与大画幅光栅模式下，每张
            3MF 都使用对应输入图作为封面图源。
            (可选的封面缩略图源路径；缺省镜像 ``image_path``)
        export_transform_metadata: Optional mutable result populated with the
            effective export transform. (可选的可变结果容器，用于返回实际导出
            变换。)
        material_backing_material_index: Optional selected-material index used
            as the backing color when ``material_source`` is
            ``"material_archive"``. Native and legacy LUT flows ignore it.
            (耗材档案模式下作为底板颜色的已选耗材索引；传统 LUT 与反推 LUT
            流程会忽略该值)
        device_profile_id: Optional generated machine registry device profile
            selection forwarded to 3MF export.
            (可选的机器注册表设备配置 ID，透传给 3MF 导出)
        build_plate_id: Optional native slicer build-plate selection forwarded
            to 3MF export. (可选的切片软件原生打印板 ID，透传给 3MF 导出)
        backing_infill_density_percent: Deep-backing sparse-infill percentage;
            viewing-surface protection is added by the 3MF writer.
            (深层底板稀疏填充百分比；观赏面保护由 3MF 写入器添加)
        material_dynamic_layer_count_enabled: Enable exact dynamic effective
            layers for material archives. (为耗材档案启用精确动态有效层数)
        material_min_layer_count: Minimum dynamic effective layers. (动态最小
            有效层数)
        material_max_layer_count: Maximum dynamic effective and physical
            layers. (动态最大有效层数及物理模型层数)
        material_delta_e00_tolerance: Allowed CIEDE2000 loss when preferring a
            shorter recipe. (优先短配方时允许的 CIEDE2000 损失)
        quantized_image_path: Optional dynamic preview-analysis asset used
            together with the other authority arrays when puzzle generation
            explicitly reuses a confirmed material matrix.
             (拼图生成明确复用已确认耗材矩阵时，与其他权威数组一同使用的可选
             动态预览分析资产)
        height_identity_rgb_path: Optional ``.npy`` path containing immutable
            per-pixel source RGB identities used for relief-height lookup after
            display-colour replacement. This is keyword-only so legacy
            positional callers retain their original argument binding.
            (可选的 ``.npy`` 路径，保存颜色替换前、用于浮雕高度查找的稳定逐像素
            RGB 身份；该参数仅允许关键字传入，以保持旧位置参数调用语义不变)
        original_matched_rgb_path: Pristine RGB used to isolate preview-time
            display edits. (用于隔离预览期显示替色的原始 RGB)
        original_material_matrix_path: Pristine material matrix used to
            isolate recipe edits. (用于隔离配方编辑的原始材料矩阵)
        edit_projection: Source-grid metadata for normalized edit replay on a
            fresh-size analysis. (把编辑归一化重放到当前尺寸新分析的源网格元数据)
        final_material_matrix_is_authoritative: Preserve a precomputed final
            material matrix after color mappings update display RGB.
            (颜色映射更新显示 RGB 后，仍保留预计算的最终材料矩阵)
        final_material_matrix_authority_mask_path: Optional ``.npy`` boolean
            mask limiting final-matrix authority to recipe pixels. A missing
            mask means the complete matrix is authoritative.
             (可选 ``.npy`` 布尔掩码，把最终矩阵权威限定在配方像素；
             未提供时整张矩阵权威生效)

    Returns:
        Tuple of (3mf_path, glb_path, preview_image, status_message, recipe_path)
    """
    if (
        material_source == "material_archive"
        and material_backing_material_index is not None
    ):
        backing_color_id = _resolve_material_archive_backing_color_id(
            selected_materials,
            material_backing_material_index,
        )
    separate_backing_color_id = _resolve_converter_separate_backing_color_id(
        material_source,
        selected_materials,
        material_backing_material_index,
        separate_backing_color_id,
    )

    ctx = {k: v for k, v in locals().items() if k != "progress"}
    ctx = build_image_model_context(progress=progress, **ctx)
    _raise_dynamic_material_pipeline_error(ctx)
    if ctx.get("error"):
        return None, None, None, ctx["error"], None
    return ctx.get("result_tuple", (None, None, None, "[ERROR] No result", None))


# ========== Preview Function (Thin Wrapper) ==========


def generate_preview_cached(
    image_path,
    lut_path,
    target_width_mm,
    color_mode,
    modeling_mode: ModelingMode = ModelingMode.HIGH_FIDELITY,
    color_layers: Optional[int] = None,
    layer_height_mm: Optional[float] = None,
    model_enable: bool = False,
    model_only: bool = False,
    model_threshold: Optional[float] = None,
    model_margin: Optional[float] = None,
    quantize_colors: int = 64,
    backing_color_id: int = 0,
    enable_cleanup: bool = True,
    enable_outline: bool = False,
    outline_width: float = 2.0,
    is_dark: bool = True,
    hue_weight: float = 0.0,
    chroma_gate: float = 15.0,
    material_source: str = "lut",
    selected_materials: Optional[List[str]] = None,
    material_layer_count: Optional[int] = None,
    material_layer_height_mm: Optional[float] = None,
    material_grid_resolution: Optional[int] = None,
    use_lut_constrained: bool = False,
    auto_dynamic_range: bool = False,
    high_precision_3d_preview: bool = False,
    svg_pixels_per_mm: float = SVG_PIXELS_PER_MM_DEFAULT,
    replacement_regions=None,
    material_backing_material_index: Optional[int] = None,
    material_dynamic_layer_count_enabled: bool = False,
    material_min_layer_count: int = 5,
    material_max_layer_count: int = 10,
    material_delta_e00_tolerance: float = 0.5,
):
    """Generate preview and cache data. Thin wrapper, delegates to coordinator.
    生成预览图和缓存数据。薄包装函数，委托给 coordinator。

    Args:
        material_backing_material_index: Selected backing material index.
            (用户选择的基板耗材索引)
        material_dynamic_layer_count_enabled: Enable exact dynamic effective
            layers. (启用精确动态有效层数)
        material_min_layer_count: Minimum dynamic effective layers. (动态最小
            有效层数)
        material_max_layer_count: Maximum dynamic effective and physical
            layers. (动态最大有效层数及物理模型层数)
        material_delta_e00_tolerance: Allowed CIEDE2000 loss for shorter
            recipes. (短配方允许的 CIEDE2000 损失)
        quantized_image_path: Optional dynamic preview-analysis asset
            forwarded with the authority matrix for puzzle reuse.
            (拼图复用时随权威矩阵透传的可选动态预览分析资产)

    Returns:
        tuple: (display_image, cache_data, status_message)
    """
    ctx = {k: v for k, v in locals().items()}

    ctx = run_preview_pipeline(ctx)
    _raise_dynamic_material_pipeline_error(ctx)
    if ctx.get("error"):
        return None, None, ctx["error"]
    return ctx.get("display_image"), ctx.get("cache"), ctx.get("status_msg", "[OK]")


# ========== Preview Helper Functions ==========


def update_preview_with_loop(cache, loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle):
    """Update preview image with keychain loop."""
    if cache is None:
        return None

    preview_rgba = cache["preview_rgba"].copy()
    color_conf = cache["color_conf"]
    target_width_mm = cache.get("target_width_mm")
    is_dark = cache.get("is_dark", True)

    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        add_loop,
        color_conf,
        bed_label=cache.get("bed_label"),
        target_width_mm=target_width_mm,
        is_dark=is_dark,
    )
    return display


def on_remove_loop():
    """Remove keychain loop."""
    return None, False, 0, "Loop removed"


def generate_final_model(
    image_path,
    lut_path,
    target_width_mm,
    spacer_thick,
    structure_mode,
    color_mode,
    add_loop,
    loop_width,
    loop_length,
    loop_hole,
    loop_pos,
    modeling_mode=ModelingMode.VECTOR,
    color_layers: Optional[int] = None,
    layer_height_mm: Optional[float] = None,
    model_enable: bool = False,
    model_only: bool = False,
    model_threshold: Optional[float] = None,
    model_margin: Optional[float] = None,
    quantize_colors=64,
    color_replacements=None,
    replacement_regions=None,
    recipe_overrides=None,
    recipe_override_masks_path: Optional[str] = None,
    backing_color_name="White",
    separate_backing_color_id: Optional[int] = None,
    separate_backing=False,
    enable_relief=False,
    color_height_map=None,
    height_mode: str = "color",
    heightmap_path=None,
    heightmap_max_height=None,
    enable_cleanup=True,
    enable_outline=False,
    outline_width=2.0,
    enable_cloisonne=False,
    wire_width_mm=0.4,
    wire_height_mm=0.4,
    free_color_set=None,
    enable_coating=False,
    coating_height_mm=0.08,
    hue_weight: float = 0.0,
    chroma_gate: float = 15.0,
    matched_rgb_path: Optional[str] = None,
    mask_solid_path: Optional[str] = None,
    quantized_image_path: Optional[str] = None,
    material_matrix_path: Optional[str] = None,
    reuse_preview_analysis: bool = False,
    preview_glb_path: Optional[str] = None,
    vector_parse_clip_cache_path: Optional[str] = None,
    piece_boundary_geometry_path: Optional[str] = None,
    disable_material_dilation: bool = True,
    loop_angle: float = 0.0,
    loop_offset_x: float = 0.0,
    loop_offset_y: float = 0.0,
    loop_position_preset: Optional[str] = "top-center",
    printer_id: str = "bambu-h2d",
    slicer: str = "BambuStudio",
    nozzle_size: str = "0.4",
    device_profile_id: Optional[str] = None,
    build_plate_id: Optional[str] = None,
    enable_base_layer_height_modifier: bool = True,
    center_on_bed: bool = True,
    relief_global_max_height: Optional[float] = None,
    progress=None,
    enable_fridge_magnet: bool = False,
    fridge_magnets: Optional[List[Dict]] = None,
    material_source: str = "lut",
    selected_materials: Optional[List[str]] = None,
    material_layer_count: Optional[int] = None,
    material_layer_height_mm: Optional[float] = None,
    material_grid_resolution: Optional[int] = None,
    use_lut_constrained: bool = False,
    auto_dynamic_range: bool = False,
    high_precision_3d_preview: bool = False,
    material_backing_material_index: Optional[int] = None,
    svg_pixels_per_mm: float = SVG_PIXELS_PER_MM_DEFAULT,
    *,
    backing_infill_density_percent: int = 100,
    height_identity_rgb_path: Optional[str] = None,
    original_matched_rgb_path: Optional[str] = None,
    original_material_matrix_path: Optional[str] = None,
    edit_projection: Optional[Dict[str, object]] = None,
    final_material_matrix_is_authoritative: bool = False,
    final_material_matrix_authority_mask_path: Optional[str] = None,
    cover_source_path: Optional[str] = None,
    export_transform_metadata: Optional[Dict[str, object]] = None,
    material_dynamic_layer_count_enabled: bool = False,
    material_min_layer_count: int = 5,
    material_max_layer_count: int = 10,
    material_delta_e00_tolerance: float = 0.5,
):
    """Wrapper function for generating final model.
    包装函数，用于生成最终模型。
    Directly calls main conversion function with smart defaults:
    - blur_kernel=0 (disable median filter, preserve details)
    - smooth_sigma=10 (gentle bilateral filter, preserve edges)

    Args:
        enable_fridge_magnet: Whether to enable opt-in fridge-magnet cavity
            handling for supported generation flows. (是否为受支持的生成流程
            启用可选的冰箱贴磁铁槽处理)
        fridge_magnets: Serialized fridge-magnet item list forwarded to the
            main converter entry point. (转发到主转换入口的冰箱贴磁铁槽列表)
        cover_source_path: Optional explicit cover thumbnail source path.
            Forwarded to ``convert_image_to_3d`` which mirrors it onto the
            staged pipeline ctx; defaults to ``image_path``.
            (可选的封面缩略图源路径，最终透传到 staged pipeline ctx)
        export_transform_metadata: Optional mutable result populated by the
            export stage. (由导出阶段写入实际变换信息的可选可变结果容器。)
        device_profile_id: Optional generated machine registry device profile
            selection forwarded to ``convert_image_to_3d`` and 3MF export.
            (可选的机器注册表设备配置 ID，透传到主转换与 3MF 导出)
        build_plate_id: Optional native slicer build-plate selection forwarded
            to ``convert_image_to_3d`` and 3MF export.
            (可选的切片软件原生打印板 ID，透传到主转换与 3MF 导出)
        backing_infill_density_percent: Deep-backing sparse-infill percentage
            forwarded to the 3MF writer.（透传到 3MF 写入器的深层底板稀疏填充
            百分比）
        material_dynamic_layer_count_enabled: Enable exact dynamic effective
            layers. (启用精确动态有效层数)
        material_min_layer_count: Minimum dynamic effective layers. (动态最小
            有效层数)
        material_max_layer_count: Maximum dynamic effective and physical
            layers. (动态最大有效层数及物理模型层数)
        material_delta_e00_tolerance: Allowed CIEDE2000 loss for shorter
             recipes. (短配方允许的 CIEDE2000 损失)
        height_identity_rgb_path: Optional ``.npy`` path containing immutable
            per-pixel source RGB identities for relief-height lookup. It is
            keyword-only to preserve all legacy positional argument bindings.
            (可选的 ``.npy`` 路径，保存浮雕高度查找使用的稳定逐像素源 RGB 身份；
            该参数仅允许关键字传入，以保持全部旧位置参数调用语义不变)
        original_matched_rgb_path: Pristine RGB used to isolate preview-time
            display edits. (用于隔离预览期显示替色的原始 RGB)
        original_material_matrix_path: Pristine material matrix used to
            isolate recipe edits. (用于隔离配方编辑的原始材料矩阵)
        edit_projection: Source-grid metadata for normalized edit replay on a
            fresh-size analysis. (把编辑归一化重放到当前尺寸新分析的源网格元数据)
        final_material_matrix_is_authoritative: Preserve a precomputed final
            material matrix after color mappings update display RGB.
            (颜色映射更新显示 RGB 后，仍保留预计算的最终材料矩阵)
        final_material_matrix_authority_mask_path: Optional ``.npy`` boolean
            mask limiting final-matrix authority to recipe pixels. A missing
            mask means the complete matrix is authoritative.
             (可选 ``.npy`` 布尔掩码，把最终矩阵权威限定在配方像素；
             未提供时整张矩阵权威生效)
    """
    # Convert backing color name to ID or use special marker for separate backing
    try:
        separate_backing = bool(separate_backing) if separate_backing is not None else False
    except (TypeError, ValueError) as exc:
        log.warning(
            "Invalid separate_backing value, fallback to False",
            extra={
                "event": "core_converter_invalid_separate_backing",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        separate_backing = False

    if material_source == "material_archive":
        resolved_backing_color_id = _resolve_material_archive_backing_color_id(
            selected_materials,
            material_backing_material_index,
        )
    else:
        color_conf = ColorSystem.get(color_mode)
        resolved_backing_color_id = color_conf["map"].get(backing_color_name, 0)

    if separate_backing_color_id is None:
        separate_backing_color_id = resolved_backing_color_id

    if separate_backing:
        backing_color_id = -2  # Special marker for separate backing
        log.info(
            "Backing will be separated as individual object",
            extra={
                "event": "core_converter_backing_separated",
                "separate_backing_color_id": int(separate_backing_color_id or 0),
            },
        )
    else:
        backing_color_id = resolved_backing_color_id
        log.info(
            "Resolved backing color",
            extra={
                "event": "core_converter_backing_color_resolved",
                "backing_color_name": backing_color_name,
                "backing_color_id": backing_color_id,
            },
        )

    # Handle relief mode parameters
    if color_height_map is None:
        color_height_map = {}

    return convert_image_to_3d(
        image_path,
        lut_path,
        target_width_mm,
        spacer_thick,
        structure_mode,
        color_mode,
        add_loop,
        loop_width,
        loop_length,
        loop_hole,
        loop_pos,
        modeling_mode,
        color_layers,
        layer_height_mm,
        model_enable,
        model_only,
        model_threshold,
        model_margin,
        quantize_colors,
        svg_pixels_per_mm=svg_pixels_per_mm,
        backing_infill_density_percent=backing_infill_density_percent,
        blur_kernel=0,
        smooth_sigma=10,
        color_replacements=color_replacements,
        replacement_regions=replacement_regions,
        recipe_overrides=recipe_overrides,
        recipe_override_masks_path=recipe_override_masks_path,
        backing_color_id=backing_color_id,
        separate_backing_color_id=separate_backing_color_id,
        separate_backing=separate_backing,
        enable_relief=enable_relief,
        color_height_map=color_height_map,
        height_mode=height_mode,
        heightmap_path=heightmap_path,
        heightmap_max_height=heightmap_max_height,
        enable_cleanup=enable_cleanup,
        enable_outline=enable_outline,
        outline_width=outline_width,
        enable_cloisonne=enable_cloisonne,
        wire_width_mm=wire_width_mm,
        wire_height_mm=wire_height_mm,
        free_color_set=free_color_set,
        enable_coating=enable_coating,
        coating_height_mm=coating_height_mm,
        hue_weight=hue_weight,
        chroma_gate=chroma_gate,
        matched_rgb_path=matched_rgb_path,
        height_identity_rgb_path=height_identity_rgb_path,
        original_matched_rgb_path=original_matched_rgb_path,
        original_material_matrix_path=original_material_matrix_path,
        edit_projection=edit_projection,
        mask_solid_path=mask_solid_path,
        quantized_image_path=quantized_image_path,
        material_matrix_path=material_matrix_path,
        reuse_preview_analysis=reuse_preview_analysis,
        preview_glb_path=preview_glb_path,
        vector_parse_clip_cache_path=vector_parse_clip_cache_path,
        piece_boundary_geometry_path=piece_boundary_geometry_path,
        disable_material_dilation=disable_material_dilation,
        loop_angle=loop_angle,
        loop_offset_x=loop_offset_x,
        loop_offset_y=loop_offset_y,
        loop_position_preset=loop_position_preset,
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=nozzle_size,
        device_profile_id=device_profile_id,
        build_plate_id=build_plate_id,
        enable_base_layer_height_modifier=enable_base_layer_height_modifier,
        center_on_bed=center_on_bed,
        relief_global_max_height=relief_global_max_height,
        progress=progress,
        final_material_matrix_is_authoritative=(
            final_material_matrix_is_authoritative
        ),
        final_material_matrix_authority_mask_path=(
            final_material_matrix_authority_mask_path
        ),
        enable_fridge_magnet=enable_fridge_magnet,
        fridge_magnets=fridge_magnets,
        material_source=material_source,
        selected_materials=selected_materials,
        material_layer_count=material_layer_count,
        material_layer_height_mm=material_layer_height_mm,
        material_grid_resolution=material_grid_resolution,
        material_backing_material_index=material_backing_material_index,
        use_lut_constrained=use_lut_constrained,
        auto_dynamic_range=auto_dynamic_range,
        high_precision_3d_preview=high_precision_3d_preview,
        material_dynamic_layer_count_enabled=material_dynamic_layer_count_enabled,
        material_min_layer_count=material_min_layer_count,
        material_max_layer_count=material_max_layer_count,
        material_delta_e00_tolerance=material_delta_e00_tolerance,
        cover_source_path=cover_source_path,
        export_transform_metadata=export_transform_metadata,
    )


# ========== Color Replacement Functions ==========


def update_preview_with_backing_color(cache, backing_color_id: int):
    """
    Update preview image with new backing color without re-processing the entire image.
    """
    if cache is None:
        return None, "[WARNING] Error: Cache cannot be None"

    try:
        # Validate backing_color_id
        color_conf = cache["color_conf"]
        num_materials = len(color_conf["slots"])
        if backing_color_id < 0 or backing_color_id >= num_materials:
            log.warning(
                "Invalid backing_color_id, fallback to 0",
                extra={
                    "event": "core_converter_invalid_backing_color_id",
                    "backing_color_id": backing_color_id,
                },
            )
            backing_color_id = 0

        # Get data from cache
        material_matrix = cache["material_matrix"]
        mask_solid = cache["mask_solid"]
        preview_rgba = cache["preview_rgba"].copy()

        target_h, target_w = material_matrix.shape[:2]

        # Get backing color from color system
        backing_color_rgba = color_conf["preview"][backing_color_id]
        backing_color_rgb = backing_color_rgba[:3]

        # Check for backing-only pixels: solid pixels where all material layers are -1
        all_layers_transparent = np.all(material_matrix == -1, axis=2)
        backing_only_mask = mask_solid & all_layers_transparent

        # Update backing-only areas with new backing color
        if np.any(backing_only_mask):
            preview_rgba[backing_only_mask, :3] = backing_color_rgb
            preview_rgba[backing_only_mask, 3] = 255
            log.debug(
                "Updated backing-only pixels",
                extra={
                    "event": "core_converter_backing_preview_updated",
                    "backing_pixels": int(np.sum(backing_only_mask)),
                    "backing_color_name": color_conf["slots"][backing_color_id],
                },
            )
        else:
            log.debug(
                "No backing-only pixels found in preview",
                extra={"event": "core_converter_no_backing_pixels"},
            )

        # Update cache with new backing_color_id
        cache["backing_color_id"] = backing_color_id
        cache["preview_rgba"] = preview_rgba.copy()

        return preview_rgba, f"Preview updated with backing color: {color_conf['slots'][backing_color_id]}"

    except (KeyError, TypeError, ValueError) as exc:
        log.warning(
            "Preview update with backing color failed",
            extra={
                "event": "core_converter_backing_preview_update_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        # Return original preview from cache if available
        original_preview = cache.get("preview_rgba") if cache else None
        return original_preview, f"[WARNING] Preview update failed: {str(exc)}. Showing original preview."


def update_preview_with_replacements(
    cache,
    replacement_regions=None,
    loop_pos=None,
    add_loop=False,
    loop_width=4,
    loop_length=8,
    loop_hole=2.5,
    loop_angle=0,
    lang: str = "zh",
    merge_map: dict = None,
):
    """
    Update preview image with color replacements and optional color merging applied.
    """
    if cache is None:
        return None, None, ""

    # Get original matched_rgb (use stored original if available)
    original_rgb = cache.get("original_matched_rgb", cache["matched_rgb"])
    mask_solid = cache["mask_solid"]
    color_conf = cache["color_conf"]
    backing_color_id = cache.get("backing_color_id", 0)
    target_h, target_w = original_rgb.shape[:2]
    # Start with original RGB
    matched_rgb = original_rgb.copy()

    # Apply merge map first (if provided)
    if merge_map:
        from core.color_merger import ColorMerger
        from core.image_processing import LuminaImageProcessor

        merger = ColorMerger(LuminaImageProcessor._rgb_to_lab)
        matched_rgb = merger.apply_color_merging(matched_rgb, merge_map)

    # Apply region replacements in-order (later items override earlier items)
    for item in replacement_regions or []:
        region_mask = item.get("mask")
        replacement_hex = item.get("replacement")
        if region_mask is None or not replacement_hex:
            continue
        replacement_rgb = _hex_to_rgb_tuple(replacement_hex)
        effective_mask = region_mask & mask_solid
        if np.any(effective_mask):
            matched_rgb[effective_mask] = np.array(replacement_rgb, dtype=np.uint8)

    # Build new preview RGBA
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    preview_rgba[mask_solid, 3] = 255

    # Update cache with new data
    updated_cache = cache.copy()
    updated_cache["matched_rgb"] = matched_rgb
    updated_cache["preview_rgba"] = preview_rgba.copy()
    updated_cache["backing_color_id"] = backing_color_id

    # Store original if not already stored
    if "original_matched_rgb" not in updated_cache:
        updated_cache["original_matched_rgb"] = original_rgb

    # Re-extract palette with new colors
    color_palette = extract_color_palette(updated_cache)
    updated_cache["color_palette"] = color_palette

    # Render display with loop if enabled
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        add_loop,
        color_conf,
        bed_label=cache.get("bed_label"),
        target_width_mm=cache.get("target_width_mm"),
        is_dark=cache.get("is_dark", True),
    )

    # Build auto pairs (quantized -> matched) for right table display
    auto_pairs = []
    q_img = updated_cache.get("quantized_image")
    if q_img is not None:
        h, w = matched_rgb.shape[:2]
        for y in range(h):
            for x in range(w):
                if not mask_solid[y, x]:
                    continue
                qh = _rgb_to_hex(q_img[y, x])
                mh = _rgb_to_hex(matched_rgb[y, x])
                auto_pairs.append({"quantized_hex": qh, "matched_hex": mh})

    # Generate palette HTML for display.
    # NOTE: Palette HTML generation used to be delegated to legacy UI extension
    # modules. It now intentionally returns empty because the web frontend renders
    # this through API data.
    palette_html = ""

    return display, updated_cache, palette_html


# ========== Color Highlight Functions ==========


def generate_highlight_preview(
    cache, highlight_color: str, loop_pos=None, add_loop=False, loop_width=4, loop_length=8, loop_hole=2.5, loop_angle=0
):
    """
    Generate preview image with a specific color highlighted.
    """
    if cache is None:
        return None, "[ERROR] 请先生成预览 | Generate preview first"

    if not highlight_color:
        # No highlight - return normal preview
        preview_rgba = cache.get("preview_rgba")
        if preview_rgba is None:
            return None, "[ERROR] 缓存数据无效 | Invalid cache"

        color_conf = cache["color_conf"]
        display = render_preview(
            preview_rgba,
            loop_pos if add_loop else None,
            loop_width,
            loop_length,
            loop_hole,
            loop_angle,
            add_loop,
            color_conf,
            bed_label=cache.get("bed_label"),
            target_width_mm=cache.get("target_width_mm"),
            is_dark=cache.get("is_dark", True),
        )
        return display, "[OK] 预览已恢复 | Preview restored"
    # Parse highlight color
    highlight_hex = highlight_color.strip().lower()
    if not highlight_hex.startswith("#"):
        highlight_hex = "#" + highlight_hex

    # Convert hex to RGB
    try:
        r = int(highlight_hex[1:3], 16)
        g = int(highlight_hex[3:5], 16)
        b = int(highlight_hex[5:7], 16)
        highlight_rgb = np.array([r, g, b], dtype=np.uint8)
    except (ValueError, IndexError):
        return None, f"[ERROR] 无效的颜色值 | Invalid color: {highlight_color}"

    # Get data from cache
    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    color_conf = cache.get("color_conf")

    if matched_rgb is None or mask_solid is None:
        return None, "[ERROR] 缓存数据不完整 | Incomplete cache"

    target_h, target_w = matched_rgb.shape[:2]

    # Create highlight mask - pixels matching the highlight color
    color_match = np.all(matched_rgb == highlight_rgb, axis=2)

    scope = cache.get("selection_scope", "global")
    region_mask = cache.get("selected_region_mask")
    highlight_mask = _resolve_highlight_mask(
        color_match,
        mask_solid,
        region_mask=region_mask,
        scope=scope,
    )

    # Count highlighted pixels
    highlight_count = np.sum(highlight_mask)
    total_solid = np.sum(mask_solid)

    if highlight_count == 0:
        return None, f"[WARNING] 未找到颜色 {highlight_hex} | Color not found"

    highlight_percentage = round(highlight_count / total_solid * 100, 2)

    # Create highlighted preview
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)

    # For non-highlighted solid pixels: convert to grayscale and dim
    non_highlight_mask = mask_solid & ~highlight_mask
    if np.any(non_highlight_mask):
        gray_values = np.mean(matched_rgb[non_highlight_mask], axis=1).astype(np.uint8)
        dimmed_gray = (gray_values * 0.4 + 80).astype(np.uint8)
        preview_rgba[non_highlight_mask, 0] = dimmed_gray
        preview_rgba[non_highlight_mask, 1] = dimmed_gray
        preview_rgba[non_highlight_mask, 2] = dimmed_gray
        preview_rgba[non_highlight_mask, 3] = 180

    # For highlighted pixels: show original color with full opacity
    preview_rgba[highlight_mask, :3] = matched_rgb[highlight_mask]
    preview_rgba[highlight_mask, 3] = 255

    # Add a subtle colored border/glow effect around highlighted regions
    try:
        kernel = np.ones((5, 5), np.uint8)
        dilated = cv2.dilate(highlight_mask.astype(np.uint8), kernel, iterations=2)
        border_mask = (dilated > 0) & ~highlight_mask & mask_solid

        if np.any(border_mask):
            preview_rgba[border_mask, 0] = 0
            preview_rgba[border_mask, 1] = 255
            preview_rgba[border_mask, 2] = 255
            preview_rgba[border_mask, 3] = 200
    except cv2.error as exc:
        log.debug(
            "Highlight border effect skipped due to OpenCV error",
            extra={
                "event": "core_converter_highlight_border_skipped",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )

    # Render display
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        add_loop,
        color_conf,
        bed_label=cache.get("bed_label"),
        target_width_mm=cache.get("target_width_mm"),
        is_dark=cache.get("is_dark", True),
    )

    return display, f"🔍 高亮 {highlight_hex} ({highlight_percentage}%, {highlight_count:,} 像素)"


def clear_highlight_preview(
    cache, loop_pos=None, add_loop=False, loop_width=4, loop_length=8, loop_hole=2.5, loop_angle=0
):
    """
    Clear highlight and restore normal preview.
    """
    log.debug(
        "Clear highlight requested",
        extra={
            "event": "core_converter_clear_highlight_start",
            "has_cache": bool(cache is not None),
            "has_loop": bool(add_loop),
        },
    )

    if cache is None:
        log.warning(
            "Clear highlight called without cache",
            extra={"event": "core_converter_clear_highlight_no_cache"},
        )
        return None, "[ERROR] 请先生成预览 | Generate preview first"

    preview_rgba = cache.get("preview_rgba")
    if preview_rgba is None:
        log.warning(
            "Clear highlight called with invalid cache",
            extra={"event": "core_converter_clear_highlight_invalid_cache"},
        )
        return None, "[ERROR] 缓存数据无效 | Invalid cache"

    color_conf = cache["color_conf"]
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        add_loop,
        color_conf,
        bed_label=cache.get("bed_label"),
        target_width_mm=cache.get("target_width_mm"),
        is_dark=cache.get("is_dark", True),
    )

    log.debug(
        "Clear highlight completed",
        extra={
            "event": "core_converter_clear_highlight_done",
            "display_is_none": bool(display is None),
        },
    )

    return display, "[OK] 预览已恢复 | Preview restored"


def on_preview_click_select_color(
    cache: dict,
    click_coords: tuple[int, int],
    bed_label: str | None = None,
) -> tuple[np.ndarray | None, str, str | None, str]:
    """Handle preview click: pick color and generate highlight.
    预览图点击事件处理：吸取颜色并高亮显示。

    Args:
        cache (dict): Preview cache data. (预览缓存数据)
        click_coords (tuple[int, int]): Click coordinates (x, y). (点击坐标)
        bed_label (str | None): Printer bed label. (打印床标签)

    Returns:
        tuple: (display_image, display_text, quantized_hex, status_message)
            (显示图像, 显示文本, 量化色 hex, 状态消息)
    """
    if cache is None:
        return None, "未选择", None, "[ERROR] 请先生成预览"

    if click_coords is None:
        return None, "未选择", None, "[WARNING] 无效点击"

    if bed_label is None:
        bed_label = cache.get("bed_label", BedManager.DEFAULT_BED)

    display_click_x, display_click_y = click_coords

    target_w = cache.get("target_w")
    target_h = cache.get("target_h")
    target_width_mm = cache.get("target_width_mm")

    if target_w is None or target_h is None:
        return None, "未选择", None, "[ERROR] Invalid cache data"

    bed_w_mm, bed_h_mm = BedManager.get_bed_size(bed_label)
    ppm = BedManager.compute_scale(bed_w_mm, bed_h_mm)
    margin = int(30 * ppm / 3)

    canvas_w = int(bed_w_mm * ppm) + margin
    canvas_h = int(bed_h_mm * ppm) + margin

    # Use target_width_mm from cache for accurate physical size
    if target_width_mm is not None and target_width_mm > 0:
        model_w_mm = target_width_mm
        model_h_mm = target_width_mm * target_h / target_w
    else:
        model_w_mm = target_w * PrinterConfig.NOZZLE_WIDTH
        model_h_mm = target_h * PrinterConfig.NOZZLE_WIDTH
    new_w = max(1, int(model_w_mm * ppm))
    new_h = max(1, int(model_h_mm * ppm))

    offset_x = margin + (int(bed_w_mm * ppm) - new_w) // 2
    offset_y = (int(bed_h_mm * ppm) - new_h) // 2

    # _scale_preview_image fits canvas into 1200x750 box
    display_scale = min(1.0, 1200 / canvas_w, 750 / canvas_h)

    canvas_click_x = display_click_x / display_scale
    canvas_click_y = display_click_y / display_scale

    # Convert canvas coords -> original image pixel coords
    mm_per_px = model_w_mm / target_w
    img_px_x = (canvas_click_x - offset_x) / (mm_per_px * ppm)
    img_px_y = (canvas_click_y - offset_y) / (mm_per_px * ppm)

    orig_x = int(img_px_x)
    orig_y = int(img_px_y)

    matched_rgb = cache.get("original_matched_rgb", cache.get("matched_rgb"))
    quantized_image = cache.get("quantized_image")
    mask_solid = cache.get("mask_solid")

    if quantized_image is None:
        _ensure_quantized_image_in_cache(cache)
        quantized_image = cache.get("quantized_image")

    if matched_rgb is None or mask_solid is None or quantized_image is None:
        return None, "未选择", None, "[ERROR] 缓存无效"

    h, w = matched_rgb.shape[:2]

    if not (0 <= orig_x < w and 0 <= orig_y < h):
        return None, "未选择", None, f"[WARNING] 点击了无效区域 ({orig_x}, {orig_y})"

    if not mask_solid[orig_y, orig_x]:
        return None, "未选择", None, "[WARNING] Clicked background area"

    q_rgb = tuple(int(v) for v in quantized_image[orig_y, orig_x])
    m_rgb = tuple(int(v) for v in matched_rgb[orig_y, orig_x])

    region_mask = _compute_connected_region_mask_4n(quantized_image, mask_solid, orig_x, orig_y)
    cache["selected_region_mask"] = region_mask
    cache.update(_build_selection_meta(q_rgb, m_rgb, scope="region"))

    q_hex = cache["selected_quantized_hex"]
    m_hex = cache["selected_matched_hex"]

    log.debug(
        "Preview click selected color",
        extra={
            "event": "core_converter_preview_click_select_color",
            "x": orig_x,
            "y": orig_y,
            "quantized_hex": q_hex,
            "matched_hex": m_hex,
        },
    )

    display_img, status_msg = generate_highlight_preview(cache, highlight_color=q_hex, add_loop=False)

    display_text = f"量化色 {q_hex} | 原配准色 {m_hex}"
    if display_img is None:
        return None, display_text, q_hex, status_msg

    return display_img, display_text, q_hex, status_msg


def generate_lut_grid_html(lut_path, lang: str = "zh"):
    """
    生成 LUT 可用颜色的 HTML 网格 (with hue filter + smart search)
    """
    from core.i18n import I18n
    import colorsys

    colors = extract_lut_available_colors(lut_path)

    if not colors:
        return f"<div style='color:orange'>LUT 文件无效或为空</div>"

    count = len(colors)

    def _classify_hue(r, g, b):
        rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
        h, s, v = colorsys.rgb_to_hsv(rf, gf, bf)
        h360 = h * 360
        if s < 0.15 or v < 0.10:
            return "neutral"
        if h360 < 15 or h360 >= 345:
            return "red"
        elif h360 < 40:
            return "orange"
        elif h360 < 70:
            return "yellow"
        elif h360 < 160:
            return "green"
        elif h360 < 195:
            return "cyan"
        elif h360 < 260:
            return "blue"
        elif h360 < 345:
            return "purple"
        return "neutral"

    # NOTE: Search/hue-filter UI is rendered by the web frontend via API data.
    _search_bar_html = ""
    _hue_filter_html = ""

    # Derive LUT key for favorites persistence
    _lut_key = os.path.splitext(os.path.basename(lut_path))[0] if lut_path else ""

    html = f"""
    <div class="lut-grid-container">
        <div style="margin-bottom: 8px; font-size: 12px; color: #666;">
            {I18n.get('lut_grid_count', lang).format(count=count)}: <span id="lut-color-visible-count">{count}</span>
        </div>
        {_search_bar_html}
        {_hue_filter_html}
        <div id="lut-color-grid-container" data-lut-key="{_lut_key}" style="
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            max-height: 300px;
            overflow-y: auto;
            padding: 5px;
            border: 1px solid #eee;
            border-radius: 8px;
            background: #f9f9f9;">
    """

    for entry in colors:
        hex_val = entry["hex"]
        r, g, b = entry["color"]
        rgb_val = f"R:{r} G:{g} B:{b}"
        hue_cat = _classify_hue(r, g, b)

        html += f"""
        <div class="lut-color-swatch-container" data-hue="{hue_cat}" style="display:flex;">
        <div class="lut-swatch lut-color-swatch"
             data-color="{hex_val}"
             style="background-color: {hex_val}; width:24px; height:24px; cursor:pointer; border:1px solid #ddd; border-radius:3px;"
             title="{hex_val} ({rgb_val})">
        </div>
        </div>
        """

    html += "</div></div>"
    return html


def generate_lut_card_grid_html(lut_path, lang: str = "zh"):
    """
    Generate a calibration-card-style (色卡) HTML grid for the LUT.

    Colors are displayed in their original LUT order arranged in a square grid,
    matching the physical calibration board layout.  For 8-color LUTs the two
    halves are shown side-by-side horizontally.

    Includes search bar (highlight-in-place, no hiding) and hue filter
    (dims non-matching swatches instead of hiding to preserve grid layout).

    Each swatch is clickable (same data-color / class as the swatch grid) so
    the existing event-delegation click handler picks it up automatically.
    """
    if not lut_path:
        return "<div style='color:orange'>LUT 文件无效或为空</div>"

    try:
        lut_grid = np.load(lut_path)
        measured_colors = lut_grid.reshape(-1, 3)
    except (OSError, ValueError) as exc:
        return f"<div style='color:orange'>LUT 加载失败: {exc}</div>"

    total = len(measured_colors)

    from core.i18n import I18n
    import colorsys

    def _classify_hue(r, g, b):
        rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
        h, s, v = colorsys.rgb_to_hsv(rf, gf, bf)
        h360 = h * 360
        if s < 0.15 or v < 0.10:
            return "neutral"
        if h360 < 15 or h360 >= 345:
            return "red"
        elif h360 < 40:
            return "orange"
        elif h360 < 70:
            return "yellow"
        elif h360 < 160:
            return "green"
        elif h360 < 195:
            return "cyan"
        elif h360 < 260:
            return "blue"
        elif h360 < 345:
            return "purple"
        return "neutral"

    import math

    if total == 2738:
        half = total // 2
        remainder = total - half
        dim1 = int(math.ceil(math.sqrt(half)))
        dim2 = int(math.ceil(math.sqrt(remainder)))
        grids = [
            (measured_colors[:half], dim1, "色卡 A" if lang == "zh" else "Card A"),
            (measured_colors[half:], dim2, "色卡 B" if lang == "zh" else "Card B"),
        ]
    else:
        dim = int(math.ceil(math.sqrt(total)))
        label = f"{total} 色卡" if lang == "zh" else f"{total}-color Card"
        grids = [(measured_colors, dim, label)]

    cell = 18
    gap = 1

    # NOTE: Search/hue-filter UI is rendered by the web frontend via API data.
    html_parts = [
        f'<div style="margin-bottom:8px; font-size:12px; color:#666;">{I18n.get("lut_grid_count", lang).format(count=total)}: <span id="lut-color-visible-count">{total}</span></div>',
    ]

    # Derive LUT key for favorites persistence
    _lut_key = os.path.splitext(os.path.basename(lut_path))[0] if lut_path else ""

    # Grid
    html_parts.append(
        f"<div id='lut-color-grid-container' data-lut-key='{_lut_key}' style='display:flex; gap:12px; align-items:flex-start; "
        "overflow-x:auto; padding:4px;'>"
    )

    for colors_arr, dim, title in grids:
        html_parts.append(
            f"<div style='flex-shrink:0;'>"
            f"<div style='font-size:11px; color:#666; margin-bottom:4px;'>{title} ({len(colors_arr)})</div>"
            f"<div style='display:grid; grid-template-columns:repeat({dim}, {cell}px); gap:{gap}px; "
            f"border:1px solid #eee; border-radius:6px; padding:4px; background:#f9f9f9;'>"
        )
        for c in colors_arr:
            r, g, b = int(c[0]), int(c[1]), int(c[2])
            hex_val = f"#{r:02x}{g:02x}{b:02x}"
            hue_cat = _classify_hue(r, g, b)
            html_parts.append(
                f"<div class='lut-swatch lut-color-swatch' data-color='{hex_val}' data-hue='{hue_cat}' "
                f"style='width:{cell}px;height:{cell}px;background:{hex_val};"
                f"cursor:pointer;border-radius:2px;' "
                f"title='{hex_val} (R:{r} G:{g} B:{b})'></div>"
            )
        html_parts.append("</div></div>")

    html_parts.append("</div>")
    return "".join(html_parts)


# ========== Auto-detection Functions ==========


def detect_lut_color_mode(lut_path):
    """
    自动检测 LUT 文件的颜色模式。

    Args:
        lut_path: LUT 文件路径

    Returns:
        str: 颜色模式 ("BW (Black & White)", "Merged", "6-Color (CMYWGK 1296)", "8-Color Max", etc.)
    """
    if not lut_path or not os.path.exists(lut_path):
        return None

    try:
        if lut_path.endswith(".npz"):
            data = np.load(lut_path)
            if "rgb" in data:
                rgb = data["rgb"]
                total_colors = int(rgb.reshape(-1, 3).shape[0])
                stacks = data["stacks"] if "stacks" in data else None
                layer_count = int(stacks.shape[1]) if isinstance(stacks, np.ndarray) and stacks.ndim == 2 else None
                max_mat = int(np.max(stacks)) if isinstance(stacks, np.ndarray) and stacks.size > 0 else None
                if (
                    total_colors >= 2400
                    and total_colors < 2600
                    and layer_count == 6
                    and (max_mat is None or max_mat <= 4)
                ):
                    log.info(f"Detected 5-Color Extended mode from .npz ({total_colors} colors)")
                    return "5-Color Extended"
                if total_colors >= 2600 and total_colors <= 2800:
                    log.info(f"Detected 8-Color mode from .npz ({total_colors} colors)")
                    return "8-Color Max"
                if total_colors >= 1200 and total_colors < 1400:
                    log.info(f"Detected 6-Color mode from .npz ({total_colors} colors)")
                    return "6-Color (CMYWGK 1296)"
                if total_colors >= 900 and total_colors < 1200:
                    log.info(f"Detected 4-Color mode from .npz ({total_colors} colors)")
                    return "4-Color"
                if total_colors >= 30 and total_colors <= 35:
                    log.info(f"Detected 2-Color BW mode from .npz ({total_colors} colors)")
                    return "BW (Black & White)"
            log.info(f"Detected Merged LUT (.npz format)")
            return "Merged"

        # .json (Keyed JSON) format
        if lut_path.endswith(".json"):
            from utils.lut_manager import LUTManager

            rgb, stacks, _meta = LUTManager.load_lut_with_metadata(lut_path)
            # 优先使用存储的 color_mode
            if _meta and _meta.color_mode:
                log.info(f"Using stored color_mode from metadata: {_meta.color_mode}")
                return _meta.color_mode
            # 回退到基于数量的推断
            total_colors = len(rgb) if rgb is not None else 0
            layer_count = int(stacks.shape[1]) if isinstance(stacks, np.ndarray) and stacks.ndim == 2 else None
            max_mat = int(np.max(stacks)) if isinstance(stacks, np.ndarray) and stacks.size > 0 else None
            log.info(f"JSON LUT: {total_colors} colors, layer_count={layer_count}, max_mat={max_mat}")
            if total_colors >= 2400 and total_colors < 2600 and layer_count == 6 and (max_mat is None or max_mat <= 4):
                log.info(f"Detected 5-Color Extended mode from .json ({total_colors} colors)")
                return "5-Color Extended"
            if total_colors >= 2600 and total_colors <= 2800:
                log.info(f"Detected 8-Color mode from .json ({total_colors} colors)")
                return "8-Color Max"
            if total_colors >= 1200 and total_colors < 1400:
                log.info(f"Detected 6-Color mode from .json ({total_colors} colors)")
                return "6-Color (CMYWGK 1296)"
            if total_colors >= 900 and total_colors < 1200:
                log.info(f"Detected 4-Color mode from .json ({total_colors} colors)")
                return "4-Color"
            if total_colors >= 30 and total_colors <= 35:
                log.info(f"Detected 2-Color BW mode from .json ({total_colors} colors)")
                return "BW (Black & White)"
            log.info(f"Non-standard JSON LUT size ({total_colors} colors), detected as Merged")
            return "Merged"

        # Standard .npy format
        lut_data = np.load(lut_path)

        # 确保是 2D 数组
        if lut_data.ndim == 1:
            # 如果是 1D 数组，假设是 (N*3,) 格式，重塑为 (N, 3)
            if len(lut_data) % 3 == 0:
                lut_data = lut_data.reshape(-1, 3)
            else:
                log.info(f"Invalid LUT format: cannot reshape to (N, 3)")
                return None

        # 计算颜色数量
        if lut_data.ndim == 2:
            total_colors = lut_data.shape[0]
        else:
            total_colors = lut_data.shape[0] * lut_data.shape[1]

        log.info(f"LUT shape: {lut_data.shape}, total colors: {total_colors}")

        # 2色模式：32色 (2^5 = 32)
        if total_colors >= 30 and total_colors <= 35:
            log.info(f"Detected 2-Color BW mode (32 colors)")
            return "BW (Black & White)"

        # 5-Color Extended 模式：2468 色 (1024 base + 1444 extended)
        elif total_colors >= 2400 and total_colors < 2600:
            log.info(f"Detected 5-Color Extended mode ({total_colors} colors)")
            return "5-Color Extended"

        # 8色模式：2600-2800色
        elif total_colors >= 2600 and total_colors <= 2800:
            log.info(f"Detected 8-Color mode ({total_colors} colors)")
            return "8-Color Max"

        # 6色模式：1200-1400色
        elif total_colors >= 1200 and total_colors < 1400:
            log.info(f"Detected 6-Color mode ({total_colors} colors)")
            return "6-Color (CMYWGK 1296)"

        # 4色模式：900-1200色
        elif total_colors >= 900 and total_colors < 1200:
            log.info(f"Detected 4-Color mode ({total_colors} colors)")
            return "4-Color"

        else:
            # 非标准尺寸：识别为合并色卡
            log.info(f"Non-standard LUT size ({total_colors} colors), detected as Merged")
            return "Merged"

    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        log.exception(
            "Failed to detect LUT color mode",
            extra={
                "event": "core_converter_detect_lut_color_mode_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "lut_path": str(lut_path),
            },
        )
        return None


def detect_image_type(image_path: str | None) -> str | None:
    """Detect image type and return recommended modeling mode.
    自动检测图像类型并返回推荐的建模模式。

    Args:
        image_path (str | None): Image file path. (图像文件路径)

    Returns:
        str | None: Modeling mode string if change recommended, None otherwise.
            (推荐的建模模式字符串，无需变更时返回 None)
    """
    if not image_path:
        return None

    try:
        ext = os.path.splitext(image_path)[1].lower()

        if ext == ".svg":
            log.info(f"SVG file detected, recommending SVG Mode")
            return ModelingMode.VECTOR
        else:
            log.info(f"Raster image detected ({ext}), keeping current mode")
            return None

    except (TypeError, ValueError, OSError) as exc:
        log.warning(
            "Failed to detect image type",
            extra={
                "event": "core_converter_detect_image_type_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "image_path": str(image_path),
            },
        )
        return None
