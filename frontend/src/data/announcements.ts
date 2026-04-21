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
    version: "2026-04-22",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "自定义配方可以加 LUT 里没有的颜色了：下拉直接选，导出的 3MF 会自动多一个对象带上这种颜色，切片那边不用自己改",
            en: "You can now add colours that aren't in the LUT to a custom recipe: pick them from the dropdown and the exported 3MF carries them as extra objects, so the slicer just works",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "打开自定义配方，下拉里能看到每种材料的真实颜色，不再是一堆灰方块",
            en: "Open the custom recipe dialog and the dropdown swatches show each material's actual colour instead of a row of grey placeholders",
          },
          {
            zh: "用耗材档案做的模型现在也能改自定义配方了，不会再弹 \"没有预测引擎\" 的提示",
            en: "Models built from the material library now accept custom recipes too — the old \"no predictive runtime\" blocker is gone",
          },
          {
            zh: "打开配方时，每层的初始值就是这个色块实际在用的配方，而不是全白；只改一两层不会再把别的层覆盖掉",
            en: "When you open the recipe dialog, every layer starts with the colour it's actually using, not pure white — so tweaking one or two layers doesn't wipe the rest",
          },
          {
            zh: "点应用之后，分层预览会整屏刷新；不再出现 \"只有改过的层亮起、其它层灰掉\" 的情况",
            en: "Hitting apply now refreshes every layer in the preview, so you don't end up with only the edited layers showing colour and the rest looking greyed-out",
          },
        ],
      },
      {
        category: {
          zh: "提取器（校色卡）",
          en: "Extractor (Calibration Card)",
        },
        items: [
          {
            zh: "耗材库里已经存好的条目，现在可以直接改名字和品牌，不用重新扫卡",
            en: "Already-saved entries in the material library can now be renamed (and have their brand changed) in place — no need to re-scan the card",
          },
          {
            zh: "品牌输入改成下拉：之前用过的品牌会自动列出来，想加新品牌也能直接打字",
            en: "Brand input is now a dropdown: it auto-lists brands you've used before, and you can still type a new one on the spot",
          },
          {
            zh: "提取完出的一堆 JSON、拟合摘要、Stage A 下载全收进一个 \"详情\" 按钮里，主面板干净多了",
            en: "The JSON dumps, fit summary and Stage A download link now live behind a single \"Details\" button, keeping the main panel uncluttered",
          },
          {
            zh: "保存成功 / 失败的提示从主面板挪到右上角小浮层，几秒自动消失，不会再把面板挤乱",
            en: "Save success / failure messages moved to a small top-right toast that fades on its own, so they no longer push the rest of the panel around",
          },
        ],
      },
      {
        category: {
          zh: "校准 & 材料",
          en: "Calibration & Materials",
        },
        items: [
          {
            zh: "梯度卡校准的默认层高从 0.04 mm 改成 0.08 mm，跟大家平时打印的层高更接近；以前存好的档案保持原样，不会被动",
            en: "Default gradient-card layer height is now 0.08 mm (was 0.04 mm) to match the layer height most people actually print at; archives you saved earlier keep their original layer height",
          },
        ],
      },
      {
        category: {
          zh: "预览 & 交互",
          en: "Preview & Interaction",
        },
        items: [
          {
            zh: "3D 预览加载大幅提速：以前上百 MB 的预览模型在远程使用时要等很久才出现，现在真实多色图通常只有几 MB，一打开画面就能看到 3D 模型；实际导出的 3MF 和打印精度完全不受影响",
            en: "The 3D preview loads dramatically faster: what used to be a 100+ MB model that kept remote users waiting is now typically just a few MB on real multi-colour images, so the 3D scene appears almost immediately; the actual exported 3MF and its print precision are completely unchanged",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "反推 LUT 导出的 3MF 不再跟上一次选过的传统 LUT 串色：之前如果上次选的是 CMYW，反推 LUT 的蓝 / 红 / 绿 / 黑会被错刷成青 / 品红 / 黄，黑甚至变成白；栅格（高保真）和 SVG 矢量建模两种路径现在都直接用反推 LUT 自己的调色板，耗材槽名和颜色不再因为上次的颜色模式而翻车",
            en: "3MF files exported from the Inferred LUT no longer pick up colours from the previously-selected legacy LUT: blue / red / green / black slots used to be silently recoloured as cyan / magenta / yellow (and black could come out white) when CMYW was picked last — both the raster (high-fidelity) and SVG vector modelling paths now honour the Inferred LUT's own palette, so filament slot names and colours are correct regardless of what colour mode was used before",
          },
          {
            zh: "梯度卡提取或保存失败时，会告诉你具体是哪一步出问题（ZIP 格式不对、图片解码不出来、角点选少了、基底方向认不出来、会话过期、找不到目标档案等），不再甩一串英文报错",
            en: "When gradient-card extract / save fails, you now get a clear sentence about what went wrong (bad ZIP, undecodable image, wrong number of corner points, can't tell substrate orientation, expired session, target archive missing, …) instead of a raw English error",
          },
          {
            zh: "提交表单填错字段时，弹窗会直接点名哪个字段有问题；之前偶尔会被 \"请求失败 status 422\" 这种模糊提示盖住",
            en: "When form fields are invalid, the dialog now names the offending field directly, instead of sometimes masking it behind a generic \"request failed with status 422\"",
          },
          {
            zh: "修了一个隐藏 bug：有些字段校验错误本来该返回 422，却被内部处理器弄成 500 显示成 \"服务器崩了\"，现在已经走正规流程",
            en: "Fixed a hidden bug where some field-validation errors (which should be 422) were turning into 500s that looked like server crashes; they now follow the normal path",
          },
          {
            zh: "耗材档案里的自定义配方应用不再卡在 \"LUT/source file missing\" 409，整套流程能走通",
            en: "Applying a custom recipe on a material-archive model no longer gets stuck on \"LUT/source file missing\" (409) — the whole flow works end to end",
          },
          {
            zh: "扩层时的边界修正：模型外面原本该透明的地方保持透明，不会再多一圈白边；模型里面没改动的像素继续沿用背板材料，不会塌成空层",
            en: "When the layer count is extended: transparent background outside the model stays transparent (no more white ring), and untouched pixels inside the model keep their backing material (no more collapsed empty layers)",
          },
        ],
      },
    ],
  },
  {
    version: "2026-04-20",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "自定义配方可以加 LUT 里没有的颜色了：下拉直接选，导出的 3MF 会自动多一个对象带上这种颜色，切片那边不用自己改",
            en: "You can now add colours that aren't in the LUT to a custom recipe: pick them from the dropdown and the exported 3MF carries them as extra objects, so the slicer just works",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "打开自定义配方，下拉里能看到每种材料的真实颜色，不再是一堆灰方块",
            en: "Open the custom recipe dialog and the dropdown swatches show each material's actual colour instead of a row of grey placeholders",
          },
          {
            zh: "用耗材档案做的模型现在也能改自定义配方了，不会再弹 \"没有预测引擎\" 的提示",
            en: "Models built from the material library now accept custom recipes too — the old \"no predictive runtime\" blocker is gone",
          },
          {
            zh: "打开配方时，每层的初始值就是这个色块实际在用的配方，而不是全白；只改一两层不会再把别的层覆盖掉",
            en: "When you open the recipe dialog, every layer starts with the colour it's actually using, not pure white — so tweaking one or two layers doesn't wipe the rest",
          },
          {
            zh: "点应用之后，分层预览会整屏刷新；不再出现 \"只有改过的层亮起、其它层灰掉\" 的情况",
            en: "Hitting apply now refreshes every layer in the preview, so you don't end up with only the edited layers showing colour and the rest looking greyed-out",
          },
        ],
      },
      {
        category: {
          zh: "提取器（校色卡）",
          en: "Extractor (Calibration Card)",
        },
        items: [
          {
            zh: "耗材库里已经存好的条目，现在可以直接改名字和品牌，不用重新扫卡",
            en: "Already-saved entries in the material library can now be renamed (and have their brand changed) in place — no need to re-scan the card",
          },
          {
            zh: "品牌输入改成下拉：之前用过的品牌会自动列出来，想加新品牌也能直接打字",
            en: "Brand input is now a dropdown: it auto-lists brands you've used before, and you can still type a new one on the spot",
          },
          {
            zh: "提取完出的一堆 JSON、拟合摘要、Stage A 下载全收进一个 \"详情\" 按钮里，主面板干净多了",
            en: "The JSON dumps, fit summary and Stage A download link now live behind a single \"Details\" button, keeping the main panel uncluttered",
          },
          {
            zh: "保存成功 / 失败的提示从主面板挪到右上角小浮层，几秒自动消失，不会再把面板挤乱",
            en: "Save success / failure messages moved to a small top-right toast that fades on its own, so they no longer push the rest of the panel around",
          },
        ],
      },
      {
        category: {
          zh: "校准 & 材料",
          en: "Calibration & Materials",
        },
        items: [
          {
            zh: "梯度卡校准的默认层高从 0.04 mm 改成 0.08 mm，跟大家平时打印的层高更接近；以前存好的档案保持原样，不会被动",
            en: "Default gradient-card layer height is now 0.08 mm (was 0.04 mm) to match the layer height most people actually print at; archives you saved earlier keep their original layer height",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "梯度卡提取或保存失败时，会告诉你具体是哪一步出问题（ZIP 格式不对、图片解码不出来、角点选少了、基底方向认不出来、会话过期、找不到目标档案等），不再甩一串英文报错",
            en: "When gradient-card extract / save fails, you now get a clear sentence about what went wrong (bad ZIP, undecodable image, wrong number of corner points, can't tell substrate orientation, expired session, target archive missing, …) instead of a raw English error",
          },
          {
            zh: "提交表单填错字段时，弹窗会直接点名哪个字段有问题；之前偶尔会被 \"请求失败 status 422\" 这种模糊提示盖住",
            en: "When form fields are invalid, the dialog now names the offending field directly, instead of sometimes masking it behind a generic \"request failed with status 422\"",
          },
          {
            zh: "修了一个隐藏 bug：有些字段校验错误本来该返回 422，却被内部处理器弄成 500 显示成 \"服务器崩了\"，现在已经走正规流程",
            en: "Fixed a hidden bug where some field-validation errors (which should be 422) were turning into 500s that looked like server crashes; they now follow the normal path",
          },
          {
            zh: "耗材档案里的自定义配方应用不再卡在 \"LUT/source file missing\" 409，整套流程能走通",
            en: "Applying a custom recipe on a material-archive model no longer gets stuck on \"LUT/source file missing\" (409) — the whole flow works end to end",
          },
          {
            zh: "扩层时的边界修正：模型外面原本该透明的地方保持透明，不会再多一圈白边；模型里面没改动的像素继续沿用背板材料，不会塌成空层",
            en: "When the layer count is extended: transparent background outside the model stays transparent (no more white ring), and untouched pixels inside the model keep their backing material (no more collapsed empty layers)",
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
