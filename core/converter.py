"""
Lumina Studio - Image Converter Coordinator (Refactored)
Image conversion coordinator - Refactored version
Coordinates modules to complete image-to-3D model conversion
"""

import os
import numpy as np
import cv2
import trimesh
from PIL import Image, ImageDraw, ImageFont
import gradio as gr


from config import PrinterConfig, ThinModeConfig, ColorSystem, PREVIEW_SCALE, PREVIEW_MARGIN, OUTPUT_DIR
from utils import Stats, safe_fix_3mf_names

# Import refactored modules
from core.image_processing import LuminaImageProcessor
from core.mesh_generators import get_mesher
from core.geometry_utils import create_keychain_loop


# ========== Debug Helper Functions ==========

def _save_debug_preview(debug_data, material_matrix, mask_solid, image_path, mode_name):
    """
    Save vector mode debug preview image
    """
    quantized_image = debug_data['quantized_image']
    num_colors = debug_data['num_colors']
    
    print(f"[DEBUG_PREVIEW] Saving {mode_name} debug preview...")
    print(f"[DEBUG_PREVIEW] Quantized to {num_colors} colors")
    
    # Create debug image (RGB format)
    debug_img = quantized_image.copy()
    
    # Optional: Draw contours
    try:
        contour_overlay = debug_img.copy()
        for mat_id in range(4):
            # Get mask for this material
            mat_mask = np.zeros(material_matrix.shape[:2], dtype=np.uint8)
            for layer in range(material_matrix.shape[2]):
                mat_mask = np.logical_or(mat_mask, material_matrix[:, :, layer] == mat_id)
            
            mat_mask = np.logical_and(mat_mask, mask_solid).astype(np.uint8) * 255
            if not np.any(mat_mask):
                continue
            
            contours, _ = cv2.findContours(mat_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(contour_overlay, contours, -1, (0, 0, 0), 1)
        
        debug_img = contour_overlay
        print(f"[DEBUG_PREVIEW] Contours drawn on preview")
    except Exception as e:
        print(f"[DEBUG_PREVIEW] Warning: Could not draw contours: {e}")
    
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    debug_path = os.path.join(OUTPUT_DIR, f"{base_name}_{mode_name}_Debug.png")
    
    debug_pil = Image.fromarray(debug_img, mode='RGB')
    debug_pil.save(debug_path, 'PNG')
    print(f"[DEBUG_PREVIEW] ✅ Saved: {debug_path}")


# ========== Main Conversion Function ==========

def convert_image_to_3d(image_path, lut_path, target_width_mm, spacer_thick,
                         structure_mode, auto_bg, bg_tol, color_mode,
                         add_loop, loop_width, loop_length, loop_hole, loop_pos,
                         modeling_mode="vector", quantize_colors=32,
                         blur_kernel=0, smooth_sigma=10):
    """
    Main conversion function
    """
    if image_path is None:
        return None, None, None, "❌ Please upload an image"
    if lut_path is None:
        return None, None, None, "⚠️ Please select or upload a .npy calibration file!"
    
    if isinstance(lut_path, str):
        actual_lut_path = lut_path
    elif hasattr(lut_path, 'name'):
        actual_lut_path = lut_path.name
    else:
        return None, None, None, "❌ Invalid LUT file format"
    
    print(f"[CONVERTER] Starting conversion... Mode: {modeling_mode}, Quantize: {quantize_colors}")
    
    color_conf = ColorSystem.get(color_mode)
    slot_names = color_conf['slots']
    preview_colors = color_conf['preview']
    is_thin_mode = ColorSystem.is_thin_mode(color_mode)
    
    # ========== Step 1: Image Processing ==========
    try:
        processor = LuminaImageProcessor(actual_lut_path, color_mode)
        result = processor.process_image(
            image_path=image_path,
            target_width_mm=target_width_mm,
            modeling_mode=modeling_mode,
            quantize_colors=quantize_colors,
            auto_bg=auto_bg,
            bg_tol=bg_tol,
            blur_kernel=blur_kernel,
            smooth_sigma=smooth_sigma
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, None, None, f"❌ Image processing failed: {e}"
    
    matched_rgb = result['matched_rgb']
    material_matrix = result['material_matrix']
    seq_lengths = result.get('seq_lengths')
    mask_solid = result['mask_solid']
    target_w, target_h = result['dimensions']
    pixel_scale = result['pixel_scale']
    mode_info = result['mode_info']
    debug_data = result.get('debug_data')
    
    print(f"[CONVERTER] Image processed: {target_w}×{target_h}px, scale={pixel_scale}mm/px, thin={is_thin_mode}")
    
    # ========== Step 2: Debug Preview ==========
    if debug_data is not None and mode_info.get('use_high_fidelity'):
        try:
            _save_debug_preview(debug_data, material_matrix, mask_solid, image_path, mode_info['name'])
        except Exception as e:
            print(f"[CONVERTER] Warning: Failed to save debug preview: {e}")
    
    # ========== Step 3: Preview Image ==========
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    preview_rgba[mask_solid, 3] = 255
    
    # ========== Step 4: Handle Keychain Loop ==========
    loop_info = None
    if add_loop and loop_pos is not None:
        loop_info = _calculate_loop_info(
            loop_pos, loop_width, loop_length, loop_hole,
            mask_solid, material_matrix, target_w, target_h, pixel_scale
        )
        if loop_info:
            preview_rgba = _draw_loop_on_preview(preview_rgba, loop_info, color_conf, pixel_scale)
    
    # Create preview image with white background
    preview_pil = Image.fromarray(preview_rgba, mode='RGBA')
    bg = Image.new('RGB', (target_w, target_h), (255, 255, 255))
    bg.paste(preview_pil, (0, 0), preview_pil)
    preview_img = bg
    
    # ========== Step 5: Build Voxel Matrix ==========
    if is_thin_mode:
        full_matrix = _build_voxel_matrix_341(
            material_matrix, seq_lengths, mask_solid, spacer_thick, structure_mode
        )
    else:
        full_matrix = _build_voxel_matrix(
            material_matrix, mask_solid, spacer_thick, structure_mode
        )
    
    total_layers = full_matrix.shape[0]
    print(f"[CONVERTER] Voxel matrix: {full_matrix.shape} (Z×H×W)")
    
    # ========== Step 6: Generate 3D Meshes ==========
    scene = trimesh.Scene()
    transform = np.eye(4)
    transform[0, 0] = pixel_scale
    transform[1, 1] = pixel_scale
    transform[2, 2] = PrinterConfig.LAYER_HEIGHT
    
    mesher = get_mesher(modeling_mode)
    print(f"[CONVERTER] Using mesher: {mesher.__class__.__name__}")
    
    valid_slot_names = []
    num_materials = 5 if is_thin_mode else 4
    
    for mat_id in range(num_materials):
        mesh = mesher.generate_mesh(full_matrix, mat_id, target_h)
        if mesh:
            mesh.apply_transform(transform)
            mesh.visual.face_colors = preview_colors[mat_id]
            name = slot_names[mat_id]
            mesh.metadata['name'] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)
            valid_slot_names.append(name)
            print(f"[CONVERTER] Added mesh for {name}")
    
    # ========== Step 7: Add Keychain Loop Mesh ==========
    loop_added = False
    if add_loop and loop_info is not None:
        try:
            loop_thickness = total_layers * PrinterConfig.LAYER_HEIGHT
            loop_mesh = create_keychain_loop(
                width_mm=loop_info['width_mm'],
                length_mm=loop_info['length_mm'],
                hole_dia_mm=loop_info['hole_dia_mm'],
                thickness_mm=loop_thickness,
                attach_x_mm=loop_info['attach_x_mm'],
                attach_y_mm=loop_info['attach_y_mm']
            )
            if loop_mesh is not None:
                loop_mat_id = loop_info['color_id']
                # Correct index for 341 mode (if needed)
                if is_thin_mode:
                    loop_mat_id += 1 # White is 0, CMYK are 1-4
                
                loop_mesh.visual.face_colors = preview_colors[loop_mat_id]
                loop_mesh.metadata['name'] = "Keychain_Loop"
                scene.add_geometry(loop_mesh, node_name="Keychain_Loop", geom_name="Keychain_Loop")
                valid_slot_names.append("Keychain_Loop")
                loop_added = True
        except Exception as e:
            print(f"[CONVERTER] Loop creation failed: {e}")
    
    # ========== Step 8: Export 3MF ==========
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    out_path = os.path.join(OUTPUT_DIR, f"{base_name}_Lumina.3mf")
    scene.export(out_path)
    safe_fix_3mf_names(out_path, valid_slot_names)
    print(f"[CONVERTER] 3MF exported: {out_path}")
    
    # ========== Step 9: Generate 3D Preview (Simplified) ==========
    preview_mesh = _create_preview_mesh(matched_rgb, mask_solid, total_layers)
    if preview_mesh:
        preview_mesh.apply_transform(transform)
        if loop_added and loop_info:
            try:
                loop_thickness = total_layers * PrinterConfig.LAYER_HEIGHT
                preview_loop = create_keychain_loop(
                    width_mm=loop_info['width_mm'],
                    length_mm=loop_info['length_mm'],
                    hole_dia_mm=loop_info['hole_dia_mm'],
                    thickness_mm=loop_thickness,
                    attach_x_mm=loop_info['attach_x_mm'],
                    attach_y_mm=loop_info['attach_y_mm']
                )
                if preview_loop:
                    loop_mat_id = loop_info['color_id']
                    if is_thin_mode: loop_mat_id += 1
                    loop_color = preview_colors[loop_mat_id]
                    preview_loop.visual.face_colors = [loop_color] * len(preview_loop.faces)
                    preview_mesh = trimesh.util.concatenate([preview_mesh, preview_loop])
            except Exception as e:
                print(f"[CONVERTER] Preview loop failed: {e}")
        
        glb_path = os.path.join(OUTPUT_DIR, f"{base_name}_Preview.glb")
        preview_mesh.export(glb_path)
    else:
        glb_path = None
    
    Stats.increment("conversions")
    mode_name = mode_info.get('name', modeling_mode)
    msg = f"✅ Conversion complete ({mode_name})! Resolution: {target_w}×{target_h}px"
    if loop_added:
        msg += f" | Loop added"
    
    return out_path, glb_path, preview_img, msg


def _calculate_loop_info(loop_pos, loop_width, loop_length, loop_hole,
                         mask_solid, material_matrix, target_w, target_h, pixel_scale):
    """Calculate keychain loop information"""
    solid_rows = np.any(mask_solid, axis=1)
    if not np.any(solid_rows):
        return None
    
    click_x, click_y = loop_pos
    attach_col = int(click_x)
    attach_row = int(click_y)
    attach_col = max(0, min(target_w - 1, attach_col))
    attach_row = max(0, min(target_h - 1, attach_row))
    
    col_mask = mask_solid[:, attach_col]
    if np.any(col_mask):
        solid_rows_in_col = np.where(col_mask)[0]
        distances = np.abs(solid_rows_in_col - attach_row)
        nearest_idx = np.argmin(distances)
        top_row = solid_rows_in_col[nearest_idx]
    else:
        top_row = np.argmax(solid_rows)
        solid_cols_in_top = np.where(mask_solid[top_row])[0]
        if len(solid_cols_in_top) > 0:
            distances = np.abs(solid_cols_in_top - attach_col)
            nearest_idx = np.argmin(distances)
            attach_col = solid_cols_in_top[nearest_idx]
        else:
            attach_col = target_w // 2
    
    attach_col = max(0, min(target_w - 1, attach_col))
    
    loop_color_id = 0
    search_area = material_matrix[
        max(0, top_row-2):top_row+3,
        max(0, attach_col-3):attach_col+4
    ]
    search_area = search_area[search_area >= 0]
    if len(search_area) > 0:
        unique, counts = np.unique(search_area, return_counts=True)
        for mat_id in unique[np.argsort(-counts)]:
            if mat_id != 0:
                loop_color_id = int(mat_id)
                break
    
    return {
        'attach_x_mm': attach_col * pixel_scale,
        'attach_y_mm': (target_h - 1 - top_row) * pixel_scale,
        'width_mm': loop_width,
        'length_mm': loop_length,
        'hole_dia_mm': loop_hole,
        'color_id': loop_color_id
    }


def _draw_loop_on_preview(preview_rgba, loop_info, color_conf, pixel_scale):
    """Draw keychain loop on preview image"""
    preview_pil = Image.fromarray(preview_rgba, mode='RGBA')
    draw = ImageDraw.Draw(preview_pil)
    
    color_id = loop_info['color_id']
    if ColorSystem.is_thin_mode(color_conf['name']):
        color_id += 1 # White is 0
    
    loop_color_rgba = tuple(color_conf['preview'][color_id][:3]) + (255,)
    
    attach_col = int(loop_info['attach_x_mm'] / pixel_scale)
    attach_row = int((preview_rgba.shape[0] - 1) - loop_info['attach_y_mm'] / pixel_scale)
    
    loop_w_px = int(loop_info['width_mm'] / pixel_scale)
    loop_h_px = int(loop_info['length_mm'] / pixel_scale)
    hole_r_px = int(loop_info['hole_dia_mm'] / 2 / pixel_scale)
    circle_r_px = loop_w_px // 2
    
    loop_bottom = attach_row
    loop_left = attach_col - loop_w_px // 2
    loop_right = attach_col + loop_w_px // 2
    rect_h_px = loop_h_px - circle_r_px
    rect_top = loop_bottom - rect_h_px
    circle_center_y = rect_top
    circle_center_x = attach_col
    
    if rect_h_px > 0:
        draw.rectangle([loop_left, rect_top, loop_right, rect_bottom], fill=loop_color_rgba)
    draw.ellipse([circle_center_x - circle_r_px, circle_center_y - circle_r_px,
                  circle_center_x + circle_r_px, circle_center_y + circle_r_px],
                 fill=loop_color_rgba)
    draw.ellipse([circle_center_x - hole_r_px, circle_center_y - hole_r_px,
                  circle_center_x + hole_r_px, circle_center_y + hole_r_px],
                 fill=(0, 0, 0, 0))
    
    return np.array(preview_pil)


def _build_voxel_matrix(material_matrix, mask_solid, spacer_thick, structure_mode):
    """Build complete voxel matrix (1024-color mode)"""
    target_h, target_w = material_matrix.shape[:2]
    mask_transparent = ~mask_solid
    bottom_voxels = np.transpose(material_matrix, (2, 0, 1))
    spacer_layers = max(1, int(round(spacer_thick / PrinterConfig.LAYER_HEIGHT)))
    
    if "双面" in structure_mode or "Double" in structure_mode:
        top_voxels = np.transpose(material_matrix[..., ::-1], (2, 0, 1))
        total_layers = 5 + spacer_layers + 5
        full_matrix = np.full((total_layers, target_h, target_w), -1, dtype=int)
        full_matrix[0:5] = bottom_voxels
        spacer = np.full((target_h, target_w), -1, dtype=int)
        spacer[~mask_transparent] = 0
        for z in range(5, 5 + spacer_layers):
            full_matrix[z] = spacer
        full_matrix[5 + spacer_layers:] = top_voxels
    else:
        total_layers = 5 + spacer_layers
        full_matrix = np.full((total_layers, target_h, target_w), -1, dtype=int)
        full_matrix[0:5] = bottom_voxels
        spacer = np.full((target_h, target_w), -1, dtype=int)
        spacer[~mask_transparent] = 0
        for z in range(5, total_layers):
            full_matrix[z] = spacer
    
    return full_matrix


def _build_voxel_matrix_341(material_matrix, seq_lengths, mask_solid, spacer_thick, structure_mode):
    """Build complete voxel matrix (341-color mode)"""
    target_h, target_w = material_matrix.shape[:2]
    mask_transparent = ~mask_solid
    base_mm = ThinModeConfig.BASE_MM
    base_layers = int(round(base_mm / PrinterConfig.LAYER_HEIGHT))
    max_color_layers = ThinModeConfig.MAX_LAYERS
    spacer_layers = max(1, int(round(spacer_thick / PrinterConfig.LAYER_HEIGHT)))
    
    if "双面" in structure_mode:
        total_layers = max_color_layers + base_layers + spacer_layers + base_layers + max_color_layers
        full_matrix = np.full((total_layers, target_h, target_w), -1, dtype=int)
        for y in range(target_h):
            for x in range(target_w):
                if mask_transparent[y, x]: continue
                seq_len = int(seq_lengths[y, x])
                for layer_idx in range(seq_len):
                    mat_id = material_matrix[y, x, layer_idx]
                    if mat_id >= 0: full_matrix[layer_idx, y, x] = mat_id + 1
        for z in range(max_color_layers, max_color_layers + base_layers):
            full_matrix[z][~mask_transparent] = 0
        mid_start = max_color_layers + base_layers
        for z in range(mid_start, mid_start + spacer_layers):
            full_matrix[z][~mask_transparent] = 0
        top_base_start = mid_start + spacer_layers
        for z in range(top_base_start, top_base_start + base_layers):
            full_matrix[z][~mask_transparent] = 0
        top_color_start = top_base_start + base_layers
        for y in range(target_h):
            for x in range(target_w):
                if mask_transparent[y, x]: continue
                seq_len = int(seq_lengths[y, x])
                for layer_idx in range(seq_len):
                    mat_id = material_matrix[y, x, seq_len - 1 - layer_idx]
                    if mat_id >= 0: full_matrix[top_color_start + layer_idx, y, x] = mat_id + 1
    else:
        total_layers = base_layers + max_color_layers
        full_matrix = np.full((total_layers, target_h, target_w), -1, dtype=int)
        for z in range(base_layers):
            full_matrix[z][~mask_transparent] = 0
        for y in range(target_h):
            for x in range(target_w):
                if mask_transparent[y, x]: continue
                seq_len = int(seq_lengths[y, x])
                for layer_idx in range(seq_len):
                    mat_id = material_matrix[y, x, layer_idx]
                    if mat_id >= 0: full_matrix[base_layers + layer_idx, y, x] = mat_id + 1
    return full_matrix


def _create_preview_mesh(matched_rgb, mask_solid, total_layers):
    """Create simplified 3D preview mesh"""
    height, width = matched_rgb.shape[:2]
    total_pixels = width * height
    if total_pixels > 2_000_000: return None
    
    if total_pixels > 500_000:
        scale_factor = max(2, min(int(np.sqrt(total_pixels / 300_000)), 16))
        new_height, new_width = height // scale_factor, width // scale_factor
        matched_rgb = cv2.resize(matched_rgb, (new_width, new_height), interpolation=cv2.INTER_AREA)
        mask_solid = cv2.resize(mask_solid.astype(np.uint8), (new_width, new_height), interpolation=cv2.INTER_NEAREST).astype(bool)
        height, width = new_height, new_width
        shrink = 0.05 * scale_factor
    else:
        shrink = 0.05
        
    vertices, faces, face_colors = [], [], []
    for y in range(height):
        for x in range(width):
            if not mask_solid[y, x]: continue
            rgb = matched_rgb[y, x]
            rgba = [int(rgb[0]), int(rgb[1]), int(rgb[2]), 255]
            world_y = (height - 1 - y)
            x0, x1 = x + shrink, x + 1 - shrink
            y0, y1 = world_y + shrink, world_y + 1 - shrink
            z0, z1 = 0, total_layers
            base_idx = len(vertices)
            vertices.extend([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                             [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]])
            cube_faces = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
                          [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
                          [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]
            for f in cube_faces:
                faces.append([v + base_idx for v in f])
                face_colors.append(rgba)
    
    if not vertices: return None
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    mesh.visual.face_colors = np.array(face_colors, dtype=np.uint8)
    return mesh


def generate_preview_cached(image_path, lut_path, target_width_mm,
                            auto_bg, bg_tol, color_mode):
    """Generate preview and cache data"""
    if image_path is None: return None, None, "❌ Please upload an image"
    if lut_path is None: return None, None, "⚠️ Please select or upload calibration file"
    
    if isinstance(lut_path, str): actual_lut_path = lut_path
    elif hasattr(lut_path, 'name'): actual_lut_path = lut_path.name
    else: return None, None, "❌ Invalid LUT file format"
    
    try:
        processor = LuminaImageProcessor(actual_lut_path, color_mode)
        result = processor.process_image(
            image_path=image_path, target_width_mm=target_width_mm,
            modeling_mode="pixel", quantize_colors=16, auto_bg=auto_bg, bg_tol=bg_tol
        )
    except Exception as e:
        return None, None, f"❌ Preview generation failed: {e}"
    
    cache = {
        'target_w': result['dimensions'][0], 'target_h': result['dimensions'][1],
        'mask_solid': result['mask_solid'], 'material_matrix': result['material_matrix'],
        'matched_rgb': result['matched_rgb'], 'preview_rgba': None,
        'color_conf': ColorSystem.get(color_mode)
    }
    
    preview_rgba = np.zeros((result['dimensions'][1], result['dimensions'][0], 4), dtype=np.uint8)
    preview_rgba[result['mask_solid'], :3] = result['matched_rgb'][result['mask_solid']]
    preview_rgba[result['mask_solid'], 3] = 255
    cache['preview_rgba'] = preview_rgba
    
    display = render_preview(preview_rgba, None, 0, 0, 0, 0, False, cache['color_conf'])
    return display, cache, "✅ Preview ready"


def render_preview(preview_rgba, loop_pos, loop_width, loop_length, 
                   loop_hole, loop_angle, loop_enabled, color_conf):
    """Render preview with keychain loop and coordinate grid"""
    h, w = preview_rgba.shape[:2]
    new_w, new_h = w * PREVIEW_SCALE, h * PREVIEW_SCALE
    margin = PREVIEW_MARGIN
    canvas_w, canvas_h = new_w + margin, new_h + margin
    canvas = Image.new('RGBA', (canvas_w, canvas_h), (240, 240, 245, 255))
    draw = ImageDraw.Draw(canvas)
    
    # Grid
    grid_step, main_step = 10 * PREVIEW_SCALE, 50 * PREVIEW_SCALE
    for x in range(margin, canvas_w, grid_step): draw.line([(x, margin), (x, canvas_h)], fill=(220, 220, 225), width=1)
    for y in range(margin, canvas_h, grid_step): draw.line([(margin, y), (canvas_w, y)], fill=(220, 220, 225), width=1)
    
    pil_img = Image.fromarray(preview_rgba, mode='RGBA').resize((new_w, new_h), Image.Resampling.NEAREST)
    canvas.paste(pil_img, (margin, 0), pil_img)
    
    if loop_enabled and loop_pos is not None:
        canvas = _draw_loop_on_canvas(canvas, loop_pos, loop_width, loop_length, loop_hole, loop_angle, color_conf, margin)
    
    return np.array(canvas.convert('RGB'))


def _draw_loop_on_canvas(pil_img, loop_pos, loop_width, loop_length, 
                         loop_hole, loop_angle, color_conf, margin):
    """Draw keychain loop marker on canvas"""
    loop_w_px = int(loop_width / PrinterConfig.NOZZLE_WIDTH * PREVIEW_SCALE)
    loop_h_px = int(loop_length / PrinterConfig.NOZZLE_WIDTH * PREVIEW_SCALE)
    hole_r_px = int(loop_hole / 2 / PrinterConfig.NOZZLE_WIDTH * PREVIEW_SCALE)
    circle_r_px = loop_w_px // 2
    cx = int(loop_pos[0] * PREVIEW_SCALE) + margin
    cy = int(loop_pos[1] * PREVIEW_SCALE)
    
    size = max(loop_w_px, loop_h_px) * 2 + 20
    layer = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    lc = size // 2
    rect_h = max(1, loop_h_px - circle_r_px)
    draw.rectangle([lc-loop_w_px//2, lc, lc+loop_w_px//2, lc+rect_h], fill=(220,60,60,200), outline=(255,255,255), width=2)
    draw.ellipse([lc-circle_r_px, lc-circle_r_px, lc+circle_r_px, lc+circle_r_px], fill=(220,60,60,200), outline=(255,255,255), width=2)
    draw.ellipse([lc-hole_r_px, lc-hole_r_px, lc+hole_r_px, lc+hole_r_px], fill=(0,0,0,0))
    
    if loop_angle != 0: layer = layer.rotate(-loop_angle, center=(lc, lc), resample=Image.BICUBIC)
    pil_img.paste(layer, (cx-lc, cy-lc-rect_h//2), layer)
    return pil_img


def on_preview_click(cache, loop_pos, evt: gr.SelectData):
    """Handle preview image click event"""
    if evt is None or cache is None: return loop_pos, False, "Error"
    click_x, click_y = evt.index
    click_x -= PREVIEW_MARGIN
    orig_x, orig_y = click_x / PREVIEW_SCALE, click_y / PREVIEW_SCALE
    orig_x = max(0, min(cache['target_w'] - 1, orig_x))
    orig_y = max(0, min(cache['target_h'] - 1, orig_y))
    return (orig_x, orig_y), True, f"Pos: ({orig_x:.1f}, {orig_y:.1f})"


def update_preview_with_loop(cache, loop_pos, add_loop,
                            loop_width, loop_length, loop_hole, loop_angle):
    """Update preview image (with keychain loop)"""
    if cache is None: return None
    return render_preview(cache['preview_rgba'], loop_pos if add_loop else None,
                         loop_width, loop_length, loop_hole, loop_angle, add_loop, cache['color_conf'])


def on_remove_loop():
    """Remove keychain loop"""
    return None, False, 0, "Loop removed"


def generate_final_model(image_path, lut_path, target_width_mm, spacer_thick,
                        structure_mode, auto_bg, bg_tol, color_mode,
                        add_loop, loop_width, loop_length, loop_hole, loop_pos,
                        modeling_mode="vector", quantize_colors=64):
    """Final model generation wrapper"""
    return convert_image_to_3d(image_path, lut_path, target_width_mm, spacer_thick,
                             structure_mode, auto_bg, bg_tol, color_mode,
                             add_loop, loop_width, loop_length, loop_hole, loop_pos,
                             modeling_mode, quantize_colors)

