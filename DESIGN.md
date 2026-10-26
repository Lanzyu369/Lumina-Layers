# Design System Inspired by Apple

## Color Workstation Selection Invariants

- **Tool is not selection:** switching between Same color, Pick blocks, and Selection brush never clears or rewrites the shared selection.
- **The server mask is authoritative:** every tool edits one revisioned union mask; the frontend may render an exact local flood-fill immediately, but stale responses cannot overwrite a newer intent.
- **No approximate flash:** click feedback uses strict RGB, 4-connected local flood-fill against the unhighlighted preview buffer. Bounding boxes and whole-image same-colour contours are never optimistic placeholders.
- **Content commits squash selection gestures:** point/brush/clear gestures are undoable until a replacement, free-colour, recipe, or gradient operation consumes them; that content action becomes one history item and undoing it preserves the execution-time selection.
- **Selection display is derived once:** touching regions are unioned before contour tracing, then shown as non-scaling marching ants; internal shared edges are not rendered.

## Color Adjustment Commit Boundary (2026-09-20)

本节补充颜色调整链路的状态设计；不改变本文后续 UI 视觉规范。目标是让一次成功编辑只产生一个可追踪的已提交作品版本，让失败只影响当前操作，让预览和生成消费同一份已提交状态。

### 1. 一个提交边界，复用现有状态

所有会改变 `matched_rgb`、`material_matrix`、配方覆盖或持久选区的入口继续使用现有 SessionStore、预览缓存事务、replacement history、SelectionDocument 和 GLB token/CAS。统一顺序为：

```text
读取并校验当前 session/cache
  → 等待同 session 的相反方向编辑提交
  → 在缓存事务中修改 RGB/材料矩阵/目标图
  → cache.commit 成功
  → 失效并预热 visible-region cache，取得服务端真实 content generation
  → 返回并合并权威 SelectionDocument
  → 写入历史/配方持久字段
  → 最后调度 GLB 派生任务
```

前端的 Promise barrier 只负责排序正在进行的请求，不保存第二份作品、历史或 mask。后端版本校验仍存在；barrier 失败会停止后续依赖操作，不会盲目重试。

### 2. 版本、回执和派生任务分开处理

| 标识 | 所有者 | 语义 | 处理方式 |
| --- | --- | --- | --- |
| 编辑内容版本 | `session.editor_content_revision` | 已提交的 RGB、材料矩阵、配方和持久空间目标的共同内容版本 | 只在现有缓存/会话/历史收敛后由服务端推进；编辑响应和生成响应返回 |
| 可见缓存版本 | visible-region cache generation | 可见区域缓存的重建代数 | 缓存失效/预热时服务端推进；用于构造 `SelectionDocument.content_revision`，不替代编辑版本 |
| 选区版本 | `SelectionDocument.selection_revision` | 共享选区 mask 的操作序列 | `selection/mutate` 串行提交；不因全局换色擅自递增 |
| 选区内容绑定 | `SelectionDocument.content_revision` | 选区可用于哪一份可见内容 | 内容提交后由服务端刷新，客户端不猜 `+1` |
| GLB 任务标识 | 现有 job token / publication revision | 派生 3D 工件是否仍属于当前内容 | 保留 token/CAS；旧任务只能被拒绝，不能覆盖新作品 |

这些标识不能互相加减或互相充当成功证明。响应丢失时，客户端查询同一个 operation id
对应的 `GET /convert/editor-commit/{session_id}/{operation_id}` 回执：`committed` 只表示
该编辑已在既有提交边界收敛，`failed` 只表示服务端确认尚未发布，`pending`、`unknown`
或查询失败都表示结果未知。未知状态保留草稿和错误上下文，暂停依赖编辑/选区/生成；不
根据版本差值回滚，也不重放 toggle、undo、redo。确认 `committed` 后再尽力读取
`GET /convert/selection/{session_id}` 补齐选区文档；这次读取失败不改变已确认内容结果，
下一次请求使用本地保留的已确认选区版本。

同一个 `operation_id` 只能进入一次实际编辑：服务端若已存在该回执，会在缓存、会话和
历史变更前返回 409，调用方应查询原回执而不是重放操作。前端旧请求的成功和错误响应都
进入同一 receipt 对账路径；如果旧错误的提交结果仍未知，同 session 内容屏障继续挂起。

### 3. 选区与内容编辑排序

选区提交等待同 session 的未完成内容提交；依赖选区的内容编辑和生成等待未完成选区提交；同类内容编辑也在发请求前同步占位并排队，避免同一事件循环内两个操作同时捕获旧版本。等待只发生在确实存在未完成 Promise 时，正常无竞态路径保持同步调用形态。成功响应统一经过 `selectionUpdatesFromResponse`，过期响应不会回写较新的 `(selection_revision, content_revision)`；失败响应统一经过 operation receipt 查询，明确区分“未提交”和“已提交但响应丢失”。

这覆盖点选、同色选择、画笔、清空、全局/批量替色、区域替色、配方、渐变操作、撤销/重做、生成等入口。它不删除真实过期请求的 409，也不通过“失败后再点一次”完成同步。

### 4. 基础输入与编辑派生层数分离

`useAutoPreview` 的基础输入 key 只代表 source、几何、基础层数等需要重建预览的输入。手工配方的层数属于 `recipe_overrides` 的编辑派生状态，不写回基础 `color_layers`/`layer_height_mm`，也不触发破坏性 session 重建。生成时按基础层数与已应用配方的最大层数解析实际 worker 输入；真实 source 或几何变化仍按原有自动预览规则处理。

### 5. 已应用配方使用持久空间目标

应用配方时将实际 region mask 位压缩存进 `recipe_override_applied_masks`，并随 replacement history 一起快照。动态重建、生成和历史恢复都通过同一 `resolve_recipe_override_masks` 解析：现代 session 不再读取后续变化的临时 `editor_selection`；快照缺失或形状不符直接返回可恢复错误，不静默忽略、不扩大为全图。只有没有快照键的旧 session 使用显式 legacy fallback。

### 6. 生成与派生失败语义

生成先等待已提交编辑，发送明确的 `editor_content_revision` 和 `selection_revision`。标准、拼图和大画幅入口在同一 session 锁内复制完整生成输入快照，服务端在进入 worker 前以及派生组装后比较两种版本；响应绑定实际输入版本，前端以生成序号、session、编辑 epoch 和设备身份丢弃旧结果。worker 只消费不可变快照，生成不无理由等待 GLB。

二维内容和材料矩阵一旦 `cache.commit` 成功，就不因后续 GLB 失败回滚。GLB 只更新派生状态；重试 GLB 不重放换色或配方。缓存事务失败则保留上一份已提交作品与会话字段。

配方覆盖在 cache 已发布后若历史或会聚阶段失败，不调用旧状态恢复，也不让事务退出路径
把已发布 cache 回滚；回执保持 pending/unknown，页面必须同步该 operation。只有 cache
尚未发布的确定性失败才恢复会话快照并标记 failed。

### 7. 为什么不新增旁路

没有引入第二套编辑 store、第二套 mask、数据库事件溯源或全局锁。新增的前端 barrier 是请求排序器，新增的后端 editor receipt 是有界的提交确认元数据，不承载作品、历史或 mask；后端 helper 复用现有 SelectionDocument/缓存/历史机制的单一解析和提交边界。所有持久数据仍挂在当前 session，锁仍按 session 作用域限制。

## 1. Visual Theme & Atmosphere

Apple's web language is a precision editorial system that alternates between gallery-like calm and retail-density information blocks. The visual tone stays restrained: broad neutral canvases, quiet chrome, and product imagery given almost all of the expressive weight. The interface is engineered to disappear so hardware, materials, and finish options become the narrative foreground.

Across the five analyzed pages, the rhythm is consistent but not monolithic. Marketing surfaces (homepage and Environment) use cinematic black-and-light chaptering, while commerce surfaces (Store and Shop flows) introduce tighter spacing, more utility controls, and denser card stacks without breaking the core brand grammar. The result is one system with two gears: showcase mode and transaction mode.

Typography is the stabilizer. SF Pro Display carries hero and merchandising hierarchy with compact line heights and controlled tracking, while SF Pro Text handles product metadata, navigation, filters, and dense selection UI. The typography stays understated, but the scale range is wide enough to support both billboard hero messaging and micro utility labels.

**Key Characteristics:**
- Binary section rhythm: deep black scenes (`#000000`) alternating with pale neutral fields (`#f5f5f7`)
- Single blue accent family for action and link semantics (`#0071e3`, `#0066cc`, `#2997ff`)
- Dual operating modes in one system: cinematic showcase modules and dense commerce configurators
- Heavy reliance on imagery and material finishes; UI chrome remains visually thin
- Tight headline metrics (SF Pro Display, semibold) paired with compact body/link typography (SF Pro Text)
- Pill and capsule geometry as signature action language (`18px` to `980px` and circular controls)
- Depth used sparingly; contrast and surface separation do most of the layering work
- Multi-page color-block rhythm: black hero chapters -> pale neutral merchandising fields -> utility white retail surfaces -> dark micro-surfaces for controls

## 2. Color Palette & Roles

> **Source Pages:** `https://www.apple.com/`, `https://www.apple.com/environment/`, `https://www.apple.com/store`, `https://www.apple.com/shop/buy-iphone/iphone-17-pro`, `https://www.apple.com/shop/accessories/all`

### Primary
- **Absolute Black** (`#000000`): Immersive hero canvases, high-drama product chapters, deep UI anchors.
- **Pale Apple Gray** (`#f5f5f7`): Main light surface for feature bands, comparison blocks, and editorial transitions.
- **Near-Black Ink** (`#1d1d1f`): Primary text and dark-fill control color on light canvases.

### Secondary & Accent
- **Apple Action Blue** (`#0071e3`): Primary action fill and focus-signaling brand accent.
- **Body Link Blue** (`#0066cc`): Inline link color optimized for long-form readability.
- **High-Luminance Link Blue** (`#2997ff`): Bright link treatment on darker scenes where stronger contrast is required.

### Surface & Background
- **Pure White Canvas** (`#ffffff`): Retail/product-list backgrounds and dense transactional sections.
- **Graphite Surface A** (`#272729`): Dark card and media-control context layer.
- **Graphite Surface B** (`#262629`): Slightly deeper dark utility layer for control groupings.
- **Graphite Surface C** (`#28282b`): Elevated dark supporting surfaces.
- **Graphite Surface D** (`#2a2a2c`): Darkest elevated step used for separation in richer dark scenes.

### Neutrals & Text
- **Secondary Neutral Gray** (`#6e6e73`): Body secondary copy, helper descriptions, tertiary metadata.
- **Soft Border Gray** (`#d2d2d7`): Dividers, subtle outlines, and muted utility containment.
- **Mid Border Gray** (`#86868b`): Stronger field outlines in product-configuration and filter contexts.
- **Utility Dark Gray** (`#424245`): Dark-neutral text/surface crossover in store contexts.

### Semantic & Accent
- **Selection/Focus Signal** (`#0071e3`): Shared focus and selected-state signal across marketing and commerce contexts.
- **Error/Warning/Success**: No distinct semantic palette was consistently visible in the extracted surface set.

### Gradient System
- The extracted pages are overwhelmingly solid-surface driven. Visual richness comes from photography and finish rendering rather than persistent UI gradients.

## 3. Typography Rules

### Font Family
- **Display Family:** `SF Pro Display`, fallbacks `SF Pro Icons, Helvetica Neue, Helvetica, Arial, sans-serif`
- **Text Family:** `SF Pro Text`, fallbacks `SF Pro Icons, Helvetica Neue, Helvetica, Arial, sans-serif`
- **Usage Split:** Display family handles hero/product headlines and merchandising headings; Text family handles navigation, controls, labels, and dense commerce copy.

### Hierarchy
| Role | Size | Weight | Line Height | Letter Spacing | Notes |
|------|------|--------|-------------|----------------|-------|
| Hero Display XL | 80px | 600 | 1.00-1.05 | -1.2px | Environment/store hero scale |
| Hero Display L | 56px | 600 | 1.07 | -0.28px | Homepage hero moments |
| Section Display | 48px | 500-600 | 1.08 | -0.144px | Major chapter headings |
| Product Heading | 40px | 600 | 1.10 | normal | Product and campaign section titles |
| Feature Display | 38px | 600 | 1.21 | 0.152px | Device and merchandising callouts |
| Promo Display | 32px | 300-600 | 1.09-1.13 | 0.128px to 0.352px | Module-level sub-heroes |
| Card/Product Title | 28px | 600 | 1.14 | 0.196px | Tile-level naming and key copy |
| Utility Heading | 24px | 600 | 1.17 | 0.216px / -0.2px | Configurator and grouped content headers |
| Link/Action Heading | 21px | 600 | 1.14-1.38 | 0.231px | Larger promotional links |
| Subhead | 19px | 600 | 1.21 | 0.228px | Compact section intros |
| Body Primary | 17px | 400 | 1.47 | -0.374px | Standard body and retail descriptions |
| Body Emphasis | 17px | 600 | 1.24 | -0.374px | Emphasized labels and key values |
| Control Label | 14px | 400-600 | 1.29-1.47 | -0.224px | Buttons, helper labels, compact nav text |
| Micro UI | 12px | 400-600 | 1.00-1.33 | -0.12px | Fine print, micro labels |
| Legal/Meta | 10px | 400 | 1.30-1.47 | -0.08px | Dense metadata and legal support text |

### Principles
- **Continuity across page types:** The same typographic DNA spans cinematic launches and product-purchase flows, preventing a brand split between marketing and commerce.
- **Compression at scale:** Display tiers use tight leading and controlled tracking to feel machined and product-first.
- **Readable density at retail depth:** SF Pro Text balances compactness with enough vertical rhythm for long product lists and option matrices.
- **Measured weight ladder:** 600 is the dominant emphasis weight; 700 appears selectively; 300 is used sparingly for contrast in larger lines.

### Note on Font Substitutes
- Closest freely available substitutes: `Inter` for text-heavy implementation and `SF Pro Display-like` metrics approximated with `Inter Tight` for headings.
- When substituting, increase line-height slightly (+0.02 to +0.06) on body sizes and reduce negative tracking intensity to preserve readability.

## 4. Component Stylings

### Buttons
- **Primary Fill Action:** `#0071e3` background, `#ffffff` text, 8px radius, compact horizontal padding (commonly 8px 15px). Used for decisive purchase/progression actions.
- **Dark Fill Action:** `#1d1d1f` background, `#ffffff` text, 8px radius. Used when light surfaces need a restrained high-contrast primary.
- **Pill/Capsule Action Family:** large capsule actions at `18px`-`56px` radii and extreme pill links at `980px`. Establishes Apple’s soft but precise call-to-action silhouette.
- **Utility Filter/Button Shells:** light shells (`#fafafc` or translucent white) with subtle gray borders (`#d2d2d7` / `#86868b`) for dense configuration contexts.
- **Pressed Behavior:** active controls commonly reduce scale or shift fill slightly to indicate physical press confirmation.

### Cards & Containers
- **Editorial/Product Cards:** light cards on `#f5f5f7` or white fields with minimal framing and image-first composition.
- **Dark Utility Cards:** graphite steps (`#272729` to `#2a2a2c`) used for overlays, media controls, and dark-context modules.
- **Configurator Panels:** rounded containers (often 12px-18px) with clear but restrained border definition.
- **Carousel/Spotlight Modules:** larger rounded shells (`28px`-`36px`) for featured content lanes.

### Inputs & Forms
- **Retail Input Fields:** translucent or white backgrounds, dark text (`#1d1d1f`), border-led containment (`#86868b`).
- **Selection Controls:** circular/toggle-like control geometry appears frequently in product selection interfaces.
- **Density Strategy:** form fields remain visually quiet to keep device imagery and pricing hierarchy dominant.

### Navigation
- **Global Marketing Nav:** compact dark translucent bar with small-type links and restrained iconography.
- **Store/Sub-shop Nav Layers:** additional utility bars, chips, and segmented controls for category and product narrowing.
- **Link Hierarchy:** link blues remain the primary interactive signal while neutral text supports dense navigation sets.

### Image Treatment
- **Object-First Photography:** hardware and accessories are foregrounded on controlled solid surfaces.
- **High-fidelity finish rendering:** reflective/material details are central to visual persuasion.
- **Mixed framing:** full-bleed hero scenes coexist with rounded retail cards and tightly cropped merchandising thumbnails.

### Other Distinctive Components
- **Product Configurator Matrix:** option stacks and selectors combining chips, radio-style controls, and contextual pricing/summary blocks.
- **Carousel Control Dots/Arrows:** circular control vocabulary in muted overlays for gallery progression.
- **Environment Story Panels:** narrative chapters that blend editorial typography with cinematic product/environment visuals.

### Inline Help Tooltips (功能提示)

#### Placement Standard (放置标准)


| Trigger type | When used | Implementation |
|---|---|---|
| **Switch** (standalone pill) | Label needs a hint | `<HelpDot title={...} description={...} />` placed inline after the label text, inside the label row |
| **Slider** | Label or value meaning is not obvious | `Slider` component prop: `tooltip={t("...")}` — renders a visible ⓘ icon inline after the label |
| **Checkbox** (switch row by default) | The option's effect needs explanation | `Checkbox` component prop: `tooltip={t("...")}` — renders a visible ⓘ icon inline after the label, outside the clickable label so it never toggles the switch |
| **Dropdown** | The choice needs explanation | `Dropdown` component prop: `tooltip={t("...")}` — renders a visible ⓘ icon after the label (ignored when `labelAccessory` is set) |
| **RadioGroup** | The group or its options need explanation | `RadioGroup` component prop: `tooltip={t("...")}` — renders a visible ⓘ icon after the group legend; multi-line hints (one line per option) are supported via `\n` |

#### Reference Implementation (参考实现)

Image-to-Vector tab (`VectorizerPanel.tsx`) is the canonical reference:

```tsx
// Switch: HelpDot inline after label text
<span className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-200">
  {t("vec.num_colors")}
  <HelpDot title={t("vec.num_colors")} description={t("vec.hint_num_colors")} />
</span>
<Switch checked={...} onChange={...} />

// Slider: tooltip prop (renders visible ⓘ icon via internal HelpDot)
<Slider
  label={t("vec.smoothness")}
  tooltip={t("vec.hint_smoothness")}
  value={params.smoothness}
  min={0} max={1} step={0.01}
  onChange={(v) => setParam("smoothness", v)}
/>

// Checkbox: tooltip prop (renders visible ⓘ icon via internal HelpDot)
<Checkbox
  label={t("vec.svg_enable_stroke")}
  tooltip={t("vec.hint_svg_enable_stroke")}
  checked={params.svg_enable_stroke}
  onChange={(v) => setParam("svg_enable_stroke", v)}
/>
```

#### Key Rules (关键规则)

- **Do not** use native `title` attribute or custom `?`/`ⓘ` spans; always use `HelpDot` (for Switch) or the `tooltip` prop (for Slider/Checkbox/Dropdown/RadioGroup)
- Keep static explanations, parameter guidance, and optional detail in the tooltip popover; do not repeat them in a visible paragraph below the control.
- When inline text and a help icon both appear, the inline text states the current result or constraint briefly; the tooltip supplies the explanation and detail. Do not reuse the same explanation in both places.
- Hint text must be bilingual (`zh` + `en`) in `translations.ts` with a `*_hint` suffix key
- The ⓘ icon visual style is fixed in `HelpDot` (stroke-style `InfoIcon`, no background); do not recreate it inline
- Hint copy is written for end users: describe the visible effect and the trade-off, avoid algorithm terms (e.g. no "K-Means", "8-neighborhood", "L\* roll-off")

### Hierarchy v2 — 单层卡片 + 凹槽 + 分割线 (Single-Card Layering)

> Lumina-specific override. This is the source of truth for panel structure across all tabs and supersedes any generic "rounded card" guidance above. 本节是 Lumina 各面板结构的唯一真源，覆盖上文通用的圆角卡片写法。

#### The problem it solves (要解决的问题)

Earlier panels expressed every level of grouping with its own rounded-rectangle bordered card, often nested 2–3 deep, plus colored-border "chips" for sub-groups. The result was visual noise: borders competing with borders, radii competing with radii, and no reliable way to tell which box was a level above which. Depth cues stopped meaning anything because *everything* was a box.
早期面板把每一层分组都做成带边框的圆角卡片，常常嵌套 2–3 层，子分组还用彩色边框小卡片区分。结果是边框套边框、圆角套圆角，层级反而读不出来——因为"什么都是盒子"，盒子就不再表达层级。

#### The core rule (核心规则)

**One bordered "card" level per page. Everything inside a card is expressed with either a well or a hairline divider — never another bordered rounded box.**
**每页只有一层带边框的"卡片"。卡片内部只用"凹槽 (well)"或"发丝分割线"表达分组，绝不再嵌套带边框的圆角盒子。**

Three primitives, three jobs:

| Primitive | Role | Visual signature |
|---|---|---|
| **Card** (`.panel-card`) | The one bordered container per logical section | Solid-ish fill + 1px outline + soft drop shadow, radius 16px |
| **Well** (`.panel-well`) | Inset region *inside* a card (e.g. a preview strip, a swatch tray, a status readout) | Tinted fill, **no border**, radius 10px — reads as "pressed into" the card |
| **Divider** (`.panel-divider`) | Separates mid-level groups *inside* a card | Single hairline rule, no box at all |

Grouping strength, weakest → strongest: **whitespace → group header → divider → well → card.** Reach for the weakest device that still reads. A divider with a small-caps header is almost always enough to separate two groups inside one card; promote to a well only when the inner content is itself a cluster of controls that needs a contained surface.
分组强度由弱到强：**留白 → 组标题 → 分割线 → 凹槽 → 卡片**。优先用能读懂的最弱手段。卡内两个分组，"分割线 + 小标题"通常就够；只有当内部本身是一簇需要独立托底面的控件时，才升级成凹槽。


#### Making dividers "一眼可辨" (visibility, per the original concern)

A plain hairline can be too quiet to separate two sizeable blocks. Boost visibility *without* adding a full border box:
1. Pair the divider with a **small-caps group header** (colored dot optional) directly under it — the label does most of the "this is a new section" signaling.
2. Give the card itself a **soft edge shadow** (`--shadow-card`) so the card边界 stays crisp against the page while internal dividers stay light. The contrast between "card edge = shadowed" and "internal divider = flat hairline" is itself a legibility cue.
3. Where a block genuinely needs to pop, promote it to a **well** (tinted fill) rather than thickening a border — fill contrast is more legible than line weight and never competes with the card outline.

#### Shadow boundary rule (边框阴影规则)

Shadow is an **outer-boundary tool only**. `--shadow-card` belongs to `.panel-card` and is used to make the one true section boundary read clearly against the page. Inner groups inside a card must not add local shadows, glow, raised borders, or shadowed mini-cards. If an inner group needs more visual weight, promote it to `.panel-well` and rely on fill contrast; if it still needs separation, pair the well with a header or divider — do not add a second elevation level.
阴影只用于**外层边界**：`--shadow-card` 只属于 `.panel-card`，用于让唯一的章节卡片边界清楚。卡片内部的分组禁止再加局部投影、发光、凸起边框或带阴影小卡片。内部区块需要更醒目时，升级成 `.panel-well`，靠填充色对比；仍需区分时加组标题或分割线，不增加第二层 elevation。

#### Radius ladder (圆角阶梯)

Radii step **down** as you go inward so outer and inner shapes never compete:

| Level | Radius | Applies to |
|---|---|---|
| Card | `16px` (`rounded-2xl`) | `.panel-card` section shells |
| Chip / banner | `6px` | status banners, hue-filter pills stay `rounded-full` by intent |

Never flatten everything to one radius, and never let an inner element's radius meet or exceed its container's.

#### Status banners (状态提示)

Banners are **not** cards. They use a **3px left accent bar + tinted fill**, radius 6px, no full border. Tone drives the accent color and fill (info/success/warning/error). This stops hints and results from reading as "yet another nested card."
提示条不是卡片：**左侧 3px 色条 + 淡色底**，6px 圆角，无完整边框。色调决定色条与底色。

#### Group headers (组标题)

Small-caps eyebrow: `text-[11px] font-semibold uppercase tracking-[0.18em]`, muted color. For color-workstation toolbar groups, a **colored dot** prefixes the label to carry category — this replaces the old colored-border mini-cards. Category color lives in a 1.5×1.5 dot, not in a box outline.

**A heading must outweigh the controls it introduces.** The eyebrow is deliberately quiet because it sits *below* the card and above a small cluster — it is a caption, not a title. When a long column is split into stages (input → color source → output size → build), each stage needs `stageHeadingClass`: 14px semibold in slightly softer ink than the panel title, with the hairline divider above it and a small top margin. The ladder is panel title (15px semibold, `WidgetHeader`) → stage (14px semibold) → field label (14px medium, secondary ink) → value. Stage headings do **not** grow a size larger than the panel title: separation comes from weight, ink, the divider and spacing, never from making the inner level the biggest thing on screen. Never name a stage with `groupHeaderClass`; 11px muted text next to a divider reads as a caption and inverts the hierarchy.
**标题必须比它所辖控件更重。** 眉标之所以安静，是因为它在卡片之下、小簇之上，本质是说明文字而不是标题。当一个长栏目按阶段切分（输入 → 颜色来源 → 输出尺寸 → 结构与质感）时，每个阶段用 `stageHeadingClass`：14px 半粗，墨色略浅于面板标题，分割线在其上方并留一点上边距。层级为：面板标题（15px 半粗）→ 阶段标题（14px 半粗）→ 字段标签（14px 中等、次要色）→ 取值。阶段标题**不**比面板标题更大——区分靠字重、墨色、分割线与间距，而不是把内层做成屏幕上最大的字。不要把阶段名写成 `groupHeaderClass`——分割线旁的 11px 浅灰字会被读成说明，层级正好反过来。

#### Token & primitive reference (令牌与原语)

CSS layer — `frontend/src/index.css`:
- `--surface-card` / `--surface-card-outline` — card fill + outline (light & `.dark`)
- `--surface-well` — well tint
- `--surface-divider` — hairline color
- `--shadow-card` — the single soft edge shadow used for cards
- classes: `.panel-card`, `.panel-well`, `.panel-divider`, `.status-banner[data-tone="…"]`

JS layer — `frontend/src/components/ui/panelPrimitives.tsx`:
- `cardClass` (`panel-card rounded-2xl`), `cardPadClass` (adds `px-5 py-5`)
- `wellClass` (`panel-well rounded-[10px]`), `wellPadClass` (adds `px-3 py-2.5`)
- `cardDividerClass` (`panel-divider border-t`)
- `stageHeadingClass` (15px semibold primary ink — names a stage of a long column)
- `groupHeaderClass` (11px muted eyebrow — sub-group caption inside a stage)

#### Migration mapping (旧 → 新)

| Old | New |
|---|---|
| `sectionCardClass` / `resolveSectionCardClass` (28px card) | `cardPadClass` (16px card) |
| `workstationPanelCardClass` (28px muted card) | `cardClass` + explicit padding |
| `workstationInsetCardClass` (22px bordered inset) | `wellPadClass` (borderless well) |
| Colored-border `ToolbarGroup` chips | Borderless group: colored dot + small-caps label |
| `border-t border-slate-200/60 … dark:border-slate-700/60` | `border-t panel-divider` |
| Full-border status box | `.status-banner` left accent bar |

#### Do / Don't

**Do**
- Keep exactly one bordered card per logical section; use wells and dividers inside it.
- Let the card's soft shadow define its edge; keep internal separators as flat hairlines.
- Use shadow only on `.panel-card`; use `.panel-well` fill contrast, headers, and dividers for all inner grouping.
- Use a group header (+ optional colored dot) as the primary "new section" signal.
- Step radii down when nesting.

**Don't**
- Don't nest a bordered rounded box inside another bordered rounded box.
- Don't add shadows, glow, or raised borders to groups inside a card.
- Don't use colored borders to categorize sub-groups — use a dot on the label.
- Don't thicken borders to make a block stand out — promote it to a well instead.
- Don't give status hints a full border; they get a left accent bar.

#### Migration status (迁移状态)

> Verified against the working tree on 2026-10-14. An earlier revision of this document claimed Settings had already migrated; that was wrong, and is corrected below.
> 2026-10-14 按工作区实际代码核对。此前本文档写“设置页已迁移”与代码不符，已在下方更正。

| Area | Status |
|---|---|
| Colour Adjustment workstation — `PalettePanel`, `LutColorGrid`, `MaterialColorPicker`, `GradientGroupsPanel`, `ColorQuickReplacePanel`, `TargetColorPanel`, `SimilarRecipeList`, `MaterialLayerBenefitCurve`, `SelectionToolPicker` | **Migrated** |
| Colour Adjustment overlay — `Color2DOverlay`, `ColorPreview2D` | **Migrated** |
| Image Conversion — widget shells, `BasicSettings`, `ActionBar`, `BedSizeSelector`, `BatchResultSummary`, `UnifiedUploader`, `LegacyLutSelector`, `ImageUpload`, `FridgeMagnetSettings`, `PuzzleSettings`, `CloisonneSettings`, `Scene3D` toolbar | **Migrated** |
| LUT Management — `LutLibraryPanel`, `LutManagerPanel`, `LutCloudSyncPanel`, `LutDetailsPanel`, `LutComparePanel`, `MaterialCloudSyncPanel` | Migrated |
| Material Management — Lumina Box panels (`LuminaBoxMaterialPanel`, `LuminaBoxLibraryCard`, `LuminaBoxBackingSetup`, `LuminaBoxMaterialCapture`, `LuminaBoxStackSamplesPanel`) | Migrated |
| Material Management — `MaterialLibraryPanel`, `GradientCardGeneratePanel`, `GradientCardExtractPanel`, `MaterialRecipeQueryPanel` | **Pending** |
| LUT Management — `CalibrationPanel`, `ExtractorPanel`, `FiveColorQueryPanel`, `ColorcheckerConfirmDialog` | **Pending** |
| Image to Vector — `VectorizerPanel` | **Pending** |
| Creative Workshop — `WorkshopPanel`, `ModuleDetails` | **Pending** |
| Dialogs — `CustomRecipeDialog`, `CustomRecipeSidePanel`, `MaterialPickerDialog`, `BugReportModal` | **Pending** (dialog shells keep their single card; inner panels still nest) |

Shared controls (`Button`, `Slider`, `Checkbox`, `RadioGroup`, `Dropdown`, field shells, `.status-banner`) are migrated platform-wide, so every page benefits even where its own containers are still pending.
共享控件已全站迁移，因此即使某一页的容器还没改，这些控件也已经干净。

Legacy helpers scheduled for removal once the last user migrates: `sectionCardClass`, `mutedSectionCardClass`, `workstationPanelCardClass`, `workstationInsetCardClass`, `workstationShellClass`, `resolveSectionCardClass` (all in `frontend/src/components/ui/panelPrimitives.tsx`).
`panelPrimitives.tsx` 里的旧常量在最后一个使用者迁移完成后删除。

### Ghost controls — 幽灵按钮与隐形边界 (Ghost Controls)

> Lumina-specific. Introduced with the Image Conversion cleanup. 与图像转换页改造一同引入。

`边界只在需要时出现。` A control that is already named by its own text or icon does not need a permanent box: the box adds a second rectangle to a column that already has a card, a well and a divider. Ghost controls keep the hit area and the label, and reveal their boundary on hover and keyboard focus.
已经带有文字或图标的控件不需要常驻边框——那只是在已有卡片、凹槽和分割线的栏里再加一个矩形。幽灵控件保留点击区域和文字，只在悬停和键盘聚焦时露出边界。

#### Three button levels (三级按钮)

| Level | At rest | Used for |
|---|---|---|


Exception: the slicer launch/download control (`SlicerSelector`, including "Generate and open in BBS") retains its slicer-specific brand colors and split-button styling.
例外：切片软件启动/下载控件（`SlicerSelector`，包括「生成并在 BBS 中打开」）保留原有品牌配色和分体按钮样式。

The four floating 3D viewer icons (performance, diagnostics, fullscreen and screenshot) also retain their original ghost-control styling.
3D 视图的性能统计、诊断、全屏、截图四个悬浮图标按钮也保留原有幽灵按钮样式。

#### Ghost control states (状态)

| State | Treatment |
|---|---|
| Rest | transparent 1px border + transparent fill; the border is present so hovering never reflows the layout |
| Hover | `--surface-card-outline` border + `--nav-chip-hover` fill, text darkened |
| Keyboard focus | same as hover plus a 2px `--focus-ring` outline (via `outline`, never `ring-*`) |
| Pressed | fill steps up to `--surface-well` |
| Toggled on (`aria-pressed="true"` / `data-active="true"`) | tinted fill + blue text, **no border** — the fill carries the state |
| Destructive (`data-tone="danger"`) | hover turns text, border and fill red |
| Disabled | 45% opacity, no hover reaction |
| `@media (hover: none)` | a faint resting border, because a touch device cannot reveal it on hover |

Implementation: `.ghost-control` in `frontend/src/index.css`. Reach it through `variant="ghost"` on `Button`, or the `ghostControlClass` export for raw `<button>` elements. Do not hand-write a ghost style — that is how six copies of the dialog close button happened.
实现见 `index.css` 的 `.ghost-control`。通过 `Button variant="ghost"` 或 `ghostControlClass` 使用，不要手写。

#### Field controls also hide their boundary (输入控件同样隐藏边界)

Text inputs, number boxes, the slider value box and the `Dropdown` trigger use `workstationInputClass` / `compactFieldClass`: a tinted `--surface-well` fill with **no border** at rest, a hairline border on hover, a blue border plus focus ring on focus. The fill still reads as a field; the border only appears when the user is about to touch it.
输入框、数字框、滑块数值框和下拉框触发按钮：静止时只有 `--surface-well` 浅底，无边框；悬停出现细边框；聚焦转蓝并加焦点环。

#### Selectable rows are borderless (可选行不画边框)

`Checkbox` and `RadioGroup` rows (`workstationChoiceRowClass`) are transparent at rest and show only a gray fill on hover, with no visible row border. The checked state lives in the indicator alone. Rows carry `-mx-2 px-2` so the hover fill extends past the text while labels stay aligned with the sliders above them.
复选框与单选项行静止透明，悬停只显示灰色底，不显示行边框；选中状态只由标记本身表达。

- **On/off setting → pill switch.** `Checkbox` defaults to `appearance="switch"`: label left, ⓘ inline after it, pill on the right edge, announced as `role="switch"`. Any single feature toggle (enable relief, crop after upload, outline, coating…) uses this.
  单个功能的开/关一律用胶囊开关：文字在左、ⓘ 紧跟文字、胶囊靠右。
- **Item in a multi-select list → square checkbox.** Pass `appearance="checkbox"` (e.g. the legacy LUT list), where a pill on every row would read as many independent settings.
  多选列表中的一项（如反推 LUT 列表）才用小圆角方框。
- **One of several exclusive choices → `RadioGroup` dot.** Source type, structure mode and modeling mode stay radios; never turn a 2+-option choice into a switch.
  多选一（颜色来源、单/双面、建模方式）保持圆点单选。
- **The pill is never wrapped.** `Switch` / `SwitchTrack` draw only the track and knob — no bordered rounded-rect shell around them; optional `checkedLabel` text sits beside the pill, unboxed.
  胶囊开关不再外套圆角矩形边框；状态文字直接放在胶囊旁边。

#### Dependent sub-settings use an indent, not a box (从属缩进)

Settings revealed by the parent control above them (`模型覆面`, `耗材档案`, `反推LUT` 品牌, `大画幅`) use `dependentGroupClass`: a 2px left hairline plus 12px indent. That is already the third grouping device on the ladder — adding a border would make it a fourth card level.
父级开关展开的子设置改用「左侧细线 + 缩进」，不再包一层带边框的盒子。

#### Controls floating over an image or the 3D canvas (画面上的控件)

A ghost boundary is invisible against arbitrary image content. When controls float over the picture:
- **Several controls:** group them into one translucent pill toolbar and make the inner buttons ghost.
- **A single control:** give it a translucent solid fill with no border.

画面上的控件不能用幽灵边界：多个控件合并成一条半透明胶囊工具条（内部按钮用幽灵样式），单个控件用半透明实底。

#### Content edges may keep a hairline (内容边缘例外)

A swatch, a layer thumbnail or a preview tile is *content*, not a container. A barely visible hairline outline is allowed there so a white swatch stays visible on a white card. This exception does not extend to grouping boxes.
色块、缩略图属于内容而非容器，允许保留极淡描边；这条例外不适用于分组盒子。

#### `shadow-*` class names kill the focus ring (`shadow-` 类名会吞掉焦点环)

`index.css` contains `:where([class*="shadow-"], [style*="box-shadow"]) { box-shadow: none !important; }`. Tailwind draws `ring-*` with `box-shadow`, so **any element whose class string contains `shadow-` loses its focus ring as well**. Never put a `shadow-*` utility on an interactive control; use `outline` (as `.ghost-control` does) or a real border for focus styling. Only `.panel-card` carries a real shadow, and it is applied through a CSS class, not a utility.
`index.css` 的全局规则会清掉含 `shadow-` 类名的阴影；Tailwind 的 `ring-*` 靠 box-shadow 实现，因此类名里出现 `shadow-` 的交互控件会连焦点环一起丢失。交互控件不要写 `shadow-*`，聚焦样式用 outline 或边框；全站只有 `.panel-card` 通过 CSS 类保留真实阴影。

### 全局滚动条

- 所有标签页、面板、列表、文本区和弹窗（包括通过 Portal 渲染的弹窗）的横向与纵向滚动条统一使用 Mac 风格：中性灰色细条、两端全圆角、透明轨道、不显示两端箭头；悬停时只加深灰度，不使用蓝色或其他强调色。
- 唯一实现放在 `frontend/src/index.css` 的全局滚动条规则中。新增滚动区域自动继承，无需添加 `dock-scrollbar`，不要在组件内另写滚动条颜色、尺寸或圆角。
- Chromium / Electron 使用 8px 轨道、1px 透明内边距形成的 6px 可见滑块、`9999px` 圆角和 32px 最小长度。浅色主题使用 `rgba(110, 110, 115, 0.42)`，深色主题使用 `rgba(161, 161, 166, 0.42)`；悬停透明度均为 `0.68`，通过 `--scrollbar-thumb` / `--scrollbar-thumb-hover` 统一维护。
- 支持 `::-webkit-scrollbar` 的浏览器使用自定义圆角样式；仅在不支持时回退到标准 `scrollbar-width` / `scrollbar-color`，避免两套属性互相覆盖。
- 顶部导航条继续使用 `scrollbar-hidden` 隐藏滚动条并保留滚动能力；`dock-scrollbar-hover` 只控制停靠面板的滚动条出现时机，不定义另一套外观。
- 验证时覆盖浅色与深色主题、普通页面与弹窗、横向与纵向滚动，以及未添加 `dock-scrollbar` 的区域。

### Top Navigation — 两级导航 (Two-Level Tabs)

> Lumina-specific rules for `TabNavBar` (primary tabs) and `SubTabBar` (sub tabs). 主导航与子导航的专用规则。

- **Rows and dividers carry the hierarchy, not boxes:** the header row (brand, primary tabs, tools) and the sub-tab row share the chrome surface, one `panel-divider` hairline separates them and a second one closes the sub-tab row. Never add tracks, outlines or tinted bands to tell the levels apart.
  层级靠行和分隔线表达：顶栏行与子导航行同底色，中间一条细线，子导航行下方再一条；不要用底槽、描边或色带区分层级。
- **Alignment is a user setting (`headerNavAlignment`):** `center` keeps both rows on one shared centre line, which is the window axis whenever there is room; `left` places the primary tabs after the brand and starts the sub tabs at the first primary tab. Never truncate, overlap, or stretch the tab group to the full width.
  对齐方式由用户设置决定：居中时两行共用一条中线，空间足够时就是窗口中线；居左时主导航紧跟标题，子导航从第一个主导航项开始。不截断、不重叠，也不把标签组拉满整行。
- **A tight header gives way in a fixed order (`headerNavLayout.ts`, `useHeaderNavFit`):** the "Lumina Studio 2" title collapses to the logo whenever that gives the tabs the room they need, before the tabs move; centered tabs leave the window axis only as far as the brand and the tools require, with the sub tabs following the same centre line; only when the tabs no longer fit between the logo and the tools do they move to a row of their own, and the title returns.
  顶栏变紧时按固定顺序让步：只要收起“Lumina Studio 2”标题文字能给主导航腾出所需空间，就先收起、只留标志，再考虑移动主导航；居中时主导航在不碰到两侧的前提下尽量靠近窗口中线，子导航跟随同一条中线；只有标志和工具按钮之间也放不下时，主导航才移到下一行，标题文字随之恢复。
- **Tab strips never show a scrollbar (`NavTabStrip`):** in a window narrower than a strip, it scrolls sideways with trackpads, keyboard focus, or a vertical mouse wheel. The selected chip slides only when the selected tab changes (`layoutDependency`); header layout changes such as alignment, title collapse or wrapping move it instantly.
  导航标签条从不显示滚动条：窗口比标签条还窄时，可用触控板、键盘或鼠标竖向滚轮横向滚动。选中块只在切换标签时滑动；对齐方式、标题收起或换行等顶栏布局变化时直接到位，不重播滑动。
- **Header tools stay minimal:** only Panel Controls sits on the right of the header row. Dark mode, beginner tour, bug report and the backend / reproduction status live in the three-line "More options" menu (`HeaderMenu`), whose rows carry visible labels. Interface language is selected under Settings → General. The menu button shows a dot only when the backend is unreachable (red) or a bug report is being reproduced (amber).
  顶栏右侧只保留“面板控件”；深色模式、新手引导、问题反馈和后端/复现状态收进三横线“更多选项”菜单，菜单项带文字。界面语言在“设置 → 常规”中选择。只有后端不可达（红点）或正在复现问题（橙点）时，菜单按钮才显示提示点。

## 5. Layout Principles

### Spacing System
- Base unit is effectively `8px`, but the system supports dense micro-steps for precision alignment.
- Frequently reused spacing values across pages: `2`, `4`, `6`, `7`, `8`, `9`, `10`, `12`, `14`, `17`, `20` px.
- Universal rhythm constants visible across both marketing and retail flows: `8px` unit scaffolding with `14-20px` utility intervals for component padding and list spacing.

### Grid & Container
- **Showcase pages:** large central columns with broad horizontal breathing room and full-width color chapters.
- **Commerce pages:** tighter multi-column product and control grids with frequent modular stacking.
- **Container behavior:** constrained readable core with generous outer margins at desktop widths.

### Whitespace Philosophy
- **Scene pacing:** major visual chapters use broad top/bottom breathing room.
- **Information compaction where needed:** retail pages deliberately compress spacing to expose more actionable information per viewport.
- **Contrast-led separation:** section transitions rely more on surface changes than decorative separators.

### Border Radius Scale

> For Lumina panels, the **Hierarchy v2 radius ladder** (§4) is authoritative and intentionally caps cards at 16px so inner controls (10px/8px) stay a clear step below. The larger tiers below are Apple-reference context, not targets for our panel chrome.

- **6px:** status banners and small chips.
- **8px:** small buttons, menu items, swatch tiles.
- **10px:** standard controls, inputs, and wells.
- **16px:** the single card level per section.
- **rounded-full:** hue-filter pills, icon buttons, and circular selection controls.
- **(reference only) 28px-980px:** Apple's spotlight shells and elongated capsules — not used for Lumina panel structure.

## 6. Depth & Elevation

| Level | Treatment | Use |
|------|-----------|-----|
| Level 0 | Flat neutral surfaces (`#ffffff`, `#f5f5f7`, `#000000`) | Main narrative and product stages |
| Level 1 | Subtle border containment (`#d2d2d7`, `#86868b`) | Filters, input fields, utility cards |
| Level 2 | Soft shadow (`rgba(0,0,0,0.08)` to `rgba(0,0,0,0.22)` where present) | Highlighted cards and elevated merchandise modules |
| Level 3 | Dark-surface stepping (`#272729` -> `#2a2a2c`) | Overlays, media controls, dark utility clusters |
| Accessibility | Blue focus signal (`#0071e3`) | Keyboard and selection emphasis |

Depth is intentionally restrained. Apple favors tonal contrast, surface stepping, and compositional hierarchy over heavy shadow stacks.

### Decorative Depth
- Decorative depth is primarily created by photographic realism and material rendering, not synthetic UI effects.
- Translucent overlays and glass-like utility bars provide mild atmospheric layering in navigation and controls.

## 7. Do's and Don'ts

### Do
- Use the neutral triad (`#000000`, `#f5f5f7`, `#ffffff`) as the structural foundation.
- Reserve blue accents for genuine action and navigation semantics.
- Keep typography tight and deliberate, especially at display scales.
- Maintain the capsule/circle geometry language for controls and key actions.
- Let product imagery carry visual drama; keep chrome understated.
- Use border-led containment in dense retail contexts instead of heavy card ornamentation.
- Preserve clear separation between showcase modules and transactional modules while keeping core tokens shared.

### Don't
- Don’t introduce broad secondary accent palettes that compete with Apple blue.
- Don’t overuse shadows, glow effects, or decorative gradients in core UI chrome.
- Don’t mix unrelated font families or loosen tracking indiscriminately.
- Don’t flatten all corners to a single radius; Apple uses purposeful radius tiers.
- Don’t overload commerce modules with thick borders or loud visual effects.
- Don’t remove neutral contrast cadence between dark and light chapters.
- Don’t treat marketing and purchase flows as separate design systems.

## 8. Responsive Behavior

### Breakpoints
| Name | Width | Key Changes |
|------|-------|-------------|
| Small Mobile | 374px and below | Tightened retail controls, single-column product stacks |
| Mobile | 375px-640px | One-column modules, compact action rows, condensed selectors |
| Tablet | 641px-833px | Expanded cards and mixed 1-2 column transitions |
| Tablet Wide | 834px-1023px | More stable multi-column merchandising, larger text blocks |
| Desktop | 1024px-1240px | Full retail layouts and product comparison structures |
| Desktop Wide | 1241px-1440px | Marketing hero expansion and broader section spacing |
| Large Desktop | 1441px+ | Maximum chapter breathing room and wide editorial composition |

### Touch Targets
- Primary and secondary actions are generally presented in tap-friendly pill/button geometries.
- Circular media and selection controls align with minimum touchable intent in mobile contexts.
- Dense commerce UI uses compact labels but maintains clear hit regions via surrounding shape padding.

### Collapsing Strategy
- Marketing hero typography scales down in discrete tiers while preserving hierarchy contrast.
- Product and commerce grids collapse from multi-column to stacked cards with persistent selector visibility.
- Utility navigation compresses into simpler link/control groupings while preserving key actions.
- Option/configuration clusters become vertically sequenced to keep purchase flow linear on small screens.

### Image Behavior
- Product imagery preserves aspect and centrality through breakpoints.
- Hero visuals remain dominant on mobile, with text repositioned around media priority.
- Retail thumbnails stay legible via tighter crop logic and denser card stacking.
- Image-led modules continue to anchor the rhythm as layout density increases.

## 9. Agent Prompt Guide

### Quick Color Reference
- Primary action blue: **Apple Action Blue** (`#0071e3`)
- Inline link blue: **Body Link Blue** (`#0066cc`)
- Dark chapter canvas: **Absolute Black** (`#000000`)
- Light chapter canvas: **Pale Apple Gray** (`#f5f5f7`)
- Primary text on light: **Near-Black Ink** (`#1d1d1f`)
- Secondary text: **Secondary Neutral Gray** (`#6e6e73`)
- Retail border soft: **Soft Border Gray** (`#d2d2d7`)
- Retail border strong: **Mid Border Gray** (`#86868b`)

### Example Component Prompts
- "Design an Apple-style product hero on a black canvas (`#000000`) with SF Pro Display semibold headline (48-56px), concise supporting copy, and two capsule CTAs using `#0071e3` and `#1d1d1f`."
- "Create a commerce configuration panel on white (`#ffffff`) with 18px rounded cards, `#86868b` border fields, SF Pro Text 17px body copy, and compact option selectors."
- "Build a merchandising card grid alternating `#f5f5f7` and white surfaces, with image-first cards, restrained shadows, and 14-17px SF Pro Text metadata."
- "Generate a carousel control cluster using circular buttons (50% radius), muted gray overlays, and clear active feedback for gallery navigation."
- "Compose a mixed marketing + retail page rhythm: dark showcase chapter -> light feature chapter -> dense product list module while keeping blue accents only for actions and links."

### Iteration Guide
1. Lock the neutral foundation first (`#000000`, `#f5f5f7`, `#ffffff`) before tuning accents.
2. Keep blue accents scarce and purposeful; if everything is blue, hierarchy collapses.
3. Tune typography in this order: display scale, body readability, then micro labels.
4. Match radius by component class (field, card, capsule, circle) rather than one-size-fits-all rounding.
5. Increase density gradually when moving from showcase sections to commerce sections.
6. Validate that product imagery remains the strongest visual layer after each revision.

### Known Gaps
- Distinct semantic status colors (error/warning/success) were not consistently visible in the extracted page set.
- Some interaction micro-states vary by module and are not represented as universal system tokens.
- A few retail modules expose context-specific typography overrides that do not appear across all five pages.
