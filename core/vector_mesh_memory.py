"""Bounded-memory policy for native Vector mesh generation.

原生矢量网格生成的有界内存策略。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import os
from typing import Callable, Generic, TypeVar

from core.errors import VectorMeshMemoryBudgetError
from core.task_parallelism_runtime import current_task_host_memory_budget_bytes


DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES = 8 * 1024 * 1024 * 1024
_VECTOR_MESH_MEMORY_BUDGET_ENV = "LUMINA_VECTOR_MESH_MEMORY_BUDGET_MB"
_VECTOR_MESH_FIXED_WORKING_BYTES = 128 * 1024 * 1024
_VECTOR_MESH_BYTES_PER_RUN_COORDINATE = 192
_VECTOR_MESH_BYTES_PER_SOURCE_COORDINATE = 128
_VECTOR_MESH_TOPOLOGY_BYTES_PER_GROUP_COORDINATE = 512


_KeyT = TypeVar("_KeyT")
_ValueT = TypeVar("_ValueT")


class ByteBudgetLRU(Generic[_KeyT, _ValueT]):
    """Small mapping-compatible LRU constrained by resident value bytes.

    按缓存值常驻字节数限制的小型 LRU 映射。

    Args:
        max_bytes: Maximum retained value bytes. 最大常驻值字节数。
        size_of: Deterministic value-size callback. 值字节估算回调。
    """

    def __init__(
        self,
        *,
        max_bytes: int,
        size_of: Callable[[_ValueT], int],
    ) -> None:
        self.max_bytes = max(0, int(max_bytes))
        self._size_of = size_of
        self._items: OrderedDict[_KeyT, tuple[_ValueT, int]] = OrderedDict()
        self.resident_bytes = 0
        self.peak_bytes = 0
        self.peak_entry_count = 0
        self.eviction_count = 0
        self.oversized_rejection_count = 0

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key: object) -> bool:
        return key in self._items

    def get(self, key: _KeyT, default=None):
        item = self._items.get(key)
        if item is None:
            return default
        self._items.move_to_end(key)
        return item[0]

    def __getitem__(self, key: _KeyT) -> _ValueT:
        item = self._items[key]
        self._items.move_to_end(key)
        return item[0]

    def __setitem__(self, key: _KeyT, value: _ValueT) -> None:
        size_bytes = max(0, int(self._size_of(value)))
        existing = self._items.pop(key, None)
        if existing is not None:
            self.resident_bytes -= existing[1]

        if size_bytes > self.max_bytes or self.max_bytes == 0:
            self.oversized_rejection_count += 1
            return

        while self._items and self.resident_bytes + size_bytes > self.max_bytes:
            _old_key, (_old_value, old_size) = self._items.popitem(last=False)
            self.resident_bytes -= old_size
            self.eviction_count += 1

        self._items[key] = (value, size_bytes)
        self.resident_bytes += size_bytes
        self.peak_bytes = max(self.peak_bytes, self.resident_bytes)
        self.peak_entry_count = max(self.peak_entry_count, len(self._items))

    def clear(self) -> None:
        """Release all cached values while preserving lifetime statistics."""

        self._items.clear()
        self.resident_bytes = 0


@dataclass(frozen=True)
class VectorMeshMemoryBudgetReport:
    """Scalar result of one Vector mesh memory admission check.

    单次矢量网格内存准入检查的标量结果。
    """

    stage: str
    estimated_additional_bytes: int
    estimated_peak_bytes: int
    memory_budget_bytes: int
    current_rss_bytes: int
    shape_count: int
    coordinate_count: int
    is_allowed: bool


@dataclass(frozen=True)
class VectorMeshBuildMemoryEstimate:
    """Conservative scalar complexity estimate before 3D allocation.

    三维分配前的保守标量复杂度估算。
    """

    shape_count: int
    coordinate_count: int
    auxiliary_coordinate_count: int
    run_count: int
    run_coordinate_references: int
    auxiliary_coordinate_references: int
    max_validation_coordinate_count: int
    estimated_final_mesh_bytes: int
    topology_validation_working_bytes: int
    estimated_additional_bytes: int


def _geometry_coordinate_count(geometry) -> int:
    explicit_count = getattr(geometry, "coordinate_count", None)
    if explicit_count is not None:
        try:
            return max(0, int(explicit_count))
        except (TypeError, ValueError, OverflowError):
            return 0

    try:
        from shapely import get_num_coordinates  # type: ignore[attr-defined]

        return max(0, int(get_num_coordinates(geometry)))
    except (ImportError, AttributeError, TypeError, ValueError, OverflowError):
        pass

    try:
        parts = (
            tuple(geometry.geoms)
            if getattr(geometry, "geom_type", "") == "MultiPolygon"
            else (geometry,)
        )
        return sum(
            len(part.exterior.coords)
            + sum(len(ring.coords) for ring in part.interiors)
            for part in parts
        )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return 0


def _recipe_runs(recipe, num_layers: int) -> list[tuple[int, int, int]]:
    try:
        layers_to_use = min(max(0, int(num_layers)), len(recipe))
    except (TypeError, ValueError, OverflowError):
        return []
    if layers_to_use <= 0:
        return []
    try:
        previous = int(recipe[0])
    except (TypeError, ValueError, OverflowError):
        return []
    run_start = 0
    runs: list[tuple[int, int, int]] = []
    for index in range(1, layers_to_use):
        try:
            current = int(recipe[index])
        except (TypeError, ValueError, OverflowError):
            return []
        if current != previous:
            runs.append((previous, run_start, index - 1))
            run_start = index
            previous = current
    runs.append((previous, run_start, layers_to_use - 1))
    return runs


def estimate_vector_mesh_build_memory(
    matched_shapes,
    *,
    num_layers: int,
    double_sided: bool,
    precision_cache_budget_bytes: int,
    extrude_cache_budget_bytes: int,
    fallback_chunk_bytes: int,
    auxiliary_geometries=(),
    auxiliary_run_count: int = 0,
) -> VectorMeshBuildMemoryEstimate:
    """Estimate retained output plus bounded peak working allocations.

    估算最终输出与有界工作区叠加后的峰值分配。

    The estimate intentionally assumes the largest material may contain the
    whole final mesh during assembly. It is conservative without traversing or
    serializing coordinates into another full buffer.
    """

    shape_count = 0
    coordinate_count = 0
    run_count = 0
    run_coordinate_references = 0
    run_group_coordinate_counts: dict[tuple[int, int, int], int] = {}
    side_multiplier = 2 if bool(double_sided) else 1
    for item in matched_shapes or ():
        geometry = item.get("geometry") if isinstance(item, dict) else None
        if geometry is None or getattr(geometry, "is_empty", False):
            continue
        coordinates = _geometry_coordinate_count(geometry)
        runs = _recipe_runs(
            item.get("recipe") if isinstance(item, dict) else None,
            num_layers,
        )
        shape_count += 1
        coordinate_count += coordinates
        run_count += len(runs)
        run_coordinate_references += coordinates * len(runs)
        for run_key in runs:
            run_group_coordinate_counts[run_key] = (
                run_group_coordinate_counts.get(run_key, 0) + coordinates
            )

    run_count *= side_multiplier
    run_coordinate_references *= side_multiplier
    auxiliary_coordinate_count = sum(
        _geometry_coordinate_count(geometry)
        for geometry in (auxiliary_geometries or ())
        if geometry is not None and not getattr(geometry, "is_empty", False)
    )
    auxiliary_runs = max(0, int(auxiliary_run_count))
    auxiliary_coordinate_references = (
        auxiliary_coordinate_count * auxiliary_runs
    )
    max_validation_coordinate_count = max(
        max(run_group_coordinate_counts.values(), default=0),
        auxiliary_coordinate_count if auxiliary_runs else 0,
    )
    estimated_final_mesh_bytes = (
        (run_coordinate_references + auxiliary_coordinate_references)
        * _VECTOR_MESH_BYTES_PER_RUN_COORDINATE
    )
    topology_validation_working_bytes = (
        max_validation_coordinate_count
        * _VECTOR_MESH_TOPOLOGY_BYTES_PER_GROUP_COORDINATE
    )
    retained_source_geometry_bytes = (
        coordinate_count * _VECTOR_MESH_BYTES_PER_SOURCE_COORDINATE
    )
    largest_slot_assembly_copy_bytes = estimated_final_mesh_bytes
    estimated_additional_bytes = sum(
        (
            _VECTOR_MESH_FIXED_WORKING_BYTES,
            estimated_final_mesh_bytes,
            largest_slot_assembly_copy_bytes,
            retained_source_geometry_bytes,
            topology_validation_working_bytes,
            max(0, int(precision_cache_budget_bytes)),
            max(0, int(extrude_cache_budget_bytes)),
            max(0, int(fallback_chunk_bytes)),
        )
    )
    return VectorMeshBuildMemoryEstimate(
        shape_count=shape_count,
        coordinate_count=coordinate_count,
        auxiliary_coordinate_count=auxiliary_coordinate_count,
        run_count=run_count,
        run_coordinate_references=run_coordinate_references,
        auxiliary_coordinate_references=auxiliary_coordinate_references,
        max_validation_coordinate_count=max_validation_coordinate_count,
        estimated_final_mesh_bytes=estimated_final_mesh_bytes,
        topology_validation_working_bytes=topology_validation_working_bytes,
        estimated_additional_bytes=estimated_additional_bytes,
    )


def resolve_vector_mesh_memory_budget_bytes() -> int:
    """Resolve the worker RSS cap, including any parent host reservation."""

    raw_value = os.environ.get(_VECTOR_MESH_MEMORY_BUDGET_ENV)
    if raw_value is None or not raw_value.strip():
        configured_budget = DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES
    else:
        try:
            value_mb = int(raw_value)
        except ValueError:
            value_mb = 0
        configured_budget = (
            value_mb * 1024 * 1024
            if value_mb > 0
            else DEFAULT_VECTOR_MESH_MEMORY_BUDGET_BYTES
        )
    host_reservation = current_task_host_memory_budget_bytes()
    if host_reservation is None:
        return configured_budget
    return min(configured_budget, max(1, int(host_reservation)))


def get_process_rss_bytes() -> int | None:
    """Return current process RSS without introducing an API-layer import."""

    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return int(psutil.Process(os.getpid()).memory_info().rss)
    except (OSError, RuntimeError):
        return None


def enforce_vector_mesh_memory_budget(
    *,
    stage: str,
    estimated_additional_bytes: int,
    memory_budget_bytes: int,
    current_rss_bytes: int,
    shape_count: int,
    coordinate_count: int,
) -> VectorMeshMemoryBudgetReport:
    """Accept safe estimated work or raise an actionable validation error.

    接受预算内任务；超预算时抛出可操作的校验错误。
    """

    additional = max(0, int(estimated_additional_bytes))
    budget = max(1, int(memory_budget_bytes))
    rss = max(0, int(current_rss_bytes))
    peak = rss + additional
    report = VectorMeshMemoryBudgetReport(
        stage=str(stage),
        estimated_additional_bytes=additional,
        estimated_peak_bytes=peak,
        memory_budget_bytes=budget,
        current_rss_bytes=rss,
        shape_count=max(0, int(shape_count)),
        coordinate_count=max(0, int(coordinate_count)),
        is_allowed=peak <= budget,
    )
    if not report.is_allowed:
        raise VectorMeshMemoryBudgetError(
            report.stage,
            report.estimated_peak_bytes,
            report.memory_budget_bytes,
            report.current_rss_bytes,
            report.shape_count,
            report.coordinate_count,
        )
    return report
