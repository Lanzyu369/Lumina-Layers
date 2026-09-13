"""Unit tests for domain error -> HTTP exception mapping."""

from __future__ import annotations

from fastapi import HTTPException

from api.errors import (
    ConflictDomainError,
    NotFoundDomainError,
    UpstreamDomainError,
    ValidationDomainError,
    to_http_exception,
)
from core.errors import (
    CoreDependencyError,
    CoreProcessingError,
    CoreValidationError,
    NativeSvgResourceLimitError,
    VectorHostMemoryAdmissionError,
    VectorMeshMemoryBudgetError,
)


def test_validation_domain_error_maps_to_422() -> None:
    exc = to_http_exception(ValidationDomainError("bad payload"), "op")
    assert isinstance(exc, HTTPException)
    assert exc.status_code == 422
    assert exc.detail == "bad payload"


def test_not_found_domain_error_maps_to_404() -> None:
    exc = to_http_exception(NotFoundDomainError("missing"), "op")
    assert exc.status_code == 404
    assert exc.detail == "missing"


def test_conflict_domain_error_maps_to_409() -> None:
    exc = to_http_exception(ConflictDomainError("conflict"), "op")
    assert exc.status_code == 409
    assert exc.detail == "conflict"


def test_upstream_domain_error_maps_to_502() -> None:
    exc = to_http_exception(UpstreamDomainError("upstream"), "op")
    assert exc.status_code == 502
    assert exc.detail == "upstream"


def test_unknown_exception_maps_to_500_without_leaking_exception_detail() -> None:
    exc = to_http_exception(
        RuntimeError("boom at /Users/min/private/input.png"),
        "vectorize",
    )
    assert exc.status_code == 500
    assert exc.detail == "vectorize failed. Check the server log for details."
    assert "boom" not in exc.detail
    assert "/Users/min" not in exc.detail


def test_core_validation_error_maps_to_422() -> None:
    exc = to_http_exception(CoreValidationError("invalid"), "converter")
    assert exc.status_code == 422
    assert exc.detail == "invalid"


def test_native_svg_resource_limit_maps_to_actionable_422() -> None:
    exc = to_http_exception(NativeSvgResourceLimitError(), "Vector preview")

    assert exc.status_code == 422
    assert exc.detail["code"] == "native_svg_resource_limit"
    assert exc.detail["reason"] == "unsupported_complexity"
    assert exc.detail["recovery_actions"] == ["simplify_svg", "split_svg"]


def test_vector_mesh_memory_budget_error_maps_to_actionable_422() -> None:
    error = VectorMeshMemoryBudgetError(
        "preflight",
        9 * 1024**3,
        8 * 1024**3,
        1 * 1024**3,
        4_200,
        420_000,
    )

    exc = to_http_exception(error, "3MF generation")

    assert exc.status_code == 422
    assert exc.detail["error"] == "vector_mesh_memory_budget_exceeded"
    assert exc.detail["code"] == "vector_mesh_memory_budget_exceeded"
    assert exc.detail["recoverable"] is True
    assert exc.detail["stage"] == "preflight"
    assert exc.detail["memory_budget_bytes"] == 8 * 1024**3
    assert "memory" in exc.detail["message"].lower()
    assert exc.detail["recovery_actions"] == [
        "free_system_memory",
        "retry",
        "reduce_output_size",
    ]


def test_vector_host_memory_admission_maps_to_retryable_503() -> None:
    error = VectorHostMemoryAdmissionError(
        requested_bytes=8,
        reserved_bytes=24,
        memory_budget_bytes=24,
    )

    exc = to_http_exception(error, "Vector generation")

    assert exc.status_code == 503
    assert exc.detail["code"] == "vector_host_memory_busy"
    assert exc.detail["retryable"] is True
    assert exc.detail["recovery_actions"] == ["retry_later"]
    assert exc.headers == {"Retry-After": "5"}


def test_idle_host_memory_error_does_not_claim_another_task_is_running() -> None:
    error = VectorHostMemoryAdmissionError(
        requested_bytes=8,
        reserved_bytes=0,
        memory_budget_bytes=4,
    )

    exc = to_http_exception(error, "Vector generation")

    assert "another Vector task" not in exc.detail["message"]
    assert exc.detail["recovery_actions"] == ["free_system_memory", "retry"]


def test_core_dependency_error_maps_to_502() -> None:
    exc = to_http_exception(CoreDependencyError("missing optional dependency"), "converter")
    assert exc.status_code == 502
    assert exc.detail == "missing optional dependency"


def test_core_processing_error_maps_to_500() -> None:
    exc = to_http_exception(CoreProcessingError("processing failed"), "converter")
    assert exc.status_code == 500
    assert exc.detail == "processing failed"
