# 第三轮（性能线）：错峰任务的 worker 准入与完成顺序派发

2026-09-15；`Min/perf/vector-material-parallelism`，基线 `dev-refactor` (`2e5d94bb`)。
本文件只描述性能线；SVG 后端诊断与文档级恢复不在本分支。

## 被修正的两个问题

**F1 只看任务数，看不到已经占用的 worker。** 静态计划用
`cpu_fair_share = effective_cpu // outer_demand` 决定并发，而 `outer_demand`
只是“同时在跑几个任务”。16 核机器上任务 A 单独进入时会取 12 个 worker；
B 随后进入，仍按 `16 // 2 = 8` 计算，于是 A 的 12 从不回收，瞬时最多 20 个
worker 挤在 16 核上。进程池的 worker 数在提交时就固定，之后无法收缩。

**F2 结果按输入顺序读取，失败被慢兄弟挡住。** `for (name, data), future in
zip(items, futures): future.result()` 意味着第 0 个材质很慢时，第 1 个材质的
异常要等第 0 个跑完才会被发现，本任务剩余计算也不会及时停止。

## 本轮做法

**worker 租约（复用既有预算发布机制，不引入全局调度器）。**
`OuterDemandPublisher` 在原有 `demand.json` 旁边发布 `workers.json`，记录每个
内部阶段实际预留的 worker 数（pid、进程创建时间、预留数、阶段、有效 CPU、
刷新时刻）。`WorkerLeaseStore.reserve` 在排他文件锁内读取活租约并给出
`free = effective_cpu - 其他任务已预留 worker`：

- 空闲够用 → 按请求授予；
- 只够一部分 → 授予剩余部分，原因记为 `worker_lease_contention`；
- 一个都不剩 → **授予 0**，原因记为 `lease_capacity_exhausted`：本份文档改为在
  已经取得位置的进程内串行构建，不新增 worker 进程，因此准入时的总和仍然等于
  机器容量，而不是靠“至少留 1 个”把总和顶到 17。

持有者进程消失（崩溃、被杀、超时回收）后，下一次预留会按 pid 与进程创建时间
判定其已不在，丢弃该租约，避免永久占位。租约表不可读（文件存在但结构不可信）
时判定为 `invalid`：不假装机器空闲，而是让本任务串行并明确记录原因。

**有界派发。** 材质提交改成“按当前额度分批提交”：

1. 额度 = 准入时的授予数；
2. 每个材质完成边界重新读取租约表，额度只下调、不上调；
3. 在飞 future 数不超过当前额度，绝不为了卡上限去终止已经在跑的计算；
4. 派发顺序与结果读取都按完成顺序进行，最终映射仍按**原始索引**组装，
   材质身份与顺序不变。

**转换保证。** 本机制保证的是：**在准入那一刻**，各任务的已授予 worker 之和
不超过有效 CPU 容量；运行中的任务只会在材质完成边界下调自身后续派发，且永不
终止正在运行的计算。它**不**证明任意时刻整机都不超载，原因有二，均在诊断里
可见：

- 运行中的租约保留 1 个 worker 的推进下限（否则已派发任务无法跑完尚未提交的
  材质）。已在运行的额度高于当前空闲时，超出量最多为“每个运行中任务 1 个”；
- 未安装租约表的路径（单次 CLI 转换、旧版本任务、多进程池各有一份账本、
  文件锁超时）没有跨任务账本，此时沿用静态计划，并在计时字段里记为
  `unavailable` / `lock_timeout`，不声称做过瞬时保证。

单个任务独占机器时不会被固定压到 1/4：没有其他租约占用时，静态计划仍是
`effective_cpu // demand`，租约按请求授予。

## 完成/失败与输出顺序解耦

`make` 派发循环用 `wait(FIRST_COMPLETED)` 观察完成与失败，任一 worker 抛出
普通异常（含结果文件缺失、结果不可读、future 被取消）都会立刻停止本任务尚未
派发的材质、终止同批 sibling 进程，再向上抛出；不会返回部分成功的映射，也不
会改变源片层（未成功时不清理输入）。

## 诊断字段（阶段计时）

| 字段 | 含义 |
|---|---|
| `materialize_lease_state` | `granted` / `unavailable` / `invalid` / `lock_timeout` |
| `materialize_lease_planned_workers` | 静态计划原本想要的 worker 数 |
| `materialize_lease_granted_workers` | 租约实际准入的 worker 数（0 = 不新增进程） |
| `materialize_lease_sibling_tasks` / `_sibling_workers` | 准入时仍在运行的其他任务及其 worker 数 |
| `materialize_lease_effective_cpu` | 用作上限的有效 CPU 容量 |
| `materialize_demand_snapshot` | `live` / `absent`：活跃负载快照是否到达计算阶段 |
| `materialize_demand_snapshot_fallback` | 是否因快照不可用回退到配置容量 |
| `materialize_dispatch_waves` / `_peak_outstanding` | 派发批次与在飞峰值（本任务自身真实并发） |
| `materialize_parallelism_limit` | 最终限制原因，如 `worker_lease_contention`、`lease_capacity_exhausted` |

子进程侧：材质 worker 的进程初始化器现在显式接收并安装父进程的负载快照路径，
spawn 子进程的空线程本地状态不再让快照在这一层丢失；`_build_material_mesh`
在计算阶段即可读到实时需求。

## 测试

`tests/test_vector_material_dispatch_unit.py`（新增 15 项）与扩写的
`test_task_parallelism_runtime_unit.py`、`test_worker_pool_unit.py`：

- 真实子进程错峰到达：A 先占 12（16 核），B 到达只得 4，C 只得 0，三次准入的
  总和始终等于 16；释放后容量回到后续任务；
- 持有者被杀后不再占位；
- 租约表不可读时拒绝加负载（串行 + 明确原因）；
- 授予 0 时真的不创建进程池，仍按原顺序构建全部材质；
- 第一项阻塞 + 第二项快速失败：父进程不等待被阻塞的材质，已提交的后续材质停发，
  sibling 进程被终止；
- 乱序完成（2,0,1）仍按原始材质顺序返回，且每个材质携带自己的几何；
- 结果读取失败、结果文件缺失、future 取消三条路径都会终止剩余计算；
- 超订机器（存在未纳入账本的占用）在完成边界把后续派发降到剩余容量，且不取消
  任何已提交的 future；
- 活跃负载快照确实到达计算阶段（子进程读到 `demand=2`，非回退）。

## 仍未覆盖

- 多进程池（同机多个 API 进程各持一份账本）之间的占用互不可见，本轮不解决；
- 容器内存配额与整机内存的区分见 F3 的单独记录；
- 本轮的耗时数据见性能测量记录，不与 SVG 缺陷修复混写。
