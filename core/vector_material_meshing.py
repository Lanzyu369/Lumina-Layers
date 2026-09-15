"""Bounded process parallelism for independent vector material volumes."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from contextlib import contextmanager
import json
import multiprocessing
import os
import sys
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Iterator

import numpy as np
import shapely
import trimesh

from api.structured_logging import get_logger
from core.material_process_lifetime import (
    MaterialProcessLifetime,
    attach_material_worker,
)
from core.task_parallelism import (
    resolve_task_parallelism_plan,
    task_parallelism_worker_scope,
)
from core.task_parallelism_runtime import (
    WorkerLeaseStore,
    current_demand_snapshot_path,
    current_worker_lease_path,
    task_host_memory_budget_scope,
    task_parallelism_runtime_scope,
)
from core.vector_layer_geometry import (
    VectorLayerGeometryPolicy,
    build_vector_layered_volume,
)
from core.vector_mesh_memory import (
    MATERIAL_COORDINATES_PER_WORKER,
    MATERIAL_MONITOR_BASE_BYTES,
    MATERIAL_OUTPUT_RETAINED_BYTES_PER_COORDINATE,
    MATERIAL_WORKER_PROCESS_BASE_BYTES,
    MATERIAL_WORKER_WORKING_BYTES_PER_COORDINATE,
    MIN_PARALLEL_MATERIAL_COORDINATES,
    get_owned_memory_report,
    get_process_rss_bytes,
    resolve_vector_mesh_memory_budget_bytes,
)

# The stage's cost model lives with the memory policy, which is also where the
# task reservation that funds this stage is computed.
# 本阶段的成本模型放在内存策略模块中，任务预留也在那里计算。
_MIN_PARALLEL_COORDINATES = MIN_PARALLEL_MATERIAL_COORDINATES
_COORDINATES_PER_WORKER = MATERIAL_COORDINATES_PER_WORKER
_PROCESS_BASE_BYTES = MATERIAL_WORKER_PROCESS_BASE_BYTES
_MONITOR_BASE_BYTES = MATERIAL_MONITOR_BASE_BYTES
_WORKING_BYTES_PER_COORDINATE = MATERIAL_WORKER_WORKING_BYTES_PER_COORDINATE
_RETAINED_BYTES_PER_COORDINATE = MATERIAL_OUTPUT_RETAINED_BYTES_PER_COORDINATE
MaterialBuilder = Callable[..., trimesh.Trimesh | None]

# A lease whose release cannot reach a trustworthy table would stay reserved
# for as long as the holder process lives, so the release is retried a bounded
# number of times before it is reported as retained.
# 释放时若无法取得可信账本，额度会一直占用到持有进程退出，因此在记为
# retained 之前做有界次数重试。
_LEASE_RELEASE_ATTEMPTS = 3
_LEASE_RELEASE_RETRY_SECONDS = 0.05

_log = get_logger(__name__)

# Set in each material worker by its process initializer: the demand snapshot
# published by the owning pool. A spawned child starts with empty thread-local
# state, so the path has to be handed over explicitly for the live snapshot to
# reach the compute stage.
# 由进程初始化器在每个材质 worker 内设置：所属进程池发布的负载快照。spawn
# 子进程的线程本地状态是空的，必须显式传入，实时负载快照才能到达计算阶段。
_CHILD_DEMAND_SNAPSHOT_PATH: Path | None = None


def _json_scalar(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Unsupported material transport scalar: {type(value).__name__}")


def _write_material_input(path: Path, slabs: list[dict]) -> None:
    records = []
    for slab in slabs:
        geometry = slab.get("geometry")
        records.append({
            "geometry": (
                shapely.to_wkb(geometry, hex=True, include_srid=True)
                if geometry is not None else None
            ),
            "precision": float(shapely.get_precision(geometry)) if geometry is not None else 0.0,
            "height": slab.get("height", 0.0),
            "z_offset": slab.get("z_offset", 0.0),
        })
    path.write_text(
        json.dumps(records, default=_json_scalar, separators=(",", ":")),
        encoding="utf-8",
    )


def _read_material_input(path: Path) -> list[dict]:
    records = json.loads(path.read_text(encoding="utf-8"))
    for record in records:
        encoded = record["geometry"]
        geometry = shapely.from_wkb(encoded) if encoded is not None else None
        precision = record.pop("precision")
        if geometry is not None and precision > 0:
            geometry = shapely.set_precision(geometry, precision, mode="pointwise")
        record["geometry"] = geometry
    return records


def _initialize_material_process(
    job_name: str, parent_pid: int, demand_snapshot_path: str | None = None
) -> None:
    global _CHILD_DEMAND_SNAPSHOT_PATH

    # Preserve the parent-owned log path and suppress duplicate log bootstrap.
    os.environ["LUMINA_LOG_INIT_BY_PARENT"] = "1"
    attach_material_worker(job_name, parent_pid)
    _CHILD_DEMAND_SNAPSHOT_PATH = (
        Path(demand_snapshot_path) if demand_snapshot_path else None
    )
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _build_material_file(
    input_path: str,
    output_path: str,
    scale_factor: float,
    grid_mm: float | None,
    memory_budget_bytes: int,
) -> tuple[str, int, float]:
    if _CHILD_DEMAND_SNAPSHOT_PATH is None:
        with (
            task_parallelism_worker_scope(),
            task_host_memory_budget_scope(memory_budget_bytes),
        ):
            return _build_material_mesh(input_path, output_path, scale_factor, grid_mm)
    with (
        task_parallelism_worker_scope(),
        task_host_memory_budget_scope(memory_budget_bytes),
        task_parallelism_runtime_scope(_CHILD_DEMAND_SNAPSHOT_PATH),
    ):
        return _build_material_mesh(input_path, output_path, scale_factor, grid_mm)


def _build_material_mesh(
    input_path: str,
    output_path: str,
    scale_factor: float,
    grid_mm: float | None,
) -> tuple[str, int, float]:
    mesh = build_vector_layered_volume(
        _read_material_input(Path(input_path)),
        scale_mm_per_svg_unit=scale_factor,
        policy=VectorLayerGeometryPolicy(grid_mm=grid_mm) if grid_mm is not None else None,
    )
    if mesh is None:
        np.savez(output_path, present=np.array(False))
    else:
        np.savez(
            output_path, present=np.array(True),
            vertices=np.asarray(mesh.vertices), faces=np.asarray(mesh.faces),
            metadata=np.array(json.dumps(mesh.metadata, default=_json_scalar)),
        )
    return output_path, os.getpid(), time.process_time()


def _read_material_result(path: str) -> trimesh.Trimesh | None:
    with np.load(path, allow_pickle=False) as result:
        if not bool(result["present"]):
            return None
        return trimesh.Trimesh(
            vertices=result["vertices"], faces=result["faces"], process=False,
            metadata=json.loads(str(result["metadata"].item())),
        )


def _coordinate_counts(items: list[tuple[str, dict]]) -> list[int] | None:
    counts = []
    for _name, data in items:
        if not isinstance(data["slabs"], (list, tuple)):
            return None
        count = 0
        for slab in data["slabs"]:
            if not isinstance(slab, dict):
                return None
            for key in ("height", "z_offset"):
                value = slab.get(key, 0.0)
                value = value.item() if isinstance(value, np.generic) else value
                if value is not None and not isinstance(value, (str, int, float)):
                    return None
            geometry = slab.get("geometry")
            if geometry is not None and not isinstance(geometry, shapely.Geometry):
                return None
            try:
                count += int(shapely.get_num_coordinates(slab.get("geometry")))
            except (TypeError, ValueError):
                return None
        counts.append(count)
    return counts


def _worker_budget(
    items: list[tuple[str, dict]],
    serial_builder: MaterialBuilder,
    policy: VectorLayerGeometryPolicy | None,
    diagnostics: dict | None = None,
) -> tuple[int, str, int, Any]:
    """Decide how many material workers this task may start.

    决定本任务可以启动多少个材质 worker。

    ``diagnostics`` receives the scalar inputs of that decision, so a serial
    outcome names the interface that bound it instead of leaving it to be
    inferred from a wall-clock column.
    ``diagnostics`` 接收该决定的标量输入，使“为什么串行”由字段直接说明，
    而不是靠耗时列反推。
    """

    counts = _coordinate_counts(items)
    if (
        counts is None or serial_builder is not build_vector_layered_volume
        or (policy is not None and not isinstance(policy, VectorLayerGeometryPolicy))
        or multiprocessing.current_process().daemon
        or len({id(data["slabs"]) for _name, data in items}) != len(items)
    ):
        _record_worker_budget_diagnostics(diagnostics, None)
        return 1, "serial_input", 0, None
    total_coordinates = sum(counts)
    worker_bytes = _PROCESS_BASE_BYTES + max(counts, default=0) * _WORKING_BYTES_PER_COORDINATE
    plan = resolve_task_parallelism_plan(
        "vector", work_items=len(items), hard_max_workers=None,
        work_units=total_coordinates,
        min_parallel_work_units=_MIN_PARALLEL_COORDINATES,
        work_units_per_worker=_COORDINATES_PER_WORKER,
        estimated_worker_bytes=worker_bytes,
    )
    rss = get_process_rss_bytes()
    budget = resolve_vector_mesh_memory_budget_bytes()
    remaining = (
        budget - rss
        - total_coordinates * _RETAINED_BYTES_PER_COORDINATE
        - _MONITOR_BASE_BYTES
        if rss is not None else 0
    )
    affordable = max(1, remaining // worker_bytes)
    _record_worker_budget_diagnostics(
        diagnostics,
        {
            "materialize_memory_budget_bytes": int(budget),
            "materialize_memory_parent_rss_bytes": None if rss is None else int(rss),
            "materialize_memory_remaining_bytes": int(remaining),
            "materialize_memory_retained_bytes": int(
                total_coordinates * _RETAINED_BYTES_PER_COORDINATE
            ),
            "materialize_memory_worker_bytes": int(worker_bytes),
            "materialize_memory_affordable_workers": int(affordable),
            "materialize_memory_planned_workers": int(plan.workers),
            "materialize_total_coordinates": int(total_coordinates),
            "materialize_max_material_coordinates": int(max(counts, default=0)),
        },
    )
    if affordable < plan.workers:
        return affordable, "vector_memory_budget", worker_bytes, plan
    return plan.workers, plan.limiting_reason, worker_bytes, plan


def _record_worker_budget_diagnostics(
    diagnostics: dict | None, values: dict | None
) -> None:
    """Publish the worker-budget decision's inputs, including "not computed".

    发布 worker 预算决定的输入；未计算时也如实标注。
    """

    if diagnostics is None:
        return
    if values is None:
        # The decision short-circuited before any memory arithmetic; say so
        # rather than leaving stale numbers from another stage.
        # 决定在任何内存运算之前就短路了，如实标注，而不是留下其他阶段的旧数字。
        diagnostics["materialize_memory_budget_bytes"] = None
        diagnostics["materialize_memory_parent_rss_bytes"] = None
        diagnostics["materialize_memory_remaining_bytes"] = None
        diagnostics["materialize_memory_retained_bytes"] = None
        diagnostics["materialize_memory_worker_bytes"] = None
        diagnostics["materialize_memory_affordable_workers"] = None
        diagnostics["materialize_memory_planned_workers"] = None
        diagnostics["materialize_total_coordinates"] = None
        diagnostics["materialize_max_material_coordinates"] = None
        return
    diagnostics.update(values)


def _accept_result(result: dict, name: str, data: dict, mesh: trimesh.Trimesh | None) -> None:
    _release_material_input(data)
    _record_material_result(result, name, data, mesh)


def materialize_material_meshes(
    slabs_by_slot: dict,
    *,
    scale_factor: float,
    geometry_policy: VectorLayerGeometryPolicy | None,
    serial_builder: MaterialBuilder,
    timings: dict | None = None,
) -> dict:
    """Build ordered material volumes under the shared CPU and memory budget.

    在共享 CPU 和内存预算内按原顺序生成材质体积。小任务保持串行；独立进程
    只传标量与文件路径，保持几何算法、材质顺序及错误传播不变。

    Args:
        slabs_by_slot: Material IDs and source slabs. 材质编号及源片层。
        scale_factor: Physical scaling factor. 物理缩放比例。
        geometry_policy: Existing grid policy. 现有物理网格策略。
        serial_builder: Existing in-process builder, preserving caller hooks.
            原有串行构建器；自定义构建器保持串行。
        timings: Optional scalar stage diagnostics. 可选的阶段诊断字段。

    Returns:
        Ordered material-to-mesh mapping. 按输入顺序排列的材质网格映射。
    """
    items = [(name, data) for name, data in slabs_by_slot.items() if data.get("slabs")]
    budget_diagnostics: dict = {}
    workers, reason, worker_bytes, plan = _worker_budget(
        items, serial_builder, geometry_policy, budget_diagnostics
    )
    if timings is not None:
        timings.update(budget_diagnostics)
        timings.update({
            "materialize_parallelism_workers": workers,
            "materialize_parallelism_limit": reason,
            "materialize_process_count": 0,
            "materialize_child_cpu_s": 0.0,
        })
    if workers <= 1:
        return _materialize_serial(items, scale_factor, geometry_policy, serial_builder)

    # The static plan above only knows how many tasks are running. Ask the
    # pool-owned lease table how many workers are still free before starting
    # any, so a task that arrives while an earlier one is already running sees
    # that task's real workers instead of dividing the machine again.
    # 上面的静态计划只知道“有几个任务在跑”。启动前先向进程池的租约表查询还剩
    # 多少 worker 空余，使后到任务看到先到任务真实占用的 worker，而不是重新整除
    # 一次机器容量。
    lease_store, grant = _reserve_worker_lease(workers, plan)
    if timings is not None:
        timings.update(_lease_timings(workers, grant, plan))
    if grant is not None and grant.state == "granted":
        workers = grant.workers
        if timings is not None:
            timings["materialize_parallelism_workers"] = max(1, workers)
            if grant.limiting_reason in {
                "worker_lease_contention",
                "lease_capacity_exhausted",
            }:
                timings["materialize_parallelism_limit"] = grant.limiting_reason
    elif grant is not None and grant.state in {"invalid", "lock_timeout"}:
        # No trustworthy view of what else is running: keep this task serial
        # rather than adding load to a machine whose state is unknown.
        # 无法可信地判断机器占用时保持串行，而不是在状态未知时继续加负载。
        workers = 1
        if timings is not None:
            timings["materialize_parallelism_workers"] = 1
            timings["materialize_parallelism_limit"] = grant.limiting_reason

    if workers <= 1:
        # Includes a lease grant of zero: every CPU is already leased out, so
        # this document is built in the process that already holds a slot
        # instead of starting new worker processes.
        # 包含“租约授予 0”的情况：CPU 已被全部租出，本份文档改为在已经取得
        # 位置的本进程内构建，而不是新增 worker 进程。
        _release_worker_lease(lease_store, grant, timings)
        return _materialize_serial(items, scale_factor, geometry_policy, serial_builder)

    # The lease is taken before anything else can fail, so its release has to
    # cover every way out of this function: a monitor that cannot start, a
    # failing diagnostic, a worker error and normal completion. It is released
    # only after this task's own compute processes have stopped, so a later
    # task never takes capacity that is still in use.
    # 租约在任何其他可能失败的动作之前取得，因此释放必须覆盖本函数的每个出口：
    # 看护启动失败、诊断失败、worker 异常与正常完成。释放发生在本任务自己的计算
    # 进程停止之后，使后到任务不会取到仍在使用中的容量。
    with _worker_lease_scope(lease_store, grant, timings):
        # Reserve all retained output above; only `workers` builders run at once.
        # Workers never mutate source slabs. Commit and release inputs in order.
        lifetime = MaterialProcessLifetime()
        try:
            try:
                lifetime.open()
            except OSError:
                if timings is not None:
                    timings["materialize_parallelism_workers"] = 1
                    timings["materialize_parallelism_limit"] = "process_ownership_unavailable"
                return _materialize_serial(items, scale_factor, geometry_policy, serial_builder)
            if timings is not None:
                # Sampled around the parallel section: the parent's own RSS is not
                # the task's footprint while material children are alive.
                # 在并行段前后采样：材质子进程存活期间，父进程自身 RSS 并非任务
                # 真实占用。
                start_report = get_owned_memory_report()
                timings["materialize_owned_group_rss_start_bytes"] = start_report[
                    "owned_group_rss_bytes"
                ]
                timings["materialize_container_limit_bytes"] = start_report[
                    "container_limit_bytes"
                ]
                timings["materialize_container_current_bytes"] = start_report[
                    "container_current_bytes"
                ]
                timings["materialize_container_source"] = start_report["container_source"]
            return _materialize_in_processes(
                items, scale_factor, geometry_policy, workers, worker_bytes,
                lifetime, timings, lease_store, grant,
            )
        finally:
            lifetime.close()
            if timings is not None:
                timings["materialize_monitor_cpu_s"] = lifetime.cpu_seconds
                timings["materialize_child_cpu_s"] += lifetime.cpu_seconds


def _reserve_worker_lease(
    workers: int, plan: Any
) -> tuple[WorkerLeaseStore | None, Any]:
    """Ask the pool-owned lease table for this task's real worker allowance.

    向进程池的租约表申请本任务真实的 worker 额度。

    Returns ``(None, None)`` when no lease table is installed: the process is
    not running under a pool (single CLI conversion), so the static plan stays
    in effect and the timings record that no instantaneous bound was claimed.
    未安装租约表时返回 ``(None, None)``：当前进程不在进程池中（单次 CLI
    转换），沿用静态计划，并在计时字段里如实记录未做瞬时并发保证。
    """

    lease_path = current_worker_lease_path()
    if lease_path is None:
        return None, None
    capacity = int(getattr(plan, "effective_cpu_capacity", 0) or 0)
    if capacity <= 0:
        from core.system_capacity import get_effective_cpu_capacity

        capacity = max(1, int(get_effective_cpu_capacity().effective_cpu_count))
    store = WorkerLeaseStore(lease_path)
    grant = store.reserve(
        requested_workers=workers,
        effective_cpu_capacity=capacity,
        stage="vector_materialize",
    )
    return store, grant


@contextmanager
def _worker_lease_scope(
    lease_store: WorkerLeaseStore | None, grant: Any, timings: dict | None
) -> Iterator[Any]:
    """Give this task's worker lease back on every exit from the leased section.

    在租约段的每个出口归还本任务的 worker 额度。

    The section starts at the reservation, so a monitor that cannot start, a
    failing diagnostic, a worker error and normal completion all return the
    capacity. Callers must place the scope so that it exits after this task's
    own compute processes have stopped.
    覆盖范围从预留开始：看护启动失败、诊断失败、worker 异常与正常完成都会归还
    额度。调用方必须让它在本任务自己的计算进程停止之后退出。
    """

    try:
        yield grant
    finally:
        _release_worker_lease(lease_store, grant, timings)


def _release_worker_lease(
    lease_store: WorkerLeaseStore | None, grant: Any, timings: dict | None
) -> None:
    """Return one worker lease, bounded and visible if the table stays busy.

    归还一个 worker 租约；账本持续不可写时有界重试并如实记录。

    A release that cannot reach a trustworthy table keeps this task's workers
    reserved for as long as the holder process lives, so it is retried a
    bounded number of times and then recorded as ``retained`` rather than
    swallowed. Nothing here raises: a cleanup failure must not replace the
    material error that is already propagating. 无法取得可信账本时本任务的额度
    会一直被占到这个持有进程退出，因此有界重试，仍失败则记为 ``retained`` 而
    不是静默吞掉。本函数不抛异常：清理失败不能替换已经在传播的材质错误。
    """

    if lease_store is None or grant is None:
        return
    token = getattr(grant, "token", None)
    if token is None:
        return
    attempts = 0
    last_error: BaseException | None = None
    for attempt in range(_LEASE_RELEASE_ATTEMPTS):
        attempts = attempt + 1
        try:
            released = bool(lease_store.release(token))
        except BaseException as exc:  # noqa: BLE001 - cleanup must not mask the caller's error
            released = False
            last_error = exc
        if released:
            if timings is not None:
                timings["materialize_lease_release"] = "released"
                timings["materialize_lease_release_attempts"] = attempts
            return
        if attempt + 1 < _LEASE_RELEASE_ATTEMPTS:
            time.sleep(_LEASE_RELEASE_RETRY_SECONDS)

    if timings is not None:
        timings["materialize_lease_release"] = "retained"
        timings["materialize_lease_release_attempts"] = attempts
    if last_error is not None:
        _log.warning(
            "Releasing the vector material worker lease raised; the reservation "
            "stays until this process exits",
            extra={
                "event": "vector_material_lease_release_error",
                "stage": "vector_materialize",
                "attempts": attempts,
                "error": type(last_error).__name__,
            },
        )
    else:
        _log.warning(
            "Vector material worker lease could not be released; the reservation "
            "stays until this process exits",
            extra={
                "event": "vector_material_lease_release_failed",
                "stage": "vector_materialize",
                "attempts": attempts,
            },
        )


def _lease_timings(planned_workers: int, grant: Any, plan: Any) -> dict:
    """Describe planned, admitted and sibling worker counts for one stage.

    记录本阶段的计划、准入与兄弟任务 worker 数，便于事后核查限流原因。
    """

    demand_path = current_demand_snapshot_path()
    payload = {
        "materialize_lease_state": "unavailable" if grant is None else grant.state,
        "materialize_lease_planned_workers": int(planned_workers),
        "materialize_lease_granted_workers": (
            int(planned_workers) if grant is None else int(grant.workers)
        ),
        "materialize_lease_sibling_tasks": 0 if grant is None else int(grant.sibling_tasks),
        "materialize_lease_sibling_workers": 0 if grant is None else int(grant.sibling_workers),
        "materialize_lease_effective_cpu": (
            0 if grant is None else int(grant.effective_cpu_capacity)
        ),
        "materialize_demand_snapshot": "live" if demand_path is not None else "absent",
        "materialize_demand_snapshot_fallback": bool(
            getattr(plan, "demand_snapshot_fallback", False)
        ),
    }
    return payload


def _materialize_serial(
    items: list[tuple[str, dict]], scale_factor: float,
    geometry_policy: VectorLayerGeometryPolicy | None, serial_builder: MaterialBuilder,
) -> dict:
    result: dict[str, dict] = {}
    for name, data in items:
        if not data["slabs"]:
            continue
        mesh = serial_builder(
            data["slabs"], scale_mm_per_svg_unit=float(scale_factor), policy=geometry_policy,
        )
        _accept_result(result, name, data, mesh)
    return result


def _materialize_in_processes(
    items: list[tuple[str, dict]],
    scale_factor: float,
    geometry_policy: VectorLayerGeometryPolicy | None,
    workers: int,
    worker_bytes: int,
    lifetime: MaterialProcessLifetime,
    timings: dict | None,
    lease_store: WorkerLeaseStore | None = None,
    grant: Any = None,
) -> dict:
    """Build materials in processes under a bounded, re-checked dispatch.

    在有界且会复核的派发下用进程构建材质。

    Two properties this loop keeps, and neither is a claim about the whole
    machine:

    * **Bounded dispatch** — at most the currently allowed number of futures
      are outstanding, and the allowance is re-read from the lease table only
      at a material-completion boundary. A task therefore gives capacity back
      to later arrivals without ever killing running work, and it never raises
      its own concurrency above the number it was admitted with.
    * **Ordered output** — completion and failure are observed in completion
      order (so a fast failure is not hidden behind a slow sibling, and its
      remaining work stops immediately), while the returned mapping is
      assembled by original index, so material identity and order are
      unchanged.

    本循环保持两个性质，且都不声称覆盖整机：
    * 有界派发：在飞的 future 不超过当前额度，额度只在材质完成边界从租约表
      复核。因此任务会把容量让给后到者，但绝不终止正在运行的计算，也绝不把
      自身并发提高到准入时的数量之上。
    * 有序输出：完成与失败按完成顺序观察（快速失败不会被慢兄弟挡住，并立即
      停止本任务剩余计算），而返回映射按原始索引组装，材质身份与顺序不变。
    """

    result: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(
        prefix="lumina-vector-material-", dir=Path(lifetime.name).parent,
    ) as directory:
        lifetime.track_data_directory(directory)
        inputs, outputs = [], []
        input_started = time.perf_counter()
        input_bytes = 0
        for index, (_name, data) in enumerate(items):
            source = Path(directory) / f"{index}.json"
            _write_material_input(source, data["slabs"])
            inputs.append(str(source))
            outputs.append(str(Path(directory) / f"{index}.npz"))
            input_bytes += source.stat().st_size
        input_write_s = time.perf_counter() - input_started
        demand_snapshot = current_demand_snapshot_path()
        slots: list[trimesh.Trimesh | None] = [None] * len(items)
        try:
            with ProcessPoolExecutor(
                max_workers=workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_initialize_material_process,
                initargs=(
                    lifetime.name,
                    os.getpid(),
                    str(demand_snapshot) if demand_snapshot is not None else None,
                ),
            ) as pool:
                process_cpu = {}
                peak_outstanding = 0
                waves = 0
                wait_s = 0.0
                result_read_s = 0.0
                result_bytes = 0
                first_result_s: float | None = None
                dispatch_started = time.perf_counter()
                try:
                    pending: dict[Future, int] = {}
                    next_index = 0
                    allowance = workers
                    while next_index < len(items) or pending:
                        if lease_store is not None and grant is not None:
                            rechecked = lease_store.allowed_workers(grant.token)
                            if rechecked is not None:
                                allowance = min(allowance, rechecked)
                        while next_index < len(items) and len(pending) < allowance:
                            pending[
                                pool.submit(
                                    _build_material_file,
                                    inputs[next_index],
                                    outputs[next_index],
                                    float(scale_factor),
                                    (
                                        geometry_policy.grid_mm
                                        if geometry_policy is not None
                                        else None
                                    ),
                                    worker_bytes,
                                )
                            ] = next_index
                            next_index += 1
                        if not pending:
                            if next_index >= len(items):
                                break
                            # Unreachable while the lease keeps its one-worker
                            # progress floor: a running task can always submit.
                            # Better to fail loudly than to return a mapping
                            # with materials silently missing.
                            raise RuntimeError(
                                "Vector material dispatch stalled with "
                                f"{len(items) - next_index} materials unscheduled"
                            )
                        peak_outstanding = max(peak_outstanding, len(pending))
                        wait_started = time.perf_counter()
                        completed, _pending = wait(
                            tuple(pending), return_when=FIRST_COMPLETED
                        )
                        wait_s += time.perf_counter() - wait_started
                        if not completed:
                            continue
                        waves += 1
                        for future in completed:
                            index = pending.pop(future)
                            name, data = items[index]
                            # Raises here the moment a worker fails, including
                            # when an earlier material is still running.
                            output_path, process_id, cpu_seconds = future.result()
                            process_cpu[process_id] = max(
                                process_cpu.get(process_id, 0.0), cpu_seconds
                            )
                            read_started = time.perf_counter()
                            slots[index] = _read_material_result(output_path)
                            result_read_s += time.perf_counter() - read_started
                            try:
                                result_bytes += Path(output_path).stat().st_size
                            except OSError:
                                pass
                            _release_material_input(data)
                            if first_result_s is None:
                                first_result_s = time.perf_counter() - dispatch_started
                except BaseException:  # Process boundary: stop siblings before shutdown waits.
                    _stop_processes(pool)
                    raise
                if timings is not None:
                    timings["materialize_process_count"] = len(process_cpu)
                    timings["materialize_child_cpu_s"] = sum(process_cpu.values())
                    timings["materialize_dispatch_waves"] = waves
                    timings["materialize_dispatch_peak_outstanding"] = peak_outstanding
                    # Stage split inside the material phase: input
                    # serialization, dispatch+compute (the first result also
                    # carries process startup) and result recovery. The sum is
                    # below the outer materialize_s because the frames overlap
                    # only where noted.
                    # 材质阶段内部分段：输入序列化、派发+计算（首个结果同时包含
                    # 进程启动）、结果回收。三者之和小于外层 materialize_s，
                    # 因为仅在注明处存在重叠。
                    timings["materialize_input_write_s"] = input_write_s
                    timings["materialize_input_bytes"] = input_bytes
                    timings["materialize_worker_wait_s"] = wait_s
                    timings["materialize_result_read_s"] = result_read_s
                    timings["materialize_result_bytes"] = result_bytes
                    timings["materialize_first_result_s"] = first_result_s
        except BrokenProcessPool as exc:
            raise RuntimeError("Vector material worker exited unexpectedly") from exc
    for index, (name, data) in enumerate(items):
        _record_material_result(result, name, data, slots[index])
    return result


def _release_material_input(data: dict) -> None:
    """Drop one material's source slabs as soon as its mesh exists.

    材质的网格一产出就释放它自己的源片层，避免所有输入一直被持有到全部完成。
    """

    slabs = data["slabs"]
    if hasattr(slabs, "clear"):
        slabs.clear()


def _record_material_result(
    result: dict, name: str, data: dict, mesh: trimesh.Trimesh | None
) -> None:
    """Commit one finished material into the ordered output mapping.

    将一个完成的材质按原始顺序写入输出映射。
    """

    if mesh is not None:
        result[name] = {"meshes": [mesh], "mat_id": int(data["mat_id"])}


def _stop_processes(pool: ProcessPoolExecutor) -> None:
    # Python 3.12 has no public terminate_workers(). Only touch this pool's
    # process objects; the executor retains responsibility for joining them.
    for process in list((getattr(pool, "_processes", None) or {}).values()):
        try:
            if process.is_alive():
                process.kill()
        except (OSError, ValueError):
            pass  # A worker may already have exited or been closed by its owner.
