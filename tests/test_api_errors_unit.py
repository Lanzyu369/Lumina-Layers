"""Unit tests for domain error -> HTTP exception mapping."""

from __future__ import annotations

from fastapi import HTTPException

from api.errors import (
    ConflictDomainError,
    GoneDomainError,
    LuminaBoxMaterialNameConflictDomainError,
    NotFoundDomainError,
    UpstreamDomainError,
    ValidationDomainError,
    to_http_exception,
)
from core.errors import (
    CoreDependencyError,
    CoreProcessingError,
    CoreValidationError,
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


def test_gone_domain_error_maps_to_410() -> None:
    exc = to_http_exception(GoneDomainError("fit expired"), "Lumina Box material save")
    assert exc.status_code == 410
    assert exc.detail == "fit expired"


def test_lumina_box_name_conflict_has_a_stable_client_code() -> None:
    exc = to_http_exception(
        LuminaBoxMaterialNameConflictDomainError("same brand/name exists"),
        "Lumina Box material save",
    )
    assert exc.status_code == 409
    assert exc.detail == {
        "code": "lumina_box_material_name_conflict",
        "message": "same brand/name exists",
    }


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


def test_core_dependency_error_maps_to_502() -> None:
    exc = to_http_exception(CoreDependencyError("missing optional dependency"), "converter")
    assert exc.status_code == 502
    assert exc.detail == "missing optional dependency"


def test_core_processing_error_maps_to_500() -> None:
    exc = to_http_exception(CoreProcessingError("processing failed"), "converter")
    assert exc.status_code == 500
    assert exc.detail == "processing failed"
