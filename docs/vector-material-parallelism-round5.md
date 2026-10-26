# 第五轮（性能线）：租约生命周期、可见父级内存上限、默认入口真正用上材质多进程

2026-09-15；`Min/perf/vector-material-parallelism`，基线 `dev-refactor` (`2e5d94bb`)。
本文件记录本轮三个修正（R1 租约泄漏、R2 容器内存链、R3 默认入口并行预算）与
有限验收的实测结果。不改颜色、几何容差、材质与打印参数；不合并、不发布。

## R1 共享 worker 租约在部分出口上不归还

**问题。** `materialize_material_meshes` 在拿到租约之后才启动看护进程、写结果
文件、建进程池。原实现只在正常完成和 worker 异常两条路径上归还，其余出口
（看护启动失败、启动后诊断失败）会带着租约返回：租约记在**进程级**账本里，
只要外层进程还活着，这份额度就一直占着，后到任务看到的是“机器已满”。

**做法。** 用 `_worker_lease_scope` 把租约生命周期包住整个函数体（`finally`
释放），并把释放本身做成有界重试的 `_release_worker_lease`：

- 归还发生在本任务自己的计算进程停止**之后**（`lifetime.close()` 之后的
  `finally`），所以后到任务不会取到仍在使用中的容量；
- 释放失败不吞掉原始业务异常，而是写入
  `materialize_lease_release = "retained"` 与 `materialize_lease_release_attempts`
  并打告警日志，让“占着但不归还”变成可见状态；
- `WorkerLeaseStore.release()` 改为返回 `bool`：账本已不含该 token（含重复释放）
  返回 `True`，取锁超时或账本不可信返回 `False`。

**测试**（`tests/test_vector_material_dispatch_unit.py`，先红后绿）：看护启动
`OSError`、启动后诊断抛错、worker 异常、正常完成四条出口各有一个用例，加一个
顺序用例断言 `pool.exit` 早于 `lease.release`，再加两个用例断言释放失败既不
掩盖业务异常、也能在 timings 里看到。修复前三条新用例分别红在
`assert (8, 1) == (0, 0)`、`assert 8 == 0`、`KeyError:
'materialize_lease_release'`。

## R2 容器内存上限看不到可见的父级

**问题。** 内存探测只看本进程 cgroup 叶子层的 `memory.max`。在
`/delegated/abc/workload.scope` 这类层级里，叶子常是 `max`，真正的上限在父级
`/delegated/abc`。只看叶子会把受限工作负载读成不受限，材质网格预算与并行度按宿主机
可用内存计算。

**做法。** 复用既有的 cgroup/mount 解析：`_read_cgroup_v2_memory_levels()`
从叶子向挂载根逐级向上（`_cgroup_v2_file_candidates_with_mounts` 已带挂载点，
不再发明不可见的祖先，也不越过可见挂载范围），每级记录
`CgroupMemoryLevel(path, limit_bytes, used_bytes, limit_known)`。合成规则：

- 硬上限 = 所有可见**有限**上限的最小值；
- 每级剩余按该级自己的 `max − current` 计算，再与宿主可用量取小——父级
  `current` 已含后代，用父级上限减叶子用量会把同一批字节算两遍；
- 区分**已确认不受限**（每个可见层级的 `memory.max` 都读到且为 `max`）、
  **受限**、**未知**（有层级读不到，且没有有限上限）。读不到**不**当成
  “已确认不受限”；Linux 上完全读不到 `/proc` 记 `unknown`，非 Linux 平台
  记 `unrestricted`（那里本来就没有 cgroup）。

**测试**（`tests/test_system_capacity_unit.py`，8 个新用例先红后绿）：父级
2 GiB/1.5 GiB 用量 + 子级 `max` → 受限且剩余 512 MiB；父级 2 GiB + 子级
8 GiB → 仍按父级；子级更严 → 按子级；全部 `max` → 用宿主数字；父级读不到 →
`unknown` 而不是“已确认不受限”；文件缺失 → 显式状态；缓存
`get_effective_memory_limit_bytes` 也看得到父级；以及既有直挂与越界夹具不回归。
另外在真实嵌套 cgroup 里复核：只读叶子时报 `limit_bytes: null`，读链后报父级
2 GiB（`available 2137030656`，宿主 `30253318144`），网格预算从 8 GiB 被压到
2 GiB。

## R3 默认入口没有真正用上材质多进程

**实测到的原因。** 在产品自己的池路由上打印材质阶段的标量输入：

| 字段 | 实测值 |
|---|---|
| `materialize_memory_budget_bytes` | 1,048,713,856（≈ 本任务的预留） |
| `materialize_memory_parent_rss_bytes` | 282,714,112 |
| `materialize_memory_retained_bytes` | 227,220,480（591,720 坐标 × 384） |
| `materialize_memory_worker_bytes` | 401,243,136（256 MiB + 129,695 坐标 × 1024） |
| `materialize_memory_remaining_bytes` | 404,561,536 |
| `materialize_memory_affordable_workers` | **1** |
| `materialize_memory_planned_workers` | **10** |
| `materialize_process_count` | 0（全部在父进程内构建） |

所以卡住的不是 CPU 也不是租约，而是**为串行管线计的预留**：它只够一个构建
进程的固定开销，同一份文档只有显式抬到 12 GiB 时才起 10 个进程。

**做法：把有根据的并行内存需求交给既有准入机制，而不是改守卫。**
`_worker_budget` 的算术保持原样（它用实时预算和真实坐标数做最终判断，是安全
边界）。新增的是**请求**：

1. `core/vector_mesh_memory.py` 把材质阶段的成本模型（进程基数、看护基数、
   每坐标工作集、每坐标保留量、并行坐标下限、每 worker 坐标数）集中到内存策略
   模块，`core/vector_material_meshing.py` 改为引用同一组常量，避免预留与被
   预留的阶段各自漂移。
2. `estimate_vector_material_parallel_memory_target_bytes()` 用**已知输入**
   （同一条路径的源文件大小与选中材质数）算出“这份工作真正能喂饱的构建进程数”
   所需预算：串行预留 + 该进程数 × 进程基数 + 坐标工作集。坐标数由**既有的
   每源字节 64 字节扩展**除以既有的每坐标 384 字节保留量得到（该模型
   0.167 坐标/源字节 高于产品自有密集文档实测的 0.156，即偏保守）。工作量低于
   阶段开始使用 worker 的坐标下限时返回 `None`——那种工作本来就在已有进程内
   完成，为它索取构建进程只会占掉别人真正能用的容量。
3. `_HostMemoryReservationGate.acquire()` 增加一个**有界的原子调整**
   （`parallel_target_bytes`）：在同一把锁内，先按原规则校验必需预留（不足仍
   按原样拒绝），再在其上追加 `min(请求量, 仍然空闲的容量)`。追加量计入
   `_reservations`，因此对后到任务可见；**拿不到追加不影响成败**，任务退回必需
   预留、以较低并行度运行。
4. `api/routers/converter/generate.py` 在默认生成路由上同时传必需预留与并行
   目标；两者都由同一个 `_vector_task_memory_inputs()` 收集输入，避免两处
   路径遍历漂移。
5. `scripts/log_quality_check.py` 的 fast 模式用白名单校验池侧提交参数（它存在的
   目的就是拦住没人预期的提交参数），因此把新的**池侧**参数
   `host_memory_parallel_target_bytes` 加入白名单；该参数由闸门授予、不转发给
   worker。全量套件里这条正是本轮唯一的新增失败，修好后
   `tests/test_log_quality_check_unit.py` 121 passed。

**没有做的事**（按边界要求）：不给所有任务固定 12 GiB，不为特定 CPU 型号
特判，不允许子进程自行抬高父任务预算，不忽略容器上限，不删除最小内存保护，
不在基准脚本里改预留而默认行为不变，也不为了进程数好看在低内存设备上强起进程。

**测试**（先红后绿）：`tests/test_worker_pool_unit.py` 新增
`TestHostMemoryParallelTarget` 5 个用例（追加量到达 worker 成为其本地预算、受
空闲容量约束、无空闲时仍按必需预留准入、追加量计入并发、无目标时行为不变）；
`tests/test_vector_mesh_memory_unit.py` 3 个用例（覆盖工作真正能用的构建进程数、
小工作量/单材质/未知源返回 `None`、受配置上限封顶）；
`tests/test_vector_material_dispatch_unit.py` 3 个用例，其中两个直接复刻实测
画像（3.80 MB、591,704 坐标、282.7 MB 父 RSS）：仅有串行预留时可负担 worker 数
为 1、且 `materialize_parallelism_limit == "vector_memory_budget"`；经闸门授予
后同一份输入可负担 > 1 个，另一个用例用同一批 slots 只改预算，从
`workers = 1 / process_count = 0 / limit = vector_memory_budget` 变成
`workers = 3 / process_count > 0`。

## 追加修正：并行预算申请改为复用现有并发策略

**问题。** 估算端自己按坐标阶梯算"能喂饱几个构建进程"，这既忽略了显式固定并发
（`LUMINA_VECTOR_PARALLELISM`）与设备有效 CPU，也在串行配置下照旧申请追加量；
更关键的是它的上限取自 `resolve_vector_mesh_memory_budget_bytes()`，而该函数把
**任务当前预留**也算进去——于是"用尚未追加的旧预算反推只能串行"在任务作用域内就会
成立，等于把默认提速关掉。

**做法（只改这一处，不新增调度器/状态机/框架）。** 估算端不再自算阶梯，改为调用
阶段实际运行的那套策略：

```python
resolve_task_parallelism_plan(
    "vector", work_items=材质数, hard_max_workers=None,
    work_units=坐标估算, min_parallel_work_units=…, work_units_per_worker=…,
    outer_demand=1,   # 本任务自己的上限，不预测兄弟任务负载
)
```

- 策略给出串行（工作量小、显式串行、只有一个可用 CPU、只有一个材质）→ 返回
  `None`，**串行不申请追加量**；
- 显式固定并发与低核设备按策略给出的上限申请（固定 3 → 3 个构建进程；2 核 → 2 个），
  而不是按材质数或坐标阶梯另算一遍；
- 上限改用新的 `_configured_vector_mesh_memory_budget_bytes()`：只含配置与容器
  上限，结构上不含任务当前预留；`resolve_vector_mesh_memory_budget_bytes()` 保持
  原语义（在此基础上再叠加任务预留），阶段侧行为不变；
- `outer_demand=1` 只影响"申请多少"，不影响"实际能起多少"：内存由准入闸门按真正
  空闲量授予，CPU 由租约在运行时约束，最终共享机器的任务只用掉预算的一部分。

**定向测试（先红后绿，4 条）**，都在 `tests/test_vector_mesh_memory_unit.py`：
串行配置不申请（旧实现会返回请求）；固定 3 → 恰好 3 个构建进程（旧实现按 12 申请）；
2 核设备 → 恰好 2 个（旧实现按 12 申请）；在旧预算作用域内调用结果与不设作用域相同
（旧实现会塌成旧预算 1,102,827,008）。

**复测（同一入口、同一输入、三臂交替）**：大样例仍是 **9 个真实材质进程**、预算
4179 MB（该文档上策略上限与原先的工作阶梯同值），同一时间窗内基线
12.83 / 13.32 s → 默认 8.86 / 9.19 s；小样例预算仍等于必需预留（1409 MB）、材质
进程 0、限制原因 `insufficient_work_units`。相关套件 578 passed。

## 有限验收（真实默认生成入口，基线与修改交替）

方法：同一份输入、同一台机器，走 `api.workers.converter_workers.worker_generate_model`
的真实 worker 与真实 `WorkerPoolManager`，内存预留与并行目标都由生成路由自己的
`_vector_task_memory_reservation_bytes()` / `_vector_task_parallel_memory_target_bytes()`
计算（即默认产品决策）。三臂交替执行：

- `baseline`：基线树，其自身默认预留；
- `perf-required-only`：本分支但**不**提交并行目标（隔离 R3 的贡献）；
- `perf-default`：本分支默认行为。

每个 run 前的池为新实例；`LUMINA_VECTOR_PARALLELISM` 不设置（auto）；三臂按
基线→required→default 的顺序交替，第 0 次视为冷启动（源文件与产品缓存首次
命中），第 1、2 次为热启动。材质阶段的标量从流水线自己的
`vector_generate_timings` 事件读回。

### 大样例：3.80 MB / 299 mm / 12 材质 / 层高按产品默认

| 臂 | 生成总耗时 s（rep0/1/2） | 中位数 | 材质阶段 s（rep0/1/2） | 中位数 | 材质进程 | 限制原因 | 材质预算 MB | 进程组 RSS 峰值 MB |
|---|---|---|---|---|---|---|---|---|
| baseline | 18.45 / 15.01 / 15.38 | 15.38 | 13.24 / 10.84 / 10.89 | 10.89 | 0 | — | — | 549 / 547 / 549 |
| perf-required-only | 12.87 / 12.69 / 13.08 | 12.87 | 8.71 / 8.49 / 9.00 | 8.71 | 2 | `vector_memory_budget` | 1640 | 846 / 841 / 853 |
| perf-default | 9.44 / 10.05 / 10.47 | 10.05 | 5.52 / 5.51 / 5.60 | 5.52 | **9** | `vector_memory_budget` | 4179 | 1685 / 1698 / 1688 |

- 用户等待（生成总耗时中位数）：**15.38 s → 10.05 s（−5.33 s，−35%）**；
- 材质阶段中位数：**10.89 s → 5.52 s（−4.93 s，−49%）**，即改善几乎全部来自
  材质阶段；
- 只把并行目标交给准入、其余不变（required → default）：**12.87 s → 10.05 s
  （−2.82 s，−22%）**，这是 R3 本身的贡献；
- 资源代价：进程组 RSS 峰值 **549 MB → 1688 MB**，材质进程 **0 → 9**；
- 9 而不是计划里的 10：`affordable 9 < planned 10`，限制原因如实标为
  `vector_memory_budget`——预算买到了 9 个构建进程，没买到第 10 个。声称的是
  “不再串行、9 个真实进程”，不是“跑满某个数字”。
- 三种臂的 3MF 字节数完全一致（大样例 31,917,737；中样例 1,296,509）。

### 小样例：24 KB / 12 材质

| 臂 | 生成总耗时 s（rep0/1/2） | 中位数 | 材质阶段 s | 材质进程 | 限制原因 | 材质预算 MB |
|---|---|---|---|---|---|---|
| baseline | 2.15 / 2.00 / 1.94 | 2.00 | 0.171 / 0.146 / 0.150 | 0 | — | — |
| perf-required-only | 2.21 / 1.96 / 2.08 | 2.08 | 0.182 / 0.146 / 0.151 | 0 | `insufficient_work_units` | 1409 |
| perf-default | 2.17 / 1.93 / 2.31 | 2.17 | 0.198 / 0.157 / 0.165 | 0 | `insufficient_work_units` | 1409 |

小样例的材质预算与必需预留相同（1409 MB），即**没有**索取并行追加量；材质进程
始终为 0，阶段在父进程内完成。三臂的耗时分部重叠（baseline 1.94–2.15，
perf-default 1.93–2.31），没有可测的默认启动开销差异。

### 错峰的两个真实任务

| 场景 | 臂 | 任务等待 s | 阶段诊断 |
|---|---|---|---|
| 大 + 中，错峰 3 s | baseline | 17.20 / 3.34 | — |
| | perf-default | 12.14 / 4.50 | 大任务 `cpu_fair_share` 8 worker；中任务 `insufficient_work_units` 1 worker |
| 两个大样例，错峰 8 s | baseline | 16.42 / 16.41 | — |
| | perf-default | 11.66 / 12.02 | 两个任务各 9 worker（预算 4179 MB），峰值租出 9 |

- 大 + 中场景里，后到任务让先到任务的额度从 9 降到 8（限制原因
  `cpu_fair_share`），两个任务都完成；中任务自身工作量低于并行门槛，所以仍为
  1 个 worker。
- 两个大样例错峰 8 s 时，两次材质阶段在时间上并未重叠（各约 5.4 s，都在开始后
  约 4 s 才进入材质阶段），因此都拿到 9 个；**峰值租出 worker 9**，从未出现
  两者之和，说明共享额度没有被加总超发。
- 所有 run 结束后：`host_memory_reserved_bytes = 0`、`outstanding_tasks = 0`，
  租约账本文件已随池关闭消失（`ledger-absent`），没有残留额度或挂住的进程。
- 后到任务在等待窗口内变慢（3.34 → 4.50 s）是因为它与 8 个构建进程共用 CPU，
  不是内存超发；机器总吞吐按两任务等待之和是 20.5 s → 16.6 s。

## 仍未覆盖

- **上传→预览仍未加速**，本轮没有碰预览路由；预览的并行目标留到下一轮 profile
  任务，不把两件事混在一起宣称都做完了。
- `ledger 0` 的回退（额度为 0 时在已有进程内构建、而不是读成“CPU 完全空闲”）
  由 `test_zero_grant_builds_in_process_without_starting_workers` 与租约表语义
  保证；本轮真实错峰没有出现 0 授予，因为两个大样例的材质阶段没有重叠。
- Mac / Linux 全链路仍无访问条件，未验证；没有为此新建环境。
- 容器实测仍是已授权的隔离环境、有界样本与时限；模拟出来的 CPU 数量不作为
  “在某台真实设备上测过”的证据。
- 份额只覆盖同一池内已登记的工作，不声称 16/16 账本是整机硬上限；跨独立 API
  进程的全局调度不在本轮范围。

## 测试

- R1/R2/R3 新增用例先红后绿；直接相关套件
  （`test_converter_generate_unit`、`test_model_surface_generate_unit`、
  `test_converter_preview_unit`、`test_converter_batch_unit`、
  `test_worker_pool_unit`、`test_worker_pool_properties`、
  `test_vector_mesh_memory_unit`、`test_vector_material_dispatch_unit`、
  `test_vector_material_parallelism_unit`、`test_system_capacity_unit`、
  `test_task_parallelism_runtime_unit`、
  `test_vector_material_output_integrity_unit`）共 **609 passed**。
- 全量套件（`.scratch/round5/suite/full-pytest-r5b.log`，不入库）：**44 failed /
  6779 passed / 53 skipped**。按用例 ID 与本轮开始前的分支头（44 failed /
  6753 passed）逐条比对：**新增失败 0 条，消失失败 0 条**，即失败集合完全相同；
  多出的 26 个通过即本轮新增用例（R1 7 + R3 3 + 准入 5 + 估算 3 + 内存链 8）。
  这些失败与内存/材质/准入无关（发布链、SDK 绑定等在基线即失败），属本分支既有
  失败集。
