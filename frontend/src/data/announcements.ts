export interface LocalizedText {
  zh: string;
  en: string;
}

export interface AnnouncementSection {
  category: LocalizedText;
  items: LocalizedText[];
}

export interface AnnouncementEntry {
  version: string;
  title: LocalizedText;
  sections: AnnouncementSection[];
}

export const ANNOUNCEMENTS: ReadonlyArray<AnnouncementEntry> = [
  {
    version: "2026-04-20",
    title: {
      zh: "Lumina Layers — 自定义配方更稳了",
      en: "Lumina Layers — Custom recipe, stabilised",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "自定义配方编辑器支持虚拟耗材：LUT 里没有的原色（比如 CMYW LUT 想要黑）可以直接在下拉里选，3MF 导出时会作为独立对象自动带上，不再需要手工编辑切片",
            en: "Custom recipe editor now supports virtual materials: primaries the LUT lacks (e.g. Black on a CMYW LUT) can be picked straight from the dropdown and are exported as separate 3MF objects, so no manual slicing tweaks are needed",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "自定义配方对话框聚焦到最核心的动作：每层直接从 LUT 调色板里选材料，下拉菜单不再是空的，色块会显示该材料的真实颜色而不是灰色",
            en: "The custom recipe dialog focuses on the core action: pick a material per layer from the LUT palette, the dropdown is no longer empty, and each swatch shows that material's real colour instead of a grey placeholder",
          },
          {
            zh: "没有前向模型的 LUT（例如材料档案 / 原生包）也能应用自定义配方了：后端会用最顶层通道的纯色堆叠作为兜底预览色，手动选材料的编辑不会再被 \"No predictive runtime\" 挡住",
            en: "Custom recipes now apply even on LUTs without a forward model (e.g. material archives / native bundles): the backend falls back to the top layer's pure-stack colour so manual edits are no longer blocked by \"No predictive runtime\"",
          },
          {
            zh: "打开自定义配方时，每层会自动预设为该色块已经匹配好的配方，而不是默认全白；只改一两层时其它层不会被覆盖",
            en: "Opening the custom recipe dialog now pre-populates every layer with the swatch's real matched recipe instead of the all-White default, so tweaking one or two layers no longer wipes the rest of the stack",
          },
          {
            zh: "应用自定义配方后，分层预览会重新拉取每一层，不再出现 \"只有被改过的层有颜色、其它层灰掉\" 的情况",
            en: "After applying a custom recipe, the per-layer preview re-fetches every layer so the old \"only overridden layers are coloured, the rest stay grey\" artefact is gone",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "后端 422 验证错误现在会写入结构化日志并回传具体字段信息，对话框能直接告诉你哪个字段不对，而不是笼统的 \"请求失败 status 422\"",
            en: "Backend 422 validation errors are now written to structured logs and surfaced with concrete field details, so the dialog tells you exactly which field is wrong instead of a generic \"request failed with status 422\"",
          },
          {
            zh: "耗材档案模式下的自定义配方预测与应用不再报 \"LUT/source file missing\" 409，整套流程走通",
            en: "Custom recipe prediction and apply no longer surface a \"LUT/source file missing\" 409 in Material Archive mode; the full flow works end to end",
          },
          {
            zh: "扩展配方层数时的填充修正：模型外的透明背景保持透明，不再被一圈白色 mesh 包裹；模型内未改动的像素则延用背板材料，不会出现额外层塌成空层的情况",
            en: "Layer-count extension padding fixed: transparent background outside the model stays transparent (no more white ring mesh around the silhouette), while untouched interior pixels keep the backing material (no more collapsed extra layers inside the model)",
          },
        ],
      },
    ],
  },
  {
    version: "2026-04-19",
    title: {
      zh: "Lumina Layers v2.0.0 — 近三天的大更新",
      en: "Lumina Layers v2.0.0 — Highlights from the past three days",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "梯度卡收纳盒生成器上线：一键生成用于收纳梯度校准卡的分格打印盒模型，卡片按品牌 / 耗材分格存放不易乱",
            en: "Gradient-card storage box generator: print a slotted box that organises your calibration cards by brand and material",
          },
          {
            zh: "梯度色卡：打印一张梯度卡扫入，自动提取该耗材的色彩物理参数入库，单卷耗材即可独立完成校准",
            en: "Gradient card calibration: print one card, scan it back in, and the physical colour parameters for that single filament are extracted into the library",
          },
          {
            zh: "耗材库支持自定义组合：把已校准的耗材自由拼成多色打印配色方案；档案按品牌 / 耗材两级目录整理，支持批量导入导出 ZIP",
            en: "Material library now supports custom bundles: freely combine calibrated filaments into multi-colour palettes; archives are organised by brand / material and support bulk ZIP import / export",
          },
          {
            zh: "3MF 底板层高修改器（Bambu）：可独立控制底板层高",
            en: "Bambu 3MF base-plate layer-height editor: control the base plate's layer height independently",
          },
          {
            zh: "0.2 mm 喷嘴元数据方案：小喷嘴用户开箱即用",
            en: "0.2 mm nozzle metadata preset: works out of the box for fine-nozzle users",
          },
          {
            zh: "LUT 下拉框新增刷新按钮：切换或放入新的 LUT 后不用重启页面，点一下即可重新加载",
            en: "LUT dropdown gains a refresh button: no page reload needed after swapping in a new LUT",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "颜色替换后，鼠标悬停“分层颜色”现在会同步更新，不再显示替换前的旧颜色",
            en: "After a colour replacement, the hover inspector's per-layer colours stay in sync instead of showing stale pre-replacement values",
          },
          {
            zh: "调色板顶部工具栏重新分组：历史 / 选择模式 / 自由色 / 配方 / 悬停显示 各自独立卡片，一眼分清",
            en: "Palette toolbar is regrouped into tinted cards — history, selection mode, free colour, recipe, and hover display — so each group is easier to spot",
          },
          {
            zh: "自定义配方编辑器升级：每层带颜色色块，目标色支持直接改 hex / Lab 双向联动；应用过的配方进历史，再点一下就能复用；材料档案模式下还会按目标色推荐相近配方。",
            en: "Custom recipe editor upgrade: each layer now shows a colour swatch, the target colour can be edited via hex or Lab with two-way sync, applied recipes are saved as reusable history snapshots, and Material Archive mode suggests recipes that match the target colour.",
          },
          {
            zh: "耗材档案颜色匹配更稳：增加耗材时，原本匹配良好的参考色不容易再被带偏",
            en: "Material-archive colour matching is steadier: adding new filaments is less likely to throw off reference colours that were already matching well",
          },
        ],
      },
      {
        category: { zh: "提取器（校色卡）", en: "Extractor (Calibration Card)" },
        items: [
          {
            zh: "5 色扩展模式每一页的角点提示修正",
            en: "Fixed per-page corner-label hints for the 5-Color Extended mode",
          },
          {
            zh: "点“清除角点”会顺带重置预览，直接回到拾取状态",
            en: "‘Clear corners’ now also resets the extraction preview so you return to corner picking immediately",
          },
          {
            zh: "RYBWGK 默认槽位名保持正确（不再误显 CMYW）",
            en: "RYBWGK slot names now stay correct instead of occasionally falling back to CMYW",
          },
          {
            zh: "小屏下按钮不再溢出",
            en: "Buttons no longer overflow on narrow screens",
          },
          {
            zh: "新增角点数值微调面板：四个校准角点可直接输入数值精调，不用再对着图像反复点拾",
            en: "New corner fine-tune panel: type exact pixel values for each of the four calibration corners instead of repeatedly clicking on the image",
          },
        ],
      },
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "默认材料改为下拉选择，告别输错名",
            en: "Default material switched from free text to a curated dropdown — no more typos",
          },
          {
            zh: "默认色块间距 0.82 → 0.84 mm",
            en: "Default colour-cell gap changed from 0.82 mm to 0.84 mm",
          },
          {
            zh: "材料求解器缓存 + 更紧凑的材料选择器",
            en: "Material solver now caches exhaustive results, and the material picker UI is more compact",
          },
          {
            zh: "校色卡色块提取采样窗口收紧：降低相邻色块串色与边缘反锯齿污染，提取出来的参考色更干净",
            en: "Calibration-card cell sampling window is tighter: less bleed from neighbouring cells and edge anti-aliasing, producing cleaner reference colours",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "滚轮缩放预览时不再连带滚动整页",
            en: "Wheel-zooming the preview no longer scrolls the whole page",
          },
          {
            zh: "Slider 范围拖动会自动吸附到步进",
            en: "Range sliders now snap to step increments when dragged",
          },
          {
            zh: "LUT 颜色网格提示文字乱码修复",
            en: "Fixed garbled text in the LUT colour-grid hints",
          },
          {
            zh: "2D 预览新增“按住查看原图”：长按按钮或按住键盘 Shift 键即可临时覆盖显示原始图片，松手自动回到生成效果",
            en: "2D preview ‘hold to view original’: press-and-hold the button or hold Shift to temporarily overlay the original upload; release to return to the generated view",
          },
          {
            zh: "2D 预览瘦身：移除打印床画布、网格与标尺，只保留核心画面，更清爽",
            en: "Slimmer 2D preview: bed canvas, grid, and rulers are removed, leaving only the core image",
          },
          {
            zh: "右键拖动平移预览时不再被浏览器菜单打断，和 3D 视图行为一致",
            en: "Right-drag panning no longer triggers the browser context menu — matches the 3D view's behaviour",
          },
          {
            zh: "下拉菜单宽度跟随触发器自适应，选项不多时也不会被错误判定为“下方空间不足”而翻到上方",
            en: "Dropdown menu width now follows its trigger, and short menus no longer flip upward when there is actually enough room below",
          },
          {
            zh: "3D 视图新增“性能”按钮：实时查看 FPS、显存占用、几何体 / 纹理数量和画布尺寸",
            en: "3D viewer gains a Diagnostics button: inspect live FPS, heap usage, geometry / texture counts, and canvas size",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "非五色单面 SVG 镜像修复",
            en: "Fixed single-side SVG mirroring for non-five-colour modes",
          },
          {
            zh: "矢量化发送到转换器流程回归覆盖",
            en: "Added regression coverage for the vectorise → converter hand-off flow",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "渐变色卡材料句柄超时回收，减少资源泄漏",
            en: "Gradient-card material registry handles now expire on a timeout to reduce resource leaks",
          },
          {
            zh: "会话租约清理",
            en: "Stale session leases are cleaned up more reliably",
          },
          {
            zh: "Windows 11 启动器修复：系统移除 wmic 后进程清理失败的问题，现改用 Get-CimInstance 查询",
            en: "Windows 11 launcher fix: process cleanup now uses Get-CimInstance because wmic was removed from the OS",
          },
          {
            zh: "修复生成穷举缓存后点预览偶发 500：worker 读取预览尺寸的方式已修正",
            en: "Fixed an occasional 500 when previewing after generating the exhaustive cache: the worker's preview-size logging is now correct",
          },
        ],
      },
    ],
  },
];
