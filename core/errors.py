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
