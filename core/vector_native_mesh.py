"""Optional native acceleration for SVG vector run-length extrusion.

The native path is deliberately opt-in. It accepts a Clipper2-style
``clipper2_batch`` module when present, but preserves the current
Shapely/trimesh extrusion as the fallback for dependency absence, native
errors, empty native meshes, or invalid mesh buffers.
"""

from __future__ import annotations

import importlib
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import trimesh
from shapely import set_precision
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from core.task_parallelism import (
    AdaptiveParallelismPlan,
    resolve_task_parallelism_plan,
    task_memory_headroom_bytes,
    task_parallelism_worker_scope,
)
from core.vector_engine import VectorProcessor, _union_run_group_geometries


NATIVE_CLOSE_DELTA_MM = 0.03
NATIVE_COORD_SCALE = 1_000_000
NATIVE_BATCH_MIN_PARALLEL_ITEMS = 3
NATIVE_BATCH_MIN_PARALLEL_GROUPS = 8
NATIVE_BATCH_FIXED_VALIDATION_BYTES = 384 * 1024**2
NATIVE_BATCH_INPUT_BYTES_PER_POINT = 2 * np.dtype(np.float64).itemsize
NATIVE_BATCH_MESH_BYTES_PER_POINT = 256
NATIVE_BATCH_GROUP_OVERHEAD_BYTES = 64 * 1024
NATIVE_BATCH_RING_OVERHEAD_BYTES = 4 * 1024
NATIVE_BATCH_GEOMETRY_OVERHEAD_BYTES = 1024
NATIVE_SURFACE_AREA_REL_TOL = 0.001
NATIVE_SURFACE_AREA_ABS_TOL_MM2 = 0.01
NATIVE_REQUIRED_GUARD_CAPABILITY = "triangulation_area_guard"
NATIVE_REJECTED_GROUP_REUSE_CAPABILITY = "rejected_group_reuse"
NATIVE_REJECTED_MESH_RETRY_CAPABILITY = "rejected_mesh_retry"
NATIVE_SURFACE_VALIDATION_CAPABILITY = "native_surface_validation"
NATIVE_SPLIT_RETRY_MIN_ORIGINAL_PATHS = 300
NATIVE_SPLIT_RETRY_MAX_ORIGINAL_PATHS_PER_GEOM = 1.15
NATIVE_SPLIT_RETRY_MIN_POLYGONS = 240
NATIVE_SPLIT_RETRY_MAX_PATH_RATIO = 1.2
NATIVE_SPLIT_PARALLEL_MIN_GROUPS = 8_192
NATIVE_SPLIT_PARALLEL_CHUNKS_PER_WORKER = 4
NATIVE_SPLIT_PARALLEL_GROUPS_PER_WORKER = 4_096
NATIVE_SPLIT_PARALLEL_ESTIMATED_WORKER_BYTES = 256 * 1024**2
NATIVE_RETRY_MESH_ACCEPTED = 0
NATIVE_RETRY_MESH_SURFACE_REJECT = 1
NATIVE_RETRY_MESH_EMPTY = 2
NATIVE_MERGED_FALLBACK_MIN_PATHS = 64
NATIVE_MERGED_FALLBACK_MAX_HOLE_RATIO = 0.5


@dataclass(frozen=True)
class NativeVectorMeshResult:
    """Result from optional native vector mesh extrusion.
    可选 native 矢量挤出返回结果。

    Args:
        meshes_by_slot: Mapping compatible with ``VectorProcessor.build_mesh``:
            slot name -> ``{"meshes": list[Trimesh], "mat_id": int}``.
            与 ``VectorProcessor.build_mesh`` 兼容的材质槽到 mesh 列表映射。
        stats: Diagnostic counters/timings for fallback and profiling.
            fallback 与性能诊断统计信息。
    """

    meshes_by_slot: dict[str, dict[str, Any]]
    stats: dict[str, float | int | str]


@dataclass(frozen=True)
class _PreparedNativeGroup:
    key: tuple[int, int, int]
    geoms: list
    paths: list
    path_count: int


@dataclass(frozen=True)
class NativeBatchCost:
    """Monotonic, overflow-safe memory signal for one semantic batch.
    单个语义批次的单调、溢出安全内存估算信号。

    Args:
        source_geometry_count: Top-level source geometry references.
            顶层源几何引用数量。
        point_count: Coordinate points counted without geometry mutation.
            不修改几何前提下统计的坐标点数量。
        ring_count: Exterior and interior ring count. 外环与内环总数。
        hole_count: Interior ring count. 洞环数量。
        group_count: Semantic run-group count. 语义 run-group 数量。
        input_coordinate_bytes: Estimated packed coordinate bytes.
            估算的打包坐标字节数。
        expected_mesh_buffer_bytes: Estimated native mesh/result bytes.
            估算的原生网格及结果缓冲字节数。
        estimated_bytes: Saturated total admission estimate.
            饱和运算后的总准入估算字节数。
    """

    source_geometry_count: int
    point_count: int
    ring_count: int
    hole_count: int
    group_count: int
    input_coordinate_bytes: int
    expected_mesh_buffer_bytes: int
    estimated_bytes: int


@dataclass(frozen=True)
class _PreparedNativeBatch:
    index: int
    height: float
    z_bot: float
    groups: tuple[_PreparedNativeGroup, ...]
    no_path_jobs: tuple[tuple[tuple[int, int, int], list], ...]
    cost: NativeBatchCost


@dataclass(frozen=True)
class _NativeGroupOutcome:
    status: str
    rejection_counter: str
    mesh_arrays: tuple[np.ndarray, np.ndarray] | None
    mesh: trimesh.Trimesh | tuple[np.ndarray, np.ndarray] | None
    retry_groups: list | None = None
    retry_record: Any | None = None


@dataclass(frozen=True)
class _ComputedNativeBatch:
    call_error: str
    outcomes: tuple[_NativeGroupOutcome, ...]
    extra_mesh_count: int
    native_seconds: float
    mesh_convert_seconds: float
    surface_validation_seconds: float
    surface_checked: int
    surface_rejects: int


def _saturating_add_bytes(left: int, right: int) -> int:
    """Add non-negative byte counts while capping at ``sys.maxsize``."""

    left_value = max(0, min(sys.maxsize, int(left)))
    right_value = max(0, min(sys.maxsize, int(right)))
    if left_value >= sys.maxsize - right_value:
        return sys.maxsize
    return left_value + right_value


def _saturating_multiply_bytes(value: int, factor: int) -> int:
    """Multiply non-negative byte counts while capping at ``sys.maxsize``."""

    value_int = max(0, min(sys.maxsize, int(value)))
    factor_int = max(0, min(sys.maxsize, int(factor)))
    if value_int == 0 or factor_int == 0:
        return 0
    if value_int > sys.maxsize // factor_int:
        return sys.maxsize
    return value_int * factor_int


def _native_batch_cost_from_counts(
    *,
    source_geometry_count: int,
    point_count: int,
    ring_count: int,
    hole_count: int,
    group_count: int,
) -> NativeBatchCost:
    """Build one cost record from already-counted immutable topology."""

    input_coordinate_bytes = _saturating_multiply_bytes(
        point_count,
        NATIVE_BATCH_INPUT_BYTES_PER_POINT,
    )
    expected_mesh_buffer_bytes = _saturating_add_bytes(
        _saturating_multiply_bytes(
            point_count,
            NATIVE_BATCH_MESH_BYTES_PER_POINT,
        ),
        _saturating_add_bytes(
            _saturating_multiply_bytes(
                group_count,
                NATIVE_BATCH_GROUP_OVERHEAD_BYTES,
            ),
            _saturating_add_bytes(
                _saturating_multiply_bytes(
                    ring_count,
                    NATIVE_BATCH_RING_OVERHEAD_BYTES,
                ),
                _saturating_multiply_bytes(
                    source_geometry_count,
                    NATIVE_BATCH_GEOMETRY_OVERHEAD_BYTES,
                ),
            ),
        ),
    )
    dynamic_bytes = _saturating_add_bytes(
        input_coordinate_bytes,
        expected_mesh_buffer_bytes,
    )
    estimated_bytes = (
        _saturating_add_bytes(
            NATIVE_BATCH_FIXED_VALIDATION_BYTES,
            dynamic_bytes,
        )
        if group_count > 0
        else 0
    )
    return NativeBatchCost(
        source_geometry_count=max(0, int(source_geometry_count)),
        point_count=max(0, int(point_count)),
        ring_count=max(0, int(ring_count)),
        hole_count=max(0, int(hole_count)),
        group_count=max(0, int(group_count)),
        input_coordinate_bytes=input_coordinate_bytes,
        expected_mesh_buffer_bytes=expected_mesh_buffer_bytes,
        estimated_bytes=estimated_bytes,
    )


def _estimate_native_jobs_cost(
    jobs: list[tuple[tuple[int, int, int], list]],
) -> NativeBatchCost:
    """Count Shapely topology without unioning or mutating source geometry."""

    source_geometry_count = 0
    point_count = 0
    ring_count = 0
    hole_count = 0
    estimation_failed = False
    for _key, geoms in jobs:
        source_geometry_count += len(geoms)
        for geom in geoms:
            try:
                for polygon in _iter_polygons(geom):
                    exterior_points = len(polygon.exterior.coords)
                    point_count += exterior_points
                    ring_count += 1
                    for interior in polygon.interiors:
                        point_count += len(interior.coords)
                        ring_count += 1
                        hole_count += 1
            except (AttributeError, TypeError, RuntimeError, ValueError):
                estimation_failed = True
    if estimation_failed:
        point_count = sys.maxsize
    return _native_batch_cost_from_counts(
        source_geometry_count=source_geometry_count,
        point_count=point_count,
        ring_count=ring_count,
        hole_count=hole_count,
        group_count=len(jobs),
    )


def _refine_native_batch_cost(
    estimated_cost: NativeBatchCost,
    groups: list[_PreparedNativeGroup],
) -> NativeBatchCost:
    """Replace cheap coordinate counts with the packed path counts."""

    point_count = sum(
        len(path)
        for group in groups
        for path in group.paths
    )
    ring_count = sum(len(group.paths) for group in groups)
    return _native_batch_cost_from_counts(
        source_geometry_count=estimated_cost.source_geometry_count,
        point_count=point_count,
        ring_count=ring_count,
        hole_count=estimated_cost.hole_count,
        group_count=estimated_cost.group_count,
    )


def _representative_batch_bytes(
    costs: list[NativeBatchCost],
) -> int:
    """Ignore isolated outliers while retaining a conservative worker cost."""

    estimates = sorted(
        max(1, int(cost.estimated_bytes))
        for cost in costs
        if cost.group_count > 0
    )
    if not estimates:
        return NATIVE_BATCH_FIXED_VALIDATION_BYTES
    return estimates[len(estimates) // 2]


def _resolve_native_batch_plan(
    *,
    batch_count: int,
    group_count: int,
    representative_batch_bytes: int,
) -> AdaptiveParallelismPlan:
    """Resolve a bounded plan for independent native mesh batches."""

    return resolve_task_parallelism_plan(
        "vector",
        work_items=batch_count,
        min_parallel_items=NATIVE_BATCH_MIN_PARALLEL_ITEMS,
        hard_max_workers=None,
        work_units=group_count,
        min_parallel_work_units=NATIVE_BATCH_MIN_PARALLEL_GROUPS,
        estimated_worker_bytes=max(1, int(representative_batch_bytes)),
    )


def _prepare_native_batch(
    *,
    index: int,
    jobs: list[tuple[tuple[int, int, int], list]],
    height: float,
    z_bot: float,
    stats: dict[str, float | int | str],
    path_cache: dict[int, tuple[Any, list[list[tuple[float, float]]]]],
    estimated_cost: NativeBatchCost | None = None,
) -> _PreparedNativeBatch:
    """Pack one batch serially while preserving the shared path cache."""

    started = time.perf_counter()
    cheap_cost = estimated_cost or _estimate_native_jobs_cost(jobs)
    groups = []
    no_path_jobs = []
    for key, geoms in jobs:
        paths = []
        for geom in geoms:
            paths.extend(_geometry_to_paths_cached(geom, path_cache, stats))
        if not paths:
            no_path_jobs.append((key, geoms))
            continue
        groups.append(
            _PreparedNativeGroup(
                key=key,
                geoms=geoms,
                paths=paths,
                path_count=len(paths),
            )
        )
        stats["native_input_paths"] = int(stats["native_input_paths"]) + len(
            paths
        )
    stats["native_group_count"] = int(stats["native_group_count"]) + len(
        groups
    )
    stats["pack_seconds"] = float(stats["pack_seconds"]) + (
        time.perf_counter() - started
    )
    return _PreparedNativeBatch(
        index=index,
        height=float(height),
        z_bot=float(z_bot),
        groups=tuple(groups),
        no_path_jobs=tuple(no_path_jobs),
        cost=_refine_native_batch_cost(cheap_cost, groups),
    )


def _compute_native_batch(
    module,
    batch: _PreparedNativeBatch,
    *,
    scale_factor: float,
    validate_surface: bool,
) -> _ComputedNativeBatch:
    """Run native extrusion and unchanged surface validation for one batch."""

    with task_parallelism_worker_scope():
        try:
            native_started = time.perf_counter()
            (
                native_meshes,
                rejected_groups,
                retry_records,
                primary_statuses,
            ) = _run_native_mesh_call(
                module=module,
                groups=[group.paths for group in batch.groups],
                height=batch.height,
                z_bot=batch.z_bot,
                scale_factor=scale_factor,
            )
            native_seconds = time.perf_counter() - native_started
        except Exception as exc:
            return _ComputedNativeBatch(
                call_error=type(exc).__name__,
                outcomes=(),
                extra_mesh_count=0,
                native_seconds=0.0,
                mesh_convert_seconds=0.0,
                surface_validation_seconds=0.0,
                surface_checked=0,
                surface_rejects=0,
            )

        convert_started = time.perf_counter()
        native_mesh_list = list(native_meshes or [])
        outcomes = []
        surface_validation_seconds = 0.0
        surface_checked = 0
        surface_rejects = 0
        for index, group in enumerate(batch.groups):
            if index >= len(native_mesh_list):
                outcomes.append(
                    _NativeGroupOutcome(
                        status="missing_native_mesh",
                        rejection_counter="native_invalid_meshes",
                        mesh_arrays=None,
                        mesh=None,
                    )
                )
                continue

            native_mesh = native_mesh_list[index]
            mesh_arrays = _native_mesh_arrays(native_mesh)
            primary_status = (
                int(primary_statuses[index])
                if index < len(primary_statuses)
                else NATIVE_RETRY_MESH_ACCEPTED
            )
            if mesh_arrays is None:
                if primary_status == NATIVE_RETRY_MESH_SURFACE_REJECT:
                    surface_checked += 1
                    surface_rejects += 1
                    outcomes.append(
                        _NativeGroupOutcome(
                            status="surface_reject",
                            rejection_counter="",
                            mesh_arrays=None,
                            mesh=None,
                        )
                    )
                    continue
                retry_groups = (
                    rejected_groups[index]
                    if index < len(rejected_groups)
                    and rejected_groups[index]
                    else None
                )
                retry_record = (
                    retry_records[index]
                    if index < len(retry_records)
                    else None
                )
                outcomes.append(
                    _NativeGroupOutcome(
                        status="native_rejected",
                        rejection_counter=_native_mesh_rejection_reason(
                            native_mesh
                        ),
                        mesh_arrays=None,
                        mesh=None,
                        retry_groups=retry_groups,
                        retry_record=retry_record,
                    )
                )
                continue

            mesh = None
            if validate_surface:
                if len(primary_statuses) > 0:
                    surface_ok = True
                    surface_checked += 1
                else:
                    validation_started = time.perf_counter()
                    surface_ok = _native_surface_area_matches_arrays(
                        mesh_arrays,
                        group.geoms,
                        height=batch.height,
                        scale_factor=scale_factor,
                    )
                    surface_validation_seconds += (
                        time.perf_counter() - validation_started
                    )
                    surface_checked += 1
                if not surface_ok:
                    surface_rejects += 1
                    outcomes.append(
                        _NativeGroupOutcome(
                            status="surface_reject",
                            rejection_counter="",
                            mesh_arrays=mesh_arrays,
                            mesh=mesh,
                        )
                    )
                    continue
                mesh = mesh_arrays

            outcomes.append(
                _NativeGroupOutcome(
                    status="accepted",
                    rejection_counter="",
                    mesh_arrays=mesh_arrays,
                    mesh=mesh,
                )
            )

        return _ComputedNativeBatch(
            call_error="",
            outcomes=tuple(outcomes),
            extra_mesh_count=max(
                0,
                len(native_mesh_list) - len(batch.groups),
            ),
            native_seconds=native_seconds,
            mesh_convert_seconds=time.perf_counter() - convert_started,
            surface_validation_seconds=surface_validation_seconds,
            surface_checked=surface_checked,
            surface_rejects=surface_rejects,
        )


def _run_native_mesh_call(
    *,
    module,
    groups,
    height: float,
    z_bot: float,
    scale_factor: float,
):
    """Run one native mesh call and optionally retain rejected merged groups."""

    reuse_rejected_meshes = _native_module_has_capability(
        module,
        NATIVE_REJECTED_MESH_RETRY_CAPABILITY,
    )
    reuse_rejected_groups = _native_module_has_capability(
        module,
        NATIVE_REJECTED_GROUP_REUSE_CAPABILITY,
    )
    native_surface_validation = _native_module_has_capability(
        module,
        NATIVE_SURFACE_VALIDATION_CAPABILITY,
    )
    validate_surfaces = _surface_validation_enabled()
    native_result = module.merge_run_groups_to_meshes(
        groups,
        close_delta_mm=NATIVE_CLOSE_DELTA_MM,
        scale=NATIVE_COORD_SCALE,
        height=height,
        z_offset=z_bot,
        xy_scale=scale_factor,
        **(
            {
                "return_rejected_meshes": True,
                "validate_retry_surfaces": (
                    validate_surfaces and native_surface_validation
                ),
                "validate_primary_surfaces": (
                    validate_surfaces and native_surface_validation
                ),
                "surface_rel_tol": _surface_area_rel_tolerance(),
                "surface_abs_tol": NATIVE_SURFACE_AREA_ABS_TOL_MM2,
            }
            if reuse_rejected_meshes
            else (
                {"return_rejected_groups": True}
                if reuse_rejected_groups
                else {}
            )
        ),
    )
    if not reuse_rejected_meshes and not reuse_rejected_groups:
        return native_result, (), (), ()
    if reuse_rejected_meshes:
        if not isinstance(native_result, tuple) or len(native_result) != 3:
            raise TypeError("native rejected-mesh retry returned an invalid result")
        native_meshes, primary_statuses, retry_records = native_result
        if validate_surfaces and not native_surface_validation:
            retry_records = ()
        if not (validate_surfaces and native_surface_validation):
            primary_statuses = ()
        return native_meshes, (), retry_records, primary_statuses
    if not isinstance(native_result, tuple) or len(native_result) != 2:
        raise TypeError("native rejected-group reuse returned an invalid result")
    native_meshes, rejected_groups = native_result
    return native_meshes, rejected_groups, (), ()


def is_native_vector_mesh_enabled(processor: Any | None = None) -> bool:
    """Return whether optional native vector meshing should be attempted.
    返回是否应尝试可选 native 矢量网格路径。

    The default remains disabled. Callers may opt in with either
    ``processor.enable_native_vector_mesh = True`` or
    ``LUMINA_VECTOR_NATIVE_MESH=1``.
    默认关闭；可通过处理器属性或环境变量显式开启。
    """

    if processor is not None and bool(getattr(processor, "enable_native_vector_mesh", False)):
        return True
    return str(os.environ.get("LUMINA_VECTOR_NATIVE_MESH", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def run_length_extrude_native_hybrid(
    *,
    matched_shapes,
    num_layers: int,
    layer_h: float,
    num_channels: int,
    slot_names,
    scale_factor: float,
    extrude_cache=None,
    face_up: bool = False,
    optical_z_base: float = 0.0,
    native_module=None,
) -> NativeVectorMeshResult:
    """Extrude SVG run groups through an optional native mesh module.
    通过可选 native 模块挤出 SVG run-group，并对失败组回退旧链路。

    Args:
        matched_shapes: Vector shapes with ``geometry`` and per-layer
            ``recipe`` entries.
        num_layers: Number of color layers to inspect.
        layer_h: Layer height in millimeters.
        num_channels: Number of material channels.
        slot_names: Material slot names by channel id.
        scale_factor: SVG user-unit to millimeter scale.
        extrude_cache: Existing Python extrusion cache used by fallback groups.
        face_up: Whether layer order is inverted for face-up workflows.
        optical_z_base: Z base used by face-up workflows.
        native_module: Optional injected module for tests. When omitted,
            ``clipper2_batch`` is imported lazily.

    Returns:
        ``NativeVectorMeshResult`` containing meshes and diagnostic stats.
    """

    stats = _empty_stats()
    module = native_module if native_module is not None else _load_native_module(stats)
    if module is None or not hasattr(module, "merge_run_groups_to_meshes"):
        raise RuntimeError("clipper2_batch.merge_run_groups_to_meshes is unavailable")

    run_groups = _build_run_groups(
        matched_shapes=matched_shapes,
        num_layers=num_layers,
        num_channels=num_channels,
        slot_names=slot_names,
    )
    stats["run_group_count"] = len(run_groups)
    try:
        source_geometry_count = len(matched_shapes)
    except TypeError:
        source_geometry_count = len(
            {
                id(geom)
                for geoms in run_groups.values()
                for geom in geoms
            }
        )
    stats["native_parallel_source_geometry_count"] = source_geometry_count

    jobs_by_height_z: dict[tuple[float, float], list[tuple[tuple[int, int, int], list]]] = defaultdict(list)
    for key, geoms in run_groups.items():
        _, run_start, run_end = key
        if face_up:
            inv_start = (num_layers - 1) - run_end
            inv_end = (num_layers - 1) - run_start
            z_bot = float(optical_z_base) + inv_start * float(layer_h)
            height = (inv_end - inv_start + 1) * float(layer_h)
        else:
            z_bot = run_start * float(layer_h)
            height = (run_end - run_start + 1) * float(layer_h)
        jobs_by_height_z[(round(float(height), 8), round(float(z_bot), 8))].append((key, geoms))

    meshes_by_slot: dict[str, dict[str, Any]] = {}
    if not _native_module_has_triangulation_area_guard(module):
        stats["native_capability_error"] = f"{NATIVE_REQUIRED_GUARD_CAPABILITY}_missing"
        stats["native_triangulation_area_guard"] = "missing"
        for (height, z_bot), jobs in jobs_by_height_z.items():
            for key, geoms in jobs:
                _fallback_key(
                    key,
                    geoms,
                    height=float(height),
                    z_bot=float(z_bot),
                    scale_factor=float(scale_factor),
                    slot_names=slot_names,
                    meshes_by_slot=meshes_by_slot,
                    extrude_cache=extrude_cache,
                    stats=stats,
                    reason="capability_missing",
                )
        return NativeVectorMeshResult(meshes_by_slot=meshes_by_slot, stats=stats)

    stats["native_triangulation_area_guard"] = "present"
    batch_items = list(jobs_by_height_z.items())
    cheap_batch_costs = [
        _estimate_native_jobs_cost(jobs)
        for (_height_z, jobs) in batch_items
    ]
    representative_batch_bytes = _representative_batch_bytes(
        cheap_batch_costs,
    )
    parallelism_plan = _resolve_native_batch_plan(
        batch_count=len(batch_items),
        group_count=len(run_groups),
        representative_batch_bytes=representative_batch_bytes,
    )
    worker_count = parallelism_plan.workers
    _record_native_parallelism_plan(stats, parallelism_plan)
    stats["native_parallel_workers"] = worker_count
    stats["native_parallel_batch_count"] = len(batch_items)
    stats["native_parallel_max_estimated_batch_bytes"] = max(
        (cost.estimated_bytes for cost in cheap_batch_costs),
        default=0,
    )
    if worker_count > 1:
        parallel_result, parallel_error = _try_run_native_batches_parallel(
            module=module,
            batch_items=batch_items,
            run_group_count=len(run_groups),
            source_geometry_count=source_geometry_count,
            parallelism_plan=parallelism_plan,
            cheap_batch_costs=cheap_batch_costs,
            representative_batch_bytes=representative_batch_bytes,
            scale_factor=float(scale_factor),
            slot_names=slot_names,
            extrude_cache=extrude_cache,
        )
        if parallel_result is not None:
            return parallel_result
        stats["native_parallel_error"] = parallel_error
        stats["native_parallel_requested_workers"] = worker_count
        stats["native_parallel_workers"] = 1

    path_cache: dict[int, tuple[Any, list[list[tuple[float, float]]]]] = {}
    for (height, z_bot), jobs in batch_items:
        _run_native_job_batch(
            module=module,
            jobs=jobs,
            height=float(height),
            z_bot=float(z_bot),
            scale_factor=float(scale_factor),
            slot_names=slot_names,
            meshes_by_slot=meshes_by_slot,
            extrude_cache=extrude_cache,
            stats=stats,
            path_cache=path_cache,
        )

    _flush_native_buffers(meshes_by_slot, stats)
    return NativeVectorMeshResult(meshes_by_slot=meshes_by_slot, stats=stats)


def _empty_stats() -> dict[str, float | int | str]:
    return {
        "run_group_count": 0,
        "native_group_count": 0,
        "native_input_paths": 0,
        "native_path_cache_hits": 0,
        "native_path_cache_misses": 0,
        "pack_seconds": 0.0,
        "native_seconds": 0.0,
        "mesh_convert_seconds": 0.0,
        "fallback_seconds": 0.0,
        "native_empty_meshes": 0,
        "native_invalid_meshes": 0,
        "native_extra_meshes": 0,
        "native_surface_checked": 0,
        "native_surface_rejects": 0,
        "surface_validation_seconds": 0.0,
        "native_meshes": 0,
        "native_coalesced_meshes": 0,
        "native_coalesced_slots": 0,
        "native_output_meshes": 0,
        "native_split_retries": 0,
        "native_split_group_count": 0,
        "native_split_meshes": 0,
        "native_split_fallback_groups": 0,
        "native_rejected_groups_reused": 0,
        "native_rejected_mesh_retries_reused": 0,
        "native_split_parallel_workers": 1,
        "native_split_parallel_batch_count": 0,
        "native_split_parallel_seconds": 0.0,
        "native_merged_fallback_groups": 0,
        "native_merged_fallback_polygons": 0,
        "native_merged_fallback_input_paths": 0,
        "native_merged_fallback_input_holes": 0,
        "native_merged_fallback_skipped_groups": 0,
        "fallback_groups": 0,
        "native_capability_error": "",
        "native_triangulation_area_guard": "",
        "native_parallel_workers": 1,
        "native_parallel_batch_count": 0,
        "native_parallel_source_geometry_count": 0,
        "native_parallel_limit_reason": "",
        "native_parallel_effective_cpu": 1,
        "native_parallel_outer_demand": 1,
        "native_parallel_cpu_fair_share": 1,
        "native_parallel_memory_ceiling": 1,
        "native_parallel_demand_fallback": False,
        "native_parallel_inflight_limit": 1,
        "native_parallel_max_estimated_batch_bytes": 0,
        "native_parallel_oversized_serial_batches": 0,
        "native_parallel_wall_seconds": 0.0,
        "native_parallel_error": "",
        "native_parallel_requested_workers": 1,
    }


def _record_native_parallelism_plan(
    stats: dict[str, float | int | str],
    plan: AdaptiveParallelismPlan,
) -> None:
    """Store only bounded scalar scheduler diagnostics."""

    stats["native_parallel_limit_reason"] = str(plan.limiting_reason)[:64]
    stats["native_parallel_effective_cpu"] = int(
        plan.effective_cpu_capacity,
    )
    stats["native_parallel_cpu_topology"] = str(plan.cpu_topology)[:64]
    stats["native_parallel_cpu_scheduling_policy"] = str(
        plan.cpu_scheduling_policy,
    )[:64]
    if plan.performance_cpu_capacity is not None:
        stats["native_parallel_performance_cpu"] = int(
            plan.performance_cpu_capacity,
        )
    stats["native_parallel_outer_demand"] = int(plan.outer_demand)
    stats["native_parallel_cpu_fair_share"] = int(
        plan.cpu_fair_share_ceiling,
    )
    stats["native_parallel_memory_ceiling"] = int(plan.memory_ceiling)
    stats["native_parallel_demand_fallback"] = bool(
        plan.demand_snapshot_fallback,
    )


def _load_native_module(stats: dict[str, float | int | str]):
    try:
        return importlib.import_module("clipper2_batch")
    except Exception as exc:
        stats["native_import_error"] = type(exc).__name__
        return None


def _native_module_capabilities(module) -> dict:
    capabilities_fn = getattr(module, "native_mesh_capabilities", None)
    if not callable(capabilities_fn):
        return {}
    try:
        capabilities = capabilities_fn()
    except Exception:
        return {}
    if not isinstance(capabilities, dict):
        return {}
    return capabilities


def _native_module_has_capability(module, capability: str) -> bool:
    return bool(_native_module_capabilities(module).get(capability))


def _native_module_has_triangulation_area_guard(module) -> bool:
    return _native_module_has_capability(
        module,
        NATIVE_REQUIRED_GUARD_CAPABILITY,
    )


def _build_run_groups(*, matched_shapes, num_layers: int, num_channels: int, slot_names) -> dict[tuple[int, int, int], list]:
    run_groups: dict[tuple[int, int, int], list] = {}
    for item in matched_shapes:
        geom = item["geometry"]
        recipe = item["recipe"]
        if geom is None or geom.is_empty:
            continue
        layers_to_use = min(int(num_layers), len(recipe))
        runs_by_channel = VectorProcessor._build_channel_runs(recipe, layers_to_use, int(num_channels))
        for ch, runs in runs_by_channel.items():
            if ch >= len(slot_names):
                continue
            for run_start, run_end in runs:
                run_groups.setdefault((int(ch), int(run_start), int(run_end)), []).append(geom)
    return run_groups


def _empty_computed_native_batch(
    batch: _PreparedNativeBatch,
) -> _ComputedNativeBatch:
    return _ComputedNativeBatch(
        call_error="",
        outcomes=(),
        extra_mesh_count=0,
        native_seconds=0.0,
        mesh_convert_seconds=0.0,
        surface_validation_seconds=0.0,
        surface_checked=0,
        surface_rejects=0,
    )


def _commit_computed_native_batch(
    *,
    module,
    batch: _PreparedNativeBatch,
    computed: _ComputedNativeBatch,
    scale_factor: float,
    slot_names,
    meshes_by_slot: dict[str, dict[str, Any]],
    extrude_cache,
    stats: dict[str, float | int | str],
    path_cache: dict[int, tuple[Any, list[list[tuple[float, float]]]]],
) -> None:
    """Commit a computed batch on the caller thread in original group order."""

    if not computed.call_error and len(computed.outcomes) != len(batch.groups):
        raise RuntimeError("native batch outcome count mismatch")

    for key, geoms in batch.no_path_jobs:
        _fallback_key(
            key,
            geoms,
            height=batch.height,
            z_bot=batch.z_bot,
            scale_factor=scale_factor,
            slot_names=slot_names,
            meshes_by_slot=meshes_by_slot,
            extrude_cache=extrude_cache,
            stats=stats,
            reason="no_paths",
        )

    stats["native_seconds"] = float(stats["native_seconds"]) + (
        computed.native_seconds
    )
    stats["mesh_convert_seconds"] = float(stats["mesh_convert_seconds"]) + (
        computed.mesh_convert_seconds
    )
    stats["surface_validation_seconds"] = float(
        stats["surface_validation_seconds"]
    ) + computed.surface_validation_seconds
    stats["native_surface_checked"] = int(stats["native_surface_checked"]) + (
        computed.surface_checked
    )
    stats["native_surface_rejects"] = int(stats["native_surface_rejects"]) + (
        computed.surface_rejects
    )

    if computed.call_error:
        stats["native_call_error"] = computed.call_error
        for group in batch.groups:
            _fallback_key(
                group.key,
                group.geoms,
                height=batch.height,
                z_bot=batch.z_bot,
                scale_factor=scale_factor,
                slot_names=slot_names,
                meshes_by_slot=meshes_by_slot,
                extrude_cache=extrude_cache,
                stats=stats,
                reason="native_call_error",
            )
        return

    stats["native_extra_meshes"] = int(stats["native_extra_meshes"]) + (
        computed.extra_mesh_count
    )
    for group, outcome in zip(batch.groups, computed.outcomes):
        key = group.key
        ch = key[0]
        slot_name = slot_names[ch]
        _ensure_slot(meshes_by_slot, slot_name, ch)

        if outcome.status == "missing_native_mesh":
            stats["native_invalid_meshes"] = int(
                stats["native_invalid_meshes"]
            ) + 1
            _fallback_key(
                key,
                group.geoms,
                height=batch.height,
                z_bot=batch.z_bot,
                scale_factor=scale_factor,
                slot_names=slot_names,
                meshes_by_slot=meshes_by_slot,
                extrude_cache=extrude_cache,
                stats=stats,
                reason="missing_native_mesh",
            )
            continue

        if outcome.status == "native_rejected":
            counter_name = outcome.rejection_counter
            stats[counter_name] = int(stats[counter_name]) + 1
            if _retry_native_group_as_reference_polygons(
                module=module,
                key=key,
                geoms=group.geoms,
                original_path_count=group.path_count,
                height=batch.height,
                z_bot=batch.z_bot,
                scale_factor=scale_factor,
                slot_names=slot_names,
                meshes_by_slot=meshes_by_slot,
                extrude_cache=extrude_cache,
                stats=stats,
                path_cache=path_cache,
                prepared_retry_groups=outcome.retry_groups,
                prepared_retry_record=outcome.retry_record,
            ):
                continue
            _fallback_key(
                key,
                group.geoms,
                height=batch.height,
                z_bot=batch.z_bot,
                scale_factor=scale_factor,
                slot_names=slot_names,
                meshes_by_slot=meshes_by_slot,
                extrude_cache=extrude_cache,
                stats=stats,
                reason=_fallback_reason_for_native_rejection(counter_name),
                native_module=module,
                path_cache=path_cache,
                input_path_count=group.path_count,
            )
            continue

        if outcome.status == "invalid_native_mesh":
            stats["native_invalid_meshes"] = int(
                stats["native_invalid_meshes"]
            ) + 1
            _fallback_key(
                key,
                group.geoms,
                height=batch.height,
                z_bot=batch.z_bot,
                scale_factor=scale_factor,
                slot_names=slot_names,
                meshes_by_slot=meshes_by_slot,
                extrude_cache=extrude_cache,
                stats=stats,
                reason="invalid_native_mesh",
            )
            continue

        if outcome.status == "surface_reject":
            _fallback_key(
                key,
                group.geoms,
                height=batch.height,
                z_bot=batch.z_bot,
                scale_factor=scale_factor,
                slot_names=slot_names,
                meshes_by_slot=meshes_by_slot,
                extrude_cache=extrude_cache,
                stats=stats,
                reason="surface_reject",
            )
            continue

        mesh_arrays = outcome.mesh_arrays
        if outcome.status != "accepted" or mesh_arrays is None:
            raise RuntimeError("invalid computed native mesh outcome")
        stats["native_meshes"] = int(stats["native_meshes"]) + 1
        if outcome.mesh is not None:
            meshes_by_slot[slot_name]["meshes"].append(outcome.mesh)
            stats["native_output_meshes"] = int(
                stats["native_output_meshes"]
            ) + 1
        else:
            _append_native_buffer(
                meshes_by_slot,
                slot_name,
                ch,
                mesh_arrays,
            )


def _try_run_native_batches_parallel(
    *,
    module,
    batch_items,
    run_group_count: int,
    source_geometry_count: int,
    parallelism_plan: AdaptiveParallelismPlan,
    cheap_batch_costs: list[NativeBatchCost],
    representative_batch_bytes: int,
    scale_factor: float,
    slot_names,
    extrude_cache,
) -> tuple[NativeVectorMeshResult | None, str]:
    """Run a memory-bounded preparation window with ordered owner commits."""

    stats = _empty_stats()
    worker_count = parallelism_plan.workers
    stats["run_group_count"] = run_group_count
    stats["native_parallel_source_geometry_count"] = source_geometry_count
    stats["native_triangulation_area_guard"] = "present"
    stats["native_parallel_workers"] = worker_count
    stats["native_parallel_requested_workers"] = worker_count
    stats["native_parallel_batch_count"] = len(batch_items)
    _record_native_parallelism_plan(stats, parallelism_plan)
    stats["native_parallel_max_estimated_batch_bytes"] = max(
        (cost.estimated_bytes for cost in cheap_batch_costs),
        default=0,
    )
    meshes_by_slot: dict[str, dict[str, Any]] = {}
    path_cache: dict[
        int,
        tuple[Any, list[list[tuple[float, float]]]],
    ] = {}
    local_extrude_cache = dict(extrude_cache) if extrude_cache is not None else None

    try:
        if len(cheap_batch_costs) != len(batch_items):
            raise RuntimeError("native batch estimate count mismatch")
        available_memory_bytes = max(
            0,
            int(parallelism_plan.available_memory_bytes or 0),
        )
        usable_memory_bytes = max(
            0,
            available_memory_bytes
            - task_memory_headroom_bytes(available_memory_bytes),
        )
        per_task_memory_budget_bytes = usable_memory_bytes // max(
            1,
            parallelism_plan.outer_demand,
        )
        memory_window_limit = max(
            1,
            per_task_memory_budget_bytes
            // max(1, int(representative_batch_bytes)),
        )
        window_limit = min(
            len(batch_items),
            worker_count + 1,
            memory_window_limit,
        )
        stats["native_parallel_inflight_limit"] = max(1, window_limit)
        validate_surface = _surface_validation_enabled()
        parallel_started = time.perf_counter()
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="lumina-vector-native",
        ) as executor:
            next_prepare_index = 0
            next_commit_index = 0
            in_flight: dict[
                int,
                tuple[_PreparedNativeBatch, Future | None, str],
            ] = {}
            live_estimated_bytes = 0

            while next_commit_index < len(batch_items):
                while (
                    next_prepare_index < len(batch_items)
                    and len(in_flight) < max(1, window_limit)
                ):
                    cheap_cost = cheap_batch_costs[next_prepare_index]
                    projected_cheap_bytes = _saturating_add_bytes(
                        live_estimated_bytes,
                        cheap_cost.estimated_bytes,
                    )
                    if (
                        in_flight
                        and projected_cheap_bytes
                        > per_task_memory_budget_bytes
                    ):
                        break

                    (height, z_bot), jobs = batch_items[next_prepare_index]
                    batch = _prepare_native_batch(
                        index=next_prepare_index,
                        jobs=jobs,
                        height=float(height),
                        z_bot=float(z_bot),
                        stats=stats,
                        path_cache=path_cache,
                        estimated_cost=cheap_cost,
                    )
                    stats["native_parallel_max_estimated_batch_bytes"] = max(
                        int(
                            stats[
                                "native_parallel_max_estimated_batch_bytes"
                            ]
                        ),
                        batch.cost.estimated_bytes,
                    )
                    projected_refined_bytes = _saturating_add_bytes(
                        live_estimated_bytes,
                        batch.cost.estimated_bytes,
                    )
                    individually_oversized = (
                        batch.cost.estimated_bytes
                        > per_task_memory_budget_bytes
                    )
                    future: Future | None = None
                    mode = "empty"
                    if batch.groups and individually_oversized:
                        mode = "oversized"
                    elif batch.groups and (
                        in_flight
                        and projected_refined_bytes
                        > per_task_memory_budget_bytes
                    ):
                        mode = "deferred"
                    elif batch.groups:
                        mode = "future"
                        future = executor.submit(
                            _compute_native_batch,
                            module,
                            batch,
                            scale_factor=scale_factor,
                            validate_surface=validate_surface,
                        )
                    in_flight[batch.index] = (batch, future, mode)
                    live_estimated_bytes = projected_refined_bytes
                    next_prepare_index += 1
                    if mode in {"oversized", "deferred"}:
                        break

                entry = in_flight.get(next_commit_index)
                if entry is None:
                    raise RuntimeError("native batch commit window stalled")
                batch, future, mode = entry
                if mode == "oversized":
                    stats["native_parallel_oversized_serial_batches"] = int(
                        stats["native_parallel_oversized_serial_batches"]
                    ) + 1
                    computed = _compute_native_batch(
                        module,
                        batch,
                        scale_factor=scale_factor,
                        validate_surface=validate_surface,
                    )
                elif mode == "deferred":
                    future = executor.submit(
                        _compute_native_batch,
                        module,
                        batch,
                        scale_factor=scale_factor,
                        validate_surface=validate_surface,
                    )
                    computed = future.result()
                elif mode == "future" and future is not None:
                    computed = future.result()
                elif mode == "empty":
                    computed = _empty_computed_native_batch(batch)
                else:
                    raise RuntimeError("invalid native batch execution mode")

                _commit_computed_native_batch(
                    module=module,
                    batch=batch,
                    computed=computed,
                    scale_factor=scale_factor,
                    slot_names=slot_names,
                    meshes_by_slot=meshes_by_slot,
                    extrude_cache=local_extrude_cache,
                    stats=stats,
                    path_cache=path_cache,
                )
                del in_flight[next_commit_index]
                live_estimated_bytes = 0
                for live_batch, _live_future, _live_mode in in_flight.values():
                    live_estimated_bytes = _saturating_add_bytes(
                        live_estimated_bytes,
                        live_batch.cost.estimated_bytes,
                    )
                next_commit_index += 1
                del batch, computed, entry, future, mode
        stats["native_parallel_wall_seconds"] = (
            time.perf_counter() - parallel_started
        )

        _flush_native_buffers(meshes_by_slot, stats)
        if extrude_cache is not None and local_extrude_cache is not None:
            extrude_cache.update(local_extrude_cache)
    except Exception as exc:
        return None, type(exc).__name__

    return NativeVectorMeshResult(
        meshes_by_slot=meshes_by_slot,
        stats=stats,
    ), ""


def _run_native_job_batch(
    *,
    module,
    jobs: list[tuple[tuple[int, int, int], list]],
    height: float,
    z_bot: float,
    scale_factor: float,
    slot_names,
    meshes_by_slot: dict[str, dict[str, Any]],
    extrude_cache,
    stats: dict[str, float | int | str],
    path_cache: dict[int, tuple[Any, list[list[tuple[float, float]]]]] | None,
) -> None:
    t0 = time.perf_counter()
    native_groups = []
    keys = []
    geoms_by_key = {}
    path_counts_by_key = {}
    for key, geoms in jobs:
        paths = []
        for geom in geoms:
            paths.extend(_geometry_to_paths_cached(geom, path_cache, stats))
        if not paths:
            _fallback_key(
                key,
                geoms,
                height=height,
                z_bot=z_bot,
                scale_factor=scale_factor,
                slot_names=slot_names,
                meshes_by_slot=meshes_by_slot,
                extrude_cache=extrude_cache,
                stats=stats,
                reason="no_paths",
            )
            continue
        keys.append(key)
        geoms_by_key[key] = geoms
        path_counts_by_key[key] = len(paths)
        native_groups.append(paths)
        stats["native_input_paths"] = int(stats["native_input_paths"]) + len(paths)
    stats["native_group_count"] = int(stats["native_group_count"]) + len(native_groups)
    stats["pack_seconds"] = float(stats["pack_seconds"]) + (time.perf_counter() - t0)
    if not native_groups:
        return

    try:
        t0 = time.perf_counter()
        (
            native_meshes,
            rejected_groups,
            retry_records,
            primary_statuses,
        ) = _run_native_mesh_call(
            module=module,
            groups=native_groups,
            height=height,
            z_bot=z_bot,
            scale_factor=scale_factor,
        )
        stats["native_seconds"] = float(stats["native_seconds"]) + (time.perf_counter() - t0)
    except Exception as exc:
        stats["native_call_error"] = type(exc).__name__
        for key in keys:
            _fallback_key(
                key,
                geoms_by_key[key],
                height=height,
                z_bot=z_bot,
                scale_factor=scale_factor,
                slot_names=slot_names,
                meshes_by_slot=meshes_by_slot,
                extrude_cache=extrude_cache,
                stats=stats,
                reason="native_call_error",
            )
        return

    t0 = time.perf_counter()
    native_mesh_list = list(native_meshes or [])
    if len(native_mesh_list) > len(keys):
        stats["native_extra_meshes"] = int(stats["native_extra_meshes"]) + (
            len(native_mesh_list) - len(keys)
        )
    for index, key in enumerate(keys):
        ch = key[0]
        slot_name = slot_names[ch]
        _ensure_slot(meshes_by_slot, slot_name, ch)
        if index >= len(native_mesh_list):
            stats["native_invalid_meshes"] = int(stats["native_invalid_meshes"]) + 1
            _fallback_key(
                key,
                geoms_by_key[key],
                height=height,
                z_bot=z_bot,
                scale_factor=scale_factor,
                slot_names=slot_names,
                meshes_by_slot=meshes_by_slot,
                extrude_cache=extrude_cache,
                stats=stats,
                reason="missing_native_mesh",
            )
            continue
        native_mesh = native_mesh_list[index]
        mesh_arrays = _native_mesh_arrays(native_mesh)
        primary_status = (
            int(primary_statuses[index])
            if index < len(primary_statuses)
            else NATIVE_RETRY_MESH_ACCEPTED
        )
        if mesh_arrays is None:
            if primary_status == NATIVE_RETRY_MESH_SURFACE_REJECT:
                stats["native_surface_checked"] = int(
                    stats["native_surface_checked"]
                ) + 1
                stats["native_surface_rejects"] = int(
                    stats["native_surface_rejects"]
                ) + 1
                _fallback_key(
                    key,
                    geoms_by_key[key],
                    height=height,
                    z_bot=z_bot,
                    scale_factor=scale_factor,
                    slot_names=slot_names,
                    meshes_by_slot=meshes_by_slot,
                    extrude_cache=extrude_cache,
                    stats=stats,
                    reason="surface_reject",
                )
                continue
            reason = _native_mesh_rejection_reason(native_mesh)
            stats[reason] = int(stats[reason]) + 1
            if _retry_native_group_as_reference_polygons(
                module=module,
                key=key,
                geoms=geoms_by_key[key],
                original_path_count=path_counts_by_key[key],
                height=height,
                z_bot=z_bot,
                scale_factor=scale_factor,
                slot_names=slot_names,
                meshes_by_slot=meshes_by_slot,
                extrude_cache=extrude_cache,
                stats=stats,
                path_cache=path_cache,
                prepared_retry_groups=(
                    rejected_groups[index]
                    if index < len(rejected_groups)
                    and rejected_groups[index]
                    else None
                ),
                prepared_retry_record=(
                    retry_records[index]
                    if index < len(retry_records)
                    else None
                ),
            ):
                continue
            _fallback_key(
                key,
                geoms_by_key[key],
                height=height,
                z_bot=z_bot,
                scale_factor=scale_factor,
                slot_names=slot_names,
                meshes_by_slot=meshes_by_slot,
                extrude_cache=extrude_cache,
                stats=stats,
                reason=_fallback_reason_for_native_rejection(reason),
                native_module=module,
                path_cache=path_cache,
                input_path_count=path_counts_by_key.get(key),
            )
            continue
        mesh = None
        if _surface_validation_enabled():
            if len(primary_statuses) > 0:
                surface_ok = True
                stats["native_surface_checked"] = int(
                    stats["native_surface_checked"]
                ) + 1
            else:
                t_validate = time.perf_counter()
                surface_ok = _native_surface_area_matches_arrays(
                    mesh_arrays,
                    geoms_by_key[key],
                    height=height,
                    scale_factor=scale_factor,
                )
                stats["surface_validation_seconds"] = float(
                    stats["surface_validation_seconds"]
                ) + (time.perf_counter() - t_validate)
                stats["native_surface_checked"] = int(
                    stats["native_surface_checked"]
                ) + 1
            if not surface_ok:
                stats["native_surface_rejects"] = int(stats["native_surface_rejects"]) + 1
                _fallback_key(
                    key,
                    geoms_by_key[key],
                    height=height,
                    z_bot=z_bot,
                    scale_factor=scale_factor,
                    slot_names=slot_names,
                    meshes_by_slot=meshes_by_slot,
                    extrude_cache=extrude_cache,
                    stats=stats,
                    reason="surface_reject",
                )
                continue
            mesh = mesh_arrays
        stats["native_meshes"] = int(stats["native_meshes"]) + 1
        if mesh is not None:
            meshes_by_slot[slot_name]["meshes"].append(mesh)
            stats["native_output_meshes"] = int(stats["native_output_meshes"]) + 1
        else:
            _append_native_buffer(meshes_by_slot, slot_name, ch, mesh_arrays)
    stats["mesh_convert_seconds"] = float(stats["mesh_convert_seconds"]) + (time.perf_counter() - t0)


def _retry_native_group_as_reference_polygons(
    *,
    module,
    key: tuple[int, int, int],
    geoms,
    original_path_count: int,
    height: float,
    z_bot: float,
    scale_factor: float,
    slot_names,
    meshes_by_slot: dict[str, dict[str, Any]],
    extrude_cache,
    stats: dict[str, float | int | str],
    path_cache: dict[int, tuple[Any, list[list[tuple[float, float]]]]] | None,
    prepared_retry_groups=None,
    prepared_retry_record=None,
) -> bool:
    if not _should_consider_native_split(
        original_geometry_count=len(geoms),
        original_path_count=original_path_count,
    ):
        return False

    if prepared_retry_record is not None:
        precomputed_result = _commit_precomputed_native_split_retry(
            key=key,
            original_path_count=original_path_count,
            retry_record=prepared_retry_record,
            height=height,
            z_bot=z_bot,
            scale_factor=scale_factor,
            slot_names=slot_names,
            meshes_by_slot=meshes_by_slot,
            extrude_cache=extrude_cache,
            stats=stats,
        )
        if precomputed_result is not None:
            return precomputed_result

    retry_polygons = None
    retry_groups = prepared_retry_groups
    if retry_groups is not None:
        stats["native_rejected_groups_reused"] = int(
            stats["native_rejected_groups_reused"]
        ) + 1
    else:
        retry_groups = _native_retry_groups_for_native_retry(
            module=module,
            geoms=geoms,
            path_cache=path_cache,
            stats=stats,
        )
    if retry_groups is None:
        polygons = _reference_polygons_for_native_retry(geoms)
        if len(polygons) <= 1:
            return False

        retry_groups = []
        retry_polygons = []
        for poly in polygons:
            paths = _geometry_to_paths_cached(poly, path_cache, stats)
            if paths:
                retry_groups.append(paths)
                retry_polygons.append(poly)
    if len(retry_groups) <= 1:
        return False
    retry_path_count = sum(len(group) for group in retry_groups)
    if not _should_retry_native_split(
        original_path_count=original_path_count,
        retry_group_count=len(retry_groups),
        retry_path_count=retry_path_count,
    ):
        return False

    stats["native_split_retries"] = int(stats["native_split_retries"]) + 1
    stats["native_split_group_count"] = int(stats["native_split_group_count"]) + len(retry_groups)
    stats["native_input_paths"] = int(stats["native_input_paths"]) + retry_path_count

    try:
        t0 = time.perf_counter()
        native_meshes = _merge_native_split_retry_groups_to_meshes(
            module=module,
            retry_groups=retry_groups,
            height=height,
            z_bot=z_bot,
            scale_factor=scale_factor,
            stats=stats,
        )
        stats["native_seconds"] = float(stats["native_seconds"]) + (
            time.perf_counter() - t0
        )
    except Exception:
        return False

    ch = key[0]
    slot_name = slot_names[ch]
    _ensure_slot(meshes_by_slot, slot_name, ch)
    native_mesh_list = list(native_meshes or [])
    any_output = False
    for index, retry_group in enumerate(retry_groups):
        native_mesh = native_mesh_list[index] if index < len(native_mesh_list) else None
        mesh_arrays = _native_mesh_arrays(native_mesh)
        if mesh_arrays is not None:
            mesh = None
            surface_ok = True
            if _surface_validation_enabled():
                poly = _retry_polygon_for_group(retry_polygons, retry_group, index)
                if poly is None:
                    return bool(any_output)
                surface_ok = _native_mesh_surface_is_acceptable(
                    mesh_arrays,
                    [poly],
                    height=height,
                    scale_factor=scale_factor,
                    stats=stats,
                )
                if surface_ok:
                    mesh = mesh_arrays
            if surface_ok:
                stats["native_meshes"] = int(stats["native_meshes"]) + 1
                stats["native_split_meshes"] = int(stats["native_split_meshes"]) + 1
                if mesh is not None:
                    meshes_by_slot[slot_name]["meshes"].append(mesh)
                    stats["native_output_meshes"] = int(stats["native_output_meshes"]) + 1
                else:
                    _append_native_buffer(meshes_by_slot, slot_name, ch, mesh_arrays)
                any_output = True
                continue
            _fallback_key(
                key,
                [poly],
                height=height,
                z_bot=z_bot,
                scale_factor=scale_factor,
                slot_names=slot_names,
                meshes_by_slot=meshes_by_slot,
                extrude_cache=extrude_cache,
                stats=stats,
                reason="split_surface_reject",
            )
            stats["native_split_fallback_groups"] = int(stats["native_split_fallback_groups"]) + 1
            any_output = True
            continue

        if native_mesh is None:
            stats["native_invalid_meshes"] = int(stats["native_invalid_meshes"]) + 1
            reason = "missing_native_mesh"
        else:
            counter_name = _native_mesh_rejection_reason(native_mesh)
            stats[counter_name] = int(stats[counter_name]) + 1
            reason = _fallback_reason_for_native_rejection(counter_name)
        poly = _retry_polygon_for_group(retry_polygons, retry_group, index)
        if poly is None:
            return bool(any_output)
        _fallback_key(
            key,
            [poly],
            height=height,
            z_bot=z_bot,
            scale_factor=scale_factor,
            slot_names=slot_names,
            meshes_by_slot=meshes_by_slot,
            extrude_cache=extrude_cache,
            stats=stats,
            reason=f"split_{reason}",
        )
        stats["native_split_fallback_groups"] = int(stats["native_split_fallback_groups"]) + 1
        any_output = True
    return any_output


def _commit_precomputed_native_split_retry(
    *,
    key: tuple[int, int, int],
    original_path_count: int,
    retry_record,
    height: float,
    z_bot: float,
    scale_factor: float,
    slot_names,
    meshes_by_slot: dict[str, dict[str, Any]],
    extrude_cache,
    stats: dict[str, float | int | str],
) -> bool | None:
    """Commit one native-side split retry, or decline malformed records safely."""

    if not isinstance(retry_record, tuple) or len(retry_record) != 4:
        return None
    (
        raw_meshes,
        raw_statuses,
        raw_fallbacks,
        raw_path_count,
    ) = retry_record
    try:
        native_meshes = list(raw_meshes)
        native_statuses = np.asarray(raw_statuses, dtype=np.uint8)
        retry_path_count = int(raw_path_count)
    except (TypeError, ValueError):
        return None
    retry_group_count = len(native_meshes)
    if (
        retry_group_count <= 1
        or retry_path_count < 0
        or native_statuses.ndim != 1
        or len(native_statuses) != retry_group_count
        or not isinstance(raw_fallbacks, dict)
    ):
        return None
    if not _should_retry_native_split(
        original_path_count=original_path_count,
        retry_group_count=retry_group_count,
        retry_path_count=retry_path_count,
    ):
        return None

    fallback_groups = {}
    for raw_index, fallback_group in raw_fallbacks.items():
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            return None
        if index < 0 or index >= retry_group_count or index in fallback_groups:
            return None
        if not isinstance(fallback_group, list) or len(fallback_group) != 1:
            return None
        polygon = _polygon_from_native_rings(fallback_group[0])
        if polygon is None:
            return None
        fallback_groups[index] = polygon

    mesh_arrays_by_index = [None] * retry_group_count
    accepted_count = 0
    surface_rejects = 0
    for index, native_mesh in enumerate(native_meshes):
        status = int(native_statuses[index])
        if status == NATIVE_RETRY_MESH_ACCEPTED:
            mesh_arrays = _native_mesh_arrays(native_mesh)
            if mesh_arrays is None or index in fallback_groups:
                return None
            mesh_arrays_by_index[index] = mesh_arrays
            accepted_count += 1
            continue
        if status not in {
            NATIVE_RETRY_MESH_SURFACE_REJECT,
            NATIVE_RETRY_MESH_EMPTY,
        }:
            return None
        if _native_mesh_arrays(native_mesh) is not None or index not in fallback_groups:
            return None
        if status == NATIVE_RETRY_MESH_SURFACE_REJECT:
            surface_rejects += 1
    if accepted_count + len(fallback_groups) != retry_group_count:
        return None

    validate_surface = _surface_validation_enabled()
    surface_checked = accepted_count + surface_rejects if validate_surface else 0

    stats["native_split_retries"] = int(stats["native_split_retries"]) + 1
    stats["native_split_group_count"] = int(
        stats["native_split_group_count"]
    ) + retry_group_count
    stats["native_input_paths"] = int(stats["native_input_paths"]) + (
        retry_path_count
    )
    stats["native_rejected_mesh_retries_reused"] = int(
        stats["native_rejected_mesh_retries_reused"]
    ) + 1
    stats["native_meshes"] = int(stats["native_meshes"]) + accepted_count
    stats["native_split_meshes"] = int(stats["native_split_meshes"]) + (
        accepted_count
    )
    stats["native_surface_checked"] = int(
        stats["native_surface_checked"]
    ) + surface_checked
    stats["native_surface_rejects"] = int(
        stats["native_surface_rejects"]
    ) + surface_rejects

    ch = key[0]
    slot_name = slot_names[ch]
    _ensure_slot(meshes_by_slot, slot_name, ch)
    for index, mesh_arrays in enumerate(mesh_arrays_by_index):
        if mesh_arrays is not None:
            if validate_surface:
                meshes_by_slot[slot_name]["meshes"].append(mesh_arrays)
                stats["native_output_meshes"] = int(
                    stats["native_output_meshes"]
                ) + 1
            else:
                _append_native_buffer(
                    meshes_by_slot,
                    slot_name,
                    ch,
                    mesh_arrays,
                )
            continue

        status = int(native_statuses[index])
        polygon = fallback_groups[index]
        if status == NATIVE_RETRY_MESH_SURFACE_REJECT:
            reason = "split_surface_reject"
        else:
            stats["native_empty_meshes"] = int(
                stats["native_empty_meshes"]
            ) + 1
            reason = "split_empty_native_mesh"
        _fallback_key(
            key,
            [polygon],
            height=height,
            z_bot=z_bot,
            scale_factor=scale_factor,
            slot_names=slot_names,
            meshes_by_slot=meshes_by_slot,
            extrude_cache=extrude_cache,
            stats=stats,
            reason=reason,
        )
        stats["native_split_fallback_groups"] = int(
            stats["native_split_fallback_groups"]
        ) + 1
    return True


def _merge_native_split_retry_groups_to_meshes(
    *,
    module,
    retry_groups,
    height: float,
    z_bot: float,
    scale_factor: float,
    stats: dict[str, float | int | str],
):
    """Extrude independent retry groups concurrently without reordering them."""

    parallelism_plan = resolve_task_parallelism_plan(
        "vector",
        work_items=len(retry_groups),
        min_parallel_items=NATIVE_SPLIT_PARALLEL_MIN_GROUPS,
        hard_max_workers=4,
        work_units=len(retry_groups),
        min_parallel_work_units=NATIVE_SPLIT_PARALLEL_MIN_GROUPS,
        work_units_per_worker=NATIVE_SPLIT_PARALLEL_GROUPS_PER_WORKER,
        estimated_worker_bytes=NATIVE_SPLIT_PARALLEL_ESTIMATED_WORKER_BYTES,
    )
    worker_count = int(parallelism_plan.workers)
    stats["native_split_parallel_workers"] = max(
        int(stats["native_split_parallel_workers"]),
        worker_count,
    )

    def run_chunk(bounds):
        start, end = bounds
        with task_parallelism_worker_scope():
            meshes = module.merge_run_groups_to_meshes(
                retry_groups[start:end],
                close_delta_mm=0.0,
                scale=NATIVE_COORD_SCALE,
                height=height,
                z_offset=z_bot,
                xy_scale=scale_factor,
            )
        mesh_list = list(meshes or [])
        expected_count = end - start
        if len(mesh_list) < expected_count:
            mesh_list.extend([None] * (expected_count - len(mesh_list)))
        return mesh_list[:expected_count]

    if worker_count <= 1:
        return run_chunk((0, len(retry_groups)))

    chunk_count = min(
        len(retry_groups),
        worker_count * NATIVE_SPLIT_PARALLEL_CHUNKS_PER_WORKER,
    )
    chunk_size = max(
        1,
        (len(retry_groups) + chunk_count - 1) // chunk_count,
    )
    chunk_bounds = [
        (start, min(len(retry_groups), start + chunk_size))
        for start in range(0, len(retry_groups), chunk_size)
    ]
    stats["native_split_parallel_batch_count"] = int(
        stats["native_split_parallel_batch_count"]
    ) + len(chunk_bounds)

    parallel_started = time.perf_counter()
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="lumina-vector-native-split",
    ) as executor:
        ordered_chunks = list(executor.map(run_chunk, chunk_bounds))
    stats["native_split_parallel_seconds"] = float(
        stats["native_split_parallel_seconds"]
    ) + (time.perf_counter() - parallel_started)
    return [mesh for chunk in ordered_chunks for mesh in chunk]


def _should_consider_native_split(
    *,
    original_geometry_count: int,
    original_path_count: int,
) -> bool:
    if original_geometry_count <= 0:
        return False
    if original_path_count < NATIVE_SPLIT_RETRY_MIN_ORIGINAL_PATHS:
        return False
    paths_per_geometry = float(original_path_count) / float(original_geometry_count)
    return paths_per_geometry <= NATIVE_SPLIT_RETRY_MAX_ORIGINAL_PATHS_PER_GEOM


def _should_retry_native_split(
    *,
    original_path_count: int,
    retry_group_count: int,
    retry_path_count: int,
) -> bool:
    if original_path_count <= 0:
        return False
    if retry_group_count < NATIVE_SPLIT_RETRY_MIN_POLYGONS:
        return False
    max_retry_paths = float(original_path_count) * NATIVE_SPLIT_RETRY_MAX_PATH_RATIO
    return float(retry_path_count) <= max_retry_paths


def _native_retry_groups_for_native_retry(
    *,
    module,
    geoms,
    path_cache: dict[int, tuple[Any, list[list[tuple[float, float]]]]] | None,
    stats: dict[str, float | int | str],
) -> list | None:
    merge_run_groups = getattr(module, "merge_run_groups", None)
    if not callable(merge_run_groups):
        return None

    original_paths = []
    for geom in geoms:
        original_paths.extend(_geometry_to_paths_cached(geom, path_cache, stats))
    if not original_paths:
        return None

    try:
        merged_groups = merge_run_groups(
            [original_paths],
            close_delta_mm=NATIVE_CLOSE_DELTA_MM,
            scale=NATIVE_COORD_SCALE,
        )
        merged_group = merged_groups[0] if merged_groups else []
    except Exception:
        return None
    retry_groups = [poly for poly in (merged_group or []) if poly]
    return retry_groups or None


def _reference_polygons_for_native_retry(geoms) -> list[Polygon]:
    merged = _merged_reference_geometry(geoms)
    if merged is None or merged.is_empty:
        return []
    if merged.geom_type == "Polygon":
        return [merged]
    if merged.geom_type == "MultiPolygon":
        return [poly for poly in merged.geoms if not poly.is_empty]
    return []


def _retry_polygon_for_group(retry_polygons, retry_group, index: int) -> Polygon | None:
    if retry_polygons is not None:
        return retry_polygons[index]
    return _polygon_from_native_rings(retry_group)


def _polygon_from_native_rings(rings) -> Polygon | None:
    if not rings:
        return None
    try:
        exterior = [(float(point[0]), float(point[1])) for point in rings[0]]
        holes = [
            [(float(point[0]), float(point[1])) for point in ring]
            for ring in rings[1:]
        ]
    except (TypeError, IndexError, ValueError):
        return None
    if len(exterior) < 3:
        return None
    try:
        polygon = Polygon(exterior, holes)
    except Exception:
        return None
    if polygon.is_empty:
        return None
    return polygon


def _native_mesh_surface_is_acceptable(
    mesh_arrays: tuple[np.ndarray, np.ndarray],
    geoms,
    *,
    height: float,
    scale_factor: float,
    stats: dict[str, float | int | str],
) -> bool:
    if not _surface_validation_enabled():
        return True
    t_validate = time.perf_counter()
    surface_ok = _native_surface_area_matches_arrays(
        mesh_arrays,
        geoms,
        height=height,
        scale_factor=scale_factor,
    )
    stats["surface_validation_seconds"] = float(stats["surface_validation_seconds"]) + (
        time.perf_counter() - t_validate
    )
    stats["native_surface_checked"] = int(stats["native_surface_checked"]) + 1
    if not surface_ok:
        stats["native_surface_rejects"] = int(stats["native_surface_rejects"]) + 1
    return surface_ok


def _fallback_key(
    key: tuple[int, int, int],
    geoms,
    *,
    height: float,
    z_bot: float,
    scale_factor: float,
    slot_names,
    meshes_by_slot: dict[str, dict[str, Any]],
    extrude_cache,
    stats: dict[str, float | int | str],
    reason: str = "unknown",
    native_module=None,
    path_cache: dict[int, tuple[Any, list[list[tuple[float, float]]]]] | None = None,
    input_path_count: int | None = None,
) -> None:
    t0 = time.perf_counter()
    ch = key[0]
    slot_name = slot_names[ch]
    _ensure_slot(meshes_by_slot, slot_name, ch)
    if reason == "empty_native_mesh" and _try_native_merged_fallback(
        key=key,
        geoms=geoms,
        height=height,
        z_bot=z_bot,
        scale_factor=scale_factor,
        slot_names=slot_names,
        meshes_by_slot=meshes_by_slot,
        extrude_cache=extrude_cache,
        stats=stats,
        native_module=native_module,
        path_cache=path_cache,
        input_path_count=input_path_count,
    ):
        stats["fallback_seconds"] = float(stats["fallback_seconds"]) + (time.perf_counter() - t0)
        return
    meshes_by_slot[slot_name]["meshes"].extend(
        _fallback_extrude_group(
            geoms,
            height=height,
            z_bot=z_bot,
            scale_factor=scale_factor,
            extrude_cache=extrude_cache,
        )
    )
    stats["fallback_groups"] = int(stats["fallback_groups"]) + 1
    _increment_fallback_reason(stats, reason)
    stats["fallback_seconds"] = float(stats["fallback_seconds"]) + (time.perf_counter() - t0)


def _try_native_merged_fallback(
    *,
    key: tuple[int, int, int],
    geoms,
    height: float,
    z_bot: float,
    scale_factor: float,
    slot_names,
    meshes_by_slot: dict[str, dict[str, Any]],
    extrude_cache,
    stats: dict[str, float | int | str],
    native_module,
    path_cache: dict[int, tuple[Any, list[list[tuple[float, float]]]]] | None,
    input_path_count: int | None,
) -> bool:
    merge_run_groups = getattr(native_module, "merge_run_groups", None)
    if not callable(merge_run_groups):
        return False

    topology_path_count, hole_count = _fallback_group_topology(geoms)
    path_count = int(input_path_count) if input_path_count is not None else topology_path_count
    hole_ratio = float(hole_count) / max(float(path_count), 1.0)
    if (
        path_count < NATIVE_MERGED_FALLBACK_MIN_PATHS
        or hole_ratio > NATIVE_MERGED_FALLBACK_MAX_HOLE_RATIO
    ):
        stats["native_merged_fallback_skipped_groups"] = int(
            stats.get("native_merged_fallback_skipped_groups", 0) or 0
        ) + 1
        return False

    paths = []
    for geom in geoms:
        paths.extend(_geometry_to_paths_cached(geom, path_cache, stats))
    if not paths:
        return False

    try:
        merged_groups = merge_run_groups(
            [paths],
            close_delta_mm=NATIVE_CLOSE_DELTA_MM,
            scale=NATIVE_COORD_SCALE,
        )
    except Exception as exc:
        stats["native_merged_fallback_error"] = type(exc).__name__
        return False

    merged_group = merged_groups[0] if merged_groups else []
    polygons = [
        polygon
        for polygon in (_polygon_from_native_rings(group) for group in (merged_group or []) if group)
        if polygon is not None and not polygon.is_empty
    ]
    if not polygons:
        return False

    merged_geom = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
    ch = key[0]
    slot_name = slot_names[ch]
    _ensure_slot(meshes_by_slot, slot_name, ch)
    meshes_by_slot[slot_name]["meshes"].extend(
        VectorProcessor._extrude_geometry(
            merged_geom,
            height=height,
            z_offset=z_bot,
            scale=scale_factor,
            extrude_cache=extrude_cache,
        )
    )
    stats["fallback_groups"] = int(stats["fallback_groups"]) + 1
    _increment_fallback_reason(stats, "native_merged_empty_native_mesh")
    stats["native_merged_fallback_groups"] = int(
        stats.get("native_merged_fallback_groups", 0) or 0
    ) + 1
    stats["native_merged_fallback_polygons"] = int(
        stats.get("native_merged_fallback_polygons", 0) or 0
    ) + len(polygons)
    stats["native_merged_fallback_input_paths"] = int(
        stats.get("native_merged_fallback_input_paths", 0) or 0
    ) + len(paths)
    stats["native_merged_fallback_input_holes"] = int(
        stats.get("native_merged_fallback_input_holes", 0) or 0
    ) + hole_count
    return True


def _ensure_slot(meshes_by_slot: dict[str, dict[str, Any]], slot_name: str, mat_id: int) -> None:
    if slot_name not in meshes_by_slot:
        meshes_by_slot[slot_name] = {"meshes": [], "mat_id": mat_id}


def _iter_polygons(geom) -> Iterable[Polygon]:
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        yield geom
    elif geom.geom_type == "MultiPolygon":
        for poly in geom.geoms:
            if not poly.is_empty:
                yield poly
    elif hasattr(geom, "geoms"):
        for part in geom.geoms:
            yield from _iter_polygons(part)


def _ring(coords) -> list[tuple[float, float]]:
    try:
        points = [(float(point[0]), float(point[1])) for point in coords]
    except (TypeError, IndexError, ValueError):
        return []
    if len(points) < 3:
        return []
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points if len(points) >= 3 else []


def _geometry_to_paths(geom) -> list[list[tuple[float, float]]]:
    paths = []
    for poly in _iter_polygons(geom):
        try:
            poly = orient(poly, sign=1.0)
        except Exception:
            pass
        exterior = _ring(poly.exterior.coords)
        if exterior:
            paths.append(exterior)
        for interior in poly.interiors:
            hole = _ring(interior.coords)
            if hole:
                paths.append(hole)
    return paths


def _fallback_group_topology(geoms) -> tuple[int, int]:
    path_count = 0
    hole_count = 0
    for geom in geoms:
        for poly in _iter_polygons(geom):
            holes = len(poly.interiors)
            hole_count += holes
            path_count += 1 + holes
    return path_count, hole_count


def _geometry_to_paths_cached(
    geom,
    path_cache: dict[int, tuple[Any, list[list[tuple[float, float]]]]] | None,
    stats: dict[str, float | int | str],
) -> list[list[tuple[float, float]]]:
    if path_cache is None:
        return _geometry_to_paths(geom)
    key = id(geom)
    cached = path_cache.get(key)
    if cached is not None and cached[0] is geom:
        stats["native_path_cache_hits"] = int(stats["native_path_cache_hits"]) + 1
        return cached[1]
    paths = _geometry_to_paths(geom)
    path_cache[key] = (geom, paths)
    stats["native_path_cache_misses"] = int(stats["native_path_cache_misses"]) + 1
    return paths


def _native_mesh_arrays(native_mesh) -> tuple[np.ndarray, np.ndarray] | None:
    try:
        vertices, faces = native_mesh
    except (TypeError, ValueError):
        return None
    try:
        if len(vertices) == 0 or len(faces) == 0:
            return None
    except TypeError:
        return None
    verts = np.asarray(vertices, dtype=np.float64)
    fac = np.asarray(faces, dtype=np.int64)
    if verts.ndim != 2 or verts.shape[1] != 3 or fac.ndim != 2 or fac.shape[1] != 3:
        return None
    if not np.all(np.isfinite(verts)):
        return None
    if len(verts) == 0 or len(fac) == 0:
        return None
    if np.any(fac < 0) or np.any(fac >= len(verts)):
        return None
    return verts, fac


def _mesh_from_arrays(mesh_arrays: tuple[np.ndarray, np.ndarray]) -> trimesh.Trimesh | None:
    verts, fac = mesh_arrays
    if len(verts) == 0 or len(fac) == 0:
        return None
    return trimesh.Trimesh(vertices=verts, faces=fac, process=False)


def _mesh_from_native(native_mesh) -> trimesh.Trimesh | None:
    mesh_arrays = _native_mesh_arrays(native_mesh)
    if mesh_arrays is None:
        return None
    return _mesh_from_arrays(mesh_arrays)


def _append_native_buffer(
    meshes_by_slot: dict[str, dict[str, Any]],
    slot_name: str,
    mat_id: int,
    mesh_arrays: tuple[np.ndarray, np.ndarray],
) -> None:
    _ensure_slot(meshes_by_slot, slot_name, mat_id)
    buffers = meshes_by_slot[slot_name].setdefault("_native_buffers", [])
    buffers.append(mesh_arrays)


def _coalesced_mesh_from_buffers(
    buffers: list[tuple[np.ndarray, np.ndarray]],
) -> trimesh.Trimesh | None:
    if not buffers:
        return None
    if len(buffers) == 1:
        return _mesh_from_arrays(buffers[0])

    vertices = []
    faces = []
    vertex_offset = 0
    for verts, fac in buffers:
        if len(verts) == 0 or len(fac) == 0:
            continue
        vertices.append(verts)
        faces.append(fac + vertex_offset)
        vertex_offset += len(verts)

    if not vertices or not faces:
        return None
    return _mesh_from_arrays((np.vstack(vertices), np.vstack(faces)))


def _flush_native_buffers(
    meshes_by_slot: dict[str, dict[str, Any]],
    stats: dict[str, float | int | str],
) -> None:
    t0 = time.perf_counter()
    for slot_data in meshes_by_slot.values():
        buffers = slot_data.pop("_native_buffers", [])
        if not buffers:
            continue
        mesh = _coalesced_mesh_from_buffers(buffers)
        if mesh is None:
            continue
        slot_data["meshes"].append(mesh)
        stats["native_coalesced_slots"] = int(stats["native_coalesced_slots"]) + 1
        stats["native_coalesced_meshes"] = int(stats["native_coalesced_meshes"]) + len(buffers)
        stats["native_output_meshes"] = int(stats["native_output_meshes"]) + 1
    stats["mesh_convert_seconds"] = float(stats["mesh_convert_seconds"]) + (
        time.perf_counter() - t0
    )


def _native_mesh_rejection_reason(native_mesh) -> str:
    try:
        vertices, faces = native_mesh
    except (TypeError, ValueError):
        return "native_invalid_meshes"
    try:
        if len(vertices) == 0 or len(faces) == 0:
            return "native_empty_meshes"
    except TypeError:
        return "native_invalid_meshes"
    return "native_invalid_meshes"


def _fallback_reason_for_native_rejection(counter_name: str) -> str:
    if counter_name == "native_empty_meshes":
        return "empty_native_mesh"
    return "invalid_native_mesh"


def _increment_fallback_reason(stats: dict[str, float | int | str], reason: str) -> None:
    safe_reason = str(reason or "unknown").strip().lower().replace("-", "_").replace(" ", "_")
    key = f"fallback_reason_{safe_reason or 'unknown'}"
    stats[key] = int(stats.get(key, 0) or 0) + 1


def _surface_validation_enabled() -> bool:
    return str(os.environ.get("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _surface_area_rel_tolerance() -> float:
    raw = os.environ.get("LUMINA_VECTOR_NATIVE_MESH_SURFACE_REL_TOL")
    if raw is None:
        return NATIVE_SURFACE_AREA_REL_TOL
    try:
        return max(0.0, float(raw))
    except ValueError:
        return NATIVE_SURFACE_AREA_REL_TOL


def _native_surface_area_matches(
    mesh: trimesh.Trimesh,
    geoms,
    *,
    height: float,
    scale_factor: float,
) -> bool:
    expected_area = _expected_extruded_surface_area(
        geoms,
        height=height,
        scale_factor=scale_factor,
    )
    if expected_area <= NATIVE_SURFACE_AREA_ABS_TOL_MM2:
        return True
    delta = abs(float(mesh.area) - expected_area)
    if delta <= NATIVE_SURFACE_AREA_ABS_TOL_MM2:
        return True
    return delta / expected_area <= _surface_area_rel_tolerance()


def _native_surface_area_matches_arrays(
    mesh_arrays: tuple[np.ndarray, np.ndarray],
    geoms,
    *,
    height: float,
    scale_factor: float,
) -> bool:
    """Apply the unchanged surface-area gate without allocating a Trimesh."""

    vertices, faces = mesh_arrays
    triangles = vertices[faces]
    crosses = trimesh.triangles.cross(triangles)
    mesh_area = float(trimesh.triangles.area(crosses=crosses).sum())
    expected_area = _expected_extruded_surface_area(
        geoms,
        height=height,
        scale_factor=scale_factor,
    )
    if expected_area <= NATIVE_SURFACE_AREA_ABS_TOL_MM2:
        return True
    delta = abs(mesh_area - expected_area)
    if delta <= NATIVE_SURFACE_AREA_ABS_TOL_MM2:
        return True
    return delta / expected_area <= _surface_area_rel_tolerance()


def _expected_extruded_surface_area(geoms, *, height: float, scale_factor: float) -> float:
    merged = _merged_reference_geometry(geoms)
    if merged is None or merged.is_empty:
        return 0.0
    area_mm2 = abs(float(merged.area)) * float(scale_factor) * float(scale_factor)
    perimeter_mm = float(merged.length) * float(scale_factor)
    return (2.0 * area_mm2) + (perimeter_mm * float(height))


def _merged_reference_geometry(geoms):
    if not geoms:
        return None
    if len(geoms) > 1:
        snapped = []
        for geom in geoms:
            if geom is not None and not geom.is_empty:
                snapped_geom = set_precision(geom, grid_size=0.001)
                if snapped_geom is not None and not snapped_geom.is_empty:
                    snapped.append(snapped_geom)
        if not snapped:
            return None
        try:
            unioned = _union_run_group_geometries(snapped)
            merged = VectorProcessor._normalize_contours(unioned, close_delta_mm=NATIVE_CLOSE_DELTA_MM)
            if merged is None or merged.is_empty:
                merged = unioned
            return merged
        except Exception:
            return unary_union(snapped)
    return geoms[0]


def _fallback_extrude_group(geoms, *, height: float, z_bot: float, scale_factor: float, extrude_cache):
    merged = _merged_reference_geometry(geoms)
    if merged is None or (isinstance(merged, GeometryCollection) and merged.is_empty):
        return []
    return VectorProcessor._extrude_geometry(
        merged,
        height=height,
        z_offset=z_bot,
        scale=scale_factor,
        extrude_cache=extrude_cache,
    )
