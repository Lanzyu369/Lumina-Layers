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
    version: "2026-04-25",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "顶部材料管理新增 “LUT 详情” 入口：可以浏览所有 LUT、看调色板和颜色覆盖范围，还能用色相图和 Lab 点云确认它适不适合当前图。",
            en: "The top Material Management menu now has a “LUT details” entry where you can browse every LUT, inspect its palette and coverage, and use hue charts plus a Lab point cloud to judge whether it fits the current artwork.",
          },
          {
            zh: "自定义配方现在可以加入 LUT 里没有的颜色，导出的 3MF 会自动带上这些额外对象，切片时不用再手动补。",
            en: "Custom recipes can now include colours that are not in the LUT, and exported 3MF files carry those extra objects automatically so you do not have to patch them in the slicer.",
          },
          {
            zh: "设置里新增“渐变自动换色”开关，打开后预览成功会自动把每组渐变压成代表色，想省事去条纹时可以直接开。",
            en: "Settings now include an “Auto replace gradient banding” switch that collapses each detected gradient group to its representative colour after preview, useful when you want the quickest banding cleanup.",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "传统 LUT 选择改成“品牌 → 颜色数”的二级菜单，个人 LUT 会显示成“个人”，选中后也会用系统真正认识的 LUT 名称去预览，不会再因为详细名对不上而找不到预设。",
            en: "The legacy LUT picker now uses a Brand → colour-count menu, shows personal LUTs as Personal, and submits the LUT name the app can actually preview so detailed catalog labels no longer lose the preset.",
          },
          {
            zh: "耗材档案预览会把平滑渐变里被切开的颜色自动整理成分组，还能展开到脸、嘴巴、手这类小区域，点哪里就只处理哪里。",
            en: "Material-archive previews now group the colours that came from one smooth gradient and can expand them into smaller regions such as face, mouth, or hands, so clicking a region edits only that spot.",
          },
          {
            zh: "渐变分组和小区域都有一键“去海带纹”，多个小区域还能勾选后一起合并成同一个代表色，或者一起刷成从 LUT 里点到的颜色。",
            en: "Gradient groups and sub-regions now have one-click flattening, and checked sub-regions can be merged to one representative colour or repainted together with a LUT colour pick.",
          },
          {
            zh: "选中的小区域可以做“二次量化”：给每块区域单独选 12–256 个颜色重新匹配，脸部和皮肤这类低频渐变会比直接压平更自然。",
            en: "Selected sub-regions can be re-quantized with their own 12–256 colour budget, keeping low-frequency gradients such as faces and skin more natural than a hard flatten.",
          },
          {
            zh: "耗材档案做出来的模型现在也能改自定义配方，弹窗一打开就是当前真实配方和真实材料颜色，改一两层不会把其它层冲掉。",
            en: "Models made from material archives can now use custom recipes too, with the dialog seeded from the real current recipe and real material colours so editing one or two layers no longer wipes the rest.",
          },
          {
            zh: "换色、区域换色和去条纹的等待时间明显短了：2D 图先更新，重的 3D 重建放到后台跑，分层预览也会并发生成，来回调色不用一直干等。",
            en: "Colour swaps, region edits, and banding cleanup are much faster: the 2D result updates first, heavy 3D rebuilds run in the background, and layer previews are generated in parallel so colour tuning has much less waiting.",
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
            zh: "耗材库里已经存好的条目可以直接改名字和品牌，品牌输入也变成了会记住旧品牌的下拉框，不用为了改个名字重新扫卡。",
            en: "Saved material-library entries can now be renamed and rebranded in place, and the brand field is a dropdown that remembers previous brands so you do not need to rescan a card just to tidy names.",
          },
          {
            zh: "提取器面板把调试文件、拟合摘要和下载入口都收进“详情”里，保存成功或失败也改成右上角提示，主面板不会再被挤乱。",
            en: "The extractor panel now tucks debug files, fit summaries, and download links behind Details, while save success or failure appears as a top-right toast instead of pushing the panel around.",
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
            zh: "梯度卡校准默认层高改成 0.08 mm，更贴近日常打印；以前保存过的档案保持原样，不会被自动改。",
            en: "Gradient-card calibration now defaults to 0.08 mm layer height, closer to everyday printing, while already-saved archives keep their original values.",
          },
          {
            zh: "设置里新增“穷举数量”：默认低档更快更省内存，也可以切到中档或高档换更细的颜色缓存，不同档位会分开存。",
            en: "Settings now include exhaustive density: the default low tier is faster and lighter, while medium and high build finer colour caches that are stored separately.",
          },
          {
            zh: "耗材库的编辑弹窗可以直接改显示颜色，既能用颜色选择器也能填 #RRGGBB；下次重新实测时会用新的测量值覆盖回来。",
            en: "The material-library edit dialog can override the display colour with a colour picker or #RRGGBB value, and a future verification run will replace it with the freshly measured colour.",
          },
          {
            zh: "耗材预设里补进了无境新材，建档和选材时少一步手动录入。",
            en: "Wujing material presets have been added, reducing manual entry when building or selecting material archives.",
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
            zh: "分层遮罩查看窗新增跟随鼠标的放大镜，检查细边和层间对齐时不用再来回缩放。",
            en: "The layer-mask viewer now has a follow-cursor magnifier, making fine-edge and layer-alignment checks easier without constant zooming.",
          },
          {
            zh: "3D 预览模型变得小很多、加载快很多，远程打开也能更快看到模型，真正导出的 3MF 和打印精度不受影响。",
            en: "3D preview models are much smaller and load far faster, especially over remote sessions, while exported 3MF files and print accuracy stay unchanged.",
          },
          {
            zh: "滑块拖动时不会再自己多跳半格，数值会乖乖停在你拖到的位置。",
            en: "Sliders no longer bump themselves by half a step while dragging, so values stay where you actually placed them.",
          },
          {
            zh: "导出的 3MF 会带一个切片器能正常读取的预览图，占位图不再卡住 Anycubic Slicer Next。",
            en: "Exported 3MF files now include a preview image that slicers can read correctly, so placeholder thumbnails no longer hang Anycubic Slicer Next.",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 导出 3MF 时会真正带上自定义配方和额外添加的颜色层，不会只在界面上看着改了、导出后又丢掉。",
            en: "SVG-to-3MF export now carries custom recipes and extra colour layers through to the file instead of only showing them in the UI.",
          },
          {
            zh: "带插画风细线的 SVG 不会再被悄悄加粗，复杂边缘处理失败时也会自动走兜底，不会整次生成断掉。",
            en: "Illustrated SVGs with fine strokes are no longer silently widened, and complex edge-processing failures now fall back safely instead of breaking the whole generation.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "反推 LUT 会坚持使用自己带的调色板，就算设置里还残留着旧颜色模式，也不会拿错颜色去匹配。",
            en: "Inferred LUTs now keep using their own palettes even if settings still contain an older colour mode, avoiding mismatched colour picks.",
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
            zh: "顶部材料管理新增 “LUT 详情” 入口：可以浏览所有可用 LUT、查看调色板和每种颜色的用量覆盖，还能在 2D/3D 视图里看色相覆盖图和 Lab 点云，心里有数再去选 LUT",
            en: "A new “LUT details” entry in the top Material-Management menu lets you browse every available LUT, inspect its palette and per-colour coverage, and view hue-coverage charts plus a Lab point cloud in 2D/3D — so you can pick a LUT with a clear idea of what it actually covers",
          },
          {
            zh: "自定义配方可以加 LUT 里没有的颜色了：下拉直接选，导出的 3MF 会自动多一个对象带上这种颜色，切片那边不用自己改",
            en: "You can now add colours that aren't in the LUT to a custom recipe: pick them from the dropdown and the exported 3MF carries them as extra objects, so the slicer just works",
          },
          {
            zh: "设置里加了“渐变自动换色”开关：开启后每次预览成功会自动把每一组渐变统一替换成组内代表色，一键去掉海带纹；默认关闭，原有手动换色流程不受影响",
            en: "New Settings → “Auto replace gradient banding” toggle: when on, every successful preview auto-collapses each gradient group to its representative colour to erase banding in one shot; off by default so the manual flow stays unchanged",
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
            zh: "每个大分组和小分组右边都加了一个“去海带纹”按钮，不必先选中再回到拾色器，直接一键把这一处渐变压成代表色",
            en: "Every group and region row now has its own Flatten button — no need to first multi-select and pick a target colour, one click collapses that specific gradient to its representative colour",
          },
          {
            zh: "区域勾选后新增“二次量化”按钮：弹窗里选一个 12-256 的色数，对每个选中的区域按原图单独做一次局部量化，再走同一个耗材求解器重匹配。能保留脸部/皮肤这类低频渐变，同时把条纹压成大块，效果比直接平坦化更自然",
            en: "A new Re-quantize button appears next to checked regions: pick a 12-256 colour budget in the dialog and, for each selected region, we run a dedicated K-Means on the original source then re-match through the same material solver — keeps low-frequency gradients like faces and skin while collapsing kelp banding into clean blocks, far more natural than flatten",
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
          {
            zh: "展开分层预览面板也变快了：过去每次换色后第一次打开要等好几秒，现在分层图按层并发生成、编码更快，同一状态下再打开几乎是秒开",
            en: "The per-layer preview panel opens much faster too: after a colour swap the first open used to stall for several seconds, now layer PNGs encode in parallel at a lighter compression and reopens under the same state are effectively instant",
          },
          {
            zh: "替换颜色、去海带纹、区域点击换色现在响应更快：2D 预览一算完就立即更新（大图上通常 10 秒内），耗时最重的 3D 预览交给后台线程重建，完成后自动刷新到 3D 窗口；以往整体要等 30–60 秒才动",
            en: "Colour swap, banding flatten and region click-to-replace now feel much snappier: the 2D preview updates as soon as it's computed (usually under 10 s even on big images) while the heavy 3D rebuild runs on a background thread and refreshes the 3D viewport on its own — no more 30–60 s stalls end to end",
          },
          {
            zh: '渐变分组面板里每个小区域多了勾选框：勾上同一个分组里的多个小区域后，分组顶部会出现"合并去海带纹"按钮，一键把这些小区域统一成同一个代表色；如果想换成别的颜色，勾选后去 LUT 拍色器点一下即可，所有勾选的小区域都会同步刷成那个色',
            en: "Each sub-region inside a gradient group now has a checkbox: tick two or more regions of the same group and a new Merge flatten button appears at the group header, collapsing those regions to one unified representative colour in one shot; for a different target, just tick the regions and pick a colour in the LUT picker — every ticked region is repainted to that colour together",
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
            zh: "设置里新增 “穷举数量” 开关：默认关闭，走低档（64³，构建快、内存小）；开启后可以选中（128³）或高（256³），穷举缓存会更细、颜色更准，代价是构建时间、内存占用、每次生成查找都会成倍变长。穷举缓存弹窗里会直接显示当前用哪一档，不同档的缓存分开存放、互不覆盖",
            en: 'New Settings → "Exhaustive density" switch: off by default and uses the low tier (64³) — fast to build, low memory; flip it on to pick medium (128³) or high (256³) for tighter colour accuracy at the cost of proportionally longer builds, more memory, and slower per-conversion lookups. The exhaustive-cache dialog shows the active tier, and caches at different tiers are stored separately so switching never overwrites an existing build',
          },
          {
            zh: "耗材库的“编辑信息”弹窗里新增显示颜色编辑：可直接用颜色选择器挑色，或输入 #RRGGBB 色号，保存后列表、选色面板和预览上的耗材色块都会跟着更新；再做一次复测会用新的测量值覆盖回去",
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
            zh: "与参考实现对齐 backing silhouette 的 close / hole / slit 过滤阈值，并为色块层补充空洞过滤，减少白色气泡。",
            en: "Align backing silhouette close / hole / slit thresholds and add color-layer hole filtering with the reference implementation to reduce white bubble artifacts.",
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
            zh: "耗材档案预览：偶尔出现的 “10 层效果反而比 5 层差” 已修复。更多层数的匹配结果现在严格不劣于少层数 + 白色垫底的方案，预览颜色趋于稳定",
            en: "Material-archive preview: the occasional “10 layers look worse than 5 layers” regression is fixed — higher layer counts are now guaranteed to be no worse than any smaller-k solution padded with white, so preview colour stays consistent as you raise the layer count",
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
            zh: "设置里加了“渐变自动换色”开关：开启后每次预览成功会自动把每一组渐变统一替换成组内代表色，一键去掉海带纹；默认关闭，原有手动换色流程不受影响",
            en: "New Settings → “Auto replace gradient banding” toggle: when on, every successful preview auto-collapses each gradient group to its representative colour to erase banding in one shot; off by default so the manual flow stays unchanged",
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
            zh: "每个大分组和小分组右边都加了一个“去海带纹”按钮，不必先选中再回到拾色器，直接一键把这一处渐变压成代表色",
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
            zh: "耗材档案预览：偶尔出现的 “10 层效果反而比 5 层差” 已修复。更多层数的匹配结果现在严格不劣于少层数 + 白色垫底的方案，预览颜色趋于稳定",
            en: "Material-archive preview: the occasional “10 layers look worse than 5 layers” regression is fixed — higher layer counts are now guaranteed to be no worse than any smaller-k solution padded with white, so preview colour stays consistent as you raise the layer count",
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
            zh: "设置里新增 “穷举数量” 开关：默认关闭，走低档（64³，构建快、内存小）；开启后可以选中（128³）或高（256³），穷举缓存会更细、颜色更准，代价是构建时间、内存占用、每次生成查找都会成倍变长。穷举缓存弹窗里会直接显示当前用哪一档，不同档的缓存分开存放、互不覆盖",
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
            zh: "耗材档案预览：偶尔出现的 “10 层效果反而比 5 层差” 已修复。更多层数的匹配结果现在严格不劣于少层数 + 白色垫底的方案，预览颜色趋于稳定",
            en: "Material-archive preview: the occasional “10 layers look worse than 5 layers” regression is fixed — higher layer counts are now guaranteed to be no worse than any smaller-k solution padded with white, so preview colour stays consistent as you raise the layer count",
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
