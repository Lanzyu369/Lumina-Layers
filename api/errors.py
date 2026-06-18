"""Domain error types and HTTP mapping helpers."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from core.errors import CoreDependencyError, CoreError, CoreProcessingError, CoreValidationError


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
    """
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, DomainError):
        return HTTPException(status_code=exc.status_code, detail=exc.detail)
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
