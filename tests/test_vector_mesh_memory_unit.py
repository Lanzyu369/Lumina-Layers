"""Bounded-memory contracts for Vector mesh generation."""

from __future__ import annotations

import pickle

import numpy as np
import pytest

from core.errors import VectorMeshMemoryBudgetError
from core.vector_mesh_memory import (
    ByteBudgetLRU,
    DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES,
    enforce_vector_mesh_memory_budget,
    estimate_vector_mesh_build_memory,
    resolve_vector_mesh_memory_budget_bytes,
)
from core.task_parallelism_runtime import task_host_memory_budget_scope


def test_byte_budget_lru_evicts_before_resident_bytes_exceed_limit() -> None:
    """Cache residency is governed by bytes, not an unbounded entry count."""

    cache = ByteBudgetLRU(
        max_bytes=24,
        size_of=lambda value: int(value.nbytes),
    )
    first = np.zeros(2, dtype=np.int64)
    second = np.ones(2, dtype=np.int64)

    cache["first"] = first
    cache["second"] = second

    assert cache.get("first") is None
    assert cache.get("second") is second
    assert cache.resident_bytes == second.nbytes
    assert cache.peak_bytes <= cache.max_bytes
    assert cache.eviction_count == 1


def test_byte_budget_lru_refuses_single_oversized_entry() -> None:
    """One entry larger than the whole budget is used but never retained."""

    cache = ByteBudgetLRU(
        max_bytes=8,
        size_of=lambda value: int(value.nbytes),
    )

    cache["oversized"] = np.zeros(2, dtype=np.int64)

    assert len(cache) == 0
    assert cache.resident_bytes == 0
    assert cache.oversized_rejection_count == 1


def test_memory_budget_error_is_structured_and_actionable() -> None:
    """Unsafe work fails before OOM with a stable recoverable error contract."""

    with pytest.raises(VectorMeshMemoryBudgetError) as raised:
        enforce_vector_mesh_memory_budget(
            stage="preflight",
            estimated_additional_bytes=900,
            memory_budget_bytes=1_000,
            current_rss_bytes=200,
            shape_count=42,
            coordinate_count=4_200,
        )

    error = raised.value
    assert error.code == "vector_mesh_memory_budget_exceeded"
    assert error.stage == "preflight"
    assert error.estimated_peak_bytes == 1_100
    assert error.memory_budget_bytes == 1_000
    assert error.recoverable is True
    assert "simpl" in str(error).lower()


def test_memory_budget_accepts_work_that_fits() -> None:
    report = enforce_vector_mesh_memory_budget(
        stage="preflight",
        estimated_additional_bytes=700,
        memory_budget_bytes=1_000,
        current_rss_bytes=200,
        shape_count=4,
        coordinate_count=40,
    )

    assert report.estimated_peak_bytes == 900
    assert report.is_allowed is True


def test_parent_host_reservation_tightens_worker_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pool-assigned cap bounds every later build/export memory guard."""

    monkeypatch.delenv("LUMINA_VECTOR_MESH_MEMORY_BUDGET_MB", raising=False)
    assert (
        resolve_vector_mesh_memory_budget_bytes()
        == DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES
    )
    with task_host_memory_budget_scope(512):
        assert resolve_vector_mesh_memory_budget_bytes() == 512
    assert (
        resolve_vector_mesh_memory_budget_bytes()
        == DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES
    )


def test_memory_budget_error_survives_process_pool_serialization() -> None:
    """Worker admission diagnostics must reach the API process intact."""

    error = VectorMeshMemoryBudgetError(
        "assemble",
        9 * 1024**3,
        8 * 1024**3,
        7 * 1024**3,
        42,
        4_200,
    )

    restored = pickle.loads(pickle.dumps(error))

    assert isinstance(restored, VectorMeshMemoryBudgetError)
    assert restored.stage == "assemble"
    assert restored.estimated_peak_bytes == 9 * 1024**3
    assert restored.memory_budget_bytes == 8 * 1024**3
    assert restored.shape_count == 42
    assert restored.coordinate_count == 4_200
    assert str(restored) == str(error)


def test_build_estimate_accounts_for_run_multiplicity_and_double_sided_output() -> None:
    shapes = [
        {
            "geometry": _CoordinateCountGeometry(100),
            "recipe": [0, 1, 0, 1],
        },
        {
            "geometry": _CoordinateCountGeometry(50),
            "recipe": [0, 0, 1, 1],
        },
    ]

    single = estimate_vector_mesh_build_memory(
        shapes,
        num_layers=4,
        double_sided=False,
        precision_cache_budget_bytes=0,
        extrude_cache_budget_bytes=0,
        fallback_chunk_bytes=0,
    )
    double = estimate_vector_mesh_build_memory(
        shapes,
        num_layers=4,
        double_sided=True,
        precision_cache_budget_bytes=0,
        extrude_cache_budget_bytes=0,
        fallback_chunk_bytes=0,
    )

    assert single.shape_count == 2
    assert single.coordinate_count == 150
    assert single.run_count == 6
    assert single.run_coordinate_references == 500
    assert double.run_coordinate_references == 1_000
    assert double.estimated_additional_bytes > single.estimated_additional_bytes


def test_build_estimate_accounts_for_backing_coating_and_topology_workspace() -> None:
    estimate = estimate_vector_mesh_build_memory(
        [],
        num_layers=4,
        double_sided=False,
        precision_cache_budget_bytes=0,
        extrude_cache_budget_bytes=0,
        fallback_chunk_bytes=0,
        auxiliary_geometries=[_CoordinateCountGeometry(10_000)],
        auxiliary_run_count=3,
    )

    assert estimate.coordinate_count == 0
    assert estimate.auxiliary_coordinate_count == 10_000
    assert estimate.auxiliary_coordinate_references == 30_000
    assert estimate.max_validation_coordinate_count == 10_000
    assert estimate.topology_validation_working_bytes > 0
    assert estimate.estimated_final_mesh_bytes > 0


def test_build_estimate_rejects_giant_single_group_before_topology_allocation() -> None:
    estimate = estimate_vector_mesh_build_memory(
        [
            {
                "geometry": _CoordinateCountGeometry(12_000_000),
                "recipe": [0],
            }
        ],
        num_layers=1,
        double_sided=False,
        precision_cache_budget_bytes=0,
        extrude_cache_budget_bytes=0,
        fallback_chunk_bytes=0,
    )

    assert estimate.max_validation_coordinate_count == 12_000_000
    assert estimate.estimated_additional_bytes > 8 * 1024**3


class _CoordinateCountGeometry:
    """Tiny fixture that exposes complexity without allocating coordinates."""

    def __init__(self, coordinate_count: int) -> None:
        self.coordinate_count = int(coordinate_count)
