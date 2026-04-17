"""
P03 — Core image processing (quantization + LUT matching).
P03 — 核心图像处理（量化 + LUT 匹配）。

从 generate_preview_cached 函数搬入的逻辑，包括：
- 创建 LuminaImageProcessor 实例
- 调用 process_image 进行图像处理
- 提取处理结果（matched_rgb, material_matrix, mask_solid 等）
- Material-archive 模式：跳过 LUT 匹配，使用 beam-search 耗材求解器
"""


import logging
import time

import numpy as np

_log = logging.getLogger(__name__)


def _run_material_archive_branch(ctx: dict) -> dict:
    """Material-archive processing: quantize image, solve recipes via cache or B&B.
    耗材档案模式处理：量化图像，通过缓存命中或 B&B 最优求解器生成配方。

    Solver selection:
      1. Try to load a persisted :class:`core.material_cache.MaterialSolverCache`
         that matches ``(palette, layer_count, layer_height_mm, substrate)``.
      2. On cache hit, resolve recipes via :meth:`MaterialSolverCache.lookup`.
      3. On cache miss, fall back to
         :func:`core.material_color_solver.solve_image_colors_optimal` —
         guaranteed globally optimal per image but slower.
    The choice is recorded in ``ctx["material_solver_info"]`` so the UI can
    show whether the cache was used.
    """
    from PIL import Image

    from core.material_cache import load_material_solver_cache
    from core.material_lut_synthesis import (
        map_pixels_to_materials,
        solve_image_colors_optimal,
    )
    from core.pipeline.processing_ops.bilateral_filter import apply_bilateral_filter
    from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors as kmeans_quantize
    from core.pipeline.processing_ops.median_filter import apply_median_filter

    _t0 = time.perf_counter()

    image_path = ctx["image_path"]
    target_width_mm = ctx["target_width_mm"]
    modeling_mode = ctx["modeling_mode"]
    quantize_colors_n = ctx["quantize_colors"]
    auto_bg = ctx["auto_bg"]
    bg_tol = ctx["bg_tol"]
    materials = ctx["_material_params"]
    layer_count = int(ctx.get("color_layers") or 5)
    layer_height_mm = float(ctx.get("layer_height_mm") or 0.08)
    substrate = str(ctx.get("material_substrate") or "white")

    # ---- Load and resize ----
    from config import ModelingMode

    PIXELS_PER_MM = 10
    is_svg = image_path.lower().endswith(".svg")
    if is_svg:
        from core.pipeline.processing_ops.svg_rasterizer import rasterize_svg

        img = Image.fromarray(rasterize_svg(image_path, target_width_mm, pixels_per_mm=PIXELS_PER_MM))
        target_w, target_h = img.size[0], img.size[1]
        pixel_scale = 1.0 / PIXELS_PER_MM
    else:
        img = Image.open(image_path).convert("RGBA")
        target_w = max(1, int(target_width_mm * PIXELS_PER_MM))
        target_h = max(1, int(target_w * img.height / img.width))
        pixel_scale = 1.0 / PIXELS_PER_MM
    img = img.resize((target_w, target_h), Image.Resampling.NEAREST)

    img_arr = np.array(img)
    rgb_arr = img_arr[:, :, :3]
    alpha_arr = img_arr[:, :, 3]
    mask_transparent = alpha_arr < 10

    # ---- Auto background removal ----
    if auto_bg:
        bg_ref = rgb_arr.copy()
        bg_mask = np.sum(np.abs(bg_ref.astype(np.int16) - bg_ref[0, 0].astype(np.int16)), axis=-1) < bg_tol
        mask_transparent = np.logical_or(mask_transparent, bg_mask)

    mask_solid = ~mask_transparent

    # ---- Quantize ----
    rgb_processed = apply_bilateral_filter(rgb_arr, 10)
    rgb_processed = apply_median_filter(rgb_processed, 0)
    quantized_image = kmeans_quantize(rgb_processed, quantize_colors_n)
    unique_colors = np.unique(quantized_image.reshape(-1, 3), axis=0)
    _log.info("[P03-Material] %d unique colors after quantization", len(unique_colors))

    # ---- Resolve recipes: cache lookup or per-image B&B fallback ----
    solver_t0 = time.perf_counter()
    cache = load_material_solver_cache(
        materials=materials,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
    )
    solver_path: str
    solver_meta: dict = {}
    if cache is not None and unique_colors.shape[0] > 0:
        matched_rgb_unique, recipes_unique, delta_e = cache.lookup(
            unique_colors, materials
        )
        solver_path = "cache"
        solver_meta = {
            "palette_hash": cache.palette_hash,
            "grid_resolution": cache.grid_resolution,
            "valid_cell_count": cache.valid_cell_count,
            "built_at": cache.metadata.get("built_at"),
            "cache_mean_delta_e": float(cache.metadata.get("mean_delta_e", 0.0)),
            "cache_max_delta_e": float(cache.metadata.get("max_delta_e", 0.0)),
        }
    else:
        matched_rgb_unique, recipes_unique, delta_e = solve_image_colors_optimal(
            unique_colors,
            materials,
            layer_count=layer_count,
            layer_height_mm=layer_height_mm,
            substrate=substrate,
        )
        solver_path = "bnb_exhaustive"
        solver_meta = {"reason": "no_cache" if cache is None else "empty_targets"}
    solver_elapsed = time.perf_counter() - solver_t0
    _log.info(
        "[P03-Material] Solver path=%s colors=%d mean_ΔE=%.2f max_ΔE=%.2f elapsed=%.2fs",
        solver_path,
        int(unique_colors.shape[0]),
        float(np.mean(delta_e)) if delta_e.size else 0.0,
        float(np.max(delta_e)) if delta_e.size else 0.0,
        solver_elapsed,
    )

    # ---- Convert layer order: solver "Bottom2Top" -> pipeline "Top2Bottom" ----
    # 层序转换：求解器/缓存输出的 ``recipes_unique[:, 0]`` 是底层（贴基底、
    # 即靠背板侧），``recipes_unique[:, -1]`` 是顶层（观赏面）。而 S06
    # ``_build_voxel_matrix`` / ``_build_voxel_matrix_faceup`` 约定
    # ``material_matrix[..., 0]`` 是观赏面，``material_matrix[..., -1]`` 贴背板。
    # 直接把求解结果喂进 ``map_pixels_to_materials`` 会让整叠层上下颠倒，
    # 产出的 3MF 配色与用户所见的预测色不一致，所以在此一次性反转列序。
    # Solver/cache output uses ``Bottom2Top`` (index 0 = substrate-adjacent)
    # while the voxel builders in S06 assume ``Top2Bottom`` (index 0 =
    # viewing surface). Reverse the recipe columns once here so downstream
    # ``material_matrix`` matches the pipeline convention.
    if recipes_unique.shape[1] > 1:
        recipes_unique = np.ascontiguousarray(recipes_unique[:, ::-1])

    # ---- Map pixels ----
    matched_rgb, material_matrix = map_pixels_to_materials(
        quantized_image, unique_colors, matched_rgb_unique, recipes_unique,
        target_h, target_w,
    )

    # ---- Transparent pixels → -1 in material_matrix ----
    material_matrix[mask_transparent] = -1

    # ---- Write output ----
    ctx["matched_rgb"] = matched_rgb
    ctx["material_matrix"] = material_matrix
    ctx["mask_solid"] = mask_solid
    ctx["target_w"] = target_w
    ctx["target_h"] = target_h
    ctx["pixel_scale"] = pixel_scale
    ctx["debug_data"] = None
    ctx["quantized_image"] = quantized_image
    ctx["lut_match_info"] = None
    ctx["material_solver_info"] = {
        "path": solver_path,
        "layer_count": layer_count,
        "layer_height_mm": layer_height_mm,
        "substrate": substrate,
        "elapsed_seconds": solver_elapsed,
        "unique_color_count": int(unique_colors.shape[0]),
        "mean_delta_e": float(np.mean(delta_e)) if delta_e.size else 0.0,
        "max_delta_e": float(np.max(delta_e)) if delta_e.size else 0.0,
        **solver_meta,
    }
    # mode_info is consumed by S04 (debug preview) and S12 (result assembly).
    # Material-archive mode does not run a LUT-based color matcher, so we
    # populate a placeholder match mode so the contract stays consistent.
    ctx["mode_info"] = {
        "mode": ctx.get("modeling_mode"),
        "lut_match_mode": "material_archive",
    }
    _elapsed = time.perf_counter() - _t0
    ctx.setdefault("_preview_timings", {})["p03_s"] = _elapsed
    _log.info("[P03] material_archive core_processing done: %.3fs", _elapsed)
    return ctx


def run(ctx: dict) -> dict:
    """Execute core image processing: quantization and LUT color matching.
    执行核心图像处理：量化与 LUT 颜色匹配。

    PipelineContext 输入键 / Input keys:
        - actual_lut_path (str): 解析后的实际 LUT 文件路径
        - color_mode (str): 颜色模式字符串
        - hue_weight (float): 色相权重
        - chroma_gate (float): 色度门限
        - image_path (str): 输入图像路径
        - target_width_mm (float): 目标宽度（毫米）
        - modeling_mode (ModelingMode): 建模模式
        - quantize_colors (int): 量化颜色数
        - auto_bg (bool): 是否自动移除背景
        - bg_tol (int): 背景容差
        - enable_cleanup (bool): 是否启用孤立像素清理

    PipelineContext 输出键 / Output keys:
        - matched_rgb (np.ndarray): LUT 匹配后的 RGB 图像 (H, W, 3)
        - material_matrix (np.ndarray): 材料矩阵 (H, W, N)
        - mask_solid (np.ndarray): 实体掩码 (H, W) bool
        - target_w (int): 目标宽度（像素）
        - target_h (int): 目标高度（像素）
        - debug_data (dict | None): 调试数据
        - quantized_image (np.ndarray | None): 量化后的图像

    Raises:
        KeyError: 缺少必需的输入键时抛出
    """
    # ---- Material-archive branch ----
    if ctx.get("material_source") == "material_archive":
        return _run_material_archive_branch(ctx)

    from core.image_processing import LuminaImageProcessor
    _t0 = time.perf_counter()

    # ---- 读取必需输入 ----
    actual_lut_path = ctx['actual_lut_path']
    color_mode = ctx['color_mode']
    hue_weight = ctx.get('hue_weight', 0.0)
    chroma_gate = ctx.get('chroma_gate', 15.0)
    image_path = ctx['image_path']
    target_width_mm = ctx['target_width_mm']
    modeling_mode = ctx['modeling_mode']
    quantize_colors = ctx['quantize_colors']
    auto_bg = ctx['auto_bg']
    bg_tol = ctx['bg_tol']
    enable_cleanup = ctx.get('enable_cleanup', True)
    color_layers = ctx.get('color_layers')
    layer_height_mm = ctx.get('layer_height_mm')
    model_enable = ctx.get('model_enable', False)
    model_only = ctx.get('model_only', False)
    model_threshold = ctx.get('model_threshold')
    model_margin = ctx.get('model_margin')

    # ---- 核心处理 ----
    processor = LuminaImageProcessor(
        actual_lut_path,
        color_mode,
        hue_weight=hue_weight,
        chroma_gate=chroma_gate,
        color_layers=color_layers,
        layer_height_mm=layer_height_mm,
        model_enable=model_enable,
        model_only=model_only,
        model_threshold=model_threshold,
        model_margin=model_margin,
    )
    processor.enable_cleanup = enable_cleanup

    result = processor.process_image(
        image_path=image_path,
        target_width_mm=target_width_mm,
        modeling_mode=modeling_mode,
        quantize_colors=quantize_colors,
        auto_bg=auto_bg,
        bg_tol=bg_tol,
        blur_kernel=0,
        smooth_sigma=10
    )

    # ---- 提取结果 ----
    matched_rgb = result['matched_rgb']
    material_matrix = result['material_matrix']
    mask_solid = result['mask_solid']
    target_w, target_h = result['dimensions']

    # ---- 写入输出 ----
    ctx['matched_rgb'] = matched_rgb
    ctx['material_matrix'] = material_matrix
    ctx['mask_solid'] = mask_solid
    ctx['target_w'] = target_w
    ctx['target_h'] = target_h
    ctx['debug_data'] = result.get('debug_data') if isinstance(result, dict) else None
    ctx['quantized_image'] = result.get('quantized_image')
    ctx['lut_match_info'] = getattr(processor, 'last_match_info', None)
    _elapsed = time.perf_counter() - _t0
    ctx.setdefault('_preview_timings', {})['p03_s'] = _elapsed
    print(f"[P03] core_processing done: {_elapsed:.3f}s")
    return ctx
