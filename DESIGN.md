# Design System Inspired by Apple

## Application Background Levels

- 浅色模式的默认页面背景使用 `slate-50`；顶部两级导航和设置页左侧分类导航使用 `slate-200`，与内容区形成层次。
- macOS 桌面端使用 `hidden` 标题栏，保留系统原生红黄绿按钮；一级导航直接放入标题栏，省去独立标题行，保留 Logo 和应用标题，左侧预留按钮空间。空白区域可拖动，导航及右侧控件使用 `no-drag`；窄窗口沿用标题收起和导航换行布局。浏览器和 Linux 保持原有窗口布局。
- macOS 红黄绿按钮与顶栏第一行 Logo 垂直居中对齐，距窗口左边缘 16pt；首次在纵向边距为零时通过 Window Controls Overlay 测量原生按钮高度，按界面缩放换算定位，左侧按 `titlebar-area-x` 预留按钮空间。导航换行时仍对齐第一行，不使用固定按钮高度或人工纵向偏移。
- Windows 同样合并一级导航，使用 Window Controls Overlay 保留系统窗口按钮，按 `titlebar-area-*` 环境变量避让右侧按钮并适应缩放；窗口按钮区域同步浅色／深色主题。浏览器和 Linux 保持原有布局。
- 页面容器使用 `--surface-panel`，弹窗使用 `--surface-panel-strong`，浅色模式均映射到 `slate-50`。需要保留卡片外框的整块工作面板使用 `panel-default-surface`，不要直接沿用白色 `--surface-card`；卡片和输入控件不等同于页面背景。
- 原先使用 `slate-50` 的内部控件、浅灰卡片和分组背景使用 `slate-100`；页面本身不随之加深。耗材卡片的悬停与选中背景使用 `slate-200`，文字保留原色。
- 深色模式保持独立映射；真实颜色色块、透明棋盘格、图标和主题开关指示点不参与背景色阶迁移。

## 仓库类页面设计规范

适用于以浏览、查找、选择和管理资源为主要任务的页面，例如耗材库、LUT 库。目标是让用户持续定位资源、切换比较，并在需要时查看详细信息。页面应按以下规则实现；资源特有的字段、操作和分组名称按业务决定。

### 页面结构与视觉层级

- 页面由固定工具栏、可滚动资源列表、按需打开的详情区组成。工具栏放在导航下方，列表独立滚动；不在整页、统计区或整个列表外再套圆角卡片。
- 页面与工具栏浅色背景使用 `slate-50`，搜索框和资源卡片使用 `slate-100`。悬停、选中使用 `slate-200`，保留原文字颜色。深色对应页面 `slate-950`、卡片 `slate-800`、悬停和选中 `slate-700`。
- 卡片使用 10px 圆角、1px 细边框、无阴影。浅色默认边框 `slate-200`、选中 `slate-300`；深色默认 `slate-700`、选中 `slate-500`。以底色层次表达状态，不复用导航的白字蓝底选中样式。
- 资源名称使用主文字色，类型、误差、日期等使用次要文字色。只使用现有 slate 色阶与共享主题令牌，不为单个仓库另建颜色体系。真实资源色块保留自身颜色。

### 固定工具栏

- 左侧放搜索与简洁统计，右侧放展开／收起、选择、导入、刷新等操作。工具栏宽度不足时自然换行，不压缩按钮文字。导航已经说明页面位置时，不重复放页面标题。
- 统计使用“资源数 · 分组数”；选择模式显示已选数量。搜索时统计反映匹配结果，避免把全库总量当作当前结果数。
- 工具栏保持不动，下方内容独立滚动。分界线在内容滚离顶部时显示，回到顶部时在 200ms 内渐隐；保留边框占位，避免布局跳动。减少动态效果偏好下关闭过渡。
- 格式说明、导入方式等静态帮助放在操作入口的提示中。错误、当前进度及无法操作的原因保持可见，不用常驻说明段落占据工具栏空间。

### 搜索与选择

- 搜索覆盖用户可识别的名称、品牌／分组和资源类型，忽略首尾空白及大小写。搜索后回到列表顶部、自动展开匹配分组，并提供明确的无结果状态。
- 搜索期间的分组展开状态与常规浏览分开维护。清空搜索后恢复原来的展开状态，不改写固定分组偏好。
- 浏览模式下点击卡片查看详情；批量操作由明确的“选择”入口进入，卡片增加勾选标记。不得让一次点击同时承担查看详情和批量选择。
- 搜索后的“全选／清除选择”只作用于当前结果，保留结果之外的已有选择；已选总数应仍可见。切换分组展开状态不清除选择。

### 分组管理

- 分组栏使用名称、带单位的数量、展开箭头及固定按钮。数量单位应符合资源含义，例如耗材显示“6种”，不只显示裸数字。
- 普通分组默认收起。固定按钮记住“每次进入默认展开”的偏好；当前手动收起或“全部收起”不取消固定。所有当前分组已收起时，工具栏按钮变为“全部展开”，否则为“全部收起”。
- 整条分组栏支持拖拽排序，不额外占用位置放拖动把手。拖动前设置小幅移动阈值，普通点击仍执行展开／收起；固定按钮独立响应，不触发拖动。
- 拖动时浮层呈现完整分组栏，其他分组实时让位；松手后保存顺序，Esc 取消。固定、展开、选择等状态按资源／分组身份关联，不依赖显示位置。新分组不打乱已保存顺序。
- 分组栏可通过键盘聚焦，使用上下方向键调整顺序；展开状态、固定状态和焦点应有可访问的表达。

### 资源卡片

- 卡片服务于快速识别和比较：优先展示色块／缩略图、名称、类型，以及确实影响选择的少量指标。耗材的拟合误差属于比较信息，可以直接展示；目录、路径、内部来源枚举等实现信息放入详情。
- 默认卡片宽度为 `15rem`，卡片间距为 `1rem`。采用固定列宽并自动换行，不用 `1fr` 均分剩余宽度。详情打开或关闭时只改变列数，不改变卡片宽度、色块、字号和内部间距；极窄容器不足 `15rem` 时允许卡片收缩至容器宽度，避免横向溢出。
- 卡片内边距为 `1.25rem`，图文间距为 `1rem`；耗材色块为 `3.5rem × 3.5rem`。名称与次要信息之间留 `0.5rem`，类型、误差、日期之间留 `0.25rem`。不强制截断长名称来凑相同高度。
- 同一品牌／分组内的卡片保持等高，高度由该分组内容最多的卡片自然撑开，可使用 `auto-rows-fr` 与 `items-stretch`；不同分组独立计算，不设置全库统一的固定高度。
- 等高卡片的文字区域统一顶部对齐，标题从相同的顶部内边距开始，后续字段按规定间距自然排列。短内容留下的空间放在底部，不将整块文字垂直居中，也不拉大字段间距填满卡片；按钮形式的卡片应显式设置内容布局，避免浏览器默认对齐造成错位。
- 同名资源需要明确区分时，增加简洁的更新日期／时间，缺失时回退创建时间；不把长目录名追加到卡片，也不以临时序号代替可识别信息。完整来源和时间保留在详情中。
- 信息缺失应如实显示未填写或缺失值，不推断类型、不把未知误差显示成零。

### 详情与交互反馈

- 详情统一按资源身份、选择依据、辅助信息、底部操作排列。顶部直接显示资源名称、品牌／类型和可用的色块，不重复“查看详情”标题；关闭按钮在右上角。
- 普通字段使用左标签右数值的紧凑行，路径和目录默认与标签同行，仅空间不足时自然换行。耗材优先显示拟合误差和采集层高，LUT 优先显示颜色模式；仅展示实际可用的数据，不推测配色或日期。
- 云端安装状态紧邻下载／更新操作，已安装不显示禁用的大按钮；可回退的版本记录按需打开。详情的全部操作集中在完整信息之后，不穿插字段；多个操作使用等尺寸两列布局，删除用红字中性底并入操作区。


- 宽窗口下详情占独立侧列，与资源列表并列展示；不覆盖可点击的列表。允许卡片换行，固定卡片自身尺寸，方便连续切换比较。
- 窄窗口下详情进入正常文档布局，避免将列表挤成不可用的窄列。详情按基本信息、业务指标和使用记录组织；路径、日期、大小等文件字段直接与其他详情排列，不设置“文件信息”标题、分组边界或折叠层级，其他低频信息可折叠，破坏性操作用红字中性底明确区分。
- 切换资源时复用详情区，不跳转到独立页面。关闭按钮和 Esc 均可关闭详情，并把焦点还给触发卡片；宽窗口下打开详情不应主动滚动列表。
- 拖拽、固定等简短操作提示使用共享的样式化悬停／键盘焦点提示组件（`HeaderTooltip`）；拖动期间隐藏提示。参数说明和详细帮助使用 `HelpDot`／控件 `tooltip`，不使用浏览器原生 `title` 气泡。
- 普通操作复用共享按钮组件。通过语义状态、勾选标记、细边框和键盘焦点区分交互，不增加与导航争夺注意力的大面积强调色。

### 实现与验收

- 复用共享颜色、按钮、提示和拖拽组件；文本集中维护在翻译表。分组固定和顺序保存在本地，存储不可用时当前会话仍能操作；临时搜索和展开不覆盖长期偏好。
- 验证宽窄布局、深浅主题、键盘操作和减少动态效果。检查列表滚动时工具栏稳定，打开详情前后卡片宽度不变，清空搜索恢复分组状态，拖拽后顺序与固定设置可恢复。
- 不把业务字段或当前数据量写成所有仓库都必须一致的模板。新增字段应先判断它是否帮助用户在列表中识别或比较，否则放入详情。

### 云端仓库的差异

- 沿用仓库页面底色、固定工具栏、固定宽度卡片及并列详情；云端目录以搜索、状态筛选和分页浏览为主，不默认复制本地品牌折叠、拖拽排序及固定展开。
- 卡片保留安装状态与下载／更新快捷入口，点击主体只查看详情，不触发安装。已安装状态不再重复占用一个禁用的大按钮。状态应有文字表达，不仅依靠颜色。
- 卡片按当前行等高、文字顶部对齐、操作贴底，不因后续加载的长标题改变整个品牌已有卡片高度。
- 搜索必须说明覆盖范围；未加载完整目录时不能把局部无结果表述为全库无结果。统计区分当前匹配目录与本地安装记录，不用同一个“已安装”标签表示不同范围的数量。
- 路径、体积与版本记录放在详情；内容哈希仅供内部比对，不在用户界面展示；版本管理仍应提供全局入口，保证已不在当前目录中的本地记录也能访问。普通浏览不执行下载、更新或回滚。
- 未下载或本地文件缺失的条目不显示本地路径；本地路径仅取自已确认存在的本地匹配或安装记录，不用云端目录预设的安装目标代替。
- 新旧版对比入口是临时验收功能，两个版本共用数据和操作逻辑；切换不得清空搜索或中断正在执行的操作。

## 关闭按钮

- 详情区、侧栏及弹窗的关闭入口统一使用共享 `CloseButton`，放在右上角：圆形灰底、居中的叉号图标，无边框、无阴影，不使用单独的“关闭”文字或方形底。
- 点击区域为 32×32px，叉号为 20×20px。浅色底为 `slate-200`、图标为 `slate-600`，悬停加深至 `slate-300`；深色底为 `slate-700`、图标为 `slate-300`，悬停为 `slate-600`。使用矢量叉号，避免 emoji 随平台改变颜色和外观。
- 使用本地化的“关闭”可访问名称（`aria-label`），保留可见焦点环；叉号含义明确，不显示悬停／键盘焦点提示，也不添加原生 `title`。普通关闭不使用删除操作的危险色。
- 关闭图标、Esc 和允许的遮罩点击应调用同一关闭逻辑；存在未保存检查时不能绕过。关闭后将焦点恢复至触发入口。
- “取消编辑”“退出选择模式”“返回”和“退出应用”具有不同含义，不因采用此样式而替换成关闭图标。系统原生窗口按钮沿用平台外观。

## 展开与收起

- 可折叠的内容分组及面板统一使用 `DisclosureChevron`：16×16px、2px 细线箭头，收起向右、展开向下，不使用实心三角或文字字符代替图标。
- 箭头放在标题行右侧，不另加圆形底或边框；它表示内容展开状态，与圆形灰底叉号的关闭操作区分。沿用 slate 次要文字色，旋转过渡为 200ms，减少动态效果时取消过渡。
- 原生 `details` 使用共享 `DisclosureSummary`，隐藏浏览器默认标记，保留原生点击和键盘行为；受控按钮通过 `aria-expanded` 表达状态。图标本身对辅助技术隐藏，按钮保留明确名称和键盘焦点。
- 下拉选择器、导航返回、排序方向和全屏按钮有不同含义，不套用内容折叠规则。

## Native Scroll Boundaries

- 独立页面、工作区侧栏和弹窗正文使用稳定的原生滚动容器，并设置 `overscroll-y-contain`，让触顶或触底后的滚动停留在所属区域。
- 区域内的小列表保留默认滚动衔接：列表到边界后可以继续滚动所属面板。不要给所有 `overflow-auto` 或 `.dock-scrollbar` 统一加隔离。
- 悬停只改变滚动条的外观，不切换 `overflow`；普通 DOM 内的滚动不通过 `wheel` 监听器手动改写 `scrollTop`。跨 Portal 的滚动衔接也必须尊重所属面板的边界。

## Color Workstation Selection Invariants

- 颜色调整页使用连续的直角工作区：预览、选择工具、换色与 LUT 区域通过横向或竖向 `panel-divider` 分割，不使用圆角卡片外框或阴影。控件保留自身圆角。
- 历史、选择工具、自由色、配方、悬停显示、目标颜色 B 和相似配方的分组标题使用中性文字，不添加装饰色点。
- 共享选择工具使用独立的 `selection-tool-control` 样式，不引用导航选中态变量。浅色默认 `slate-100`、激活 `slate-200`，文字 `slate-900`；深色默认 `slate-800`、激活 `slate-700`，文字 `slate-100`。保留 `aria-pressed`、细描边和键盘焦点轮廓，悬停不清除激活态。「选区闪烁」放在选择工具下方的独立行，使用共享 `Switch` 组件，不使用工具按钮选中态。

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

Parameter explanations across all tabs follow this single source of truth. A visible info icon (ⓘ, stroke-style, no background — rendered by `HelpDot`) is shown for controls with explanatory help. Short action hints (such as pinning or dragging) use the shared `HeaderTooltip` on the action itself, as specified for repository pages above; they do not require an additional info icon.

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
- Keep current values, actionable status, unavailable-option reasons, active compatibility limits, validation errors, and action-critical warnings visible. Do not make users open a tooltip to find out why an action is unavailable or unsafe.
- When inline text and a help icon both appear, the inline text states the current result or constraint briefly; the tooltip supplies the explanation and detail. Do not reuse the same explanation in both places.
- Hint text must be bilingual (`zh` + `en`) in `translations.ts` with a `*_hint` suffix key
- The ⓘ icon visual style is fixed in `HelpDot` (stroke-style `InfoIcon`, no background); do not recreate it inline
- Every control with parameter explanations **must** display a visible ⓘ icon. Short action hints use the shared hover/focus tooltip exception described above.
- Hint copy is written for end users: describe the visible effect and the trade-off, avoid algorithm terms (e.g. no "K-Means", "8-neighborhood", "L\* roll-off")

#### 提示语与帮助说明的信息分工

判断一句话放在哪里，先问：**用户现在是否必须看到它，才能正确完成操作？** 必须看到的信息直接展示；用于理解功能的信息放入 ⓘ；只在特定条件下有用的信息按条件显示。

| 信息类型 | 展示位置与时机 | 示例 |
|---|---|---|
| 功能解释、使用方法、默认值与取舍 | 标签旁的 ⓘ 帮助中，不在控件下方重复 | 模板继承哪些参数、SVG 清晰度的适用范围、缓存清理的作用 |
| 当前取值、已选内容 | 控件自身或附近的简短摘要 | 保存目录、模板名称、模板设备信息、当前颜色计算精度 |
| 影响当前操作的限制 | 相关选项启用、内容选中或操作触发后直接显示 | 自定义模板不支持批量、拼图、校准和色块生成 |
| 错误、不可用原因及处理办法 | 对应控件或操作附近直接显示，不依赖打开帮助；问题解决后移除 | 模板缺失、通知权限被拒绝、功能不可用、路径校验失败 |
| 用户操作的结果 | 操作完成后在原操作附近显示 | 缓存清理数量与释放空间、路径保存结果 |

提示语与 ⓘ 可以同时存在，但必须提供不同的信息：行内文字简述当前状态或限制，帮助说明解释功能和细节。不要在两处复述同一段内容，也不要把所有解释都变成常驻提示条。没有需要处理的问题时，不使用成功或警告提示条长期占位。

设置页遵循以下具体规则：

- **3MF 项目模板**：使用内置配置时，不显示自定义模板的限制段落；匹配规则、参数继承和支持范围放入帮助。选中自定义模板后，显示模板摘要及简短的生成范围限制，帮助中不再重复该范围说明。模板丢失或校验失败时，直接给出原因和恢复方式；生成入口仍须直接解释实际的不兼容问题。
- **完成通知**：正常的权限状态放在帮助中；权限被拒绝、浏览器不支持或请求失败时，直接显示原因及可行的处理办法，不能仅放进 ⓘ。
- **SVG 清晰度与缓存管理**：通用适用范围、使用取舍和清理作用放入帮助。SVG 小洞补偿不可用的原因、缓存清理结果仍在界面中直接展示。
- **手动设置切片软件**：折叠入口保留一句适用条件，帮助用户决定是否展开；路径格式和示例在展开后展示。
- **父级设置与从属字段**：共享说明由父级提供一个帮助入口。只有子字段存在独立含义或操作要求时，才增加自己的 ⓘ，避免同一帮助在父子两处重复。

行内提示保持简短，说明当前发生了什么；错误和限制需要给出下一步做法。中英文同步维护于 `frontend/src/i18n/translations.ts`，复用 `HelpDot`、控件的 `tooltip` 和现有状态提示组件。

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

图像转换的核心设置使用 `settingsGroupClass` 将导入、颜色设置（含来源类型、LUT／耗材选择与量化颜色数）、尺寸和底板、单面/双面打印、建模模式分别放在连续的灰底分组中。分组使用 `--surface-well`、10px 圆角、12px 内边距和 16px 组间距，不再使用标题右侧横线；结构与建模直接使用单选组标题，避免重复标题。只有分组标题使用半粗字重；“来源类型”等组选项标签沿用普通字段字重。组内滑块数值框使用 `--surface-card` 与灰底区分，深色主题沿用对应表面变量。

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
| Control / Well | `10px` (`rounded-[10px]`) | wells, inputs, dropdown trigger |
| Small control | `8px` (`rounded-lg`) | buttons, dropdown menu items, swatch tiles |
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

设置页各分类复用 `cardPadClass` 作为唯一外层卡片，内部设备摘要和路径使用 10px 无边框凹槽，选项之间使用 `panel-divider`。普通选项标签统一 14px medium、次要墨色；组标题使用 14px semibold，弹窗标题使用 15px semibold。独立选项间距为 20px，开关行使用 16px 横向间距并垂直居中；开关展开的从属参数使用 `dependentGroupClass`。帮助说明统一由标签旁的 `HelpDot` 或控件的 `tooltip` 提供，兼容限制、当前状态和错误仍直接显示。分类导航复用主导航标签样式；打印机和打印板选项以底色及显式选中标记表达状态，内部不增加卡片描边或阴影。

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
| Settings — `SettingsPanel`, category navigation, device / build-plate chooser and setting rows | **Migrated** |
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
| **Primary** | blue fill + white text (`.action-control-primary`) | the main commit in an area: generate, apply, confirm, save |
| **Secondary / ordinary operation** | neutral fill + dark text + thin gray border (`.action-control`) | import, choose a file or device, edit, history, reset, cancel, close, back |
| **Ghost** | text / icon only | compact tools, mode selections, toggles, dialog close icons and collapse headers |

`Button` defaults to `secondary`. Explicitly select `variant="primary"` for the main commit; an operation dialog or a function call alone does not justify blue emphasis. A group usually has one primary action. Destructive actions use a neutral button with `tone="danger"` (red text), including delete and uninstall. Raw buttons use `.action-control` for ordinary operations and add `.action-control-primary` only for the main commit. Field pickers, selectable options, tabs and switches retain their own component styles.
按钮默认使用中性 `secondary`；仅区域内的主要提交动作显式设置 `variant="primary"`，通常一组只保留一个蓝色主按钮。导入、选文件、更改设备、历史、重置和撤销等普通操作使用中性底色；删除与卸载使用中性底配 `tone="danger"` 红字。原生按钮沿用 `.action-control`，主要提交额外添加 `.action-control-primary`。导航选中态、字段选择器和开关保持各自语义。

Standard text buttons use 8px corners: ordinary controls have a 32px minimum height and primary actions 36px. Small buttons remain 32px; icon-only buttons may remain circular. Buttons change fill on hover and press without moving or scaling. Both neutral and primary buttons use gray fill/text when disabled. The `--button-*` tokens in `index.css` define light and dark appearances; avoid per-page color overrides. Keyboard focus remains visible through an outline.
普通文字按钮高度至少 32px，主操作至少 36px，圆角 8px；图标按钮可保留圆形。悬停与按下只改变底色，不上浮、不缩放。禁用时统一灰底灰字。深浅色统一使用 `--button-*` 变量，不在页面另写按钮配色；键盘聚焦保留轮廓提示。

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

- **One tab style for both levels:** borderless tabs with no track behind the group; the selected tab uses a solid blue fill (`--nav-tab-selected-bg`), white text and icons (`--nav-tab-selected-text`), 8px radius and no shadow. Hover uses `--nav-chip-hover`. Shared classes live in `frontend/src/components/widget/navTabStyles.ts`; Settings category navigation uses the same selected treatment.
  两级导航使用同一种标签：无描边、无底槽，选中项是蓝底白字、白色图标（8px 圆角、无阴影），悬停用浅灰底。设置分类导航沿用同一选中态。
- **Rows and dividers carry the hierarchy, not boxes:** the header row (brand, primary tabs, tools) and the sub-tab row share the chrome surface, one `panel-divider` hairline separates them and a second one closes the sub-tab row. Never add tracks, outlines or tinted bands to tell the levels apart.
  层级靠行和分隔线表达：顶栏行与子导航行同底色，中间一条细线，子导航行下方再一条；不要用底槽、描边或色带区分层级。
- **Primary vs sub:** both levels use white selected text and icons in light and dark themes; both use semibold text, with 16px primary icons and 14px sub-tab icons.
  两级导航的选中文字和图标在浅色和深色主题下均为白色；字重统一为半粗，主导航图标为 16px，子导航图标为 14px。
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
