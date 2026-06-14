# SVG 预览 GLB V2 设计说明

## 先说结论

这次要优化的是 **SVG 文件生成前端 3D 预览模型，也就是 GLB 预览模型的速度**。用户能感知到的目标是：上传或调整 SVG 后，右侧 3D 预览更快出来，同时现有前端预览功能不丢、不偏、不少。

结论分三点：

1. 这条路线可以增加速度，但前提是 V2 接在 **旧 mesh 生成之前**，不能只把 V1 已经生成好的 `trimesh` 再重新导出一次。
2. 兼容性的关键不是重写描边、拼图、钥匙扣、冰箱贴等规则，而是把这些规则的结果统一沉淀成一层 **SVG 预览描述层**，再让 V1 和 V2 exporter 都消费同一份描述。
3. 第一版不能默认全量替换 V1。应该本地通过 `LUMINA_VECTOR_GLB_KERNEL=v2` 开启灰度，V2 失败时整次回退 V1，人工测试稳定后再考虑默认启用。

换句话说，这个方案不是“另做一套 SVG 预览”。它是把现有业务规则保留住，只替换最慢的 3D mesh 生成器。

## 为什么现在会慢

当前 SVG 预览 GLB 的主要链路在：

- `core/vector_engine.py`：解析 SVG、裁剪遮挡、识别孔洞、匹配材料、生成 vector scene。
- `core/pipeline/vector_branch.py`：处理底板、描边、导出 3MF、导出 GLB、生成 2D 预览。
- `frontend/src/components/Scene3D.tsx` 和 `InteractiveModelViewer.tsx`：加载 GLB，并叠加描边、景泰蓝、拼图、钥匙扣、冰箱贴交互层。

慢点大概率不在“把文件写成 GLB”这一步本身，而是在 SVG 复杂轮廓被转换成 3D mesh 的过程：

1. SVG 里有大量 path、孔洞、重叠、透明区域。
2. 后端要按最终可见区域裁剪。
3. 后端要按材料槽、单双面、5 色扩展、底板、冰箱贴凹槽等规则分层。
4. 每一层都要从 2D 轮廓挤出成 3D 网格。
5. 旧路径主要依赖 Shapely / trimesh 做轮廓处理和挤出，复杂图形下会明显变慢。

之前位图 GLB V2 已经验证过 `rasterio + manifold3d` 这类更接近底层几何库的路径，在“按颜色轮廓生成 mesh”时可以比旧路径快。SVG 也有相同类型的重活，所以值得把 SVG 预览 GLB 接入 V2。

## 不能直接用普通 V2 的原因

不能把 SVG 预览 GLB 简单改成已有的 `matched_rgb + mask_solid` 分色 GLB。

这个捷径可能很快，但会绕过很多业务规则：

- SVG 的孔洞、遮挡和重叠绘制顺序。
- 用户区域改色、自定义配方、材料层编辑。
- 单面和双面的前后方向。
- 5 色扩展的 face-up 方向。
- 底板是否单独存在，或是否合并到某个材料槽。
- 冰箱贴凹槽这种底板盲孔几何。
- 后端 `Outline` 对象，以及它不能进入项目材料列表的规则。
- 前端依赖 `color_RRGGBB` 命名识别可换色 mesh。
- 前端依赖 `backing_plate` / backing mesh 判断底板。
- 拼图 overlay 依赖 GLB 的 `modelBounds` 定位。
- 钥匙扣、冰箱贴交互层依赖 GLB bounds 和 Z 高度。

所以普通 V2 只能作为低保真快速预览的候选方案，不能作为这次“完美兼容前端预览功能”的主方案。

## 设计目标

这次设计的目标是：

1. SVG 预览 GLB 生成速度变快。
2. V2 输出和 V1 在业务语义上等价。
3. 前端不需要因为 V2 大改。
4. V1 保留，并作为 V2 的整次 fallback。
5. 本地先启用 V2 做真实测试，PR 默认不强制线上启用。
6. 用 profile 数据判断是否真的变快，不凭感觉宣布成功。

这里的“兼容”不是只要模型能显示就行，而是必须覆盖前端预览里已经承载的业务能力。

## 必须兼容的前端能力

### 1. 描边

描边有两类相关逻辑：

- 后端 vector `Outline` mesh：用于导出对象级几何，且不能污染项目材料槽。
- 前端 `OutlineFrame3D`：根据模型边界和高度在 3D 预览里叠加外轮廓效果。

V2 必须保证：

- 如果 V1 会生成 `Outline`，V2 也必须生成或回退 V1。
- `Outline` 不能被命名成 `color_...`，否则前端会把它误认为可换色材料层。
- `Outline` 不能进入 project-level 材料列表。
- GLB 的 bounds 和高度不能变化，否则前端描边位置会偏。

### 2. 拼图

拼图 3D 预览不是只看 GLB 本身。前端会把拼图线作为 overlay 放到模型上方。

V2 必须保证：

- GLB 的 `modelBounds` 与 V1 对齐。
- 模型的 XY 尺寸、中心点、Z 顶面高度不漂移。
- 拼图 + 冰箱贴等互斥规则不改变。
- 常规拼图、异形拼图、不同网格和片数设置都能继续正确定位。

### 3. 钥匙扣

钥匙扣预览由前端 `KeychainRing3D` 叠加，它依赖模型 bounds、偏移、角度和 Z 高度。

V2 必须保证：

- 主 GLB 的 bounds 语义不变。
- 单面 / 双面 / 5 色扩展下模型朝向不变。
- 如果前端根据模型顶面放置钥匙扣，V2 不能让顶面高度变化。
- 钥匙扣与拼图、冰箱贴的禁用关系不变。

### 4. 冰箱贴

冰箱贴最危险，因为它不只是前端叠一个标记。后端 vector 路径会在底板里生成真实凹槽。

V2 必须保证：

- 底板仍然存在，且命名能被前端识别。
- 圆形和矩形磁铁凹槽位置、尺寸、深度不丢。
- 如果第一版 V2 不能无损生成凹槽，就必须整次回退 V1。
- 不能输出“彩色层是 V2、底板凹槽缺失”的半成品。

### 5. 景泰蓝和其他叠加预览

景泰蓝线、轮廓线、材料命名、颜色重映射都依赖模型拆分和命名契约。

V2 必须保证：

- 可换色 mesh 继续使用 `color_RRGGBB` 命名。
- 相同颜色的多个 mesh 继续追加 `_1`、`_2` 这类后缀。
- 非颜色辅助对象不进入可换色列表。
- 模型 bounds 和材料层 Z 范围与 V1 对齐。

## 核心设计：统一 SVG 预览描述层

推荐新增一层 **SVG 预览描述层**。它的作用是把“业务规则结果”和“mesh 生成方式”拆开。

现状可以理解成：

```text
SVG 业务规则 -> V1 直接生成 trimesh scene -> V1 GLB 导出
```

目标结构是：

```text
SVG 业务规则 -> SVG 预览描述层 -> V1 exporter
                          |
                          -> V2 exporter
```

这个描述层要表达的是：

- 这个部件是什么角色：颜色层、底板、描边、辅助对象。
- 它应该导出成什么名字。
- 它是什么颜色。
- 它是否允许前端换色。
- 它的 2D footprint / 高度 / Z 范围是什么。
- 必要时保留 V1 mesh 作为 fallback 或无损复制来源。

建议的数据结构可以类似：

```python
@dataclass(frozen=True)
class VectorPreviewPart:
    source_name: str
    export_name: str
    role: Literal["color", "backing", "outline", "auxiliary"]
    rgba: tuple[int, int, int, int]
    is_recolorable: bool
    z_min: float
    z_max: float
    footprint: BaseGeometry | None
    fallback_mesh: trimesh.Trimesh | None
```

注意这里的关键点是 `footprint` 和 `z_min/z_max`。如果只放 `fallback_mesh`，V2 就只能复制 V1 已经生成好的 mesh，速度提升会很有限。要提速，V2 必须尽量消费 2D footprint + 高度，然后用更快的 mesh kernel 挤出。

## 描述层应该从哪里来

描述层不能从原始 SVG 直接生成，因为原始 SVG 还没有包含完整业务结果。

它应该在这些业务处理之后生成：

1. SVG 解析和遮挡裁剪完成。
2. `matched_shapes` 已经包含最终可见区域。
3. 用户区域改色和配方覆盖已经写回。
4. 单双面、5 色扩展、材料层顺序已经确定。
5. 底板规则已经确定。
6. 冰箱贴参数已经转换成底板凹槽描述。
7. Outline 是否启用、宽度、Z 高度已经确定。
8. 前端需要的导出命名已经确定。

但它应该尽量在旧的 `trimesh` 挤出重活之前拿到 2D footprint。这样 V2 才能跳过旧 mesh 生成，产生实际速度提升。

因此实现时不能只在 `VectorProcessor.build_mesh()` 之后从 scene 反推描述层。那样兼容会容易，但提速空间不够。更合理的实施顺序是：

1. 先做一个保守描述层，保证能和 V1 完全对齐。
2. 再逐步把颜色层、底板、Outline 等可以表达为 2D footprint 的部件提前到 V2 生成。
3. 对暂时无法安全表达的复杂部件，整次 fallback V1。

## V1 和 V2 的分工

### V1 exporter

V1 exporter 保持现有行为，用作基准和 fallback：

- 接收 `VectorPreviewPart`。
- 如果 part 有 `fallback_mesh`，按当前方式复制 mesh、设置颜色、写入 GLB。
- 保持 `color_RRGGBB` 命名。
- 保持重复颜色后缀。
- 保持底板、Outline、辅助对象命名。
- 保持现有 warning 和跳过语义。

这一步是行为保持型重构，用来给 V2 建同一套输入和测试基准。

### V2 exporter

V2 exporter 负责提速：

- 对有 `footprint + z_min + z_max` 的 part，使用 V2 mesh kernel 生成挤出 mesh。
- 对颜色层、普通底板、普通 Outline 优先走 V2。
- 对冰箱贴凹槽、特殊辅助对象等复杂几何，只有确认能无损表达后才走 V2。
- 任一关键 part 失败，整次回退 V1。
- 不允许输出缺底板、缺凹槽、缺描边或 bounds 错误的半成品。

第一版建议 V2 只处理最有把握的部件。这样能先让常规 SVG 获得速度收益，同时复杂模式仍然安全回退。

## 能不能增加速度

可以，但要分清三种情况：

### 情况 A：只重构导出，不提前接 V2

如果只是把 V1 scene 整理成描述层，再由 V2 复制已有 `trimesh` 导出，那么速度提升很小。

原因是旧的重活已经完成了，V2 没有跳过慢步骤。

### 情况 B：颜色层和普通底板提前走 V2

这是第一版最值得做的目标。

常规 SVG 最耗时的通常是大量颜色区域的轮廓挤出。如果这些部件可以从 `matched_shapes` 的最终 footprint 直接交给 `rasterio + manifold3d` 生成 mesh，就有实际提速空间。

预期收益来自：

- 减少 Shapely / trimesh 挤出次数。
- 降低复杂轮廓三角化耗时。
- 减少 Python 层循环和对象构造。
- 对多颜色、多区域 SVG 更明显。

### 情况 C：复杂功能也逐步原生 V2

后续可以让 V2 支持更多复杂部件，比如：

- 冰箱贴凹槽底板。
- 更复杂的 Outline。
- 特殊辅助 mesh。
- 双面和 5 色扩展的更多特殊布局。

这会扩大 V2 覆盖率，减少 fallback 次数，整体速度才会稳定提升。

所以准确回答是：**这个方案能提速，但第一版必须把 V2 接到旧 mesh 生成之前；如果只做 scene 后处理，不能解决你关心的慢。**

## 开关和安全策略

新增 SVG 专用开关：

- 未设置 `LUMINA_VECTOR_GLB_KERNEL`：默认 V1。
- `LUMINA_VECTOR_GLB_KERNEL=v1`：强制 V1。
- `LUMINA_VECTOR_GLB_KERNEL=v2`：尝试 V2，失败回退 V1。

第一版 PR 不建议让所有环境默认 V2。我们本地 Docker 可以单独设置：

```text
LUMINA_VECTOR_GLB_KERNEL=v2
```

这样用户在线使用时，我们可以在本机真实测试 V2，但不会影响团队其他服务器。稳定后再决定是否把默认策略改成 `auto` 或 V2。

## 最小实现范围

第一版建议只改后端 SVG GLB 生成链路和测试，不改前端。

建议改动点：

1. `core/pipeline/vector_branch.py`
   - 提取当前 V1 GLB 导出 helper。
   - 增加 SVG GLB kernel resolver。
   - 增加 `VectorPreviewPart` 描述层。
   - 增加 V2 dispatcher 和整次 fallback。
   - 记录 V1/V2/fallback 的结构化日志。

2. `core/vector_engine.py`
   - 只在必要时暴露 V2 需要的 footprint、Z 范围、底板和凹槽描述。
   - 不重写 SVG 业务规则。

3. `tests/test_vector_glb_v2_kernel_unit.py`
   - 覆盖开关、描述层、V1 parity、V2 fallback、简单 V2 成功路径。

4. SVG parity 测试
   - 覆盖单面、双面、5 色扩展、底板、Outline、冰箱贴、拼图 bounds。

5. 本地 Docker 配置
   - 只给本地环境启用 `LUMINA_VECTOR_GLB_KERNEL=v2`。
   - 不改耗材数据 volume。
   - 不更新或覆盖用户材料库。

## 测试和验收

### 功能兼容测试

必须覆盖：

1. 普通单面 SVG。
2. 双面 SVG。
3. 5 色扩展 SVG。
4. 带孔洞 SVG。
5. 带重叠和遮挡 SVG。
6. 多个相同颜色区域。
7. 单独底板。
8. 合并底板。
9. Outline 开启。
10. 冰箱贴圆形凹槽。
11. 冰箱贴矩形凹槽。
12. 钥匙扣叠加。
13. 拼图常规模式。
14. 拼图异形模式。
15. 景泰蓝叠加。

### 前端契约测试

至少确认：

1. `color_RRGGBB` 仍被识别为可换色 mesh。
2. `backing_plate` 或底板 mesh 仍被识别为底板。
3. `Outline` 不被误认为颜色层。
4. `modelBounds` 和 V1 在容差内一致。
5. 拼图 overlay 位置不偏。
6. 钥匙扣位置不偏。
7. 冰箱贴代理和后端凹槽位置一致。

### 性能测试

必须用同一批真实 SVG 对比 V1 和 V2：

- `export_glb_s`
- `mesh_total_s`
- `vector_branch_total_s`
- GLB 文件大小
- mesh 数量
- face 数量
- vertex 数量
- V2 fallback 次数
- fallback 原因
- 前端实际加载时间

验收标准建议：

1. 常规复杂 SVG 的 `export_glb_s` 明显下降。
2. 总 preview/generate 耗时下降，而不是只优化某个小阶段。
3. V2 输出与 V1 的 mesh 名称、颜色数量、bounds 在容差内一致。
4. 复杂功能不支持 V2 时必须回退 V1，并且用户仍能看到正确预览。
5. 日志里 fallback 原因清楚，方便继续扩大 V2 覆盖率。

## 风险

### 风险 1：描述层位置太晚

如果描述层从 V1 已经生成好的 scene 里抽取，兼容容易，但提速有限。

规避方式：描述层必须支持 2D footprint + Z 范围，让 V2 能跳过旧 mesh 生成。

### 风险 2：为了速度绕过业务规则

如果 V2 直接读原始 SVG 或普通 preview cache，会丢描边、底板、冰箱贴、拼图 bounds 等规则。

规避方式：V2 只消费业务规则处理后的描述层，不重新解释原始 SVG。

### 风险 3：输出半成品

最危险的情况是 V2 输出了一个能加载但业务缺失的 GLB，例如颜色层有了，但冰箱贴凹槽没了。

规避方式：关键部件失败时整次 fallback V1，不允许局部成功。

### 风险 4：前端功能看似可用但位置偏

描边、拼图、钥匙扣、冰箱贴都可能因为 bounds 或 Z 高度轻微变化而位置偏。

规避方式：做 V1/V2 bounds parity 测试，并让用户用真实复杂 SVG 人工确认。

## 推荐实施顺序

1. 先写测试，把当前 V1 的 GLB 命名、颜色、bounds、底板、Outline 行为锁住。
2. 提取 V1 exporter，保证重构后输出不变。
3. 增加描述层，但先让 V1 消费它，确认兼容。
4. 增加 V2 开关和 fallback，不默认启用。
5. 让简单颜色层和普通底板走 V2。
6. 跑真实 SVG profile，对比 V1/V2 时间。
7. 本地 Docker 开启 `LUMINA_VECTOR_GLB_KERNEL=v2` 让你人工测试。
8. 根据 fallback 日志逐步补冰箱贴、Outline、复杂双面等能力。
9. 人工确认后再提 PR。
10. PR 合并后，本地保留 V2 开关和用户耗材数据。

## 当前建议

我建议采用 **统一 SVG 预览描述层 + V2 exporter + V1 整次 fallback**。

原因是：

- 它能保留现有 SVG 业务规则，不需要重写描边、拼图、钥匙扣、冰箱贴。
- 它能把真正慢的 mesh 生成逐步替换成 V2。
- 它允许第一版只覆盖最有把握的常规 SVG，复杂模式仍走 V1。
- 它能用同一套 parity 测试证明 V2 没有破坏前端预览契约。

需要特别明确：**只做“从 V1 scene 抽 descriptor 再导出”的版本不够，它主要是兼容性重构，不是性能优化。真正的性能优化必须让 V2 从业务处理后的 2D footprint 直接生成 mesh。**
