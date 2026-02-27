"""
Lumina Studio - Image Processing Core

Handles image loading, preprocessing, color quantization and matching.
"""

import os
import sys
import numpy as np
import cv2
from PIL import Image
from scipy.spatial import KDTree

from config import PrinterConfig, ModelingMode

# SVG support (optional dependency)
try:
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPM
    HAS_SVG = True
except ImportError:
    HAS_SVG = False
    print("⚠️ [SVG] svglib/reportlab not installed. SVG support disabled.")


class LuminaImageProcessor:
    """
    Image processor class.
    
    Handles LUT loading, image processing, and color matching.
    """

    @staticmethod
    def _rgb_to_lab(rgb_array):
        """灏?RGB 鏁扮粍杞崲涓?CIELAB 绌洪棿锛堟劅鐭ュ潎鍖€鑹插僵绌洪棿锛夈€

        Args:
            rgb_array: numpy array, shape (N, 3) 鎴?(H, W, 3), dtype uint8

        Returns:
            numpy array, 鍚?shape, dtype float64, Lab 鍊
        """
        original_shape = rgb_array.shape
        if rgb_array.ndim == 2:
            rgb_3d = rgb_array.reshape(1, -1, 3).astype(np.uint8)
        else:
            rgb_3d = rgb_array.astype(np.uint8)
        bgr = cv2.cvtColor(rgb_3d, cv2.COLOR_RGB2BGR)
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64)
        if len(original_shape) == 2:
            return lab.reshape(original_shape)
        return lab

    def __init__(self, lut_path, color_mode):
        """
        Initialize image processor.
        
        Args:
            lut_path: LUT file path (.npy)
            color_mode: Color mode string (CMYW/RYBW/6-Color)
        """
        self.color_mode = color_mode
        self.lut_rgb = None
        self.lut_lab = None  # CIELAB 绌洪棿鐨?LUT 棰滆壊锛堢敤浜?KDTree 鍖归厤锛
        self.ref_stacks = None
        self.kdtree = None
        self.enable_cleanup = True  # 榛樿寮€鍚绔嬪儚绱犳竻鐞
        
        self._load_lut(lut_path)
    
    def _load_svg(self, svg_path, target_width_mm):
        """
        [Final Fix] Safe Padding + Dual-Pass Transparency Detection.
        """
        if not HAS_SVG:
            raise ImportError("Please install 'svglib' and 'reportlab'.")
        
        print(f"[SVG] Rasterizing: {svg_path}")
        drawing = svg2rlg(svg_path)
        x1, y1, x2, y2 = drawing.getBounds()
        raw_w, raw_h = x2 - x1, y2 - y1
        padding_x, padding_y = raw_w * 0.2, raw_h * 0.2
        drawing.translate(-x1 + padding_x, -y1 + padding_y)
        drawing.width, drawing.height = raw_w + (padding_x * 2), raw_h + (padding_y * 2)
        
        pixels_per_mm = 20.0
        target_width_px = int(target_width_mm * pixels_per_mm)
        scale_factor = target_width_px / raw_w if raw_w > 0 else 1.0
        drawing.scale(scale_factor, scale_factor)
        drawing.width, drawing.height = int(drawing.width * scale_factor), int(drawing.height * scale_factor)
        
        try:
            pil_white = renderPM.drawToPIL(drawing, bg=0xFFFFFF, configPIL={'transparent': False})
            arr_white = np.array(pil_white.convert('RGB'))
            pil_black = renderPM.drawToPIL(drawing, bg=0x000000, configPIL={'transparent': False})
            arr_black = np.array(pil_black.convert('RGB'))
            diff = np.abs(arr_white.astype(int) - arr_black.astype(int))
            alpha_mask = np.where(np.sum(diff, axis=2) < 10, 255, 0).astype(np.uint8)
            img_final = cv2.merge([cv2.split(arr_white)[0], cv2.split(arr_white)[1], cv2.split(arr_white)[2], alpha_mask])
            coords = cv2.findNonZero(alpha_mask)
            if coords is not None:
                x, y, w_rect, h_rect = cv2.boundingRect(coords)
                pad = 2
                img_final = img_final[max(0, y-pad):min(img_final.shape[0], y+h_rect+pad), max(0, x-pad):min(img_final.shape[1], x+w_rect+pad)]
            return img_final
        except Exception as e:
            print(f"[SVG] Dual-Pass failed: {e}")
            return np.array(renderPM.drawToPIL(drawing, bg=None, configPIL={'transparent': True}).convert('RGBA'))

    def _load_lut(self, lut_path):
        """Load and validate LUT file."""
        if lut_path.endswith('.npz'):
            try:
                data = np.load(lut_path)
                self.lut_rgb, self.ref_stacks = data['rgb'], data['stacks']
                self.lut_lab = self._rgb_to_lab(self.lut_rgb)
                self.kdtree = KDTree(self.lut_lab)
                print(f"鉁?Merged LUT loaded: {len(self.lut_rgb)} colors (.npz format, Lab KDTree)")
                return
            except Exception as e:
                raise ValueError(f"鉂?Merged LUT file corrupted: {e}")

        try:
            lut_grid = np.load(lut_path)
            if lut_grid.ndim == 1:
                measured_colors = lut_grid.reshape(-1, 3) if lut_grid.size % 3 == 0 else None
            elif lut_grid.ndim == 2:
                measured_colors = lut_grid[:, :3] if lut_grid.shape[1] in (3, 4) else None
            elif lut_grid.ndim == 3:
                measured_colors = lut_grid[:, :, :3].reshape(-1, 3) if lut_grid.shape[2] in (3, 4) else None
            
            if measured_colors is None: raise ValueError("Invalid LUT shape")
            if measured_colors.dtype != np.uint8:
                measured_colors = (measured_colors * 255).astype(np.uint8) if measured_colors.max() <= 1.0 else measured_colors.astype(np.uint8)
            total_colors = measured_colors.shape[0]
        except Exception as e:
            raise ValueError(f"鉂?LUT file corrupted: {e}")

        base_path, _ = os.path.splitext(lut_path)
        companion_stacks_path = base_path + "_stacks.npy"
        if os.path.exists(companion_stacks_path):
            try:
                companion_stacks = np.load(companion_stacks_path)
                if len(companion_stacks) == total_colors:
                    self.lut_rgb, self.ref_stacks = measured_colors, np.array(companion_stacks)
                    self.lut_lab = self._rgb_to_lab(self.lut_rgb)
                    self.kdtree = KDTree(self.lut_lab)
                    print(f"鉁?LUT loaded: {total_colors} colors (with companion stacks)")
                    return
            except: pass

        # Auto-detect modes
        valid_rgb, valid_stacks = [], []
        if self.color_mode in ("BW (Black & White)", "BW") or total_colors == 32:
            for i in range(min(32, total_colors)):
                temp, stack = i, []
                for _ in range(5): stack.append(temp % 2); temp //= 2
                valid_rgb.append(measured_colors[i]); valid_stacks.append(stack[::-1])
            self.lut_rgb, self.ref_stacks = np.array(valid_rgb), np.array(valid_stacks)
        elif "8-Color" in self.color_mode or total_colors == 2738:
            stacks_path = os.path.join(sys._MEIPASS, 'assets', 'smart_8color_stacks.npy') if getattr(sys, 'frozen', False) else 'assets/smart_8color_stacks.npy'
            smart_stacks = np.flip(np.load(stacks_path), axis=1)
            self.lut_rgb, self.ref_stacks = measured_colors[:len(smart_stacks)], smart_stacks[:len(measured_colors)]
        elif "6-Color" in self.color_mode or total_colors == 1296:
            from core.calibration import get_top_1296_colors
            smart_stacks = np.array([tuple(reversed(s)) for s in get_top_1296_colors()])
            self.lut_rgb, self.ref_stacks = measured_colors[:len(smart_stacks)], smart_stacks[:len(measured_colors)]
        elif self.color_mode == "Merged" or total_colors not in (32, 1024, 1296, 2738):
            npz_path = lut_path.rsplit('.', 1)[0] + '.npz'
            if os.path.exists(npz_path):
                try:
                    data = np.load(npz_path)
                    self.lut_rgb, self.ref_stacks = data['rgb'], data['stacks']
                    self.lut_lab = self._rgb_to_lab(self.lut_rgb)
                    self.kdtree = KDTree(self.lut_lab)
                    return
                except: pass
            self.lut_rgb, self.ref_stacks = measured_colors, np.zeros((total_colors, 5), dtype=np.int32)
        else: # 4-Color
            base_blue = np.array([30, 100, 200])
            for i in range(min(1024, total_colors)):
                temp, stack = i, []
                for _ in range(5): stack.append(temp % 4); temp //= 4
                if np.linalg.norm(measured_colors[i] - base_blue) < 60 and 3 not in stack: continue
                valid_rgb.append(measured_colors[i]); valid_stacks.append(stack[::-1])
            self.lut_rgb, self.ref_stacks = np.array(valid_rgb), np.array(valid_stacks)

        self.lut_lab = self._rgb_to_lab(self.lut_rgb)
        self.kdtree = KDTree(self.lut_lab)

    def process_image(self, image_path, target_width_mm, modeling_mode, quantize_colors, auto_bg, bg_tol, blur_kernel=0, smooth_sigma=10):
        """Main image processing method."""
        is_svg = image_path.lower().endswith('.svg')
        if is_svg:
            img = Image.fromarray(self._load_svg(image_path, target_width_mm))
            blur_kernel, smooth_sigma, pixel_to_mm_scale = 0, 0, 0.05
            target_w, target_h = img.size
        else:
            img = Image.open(image_path).convert('RGBA')
            if modeling_mode == ModelingMode.HIGH_FIDELITY:
                PIXELS_PER_MM = 10
                target_w, pixel_to_mm_scale = int(target_width_mm * PIXELS_PER_MM), 1.0 / PIXELS_PER_MM
            else:
                target_w, pixel_to_mm_scale = int(target_width_mm / PrinterConfig.NOZZLE_WIDTH), PrinterConfig.NOZZLE_WIDTH
            target_h = int(target_w * img.height / img.width)

        img = img.resize((target_w, target_h), Image.Resampling.NEAREST)
        img_arr = np.array(img)
        rgb_arr, alpha_arr = img_arr[:, :, :3], img_arr[:, :, 3]
        mask_transparent = alpha_arr < 10

        if modeling_mode == ModelingMode.HIGH_FIDELITY:
            matched_rgb, material_matrix, bg_reference, debug_data = self._process_high_fidelity_mode(rgb_arr, target_h, target_w, quantize_colors, blur_kernel, smooth_sigma)
        else:
            matched_rgb, material_matrix, bg_reference = self._process_pixel_mode(rgb_arr, target_h, target_w)
            debug_data = None
        
        if modeling_mode == ModelingMode.HIGH_FIDELITY and self.enable_cleanup:
            try:
                from core.isolated_pixel_cleanup import cleanup_isolated_pixels
                matched_rgb, material_matrix = cleanup_isolated_pixels(material_matrix, matched_rgb, self.lut_rgb, self.ref_stacks)
            except: pass
        
        if auto_bg:
            mask_transparent = np.logical_or(mask_transparent, np.sum(np.abs(bg_reference - bg_reference[0,0]), axis=-1) < bg_tol)
        
        material_matrix[mask_transparent] = -1
        return {'matched_rgb': matched_rgb, 'material_matrix': material_matrix, 'mask_solid': ~mask_transparent, 'dimensions': (target_w, target_h), 'pixel_scale': pixel_to_mm_scale, 'mode_info': {'mode': modeling_mode}, 'debug_data': debug_data}

    def _process_high_fidelity_mode(self, rgb_arr, target_h, target_w, quantize_colors, blur_kernel, smooth_sigma):
        """High-fidelity processing with K-Means."""
        rgb_processed = cv2.bilateralFilter(rgb_arr.astype(np.uint8), d=9, sigmaColor=smooth_sigma, sigmaSpace=smooth_sigma) if smooth_sigma > 0 else rgb_arr.astype(np.uint8)
        if blur_kernel > 0: rgb_processed = cv2.medianBlur(rgb_processed, blur_kernel if blur_kernel % 2 == 1 else blur_kernel + 1)
        
        h, w = rgb_processed.shape[:2]
        if h * w > 500_000:
            scale = np.sqrt((h * w) / 500_000)
            rgb_small = cv2.resize(rgb_processed, (int(w/scale), int(h/scale)), interpolation=cv2.INTER_AREA)
            _, _, centers = cv2.kmeans(rgb_small.reshape(-1, 3).astype(np.float32), quantize_colors, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5), 5, cv2.KMEANS_PP_CENTERS)
            _, labels = KDTree(centers).query(rgb_processed.reshape(-1, 3).astype(np.float32))
            quantized_image = centers.astype(np.uint8)[labels].reshape(h, w, 3)
        else:
            _, labels, centers = cv2.kmeans(rgb_processed.reshape(-1, 3).astype(np.float32), quantize_colors, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2), 10, cv2.KMEANS_PP_CENTERS)
            quantized_image = centers.astype(np.uint8)[labels.flatten()].reshape(h, w, 3)
        
        quantized_image = cv2.medianBlur(quantized_image, 3)
        unique_colors = np.unique(quantized_image.reshape(-1, 3), axis=0)
        _, unique_indices = self.kdtree.query(self._rgb_to_lab(unique_colors))
        
        codes = unique_colors[:, 0].astype(np.int32) * 65536 + unique_colors[:, 1].astype(np.int32) * 256 + unique_colors[:, 2].astype(np.int32)
        sort_idx = np.argsort(codes)
        sorted_codes, sorted_indices = codes[sort_idx], unique_indices[sort_idx]
        
        pixel_codes = quantized_image.reshape(-1, 3).astype(np.int32) @ np.array([65536, 256, 1])
        lut_idx = sorted_indices[np.searchsorted(sorted_codes, pixel_codes)]
        
        return self.lut_rgb[lut_idx].reshape(target_h, target_w, 3), self.ref_stacks[lut_idx].reshape(target_h, target_w, PrinterConfig.COLOR_LAYERS), quantized_image, {'quantized_image': quantized_image, 'num_colors': len(unique_colors), 'bilateral_filtered': rgb_processed}

    def _process_pixel_mode(self, rgb_arr, target_h, target_w):
        """Pixel art mode processing."""
        _, indices = self.kdtree.query(self._rgb_to_lab(rgb_arr.reshape(-1, 3)))
        return self.lut_rgb[indices].reshape(target_h, target_w, 3), self.ref_stacks[indices].reshape(target_h, target_w, PrinterConfig.COLOR_LAYERS), rgb_arr

    def _extract_wireframe_mask(self, rgb_arr, target_w, pixel_scale, wire_width_mm=0.6):
        """Extract cloisonn茅 wireframe mask."""
        gray = cv2.GaussianBlur(cv2.cvtColor(rgb_arr.astype(np.uint8), cv2.COLOR_RGB2GRAY), (3, 3), 0)
        otsu, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        edges = cv2.Canny(gray, int(otsu * 0.4), int(otsu * 0.8))
        w_px = max(1, int(round(wire_width_mm / pixel_scale)))
        return cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (w_px|1, w_px|1)), iterations=1) > 0
