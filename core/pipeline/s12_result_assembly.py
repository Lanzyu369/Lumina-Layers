"""
S12 — Final result assembly.
S12 — 最终结果组装。

从 converter.py 搬入的结果组装逻辑：
- 统计信息输出
- 状态消息生成
- 5 元组返回值组装
"""

import time

from api.structured_logging import get_logger
from utils import Stats

_log = get_logger(__name__)


def run(ctx: dict) -> dict:
    """Assemble final result tuple from pipeline context.
    从管道上下文组装最终结果元组。

    PipelineContext 输入键 / Input keys:
        - out_path (str): 3MF 文件路径
        - glb_path (str | None): GLB 预览文件路径
        - preview_img (PIL.Image | None): 2D 预览图像
        - mode_info (dict): 模式信息
        - target_w (int): 图像宽度（像素）
        - target_h (int): 图像高度（像素）
        - loop_info (dict | None): 挂件环信息
        - loop_added (bool): 挂件环是否已添加
        - slot_names (list[str]): 材料槽位名称
        - heightmap_stats (dict | None): 高度图统计信息
        - color_recipe_path (str | None): 颜色配方报告路径
        - _hifi_timings (dict): 性能计时数据

    PipelineContext 输出键 / Output keys:
        - result_tuple (tuple): (out_path, glb_path, preview_img, msg, color_recipe_path)
    """
    out_path = ctx['out_path']
    glb_path = ctx.get('glb_path')
    preview_img = ctx.get('preview_img')
    mode_info = ctx['mode_info']
    target_w = ctx['target_w']
    target_h = ctx['target_h']
    loop_info = ctx.get('loop_info')
    loop_added = ctx.get('loop_added', False)
    slot_names = ctx['slot_names']
    heightmap_stats = ctx.get('heightmap_stats')
    color_recipe_path = ctx.get('color_recipe_path')
    _hifi_timings = ctx.get('_hifi_timings', {})

    # Step 10: Generate Status Message
    Stats.increment("conversions")

    # Output detailed timing summary
    if _hifi_timings:
        _keys_order = [
            ('input_val_s',    'input_val'),
            ('image_proc_s',   'image_proc'),
            ('color_replace_s','color_replace'),
            ('debug_preview_s','debug_preview'),
            ('preview_gen_s',  'preview_gen'),
            ('voxel_build_s',  'voxel_build'),
            ('mesh_gen_s',     'mesh_gen'),
            ('aux_meshes_s',   'aux_meshes'),
            ('color_recipe_s', 'color_recipe'),
            ('export_3mf_s',   'export_3mf'),
            ('glb_preview_s',  'glb_preview'),
        ]
        total_s = 0.0
        timings_ms = {}
        for key, label in _keys_order:
            val = _hifi_timings.get(key, 0.0)
            if val > 0:
                timings_ms[label] = round(val * 1000, 3)
                total_s += val
        _log.debug(
            "timing summary: %.3fs",
            total_s,
            extra={
                "event": "s12_timing_summary",
                "duration_ms": round(total_s * 1000, 3),
                "step_timings_ms": timings_ms,
                "count": len(timings_ms),
            },
        )

    mode_name = mode_info['mode'].get_display_name()
    msg = f"Conversion complete ({mode_name})! Resolution: {target_w}x{target_h}px"

    # Heightmap statistics
    if heightmap_stats is not None:
        msg += (f" | Heightmap: {heightmap_stats['min_mm']:.1f}mm ~ "
                f"{heightmap_stats['max_mm']:.1f}mm (avg {heightmap_stats['avg_mm']:.1f}mm)")

    if loop_added and loop_info:
        msg += f" | Loop: {slot_names[loop_info['color_id']]}"

    total_pixels = target_w * target_h
    if glb_path and total_pixels > 500_000:
        msg += " | 3D preview simplified"

    result_tuple = (out_path, glb_path, preview_img, msg, color_recipe_path)
    ctx['result_tuple'] = result_tuple

    return ctx
