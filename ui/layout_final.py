def create_about_tab(stats_component):
    """创建关于Tab"""
    with gr.TabItem("ℹ️ 关于 About", id=3):
        with gr.Row():
            with gr.Column(scale=4):
                gr.Markdown("""
                ## 🌟 Lumina Studio CMYK+W_TMP1 base on v1.4.2
                
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
        | **CMYK+W** | 🟨 Yellow | 🟣 Magenta | 🔵 Cyan | ⬜ White |
        
        > ⚠️ **注意**: CMYK+W模式的角点顺序是从底面（外观面）观看的结果
        
        ---
        
        ### 🔬 技术原理 Technology
        
        - **Beer-Lambert 光学混色** Optical Color Mixing
        - **KD-Tree 色彩匹配** Color Matching
        - **OpenCV 轮廓提取** Contour Extraction for Vector Mode
        - **SLIC 超像素分割** Superpixel Segmentation for Woodblock Mode
        - **K-Means 色彩量化** Color Quantization for Detail Preservation
        
        ---
        
        ### 📝 CMYK+W_TMP1 base on v1.4.2 更新日志 Changelog
        
        #### 🆕 CMYK+W 模式
        
        - ✅ **341色块校准板** - 19×18网格，可变层数(0-4层)
        - ✅ **5种材质支持** - White底座 + Cyan/Magenta/Yellow/Black色彩层
        - ✅ **阶梯高度网格** - 每个色块根据序列长度呈现不同高度
        - ✅ **固定1.0mm白色底座** - 更薄的打印件，更高的透光性
        - ✅ **动态LUT匹配** - 341个颜色序列的精确匹配
        
        ---
        
        ### 📝 v1.4 更新日志 Previous Changelog
        
        #### 🚀 核心功能：三大建模模式
        
        - ✅ **矢量模式（Vector）** - CAD级精度，平滑曲线（10 px/mm）
        - ✅ **版画模式（Woodblock）** ⭐ - SLIC超像素 + 细节保护
        - ✅ **像素模式（Voxel）** - 经典方块美学，像素艺术风格
        
        #### 🖼️ 版画模式技术栈
    
        - RAG智能合并（区分噪点与真实细节）
        - Mitre连接（保持尖锐角点，版画刀刻质感）
        
        #### 🎨 矢量模式升级
        
        - 超高精度矢量化（epsilon=0.1，~80-100点/cm）
        - 0.2mm喷嘴兼容（保留 ≥ 4像素² 特征）
        - 垂直层合并RLE（消除Z轴阶梯伪影）
        
        #### 🌈 色彩量化新架构
        
        - K-Means聚类（8-256色可调，默认16色）
        - "先聚类，后匹配"（速度提升1000×）
        - 双边滤波 + 中值滤波（消除碎片化区域）
        
        #### 其他改进
        
        - 📏 分辨率解耦（矢量/版画10px/mm，像素2.4px/mm）
        - 🎮 3D预览智能降采样（大模型自动简化）
        - 🚫 浏览器崩溃保护（检测复杂度，超200万像素禁用预览）
        
        ---
        
        ### 📝 v1.3 更新日志 Previous Changelog
        
        - ✅ **新增钥匙扣挂孔** Added keychain loop feature
        - ✅ 挂孔颜色自动检测 Auto-detect loop color from nearby pixels
        - ✅ 2D预览显示挂孔 2D preview shows loop
        - ✅ 修复3MF对象命名 Fixed 3MF object naming
        - ✅ 颜色提取/转换添加模式选择 Added color mode selection
        - ✅ 默认间隙改为0.82mm Default gap changed to 0.82mm
        - ✅ **新增3D实时预览** Added 3D preview with true colors
        
        ---
        
        ### 🚧 开发路线图 Roadmap
        
        - [✅] 4色基础模式 4-color base mode
        - [✅] 三种建模模式 Three modeling modes (Vector/Woodblock/Voxel)
        - [✅] 版画模式SLIC引擎 Woodblock mode SLIC engine
        - [✅] 钥匙扣挂孔 Keychain loop
        - [✅] **CMYK+W 模式** 5-color thin mode with variable layers
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
            CMYK+W_TMP1 base on v1.4.2 | 2026
        </div>
        """)

