"""
Lumina Studio - UI Callbacks
UI event handling callback functions
"""

import gradio as gr

from config import ColorSystem, ThinModeConfig
from core.extractor import generate_simulated_reference
from utils import LUTManager


# ═══════════════════════════════════════════════════════════════
# LUT Management Callbacks
# ═══════════════════════════════════════════════════════════════

def on_lut_select(display_name):
    """
    When user selects LUT from dropdown
    
    Returns:
        tuple: (lut_path, status_message)
    """
    if not display_name:
        return None, ""
    
    lut_path = LUTManager.get_lut_path(display_name)
    
    if lut_path:
        return lut_path, f"✅ Selected: {display_name}"
    else:
        return None, f"❌ File not found: {display_name}"


def on_lut_upload_save(uploaded_file):
    """
    Save uploaded LUT file (auto-save, no custom name needed)
    
    Returns:
        tuple: (new_dropdown, status_message)
    """
    success, message, new_choices = LUTManager.save_uploaded_lut(uploaded_file, custom_name=None)
    
    return gr.Dropdown(choices=new_choices), message


# ═══════════════════════════════════════════════════════════════
# Extractor Callbacks
# ═══════════════════════════════════════════════════════════════

def get_first_hint(mode):
    """Get first corner point hint based on mode"""
    conf = ColorSystem.get(mode)
    label_zh = conf['corner_labels'][0]
    label_en = conf['corner_labels_en'][0]
    return f"#### 👉 点击 Click: **{label_zh} / {label_en}**"


def get_next_hint(mode, pts_count):
    """Get next corner point hint based on mode"""
    conf = ColorSystem.get(mode)
    if pts_count >= 4:
        return "#### ✅ Positioning complete! Ready to extract!"
    label_zh = conf['corner_labels'][pts_count]
    label_en = conf['corner_labels_en'][pts_count]
    return f"#### 👉 点击 Click: **{label_zh} / {label_en}**"


def on_extractor_upload(i, mode):
    """Handle image upload"""
    hint = get_first_hint(mode)
    return i, i, [], None, hint


def on_extractor_mode_change(img, mode):
    """Handle color mode change"""
    hint = get_first_hint(mode)
    return [], hint, img


def on_extractor_rotate(i, mode):
    """Rotate image"""
    from core.extractor import rotate_image
    if i is None:
        return None, None, [], get_first_hint(mode)
    r = rotate_image(i, "Rotate Left 90°")
    return r, r, [], get_first_hint(mode)


def on_extractor_click(img, pts, mode, evt: gr.SelectData):
    """Set corner point by clicking image"""
    from core.extractor import draw_corner_points

    if len(pts) >= 4:
        return img, pts, "#### ✅ 定位完成 Complete!"
    n = pts + [[evt.index[0], evt.index[1]]]
    vis = draw_corner_points(img, n, mode)
    hint = get_next_hint(mode, len(n))
    return vis, n, hint


def on_extractor_clear(img, mode):
    """Clear corner points"""
    hint = get_first_hint(mode)
    return img, [], hint
