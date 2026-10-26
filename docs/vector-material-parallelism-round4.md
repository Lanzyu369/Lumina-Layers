# 第四轮（性能线）：容器内存上限沿调用链生效与任务进程组测量

2026-09-15；`Min/perf/vector-material-parallelism`，基线 `dev-refactor` (`2e5d94bb`)。
本文件只描述性能线；SVG 后端诊断与文档级恢复不在本分支。

## 被修正的问题

**F3 内存判断读的是宿主机的空闲内存。** 内存相关判断此前统一使用
`psutil.virtual_memory().available`，在受限容器里这是**宿主机**的可用内存，
不是本任务的上限。后果是：容器限额 128 MiB、宿主机还剩 29 GiB 时，材质阶段
仍按宿主机算出可用的 worker 数（见下表“旧口径会怎么选”一列，仍会选 8 个），
材质网格预算也不会被容器上限压下来。写盘分流阈值同样受影响。

CPU 侧本来就有 cgroup v2 配额探测，内存侧没有对应的实现，两边的“有效容量”
因此可能来自完全不同的口径。

## 本轮做法

**探测集中到 `core/system_capacity.py`。** 新增
`get_effective_memory_capacity()` 与 `get_effective_memory_limit_bytes()`，
返回 `EffectiveMemoryCapacity(available_bytes, limit_bytes,
container_used_bytes, host_available_bytes, source)`，`source` 为
`cgroup_v2` / `unrestricted` / `unavailable`。cgroup v2 路径发现**复用既有
CPU 配额的那套方法**（`_parse_process_cgroup_v2_path`、`_parse_cgroup2_mounts`
和带排名的候选遍历），泛化为 `_cgroup_v2_file_candidates()`，`memory.max`
与 `cpu.max` 使用同一套候选顺序，而不是再写一份更弱的副本。规则保持可预期：

- `memory.max == "max"` 视为不限额；
- 路径缺失或不可读 → `unavailable`，并**显式**回退到 `psutil`（再退到
  `/proc/meminfo`）；
- 报告同时带 `host_available_bytes`，调用方不需要猜自己拿到的是哪种口径。

**每一跳都改用这个数，不放大也不忽略。**

| 跳 | 位置 | 行为 |
|---|---|---|
| API 准入 | `api/worker_pool.py` `_available_host_memory_bytes` | 用容器剩余量判断是否接受提交 |
| 任务计划 | `core/task_parallelism.py` 计划与 `_available_memory_bytes` | `memory_ceiling` 由容器剩余量推导 |
| 材质预算 | `core/vector_mesh_memory.resolve_vector_mesh_memory_budget_bytes` | 配置预算先被容器 `memory.max` 夹住，再被既有父任务预留夹住，只降不升 |
| 写盘分流 | `core/vector_mesh_spill.py` 保留内存阈值 | 跟随容器剩余量 |
| 诊断 | `core/vector_material_meshing.py` | 记录进程组与容器上下文字段 |

环境变量 `LUMINA_VECTOR_MESH_MEMORY_BUDGET_MB` 仍是**上限**，不会抬高容器上限。
容器限额低于配置预算且没有任何覆盖时，默认路径依次是：下调并发 → 使用既有
写盘容量 → 连一个 worker 都放不下时明确拒绝。

**进程组测量。** `core/vector_mesh_memory.get_owned_memory_report()` 汇总
父进程与递归子进程的 RSS，并带容器限额/当前用量/来源。材质阶段把它记进
`materialize_owned_group_rss_start_bytes`、`materialize_container_limit_bytes`
/`_current_bytes`/`_source`。Windows 上没有 cgroup，`container_used_bytes`
为 `None`，`source` 记为 `unrestricted`——这是“没有容器”，不是“容器为空”。

## 在真正受限的容器里核实

方法：在 WSL Ubuntu 24.04（Python 3.12.3）里创建真实的 cgroup v2
`/sys/fs/cgroup/lumina-f3-probe`，把自己的 pid 写进 `cgroup.procs` 后
`exec` 探测脚本，再**通过真实发现代码路径**读取——下表数字来自真实
`memory.max`/`memory.current` 文件，没有注入值。脚本：
`.scratch/round5/cgroup_probe_real.py`（`own_cgroup` 读数确认为
`0::/lumina-f3-probe`）。宿主机 `MemTotal` 31.65 GiB，同一次运行里
`host_available_bytes` 约 31.6 GB。

| `memory.max` | `source` | `available_bytes` | 计划 worker（容器口径） | `limiting_reason` | 材质预算 | 512 MiB 估算 |
|---:|---|---:|---:|---|---:|---|
| 2147483648 (2 GiB) | `cgroup_v2` | 2137079808 | 8 | `work_units` | 2147483648 | 接受 |
| 134217728 (128 MiB) | `cgroup_v2` | 123707392 | 1 | `memory` | 134217728 | 明确拒绝 |
| 33554432 (32 MiB) | `cgroup_v2` | 23441408 | 1 | `memory` | 33554432 | 明确拒绝 |

同一次运行里的对照列（“旧口径会怎么选”）：把 `host_available_bytes` 喂给同一
个计划函数，三种限额下都得到 **8 个 worker、`memory_ceiling` 424**——
正是 F3 描述的缺陷：128 MiB 的容器会按 31.6 GB 的宿主内存放行 8 个 worker。

三种限额分别覆盖了要求的三种默认行为：2 GiB 时内存不是限制项（并发由工作量
决定）；128 MiB 时并发被内存压到 1，写盘分流仍在既有容量内工作；余量连一个
worker 都放不下时，`enforce_vector_mesh_memory_budget` 抛出可操作的
`VectorMeshMemoryBudgetError`（“estimated peak 0.50 GiB, safe limit 0.12 GiB …
Generation stopped before the large allocation”），而不是继续分配。

## 测试

`tests/test_system_capacity_unit.py`（新增 242 行）与
`tests/test_vector_material_dispatch_unit.py` 增补，其中内存相关的核心用例：

- `test_cgroup_reader_resolves_memory_limit_and_usage`：真实目录布局下解析
  `memory.max`/`memory.current`；
- `test_memory_limit_parsing_treats_max_as_unlimited`；
- `test_effective_memory_is_capped_by_the_container_not_host_ram`：宿主内存
  很大的情况下仍然返回容器剩余量；
- `test_over_limit_container_reports_zero_available`；
- `test_unlimited_container_keeps_the_host_figure`；
- `test_memory_probe_without_any_source_is_explicitly_unavailable`；
- `test_task_memory_probe_uses_the_container_remaining`：计划函数拿到的是
  容器剩余量；
- `test_mesh_budget_is_capped_by_the_container_limit` 与
  `test_parent_reservation_still_bounds_the_mesh_budget`：预算只降不升，
  既有父任务预留仍然生效；
- `test_spill_limit_follows_the_container_remaining`：写盘阈值跟随容器；
- `test_owned_memory_report_names_the_container_source`：进程组报告带来源。

## 仍未覆盖

- WSL 里只做了容量探测（真实 cgroup 文件 + 真实发现代码路径）。**完整的
  Linux 转换流程在受限容器中的实测为“未测”**：该 WSL 发行版没有
  numpy/shapely/trimesh/psutil，也没有原生扩展；本轮不做环境安装，也不拿
  探测结果冒充流程实测。
- 生产容器（真实 8 GiB 配额容器）里的端到端材质阶段为“未测”，原因同上：
  本轮不启动/不改动既有服务，也不新建付费机器。
- NPZ/网格结果仍回到父进程内存，材质子进程写盘**不等于**整条流水线写盘；
  父进程侧峰值随材质数和文档规模增长，这是既有边界。
- 多进程池各持一份账本、跨 API 进程的占用互不可见，本轮不解决（同第三轮）。
