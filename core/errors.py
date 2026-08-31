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
            "The final Vector mesh cannot fit the memory currently available "
            f"to this task: estimated peak {estimated_gib:.2f} GiB, safe "
            f"limit {budget_gib:.2f} GiB. Generation stopped before the large "
            "allocation. Free memory and retry; reduce the output size only "
            "if the same limit is reached again."
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
        if self.reserved_bytes > 0:
            detail = (
                "Another Vector task is using the available generation "
                "memory. Wait for it to finish, then retry; you do not need "
                "to change this SVG."
            )
        else:
            detail = (
                "The device does not currently have enough free memory for "
                "this Vector task. Close other memory-intensive applications "
                "and retry; you do not need to change this SVG."
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


class NativeSvgInvalidError(CoreValidationError):
    """Report deterministic invalid input from the native SVG boundary.

    报告原生 SVG 边界识别出的确定性无效输入。
    """

    def __init__(self, detail: str, *, reason_code: str):
        self.reason_code = str(reason_code)
        super().__init__(detail)


class NativeSvgResourceLimitError(CoreValidationError):
    """Reject SVG work that exceeds the deterministic native resource cap.

    拒绝超过原生 SVG 确定性资源上限的输入，且禁止转交无同等限额的旧链路。
    """

    code = "native_svg_resource_limit"
    recoverable = False

    def __init__(self, *, reason_code: str = "unsupported_complexity") -> None:
        self.reason_code = str(reason_code)
        super().__init__(
            "This SVG exceeds the safe native processing complexity limit. "
            "Simplify the document or split it into smaller SVG files."
        )


class NativeSvgInternalError(CoreProcessingError):
    """Report a native SVG ABI or processing failure without legacy retry.

    报告原生 SVG ABI 或处理故障；此类错误不得静默走旧链路重试。
    """

    def __init__(self, detail: str, *, reason_code: str):
        self.reason_code = str(reason_code)
        super().__init__(detail)


class CachedPreviewAnalysisError(CoreError):
    """Raised when explicitly required preview analysis cannot be consumed.

    当用户的空间编辑要求复用预览分析，而缓存三件套无法安全读取或投影时抛出。
    """

    def __init__(self, detail: str):
        super().__init__(
            detail=detail,
            error_type="cached_preview_analysis_error",
        )
