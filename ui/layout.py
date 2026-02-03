"""
Lumina Studio - UI Layout
UI layout definition
"""

import gradio as gr     # type:ignore

from config import ColorSystem
from utils import Stats, LUTManager
from core.calibration import generate_calibration_board
from core.extractor import (
    rotate_image,
    draw_corner_points,
    run_extraction,
    probe_lut_cell,
    manual_fix_cell,
    generate_simulated_reference
)
from core.converter import (
    generate_preview_cached,
    render_preview,
    on_preview_click,
    update_preview_with_loop,
    on_remove_loop,
    generate_final_model
)
from .styles import CUSTOM_CSS
from .callbacks import (
    get_first_hint,
    get_next_hint,
    on_extractor_upload,
    on_extractor_mode_change,
    on_extractor_rotate,
    on_extractor_click,
    on_extractor_clear,
    on_lut_select,
    on_lut_upload_save
)


def create_app():
    """创建 Gradio 应用界面 | Create Gradio application interface"""
    with gr.Blocks(title="Lumina Studio", css=CUSTOM_CSS, theme=gr.themes.Soft()) as app:

        # Header with Language Selector
        with gr.Row():
            with gr.Column(scale=10):
                gr.HTML("""
                <div class="header-banner">
                    <h1>✨ Lumina Studio</h1>
                    <p>多材料3D打印色彩系统 | Multi-Material 3D Print Color System | v1.4.2-cmykw</p>
                </div>
                """)
            with gr.Column(scale=1, min_width=150):
                # Language selector - currently display only (i18n framework not implemented)
                gr.HTML("""
                <div style="text-align:right; padding:10px;">
                    <span style="background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                                 color:white; padding:5px 15px; border-radius:20px; font-weight:bold; white-space: nowrap;
                                 cursor: default; user-select: none;" title="界面已双语显示 / UI is bilingual">
                        🌐 中文 / EN
                    </span>
                </div>
                """)

        # Stats Bar
        stats = Stats.get_all()
        stats_html = gr.HTML(f"""
        <div class="stats-bar">
            📊 累计生成 Total: 
            <strong>{stats.get('calibrations', 0)}</strong> 校准板 Calibrations | 
            <strong>{stats.get('extractions', 0)}</strong> 颜色提取 Extractions | 
            <strong>{stats.get('conversions', 0)}</strong> 模型转换 Conversions
        </div>
        """)

        # Main Tabs
        with gr.Tabs() as tabs:

            # ═══════════════════════════════════════════════════════════════
            # TAB 1: Image Converter
            # ═══════════════════════════════════════════════════════════════
            create_converter_tab()

            # ═══════════════════════════════════════════════════════════════
            # TAB 2: Calibration Generator
            # ═══════════════════════════════════════════════════════════════
            create_calibration_tab()

            # ═══════════════════════════════════════════════════════════════
            # TAB 3: Color Extractor
            # ═══════════════════════════════════════════════════════════════
            create_extractor_tab()

            # ═══════════════════════════════════════════════════════════════
            # TAB 4: About
            # ═══════════════════════════════════════════════════════════════
            create_about_tab(stats_html)

        # Footer
        gr.HTML("""
        <div class="footer">
            <p>💡 提示 Tip: 使用高质量的PLA/PETG basic材料可获得最佳效果 | Use high-quality translucent PLA/PETG basic for best results</p>
        </div>
        """)

    return app


def create_calibration_tab():
    """创建校准板生成Tab"""
    with gr.TabItem("📐 校准板 Calibration", id=1):
        cal_desc = gr.Markdown("""
        ### 第二步：生成校准板 | Step 2: Generate Calibration Board
        生成1024种颜色的校准板，打印后用于提取打印机的实际色彩数据。
        Generate a 1024-color calibration board to extract your printer's actual color data.
        """)

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("#### ⚙️ 参数 Parameters")
                cal_mode = gr.Radio(
                    choices=[
                        "CMYW (Cyan/Magenta/Yellow)", 
                        "RYBW (Red/Yellow/Blue)",
                        "W+CMYK (341 Swatches)"
                    ],
                    value="RYBW (Red/Yellow/Blue)",
                    label="色彩模式 Color Mode"
                )
                cal_block_size = gr.Slider(3, 10, 5, step=1, label="色块尺寸 Block Size (mm)")
                cal_gap = gr.Slider(0.4, 2.0, 0.82, step=0.02, label="间隙 Gap (mm)")
                cal_backing = gr.Dropdown(
                    choices=["White", "Cyan", "Magenta", "Yellow", "Red", "Blue"],
                    value="White",
                    label="底板颜色 Backing Color"
                )
                cal_btn = gr.Button("🚀 生成 Generate", variant="primary", elem_classes=["primary-btn"])
                cal_log = gr.Textbox(label="状态 Status", interactive=False)

            with gr.Column(scale=1):
                gr.Markdown("#### 👁️ 预览 Preview")
                cal_preview = gr.Image(label="Calibration Preview", show_label=False, show_fullscreen_button=True)
                cal_file = gr.File(label="下载 Download 3MF")

        cal_btn.click(
            generate_calibration_board,
            inputs=[cal_mode, cal_block_size, cal_gap, cal_backing],
            outputs=[cal_file, cal_preview, cal_log]
        )


def create_extractor_tab():
    """创建颜色提取Tab"""
    with gr.TabItem("🎨 颜色提取 Extractor", id=2):
        gr.Markdown("""
        ### 第三步：提取颜色数据 | Step 3: Extract Color Data
        拍摄打印好的校准板照片，提取真实的色彩数据生成 LUT 文件。
        Take a photo of your printed calibration board to extract real color data.
        """)

        ext_state_img = gr.State(None)
        ext_state_pts = gr.State([])
        ext_curr_coord = gr.State(None)
        ref_img = generate_simulated_reference("RYBW")  # Default mode

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("#### 📸 上传照片 Upload Photo")

                ext_color_mode = gr.Radio(
                    choices=[
                        "CMYW (Cyan/Magenta/Yellow)", 
                        "RYBW (Red/Yellow/Blue)",
                        "W+CMYK (341 Swatches)"
                    ],
                    value="RYBW (Red/Yellow/Blue)",
                    label="🎨 色彩模式 Color Mode"
                )

                ext_img_in = gr.Image(
                    label="校准板照片 Calibration Photo", 
                    type="numpy", 
                    interactive=True, 
                    show_fullscreen_button=False,
                    show_download_button=False,
                    elem_classes=["no-clear-btn"]
                )

                with gr.Row():
                    ext_rot_btn = gr.Button("↺ 旋转 Rotate")
                    ext_clear_btn = gr.Button("🗑️ 重置 Reset")

                gr.Markdown("#### 🔧 校正参数 Correction")
                with gr.Row():
                    ext_wb = gr.Checkbox(label="自动白平衡 Auto WB", value=True)
                    ext_bf = gr.Checkbox(label="暗角校正 Vignette", value=False)

                ext_zoom = gr.Slider(0.8, 1.2, 1.0, step=0.005, label="缩放 Zoom")
                ext_barrel = gr.Slider(-0.2, 0.2, 0.0, step=0.01, label="畸变 Distortion")
                ext_off_x = gr.Slider(-30, 30, 0, step=1, label="X偏移 Offset X")
                ext_off_y = gr.Slider(-30, 30, 0, step=1, label="Y偏移 Offset Y")

                ext_run_btn = gr.Button("🚀 提取 Extract", variant="primary", elem_classes=["primary-btn"])
                ext_log = gr.Textbox(label="状态 Status", interactive=False)

            with gr.Column(scale=1):
                ext_hint = gr.Markdown("#### 👉 点击 Click: **White (左上 Top-Left)**")
                ext_work_img = gr.Image(
                    label="标记图 Marked", 
                    show_label=False, 
                    interactive=False, 
                    show_fullscreen_button=False, 
                    show_download_button=False,
                    elem_classes=["no-clear-btn"]
                )

                with gr.Row():
                    with gr.Column():
                        gr.Markdown("#### 📍 采样预览 Sampling")
                        ext_warp_view = gr.Image(show_label=False, show_fullscreen_button=True)
                    with gr.Column():
                        gr.Markdown("#### 🎯 参考 Reference")
                        ext_ref_view = gr.Image(show_label=False, value=ref_img, interactive=False, show_fullscreen_button=True)

                with gr.Row():
                    with gr.Column():
                        gr.Markdown("#### 📊 结果 Result (点击修正 Click to fix)")
                        ext_lut_view = gr.Image(show_label=False, interactive=False, show_fullscreen_button=True)
                    with gr.Column():
                        gr.Markdown("#### 🛠️ 手动修正 Manual Fix")
                        ext_probe_html = gr.HTML("点击左侧色块 Click cell on left...")
                        ext_picker = gr.ColorPicker(label="替换颜色 Override", value="#FF0000")
                        ext_fix_btn = gr.Button("🔧 应用 Apply")
                        ext_dl_btn = gr.File(label="下载 Download .npy")

        # Event handlers for extractor
        ext_img_in.upload(
            on_extractor_upload,
            [ext_img_in, ext_color_mode],
            [ext_state_img, ext_work_img, ext_state_pts, ext_curr_coord, ext_hint, ext_ref_view]
        )

        ext_color_mode.change(
            on_extractor_mode_change,
            [ext_state_img, ext_color_mode],
            [ext_state_img, ext_state_pts, ext_hint, ext_work_img, ext_ref_view]
        )

        ext_rot_btn.click(
            on_extractor_rotate,
            [ext_state_img, ext_color_mode],
            [ext_state_img, ext_work_img, ext_state_pts, ext_hint]
        )

        ext_work_img.select(
            on_extractor_click,
            [ext_state_img, ext_state_pts, ext_color_mode],
            [ext_work_img, ext_state_pts, ext_hint]
        )

        ext_clear_btn.click(
            on_extractor_clear,
            [ext_state_img, ext_color_mode],
            [ext_work_img, ext_state_pts, ext_hint]
        )

        extract_inputs = [ext_state_img, ext_state_pts, ext_off_x, ext_off_y,
                          ext_zoom, ext_barrel, ext_wb, ext_bf, ext_color_mode]
        extract_outputs = [ext_warp_view, ext_lut_view, ext_dl_btn, ext_log]

        ext_run_btn.click(run_extraction, extract_inputs, extract_outputs)

        for s in [ext_off_x, ext_off_y, ext_zoom, ext_barrel]:
            s.release(run_extraction, extract_inputs, extract_outputs)

        ext_lut_view.select(probe_lut_cell, [ext_color_mode], [ext_probe_html, ext_picker, ext_curr_coord])
        ext_fix_btn.click(manual_fix_cell, [ext_curr_coord, ext_picker, ext_color_mode], [ext_lut_view, ext_log])


def create_converter_tab():
    """创建图像转换Tab"""
    with gr.TabItem("💎 图像转换 Converter", id=0):
        gr.Markdown("""
        ### 第一步：转换图像 | Step 1: Convert Image
        **两种建模模式**：高保真（RLE无缝拼接）、像素艺术（方块风格）
        
        **流程**: 上传LUT和图像 → 选择建模模式 → 调整色彩细节 → 预览 → 生成
        """)

        # State variables
        conv_loop_pos = gr.State(None)  # Loop position (x, y)
        conv_preview_cache = gr.State(None)  # Cache preview data

        with gr.Row():
            # Left: Input and parameters
            with gr.Column(scale=1):
                gr.Markdown("#### 📁 输入 Input")
                
                # ========== LUT Preset Selector (Upstream Feature) ==========
                with gr.Group():
                    gr.Markdown("**校准数据 Calibration Data (.npy)**")
                    
                    # LUT selection dropdown
                    conv_lut_dropdown = gr.Dropdown(
                        choices=LUTManager.get_lut_choices(),
                        label="选择预设 Select Preset",
                        value=None,
                        interactive=True,
                        info="从预设库中选择LUT | Select from library"
                    )
                    
                    # Micro upload area (auto-save)
                    conv_lut_upload = gr.File(
                        label="",
                        show_label=False,
                        file_types=['.npy'],
                        height=60,
                        elem_classes=["micro-upload"]
                    )
                    
                    # Status hint
                    conv_lut_status = gr.Markdown(
                        value="💡 拖放.npy文件自动添加 | Drop .npy to add",
                        visible=True
                    )
                
                # Hidden State to store actual LUT path
                conv_lut_path = gr.State(None)
                # ========== END LUT SELECTOR ==========
                
                conv_img = gr.Image(label="输入图像 Input Image", type="filepath")

                gr.Markdown("#### ⚙️ 参数 Parameters")
                conv_color_mode = gr.Radio(
                    choices=[
                        "CMYW (Cyan/Magenta/Yellow)", 
                        "RYBW (Red/Yellow/Blue)",
                        "W+CMYK (341 Swatches)"
                    ],
                    value="RYBW (Red/Yellow/Blue)",
                    label="色彩模式 Color Mode"
                )
                conv_structure = gr.Radio(
                    ["双面 (钥匙扣) Double-Sided", "单面 (浮雕) Single-Sided"],
                    value="双面 (钥匙扣) Double-Sided",
                    label="结构 Structure"
                )

                # ========== Modeling Mode Controls (Upstream Consolidated) ==========
                conv_modeling_mode = gr.Radio(
                    choices=[
                        "高保真 (细节优先) High-Fidelity (Detail)",
                        "像素艺术 (方块风格) Pixel Art (Blocky)"
                    ],
                    value="高保真 (细节优先) High-Fidelity (Detail)",
                    label="🎨 建模模式 Modeling Mode",
                    info="高保真：RLE无缝拼接，水密模型 | 像素艺术：经典方块美学"
                )

                conv_quantize_count = gr.Slider(
                    minimum=8, maximum=256, step=8, value=64,
                    label="🎨 色彩细节 Color Detail",
                    info="颜色数量越多细节越丰富，但生成越慢 | Higher = More detail, Slower"
                )
                # ========== END CONTROLS ==========

                conv_auto_bg = gr.Checkbox(label="🗑️ 移除背景 Remove Background", value=True,
                                          info="自动移除图像背景色 | Auto remove background")
                conv_tol = gr.Slider(0, 150, 40, label="容差 Tolerance",
                                    info="背景容差值 (0-150)，值越大移除越多 | Higher = Remove more")

                conv_width = gr.Slider(20, 400, 60, label="宽度 Width (mm)")
                conv_thick = gr.Slider(0.2, 3.5, 1.2, step=0.08, label="背板 Spacer (mm)")

                conv_preview_btn = gr.Button("👁️👁️ 生成预览 Generate Preview", variant="secondary", size="lg")

            # Middle: Preview edit area
            with gr.Column(scale=2):
                gr.Markdown("#### 🎨 2D预览 - 点击图片放置挂孔位置 | 2D Preview - Click to place loop")

                # Preview image - not interactive for upload, but clickable
                conv_preview = gr.Image(
                    label="",
                    type="numpy",
                    height=500,
                    interactive=False,  # 禁止拖拽上传
                    show_label=False,
                    show_fullscreen_button=True
                )

                # Loop settings
                with gr.Group():
                    gr.Markdown("##### 🔗 挂孔设置 Loop Settings")
                    with gr.Row():
                        conv_add_loop = gr.Checkbox(label="启用挂孔 Enable Loop", value=False)
                        conv_remove_loop = gr.Button("🗑️ 移除挂孔 Remove Loop", size="sm")
                    with gr.Row():
                        conv_loop_width = gr.Slider(2, 10, 4, step=0.5, label="宽度 Width (mm)")
                        conv_loop_length = gr.Slider(4, 15, 8, step=0.5, label="长度 Length (mm)")
                        conv_loop_hole = gr.Slider(1, 5, 2.5, step=0.25, label="孔径 Hole (mm)")
                    with gr.Row():
                        conv_loop_angle = gr.Slider(-180, 180, 0, step=5, label="旋转角度 Angle°")
                        conv_loop_info = gr.Textbox(label="挂孔位置 Position", interactive=False, scale=2)

                conv_log = gr.Textbox(label="状态 Status", lines=6, interactive=False, max_lines=10, show_label=True)

            # Right: Output
            with gr.Column(scale=1):
                conv_btn = gr.Button("🚀 生成3MF Generate 3MF", variant="primary", size="lg")
                gr.Markdown("#### 🎮 3D预览 3D Preview")
                conv_3d_preview = gr.Model3D(
                    label="3D",
                    clear_color=[0.9, 0.9, 0.9, 1.0],
                    height=280
                )
                gr.Markdown("#### 📁 下载 Download")
                conv_file = gr.File(label="3MF文件")

        # ===== Event Binding =====
        
        # LUT selection event
        conv_lut_dropdown.change(
            on_lut_select,
            inputs=[conv_lut_dropdown],
            outputs=[conv_lut_path, conv_lut_status]
        )
        
        # LUT upload event (auto-save)
        conv_lut_upload.upload(
            on_lut_upload_save,
            inputs=[conv_lut_upload],
            outputs=[conv_lut_dropdown, conv_lut_status]
        )

        # Generate preview
        conv_preview_btn.click(
            generate_preview_cached,
            inputs=[conv_img, conv_lut_path, conv_width, conv_auto_bg, conv_tol, conv_color_mode],
            outputs=[conv_preview, conv_preview_cache, conv_log]
        )

        # Click preview image to place loop
        conv_preview.select(
            on_preview_click,
            inputs=[conv_preview_cache, conv_loop_pos],
            outputs=[conv_loop_pos, conv_add_loop, conv_loop_info]
        ).then(
            update_preview_with_loop,
            inputs=[conv_preview_cache, conv_loop_pos, conv_add_loop,
                   conv_loop_width, conv_loop_length, conv_loop_hole, conv_loop_angle],
            outputs=[conv_preview]
        )

        # Remove loop
        conv_remove_loop.click(
            on_remove_loop,
            outputs=[conv_loop_pos, conv_add_loop, conv_loop_angle, conv_loop_info]
        ).then(
            update_preview_with_loop,
            inputs=[conv_preview_cache, conv_loop_pos, conv_add_loop,
                   conv_loop_width, conv_loop_length, conv_loop_hole, conv_loop_angle],
            outputs=[conv_preview]
        )

        # Update preview in real-time when loop parameters change
        loop_params = [conv_loop_width, conv_loop_length, conv_loop_hole, conv_loop_angle]
        for param in loop_params:
            param.change(
                update_preview_with_loop,
                inputs=[conv_preview_cache, conv_loop_pos, conv_add_loop,
                       conv_loop_width, conv_loop_length, conv_loop_hole, conv_loop_angle],
                outputs=[conv_preview]
            )

        # Generate final model
        conv_btn.click(
            generate_final_model,
            inputs=[conv_img, conv_lut_path, conv_width, conv_thick,
                    conv_structure, conv_auto_bg, conv_tol, conv_color_mode,
                    conv_add_loop, conv_loop_width, conv_loop_length, conv_loop_hole, conv_loop_pos,
                    conv_modeling_mode, conv_quantize_count],
            outputs=[conv_file, conv_3d_preview, conv_preview, conv_log]
        )


def create_about_tab(stats_component):
    """创建关于Tab"""
    with gr.TabItem("ℹ️ 关于 About", id=3):
        with gr.Row():
            with gr.Column(scale=4):
                gr.Markdown("""
                ## 🌟 Lumina Studio v1.4.2-cmykw
                
                **多材料3D打印色彩系统** | Multi-Material 3D Print Color System
                
                让FDM打印也能拥有精准的色彩还原 | Accurate color reproduction for FDM printing
                """)
            with gr.Column(scale=1):
                reset_btn = gr.Button("🗑️ 重置统计数据 Reset Stats", variant="secondary")
                reset_status = gr.Markdown("")

        def handle_reset_stats():
            new_stats = Stats.reset_all()
            new_html = f"""
            <div class="stats-bar">
                📊 累计生成 Total: 
                <strong>{new_stats.get('calibrations', 0)}</strong> 校准板 Calibrations | 
                <strong>{new_stats.get('extractions', 0)}</strong> 颜色提取 Extractions | 
                <strong>{new_stats.get('conversions', 0)}</strong> 模型转换 Conversions
            </div>
            """
            return new_html, "✅ 已重置 Reset Complete"

        reset_btn.click(
            handle_reset_stats,
            outputs=[stats_component, reset_status]
        )

        gr.Markdown("""
        ---
        
        ### 📖 使用流程 Workflow
        
        1. **生成校准板 Generate Calibration** → 打印1024色校准网格 Print 1024-color grid
        2. **提取颜色 Extract Colors** → 拍照并提取打印机实际色彩 Photo → extract real colors
        3. **转换图像 Convert Image** → 将图片转为多层3D模型 Image → multi-layer 3D model
        
        ---
        
        ### 🎨 色彩模式定位点顺序 Color Mode Corner Order
        
        | 模式 Mode | 左上 TL | 右上 TR | 右下 BR | 左下 BL |
        |-----------|---------|---------|---------|---------|
        | **RYBW** | ⬜ White | 🟥 Red | 🟦 Blue | 🟨 Yellow |
        | **CMYW** | ⬜ White | 🔵 Cyan | 🟣 Magenta | 🟨 Yellow |
        | **W+CMYK (341)** | 🟨 Yellow | 🟣 Magenta | 🔵 Cyan | ⬜ White |
        
        > ⚠️ **注意**: CMYK+W模式的角点顺序是从正面（外观面）观看的结果，和其他模式相反。
        
        ---
        
        ### 🔬 技术原理 Technology
        
        - **Beer-Lambert 光学混色** Optical Color Mixing
        - **KD-Tree 色彩匹配** Color Matching
        - **RLE 几何生成** Run-Length Encoding for Geometry
        - **K-Means 色彩量化** Color Quantization for Detail Preservation
        
        ---
        
        ### 📝 v1.4.2-cmykw 更新日志 Changelog
        
        #### 🆕 W+CMYK 341色块模式
        
        - ✅ **341色块校准板** - 19×18网格，可变层数(0-4层)
        - ✅ **5种材质支持** - White底座 + Cyan/Magenta/Yellow/Black色彩层
        - ✅ **阶梯高度网格** - 每个色块根据序列长度呈现不同高度
        - ✅ **固定1.0mm白色底座** - 更薄的打印件，更高的透光性
        - ✅ **动态LUT匹配** - 341个颜色序列的精确匹配

        #### 🐛 Bug修复 Bug Fixes
        - 修复了一些已知问题 Fixed some known issues
        - 优化了性能和稳定性 Improved performance and stability
        
        ---
        
        ### 📝 v1.4.1 更新日志 Changelog
        
        #### 🚀 建模模式整合 Modeling Mode Consolidation
        
        - **高保真模式取代矢量和版画模式** High-Fidelity Mode Replaces Vector & Woodblock
        - **优化 RLE 几何引擎** Optimized RLE geometry engine for water-tight meshes
        
        ---
        
        ### 📝 v1.4.1 更新日志 Previous Changelog
        
        - **语言切换功能** Language Switching Feature
        - **LUT 预设库** LUT Preset Selector
        
        ---
        
        ### 📝 v1.4 更新日志 Previous Changelog
        
        - ✅ **高保真模式（High-Fidelity）** - RLE算法，无缝拼接，水密模型（10 px/mm）
        - ✅ **像素艺术模式（Pixel Art）** - 经典方块美学，像素艺术风格
        - ✅ **色彩量化架构** K-Means聚类（8-256色可调，默认64色）
        
        ---
        
        ### 🚧 开发路线图 Roadmap
        
        - [✅] 4色基础模式 4-color base mode
        - [✅] 两种建模模式 Two modeling modes (High-Fidelity/Pixel Art)
        - [✅] RLE几何引擎 RLE geometry engine
        - [✅] 钥匙扣挂孔 Keychain loop
        - [✅] **W+CMYK 341色块模式** 5-color thin mode with variable layers
        - [🚧] 漫画模式 Manga mode (Ben-Day dots simulation)
        - [ ] 6色扩展模式 6-color extended mode
        - [ ] 8色专业模式 8-color professional mode
        - [ ] 拼豆模式 Perler bead mode
        
        ---
        
        ### 📄 许可证 License
        
        **CC BY-NC-SA 4.0** - Attribution-NonCommercial-ShareAlike
        
        **商业豁免 Commercial Exemption**: 个人创作者、街边摊贩、小型私营企业可免费使用本软件生成模型并销售实体打印品。
        
        Individual creators, street vendors, and small businesses may freely use this software to generate models and sell physical prints.
        
        ---
        
        ### 🙏 致谢 Acknowledgments
        
        特别感谢 Special thanks to:
        - **HueForge** - 在FDM打印中开创光学混色技术 Pioneering optical color mixing
        - **AutoForge** - 让多色工作流民主化 Democratizing multi-color workflows
        - **3D打印社区** - 持续创新 Continuous innovation
        
        ---
        
        <div style="text-align:center; color:#888; margin-top:20px;">
            Made with ❤️ by [MIN]<br>
            v1.4.2-cmykw | 2026
        </div>
        """)

