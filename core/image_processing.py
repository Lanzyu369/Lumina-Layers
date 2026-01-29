"""
Lumina Studio - Image Processing Core
图像处理核心模块 - 负责图像加载、预处理、色彩量化和匹配
"""

import numpy as np
import cv2
from PIL import Image
from scipy.spatial import KDTree

from config import PrinterConfig, ThinModeConfig, ColorSystem
from config import THIN_DATA_GRID_W, THIN_DATA_GRID_H


class LuminaImageProcessor:
    """
    图像处理器类
    负责加载LUT、处理图像、执行色彩匹配
    """
    
    def __init__(self, lut_path, color_mode):
        """
        初始化图像处理器
        
        Args:
            lut_path: LUT文件路径 (.npy)
            color_mode: 色彩模式字符串 (CMYW/RYBW/W+CMYK)
        """
        self.color_mode = color_mode
        self.is_thin_mode = ColorSystem.is_thin_mode(color_mode)
        self.lut_rgb = None
        self.ref_stacks = None
        self.ref_seq_lengths = None  # For 341 mode
        self.kdtree = None
        
        # 加载并验证LUT
        if self.is_thin_mode:
            self._load_lut_341(lut_path)
        else:
            self._load_lut_1024(lut_path)
    
    def _load_lut_1024(self, lut_path):
        """加载并验证1024色LUT文件"""
        try:
            lut_grid = np.load(lut_path)
            measured_colors = lut_grid.reshape(-1, 3)
        except Exception as e:
            raise ValueError(f"❌ LUT文件损坏: {e}")
        
        valid_rgb, valid_stacks = [], []
        base_blue = np.array([30, 100, 200])
        dropped = 0
        
        # 过滤异常点
        for i in range(1024):
            digits = []
            temp = i
            for _ in range(5):
                digits.append(temp % 4)
                temp //= 4
            stack = digits[::-1]
            
            real_rgb = measured_colors[i]
            dist = np.linalg.norm(real_rgb - base_blue)
            
            # 过滤掉不含蓝色但接近蓝色的异常点
            if dist < 60 and 3 not in stack:
                dropped += 1
                continue
            
            valid_rgb.append(real_rgb)
            valid_stacks.append(stack)
        
        self.lut_rgb = np.array(valid_rgb)
        self.ref_stacks = np.array(valid_stacks)
        self.ref_seq_lengths = np.full(len(valid_stacks), 5, dtype=np.int32)  # All 5 layers
        self.kdtree = KDTree(self.lut_rgb)
        
        print(f"✅ LUT已加载 (1024色模式, 过滤了{dropped}个异常点)")
    
    def _load_lut_341(self, lut_path):
        """加载并验证341色LUT文件"""
        from core.calibration import generate_341_sequences
        
        try:
            lut_grid = np.load(lut_path)
            # 341 mode uses 19x18 grid
            if lut_grid.shape[0] == THIN_DATA_GRID_H and lut_grid.shape[1] == THIN_DATA_GRID_W:
                measured_colors = lut_grid.reshape(-1, 3)
            else:
                measured_colors = lut_grid.reshape(-1, 3)
        except Exception as e:
            raise ValueError(f"❌ LUT文件损坏: {e}")
        
        # Generate reference sequences
        sequences = generate_341_sequences()
        
        valid_rgb, valid_stacks, valid_lengths = [], [], []
        
        num_colors = min(len(measured_colors), 341)
        for i in range(num_colors):
            seq = sequences[i]
            real_rgb = measured_colors[i]
            
            # Pad sequence to 4 elements for consistent array shape
            padded_seq = seq + [-1] * (4 - len(seq))  # Pad with -1
            
            valid_rgb.append(real_rgb)
            valid_stacks.append(padded_seq)
            valid_lengths.append(len(seq))
        
        self.lut_rgb = np.array(valid_rgb)
        self.ref_stacks = np.array(valid_stacks)
        self.ref_seq_lengths = np.array(valid_lengths, dtype=np.int32)
        self.kdtree = KDTree(self.lut_rgb)
        
        print(f"✅ LUT已加载 (341色模式, {num_colors}个颜色)")
    
    def process_image(self, image_path, target_width_mm, modeling_mode,
                     quantize_colors, auto_bg, bg_tol):
        """
        处理图像的主方法
        
        Args:
            image_path: 图像文件路径
            target_width_mm: 目标宽度(毫米)
            modeling_mode: 建模模式 ("vector", "woodblock", "voxel")
            quantize_colors: K-Means量化颜色数量
            auto_bg: 是否自动移除背景
            bg_tol: 背景容差
        
        Returns:
            dict: 包含处理结果的字典
                - matched_rgb: (H, W, 3) 匹配后的RGB数组
                - material_matrix: (H, W, Layers) 材质索引矩阵
                - seq_lengths: (H, W) 每个像素的序列长度 (341模式)
                - mask_solid: (H, W) 实体掩码
                - dimensions: (width, height) 像素尺寸
                - pixel_scale: mm/pixel 比例
                - mode_info: 模式信息字典
        """
        # 标准化建模模式
        mode_str = str(modeling_mode).lower()
        use_vector_mode = "vector" in mode_str or "矢量" in mode_str
        use_woodblock_mode = "woodblock" in mode_str or "版画" in mode_str
        
        if use_woodblock_mode:
            mode_name = "Woodblock"
        elif use_vector_mode:
            mode_name = "Vector"
        else:
            mode_name = "Voxel"
        
        # Add thin mode indicator
        if self.is_thin_mode:
            mode_name += " (341)"
        
        print(f"[IMAGE_PROCESSOR] Mode: {mode_name}, Thin: {self.is_thin_mode}")
        
        # 加载图像
        img = Image.open(image_path).convert('RGBA')
        
        # 计算目标分辨率
        if use_vector_mode or use_woodblock_mode:
            # 高精度模式: 10 pixels/mm
            PIXELS_PER_MM = 10
            target_w = int(target_width_mm * PIXELS_PER_MM)
            pixel_to_mm_scale = 1.0 / PIXELS_PER_MM  # 0.1 mm per pixel
            print(f"[IMAGE_PROCESSOR] High-res mode: {PIXELS_PER_MM} px/mm")
        else:
            # 像素模式: 基于喷嘴宽度
            target_w = int(target_width_mm / PrinterConfig.NOZZLE_WIDTH)
            pixel_to_mm_scale = PrinterConfig.NOZZLE_WIDTH
            print(f"[IMAGE_PROCESSOR] Voxel mode: {1.0/pixel_to_mm_scale:.2f} px/mm")
        
        target_h = int(target_w * img.height / img.width)
        print(f"[IMAGE_PROCESSOR] Target: {target_w}×{target_h}px ({target_w*pixel_to_mm_scale:.1f}×{target_h*pixel_to_mm_scale:.1f}mm)")
        
        # Resize图像
        if use_vector_mode or use_woodblock_mode:
            img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        else:
            img = img.resize((target_w, target_h), Image.Resampling.NEAREST)
        
        img_arr = np.array(img)
        rgb_arr = img_arr[:, :, :3]
        alpha_arr = img_arr[:, :, 3]
        
        # 色彩处理和匹配
        if use_vector_mode or use_woodblock_mode:
            matched_rgb, material_matrix, seq_lengths, bg_reference = self._process_vector_mode(
                rgb_arr, target_h, target_w, quantize_colors
            )
        else:
            matched_rgb, material_matrix, seq_lengths, bg_reference = self._process_voxel_mode(
                rgb_arr, target_h, target_w
            )
        
        # 背景移除
        mask_transparent = alpha_arr < 10
        if auto_bg:
            bg_color = bg_reference[0, 0]
            diff = np.sum(np.abs(bg_reference - bg_color), axis=-1)
            mask_transparent = np.logical_or(mask_transparent, diff < bg_tol)
        
        material_matrix[mask_transparent] = -1
        mask_solid = ~mask_transparent
        
        return {
            'matched_rgb': matched_rgb,
            'material_matrix': material_matrix,
            'seq_lengths': seq_lengths,
            'mask_solid': mask_solid,
            'dimensions': (target_w, target_h),
            'pixel_scale': pixel_to_mm_scale,
            'is_thin_mode': self.is_thin_mode,
            'mode_info': {
                'name': mode_name,
                'use_vector': use_vector_mode,
                'use_woodblock': use_woodblock_mode,
                'is_thin': self.is_thin_mode
            }
        }

    
    def _process_vector_mode(self, rgb_arr, target_h, target_w, quantize_colors):
        """
        矢量/版画模式的图像处理
        包含双边滤波、中值滤波、K-Means量化和色彩匹配
        """
        print(f"[IMAGE_PROCESSOR] Applying bilateral filter...")
        rgb_denoised = cv2.bilateralFilter(
            rgb_arr.astype(np.uint8), 
            d=5, 
            sigmaColor=50, 
            sigmaSpace=50
        )
        
        print(f"[IMAGE_PROCESSOR] Applying median blur...")
        rgb_denoised = cv2.medianBlur(rgb_denoised, 7)
        
        print(f"[IMAGE_PROCESSOR] K-Means quantization to {quantize_colors} colors...")
        h, w = rgb_denoised.shape[:2]
        pixels = rgb_denoised.reshape(-1, 3).astype(np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
        flags = cv2.KMEANS_PP_CENTERS
        
        _, labels, centers = cv2.kmeans(
            pixels, quantize_colors, None, criteria, 10, flags
        )
        
        centers = centers.astype(np.uint8)
        quantized_pixels = centers[labels.flatten()]
        quantized_image = quantized_pixels.reshape(h, w, 3)
        
        print(f"[IMAGE_PROCESSOR] Quantization complete!")
        
        # 找到唯一颜色
        unique_colors = np.unique(quantized_image.reshape(-1, 3), axis=0)
        print(f"[IMAGE_PROCESSOR] Found {len(unique_colors)} unique colors")
        
        # 匹配到LUT
        print(f"[IMAGE_PROCESSOR] Matching colors to LUT...")
        _, unique_indices = self.kdtree.query(unique_colors.astype(float))
        
        # 建立颜色映射
        color_to_stack = {}
        color_to_rgb = {}
        color_to_length = {}
        for i, color in enumerate(unique_colors):
            color_key = tuple(color)
            color_to_stack[color_key] = self.ref_stacks[unique_indices[i]]
            color_to_rgb[color_key] = self.lut_rgb[unique_indices[i]]
            color_to_length[color_key] = self.ref_seq_lengths[unique_indices[i]]
        
        # Determine layer count based on mode
        if self.is_thin_mode:
            max_layers = ThinModeConfig.MAX_LAYERS  # 4 for 341 mode
        else:
            max_layers = PrinterConfig.COLOR_LAYERS  # 5 for 1024 mode
        
        # 映射回完整图像
        print(f"[IMAGE_PROCESSOR] Mapping to full image...")
        matched_rgb = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        material_matrix = np.zeros((target_h, target_w, max_layers), dtype=int)
        seq_lengths = np.zeros((target_h, target_w), dtype=np.int32)
        
        for y in range(target_h):
            for x in range(target_w):
                color_key = tuple(quantized_image[y, x])
                matched_rgb[y, x] = color_to_rgb[color_key]
                material_matrix[y, x] = color_to_stack[color_key][:max_layers]
                seq_lengths[y, x] = color_to_length[color_key]
        
        print(f"[IMAGE_PROCESSOR] Color matching complete!")
        
        return matched_rgb, material_matrix, seq_lengths, quantized_image
    
    def _process_voxel_mode(self, rgb_arr, target_h, target_w):
        """
        像素模式的图像处理
        直接进行像素级色彩匹配，无平滑处理
        """
        print(f"[IMAGE_PROCESSOR] Direct pixel-level matching (Voxel mode)...")
        
        flat_rgb = rgb_arr.reshape(-1, 3)
        _, indices = self.kdtree.query(flat_rgb)
        
        # Determine layer count based on mode
        if self.is_thin_mode:
            max_layers = ThinModeConfig.MAX_LAYERS  # 4 for 341 mode
        else:
            max_layers = PrinterConfig.COLOR_LAYERS  # 5 for 1024 mode
        
        matched_rgb = self.lut_rgb[indices].reshape(target_h, target_w, 3)
        
        # Handle stacks with proper shape
        stacks = self.ref_stacks[indices]
        material_matrix = stacks[:, :max_layers].reshape(target_h, target_w, max_layers)
        
        # Get sequence lengths
        seq_lengths = self.ref_seq_lengths[indices].reshape(target_h, target_w)
        
        print(f"[IMAGE_PROCESSOR] Direct matching complete!")
        
        return matched_rgb, material_matrix, seq_lengths, rgb_arr
