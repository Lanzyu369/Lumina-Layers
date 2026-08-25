"""Domain error types and HTTP mapping helpers."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from core.errors import (
    CoreDependencyError,
    CoreError,
    CoreProcessingError,
    CoreValidationError,
    VectorHostMemoryAdmissionError,
    VectorMeshMemoryBudgetError,
)
from core.material_dynamic_solver import (
    DynamicMaterialCandidateError,
    DynamicMaterialSolverError,
)


@dataclass
class DomainError(Exception):
    """Base domain error that can be mapped to HTTPException."""

    detail: str
    status_code: int = 500
    error_type: str = "internal_error"

    def __post_init__(self) -> None:
        Exception.__init__(self, self.detail)

    def __str__(self) -> str:
        return self.detail


class ValidationDomainError(DomainError):  # Reserved for future use
    def __init__(self, detail: str):
        super().__init__(detail=detail, status_code=422, error_type="validation_error")


class NotFoundDomainError(DomainError):  # Reserved for future use
    def __init__(self, detail: str):
        super().__init__(detail=detail, status_code=404, error_type="not_found")


class ConflictDomainError(DomainError):  # Reserved for future use
    def __init__(self, detail: str):
        super().__init__(detail=detail, status_code=409, error_type="conflict")


class UpstreamDomainError(DomainError):  # Reserved for future use
    def __init__(self, detail: str):
        super().__init__(detail=detail, status_code=502, error_type="upstream_error")


def to_http_exception(exc: Exception, context: str) -> HTTPException:
    """Map domain/unknown exceptions to stable HTTPException.

    将领域异常和未知异常映射为稳定的 HTTPException。

    Args:
        exc: Exception raised by the domain, core, or boundary layer. 领域层、
            核心层或边界层抛出的异常。
        context: Safe operation label used in the fallback error message.
            用于兜底错误消息的安全操作标签。

    Returns:
        HTTPException: Existing HTTP exception or a stable mapped response.
            原有 HTTP 异常，或映射后的稳定 HTTP 响应异常。
    """
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, DynamicMaterialCandidateError):
        no_candidate = exc.phase in {"exact_search", "fixed_max_baseline"}
        return HTTPException(
            status_code=409 if no_candidate else 503,
            detail={
                "code": (
                    "dynamic_material_no_candidate"
                    if no_candidate
                    else "dynamic_material_solver_unavailable"
                ),
                "message": (
                    "No exact dynamic material candidate is available for this target."
                    if no_candidate
                    else "The exact dynamic material solver is temporarily unavailable."
                ),
                "target_srgb": (
                    list(exc.target_srgb) if exc.target_srgb is not None else None
                ),
                "layer_count": exc.layer_count,
                "stage": exc.phase,
            },
        )
    if isinstance(exc, DynamicMaterialSolverError):
        return HTTPException(
            status_code=503,
            detail={
                "code": "dynamic_material_solver_unavailable",
                "message": (
                    "The exact dynamic material solver is temporarily unavailable."
                ),
                "target_srgb": None,
                "layer_count": None,
                "stage": "exact_search_engine",
            },
        )
    if isinstance(exc, DomainError):
        return HTTPException(status_code=exc.status_code, detail=exc.detail)
    if isinstance(exc, VectorHostMemoryAdmissionError):
        return HTTPException(
            status_code=503,
            detail={
                "error": exc.code,
                "code": exc.code,
                "message": exc.detail,
                "requested_bytes": exc.requested_bytes,
                "reserved_bytes": exc.reserved_bytes,
                "memory_budget_bytes": exc.memory_budget_bytes,
                "reason": exc.reason,
                "recoverable": exc.recoverable,
                "retryable": True,
                "recovery_actions": ["retry_later"],
            },
            headers={"Retry-After": "5"},
        )
    if isinstance(exc, VectorMeshMemoryBudgetError):
        return HTTPException(
            status_code=422,
            detail={
                "error": exc.code,
                "code": exc.code,
                "message": exc.detail,
                "stage": exc.stage,
                "estimated_peak_bytes": exc.estimated_peak_bytes,
                "memory_budget_bytes": exc.memory_budget_bytes,
                "recoverable": exc.recoverable,
                "recovery_actions": [
                    "simplify_svg_paths",
                    "reduce_model_size",
                    "split_artwork",
                ],
            },
        )
    if isinstance(exc, CoreValidationError):
        return HTTPException(status_code=422, detail=exc.detail)
    if isinstance(exc, CoreDependencyError):
        return HTTPException(status_code=502, detail=exc.detail)
    if isinstance(exc, (CoreProcessingError, CoreError)):
        return HTTPException(status_code=500, detail=exc.detail)
    return HTTPException(
        status_code=500,
        detail=f"{context} failed. Check the server log for details.",
    )
