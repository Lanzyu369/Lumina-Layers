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
        ],
      },
    ],
  },
];
