"""
P03 — Core image processing (quantization + LUT matching).
P03 — 核心图像处理（量化 + LUT 匹配）。

从 generate_preview_cached 函数搬入的逻辑，包括：
- 创建 LuminaImageProcessor 实例
- 调用 process_image 进行图像处理
- 提取处理结果（matched_rgb, material_matrix, mask_solid 等）
"""


import time


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
