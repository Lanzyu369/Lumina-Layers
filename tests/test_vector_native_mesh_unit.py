"""Unit tests for optional native SVG vector mesh extrusion.

These tests keep the accelerated path behind a quality-preserving fallback:
valid native meshes can be used, but empty/invalid native output must fall
back to the current Shapely/trimesh extrusion.
"""

from __future__ import annotations

import threading
import time
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

import core.vector_native_mesh as vector_native_mesh
from core import task_parallelism
from core.system_capacity import EffectiveCpuCapacity
from core.task_parallelism import AdaptiveParallelismPlan
from core.vector_engine import VectorAnalysis, VectorProcessor
from core.vector_native_mesh import NativeVectorMeshResult, run_length_extrude_native_hybrid


def _square() -> Polygon:
    return Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)])


def _square_at(x_offset: float) -> Polygon:
    return Polygon(
        [
            (x_offset, 0.0),
            (x_offset + 2.0, 0.0),
            (x_offset + 2.0, 2.0),
            (x_offset, 2.0),
        ]
    )


def _analysis() -> VectorAnalysis:
    square = _square()
    return VectorAnalysis(
        shape_data=[],
        clipped_shapes=[{"geometry": square}],
        matched_shapes=[{"geometry": square, "recipe": [0], "matched_rgb": (255, 255, 255)}],
        silhouette=square,
        scale_factor=1.0,
        bbox=(0.0, 0.0, 2.0, 2.0),
        color_conf={},
        slot_names=["White"],
        num_channels=1,
        num_layers=1,
        preview_colors={0: [255, 255, 255, 255], "White": [255, 255, 255, 255]},
        stage_timings={},
    )


def _processor() -> VectorProcessor:
    processor = object.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.last_stage_timings = {}
    return processor


def _box_mesh() -> trimesh.Trimesh:
    vertices = [
        (0.0, 0.0, 0.0),
        (2.0, 0.0, 0.0),
        (2.0, 2.0, 0.0),
        (0.0, 2.0, 0.0),
        (0.0, 0.0, 0.08),
        (2.0, 0.0, 0.08),
        (2.0, 2.0, 0.08),
        (0.0, 2.0, 0.08),
    ]
    faces = [
        (0, 2, 1),
        (0, 3, 2),
        (4, 5, 6),
        (4, 6, 7),
        (0, 1, 5),
        (0, 5, 4),
        (1, 2, 6),
        (1, 6, 5),
        (2, 3, 7),
        (2, 7, 6),
        (3, 0, 4),
        (3, 4, 7),
    ]
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def _box_mesh_buffers(*, height: float = 0.08, z_offset: float = 0.0):
    vertices = [
        (0.0, 0.0, z_offset),
        (2.0, 0.0, z_offset),
        (2.0, 2.0, z_offset),
        (0.0, 2.0, z_offset),
        (0.0, 0.0, z_offset + height),
        (2.0, 0.0, z_offset + height),
        (2.0, 2.0, z_offset + height),
        (0.0, 2.0, z_offset + height),
    ]
    faces = [
        (0, 2, 1),
        (0, 3, 2),
        (4, 5, 6),
        (4, 6, 7),
        (0, 1, 5),
        (0, 5, 4),
        (1, 2, 6),
        (1, 6, 5),
        (2, 3, 7),
        (2, 7, 6),
        (3, 0, 4),
        (3, 4, 7),
    ]
    return vertices, faces


def _guarded_module(**attrs):
    return SimpleNamespace(
        native_mesh_capabilities=lambda: {"triangulation_area_guard": True},
        **attrs,
    )


def _parallel_batch_shapes() -> list[dict]:
    recipes = [
        [0, 0, 0, 0, 0],
        [1, 0, 0, 0, 0],
        [0, 1, 0, 1, 0],
        [1, 1, 0, 0, 1],
    ]
    return [
        {"geometry": _square_at(float(index) * 4.0), "recipe": recipe}
        for index, recipe in enumerate(recipes)
    ]


def _native_result_mesh_signature(result: NativeVectorMeshResult) -> tuple:
    return tuple(
        (
            slot_name,
            int(slot_data["mat_id"]),
            tuple(
                (
                    np.asarray(mesh.vertices).tobytes(order="C"),
                    np.asarray(mesh.faces).tobytes(order="C"),
                )
                for mesh in slot_data["meshes"]
            ),
        )
        for slot_name, slot_data in result.meshes_by_slot.items()
    )


def _native_plan(
    workers: int,
    *,
    available_memory_bytes: int = 8 * 1024**3,
    outer_demand: int = 1,
) -> AdaptiveParallelismPlan:
    """Build a deterministic native scheduling plan."""

    effective_cpu = max(1, workers * outer_demand)
    return AdaptiveParallelismPlan(
        workers=workers,
        requested_ceiling=max(1, workers),
        effective_cpu_capacity=effective_cpu,
        outer_demand=outer_demand,
        cpu_fair_share_ceiling=max(1, effective_cpu // outer_demand),
        work_item_ceiling=8,
        work_unit_ceiling=8,
        stage_ceiling=4,
        memory_ceiling=max(1, workers),
        available_memory_bytes=available_memory_bytes,
        estimated_worker_bytes=384 * 1024**2,
        limiting_reason="requested",
        demand_snapshot_fallback=False,
    )


def _native_batch_items(count: int = 5) -> list:
    return [
        (
            (0.08, round(index * 0.08, 8)),
            [((0, index, index), [_square_at(float(index) * 4.0)])],
        )
        for index in range(count)
    ]


def test_native_batch_cost_grows_with_points_rings_and_groups() -> None:
    dense = Polygon(
        [
            (
                float(np.cos(theta)),
                float(np.sin(theta)),
            )
            for theta in np.linspace(0.0, 2.0 * np.pi, 65)
        ]
    )
    one_square_job = [((0, 0, 0), [_square()])]
    dense_polygon_job = [((0, 0, 0), [dense])]
    two_group_jobs = [
        ((0, 0, 0), [_square()]),
        ((1, 0, 0), [_square_at(4.0)]),
    ]

    small = vector_native_mesh._estimate_native_jobs_cost(one_square_job)
    more_points = vector_native_mesh._estimate_native_jobs_cost(
        dense_polygon_job,
    )
    more_groups = vector_native_mesh._estimate_native_jobs_cost(
        two_group_jobs,
    )

    assert small.estimated_bytes > 0
    assert more_points.point_count > small.point_count
    assert more_points.estimated_bytes > small.estimated_bytes
    assert more_groups.group_count > small.group_count
    assert more_groups.estimated_bytes > small.estimated_bytes


def test_native_batch_cost_counts_geometry_types_without_mutation() -> None:
    holed = Polygon(
        [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)],
        [[(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)]],
    )
    multi = MultiPolygon([_square_at(8.0), _square_at(12.0)])
    collection = GeometryCollection([holed, multi, Polygon()])
    before = collection.wkb

    cost = vector_native_mesh._estimate_native_jobs_cost(
        [((0, 0, 0), [collection, Polygon()])],
    )

    assert collection.wkb == before
    assert cost.source_geometry_count == 2
    assert cost.group_count == 1
    assert cost.ring_count == 4
    assert cost.hole_count == 1
    assert cost.point_count == 20


def test_native_batch_cost_saturates_instead_of_overflowing() -> None:
    assert (
        vector_native_mesh._saturating_add_bytes(sys.maxsize, sys.maxsize)
        == sys.maxsize
    )
    assert (
        vector_native_mesh._saturating_multiply_bytes(
            sys.maxsize,
            sys.maxsize,
        )
        == sys.maxsize
    )


def test_native_batch_cost_probe_failure_fails_closed() -> None:
    class _BrokenGeometry:
        @property
        def is_empty(self) -> bool:
            raise RuntimeError("broken geometry probe")

    cost = vector_native_mesh._estimate_native_jobs_cost(
        [((0, 0, 0), [_BrokenGeometry()])],
    )

    assert cost.estimated_bytes == sys.maxsize


def test_native_batch_worker_policy_uses_requested_ceiling_and_nested_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "4")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    monkeypatch.setattr(task_parallelism.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(
        task_parallelism,
        "_available_memory_bytes",
        lambda: 8 * 1024**3,
    )
    monkeypatch.setattr(
        task_parallelism,
        "get_effective_cpu_capacity",
        lambda: EffectiveCpuCapacity(
            host_cpu_count=8,
            affinity_cpu_count=None,
            cgroup_quota_cpu_count=None,
            apple_performance_cpu_count=None,
            effective_cpu_count=8,
            limiting_source="host_fallback",
        ),
    )

    assert vector_native_mesh._resolve_native_batch_plan(
        batch_count=2,
        group_count=20,
        representative_batch_bytes=384 * 1024**2,
    ).workers == 1
    assert vector_native_mesh._resolve_native_batch_plan(
        batch_count=15,
        group_count=43,
        representative_batch_bytes=384 * 1024**2,
    ).workers == 4
    assert vector_native_mesh._resolve_native_batch_plan(
        batch_count=54,
        group_count=314,
        representative_batch_bytes=384 * 1024**2,
    ).workers == 4
    with task_parallelism.task_parallelism_worker_scope():
        assert vector_native_mesh._resolve_native_batch_plan(
            batch_count=15,
            group_count=43,
            representative_batch_bytes=384 * 1024**2,
        ).workers == 1


def test_native_batch_plan_scales_to_thirty_two_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUMINA_VECTOR_PARALLELISM", raising=False)
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    monkeypatch.setattr(
        task_parallelism,
        "_available_memory_bytes",
        lambda: 64 * 1024**3,
    )
    monkeypatch.setattr(
        task_parallelism,
        "get_effective_cpu_capacity",
        lambda: EffectiveCpuCapacity(
            host_cpu_count=32,
            affinity_cpu_count=32,
            cgroup_quota_cpu_count=None,
            apple_performance_cpu_count=None,
            effective_cpu_count=32,
            limiting_source="affinity",
        ),
    )

    plan = vector_native_mesh._resolve_native_batch_plan(
        batch_count=44,
        group_count=55,
        representative_batch_bytes=384 * 1024**2,
    )

    assert plan.workers == 32
    assert plan.stage_ceiling == 32


def test_representative_batch_bytes_uses_upper_median_without_outlier_cap() -> None:
    base_cost = vector_native_mesh._estimate_native_jobs_cost(
        [((0, 0, 0), [_square()])],
    )
    costs = [
        replace(base_cost, estimated_bytes=value)
        for value in (10, 20, 30, 10_000)
    ]

    assert vector_native_mesh._representative_batch_bytes(costs) == 30


def test_native_parallel_window_is_memory_bounded_and_commits_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch_items = _native_batch_items(5)
    cheap_costs = [
        vector_native_mesh._estimate_native_jobs_cost(jobs)
        for (_height_z, jobs) in batch_items
    ]
    representative_bytes = max(cost.estimated_bytes for cost in cheap_costs)
    plan = _native_plan(
        2,
        available_memory_bytes=1024**3 + representative_bytes * 2,
    )
    live_batches = 0
    max_live_batches = 0
    commit_indices: list[int] = []
    completion_indices: list[int] = []
    original_prepare = vector_native_mesh._prepare_native_batch
    original_commit = vector_native_mesh._commit_computed_native_batch

    def tracked_prepare(*args, **kwargs):
        nonlocal live_batches, max_live_batches
        batch = original_prepare(*args, **kwargs)
        live_batches += 1
        max_live_batches = max(max_live_batches, live_batches)
        return batch

    def tracked_commit(*args, **kwargs):
        nonlocal live_batches
        batch = kwargs["batch"]
        commit_indices.append(batch.index)
        try:
            return original_commit(*args, **kwargs)
        finally:
            live_batches -= 1

    def merge(groups, **kwargs):
        index = int(round(float(kwargs["z_offset"]) / 0.08))
        time.sleep(0.02 if index == 0 else 0.001)
        completion_indices.append(index)
        return [
            _box_mesh_buffers(
                height=float(kwargs["height"]),
                z_offset=float(kwargs["z_offset"]),
            )
            for _group in groups
        ]

    monkeypatch.setattr(
        vector_native_mesh,
        "_prepare_native_batch",
        tracked_prepare,
    )
    monkeypatch.setattr(
        vector_native_mesh,
        "_commit_computed_native_batch",
        tracked_commit,
    )

    result, error = vector_native_mesh._try_run_native_batches_parallel(
        module=_guarded_module(merge_run_groups_to_meshes=merge),
        batch_items=batch_items,
        run_group_count=5,
        source_geometry_count=5,
        parallelism_plan=plan,
        cheap_batch_costs=cheap_costs,
        representative_batch_bytes=representative_bytes,
        scale_factor=1.0,
        slot_names=["White"],
        extrude_cache=None,
    )

    assert error == ""
    assert result is not None
    assert max_live_batches <= 2
    assert result.stats["native_parallel_inflight_limit"] == 2
    assert result.stats["native_parallel_limit_reason"] == "requested"
    assert result.stats["native_parallel_effective_cpu"] == 2
    assert result.stats["native_parallel_outer_demand"] == 1
    assert result.stats["native_parallel_cpu_fair_share"] == 2
    assert result.stats["native_parallel_memory_ceiling"] == 2
    assert result.stats["native_parallel_demand_fallback"] is False
    assert (
        result.stats["native_parallel_max_estimated_batch_bytes"]
        >= representative_bytes
    )
    assert commit_indices == [0, 1, 2, 3, 4]
    assert completion_indices != commit_indices


def test_oversized_middle_batch_drains_then_safe_batches_resume_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch_items = _native_batch_items(5)
    cheap_costs = [
        replace(
            vector_native_mesh._estimate_native_jobs_cost(jobs),
            estimated_bytes=10,
        )
        for (_height_z, jobs) in batch_items
    ]
    plan = _native_plan(2, available_memory_bytes=1024**3 + 100)
    owner_thread = threading.get_ident()
    compute_threads: dict[int, int] = {}
    commit_indices: list[int] = []
    original_prepare = vector_native_mesh._prepare_native_batch
    original_commit = vector_native_mesh._commit_computed_native_batch

    def make_middle_oversized(*args, **kwargs):
        batch = original_prepare(*args, **kwargs)
        estimated_bytes = 101 if batch.index == 2 else 10
        return replace(
            batch,
            cost=replace(batch.cost, estimated_bytes=estimated_bytes),
        )

    def record_commit(*args, **kwargs):
        commit_indices.append(kwargs["batch"].index)
        return original_commit(*args, **kwargs)

    def merge(groups, **kwargs):
        index = int(round(float(kwargs["z_offset"]) / 0.08))
        compute_threads[index] = threading.get_ident()
        return [
            _box_mesh_buffers(
                height=float(kwargs["height"]),
                z_offset=float(kwargs["z_offset"]),
            )
            for _group in groups
        ]

    monkeypatch.setattr(
        vector_native_mesh,
        "_prepare_native_batch",
        make_middle_oversized,
    )
    monkeypatch.setattr(
        vector_native_mesh,
        "_commit_computed_native_batch",
        record_commit,
    )

    result, error = vector_native_mesh._try_run_native_batches_parallel(
        module=_guarded_module(merge_run_groups_to_meshes=merge),
        batch_items=batch_items,
        run_group_count=5,
        source_geometry_count=5,
        parallelism_plan=plan,
        cheap_batch_costs=cheap_costs,
        representative_batch_bytes=10,
        scale_factor=1.0,
        slot_names=["White"],
        extrude_cache=None,
    )

    assert error == ""
    assert result is not None
    assert commit_indices == [0, 1, 2, 3, 4]
    assert compute_threads[2] == owner_thread
    assert compute_threads[3] != owner_thread
    assert compute_threads[4] != owner_thread
    assert result.stats["native_parallel_oversized_serial_batches"] == 1


def test_more_than_three_thousand_sources_no_longer_force_global_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE",
        raising=False,
    )
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "2")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    monkeypatch.setattr(
        task_parallelism,
        "_available_memory_bytes",
        lambda: 8 * 1024**3,
    )
    base_shapes = _parallel_batch_shapes()
    shapes = [
        {
            "geometry": base_shapes[index % len(base_shapes)]["geometry"],
            "recipe": base_shapes[index % len(base_shapes)]["recipe"],
        }
        for index in range(3_001)
    ]

    def merge(groups, **kwargs):
        return [
            _box_mesh_buffers(
                height=float(kwargs["height"]),
                z_offset=float(kwargs["z_offset"]),
            )
            for _group in groups
        ]

    result = run_length_extrude_native_hybrid(
        matched_shapes=shapes,
        num_layers=5,
        layer_h=0.08,
        num_channels=2,
        slot_names=["White", "Red"],
        scale_factor=1.0,
        native_module=_guarded_module(
            merge_run_groups_to_meshes=merge,
        ),
    )

    assert result.stats["native_parallel_source_geometry_count"] == 3_001
    assert result.stats["native_parallel_workers"] == 2
    assert result.stats["native_parallel_batch_count"] >= 3
    assert "native_parallel_source_geometry_limited" not in result.stats


def test_native_batches_commit_in_serial_order_after_parallel_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", raising=False)
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    monkeypatch.setattr(task_parallelism.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(
        task_parallelism,
        "_available_memory_bytes",
        lambda: 8 * 1024**3,
    )
    shapes = _parallel_batch_shapes()

    def run(worker_count: int):
        completion_order = []
        thread_ids = set()

        def merge(groups, **kwargs):
            z_offset = float(kwargs["z_offset"])
            time.sleep(0.02 if z_offset == 0.0 else 0.001)
            thread_ids.add(threading.get_ident())
            completion_order.append(z_offset)
            return [
                _box_mesh_buffers(
                    height=float(kwargs["height"]),
                    z_offset=z_offset,
                )
                for _group in groups
            ]

        monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", str(worker_count))
        result = run_length_extrude_native_hybrid(
            matched_shapes=shapes,
            num_layers=5,
            layer_h=0.08,
            num_channels=2,
            slot_names=["White", "Red"],
            scale_factor=1.0,
            native_module=_guarded_module(
                merge_run_groups_to_meshes=merge,
            ),
        )
        return result, completion_order, thread_ids

    serial, serial_completion, serial_threads = run(1)
    parallel, parallel_completion, parallel_threads = run(2)

    assert _native_result_mesh_signature(parallel) == _native_result_mesh_signature(
        serial
    )
    assert parallel.stats["native_meshes"] == serial.stats["native_meshes"]
    assert parallel.stats["fallback_groups"] == serial.stats["fallback_groups"]
    assert parallel.stats["native_output_meshes"] == serial.stats["native_output_meshes"]
    for counter in (
        "native_group_count",
        "native_input_paths",
        "native_path_cache_hits",
        "native_path_cache_misses",
        "native_empty_meshes",
        "native_invalid_meshes",
        "native_surface_checked",
        "native_surface_rejects",
        "native_call_error",
        "fallback_groups",
    ):
        assert parallel.stats.get(counter, 0) == serial.stats.get(counter, 0)
    assert parallel.stats["native_parallel_workers"] == 2
    assert parallel.stats["native_parallel_batch_count"] >= 3
    assert parallel.stats["native_parallel_source_geometry_count"] == len(shapes)
    assert len(serial_threads) == 1
    assert len(parallel_threads) == 2
    assert parallel_completion != serial_completion


def test_parallel_batches_keep_shapely_surface_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", "1")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    monkeypatch.setattr(task_parallelism.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(
        task_parallelism,
        "_available_memory_bytes",
        lambda: 8 * 1024**3,
    )
    shapes = _parallel_batch_shapes()
    fallback_caches = []
    original_fallback = vector_native_mesh._fallback_extrude_group

    def record_fallback_cache(geoms, **kwargs):
        fallback_caches.append(kwargs["extrude_cache"])
        return original_fallback(geoms, **kwargs)

    monkeypatch.setattr(
        vector_native_mesh,
        "_fallback_extrude_group",
        record_fallback_cache,
    )

    def merge(groups, **kwargs):
        height = float(kwargs["height"])
        z_offset = float(kwargs["z_offset"])
        meshes = []
        for _group in groups:
            vertices, faces = _box_mesh_buffers(
                height=height,
                z_offset=z_offset,
            )
            stretched = np.asarray(vertices, dtype=np.float64)
            stretched[stretched[:, 2] > z_offset, 2] = (
                z_offset + height * 10.0
            )
            meshes.append((stretched, np.asarray(faces, dtype=np.int64)))
        return meshes

    def run(worker_count: int) -> NativeVectorMeshResult:
        monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", str(worker_count))
        return run_length_extrude_native_hybrid(
            matched_shapes=shapes,
            num_layers=5,
            layer_h=0.08,
            num_channels=2,
            slot_names=["White", "Red"],
            scale_factor=1.0,
            native_module=_guarded_module(
                merge_run_groups_to_meshes=merge,
            ),
        )

    serial = run(1)
    serial_fallback_caches = list(fallback_caches)
    fallback_caches.clear()
    parallel = run(2)
    parallel_fallback_caches = list(fallback_caches)

    assert parallel.stats["native_parallel_workers"] == 2
    assert serial_fallback_caches
    assert all(cache is None for cache in serial_fallback_caches)
    assert parallel_fallback_caches
    assert all(cache is None for cache in parallel_fallback_caches)
    assert parallel.stats["native_surface_checked"] == serial.stats[
        "native_surface_checked"
    ]
    assert parallel.stats["native_surface_rejects"] == serial.stats[
        "native_surface_rejects"
    ]
    assert parallel.stats["native_meshes"] == 0
    assert parallel.stats["fallback_groups"] == serial.stats["fallback_groups"]
    assert _native_result_mesh_signature(parallel) == _native_result_mesh_signature(
        serial
    )


def test_parallel_native_call_error_keeps_per_batch_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", raising=False)
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    monkeypatch.setattr(task_parallelism.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(
        task_parallelism,
        "_available_memory_bytes",
        lambda: 8 * 1024**3,
    )
    shapes = _parallel_batch_shapes()

    def merge(groups, **kwargs):
        height = float(kwargs["height"])
        z_offset = float(kwargs["z_offset"])
        if z_offset == pytest.approx(0.08):
            raise RuntimeError("injected native batch failure")
        return [
            _box_mesh_buffers(height=height, z_offset=z_offset)
            for _group in groups
        ]

    def run(worker_count: int) -> NativeVectorMeshResult:
        monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", str(worker_count))
        return run_length_extrude_native_hybrid(
            matched_shapes=shapes,
            num_layers=5,
            layer_h=0.08,
            num_channels=2,
            slot_names=["White", "Red"],
            scale_factor=1.0,
            native_module=_guarded_module(
                merge_run_groups_to_meshes=merge,
            ),
        )

    serial = run(1)
    parallel = run(2)

    assert parallel.stats["native_parallel_workers"] == 2
    assert parallel.stats["native_call_error"] == "RuntimeError"
    assert parallel.stats["fallback_reason_native_call_error"] == serial.stats[
        "fallback_reason_native_call_error"
    ]
    assert parallel.stats["fallback_groups"] == serial.stats["fallback_groups"]
    assert _native_result_mesh_signature(parallel) == _native_result_mesh_signature(
        serial
    )


def test_parallel_executor_failure_reruns_serial_without_partial_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", raising=False)
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    monkeypatch.setattr(task_parallelism.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(
        task_parallelism,
        "_available_memory_bytes",
        lambda: 8 * 1024**3,
    )
    shapes = _parallel_batch_shapes()

    def merge(groups, **kwargs):
        return [
            _box_mesh_buffers(
                height=float(kwargs["height"]),
                z_offset=float(kwargs["z_offset"]),
            )
            for _group in groups
        ]

    module = _guarded_module(merge_run_groups_to_meshes=merge)
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "1")
    serial = run_length_extrude_native_hybrid(
        matched_shapes=shapes,
        num_layers=5,
        layer_h=0.08,
        num_channels=2,
        slot_names=["White", "Red"],
        scale_factor=1.0,
        native_module=module,
    )

    def fail_worker(*_args, **_kwargs):
        raise RuntimeError("injected executor failure")

    monkeypatch.setattr(
        vector_native_mesh,
        "_compute_native_batch",
        fail_worker,
    )
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "2")
    recovered = run_length_extrude_native_hybrid(
        matched_shapes=shapes,
        num_layers=5,
        layer_h=0.08,
        num_channels=2,
        slot_names=["White", "Red"],
        scale_factor=1.0,
        native_module=module,
    )

    assert recovered.stats["native_parallel_workers"] == 1
    assert recovered.stats["native_parallel_requested_workers"] == 2
    assert recovered.stats["native_parallel_error"] == "RuntimeError"
    assert _native_result_mesh_signature(recovered) == _native_result_mesh_signature(
        serial
    )


def test_parallel_outcome_count_mismatch_reruns_serial_without_missing_meshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", raising=False)
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    monkeypatch.setattr(task_parallelism.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(
        task_parallelism,
        "_available_memory_bytes",
        lambda: 8 * 1024**3,
    )
    shapes = _parallel_batch_shapes()

    def merge(groups, **kwargs):
        return [
            _box_mesh_buffers(
                height=float(kwargs["height"]),
                z_offset=float(kwargs["z_offset"]),
            )
            for _group in groups
        ]

    module = _guarded_module(merge_run_groups_to_meshes=merge)
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "1")
    serial = run_length_extrude_native_hybrid(
        matched_shapes=shapes,
        num_layers=5,
        layer_h=0.08,
        num_channels=2,
        slot_names=["White", "Red"],
        scale_factor=1.0,
        native_module=module,
    )

    original_compute = vector_native_mesh._compute_native_batch

    def shorten_one_batch(*args, **kwargs):
        batch = args[1]
        computed = original_compute(*args, **kwargs)
        if batch.index == 0 and computed.outcomes:
            return replace(computed, outcomes=computed.outcomes[:-1])
        return computed

    monkeypatch.setattr(
        vector_native_mesh,
        "_compute_native_batch",
        shorten_one_batch,
    )
    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "2")
    recovered = run_length_extrude_native_hybrid(
        matched_shapes=shapes,
        num_layers=5,
        layer_h=0.08,
        num_channels=2,
        slot_names=["White", "Red"],
        scale_factor=1.0,
        native_module=module,
    )

    assert recovered.stats["native_parallel_workers"] == 1
    assert recovered.stats["native_parallel_requested_workers"] == 2
    assert recovered.stats["native_parallel_error"] == "RuntimeError"
    assert _native_result_mesh_signature(recovered) == _native_result_mesh_signature(
        serial
    )


def test_native_hybrid_falls_back_when_native_module_lacks_area_guard() -> None:
    called = False

    def fake_merge_run_groups_to_meshes(*args, **kwargs):
        nonlocal called
        called = True
        native_mesh = _box_mesh()
        return [(native_mesh.vertices.tolist(), native_mesh.faces.tolist())]

    fake_module = SimpleNamespace(merge_run_groups_to_meshes=fake_merge_run_groups_to_meshes)

    result = run_length_extrude_native_hybrid(
        matched_shapes=[{"geometry": _square(), "recipe": [0]}],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        native_module=fake_module,
    )

    assert called is False
    assert result.stats["native_capability_error"] == "triangulation_area_guard_missing"
    assert result.stats["native_triangulation_area_guard"] == "missing"
    assert result.stats["native_meshes"] == 0
    assert result.stats["fallback_groups"] == 1
    assert result.stats["fallback_reason_capability_missing"] == 1
    assert len(result.meshes_by_slot["White"]["meshes"][0].vertices) > 0


def test_native_hybrid_uses_valid_native_mesh() -> None:
    def fake_merge_run_groups_to_meshes(
        groups,
        *,
        close_delta_mm,
        scale,
        height,
        z_offset,
        xy_scale,
    ):
        assert len(groups) == 1
        assert close_delta_mm == pytest.approx(0.03)
        assert scale == 1_000_000
        assert height == pytest.approx(0.08)
        assert z_offset == pytest.approx(0.0)
        assert xy_scale == pytest.approx(2.0)
        return [
            (
                [
                    (0.0, 0.0, 0.0),
                    (4.0, 0.0, 0.0),
                    (4.0, 4.0, 0.0),
                    (0.0, 4.0, 0.0),
                    (0.0, 0.0, 0.08),
                    (4.0, 0.0, 0.08),
                    (4.0, 4.0, 0.08),
                    (0.0, 4.0, 0.08),
                ],
                [
                    (0, 2, 1),
                    (0, 3, 2),
                    (4, 5, 6),
                    (4, 6, 7),
                    (0, 1, 5),
                    (0, 5, 4),
                    (1, 2, 6),
                    (1, 6, 5),
                    (2, 3, 7),
                    (2, 7, 6),
                    (3, 0, 4),
                    (3, 4, 7),
                ],
            )
        ]

    fake_module = _guarded_module(merge_run_groups_to_meshes=fake_merge_run_groups_to_meshes)
    result = run_length_extrude_native_hybrid(
        matched_shapes=[{"geometry": _square(), "recipe": [0]}],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=2.0,
        native_module=fake_module,
    )

    assert result.stats["native_meshes"] == 1
    assert result.stats["fallback_groups"] == 0
    mesh = result.meshes_by_slot["White"]["meshes"][0]
    assert len(mesh.vertices) == 8
    assert len(mesh.faces) == 12


def test_native_hybrid_reuses_geometry_paths_across_run_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geometry_to_paths_calls = 0
    original_geometry_to_paths = vector_native_mesh._geometry_to_paths

    def counting_geometry_to_paths(geom):
        nonlocal geometry_to_paths_calls
        geometry_to_paths_calls += 1
        return original_geometry_to_paths(geom)

    def fake_merge_run_groups_to_meshes(groups, **kwargs):
        return [
            _box_mesh_buffers(
                height=float(kwargs["height"]),
                z_offset=float(kwargs["z_offset"]),
            )
            for _group in groups
        ]

    monkeypatch.setattr(vector_native_mesh, "_geometry_to_paths", counting_geometry_to_paths)
    square = _square()
    fake_module = _guarded_module(merge_run_groups_to_meshes=fake_merge_run_groups_to_meshes)
    result = run_length_extrude_native_hybrid(
        matched_shapes=[{"geometry": square, "recipe": [0, 1, 0]}],
        num_layers=3,
        layer_h=0.08,
        num_channels=2,
        slot_names=["White", "Red"],
        scale_factor=1.0,
        native_module=fake_module,
    )

    assert geometry_to_paths_calls == 1
    assert result.stats["native_path_cache_hits"] == 2
    assert result.stats["native_path_cache_misses"] == 1
    assert result.stats["native_meshes"] == 3
    assert result.stats["fallback_groups"] == 0


def test_native_hybrid_falls_back_when_native_mesh_is_empty() -> None:
    fake_module = _guarded_module(
        merge_run_groups_to_meshes=lambda *args, **kwargs: [([], [])],
    )
    result = run_length_extrude_native_hybrid(
        matched_shapes=[{"geometry": _square(), "recipe": [0]}],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        native_module=fake_module,
    )

    assert result.stats["native_empty_meshes"] == 1
    assert result.stats["fallback_groups"] == 1
    assert result.stats["fallback_reason_empty_native_mesh"] == 1
    mesh = result.meshes_by_slot["White"]["meshes"][0]
    assert len(mesh.vertices) > 0
    assert len(mesh.faces) > 0


def test_native_hybrid_uses_native_merged_fallback_for_large_empty_groups() -> None:
    calls = []

    def fake_merge_run_groups_to_meshes(groups, **_kwargs):
        calls.append(("mesh", len(groups), sum(len(group) for group in groups)))
        return [([], [])]

    def fake_merge_run_groups(groups, **kwargs):
        calls.append(("merge", len(groups), sum(len(group) for group in groups), kwargs["close_delta_mm"]))
        return [
            [
                [[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]],
            ]
        ]

    fake_module = _guarded_module(
        merge_run_groups=fake_merge_run_groups,
        merge_run_groups_to_meshes=fake_merge_run_groups_to_meshes,
    )
    result = run_length_extrude_native_hybrid(
        matched_shapes=[
            {"geometry": _square_at(float(index) * 3.0), "recipe": [0]}
            for index in range(64)
        ],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        native_module=fake_module,
    )

    assert calls == [("mesh", 1, 64), ("merge", 1, 64, 0.03)]
    assert result.stats["native_empty_meshes"] == 1
    assert result.stats["native_merged_fallback_groups"] == 1
    assert result.stats["native_merged_fallback_polygons"] == 1
    assert result.stats["native_merged_fallback_input_paths"] == 64
    assert result.stats["native_merged_fallback_input_holes"] == 0
    assert result.stats.get("fallback_reason_empty_native_mesh", 0) == 0
    assert result.stats["fallback_reason_native_merged_empty_native_mesh"] == 1
    assert result.stats["fallback_groups"] == 1
    mesh = result.meshes_by_slot["White"]["meshes"][0]
    assert len(mesh.vertices) > 0
    assert len(mesh.faces) > 0


def test_native_hybrid_skips_native_merged_fallback_for_hole_dense_groups() -> None:
    calls = []

    def fake_merge_run_groups_to_meshes(groups, **_kwargs):
        calls.append(("mesh", len(groups), sum(len(group) for group in groups)))
        return [([], [])]

    def fake_merge_run_groups(*_args, **_kwargs):
        raise AssertionError("hole-dense groups should keep the existing fallback")

    def holed_square(index: int) -> Polygon:
        x = float(index) * 4.0
        return Polygon(
            [(x, 0.0), (x + 3.0, 0.0), (x + 3.0, 3.0), (x, 3.0)],
            [
                [(x + 0.4, 0.4), (x + 0.9, 0.4), (x + 0.9, 0.9), (x + 0.4, 0.9)],
                [(x + 1.4, 1.4), (x + 1.9, 1.4), (x + 1.9, 1.9), (x + 1.4, 1.9)],
            ],
        )

    fake_module = _guarded_module(
        merge_run_groups=fake_merge_run_groups,
        merge_run_groups_to_meshes=fake_merge_run_groups_to_meshes,
    )
    result = run_length_extrude_native_hybrid(
        matched_shapes=[
            {"geometry": holed_square(index), "recipe": [0]}
            for index in range(22)
        ],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        native_module=fake_module,
    )

    assert calls == [("mesh", 1, 66)]
    assert result.stats["native_empty_meshes"] == 1
    assert result.stats["native_merged_fallback_skipped_groups"] == 1
    assert result.stats.get("native_merged_fallback_groups", 0) == 0
    assert result.stats["fallback_reason_empty_native_mesh"] == 1
    assert result.stats["fallback_groups"] == 1


def test_native_hybrid_skips_split_retry_for_small_empty_groups() -> None:
    calls = []

    def fake_merge_run_groups_to_meshes(groups, **_kwargs):
        calls.append([len(group) for group in groups])
        return [([], [])]

    fake_module = _guarded_module(merge_run_groups_to_meshes=fake_merge_run_groups_to_meshes)
    result = run_length_extrude_native_hybrid(
        matched_shapes=[
            {"geometry": _square_at(0.0), "recipe": [0]},
            {"geometry": _square_at(4.0), "recipe": [0]},
        ],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        native_module=fake_module,
    )

    assert calls == [[2]]
    assert result.stats["native_empty_meshes"] == 1
    assert result.stats["native_split_retries"] == 0
    assert result.stats["fallback_groups"] == 1
    assert result.stats["fallback_reason_empty_native_mesh"] == 1


def test_native_split_retry_requires_large_non_expanding_reference_groups() -> None:
    assert vector_native_mesh._should_consider_native_split(
        original_geometry_count=344,
        original_path_count=357,
    )
    assert not vector_native_mesh._should_consider_native_split(
        original_geometry_count=304,
        original_path_count=358,
    )
    assert not vector_native_mesh._should_consider_native_split(
        original_geometry_count=133,
        original_path_count=431,
    )
    assert not vector_native_mesh._should_consider_native_split(
        original_geometry_count=260,
        original_path_count=268,
    )
    assert vector_native_mesh._should_retry_native_split(
        original_path_count=357,
        retry_group_count=304,
        retry_path_count=359,
    )
    assert not vector_native_mesh._should_retry_native_split(
        original_path_count=275,
        retry_group_count=203,
        retry_path_count=362,
    )
    assert not vector_native_mesh._should_retry_native_split(
        original_path_count=431,
        retry_group_count=82,
        retry_path_count=996,
    )


def test_native_hybrid_retries_empty_group_as_reference_polygons(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", raising=False)
    monkeypatch.setattr(vector_native_mesh, "NATIVE_SPLIT_RETRY_MIN_ORIGINAL_PATHS", 1)
    monkeypatch.setattr(vector_native_mesh, "NATIVE_SPLIT_RETRY_MIN_POLYGONS", 2)
    native_box = _box_mesh()
    calls = []

    def fake_merge_run_groups_to_meshes(groups, **_kwargs):
        calls.append([len(group) for group in groups])
        if len(groups) == 1:
            return [([], [])]
        return [
            (native_box.vertices.tolist(), native_box.faces.tolist())
            for _group in groups
        ]

    fake_module = _guarded_module(merge_run_groups_to_meshes=fake_merge_run_groups_to_meshes)
    result = run_length_extrude_native_hybrid(
        matched_shapes=[
            {"geometry": _square_at(0.0), "recipe": [0]},
            {"geometry": _square_at(4.0), "recipe": [0]},
        ],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        native_module=fake_module,
    )

    assert calls == [[2], [1, 1]]
    assert result.stats["native_empty_meshes"] == 1
    assert result.stats["native_split_retries"] == 1
    assert result.stats["native_split_group_count"] == 2
    assert result.stats["native_split_meshes"] == 2
    assert result.stats["fallback_groups"] == 0
    assert result.stats.get("fallback_reason_empty_native_mesh", 0) == 0
    assert result.stats["native_coalesced_meshes"] == 2
    assert result.stats["native_output_meshes"] == 1
    assert len(result.meshes_by_slot["White"]["meshes"]) == 1


def test_native_split_retry_prefers_native_merged_polygons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vector_native_mesh, "NATIVE_SPLIT_RETRY_MIN_ORIGINAL_PATHS", 1)
    monkeypatch.setattr(vector_native_mesh, "NATIVE_SPLIT_RETRY_MIN_POLYGONS", 2)

    def fail_reference_polygons(_geoms):
        raise AssertionError("native split retry should not need Shapely reference polygons")

    calls = []

    def fake_merge_run_groups(groups, **kwargs):
        calls.append(("merge", len(groups), kwargs["close_delta_mm"]))
        assert len(groups) == 1
        return [
            [
                [[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]],
                [[(4.0, 0.0), (6.0, 0.0), (6.0, 2.0), (4.0, 2.0)]],
            ]
        ]

    def fake_merge_run_groups_to_meshes(groups, **kwargs):
        calls.append(("mesh", len(groups), kwargs["close_delta_mm"]))
        if len(groups) == 1:
            return [([], [])]
        return [
            _box_mesh_buffers(
                height=float(kwargs["height"]),
                z_offset=float(kwargs["z_offset"]),
            )
            for _group in groups
        ]

    monkeypatch.setattr(
        vector_native_mesh,
        "_reference_polygons_for_native_retry",
        fail_reference_polygons,
    )
    fake_module = _guarded_module(
        merge_run_groups=fake_merge_run_groups,
        merge_run_groups_to_meshes=fake_merge_run_groups_to_meshes,
    )

    result = run_length_extrude_native_hybrid(
        matched_shapes=[
            {"geometry": _square_at(0.0), "recipe": [0]},
            {"geometry": _square_at(4.0), "recipe": [0]},
        ],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        native_module=fake_module,
    )

    assert calls == [("mesh", 1, 0.03), ("merge", 1, 0.03), ("mesh", 2, 0.0)]
    assert result.stats["native_split_retries"] == 1
    assert result.stats["native_split_group_count"] == 2
    assert result.stats["native_split_meshes"] == 2
    assert result.stats["native_path_cache_hits"] == 2
    assert result.stats["native_path_cache_misses"] == 2
    assert result.stats["fallback_groups"] == 0


def test_native_hybrid_falls_back_when_native_returns_too_few_meshes() -> None:
    native_mesh = _box_mesh()
    fake_module = _guarded_module(
        merge_run_groups_to_meshes=lambda *args, **kwargs: [
            (native_mesh.vertices.tolist(), native_mesh.faces.tolist())
        ],
    )
    result = run_length_extrude_native_hybrid(
        matched_shapes=[
            {"geometry": _square_at(0.0), "recipe": [0]},
            {"geometry": _square_at(3.0), "recipe": [1]},
        ],
        num_layers=1,
        layer_h=0.08,
        num_channels=2,
        slot_names=["White", "Red"],
        scale_factor=1.0,
        native_module=fake_module,
    )

    assert result.stats["native_meshes"] == 1
    assert result.stats["native_invalid_meshes"] == 1
    assert result.stats["fallback_groups"] == 1
    assert result.stats["fallback_reason_missing_native_mesh"] == 1
    assert "White" in result.meshes_by_slot
    assert "Red" in result.meshes_by_slot
    assert len(result.meshes_by_slot["Red"]["meshes"][0].vertices) > 0


def test_native_hybrid_accepts_numpy_native_buffers() -> None:
    native_mesh = _box_mesh()
    fake_module = _guarded_module(
        merge_run_groups_to_meshes=lambda *args, **kwargs: [
            (np.asarray(native_mesh.vertices), np.asarray(native_mesh.faces))
        ],
    )
    result = run_length_extrude_native_hybrid(
        matched_shapes=[{"geometry": _square(), "recipe": [0]}],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        native_module=fake_module,
    )

    assert result.stats["native_meshes"] == 1
    assert result.stats["fallback_groups"] == 0
    assert len(result.meshes_by_slot["White"]["meshes"][0].vertices) == 8


def test_ring_reads_coordinate_sequences_without_numpy_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_asarray(*_args, **_kwargs):
        raise AssertionError("hot ring conversion should iterate coordinates directly")

    monkeypatch.setattr(vector_native_mesh.np, "asarray", fail_asarray)

    coords = [
        (0.0, 0.0, 9.0),
        (2.0, 0.0, 9.0),
        (2.0, 2.0, 9.0),
        (0.0, 0.0, 9.0),
    ]

    assert vector_native_mesh._ring(coords) == [
        (0.0, 0.0),
        (2.0, 0.0),
        (2.0, 2.0),
    ]


def test_compiled_native_mesh_module_returns_numpy_arrays() -> None:
    clipper2_batch = pytest.importorskip("clipper2_batch")

    meshes = clipper2_batch.merge_run_groups_to_meshes(
        [[[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]]],
        height=0.08,
        z_offset=0.0,
        xy_scale=1.0,
    )

    vertices, faces = meshes[0]
    assert isinstance(vertices, np.ndarray)
    assert isinstance(faces, np.ndarray)
    assert vertices.dtype == np.float64
    assert faces.dtype == np.int64
    assert vertices.shape == (8, 3)
    assert faces.shape == (12, 3)
    assert vertices.flags.c_contiguous
    assert faces.flags.c_contiguous


def test_compiled_native_mesh_batches_are_byte_exact_across_threads() -> None:
    clipper2_batch = pytest.importorskip("clipper2_batch")
    square = [(0.0, 0.0), (3.0, 0.0), (3.0, 2.0), (0.0, 2.0)]
    outer = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    hole = [(1.0, 1.0), (1.0, 3.0), (3.0, 3.0), (3.0, 1.0)]
    right_square = [
        (5.0, 0.0),
        (7.0, 0.0),
        (7.0, 2.0),
        (5.0, 2.0),
    ]
    batches = [
        ([[square]], 0.08, 0.0),
        ([[outer, hole]], 0.16, 0.08),
        ([[square, right_square]], 0.24, 0.24),
    ]

    def run(batch):
        groups, height, z_offset = batch
        return clipper2_batch.merge_run_groups_to_meshes(
            groups,
            height=height,
            z_offset=z_offset,
            xy_scale=1.7,
        )

    serial = [run(batch) for batch in batches]
    for worker_count in (2, 4):
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            parallel = list(executor.map(run, batches))
        for serial_batch, parallel_batch in zip(serial, parallel):
            assert len(parallel_batch) == len(serial_batch)
            for serial_mesh, parallel_mesh in zip(
                serial_batch,
                parallel_batch,
            ):
                np.testing.assert_array_equal(parallel_mesh[0], serial_mesh[0])
                np.testing.assert_array_equal(parallel_mesh[1], serial_mesh[1])


def test_native_hybrid_coalesces_native_meshes_per_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", raising=False)

    def fake_merge_run_groups_to_meshes(
        groups,
        *,
        close_delta_mm,
        scale,
        height,
        z_offset,
        xy_scale,
    ):
        return [
            _box_mesh_buffers(height=float(height), z_offset=float(z_offset))
            for _group in groups
        ]

    fake_module = _guarded_module(merge_run_groups_to_meshes=fake_merge_run_groups_to_meshes)
    result = run_length_extrude_native_hybrid(
        matched_shapes=[
            {"geometry": _square_at(0.0), "recipe": [0, 0]},
            {"geometry": _square_at(4.0), "recipe": [0, 1]},
        ],
        num_layers=2,
        layer_h=0.08,
        num_channels=2,
        slot_names=["White", "Red"],
        scale_factor=1.0,
        native_module=fake_module,
    )

    assert result.stats["native_meshes"] == 3
    assert result.stats["native_coalesced_meshes"] == 3
    assert result.stats["native_output_meshes"] == 2
    assert len(result.meshes_by_slot["White"]["meshes"]) == 1
    assert len(result.meshes_by_slot["Red"]["meshes"]) == 1



def test_native_hybrid_surface_validation_rejects_area_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", "1")
    native_mesh = _box_mesh()
    stretched_vertices = native_mesh.vertices.copy()
    stretched_vertices[:, 2] *= 10.0
    fake_module = _guarded_module(
        merge_run_groups_to_meshes=lambda *args, **kwargs: [
            (stretched_vertices.tolist(), native_mesh.faces.tolist())
        ],
    )

    result = run_length_extrude_native_hybrid(
        matched_shapes=[{"geometry": _square(), "recipe": [0]}],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        native_module=fake_module,
    )

    assert result.stats["native_surface_rejects"] == 1
    assert result.stats["fallback_groups"] == 1
    assert result.stats["native_meshes"] == 0
    mesh = result.meshes_by_slot["White"]["meshes"][0]
    assert mesh.bounds[1][2] == pytest.approx(0.08)


def test_build_mesh_uses_native_hybrid_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def fake_native_hybrid(**kwargs):
        nonlocal called
        called = True
        assert kwargs["scale_factor"] == pytest.approx(1.0)
        return NativeVectorMeshResult(
            meshes_by_slot={"White": {"meshes": [_box_mesh()], "mat_id": 0}},
            stats={"native_meshes": 1, "fallback_groups": 0},
        )

    monkeypatch.setattr(
        "core.vector_native_mesh.run_length_extrude_native_hybrid",
        fake_native_hybrid,
    )
    processor = _processor()
    processor.enable_native_vector_mesh = True

    scene = processor.build_mesh(
        analysis=_analysis(),
        thickness_mm=0.0,
        structure_mode="Single-sided",
    )

    assert called is True
    assert "White" in scene.geometry
    assert processor.last_native_vector_mesh_stats == {"native_meshes": 1, "fallback_groups": 0}
