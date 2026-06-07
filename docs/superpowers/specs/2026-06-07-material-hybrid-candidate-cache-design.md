# 耗材混合候选缓存设计

## 目标

用一个有预算、有目标色精修能力的缓存构建模式，替代 Lumina 当前在大耗材数量下尝试扫描全部 `M ** N` 配方的耗材档案求解缓存路径。

新的策略是：

```text
小规模耗材/层数组合：继续使用精确穷举缓存
大规模耗材/层数组合：使用有限候选覆盖缓存 + 目标色反向精修
```

这个文档只描述设计和实际落地可行性，不直接授权开始实现。进入代码实现前，必须先按仓库规约把这项计划登记到在线 tracking spreadsheet，并单独评审 implementation plan。

## 当前证据

Lumina 当前的磁盘耗材求解缓存是明确的穷举缓存：

- `core/material_cache.py` 的模块说明写明：缓存通过枚举每个 `M**N` 有序层序列，再把结果压缩到 3D Lab 网格。
- `build_material_solver_cache()` 会先枚举 bottom/top 两半的 affine 表，再逐块组合，最终仍然产生每一个配方的最终颜色。
- `core/pipeline/p03_core_processing.py` 在没有持久缓存时，会现场构建一个临时 64-grid 缓存。降低 grid 只会减少最终保留的 bucket 数量，不会避免完整 `M**N` 扫描。

对于 22 个耗材：

```text
22 ** 8  = 54,875,873,536 个配方
22 ** 10 = 26,559,922,791,424 个配方
```

任何需要扫描这个空间的构建器，都不适合出现在交互式服务路径里。

## 非目标

- 本阶段不改变 Beer-Lambert 物理公式。
- 本阶段不改变 3MF 中的材料身份、槽位顺序、层图语义。
- 本阶段不重做前端耗材选择流程。
- 本阶段不移除现有 exact 和 bucketed 缓存文件的支持。
- 本阶段不强迫 LUT-backed predictive runtime 使用耗材档案缓存。
- 本阶段不直接引入 ChromaPrint3D 的包格式作为 Lumina material archive 的依赖。

## 物理模型基础

Lumina 当前的耗材模型已经具备更智能搜索所需的数学结构。

单层公式是：

```text
C_new = E + (C_prev - E) * exp(-k * t)
```

等价写法是：

```text
C_new = a_i * C_prev + b_i
a_i = exp(-k_i * t)
b_i = E_i * (1 - a_i)
```

多层组合后，整个配方仍然是一个 affine 变换：

```text
C_final = alpha_total * C0 + beta_total
```

如果把配方拆成 bottom prefix 和 top suffix：

```text
C_final = alpha_top * C_bottom + beta_top
```

给定目标线性 RGB `T` 和一个 top suffix，可以反推出它希望 bottom prefix 提供的颜色：

```text
C_bottom_required = (T - beta_top) / alpha_top
```

这就是关键点：大 palette 查找时，不需要把每个 top 和每个 bottom 全部配对。我们可以搜索一批可能有效的 top suffix，再用 bottom-prefix 索引去找接近 `C_bottom_required` 的 prefix，最后只对少量组合做正向模型验证。

## 推荐架构

### 总览

在 `MaterialSolverCache` 旁边新增一个运行时对象：

```text
MaterialCandidateRuntime
```

它必须提供和 `MaterialSolverCache.lookup()` 一致的查询接口：

```python
lookup(
    target_srgb: np.ndarray,
    user_materials: list[MaterialParams],
    *,
    hue_weight: float = 0.0,
    neighbor_coherence: float = 0.5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]
```

现有调用方继续拿到同样的返回值：

```text
matched_rgb: (C, 3) uint8
recipes_user_order: (C, N) int32
delta_e: (C,) float64
```

这个 duck-typed 兼容边界是控制风险的核心。预览、矢量匹配、局部重算、替换逻辑不应该知道内部到底来自 exact cache、bucketed cache，还是新的 hybrid candidate cache。

### 运行时选择

新增 resolver，而不是直接改旧函数语义：

```text
core.material_lut_provider.load_solver_runtime(...)
```

解析顺序：

1. 如果已有 exact 或 bucketed `MaterialSolverCache`，优先加载。
2. 如果当前组合满足 exact 阈值，仍然允许构建 exact 缓存。
3. 如果当前组合超过安全阈值，构建或加载 `MaterialCandidateRuntime`。
4. 只有当旧缓存加载和新的 bounded runtime 构建都失败时，才返回确定性的 4xx/409 类错误。

当前已有的 `load_solver_cache(...)` 应保持原 pass-through 语义，直到每个调用方被明确迁移。这样可以避免一次改动扩散到所有路径。

## 新模块

### `core/material_candidate_cache.py`

职责：

- 持有新的 runtime dataclass。
- 保存和加载 candidate cache 文件。
- 基于 `achieved_lab` 构建 KD-tree。
- 实现 `lookup()`，以及可选的 `lookup_top_k()`。
- 持有 metadata 和兼容现有诊断逻辑的属性。

建议公开类型：

```python
@dataclass(frozen=True)
class MaterialCandidateCacheConfig:
    candidate_budget: int
    candidate_pool_multiplier: int
    lab_grid_resolution: int
    seed: int
    max_build_seconds: float | None
    enable_inverse_refinement: bool
    max_refine_materials: int
    max_refine_top_suffixes: int
    max_refine_bottom_prefixes: int

@dataclass
class MaterialCandidateRuntime:
    candidate_recipes: np.ndarray
    achieved_srgb: np.ndarray
    achieved_lab: np.ndarray
    pinned_mask: np.ndarray
    metadata: dict[str, Any]

    def lookup(...): ...
```

必须提供的兼容属性：

```text
mode -> "candidate_hybrid"
layer_count
layer_height_mm
substrate
palette_hash
grid_resolution -> lab_grid_resolution
valid_cell_count -> candidate_recipes.shape[0]
metadata
```

### `core/material_candidate_sampling.py`

职责：

- 在不扫描 `M ** N` 的前提下生成有限候选配方。
- 固定 palette hash 和 config 时，输出必须确定。
- 提供纯函数，便于单元测试。

候选来源：

1. **固定保留的纯色配方**
   - 每个耗材一条 `[m, m, ..., m]`。
   - 作用是保证每种耗材的本色始终可查。

2. **双耗材 ramp 配方**
   - 对每个 `(a, b)` 组合生成多个层比例：
     - 全部 `a`
     - 全部 `b`
     - 顶层 1 层 `b`
     - 顶层 2 层 `b`
     - 底半 `a` / 顶半 `b`
     - `a/b` 交错
   - 当 `M` 很大时，用确定性排序截断 pair 数量。

3. **底色材料锚定配方**
   - 底部强制白色/base 材料，顶部放彩色材料。
   - 如果存在黑色/深色材料，只在下层组合中使用它，不默认假设一定有黑色。
   - base 材料通过现有 material archive 的 base-channel 推断逻辑获得，不能假设 index `0`。

4. **top-heavy 可见性配方**
   - 顶部 1 到 3 个可见层做更密集变化。
   - 原因是物理模型里 top suffix 的透射率通常更影响最终可见颜色。

5. **低差异随机覆盖**
   - 优先使用确定性的 Sobol 或类似低差异序列。
   - 如果环境里没有低差异生成器，退回 `np.random.default_rng(seed)`。
   - 配方按 batch 生成，并用 recipe bytes 去重。

6. **历史和测量 seed**
   - 如果能加载旧缓存，使用旧缓存中的 recipe 作为 seed。
   - 如果当前 session 有用户保存过的 recipe，作为 seed。
   - 如果未来有规范化测量校准 recipe 来源，也可接入为 seed。

### `core/material_candidate_selection.py`

职责：

- 把候选配方正向预测到 Lab。
- 在有限预算下保持尽量宽的颜色覆盖面。
- 选择最终候选行。

选择器必须是 streaming 的：

```text
生成 batch -> 正向预测 -> 转 Lab -> 更新每个 cell 的 reservoir -> 丢弃 batch
```

它不能把完整候选池长期放在内存里。

选择规则：

- 所有 pinned recipes 永远保留。
- 每个 Lab grid cell 只保留很小的 reservoir，例如 1 到 4 条候选。
- 如果 reservoir 总数超过最终预算，再在 cell representatives 上做近似 k-center / farthest-point 选择。
- 最终输出行数必须小于等于 `candidate_budget`。

建议默认预算：

```text
fast       65,536 candidates
balanced 262,144 candidates
quality  524,288 candidates
```

默认 preview fallback 是否使用 `balanced`，需要用真实服务主机测构建时间后决定。如果构建时间偏长，先默认 `fast`，再开启目标色反向精修补质量。

### `core/material_inverse_refinement.py`

职责：

- 针对当前图片实际出现的目标色改善匹配。
- 利用 affine 反推关系，而不是完整 top/bottom 笛卡尔积。
- 只接受经过最终正向模型验证的 recipe。

每批目标色的算法：

1. 先用 `MaterialCandidateRuntime` KD-tree 查询每个目标色的 top `K=64` baseline candidates。
2. 为目标色构造相关材料子集：
   - top candidates 中出现过的材料；
   - 目标色附近的 material identity colors；
   - 推断出的 base/white 材料；
   - 可选 black/dark 材料。
3. 限制材料子集大小：
   - 默认 `max_refine_materials = 8`；
   - 硬上限 `12`。
4. 在这个子集内枚举 bottom prefixes 和 top suffixes，但要受预算限制：
   - `max_refine_bottom_prefixes = 65,536`
   - `max_refine_top_suffixes = 32,768`
5. 为 bottom prefix colors 建 KD-tree。
6. 对每个 target 和 top suffix：
   - 计算 `C_bottom_required`；
   - 明显超出 `[0, 1]` 的 required color 直接拒绝；
   - 查询最近的 bottom prefixes；
   - 组合成完整 recipe。
7. 对所有组合候选用现有 `forward_model` 或 affine batch path 做正向预测。
8. 选 Lab ΔE 最小者，再套用现有 hue-aware 和 neighbor-coherence reranking 规则。

这个搜索是 target-aware 的：它只围绕当前图片出现的颜色花计算量，不围绕整个理论配方宇宙花计算量。

## 缓存文件格式

不要复用当前 `-gNNN.npz` 文件名表示 hybrid cache。使用独立 stem：

```text
<palette_hash>-N<count>-t<height>-<substrate>-hybrid-v2-b<budget>.npz
<palette_hash>-N<count>-t<height>-<substrate>-hybrid-v2-b<budget>.meta.json
```

必须保存的 `.npz` 数组：

```text
candidate_recipes   uint8/int16, shape (B, N)
achieved_srgb       uint8,       shape (B, 3)
achieved_lab        float32,     shape (B, 3)
pinned_mask         bool,        shape (B,)
```

当 material count <= 255 时，recipe 使用 `uint8`。只有未来允许超过 255 个材料时，才需要 `uint16`。recipe dtype 必须写入 metadata。

必须保存的 metadata：

```json
{
  "schema_version": "2.0",
  "mode": "candidate_hybrid",
  "palette_hash": "...",
  "canonical_materials": [],
  "layer_count": 10,
  "layer_height_mm": 0.08,
  "substrate": "white",
  "candidate_budget": 262144,
  "candidate_count": 262144,
  "candidate_pool_multiplier": 8,
  "lab_grid_resolution": 96,
  "seed": 123456,
  "generator_version": "material_candidate_sampling_v1",
  "selection_version": "lab_reservoir_kcenter_v1",
  "inverse_refinement": {
    "enabled": true,
    "max_refine_materials": 8,
    "max_refine_top_suffixes": 32768,
    "max_refine_bottom_prefixes": 65536
  },
  "total_combinations": 26559922791424,
  "scanned_combinations": 0,
  "generated_candidate_count": 2097152,
  "pinned_candidate_count": 500,
  "build_time_seconds": 0.0,
  "built_at": "..."
}
```

`scanned_combinations` 对 hybrid cache 必须是 `0`，因为它的设计目标就是不扫描理论全集。

## 现有调用方影响

### `core/pipeline/p03_core_processing.py`

当前行为：

- 加载持久缓存。
- 如果没有缓存，就构建临时 `build_material_solver_cache(... grid=64)`。

要求改动：

- 只替换 absent-cache fallback 为 `load_solver_runtime(...)`。
- 保留现有 `solver_meta` 中的 metadata keys。
- 允许增加可选 keys：
  - `runtime_mode`
  - `candidate_budget`
  - `inverse_refinement_enabled`
  - `generated_candidate_count`

不能改变：

- `matched_rgb_unique`
- `recipes_unique`
- `delta_e`
- `map_pixels_to_materials(...)`
- downstream pipeline stages 消费的 cache dictionary keys。

### `core/vector_matchers.py`

当前行为：

- 模仿 P03 cache fallback，并期望对象提供 `.lookup()`。

要求改动：

- 使用和 P03 相同的 provider 解析 runtime。
- `self._solver_cache` 可以暂时保留这个变量名；如果改名为 `self._solver_runtime`，必须同步更新测试。
- 保持 `solve_for_fills()` 输出 shape 和 layer order。

不能改变：

- vector fill quantization；
- solved fill colors 的 KD-tree；
- downstream vector branch metadata。

### `core/gradient_region_requantize.py`

当前行为：

- 只调用 `material_solver_cache.lookup()`。

要求改动：

- 类型注解可以改成 protocol，但行为不需要变。
- 不允许访问算法特定字段。

不能改变：

- local region K-Means；
- region mask handling；
- rewritten pixel counting。

### `core/pipeline/s03_color_replacement.py`

当前行为：

- 使用 `load_solver_cache(...)`，有 cache 时调用 `.lookup(...)`。

推荐阶段：

- 第一轮集成不要迁移这个路径。
- 等 `load_solver_runtime(...)` 稳定后，只切换 lookup path。
- 对单色 replacement，先保留当前 MITM fallback，直到 hybrid `lookup_top_k` 实现并验证。

### `api/routers/converter/replace.py`

当前行为：

- region re-quantize endpoint 要求存在持久化 `MaterialSolverCache`。

推荐阶段：

- 第一轮集成不要改变这个 endpoint，除非已经实现并验证 persisted hybrid runtime loader。
- 后续可以允许 exact/bucketed cache 或 hybrid candidate runtime。
- 当没有可复用 runtime 时，继续保持当前 409 行为。

### `api/routers/single_stage.py`

当前行为：

- `/material-solver-cache/build` 构建现有 exact/bucketed cache。
- `/status`、`/details`、`/suggest-colors`、`/delete` 假设现有 cache shape。

推荐阶段：

- 第一轮保持这些 endpoint 稳定。
- core runtime 证明可行后，再增加单独的 hybrid build/status endpoint：
  - `/material-solver-runtime/status`
  - `/material-solver-runtime/build`
- 不要把 `grid_resolution` 重载成 candidate budget。
- 新 response fields 只能追加，不能删除现有 required fields。

### `core/material_cache_visualization.py`

当前行为：

- 可视化 Lab-grid cache details。

推荐阶段：

- 暂时只支持 exact/bucketed。
- 第五阶段再增加 hybrid visualization，并清楚标注：这是 candidate coverage，不是 exhaustive grid coverage。

## 兼容性规则

1. 现有 exact 和 bucketed cache 文件必须继续可加载。
2. 除非调用方明确请求 hybrid，新实现不得改变 `build_material_solver_cache()` 的旧语义。
3. 现有 API endpoint 的 request schema 保持向后兼容。
4. hybrid lookup 返回的 material recipe layer order 必须和 `MaterialSolverCache.lookup()` 一致。
5. palette fingerprint 继续保持 canonical 和 order-independent。
6. hybrid cache key 必须包含 algorithm version 和 budget，避免不兼容 runtime 文件被静默复用。
7. 对不安全大 palette，hybrid fallback 绝不能调用会导致完整 `M ** N` 扫描的 `_enumerate_cumulative_affines()` 深度组合。
8. 如果 hybrid lookup 失败，用户收到确定、可操作的错误；不能暴露 raw traceback。
9. 第一轮 backend-only 阶段不需要前端状态迁移。
10. export 和 3MF generation 继续消费同样 shape 的 `material_matrix`。

## 精度策略

hybrid runtime 对大 palette 是近似算法。精度由以下因素控制：

- candidate budget；
- pinned recipe 覆盖；
- Lab-space k-center 覆盖；
- target-aware inverse refinement；
- 最终 exact forward-model verification。

质量门禁：

1. 对小 palette，只要 exhaustive brute force 可行，exact mode 仍然是真值来源。
2. 对小 palette 强制 hybrid mode 时，hybrid 返回 recipe 的 forward-predicted RGB 必须和它报告的 matched RGB 一致。
3. 对采样测试 palette，开启 refinement 的 hybrid mean ΔE 不能比关闭 refinement 更差。
4. 对代表性图片，hybrid preview 在成为大 palette 默认路径前，应满足约定阈值：
   - 相对小子集 exact baseline 的 mean ΔE <= 3.0，前提是 baseline 可计算；
   - 在安全 palette 上 forced hybrid 相对当前 exact/bucketed cache 的 p95 ΔE 回归 <= 1.0；
   - max ΔE 必须报告，不能隐藏，因为 out-of-gamut colors 的 max ΔE 可能合理偏高。

## 性能策略

### 构建内存

当 `candidate_budget = 262,144` 且 `N = 10`：

```text
candidate_recipes uint8  约 2.5 MB
achieved_srgb uint8      约 0.8 MB
achieved_lab float32     约 3.0 MB
pinned_mask bool         约 0.3 MB
KD-tree/runtime overhead 取决于实现，预计几十 MB
```

streaming build 可以评估多于最终预算的候选，例如 `budget * 8`，但必须按 bounded batches 评估。每个 batch 只短暂保存当前 recipe ids、linear RGB、sRGB、Lab 和 selection bookkeeping，然后释放。

### 查询内存

baseline lookup：

```text
target_count * top_k * 3 float32/float64
```

如果图片量化后有 256 个 unique colors，top-K 为 64，这个内存很小。

inverse refinement：

- 按 material subset 分组 targets；
- 每个 subset 复用 prefix/suffix tables；
- table size 独立受预算限制，而不是受理论 `S ** half_depth` 直接支配；
- final forward scoring 保持 chunked。

安全默认值：

```text
max_refine_materials = 8
max_refine_bottom_prefixes = 65,536
max_refine_top_suffixes = 32,768
refine_bottom_neighbors = 2
```

这些默认值避免 `12 ** 10` 级别的完整配对，同时保留质量提升空间。

## 错误处理

新的 domain errors 应放在 core 层，并在 API 边界映射：

```text
MaterialCandidateCacheError
MaterialCandidateCacheBuildBudgetError
MaterialCandidateRuntimeUnavailableError
MaterialInverseRefinementBudgetError
```

面向用户的错误信息应包含：

- material count；
- layer count；
- selected strategy；
- candidate budget；
- rejection 或 fallback 原因；
- 推荐操作。

`core/*` 里不能抛 `HTTPException`。

## 结构化日志

只增加少量聚焦事件，并控制 INFO 预算：

```text
material_candidate_cache_build_started   仅 explicit build endpoint 使用 DEBUG 或 INFO
material_candidate_cache_build_done      INFO
material_candidate_cache_build_failed    WARNING/ERROR
material_candidate_runtime_used          只在 preview path 的匹配策略发生实质变化时 INFO
material_inverse_refinement_done         默认 DEBUG
```

如果新增 mutating API endpoint，必须把 success event 注册进 logging governance tests。除非单独批准，不要扩展 default canonical workflow。

## 测试计划

### 单元测试

新增 `tests/test_material_candidate_cache_unit.py`：

- 固定 seed 时 candidate generation 确定；
- palette hash 变化会改变 seed/key；
- pinned uniform recipes 永远存在；
- candidate count 永远不超过 budget；
- unsafe 22-material palette 不调用 exhaustive builder；
- runtime `.lookup()` 返回和 `MaterialSolverCache.lookup()` 一致的 shape 和 dtype；
- lookup 会校验 palette fingerprint；
- save/load roundtrip 保留 arrays 和 metadata；
- corrupt hybrid cache 返回 `None` 或 domain error，不崩溃。

新增 `tests/test_material_inverse_refinement_unit.py`：

- affine inverse 对有效 top suffix 能算出 finite required bottom color；
- 明显超出容差的 required colors 会被拒绝；
- refinement candidate 被接受前必须经过 forward verification；
- 对同一个 target，refinement 不能比 baseline candidate 更差；
- prefix/suffix caps 被严格遵守。

只在共享 helper 需要断言时扩展 `tests/test_material_cache_unit.py`，不要把 hybrid 特定行为混进 legacy cache tests。

### Pipeline 测试

更新 material-archive P03 tests：

- 没有持久 cache 且 palette 不安全时，使用 hybrid runtime，而不是 `build_material_solver_cache`；
- 安全小 palette 仍然使用 exact/bucketed 路径；
- output cache 继续包含 `matched_rgb`、`material_matrix`、`color_layers`、`layer_height_mm`；
- layer order 符合现有 material matrix 预期。

更新 vector matcher tests：

- vector material matcher 接受 duck-typed hybrid runtime；
- solved fill cache 行为保持稳定。

region re-quantize tests 只在该 endpoint 迁移时更新。

### API 测试

第一轮 backend-only 阶段：

- 现有 `/material-solver-cache/*` tests 必须不改或最小改动后继续通过。

第五阶段 hybrid endpoint：

- status 能把 candidate runtime 和 legacy cache 分开报告；
- build 拒绝非法 candidate budgets；
- build 返回确定 metadata；
- delete 只删除请求 budget 对应的 hybrid runtime 文件。

### 回归门禁

实现合并前至少运行：

```bash
python -m pytest tests/test_material_cache_unit.py tests/test_material_solver_optimal_unit.py -v
python -m pytest tests/test_material_candidate_cache_unit.py tests/test_material_inverse_refinement_unit.py -v
python -m pytest tests/test_p03_material_archive_layer_order_unit.py tests/test_p03_material_archive_not_worse_fallback_unit.py -v
python -m pytest tests/test_vector_material_matcher_unit.py tests/test_gradient_region_requantize_unit.py -v
python -m pytest tests/test_converter_recipe_override_unit.py tests/test_converter_replace_layer_sync_unit.py -v
python scripts/log_quality_check.py --mode fast
```

如果包含 API logging 改动，还要运行：

```bash
python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v
```

第一轮 backend-only 阶段如果不改 UI 和翻译，不要求前端测试。如果 UI 暴露 candidate budget 或 strategy，必须补：

```bash
python scripts/run_vitest.py run
```

## 可行性评估

### 总体结论

可落地。算法风险中等，产品表面风险较低，前提是严格按阶段推进，并把兼容外壳作为边界。

### 为什么可落地

- 当前物理模型每层已经是 affine。
- Lumina 已经有 canonical palette fingerprint 和 order rebinding。
- 现有调用方大多只需要 `.lookup()` 输出，不关心 cache 内部实现。
- ChromaPrint3D 已经证明 bounded candidate package 可用于 runtime matching。
- 当前测试已经覆盖 exact/bucketed cache 契约，可以作为回归保护。

### 主要风险

1. **质量风险**
   - bounded candidate cache 可能漏掉 exhaustive search 能找到的颜色。
   - 缓解：pinned recipes、Lab coverage selection、target-aware inverse refinement、对 exact baseline 的质量门禁。

2. **layer-order 风险**
   - material matrix 和 solver recipes 对顺序非常敏感。
   - 缓解：严格复用 `MaterialSolverCache.lookup()` 契约，并增加 layer-order 回归测试。

3. **隐含调用方假设风险**
   - 有些代码读取 `.valid_cell_count`、`.metadata`、`.mode`、`.grid_resolution`。
   - 缓解：hybrid runtime 提供兼容属性和 metadata fields。

4. **可视化语义风险**
   - 现有 details views 假设 Lab-grid exhaustive/bucketed cells。
   - 缓解：hybrid cache 不接入现有 visualization，直到有明确的 candidate-coverage visualization。

5. **API 预期风险**
   - 当前 `/material-solver-cache/build` 的含义是 exhaustive/bucketed cache。
   - 缓解：保持 endpoint 不变，第五阶段新增独立 runtime endpoints。

6. **性能调参风险**
   - candidate budget 和 inverse refinement caps 需要实测。
   - 缓解：从保守默认值开始，增加结构化指标，分阶段/feature flag 推出。

### 设计本身不能保证的事情

不经过实现和回归测试，不能诚实地保证“绝对不影响任何地方”。可执行的保证应该是：

- 没有测试覆盖就不改变 public contract；
- 不删除现有 endpoint schema；
- 不改变 exact/bucketed cache 行为，除非明确要求；
- 不改变 3MF/export layer order；
- 合并前通过本文列出的所有回归门禁。

## 推出计划

### Phase 1：只实现 core runtime，不接生产路径

创建 hybrid candidate modules 和测试。暂时不从 P03、vector、API、frontend 调用。

退出条件：

- unit tests 通过；
- small palette forced hybrid mode 能工作；
- unsafe large palette build 受 candidate budget 限制。

### Phase 2：provider opt-in 集成

新增 `load_solver_runtime(...)`，通过内部参数或环境变量 opt-in。

退出条件：

- 旧 `load_solver_cache(...)` tests 不变且通过；
- P03 可以用 mocked hybrid runtime 测试，不改变默认行为。

### Phase 3：preview 和 vector fallback

只替换 P03 和 vector matcher 中“没有持久 cache”的 unsafe palette fallback。

退出条件：

- 安全小 palette 仍然使用 exact/bucketed cache；
- unsafe palette 不调用 exhaustive builder；
- preview 返回确定输出和 metadata。

### Phase 4：持久化 hybrid runtime

实现 hybrid cache 文件保存/加载，并跨 preview session 复用。

退出条件：

- roundtrip tests 通过；
- cache deletion 和 feedback bundle exclusion 正确处理 hybrid 文件；
- 文件名不和 legacy cache 冲突。

### Phase 5：API/UI 暴露

只有 backend 行为稳定后，才暴露 candidate budget 和 strategy。

退出条件：

- translations 更新；
- API schemas 更新；
- frontend settings persistence 更新；
- 如果新增 endpoint event，logging governance 更新。

## 回滚策略

回滚必须简单：

- 保持旧 exact/bucketed builder 不变。
- 保持 `load_solver_cache(...)` 不变。
- 生产路径只通过 `load_solver_runtime(...)` 选择 hybrid。
- 如果 hybrid 出现质量或稳定性问题，禁用 hybrid selection，回到当前 cache 行为和已有安全拒绝逻辑。
- hybrid 文件名独立，所以禁用 feature 不影响 legacy cache 文件。

## 验收标准

实现只有同时满足以下条件，才可以接受：

1. 22-material x 8-layer preview 不再尝试完整 `22 ** 8` 扫描。
2. 小 palette 的 exact cache 行为不变。
3. 已存在的 exact/bucketed cache 仍然可加载。
4. `material_matrix` shape 和 layer order 不变。
5. 3MF export、layer images、recipe override、region replacement、vector material archive tests 通过。
6. hybrid runtime 在 metadata 中明确说明自己是近似 runtime。
7. 固定 palette/config 时 hybrid lookup 确定。
8. hybrid candidate count 受 config 严格限制。
9. 实现提供清晰 feature flag 或 resolver switch，方便回滚。
10. 开始实现前，online tracking spreadsheet 已登记这项 planned change。
