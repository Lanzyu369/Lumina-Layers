/**
 * Lumina Studio - Translation Dictionary
 * Migrated from core/i18n.py TEXTS dictionary
 * Contains all zh/en translation key-value pairs
 */
export const translations: Record<string, Record<"zh" | "en", string>> = {
  // ==================== Application Title and Header ====================
  app_title: {
    zh: "✨ Lumina Studio",
    en: "✨ Lumina Studio",
  },
  app_subtitle: {
    zh: "多材料3D打印色彩系统 | v1.6.3",
    en: "Multi-Material 3D Print Color System | v1.6.3",
  },
  app_panel_controls: {
    zh: "面板控件",
    en: "Panel Controls",
  },
  lang_btn_zh: {
    zh: "🌐 中文",
    en: "🌐 中文",
  },
  lang_btn_en: {
    zh: "🌐 English",
    en: "🌐 English",
  },

  // ==================== Stats Bar ====================
  stats_total: {
    zh: "📊 累计生成",
    en: "📊 Total Generated",
  },
  stats_calibrations: {
    zh: "校准板",
    en: "Calibrations",
  },
  stats_extractions: {
    zh: "颜色提取",
    en: "Extractions",
  },
  stats_conversions: {
    zh: "模型转换",
    en: "Conversions",
  },

  // ==================== Tab Titles ====================
  tab_converter: {
    zh: "💎 图像转换",
    en: "💎 Image Converter",
  },
  tab_calibration: {
    zh: "📐 校准板生成",
    en: "📐 Calibration",
  },
  tab_extractor: {
    zh: "🎨 颜色提取",
    en: "🎨 Color Extractor",
  },
  tab_about: {
    zh: "ℹ️ 关于",
    en: "ℹ️ About",
  },

  // ==================== Converter Tab ====================
  conv_title: {
    zh: "### 第一步：转换图像",
    en: "### Step 1: Convert Image",
  },
  conv_desc: {
    zh: "**两种建模模式**：高保真（RLE无缝拼接）、像素艺术（方块风格）\n\n**流程**: 上传LUT和图像 → 选择建模模式 → 调整色彩细节 → 预览 → 生成",
    en: "**Two Modeling Modes**: High-Fidelity (RLE seamless) and Pixel Art (blocky style)\n\n**Workflow**: Upload LUT & Image → Select Mode → Adjust Color Detail → Preview → Generate",
  },
  conv_input_section: {
    zh: "#### 📁 输入",
    en: "#### 📁 Input",
  },
  conv_lut_title: {
    zh: "**校准数据**",
    en: "**Calibration Data**",
  },
  conv_lut_dropdown: {
    zh: "选择预设",
    en: "Select Preset",
  },
  conv_lut_info: {
    zh: "从预设库中选择LUT",
    en: "Select from library",
  },
  conv_lut_status_default: {
    zh: "💡 拖放 .npy / .json / .npz 文件自动添加",
    en: "💡 Drop .npy / .json / .npz to add",
  },
  conv_lut_status_selected: {
    zh: "✅ 已选择",
    en: "✅ Selected",
  },
  conv_lut_status_saved: {
    zh: "✅ LUT已保存",
    en: "✅ LUT saved",
  },
  conv_lut_status_error: {
    zh: "❌ 文件不存在",
    en: "❌ File not found",
  },
  conv_image_label: {
    zh: "输入图像",
    en: "Input Image",
  },
  crop_title: {
    zh: "图片裁剪",
    en: "Image Crop",
  },
  crop_original_size: {
    zh: "原图尺寸",
    en: "Original size",
  },
  crop_selection_size: {
    zh: "选区尺寸",
    en: "Selection size",
  },
  crop_x: {
    zh: "X 偏移",
    en: "X Offset",
  },
  crop_y: {
    zh: "Y 偏移",
    en: "Y Offset",
  },
  crop_width: {
    zh: "宽度",
    en: "Width",
  },
  crop_height: {
    zh: "高度",
    en: "Height",
  },
  crop_use_original: {
    zh: "使用原图",
    en: "Use original",
  },
  crop_confirm: {
    zh: "确认裁剪",
    en: "Confirm crop",
  },
  crop_auto_color: {
    zh: "🎨 计算最佳色彩细节",
    en: "🎨 Calculate optimal color detail",
  },
  conv_params_section: {
    zh: "#### ⚙️ 参数",
    en: "#### ⚙️ Parameters",
  },
  conv_color_mode: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  conv_color_mode_cmyw: {
    zh: "CMYW (青/品红/黄)",
    en: "CMYW (Cyan/Magenta/Yellow)",
  },
  conv_color_mode_rybw: {
    zh: "RYBW (红/黄/蓝)",
    en: "RYBW (Red/Yellow/Blue)",
  },
  conv_structure: {
    zh: "结构",
    en: "Structure",
  },
  conv_structure_double: {
    zh: "双面",
    en: "Double-sided",
  },
  conv_structure_single: {
    zh: "单面",
    en: "Single-sided",
  },
  conv_modeling_mode: {
    zh: "🎨 建模模式",
    en: "🎨 Modeling Mode",
  },
  conv_modeling_mode_info: {
    zh: "高保真：RLE无缝拼接，水密模型 | 像素艺术：经典方块美学 | SVG模式：矢量直接转换",
    en: "High-Fidelity: RLE seamless, watertight | Pixel Art: Classic blocky aesthetic | SVG Mode: Direct vector conversion",
  },
  conv_modeling_mode_hifi: {
    zh: "🎨 高保真",
    en: "🎨 High-Fidelity",
  },
  conv_modeling_mode_pixel: {
    zh: "🧱 像素艺术",
    en: "🧱 Pixel Art",
  },
  conv_modeling_mode_vector: {
    zh: "📐 SVG模式",
    en: "📐 SVG Mode",
  },
  conv_quantize_colors: {
    zh: "🎨 色彩细节",
    en: "🎨 Color Detail",
  },
  conv_quantize_info: {
    zh: "颜色数量越多细节越丰富，但生成越慢",
    en: "Higher = More detail, Slower",
  },
  conv_auto_color_btn: {
    zh: "🔍 自动计算",
    en: "🔍 Auto Detect",
  },
  conv_auto_color_calculating: {
    zh: "⏳ 计算中...",
    en: "⏳ Calculating...",
  },
  conv_auto_bg: {
    zh: "🗑️ 移除背景",
    en: "🗑️ Remove Background",
  },
  conv_auto_bg_info: {
    zh: "自动移除图像背景色",
    en: "Auto remove background",
  },
  conv_tolerance: {
    zh: "容差",
    en: "Tolerance",
  },
  conv_tolerance_info: {
    zh: "背景容差值 (0-150)，值越大移除越多",
    en: "Higher = Remove more",
  },
  conv_width: {
    zh: "宽度 (mm)",
    en: "Width (mm)",
  },
  conv_height: {
    zh: "高度 (mm)",
    en: "Height (mm)",
  },
  conv_thickness: {
    zh: "背板 (mm)",
    en: "Backing (mm)",
  },
  conv_backing_color: {
    zh: "底板颜色",
    en: "Backing Color",
  },
  conv_preview_btn: {
    zh: "👁️ 生成预览",
    en: "👁️ Generate Preview",
  },
  conv_preview_section: {
    zh: "#### 🎨 2D预览",
    en: "#### 🎨 2D Preview",
  },
  conv_palette: {
    zh: "🎨 颜色调色板",
    en: "🎨 Color Palette",
  },
  conv_palette_step1: {
    zh: "### 1. 原图颜色（点击预览图）",
    en: "### 1. Original Color (Click Preview)",
  },
  conv_palette_step2: {
    zh: "### 2. 替换为（点击色块）",
    en: "### 2. Replace With (Click Swatch)",
  },
  conv_palette_selected_label: {
    zh: "当前选中",
    en: "Selected",
  },
  conv_palette_replace_label: {
    zh: "将替换为",
    en: "Replace With",
  },
  conv_palette_lut_loading: {
    zh: "⏳ 正在加载 LUT 颜色...",
    en: "⏳ Loading LUT colors...",
  },
  conv_palette_replacements_placeholder: {
    zh: "生成预览后显示替换列表",
    en: "Generate preview to see replacements",
  },
  conv_palette_replacements_label: {
    zh: "已生效的替换",
    en: "Applied Replacements",
  },
  conv_palette_apply_btn: {
    zh: "✅ 确认替换",
    en: "✅ Apply",
  },
  conv_palette_undo_btn: {
    zh: "↩️ 撤销",
    en: "↩️ Undo",
  },
  conv_palette_clear_btn: {
    zh: "🗑️ 清除所有",
    en: "🗑️ Clear",
  },
  conv_palette_user_replacements_title: {
    zh: "用户替换",
    en: "User Replacements",
  },
  conv_palette_auto_pairs_title: {
    zh: "自动配准",
    en: "Auto Pairs",
  },
  conv_palette_delete_selected_btn: {
    zh: "删除选中",
    en: "Delete Selected",
  },
  conv_palette_delete_selected_empty: {
    zh: "❌ 请先选中一项用户替换",
    en: "❌ Select one user replacement first",
  },
  conv_palette_user_empty: {
    zh: "暂无替换",
    en: "No replacements",
  },
  conv_palette_auto_empty: {
    zh: "暂无自动配准",
    en: "No auto pairs",
  },
  lut_grid_invalid: {
    zh: "⚠️ 请先选择一个有效的 LUT 文件",
    en: "⚠️ Please select a valid LUT file",
  },
  lut_grid_header: {
    zh: "🎨 当前 LUT 包含 <b>{count}</b> 种可打印颜色（点击选择）",
    en: "🎨 Current LUT contains <b>{count}</b> printable colors (click to select)",
  },

  // ==================== Loop / Outline / Cloisonne / Coating ====================
  conv_loop_section: {
    zh: "##### 🔗 挂孔设置",
    en: "##### 🔗 Loop Settings",
  },
  conv_loop_enable: {
    zh: "启用挂孔",
    en: "Enable Loop",
  },
  conv_loop_remove: {
    zh: "🗑️ 移除挂孔",
    en: "🗑️ Remove Loop",
  },
  conv_loop_width: {
    zh: "宽度(mm)",
    en: "Width(mm)",
  },
  conv_loop_length: {
    zh: "长度(mm)",
    en: "Length(mm)",
  },
  conv_loop_hole: {
    zh: "孔径(mm)",
    en: "Hole(mm)",
  },
  conv_loop_angle: {
    zh: "旋转角度°",
    en: "Rotation°",
  },
  conv_loop_info: {
    zh: "挂孔位置",
    en: "Loop Position",
  },
  conv_outline_section: {
    zh: "##### 外轮廓设置",
    en: "##### Outline Settings",
  },
  conv_outline_enable: {
    zh: "启用外轮廓",
    en: "Enable Outline",
  },
  conv_outline_width: {
    zh: "外轮廓厚度(mm)",
    en: "Outline Width(mm)",
  },
  conv_cloisonne_section: {
    zh: "##### 掐丝珐琅特效",
    en: "##### Cloisonné Effect",
  },
  conv_cloisonne_enable: {
    zh: "启用掐丝珐琅",
    en: "Enable Cloisonné",
  },
  conv_cloisonne_wire_width: {
    zh: "丝线宽度(mm)",
    en: "Wire Width(mm)",
  },
  conv_cloisonne_wire_height: {
    zh: "丝线高度(mm)",
    en: "Wire Height(mm)",
  },
  conv_cloisonne_wire_color: {
    zh: "丝线颜色槽位",
    en: "Wire Color Slot",
  },
  conv_free_color_btn: {
    zh: "🎯 标记为自由色",
    en: "🎯 Mark as Free Color",
  },
  conv_free_color_clear_btn: {
    zh: "清除自由色",
    en: "Clear Free Colors",
  },
  conv_free_color_label: {
    zh: "🎯 自由色",
    en: "🎯 Free Colors",
  },
  conv_coating_section: {
    zh: "##### 透明镀层",
    en: "##### Transparent Coating",
  },
  conv_coating_enable: {
    zh: "启用透明镀层",
    en: "Enable Coating",
  },
  conv_coating_height: {
    zh: "镀层厚度(mm)",
    en: "Coating Height(mm)",
  },
  conv_status: {
    zh: "状态",
    en: "Status",
  },
  conv_generate_btn: {
    zh: "🚀 生成3MF",
    en: "🚀 Generate 3MF",
  },
  conv_3d_preview: {
    zh: "#### 🎮 3D预览",
    en: "#### 🎮 3D Preview",
  },
  conv_download_section: {
    zh: "#### 📁 下载【务必合并对象后再切片】",
    en: "#### 📁 Download [Merge objects before slicing]",
  },
  conv_download_file: {
    zh: "3MF文件",
    en: "3MF File",
  },

  // ==================== Calibration Tab ====================
  cal_title: {
    zh: "生成校准板",
    en: "Generate Calibration Board",
  },
  cal_desc: {
    zh: "生成1024种颜色的校准板，打印后用于提取打印机的实际色彩数据。",
    en: "Generate a 1024-color calibration board to extract your printer's actual color data.",
  },
  cal_params: {
    zh: "参数",
    en: "Parameters",
  },
  cal_color_mode: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  cal_block_size: {
    zh: "色块尺寸 (mm)",
    en: "Block Size (mm)",
  },
  cal_gap: {
    zh: "间隙 (mm)",
    en: "Gap (mm)",
  },
  cal_backing: {
    zh: "底板颜色",
    en: "Backing Color",
  },
  cal_generate_btn: {
    zh: "生成",
    en: "Generate",
  },
  cal_status: {
    zh: "状态",
    en: "Status",
  },
  cal_preview: {
    zh: "预览",
    en: "Preview",
  },
  cal_download: {
    zh: "下载 3MF",
    en: "Download 3MF",
  },

  // ==================== Color Extractor Tab ====================
  ext_title: {
    zh: "提取颜色数据",
    en: "Extract Color Data",
  },
  ext_desc: {
    zh: "拍摄打印好的校准板照片，提取真实的色彩数据生成 LUT 文件。",
    en: "Take a photo of your printed calibration board to extract real color data.",
  },
  ext_upload_section: {
    zh: "#### 📸 上传照片",
    en: "#### 📸 Upload Photo",
  },
  ext_color_mode: {
    zh: "🎨 色彩模式",
    en: "🎨 Color Mode",
  },
  ext_photo: {
    zh: "校准板照片",
    en: "Calibration Photo",
  },
  ext_rotate_btn: {
    zh: "↺ 旋转",
    en: "↺ Rotate",
  },
  ext_reset_btn: {
    zh: "🗑️ 重置",
    en: "🗑️ Reset",
  },
  ext_correction_section: {
    zh: "校正参数",
    en: "Correction",
  },
  ext_vignette: {
    zh: "暗角校正",
    en: "Vignette",
  },
  ext_zoom: {
    zh: "缩放",
    en: "Zoom",
  },
  ext_distortion: {
    zh: "畸变",
    en: "Distortion",
  },
  ext_offset_x: {
    zh: "X偏移",
    en: "Offset X",
  },
  ext_offset_y: {
    zh: "Y偏移",
    en: "Offset Y",
  },
  ext_extract_btn: {
    zh: "🚀 提取",
    en: "🚀 Extract",
  },
  ext_status: {
    zh: "状态",
    en: "Status",
  },
  ext_hint_white: {
    zh: "#### 👉 点击: **白色色块 (左上角)**",
    en: "#### 👉 Click: **White Block (Top-Left)**",
  },
  ext_marked: {
    zh: "标记图",
    en: "Marked",
  },
  ext_sampling: {
    zh: "#### 📍 采样预览",
    en: "#### 📍 Sampling",
  },
  ext_reference: {
    zh: "#### 🎯 参考",
    en: "#### 🎯 Reference",
  },
  ext_result: {
    zh: "#### 📊 结果 (点击修正)",
    en: "#### 📊 Result (Click to fix)",
  },
  ext_manual_fix: {
    zh: "#### 🛠️ 手动修正",
    en: "#### 🛠️ Manual Fix",
  },
  ext_click_cell: {
    zh: "点击左侧色块查看...",
    en: "Click cell on left...",
  },
  ext_override: {
    zh: "替换颜色",
    en: "Override Color",
  },
  ext_apply_btn: {
    zh: "🔧 应用",
    en: "🔧 Apply",
  },
  ext_download_npy: {
    zh: "下载 .npy",
    en: "Download .npy",
  },

  // ==================== 3D Viewer ====================
  viewer_fullscreen: {
    zh: "全屏",
    en: "Fullscreen",
  },
  viewer_exit_fullscreen: {
    zh: "退出全屏",
    en: "Exit Fullscreen",
  },
  viewer_screenshot: {
    zh: "截图",
    en: "Screenshot",
  },
  viewer_hover_magnifier: {
    zh: "放大镜",
    en: "Magnifier",
  },
  viewer_hover_toggle_group: {
    zh: "悬停显示",
    en: "Hover Display",
  },
  viewer_hover_toggle_magnifier: {
    zh: "放大镜",
    en: "Magnifier",
  },
  viewer_hover_toggle_layers: {
    zh: "分层颜色",
    en: "Layer Colors",
  },
  viewer_hover_pixel: {
    zh: "像素坐标",
    en: "Pixel",
  },
  viewer_hover_surface_color: {
    zh: "表面颜色",
    en: "Surface Color",
  },
  viewer_hover_layers_title: {
    zh: "分层颜色",
    en: "Layer Colors",
  },
  viewer_hover_loading_layers: {
    zh: "正在加载分层颜色...",
    en: "Loading layer colors...",
  },
  viewer_hover_no_layer_data: {
    zh: "暂无分层颜色数据",
    en: "No layer color data",
  },
  viewer_hover_transparent: {
    zh: "透明",
    en: "Transparent",
  },

  // ==================== Footer ====================
  footer_tip: {
    zh: "💡 提示: 使用高质量的PLA/PETG basic材料可获得最佳效果",
    en: "💡 Tip: Use high-quality translucent PLA/PETG basic for best results",
  },

  // ==================== Status Messages ====================
  msg_no_image: {
    zh: "❌ 请上传图片",
    en: "❌ Please upload an image",
  },
  msg_no_lut: {
    zh: "⚠️ 请选择或上传校准文件！",
    en: "⚠️ Please select or upload a calibration file!",
  },
  msg_preview_success: {
    zh: "✅ 预览",
    en: "✅ Preview",
  },
  msg_click_to_place: {
    zh: "点击图片放置挂孔",
    en: "Click to place loop",
  },
  msg_conversion_complete: {
    zh: "✅ 转换完成",
    en: "✅ Conversion complete",
  },
  msg_resolution: {
    zh: "分辨率",
    en: "Resolution",
  },
  msg_loop: {
    zh: "挂孔",
    en: "Loop",
  },
  msg_model_too_large: {
    zh: "⚠️ 模型过大，已禁用3D预览",
    en: "⚠️ Model too large, 3D preview disabled",
  },
  msg_preview_simplified: {
    zh: "ℹ️ 3D预览已简化",
    en: "ℹ️ 3D preview simplified",
  },

  // ==================== Palette / Replacement ====================
  palette_empty: {
    zh: "暂无颜色，请先生成预览。",
    en: "No colors yet. Generate a preview first.",
  },
  palette_count: {
    zh: "共 {count} 种颜色",
    en: "{count} colors in image",
  },
  palette_hint: {
    zh: "点击色块高亮预览",
    en: "Click swatch to highlight in preview",
  },
  palette_tooltip: {
    zh: "点击高亮: {hex} ({pct}%)",
    en: "Click to highlight: {hex} ({pct}%)",
  },
  palette_replaced_with: {
    zh: "替换为 {hex}",
    en: "Replaced with {hex}",
  },
  palette_click_to_select: {
    zh: "点击调色板选择颜色",
    en: "Click palette to select",
  },
  palette_need_preview: {
    zh: "❌ 请先生成预览",
    en: "❌ Please generate preview first",
  },
  palette_need_original: {
    zh: "❌ 请先选择要替换的颜色",
    en: "❌ Select a color to replace",
  },
  palette_need_replacement: {
    zh: "❌ 请先选择替换颜色",
    en: "❌ Select a replacement color",
  },
  palette_replaced: {
    zh: "✅ 已替换 {src} → {dst}",
    en: "✅ Replaced {src} → {dst}",
  },
  palette_cleared: {
    zh: "✅ 已清除所有颜色替换",
    en: "✅ Cleared all replacements",
  },
  palette_undo_empty: {
    zh: "❌ 没有可撤销的操作",
    en: "❌ Nothing to undo",
  },
  palette_undone: {
    zh: "↩️ 已撤销",
    en: "↩️ Undone",
  },
  palette_mode_select_all: {
    zh: "全选",
    en: "All",
  },
  palette_mode_current: {
    zh: "当前",
    en: "Current",
  },
  palette_mode_multi_select: {
    zh: "多选",
    en: "Multi",
  },
  palette_mode_region: {
    zh: "局部区域",
    en: "Region",
  },
  palette_multi_select_count: {
    zh: "已选 {count} 色",
    en: "{count} selected",
  },
  palette_multi_select_region_count: {
    zh: "已选 {count} 个区域",
    en: "{count} regions selected",
  },
  palette_multi_select_click_remove: {
    zh: "点击取消选择",
    en: "Click to deselect",
  },

  // ==================== Color Merging ====================
  merge_enable_label: {
    zh: "启用自动颜色合并 Enable Auto Color Merging",
    en: "Enable Auto Color Merging",
  },
  merge_enable_info: {
    zh: "自动合并低使用率颜色到相近颜色",
    en: "Automatically merge low-usage colors to similar colors",
  },
  merge_threshold_label: {
    zh: "使用率阈值 Usage Threshold (%)",
    en: "Usage Threshold (%)",
  },
  merge_threshold_info: {
    zh: "低于此百分比的颜色将被合并",
    en: "Colors below this percentage will be merged",
  },
  merge_max_distance_label: {
    zh: "最大颜色距离 Max Color Distance (Delta-E)",
    en: "Max Color Distance (Delta-E)",
  },
  merge_max_distance_info: {
    zh: "只合并距离小于此值的颜色",
    en: "Only merge colors with distance below this value",
  },
  merge_preview_btn: {
    zh: "🔍 预览合并效果 Preview Merge",
    en: "🔍 Preview Merge",
  },
  merge_apply_btn: {
    zh: "✅ 应用合并 Apply Merge",
    en: "✅ Apply Merge",
  },
  merge_revert_btn: {
    zh: "↩️ 恢复原始 Revert",
    en: "↩️ Revert",
  },
  merge_status_empty: {
    zh: "💡 调整参数后点击预览",
    en: "💡 Adjust parameters and click preview",
  },
  merge_status_preview: {
    zh: "🔍 预览: {merged} 种颜色被合并 (质量: {quality:.1f})",
    en: "🔍 Preview: {merged} colors merged (quality: {quality:.1f})",
  },
  merge_status_applied: {
    zh: "✅ 已应用: {merged} 种颜色被合并",
    en: "✅ Applied: {merged} colors merged",
  },
  merge_status_reverted: {
    zh: "↩️ 已恢复到原始颜色",
    en: "↩️ Reverted to original colors",
  },
  merge_error_empty_palette: {
    zh: "❌ 调色板为空，无法执行颜色合并",
    en: "❌ Empty palette, cannot perform color merging",
  },
  merge_error_single_color: {
    zh: "❌ 图像只包含一种颜色，已禁用颜色合并",
    en: "❌ Image contains only one color, merging disabled",
  },
  merge_error_all_below_threshold: {
    zh: "⚠️ 所有颜色使用率都低于阈值，已禁用颜色合并以防止颜色丢失",
    en: "⚠️ All colors below threshold, merging disabled to prevent color loss",
  },
  merge_warning_no_targets: {
    zh: "⚠️ 部分颜色未找到合适的合并目标，保持原始颜色",
    en: "⚠️ Some colors have no suitable merge targets, keeping original",
  },
  merge_info_low_usage: {
    zh: "💡 检测到 {count} 种低使用率颜色 (<{threshold}%)",
    en: "💡 Detected {count} low-usage colors (<{threshold}%)",
  },
  merge_accordion_title: {
    zh: "🎨 颜色合并 Color Merging",
    en: "🎨 Color Merging",
  },

  // ==================== LUT Grid ====================
  lut_grid_load_hint: {
    zh: "加载 LUT 后显示可用颜色",
    en: "Load LUT to see available colors",
  },
  lut_grid_count: {
    zh: "共 {count} 种可用颜色",
    en: "{count} available colors",
  },
  lut_grid_search_placeholder: {
    zh: "搜索色号 (如 ff0000)",
    en: "Search hex (e.g. ff0000)",
  },
  lut_grid_search_clear: {
    zh: "清除",
    en: "Clear",
  },
  lut_grid_used: {
    zh: "图中已使用 ({count})",
    en: "Used in image ({count})",
  },
  lut_grid_other: {
    zh: "其他可用颜色 ({count})",
    en: "Other colors ({count})",
  },
  lut_grid_tooltip: {
    zh: "点击选择: {hex}",
    en: "Click to select: {hex}",
  },
  lut_grid_picker_label: {
    zh: "🎯 以色找色",
    en: "🎯 Find by Color",
  },
  lut_grid_picker_hint: {
    zh: "选一个颜色，自动匹配 LUT 中最接近的物理色",
    en: "Pick a color to find the closest match in LUT",
  },
  lut_grid_picker_btn: {
    zh: "匹配最近色",
    en: "Find Nearest",
  },
  lut_grid_picker_result: {
    zh: "✅ 最接近: {hex} (距离: {dist:.1f})",
    en: "✅ Nearest: {hex} (distance: {dist:.1f})",
  },
  lut_grid_hue_all: {
    zh: "全部",
    en: "All",
  },
  lut_grid_hue_red: {
    zh: "红色系",
    en: "Red",
  },
  lut_grid_hue_orange: {
    zh: "橙色系",
    en: "Orange",
  },
  lut_grid_hue_yellow: {
    zh: "黄色系",
    en: "Yellow",
  },
  lut_grid_hue_green: {
    zh: "绿色系",
    en: "Green",
  },
  lut_grid_hue_cyan: {
    zh: "青色系",
    en: "Cyan",
  },
  lut_grid_hue_blue: {
    zh: "蓝色系",
    en: "Blue",
  },
  lut_grid_hue_purple: {
    zh: "紫色系",
    en: "Purple",
  },
  lut_grid_hue_neutral: {
    zh: "中性色",
    en: "Neutral",
  },
  lut_grid_hue_fav: {
    zh: "收藏",
    en: "Favorites",
  },
  lut_grid_search_hex_placeholder: {
    zh: "输入 Hex 或 RGB 搜索定位 (如 #FF0000 或 255,0,0)",
    en: "Search by Hex or RGB (e.g. #FF0000 or 255,0,0)",
  },

  // ==================== Settings ====================
  settings_title: {
    zh: "## ⚙️ 设置",
    en: "## ⚙️ Settings",
  },
  settings_clear_cache: {
    zh: "🗑️ 清空缓存",
    en: "🗑️ Clear Cache",
  },
  settings_clear_output: {
    zh: "🗑️ 清空输出",
    en: "🗑️ Clear Output",
  },
  settings_reset_counters: {
    zh: "🔢 使用计数归零",
    en: "🔢 Reset Counters",
  },
  settings_cache_cleared: {
    zh: "✅ 缓存已清空，释放了 {} 空间",
    en: "✅ Cache cleared, freed {} of space",
  },
  settings_output_cleared: {
    zh: "✅ 输出已清空，释放了 {} 空间",
    en: "✅ Output cleared, freed {} of space",
  },
  settings_counters_reset: {
    zh: "✅ 计数器已归零：校准板: {} | 颜色提取: {} | 模型转换: {}",
    en: "✅ Counters reset: Calibrations: {} | Extractions: {} | Conversions: {}",
  },
  settings_cache_size: {
    zh: "📦 缓存大小: {}",
    en: "📦 Cache size: {}",
  },
  settings_output_size: {
    zh: "📦 输出大小: {}",
    en: "📦 Output size: {}",
  },
  theme_toggle_night: {
    zh: "🌙 夜间模式",
    en: "🌙 Night Mode",
  },
  theme_toggle_day: {
    zh: "☀️ 日间模式",
    en: "☀️ Day Mode",
  },

  // ==================== LUT Merge Tab ====================
  tab_merge: {
    zh: "🔀 色卡合并",
    en: "🔀 LUT Merge",
  },
  merge_title: {
    zh: "### 🔀 色卡合并",
    en: "### 🔀 LUT Merge",
  },
  merge_desc: {
    zh: "将不同色彩模式的LUT色卡合并为一个，获得更丰富的色彩。",
    en: "Merge LUT cards from different color modes into one for richer colors.",
  },
  merge_lut_primary_label: {
    zh: "🎯 主色卡（6色或8色）",
    en: "🎯 Primary LUT (6-Color or 8-Color)",
  },
  merge_lut_secondary_label: {
    zh: "➕ 副色卡（可多选）",
    en: "➕ Secondary LUTs (Multi-select)",
  },
  merge_lut_1_label: {
    zh: "选择LUT 1（主色卡）",
    en: "Select LUT 1 (Primary)",
  },
  merge_lut_2_label: {
    zh: "选择LUT 2（合并色卡）",
    en: "Select LUT 2 (Secondary)",
  },
  merge_secondary_modes: {
    zh: "已选副色卡",
    en: "Selected Secondary LUTs",
  },
  merge_secondary_none: {
    zh: "未选择副色卡",
    en: "No secondary LUTs selected",
  },
  merge_primary_hint: {
    zh: "💡 请先选择一个6色或8色的主色卡",
    en: "💡 Please select a 6-Color or 8-Color primary LUT first",
  },
  merge_primary_not_high: {
    zh: "❌ 主色卡必须是6色或8色模式",
    en: "❌ Primary LUT must be 6-Color or 8-Color mode",
  },
  merge_error_no_secondary: {
    zh: "❌ 请至少选择一个副色卡",
    en: "❌ Please select at least one secondary LUT",
  },
  merge_mode_label: {
    zh: "检测到的模式",
    en: "Detected Mode",
  },
  merge_mode_unknown: {
    zh: "未选择",
    en: "Not selected",
  },
  merge_dedup_label: {
    zh: "Delta-E 去重阈值",
    en: "Delta-E Dedup Threshold",
  },
  merge_dedup_info: {
    zh: "值越大去除的相近色越多，0=仅精确去重",
    en: "Higher = remove more similar colors, 0 = exact dedup only",
  },
  merge_btn: {
    zh: "🔀 执行合并",
    en: "🔀 Merge",
  },
  merge_status_ready: {
    zh: "💡 选择两个LUT后点击合并",
    en: "💡 Select two LUTs then click Merge",
  },
  merge_status_running: {
    zh: "⏳ 合并中...",
    en: "⏳ Merging...",
  },
  merge_status_success: {
    zh: "✅ 合并完成！合并前: {before} 色 → 合并后: {after} 色（精确去重: {exact}，相近色去除: {similar}）\n保存至: {path}",
    en: "✅ Merge complete! Before: {before} → After: {after} (exact dupes: {exact}, similar removed: {similar})\nSaved to: {path}",
  },
  merge_error_no_lut: {
    zh: "❌ 请选择至少两个LUT文件",
    en: "❌ Please select at least two LUT files",
  },
  merge_error_same_lut: {
    zh: "❌ 请选择不同的LUT文件",
    en: "❌ Please select different LUT files",
  },
  merge_error_incompatible: {
    zh: "❌ 不兼容的LUT组合: {msg}",
    en: "❌ Incompatible LUT combination: {msg}",
  },
  merge_error_failed: {
    zh: "❌ 合并失败: {msg}",
    en: "❌ Merge failed: {msg}",
  },

  // ==================== About Page Content ====================
  about_content: {
    zh: [
      "## 🌟 Lumina Studio v1.6.3",
      "",
      "**多材料3D打印色彩系统**",
      "",
      "让FDM打印也能拥有精准的色彩还原",
      "",
      "---",
      "",
      "### 📖 使用流程",
      "",
      "1. **生成校准板** → 打印1024色校准网格",
      "2. **提取颜色** → 拍照并提取打印机实际色彩",
      "3. **转换图像** → 将图片转为多层3D模型",
      "",
      "---",
      "",
      "### 🎨 色彩模式定位点顺序",
      "",
      "| 模式 | 左上 | 右上 | 右下 | 左下 |",
      "|------|------|------|------|------|",
      "| **RYBW** | ⬜ 白色 | 🟥 红色 | 🟦 蓝色 | 🟨 黄色 |",
      "| **CMYW** | ⬜ 白色 | 🔵 青色 | 🟣 品红 | 🟨 黄色 |",
      "",
      "---",
      "",
      "### 🔬 技术原理",
      "",
      "- **Beer-Lambert 光学混色**",
      "- **KD-Tree 色彩匹配**",
      "- **RLE 几何生成**",
      "- **K-Means 色彩量化**",
    ].join("\n"),
    en: [
      "## 🌟 Lumina Studio v1.6.3",
      "",
      "**Multi-Material 3D Print Color System**",
      "",
      "Accurate color reproduction for FDM printing",
      "",
      "---",
      "",
      "### 📖 Workflow",
      "",
      "1. **Generate Calibration** → Print 1024-color grid",
      "2. **Extract Colors** → Photo → extract real colors",
      "3. **Convert Image** → Image → multi-layer 3D model",
      "",
      "---",
      "",
      "### 🎨 Color Mode Corner Order",
      "",
      "| Mode | Top-Left | Top-Right | Bottom-Right | Bottom-Left |",
      "|------|----------|-----------|--------------|-------------|",
      "| **RYBW** | ⬜ White | 🟥 Red | 🟦 Blue | 🟨 Yellow |",
      "| **CMYW** | ⬜ White | 🔵 Cyan | 🟣 Magenta | 🟨 Yellow |",
      "",
      "---",
      "",
      "### 🔬 Technology",
      "",
      "- **Beer-Lambert Optical Color Mixing**",
      "- **KD-Tree Color Matching**",
      "- **RLE Geometry Generation**",
      "- **K-Means Color Quantization**",
    ].join("\n"),
  },

  // ==================== Widget Titles ====================
  "widget.converter": {
    zh: "图像转换",
    en: "Converter",
  },
  "widget.calibration": {
    zh: "校准板",
    en: "Calibration",
  },
  "widget.extractor": {
    zh: "颜色提取",
    en: "Extractor",
  },
  "widget.lutManager": {
    zh: "LUT 合并",
    en: "LUT Merge",
  },
  "widget.fiveColor": {
    zh: "配方查询",
    en: "Five-Color",
  },
  "widget.basicSettings": {
    zh: "基础设置",
    en: "Basic Settings",
  },
  "widget.advancedSettings": {
    zh: "高级设置",
    en: "Advanced Settings",
  },
  "widget.reliefSettings": {
    zh: "浮雕设置",
    en: "Relief Settings",
  },
  "widget.palettePanel": {
    zh: "调色板",
    en: "Palette",
  },
  "widget.lutColorGrid": {
    zh: "LUT 颜色网格",
    en: "LUT Color Grid",
  },
  "widget.outlineSettings": {
    zh: "外轮廓设置",
    en: "Outline Settings",
  },
  "widget.cloisonneSettings": {
    zh: "掐丝珐琅设置",
    en: "Cloisonné Settings",
  },
  "widget.coatingSettings": {
    zh: "涂层设置",
    en: "Coating Settings",
  },
  "widget.keychainLoop": {
    zh: "挂件环设置",
    en: "Keychain Loop",
  },
  "widget.fridgeMagnetSettings": {
    zh: "冰箱贴磁铁槽",
    en: "Fridge Magnet Settings",
  },
  "widget.puzzleSettings": {
    zh: "拼图设置",
    en: "Puzzle Settings",
  },
  "widget.actionBar": {
    zh: "操作栏",
    en: "Actions",
  },
  "widget.colorWorkstation": {
    zh: "颜色工作站",
    en: "Color Workstation",
  },
  "widget.colorWorkstationHint": {
    zh: "点击打开颜色工作站",
    en: "Click to open Color Workstation",
  },

  // ==================== 2D Color Overlay ====================
  fridge_magnet_enable: {
    zh: "启用冰箱贴磁铁槽",
    en: "Enable Fridge Magnet Mode",
  },
  fridge_magnet_mode_hint: {
    zh: "冰箱贴模式会强制切换为单面结构，并禁用拼图、大画幅和挂件环。",
    en: "Fridge magnet mode forces single-sided structure and disables puzzle, large-format, and keychain loop modes.",
  },
  fridge_magnet_summary_structure: {
    zh: "当前结构",
    en: "Structure",
  },
  fridge_magnet_summary_spacer: {
    zh: "当前底板厚度",
    en: "Spacer Thickness",
  },
  fridge_magnet_add: {
    zh: "添加磁铁",
    en: "Add Magnet",
  },
  fridge_magnet_reset_layout: {
    zh: "自动布局",
    en: "Auto Layout",
  },
  fridge_magnet_remove_selected: {
    zh: "删除当前磁铁",
    en: "Remove Selected",
  },
  fridge_magnet_list_title: {
    zh: "磁铁列表",
    en: "Magnet List",
  },
  fridge_magnet_item_label: {
    zh: "磁铁 {index}",
    en: "Magnet {index}",
  },
  fridge_magnet_empty_state: {
    zh: "当前没有磁铁槽，请先添加一个磁铁。",
    en: "No magnet cavities are configured yet. Add a magnet first.",
  },
  fridge_magnet_select_hint: {
    zh: "从上方列表选择一个磁铁以编辑尺寸和位置。",
    en: "Select a magnet above to edit its size and position.",
  },
  fridge_magnet_clear_selection: {
    zh: "清除选中",
    en: "Clear Selection",
  },
  fridge_magnet_shape: {
    zh: "形状",
    en: "Shape",
  },
  fridge_magnet_shape_round: {
    zh: "圆形",
    en: "Round",
  },
  fridge_magnet_shape_rect: {
    zh: "矩形",
    en: "Rectangular",
  },
  fridge_magnet_preset: {
    zh: "官方预设",
    en: "Official Preset",
  },
  fridge_magnet_preset_custom: {
    zh: "自定义",
    en: "Custom",
  },
  fridge_magnet_preset_round_d6x2: {
    zh: "圆形 D6×2 mm",
    en: "Round D6×2 mm",
  },
  fridge_magnet_preset_round_d12x3: {
    zh: "圆形 D12×3 mm",
    en: "Round D12×3 mm",
  },
  fridge_magnet_preset_round_d8x3: {
    zh: "圆形 D8×3 mm",
    en: "Round D8×3 mm",
  },
  fridge_magnet_preset_round_d10x3: {
    zh: "圆形 D10×3 mm",
    en: "Round D10×3 mm",
  },
  fridge_magnet_preset_rect_10x5x1: {
    zh: "矩形 10×5×1 mm",
    en: "Rect 10×5×1 mm",
  },
  fridge_magnet_preset_rect_15x5x2: {
    zh: "矩形 15×5×2 mm",
    en: "Rect 15×5×2 mm",
  },
  fridge_magnet_preset_rect_20x10x2: {
    zh: "矩形 20×10×2 mm",
    en: "Rect 20×10×2 mm",
  },
  fridge_magnet_diameter: {
    zh: "直径",
    en: "Diameter",
  },
  fridge_magnet_width: {
    zh: "宽度",
    en: "Width",
  },
  fridge_magnet_height: {
    zh: "高度",
    en: "Height",
  },
  fridge_magnet_thickness: {
    zh: "厚度",
    en: "Thickness",
  },
  fridge_magnet_center_x: {
    zh: "中心 X",
    en: "Center X",
  },
  fridge_magnet_center_y: {
    zh: "中心 Y",
    en: "Center Y",
  },
  color_2d_overlay_title: {
    zh: "颜色工作站",
    en: "Color Workstation",
  },
  color_2d_overlay_close: {
    zh: "关闭",
    en: "Close",
  },
  color_2d_overlay_close_shortcut: {
    zh: "ESC",
    en: "ESC",
  },
  color_2d_tab_preview: {
    zh: "2D 预览",
    en: "2D Preview",
  },
  color_2d_tab_palette: {
    zh: "调色板",
    en: "Palette",
  },
  color_2d_tab_lut_grid: {
    zh: "LUT 颜色",
    en: "LUT Colors",
  },
  color_2d_no_preview: {
    zh: "暂无预览图，请先完成预览",
    en: "No preview available. Please generate a preview first.",
  },
  color_2d_generating_preview: {
    zh: "正在生成预览…",
    en: "Generating preview…",
  },
  preview_debug_main_2d: {
    zh: "主 2D 预览",
    en: "Main 2D Preview",
  },
  preview_debug_action_2d: {
    zh: "操作栏 2D 小预览",
    en: "ActionBar Mini Preview",
  },
  puzzle_enable: {
    zh: "启用拼图模式",
    en: "Enable Puzzle Mode",
  },
  puzzle_batch_disabled_hint: {
    zh: "批量模式下暂不支持拼图模式。",
    en: "Puzzle mode is unavailable while batch mode is active.",
  },
  puzzle_style: {
    zh: "拼图风格",
    en: "Puzzle Style",
  },
  puzzle_style_regular: {
    zh: "规则拼图",
    en: "Regular Puzzle",
  },
  puzzle_style_irregular: {
    zh: "不规则拼图",
    en: "Irregular Puzzle",
  },
  puzzle_sizing_mode: {
    zh: "尺寸控制方式",
    en: "Sizing Mode",
  },
  puzzle_sizing_piece_size: {
    zh: "按块尺寸",
    en: "By Piece Size",
  },
  puzzle_sizing_grid: {
    zh: "按行列",
    en: "By Grid",
  },
  puzzle_sizing_piece_count: {
    zh: "按总片数",
    en: "By Piece Count",
  },
  puzzle_piece_width: {
    zh: "平均块宽",
    en: "Average Piece Width",
  },
  puzzle_piece_height: {
    zh: "平均块高",
    en: "Average Piece Height",
  },
  puzzle_rows: {
    zh: "行数",
    en: "Rows",
  },
  puzzle_cols: {
    zh: "列数",
    en: "Columns",
  },
  puzzle_target_piece_count: {
    zh: "目标片数",
    en: "Target Piece Count",
  },
  puzzle_connector_style: {
    zh: "连接器风格",
    en: "Connector Style",
  },
  puzzle_connector_classic: {
    zh: "经典风格",
    en: "Classic",
  },
  puzzle_connector_easy_cut: {
    zh: "易切割风格",
    en: "Easy Cut",
  },
  puzzle_seed: {
    zh: "随机种子",
    en: "Seed",
  },
  puzzle_randomize_seed: {
    zh: "重新随机",
    en: "Randomize",
  },
  puzzle_labels: {
    zh: "显示编号",
    en: "Show Piece Labels",
  },
  puzzle_engrave_back_labels: {
    zh: "背面刻号",
    en: "Engrave Back Labels",
  },
  puzzle_back_engrave_unavailable_hint: {
    zh: "背面刻号尚未写入导出几何，当前版本暂不可用。",
    en: "Back-label engraving is not embedded into exported geometry yet, so it is disabled for now.",
  },
  puzzle_irregularity_strength: {
    zh: "不规则强度",
    en: "Irregularity Strength",
  },
  puzzle_min_neck_width: {
    zh: "最小脖颈宽度",
    en: "Minimum Neck Width",
  },
  puzzle_summary_grid: {
    zh: "解析网格",
    en: "Resolved Grid",
  },
  puzzle_summary_requested_grid: {
    zh: "目标网格",
    en: "Requested Grid",
  },
  puzzle_summary_requested_piece_count: {
    zh: "目标片数",
    en: "Requested Piece Count",
  },
  puzzle_summary_piece_count: {
    zh: "最终片数",
    en: "Resolved Piece Count",
  },
  puzzle_summary_piece_size: {
    zh: "平均块尺寸",
    en: "Derived Piece Size",
  },
  puzzle_warnings: {
    zh: "几何警告",
    en: "Geometry Warnings",
  },
  puzzle_large_format_disabled_hint: {
    zh: "拼图模式开启时，大画幅模式会被禁用。",
    en: "Large Format is disabled while puzzle mode is enabled.",
  },
  puzzle_loop_disabled_hint: {
    zh: "拼图模式开启时，挂件环会被禁用。",
    en: "Keychain Loop is disabled while puzzle mode is enabled.",
  },

  // ==================== TAB Navigation Titles ====================
  "tab.converter": {
    zh: "图像转换",
    en: "Converter",
  },
  "tab.lutManagement": {
    zh: "LUT管理",
    en: "LUT Management",
  },
  "tab.calibration": {
    zh: "校准",
    en: "Calibration",
  },
  "tab.extractor": {
    zh: "提取器",
    en: "Extractor",
  },
  "tab.lutManager": {
    zh: "LUT 合并",
    en: "LUT Merge",
  },
  "tab.lutCompare": {
    zh: "LUT 对比",
    en: "LUT Compare",
  },
  "tab.fiveColor": {
    zh: "配方查询",
    en: "Five-Color",
  },
  "tab.vectorizer": {
    zh: "图像转矢量",
    en: "Vectorizer",
  },
  "tab.settings": {
    zh: "设置",
    en: "Settings",
  },

  // ==================== Settings Panel (Particle Loading) ====================
  "settings.title": {
    zh: "系统设置",
    en: "System Settings",
  },
  "settings.desc": {
    zh: "管理缓存与运行时偏好设置，保持工作区轻量且稳定。",
    en: "Manage cache and runtime preferences to keep the workspace light and stable.",
  },
  "settings.maintenance": {
    zh: "维护",
    en: "Maintenance",
  },
  "settings.fancy_loading": {
    zh: "粒子特效加载动画",
    en: "Particle Effect Loading",
  },
  "settings.fancy_loading_desc": {
    zh: "启用七彩粒子聚合加载特效，关闭后使用轻量级扫描线动画",
    en: "Enable rainbow particle convergence effect, disable for lightweight scan line animation",
  },
  "settings.cache": {
    zh: "缓存管理",
    en: "Cache Management",
  },
  "settings.clear_cache": {
    zh: "清除缓存",
    en: "Clear Cache",
  },
  "settings.clear_cache_desc": {
    zh: "清除后端临时文件和缓存数据",
    en: "Clear backend temporary files and cached data",
  },
  "settings.cache_summary": {
    zh: "快速回收后端临时文件，适合在长时间使用后整理空间。",
    en: "Reclaim backend temporary files after longer sessions to tidy up storage.",
  },
  "settings.cache_cleared": {
    zh: "缓存已清除",
    en: "Cache cleared",
  },
  "settings.cache_cleared_detail": {
    zh: "已清除 {count} 个临时文件，释放 {size}",
    en: "Cleared {count} temporary files, freed {size}",
  },
  "settings.cache_clear_failed": {
    zh: "清除缓存失败，请稍后重试",
    en: "Failed to clear cache. Please try again.",
  },

  // ==================== Settings Panel (Slicer Settings) ====================
  "settings.slicer_settings": {
    zh: "切片软件设置",
    en: "Slicer Settings",
  },
  "settings.slicer_software": {
    zh: "切片软件",
    en: "Slicer Software",
  },
  "settings.printer_model": {
    zh: "打印机型号",
    en: "Printer Model",
  },
  "settings.bed_size": {
    zh: "打印床尺寸",
    en: "Bed Size",
  },
  "settings.nozzle_count": {
    zh: "喷头数量",
    en: "Nozzle Count",
  },
  "settings.dual_head": {
    zh: "双头",
    en: "Dual Head",
  },
  "settings.single_head": {
    zh: "单头",
    en: "Single Head",
  },
  "loading.generating": {
    zh: "模型生成中...",
    en: "Generating model...",
  },

  // ==================== App Header ====================
  app_header_title: {
    zh: "Lumina Studio 2.0",
    en: "Lumina Studio 2.0",
  },
  app_checking_backend: {
    zh: "正在检查后端…",
    en: "Checking backend…",
  },
  app_backend_connected: {
    zh: "后端已连接",
    en: "Backend Connected",
  },
  app_backend_unreachable: {
    zh: "后端不可达",
    en: "Backend Unreachable",
  },
  app_reset_layout: {
    zh: "重置布局",
    en: "Reset Layout",
  },
  app_3d_scene_error: {
    zh: "3D 场景加载失败",
    en: "3D scene failed to load",
  },
  app_toggle_language: {
    zh: "切换语言",
    en: "Toggle language",
  },
  app_toggle_theme: {
    zh: "切换主题",
    en: "Toggle theme",
  },

  // ==================== LUT Manager Panel ====================
  lut_manager_title: {
    zh: "LUT 合并工具",
    en: "LUT Merge Tool",
  },
  lut_manager_desc: {
    zh: "将多个 LUT 合并为一个，支持 Delta-E 去重。主 LUT 必须为 6-Color 或 8-Color 模式。",
    en: "Merge multiple LUTs into one with Delta-E dedup. Primary LUT must be 6-Color or 8-Color mode.",
  },
  lut_manager_primary_label: {
    zh: "主 LUT",
    en: "Primary LUT",
  },
  lut_manager_primary_placeholder: {
    zh: "选择主 LUT...",
    en: "Select primary LUT...",
  },
  lut_manager_loading: {
    zh: "加载中...",
    en: "Loading...",
  },
  lut_manager_primary_mode_invalid: {
    zh: "主 LUT 必须为 6-Color 或 8-Color 模式",
    en: "Primary LUT must be 6-Color or 8-Color mode",
  },
  lut_manager_secondary_label: {
    zh: "副 LUT",
    en: "Secondary LUTs",
  },
  lut_manager_no_secondary: {
    zh: "无可用的副 LUT",
    en: "No secondary LUTs available",
  },
  lut_manager_select_primary_first: {
    zh: "请先选择主 LUT",
    en: "Please select a primary LUT first",
  },
  lut_manager_dedup_label: {
    zh: "去重阈值",
    en: "Dedup Threshold",
  },
  lut_manager_dedup_hint: {
    zh: "0 = 仅精确去重，值越大去除越多相近色",
    en: "0 = exact dedup only, higher = remove more similar colors",
  },
  lut_manager_merge_btn: {
    zh: "合并并保存",
    en: "Merge & Save",
  },
  lut_manager_merge_success: {
    zh: "✓ 合并成功！",
    en: "✓ Merge successful!",
  },
  lut_manager_merge_before: {
    zh: "合并前",
    en: "Before",
  },
  lut_manager_merge_after: {
    zh: "合并后",
    en: "After",
  },
  lut_manager_exact_dupes: {
    zh: "精确去重",
    en: "Exact dupes",
  },
  lut_manager_similar_removed: {
    zh: "相近色去除",
    en: "Similar removed",
  },
  lut_manager_file: {
    zh: "文件",
    en: "File",
  },
  lut_manager_close_error: {
    zh: "关闭错误",
    en: "Close error",
  },
  lut_manager_mode_summary: {
    zh: "模式 {mode} · 共 {count} 色",
    en: "Mode {mode} · {count} colors",
  },
  lut_manager_selected_count: {
    zh: "已选择 {count} 个副 LUT",
    en: "{count} secondary LUTs selected",
  },

  lut_compare_title: {
    zh: "LUT 对比工具",
    en: "LUT Compare Tool",
  },
  lut_compare_desc: {
    zh: "按同配方比较两个 LUT 的颜色偏移，适用于耗材、批次和重复校准的一致性分析。",
    en: "Compare two LUTs by shared recipe to measure material, batch, and calibration drift.",
  },
  lut_compare_lut_a_label: {
    zh: "基准 LUT",
    en: "Baseline LUT",
  },
  lut_compare_lut_b_label: {
    zh: "对比 LUT",
    en: "Comparison LUT",
  },
  lut_compare_lut_a_placeholder: {
    zh: "选择基准 LUT...",
    en: "Select baseline LUT...",
  },
  lut_compare_lut_b_placeholder: {
    zh: "选择对比 LUT...",
    en: "Select comparison LUT...",
  },
  lut_compare_compare_btn: {
    zh: "开始对比",
    en: "Compare LUTs",
  },
  lut_compare_result_title: {
    zh: "对比结果",
    en: "Comparison Result",
  },
  lut_compare_summary: {
    zh: "已比较 {lutA} 与 {lutB} 的 {count} 个共享配方。",
    en: "Compared {count} shared recipes between {lutA} and {lutB}.",
  },
  lut_compare_matched: {
    zh: "共享配方",
    en: "Shared Recipes",
  },
  lut_compare_coverage_a: {
    zh: "A 覆盖率",
    en: "A Coverage",
  },
  lut_compare_coverage_b: {
    zh: "B 覆盖率",
    en: "B Coverage",
  },
  lut_compare_mean: {
    zh: "平均 ΔE00",
    en: "Mean ΔE00",
  },
  lut_compare_p95: {
    zh: "P95 ΔE00",
    en: "P95 ΔE00",
  },
  lut_compare_max: {
    zh: "最大 ΔE00",
    en: "Max ΔE00",
  },
  lut_compare_identical: {
    zh: "RGB 完全一致",
    en: "Exact RGB Matches",
  },
  lut_compare_warnings_title: {
    zh: "注意事项",
    en: "Warnings",
  },
  lut_compare_warning_mode_mismatch: {
    zh: "LUT 模式不一致：{modeA} vs {modeB}",
    en: "LUT modes differ: {modeA} vs {modeB}",
  },
  lut_compare_warning_layer_count_mismatch: {
    zh: "配方层数不一致：{countA} vs {countB}",
    en: "Recipe layer counts differ: {countA} vs {countB}",
  },
  lut_compare_warning_layer_height_mismatch: {
    zh: "层高不一致：{values}",
    en: "Layer heights differ: {values}",
  },
  lut_compare_warning_line_width_mismatch: {
    zh: "线宽不一致：{values}",
    en: "Line widths differ: {values}",
  },
  lut_compare_warning_no_shared_recipes: {
    zh: "没有共享配方，统计结果已归零。",
    en: "No shared recipes were found, so comparison metrics were zeroed.",
  },
  lut_compare_warning_row_mismatch: {
    zh: "{label} 的 rgb/stacks 行数不一致：rgb={rgb}，stacks={stacks}；已仅使用前 {used} 行。",
    en: "{label} has mismatched rgb/stacks rows: rgb={rgb}, stacks={stacks}; only the first {used} rows were used.",
  },
  lut_compare_warning_duplicate_recipes: {
    zh: "{label} 存在 {count} 条重复配方记录；每个配方仅保留第一条。",
    en: "{label} contains {count} duplicate recipe rows; only the first row for each recipe was kept.",
  },
  lut_compare_warning_generic: {
    zh: "对比过程中返回了额外警告，请结合结果谨慎解读。",
    en: "Additional warnings were returned during comparison; please interpret the result with care.",
  },
  lut_compare_worst_title: {
    zh: "最大差异配方",
    en: "Largest Recipe Diffs",
  },
  lut_compare_worst_desc: {
    zh: "展示共享配方中差异最大的若干条目，帮助快速定位色偏最明显的配方。",
    en: "Shows the shared recipes with the largest differences so the biggest color shifts are easy to spot.",
  },
  lut_compare_delta: {
    zh: "ΔE00",
    en: "ΔE00",
  },
  lut_compare_no_result: {
    zh: "选择两个 LUT 后即可开始对比。",
    en: "Select two LUTs to start comparing.",
  },
  lut_compare_no_diffs: {
    zh: "当前没有可展示的共享配方差异。",
    en: "There are no shared recipe diffs to display.",
  },

  // ==================== About View ====================
  about_title: {
    zh: "Lumina Studio 2.0",
    en: "Lumina Studio 2.0",
  },
  about_desc: {
    zh: "更多信息即将推出",
    en: "More info coming soon",
  },
  about_clear_cache_loading: {
    zh: "清理中...",
    en: "Clearing...",
  },
  about_clear_cache: {
    zh: "清除系统缓存",
    en: "Clear System Cache",
  },
  about_close_notification: {
    zh: "关闭通知",
    en: "Close notification",
  },
  about_cache_clear_success: {
    zh: "已清理 {deleted_files} 个缓存文件，释放 {freed}",
    en: "Cleared {deleted_files} cached files, freed {freed}",
  },
  about_cache_clear_failed: {
    zh: "缓存清理失败",
    en: "Cache clear failed",
  },

  // ==================== Calibration Panel ====================
  cal_color_mode_label: {
    zh: "颜色模式",
    en: "Color Mode",
  },
  cal_block_size_label: {
    zh: "色块尺寸",
    en: "Block Size",
  },
  cal_gap_label: {
    zh: "色块间距",
    en: "Block Gap",
  },
  cal_backing_label: {
    zh: "底板颜色",
    en: "Backing Color",
  },
  cal_generate_btn_panel: {
    zh: "生成校准板",
    en: "Generate Calibration",
  },
  cal_download_3mf: {
    zh: "下载校准文件",
    en: "Download Calibration File",
  },
  cal_8color_full_export_label: {
    zh: "导出全部 8 色配方",
    en: "Export Full 8-Color Recipes",
  },
  cal_8color_full_export_hint: {
    zh: "生成多页 ZIP，每页包含 3MF 和对应配方 JSON，不影响现有两页提取流程。",
    en: "Generate a multi-page ZIP with a 3MF and matching recipe JSON for each page without changing the existing two-page extraction flow.",
  },
  cal_8color_full_export_on: {
    zh: "全量",
    en: "Full",
  },
  cal_8color_full_export_off: {
    zh: "精简",
    en: "Compact",
  },
  cal_preview_alt: {
    zh: "校准板预览",
    en: "Calibration preview",
  },

  // ==================== Extractor Panel ====================
  ext_color_mode_label: {
    zh: "颜色模式",
    en: "Color Mode",
  },
  ext_page_label: {
    zh: "页码",
    en: "Page",
  },
  ext_page_number_prefix: {
    zh: "",
    en: "Page ",
  },
  ext_page_number_suffix: {
    zh: "号",
    en: "",
  },
  ext_upload_label: {
    zh: "上传校准板照片",
    en: "Upload Calibration Board Photo",
  },
  ext_offset_x_label: {
    zh: "水平偏移 (offset_x)",
    en: "Horizontal Offset (offset_x)",
  },
  ext_offset_y_label: {
    zh: "垂直偏移 (offset_y)",
    en: "Vertical Offset (offset_y)",
  },
  ext_zoom_label: {
    zh: "缩放 (zoom)",
    en: "Zoom",
  },
  ext_distortion_label: {
    zh: "畸变校正 (distortion)",
    en: "Distortion Correction",
  },
  ext_vignette_label: {
    zh: "暗角校正",
    en: "Vignette Correction",
  },
  ext_auto_wb_label: {
    zh: "自动白平衡",
    en: "Auto White Balance",
  },
  ext_extract_btn_label: {
    zh: "提取颜色",
    en: "Extract Colors",
  },
  ext_clear_corners: {
    zh: "清除角点",
    en: "Clear Corners",
  },
  ext_merge_5c_title: {
    zh: "5色扩展双页合并",
    en: "5-Color Extended Dual-Page Merge",
  },
  ext_merge_8c_title: {
    zh: "8色双页合并",
    en: "8-Color Dual-Page Merge",
  },
  ext_merge_8c_full_title: {
    zh: "8色完整版合并",
    en: "8-Color Full Merge",
  },
  ext_merge_5c_btn: {
    zh: "合并 5 色 LUT",
    en: "Merge 5-Color LUT",
  },
  ext_merge_8c_btn: {
    zh: "合并 8 色 LUT",
    en: "Merge 8-Color LUT",
  },
  ext_merge_8c_full_btn: {
    zh: "合并 8 色完整版 LUT",
    en: "Merge Full 8-Color LUT",
  },
  ext_pages_extracted_label: {
    zh: "已提取页数",
    en: "Extracted Pages",
  },
  ext_page_extracted: {
    zh: "已提取",
    en: "Extracted",
  },
  ext_page_not_extracted: {
    zh: "未提取",
    en: "Not extracted",
  },
  ext_page_1_label: {
    zh: "第 1 页",
    en: "Page 1",
  },
  ext_page_2_label: {
    zh: "第 2 页",
    en: "Page 2",
  },
  ext_8color_full_export_label: {
    zh: "8色完整版提取",
    en: "Full 8-Color Extraction",
  },
  ext_8color_full_export_hint: {
    zh: "如果你的校准板来自完整版 ZIP，请开启后按 1号-24号逐页提取并在全部完成后合并。",
    en: "Enable this if your calibration boards come from the full 8-color ZIP, then extract pages 1-24 and merge after all pages are complete.",
  },
  ext_8color_full_export_on: {
    zh: "全量",
    en: "Full",
  },
  ext_8color_full_export_off: {
    zh: "精简",
    en: "Compact",
  },
  ext_download_lut: {
    zh: "下载 LUT 文件 (.json)",
    en: "Download LUT File (.json)",
  },
  ext_manual_fix_hint: {
    zh: "点击右侧 LUT 预览图中的色块可手动修正颜色",
    en: "Click a cell in the LUT preview to manually fix its color",
  },
  ext_material_type_label: {
    zh: "耗材类型",
    en: "Material Type",
  },
  ext_palette_title: {
    zh: "调色板确认",
    en: "Palette Confirmation",
  },
  ext_palette_metadata_hint: {
    zh: "填写厂商、类型，并为每个颜色记录厂商命名",
    en: "Set manufacturer, type, and vendor color names for each entry",
  },
  ext_manufacturer_label: {
    zh: "厂商",
    en: "Manufacturer",
  },
  ext_type_label: {
    zh: "类型",
    en: "Type",
  },
  ext_palette_internal_color_label: {
    zh: "内部通道",
    en: "Internal Slot",
  },
  ext_palette_color_name_label: {
    zh: "厂商颜色名称",
    en: "Vendor Color Name",
  },
  ext_confirm_palette_btn: {
    zh: "确认调色板",
    en: "Confirm Palette",
  },
  ext_palette_confirmed: {
    zh: "✓ 调色板已确认",
    en: "✓ Palette confirmed",
  },

  // ==================== Extractor Canvas ====================
  ext_canvas_warp_view: {
    zh: "透视校正",
    en: "Warp View",
  },
  ext_canvas_lut_preview: {
    zh: "LUT 预览 / 点击色块修正颜色",
    en: "LUT Preview / Click cell to fix color",
  },
  ext_canvas_row: {
    zh: "行",
    en: "Row",
  },
  ext_canvas_col: {
    zh: "列",
    en: "Col",
  },
  ext_canvas_fixing: {
    zh: "修正中...",
    en: "Fixing...",
  },
  ext_canvas_confirm_fix: {
    zh: "确认修正",
    en: "Confirm Fix",
  },
  ext_canvas_cancel: {
    zh: "取消",
    en: "Cancel",
  },
  ext_canvas_upload_hint: {
    zh: "请在左侧面板上传校准板照片",
    en: "Upload a calibration board photo from the left panel",
  },
  ext_canvas_upload_hint_en: {
    zh: "上传校准板照片以开始",
    en: "Upload a calibration board photo to begin",
  },
  ext_canvas_positioning_done: {
    zh: "定位完成",
    en: "Positioning Complete",
  },
  ext_canvas_click_corner: {
    zh: "请点击第 {n} 个角点: {label}",
    en: "Click corner {n}: {label}",
  },

  // ==================== Basic Settings ====================
  basic_crop_after_upload: {
    zh: "上传后裁剪",
    en: "Crop After Upload",
  },
  basic_lut_label: {
    zh: "LUT",
    en: "LUT",
  },
  basic_lut_placeholder: {
    zh: "选择 LUT...",
    en: "Select LUT...",
  },
  basic_lut_upload: {
    zh: "上传",
    en: "Upload",
  },
  basic_lut_upload_success: {
    zh: "LUT 上传成功",
    en: "LUT uploaded",
  },
  basic_lut_upload_error: {
    zh: "LUT 上传失败",
    en: "LUT upload failed",
  },
  basic_color_mode_label: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  basic_source_version_label: {
    zh: "来源类型",
    en: "Source Type",
  },
  basic_source_version_legacy: {
    zh: "传统 LUT",
    en: "Legacy LUT",
  },
  basic_source_version_native: {
    zh: "反推LUT",
    en: "Inferred LUT",
  },
  basic_source_kind_label: {
    zh: "颜色源类型",
    en: "Source Kind",
  },
  basic_brand_label: {
    zh: "品牌",
    en: "Brand",
  },
  basic_brand_loading: {
    zh: "品牌目录加载中…",
    en: "Loading brands…",
  },
  basic_brand_placeholder: {
    zh: "请选择品牌",
    en: "Select a brand",
  },
  basic_native_brand_placeholder: {
    zh: "请选择品牌",
    en: "Select a brand",
  },
  basic_native_brand_summary_label: {
    zh: "品牌信息",
    en: "Brand Info",
  },
  basic_native_material_label: {
    zh: "材质类型",
    en: "Material Type",
  },
  basic_native_vendor_label: {
    zh: "供应商",
    en: "Vendor",
  },
  basic_native_db_label: {
    zh: "数据库",
    en: "Databases",
  },
  basic_native_db_placeholder: {
    zh: "未选择数据库",
    en: "No databases selected",
  },
  basic_native_mode_label: {
    zh: "动态层模式",
    en: "Layer Mode",
  },
  basic_native_layer_count_label: {
    zh: "层数",
    en: "Layer Count",
  },
  basic_native_mode_placeholder: {
    zh: "请选择支持模式",
    en: "Select a supported mode",
  },
  basic_color_layers_label: {
    zh: "叠色层数",
    en: "Color Layers",
  },
  basic_layer_height_label: {
    zh: "叠色层高",
    en: "Layer Height",
  },
  basic_supported_modes_label: {
    zh: "支持模式",
    en: "Supported Modes",
  },
  basic_model_gate_label: {
    zh: "模型辅助匹配",
    en: "Model-Assisted Matching",
  },
  basic_model_enable: {
    zh: "模型辅助匹配",
    en: "Model-Assisted Matching",
  },
  basic_model_only: {
    zh: "仅模型匹配",
    en: "Model only",
  },
  basic_model_threshold: {
    zh: "模型阈值",
    en: "Model Threshold",
  },
  basic_model_margin: {
    zh: "模型边距",
    en: "Model Margin",
  },
  basic_model_runtime_defaults_hint: {
    zh: "留空则使用运行时默认值。",
    en: "Leave blank to use runtime defaults.",
  },
  basic_dynamic_layers_legacy_hint: {
    zh: "当前为旧 LUT，不支持动态层数或自定义配方。",
    en: "This legacy LUT does not support dynamic layers or custom recipes.",
  },
  basic_width: {
    zh: "宽度",
    en: "Width",
  },
  basic_height: {
    zh: "高度",
    en: "Height",
  },
  basic_thickness: {
    zh: "厚度",
    en: "Thickness",
  },
  basic_structure_mode: {
    zh: "结构模式",
    en: "Structure Mode",
  },
  basic_modeling_mode: {
    zh: "建模模式",
    en: "Modeling Mode",
  },
  basic_image_format_error: {
    zh: "仅支持 JPG/PNG/SVG/WebP/HEIC 格式",
    en: "Only JPG/PNG/SVG/WebP/HEIC formats are supported",
  },

  // ==================== Large Format Mode ====================
  slicer_download_zip: {
    zh: "下载 ZIP",
    en: "Download ZIP",
  },
  slicer_generate_download_zip: {
    zh: "生成并下载 ZIP",
    en: "Generate & Download ZIP",
  },
  basic_large_format: {
    zh: "大画幅模式",
    en: "Large Format Mode",
  },
  basic_large_format_hint: {
    zh: "自动切割为多片 3MF 压缩包",
    en: "Auto-tiled into a ZIP of 3MF files",
  },
  basic_tile_width: {
    zh: "切片宽度",
    en: "Tile Width",
  },
  basic_tile_height: {
    zh: "切片高度",
    en: "Tile Height",
  },

  // ==================== Structure Mode Options ====================
  "structure_mode.Double-sided": {
    zh: "双面",
    en: "Double-sided",
  },
  "structure_mode.Single-sided": {
    zh: "单面",
    en: "Single-sided",
  },

  // ==================== Modeling Mode Options ====================
  "modeling_mode.high-fidelity": {
    zh: "高保真",
    en: "High-Fidelity",
  },
  "modeling_mode.pixel": {
    zh: "像素艺术",
    en: "Pixel Art",
  },
  "modeling_mode.vector": {
    zh: "矢量模式",
    en: "Vector",
  },

  // ==================== Advanced Settings ====================
  adv_quantize_colors: {
    zh: "量化颜色数",
    en: "Quantize Colors",
  },
  adv_bg_tolerance: {
    zh: "背景容差",
    en: "Background Tolerance",
  },
  adv_auto_bg: {
    zh: "自动背景",
    en: "Auto Background",
  },
  adv_enable_cleanup: {
    zh: "启用清理",
    en: "Enable Cleanup",
  },
  adv_separate_backing: {
    zh: "分离底板",
    en: "Separate Backing",
  },
  adv_hue_protection: {
    zh: "🎨 色相保护",
    en: "🎨 Hue Protection",
  },
  adv_chroma_gate: {
    zh: "🌈 暗色彩度门槛",
    en: "🌈 Dark Chroma Gate",
  },

  // ==================== Relief Settings ====================
  relief_enable: {
    zh: "启用浮雕",
    en: "Enable Relief",
  },
  relief_vector_unsupported: {
    zh: "矢量模式暂不支持浮雕",
    en: "Relief is not supported in Vector mode",
  },
  relief_max_height: {
    zh: "最大高度",
    en: "Max Height",
  },
  relief_auto_height_mode: {
    zh: "自动高度模式",
    en: "Auto Height Mode",
  },
  relief_darker_higher: {
    zh: "深色凸起",
    en: "Darker Higher",
  },
  relief_lighter_higher: {
    zh: "浅色凸起",
    en: "Lighter Higher",
  },
  relief_use_heightmap: {
    zh: "根据高度图",
    en: "Use Heightmap",
  },
  relief_heightmap_label: {
    zh: "高度图",
    en: "Heightmap",
  },
  relief_file_selected: {
    zh: "已选择",
    en: "Selected",
  },

  // ==================== Outline Settings ====================
  outline_enable: {
    zh: "启用外轮廓",
    en: "Enable Outline",
  },
  outline_width: {
    zh: "外轮廓厚度",
    en: "Outline Width",
  },

  // ==================== Cloisonne Settings ====================
  cloisonne_enable: {
    zh: "启用掐丝珐琅",
    en: "Enable Cloisonné",
  },
  cloisonne_wire_width: {
    zh: "金属丝宽度",
    en: "Wire Width",
  },
  cloisonne_wire_height: {
    zh: "金属丝高度",
    en: "Wire Height",
  },
  cloisonne_wip: {
    zh: "此功能正在施工中，部分效果可能不完整",
    en: "This feature is under construction, some effects may be incomplete",
  },

  // ==================== Coating Settings ====================
  coating_enable: {
    zh: "启用涂层",
    en: "Enable Coating",
  },
  coating_height: {
    zh: "涂层高度",
    en: "Coating Height",
  },

  // ==================== Keychain Loop Settings ====================
  loop_enable: {
    zh: "添加挂件环",
    en: "Add Keychain Loop",
  },
  loop_width: {
    zh: "环宽度",
    en: "Loop Width",
  },
  loop_length: {
    zh: "环长度",
    en: "Loop Length",
  },
  loop_hole_diameter: {
    zh: "环孔直径",
    en: "Loop Hole Diameter",
  },
  loop_angle: {
    zh: "旋转角度",
    en: "Rotation Angle",
  },
  loop_position_preset: {
    zh: "位置预设",
    en: "Position Preset",
  },
  loop_offset_x: {
    zh: "X 偏移",
    en: "X Offset",
  },
  loop_offset_y: {
    zh: "Y 偏移",
    en: "Y Offset",
  },
  loop_preset_top_center: {
    zh: "上中",
    en: "Top Center",
  },
  loop_preset_top_left: {
    zh: "左上",
    en: "Top Left",
  },
  loop_preset_top_right: {
    zh: "右上",
    en: "Top Right",
  },
  loop_preset_left_center: {
    zh: "左中",
    en: "Left Center",
  },
  loop_preset_right_center: {
    zh: "右中",
    en: "Right Center",
  },
  loop_preset_bottom_center: {
    zh: "下中",
    en: "Bottom Center",
  },

  // ==================== Action Bar ====================
  action_upload_hint: {
    zh: "请先上传图片并选择 LUT",
    en: "Please upload an image and select a LUT first",
  },
  action_batch_upload_hint: {
    zh: "请先添加图片并选择 LUT",
    en: "Please add images and select a LUT first",
  },
  action_preview: {
    zh: "预览",
    en: "Preview",
  },
  action_generate: {
    zh: "生成",
    en: "Generate",
  },
  action_batch_generate: {
    zh: "批量生成",
    en: "Batch Generate",
  },
  action_preview_alt: {
    zh: "预览结果",
    en: "Preview result",
  },
  action_view_layers: {
    zh: "查看分层",
    en: "View Layers",
  },
  action_layers_loading: {
    zh: "加载分层...",
    en: "Loading layers...",
  },
  loading_witty_1: {
    zh: "正在折叠高维空间...",
    en: "Folding higher dimensions...",
  },
  loading_witty_2: {
    zh: "正在为打印床预热赛博能量...",
    en: "Preheating cyber energy for the print bed...",
  },
  loading_witty_3: {
    zh: "正在提炼像素点中的灵魂...",
    en: "Extracting souls from pixels...",
  },
  loading_witty_4: {
    zh: "正在拼接彩色多边形...",
    en: "Splicing colorful polygons...",
  },
  loading_witty_5: {
    zh: "正在向打印机注入魔法...",
    en: "Injecting magic into the printer...",
  },
  loading_witty_6: {
    zh: "正在打磨 3MF 积木块...",
    en: "Polishing 3MF building blocks...",
  },
  loading_witty_7: {
    zh: "正在从异世界召唤材质...",
    en: "Summoning textures from another world...",
  },
  loading_witty_8: {
    zh: "正在计算光子跳跃轨道...",
    en: "Calculating photon jump trajectories...",
  },
  loading_witty_9: {
    zh: "不要走开，马上渲染完毕...",
    en: "Hold on, rendering almost complete...",
  },
  loading_witty_10: {
    zh: "请给您的喷嘴一点准备时间...",
    en: "Please give your nozzle some time to prepare...",
  },
  loading_witty_11: {
    zh: "正在校准多发混合挤出机...",
    en: "Calibrating multi-color mixing extruder...",
  },
  loading_witty_12: {
    zh: "正在清理虚拟构建底板...",
    en: "Cleaning virtual build plate...",
  },
  loading_witty_13: {
    zh: "正在熔化高精度的数字耗材...",
    en: "Melting high-precision digital filament...",
  },
  loading_witty_14: {
    zh: "正在挤出完美的底层裙边...",
    en: "Extruding the perfect base skirt...",
  },
  loading_witty_15: {
    zh: "正在规划 G 代码的最优路径...",
    en: "Planning optimal G-code paths...",
  },
  loading_witty_16: {
    zh: "正在调教步进电机的脾气...",
    en: "Tuning the temper of stepper motors...",
  },
  loading_witty_17: {
    zh: "正在精心填充网格内部...",
    en: "Carefully infilling the mesh interior...",
  },
  loading_witty_18: {
    zh: "预热虚拟喷头至 210°C 中...",
    en: "Preheating virtual nozzle to 210°C...",
  },
  loading_witty_19: {
    zh: "正在生成仿生有机树状支撑...",
    en: "Generating bionic organic tree supports...",
  },
  loading_witty_20: {
    zh: "正在抹平第一层讨厌的大象腿...",
    en: "Smoothing the annoying first layer elephant foot...",
  },
  loading_witty_21: {
    zh: "超级风扇启动，冷却悬垂区域...",
    en: "Superfan activated, cooling overhangs...",
  },
  loading_witty_22: {
    zh: "正在计算桥接的完美抛物线...",
    en: "Calculating the perfect parabola for bridging...",
  },
  loading_witty_23: {
    zh: "正在对层叠颜色进行魔法混合...",
    en: "Magically blending stacked layers of colors...",
  },
  loading_witty_24: {
    zh: "正在宇宙中寻找丢失的 Z 轴原点...",
    en: "Searching the universe for the lost Z-axis origin...",
  },
  loading_witty_25: {
    zh: "正在安抚打滑的挤出机齿轮...",
    en: "Pacifying slipping extruder gears...",
  },
  loading_witty_26: {
    zh: "为模型注入强防翘边附着力...",
    en: "Injecting anti-warping adhesion into the model...",
  },
  loading_witty_27: {
    zh: "正在用微波清理喷嘴上的拉丝...",
    en: "Microwaving stringing residue off the nozzle...",
  },
  loading_witty_28: {
    zh: "正在将您的灵感切片成一层层...",
    en: "Slicing your inspiration layer by layer...",
  },
  loading_witty_29: {
    zh: "为调色盘补充一点赛博朋克墨水...",
    en: "Refilling cyberpunk ink for the palette...",
  },
  loading_witty_30: {
    zh: "正在进行一百万次色彩碰撞测试...",
    en: "Conducting an intense color collision test...",
  },
  loading_witty_31: {
    zh: "正在把二维像素用力吹成三维...",
    en: "Blowing 2D pixels vigorously into 3D...",
  },
  loading_witty_32: {
    zh: "构建坚不可摧的 3D 底层网格中...",
    en: "Building indestructible 3D base grids...",
  },
  loading_witty_33: {
    zh: "熨平顶层，让它像镜面一样反光...",
    en: "Ironing top layers until they shine like mirrors...",
  },
  loading_witty_34: {
    zh: "正在从虚空深渊中召唤支撑材料...",
    en: "Summoning support structures from the void abyss...",
  },
  loading_witty_35: {
    zh: "正在解构庞大的彩色三维点云矩阵...",
    en: "Deconstructing massive colorful 3D matrices...",
  },
  loading_witty_36: {
    zh: "正在为立体模型注入引力波形...",
    en: "Injecting gravitational waveforms into 3D models...",
  },
  loading_witty_37: {
    zh: "调色中...不，是在重新发明颜色...",
    en: "Calibrating colors... no, reinventing colors...",
  },
  loading_witty_38: {
    zh: "正在为您一砖一瓦搭建浮雕世界...",
    en: "Building a relief world for you, brick by brick...",
  },
  loading_witty_39: {
    zh: "正在拿针线缝补模型的破损多边形...",
    en: "Darning the broken polygons of your model...",
  },
  loading_witty_40: {
    zh: "Lumina 工作室正在为您打印一个好心情...",
    en: "Lumina Studio is printing a good mood for you...",
  },
  action_layers_title: {
    zh: "分层预览",
    en: "Layer Preview",
  },
  action_layer_nth: {
    zh: "第",
    en: "Layer ",
  },
  action_layer_unit: {
    zh: "层",
    en: "",
  },
  action_layer_prev: {
    zh: "上一层",
    en: "Prev",
  },
  action_layer_next: {
    zh: "下一层",
    en: "Next",
  },

  // ==================== Bed Size Selector ====================
  bed_size_label: {
    zh: "热床尺寸",
    en: "Bed Size",
  },
  bed_size_loading: {
    zh: "加载中...",
    en: "Loading...",
  },
  bed_size_placeholder: {
    zh: "选择热床尺寸...",
    en: "Select bed size...",
  },

  // ==================== Palette Panel ====================
  palette_no_data: {
    zh: "暂无调色板数据，请先完成预览",
    en: "No palette data. Please generate a preview first.",
  },
  palette_quantized: {
    zh: "量化色",
    en: "Quantized",
  },
  palette_matched: {
    zh: "匹配色",
    en: "Matched",
  },
  palette_replaced_label: {
    zh: "替换色",
    en: "Replaced",
  },
  palette_undo: {
    zh: "撤销",
    en: "Undo",
  },
  palette_clear_remaps: {
    zh: "清空替换",
    en: "Clear Remaps",
  },
  palette_list_label: {
    zh: "调色板颜色列表",
    en: "Palette color list",
  },

  // ==================== LUT Color Grid ====================
  lut_grid_loading: {
    zh: "加载 LUT 颜色中...",
    en: "Loading LUT colors...",
  },
  lut_grid_select_lut: {
    zh: "请先选择 LUT 以加载可用颜色",
    en: "Select a LUT to load available colors",
  },
  lut_grid_total_colors: {
    zh: "共 {total} 色，显示 {visible} 色",
    en: "{total} colors, showing {visible}",
  },
  lut_grid_selected: {
    zh: "已选中",
    en: "Selected",
  },
  lut_grid_search_placeholder_short: {
    zh: "搜索 HEX / RGB 颜色...",
    en: "Search HEX / RGB...",
  },
  lut_grid_hue_all_short: {
    zh: "全部",
    en: "All",
  },
  lut_grid_hue_fav_short: {
    zh: "收藏",
    en: "Favorites",
  },
  lut_grid_hue_red_short: {
    zh: "红",
    en: "Red",
  },
  lut_grid_hue_orange_short: {
    zh: "橙",
    en: "Orange",
  },
  lut_grid_hue_yellow_short: {
    zh: "黄",
    en: "Yellow",
  },
  lut_grid_hue_green_short: {
    zh: "绿",
    en: "Green",
  },
  lut_grid_hue_cyan_short: {
    zh: "青",
    en: "Cyan",
  },
  lut_grid_hue_blue_short: {
    zh: "蓝",
    en: "Blue",
  },
  lut_grid_hue_purple_short: {
    zh: "紫",
    en: "Purple",
  },
  lut_grid_hue_neutral_short: {
    zh: "中性",
    en: "Neutral",
  },
  lut_grid_recommendations: {
    zh: "推荐替换色",
    en: "Recommended Replacements",
  },
  lut_grid_used_in_image: {
    zh: "图中使用",
    en: "Used in image",
  },
  lut_grid_other_available: {
    zh: "其他可用",
    en: "Other available",
  },
  lut_grid_all_available: {
    zh: "全部可用",
    en: "All available",
  },
  lut_grid_no_match: {
    zh: "无匹配颜色",
    en: "No matching colors",
  },
  lut_grid_color_label: {
    zh: "颜色 {hex}",
    en: "Color {hex}",
  },
  lut_grid_color_fav: {
    zh: "已收藏",
    en: "Favorited",
  },
  lut_grid_dblclick_fav: {
    zh: "双击收藏",
    en: "Double-click to favorite",
  },
  lut_grid_dblclick_unfav: {
    zh: "双击取消收藏",
    en: "Double-click to unfavorite",
  },
  lut_grid_mode_swatch: {
    zh: "色块",
    en: "Swatch",
  },
  lut_grid_mode_card: {
    zh: "色卡",
    en: "Card",
  },
  lut_grid_card_a: {
    zh: "色卡 A",
    en: "Card A",
  },
  lut_grid_card_b: {
    zh: "色卡 B",
    en: "Card B",
  },

  // ==================== Replace Confirmation ====================
  replace_confirm_btn: {
    zh: "确认替换",
    en: "Confirm Replace",
  },
  replace_cancel_btn: {
    zh: "取消",
    en: "Cancel",
  },
  replace_preview_label: {
    zh: "替换预览",
    en: "Replace Preview",
  },

  // ==================== Image Upload ====================
  upload_drag_hint: {
    zh: "拖拽图片或点击上传",
    en: "Drag & drop image or click to upload",
  },

  // ==================== Unified Uploader ====================
  upload_unified_hint: {
    zh: "拖拽图片或点击上传（支持多选）",
    en: "Drag & drop or click to upload (multi-select)",
  },
  upload_tap_to_change: {
    zh: "点击更换",
    en: "Tap to change",
  },
  upload_unified_aria: {
    zh: "拖拽图片或点击上传文件",
    en: "Drag images or click to upload files",
  },
  upload_add_more: {
    zh: "添加更多图片",
    en: "Add more images",
  },
  upload_file_count: {
    zh: "已选 {count} 个文件",
    en: "{count} files selected",
  },
  upload_file_list_label: {
    zh: "已选文件列表",
    en: "Selected files list",
  },
  upload_delete_file: {
    zh: "删除 {name}",
    en: "Delete {name}",
  },

  // ==================== Zoomable Image ====================
  zoom_reset: {
    zh: "重置缩放",
    en: "Reset Zoom",
  },

  // ==================== Batch Result Summary ====================
  batch_success: {
    zh: "成功",
    en: "Success",
  },
  batch_total: {
    zh: "总计",
    en: "Total",
  },
  batch_failed: {
    zh: "失败",
    en: "Failed",
  },
  batch_download_zip: {
    zh: "下载 ZIP",
    en: "Download ZIP",
  },
  batch_download_zip_aria: {
    zh: "下载 ZIP 文件",
    en: "Download ZIP file",
  },
  batch_failed_files: {
    zh: "失败文件：",
    en: "Failed files:",
  },
  batch_failed_list_label: {
    zh: "失败文件列表",
    en: "Failed files list",
  },

  // ==================== Slicer Selector ====================
  slicer_open_in: {
    zh: "在 {name} 中打开",
    en: "Open in {name}",
  },
  slicer_generate_open_in: {
    zh: "生成并在 {name} 中打开",
    en: "Generate & open in {name}",
  },
  slicer_download_3mf: {
    zh: "下载 3MF",
    en: "Download 3MF",
  },
  slicer_generate_download: {
    zh: "生成并下载",
    en: "Generate & Download",
  },
  slicer_detecting: {
    zh: "正在检测切片软件...",
    en: "Detecting slicers...",
  },
  slicer_not_detected: {
    zh: "未检测到切片软件",
    en: "No slicers detected",
  },
  slicer_toggle_list: {
    zh: "切换切片软件列表",
    en: "Toggle slicer list",
  },
  slicer_preferred_mismatch: {
    zh: "当前导出格式为 {expected}，但操作栏启动目标是 {actual}",
    en: "Current export format targets {expected}, but the action bar is set to {actual}",
  },
  slicer_preferred_missing: {
    zh: "当前导出格式为 {name}，但本机未检测到对应切片软件",
    en: "Current export format targets {name}, but the matching slicer is not detected on this device",
  },

  // ==================== Crop Modal ====================
  crop_modal_title: {
    zh: "裁剪图片",
    en: "Crop Image",
  },
  crop_modal_close: {
    zh: "关闭",
    en: "Close",
  },
  crop_modal_original: {
    zh: "原图",
    en: "Original",
  },
  crop_modal_selection: {
    zh: "选区",
    en: "Selection",
  },
  crop_modal_free: {
    zh: "自由",
    en: "Free",
  },
  crop_modal_use_original: {
    zh: "使用原图",
    en: "Use Original",
  },
  crop_modal_confirm: {
    zh: "确认裁剪",
    en: "Confirm Crop",
  },

  // ==================== Five Color Query Panel ====================
  five_color_lut_label: {
    zh: "LUT 选择",
    en: "LUT Selection",
  },
  five_color_title: {
    zh: "五色配方查询",
    en: "Five-Color Recipe Query",
  },
  five_color_desc: {
    zh: "从基础色中选出 5 种颜色并查询叠层后的结果色，适合快速验证色片配方。",
    en: "Pick five base colors and query the blended result to validate layered color recipes quickly.",
  },
  five_color_palette: {
    zh: "基础色板",
    en: "Base Palette",
  },
  five_color_actions: {
    zh: "操作",
    en: "Actions",
  },
  five_color_lut_placeholder: {
    zh: "请选择 LUT",
    en: "Select LUT",
  },
  five_color_clear: {
    zh: "清除",
    en: "Clear",
  },
  five_color_undo: {
    zh: "撤销",
    en: "Undo",
  },
  five_color_reverse: {
    zh: "反序",
    en: "Reverse",
  },
  five_color_query: {
    zh: "查询",
    en: "Query",
  },
  five_color_query_loading: {
    zh: "查询中...",
    en: "Querying...",
  },
  five_color_close_error: {
    zh: "关闭错误",
    en: "Close error",
  },
  five_color_result_hex: {
    zh: "Hex",
    en: "Hex",
  },
  five_color_result_rgb: {
    zh: "RGB",
    en: "RGB",
  },
  five_color_result_row: {
    zh: "行号",
    en: "Row",
  },
  five_color_result_source: {
    zh: "来源",
    en: "Source",
  },
  five_color_result_color: {
    zh: "结果颜色 {hex}",
    en: "Result color {hex}",
  },
  five_color_result_panel: {
    zh: "查询结果",
    en: "Query Result",
  },
  five_color_not_found: {
    zh: "未找到匹配",
    en: "No match found",
  },
  five_color_selection_progress: {
    zh: "已选择 {count}/{total} 种颜色，请继续完成配方。",
    en: "{count}/{total} colors selected. Keep building the recipe.",
  },
  five_color_selected: {
    zh: "已选颜色 {n}: {name}",
    en: "Selected color {n}: {name}",
  },
  five_color_slot_empty: {
    zh: "颜色槽 {n}: 空",
    en: "Color slot {n}: empty",
  },
  five_color_select_color: {
    zh: "选择颜色 {name} ({hex})",
    en: "Select color {name} ({hex})",
  },
  five_color_no_base_colors: {
    zh: "未加载到基础颜色",
    en: "No base colors loaded",
  },
  five_color_select_lut_first: {
    zh: "请先选择 LUT 以加载基础颜色",
    en: "Select a LUT to load base colors",
  },

  // ==================== Widget Error ====================
  widget_error: {
    zh: "组件出错",
    en: "Widget error",
  },
  widget_retry: {
    zh: "重试",
    en: "Retry",
  },
  widget_expand: {
    zh: "展开",
    en: "Expand",
  },
  widget_collapse: {
    zh: "折叠",
    en: "Collapse",
  },

  // ==================== WikiTooltip ====================
  wiki_tooltip_link: {
    zh: "查看 Wiki 详情 ↗",
    en: "View Wiki Details ↗",
  },

  // ==================== Vectorizer Panel ====================
  "vec.title": {
    zh: "图像转矢量",
    en: "Image Vectorizer",
  },
  "vec.upload_hint": {
    zh: "拖放或点击上传图片进行矢量化",
    en: "Drag & drop or click to upload an image for vectorization",
  },
  "vec.basic_params": {
    zh: "基础参数",
    en: "Basic Parameters",
  },
  "vec.advanced_params": {
    zh: "高级参数",
    en: "Advanced Parameters",
  },
  "vec.output_enhance": {
    zh: "输出增强",
    en: "Output Enhancement",
  },

  // Core params
  "vec.num_colors": {
    zh: "颜色数量",
    en: "Number of Colors",
  },
  "vec.num_colors_auto": {
    zh: "自动",
    en: "Auto",
  },
  "vec.num_colors_manual": {
    zh: "手动",
    en: "Manual",
  },
  "vec.detail_level": {
    zh: "细节等级",
    en: "Detail Level",
  },
  "vec.detail_level_enable": {
    zh: "启用统一细节控制",
    en: "Enable Unified Detail Control",
  },
  "vec.detail_level_on": {
    zh: "启用",
    en: "On",
  },
  "vec.detail_level_off": {
    zh: "禁用",
    en: "Off",
  },
  "vec.smoothness": {
    zh: "平滑度",
    en: "Smoothness",
  },

  // Output enhancement
  "vec.svg_enable_stroke": {
    zh: "启用描边",
    en: "Enable Stroke",
  },
  "vec.svg_stroke_width": {
    zh: "描边宽度",
    en: "Stroke Width",
  },
  "vec.thin_line_max_radius": {
    zh: "薄线检测半径",
    en: "Thin Line Max Radius",
  },
  "vec.enable_coverage_fix": {
    zh: "启用覆盖修复",
    en: "Enable Coverage Fix",
  },
  "vec.min_coverage_ratio": {
    zh: "最小覆盖率",
    en: "Min Coverage Ratio",
  },

  // Advanced - Preprocessing
  "vec.adv_preprocess": {
    zh: "预处理",
    en: "Preprocessing",
  },
  "vec.smoothing_spatial": {
    zh: "空间平滑半径",
    en: "Spatial Smoothing",
  },
  "vec.smoothing_color": {
    zh: "颜色平滑半径",
    en: "Color Smoothing",
  },
  "vec.max_working_pixels": {
    zh: "最大工作像素数",
    en: "Max Working Pixels",
  },

  // Advanced - Segmentation
  "vec.adv_segmentation": {
    zh: "超像素分割",
    en: "Superpixel Segmentation",
  },
  "vec.slic_region_size": {
    zh: "超像素区域大小",
    en: "SLIC Region Size",
  },
  "vec.edge_sensitivity": {
    zh: "边缘敏感度",
    en: "Edge Sensitivity",
  },
  "vec.refine_passes": {
    zh: "边界细化次数",
    en: "Refine Passes",
  },
  "vec.enable_antialias_detect": {
    zh: "启用抗锯齿检测",
    en: "Antialiasing Detection",
  },
  "vec.aa_tolerance": {
    zh: "抗锯齿容差",
    en: "AA Tolerance",
  },

  // Advanced - Curve fitting
  "vec.adv_curve_fitting": {
    zh: "曲线拟合",
    en: "Curve Fitting",
  },
  "vec.curve_fit_error": {
    zh: "曲线拟合误差",
    en: "Curve Fit Error",
  },
  "vec.contour_simplify": {
    zh: "轮廓简化强度",
    en: "Contour Simplification",
  },
  "vec.merge_segment_tolerance": {
    zh: "线段合并容差",
    en: "Merge Segment Tolerance",
  },

  // Advanced - Filtering
  "vec.adv_filtering": {
    zh: "区域过滤",
    en: "Region Filtering",
  },
  "vec.min_region_area": {
    zh: "最小区域面积",
    en: "Min Region Area",
  },
  "vec.max_merge_color_dist": {
    zh: "最大合并色差",
    en: "Max Merge Color Dist",
  },
  "vec.min_contour_area": {
    zh: "最小轮廓面积",
    en: "Min Contour Area",
  },
  "vec.min_hole_area": {
    zh: "最小孔洞面积",
    en: "Min Hole Area",
  },
  "vec.submit": {
    zh: "开始矢量化",
    en: "Start Vectorization",
  },
  "vec.processing": {
    zh: "正在矢量化...",
    en: "Vectorizing...",
  },
  "vec.result_title": {
    zh: "矢量化结果",
    en: "Vectorization Result",
  },
  "vec.original": {
    zh: "原始图片",
    en: "Original",
  },
  "vec.svg_preview": {
    zh: "SVG 预览",
    en: "SVG Preview",
  },
  "vec.shapes": {
    zh: "形状数",
    en: "Shapes",
  },
  "vec.colors": {
    zh: "颜色数",
    en: "Colors",
  },
  "vec.download_svg": {
    zh: "下载 SVG",
    en: "Download SVG",
  },
  "vec.send_to_converter": {
    zh: "发送到图像转换",
    en: "Send to Image Converter",
  },
  "vec.error": {
    zh: "矢量化失败",
    en: "Vectorization Failed",
  },
  "vec.no_image": {
    zh: "请先上传图片",
    en: "Please upload an image first",
  },

  // ===== Vectorizer Parameter Hints =====
  "vec.hint_num_colors": {
    zh: "自动模式会检测图像的最优颜色数量。切换到手动模式可指定固定值（2-256）。",
    en: "Auto mode detects the optimal color count. Switch to Manual to specify a fixed value (2-256).",
  },
  "vec.hint_smoothness": {
    zh: "整体轮廓平滑度。0 = 保留所有细节；1 = 最大平滑。控制抽稀精度和平滑迭代。",
    en: "Overall contour smoothness. 0 = preserve all details; 1 = maximum smoothing. Controls decimation precision and smoothing iterations.",
  },
  "vec.hint_detail_level": {
    zh: "统一细节控制。启用后用一个滑块同时调整多个细节参数；禁用时使用各项独立参数。",
    en: "Unified detail control. When enabled, a single slider adjusts multiple detail parameters; when disabled, individual parameters are used.",
  },
  "vec.hint_svg_enable_stroke": {
    zh: "为 SVG 路径添加描边。可以减少色块之间的接缝（白线）。",
    en: "Add stroke to SVG paths. Helps reduce visible seams (white gaps) between color regions.",
  },
  "vec.hint_svg_stroke_width": {
    zh: "描边线条的宽度。增大可更好覆盖接缝，但可能导致细节丢失。",
    en: "Width of the stroke lines. Larger values cover seams better but may blur fine details.",
  },
  "vec.hint_thin_line_max_radius": {
    zh: "薄线检测的最大半径。用于检测并保留图像中的细线结构。",
    en: "Max radius for thin line detection. Used to detect and preserve thin structures in the image.",
  },
  "vec.hint_enable_coverage_fix": {
    zh: "启用后会扩展区域边界以确保完整覆盖画布，消除微小间隙。",
    en: "Expands region boundaries to ensure full canvas coverage, eliminating tiny gaps.",
  },
  "vec.hint_min_coverage_ratio": {
    zh: "画布最小覆盖率阈值。低于此值时会触发覆盖修复。通常保持接近 1.0。",
    en: "Minimum canvas coverage ratio threshold. Coverage fix is triggered below this value. Keep close to 1.0.",
  },
  "vec.hint_smoothing_spatial": {
    zh: "Mean Shift 空间半径。增大可降噪，但可能模糊细小结构。",
    en: "Mean Shift spatial radius. Larger values reduce noise but may blur fine structures.",
  },
  "vec.hint_smoothing_color": {
    zh: "Mean Shift 颜色半径。增大可合并相近颜色，减少颜色碎片。",
    en: "Mean Shift color radius. Larger values merge similar colors, reducing color fragmentation.",
  },
  "vec.hint_max_working_pixels": {
    zh: "内部处理的最大像素数。大图会被缩小到此限制以提升速度。增大可保留更多细节但更慢。",
    en: "Max pixels for internal processing. Large images are downscaled to this limit for speed. Increase to preserve more detail at the cost of speed.",
  },
  "vec.hint_slic_region_size": {
    zh: "超像素初始区域大小。小值产生更多超像素，保留更多细节但更慢。",
    en: "Initial superpixel region size. Smaller values create more superpixels with more detail but slower processing.",
  },
  "vec.hint_edge_sensitivity": {
    zh: "边缘检测敏感度。高值更积极地保留边缘，低值产生更平滑的分割。",
    en: "Edge detection sensitivity. Higher values preserve edges more aggressively; lower values produce smoother segmentation.",
  },
  "vec.hint_refine_passes": {
    zh: "边界细化迭代次数。更多次迭代产生更精确的区域边界，但增加处理时间。",
    en: "Boundary refinement iterations. More passes produce more precise region boundaries at the cost of processing time.",
  },
  "vec.hint_enable_antialias_detect": {
    zh: "检测并处理抗锯齿像素。对带有平滑边缘的图像效果好，但可能影响像素画风格图像。",
    en: "Detect and handle antialiased pixels. Works well for images with smooth edges but may affect pixel art style images.",
  },
  "vec.hint_aa_tolerance": {
    zh: "抗锯齿检测的颜色容差（LAB ΔE）。增大可检测更多抗锯齿像素。",
    en: "Color tolerance for antialiasing detection (LAB ΔE). Increase to detect more antialiased pixels.",
  },
  "vec.hint_curve_fit_error": {
    zh: "贝塞尔曲线拟合的最大误差（像素）。小值更精确但产生更多锚点；大值更平滑但可能丢失细节。",
    en: "Max error for Bezier curve fitting (pixels). Smaller values are more precise with more anchor points; larger values are smoother but may lose detail.",
  },
  "vec.hint_contour_simplify": {
    zh: "轮廓简化强度。增大可减少轮廓点数，使路径更简洁。",
    en: "Contour simplification strength. Increase to reduce contour points for cleaner paths.",
  },
  "vec.hint_merge_segment_tolerance": {
    zh: "共线线段合并容差。增大可合并更多近似共线的线段。",
    en: "Tolerance for merging collinear segments. Increase to merge more nearly-collinear segments.",
  },
  "vec.hint_min_region_area": {
    zh: "面积小于此值的区域会被合并到相邻区域。增大可减少小碎片。",
    en: "Regions smaller than this area are merged into neighbors. Increase to reduce small fragments.",
  },
  "vec.hint_max_merge_color_dist": {
    zh: "区域合并时允许的最大色差（LAB ΔE²）。增大可合并颜色差异更大的相邻区域。",
    en: "Max color distance for region merging (LAB ΔE²). Increase to merge neighbors with larger color differences.",
  },
  "vec.hint_min_contour_area": {
    zh: "面积小于此值的轮廓会被过滤掉。用于去除微小噪点形状。",
    en: "Contours smaller than this area are filtered out. Used to remove tiny noise shapes.",
  },
  "vec.hint_min_hole_area": {
    zh: "面积小于此值的孔洞会被填充。用于去除区域内的微小空洞。",
    en: "Holes smaller than this area are filled in. Used to remove tiny voids inside regions.",
  },

  app_logo_alt: {
    zh: "Lumina Studio 标志",
    en: "Lumina Studio logo",
  },
  common_preview_alt: {
    zh: "预览图片",
    en: "Preview image",
  },
  common_unit_mm: {
    zh: "毫米",
    en: "mm",
  },
  common_unit_px: {
    zh: "像素",
    en: "px",
  },
  crop_modal_axis_x: {
    zh: "X 轴",
    en: "X",
  },
  crop_modal_axis_y: {
    zh: "Y 轴",
    en: "Y",
  },
  action_generate_model_title: {
    zh: "生成 3D 模型",
    en: "Generate 3D Model",
  },
  action_generate_model_desc: {
    zh: "根据当前图像和 LUT 生成可打印的 3MF 模型文件。",
    en: "Generate a printable 3MF model from current image and LUT.",
  },
  action_zoom_icon: {
    zh: "缩放",
    en: "Zoom",
  },
  action_layer_prev_arrow: {
    zh: "<",
    en: "<",
  },
  action_layer_next_arrow: {
    zh: ">",
    en: ">",
  },
  action_close_overlay: {
    zh: "关闭预览",
    en: "Close preview",
  },
  action_close_icon: {
    zh: "✕",
    en: "✕",
  },
  five_color_combinations_loaded: {
    zh: "已加载 {count} 个有效组合",
    en: "{count} valid combinations loaded",
  },
  five_color_combinations_hint: {
    zh: "灰色选项表示当前选择路径下不可用的组合。",
    en: "Gray items are unavailable for the current selection path.",
  },
  five_color_error_close_icon: {
    zh: "✕",
    en: "✕",
  },
  five_color_not_found_suggestions_title: {
    zh: "建议操作：",
    en: "Suggestions:",
  },
  five_color_not_found_tip_reverse: {
    zh: "尝试使用反转操作来反转颜色顺序。",
    en: "Try the reverse order with the reverse action.",
  },
  five_color_not_found_tip_change: {
    zh: "尝试不同的颜色组合。",
    en: "Try a different color combination.",
  },
  five_color_not_found_tip_gray: {
    zh: "灰色选项表示该位置上的无效组合。",
    en: "Gray options indicate invalid combinations at that position.",
  },

  // ==================== Recipe Share Card ====================
  recipe_export_btn: {
    zh: "导出分享卡",
    en: "Export Share Card",
  },
  recipe_export_sidecar_btn: {
    zh: "导出 JSON",
    en: "Export JSON",
  },
  recipe_export_loading: {
    zh: "正在导出...",
    en: "Exporting...",
  },
  recipe_export_success: {
    zh: "分享卡已保存",
    en: "Share card saved",
  },
  recipe_export_error: {
    zh: "导出失败：{error}",
    en: "Export failed: {error}",
  },
  recipe_import_title: {
    zh: "导入分享卡",
    en: "Import Share Card",
  },
  recipe_import_source_label: {
    zh: "来源",
    en: "Source",
  },
  recipe_import_source_png: {
    zh: "PNG 分享卡",
    en: "PNG Share Card",
  },
  recipe_import_source_json: {
    zh: "JSON 配方文件",
    en: "JSON Recipe File",
  },
  recipe_import_version_label: {
    zh: "应用版本",
    en: "App Version",
  },
  recipe_import_created_label: {
    zh: "创建时间",
    en: "Created",
  },
  recipe_import_lut_label: {
    zh: "LUT",
    en: "LUT",
  },
  recipe_import_color_mode_label: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  recipe_import_size_label: {
    zh: "尺寸",
    en: "Size",
  },
  recipe_import_warnings_label: {
    zh: "警告",
    en: "Warnings",
  },
  recipe_import_confirm: {
    zh: "确认恢复",
    en: "Confirm Restore",
  },
  recipe_import_cancel: {
    zh: "取消",
    en: "Cancel",
  },
  recipe_import_success: {
    zh: "配方已恢复",
    en: "Recipe restored",
  },
  recipe_import_error: {
    zh: "导入失败：{error}",
    en: "Import failed: {error}",
  },
  recipe_import_not_share_card: {
    zh: "该 PNG 不包含 Lumina 配方数据",
    en: "This PNG does not contain Lumina recipe data",
  },
  recipe_export_with_sidecar: {
    zh: "同时导出 JSON",
    en: "Also export JSON",
  },
  recipe_custom_button: {
    zh: "自定义配方",
    en: "Custom Recipe",
  },
  recipe_custom_title: {
    zh: "自定义配方编辑器",
    en: "Custom Recipe Editor",
  },
  recipe_custom_close: {
    zh: "关闭",
    en: "Close",
  },
  recipe_custom_layer_count: {
    zh: "{count} 层",
    en: "{count} layers",
  },
  recipe_custom_layer_label: {
    zh: "第 {index} 层",
    en: "Layer {index}",
  },
  recipe_custom_add_layer: {
    zh: "添加层",
    en: "Add Layer",
  },
  recipe_custom_remove_layer: {
    zh: "删除层",
    en: "Remove Layer",
  },
  recipe_custom_move_up: {
    zh: "上移",
    en: "Move Up",
  },
  recipe_custom_move_down: {
    zh: "下移",
    en: "Move Down",
  },
  recipe_custom_predict: {
    zh: "预测颜色",
    en: "Predict Color",
  },
  recipe_custom_predicting: {
    zh: "正在预测…",
    en: "Predicting…",
  },
  recipe_custom_predict_hint: {
    zh: "点击“预测颜色”查看当前配方的预览颜色。",
    en: "Use Predict Color to preview the current recipe.",
  },
  recipe_custom_preview_color: {
    zh: "预览颜色",
    en: "Preview Color",
  },
  recipe_custom_rgb_label: {
    zh: "RGB",
    en: "RGB",
  },
  recipe_custom_lab_label: {
    zh: "Lab",
    en: "Lab",
  },
  recipe_custom_apply: {
    zh: "应用到选区",
    en: "Apply to Selection",
  },
  recipe_custom_applying: {
    zh: "正在应用…",
    en: "Applying…",
  },
  recipe_custom_region_required: {
    zh: "请先选中至少一个区域，再应用自定义配方。",
    en: "Select at least one region before applying a custom recipe.",
  },
  recipe_custom_region_count: {
    zh: "目标区域：{count}",
    en: "Target Regions: {count}",
  },
  recipe_custom_pattern_placeholder: {
    zh: "层色搜索，例如 WRYB?",
    en: "Pattern search, e.g. WRYB?",
  },
  recipe_custom_pattern_hint: {
    zh: "按层颜色快速填充。字母=颜色首字母，?=保留当前层，-=可选分隔。",
    en: "Quick-fill by layer pattern. Letter=color initial, ?=keep current, -=optional separator.",
  },
  recipe_custom_pattern_apply: {
    zh: "应用模式",
    en: "Apply Pattern",
  },
  recipe_custom_pattern_invalid: {
    zh: "无法识别的字符：{char}",
    en: "Unrecognized character: {char}",
  },
  recipe_custom_predict_failed: {
    zh: "颜色预测失败",
    en: "Color prediction failed",
  },
  recipe_custom_apply_failed: {
    zh: "应用自定义配方失败",
    en: "Failed to apply custom recipe",
  },
  recipe_import_lut_missing: {
    zh: "LUT 未找到，请手动选择兼容的 LUT",
    en: "LUT not found, please select a compatible LUT manually",
  },
  recipe_import_lut_degraded: {
    zh: "LUT 已降级匹配（名称相同但指纹不一致）",
    en: "LUT matched by name but fingerprint differs — colors may vary",
  },
  recipe_import_schema_newer: {
    zh: "配方版本较新，部分参数可能无法恢复",
    en: "Recipe uses a newer schema version — some parameters may not restore",
  },
  recipe_import_integrity_fail: {
    zh: "完整性校验失败，配方数据可能已损坏",
    en: "Integrity check failed — recipe data may be corrupted",
  },
  recipe_import_asset_corrupt: {
    zh: "素材数据损坏，无法恢复原始文件",
    en: "Asset data is corrupted — unable to restore original file",
  },

  lut_info_schema_label: {
    zh: "Schema",
    en: "Schema",
  },
  lut_info_capabilities_label: {
    zh: "能力",
    en: "Capabilities",
  },
  lut_info_predictive_enabled: {
    zh: "支持预测式匹配",
    en: "Predictive match enabled",
  },
  lut_info_predictive_disabled: {
    zh: "仅传统查表",
    en: "Legacy lookup only",
  },
  lut_info_dynamic_enabled: {
    zh: "支持动态层高",
    en: "Dynamic layer height enabled",
  },
  lut_info_dynamic_disabled: {
    zh: "固定层高",
    en: "Fixed layer height",
  },
  lut_info_dynamic_count_enabled: {
    zh: "支持动态层数",
    en: "Dynamic layer count enabled",
  },
  lut_info_dynamic_count_disabled: {
    zh: "固定层数",
    en: "Fixed layer count",
  },
  lut_info_custom_recipe_enabled: {
    zh: "支持自定义配方",
    en: "Custom recipe enabled",
  },
  lut_info_custom_recipe_disabled: {
    zh: "不支持自定义配方",
    en: "Custom recipe unavailable",
  },
  lut_info_source_kind_label: {
    zh: "来源类型",
    en: "Source Kind",
  },
  lut_info_supported_modes_label: {
    zh: "支持模式",
    en: "Supported Modes",
  },
  lut_info_capability_legacy_lookup: {
    zh: "传统查表",
    en: "Legacy lookup",
  },
  lut_info_capability_predictive_match: {
    zh: "预测式匹配",
    en: "Predictive match",
  },
  lut_info_capability_predictive_model: {
    zh: "预测模型",
    en: "Predictive model",
  },
  lut_info_capability_dynamic_layer_height: {
    zh: "动态层高",
    en: "Dynamic layer height",
  },
  lut_info_capability_dynamic_layer_count: {
    zh: "动态层数",
    en: "Dynamic layer count",
  },
  lut_info_capability_custom_recipe: {
    zh: "自定义配方",
    en: "Custom recipe",
  },
  lut_info_capability_native_reference: {
    zh: "原生参考源",
    en: "Native reference",
  },
  lut_compare_warning_schema_mismatch: {
    zh: "Schema 版本不一致：{schemaA} vs {schemaB}",
    en: "Schema versions differ: {schemaA} vs {schemaB}",
  },
  lut_compare_warning_predictive_mismatch: {
    zh: "预测式匹配支持不一致：{valueA} vs {valueB}",
    en: "Predictive match support differs: {valueA} vs {valueB}",
  },
  lut_compare_warning_dynamic_mismatch: {
    zh: "动态层高支持不一致：{valueA} vs {valueB}",
    en: "Dynamic layer height support differs: {valueA} vs {valueB}",
  },
  action_lut_match_label: {
    zh: "LUT 匹配",
    en: "LUT Match",
  },
  action_lut_match_legacy: {
    zh: "传统查表",
    en: "Legacy KD-tree",
  },
  action_lut_match_predictive: {
    zh: "预测式运行时",
    en: "Predictive Runtime",
  },
  action_lut_match_mode_key: {
    zh: "模式 {mode}",
    en: "Mode {mode}",
  },
  recipe_editor_button: {
    zh: "自定义配方",
    en: "Custom Recipe",
  },
  recipe_editor_title: {
    zh: "自定义配方编辑器",
    en: "Custom Recipe Editor",
  },
  recipe_editor_layers_label: {
    zh: "按层编辑当前选区的配方，并可直接预测颜色。",
    en: "Edit the per-layer recipe for the current selection and predict its color.",
  },
  recipe_editor_layer_n: {
    zh: "第 {n} 层",
    en: "Layer {n}",
  },
  recipe_editor_add_layer: {
    zh: "添加层",
    en: "Add Layer",
  },
  recipe_editor_remove_layer: {
    zh: "删除层",
    en: "Remove Layer",
  },
  recipe_editor_move_up: {
    zh: "上移",
    en: "Move Up",
  },
  recipe_editor_move_down: {
    zh: "下移",
    en: "Move Down",
  },
  recipe_editor_predict: {
    zh: "预测颜色",
    en: "Predict Color",
  },
  recipe_editor_predict_loading: {
    zh: "预测中...",
    en: "Predicting...",
  },
  recipe_editor_predict_failed: {
    zh: "颜色预测失败",
    en: "Color prediction failed",
  },
  recipe_editor_search: {
    zh: "搜索候选",
    en: "Search Recipes",
  },
  recipe_editor_search_loading: {
    zh: "搜索中...",
    en: "Searching...",
  },
  recipe_editor_search_placeholder: {
    zh: "按层搜索，如 W?BK*",
    en: "Search by layer pattern, e.g. W?BK*",
  },
  recipe_editor_search_results: {
    zh: "候选配方",
    en: "Candidate Recipes",
  },
  recipe_editor_search_failed: {
    zh: "配方搜索失败",
    en: "Recipe search failed",
  },
  recipe_editor_apply: {
    zh: "应用到选区",
    en: "Apply to Selection",
  },
  recipe_editor_apply_failed: {
    zh: "配方应用失败",
    en: "Failed to apply recipe override",
  },
  recipe_editor_clear: {
    zh: "清除覆盖",
    en: "Clear Override",
  },
  recipe_editor_no_region: {
    zh: "请先选择一个区域或选区。",
    en: "Select a region or active selection first.",
  },
  recipe_editor_upgrade_confirm: {
    zh: "当前全局层数为 {old}，应用该配方后会升到 {new} 层。继续吗？",
    en: "The current global layer count is {old}. Applying this recipe will upgrade it to {new}. Continue?",
  },
  cal_workflow_label: {
    zh: "工作流模式",
    en: "Workflow",
  },
  cal_substrate_id_label: {
    zh: "基板 ID",
    en: "Substrate ID",
  },
  cal_substrate_name_label: {
    zh: "基板名称",
    en: "Substrate Name",
  },
  cal_material_default_label: {
    zh: "默认材料",
    en: "Default Material",
  },
  cal_generate_single_stage_btn: {
    zh: "生成 Single-Stage Kit",
    en: "Generate Single-Stage Kit",
  },
  cal_download_kit: {
    zh: "下载 Kit ZIP",
    en: "Download Kit ZIP",
  },
  cal_download_manifest: {
    zh: "下载 Manifest",
    en: "Download Manifest",
  },
  cal_single_stage_jobs_title: {
    zh: "Single-Stage 任务",
    en: "Single-Stage Jobs",
  },
  cal_single_stage_jobs_desc: {
    zh: "每个颜色都会生成一个可打印的 3MF 任务",
    en: "One printable 3MF job is generated per color",
  },
  ext_workflow_label: {
    zh: "工作流模式",
    en: "Workflow",
  },
  ext_single_stage_upload_title: {
    zh: "Single-Stage 数据集上传",
    en: "Single-Stage Dataset Upload",
  },
  ext_single_stage_upload_desc: {
    zh: "上传按 {substrate}/{color}/ 结构打包的 ZIP 数据集",
    en: "Upload a ZIP dataset organized as {substrate}/{color}/",
  },
  ext_single_stage_zip_label: {
    zh: "数据集 ZIP",
    en: "Dataset ZIP",
  },
  ext_single_stage_extract_btn: {
    zh: "提取 1_single_stage.json",
    en: "Extract 1_single_stage.json",
  },
  ext_single_stage_download_json: {
    zh: "下载 1_single_stage.json",
    en: "Download 1_single_stage.json",
  },
  ext_single_stage_fit_btn: {
    zh: "继续拟合 Stage A",
    en: "Fit Stage A",
  },
  ext_single_stage_download_stage_a: {
    zh: "下载 stage_A_parameters.json",
    en: "Download stage_A_parameters.json",
  },
  ext_single_stage_summary_title: {
    zh: "数据集摘要",
    en: "Dataset Summary",
  },
  ext_single_stage_fit_summary_title: {
    zh: "Stage A 拟合摘要",
    en: "Stage A Fit Summary",
  },
  ext_single_stage_warnings_title: {
    zh: "提取警告",
    en: "Extraction Warnings",
  },
  cal_workflow_legacy: {
    zh: "传统 LUT",
    en: "Legacy LUT",
  },
  cal_workflow_single_stage: {
    zh: "梯度卡",
    en: "Gradient Card",
  },
  ext_workflow_legacy: {
    zh: "传统 LUT",
    en: "Legacy LUT",
  },
  ext_workflow_single_stage: {
    zh: "梯度卡",
    en: "Gradient Card",
  },
};
