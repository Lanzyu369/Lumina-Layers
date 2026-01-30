"""
Lumina Studio - Image Processing Core
Image processing core module - Handles image loading, preprocessing, color quantization and matching
"""

import numpy as np
import cv2
from PIL import Image
from scipy.spatial import KDTree

from config import PrinterConfig, ThinModeConfig, ColorSystem
from config import THIN_DATA_GRID_W, THIN_DATA_GRID_H


class LuminaImageProcessor:
    """
    Image processor class
    Handles LUT loading, image processing, and color matching
    """
    
    def __init__(self, lut_path, color_mode):
        """
        Initialize image processor
        """
        self.color_mode = color_mode
        self.is_thin_mode = ColorSystem.is_thin_mode(color_mode)
        self.lut_rgb = None
        self.ref_stacks = None
        self.ref_seq_lengths = None  # For 341 mode
        self.kdtree = None
        
        # Load and validate LUT
        if self.is_thin_mode:
            self._load_lut_341(lut_path)
        else:
            self._load_lut_1024(lut_path)
    
    def _load_lut_1024(self, lut_path):
        """加载并验证1024色LUT文件 | Load and validate 1024-color LUT file"""
        try:
            lut_grid = np.load(lut_path)
            measured_colors = lut_grid.reshape(-1, 3)
        except Exception as e:
            raise ValueError(f"❌ LUT file corrupted: {e}")
        
        valid_rgb, valid_stacks = [], []
        base_blue = np.array([30, 100, 200])
        dropped = 0
        
        # Filter outliers
        for i in range(1024):
            digits = []
            temp = i
            for _ in range(5):
                digits.append(temp % 4)
                temp //= 4
            stack = digits[::-1]
            
            real_rgb = measured_colors[i]
            dist = np.linalg.norm(real_rgb - base_blue)
            
            # Filter out anomalies: close to blue but doesn't contain blue
            if dist < 60 and 3 not in stack:
                dropped += 1
                continue
            
            valid_rgb.append(real_rgb)
            valid_stacks.append(stack)
        
        self.lut_rgb = np.array(valid_rgb)
        self.ref_stacks = np.array(valid_stacks)
        self.ref_seq_lengths = np.full(len(valid_stacks), 5, dtype=np.int32)  # All 5 layers
        self.kdtree = KDTree(self.lut_rgb)
        
        print(f"✅ LUT loaded (1024 mode, filtered {dropped} outliers)")
    
    def _load_lut_341(self, lut_path):
        """加载并验证341色LUT文件 | Load and validate 341-color LUT file"""
        from core.calibration import generate_341_sequences
        
        try:
            lut_grid = np.load(lut_path)
            if lut_grid.shape[0] == THIN_DATA_GRID_H and lut_grid.shape[1] == THIN_DATA_GRID_W:
                measured_colors = lut_grid.reshape(-1, 3)
            else:
                measured_colors = lut_grid.reshape(-1, 3)
        except Exception as e:
            raise ValueError(f"❌ LUT file corrupted: {e}")
        
        sequences = generate_341_sequences()
        valid_rgb, valid_stacks, valid_lengths = [], [], []
        num_colors = min(len(measured_colors), 341)
        
        for i in range(num_colors):
            seq = sequences[i]
            real_rgb = measured_colors[i]
            padded_seq = seq + [-1] * (4 - len(seq))
            valid_rgb.append(real_rgb)
            valid_stacks.append(padded_seq)
            valid_lengths.append(len(seq))
        
        self.lut_rgb = np.array(valid_rgb)
        self.ref_stacks = np.array(valid_stacks)
        self.ref_seq_lengths = np.array(valid_lengths, dtype=np.int32)
        self.kdtree = KDTree(self.lut_rgb)
        print(f"✅ LUT loaded (341 mode, {num_colors} colors)")
    
    def process_image(self, image_path, target_width_mm, modeling_mode,
                     quantize_colors, auto_bg, bg_tol,
                     blur_kernel=0, smooth_sigma=10):
        """
        Main image processing method
        """
        mode_str = str(modeling_mode).lower()
        use_high_fidelity = "high-fidelity" in mode_str or "高保真" in mode_str
        use_pixel = "pixel" in mode_str or "像素" in mode_str
        
        if use_high_fidelity:
            mode_name = "High-Fidelity"
        elif use_pixel:
            mode_name = "Pixel Art"
        else:
            mode_name = "High-Fidelity"
            use_high_fidelity = True
        
        if self.is_thin_mode: mode_name += " (341)"
        print(f"[IMAGE_PROCESSOR] Mode: {mode_name}, Filter: blur={blur_kernel}, sigma={smooth_sigma}")
        
        img = Image.open(image_path).convert('RGBA')
        img_arr_orig = np.array(img)
        alpha_arr_orig = img_arr_orig[:, :, 3]
        
        if use_high_fidelity:
            PIXELS_PER_MM = 10
            target_w = int(target_width_mm * PIXELS_PER_MM)
            pixel_to_mm_scale = 1.0 / PIXELS_PER_MM
        else:
            target_w = int(target_width_mm / PrinterConfig.NOZZLE_WIDTH)
            pixel_to_mm_scale = PrinterConfig.NOZZLE_WIDTH
        
        target_h = int(target_w * img.height / img.width)
        img = img.resize((target_w, target_h), Image.Resampling.NEAREST)
        img_arr = np.array(img)
        rgb_arr = img_arr[:, :, :3]
        alpha_arr = img_arr[:, :, 3]
        
        mask_transparent_initial = alpha_arr < 10
        
        debug_data = None
        if use_high_fidelity:
            matched_rgb, material_matrix, seq_lengths, bg_reference, debug_data = self._process_high_fidelity_mode(
                rgb_arr, target_h, target_w, quantize_colors, blur_kernel, smooth_sigma
            )
        else:
            matched_rgb, material_matrix, seq_lengths, bg_reference = self._process_pixel_mode(
                rgb_arr, target_h, target_w
            )
        
        mask_transparent = mask_transparent_initial.copy()
        if auto_bg:
            bg_color = bg_reference[0, 0]
            diff = np.sum(np.abs(bg_reference - bg_color), axis=-1)
            mask_transparent = np.logical_or(mask_transparent, diff < bg_tol)
        
        material_matrix[mask_transparent] = -1
        mask_solid = ~mask_transparent
        
        result = {
            'matched_rgb': matched_rgb,
            'material_matrix': material_matrix,
            'seq_lengths': seq_lengths,
            'mask_solid': mask_solid,
            'dimensions': (target_w, target_h),
            'pixel_scale': pixel_to_mm_scale,
            'is_thin_mode': self.is_thin_mode,
            'mode_info': {
                'name': mode_name,
                'use_high_fidelity': use_high_fidelity,
                'use_pixel': use_pixel,
                'is_thin': self.is_thin_mode
            }
        }
        if debug_data is not None: result['debug_data'] = debug_data
        return result

    def _process_high_fidelity_mode(self, rgb_arr, target_h, target_w, quantize_colors,
                                    blur_kernel, smooth_sigma):
        """High-fidelity mode with edge-preserving processing and K-Means"""
        if smooth_sigma > 0:
            rgb_processed = cv2.bilateralFilter(rgb_arr.astype(np.uint8), d=9, sigmaColor=smooth_sigma, sigmaSpace=smooth_sigma)
        else:
            rgb_processed = rgb_arr.astype(np.uint8)
        
        if blur_kernel > 0:
            kernel_size = blur_kernel if blur_kernel % 2 == 1 else blur_kernel + 1
            rgb_processed = cv2.medianBlur(rgb_processed, kernel_size)
            
        sharpen_kernel = np.array([[0, -0.5, 0], [-0.5, 3, -0.5], [0, -0.5, 0]])
        rgb_sharpened = cv2.filter2D(rgb_processed, -1, sharpen_kernel)
        rgb_sharpened = np.clip(rgb_sharpened, 0, 255).astype(np.uint8)
        
        pixels = rgb_sharpened.reshape(-1, 3).astype(np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
        _, labels, centers = cv2.kmeans(pixels, quantize_colors, None, criteria, 10, cv2.KMEANS_PP_CENTERS)
        centers = centers.astype(np.uint8)
        quantized_image = centers[labels.flatten()].reshape(target_h, target_w, 3)
        
        unique_colors = np.unique(quantized_image.reshape(-1, 3), axis=0)
        _, unique_indices = self.kdtree.query(unique_colors.astype(float))
        
        color_to_stack, color_to_rgb, color_to_length = {}, {}, {}
        for i, color in enumerate(unique_colors):
            key = tuple(color)
            color_to_stack[key] = self.ref_stacks[unique_indices[i]]
            color_to_rgb[key] = self.lut_rgb[unique_indices[i]]
            color_to_length[key] = self.ref_seq_lengths[unique_indices[i]]
            
        max_layers = ThinModeConfig.MAX_LAYERS if self.is_thin_mode else PrinterConfig.COLOR_LAYERS
        matched_rgb = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        material_matrix = np.zeros((target_h, target_w, max_layers), dtype=int)
        seq_lengths = np.zeros((target_h, target_w), dtype=np.int32)
        
        for y in range(target_h):
            for x in range(target_w):
                key = tuple(quantized_image[y, x])
                matched_rgb[y, x] = color_to_rgb[key]
                material_matrix[y, x] = color_to_stack[key][:max_layers]
                seq_lengths[y, x] = color_to_length[key]
                
        debug_data = {
            'quantized_image': quantized_image.copy(), 'num_colors': len(unique_colors),
            'bilateral_filtered': rgb_processed.copy(), 'sharpened': rgb_sharpened.copy(),
            'filter_settings': {'blur_kernel': blur_kernel, 'smooth_sigma': smooth_sigma}
        }
        return matched_rgb, material_matrix, seq_lengths, quantized_image, debug_data
    
    def _process_pixel_mode(self, rgb_arr, target_h, target_w):
        """Pixel art mode: direct color matching"""
        flat_rgb = rgb_arr.reshape(-1, 3)
        _, indices = self.kdtree.query(flat_rgb)
        max_layers = ThinModeConfig.MAX_LAYERS if self.is_thin_mode else PrinterConfig.COLOR_LAYERS
        matched_rgb = self.lut_rgb[indices].reshape(target_h, target_w, 3)
        stacks = self.ref_stacks[indices]
        material_matrix = stacks[:, :max_layers].reshape(target_h, target_w, max_layers)
        seq_lengths = self.ref_seq_lengths[indices].reshape(target_h, target_w)
        return matched_rgb, material_matrix, seq_lengths, rgb_arr
