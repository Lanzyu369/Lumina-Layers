"""Unit coverage for bounded parallel mesh generation in pipeline stage S07."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor
import time

import numpy as np
import pytest
import trimesh

from config import ModelingMode
from core.pipeline import s07_mesh_generation


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

    policy_calls: list[tuple[str, int, int, int]] = []
    pool_workers: list[int] = []

    def _resolve(
        workload: str,
        *,
        work_items: int,
        min_parallel_items: int,
        hard_max_workers: int,
    ) -> int:
        policy_calls.append(
            (
                workload,
                work_items,
                min_parallel_items,
                hard_max_workers,
            ),
        )
        return 3

    def _pool(*, max_workers: int) -> RealThreadPoolExecutor:
        pool_workers.append(max_workers)
        return RealThreadPoolExecutor(max_workers=max_workers)

    monkeypatch.setattr(s07_mesh_generation, "get_mesher", lambda *args, **kwargs: _DelayedBoxMesher())
    monkeypatch.setattr(s07_mesh_generation, "resolve_task_parallelism", _resolve)
    monkeypatch.setattr(s07_mesh_generation, "ThreadPoolExecutor", _pool)
    monkeypatch.delenv("LUMINA_DISABLE_PARALLEL_MESH", raising=False)

    result = s07_mesh_generation.run(_make_context(4))

    assert policy_calls == [("raster", 4, 2, 4)]
    assert pool_workers == [3]
    assert result["valid_slot_names"] == [
        "Material 0",
        "Material 1",
        "Material 2",
        "Material 3",
    ]
    assert list(result["scene"].geometry) == result["valid_slot_names"]
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == 3


def test_s07_legacy_disable_override_forces_serial_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legacy emergency switch remains a strict serial override."""

    monkeypatch.setattr(s07_mesh_generation, "get_mesher", lambda *args, **kwargs: _DelayedBoxMesher())
    monkeypatch.setattr(
        s07_mesh_generation,
        "resolve_task_parallelism",
        lambda *args, **kwargs: 4,
    )
    monkeypatch.setattr(
        s07_mesh_generation,
        "ThreadPoolExecutor",
        lambda **kwargs: pytest.fail("serial override must not create a pool"),
    )
    monkeypatch.setenv("LUMINA_DISABLE_PARALLEL_MESH", "1")

    result = s07_mesh_generation.run(_make_context(3))

    assert result["valid_slot_names"] == [
        "Material 0",
        "Material 1",
        "Material 2",
    ]
    assert result["_hifi_timings"]["mesh_parallelism_workers"] == 1
