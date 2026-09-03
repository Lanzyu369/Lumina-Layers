# SVG 平滑轻量预览、模型覆面真实颜色与实时尺寸设计

## 结论

本次修复把三个已经互相影响的前端预览问题放在同一个独立 PR 中处理：

1. 原生 SVG/Vector 的普通 3D 预览改用解析后的矢量轮廓生成轻量网格，不能再从降采样像素掩膜反推边界。
2. 模型覆面仍使用现有的平滑纹理预览，但颜色预览完成后必须显示 LUT、配方叠色、替色和撤销/重做后的干净结果，不能一直显示原始上传颜色。
3. 修改普通目标尺寸恢复为前端即时缩放，不销毁 session，也不重新请求主预览；显示坐标、用户编辑坐标和最终生成坐标使用明确且可测试的转换契约。
4. 高级设置提供“平滑 SVG 轻量预览”开关，默认开启；关闭时只让原生 Vector 3D 预览回退到旧 segmented GLB，作为兼容/排障手段。

精确打印几何继续只属于 3MF 生成链路。浏览器不因点击“生成”而切换到打印级 GLB。本次不修改 3MF 网格、切片 coverage、独立壳体、拓扑、材料身份或打印质量。

## 已确认的根因

### 普通 SVG 的像素感

原生 SVG 在 `VectorProcessor` 中已经解析成 Shapely 矢量几何，但当前异步轻量 GLB 没有消费这些几何。预览链路先以 10 px/mm 构建 `matched_rgb` / `mask_solid`，大图再降到约 30 万像素，然后从像素掩膜提取轮廓并挤出。

因此当前 GLB 虽然不再逐像素生成体素，却仍然是“像素轮廓的挤出”。R4C1 的 1110×2407 缓存还会在 GLB 阶段继续降采样，所以 SVG 曲线会出现可见台阶。

### 模型覆面显示原始颜色

模型覆面选择器没有加载普通预览 GLB。它把 `Scene3D` 传入的 `imagePreviewUrl` 画入动态 CanvasTexture，再贴到用户选择的模型表面。对于 SVG，`imagePreviewUrl` 是原始文件的 Blob URL，所以浏览器能够平滑抗锯齿，但完全绕过了 LUT 匹配、配方叠色和后续替色。

状态中已经存在合适的颜色来源：

- `previewBaseImageUrl` 是当前干净的、无选区高亮的显示结果；
- 初次预览时它指向像素对齐的 `preview_rgba`；
- 区域替色、批量替色、自定义配方、撤销和重做都会更新它；
- `previewImageUrl` 可能暂时指向选区高亮图，不能用作覆面纹理。

### 修改尺寸会重新生成预览

实时 XY 缩放能力仍在 `Scene3D` / `InteractiveModelViewer` 中。回归来自 PR #519 引入的自动预览输入键：`target_width_mm` 被当成所有预览参数的一部分，宽度变化会立刻清空当前 session 和 GLB，再延迟请求新预览。

这覆盖了原有的即时缩放语义，也与 #586 已确定的“尺寸属于前端实时显示状态”契约冲突。

但不能只从自动预览 key 中删掉宽度。当用户先做区域替色或自定义配方，再改尺寸时，现有生成校验会因预览宽度不同返回 409；若直接放宽校验，旧像素网格又会被当成新物理尺寸的网格，造成编辑错位。

### 异步状态可能串回旧 session

部分替色请求只校验全局 replacement epoch，没有同时校验发起请求时的 session id 和 preview request revision。用户切换文件后，旧请求仍可能把 `previewBaseImageUrl` 写回当前 store，进而让模型覆面显示上一个素材。

## 方案比较

### 方案 A：提高 segmented GLB 的像素分辨率

优点是改动小。缺点是曲线仍然受像素网格限制，文件、内存和生成时间会继续增长；放大后仍能看到台阶。该方案不解决根因，拒绝采用。

### 方案 B：普通 SVG 也只使用一张平滑顶面贴图

模型覆面已经证明这种方式平滑且轻量。但普通 3D 预览还要表达逐色高度、浮雕、描边、景泰蓝线、单双面和轮廓侧壁。单张平面纹理会把这些三维语义压平，只适合作为模型覆面的平面排版预览，不能成为普通 SVG 的唯一几何来源。

### 方案 C：复用现有 Vector 几何缓存 + 解析式轻量网格 + 正确的覆面纹理（采用）

普通 SVG 从已存在的 session-bound `vector_parse_clip_cache_path` 取得解析、遮挡裁剪后的矢量 footprint，再从当前预览像素缓存中只读取显示颜色与高度身份。几何边界不再来自像素。模型覆面继续使用纹理，但切换到干净的叠色预览图。

不再新增第二份 WKB/“通用显示描述”文件。类型化的 `VectorQuickPreviewSourceV1` 只是对现有私有几何缓存的受限加载视图，避免两套几何序列化和两套 TTL。

该方案同时满足平滑、轻量、创意功能和真实颜色。

## 架构设计

### 1. 三种不同的状态身份

不再让一个 `params_match` 同时承担编辑缓存、预览资产和打印生成三种语义：

- `edit_projection_identity`：源文件、session、预览像素网格、颜色/配方编辑版本。它表达“用户编辑了图上哪里”，不把物理宽度当成编辑内容。
- `preview_asset_identity`：上述身份 + GLB 构建 job token + 资产基准宽高。它只能作为浏览器快速预览，尺寸不同时由前端变换，不能冒充同尺寸生成资产。
- `generate_identity`：当前完整打印参数，包括最新尺寸、材料、高度和创意功能，只用于精确 3MF。

这三种身份用独立 helper/类型表达，不再用一个布尔值隐式推断。

### 2. 复用现有 Vector 几何缓存

`vector_parse_clip_cache_path` 已经包含裁剪后 shapes、silhouette、scale factor 和 bounds，并已由 preview session 注册、限制为 64 MiB 且随 session 清理。新实现不重复保存这些几何，而是在 `vector_glb_preview.py` 中增加一个受限加载器：

- schema 和 cache key 必须与当前 session/source 完全匹配；
- 创建 artifact 时，服务端同时把现有 cache key 的 provenance digest 保存到 preview session metadata；异步 GLB worker 只接受 session 传入的 expected digest，不能拿 artifact 内自带的 key 给自己作证明；
- provenance 覆盖 source 绝对路径与 mtime、预览目标宽度、采样精度、stroke 展开和 gradient bands；任一项变化都必须重新取得当前 session 的几何源；
- 只接受 Polygon / MultiPolygon；
- 坐标、bounds、scale 必须为有限数；
- 对 shape、ring、coordinate 和总字节数设定硬上限；
- 路径必须仍由当前 session 的 temp-file ownership 记录持有，不注册成 FileRegistry 下载资产；
- 校验失败时回退当前 segmented GLB，不读取其他 session 的路径。

provenance digest 只是与现有 artifact path 并列的一小段服务端元数据，不是第二份几何 artifact，也不由前端提交。

### 3. 解析式矢量轻量 GLB

异步 GLB worker 检测到有效的原生 Vector 几何源时，优先走现有 `vector_glb_preview.py` 内的解析式构建器：

1. 用预览网格只对每个原始矢量连通部件做当前显示颜色与高度身份分类；
2. 按 `display RGB + height identity` 分组，材料档案/自定义配方显示合成后的真实外观色，不把每个打印材料层都搬进浏览器；
3. 复用 `VectorPreviewPart` / `VectorPreviewExtrusion`、节点命名和 GLB buffer 打包；
4. 复用 `vector_mesh_topology.py` 的有界三角化/挤出能力，直接挤出 Polygon，不经过像素掩膜；
5. 保留 `color_RRGGBB`、`backing_plate` 和 `preview_canvas_bounds` 等前端契约；同时给每个解析式颜色 part 增加显式 `height_key`，由 exporter 写入 glTF extras/userData；现有 batched material appearance 继续使用 `height_segments`，两者都不能从当前显示色反推浮雕高度；
6. 沿用当前异步 job token、每次 UUID 唯一的 GLB 文件名、FileRegistry 和 session 清理流程。

`height_key` 是 `VectorPreviewPart` 上单一职责的可选字段，不扩成任意 metadata 字典。查看器对解析式单 part 优先读取 `mesh.userData.height_key`，对现有 batched part 继续读取 `height_segments`，最后才对没有新 metadata 的旧 GLB 回退 mesh 名称。替色只改变 `display RGB`，不能改变稳定高度身份；若同一显示色由两个不同高度身份合并而来，仍输出两个轻量 part。

第一版不再额外做会改变轮廓的 Shapely simplify；SVG 解析阶段已经有毫米级曲线采样容差。这样能直接保留孔洞、独立部件和可见拓扑，也避免新增一套简化规则。

### 4. 编辑后的平滑重建

全局颜色替换仍可先由前端即时改材质。需要服务端确认的区域替色、配方替换和撤销/重做完成后，异步构建器用当前 `matched_rgb`、`height_identity_rgb` 和现有矢量几何源重新归类 shape，再生成同一套平滑网格。显示色变化只更新 part 的颜色，`height_key` 始终来自未被显示替色重写的 `height_identity_rgb`。

像素缓存只用于判断一个既有矢量连通部件当前属于什么显示颜色或高度身份，不再作为网格边界。这样替色结果与 2D 预览一致，同时边界仍来自 SVG 矢量轮廓。

本 PR 的准确契约是：

- 整色替换和配方变化：保留原 SVG 轮廓，显示颜色与当前干净 2D 预览一致；
- 连通区域编辑：遵循当前 native Vector 生成链路已有的“连通部件多数分类”语义；
- 任意像素画笔在一个 SVG 连通面内创建新分割边界的自动矢量化，不属于本 PR。

### 5. 统一 PreviewSpace 和创意功能

前端建立一个小而明确的 `PreviewSpace`，统一计算资产基准 bounds、当前缩放后 bounds 和屏幕/模型坐标转换。规则只有两类：

- 资产局部坐标：主模型轮廓、颜色区域、底板和拼图画布随当前目标尺寸缩放。
- 绝对毫米参数：钥匙扣宽/孔径、磁铁直径/厚度、描边宽度、景泰蓝线宽/线高、底板和涂层厚度不随 XY 比例放大。

具体行为：

- 浮雕和逐色高度继续按 `height identity` 调整 Z；
- 钥匙扣使用缩放后的模型边界定位，扣体尺寸和用户偏移保持绝对毫米；
- 冰箱贴中心是相对模型中心的绝对毫米坐标，预览不再自行乘 scale；必要时对缩放后 bounds 做夹取，生成请求发送同一份坐标；
- 描边和景泰蓝从当前缩放后的 footprint 构建，或在缩放 group 内做明确的宽度逆变换，确保世界坐标中的毫米宽度不变；
- 拼图不重跑主 GLB，继续由已有轻量 layout overlay hook 按新尺寸更新；
- 相机范围、热床交互和拖拽逆变换都消费同一个 `PreviewSpace`；
- 双面继续镜像轻量颜色层；最终 3MF 不消费显示网格。

普通 raster、高保真高度图和非原生 Vector 路径继续使用现有 segmented GLB 构建器；它们共享尺寸即时缩放与坐标修正，但不误入解析式 Vector 构建器。

### 6. 模型覆面纹理来源

新增一个明确的覆面纹理选择规则：

```text
存在当前 session 的 previewBaseImageUrl -> 使用干净的叠色/替色结果
尚未完成颜色预览                    -> 使用原始 imagePreviewUrl 供选面与排版
session 被关闭、切换或失效           -> 清除旧 previewBaseImageUrl，禁止继续显示
```

不能使用 `previewImageUrl`，因为它可能包含颜色选择、连通区域或渐变区域的临时高亮。

CanvasTexture 的动态分辨率、SVG 浏览器抗锯齿、LinearFilter 和资源释放逻辑保持不变。但所有会写入 `previewBaseImageUrl` 的异步操作必须通过同一个提交守卫。覆盖范围包括 batch replace、custom recipe、multi-select、gradient replace、`submitReplacePreview` 及其撤销/重做入口，不能只修目前最明显的一条路径：

```text
captured session id
+ captured previewRequestRevision
+ replacement epoch
== current store identity
```

切换文件、关闭 session 或新预览建立后，旧响应不得更新纹理、GLB URL 或 loading 状态。

### 7. 尺寸即时缩放与生成时编辑投影

`target_width_mm` / 派生高度不再进入普通流程自动预览的重建身份。尺寸变化只更新前端目标尺寸，并通过 `PreviewSpace` 缩放当前轻量模型。大幅面分块是例外：总尺寸会改变分片数和布局，仍保留其专用刷新语义。

点击生成时，必须按最新尺寸重算精确生成分析，但保留用户在旧预览网格上已做的空间编辑：

- 增加一个小型、纯数据的 `EditProjectionGrid` 契约，显式携带旧网格宽高、像素中心归一化规则、solid mask 和编辑 revision；放大、缩小以及跨过 1600 px cap 时都使用同一变换，禁止 helper 各自猜测 px/mm。
- 原生 Vector：在当前尺寸下重新解析精确几何；颜色/材料路径把 `matched_rgb`、`height_identity_rgb`、`material_matrix` 中相对 pristine 基线真正变化的部分投影到当前连通部件，配方路径把 region masks 投影给 `apply_recipe_overrides_to_analysis`。两套 helper 共同消费 `EditProjectionGrid`，不把旧像素密度当成新物理像素密度。
- 自定义配方、追加层、虚拟材料以及 material archive 动态层都走上述配方投影；未编辑区域必须逐项等于当前尺寸的一次全新分析，不能被旧缓存覆盖。
- Raster/高保真：尺寸不同时先按当前尺寸跑正常生成分析，再把预览网格中“相对于 pristine 基线真正被用户改过的部分”按归一化坐标投影到新网格。不直接放大整张旧材料矩阵，以免用旧采样分辨率替代新尺寸的打印分析。
- 只有存在待重放的空间编辑时才要求完整 pristine/current artifact；任何必需缓存缺失、过期、维度不一致或 session 不匹配都失败关闭，返回可操作的 409。没有编辑时直接按当前尺寸正常生成。

旧尺寸 preview GLB 只在浏览器中实时缩放；其 fingerprint 不得冒充新尺寸的可复用生成资产。

### 8. 可选的平滑 SVG 预览开关

高级转换设置新增 `enableSmoothVectorPreview`，用户文案为“平滑 SVG 轻量预览”，默认值为 `true`：

- 开启：原生 Vector 优先使用本设计的解析式平滑 GLB；几何源无效时仍安全降级到 segmented GLB。
- 关闭：原生 Vector 明确使用既有 segmented GLB，便于兼容旧显卡、定位素材边界差异或临时对比。
- raster、高保真、模型覆面与最终 3MF 不读取该开关。
- 尺寸即时缩放、session/竞态修复、覆面真实颜色和“禁止打印级 GLB 回退”是正确性契约，始终生效，不能被开关重新关闭。

设置由 `settingsStore` 持久化在当前浏览器。它是个人显示偏好，不属于作品内容或打印参数，因此不写入分享卡，也不随配方导入覆盖其他用户的设置。前端 preview 请求使用 `enable_smooth_vector_preview` 把偏好传给后端；后端把当次选择保存在当前 preview session 的服务端 metadata，后续替色/配方触发的 GLB 重建继续使用同一模式，不能从全局默认值猜测。

用户在已有原生 Vector session 中切换开关时，只调用窄职责的 quick-preview GLB rebuild，不重跑 2D 颜色分析、不清空编辑历史、不销毁 session，也不影响已经生成的 3MF。旧 GLB 保持显示，所选 renderer 的新 GLB ready 后原子切换；快速连续切换仍由现有 job token 保证只有最后一次生效。没有当前 Vector session 时，设置只影响下一次预览。

设置 UI 遵循 `DESIGN.md`：放在高级转换设置现有单层卡片内，用分割线分组；标题旁使用标准 `HelpDot`，说明“只影响浏览器 3D 显示，不影响打印文件”，不增加嵌套卡片。

## 生命周期与竞态

- 现有 Vector parse/clip 几何缓存、GLB 和叠色 PNG 都属于 preview session，随 session 关闭清理。
- 最终 3MF 仍是独立 TTL 下载资产，关闭源 session 后继续可下载。
- 每次异步平滑 GLB 构建继续使用 session id + job token；现有 `generate_segmented_glb_filename()` 已经为每次调用附加 UUID，所以每个已注册 URL 对应不可变文件。本 PR 只补并发/清理回归，不重写已正确的命名机制。
- 覆面纹理只能选择通过当前身份守卫的 `previewBaseImageUrl`；切换图片或 session 时必须立即失效。
- 预览 GLB 尚未完成时点击生成，浏览器继续等待/显示轻量预览，不能回退打印精确 GLB。
- 最终 3MF 的 TTL 下载语义沿用现有独立 registry：关闭或切换源 session 后仍能下载；只有 preview GLB、几何缓存和叠色 PNG 随 session 失效。
- session 同时记录当前 renderer mode；设置切换启动的新 job 仍使用唯一物理路径，旧 job 完成后不能覆盖最后一次选择。

## 测试设计

### 后端

- 现有 parse/clip 几何缓存的受限加载器保留曲线轮廓、孔洞、独立部件和 bounds；
- 矢量 GLB 顶点不再锁定在预览像素网格上；
- 解析式挤出的面积误差在现有拓扑容差内，孔洞与组件数不变；
- 编辑后的颜色归类使用当前缓存，但 footprint 仍来自矢量描述；替色改变 `display RGB` 后 `height_key` 不变，开启浮雕时高度不跳色；
- 无效、过期、超限、外部 session 几何缓存安全降级且不串模型；
- parse-cache provenance 必须由当前 session 的 expected digest 验证，篡改 artifact 自带 key 不能通过；
- 异步 GLB 并发任务使用不同物理路径，旧 URL 内容不被改写，session 关闭可清理全部预览资产；
- 旧尺寸空间编辑在新尺寸 Vector 和 raster 生成中正确投影；覆盖放大、缩小、1600 px cap、自定义配方、追加层、虚拟材料和 material archive 动态层，未编辑区域等于当前尺寸 fresh analysis，缺失必需基线时失败关闭；
- raster、高保真、material archive 和模型覆面路由不误入错误构建器；
- 原生 Vector 生成和 3MF 相关既有测试保持通过。
- `enable_smooth_vector_preview=true` 选择解析式构建器，`false` 选择 legacy segmented 构建器；无效解析式输入在开启状态安全降级；session 内后续替色重建继承已选择模式。

### 前端

- 模型覆面在预览完成前使用原图，完成后切换 `previewBaseImageUrl`；
- 替色、配方和撤销/重做更新覆面纹理；
- 选区高亮变化不污染覆面纹理；
- session 切换/关闭后不显示旧纹理；
- batch replace、custom recipe、multi-select、gradient replace、`submitReplacePreview` 的旧 session 延迟响应都不能回写新 session 的纹理、GLB URL 或 loading 状态；
- 查看器对解析式 Vector 优先使用 `mesh.userData.height_key`；替色前后 Z 高度不变，同时旧 GLB 的 mesh-name fallback 与 batched `height_segments` 行为保持通过；
- 修改尺寸不调用 preview、不清空 session/GLB，并立即改变模型 scale；
- 钥匙扣、冰箱贴、描边和景泰蓝在缩放后仍正确贴合；单元测试直接断言世界坐标中的毫米尺寸、锚点与生成请求坐标一致，截图只作补充；
- raster 路径仍能实时缩放且不改变 GLB 来源；
- 大幅面仍按总尺寸更新分片布局，不被普通预览的尺寸例外误伤；
- Generate 期间始终保持 quick-preview 资产所有权。
- 设置开关默认开启并持久化；当前 Vector session 中切换只触发 GLB rebuild，保持 2D 预览、编辑历史和 session id，连续切换只提交最后一次 GLB；非 Vector session 不发 rebuild 请求。

生命周期回归还必须显式运行“关闭/切换源 session 后 3MF 下载仍成功”，并同时证明该 session 的 GLB URL 已失效、几何缓存和叠色 PNG 已清理。

所有非 watch 前端测试必须通过 `python scripts/run_vitest.py` 运行。

### R4C1 真人流程

使用已确认的 R4C1 SVG，分别验证：

1. 上传后等待预览完成，再生成；
2. 轻量 GLB 尚未完成时立即生成；
3. 先做区域替色/配方编辑，再修改尺寸并生成，确认无 409、无投影错位；
4. 开启浮雕、描边、景泰蓝、钥匙扣、冰箱贴、拼图和模型覆面逐项检查。

记录浏览器实际 URL、Content-Length/文件大小、GLB 顶点/面数、加载耗时、峰值内存和截图。普通 SVG 的曲线必须无像素台阶，颜色区域和透明孔洞完整；模型覆面必须显示叠色后的颜色。必要时用 Bambu Studio / OrcaSlicer 对比 3MF，确认对象、材料、拓扑和切片结果未变化。

## 验收标准

- R4C1 普通 SVG 3D 预览曲线平滑，且使用 session-bound 轻量预览资产；
- 轻量资产不大于当前约 20.51 MB 基线，并以明显减少网格量为优化目标；
- 模型覆面在颜色预览后显示真实叠色/替色结果，同时保留当前平滑度；
- 尺寸修改无预览请求、无 loading 闪烁、无 session 重建；
- 尺寸修改前的空间替色/配方编辑在生成时正确投影，不用旧像素密度冒充新尺寸分析；
- 所有创意功能仍在轻量预览上正确定位和更新，绝对毫米参数与生成请求一致；
- 平滑预览开关默认开启；关闭可回退旧 segmented Vector 预览，但不恢复任何竞态、覆面颜色或打印级 GLB 回退问题；
- 打印精确 GLB 不再成为浏览器回退来源；
- 3MF 内容、打印质量与下载生命周期无变化；
- 后端聚焦 pytest、前端 Vitest、smoke、日志质量检查和 R4C1 两种时序验证通过。

## 非目标

- 不修改 3MF writer、切片 coverage、独立壳体或打印拓扑；
- 不把 raster/位图轮廓伪装成矢量；
- 不为任意像素画笔边界新建自动矢量化系统；
- 不新建通用 artifact/display descriptor 平台；
- 不在本 PR 重写整个 Three.js 查看器；
- 不自动合并 PR。
