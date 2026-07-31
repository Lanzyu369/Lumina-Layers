"""Unit coverage for bounded parallel mesh generation in pipeline stage S07."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor
import logging
import threading
import time

import numpy as np
import pytest
import trimesh

from config import ModelingMode
from core.pipeline import s07_mesh_generation
from core.task_parallelism import AdaptiveParallelismPlan


class _DelayedBoxMesher:
    """Return deterministic boxes while completing higher IDs first."""

    def generate_mesh(
        self,
        _full_matrix: np.ndarray,
        mat_id: int,
        _target_h: int,
    ) -> trimesh.Trimesh:
        time.sleep(0.003 * (4 - mat_id))
        return trimesh.creation.box(extents=(float(mat_id + 1), 1.0, 1.0))


class _RecordingMesher:
    """Record worker identity and optionally fail one material."""

    def __init__(self, *, failing_material: int | None = None) -> None:
        self.failing_material = failing_material
        self.thread_ids: list[int] = []

    def generate_mesh(
        self,
        _full_matrix: np.ndarray,
        mat_id: int,
        _target_h: int,
    ) -> trimesh.Trimesh:
        self.thread_ids.append(threading.get_ident())
        if mat_id == self.failing_material:
            raise RuntimeError(f"material-{mat_id}-failed")
        return trimesh.creation.box(extents=(float(mat_id + 1), 1.0, 1.0))


def _parallelism_plan(
    workers: int,
    *,
    requested_ceiling: int | None = None,
    effective_cpu_capacity: int | None = None,
    outer_demand: int = 1,
    cpu_fair_share_ceiling: int | None = None,
    memory_ceiling: int | None = None,
    limiting_reason: str = "requested",
    demand_snapshot_fallback: bool = False,
) -> AdaptiveParallelismPlan:
    """Build a coherent deterministic plan for stage-adoption tests."""

    requested = requested_ceiling or max(1, workers)
    effective_cpu = effective_cpu_capacity or max(1, workers * outer_demand)
    cpu_share = cpu_fair_share_ceiling or max(
        1,
        effective_cpu // max(1, outer_demand),
    )
    memory = memory_ceiling or max(1, workers)
    return AdaptiveParallelismPlan(
        workers=workers,
        requested_ceiling=requested,
        effective_cpu_capacity=effective_cpu,
        outer_demand=outer_demand,
        cpu_fair_share_ceiling=cpu_share,
        work_item_ceiling=4,
        work_unit_ceiling=4,
        stage_ceiling=4,
        memory_ceiling=memory,
        available_memory_bytes=8 * 1024**3,
        estimated_worker_bytes=64 * 1024**2,
        limiting_reason=limiting_reason,
        demand_snapshot_fallback=demand_snapshot_fallback,
    )


def _make_context(material_count: int) -> dict:
    return {
        "full_matrix": np.zeros((1, 2, 2), dtype=np.int16),
        "slot_names": [f"Material {index}" for index in range(material_count)],
        "preview_colors": {
            index: (index * 20, 100, 200, 255)
            for index in range(material_count)
        },
        "modeling_mode": ModelingMode.HIGH_FIDELITY,
        "target_h": 2,
        "pixel_scale": 1.0,
        "_bench_enabled": True,
    }


def test_s07_uses_bounded_policy_and_restores_material_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Thread completion order must not affect scene or material ordering."""

    policy_calls: list[dict[str, int | str]] = []
    pool_workers: list[int] = []

    def _resolve(
        workload: str,
        *,
        work_items: int,
        min_parallel_items: int,
        hard_max_workers: int,
        work_units: int,
        min_parallel_work_units: int,
        estimated_worker_bytes: int,
    ) -> AdaptiveParallelismPlan:
        policy_calls.append(
            {
                "workload": workload,
                "work_items": work_items,
                "min_parallel_items": min_parallel_items,
                "hard_max_workers": hard_max_workers,
                "work_units": work_units,
                "min_parallel_work_units": min_parallel_work_units,
                "estimated_worker_bytes": estimated_worker_bytes,
            },
        )
        return _parallelism_plan(
            2,
            requested_ceiling=4,
            effective_cpu_capacity=4,
            outer_demand=2,
            cpu_fair_share_ceiling=2,
            memory_ceiling=3,
            limiting_reason="cpu_fair_share",
        )

    def _pool(*, max_workers: int) -> RealThreadPoolExecutor:
        pool_workers.append(max_workers)
        return RealThreadPoolExecutor(max_workers=max_workers)

    monkeypatch.setattr(s07_mesh_generation, "get_mesher", lambda *args, **kwargs: _DelayedBoxMesher())
    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism_plan",
        _resolve,
    )
    monkeypatch.setattr(s07_mesh_generation, "ThreadPoolExecutor", _pool)
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)

    result = s07_mesh_generation.run(_make_context(4))

    assert policy_calls == [
        {
            "workload": "raster",
            "work_items": 4,
            "min_parallel_items": 2,
            "hard_max_workers": 4,
            "work_units": 4,
            "min_parallel_work_units": 100_000,
            "estimated_worker_bytes": 64 * 1024**2,
        }
    ]
    assert pool_workers == [2]
    assert result["valid_slot_names"] == [
        "Material 0",
        "Material 1",
        "Material 2",
        "Material 3",
    ]
    assert list(result["scene"].geometry) == result["valid_slot_names"]
    assert result["_hifi_timings"]["mesh_parallelism_requested"] == "auto"
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == 2
    assert (
        result["_hifi_timings"]["mesh_parallelism_limit"]
        == "cpu_fair_share"
    )
    assert result["_hifi_timings"]["mesh_parallelism_effective_cpu"] == 4
    assert result["_hifi_timings"]["mesh_parallelism_outer_demand"] == 2
    assert result["_hifi_timings"]["mesh_parallelism_cpu_fair_share"] == 2
    assert result["_hifi_timings"]["mesh_parallelism_memory_ceiling"] == 3
    assert result["_hifi_timings"]["mesh_parallelism_demand_fallback"] is False


def test_s07_effective_one_executes_on_calling_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Serial policy must not create an executor or move work off-thread."""

    mesher = _RecordingMesher()
    calling_thread = threading.get_ident()
    monkeypatch.setattr(
        s07_mesh_generation,
        "get_mesher",
        lambda *args, **kwargs: mesher,
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: _parallelism_plan(
            1,
            limiting_reason="insufficient_work_units",
        ),
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "ThreadPoolExecutor",
        lambda **kwargs: pytest.fail("serial policy must not create a pool"),
    )
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", "1")
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)

    result = s07_mesh_generation.run(_make_context(3))

    assert mesher.thread_ids == [calling_thread, calling_thread, calling_thread]
    assert result["_hifi_timings"]["mesh_parallelism_requested"] == "1"
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == 1


@pytest.mark.parametrize("worker_count", [2, 4])
def test_s07_uses_exact_effective_worker_limit(
    monkeypatch: pytest.MonkeyPatch,
    worker_count: int,
) -> None:
    """The executor limit must equal the bounded policy decision."""

    observed_workers: list[int] = []

    def _pool(*, max_workers: int) -> RealThreadPoolExecutor:
        observed_workers.append(max_workers)
        return RealThreadPoolExecutor(max_workers=max_workers)

    monkeypatch.setattr(
        s07_mesh_generation,
        "get_mesher",
        lambda *args, **kwargs: _DelayedBoxMesher(),
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: _parallelism_plan(
            worker_count,
            requested_ceiling=worker_count,
        ),
    )
    monkeypatch.setattr(s07_mesh_generation, "ThreadPoolExecutor", _pool)
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", str(worker_count))
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)

    result = s07_mesh_generation.run(_make_context(4))

    assert observed_workers == [worker_count]
    assert result["_hifi_timings"]["mesh_parallelism_requested"] == str(
        worker_count
    )
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == worker_count


def test_s07_worker_exception_stays_attached_to_original_material(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed future must not shift names, colors, or later materials."""

    mesher = _RecordingMesher(failing_material=1)
    monkeypatch.setattr(
        s07_mesh_generation,
        "get_mesher",
        lambda *args, **kwargs: mesher,
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: _parallelism_plan(2),
    )
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)
    caplog.set_level(logging.WARNING)
    target_logger = logging.getLogger(
        "lumina.core.pipeline.s07_mesh_generation"
    )
    target_logger.addHandler(caplog.handler)
    try:
        result = s07_mesh_generation.run(_make_context(3))
    finally:
        target_logger.removeHandler(caplog.handler)

    assert result["valid_slot_names"] == ["Material 0", "Material 2"]
    assert list(result["scene"].geometry) == ["Material 0", "Material 2"]
    failure_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "s07_material_mesh_failed"
    ]
    assert len(failure_records) == 1
    assert failure_records[0].material_id == 1
    assert failure_records[0].material == "Material 1"
    assert failure_records[0].error_message == "material-1-failed"


def test_s07_single_material_stays_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One material must remain on the caller even under a high request."""

    mesher = _RecordingMesher()
    calling_thread = threading.get_ident()
    monkeypatch.setattr(
        s07_mesh_generation,
        "get_mesher",
        lambda *args, **kwargs: mesher,
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "ThreadPoolExecutor",
        lambda **kwargs: pytest.fail("one material must not create a pool"),
    )
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", "8")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)

    result = s07_mesh_generation.run(_make_context(1))

    assert mesher.thread_ids == [calling_thread]
    assert result["_hifi_timings"]["mesh_parallelism_requested"] == "8"
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == 1


def test_s07_tiny_two_material_workload_stays_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two 1x2 materials are not enough work to amortize a thread pool."""

    mesher = _RecordingMesher()
    calling_thread = threading.get_ident()
    monkeypatch.setattr(
        s07_mesh_generation,
        "get_mesher",
        lambda *args, **kwargs: mesher,
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "ThreadPoolExecutor",
        lambda **kwargs: pytest.fail("tiny workload must not create a pool"),
    )
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", "8")
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "1")
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)

    result = s07_mesh_generation.run(_make_context(2))

    assert mesher.thread_ids == [calling_thread, calling_thread]
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == 1


def test_s07_legacy_disable_override_forces_serial_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legacy emergency switch remains a strict serial override."""

    monkeypatch.setattr(s07_mesh_generation, "get_mesher", lambda *args, **kwargs: _DelayedBoxMesher())
    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: _parallelism_plan(4),
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "ThreadPoolExecutor",
        lambda **kwargs: pytest.fail("serial override must not create a pool"),
    )
    monkeypatch.setenv("LUMINA_DISABLE_PARALLEL_MESH", "1")
    monkeypatch.setenv("LUMINA_RASTER_PARALLELISM", "4")

    result = s07_mesh_generation.run(_make_context(3))

    assert result["valid_slot_names"] == [
        "Material 0",
        "Material 1",
        "Material 2",
    ]
    assert result["_hifi_timings"]["mesh_parallelism_requested"] == "4"
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == 1
    assert result["_hifi_timings"]["mesh_parallelism_limit"] == "legacy_disable"


def test_s07_serial_and_parallel_mesh_outputs_are_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduling must not change geometry, colors, names, or ordering."""

    monkeypatch.setattr(
        s07_mesh_generation,
        "get_mesher",
        lambda *args, **kwargs: _DelayedBoxMesher(),
    )
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)

    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: _parallelism_plan(
            1,
            limiting_reason="requested",
        ),
    )
    serial_result = s07_mesh_generation.run(_make_context(4))

    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism_plan",
        lambda *args, **kwargs: _parallelism_plan(
            4,
            requested_ceiling=4,
        ),
    )
    parallel_result = s07_mesh_generation.run(_make_context(4))

    def _scene_signature(result: dict) -> tuple:
        scene = result["scene"]
        return tuple(
            (
                name,
                scene.geometry[name].vertices.tobytes(),
                scene.geometry[name].faces.tobytes(),
                scene.geometry[name].visual.face_colors.tobytes(),
                scene.geometry[name].metadata["name"],
            )
            for name in result["valid_slot_names"]
        )

    assert serial_result["valid_slot_names"] == parallel_result["valid_slot_names"]
    assert _scene_signature(serial_result) == _scene_signature(parallel_result)
