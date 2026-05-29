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
    version: "2026-05-29",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 矢量模式现在也能勾选「启用描边」了，设置的描边宽度会写进导出的 3MF；大画幅模式仍按既有规则不支持描边。",
            en: "SVG vector mode now lets you turn on outlines. The chosen outline width is written into exported 3MF files; large-format generation still follows the existing no-outline rule.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-28",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "ColorChecker 色卡校色现在直接在提取器和梯度卡页面里完成，不再跳到独立工具，确认后会自动衔接到提取或梯度卡拟合。",
            en: "ColorChecker calibration now runs inside the Extractor and Gradient Card pages instead of opening a separate tool, and feeds straight into extraction or gradient-card fitting once you confirm it.",
          },
          {
            zh: "ColorChecker 校色支持导入自定义参考表（xlsx）：可以用自己量出来的色卡数据替换默认基准，列表会保存在浏览器里下次直接选用。",
            en: "ColorChecker calibration now imports custom reference tables (xlsx). Your own measured patches can replace the default reference, and the list is remembered locally for next time.",
          },
          {
            zh: "导出的分享卡 PNG 底部新增官网二维码和「可直接导入 Lumina 2.0 重新生成」字样，方便发给别人时对方能直接扫码入门或重做。",
            en: "Exported share-card PNGs now include a wiki QR code and a caption telling viewers they can import the image back into Lumina 2.0 to recreate the result.",
          },
          {
            zh: "新增「必趣 PLA」六种颜色（白、红、绿、蓝、黄、黑）的梯度卡材料档案，可以直接在材料库里选用。",
            en: "Added BIQU PLA gradient-card profiles for six colours (white, red, green, blue, yellow, black), available directly from the material library.",
          },
          {
            zh: "颜色工作站对 10 色 5 层以内的调色板改为精确穷举匹配，并且会让相近颜色之间保持原图的明暗顺序，过渡不会被打乱。",
            en: "The Color Workstation now does an exhaustive match for palettes up to 10 colours and 5 layers, and keeps neighbouring colours in their original light-to-dark order so gradients stay smooth.",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 矢量模式的第一次预览现在就能看到完整底板，不会出现「预览没底板、生成后才有」的情况。",
            en: "The first SVG vector preview now shows the full backing plate, so you no longer see \"no backing in preview, backing appears after generation.\"",
          },
          {
            zh: "在矢量化页面把 SVG 发到转换器时，不再弹出裁剪窗口，直接进入颜色匹配流程。",
            en: "Sending an SVG from the Vectoriser to the Converter no longer pops up the crop dialog; the artwork goes straight to colour matching.",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "矢量生成完成后，3D 预览继续显示像素级的混色效果，不再切换成只有几个纯色块的版本。",
            en: "After vector generation, the 3D preview keeps the pixel-level colour-mixed view instead of switching to a flat per-material block view.",
          },
          {
            zh: "用 SVG 生成的 3MF 在 Windows 资源管理器和切片软件里的封面缩略图终于会显示真实图案，不再是一张白图。",
            en: "3MFs generated from SVGs now show the real artwork in the cover thumbnail used by Windows Explorer and slicer project lists, instead of a blank white image.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "用耗材档案做大画幅生成时偶尔报错的问题修好了；同时 bug 反馈里收集的最终产物会按真正的下载文件分类，不会再把大画幅 ZIP 误标。",
            en: "Fixed an occasional failure when running large-format generation under the material archive workflow. Bug-report attachments now classify the final artifact by the real download, so large-format ZIPs are no longer mislabeled.",
          },
          {
            zh: "macOS 上检测已安装的切片软件时，碰到某个应用包内信息文件损坏不会再让整次检测失败，会跳过坏的应用继续找其他切片软件。",
            en: "On macOS, scanning for installed slicers no longer aborts when one app bundle has a corrupted info file; the broken bundle is skipped and the rest of the scan continues.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-21",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 里由线条围出的白色留白不再在颜色识别时显示成黑色。",
            en: "White spaces enclosed by SVG linework no longer show up as black during colour matching.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "在耗材档案下用 SVG 图打开“自定义配方”加层后，新增的几层有时会被填成耗材列表里的第一种颜色，即使你列表里第一种不是白色。修好了：现在新增层会用真正的白色/底色耗材，导出的 3MF 跟分层预览一致。",
            en: "Under the material archive workflow with SVG inputs, adding extra layers in the Custom Recipe dialog could fill the new layers with the first material in your list instead of the white/backing one. This is now fixed — the exported 3MF matches the layer-by-layer preview.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-20",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "批量生成现在会把成功的模型打包成一个 3MF 下载，不用再解压后一件件导入切片软件。",
            en: "Batch generation now downloads successful models as one 3MF, so you no longer need to unzip and import each model into the slicer one by one.",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "批量生成完成后，3D 预览会直接在热床上显示多个模型，并在数量太多时只预览能稳定显示的前几件。",
            en: "After batch generation, the 3D preview now shows multiple models on the bed and limits the preview to the first models that can be displayed smoothly when a batch is very large.",
          },
          {
            zh: "透明区域会用棋盘格显示，预览和分层图里更容易分清透明和黑色。",
            en: "Transparent areas now use a checkerboard background, making it easier to tell transparency from black in previews and layer images.",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 里的透明背景不再被当成黑色实体，矢量模式打开透明图时不会整片发黑。",
            en: "Transparent SVG backgrounds are no longer treated as solid black, so vector previews no longer turn the whole artwork black.",
          },
          {
            zh: "SVG 渐变图不分离底板时，底板层高修改器现在也能正常生效。",
            en: "The base-plate layer-height modifier now also works for SVG gradient artwork when the base plate is not exported separately.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "批量生成的合并 3MF 打开后会保留工艺参数，不再出现切片软件里看不到参数的情况。",
            en: "Merged batch 3MF files now keep their process settings when opened in slicers instead of appearing with no parameters.",
          },
          {
            zh: "批量生成合并成一个 3MF 时，底板层高修改器会一起保留。",
            en: "Batch generation now preserves the base-plate layer-height modifier inside the merged 3MF.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-19",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "耗材档案搭配 SVG 时，深色和受限材料组合不再容易被吸到错误的大面积颜色上。",
            en: "SVGs in material-library mode are less likely to pull dark or limited-palette colours into the wrong large-area match.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-17",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "导出的 3MF 现在会带上封面缩略图，在切片软件和文件管理器里更容易认出是哪张图。",
            en: "Exported 3MF files now include cover thumbnails, making models easier to recognise in slicers and file managers.",
          },
        ],
      },
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "彩多屋梯度卡材料数据已更新，红色和青色档案会按新的校准结果使用。",
            en: "Caiduowu gradient-card material data has been refreshed, with red and cyan archives using the latest calibration results.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-15",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "配方查询会按观赏面优先显示和生成验证色块，预览里看到的层顺序和导出的色块样板更一致。",
            en: "Recipe lookup now follows the visible face first, so the preview order and exported swatch boards line up more naturally.",
          },
        ],
      },
      {
        category: { zh: "提取器（校色卡）", en: "Extractor (Calibration Card)" },
        items: [
          {
            zh: "梯度卡提取里的校色卡识别现在能稳定触发，不再偶发点了以后没有反应。",
            en: "Calibration-card detection in gradient-card extraction now triggers reliably instead of occasionally doing nothing after you click it.",
          },
        ],
      },
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "材料验证色块的层顺序会跟界面里的观赏面设置对齐，实物对色时更不容易看反。",
            en: "Material validation swatches now follow the visible-face setting from the UI, making real-world colour checks harder to read backwards.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-14",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "高保真模式处理 SVG 时，现在可以在设置里调整清晰度；默认值保持不变，想要更细或更快时可以自己调。",
            en: "High-Fidelity SVG conversion now has a detail setting. The default stays the same, and you can tune it for cleaner detail or faster runs.",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "耗材档案模式会保留每种耗材自己的纯色配方，查询本色时不再容易被相近颜色挤掉。",
            en: "Material-library matching now keeps each material's own pure-colour recipe, so native filament colours are less likely to be crowded out by nearby matches.",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "macOS 桌面版现在能更顺地启动和退出，Dock 里也会显示 Lumina 的彩色图标。",
            en: "The macOS desktop app now starts and quits more cleanly, and the Dock shows the coloured Lumina icon.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-10",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "Bug 反馈会自动带上最近的前端日志、接口失败和材料底板选择，开发者更容易复现问题。",
            en: "Bug reports now include recent frontend logs, API failures, and the selected backing material, making issues easier to reproduce.",
          },
          {
            zh: "反馈问题时现在会自动带上你当时用的原图、生成的 3MF、所选耗材档案，开发者更容易在本地复现你遇到的情况。",
            en: "Bug reports now automatically include the original image you used, the generated 3MF, and the selected material archives, so the developer can reproduce the problem locally more easily.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-05",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "全选颜色后现在也能打开自定义配方，不用再一个区域一个区域点；应用后只会改你选中的颜色区域。",
            en: "Custom recipes now open correctly after selecting a whole colour, so you no longer need to click regions one by one; applying the recipe only changes the colour areas you selected.",
          },
          {
            zh: "耗材档案高保真模式下，手动改过的 10 层配方会按真实槽位应用，默认白色层也不会再变成其它材料色。",
            en: "In high-fidelity material-library mode, edited 10-layer recipes now apply to the real material slots, and untouched white layers no longer turn into another material colour.",
          },
          {
            zh: "配方查询新增「配方队列」和验证色块生成：可以把多组材料配方先收进队列，一次导出 3MF 色块样板和图例，方便实物对色。",
            en: "Recipe lookup now has a recipe queue and validation-swatch export: collect multiple material recipes first, then generate one 3MF swatch board with a legend for real-world colour checks.",
          },
          {
            zh: "耗材选择器会按品牌分组并标出未分组材料；基础设置里也能指定底板耗材，背板和底色不再只能默认跟第一个耗材槽。",
            en: "Material pickers now group entries by brand and label unassigned materials; Basic Settings can also choose the backing material, so backing and base colours no longer have to follow the first material slot.",
          },
          {
            zh: "材料提取结果旁边现在直接显示合并、覆盖和取消操作，不用再滚回页面顶部处理保存确认。",
            en: "Material extraction results now show merge, override, and cancel actions right beside the results, so you no longer need to scroll back to the top to finish saving.",
          },
          {
            zh: "主动切到提取页面时会清理旧的确认状态，重新校验材料时仍会保留当前上下文，操作不再串台。",
            en: "Opening the extraction page now clears stale confirmation state, while material re-verification still keeps the current context, preventing actions from bleeding between workflows.",
          },
        ],
      },
      {
        category: { zh: "提取器（校色卡）", en: "Extractor (Calibration Card)" },
        items: [
          {
            zh: "6 色 RYBWGK / CMYWGK 的提取和保存更稳定，颜色模式不会再被错误显示成另一套 6 色或 4 色模式。",
            en: "6-Colour RYBWGK / CMYWGK extraction and saving are more stable, so a LUT is no longer displayed as the wrong 6-Colour or 4-Colour mode.",
          },
          {
            zh: "修复一组 6 色耗材通道顺序不一致导致的颜色错位，选择这类 LUT 时预览和生成会按实际通道顺序来。",
            en: "Fixed colour shifts from a 6-Colour filament set whose channel order differed from the standard order; previews and generation now follow the LUT's actual channel order.",
          },
        ],
      },
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "导出到 Bambu Studio / OrcaSlicer 时，PETG 槽位会保留 PETG 材料和温度配置，不再每次打开都退回 PLA。",
            en: "Exports to Bambu Studio / OrcaSlicer now keep PETG material and temperature settings for PETG slots instead of falling back to PLA every time.",
          },
          {
            zh: "材料档案、单阶段标定卡和挂件环会一起传递真实材料名，辅助零件不再偷偷变回默认 PLA。",
            en: "Material-library exports, single-stage calibration cards, and keychain loops now carry the real material names together, so auxiliary parts no longer silently fall back to default PLA.",
          },
          {
            zh: "校准板色块尺寸支持 5.5mm 这类小数输入，仍会保留原来的 3–10mm 安全范围。",
            en: "Calibration block size now accepts fractional values such as 5.5mm while keeping the existing safe 3–10mm range.",
          },
          {
            zh: "6 色传统 LUT 和 6 色校准板会复用预计算 Smart1296 配方，生成更快，也不再每次现场跑选色。",
            en: "6-Colour traditional LUTs and 6-Colour calibration boards now reuse a precomputed Smart1296 recipe set, making generation faster without running colour selection every time.",
          },
          {
            zh: "挂件环的几何面片更干净，切片软件预览不再容易出现未知面或闪烁，但仍保持正常切片。",
            en: "Keychain loop geometry is cleaner, so slicer previews are less likely to show unknown faces or flicker while slicing remains normal.",
          },
          {
            zh: "导出的 Bambu / Orca 项目不再把切料回抽相关的耗材覆盖项写死，避免模板里的长回抽和切料回抽距离影响实际切片参数。",
            en: "Bambu / Orca exports no longer hard-code filament cut-retraction overrides, preventing template long-retraction and cut-distance values from unexpectedly changing slicer settings.",
          },
          {
            zh: "耗材档案生成的白色底板和描边会继续使用当前底板材料；只有你显式指定独立背板颜色时才会切到另一种材料。",
            en: "Material-library white backing and outlines now keep using the selected backing material; they switch to another material only when a separate backing colour is explicitly chosen.",
          },
        ],
      },
      {
        category: { zh: "预览、切片器 & 交互", en: "Preview, Slicers & Interaction" },
        items: [
          {
            zh: "透明 PNG 和不规则图形的 3D 外轮廓更贴近实际图案，耗材档案预览不再把背板或其它颜色混进轮廓里。",
            en: "3D outlines for transparent PNGs and irregular shapes now follow the actual artwork more closely, and material-library previews no longer mix backing or other colours into the outline.",
          },
          {
            zh: "冰箱贴模式的槽位外轮廓会跟随当前厚度和主体形状，磁铁孔不会再污染轮廓预览。",
            en: "Fridge-magnet slot outlines now follow the current thickness and main shape, and magnet holes no longer pollute the outline preview.",
          },
          {
            zh: "图像转矢量页面改成更宽的左右布局，上传、基础设置、高级参数和结果区域不再挤成一列。",
            en: "The Image-to-Vector page now uses a wider split layout, so upload, basic settings, advanced parameters, and results no longer crowd into one column.",
          },
          {
            zh: "切片成功后切换打印机时会清理旧预览模型，重新导入前不再继续显示上一台设备的过期预览。",
            en: "After slicing, switching printers now clears stale preview models instead of keeping an outdated preview from the previous device.",
          },
          {
            zh: "选择或取消耗材时，耗材列表不再自动折叠变小，靠近列表底部的项目也能稳定点选。",
            en: "When selecting or unselecting materials, the material list no longer collapses unexpectedly, so items near the bottom stay easy to click.",
          },
          {
            zh: "梯度卡里的链接点击区域收窄到实际文字附近，不再横向占满整块结果区域。",
            en: "Gradient-card links now keep their clickable area close to the text instead of stretching across the whole result row.",
          },
          {
            zh: "macOS 设置页现在能自动扫描常见 Applications 目录和 Spotlight 里的 `.app` 切片软件，也支持手动指定 `.app` 路径。",
            en: "On macOS, Settings can now scan common Applications folders and Spotlight for slicer `.app` bundles, and custom `.app` paths can be validated manually.",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 矢量模式开启涂层后，生成的 3MF 会真正带上完整涂层，不再只在参数里显示已开启。",
            en: "When coating is enabled in SVG vector mode, the generated 3MF now actually includes the full coating instead of only showing the option as enabled.",
          },
          {
            zh: "矢量预览后的分享卡会保留来源、色层、材料和模型参数，导出再导入不再丢关键设置。",
            en: "Share cards exported after vector previews now preserve source, layer, material, and model settings, so importing them no longer loses key options.",
          },
          {
            zh: "SVG + 梯度卡和小矢量图形的材料匹配更干净，边缘和小色块不再容易冒出杂色。",
            en: "SVG + gradient-card and small vector artwork now get cleaner material matching, reducing stray colours around edges and tiny shapes.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "Custom 开头的个人 LUT 会正确生成颜色层和分层预览，不再只导出一个底层。",
            en: "Personal LUTs under Custom now generate colour layers and layer previews correctly instead of exporting only a base layer.",
          },
          {
            zh: "生成完成后切换 LUT 再下载，浏览器不再下载失败的 JSON 错误文件，3MF / ZIP 下载会在会话切换后继续可用一段时间。",
            en: "After generating and switching LUTs, the browser no longer downloads failed JSON error files; 3MF / ZIP downloads remain available for a while even after the session changes.",
          },
          {
            zh: "矢量预览后的分享卡导出在普通 HTTP 环境下也更可靠，不再因为浏览器加密接口限制直接失败。",
            en: "Share-card export after vector previews is more reliable on regular HTTP pages and no longer fails outright because of browser crypto restrictions.",
          },
          {
            zh: "批量转换会按当前设置正确传递参数，减少批量生成时出现设置错位的情况。",
            en: "Batch conversion now forwards the current settings in the correct order, reducing parameter mix-ups during batch generation.",
          },
          {
            zh: "反馈问题支持附带截图，并会带上当前来源、LUT、材料和打印参数，开发者更容易复现你遇到的情况。",
            en: "Bug reports can now include a screenshot and carry the current source, LUT, material, and print settings, making it easier for the developer to reproduce what you saw.",
          },
          {
            zh: "反馈弹窗的复制按钮增加兜底方案，即使浏览器剪贴板权限不稳定，也能手动复制问题信息。",
            en: "The bug-report copy button now has a fallback path, so you can still copy the report details manually when browser clipboard permissions are unreliable.",
          },
          {
            zh: "前后端回归测试重新稳定：缺少外部参考资产的环境会明确跳过对应测试，frozen raster 基线也已同步当前转换输出。",
            en: "Frontend and backend regression suites are stable again: environments without external reference assets now skip those tests explicitly, and frozen raster baselines match the current converter output.",
          },
          {
            zh: "App 启动、健康状态和设置初始化相关测试补齐了后台 hook / API mock，Vitest 不再因为未 mock 的副作用挂住。",
            en: "App startup, health-status, and settings-bootstrap tests now mock their background hooks and APIs, so Vitest no longer hangs on unmocked side effects.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-03",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "全选颜色后现在也能打开自定义配方，不用再一个区域一个区域点；应用后只会改你选中的颜色区域。",
            en: "Custom recipes now open correctly after selecting a whole colour, so you no longer need to click regions one by one; applying the recipe only changes the colour areas you selected.",
          },
          {
            zh: "耗材档案高保真模式下，手动改过的 10 层配方会按真实槽位应用，默认白色层也不会再变成其它材料色。",
            en: "In high-fidelity material-library mode, edited 10-layer recipes now apply to the real material slots, and untouched white layers no longer turn into another material colour.",
          },
        ],
      },
      {
        category: { zh: "提取器（校色卡）", en: "Extractor (Calibration Card)" },
        items: [
          {
            zh: "6 色 RYBWGK / CMYWGK 的提取和保存更稳定，颜色模式不会再被错误显示成另一套 6 色或 4 色模式。",
            en: "6-Colour RYBWGK / CMYWGK extraction and saving are more stable, so a LUT is no longer displayed as the wrong 6-Colour or 4-Colour mode.",
          },
          {
            zh: "修复一组 6 色耗材通道顺序不一致导致的颜色错位，选择这类 LUT 时预览和生成会按实际通道顺序来。",
            en: "Fixed colour shifts from a 6-Colour filament set whose channel order differed from the standard order; previews and generation now follow the LUT's actual channel order.",
          },
        ],
      },
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "导出到 Bambu Studio / OrcaSlicer 时，PETG 槽位会保留 PETG 材料和温度配置，不再每次打开都退回 PLA。",
            en: "Exports to Bambu Studio / OrcaSlicer now keep PETG material and temperature settings for PETG slots instead of falling back to PLA every time.",
          },
          {
            zh: "材料档案、单阶段标定卡和挂件环会一起传递真实材料名，辅助零件不再偷偷变回默认 PLA。",
            en: "Material-library exports, single-stage calibration cards, and keychain loops now carry the real material names together, so auxiliary parts no longer silently fall back to default PLA.",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "透明 PNG 和不规则图形的 3D 外轮廓更贴近实际图案，耗材档案预览不再把背板或其它颜色混进轮廓里。",
            en: "3D outlines for transparent PNGs and irregular shapes now follow the actual artwork more closely, and material-library previews no longer mix backing or other colours into the outline.",
          },
          {
            zh: "冰箱贴模式的槽位外轮廓会跟随当前厚度和主体形状，磁铁孔不会再污染轮廓预览。",
            en: "Fridge-magnet slot outlines now follow the current thickness and main shape, and magnet holes no longer pollute the outline preview.",
          },
          {
            zh: "图像转矢量页面改成更宽的左右布局，上传、基础设置、高级参数和结果区域不再挤成一列。",
            en: "The Image-to-Vector page now uses a wider split layout, so upload, basic settings, advanced parameters, and results no longer crowd into one column.",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 矢量模式开启涂层后，生成的 3MF 会真正带上完整涂层，不再只在参数里显示已开启。",
            en: "When coating is enabled in SVG vector mode, the generated 3MF now actually includes the full coating instead of only showing the option as enabled.",
          },
          {
            zh: "矢量预览后的分享卡会保留来源、色层、材料和模型参数，导出再导入不再丢关键设置。",
            en: "Share cards exported after vector previews now preserve source, layer, material, and model settings, so importing them no longer loses key options.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "Custom 开头的个人 LUT 会正确生成颜色层和分层预览，不再只导出一个底层。",
            en: "Personal LUTs under Custom now generate colour layers and layer previews correctly instead of exporting only a base layer.",
          },
          {
            zh: "生成完成后切换 LUT 再下载，浏览器不再下载失败的 JSON 错误文件，3MF / ZIP 下载会在会话切换后继续可用一段时间。",
            en: "After generating and switching LUTs, the browser no longer downloads failed JSON error files; 3MF / ZIP downloads remain available for a while even after the session changes.",
          },
          {
            zh: "反馈问题支持附带截图，并会带上当前来源、LUT、材料和打印参数，开发者更容易复现你遇到的情况。",
            en: "Bug reports can now include a screenshot and carry the current source, LUT, material, and print settings, making it easier for the developer to reproduce what you saw.",
          },
          {
            zh: "反馈弹窗的复制按钮增加兜底方案，即使浏览器剪贴板权限不稳定，也能手动复制问题信息。",
            en: "The bug-report copy button now has a fallback path, so you can still copy the report details manually when browser clipboard permissions are unreliable.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-04-30",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "应用右上角新增「反馈问题」入口：遇到问题写一句描述就能直接提交给开发者，不用再先截图发微信再讲半天环境。",
            en: "A new 「Report a bug」 entry sits in the top-right corner: type a one-liner and submit it straight to the developer — no more screenshot-first-then-explain workflow.",
          },
          {
            zh: "反馈会自动带上你当前的工作流（converter / single stage 等）、color mode、LUT 名字、session ID 和浏览器信息，不用自己回忆环境；同一个工单号也会出现在邮件主题里，开发者一眼对得上。",
            en: "Each report auto-collects your active workstream (converter / single stage), color mode, LUT name, session id, and browser info — no need to recall the environment yourself; the same ticket id is in the email subject so the developer can match it instantly.",
          },
          {
            zh: "提交成功后弹窗会留住工单号方便你复制，关闭按钮在你手上——不会再 1 秒自动消失来不及抄。",
            en: "The success view keeps the ticket id on screen so you have time to copy it — closing is up to you, no more 1-second auto-dismiss.",
          },
          {
            zh: "即使本地没配邮件服务，反馈也会落盘到 feedback/ 目录兜底，开发者可以直接拷走那份 JSON；网络断了也丢不了反馈。",
            en: "Even when SMTP isn't configured locally, reports still land in the feedback/ directory as a JSON dump that the developer can pull directly — flaky networks no longer lose reports.",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "转换器主面板拆分为「核心」「颜色」「高级」三个子标签页，常用功能和高级选项不再挤在同一屏；底部颜色工作站入口也改到顶部二级标签，找起来更直觉。",
            en: "The converter panel is now split into Core / Colour / Advanced sub-tabs so everyday controls and power-user options no longer share a single scroll; the Color Workstation entry moves from the bottom drawer up to a top-level secondary tab for easier access.",
          },
          {
            zh: "3D 查看器右下角诊断弹窗精简：FPS 旁加了红/黄/绿状态点，新增帧耗时一行，去掉了几行只有开发者才关心的指标。",
            en: "The 3D viewer diagnostics popover is now leaner: FPS gets a green/yellow/red dot, a new frame-time row is added, and several developer-only metrics are removed.",
          },
          {
            zh: "颜色工作站 2D 叠层打开时不再上下滑入，改为淡入淡出，过渡更快也不会闪一下布局。",
            en: "The Color Workstation 2D overlay now fades in instead of sliding, making the transition faster and eliminating a brief layout flash.",
          },
          {
            zh: "所有滑块和复选框旁边的帮助提示统一为可见的小问号图标，鼠标悬停弹出说明，不再需要猜哪个控件有隐藏提示。",
            en: "Help hints on all sliders and checkboxes are now shown as a visible question-mark chip that reveals a description on hover, so you no longer have to guess which controls have hidden tooltips.",
          },
          {
            zh: "面板展开/收起动画全面优化：面板高度变化与同级组件位置避让完全同步，不再出现面板展开了但旁边还在挪的割裂感。",
            en: "Widget expand/collapse animations fully optimised: panel height and sibling position shifts now animate in sync, eliminating the visible disconnect where the panel finished expanding but siblings were still sliding.",
          },
          {
            zh: "面板背景毛玻璃效果移除，改用 80% 不透明度背景：之前的 backdrop-blur 在 92% 不透明度下模糊几乎看不见但 GPU 每帧都要采样卷积，去掉后以接近零开销提供同等半透明视觉。",
            en: "Panel backdrop-blur removed in favour of a fixed 80% opacity background: the previous blur was barely visible at 92% opacity but cost a per-frame GPU sample-and-convolve; removing it gives the same translucent look at near-zero cost.",
          },
        ],
      },
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "「再次验证」现在做合并样本重拟合，而不是对参数取算术平均：Beer-Lambert 在 k 上是非线性的，平均参数统计上不成立；改成把每次拍摄的样本拼起来重新拟合后，多次校准 = 真正更精确才成立。",
            en: "Re-verification now refits Beer-Lambert on the concatenated samples instead of arithmetically averaging (E, k): the model is non-linear in k, so parameter averaging is statistically meaningless. With combined-sample refitting, more captures actually yield a more accurate fit.",
          },
          {
            zh: "「图像来源」标签现在区分原图和 ColorChecker 校正/还原图：校正图可以减少相机色差，但会和原图样本分开合并；真正需要处理的是采样区出现高光或阴影裁切，软件会用「零厚度白底采样接近纯白」等警告提示。",
            en: "The Image Source tag now separates raw captures from ColorChecker-corrected/restored images. Corrected images can reduce camera colour bias, but they are merged separately from raw samples; the real issue to handle is highlight or shadow clipping in the sampled area, surfaced through warnings such as \"zero-thickness white near pure white\".",
          },
          {
            zh: "多 run 聚合自动剔除偏置 run：白底过亮、底板平、单 run ΔE>3 等结构性偏置会被排除在联合重拟合之外；3 个以上历史 run 还会做交叉验证，剔除「自我一致但和别人不一致」的捕获；新 run 始终保留以便审计。",
            en: "Multi-run aggregation now bias-filters: structurally biased runs (overbright white substrate, flat substrate, single-run ΔE>3, …) are excluded from the joint refit; with 3+ historicals a cross-validation pass also drops self-consistent-but-pairwise-inconsistent captures; the freshest run is always kept for audit.",
          },
          {
            zh: "拟合零厚度白底接近纯白（C0_white 均值 > 0.95）现在会单独发警告，识别「ΔE 看着低但 (E, k) 已偏离物理真值」的隐形失效。",
            en: "Stage A now emits a dedicated warning when the zero-thickness white-substrate sample sits above 0.95 in linear RGB, exposing the silent failure mode where ΔE still looks fine but (E, k) has drifted off the true physical attenuation.",
          },
          {
            zh: "校准板默认底板厚度从 1.6 mm 改为 1.2 mm，更贴近常见打印设置；所有颜色模式（包括 6 色）现在都能调底板厚度滑块，不再有模式限制。",
            en: "Default calibration board backing thickness changed from 1.6 mm to 1.2 mm to match common print settings; the slider is now available in every colour mode (including 6-Colour) with no mode restriction.",
          },
        ],
      },
      {
        category: { zh: "提取器（校色卡）", en: "Extractor (Calibration Card)" },
        items: [
          {
            zh: "SVG + 梯度卡模式不再走 K-Means 量化预算，改为用频次直方图取覆盖 99% 可见像素的真实填充色板，再 KDTree 把剩余像素吸附到最近填充色：以前 256 量化预算会给抗锯齿过渡带开簇产生「不沿走线」的杂色配方，现在 SVG 真实有几个填充色就只生成几条配方。",
            en: "SVG + gradient-card material-archive mode no longer feeds the rasterized image to K-Means with a 256-cluster budget. Instead it picks the smallest top-K colors covering 99% of visible pixels as the real fill palette and KDTree-snaps every visible pixel to its nearest fill. The old path spent clusters on anti-aliased edge blends and produced 'noise pixels off the strokes'; now the SVG yields exactly its true fill count of recipes.",
          },
          {
            zh: "耗材档案 + SVG + 矢量现在与 LUT 矢量共用同一条原生矢量管线（解析 → 遮挡裁剪 → 网格挤出 → 抗锯齿预览光栅化），只在颜色匹配那一步用 Beer-Lambert 求解器替代 LUT KDTree：之前耗材档案会先把 SVG 光栅化再做像素吸附 + 逐像素材料映射，2D 预览出来的是硬边像素图、走线边缘还会有 1px 邻色杂点；现在矢量预览的边缘抗锯齿和填充色边界都和 LUT 矢量保持一致，配方仍然由耗材求解器逐唯一色输出。",
            en: "Material archive + SVG + vector now shares the same native vector pipeline as LUT vector mode (parse → occlusion clip → mesh extrude → anti-aliased preview rasterisation); only the per-fill colour matching step is swapped — the LUT KDTree is replaced by the Beer-Lambert solver. The old path rasterised the SVG first, snapped pixels to a fill palette, then ran a per-pixel material mapping, which produced hard-edged pixel previews and the occasional 1-pixel off-colour speck along strokes; the new path keeps anti-aliased fill edges identical to LUT vector mode while still routing recipes through the material solver per unique colour.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "修复矢量模式下颜色工作站做区域替换或多选区域替换后，生成的 3MF 模型不反映替换的问题；现在 2D 预览改了什么，最终模型就改了什么。",
            en: "Fixed vector mode losing region or multi-region colour edits made in the Color Workstation; what you see in the 2D preview now matches the generated 3MF.",
          },
          {
            zh: "SVG 矢量生成现在纳入和光栅流程同一套日志治理检查，预览到生成之间的问题更容易在发布前被发现。",
            en: "SVG vector generation is now covered by the same log-governance checks as raster, making preview-to-generate issues easier to catch before release.",
          },
          {
            zh: "修复校准板生成完成后日志记录引用已删除字段导致的报错，之前在默认 4 色模式下生成校准板会返回 500。",
            en: "Fixed a logging error that referenced a removed field after calibration board generation, which previously turned a successful 4-Colour generation into a 500 response.",
          },
          {
            zh: "5 色扩展 Page 2 的分层预览现在包含全部 6 个色层，之前漏掉了最后一层。",
            en: "The layer preview for 5-Colour Extended Page 2 now includes all 6 colour layers instead of silently dropping the last one.",
          },
          {
            zh: "Widget 面板不再拦截 3D 场景的旋转拖拽，拖到面板区域时模型照常转动；LUT 详情标签页切换时也不再黑屏闪烁。",
            en: "Widget panels no longer block 3D orbit controls — dragging into a panel area keeps the model rotating as expected; switching LUT detail tabs no longer causes a brief black flash either.",
          },
          {
            zh: "修复在梯度卡提取子标签之间切换时，上一次「再次验证」的状态可能污染下一次新校准的问题。",
            en: "Fixed verification state from a previous re-verification leaking into a fresh calibration when switching between gradient-card extract sub-tabs.",
          },
          {
            zh: "五色 LUT 基础颜色端点改用规范的 combinations 接口；旧版 flat-list JSON LUT（根为列表）不再因 schema 不匹配返回 500。",
            en: "The five-color base-colors endpoint now reads through the canonical combinations accessor; legacy flat-list JSON LUTs (list-rooted) no longer 500 due to a schema mismatch in the source extractor.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-04-26",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "顶部材料管理新增 「LUT 详情」 入口：可以浏览所有可用 LUT、查看调色板和每种颜色的用量覆盖，还能在 2D/3D 视图里看色相覆盖图和 Lab 点云，心里有数再去选 LUT",
            en: "A new 「LUT details」 entry in the top Material-Management menu lets you browse every available LUT, inspect its palette and per-colour coverage, and view hue-coverage charts plus a Lab point cloud in 2D/3D — so you can pick a LUT with a clear idea of what it actually covers",
          },
          {
            zh: "自定义配方可以加 LUT 里没有的颜色了：下拉直接选，导出的 3MF 会自动多一个对象带上这种颜色，切片那边不用自己改",
            en: "You can now add colours that aren't in the LUT to a custom recipe: pick them from the dropdown and the exported 3MF carries them as extra objects, so the slicer just works",
          },
          {
            zh: "设置里加了「渐变自动换色」开关：开启后每次预览成功会自动把每一组渐变统一替换成组内代表色，一键去掉海带纹；默认关闭，原有手动换色流程不受影响",
            en: "New Settings → 「Auto replace gradient banding」 toggle: when on, every successful preview auto-collapses each gradient group to its representative colour to erase banding in one shot; off by default so the manual flow stays unchanged",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "耗材档案模式下，预览完成后会自动检测原图里平滑渐变被切成多种耗材色的情况，在颜色面板里列成一组一组，点一下就能把整组色块一次选中送去换色",
            en: "In material-archive mode, a successful preview automatically detects smooth source gradients that got quantised into several material colours and lists them as gradient groups; one click multi-selects the whole group for batch replacement",
          },
          {
            zh: "每组还能展开看到里面的独立区域（脸、嘴巴、手等），按区域单独选颜色，而不是只能整组一起换",
            en: "Expand a group to see its spatial regions (face, mouth, hand, etc.) and select a single region's colours instead of the whole group",
          },
          {
            zh: "每个大分组和小分组右边都加了一个「去海带纹」按钮，不必先选中再回到拾色器，直接一键把这一处渐变压成代表色",
            en: "Every group and region row now has its own Flatten button — no need to first multi-select and pick a target colour, one click collapses that specific gradient to its representative colour",
          },
          {
            zh: "在不同分组之间快速切换时，预览上不会再因为旧请求晚到而显示到旧的高亮色，始终跟当前选中保持一致",
            en: "Rapid switching between gradient groups no longer leaves a stale highlight on the preview: out-of-order responses are dropped so the canvas always matches the current selection",
          },
          {
            zh: "从整组切到组内某个区域时，整组按钮会正确地变灰、只有被点击的区域保持选中态；不会再出现整组和区域同时显示选中的情况",
            en: "Clicking a region inside a group correctly dims the parent group button so only the region you just picked stays highlighted, instead of both lighting up at once",
          },
          {
            zh: "点击小分组时，右边预览只会高亮这个小分组所在的那一块区域，不再把整组覆盖的同色像素全部点亮",
            en: "Clicking a sub-region now highlights only that region in the preview, instead of lighting up every matching pixel across the whole group",
          },
          {
            zh: "选中某个小分组后再从 LUT 里挑颜色换色，现在只会改这一块区域的像素；共享相同颜色的其它区域不会再被一起覆盖",
            en: "Picking a LUT colour while a sub-region is selected now repaints only that region's pixels; other regions that happen to share the same colour stay untouched",
          },
          {
            zh: "打开自定义配方，下拉里能看到每种材料的真实颜色，不再是一堆灰方块",
            en: "Open the custom recipe dialog and the dropdown swatches show each material's actual colour instead of a row of grey placeholders",
          },
          {
            zh: '用耗材档案做的模型现在也能改自定义配方了，不会再弹 "没有预测引擎" 的提示',
            en: 'Models built from the material library now accept custom recipes too — the old "no predictive runtime" blocker is gone',
          },
          {
            zh: "打开配方时，每层的初始值就是这个色块实际在用的配方，而不是全白；只改一两层不会再把别的层覆盖掉",
            en: "When you open the recipe dialog, every layer starts with the colour it's actually using, not pure white — so tweaking one or two layers doesn't wipe the rest",
          },
          {
            zh: '点应用之后，分层预览会整屏刷新；不再出现 "只有改过的层亮起、其它层灰掉" 的情况',
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
            zh: '提取完出的一堆 JSON、拟合摘要、Stage A 下载全收进一个 "详情" 按钮里，主面板干净多了',
            en: 'The JSON dumps, fit summary and Stage A download link now live behind a single "Details" button, keeping the main panel uncluttered',
          },
          {
            zh: "保存成功 / 失败的提示从主面板挪到右上角小浮层，几秒自动消失，不会再把面板挤乱",
            en: "Save success / failure messages moved to a small top-right toast that fades on its own, so they no longer push the rest of the panel around",
          },
          {
            zh: "梯度卡方向控制改成大白话：原来那个看不懂的「白底/黑底方向覆盖」下拉，现在变成「纯白/纯黑色块位置」——直接选色块在照片的哪个角（左上/右上/右下/左下），不用再猜「沿主对角线转置」是什么意思了。",
            en: "Gradient-card orientation control speaks plain language now: the cryptic 「White/Black Orientation Override」 dropdown has been replaced by 「Pure White/Black Block Position」, where you simply pick which screen corner holds the bare-board patch (top-left, top-right, bottom-right, or bottom-left).",
          },
          {
            zh: "梯度卡图片栏的「旋转 90°」按钮拆成「顺时针 90°」和「逆时针 90°」两个，点哪个图就直接转哪个方向，不用再连点 3 下凑出顺时针。",
            en: "The single 「Rotate 90°」 button on each gradient-card image card is now split into 「Rotate 90° CW」 and 「Rotate 90° CCW」, so you can rotate either direction in one click instead of triple-tapping the counter-clockwise button.",
          },
          {
            zh: "梯度卡四角点选会明确提示按 1.左上 → 2.右上 → 3.右下 → 4.左下 顺时针顺序点，配合「色块位置」选项能稳定推导采样方向。",
            en: "Gradient-card corner picking now clearly prompts you to click the four corners in 1.top-left → 2.top-right → 3.bottom-right → 4.bottom-left clockwise order, which combines with the new 「block position」 selector to determine sampling orientation reliably.",
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
          {
            zh: "梯度卡生成界面重新排版并去除了中英夹杂：现在清晰分为「生成设置」与「使用须知」，在线模型链接和两张卡（白底/黑底）的打印说明一目了然，不用再到处找教程了。",
            en: "The Gradient Generator panel has been redesigned with clean, plain-language sections: 「Generation Settings」 and 「Instructions & Online Models」 are clearly separated, and the requirement to print two cards (white base and black base) is prominently explained so you no longer have to hunt for tutorials.",
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
            zh: "分层遮罩查看窗新增跟随鼠标的放大镜，检查细边和层间对齐时不用再来回缩放",
            en: "The layer-mask viewer now has a follow-cursor magnifier, making fine-edge and layer-alignment checks easier without constant zooming",
          },
          {
            zh: "颜色工作站放大后会继续用精准点选光标，不再用小手挡住小色块；需要移动画面时仍可右键拖动",
            en: "The Color Workstation now keeps a precise picking cursor after zooming instead of covering tiny swatches with a hand cursor, while right-button panning still works when you need to move the view",
          },
          {
            zh: "3D 预览模型变得小很多、加载快很多，远程打开也能更快看到模型，真正导出的 3MF 和打印精度不受影响",
            en: "3D preview models are much smaller and load far faster, especially over remote sessions, while exported 3MF files and print accuracy stay unchanged",
          },
          {
            zh: "滑块拖动时不会再自己多跳半格，数值会乖乖停在你拖到的位置",
            en: "Sliders no longer bump themselves by half a step while dragging, so values stay where you actually placed them",
          },
          {
            zh: "导出的 3MF 会带一个切片器能正常读取的预览图，占位图不再卡住 Anycubic Slicer Next",
            en: "Exported 3MF files now include a preview image that slicers can read correctly, so placeholder thumbnails no longer hang Anycubic Slicer Next",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 导出 3MF 时会真正带上自定义配方和额外添加的颜色层，不会只在界面上看着改了、导出后又丢掉",
            en: "SVG-to-3MF export now carries custom recipes and extra colour layers through to the file instead of only showing them in the UI",
          },
          {
            zh: "带插画风细线的 SVG 不会再被悄悄加粗，复杂边缘处理失败时也会自动走兜底，不会整次生成断掉",
            en: "Illustrated SVGs with fine strokes are no longer silently widened, and complex edge-processing failures now fall back safely instead of breaking the whole generation",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "反推 LUT 会坚持使用自己带的调色板，就算设置里还残留着旧颜色模式，也不会拿错颜色去匹配",
            en: "Inferred LUTs now keep using their own palettes even if settings still contain an older colour mode, avoiding mismatched colour picks",
          },
          {
            zh: "生成 3D 时，加载按钮不会再被浏览器翻译或插件改乱后把操作栏弄崩，模型生成完成后能继续正常显示",
            en: "During 3D generation, loading buttons no longer let browser translation or extensions break the action panel, so the finished model can keep showing normally",
          },
          {
            zh: "下载或复制 3MF 链接后再回来重新生成，不会再因为临时文件被清掉而报 409",
            en: "After downloading or copying a 3MF link, generating again no longer fails with 409 because required temp files were cleaned too aggressively",
          },
        ],
      },
    ],
  },
  {
    version: "2026-04-24",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "顶部材料管理新增 「LUT 详情」 入口：可以浏览所有可用 LUT、查看调色板和每种颜色的用量覆盖，还能在 2D/3D 视图里看色相覆盖图和 Lab 点云，心里有数再去选 LUT",
            en: "A new 「LUT details」 entry in the top Material-Management menu lets you browse every available LUT, inspect its palette and per-colour coverage, and view hue-coverage charts plus a Lab point cloud in 2D/3D — so you can pick a LUT with a clear idea of what it actually covers",
          },
          {
            zh: "自定义配方可以加 LUT 里没有的颜色了：下拉直接选，导出的 3MF 会自动多一个对象带上这种颜色，切片那边不用自己改",
            en: "You can now add colours that aren't in the LUT to a custom recipe: pick them from the dropdown and the exported 3MF carries them as extra objects, so the slicer just works",
          },
          {
            zh: "设置里加了「渐变自动换色」开关：开启后每次预览成功会自动把每一组渐变统一替换成组内代表色，一键去掉海带纹；默认关闭，原有手动换色流程不受影响",
            en: "New Settings → 「Auto replace gradient banding」 toggle: when on, every successful preview auto-collapses each gradient group to its representative colour to erase banding in one shot; off by default so the manual flow stays unchanged",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "耗材档案模式下，预览完成后会自动检测原图里平滑渐变被切成多种耗材色的情况，在颜色面板里列成一组一组，点一下就能把整组色块一次选中送去换色",
            en: "In material-archive mode, a successful preview automatically detects smooth source gradients that got quantised into several material colours and lists them as gradient groups; one click multi-selects the whole group for batch replacement",
          },
          {
            zh: "每组还能展开看到里面的独立区域（脸、嘴巴、手等），按区域单独选颜色，而不是只能整组一起换",
            en: "Expand a group to see its spatial regions (face, mouth, hand, etc.) and select a single region's colours instead of the whole group",
          },
          {
            zh: "每个大分组和小分组右边都加了一个「去海带纹」按钮，不必先选中再回到拾色器，直接一键把这一处渐变压成代表色",
            en: "Every group and region row now has its own Flatten button — no need to first multi-select and pick a target colour, one click collapses that specific gradient to its representative colour",
          },
          {
            zh: "在不同分组之间快速切换时，预览上不会再因为旧请求晚到而显示到旧的高亮色，始终跟当前选中保持一致",
            en: "Rapid switching between gradient groups no longer leaves a stale highlight on the preview: out-of-order responses are dropped so the canvas always matches the current selection",
          },
          {
            zh: "从整组切到组内某个区域时，整组按钮会正确地变灰、只有被点击的区域保持选中态；不会再出现整组和区域同时显示选中的情况",
            en: "Clicking a region inside a group correctly dims the parent group button so only the region you just picked stays highlighted, instead of both lighting up at once",
          },
          {
            zh: "点击小分组时，右边预览只会高亮这个小分组所在的那一块区域，不再把整组覆盖的同色像素全部点亮",
            en: "Clicking a sub-region now highlights only that region in the preview, instead of lighting up every matching pixel across the whole group",
          },
          {
            zh: "选中某个小分组后再从 LUT 里挑颜色换色，现在只会改这一块区域的像素；共享相同颜色的其它区域不会再被一起覆盖",
            en: "Picking a LUT colour while a sub-region is selected now repaints only that region's pixels; other regions that happen to share the same colour stay untouched",
          },
          {
            zh: "打开自定义配方，下拉里能看到每种材料的真实颜色，不再是一堆灰方块",
            en: "Open the custom recipe dialog and the dropdown swatches show each material's actual colour instead of a row of grey placeholders",
          },
          {
            zh: '用耗材档案做的模型现在也能改自定义配方了，不会再弹 "没有预测引擎" 的提示',
            en: 'Models built from the material library now accept custom recipes too — the old "no predictive runtime" blocker is gone',
          },
          {
            zh: "打开配方时，每层的初始值就是这个色块实际在用的配方，而不是全白；只改一两层不会再把别的层覆盖掉",
            en: "When you open the recipe dialog, every layer starts with the colour it's actually using, not pure white — so tweaking one or two layers doesn't wipe the rest",
          },
          {
            zh: '点应用之后，分层预览会整屏刷新；不再出现 "只有改过的层亮起、其它层灰掉" 的情况',
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
            zh: '提取完出的一堆 JSON、拟合摘要、Stage A 下载全收进一个 "详情" 按钮里，主面板干净多了',
            en: 'The JSON dumps, fit summary and Stage A download link now live behind a single "Details" button, keeping the main panel uncluttered',
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
          {
            zh: "设置里新增 「穷举数量」 开关：默认关闭，走低档（64³，构建快、内存小）；开启后可以选中（128³）或高（256³），穷举缓存会更细、颜色更准，代价是构建时间、内存占用、每次生成查找都会成倍变长。穷举缓存弹窗里会直接显示当前用哪一档，不同档的缓存分开存放、互不覆盖",
            en: 'New Settings → "Exhaustive density" switch: off by default and uses the low tier (64³) — fast to build, low memory; flip it on to pick medium (128³) or high (256³) for tighter colour accuracy at the cost of proportionally longer builds, more memory, and slower per-conversion lookups. The exhaustive-cache dialog shows the active tier, and caches at different tiers are stored separately so switching never overwrites an existing build',
          },
          {
            zh: "耗材库的「编辑信息」弹窗里新增显示颜色编辑：可直接用颜色选择器挑色，或输入 #RRGGBB 色号，保存后列表、选色面板和预览上的耗材色块都会跟着更新；再做一次复测会用新的测量值覆盖回去",
            en: "The Material Library → Edit Details dialog now lets you override the display colour: pick a colour with the native picker or type a #RRGGBB code, and after saving the library, picker and preview swatches all follow suit; running a new verification will overwrite it with the freshly measured colour again",
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
            zh: "分层遮罩查看窗新增放大镜：鼠标悬停画布时会跟随出现一个高倍放大窗口，对齐细小边缘和逐层检查方便多了，窗口内部仍用 Canvas 绘制，不占显存",
            en: "The layer-mask viewer gains a follow-cursor magnifier: hover over the canvas and a zoomed-in lens tracks the pointer, making it easier to align fine edges and double-check layers without extra GPU cost",
          },
          {
            zh: "3D 预览加载大幅提速：以前上百 MB 的预览模型在远程使用时要等很久才出现，现在真实多色图通常只有几 MB，一打开画面就能看到 3D 模型；实际导出的 3MF 和打印精度完全不受影响",
            en: "The 3D preview loads dramatically faster: what used to be a 100+ MB model that kept remote users waiting is now typically just a few MB on real multi-colour images, so the 3D scene appears almost immediately; the actual exported 3MF and its print precision are completely unchanged",
          },
          {
            zh: '厚度等滑条修掉了"一松手就自动加 0.08"的问题：之前每次拖动停下来，值都会被悄悄往上多挪半格；右边数字框里手动输入 1.5 / 3.5 也不会再被改成 0.08 的整数倍（如 1.52）',
            en: "Sliders like Thickness no longer add an extra 0.08 every time you let go: previously each drag release was silently bumped up by half a step, and typing precise values like 1.5 or 3.5 into the number box on the right got rewritten to the nearest step multiple (such as 1.52)",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "含描边的 SVG 生成更贴合线稿：默认忽略纯描边轮廓与同色描边扩边，避免黑边与线条变粗",
            en: "SVGs with strokes now match the drawing more closely: stroke-only outlines and same-colour stroke padding are ignored by default, removing dark edges and thickened lines",
          },
          {
            zh: "插画类 SVG 预览回到干净矢量效果：细描边的粗细和源文件保持一致，不再被整体加粗；尖角也不会外突出锯齿毛刺",
            en: "Illustrated SVGs now preview as clean vectors: thin stroke widths follow the source file instead of being globally thickened, and sharp corners no longer produce outward spikes or fuzzy jaggies",
          },
          {
            zh: "2D 预览形状边缘过渡更平滑，告别像素化阶梯锯齿",
            en: "2D preview shape boundaries are noticeably smoother, replacing the stair-stepped pixel jaggies with anti-aliased edges",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "与参考实现对齐 backing silhouette 的 close / hole / slit 过滤阈值，并为色块层补充空洞过滤，减少白色气泡",
            en: "Align backing silhouette close / hole / slit thresholds and add color-layer hole filtering with the reference implementation to reduce white bubble artifacts",
          },
          {
            zh: "SVG 矢量图 + 传统 LUT 模式下，自定义配方里改过的颜色和加过的层，现在会真实写进导出的 3MF；之前只能在 2D 预览里看到效果，实际 3MF 会悄悄退回 LUT 默认配色，加的层也像没加过一样",
            en: "For SVG vector inputs with a traditional LUT, recipe edits and extra layers made in the custom recipe dialog now actually land in the exported 3MF; previously the 2D preview reflected them but the 3MF silently fell back to the LUT's default match, as if the custom recipe and added layers had never been applied",
          },
          {
            zh: "反推 LUT 导出的 3MF 不再跟上一次选过的传统 LUT 串色：之前如果上次选的是 CMYW，反推 LUT 的蓝 / 红 / 绿 / 黑会被错刷成青 / 品红 / 黄，黑甚至变成白；栅格（高保真）和 SVG 矢量建模两种路径现在都直接用反推 LUT 自己的调色板，耗材槽名和颜色不再因为上次的颜色模式而翻车",
            en: "3MF files exported from the Inferred LUT no longer pick up colours from the previously-selected legacy LUT: blue / red / green / black slots used to be silently recoloured as cyan / magenta / yellow (and black could come out white) when CMYW was picked last — both the raster (high-fidelity) and SVG vector modelling paths now honour the Inferred LUT's own palette, so filament slot names and colours are correct regardless of what colour mode was used before",
          },
          {
            zh: "梯度卡提取或保存失败时，会告诉你具体是哪一步出问题（ZIP 格式不对、图片解码不出来、角点选少了、基底方向认不出来、会话过期、找不到目标档案等），不再甩一串英文报错",
            en: "When gradient-card extract / save fails, you now get a clear sentence about what went wrong (bad ZIP, undecodable image, wrong number of corner points, can't tell substrate orientation, expired session, target archive missing, …) instead of a raw English error",
          },
          {
            zh: '提交表单填错字段时，弹窗会直接点名哪个字段有问题；之前偶尔会被 "请求失败 status 422" 这种模糊提示盖住',
            en: 'When form fields are invalid, the dialog now names the offending field directly, instead of sometimes masking it behind a generic "request failed with status 422"',
          },
          {
            zh: '修了一个隐藏 bug：有些字段校验错误本来该返回 422，却被内部处理器弄成 500 显示成 "服务器崩了"，现在已经走正规流程',
            en: "Fixed a hidden bug where some field-validation errors (which should be 422) were turning into 500s that looked like server crashes; they now follow the normal path",
          },
          {
            zh: '耗材档案里的自定义配方应用不再卡在 "LUT/source file missing" 409，整套流程能走通',
            en: 'Applying a custom recipe on a material-archive model no longer gets stuck on "LUT/source file missing" (409) — the whole flow works end to end',
          },
          {
            zh: "扩层时的边界修正：模型外面原本该透明的地方保持透明，不会再多一圈白边；模型里面没改动的像素继续沿用背板材料，不会塌成空层",
            en: "When the layer count is extended: transparent background outside the model stays transparent (no more white ring), and untouched pixels inside the model keep their backing material (no more collapsed empty layers)",
          },
          {
            zh: "导出的 3MF 现在能在 Anycubic 切片软件（纵维立方 Anycubic Slicer Next）里正常打开——之前一拖进去就闪退，原因是自动生成的预览缩略图本身就是损坏的；别的切片软件一直没受影响，是因为它们遇到坏缩略图会静默跳过",
            en: "Exported 3MF files now open normally in Anycubic Slicer Next — they used to crash the moment you dropped one in, because the auto-generated preview thumbnails were themselves corrupt; other slicers were unaffected because they silently skip over broken thumbnails",
          },
          {
            zh: "耗材档案预览：偶尔出现的 「10 层效果反而比 5 层差」 已修复。更多层数的匹配结果现在严格不劣于少层数 + 白色垫底的方案，预览颜色趋于稳定",
            en: "Material-archive preview: the occasional 「10 layers look worse than 5 layers」 regression is fixed — higher layer counts are now guaranteed to be no worse than any smaller-k solution padded with white, so preview colour stays consistent as you raise the layer count",
          },
        ],
      },
    ],
  },
  {
    version: "2026-04-23",
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
          {
            zh: "设置里加了「渐变自动换色」开关：开启后每次预览成功会自动把每一组渐变统一替换成组内代表色，一键去掉海带纹；默认关闭，原有手动换色流程不受影响",
            en: "New Settings → 「Auto replace gradient banding」 toggle: when on, every successful preview auto-collapses each gradient group to its representative colour to erase banding in one shot; off by default so the manual flow stays unchanged",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "耗材档案模式下，预览完成后会自动检测原图里平滑渐变被切成多种耗材色的情况，在颜色面板里列成一组一组，点一下就能把整组色块一次选中送去换色",
            en: "In material-archive mode, a successful preview automatically detects smooth source gradients that got quantised into several material colours and lists them as gradient groups; one click multi-selects the whole group for batch replacement",
          },
          {
            zh: "每组还能展开看到里面的独立区域（脸、嘴巴、手等），按区域单独选颜色，而不是只能整组一起换",
            en: "Expand a group to see its spatial regions (face, mouth, hand, etc.) and select a single region's colours instead of the whole group",
          },
          {
            zh: "每个大分组和小分组右边都加了一个「去海带纹」按钮，不必先选中再回到拾色器，直接一键把这一处渐变压成代表色",
            en: "Every group and region row now has its own Flatten button — no need to first multi-select and pick a target colour, one click collapses that specific gradient to its representative colour",
          },
          {
            zh: "在不同分组之间快速切换时，预览上不会再因为旧请求晚到而显示到旧的高亮色，始终跟当前选中保持一致",
            en: "Rapid switching between gradient groups no longer leaves a stale highlight on the preview: out-of-order responses are dropped so the canvas always matches the current selection",
          },
          {
            zh: "从整组切到组内某个区域时，整组按钮会正确地变灰、只有被点击的区域保持选中态；不会再出现整组和区域同时显示选中的情况",
            en: "Clicking a region inside a group correctly dims the parent group button so only the region you just picked stays highlighted, instead of both lighting up at once",
          },
          {
            zh: "点击小分组时，右边预览只会高亮这个小分组所在的那一块区域，不再把整组覆盖的同色像素全部点亮",
            en: "Clicking a sub-region now highlights only that region in the preview, instead of lighting up every matching pixel across the whole group",
          },
          {
            zh: "选中某个小分组后再从 LUT 里挑颜色换色，现在只会改这一块区域的像素；共享相同颜色的其它区域不会再被一起覆盖",
            en: "Picking a LUT colour while a sub-region is selected now repaints only that region's pixels; other regions that happen to share the same colour stay untouched",
          },
          {
            zh: "打开自定义配方，下拉里能看到每种材料的真实颜色，不再是一堆灰方块",
            en: "Open the custom recipe dialog and the dropdown swatches show each material's actual colour instead of a row of grey placeholders",
          },
          {
            zh: '用耗材档案做的模型现在也能改自定义配方了，不会再弹 "没有预测引擎" 的提示',
            en: 'Models built from the material library now accept custom recipes too — the old "no predictive runtime" blocker is gone',
          },
          {
            zh: "打开配方时，每层的初始值就是这个色块实际在用的配方，而不是全白；只改一两层不会再把别的层覆盖掉",
            en: "When you open the recipe dialog, every layer starts with the colour it's actually using, not pure white — so tweaking one or two layers doesn't wipe the rest",
          },
          {
            zh: '点应用之后，分层预览会整屏刷新；不再出现 "只有改过的层亮起、其它层灰掉" 的情况',
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
            zh: '提取完出的一堆 JSON、拟合摘要、Stage A 下载全收进一个 "详情" 按钮里，主面板干净多了',
            en: 'The JSON dumps, fit summary and Stage A download link now live behind a single "Details" button, keeping the main panel uncluttered',
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
          {
            zh: '厚度等滑条修掉了"一松手就自动加 0.08"的问题：之前每次拖动停下来，值都会被悄悄往上多挪半格；右边数字框里手动输入 1.5 / 3.5 也不会再被改成 0.08 的整数倍（如 1.52）',
            en: "Sliders like Thickness no longer add an extra 0.08 every time you let go: previously each drag release was silently bumped up by half a step, and typing precise values like 1.5 or 3.5 into the number box on the right got rewritten to the nearest step multiple (such as 1.52)",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "SVG 矢量图 + 传统 LUT 模式下，自定义配方里改过的颜色和加过的层，现在会真实写进导出的 3MF；之前只能在 2D 预览里看到效果，实际 3MF 会悄悄退回 LUT 默认配色，加的层也像没加过一样",
            en: "For SVG vector inputs with a traditional LUT, recipe edits and extra layers made in the custom recipe dialog now actually land in the exported 3MF; previously the 2D preview reflected them but the 3MF silently fell back to the LUT's default match, as if the custom recipe and added layers had never been applied",
          },
          {
            zh: "反推 LUT 导出的 3MF 不再跟上一次选过的传统 LUT 串色：之前如果上次选的是 CMYW，反推 LUT 的蓝 / 红 / 绿 / 黑会被错刷成青 / 品红 / 黄，黑甚至变成白；栅格（高保真）和 SVG 矢量建模两种路径现在都直接用反推 LUT 自己的调色板，耗材槽名和颜色不再因为上次的颜色模式而翻车",
            en: "3MF files exported from the Inferred LUT no longer pick up colours from the previously-selected legacy LUT: blue / red / green / black slots used to be silently recoloured as cyan / magenta / yellow (and black could come out white) when CMYW was picked last — both the raster (high-fidelity) and SVG vector modelling paths now honour the Inferred LUT's own palette, so filament slot names and colours are correct regardless of what colour mode was used before",
          },
          {
            zh: "梯度卡提取或保存失败时，会告诉你具体是哪一步出问题（ZIP 格式不对、图片解码不出来、角点选少了、基底方向认不出来、会话过期、找不到目标档案等），不再甩一串英文报错",
            en: "When gradient-card extract / save fails, you now get a clear sentence about what went wrong (bad ZIP, undecodable image, wrong number of corner points, can't tell substrate orientation, expired session, target archive missing, …) instead of a raw English error",
          },
          {
            zh: '提交表单填错字段时，弹窗会直接点名哪个字段有问题；之前偶尔会被 "请求失败 status 422" 这种模糊提示盖住',
            en: 'When form fields are invalid, the dialog now names the offending field directly, instead of sometimes masking it behind a generic "request failed with status 422"',
          },
          {
            zh: '修了一个隐藏 bug：有些字段校验错误本来该返回 422，却被内部处理器弄成 500 显示成 "服务器崩了"，现在已经走正规流程',
            en: "Fixed a hidden bug where some field-validation errors (which should be 422) were turning into 500s that looked like server crashes; they now follow the normal path",
          },
          {
            zh: '耗材档案里的自定义配方应用不再卡在 "LUT/source file missing" 409，整套流程能走通',
            en: 'Applying a custom recipe on a material-archive model no longer gets stuck on "LUT/source file missing" (409) — the whole flow works end to end',
          },
          {
            zh: "扩层时的边界修正：模型外面原本该透明的地方保持透明，不会再多一圈白边；模型里面没改动的像素继续沿用背板材料，不会塌成空层",
            en: "When the layer count is extended: transparent background outside the model stays transparent (no more white ring), and untouched pixels inside the model keep their backing material (no more collapsed empty layers)",
          },
          {
            zh: "导出的 3MF 现在能在 Anycubic 切片软件（纵维立方 Anycubic Slicer Next）里正常打开——之前一拖进去就闪退，原因是自动生成的预览缩略图本身就是损坏的；别的切片软件一直没受影响，是因为它们遇到坏缩略图会静默跳过",
            en: "Exported 3MF files now open normally in Anycubic Slicer Next — they used to crash the moment you dropped one in, because the auto-generated preview thumbnails were themselves corrupt; other slicers were unaffected because they silently skip over broken thumbnails",
          },
          {
            zh: "耗材档案预览：偶尔出现的 「10 层效果反而比 5 层差」 已修复。更多层数的匹配结果现在严格不劣于少层数 + 白色垫底的方案，预览颜色趋于稳定",
            en: "Material-archive preview: the occasional 「10 layers look worse than 5 layers」 regression is fixed — higher layer counts are now guaranteed to be no worse than any smaller-k solution padded with white, so preview colour stays consistent as you raise the layer count",
          },
        ],
      },
    ],
  },
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
            zh: '用耗材档案做的模型现在也能改自定义配方了，不会再弹 "没有预测引擎" 的提示',
            en: 'Models built from the material library now accept custom recipes too — the old "no predictive runtime" blocker is gone',
          },
          {
            zh: "打开配方时，每层的初始值就是这个色块实际在用的配方，而不是全白；只改一两层不会再把别的层覆盖掉",
            en: "When you open the recipe dialog, every layer starts with the colour it's actually using, not pure white — so tweaking one or two layers doesn't wipe the rest",
          },
          {
            zh: '点应用之后，分层预览会整屏刷新；不再出现 "只有改过的层亮起、其它层灰掉" 的情况',
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
            zh: '提取完出的一堆 JSON、拟合摘要、Stage A 下载全收进一个 "详情" 按钮里，主面板干净多了',
            en: 'The JSON dumps, fit summary and Stage A download link now live behind a single "Details" button, keeping the main panel uncluttered',
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
          {
            zh: "设置里新增 「穷举数量」 开关：默认关闭，走低档（64³，构建快、内存小）；开启后可以选中（128³）或高（256³），穷举缓存会更细、颜色更准，代价是构建时间、内存占用、每次生成查找都会成倍变长。穷举缓存弹窗里会直接显示当前用哪一档，不同档的缓存分开存放、互不覆盖",
            en: 'New Settings → "Exhaustive density" switch: off by default and uses the low tier (64³) — fast to build, low memory; flip it on to pick medium (128³) or high (256³) for tighter colour accuracy at the cost of proportionally longer builds, more memory, and slower per-conversion lookups. The exhaustive-cache dialog shows the active tier, and caches at different tiers are stored separately so switching never overwrites an existing build',
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
          {
            zh: '厚度等滑条修掉了"一松手就自动加 0.08"的问题：之前每次拖动停下来，值都会被悄悄往上多挪半格；右边数字框里手动输入 1.5 / 3.5 也不会再被改成 0.08 的整数倍（如 1.52）',
            en: "Sliders like Thickness no longer add an extra 0.08 every time you let go: previously each drag release was silently bumped up by half a step, and typing precise values like 1.5 or 3.5 into the number box on the right got rewritten to the nearest step multiple (such as 1.52)",
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
            zh: '提交表单填错字段时，弹窗会直接点名哪个字段有问题；之前偶尔会被 "请求失败 status 422" 这种模糊提示盖住',
            en: 'When form fields are invalid, the dialog now names the offending field directly, instead of sometimes masking it behind a generic "request failed with status 422"',
          },
          {
            zh: '修了一个隐藏 bug：有些字段校验错误本来该返回 422，却被内部处理器弄成 500 显示成 "服务器崩了"，现在已经走正规流程',
            en: "Fixed a hidden bug where some field-validation errors (which should be 422) were turning into 500s that looked like server crashes; they now follow the normal path",
          },
          {
            zh: '耗材档案里的自定义配方应用不再卡在 "LUT/source file missing" 409，整套流程能走通',
            en: 'Applying a custom recipe on a material-archive model no longer gets stuck on "LUT/source file missing" (409) — the whole flow works end to end',
          },
          {
            zh: "扩层时的边界修正：模型外面原本该透明的地方保持透明，不会再多一圈白边；模型里面没改动的像素继续沿用背板材料，不会塌成空层",
            en: "When the layer count is extended: transparent background outside the model stays transparent (no more white ring), and untouched pixels inside the model keep their backing material (no more collapsed empty layers)",
          },
          {
            zh: "导出的 3MF 现在能在 Anycubic 切片软件（纵维立方 Anycubic Slicer Next）里正常打开——之前一拖进去就闪退，原因是自动生成的预览缩略图本身就是损坏的；别的切片软件一直没受影响，是因为它们遇到坏缩略图会静默跳过",
            en: "Exported 3MF files now open normally in Anycubic Slicer Next — they used to crash the moment you dropped one in, because the auto-generated preview thumbnails were themselves corrupt; other slicers were unaffected because they silently skip over broken thumbnails",
          },
          {
            zh: "耗材档案预览：偶尔出现的 「10 层效果反而比 5 层差」 已修复。更多层数的匹配结果现在严格不劣于少层数 + 白色垫底的方案，预览颜色趋于稳定",
            en: "Material-archive preview: the occasional 「10 layers look worse than 5 layers」 regression is fixed — higher layer counts are now guaranteed to be no worse than any smaller-k solution padded with white, so preview colour stays consistent as you raise the layer count",
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
            zh: '用耗材档案做的模型现在也能改自定义配方了，不会再弹 "没有预测引擎" 的提示',
            en: 'Models built from the material library now accept custom recipes too — the old "no predictive runtime" blocker is gone',
          },
          {
            zh: "打开配方时，每层的初始值就是这个色块实际在用的配方，而不是全白；只改一两层不会再把别的层覆盖掉",
            en: "When you open the recipe dialog, every layer starts with the colour it's actually using, not pure white — so tweaking one or two layers doesn't wipe the rest",
          },
          {
            zh: '点应用之后，分层预览会整屏刷新；不再出现 "只有改过的层亮起、其它层灰掉" 的情况',
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
            zh: '提取完出的一堆 JSON、拟合摘要、Stage A 下载全收进一个 "详情" 按钮里，主面板干净多了',
            en: 'The JSON dumps, fit summary and Stage A download link now live behind a single "Details" button, keeping the main panel uncluttered',
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
            zh: '提交表单填错字段时，弹窗会直接点名哪个字段有问题；之前偶尔会被 "请求失败 status 422" 这种模糊提示盖住',
            en: 'When form fields are invalid, the dialog now names the offending field directly, instead of sometimes masking it behind a generic "request failed with status 422"',
          },
          {
            zh: '修了一个隐藏 bug：有些字段校验错误本来该返回 422，却被内部处理器弄成 500 显示成 "服务器崩了"，现在已经走正规流程',
            en: "Fixed a hidden bug where some field-validation errors (which should be 422) were turning into 500s that looked like server crashes; they now follow the normal path",
          },
          {
            zh: '耗材档案里的自定义配方应用不再卡在 "LUT/source file missing" 409，整套流程能走通',
            en: 'Applying a custom recipe on a material-archive model no longer gets stuck on "LUT/source file missing" (409) — the whole flow works end to end',
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
            zh: "颜色替换后，鼠标悬停「分层颜色」现在会同步更新，不再显示替换前的旧颜色",
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
        category: {
          zh: "提取器（校色卡）",
          en: "Extractor (Calibration Card)",
        },
        items: [
          {
            zh: "5 色扩展模式每一页的角点提示修正",
            en: "Fixed per-page corner-label hints for the 5-Color Extended mode",
          },
          {
            zh: "点「清除角点」会顺带重置预览，直接回到拾取状态",
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
            zh: "2D 预览新增「按住查看原图」：长按按钮或按住键盘 Shift 键即可临时覆盖显示原始图片，松手自动回到生成效果",
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
            zh: "下拉菜单宽度跟随触发器自适应，选项不多时也不会被错误判定为「下方空间不足」而翻到上方",
            en: "Dropdown menu width now follows its trigger, and short menus no longer flip upward when there is actually enough room below",
          },
          {
            zh: "3D 视图新增「性能」按钮：实时查看 FPS、显存占用、几何体 / 纹理数量和画布尺寸",
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
