"""
P03 — Core image processing (quantization + LUT matching).
P03 — 核心图像处理（量化 + LUT 匹配）。

从 generate_preview_cached 函数搬入的逻辑，包括：
- 创建 LuminaImageProcessor 实例
- 调用 process_image 进行图像处理
- 提取处理结果（matched_rgb, material_matrix, mask_solid 等）
- Material-archive 模式：跳过 LUT 匹配，使用 beam-search 耗材求解器
"""


from api.structured_logging import get_logger
import time

import numpy as np

_log = get_logger(__name__)


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

    from core.material_cache import (
        DEFAULT_GRID_RESOLUTION,
        build_material_solver_cache,
        load_material_solver_cache_with_fallback,
    )
    from core.material_lut_synthesis import (
        ensure_not_worse_than_smaller_N,
        map_pixels_to_materials,
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
    requested_grid = int(ctx.get("grid_resolution") or DEFAULT_GRID_RESOLUTION)

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
    # Pass ``skip_post_blur=True``: the material-archive solver (and its
    # cache) consumes ``unique_colors`` and relies on the quantization
    # contract (``unique RGB count <= quantize_colors_n``). Letting
    # ``cv2.medianBlur`` run would inflate unique_colors by 10-100x and
    # produce visible banding at higher layer counts because neighbouring
    # pixels get mapped to distinct recipes for colors that were supposed
    # to collapse into the same cluster.
    # (耗材档案分支必须关闭后量化模糊：medianBlur 逐通道取中值会把 unique
    # RGB 数炸到 10-100 倍，层数越多相邻像素越容易被映射到不同配方，从而
    # 在预览里表现为肉眼可见的色块/带状化。)
    rgb_processed = apply_bilateral_filter(rgb_arr, 10)
    rgb_processed = apply_median_filter(rgb_processed, 0)
    quantized_image = kmeans_quantize(
        rgb_processed, quantize_colors_n, skip_post_blur=True
    )
    unique_colors = np.unique(quantized_image.reshape(-1, 3), axis=0)
    _log.debug("%d unique colors after quantization", len(unique_colors))

    # ---- Resolve recipes: cache lookup or per-image B&B fallback ----
    solver_t0 = time.perf_counter()
    cache, actual_grid = load_material_solver_cache_with_fallback(
        materials=materials,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        grid_resolution=requested_grid,
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
            "requested_grid_resolution": requested_grid,
            "grid_resolution": cache.grid_resolution,
            "grid_fallback_used": actual_grid != requested_grid,
            "valid_cell_count": cache.valid_cell_count,
            "built_at": cache.metadata.get("built_at"),
            "cache_mean_delta_e": float(cache.metadata.get("mean_delta_e", 0.0)),
            "cache_max_delta_e": float(cache.metadata.get("max_delta_e", 0.0)),
        }
    else:
        # No persisted cache found — build a temporary low-res (64³) cache
        # in-memory and use it for lookup.  This avoids the MITM per-pixel
        # solver whose delta_e broadcast (C, chunk, K_bot) can exceed
        # available RAM for large palettes (e.g. M=8, N=10 → ~2.7 GiB).
        # The cache builder uses a per-bucket approach that stays within
        # ~100 MiB per chunk regardless of palette size.
        # 没有持久化缓存时，现场构建一个最低分辨率（64³）的临时缓存用于匹配。
        # 缓存构建器采用逐桶写入模式，内存可控，不会像 MITM 求解器那样 OOM。
        _MIN_FALLBACK_GRID = 64
        _log.debug(
            "No cache found; building temporary grid=%d "
            "cache in-memory (M=%d, N=%d) …",
            _MIN_FALLBACK_GRID, len(materials), layer_count,
        )
        try:
            cache = build_material_solver_cache(
                materials=materials,
                layer_count=layer_count,
                layer_height_mm=layer_height_mm,
                substrate=substrate,
                grid_resolution=_MIN_FALLBACK_GRID,
            )
        except (MemoryError, ValueError) as exc:
            _log.error(
                "Temporary cache build failed: %s", exc
            )
            ctx["error"] = (
                "[P03] 临时缓存构建失败，请先为该调色板构建穷举缓存。"
                " / Temporary cache build failed. "
                "Please build the solver cache for this palette first."
            )
            return ctx
        _log.debug(
            "Temporary cache built: %d valid cells, "
            "mean_ΔE=%.2f, build=%.1fs",
            cache.valid_cell_count,
            float(cache.metadata.get("mean_delta_e", 0.0)),
            float(cache.metadata.get("build_time_seconds", 0.0)),
        )
        if unique_colors.shape[0] > 0:
            matched_rgb_unique, recipes_unique, delta_e = cache.lookup(
                unique_colors, materials
            )
        else:
            matched_rgb_unique = np.zeros((0, 3), dtype=np.uint8)
            recipes_unique = np.zeros((0, layer_count), dtype=np.int32)
            delta_e = np.zeros((0,), dtype=np.float64)
        solver_path = "cache_built_on_the_fly"
        solver_meta = {
            "palette_hash": cache.palette_hash,
            "requested_grid_resolution": requested_grid,
            "grid_resolution": cache.grid_resolution,
            "grid_fallback_used": True,
            "valid_cell_count": cache.valid_cell_count,
            "built_at": cache.metadata.get("built_at"),
            "cache_mean_delta_e": float(cache.metadata.get("mean_delta_e", 0.0)),
            "cache_max_delta_e": float(cache.metadata.get("max_delta_e", 0.0)),
            "build_time_seconds": float(cache.metadata.get("build_time_seconds", 0.0)),
            "reason": "no_persisted_cache",
        }
    solver_elapsed = time.perf_counter() - solver_t0
    _log.debug(
        "Solver path=%s colors=%d mean_ΔE=%.2f max_ΔE=%.2f elapsed=%.2fs",
        solver_path,
        int(unique_colors.shape[0]),
        float(np.mean(delta_e)) if delta_e.size else 0.0,
        float(np.max(delta_e)) if delta_e.size else 0.0,
        solver_elapsed,
    )

    # ---- Enforce "N-layer recipe not worse than smaller-N + white padding" ----
    # Only run the cross-N fallback when the solver ran exhaustively on-the-fly.
    # When a cache was loaded, the exhaustive grid already encodes globally-optimal
    # N-layer solutions; re-solving k<N via the MITM solver would be redundant and
    # catastrophically expensive for large palettes (e.g. M=8, k≥8 creates multi-GB
    # MITM tables that OOM the worker process).
    # (仅在走了在线穷举路径时才做跨 N 比较。缓存命中时网格已全局最优，且大调色板
    # k≥8 的 MITM 求解会产生数 GB 表引发 OOM。)
    _run_cross_n = unique_colors.shape[0] > 0 and solver_path not in ("cache", "cache_built_on_the_fly")
    if _run_cross_n:
        fallback_t0 = time.perf_counter()
        matched_rgb_unique, recipes_unique, delta_e, fallback_stats = (
            ensure_not_worse_than_smaller_N(
                unique_colors,
                materials,
                matched_rgb_unique,
                recipes_unique,
                delta_e,
                target_layer_count=layer_count,
                layer_height_mm=layer_height_mm,
                substrate=substrate,
            )
        )
        fallback_elapsed = time.perf_counter() - fallback_t0
        solver_meta["not_worse_fallback"] = {
            **fallback_stats,
            "elapsed_seconds": float(fallback_elapsed),
        }
        if fallback_stats["applied"] and fallback_stats["improved_pixels"] > 0:
            _log.debug(
                "Not-worse fallback replaced %d/%d unique colours "
                "(mean ΔE %.2f→%.2f, max ΔE %.2f→%.2f, elapsed=%.2fs)",
                fallback_stats["improved_pixels"],
                int(unique_colors.shape[0]),
                fallback_stats["mean_delta_e_before"],
                fallback_stats["mean_delta_e_after"],
                fallback_stats["max_delta_e_before"],
                fallback_stats["max_delta_e_after"],
                fallback_elapsed,
            )
        elif not fallback_stats["applied"]:
            _log.debug(
                "Not-worse fallback skipped (no white material "
                "detected in palette or N=%d already at the lower bound).",
                layer_count,
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
    _log.debug("material_archive core_processing done: %.3fs", _elapsed)
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
    _log.debug("core_processing done: %.3fs", _elapsed)
    return ctx
