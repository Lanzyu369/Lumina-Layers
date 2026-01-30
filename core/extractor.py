"""
Lumina Studio - Color Extractor Module
Color extraction module
"""

import os
import numpy as np
import cv2
import gradio as gr

from config import (
    ColorSystem,
    PHYSICAL_GRID_SIZE,
    DATA_GRID_SIZE,
    DST_SIZE,
    CELL_SIZE,
    LUT_FILE_PATH,
    # Thin mode (341) constants
    THIN_PHYSICAL_GRID_W,
    THIN_PHYSICAL_GRID_H,
    THIN_DATA_GRID_W,
    THIN_DATA_GRID_H,
    THIN_DST_SIZE_W,
    THIN_DST_SIZE_H,
    THIN_CELL_SIZE_W,
    THIN_CELL_SIZE_H,
    THIN_LUT_FILE_PATH
)
from utils import Stats


def generate_simulated_reference(color_mode: str = "RYBW"):
    """Generate reference image for visual comparison."""
    is_thin = ColorSystem.is_thin_mode(color_mode)
    
    if is_thin:
        return generate_simulated_reference_341(color_mode)
    else:
        return generate_simulated_reference_1024(color_mode)


def generate_simulated_reference_1024(color_mode: str = "RYBW"):
    """Generate reference image for 1024-color mode."""
    color_conf = ColorSystem.get(color_mode)
    preview = color_conf['preview']
    
    colors = {
        0: np.array(preview[0][:3]),
        1: np.array(preview[1][:3]),
        2: np.array(preview[2][:3]),
        3: np.array(preview[3][:3])
    }

    ref_img = np.zeros((DATA_GRID_SIZE, DATA_GRID_SIZE, 3), dtype=np.uint8)
    for i in range(1024):
        digits = []
        temp = i
        for _ in range(5):
            digits.append(temp % 4)
            temp //= 4
        stack = digits[::-1]

        mixed = sum(colors[mid] for mid in stack) / 5.0
        ref_img[i // DATA_GRID_SIZE, i % DATA_GRID_SIZE] = mixed.astype(np.uint8)

    return cv2.resize(ref_img, (512, 512), interpolation=cv2.INTER_NEAREST)


def generate_simulated_reference_341(color_mode: str):
    """Generate reference image for 341-color (W+CMYK) mode."""
    from core.calibration import generate_341_sequences
    
    color_conf = ColorSystem.get(color_mode)
    preview = color_conf['preview']
    
    # Colors: White(0), C(1), M(2), Y(3), K(4)
    colors = {
        0: np.array(preview[0][:3]),  # White
        1: np.array(preview[1][:3]),  # Cyan
        2: np.array(preview[2][:3]),  # Magenta
        3: np.array(preview[3][:3]),  # Yellow
        4: np.array(preview[4][:3])   # Black
    }
    
    sequences = generate_341_sequences()
    
    ref_img = np.zeros((THIN_DATA_GRID_H, THIN_DATA_GRID_W, 3), dtype=np.uint8)
    
    for i, seq in enumerate(sequences):
        if i >= THIN_DATA_GRID_W * THIN_DATA_GRID_H:
            break
        
        row = i // THIN_DATA_GRID_W
        col = i % THIN_DATA_GRID_W
        
        if len(seq) == 0:
            # White base only
            ref_img[row, col] = colors[0]
        else:
            # Mix white base with color layers
            # White base contributes, color layers are on top
            base_weight = 0.3  # Base white contribution
            layer_weight = 0.7 / len(seq)  # Equal weight for each color layer
            
            mixed = colors[0] * base_weight
            for mat_id in seq:
                mixed += colors[mat_id + 1] * layer_weight  # +1 because C=0 in seq but C=1 in colors
            
            ref_img[row, col] = np.clip(mixed, 0, 255).astype(np.uint8)
    
    # Resize for display (maintain aspect ratio)
    display_w = 512
    display_h = int(512 * THIN_DATA_GRID_H / THIN_DATA_GRID_W)
    return cv2.resize(ref_img, (display_w, display_h), interpolation=cv2.INTER_NEAREST)


def rotate_image(img, direction):
    if img is None:
        return None
    if direction in ("左旋 90°", "Rotate Left 90°"):
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif direction in ("右旋 90°", "Rotate Right 90°"):
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    return img


def draw_corner_points(img, points, color_mode: str):
    """Draw corner points with mode-specific colors and labels."""
    if img is None:
        return None

    vis = img.copy()
    color_conf = ColorSystem.get(color_mode)
    labels = color_conf['corner_labels']

    # Define colors for drawing (BGR for OpenCV)
    # Colors must match the corner_labels order for each mode
    if ColorSystem.is_thin_mode(color_mode):
        # W+CMYK (341) mode - viewed from bottom/print surface
        # Order: Yellow (TL), Magenta (TR), Cyan (BR), White (BL)
        draw_colors = [
            (42, 238, 244),   # Yellow (TL) - BGR
            (140, 0, 236),    # Magenta (TR) - BGR
            (214, 134, 0),    # Cyan (BR) - BGR
            (255, 255, 255),  # White (BL)
        ]
    elif "CMYW" in color_mode:
        # CMYW mode: White, Cyan, Magenta, Yellow
        draw_colors = [
            (255, 255, 255),  # White (TL)
            (214, 134, 0),    # Cyan (TR) - BGR
            (140, 0, 236),    # Magenta (BR) - BGR
            (42, 238, 244)    # Yellow (BL) - BGR
        ]
    else:  # RYBW
        draw_colors = [
            (255, 255, 255),  # White (TL)
            (60, 20, 220),    # Red (TR) - BGR
            (240, 100, 0),    # Blue (BR) - BGR
            (0, 230, 255)     # Yellow (BL) - BGR
        ]

    for i, pt in enumerate(points):
        color = draw_colors[i] if i < 4 else (0, 255, 0)
        px, py = int(round(pt[0])), int(round(pt[1]))

        # Draw filled circle
        cv2.circle(vis, (px, py), 15, color, -1)
        # Draw outline
        cv2.circle(vis, (px, py), 15, (0, 0, 0), 2)
        # Draw number
        cv2.putText(vis, str(i + 1), (px + 20, py + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)

        # Draw label
        if i < 4:
            cv2.putText(vis, labels[i], (px + 20, py + 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    return vis


def apply_auto_white_balance(img):
    h, w, _ = img.shape
    m = 50
    corners = [img[0:m, 0:m], img[0:m, w-m:w], img[h-m:h, 0:m], img[h-m:h, w-m:w]]
    avg_white = sum(c.mean(axis=(0, 1)) for c in corners) / 4.0
    gain = np.array([255, 255, 255]) / (avg_white + 1e-5)
    return np.clip(img.astype(float) * gain, 0, 255).astype(np.uint8)


def apply_brightness_correction(img):
    h, w, _ = img.shape
    img_lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(img_lab)

    m = 50
    tl, tr = l[0:m, 0:m].mean(), l[0:m, w-m:w].mean()
    bl, br = l[h-m:h, 0:m].mean(), l[h-m:h, w-m:w].mean()

    top = np.linspace(tl, tr, w)
    bot = np.linspace(bl, br, w)
    mask = np.array([top * (1 - y/h) + bot * (y/h) for y in range(h)])

    target = (tl + tr + bl + br) / 4.0
    l_new = np.clip(l.astype(float) * (target / (mask + 1e-5)), 0, 255).astype(np.uint8)

    return cv2.cvtColor(cv2.merge([l_new, a, b]), cv2.COLOR_LAB2RGB)


def run_extraction(img, points, offset_x, offset_y, zoom, barrel, wb, bright, color_mode="RYBW"):
    """Main extraction pipeline. Supports both 1024 and 341 modes."""
    if img is None:
        return None, None, None, "❌ 请先上传图片"
    if len(points) != 4:
        return None, None, None, "❌ 请点击4个角点"
    
    is_thin = ColorSystem.is_thin_mode(color_mode)
    
    if is_thin:
        return run_extraction_341(img, points, offset_x, offset_y, zoom, barrel, wb, bright)
    else:
        return run_extraction_1024(img, points, offset_x, offset_y, zoom, barrel, wb, bright)


def run_extraction_1024(img, points, offset_x, offset_y, zoom, barrel, wb, bright):
    """Extraction pipeline for 1024-color mode (32x32 grid)."""
    
    # Perspective transform
    # Map the four corner clicks directly to the image boundaries [0, 1000]
    # This assumes the user clicks the four corners of the entire calibration board.
    src = np.float32(points)
    dst = np.float32([
        [0, 0], [DST_SIZE, 0],
        [DST_SIZE, DST_SIZE], [0, DST_SIZE]
    ])

    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(img, M, (DST_SIZE, DST_SIZE))

    if wb:
        warped = apply_auto_white_balance(warped)
    if bright:
        warped = apply_brightness_correction(warped)

    # Sampling
    extracted = np.zeros((DATA_GRID_SIZE, DATA_GRID_SIZE, 3), dtype=np.uint8)
    vis = warped.copy()

    for r in range(DATA_GRID_SIZE):
        for c in range(DATA_GRID_SIZE):
            phys_r, phys_c = r + 1, c + 1
            nx = (phys_c + 0.5) / PHYSICAL_GRID_SIZE * 2 - 1
            ny = (phys_r + 0.5) / PHYSICAL_GRID_SIZE * 2 - 1

            rad = np.sqrt(nx**2 + ny**2)
            k = 1 + barrel * (rad**2)
            dx, dy = nx * k * zoom, ny * k * zoom

            cx = (dx + 1) / 2 * DST_SIZE + offset_x
            cy = (dy + 1) / 2 * DST_SIZE + offset_y

            if 0 <= cx < DST_SIZE and 0 <= cy < DST_SIZE:
                x0, y0 = int(max(0, cx - 4)), int(max(0, cy - 4))
                x1, y1 = int(min(DST_SIZE, cx + 4)), int(min(DST_SIZE, cy + 4))
                reg = warped[y0:y1, x0:x1]
                avg = reg.mean(axis=(0, 1)).astype(int) if reg.size > 0 else [0, 0, 0]
                cv2.drawMarker(vis, (int(cx), int(cy)), (0, 255, 0), cv2.MARKER_CROSS, 8, 1)
            else:
                avg = [0, 0, 0]
            extracted[r, c] = avg

    np.save(LUT_FILE_PATH, extracted)
    prev = cv2.resize(extracted, (512, 512), interpolation=cv2.INTER_NEAREST)

    Stats.increment("extractions")

    return vis, prev, LUT_FILE_PATH, "✅ 提取完成！LUT已保存 (1024色)"


def run_extraction_341(img, points, offset_x, offset_y, zoom, barrel, wb, bright):
    """Extraction pipeline for 341-color mode (19x18 grid)."""
    # Non-square perspective transform
    half_w = THIN_CELL_SIZE_W / 2.0
    half_h = THIN_CELL_SIZE_H / 2.0
    
    src = np.float32(points)
    dst = np.float32([
        [half_w, half_h], 
        [THIN_DST_SIZE_W - half_w, half_h],
        [THIN_DST_SIZE_W - half_w, THIN_DST_SIZE_H - half_h], 
        [half_w, THIN_DST_SIZE_H - half_h]
    ])

    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(img, M, (THIN_DST_SIZE_W, THIN_DST_SIZE_H))

    if wb:
        warped = apply_auto_white_balance(warped)
    if bright:
        warped = apply_brightness_correction(warped)

    # Sampling for 19x18 grid
    extracted = np.zeros((THIN_DATA_GRID_H, THIN_DATA_GRID_W, 3), dtype=np.uint8)
    vis = warped.copy()

    for r in range(THIN_DATA_GRID_H):
        for c in range(THIN_DATA_GRID_W):
            # Physical position (with padding offset)
            phys_r, phys_c = r + 1, c + 1
            
            # Normalized coordinates
            nx = (phys_c + 0.5) / THIN_PHYSICAL_GRID_W * 2 - 1
            ny = (phys_r + 0.5) / THIN_PHYSICAL_GRID_H * 2 - 1

            rad = np.sqrt(nx**2 + ny**2)
            k = 1 + barrel * (rad**2)
            dx, dy = nx * k * zoom, ny * k * zoom

            # Map to destination coordinates
            cx = (dx + 1) / 2 * THIN_DST_SIZE_W + offset_x
            cy = (dy + 1) / 2 * THIN_DST_SIZE_H + offset_y

            if 0 <= cx < THIN_DST_SIZE_W and 0 <= cy < THIN_DST_SIZE_H:
                x0, y0 = int(max(0, cx - 4)), int(max(0, cy - 4))
                x1, y1 = int(min(THIN_DST_SIZE_W, cx + 4)), int(min(THIN_DST_SIZE_H, cy + 4))
                reg = warped[y0:y1, x0:x1]
                avg = reg.mean(axis=(0, 1)).astype(int) if reg.size > 0 else [0, 0, 0]
                cv2.drawMarker(vis, (int(cx), int(cy)), (0, 255, 0), cv2.MARKER_CROSS, 8, 1)
            else:
                avg = [0, 0, 0]
            extracted[r, c] = avg

    # Save as 1D array of 341 RGB values (flatten the 19x18 grid)
    np.save(THIN_LUT_FILE_PATH, extracted)
    
    # Generate preview (maintain aspect ratio)
    preview_w = 512
    preview_h = int(512 * THIN_DATA_GRID_H / THIN_DATA_GRID_W)
    prev = cv2.resize(extracted, (preview_w, preview_h), interpolation=cv2.INTER_NEAREST)

    Stats.increment("extractions")

    return vis, prev, THIN_LUT_FILE_PATH, f"✅ 提取完成！LUT已保存 (341色 {THIN_DATA_GRID_W}×{THIN_DATA_GRID_H})"


def probe_lut_cell(evt: gr.SelectData, color_mode: str = "RYBW"):
    """Probe a LUT cell and return its color information."""
    is_thin = ColorSystem.is_thin_mode(color_mode)
    lut_path = THIN_LUT_FILE_PATH if is_thin else LUT_FILE_PATH
    
    if not os.path.exists(lut_path):
        return "⚠️ 无数据", None, None
    try:
        lut = np.load(lut_path)
    except:
        return "⚠️ 数据损坏", None, None

    x, y = evt.index
    
    if is_thin:
        # 341 mode: 19x18 grid displayed at variable size
        grid_w, grid_h = THIN_DATA_GRID_W, THIN_DATA_GRID_H
        preview_w = 512
        preview_h = int(512 * grid_h / grid_w)
        scale_x = preview_w / grid_w
        scale_y = preview_h / grid_h
        c = min(max(int(x / scale_x), 0), grid_w - 1)
        r = min(max(int(y / scale_y), 0), grid_h - 1)
    else:
        # 1024 mode: 32x32 grid
        scale = 512 / DATA_GRID_SIZE
        c = min(max(int(x / scale), 0), DATA_GRID_SIZE - 1)
        r = min(max(int(y / scale), 0), DATA_GRID_SIZE - 1)

    rgb = lut[r, c]
    hex_c = '#{:02x}{:02x}{:02x}'.format(*rgb)
    
    # Calculate sequence ID for 341 mode
    seq_info = ""
    if is_thin:
        seq_id = r * THIN_DATA_GRID_W + c
        if seq_id < 341:
            from core.calibration import get_sequence_by_id
            seq = get_sequence_by_id(seq_id)
            mat_names = ["C", "M", "Y", "K"]
            seq_str = "".join([mat_names[m] for m in seq]) if seq else "Base"
            seq_info = f"<br><b>序列 #{seq_id}:</b> {seq_str}"

    html = f"""
    <div style='background:#1a1a2e; padding:10px; border-radius:8px; color:white;'>
        <b>行 {r+1} / 列 {c+1}</b>{seq_info}<br>
        <div style='background:{hex_c}; width:60px; height:30px; border:2px solid white; 
             display:inline-block; vertical-align:middle; border-radius:4px;'></div>
        <span style='margin-left:10px; font-family:monospace;'>{hex_c}</span>
    </div>
    """
    return html, hex_c, (r, c)


def manual_fix_cell(coord, color_input, color_mode: str = "RYBW"):
    """Manually fix a LUT cell color."""
    is_thin = ColorSystem.is_thin_mode(color_mode)
    lut_path = THIN_LUT_FILE_PATH if is_thin else LUT_FILE_PATH
    
    if not coord or not os.path.exists(lut_path):
        return None, "⚠️ 错误"

    try:
        lut = np.load(lut_path)
        r, c = coord
        new_color = [0, 0, 0]

        color_str = str(color_input)
        if color_str.startswith('rgb'):
            clean = color_str.replace('rgb', '').replace('a', '').replace('(', '').replace(')', '')
            parts = clean.split(',')
            if len(parts) >= 3:
                new_color = [int(float(p.strip())) for p in parts[:3]]
        elif color_str.startswith('#'):
            hex_s = color_str.lstrip('#')
            new_color = [int(hex_s[i:i+2], 16) for i in (0, 2, 4)]
        else:
            new_color = [int(color_str[i:i+2], 16) for i in (0, 2, 4)]

        lut[r, c] = new_color
        np.save(lut_path, lut)
        
        # Generate preview with correct aspect ratio
        if is_thin:
            preview_w = 512
            preview_h = int(512 * THIN_DATA_GRID_H / THIN_DATA_GRID_W)
            prev = cv2.resize(lut, (preview_w, preview_h), interpolation=cv2.INTER_NEAREST)
        else:
            prev = cv2.resize(lut, (512, 512), interpolation=cv2.INTER_NEAREST)
        
        return prev, "✅ 已修正"
    except Exception as e:
        return None, f"❌ 格式错误: {color_input}"
