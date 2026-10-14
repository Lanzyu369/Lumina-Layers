"""Local measured-stack collection endpoints. / 本地叠色实测采集接口。"""

from datetime import datetime, timezone
from typing import Callable, NoReturn, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api.errors import ConflictDomainError, NotFoundDomainError, to_http_exception
from api.local_origin_guard import require_local_app_origin
from api.schemas.lumina_box_stack_samples import (
    StackSampleDeleteResponse, StackSampleListResponse, StackSampleRecordResponse,
    StackSampleSaveRequest,
)
from api.structured_logging import get_logger
from core import lumina_box_archive
from core.errors import CoreError
from core.lumina_box_stack_samples import (
    StackSampleConflictError, StackSampleNotFoundError, StackSampleStore,
)


router = APIRouter(
    prefix="/lumina-box/stack-samples",
    tags=["Lumina Box"],
    dependencies=[Depends(require_local_app_origin)],
)
log = get_logger(__name__)
_Result = TypeVar("_Result")


def get_stack_sample_store() -> StackSampleStore:
    """Use the same current material location as the Box library.
    使用与BOX材料库一致的当前存储位置。

    Returns:
        The independent persistent stack store.（独立持久化叠色样片库。）
    """
    return StackSampleStore(lumina_box_archive.MATERIALS_DIR)


def _raise_mapped(exc: CoreError, operation: str) -> NoReturn:
    domain = (
        ConflictDomainError(str(exc)) if isinstance(exc, StackSampleConflictError)
        else NotFoundDomainError(str(exc)) if isinstance(exc, StackSampleNotFoundError)
        else exc
    )
    mapped = to_http_exception(domain, f"Lumina Box stack sample {operation}")
    log.warning(
        "Lumina Box stack sample operation failed",
        extra={"event": "lumina_box_stack_sample_failed", "operation": operation,
               "error_type": exc.error_type, "error_message": str(exc),
               "status_code": mapped.status_code},
    )
    raise mapped from exc


def _perform(operation: str, action: Callable[[], _Result]) -> _Result:
    try:
        return action()
    except CoreError as exc:
        _raise_mapped(exc, operation)


@router.post("", response_model=StackSampleRecordResponse)
def save_stack_sample(
    payload: StackSampleSaveRequest,
    store: StackSampleStore = Depends(get_stack_sample_store),
) -> StackSampleRecordResponse:
    """Save one actual reflection capture without running a fit.
    保存一次真实反射采集，不执行拟合。

    Args:
        payload: Validated sample metadata and raw device frame.（已校验样片信息及原始设备帧。）
        store: Independent persistent capture store.（独立持久采集库。）

    Returns:
        Durable sample and identical-delivery status.（持久样片及相同投递状态。）
    """
    record, deduplicated = _perform("save", lambda: store.save(payload.model_dump()))
    log.info(
        "Lumina Box stack sample saved",
        extra={"event": "lumina_box_stack_sample_save_done", "record_id": record["record_id"],
               "capture_id": record["capture_id"], "deduplicated": deduplicated},
    )
    return StackSampleRecordResponse(record=record, deduplicated=deduplicated)


@router.get("", response_model=StackSampleListResponse)
def list_stack_samples(
    store: StackSampleStore = Depends(get_stack_sample_store),
) -> StackSampleListResponse:
    """List saved actual captures, newest first. / 按时间倒序列出已存真实采集。

    Args:
        store: Independent persistent capture store.（独立持久采集库。）

    Returns:
        All undeleted samples.（全部未删除样片。）
    """
    return StackSampleListResponse(records=_perform("list", store.list))


@router.get("/export")
def export_stack_samples(
    store: StackSampleStore = Depends(get_stack_sample_store),
) -> JSONResponse:
    """Download all undeleted samples and their original measurements.
    下载全部未删除样片及其原始测量值。

    Args:
        store: Independent persistent capture store.（独立持久采集库。）

    Returns:
        A JSON attachment containing actual captures and provenance.（包含真实采集及来源的JSON附件。）
    """
    records = _perform("export", store.list)
    return JSONResponse(
        content={"schema_version": "1.0", "kind": "lumina_box_stack_samples_export",
                 "exported_at": datetime.now(timezone.utc).isoformat(), "records": records},
        headers={"Content-Disposition": 'attachment; filename="lumina-box-stack-samples.json"',
                 "Cache-Control": "no-store"},
    )


@router.get("/{record_id}", response_model=StackSampleRecordResponse)
def get_stack_sample(
    record_id: UUID,
    store: StackSampleStore = Depends(get_stack_sample_store),
) -> StackSampleRecordResponse:
    """Read one actual capture without changing the acquisition form.
    读取单条真实采集，不改变采集表单。

    Args:
        record_id: UUID of the selected sample.（选中样片的UUID。）
        store: Independent persistent capture store.（独立持久采集库。）

    Returns:
        The complete capture with replay status false.（完整采集，重放状态为假。）
    """
    record = _perform("read", lambda: store.get(str(record_id)))
    return StackSampleRecordResponse(record=record)


@router.delete("/{record_id}", response_model=StackSampleDeleteResponse)
def delete_stack_sample(
    record_id: UUID,
    store: StackSampleStore = Depends(get_stack_sample_store),
) -> StackSampleDeleteResponse:
    """Delete only the selected capture while preventing replay recreation.
    仅删除选中的采集，并阻止重放消息重建。

    Args:
        record_id: UUID of the single sample to delete.（唯一待删除样片的UUID。）
        store: Independent persistent capture store.（独立持久采集库。）

    Returns:
        The identity of the deleted sample.（已删除样片的标识。）
    """
    _perform("delete", lambda: store.delete(str(record_id)))
    log.info(
        "Lumina Box stack sample deleted",
        extra={"event": "lumina_box_stack_sample_delete_done", "record_id": str(record_id)},
    )
    return StackSampleDeleteResponse(record_id=record_id)
