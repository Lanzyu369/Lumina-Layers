"""Unit tests for optional native SVG vector mesh extrusion.

These tests keep the accelerated path behind a quality-preserving fallback:
valid native meshes can be used, but empty/invalid native output must fall
back to the current Shapely/trimesh extrusion.
"""

from __future__ import annotations

import threading
import time
import sys
import gc
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh
from shapely import wkt
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

import core.vector_native_mesh as vector_native_mesh
from core import task_parallelism
from core.system_capacity import EffectiveCpuCapacity
from core.task_parallelism import AdaptiveParallelismPlan
from core.errors import VectorMeshMemoryBudgetError
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
        native_mesh_capabilities=lambda: {
            "triangulation_area_guard": True,
            "indexed_edge_manifold_guard": True,
        },
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


def _assert_public_mesh_contract(result: NativeVectorMeshResult) -> None:
    """Final slot meshes must never expose internal native buffer tuples."""

    assert result.meshes_by_slot
    for slot_data in result.meshes_by_slot.values():
        assert "_native_buffers" not in slot_data
        assert slot_data["meshes"]
        for mesh in slot_data["meshes"]:
            assert isinstance(mesh, trimesh.Trimesh)
            assert len(mesh.vertices) > 0
            assert len(mesh.faces) > 0
            assert np.all(np.isfinite(mesh.bounds))


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
    assert vector_native_mesh.NATIVE_BATCH_INPUT_BYTES_PER_POINT >= 128


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


def test_native_parallelism_stats_record_cpu_topology() -> None:
    plan = task_parallelism.AdaptiveParallelismPlan(
        workers=16,
        requested_ceiling=32,
        effective_cpu_capacity=32,
        outer_demand=1,
        cpu_fair_share_ceiling=32,
        work_item_ceiling=44,
        work_unit_ceiling=16,
        stage_ceiling=32,
        memory_ceiling=20,
        available_memory_bytes=64 * 1024**3,
        estimated_worker_bytes=384 * 1024**2,
        limiting_reason="work_units",
        demand_snapshot_fallback=False,
        cpu_topology="heterogeneous",
        cpu_scheduling_policy="os_core_type_scheduler",
        performance_cpu_capacity=16,
    )
    stats: dict[str, float | int | str] = {}

    vector_native_mesh._record_native_parallelism_plan(stats, plan)

    assert stats["native_parallel_cpu_topology"] == "heterogeneous"
    assert stats["native_parallel_cpu_scheduling_policy"] == (
        "os_core_type_scheduler"
    )
    assert stats["native_parallel_performance_cpu"] == 16


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
    monkeypatch.setenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", "1")
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
    _assert_public_mesh_contract(result)
    assert result.stats["native_meshes"] == 5
    assert result.stats["native_coalesced_meshes"] == 5
    assert result.stats["native_output_meshes"] == 1


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
    original_fallback = (
        vector_native_mesh._extrude_source_geometries_with_coverage_guard
    )

    def record_fallback_cache(geoms, merged, **kwargs):
        fallback_caches.append(kwargs["extrude_cache"])
        return original_fallback(geoms, merged, **kwargs)

    monkeypatch.setattr(
        vector_native_mesh,
        "_extrude_source_geometries_with_coverage_guard",
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


def test_native_memory_error_is_not_converted_to_python_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native allocation failure must abort instead of allocating fallback too."""

    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "1")

    def fail_native(*_args, **_kwargs):
        raise MemoryError("injected native allocation failure")

    with pytest.raises(MemoryError, match="injected native allocation failure"):
        run_length_extrude_native_hybrid(
            matched_shapes=[{"geometry": _square(), "recipe": [0]}],
            num_layers=1,
            layer_h=0.08,
            num_channels=1,
            slot_names=["White"],
            scale_factor=1.0,
            native_module=_guarded_module(
                merge_run_groups_to_meshes=fail_native,
            ),
        )


def test_serial_surface_reject_releases_native_arrays_before_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected native candidate must not overlap the Python rebuild."""

    monkeypatch.setenv("LUMINA_VECTOR_PARALLELISM", "1")
    array_refs: list[weakref.ReferenceType[np.ndarray]] = []
    released_at_fallback: list[bool] = []

    def merge(_groups, **kwargs):
        vertices, faces = _box_mesh_buffers(
            height=float(kwargs["height"]),
            z_offset=float(kwargs["z_offset"]),
        )
        vertex_array = np.asarray(vertices, dtype=np.float64)
        face_array = np.asarray(faces, dtype=np.int64)
        array_refs.extend((weakref.ref(vertex_array), weakref.ref(face_array)))
        return [(vertex_array, face_array)]

    def record_fallback(*_args, **_kwargs):
        gc.collect()
        released_at_fallback.append(all(ref() is None for ref in array_refs))

    monkeypatch.setattr(
        vector_native_mesh,
        "_native_source_coverage_matches_arrays",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(vector_native_mesh, "_fallback_key", record_fallback)

    run_length_extrude_native_hybrid(
        matched_shapes=[{"geometry": _square(), "recipe": [0]}],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        native_module=_guarded_module(merge_run_groups_to_meshes=merge),
    )

    assert released_at_fallback == [True]


def test_parallel_surface_reject_releases_native_arrays_before_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Computed batch outcomes must not retain rejected native arrays."""

    batch_items = _native_batch_items(1)
    cheap_costs = [
        vector_native_mesh._estimate_native_jobs_cost(jobs)
        for (_height_z, jobs) in batch_items
    ]
    representative_bytes = cheap_costs[0].estimated_bytes
    array_refs: list[weakref.ReferenceType[np.ndarray]] = []
    released_at_fallback: list[bool] = []

    def merge(_groups, **kwargs):
        vertices, faces = _box_mesh_buffers(
            height=float(kwargs["height"]),
            z_offset=float(kwargs["z_offset"]),
        )
        vertex_array = np.asarray(vertices, dtype=np.float64)
        face_array = np.asarray(faces, dtype=np.int64)
        array_refs.extend((weakref.ref(vertex_array), weakref.ref(face_array)))
        return [(vertex_array, face_array)]

    def record_fallback(*_args, **_kwargs):
        gc.collect()
        released_at_fallback.append(all(ref() is None for ref in array_refs))

    monkeypatch.setattr(
        vector_native_mesh,
        "_native_source_coverage_matches_arrays",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(vector_native_mesh, "_fallback_key", record_fallback)

    result, error = vector_native_mesh._try_run_native_batches_parallel(
        module=_guarded_module(merge_run_groups_to_meshes=merge),
        batch_items=batch_items,
        run_group_count=1,
        source_geometry_count=1,
        parallelism_plan=_native_plan(
            2,
            available_memory_bytes=1024**3 + representative_bytes * 2,
        ),
        cheap_batch_costs=cheap_costs,
        representative_batch_bytes=representative_bytes,
        scale_factor=1.0,
        slot_names=["White"],
        extrude_cache=None,
    )

    assert error == ""
    assert result is not None
    assert released_at_fallback == [True]


def test_split_surface_reject_releases_entire_native_batch_before_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Split retry must discard all rejected candidates before rebuilding."""

    polygons = [_square(), _square_at(4.0)]
    retry_groups = [
        vector_native_mesh._geometry_to_paths(poly)
        for poly in polygons
    ]
    array_refs: list[weakref.ReferenceType[np.ndarray]] = []
    released_at_fallback: list[bool] = []

    def merge_split(**_kwargs):
        meshes = []
        for index in range(2):
            vertices, faces = _box_mesh_buffers(z_offset=index * 0.08)
            vertex_array = np.asarray(vertices, dtype=np.float64)
            face_array = np.asarray(faces, dtype=np.int64)
            array_refs.extend(
                (weakref.ref(vertex_array), weakref.ref(face_array))
            )
            meshes.append((vertex_array, face_array))
        return meshes

    def record_fallback(*_args, **_kwargs):
        gc.collect()
        released_at_fallback.append(all(ref() is None for ref in array_refs))

    monkeypatch.setattr(
        vector_native_mesh,
        "_should_consider_native_split",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        vector_native_mesh,
        "_should_retry_native_split",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        vector_native_mesh,
        "_merge_native_split_retry_groups_to_meshes",
        merge_split,
    )
    monkeypatch.setattr(
        vector_native_mesh,
        "_surface_validation_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        vector_native_mesh,
        "_native_mesh_surface_is_acceptable",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(vector_native_mesh, "_fallback_key", record_fallback)

    result = vector_native_mesh._retry_native_group_as_reference_polygons_unchecked(
        module=SimpleNamespace(),
        key=(0, 0, 0),
        geoms=polygons,
        original_path_count=2,
        height=0.08,
        z_bot=0.0,
        scale_factor=1.0,
        slot_names=["White"],
        meshes_by_slot={},
        extrude_cache=None,
        stats=vector_native_mesh._empty_stats(),
        path_cache=None,
        prepared_retry_groups=retry_groups,
    )

    assert result is True
    assert released_at_fallback == [True, True]


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

    fake_module = SimpleNamespace(
        native_mesh_capabilities=lambda: {
            "indexed_edge_manifold_guard": True,
        },
        merge_run_groups_to_meshes=fake_merge_run_groups_to_meshes,
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

    assert called is False
    assert result.stats["native_capability_error"] == "triangulation_area_guard_missing"
    assert result.stats["native_triangulation_area_guard"] == "missing"
    assert result.stats["native_meshes"] == 0
    assert result.stats["fallback_groups"] == 1
    assert result.stats["fallback_reason_capability_missing"] == 1
    assert len(result.meshes_by_slot["White"]["meshes"][0].vertices) > 0


def test_native_hybrid_falls_back_when_native_module_lacks_topology_guard() -> None:
    """Old native binaries must not bypass indexed edge safety."""

    called = False

    def fake_merge_run_groups_to_meshes(*args, **kwargs):
        nonlocal called
        called = True
        native_mesh = _box_mesh()
        return [(native_mesh.vertices.tolist(), native_mesh.faces.tolist())]

    fake_module = SimpleNamespace(
        native_mesh_capabilities=lambda: {"triangulation_area_guard": True},
        merge_run_groups_to_meshes=fake_merge_run_groups_to_meshes,
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

    assert called is False
    assert result.stats["native_topology_guard"] == "missing"
    assert "indexed_edge_manifold_guard" in result.stats["native_capability_error"]
    assert result.stats["native_meshes"] == 0
    assert result.stats["fallback_groups"] == 1
    assert result.stats["fallback_reason_capability_missing"] == 1


def test_native_hybrid_uses_valid_native_mesh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", "1")

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
    _assert_public_mesh_contract(result)
    mesh = result.meshes_by_slot["White"]["meshes"][0]
    assert len(mesh.vertices) == 8
    assert len(mesh.faces) == 12
    np.testing.assert_allclose(mesh.bounds, [[0.0, 0.0, 0.0], [4.0, 4.0, 0.08]])


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


def test_native_path_cache_is_byte_bounded(
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
    monkeypatch.setattr(vector_native_mesh, "NATIVE_PATH_CACHE_BUDGET_BYTES", 1)
    square = _square()
    result = run_length_extrude_native_hybrid(
        matched_shapes=[{"geometry": square, "recipe": [0, 1, 0]}],
        num_layers=3,
        layer_h=0.08,
        num_channels=2,
        slot_names=["White", "Red"],
        scale_factor=1.0,
        native_module=_guarded_module(
            merge_run_groups_to_meshes=fake_merge_run_groups_to_meshes,
        ),
    )

    assert geometry_to_paths_calls == 3
    assert result.stats["native_path_cache_peak_bytes"] <= 1
    assert result.stats["native_path_cache_oversized_rejections"] == 3


def test_native_buffer_coalescing_uses_one_bounded_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_raw = _box_mesh_buffers(height=0.08, z_offset=0.0)
    second_raw = _box_mesh_buffers(height=0.08, z_offset=0.08)
    first = (np.asarray(first_raw[0]), np.asarray(first_raw[1]))
    second = (np.asarray(second_raw[0]), np.asarray(second_raw[1]))
    guard_calls: list[dict[str, int | str]] = []

    monkeypatch.setattr(
        vector_native_mesh,
        "_enforce_vector_mesh_runtime_headroom",
        lambda **kwargs: guard_calls.append(kwargs),
    )
    monkeypatch.setattr(
        vector_native_mesh.np,
        "vstack",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("native buffer coalescing must not vstack full copies")
        ),
    )

    mesh = vector_native_mesh._coalesced_mesh_from_buffers([first, second])

    assert mesh is not None
    assert len(mesh.vertices) == len(first[0]) + len(second[0])
    assert len(mesh.faces) == len(first[1]) + len(second[1])
    assert guard_calls
    assert guard_calls[0]["stage"] == "native_buffer_coalescing"


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


def test_native_hybrid_rejects_lossy_merged_fallback_for_large_empty_groups() -> None:
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
    assert result.stats["native_merged_fallback_groups"] == 0
    assert result.stats["native_merged_fallback_polygons"] == 0
    assert result.stats["native_merged_fallback_input_paths"] == 0
    assert result.stats["native_merged_fallback_input_holes"] == 0
    assert result.stats["fallback_reason_empty_native_mesh"] == 1
    assert result.stats.get("fallback_reason_native_merged_empty_native_mesh", 0) == 0
    assert result.stats["fallback_groups"] == 1
    meshes = result.meshes_by_slot["White"]["meshes"]
    assert len(meshes) == 64
    assert sum(abs(float(mesh.volume)) for mesh in meshes) == pytest.approx(
        64 * 4.0 * 0.08
    )


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
    monkeypatch.setenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", "1")
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
    _assert_public_mesh_contract(result)


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


def test_native_split_retry_reuses_rejected_groups_from_first_native_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vector_native_mesh, "NATIVE_SPLIT_RETRY_MIN_ORIGINAL_PATHS", 1)
    monkeypatch.setattr(vector_native_mesh, "NATIVE_SPLIT_RETRY_MIN_POLYGONS", 2)
    path_left = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    path_right = [(4.0, 0.0), (6.0, 0.0), (6.0, 2.0), (4.0, 2.0)]
    calls = []

    def fake_merge_run_groups_to_meshes(groups, **kwargs):
        capture_rejected = bool(kwargs.get("return_rejected_groups"))
        calls.append((len(groups), capture_rejected))
        if capture_rejected:
            return [([], [])], [[[path_left], [path_right]]]
        return [
            _box_mesh_buffers(
                height=float(kwargs["height"]),
                z_offset=float(kwargs["z_offset"]),
            )
            for _group in groups
        ]

    fake_module = SimpleNamespace(
        native_mesh_capabilities=lambda: {
            "triangulation_area_guard": True,
            "indexed_edge_manifold_guard": True,
            "rejected_group_reuse": True,
        },
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

    assert calls == [(1, True), (2, False)]
    assert result.stats["native_rejected_groups_reused"] == 1
    assert result.stats["native_split_meshes"] == 2
    assert result.stats["fallback_groups"] == 0


def test_native_split_retry_uses_precomputed_native_mesh_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", "1")
    monkeypatch.setattr(vector_native_mesh, "NATIVE_SPLIT_RETRY_MIN_ORIGINAL_PATHS", 1)
    monkeypatch.setattr(vector_native_mesh, "NATIVE_SPLIT_RETRY_MIN_POLYGONS", 2)
    retry_meshes = [
        _box_mesh_buffers(height=0.08, z_offset=0.0),
        _box_mesh_buffers(height=0.08, z_offset=0.0),
    ]
    calls = []

    def fake_merge_run_groups_to_meshes(groups, **kwargs):
        precompute_retry = bool(kwargs.get("return_rejected_meshes"))
        calls.append((len(groups), precompute_retry))
        if precompute_retry:
            retry_record = (
                retry_meshes,
                np.asarray([0, 0], dtype=np.uint8),
                {},
                2,
            )
            return (
                [([], [])],
                np.asarray([2], dtype=np.uint8),
                [retry_record],
            )
        return [([], [])]

    fake_module = SimpleNamespace(
        native_mesh_capabilities=lambda: {
            "triangulation_area_guard": True,
            "indexed_edge_manifold_guard": True,
            "rejected_mesh_retry": True,
            "native_surface_validation": True,
        },
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

    assert calls == [(1, True)]
    assert result.stats["native_rejected_mesh_retries_reused"] == 1
    assert result.stats["native_surface_checked"] == 2
    assert result.stats["native_split_meshes"] == 2
    assert result.stats["fallback_groups"] == 0
    assert result.stats["native_coalesced_meshes"] == 2
    assert result.stats["native_output_meshes"] == 1
    _assert_public_mesh_contract(result)


def test_native_split_retry_reuses_precomputed_small_group() -> None:
    """Already-computed safe retries should not be repeated in Python."""

    retry_record = (
        [
            _box_mesh_buffers(height=0.08, z_offset=0.0),
            _box_mesh_buffers(height=0.08, z_offset=0.0),
        ],
        np.asarray([0, 0], dtype=np.uint8),
        {},
        2,
    )
    module = SimpleNamespace(
        native_mesh_capabilities=lambda: {
            "triangulation_area_guard": True,
            "indexed_edge_manifold_guard": True,
            "rejected_mesh_retry": True,
            "native_surface_validation": True,
        },
        merge_run_groups_to_meshes=lambda *_args, **_kwargs: (
            [([], [])],
            np.asarray([2], dtype=np.uint8),
            [retry_record],
        ),
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
        native_module=module,
    )

    assert result.stats["native_rejected_mesh_retries_reused"] == 1
    assert result.stats["native_split_meshes"] == 2
    assert result.stats["fallback_groups"] == 0


def test_native_split_retry_accepts_one_coalesced_native_mesh_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accepted retry polygons may cross the extension boundary as one mesh."""

    monkeypatch.setenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", "1")
    monkeypatch.setattr(vector_native_mesh, "NATIVE_SPLIT_RETRY_MIN_ORIGINAL_PATHS", 1)
    monkeypatch.setattr(vector_native_mesh, "NATIVE_SPLIT_RETRY_MIN_POLYGONS", 2)

    first_vertices, first_faces = _box_mesh_buffers(height=0.08, z_offset=0.0)
    second_vertices = np.asarray(first_vertices, dtype=np.float64).copy()
    second_vertices[:, 0] += 4.0
    first_vertices = np.asarray(first_vertices, dtype=np.float64)
    first_faces = np.asarray(first_faces, dtype=np.int64)
    coalesced_mesh = (
        np.vstack((first_vertices, second_vertices)),
        np.vstack((first_faces, first_faces + len(first_vertices))),
    )
    fallback_path = [
        (8.0, 0.0),
        (10.0, 0.0),
        (10.0, 2.0),
        (8.0, 2.0),
    ]
    retry_record = (
        coalesced_mesh,
        np.asarray([0, 0, 2], dtype=np.uint8),
        {2: [[fallback_path]]},
        3,
        True,
    )

    stats = vector_native_mesh._empty_stats()
    meshes_by_slot = {}
    committed = vector_native_mesh._commit_precomputed_native_split_retry(
        key=(0, 0, 0),
        original_path_count=3,
        retry_record=retry_record,
        height=0.08,
        z_bot=0.0,
        scale_factor=1.0,
        slot_names=["White"],
        meshes_by_slot=meshes_by_slot,
        extrude_cache={},
        stats=stats,
    )

    assert committed is True
    assert stats["native_rejected_mesh_retries_reused"] == 1
    assert stats["native_split_group_count"] == 3
    assert stats["native_split_meshes"] == 2
    assert stats["native_split_fallback_groups"] == 1
    assert stats["fallback_groups"] == 1
    assert len(meshes_by_slot["White"]["_native_buffers"]) == 1


def test_unvalidated_native_retry_records_are_not_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", "1")
    retry_record = (
        [_box_mesh_buffers(height=0.08, z_offset=0.0)],
        np.asarray([0], dtype=np.uint8),
        {},
        1,
    )
    module = SimpleNamespace(
        native_mesh_capabilities=lambda: {
            "triangulation_area_guard": True,
            "indexed_edge_manifold_guard": True,
            "rejected_mesh_retry": True,
        },
        merge_run_groups_to_meshes=lambda *_args, **_kwargs: (
            [([], [])],
            np.asarray([2], dtype=np.uint8),
            [retry_record],
        ),
    )

    _meshes, _rejected_groups, retry_records, primary_statuses = (
        vector_native_mesh._run_native_mesh_call(
            module=module,
            groups=[[]],
            height=0.08,
            z_bot=0.0,
            scale_factor=1.0,
        )
    )

    assert retry_records == ()
    assert primary_statuses == ()


def test_native_split_retry_parallel_chunks_preserve_exact_group_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry_groups = [
        [
            [
                (float(index), 0.0),
                (float(index) + 0.5, 0.0),
                (float(index) + 0.5, 0.5),
                (float(index), 0.5),
            ]
        ]
        for index in range(64)
    ]
    worker_threads: set[int] = set()
    worker_lock = threading.Lock()
    worker_barrier = threading.Barrier(4)

    def fake_merge_run_groups_to_meshes(groups, **_kwargs):
        with worker_lock:
            worker_threads.add(threading.get_ident())
        worker_barrier.wait(timeout=2.0)
        return [
            (
                np.asarray([[group[0][0][0], 0.0, 0.0]], dtype=np.float64),
                np.asarray([[0, 0, 0]], dtype=np.int64),
            )
            for group in groups
        ]

    monkeypatch.setattr(
        vector_native_mesh,
        "resolve_task_parallelism_plan",
        lambda *_args, **_kwargs: SimpleNamespace(workers=4),
    )
    stats = vector_native_mesh._empty_stats()

    meshes = vector_native_mesh._merge_native_split_retry_groups_to_meshes(
        module=SimpleNamespace(
            merge_run_groups_to_meshes=fake_merge_run_groups_to_meshes,
        ),
        retry_groups=retry_groups,
        height=0.08,
        z_bot=0.0,
        scale_factor=1.0,
        stats=stats,
    )

    assert len(worker_threads) == 4
    assert stats["native_split_parallel_workers"] == 4
    assert [mesh[0][0, 0] for mesh in meshes] == list(map(float, range(64)))


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


def test_native_hybrid_accepts_numpy_native_buffers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", "1")

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
    _assert_public_mesh_contract(result)
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


def test_compiled_native_mesh_keeps_point_touching_shells_independent() -> None:
    """Point-touching polygons must not become one 4-face indexed edge."""

    clipper2_batch = pytest.importorskip("clipper2_batch")
    groups = [
        [
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
            [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)],
        ]
    ]

    meshes = clipper2_batch.merge_run_groups_to_meshes(
        groups,
        close_delta_mm=0.0,
        height=0.08,
        z_offset=0.0,
        xy_scale=1.0,
    )

    vertices, faces = meshes[0]
    assert vertices.shape == (16, 3)
    assert faces.shape == (24, 3)
    edges = np.sort(
        np.concatenate(
            (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]),
            axis=0,
        ),
        axis=1,
    )
    _unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    assert np.all(counts == 2)


def test_compiled_native_mesh_handles_lum_20260811_002_ring_contact() -> None:
    """The production contour must stay closed through the native path."""

    clipper2_batch = pytest.importorskip("clipper2_batch")
    fixture_path = (
        Path(__file__).parent
        / "fixtures"
        / "svg_regression"
        / "lum_20260811_002_ring_contact.wkt"
    )
    polygon = wkt.loads(fixture_path.read_text(encoding="utf-8"))
    result = run_length_extrude_native_hybrid(
        matched_shapes=[{"geometry": polygon, "recipe": [0]}],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=0.2762232707950837,
        native_module=clipper2_batch,
    )

    mesh = result.meshes_by_slot["White"]["meshes"][0]
    edges = np.asarray(mesh.edges_sorted, dtype=np.int64)
    _unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    assert result.stats["native_topology_guard"] == "present"
    assert mesh.is_watertight
    assert np.all(counts == 2)
    assert abs(float(mesh.volume)) == pytest.approx(
        float(polygon.area) * 0.2762232707950837**2 * 0.08,
        rel=1e-6,
    )


def test_compiled_native_mesh_can_return_rejected_merged_groups() -> None:
    clipper2_batch = pytest.importorskip("clipper2_batch")
    groups = [
        [[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]],
        [[(4.0, 0.0), (6.0, 0.0), (6.0, 2.0), (4.0, 2.0)]],
    ]

    assert clipper2_batch.native_mesh_capabilities()["rejected_group_reuse"]
    assert clipper2_batch.native_mesh_capabilities()["rejected_mesh_retry"]
    assert clipper2_batch.native_mesh_capabilities()[
        "coalesced_rejected_mesh_retry"
    ]
    assert clipper2_batch.native_mesh_capabilities()["native_surface_validation"]
    assert clipper2_batch.native_mesh_capabilities()["indexed_edge_manifold_guard"]
    baseline = clipper2_batch.merge_run_groups_to_meshes(groups)
    meshes, rejected_groups = clipper2_batch.merge_run_groups_to_meshes(
        groups,
        return_rejected_groups=True,
    )

    assert rejected_groups == [[], []]
    for baseline_mesh, candidate_mesh in zip(baseline, meshes):
        np.testing.assert_array_equal(candidate_mesh[0], baseline_mesh[0])
        np.testing.assert_array_equal(candidate_mesh[1], baseline_mesh[1])

    direct_meshes, primary_statuses, retry_records = (
        clipper2_batch.merge_run_groups_to_meshes(
            groups,
            return_rejected_meshes=True,
            validate_retry_surfaces=True,
            validate_primary_surfaces=True,
        )
    )
    np.testing.assert_array_equal(primary_statuses, np.zeros(2, dtype=np.uint8))
    assert retry_records == [None, None]
    for baseline_mesh, candidate_mesh in zip(baseline, direct_meshes):
        np.testing.assert_array_equal(candidate_mesh[0], baseline_mesh[0])
        np.testing.assert_array_equal(candidate_mesh[1], baseline_mesh[1])

    _coalesced_meshes, coalesced_statuses, coalesced_records = (
        clipper2_batch.merge_run_groups_to_meshes(
            groups,
            return_rejected_meshes=True,
            coalesce_retry_meshes=True,
            validate_retry_surfaces=True,
            validate_primary_surfaces=True,
        )
    )
    np.testing.assert_array_equal(
        coalesced_statuses,
        np.zeros(2, dtype=np.uint8),
    )
    assert coalesced_records == [None, None]


def test_native_mesh_call_requests_coalesced_retry_when_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs = {}

    def fake_merge(groups, **kwargs):
        captured_kwargs.update(kwargs)
        return (
            [([], [])],
            np.asarray([2], dtype=np.uint8),
            [None],
        )

    module = SimpleNamespace(
        native_mesh_capabilities=lambda: {
            "rejected_mesh_retry": True,
            "coalesced_rejected_mesh_retry": True,
            "native_surface_validation": True,
        },
        merge_run_groups_to_meshes=fake_merge,
    )

    vector_native_mesh._run_native_mesh_call(
        module=module,
        groups=[[[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0)]]],
        height=0.08,
        z_bot=0.0,
        scale_factor=1.0,
    )

    assert captured_kwargs["return_rejected_meshes"] is True
    assert captured_kwargs["coalesce_retry_meshes"] is True


def test_compiled_native_rejected_retry_coalescing_is_opt_in() -> None:
    clipper2_batch = pytest.importorskip("clipper2_batch")
    with pytest.raises(ValueError, match="requires return_rejected_meshes"):
        clipper2_batch.merge_run_groups_to_meshes(
            [[[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0)]]],
            coalesce_retry_meshes=True,
        )


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


def test_compiled_native_split_chunks_are_byte_exact_and_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clipper2_batch = pytest.importorskip("clipper2_batch")
    groups = [
        [
            [
                (float(index), 0.0),
                (float(index) + 0.75, 0.0),
                (float(index) + 0.75, 0.75),
                (float(index), 0.75),
            ]
        ]
        for index in range(1_024)
    ]
    serial = clipper2_batch.merge_run_groups_to_meshes(
        groups,
        close_delta_mm=0.0,
        height=0.08,
        z_offset=0.16,
        xy_scale=1.7,
    )
    monkeypatch.setattr(
        vector_native_mesh,
        "resolve_task_parallelism_plan",
        lambda *_args, **_kwargs: SimpleNamespace(workers=4),
    )

    parallel = vector_native_mesh._merge_native_split_retry_groups_to_meshes(
        module=clipper2_batch,
        retry_groups=groups,
        height=0.08,
        z_bot=0.16,
        scale_factor=1.7,
        stats=vector_native_mesh._empty_stats(),
    )

    assert len(parallel) == len(serial)
    for serial_mesh, parallel_mesh in zip(serial, parallel):
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
    assert list(result.meshes_by_slot) == ["White", "Red"]
    assert [slot["mat_id"] for slot in result.meshes_by_slot.values()] == [0, 1]
    assert len(result.meshes_by_slot["White"]["meshes"]) == 1
    assert len(result.meshes_by_slot["Red"]["meshes"]) == 1
    _assert_public_mesh_contract(result)


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
    _assert_public_mesh_contract(result)
    mesh = result.meshes_by_slot["White"]["meshes"][0]
    assert mesh.bounds[1][2] == pytest.approx(0.08)


def test_native_guard_compares_output_with_untouched_source_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native self-validation must not hide a component lost before meshing."""

    monkeypatch.setenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", "1")
    left = _square()
    right = _square_at(4.0)
    left_only = _box_mesh_buffers(height=0.08)

    fake_module = SimpleNamespace(
        native_mesh_capabilities=lambda: {
            "triangulation_area_guard": True,
            "indexed_edge_manifold_guard": True,
            "rejected_mesh_retry": True,
            "native_surface_validation": True,
        },
        # Simulate a native pipeline that claims its own lossy result passed.
        merge_run_groups_to_meshes=lambda *_args, **_kwargs: (
            [left_only],
            [vector_native_mesh.NATIVE_RETRY_MESH_ACCEPTED],
            [None],
        ),
    )

    result = run_length_extrude_native_hybrid(
        matched_shapes=[
            {"geometry": left, "recipe": [0]},
            {"geometry": right, "recipe": [0]},
        ],
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
    meshes = result.meshes_by_slot["White"]["meshes"]
    assert sum(abs(float(mesh.volume)) for mesh in meshes) == pytest.approx(
        (float(left.area) + float(right.area)) * 0.08
    )


def test_native_guard_rejects_lost_5mm_island_beside_200mm_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A large main body may not dilute the loss of a printable island."""

    monkeypatch.setenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", "1")
    main_body = Polygon(
        [(0.0, 0.0), (200.0, 0.0), (200.0, 200.0), (0.0, 200.0)]
    )
    small_island = Polygon(
        [(210.0, 0.0), (215.0, 0.0), (215.0, 5.0), (210.0, 5.0)]
    )
    main_mesh = VectorProcessor._extrude_geometry(
        main_body,
        height=0.08,
        z_offset=0.0,
        scale=1.0,
    )[0]
    main_only = (main_mesh.vertices.tolist(), main_mesh.faces.tolist())
    fake_module = SimpleNamespace(
        native_mesh_capabilities=lambda: {
            "triangulation_area_guard": True,
            "indexed_edge_manifold_guard": True,
            "rejected_mesh_retry": True,
            "native_surface_validation": True,
        },
        merge_run_groups_to_meshes=lambda *_args, **_kwargs: (
            [main_only],
            [vector_native_mesh.NATIVE_RETRY_MESH_ACCEPTED],
            [None],
        ),
    )

    result = run_length_extrude_native_hybrid(
        matched_shapes=[
            {"geometry": main_body, "recipe": [0]},
            {"geometry": small_island, "recipe": [0]},
        ],
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
    meshes = result.meshes_by_slot["White"]["meshes"]
    assert sum(abs(float(mesh.volume)) for mesh in meshes) == pytest.approx(
        (40000.0 + 25.0) * 0.08,
        rel=1e-9,
        abs=1e-6,
    )


def test_legacy_native_guard_also_compares_untouched_source_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Modules without primary statuses still need the independent source gate."""

    monkeypatch.setenv("LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE", "1")
    left = _square()
    right = _square_at(4.0)
    monkeypatch.setattr(
        vector_native_mesh,
        "_merged_reference_geometry",
        lambda _geoms: left,
    )
    fake_module = _guarded_module(
        merge_run_groups_to_meshes=lambda *_args, **_kwargs: [
            _box_mesh_buffers(height=0.08)
        ],
    )

    result = run_length_extrude_native_hybrid(
        matched_shapes=[
            {"geometry": left, "recipe": [0]},
            {"geometry": right, "recipe": [0]},
        ],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        native_module=fake_module,
    )

    assert result.stats["native_surface_rejects"] == 1
    assert result.stats["fallback_groups"] == 1
    meshes = result.meshes_by_slot["White"]["meshes"]
    assert sum(abs(float(mesh.volume)) for mesh in meshes) == pytest.approx(
        (float(left.area) + float(right.area)) * 0.08
    )


def test_native_split_retry_cannot_commit_partial_source_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lossy prepared retry record is discarded before source fallback."""

    left = _square()
    right = _square_at(4.0)
    monkeypatch.setattr(
        vector_native_mesh,
        "NATIVE_SPLIT_RETRY_MIN_ORIGINAL_PATHS",
        1,
    )
    monkeypatch.setattr(
        vector_native_mesh,
        "NATIVE_SPLIT_RETRY_MIN_POLYGONS",
        2,
    )
    monkeypatch.setattr(
        vector_native_mesh,
        "NATIVE_SPLIT_RETRY_MAX_PATH_RATIO",
        2.0,
    )
    monkeypatch.setattr(
        vector_native_mesh,
        "NATIVE_SPLIT_RETRY_MAX_ORIGINAL_PATHS_PER_GEOM",
        2.0,
    )
    monkeypatch.setattr(
        vector_native_mesh,
        "_native_retry_groups_for_native_retry",
        lambda **_kwargs: [
            [[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]],
            [[(4.0, 0.0), (6.0, 0.0), (6.0, 2.0), (4.0, 2.0)]],
        ],
    )
    monkeypatch.setattr(
        vector_native_mesh,
        "_commit_precomputed_native_split_retry",
        lambda **kwargs: (
            vector_native_mesh._append_native_buffer(
                kwargs["meshes_by_slot"],
                kwargs["slot_names"][kwargs["key"][0]],
                kwargs["key"][0],
                _box_mesh_buffers(height=kwargs["height"]),
            )
            or True
        ),
    )
    left_only = _box_mesh_buffers(height=0.08)
    lossy_retry_record = (
        left_only,
        np.asarray(
            [
                vector_native_mesh.NATIVE_RETRY_MESH_ACCEPTED,
                vector_native_mesh.NATIVE_RETRY_MESH_EMPTY,
            ],
            dtype=np.uint8,
        ),
        {
            1: [
                [
                    (4.0, 0.0),
                    (4.1, 0.0),
                    (4.1, 0.1),
                    (4.0, 0.1),
                ]
            ]
        },
        2,
        True,
    )
    fake_module = SimpleNamespace(
        native_mesh_capabilities=lambda: {
            "triangulation_area_guard": True,
            "indexed_edge_manifold_guard": True,
            "rejected_mesh_retry": True,
            "coalesced_rejected_mesh_retry": True,
            "native_surface_validation": True,
        },
        merge_run_groups_to_meshes=lambda *_args, **_kwargs: (
            [([], [])],
            [vector_native_mesh.NATIVE_RETRY_MESH_EMPTY],
            [lossy_retry_record],
        ),
    )

    result = run_length_extrude_native_hybrid(
        matched_shapes=[
            {"geometry": left, "recipe": [0]},
            {"geometry": right, "recipe": [0]},
        ],
        num_layers=1,
        layer_h=0.08,
        num_channels=1,
        slot_names=["White"],
        scale_factor=1.0,
        native_module=fake_module,
    )

    assert result.stats["native_split_source_coverage_rejects"] == 1
    assert result.stats["fallback_groups"] >= 1
    meshes = result.meshes_by_slot["White"]["meshes"]
    assert sum(abs(float(mesh.volume)) for mesh in meshes) == pytest.approx(
        (float(left.area) + float(right.area)) * 0.08
    )


def test_native_surface_validation_arrays_match_trimesh_decision() -> None:
    polygon = _square()
    mesh = trimesh.creation.box(extents=(2.0, 2.0, 0.08))
    mesh.apply_translation((1.0, 1.0, 0.04))
    mesh_arrays = (
        np.asarray(mesh.vertices, dtype=np.float64),
        np.asarray(mesh.faces, dtype=np.int64),
    )

    assert vector_native_mesh._native_surface_area_matches_arrays(
        mesh_arrays,
        [polygon],
        height=0.08,
        scale_factor=1.0,
    ) == vector_native_mesh._native_surface_area_matches(
        mesh,
        [polygon],
        height=0.08,
        scale_factor=1.0,
    )


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


def test_build_mesh_does_not_retry_python_after_native_memory_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A native admission failure must not double the task's memory work."""

    error = VectorMeshMemoryBudgetError(
        "native_extrude",
        9 * 1024**3,
        8 * 1024**3,
        1 * 1024**3,
        1,
        5,
    )

    def reject_native(**_kwargs):
        raise error

    def fail_python_retry(*_args, **_kwargs):
        raise AssertionError("memory rejection retried the Python mesh path")

    monkeypatch.setattr(
        "core.vector_native_mesh.run_length_extrude_native_hybrid",
        reject_native,
    )
    monkeypatch.setattr(
        VectorProcessor,
        "_run_length_extrude",
        staticmethod(fail_python_retry),
    )
    processor = _processor()
    processor.enable_native_vector_mesh = True

    with pytest.raises(VectorMeshMemoryBudgetError) as raised:
        processor.build_mesh(
            analysis=_analysis(),
            thickness_mm=0.0,
            structure_mode="Single-sided",
        )

    assert raised.value is error
