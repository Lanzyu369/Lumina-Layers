"""
Lumina Studio - UI Callbacks
界面事件处理回调函数
"""

import gradio as gr

from config import ColorSystem, ThinModeConfig
from core.extractor import generate_simulated_reference


# ═══════════════════════════════════════════════════════════════
# Extractor Callbacks
# ═══════════════════════════════════════════════════════════════

def get_first_hint(mode):
    """根据模式获取第一个定位点提示"""
    conf = ColorSystem.get(mode)
    label_zh = conf['corner_labels'][0]
    label_en = conf['corner_labels_en'][0]
    return f"#### 👉 点击 Click: **{label_zh} / {label_en}**"


def get_next_hint(mode, pts_count):
    """根据模式获取下一个定位点提示"""
    conf = ColorSystem.get(mode)
    if pts_count >= 4:
        return "#### ✅ 定位完成！Ready to extract!"
    label_zh = conf['corner_labels'][pts_count]
    label_en = conf['corner_labels_en'][pts_count]
    return f"#### 👉 点击 Click: **{label_zh} / {label_en}**"


def on_extractor_upload(i, mode):
    """上传图片时的处理"""
    hint = get_first_hint(mode)
    return i, i, [], None, hint


def on_extractor_mode_change(img, mode):
    """切换色彩模式时的处理"""
    hint = get_first_hint(mode)
    return [], hint, img


def on_extractor_rotate(i, mode):
    """旋转图片"""
    from core.extractor import rotate_image
    if i is None:
        return None, None, [], get_first_hint(mode)
    r = rotate_image(i, "左旋 90°")
    return r, r, [], get_first_hint(mode)


def on_extractor_click(img, pts, mode, evt: gr.SelectData):
    """点击图片设置角点"""
    from core.extractor import draw_corner_points

    if len(pts) >= 4:
        return img, pts, "#### ✅ 定位完成 Complete!"
    n = pts + [[evt.index[0], evt.index[1]]]
    vis = draw_corner_points(img, n, mode)
    hint = get_next_hint(mode, len(n))
    return vis, n, hint


def on_extractor_clear(img, mode):
    """清除角点"""
    hint = get_first_hint(mode)
    return img, [], hint
