# DESIGN.md 合规审查报告 / DESIGN.md Compliance Audit

> 审查范围：`frontend/src/components/**` 下所有顶层 tab + 子 tab 的视觉与交互
> 基准：仓库根目录 `DESIGN.md`（Apple 系列页面提取的设计语言）
> 生成时间：与提交 `096a29a` 同期；后续修复进度更新见本文末尾

## 0. 审查方法

1. 抽样所有 tab 入口（顶层 `TabNavBar` + 各子 tab 区域）
2. 自动扫描以下偏离信号：
   - 神经色阶错位：`text-gray-*` / `bg-gray-*` / `border-gray-*`（项目约定使用 `slate`）
   - 硬编码原始色：`bg-white`、`text-black`、`#fff`、`#000` 且无 `dark:` 配对
   - 装饰性 emoji 出现在控件标签 / 段落标题中（与 "restrained chrome" 原则冲突）
   - 圆角分布违反 DESIGN.md §5 圆角分级（5 / 8-12 / 16-18 / 28-36 / 56-980 / 50%）
3. 人工抽查标题层级、tooltip 一致性、间距节奏

## 1. 总体结论

**符合度评估**：约 70%。布局、间距、圆角、阴影体系基本对齐 DESIGN.md。剩余偏离集中在三类系统性问题。

| 类别 | 说明 | 严重度 |
|---|---|---|
| A. `gray-*` Tailwind 色阶 | 与项目约定 `slate-*` token 混用 | 中（视觉割裂） |
| B. 装饰性 emoji 嵌入 i18n 字符串 | 218 处出现于 `translations.ts`，违反 §7 "Don't ... loud visual effects" | 中 |
| C. VectorizerPanel 风格自成一派 | h2 + section 标题、容器都用 `gray-*` + 自写 `bg-white/85` | 高（单页） |

低优先级：`Switch.tsx` / `Checkbox.tsx` / `RadioGroup.tsx` 内部小白点用裸 `bg-white`，无 dark 对偶。这是 thumb 视觉所需，不影响合规，保留。

## 2. 偏离明细 + 修改方案

### A. `gray-*` 色阶（应统一到 `slate-*`）

**总数**：13 个文件命中 44 处。

| 文件 | 命中数 | 修改方案 |
|---|---|---|
| `components/VectorizerPanel.tsx` | 8 | A1 见下，整体替换 `gray-` → `slate-`，统一标题字号到 `panelPrimitives` |
| `components/ui/CropModal.tsx` | 7 | A2，原样 `gray-` → `slate-` |
| `components/sections/SlicerSelector.tsx` | 6 | A3 |
| `components/ui/UnifiedUploader.tsx` | 5 | A4 |
| `components/widget/TabNavBar.tsx` | 3 | A5：active/hover 主色对，`gray-600/900/400/200` → `slate-` |
| `components/ui/BatchResultSummary.tsx` | 3 | A6 |
| `components/AboutView.tsx` | 2 | A7 |
| `components/sections/ActionBar.tsx` | 2 | A8 |
| `components/ui/Accordion.tsx` | 2 | A9 |
| `components/ui/WikiTooltip.tsx` | 2 | A10 |
| `components/widget/WidgetHeader.tsx` | 2 | A11 |
| `components/LanguageToggle.tsx` | 1 | A12 |
| `components/ThemeToggle.tsx` | 1 | A13 |

**统一修改原则**：

```
text-gray-50  → text-slate-50
text-gray-100 → text-slate-100
text-gray-200 → text-slate-200
text-gray-300 → text-slate-300
text-gray-400 → text-slate-400
text-gray-500 → text-slate-500
text-gray-600 → text-slate-600
text-gray-700 → text-slate-700
text-gray-800 → text-slate-800
text-gray-900 → text-slate-900
（bg- / border- / hover- / dark- 同理）
```

> 注：`slate` 在我们的 Tailwind 主题里携带稍偏冷的色相，更接近 DESIGN.md "Near-Black Ink #1d1d1f" + "Secondary Neutral Gray #6e6e73" 的中性调；项目其余 panel 已全部切到 slate。

### B. 装饰性 emoji（需要逐项决策）

**总数**：218 处，覆盖 41 种 emoji。集中在三类位置：

1. **顶层 tab 名**（`tab_calibration` `🎨 颜色提取` 等）→ 与 DESIGN.md §7 "Don't ... loud visual effects" 强冲突。**建议全部移除**。
2. **段落标题**（如 `### 🎨 色彩模式定位点顺序`）→ 同上。**建议全部移除**。
3. **状态/Badge 文案**（`⚠️ Please select`、`✅ ...`）→ 在缺乏正式 status token 的当下作为最小标识可保留；DESIGN.md §9 "Known Gaps" 也明确说没有 status palette。**短期保留，长期换正式 status badge 组件**。
4. **颜色块标签**（`🟦` `🟨` `🟥` 等方块色 emoji 出现在颜色相关说明里）→ 用 emoji 表达色块 = 占位行为，**应替换为真实色样**。

**修改方案**：
- B1：先一次性清掉 §1、§2 类别（顶层 tab + 段落标题中的装饰 emoji）。约 ~120 处。
- B2：§3 状态文案保留，但记入 follow-up 任务"实现统一 StatusBadge 组件取代纯文本 emoji"。
- B3：§4 颜色 emoji 替换为 `<ColorChip>` 内联组件（已有 `LutColorGrid` 的小色块样式可复用）。

需要 i18n 翻译同步更新；建议作为单独 PR，由 i18n owner 复核。

### C. VectorizerPanel 整体风格自成一派

**已部分修复**：commit `096a29a` 把两处 `title=` + 虚线下划线提示统一到 HelpDot。

**剩余偏离**：
1. `VectorizerPanel.tsx:173` 自写 `bg-white/85` 容器，未使用 `resolvePanelSurfaceClass`
2. `VectorizerPanel.tsx:176` `text-gray-800` 标题
3. `VectorizerPanel.tsx:189,497` `text-gray-600` 段落标题
4. `VectorizerPanel.tsx:503,543,544,562` 信息 / 调色板小卡用 `gray-*`
5. 标题层级与其它 panel 不一致：其它面板首屏不再有 h2 大标题（已删 PanelIntro），而 VectorizerPanel 仍保留 `vec.title`

**修改方案 C-plan**：
- C1：`bg-white/85 ... dark:bg-slate-900/85` → 调用 `resolvePanelSurfaceClass(workspace.mode)`
- C2：`text-gray-{600,800,...}` 全部改 slate
- C3：考虑同其它 panel 一样删 h2 标题（顶层 tab 已经是名字）；保留 description 时压成 muted 一行

### D. 其它低优 / 单点偏离

| 位置 | 问题 | 优先级 | 备选方案 |
|---|---|---|---|
| `Switch.tsx:61` | thumb 用裸 `bg-white` 无 dark 配对 | 低 | 保留（thumb 在两个主题下都白） |
| `Checkbox.tsx:48,51` | 同上 | 低 | 保留 |
| `RadioGroup.tsx:63,69` | 同上 | 低 | 保留 |
| `CustomRecipeDialog.tsx:980` | `bg-white` 与 `style backgroundColor: var(--surface-panel-strong)` 同时存在 | 低 | 删除冗余 `bg-white`，保留 CSS 变量 |
| `LutColorGrid.tsx:122,235` | `title={...hex...}` native tooltip | 低 | DESIGN.md 没要求富 tooltip 用于 hex 标识，保留 |
| `ColorPreview2D.tsx:792-795` | 长按按钮的 native title | 低 | 保留 |

### E. 圆角节奏（抽查）

DESIGN.md 圆角分级：5 / 8-12 / 16-18 / 28-36 / 56-980 / 50%。

抽查命中：
- 大面板：`rounded-[28px] / [32px]` ✓
- section card：`rounded-[20px] / 22px / 24px` ✓
- 控件：`rounded-xl(12px) / [18px] / [22px]` ✓
- 圆形：`rounded-full` ✓

**结论**：基本符合，未发现明显 "一刀切单一圆角" 现象。

## 3. 修复进度跟踪

| 编号 | 状态 | 提交 / 备注 |
|---|---|---|
| C1-C3（VectorizerPanel） | ✅ | `096a29a` + `bf563a3` |
| A 系列 gray→slate | ✅ | `bf563a3`（21 文件 / 218 处） |
| B1+B2（清理装饰 emoji） | ✅ | `a694c5d`：删 92 个旧 i18n 死 key + 剥 3 个仍在用的 emoji 装饰前缀（`conv_free_color_*`、`conv_auto_color_btn`） |
| B3（状态消息 emoji） | ⏳ 长期 follow-up | 保留 `✓ ✕` 作为图标用法；`✅ ⚠️ ❌ 💡 🔍` 未来另做 StatusBadge 一次性替换 |
| B4（色块 emoji） | ⏳ 长期 follow-up | 需新 `<ColorChip>` 组件 |
| D 单点 | ⏳ 低优 | 后续随机回收 |

## 4. 不会改的项（明确决定）

- **`bg-white/<opacity>` + 配对 `dark:bg-slate-...`**：这是项目既定的玻璃面板组合，符合 DESIGN.md "translucent overlays and glass-like utility bars"，不视为违规。
- **`Switch / Checkbox / RadioGroup` 内部 thumb / dot 用 `bg-white`**：thumb 必须在两个主题下都白，是有意为之。
- **色块查 hex 用 native `title={hex}`**：DESIGN.md 没规定 hex 提示样式；切到 WikiTooltip 会让色板交互拖累。
