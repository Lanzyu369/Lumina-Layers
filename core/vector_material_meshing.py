"""Bounded process parallelism for independent vector material volumes."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import json
import multiprocessing
import os
import sys
from pathlib import Path
import tempfile
import time
from typing import Any, Callable

import numpy as np
import shapely
import trimesh

from core.material_process_lifetime import (
    MaterialProcessLifetime,
    attach_material_worker,
)

from core.task_parallelism import (
    resolve_task_parallelism_plan,
    task_parallelism_worker_scope,
)
from core.task_parallelism_runtime import task_host_memory_budget_scope
from core.vector_layer_geometry import (
    VectorLayerGeometryPolicy,
    build_vector_layered_volume,
)
from core.vector_mesh_memory import (
    get_process_rss_bytes,
    resolve_vector_mesh_memory_budget_bytes,
)

_MIN_PARALLEL_COORDINATES = 131_072
_COORDINATES_PER_WORKER = 65_536
_PROCESS_BASE_BYTES = 256 * 1024**2
_MONITOR_BASE_BYTES = 128 * 1024**2
_WORKING_BYTES_PER_COORDINATE = 1024
_RETAINED_BYTES_PER_COORDINATE = 384
MaterialBuilder = Callable[..., trimesh.Trimesh | None]


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


def _initialize_material_process(job_name: str | None, parent_pid: int) -> None:
    # Preserve the parent-owned log path and suppress duplicate log bootstrap.
    os.environ["LUMINA_LOG_INIT_BY_PARENT"] = "1"
    attach_material_worker(job_name, parent_pid)
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
    with task_parallelism_worker_scope(), task_host_memory_budget_scope(memory_budget_bytes):
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
) -> tuple[int, str, int]:
    counts = _coordinate_counts(items)
    if (
        counts is None or serial_builder is not build_vector_layered_volume
        or (policy is not None and not isinstance(policy, VectorLayerGeometryPolicy))
        or multiprocessing.current_process().daemon
        or len({id(data["slabs"]) for _name, data in items}) != len(items)
    ):
        return 1, "serial_input", 0
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
    remaining = (
        resolve_vector_mesh_memory_budget_bytes() - rss
        - total_coordinates * _RETAINED_BYTES_PER_COORDINATE
        - _MONITOR_BASE_BYTES
        if rss is not None else 0
    )
    affordable = max(1, remaining // worker_bytes)
    if affordable < plan.workers:
        return affordable, "vector_memory_budget", worker_bytes
    return plan.workers, plan.limiting_reason, worker_bytes


def _accept_result(result: dict, name: str, data: dict, mesh: trimesh.Trimesh | None) -> None:
    slabs = data["slabs"]
    if hasattr(slabs, "clear"):
        slabs.clear()
    if mesh is not None:
        result[name] = {"meshes": [mesh], "mat_id": int(data["mat_id"])}


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
    workers, reason, worker_bytes = _worker_budget(items, serial_builder, geometry_policy)
    if timings is not None:
        timings.update({
            "materialize_parallelism_workers": workers,
            "materialize_parallelism_limit": reason,
            "materialize_process_count": 0,
            "materialize_child_cpu_s": 0.0,
        })
    if workers <= 1:
        return _materialize_serial(items, scale_factor, geometry_policy, serial_builder)

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
        return _materialize_in_processes(
            items, scale_factor, geometry_policy, workers, worker_bytes,
            lifetime, timings,
        )
    finally:
        lifetime.close()
        if timings is not None:
            timings["materialize_monitor_cpu_s"] = lifetime.cpu_seconds
            timings["materialize_child_cpu_s"] += lifetime.cpu_seconds


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
) -> dict:
    result: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(
        prefix="lumina-vector-material-", dir=Path(lifetime.name).parent,
    ) as directory:
        lifetime.track_data_directory(directory)
        inputs, outputs = [], []
        for index, (_name, data) in enumerate(items):
            source = Path(directory) / f"{index}.json"
            _write_material_input(source, data["slabs"])
            inputs.append(str(source))
            outputs.append(str(Path(directory) / f"{index}.npz"))
        try:
            with ProcessPoolExecutor(
                max_workers=workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_initialize_material_process,
                initargs=(lifetime.name, os.getpid()),
            ) as pool:
                process_cpu = {}
                try:
                    futures = [
                        pool.submit(
                            _build_material_file, source, target, float(scale_factor),
                            geometry_policy.grid_mm if geometry_policy is not None else None,
                            worker_bytes,
                        )
                        for source, target in zip(inputs, outputs)
                    ]
                    for (name, data), future in zip(items, futures):
                        output_path, process_id, cpu_seconds = future.result()
                        process_cpu[process_id] = max(process_cpu.get(process_id, 0.0), cpu_seconds)
                        _accept_result(result, name, data, _read_material_result(output_path))
                except BaseException:  # Process boundary: stop siblings before shutdown waits.
                    _stop_processes(pool)
                    raise
                if timings is not None:
                    timings["materialize_process_count"] = len(process_cpu)
                    timings["materialize_child_cpu_s"] = sum(process_cpu.values())
        except BrokenProcessPool as exc:
            raise RuntimeError("Vector material worker exited unexpectedly") from exc
    return result


def _stop_processes(pool: ProcessPoolExecutor) -> None:
    # Python 3.12 has no public terminate_workers(). Only touch this pool's
    # process objects; the executor retains responsibility for joining them.
    for process in list((getattr(pool, "_processes", None) or {}).values()):
        try:
            if process.is_alive():
                process.kill()
        except (OSError, ValueError):
            pass  # A worker may already have exited or been closed by its owner.
