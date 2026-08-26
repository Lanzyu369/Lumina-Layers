"""Core-layer domain exceptions.

Core modules should raise these exceptions instead of API-specific errors.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CoreError(Exception):
    """Base exception for core-layer failures."""

    detail: str
    error_type: str = "core_error"

    def __str__(self) -> str:
        return self.detail


class CoreValidationError(CoreError):
    """Raised when caller input/parameters are invalid for core logic."""

    def __init__(self, detail: str):
        super().__init__(detail=detail, error_type="core_validation_error")


class VectorMeshMemoryBudgetError(CoreValidationError):
    """Reject Vector meshing that cannot fit its configured memory budget.

    拒绝预计无法在配置内存预算内安全完成的矢量网格任务。

    The exception keeps only scalar diagnostics so it remains safely picklable
    across the process-pool worker boundary.
    """

    code = "vector_mesh_memory_budget_exceeded"
    recoverable = True

    def __init__(
        self,
        stage: str,
        estimated_peak_bytes: int,
        memory_budget_bytes: int,
        current_rss_bytes: int,
        shape_count: int,
        coordinate_count: int,
    ) -> None:
        self.stage = str(stage)
        self.estimated_peak_bytes = max(0, int(estimated_peak_bytes))
        self.memory_budget_bytes = max(1, int(memory_budget_bytes))
        self.current_rss_bytes = max(0, int(current_rss_bytes))
        self.shape_count = max(0, int(shape_count))
        self.coordinate_count = max(0, int(coordinate_count))
        estimated_gib = self.estimated_peak_bytes / (1024 ** 3)
        budget_gib = self.memory_budget_bytes / (1024 ** 3)
        detail = (
            "This Vector model is too complex to process safely: estimated "
            f"peak memory is {estimated_gib:.2f} GiB, above the configured "
            f"{budget_gib:.2f} GiB budget. Simplify SVG paths, reduce the "
            "model size, or split the artwork into smaller files, then try "
            "again."
        )
        super().__init__(detail)
        # Exception pickling reconstructs from ``args``. Keep this aligned with
        # the positional constructor instead of serializing geometry objects.
        self.args = (
            self.stage,
            self.estimated_peak_bytes,
            self.memory_budget_bytes,
            self.current_rss_bytes,
            self.shape_count,
            self.coordinate_count,
        )


class VectorHostMemoryAdmissionError(CoreError):
    """Reject a Vector task while other admitted tasks occupy host capacity.

    当其他已准入的矢量任务占用主机容量时，暂时拒绝新任务。该错误表示
    服务端繁忙，不表示当前 SVG 本身过于复杂。
    """

    code = "vector_host_memory_busy"
    recoverable = True

    def __init__(
        self,
        requested_bytes: int,
        reserved_bytes: int,
        memory_budget_bytes: int,
        reason: str = "host_capacity_busy",
    ) -> None:
        self.requested_bytes = max(1, int(requested_bytes))
        self.reserved_bytes = max(0, int(reserved_bytes))
        self.memory_budget_bytes = max(1, int(memory_budget_bytes))
        self.reason = str(reason)
        detail = (
            "The server cannot verify enough safe memory for another Vector "
            "task right now. Wait for running jobs to finish, then retry; "
            "you do not need to change this SVG."
        )
        super().__init__(detail=detail, error_type=self.code)
        self.args = (
            self.requested_bytes,
            self.reserved_bytes,
            self.memory_budget_bytes,
            self.reason,
        )


class CoreDependencyError(CoreError):
    """Raised when optional dependencies or external resources are unavailable."""

    def __init__(self, detail: str):
        super().__init__(detail=detail, error_type="core_dependency_error")


class CoreProcessingError(CoreError):
    """Raised for unexpected processing failures in core logic."""

    def __init__(self, detail: str):
        super().__init__(detail=detail, error_type="core_processing_error")


class VectorTopologyError(CoreError):
    """Report a bounded vector-topology rejection. / 报告有界矢量拓扑拒绝。

    Args:
        detail: Stable internal error summary. / 稳定的内部错误摘要。
        attempts: Coordinate-free metrics for each failed ladder stage. /
            每个失败阶梯的无坐标诊断指标。
    """

    def __init__(
        self,
        detail: str,
        attempts: tuple[dict[str, object], ...],
    ) -> None:
        super().__init__(
            detail=detail,
            error_type="vector_topology_unrepairable",
        )
        self.attempts = tuple(dict(attempt) for attempt in attempts)

    def __reduce__(self) -> tuple[object, tuple[object, ...]]:
        """Preserve diagnostics across process-pool serialization."""

        return type(self), (str(self), self.attempts)


class CachedPreviewAnalysisError(CoreError):
    """Raised when explicitly required preview analysis cannot be consumed.

    当用户的空间编辑要求复用预览分析，而缓存三件套无法安全读取或投影时抛出。
    """

    def __init__(self, detail: str):
        super().__init__(
            detail=detail,
            error_type="cached_preview_analysis_error",
        )
