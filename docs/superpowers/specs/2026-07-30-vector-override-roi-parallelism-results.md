# Vector 区域覆盖 ROI 性能优化结果

> Deployment update (2026-10-06): Docker support and the public-test bypass
> are retired. This historical record preserves earlier implementation and
> validation evidence; use [Runtime support](../../runtime-support.md) for current behavior.
> 部署更新：Docker 支持及公网测试访问旁路已移除；本文保留历史实现与验证记录，当前运行方式以上述说明为准。

日期：2026-07-30
状态：`ready_for_draft_pr_with_tooling_caveat`。实现、独立 base 对照、
第二轮独立代码审核和最终功能门禁已完成；Smoke 包装器的后端与前端测试均
通过，但其自动 `pnpm install` 被仓库现有的 pnpm 构建脚本许可配置拦截，
因此包装器本身没有返回 0。用户已批准提交；主题分支已重放到最新
`origin/dev-refactor` 并包含一个本地提交，尚未 push、尚未创建 PR、未部署。

## 1. 当前结论

本轮找到了真实热点，并用减少无效工作而不是降低质量或盲目增加线程来解决。

- 真实复杂 SVG、200 mm、12 色耗材档案、10 层、`1600 × 2471`
  网格、2251 个 component：
  - 独立 base 的 4 个 fresh-process 总耗时中位数为 `64.681 s`，
    p90 为 `66.588 s`；
  - 最终 candidate 的 3 个 fresh-process 总耗时中位数为 `16.854 s`，
    p90 为 `19.479 s`；
  - 端到端中位数加速 `3.84×`，p90 加速 `3.42×`；
  - candidate 中一次完整产物校验为 `13.892 s`，对独立 base
    `64.837 s`，加速 `4.67×`；
  - 同一对照中，旧版覆盖空档约 `51.698 s`，candidate 的
    `matched_rgb_override_s` 为 `0.694 s`，约 `74.5×`；
  - 全画布等价工作量从 `8,899,553,600` 像素降到
    `22,157,263` ROI 像素，减少 `401.65×`。
- candidate 的 fresh-process peak RSS 中位数比 base 高 `8.44%`，
  p90 高 `8.28%`，均低于 `+15%` 硬门槛；相邻高内存压力对照中
  candidate 反而低 `1.96%`。
- 最终 candidate 的完整 semantic hash 与 detached base 都是
  `d6d2e13cbb447df36fd44ea488e40532d3443be671406fd7bc4c9f3c2e4c4ff6`。
- 8、12、15 色耗材档案的 matched-RGB、recipe-only、combined
  三条完整链路都与独立 base exact 相等。
- ROI component 线程实验比串行更慢，因此最终没有新增 ROI executor；
  推荐保留串行 ROI。现有 vector material solve 的统一并行策略没有被删除。
- 质量硬门没有使用采样、降分辨率、近似颜色、扩大公差或更改
  3MF/GLB 输出语义。

仍需准确限定结论：

1. 用户提供的 SVG 与生产日志中的复杂度接近，但不是日志中
   142 mm / 5220 components、200 mm / 3109 components 或
   164 mm / 896 components 的原始文件；“同一生产原图复测”仍是
   `incomplete`。
2. 第一次让两个同名任务在同一秒启动时，碰到了既有的秒级输出文件名冲突。
   将任务错开 2 秒后，两个真正重叠执行的任务都通过 exact gate。
   该问题不由本轮算法改动引入，但属于需要单独修复的
   `regression_risk`，本轮没有扩展修改导出命名规则。
3. API 的五段 timing 当前覆盖成功响应；worker 抛错或超时仍走现有异常路径，
   不会返回完整五段 timing。

## 2. Base、分支和改动范围

- 实现和性能 reference base：
  `8d26399bafca05f2a34059d66ea0eb42495645b5`
- 测试时建立独立 detached base worktree 到上述 SHA，不加载 candidate
  的 `core/`；全部 base artifact 生成后已移除该临时 worktree。
- 分支：`MOVIBALE/feat/vector-override-roi-parallelism`
- 当前 PR base：`origin/dev-refactor@2ce7b6c90e8c6c7ea1733b0b7df86478c141117f`
- 当前主题分支：已将本轮单一提交无冲突重放到上述 base，提交后门禁见第
  11 节。

改动文件：

- `core/vector_engine.py`
- `core/pipeline/vector_branch.py`
- `api/worker_pool.py`
- `api/routers/converter/preview.py`
- `api/routers/converter/generate.py`
- `api/schemas/responses.py`
- `scripts/log_quality_check.py`
- `scripts/profile_converter_multicore.py`
- `tests/test_vector_matched_rgb_overrides_unit.py`
- `tests/test_converter_multicore_profile_unit.py`
- `tests/test_worker_pool_unit.py`
- `tests/test_converter_preview_unit.py`
- `tests/test_converter_generate_unit.py`
- `tests/test_performance_timing_response_unit.py`
- `tests/test_log_quality_check_unit.py`
- `docs/superpowers/plans/2026-07-30-vector-override-roi-parallelism.md`
- 本结果文档

没有修改前端业务代码、耗材档案、用户设置、输出格式、V1/V2 fallback、
服务器、Docker 或生产环境变量。

## 3. 日志热点与根因

内部测试服务器日志显示：

- 31 个包含 matched-RGB override 的任务，旧计时空档合计
  `604.804 s`，p50 `12.691 s`、p90 `46.139 s`、max `94.735 s`；
- 9 个不含 override 的任务，同一空档合计只有 `0.114 s`；
- 该空档约占 40 个 vector generate 总 wall time 的 `59.3%`。

旧实现对每个 polygon component 都会：

1. 分配一张完整 `H × W` mask；
2. 在完整画布绘制 exterior 和 holes；
3. 再扫描完整 matched RGB、identity RGB 和 material matrix；
4. 做颜色与配方多数投票。

例如 `1600 × 2401 × 3109 components` 接近 119 亿像素级工作量。
绝大多数像素与当前小 component 无关。直接加线程会放大内存分配和带宽争用，
不会消除根因。

## 4. 最终实现

### 4.1 精确 ROI 栅格化

每个 component 仍沿用 base 的：

- 相同坐标缩放；
- 相同 `astype(np.int32)` 截断；
- 相同 OpenCV `fillPoly`；
- 相同先填 exterior、再清 holes 的顺序。

唯一变化是临时工作区：从同一批整数点求包围盒，保守扩一像素并裁到画布，
把点平移到局部 ROI，只在该 ROI 中切片、绘制和投票。

完全在画布外、负坐标、贴边、亚像素、holes、MultiPolygon、
GeometryCollection、一像素 ROI 和接近整画布的 component 均走相同规则。

### 4.2 精确颜色和耗材配方投票

保留的优化：

- RGB 使用无损 `uint32` code；数值排序与旧版
  `np.unique(...); np.argmax(counts)` 的平票规则一致；
- 相同 exact RGB 的 Lab/KDTree 查询只在本次函数调用内缓存；
- material stack 在编码空间能完整放进 `uint64` 时，每个有效像素只保留
  一个无碰撞 mixed-radix code，再由 NumPy `unique` 统计；
- 编码空间溢出时精确回退旧版 `np.unique(axis=0)`；
- 旧版会先把配方行转成 `int32`。candidate 对 `int64`/`uint64`
  也先复现这个转换，包括超出 `int32` 范围时的 wrap 语义；
- 只有在转为 `int32` 数值完全不变时才保留紧凑 dtype。

这保证了多数票、lexicographic tie-break 和历史宽整数行为不变。

### 4.3 降低生命周期峰值

- generate 加载四个 preview-cache `.npy` 时使用只读 `mmap_mode="r"`；
- 完成 override 投影后立即释放这些大数组；
- mesh 构建后立即释放只用于构建的参数字典；
- 不需要 2D preview 时，在 3MF/GLB 导出前释放完整 SVG analysis 和
  processor，只保留 GLB 定位所需的两个标量/小字段；
- 需要 2D preview 时仍保留完整 analysis，行为不变。

弱引用回归测试证明，Python/mmap 引用在 build mesh 前、完整 analysis 引用
在导出前已经消失，避免这些对象的生命周期重叠。这不等同于声称操作系统会在
同一时刻立即回收 page cache 或让 RSS 同步下降。

### 4.4 可观测性和 Worker API

现有 `vector_generate_timings` 增加：

- `matched_rgb_override_s`
- `recipe_override_s`
- `build_mesh_s`

并保留 `analyze_svg_s`、`mesh_total_s`、`export_3mf_s`、
`export_glb_s` 和 `vector_branch_total_s`。

API 成功响应增加：

- `endpoint_to_enqueue_ms`
- `queue_wait_ms`
- `worker_execution_ms`
- `result_delivery_ms`
- `endpoint_post_worker_ms`

普通 `WorkerPool.submit()` 的返回值完全不变；需要计时的 preview/generate
明确调用新 `submit_timed()`，避免把内部字段塞进任意业务字典。
这些字段已声明在 Pydantic response schema 中，不会在序列化时丢失。
没有新增 INFO 事件；worker timing 仅复用现有日志并增加 DEBUG 记录。

Profiler 额外记录：

- `rss_at_start_mb`
- `peak_rss_mb`
- `peak_rss_increase_mb`
- requested/effective parallelism
- thread/child-process peak
- full-canvas/ROI/effective pixel work
- semantic snapshot 和 external base gate

## 5. 质量证据的独立性

本轮没有让 candidate 与自己比较。

### 5.1 Detached base 产物

实际 base SHA 在独立 worktree 中执行。candidate 的完整 semantic snapshot
通过 `--reference-report <detached-base-profile.json>` 比较。该 snapshot 覆盖：

- `matched_rgb`
- `height_identity_rgb`
- `material_matrix`
- `mask_solid`
- slot names/order
- 规范化 world-space mesh triangles、bounds、area、volume、
  watertightness、Euler number、degenerate-face count
- face/vertex color、UV、texture/material factor
- scene nodes、instances 和 transforms
- GLB 文件内容
- 解压后的 3MF members；仅规范化 `source_file` 这一运行时文件名字段

完整 snapshot 不包含 Python `matched_shapes` 记录，因此不能用一个 hash
声称它覆盖 shape record。shape record 由下面的独立测试单独锁定。

### 5.2 独立 shape-record golden

测试内保留一份从 base SHA `8d26399b` 复制的 legacy full-canvas rasterizer，
它不调用 candidate ROI helper。七个独立几何案例的 base golden：

- holes
- MultiPolygon
- GeometryCollection
- canvas clipping
- subpixel
- fully outside
- one pixel

预期 changed counts 为 `[1, 2, 2, 2, 1, 0, 1]`，并分别比较完整规范化
shape record 的固定 SHA-256。另有 64 个 seeded polygon × 3 组
canvas/scale，逐像素重建完整 mask 后与 legacy oracle exact 比较。

### 5.3 语义边界

单元测试还覆盖：

- RGB tie 和 material-row lexicographic tie；
- `int8/int16/int32/int64/uint64` 及超范围旧版 int32 转换；
- radix overflow 的精确 fallback；
- height identity 与 `original_recipe`；
- component 状态一致时保留 compound geometry；
- 状态不一致时按稳定 source/component 顺序拆分；
- shallow-copy metadata 和 changed count；
- no-op、global replacement、regional replacement；
- strict dtype/shape/grid mismatch；
- required cache 投影异常会中止导出；
- 4/5/6/8-color 单元路径、8/12/15 色完整工作流；
- V1 fallback、V2 GLB、large-format 和既有导出测试。

## 6. 200 mm / 12 色独立性能对照

输入：

- `mmexport1784271438721.svg`
- SHA-256：
  `88f9a92690e765e48533b344ff1b313cf2168d7952ecb96253e036fb54a07788`
- 目标宽度：200 mm
- 网格：`1600 × 2471`
- 耗材：12 色，10 层
- component：2251
- rewritten component：1087

机器：Apple M5，原生 arm64，10 个可见 CPU，16 GiB 内存，
Python 3.12.13。NumPy/OpenCV/Shapely/SciPy/Trimesh/psutil 分别为
2.4.6 / 5.0.0 / 2.1.2 / 1.18.0 / 4.12.2 / 7.2.2。
BLAS/OpenMP 线程均固定为 1。机器已有较高 encrypted swap，因此每次复杂
对照使用新 Python 进程，并同时报告中位数、p90 和相邻压力对照。

### 6.1 Fresh-process 分布

| 模式 | n | total median | total p90 | RSS median | RSS p90 | RSS max | threads | children |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| detached base | 4 | 64.681 s | 66.588 s | 1350.19 MiB | 1379.54 MiB | 1390.33 MiB | 11 | 0 |
| final candidate | 3 | 16.854 s | 19.479 s | 1464.11 MiB | 1493.80 MiB | 1501.22 MiB | 11 | 0 |
| candidate 相对 base | - | `3.84×` | `3.42×` | `+8.44%` | `+8.28%` | `+7.98%` | 不变 | 不变 |

最接近的高内存压力相邻对照：

| 模式 | total | RSS start | RSS peak | RSS increase |
|---|---:|---:|---:|---:|
| detached base | 67.338 s | 936.25 MiB | 1346.02 MiB | 409.77 MiB |
| final candidate | 16.854 s | 936.06 MiB | 1319.61 MiB | 383.55 MiB |

该对照中端到端加速 `4.00×`，candidate peak RSS 低 `1.96%`。

### 6.2 完整 exact 对照

| 模式 | total | override | build mesh | 3MF | GLB | peak RSS | exact |
|---|---:|---:|---:|---:|---:|---:|---|
| detached base | 64.837 s | 约 51.698 s（由旧 aggregate 反推） | 7.258 s | 1.410 s | 1.894 s | 1267.27 MiB | reference |
| final candidate | 13.892 s | 0.694 s | 7.220 s | 1.409 s | 1.918 s | 1501.22 MiB | PASS |

两边 semantic hash 完全相等。candidate 的 build/3MF/GLB 耗时和内容都没有
通过降质缩短；主要收益只发生在旧版全画布覆盖空档。

### 6.3 最终代码的 1 cold + 3 warm 压力运行

在第二轮审核进程同时读取/跑测试、整机 swap 压力较高时，最终代码又在同一
Python 进程内运行 4 次 timing-only。质量由上一节独立 exact gate 锁定。

| run | total | override | RSS start | RSS peak | RSS increase |
|---|---:|---:|---:|---:|---:|
| cold | 27.052 s | 1.318 s | 893.36 MiB | 1279.31 MiB | 385.95 MiB |
| warm 1 | 28.465 s | 1.356 s | 1216.41 MiB | 1485.62 MiB | 269.22 MiB |
| warm 2 | 33.002 s | 2.492 s | 864.14 MiB | 1347.59 MiB | 483.45 MiB |
| warm 3 | 39.626 s | 2.035 s | 1078.52 MiB | 1308.98 MiB | 230.47 MiB |

warm median 为 `33.002 s`、p90 为 `38.301 s`；即使在这组持续恶化的
高压力运行里，相对 fresh base 中位数仍约 `1.96×`，相对 base p90 仍约
`1.74×`。这组数据只说明最终代码在 retained allocator/swap 压力下仍有界，
不能替代同负载、同进程的 base warm A/B；独立 base 没有保留同进程
1 cold + 3 warm，因此该项证据仍标为 `partial`。

### 6.4 1 / 2 / 4 / 8 选择实验

下表用于决定是否保留新的 ROI component 线程；它早于最后一次
analysis-lifetime 内存清理，因此只作为并行策略选择证据，不作为最终质量 oracle。
完整质量结论以上述 detached-base exact gate 为准。

| 请求/有效 worker | total | override | 平均 CPU | peak RSS | threads | children |
|---|---:|---:|---:|---:|---:|---:|
| 1 / 1 | 13.520 s | 0.648 s | 98.78% | 1136.6 MiB | 11 | 0 |
| 2 / 2 | 14.293 s | 0.685 s | 101.38% | 1241.7 MiB | 11 | 0 |
| 4 / 4 | 13.731 s | 0.736 s | 103.39% | 1305.0 MiB | 13 | 0 |
| 8 / 4（现有策略封顶） | 13.899 s | 0.706 s | 103.34% | 1223.1 MiB | 13 | 0 |

2/4/8 没有比 1 稳定更快，且 RSS/线程数更高。因此没有采用 component
executor，也没有为了 CPU 图表保留负收益代码。

## 7. 8、12、15 色耗材档案

输入为 `945695877_20260622_232544_vector.svg`，40 mm。
每个 candidate 都对 detached base 的完整 snapshot。

下表是最终生命周期清理前的同机受控 A/B。ROI、颜色投票和耗材投票算法与
最终代码相同，用来说明性能方向；最终代码的质量新鲜度由下一张表单独确认。

| 场景 | 颜色数 | base total | earlier candidate total | e2e 加速 | base RSS | earlier candidate RSS | exact hash |
|---|---:|---:|---:|---:|---:|---:|---|
| matched-RGB | 8 | 2.679 s | 2.099 s | 1.28× | 818.42 MiB | 802.72 MiB | `d1b9cf8e…c7cf8` |
| recipe-only | 12 | 3.618 s | 3.029 s | 1.19× | 812.22 MiB | 824.03 MiB | `639e11f9…59083` |
| matched + recipe | 15 | 3.579 s | 3.108 s | 1.15× | 836.45 MiB | 823.31 MiB | `ca362329…f878` |

第二轮审核后，最终工作树又在新的 Python 进程中重跑三种场景：

| 场景 | 颜色数 | final-current total | peak RSS | matched override | recipe override | detached-base exact |
|---|---:|---:|---:|---:|---:|---|
| matched-RGB | 8 | 3.840 s | 786.77 MiB | 0.150 s | 0.000 s | PASS |
| recipe-only | 12 | 4.894 s | 758.06 MiB | 0.117 s | 0.076 s | PASS |
| matched + recipe | 15 | 6.014 s | 790.69 MiB | 0.183 s | 0.111 s | PASS |

这组最终代码运行时整机仍处于高 swap 压力，且没有同压力、相邻执行的 base，
因此不用它反推性能回退或加速；它只作为“最终工作树仍与独立 base 完全相等”
的新鲜质量证据。三行 external reference 均为 PASS。recipe-only fixture
仍会执行一次 matched-RGB cache projection，以模拟真实 generate。

## 8. No-override 控制

### 8.1 小任务

同一 40 mm、8 色 SVG，不准备任何 override：

| 指标 | base | candidate | 变化 |
|---|---:|---:|---:|
| cold | 3.344 s | 3.354 s | +0.30% |
| warm median | 1.488 s | 1.543 s | +3.72% |
| p90 | 1.504 s | 1.612 s | +7.14% |
| fresh cold RSS | 664.9 MiB | 665.2 MiB | +0.04% |

小任务低于 `+10%` 门槛。base 的旧 profiler 对一种无 UV 的纯色
PBR material 不能生成完整视觉 snapshot，因此该控制只用于 timing，
不能冒充 artifact parity。

### 8.2 13,496-shape 大任务

输入 `梵高星空款式西森猫猫.svg`，SHA-256
`ba6d44586c4c9903091ade81ed331c09308ec6a6f684c72f1b8cc15aad42f717`，
136 mm、8 色、无 override，base/candidate 各 1 cold + 3 warm：

| 指标 | base | candidate | 变化 |
|---|---:|---:|---:|
| cold | 99.887 s | 99.045 s | -0.84% |
| warm median | 83.680 s | 86.509 s | +3.38% |
| p90 | 84.195 s | 88.481 s | +5.09% |
| warm median peak RSS | 4169.95 MiB | 4181.23 MiB | +0.27% |
| p90 peak RSS | 4292.95 MiB | 4417.75 MiB | +2.91% |
| max peak RSS | 4323.70 MiB | 4476.88 MiB | +3.54% |

这也是 timing-only 控制。所有回退都低于时间 `+10%`、RSS `+15%` 门槛。

## 9. 两个并发 outer task

两个 200 mm、12 色任务在生成阶段真正重叠，并各自对同一个 detached-base
semantic reference：

| 任务 | total | override | CPU | peak RSS | threads | children | exact |
|---|---:|---:|---:|---:|---:|---:|---|
| A | 33.133 s | 1.666 s | 90.25% | 1128.55 MiB | 11 | 0 | PASS |
| B | 27.057 s | 1.636 s | 99.23% | 1248.98 MiB | 11 | 0 | PASS |

- 两任务 peak RSS 简单相加约 `2.32 GiB`；
- 没有 child process、嵌套 ROI executor、OOM 或残留 profiler 进程；
- 两个 hash 都是
  `d6d2e13cbb447df36fd44ea488e40532d3443be671406fd7bc4c9f3c2e4c4ff6`。

第一次完全同秒启动时，一个任务成功，另一个在 3MF `.tmp` rename 处失败。
原因是现有导出文件名只有秒级精度，并非 ROI/投票/线程导致。错开 2 秒后，
两任务仍有约 9 秒 generate 重叠且均成功。该命名碰撞应单独修复并补
same-name/same-second 并发测试，不能把错开启动写成它已经不存在。

## 10. 采用与排除的实验

### 采用

1. 串行精确 ROI：像素工作量减少 `401.65×`。
2. exact `uint32` RGB code 和单次调用 KD 查询缓存。
3. 每有效像素一个 exact `uint64` material code；溢出时走旧版二维
   `np.unique`。
4. 保留旧版 int32 coercion 语义。
5. 只读 mmap、及时释放 cache/analysis。
6. stage timing、API queue/worker timing 和 profiler RSS 起点/增量。

### 排除

| 实验 | 证据 | 决定 |
|---|---|---|
| ROI component threads 1/2/4/8 | 2/4/8 均慢于串行；该早期 ad-hoc 微基准没有保留标准 profiler artifact | worker 越多越慢，删除 |
| 2/4/8 完整工作流 | total 均未稳定优于 1 | 不新增 executor |
| searchsorted/bincount RGB vote | 早期 ad-hoc 微基准慢于保留方案，未保留标准 artifact | 删除，不把精确百分比写成可复现结论 |
| Python dict 分块聚合 material code | 在 2251 components 上会长期保留数百 MiB | 删除，改为单次 NumPy unique |
| 整个 `N × layers` 强制 int32 临时矩阵 | 增加大对象与 allocator 压力 | 改为每像素一个 uint64 code |
| 普通 hash / 采样 / 近似直方图 | 可能碰撞或改变多数票 | 禁止 |
| process fallback | ROI 后没有值得承担 spawn/IPC/RSS 的 Python 热点 | 不实现 |

## 11. 最终验证状态

| 门禁 | 结果 |
|---|---|
| 第二轮独立代码审核 | 无 Critical；首轮 Important 均已解决；审核要求的新鲜 8/12/15 色 final-current exact 复测已补齐 |
| 直接相关 vector/profile/worker/API/schema/fast-gate 回归 | `377 passed, 1 skipped` |
| Prompt 指定的 vector/large-format/parallelism/export/V2 GLB 门禁 | `207 passed, 1 skipped` |
| logging exception governance / structured logging / logger | `21 passed` |
| `scripts/log_quality_check.py --mode fast` | PASS；14 INFO、0 WARNING、0 ERROR |
| Smoke 后端 | `131 passed` |
| Smoke 前端 | `10 files / 140 tests passed` |
| 直接 ESLint | 返回 0；0 error、60 个仓库既有 warning |
| `git diff --check` | PASS |
| UTF-8/mojibake 扫描 | PASS |
| profiler/pytest/backend/frontend 残留进程 | 未发现 |
| 补丁套用最新 `origin/dev-refactor@2ce7b6c9` | 无冲突；相关 `377 passed, 1 skipped`；Prompt 门禁 `207 passed, 1 skipped`；logging `21 passed`；fast log gate PASS |

唯一工具链例外：`scripts/run_smoke_tests.py` 的第三步调用 `pnpm lint` 时，
Codex 的 pnpm 包装器先尝试重建 `node_modules`。pnpm 10.33.2 已不再读取
`frontend/package.json` 中的 `pnpm.onlyBuiltDependencies`，随后因
`esbuild@0.25.12` 的 build script 未获许可而退出 1。该脚本在退出前已经
跑完并通过 131 项后端 Smoke 与 140 项前端 Smoke；使用同一
`node_modules` 直接执行 ESLint 返回 0。该限制来自当前 base 的依赖配置，
本 PR 不扩展修改前端供应链配置。

上述 skip 是“helper 已存在后自动退出”的旧红灯 reproducer，不是功能路径
被跳过。

### 11.1 全新依赖环境

另建 `/private/tmp` 下的全新 arm64 Python 3.12.13 venv，没有复用仓库
`.venv` 的任何 site-packages。

首先仅安装 `requirements.txt`。安装和 `pip check` 都成功，但 Prompt
指定门禁中的 8 个 V2 GLB 用例因缺少 `rasterio` 失败。继续核对后确认这不是
发布清单遗漏：仓库刻意把 V2 原生依赖放在
`requirements-glb-v2.txt`，而 Dockerfile 会同时安装两份清单；现有
`test_local_docker_deploy_contract_unit.py` 也明确锁定这一拆分。

随后按正式 V2/Docker 依赖合同执行：

```text
python -m pip install -r requirements.txt
python -m pip install -r requirements-glb-v2.txt
python -m pip check
```

结果：

- 两次安装均返回 0；
- `pip check`：`No broken requirements found`；
- `rasterio 1.5.0`、`manifold3d 3.5.2`、`psutil 7.2.2` 均来自新 venv；
- Prompt 指定的 7 个 quality test 文件加 Docker 依赖合同：
  `216 passed, 1 skipped`；
- 同一新 venv 完整运行 8 色 matched-RGB：
  `2.143 s`、peak RSS `805.30 MiB`、detached-base exact PASS；
- 同一新 venv 完整运行 15 色 combined：
  `2.867 s`、peak RSS `798.48 MiB`、detached-base exact PASS。

两条完整运行都实际导出 V2 GLB 和 3MF，并比较完整 external semantic
reference；因此干净环境证据不只是 import smoke。完成后已移除临时 venv。

### 11.2 最新远端集成验证

最终审核时 `origin/dev-refactor` 已前进到 `2ce7b6c9`。为了不在包含未提交
实现的工作树上执行破坏性 rebase，本轮建立 detached 临时 worktree：

1. 对当前 tracked patch 执行 `git apply --check`：PASS；
2. 实际套用 patch：无冲突；
3. 补齐最新 base 新增但旧 `.venv` 尚未安装的临时
   `cryptography 45.0.7` 依赖；
4. 相关测试：`377 passed, 1 skipped`；
5. Prompt 指定质量门：`207 passed, 1 skipped`；
6. logging governance：`21 passed`；
7. `log_quality_check.py --mode fast`：PASS，14 INFO、0 WARNING、0 ERROR；
8. 8 色完整 matched-RGB generate：`2.096 s`、peak RSS
   `755.67 MiB`，对原 detached-base semantic reference exact PASS。

该临时 worktree 只用于兼容性验证，复用旧工作树 `.venv` 并通过临时
`PYTHONPATH` 补齐最新依赖；它不是上一节的干净依赖证据。验证结束后已移除
worktree 和临时依赖目录。

## 12. 剩余热点与已知风险

1. ROI 后代表性任务的 `build_mesh_s` 约 `7.22 s`，其中
   `extrude_bottom_s` 约 `6.19 s`，成为下一热点。它涉及三角化、holes、
   winding、Z 和 material assignment，应作为独立 PR。
2. vector preview 的 parse/occlusion 在生产日志中可达
   `27.031 s` / `12.476 s`，也应独立 profile。
3. 两个 470/342 秒 preview 极端值仍不能从历史日志区分排队与执行。
   本轮补齐成功路径字段；需要 canary 后采集真实 queue wait。
4. 同名任务秒级输出路径冲突是已确认的既有并发风险，必须单独修复。
5. 本机已有较高 swap；绝对 tail latency 需在干净重启环境和 Ubuntu
   canary 再确认。当前相同机器的 fresh-process 相对门槛已通过。
6. 未取得生产日志对应原始 SVG，不能把本地绝对耗时写成服务器复测。

## 13. 推荐并行度

本轮 matched-RGB ROI 阶段推荐串行。不要新增 ROI component executor。

`LUMINA_VECTOR_PARALLELISM` 同时控制已有 material solve/mesh 策略，
不能只根据 Mac 的 ROI 结果直接修改 Ubuntu。canary 应先保持当前服务器配置；
若比较 `1` 与现状，必须使用相同输入、相同外层并发，并同时看端到端
p50/p90、RSS、queue wait 和 exact hash。

## 14. Canary 与回滚建议

仅在用户审核、提交、PR 合并后，服务器维护任务才可以：

1. 用明确 commit SHA 构建独立 canary image；
2. 不改耗材、DDNS、代理、持久化数据或现有并行环境变量；
3. 只导入小比例 vector generate 流量；
4. 观察 `matched_rgb_override_s`、`build_mesh_s`、`queue_wait_ms`、
   `worker_execution_ms`、generate p50/p90、RSS/OOM、5xx、
   `vector_overrides_grid_mismatch`；
5. 用同一原始 SVG 做 old/new image 串行 exact 对照和 3MF/GLB 人工验收；
6. 若出现质量差异、5xx、RSS 超门槛或 tail 恶化，流量切回旧 image digest；
   本轮无数据库或文件格式迁移，不需要数据回滚；
7. 稳定后再扩大流量，不在同一 canary 顺便优化 extrusion 或 preview parse。

## 15. 可复现命令与本地证据

最终 candidate 对 detached base 的代表性命令：

```text
OMP_NUM_THREADS=1 \
OPENBLAS_NUM_THREADS=1 \
MKL_NUM_THREADS=1 \
VECLIB_MAXIMUM_THREADS=1 \
NUMEXPR_NUM_THREADS=1 \
BLIS_NUM_THREADS=1 \
LUMINA_VECTOR_PARALLELISM=1 \
.venv/bin/python scripts/profile_converter_multicore.py \
  --kind vector \
  --input /Users/min/Downloads/mmexport1784271438721.svg \
  --phase generate \
  --target-width-mm 200 \
  --material-count 12 \
  --runs 1 \
  --no-cprofile \
  --reference-report \
    .scratch/vector-override-roi/mmexport-base-sha-rss-instrumented-200-12/profile.json \
  --override-scenario matched-rgb \
  --output-dir \
    .scratch/vector-override-roi/mmexport-candidate-release-analysis-final-200-12
```

主要本地 artifact：

- detached base：
  - `mmexport-base-sha-8d26399b-200-12`
  - `mmexport-base-sha-repeat-200-12`
  - `mmexport-base-sha-rss-instrumented-200-12`
  - `mmexport-base-sha-rss-high-pressure-200-12`
- final candidate fresh：
  - `mmexport-candidate-release-analysis-final-200-12`
  - `mmexport-candidate-after-base-final-200-12`
  - `mmexport-candidate-final-third-200-12`
- final candidate warm stress：
  `mmexport-candidate-final-warm-4runs-200-12`
- 8/12/15 色：
  - `small8-base-sha-final` / `small8-candidate-final`
    / `small8-candidate-final-current`
  - `small12-recipe-base-sha-final` /
    `small12-recipe-candidate-final` /
    `small12-recipe-candidate-final-current`
  - `small15-combined-base-sha-final` /
    `small15-combined-candidate-final` /
    `small15-combined-candidate-final-current`
- clean V2 dependency environment：
  - `small8-clean-v2-env-current`
  - `small15-combined-clean-v2-env-current`
- latest origin integration：
  `small8-latest-origin-patch`
- final exact concurrency：
  - `mmexport-candidate-concurrent-staggered-a-200-12`
  - `mmexport-candidate-concurrent-staggered-b-200-12`
- no-override：
  - `small8-no-override-base-timing-4runs` /
    `small8-no-override-current-4runs`
  - `starry-base-no-override-136-8-4runs` /
    `starry-current-no-override-136-8-4runs`
- 1/2/4/8 完整选择实验：
  - `mmexport-current-200-12`
  - `mmexport-current-request2-200-12`
  - `mmexport-current-request4-200-12`
  - `mmexport-current-request8-200-12`

这些位于 `.scratch/vector-override-roi/`，不进入 Git；输入原图也不提交。
没有标准 artifact 的早期微实验只保留方向性取舍，不再写精确百分比。

当前停止点：用户已批准报告，进入 Draft PR 发布；仍不执行服务器部署。
