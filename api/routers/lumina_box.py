"""Lumina Box measurement records and spectral material-archive API routes.
Lumina Box 测量记录与波段耗材档案接口。

Calibrated paired XYZ percentages enter a bounded worker using the explicit
calibration-white reference. The server owns fitted data until an archive save.
校准后的配对 XYZ 百分数与明确的白参考进入有时限的工作进程，拟合结果由服务器持有至保存。
"""

from __future__ import annotations

import asyncio

import json
import math
from pathlib import Path
import time
from typing import Any, NoReturn
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.errors import (
    DomainError,
    GoneDomainError,
    NotFoundDomainError,
    LuminaBoxMaterialNameConflictDomainError,
    ValidationDomainError,
    to_http_exception,
)
from api.file_registry import FileRegistry
from api.local_origin_guard import require_local_app_origin
from api.routers.lumina_box_stack_samples import router as stack_samples_router
from api.routers.backed_gradient import router as backed_gradient_router
from api.schemas.lumina_box import (
    LUMINA_BOX_COLOR_BRIDGE_ID,
    LUMINA_BOX_MEASUREMENT_REFLECTION_BOUNDARY_ID,
    LUMINA_BOX_OPTICAL_MODEL_ID,
    LUMINA_BOX_PROTOCOL_ID,
    LuminaBoxFitRequest,
    LuminaBoxFitResponse,
    LuminaBoxMaterialLibraryResponse,
    LuminaBoxMeasurementListResponse,
    LuminaBoxMeasurementRecordResponse,
    LuminaBoxRawMeasurementsRequest,
    LuminaBoxSaveRequest,
    LuminaBoxSaveResponse,
)
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from api.workers.lumina_box_workers import fit_lumina_box_spectral_worker
from api.structured_logging import bind_session_id, get_logger
from core.errors import CoreError, CoreProcessingError, CoreValidationError
from core.lumina_box_fitting import LuminaBoxFitError
from core.lumina_box_spectral import LUMINA_BOX_CONSTRAINED_OBJECTIVE_ID, LuminaBoxModelError
from core.lumina_box_spectral_archive import load_calibration_white_reference, normalize_spectral_fit_payload
from core.lumina_box_archive import (
    LUMINA_BOX_FIT_QUALITY_UNSAVABLE_CODE,
    evaluate_lumina_box_fit_quality,
    list_lumina_box_material_archives,
    list_lumina_box_measurements,
    load_lumina_box_measurements,
    save_lumina_box_measurements,
    save_lumina_box_material_archive,
)
from core.single_stage import invalidate_material_library_cache


router = APIRouter(prefix="/api/extractor", tags=["Lumina Box"])
router.include_router(stack_samples_router)
router.include_router(backed_gradient_router)
log = get_logger(__name__)

_FIT_SESSION_KEY = "lumina_box_spectral_fit"
_FIT_SESSION_KIND = "lumina_box_spectral_fit/v1"
LUMINA_BOX_FIT_SESSION_TTL_SECONDS = 30 * 60


def _measurement_payload(payload: LuminaBoxFitRequest) -> dict[str, Any]:
    """Build the canonical raw percent sample record stored alongside a fit."""
    return {
        "protocol_id": payload.protocol_id,
        "value_scale": payload.value_scale,
        "measurement_backing_percent_xyz": list(
            payload.measurement_backing_percent_xyz
        ),
        "samples": [
            {
                "thickness_mm": sample.thickness_mm,
                "transmittance_percent_xyz": list(sample.transmittance_percent_xyz),
                "reflectance_percent_xyz": list(sample.reflectance_percent_xyz),
            }
            for sample in payload.samples
        ],
    }


def _raise_save_fit_session_error(
    *,
    fit_session_id: str,
    reason: str,
    error: GoneDomainError | ValidationDomainError,
) -> NoReturn:
    """Log and map a failed server-owned fit-session lookup consistently."""
    mapped_error = to_http_exception(error, "Lumina Box material save")
    log.warning(
        "Lumina Box material save fit session rejected",
        extra={
            "event": "lumina_box_save_failed",
            "session_id": fit_session_id,
            "status_code": mapped_error.status_code,
            "error_type": error.error_type,
            "error_message": error.detail,
            "failure_reason": reason,
        },
    )
    raise mapped_error


def _raise_unsavable_fit_error(
    *,
    fit_session_id: str,
    reasons: list[str],
) -> NoReturn:
    """Reject a fitted profile when the optimizer did not converge."""
    message = (
        "Lumina Box fitting did not converge. "
        "Save the original measurements for another attempt."
    )
    log.warning(
        "Lumina Box material save fit quality rejected",
        extra={
            "event": "lumina_box_save_failed",
            "session_id": fit_session_id,
            "status_code": 422,
            "error_type": LUMINA_BOX_FIT_QUALITY_UNSAVABLE_CODE,
            "error_message": message,
            "failure_reason": "fit_quality_unsavable",
            "quality_reasons": reasons,
        },
    )
    raise HTTPException(
        status_code=422,
        detail={
            "code": LUMINA_BOX_FIT_QUALITY_UNSAVABLE_CODE,
            "message": message,
            "reasons": reasons,
        },
    )


@router.post(
    "/lumina-box/fit",
    response_model=LuminaBoxFitResponse,
    dependencies=[Depends(require_local_app_origin)],
)
async def fit_lumina_box_material(
    payload: LuminaBoxFitRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
    pool: WorkerPoolManager = Depends(get_worker_pool),
) -> LuminaBoxFitResponse:
    """Fit the adopted spectral model in a bounded CPU worker.
    在有耗时上限的工作进程内拟合已采用波段模型，明确保存前结果仅由服务器持有。

    Args:
        payload: Validated paired observations and reference selection.（已校验测量及白参考选择。）
        store: Server-owned fit sessions.（服务器拟合会话。）
        registry: Private temporary-file ownership.（私有临时文件登记。）
        pool: Managed CPU worker pool.（受管理计算进程池。）

    Returns:
        The adopted-model result and its save-session identity.（新版结果及保存会话标识。）
    """
    measurement = _measurement_payload(payload)
    work_id = str(uuid4())
    try:
        reference = None if payload.is_reference_white else load_calibration_white_reference(
            payload.reference_directory_name or ""
        )
        request_data = {
            "measurement": measurement,
            "is_reference_white": payload.is_reference_white,
            "reference_min_reflectance_percent": payload.reference_min_reflectance_percent,
            "white_reference": reference.to_dict() if reference is not None else None,
        }
        input_id = registry.register_bytes(
            work_id, json.dumps(request_data, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            "box-fit-input.json", ttl_seconds=600, is_public=False, purpose="lumina_box_fit_input",
        )
        output_id = registry.register_bytes(
            work_id, b"{}", "box-fit-output.json", ttl_seconds=600,
            is_public=False, purpose="lumina_box_fit_output",
        )
        input_file, output_file = registry.resolve(input_id), registry.resolve(output_id)
        if input_file is None or output_file is None:
            raise RuntimeError("Registered Box fitting files are unavailable")
        returned_path = await asyncio.wait_for(
            pool.submit(fit_lumina_box_spectral_worker, input_file[0], output_file[0]),
            timeout=240.0,
        )
        if returned_path != output_file[0]:
            raise RuntimeError("Box fitting worker returned an unexpected result path")
        fit = normalize_spectral_fit_payload(
            json.loads(Path(output_file[0]).read_text(encoding="utf-8")), measurement,
        )
        if fit["is_reference_white"] != payload.is_reference_white:
            raise RuntimeError("Box fitting result does not match the requested reference role")
        if payload.is_reference_white and not math.isclose(
            fit["white_reference"].get("minimum_total_reflectance_y", -1.0),
            payload.reference_min_reflectance_percent / 100.0, rel_tol=0.0, abs_tol=1e-12,
        ):
            raise RuntimeError("Box fitting result changed the requested white reflectance bound")
        if reference is not None and fit["white_reference"]["reference_id"] != reference.reference_id:
            raise RuntimeError("Box fitting result used a different white reference")
    except TimeoutError as exc:
        log.warning(
            "Lumina Box fit timed out",
            extra={"event": "lumina_box_fit_failed", "status_code": 504,
                   "error_type": "lumina_box_fit_timeout", "error_message": str(exc)},
        )
        raise to_http_exception(
            DomainError("Lumina Box fitting timed out. Retry the same measurements.", 504, "lumina_box_fit_timeout"),
            "Lumina Box fit",
        ) from exc
    except (CoreValidationError, LuminaBoxModelError, LuminaBoxFitError) as exc:
        log.warning(
            "Lumina Box fit input or reference rejected",
            extra={"event": "lumina_box_fit_failed", "status_code": 422,
                   "error_type": type(exc).__name__, "error_message": str(exc)},
        )
        raise to_http_exception(ValidationDomainError(str(exc)), "Lumina Box fit") from exc
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        log.error(
            "Lumina Box fit failed unexpectedly",
            extra={"event": "lumina_box_fit_failed", "status_code": 500,
                   "error_type": type(exc).__name__, "error_message": str(exc)},
        )
        raise to_http_exception(CoreProcessingError("Lumina Box fit failed"), "Lumina Box fit") from exc
    finally:
        registry.cleanup_session(work_id)

    fit_record = {
        "kind": _FIT_SESSION_KIND,
        "expires_at_monotonic": time.monotonic() + LUMINA_BOX_FIT_SESSION_TTL_SECONDS,
        "measurement": measurement, "fit": fit,
        "reference_directory_name": payload.reference_directory_name,
    }
    fit_session_id = store.create()
    bind_session_id(fit_session_id)
    store.put(fit_session_id, _FIT_SESSION_KEY, fit_record)
    log.info(
        "Lumina Box material fitted",
        extra={"event": "lumina_box_fit_done", "session_id": fit_session_id,
               "sample_count": len(fit["sample_predictions"]), "warning_count": len(fit["warnings"]),
               "optical_model_id": LUMINA_BOX_OPTICAL_MODEL_ID},
    )
    response = {key: value for key, value in fit.items() if key in LuminaBoxFitResponse.model_fields}
    return LuminaBoxFitResponse(
        **response, message="Lumina Box material fitted successfully", fit_session_id=fit_session_id,
        reference_id=fit["white_reference"]["reference_id"],
        estimated_srgb=[channel / 255.0 for channel in fit["estimated_rgb"]],
    )


@router.post(
    "/lumina-box/save",
    response_model=LuminaBoxSaveResponse,
    dependencies=[Depends(require_local_app_origin)],
)
async def save_lumina_box_material(
    payload: LuminaBoxSaveRequest,
    store: SessionStore = Depends(get_session_store),
) -> LuminaBoxSaveResponse:
    """Persist only a server-owned Lumina Box fit session as a material archive."""
    fit_session_id = str(payload.fit_session_id)
    bind_session_id(fit_session_id)
    session_data = store.get(fit_session_id)
    if session_data is None:
        _raise_save_fit_session_error(
            fit_session_id=fit_session_id,
            reason="fit_session_unavailable",
            error=GoneDomainError(
                "Lumina Box fit session is no longer available. Fit the measurements again before saving."
            ),
        )
    fit_record = session_data.get(_FIT_SESSION_KEY)
    if not isinstance(fit_record, dict) or fit_record.get("kind") != _FIT_SESSION_KIND:
        _raise_save_fit_session_error(
            fit_session_id=fit_session_id,
            reason="fit_record_invalid",
            error=ValidationDomainError(
                "Session does not contain a valid Lumina Box fit result"
            ),
        )
    expires_at = fit_record.get("expires_at_monotonic")
    if (
        not isinstance(expires_at, (int, float))
        or not math.isfinite(float(expires_at))
        or time.monotonic() >= float(expires_at)
    ):
        _raise_save_fit_session_error(
            fit_session_id=fit_session_id,
            reason="fit_session_expired",
            error=GoneDomainError(
                "Lumina Box fit session has expired. Fit the measurements again before saving."
            ),
        )
    measurement = fit_record.get("measurement")
    fit = fit_record.get("fit")
    if not isinstance(measurement, dict) or not isinstance(fit, dict):
        _raise_save_fit_session_error(
            fit_session_id=fit_session_id,
            reason="fit_record_incomplete",
            error=ValidationDomainError(
                "Session does not contain a complete Lumina Box fit result"
            ),
        )
    if fit.get("optical_model_id") != LUMINA_BOX_OPTICAL_MODEL_ID:
        _raise_save_fit_session_error(
            fit_session_id=fit_session_id, reason="fit_model_outdated",
            error=ValidationDomainError("Fit these measurements again with the current Lumina Box model"),
        )
    fit_quality = fit.get("fit_quality")
    if not isinstance(fit_quality, dict) or not isinstance(
        fit_quality.get("savable"),
        bool,
    ):
        _raise_save_fit_session_error(
            fit_session_id=fit_session_id,
            reason="fit_quality_invalid",
            error=ValidationDomainError(
                "Session does not contain a valid Lumina Box fit quality result"
            ),
        )
    if not fit_quality["savable"]:
        raw_reasons = fit_quality.get("reasons")
        reasons = (
            [str(reason) for reason in raw_reasons]
            if isinstance(raw_reasons, list)
            else []
        )
        _raise_unsavable_fit_error(
            fit_session_id=fit_session_id,
            reasons=reasons,
        )
    try:
        if not fit.get("is_reference_white"):
            current_reference = load_calibration_white_reference(
                str(fit_record.get("reference_directory_name") or "")
            )
            if current_reference.reference_id != fit.get("white_reference", {}).get("reference_id"):
                raise CoreValidationError("The calibration white changed after fitting; fit this material again before saving")
        result = save_lumina_box_material_archive(
            material_name=payload.material_name,
            brand=payload.brand,
            material_type=payload.material_type,
            notes=payload.notes,
            measurement_payload=measurement,
            fit_payload=fit,
            overwrite=payload.overwrite,
        )
        invalidate_material_library_cache()
    except CoreError as exc:
        if exc.detail == LUMINA_BOX_FIT_QUALITY_UNSAVABLE_CODE:
            raw_quality = fit.get("fit_quality")
            raw_reasons = (
                raw_quality.get("reasons")
                if isinstance(raw_quality, dict)
                else []
            )
            _raise_unsavable_fit_error(
                fit_session_id=fit_session_id,
                reasons=(
                    [str(reason) for reason in raw_reasons]
                    if isinstance(raw_reasons, list)
                    else []
                ),
            )
        domain_error: CoreError | LuminaBoxMaterialNameConflictDomainError = exc
        if exc.error_type == "material_archive_conflict":
            domain_error = LuminaBoxMaterialNameConflictDomainError(exc.detail)
        mapped_error = to_http_exception(domain_error, "Lumina Box material save")
        log.warning(
            "Lumina Box material save rejected",
            extra={
                "event": "lumina_box_save_failed",
                "session_id": fit_session_id,
                "status_code": mapped_error.status_code,
                "error_type": exc.error_type,
                "error_message": exc.detail,
            },
        )
        raise mapped_error from exc
    except (OSError, RuntimeError) as exc:
        log.error(
            "Lumina Box material save failed",
            extra={
                "event": "lumina_box_save_failed",
                "session_id": fit_session_id,
                "status_code": 500,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise to_http_exception(
            CoreProcessingError("Lumina Box material save failed"),
            "Lumina Box material save",
        ) from exc

    log.info(
        "Lumina Box material saved",
        extra={
            "event": "lumina_box_save_done",
            "session_id": fit_session_id,
            "directory_name": result.material_summary["directory_name"],
            "overwrite": bool(payload.overwrite),
        },
    )
    return LuminaBoxSaveResponse(
        message="Lumina Box material saved successfully",
        material=result.material_summary,
    )


def _raise_measurement_record_error(
    exc: CoreError | OSError, action: str,
) -> NoReturn:
    if isinstance(exc, FileNotFoundError):
        error = NotFoundDomainError("Lumina Box measurement record was not found")
    elif isinstance(exc, CoreError):
        error = exc
    else:
        error = CoreProcessingError(
            "Lumina Box measurement records could not be accessed"
        )
    mapped = to_http_exception(error, "Lumina Box measurements")
    log.warning(
        "Lumina Box measurement record operation failed",
        extra={
            "event": "lumina_box_measurements_failed",
            "action": action,
            "status_code": mapped.status_code,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        },
    )
    raise mapped from exc


@router.post(
    "/lumina-box/measurements",
    response_model=LuminaBoxMeasurementRecordResponse,
    dependencies=[Depends(require_local_app_origin)],
)
async def save_lumina_box_measurement_record(
    payload: LuminaBoxRawMeasurementsRequest,
) -> LuminaBoxMeasurementRecordResponse:
    """Save original input independently of fit quality and session lifetime.
    保存原始输入，不受拟合质量或会话有效期影响。
    """
    try:
        record = save_lumina_box_measurements(payload.model_dump())
    except (CoreError, OSError) as exc:
        _raise_measurement_record_error(exc, "save")
    log.info(
        "Lumina Box original measurements saved",
        extra={
            "event": "lumina_box_measurements_save_done",
            "record_id": record["record_id"],
            "sample_count": len(record["samples"]),
        },
    )
    return LuminaBoxMeasurementRecordResponse(record=record)


@router.get(
    "/lumina-box/measurements",
    response_model=LuminaBoxMeasurementListResponse,
    dependencies=[Depends(require_local_app_origin)],
)
async def list_lumina_box_measurement_records() -> LuminaBoxMeasurementListResponse:
    """List durable raw captures.（列出持久保存的原始采集记录）"""
    try:
        records = list_lumina_box_measurements()
    except (CoreError, OSError) as exc:
        _raise_measurement_record_error(exc, "list")
    return LuminaBoxMeasurementListResponse(records=records)


@router.get(
    "/lumina-box/measurements/{record_id}",
    response_model=LuminaBoxMeasurementRecordResponse,
    dependencies=[Depends(require_local_app_origin)],
)
async def load_lumina_box_measurement_record(
    record_id: UUID,
) -> LuminaBoxMeasurementRecordResponse:
    """Reload original input for another fitting attempt.（载入原始输入以再次拟合）"""
    try:
        record = load_lumina_box_measurements(str(record_id))
    except (CoreError, OSError) as exc:
        _raise_measurement_record_error(exc, "load")
    return LuminaBoxMeasurementRecordResponse(record=record)


@router.get(
    "/lumina-box/materials",
    response_model=LuminaBoxMaterialLibraryResponse,
    dependencies=[Depends(require_local_app_origin)],
)
async def list_lumina_box_materials() -> LuminaBoxMaterialLibraryResponse:
    """List current spectral archives and count historical archives needing upgrade.
    列出当前波段档案，并统计需要升级的旧版档案；不返回本机文件路径。
    """
    try:
        materials = list_lumina_box_material_archives()
    except (OSError, RuntimeError, ValueError) as exc:
        log.error(
            "Lumina Box material library failed",
            extra={
                "event": "lumina_box_material_library_failed",
                "status_code": 500,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise to_http_exception(
            CoreProcessingError("Lumina Box material library could not be loaded"),
            "Lumina Box material library",
        ) from exc
    current = [material for material in materials if (
        material.get("optical_model_id") == LUMINA_BOX_OPTICAL_MODEL_ID
        and material.get("fit_objective_id") == LUMINA_BOX_CONSTRAINED_OBJECTIVE_ID
    )]
    return LuminaBoxMaterialLibraryResponse(
        message=f"Loaded {len(current)} Lumina Box materials",
        materials=current,
        outdated_count=len(materials) - len(current),
    )
