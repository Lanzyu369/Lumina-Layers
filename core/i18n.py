"""
Lumina Studio - Internationalization Module
Internationalization module - Complete Chinese-English translation dictionary
"""


class I18n:
    """
    Internationalization management class
    Provides Chinese-English translation and language switching functionality
    """
    
    # Complete translation dictionary
    TEXTS = {
        # ==================== Application Title and Header ====================
        'app_title': {
            'zh': '✨ Lumina Studio',
            'en': '✨ Lumina Studio'
        },
        'app_subtitle': {
            'zh': '多材料3D打印色彩系统 | v1.4.2',
            'en': 'Multi-Material 3D Print Color System | v1.4.2'
        },
        'lang_btn_zh': {
            'zh': '🌐 中文',
            'en': '🌐 中文'
        },
        'lang_btn_en': {
            'zh': '🌐 English',
            'en': '🌐 English'
        },
        
        # ==================== Stats Bar ====================
        'stats_total': {
            'zh': '📊 累计生成',
            'en': '📊 Total Generated'
        },
        'stats_calibrations': {
            'zh': '校准板',
            'en': 'Calibrations'
        },
        'stats_extractions': {
            'zh': '颜色提取',
            'en': 'Extractions'
        },
        'stats_conversions': {
            'zh': '模型转换',
            'en': 'Conversions'
        },
        
        # ==================== Tab Titles ====================
        'tab_converter': {
            'zh': '💎 图像转换',
            'en': '💎 Image Converter'
        },
        'tab_calibration': {
            'zh': '📐 校准板生成',
            'en': '📐 Calibration'
        },
        'tab_extractor': {
            'zh': '🎨 颜色提取',
            'en': '🎨 Color Extractor'
        },
        'tab_about': {
            'zh': 'ℹ️ 关于',
            'en': 'ℹ️ About'
        },
        
        # ==================== Converter Tab ====================
        'conv_title': {
            'zh': '### 第一步：转换图像',
            'en': '### Step 1: Convert Image'
        },
        'conv_desc': {
            'zh': '**两种建模模式**：高保真（RLE无缝拼接）、像素艺术（方块风格）\n\n**流程**: 上传LUT和图像 → 选择建模模式 → 调整色彩细节 → 预览 → 生成',
            'en': '**Two Modeling Modes**: High-Fidelity (RLE seamless) and Pixel Art (blocky style)\n\n**Workflow**: Upload LUT & Image → Select Mode → Adjust Color Detail → Preview → Generate'
        },
        'conv_input_section': {
            'zh': '#### 📁 输入',
            'en': '#### 📁 Input'
        },
        'conv_lut_title': {
            'zh': '**校准数据 (.npy)**',
            'en': '**Calibration Data (.npy)**'
        },
        'conv_lut_dropdown': {
            'zh': '选择预设',
            'en': 'Select Preset'
        },
        'conv_lut_info': {
            'zh': '从预设库中选择LUT',
            'en': 'Select from library'
        },
        'conv_lut_status_default': {
            'zh': '💡 拖放.npy文件自动添加',
            'en': '💡 Drop .npy to add'
        },
        'conv_lut_status_selected': {
            'zh': '✅ 已选择',
            'en': '✅ Selected'
        },
        'conv_lut_status_saved': {
            'zh': '✅ LUT已保存',
            'en': '✅ LUT saved'
        },
        'conv_lut_status_error': {
            'zh': '❌ 文件不存在',
            'en': '❌ File not found'
        },
        'conv_image_label': {
            'zh': '输入图像',
            'en': 'Input Image'
        },
        'conv_params_section': {
            'zh': '#### ⚙️ 参数',
            'en': '#### ⚙️ Parameters'
        },
        'conv_color_mode': {
            'zh': '色彩模式',
            'en': 'Color Mode'
        },
        'conv_color_mode_cmyw': {
            'zh': 'CMYW (青/品红/黄)',
            'en': 'CMYW (Cyan/Magenta/Yellow)'
        },
        'conv_color_mode_rybw': {
            'zh': 'RYBW (红/黄/蓝)',
            'en': 'RYBW (Red/Yellow/Blue)'
        },
        'conv_color_mode_cmykw': {
            'zh': 'CMYK+W',
            'en': 'CMYK+W'
        },
        'conv_structure': {
            'zh': '结构',
            'en': 'Structure'
        },
        'conv_structure_double': {
            'zh': '双面 (钥匙扣)',
            'en': 'Double-sided (Keychain)'
        },
        'conv_structure_single': {
            'zh': '单面 (浮雕)',
            'en': 'Single-sided (Relief)'
        },
        'conv_modeling_mode': {
            'zh': '🎨 建模模式',
            'en': '🎨 Modeling Mode'
        },
        'conv_modeling_mode_info': {
            'zh': '高保真：RLE无缝拼接，水密模型 | 像素艺术：经典方块美学',
            'en': 'High-Fidelity: RLE seamless, watertight | Pixel Art: Classic blocky aesthetic'
        },
        'conv_modeling_mode_hifi': {
            'zh': '高保真 (细节优先)',
            'en': 'High-Fidelity (Detail)'
        },
        'conv_modeling_mode_pixel': {
            'zh': '像素艺术 (方块风格)',
            'en': 'Pixel Art (Blocky)'
        },
        'conv_quantize_colors': {
            'zh': '🎨 色彩细节',
            'en': '🎨 Color Detail'
        },
        'conv_quantize_info': {
            'zh': '颜色数量越多细节越丰富，但生成越慢',
            'en': 'Higher = More detail, Slower'
        },
        'conv_auto_bg': {
            'zh': '🗑️ 移除背景',
            'en': '🗑️ Remove Background'
        },
        'conv_auto_bg_info': {
            'zh': '自动移除图像背景色',
            'en': 'Auto remove background'
        },
        'conv_tolerance': {
            'zh': '容差',
            'en': 'Tolerance'
        },
        'conv_tolerance_info': {
            'zh': '背景容差值 (0-150)，值越大移除越多',
            'en': 'Higher = Remove more'
        },
        'conv_width': {
            'zh': '宽度 (mm)',
            'en': 'Width (mm)'
        },
        'conv_thickness': {
            'zh': '背板 (mm)',
            'en': 'Backing (mm)'
        },
        'conv_preview_btn': {
            'zh': '👁️ 生成预览',
            'en': '👁️ Generate Preview'
        },
        'conv_preview_section': {
            'zh': '#### 🎨 2D预览 - 点击图片放置挂孔位置（暂不推荐使用）',
            'en': '#### 🎨 2D Preview - Click to place loop (Not recommended)'
        },
        'conv_loop_section': {
            'zh': '##### 🔗 挂孔设置',
            'en': '##### 🔗 Loop Settings'
        },
        'conv_loop_enable': {
            'zh': '启用挂孔',
            'en': 'Enable Loop'
        },
        'conv_loop_remove': {
            'zh': '🗑️ 移除挂孔',
            'en': '🗑️ Remove Loop'
        },
        'conv_loop_width': {
            'zh': '宽度(mm)',
            'en': 'Width(mm)'
        },
        'conv_loop_length': {
            'zh': '长度(mm)',
            'en': 'Length(mm)'
        },
        'conv_loop_hole': {
            'zh': '孔径(mm)',
            'en': 'Hole(mm)'
        },
        'conv_loop_angle': {
            'zh': '旋转角度°',
            'en': 'Rotation°'
        },
        'conv_loop_info': {
            'zh': '挂孔位置',
            'en': 'Loop Position'
        },
        'conv_status': {
            'zh': '状态',
            'en': 'Status'
        },
        'conv_generate_btn': {
            'zh': '🚀 生成3MF',
            'en': '🚀 Generate 3MF'
        },
        'conv_3d_preview': {
            'zh': '#### 🎮 3D预览',
            'en': '#### 🎮 3D Preview'
        },
        'conv_download_section': {
            'zh': '#### 📁 下载【务必合并对象后再切片】',
            'en': '#### 📁 Download [Merge objects before slicing]'
        },
        'conv_download_file': {
            'zh': '3MF文件',
            'en': '3MF File'
        },
        
        # ==================== Calibration Tab ====================
        'cal_title': {
            'zh': '### 第二步：生成校准板',
            'en': '### Step 2: Generate Calibration Board'
        },
        'cal_desc': {
            'zh': '生成1024种颜色的校准板，打印后用于提取打印机的实际色彩数据。',
            'en': 'Generate a 1024-color calibration board to extract your printer\'s actual color data.'
        },
        'cal_params': {
            'zh': '#### ⚙️ 参数',
            'en': '#### ⚙️ Parameters'
        },
        'cal_color_mode': {
            'zh': '色彩模式',
            'en': 'Color Mode'
        },
        'cal_block_size': {
            'zh': '色块尺寸 (mm)',
            'en': 'Block Size (mm)'
        },
        'cal_gap': {
            'zh': '间隙 (mm)',
            'en': 'Gap (mm)'
        },
        'cal_backing': {
            'zh': '底板颜色',
            'en': 'Backing Color'
        },
        'cal_generate_btn': {
            'zh': '🚀 生成',
            'en': '🚀 Generate'
        },
        'cal_status': {
            'zh': '状态',
            'en': 'Status'
        },
        'cal_preview': {
            'zh': '#### 👁️ 预览',
            'en': '#### 👁️ Preview'
        },
        'cal_download': {
            'zh': '下载 3MF',
            'en': 'Download 3MF'
        },
        
        # ==================== Color Extractor Tab ====================
        'ext_title': {
            'zh': '### 第三步：提取颜色数据',
            'en': '### Step 3: Extract Color Data'
        },
        'ext_desc': {
            'zh': '拍摄打印好的校准板照片，提取真实的色彩数据生成 LUT 文件。',
            'en': 'Take a photo of your printed calibration board to extract real color data.'
        },
        'ext_upload_section': {
            'zh': '#### 📸 上传照片',
            'en': '#### 📸 Upload Photo'
        },
        'ext_color_mode': {
            'zh': '🎨 色彩模式',
            'en': '🎨 Color Mode'
        },
        'ext_photo': {
            'zh': '校准板照片',
            'en': 'Calibration Photo'
        },
        'ext_rotate_btn': {
            'zh': '↺ 旋转',
            'en': '↺ Rotate'
        },
        'ext_reset_btn': {
            'zh': '🗑️ 重置',
            'en': '🗑️ Reset'
        },
        'ext_correction_section': {
            'zh': '#### 🔧 校正参数',
            'en': '#### 🔧 Correction'
        },
        'ext_wb': {
            'zh': '自动白平衡',
            'en': 'Auto WB'
        },
        'ext_vignette': {
            'zh': '暗角校正',
            'en': 'Vignette'
        },
        'ext_zoom': {
            'zh': '缩放',
            'en': 'Zoom'
        },
        'ext_distortion': {
            'zh': '畸变',
            'en': 'Distortion'
        },
        'ext_offset_x': {
            'zh': 'X偏移',
            'en': 'Offset X'
        },
        'ext_offset_y': {
            'zh': 'Y偏移',
            'en': 'Offset Y'
        },
        'ext_extract_btn': {
            'zh': '🚀 提取',
            'en': '🚀 Extract'
        },
        'ext_status': {
            'zh': '状态',
            'en': 'Status'
        },
        'ext_hint_white': {
            'zh': '#### 👉 点击: **白色色块 (左上角)**',
            'en': '#### 👉 Click: **White Block (Top-Left)**'
        },
        'ext_marked': {
            'zh': '标记图',
            'en': 'Marked'
        },
        'ext_sampling': {
            'zh': '#### 📍 采样预览',
            'en': '#### 📍 Sampling'
        },
        'ext_reference': {
            'zh': '#### 🎯 参考',
            'en': '#### 🎯 Reference'
        },
        'ext_result': {
            'zh': '#### 📊 结果 (点击修正)',
            'en': '#### 📊 Result (Click to fix)'
        },
        'ext_manual_fix': {
            'zh': '#### 🛠️ 手动修正',
            'en': '#### 🛠️ Manual Fix'
        },
        'ext_click_cell': {
            'zh': '点击左侧色块查看...',
            'en': 'Click cell on left...'
        },
        'ext_override': {
            'zh': '替换颜色',
            'en': 'Override Color'
        },
        'ext_apply_btn': {
            'zh': '🔧 应用',
            'en': '🔧 Apply'
        },
        'ext_download_npy': {
            'zh': '下载 .npy',
            'en': 'Download .npy'
        },
        
        # ==================== Footer ====================
        'footer_tip': {
            'zh': '💡 提示: 使用高质量的PLA/PETG basic材料可获得最佳效果',
            'en': '💡 Tip: Use high-quality translucent PLA/PETG basic for best results'
        },
        
        # ==================== Status Messages ====================
        'msg_no_image': {
            'zh': '❌ 请上传图片',
            'en': '❌ Please upload an image'
        },
        'msg_no_lut': {
            'zh': '⚠️ 请选择或上传 .npy 校准文件！',
            'en': '⚠️ Please upload a .npy calibration file!'
        },
        'msg_preview_success': {
            'zh': '✅ 预览',
            'en': '✅ Preview'
        },
        'msg_click_to_place': {
            'zh': '点击图片放置挂孔',
            'en': 'Click to place loop'
        },
        'msg_conversion_complete': {
            'zh': '✅ 转换完成',
            'en': '✅ Conversion complete'
        },
        'msg_resolution': {
            'zh': '分辨率',
            'en': 'Resolution'
        },
        'msg_loop': {
            'zh': '挂孔',
            'en': 'Loop'
        },
        'msg_model_too_large': {
            'zh': '⚠️ 模型过大，已禁用3D预览',
            'en': '⚠️ Model too large, 3D preview disabled'
        },
        'msg_preview_simplified': {
            'zh': 'ℹ️ 3D预览已简化',
            'en': 'ℹ️ 3D preview simplified'
        },
        
        # ==================== About Page Content ====================
        'about_content': {
            'zh': """## 🌟 Lumina Studio v1.4.2

**多材料3D打印色彩系统**

让FDM打印也能拥有精准的色彩还原

---

### 📖 使用流程

1. **生成校准板** → 打印校准网格
2. **提取颜色** → 拍照并提取打印机实际色彩
3. **转换图像** → 将图片转为多层3D模型

---

### 🎨 色彩模式定位点顺序

| 模式 | 左上 | 右上 | 右下 | 左下 |
|------|------|------|------|------|
| **RYBW** | ⬜ 白色 | 🟥 红色 | 🟦 蓝色 | 🟨 黄色 |
| **CMYW** | ⬜ 白色 | 🔵 青色 | 🟣 品红 | 🟨 黄色 |
| **CMYK+W** | 🟨 黄色 | 🟣 品红 | 🔵 青色 | ⬜ 白色 |

> ⚠️ **注意**: CMYK+W模式的角点顺序是从底面（外观面）观看的结果

---

### 🔬 技术原理

- **Beer-Lambert 光学混色**
- **KD-Tree 色彩匹配**
- **RLE 几何生成**
- **K-Means 色彩量化**

---

### 📝 v1.4.2 更新日志

#### 🐛 Bug修复
- 修复了一些已知问题
- 优化了性能和稳定性

#### 🚀 功能整合与优化
- ✅ **整合 341 色块模式** - 将 v1.5 的 CMYK+W 核心功能合入 v1.4.1 架构
- ✅ **保持 1.4.1 核心引擎** - 使用最新的 RLE 高保真建模引擎
- ✅ **界面布局还原** - 保持 1.4.1 的页面顺序与多语言切换支持

---

### 📝 历史更新日志

#### v1.5 (Local)
- ✅ **CMYK+W 模式**
- ✅ **矢量/版画/像素三大建模模式**
- ✅ **钥匙扣挂孔颜色自动检测**

#### v1.4.1 (Upstream)
- ✅ **高保真（High-Fidelity）模式** - RLE 算法，无缝拼接
- ✅ **语言切换功能** & **LUT 预设库**

---

### 🚧 开发路线图

- [✅] 4色基础模式
- [✅] 两种建模模式（高保真/像素艺术）
- [✅] RLE几何引擎
- [✅] 钥匙扣挂孔
- [✅] **CMYK+W 模式**
- [🚧] 漫画模式（Ben-Day dots模拟）
- [ ] 6色扩展模式
- [ ] 拼豆模式

---

### 📄 许可证

**CC BY-NC-SA 4.0** - Attribution-NonCommercial-ShareAlike

**商业豁免**: 个人创作者、街边摊贩、小型私营企业可免费使用本软件生成模型并销售实体打印品。

---

### 🙏 致谢

特别感谢：
- **HueForge** - 在FDM打印中开创光学混色技术
- **AutoForge** - 让多色工作流民主化
- **3D打印社区** - 持续创新

---

<div style="text-align:center; color:#888; margin-top:20px;">
    Made with ❤️ by [MIN]<br>
    v1.4.2 | 2026
</div>
""",
            'en': """## 🌟 Lumina Studio v1.4.2

**Multi-Material 3D Print Color System**

Accurate color reproduction for FDM printing

---

### 📖 Workflow

1. **Generate Calibration** → Print calibration grid
2. **Extract Colors** → Photo → extract real colors
3. **Convert Image** → Image → multi-layer 3D model

---

### 🎨 Color Mode Corner Order

| Mode | Top-Left | Top-Right | Bottom-Right | Bottom-Left |
|------|----------|-----------|--------------|-------------|
| **RYBW** | ⬜ White | 🟥 Red | 🟦 Blue | 🟨 Yellow |
| **CMYW** | ⬜ White | 🔵 Cyan | 🟣 Magenta | 🟨 Yellow |
| **CMYK+W** | 🟨 Yellow | 🟣 Magenta | 🔵 Cyan | ⬜ White |

---

### 🔬 Technology

- **Beer-Lambert Optical Color Mixing**
- **KD-Tree Color Matching**
- **RLE Geometry Generation** (High-Fidelity Mode)
- **K-Means Color Quantization**

---

### 📝 v1.4.2 Changelog

#### 🐛 Bug Fixes
- Fixed some known issues
- Improved performance and stability

#### 🚀 Integration & Optimization
- ✅ **341-Swatch Mode Integration** - Ported CMYK+W core features from v1.5 to v1.4.1 architecture
- ✅ **Upstream Engine Maintained** - Kept the advanced RLE High-Fidelity modeling engine
- ✅ **Layout Restored** - Restored v1.4.1 tab order and multi-language support

---

### 📝 Previous Changelogs

#### v1.5 (Local)
- ✅ **CMYK+W Mode**
- ✅ **Vector/Woodblock/Pixel Modeling Modes**
- ✅ **Auto Loop Color Detection**

#### v1.4.1 (Upstream)
- ✅ **High-Fidelity Mode** - RLE algorithm, seamless
- ✅ **Language Switching** & **LUT Presets**

---

### 🚧 Roadmap

- [✅] 4-color base mode
- [✅] Two modeling modes (High-Fidelity/Pixel Art)
- [✅] RLE geometry engine
- [✅] Keychain loop
- [✅] **CMYK+W Mode**
- [🚧] Manga mode (Ben-Day dots simulation)
- [ ] 6-color extended mode

---

### 📄 License

**CC BY-NC-SA 4.0** - Attribution-NonCommercial-ShareAlike

**Commercial Exemption**: Individual creators, street vendors, and small businesses may freely use this software to generate models and sell physical prints.

---

### 🙏 Acknowledgments

Special thanks to:
- **HueForge** - Pioneering optical color mixing in FDM
- **AutoForge** - Democratizing multi-color workflows
- **3D printing community** - Continuous innovation

---

<div style="text-align:center; color:#888; margin-top:20px;">
    Made with ❤️ by [MIN]<br>
    v1.4.2 | 2026
</div>
"""
        },
    }
    
    @staticmethod
    def get(key: str, lang: str = 'zh') -> str:
        """
        Get text in specified language
        
        Args:
            key: Text key name
            lang: Language code ('zh' or 'en')
        
        Returns:
            str: Translated text, returns key itself if key doesn't exist
        """
        if key in I18n.TEXTS:
            return I18n.TEXTS[key].get(lang, I18n.TEXTS[key].get('zh', key))
        return key
    
    @staticmethod
    def get_all(lang: str = 'zh') -> dict:
        """
        Get all texts in specified language version
        
        Args:
            lang: Language code ('zh' or 'en')
        
        Returns:
            dict: {key: translated_text}
        """
        return {key: I18n.get(key, lang) for key in I18n.TEXTS.keys()}
