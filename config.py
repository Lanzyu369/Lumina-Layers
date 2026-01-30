"""
Lumina Studio - Configuration Module
Contains all configuration classes, constants, and internationalization texts
"""

import os
import tempfile


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                           OUTPUT DIRECTORY                                    ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

# 输出目录：项目根目录下的 output 文件夹（不再写入 C 盘临时目录）
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                           SHARED CONFIGURATION                                ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

class PrinterConfig:
    """Physical printer parameters."""
    LAYER_HEIGHT: float = 0.08
    NOZZLE_WIDTH: float = 0.42
    COLOR_LAYERS: int = 5
    BACKING_MM: float = 1.6
    SHRINK_OFFSET: float = 0.02


class ThinModeConfig:
    """CMYK+W mode configuration. Total 341 swatches."""
    GRID_W: int = 19  # 19 columns
    GRID_H: int = 18  # 18 rows
    MAX_LAYERS: int = 4  # 0-4 layers variable
    BASE_MM: float = 1.0  # 1.0mm white base
    TOTAL_SWATCHES: int = 341  # 1 + 4 + 16 + 64 + 256 = 341


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                           INTERNATIONALIZATION                                ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

class I18N:
    """Internationalization support for Chinese and English."""

    TEXTS = {
        # Header
        'app_title': {'zh': '✨ Lumina Studio', 'en': '✨ Lumina Studio'},
        'app_subtitle': {'zh': '多材料3D打印色彩系统', 'en': 'Multi-Material 3D Print Color System'},

        # Stats
        'stats_total': {'zh': '📊 累计生成:', 'en': '📊 Total Generated:'},
        'stats_calibrations': {'zh': '校准板', 'en': 'Calibrations'},
        'stats_extractions': {'zh': '颜色提取', 'en': 'Extractions'},
        'stats_conversions': {'zh': '模型转换', 'en': 'Conversions'},

        # Tabs
        'tab_calibration': {'zh': '📐 校准板生成', 'en': '📐 Calibration'},
        'tab_extractor': {'zh': '🎨 颜色提取', 'en': '🎨 Color Extractor'},
        'tab_converter': {'zh': '💎 图像转换', 'en': '💎 Image Converter'},
        'tab_about': {'zh': 'ℹ️ 关于', 'en': 'ℹ️ About'},

        # Tab 1: Calibration
        'cal_title': {'zh': '### 第一步：生成校准板', 'en': '### Step 1: Generate Calibration Board'},
        'cal_desc': {'zh': '生成1024种颜色的校准板，打印后用于提取打印机的实际色彩数据。',
                     'en': 'Generate a 1024-color calibration board. Print it to extract your printer\'s actual color data.'},
        'cal_params': {'zh': '#### ⚙️ 参数设置', 'en': '#### ⚙️ Parameters'},
        'cal_mode': {'zh': '色彩模式', 'en': 'Color Mode'},
        'cal_mode_cmyw': {'zh': 'CMYW (青/品红/黄)', 'en': 'CMYW (Cyan/Magenta/Yellow)'},
        'cal_mode_rybw': {'zh': 'RYBW (红/黄/蓝)', 'en': 'RYBW (Red/Yellow/Blue)'},
        'cal_mode_cmykw': {'zh': 'CMYK+W', 'en': 'CMYK+W'},
        'cal_block_size': {'zh': '色块尺寸 (mm)', 'en': 'Block Size (mm)'},
        'cal_gap': {'zh': '间隙 (mm)', 'en': 'Gap (mm)'},
        'cal_backing': {'zh': '底板颜色', 'en': 'Backing Color'},
        'cal_generate': {'zh': '🚀 生成校准板', 'en': '🚀 Generate'},
        'cal_status': {'zh': '状态', 'en': 'Status'},
        'cal_preview': {'zh': '#### 👁️ 预览', 'en': '#### 👁️ Preview'},
        'cal_download': {'zh': '下载 3MF 文件', 'en': 'Download 3MF'},
        'cal_success': {'zh': '✅ 校准板已生成！对象名称:', 'en': '✅ Calibration board generated! Object names:'},

        # Tab 2: Extractor
        'ext_title': {'zh': '### 第二步：提取颜色数据', 'en': '### Step 2: Extract Color Data'},
        'ext_desc': {'zh': '拍摄打印好的校准板照片，提取真实的色彩数据生成 LUT 文件。',
                     'en': 'Take a photo of your printed calibration board to extract real color data and generate a LUT file.'},
        'ext_upload': {'zh': '#### 📸 上传照片', 'en': '#### 📸 Upload Photo'},
        'ext_color_mode': {'zh': '🎨 校准板的色彩模式', 'en': '🎨 Calibration Board Color Mode'},
        'ext_photo': {'zh': '校准板照片', 'en': 'Calibration Photo'},
        'ext_rotate': {'zh': '↺ 旋转', 'en': '↺ Rotate'},
        'ext_reset': {'zh': '🗑️ 重置点位', 'en': '🗑️ Reset Points'},
        'ext_correction': {'zh': '#### 🔧 校正参数', 'en': '#### 🔧 Correction'},
        'ext_wb': {'zh': '自动白平衡', 'en': 'Auto White Balance'},
        'ext_vignette': {'zh': '暗角校正', 'en': 'Vignette Fix'},
        'ext_zoom': {'zh': '缩放', 'en': 'Zoom'},
        'ext_distortion': {'zh': '畸变', 'en': 'Distortion'},
        'ext_offset_x': {'zh': 'X偏移', 'en': 'Offset X'},
        'ext_offset_y': {'zh': 'Y偏移', 'en': 'Offset Y'},
        'ext_extract': {'zh': '🚀 提取颜色', 'en': '🚀 Extract Colors'},
        'ext_hint_white': {'zh': '#### 👉 点击: **白色色块 (左上角)**', 'en': '#### 👉 Click: **White Block (Top-Left)**'},
        'ext_hint_done': {'zh': '#### ✅ 定位完成，可以提取颜色了！', 'en': '#### ✅ Positioning complete, ready to extract!'},
        'ext_sampling': {'zh': '#### 📍 采样预览', 'en': '#### 📍 Sampling Preview'},
        'ext_reference': {'zh': '#### 🎯 参考对照', 'en': '#### 🎯 Reference'},
        'ext_result': {'zh': '#### 📊 提取结果 (点击修正)', 'en': '#### 📊 Result (Click to Fix)'},
        'ext_manual_fix': {'zh': '#### 🛠️ 手动修正', 'en': '#### 🛠️ Manual Fix'},
        'ext_click_cell': {'zh': '点击左侧色块查看...', 'en': 'Click a cell on the left...'},
        'ext_override': {'zh': '替换颜色', 'en': 'Override Color'},
        'ext_apply': {'zh': '🔧 应用修正', 'en': '🔧 Apply Fix'},
        'ext_download_npy': {'zh': '下载 .npy', 'en': 'Download .npy'},
        'ext_success': {'zh': '✅ 提取完成！LUT已保存', 'en': '✅ Extraction complete! LUT saved'},
        'ext_no_image': {'zh': '❌ 请先上传图片', 'en': '❌ Please upload an image first'},
        'ext_need_4_points': {'zh': '❌ 请点击4个角点', 'en': '❌ Please click 4 corner points'},

        # Tab 3: Converter
        'conv_title': {'zh': '### 第三步：转换图像', 'en': '### Step 3: Convert Image'},
        'conv_desc': {'zh': '使用校准数据将图像转换为多层 3D 模型，实现精准色彩还原。',
                      'en': 'Convert images to multi-layer 3D models using calibration data for accurate color reproduction.'},
        'conv_input': {'zh': '#### 📁 输入文件', 'en': '#### 📁 Input Files'},
        'conv_lut': {'zh': '1. 校准数据 (.npy)', 'en': '1. Calibration Data (.npy)'},
        'conv_image': {'zh': '2. 输入图像', 'en': '2. Input Image'},
        'conv_params': {'zh': '#### ⚙️ 参数设置', 'en': '#### ⚙️ Parameters'},
        'conv_color_mode': {'zh': '🎨 色彩模式（需与校准板一致）', 'en': '🎨 Color Mode (must match calibration)'},
        'conv_structure': {'zh': '结构类型', 'en': 'Structure Type'},
        'conv_double': {'zh': '双面 (钥匙扣)', 'en': 'Double-sided (Keychain)'},
        'conv_single': {'zh': '单面 (浮雕)', 'en': 'Single-sided (Relief)'},
        'conv_auto_bg': {'zh': '自动移除背景', 'en': 'Auto Background Removal'},
        'conv_tolerance': {'zh': '背景容差', 'en': 'Background Tolerance'},
        'conv_width': {'zh': '目标宽度 (mm)', 'en': 'Target Width (mm)'},
        'conv_thickness': {'zh': '背板厚度 (mm)', 'en': 'Backing Thickness (mm)'},
        'conv_generate': {'zh': '🚀 生成模型', 'en': '🚀 Generate Model'},
        'conv_3d_preview': {'zh': '#### 🎮 3D 预览（可拖拽旋转/滚轮缩放）', 'en': '#### 🎮 3D Preview (Drag to rotate / Scroll to zoom)'},
        'conv_color_preview': {'zh': '#### 🎨 色彩预览', 'en': '#### 🎨 Color Preview'},
        'conv_download': {'zh': '#### 📁 下载', 'en': '#### 📁 Download'},
        'conv_download_3mf': {'zh': '下载 3MF 文件', 'en': 'Download 3MF'},
        'conv_success': {'zh': '✅ 转换完成！分辨率:', 'en': '✅ Conversion complete! Resolution:'},
        'conv_no_image': {'zh': '❌ 请上传图片', 'en': '❌ Please upload an image'},
        'conv_no_lut': {'zh': '⚠️ 请上传 .npy 校准文件！', 'en': '⚠️ Please upload a .npy calibration file!'},

        # Footer
        'footer_tip': {'zh': '💡 提示: 使用高质量的PLA/PETG透光材料可获得最佳效果',
                       'en': '💡 Tip: Use high-quality translucent PLA/PETG for best results'},

        # Language
        'lang_label': {'zh': '🌐 语言', 'en': '🌐 Language'},
        'lang_zh': {'zh': '中文', 'en': '中文'},
        'lang_en': {'zh': 'English', 'en': 'English'},
    }

    @staticmethod
    def get(key: str, lang: str = 'zh') -> str:
        """Get translated text for a key."""
        if key in I18N.TEXTS:
            return I18N.TEXTS[key].get(lang, I18N.TEXTS[key].get('zh', key))
        return key


class ColorSystem:
    """Color model definitions for CMYW, RYBW, and CMYK_W (341 mode)."""

    CMYW = {
        'name': 'CMYW',
        'slots': ["White", "Cyan", "Magenta", "Yellow"],
        'preview': {
            0: [255, 255, 255, 255],
            1: [0, 134, 214, 255],
            2: [236, 0, 140, 255],
            3: [244, 238, 42, 255]
        },
        'map': {"White": 0, "Cyan": 1, "Magenta": 2, "Yellow": 3},
        # Corner point order: TL, TR, BR, BL
        'corner_labels': ["白色 (左上)", "青色 (右上)", "品红 (右下)", "黄色 (左下)"],
        'corner_labels_en': ["White (TL)", "Cyan (TR)", "Magenta (BR)", "Yellow (BL)"],
        'is_thin_mode': False,
        'color_layers': 5
    }

    RYBW = {
        'name': 'RYBW',
        'slots': ["White", "Red", "Yellow", "Blue"],
        'preview': {
            0: [255, 255, 255, 255],
            1: [220, 20, 60, 255],
            2: [255, 230, 0, 255],
            3: [0, 100, 240, 255]
        },
        'map': {"White": 0, "Red": 1, "Yellow": 2, "Blue": 3},
        # Corner point order: TL, TR, BR, BL
        'corner_labels': ["白色 (左上)", "红色 (右上)", "蓝色 (右下)", "黄色 (左下)"],
        'corner_labels_en': ["White (TL)", "Red (TR)", "Blue (BR)", "Yellow (BL)"],
        'is_thin_mode': False,
        'color_layers': 5
    }

    # CMYK+W mode (thin). Total 341 swatches.
    # 5 slots: White(base) + Cyan, Magenta, Yellow, Black (color layers)
    # Note: Corner labels are for VIEWING FROM BOTTOM (print surface)
    # The printed calibration board is viewed from the bottom/color side
    CMYK_W = {
        'name': 'CMYK_W',
        'slots': ["White", "Cyan", "Magenta", "Yellow", "Black"],
        'preview': {
            0: [255, 255, 255, 255],  # White (Base)
            1: [0, 134, 214, 255],     # Cyan
            2: [236, 0, 140, 255],     # Magenta
            3: [244, 238, 42, 255],    # Yellow
            4: [30, 30, 30, 255]       # Black
        },
        'map': {"White": 0, "Cyan": 1, "Magenta": 2, "Yellow": 3, "Black": 4},
        # 定位点顺序: TL, TR, BR, BL (从底面/外观面观看)
        # 打印后翻转观看: 左上=黄, 右上=品红, 右下=青, 左下=白
        'corner_labels': ["黄色 (左上)", "品红 (右上)", "青色 (右下)", "白色 (左下)"],
        'corner_labels_en': ["Yellow (TL)", "Magenta (TR)", "Cyan (BR)", "White (BL)"],
        'is_thin_mode': True,
        'color_layers': 4,  # Variable 0-4 layers
        'grid_w': 19,
        'grid_h': 18,
        'total_swatches': 341,
        'base_mm': 1.0
    }

    @staticmethod
    def get(mode: str):
        if "CMYK_W" in mode or "CMYK+W" in mode or "341" in mode:
            return ColorSystem.CMYK_W
        elif "CMYW" in mode:
            return ColorSystem.CMYW
        else:
            return ColorSystem.RYBW
    
    @staticmethod
    def is_thin_mode(mode: str) -> bool:
        """Check if the mode is thin mode (CMYK+W, 341 swatches)."""
        return "CMYK_W" in mode or "CMYK+W" in mode or "341" in mode


# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                           GLOBAL CONSTANTS                                    ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

# Extractor constants (1024 mode: 32x32 data grid + 2 padding = 34x34 physical)
PHYSICAL_GRID_SIZE = 34
DATA_GRID_SIZE = 32
DST_SIZE = 1000
CELL_SIZE = DST_SIZE / PHYSICAL_GRID_SIZE
LUT_FILE_PATH = os.path.join(OUTPUT_DIR, "lumina_lut.npy")

# Thin Mode (341 swatches) extractor constants
# 19x18 data grid + 2 padding = 21x20 physical grid
THIN_PHYSICAL_GRID_W = 21  # 19 + 2 padding
THIN_PHYSICAL_GRID_H = 20  # 18 + 2 padding
THIN_DATA_GRID_W = 19
THIN_DATA_GRID_H = 18
THIN_DST_SIZE_W = 1000
THIN_DST_SIZE_H = int(1000 * THIN_PHYSICAL_GRID_H / THIN_PHYSICAL_GRID_W)
THIN_CELL_SIZE_W = THIN_DST_SIZE_W / THIN_PHYSICAL_GRID_W
THIN_CELL_SIZE_H = THIN_DST_SIZE_H / THIN_PHYSICAL_GRID_H
THIN_LUT_FILE_PATH = os.path.join(OUTPUT_DIR, "lumina_lut_341.npy")

# Converter constants
PREVIEW_SCALE = 2  # 固定预览缩放倍数
PREVIEW_MARGIN = 30  # 预览图边距（显示坐标轴用）
