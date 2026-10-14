"""Independent backed-gradient capture and modeling endpoints.
独立的黑白底梯度采集与建模接口。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import FileResponse, JSONResponse

from api.backed_gradient_jobs import (
    read_result, read_run, start_material_fit, start_backing_fit,
    start_backing_material_fit,
)
from api.dependencies import get_file_registry, get_worker_pool
from api.errors import ConflictDomainError, NotFoundDomainError, to_http_exception
from api.file_registry import FileRegistry
from api.local_origin_guard import require_local_app_origin
from api.schemas.backed_gradient import (
    GradientCaptureRequest, GradientDatasetCreate, GradientSelectionRequest,
    MaterialDatasetCreate, BackingDatasetCreate, MaterialFitRequest, MaterialArchiveSaveRequest,
    BackingMaterialDatasetCreate, BlackWhitePairCreate,
)
from api.structured_logging import get_logger
from api.worker_pool import WorkerPoolManager
from core import lumina_box_archive
from core.backed_gradient_store import BackedGradientConflictError, BackedGradientNotFoundError, BackedGradientStore
from core.backed_gradient_product_store import (
    create_material_dataset, create_backing_dataset, list_backing_references,
)
from core.errors import CoreError, CoreProcessingError, CoreValidationError


router = APIRouter(prefix="/lumina-box/backed-gradient", tags=["Lumina Box"],
                   dependencies=[Depends(require_local_app_origin)])
log = get_logger(__name__)
_Result = TypeVar("_Result")


def get_gradient_store() -> BackedGradientStore:
    """Use the active library only for independent experiment storage.
    仅使用当前材料库位置存放独立实验。

    Returns:
        Independent backed-gradient store.（独立黑白底梯度库。）
    """
    return BackedGradientStore(lumina_box_archive.MATERIALS_DIR)


def _perform(operation: str, action: Callable[[], _Result]) -> _Result:
    try:
        return action()
    except CoreError as exc:
        error = (ConflictDomainError(str(exc)) if isinstance(exc, BackedGradientConflictError)
                 else NotFoundDomainError(str(exc)) if isinstance(exc, BackedGradientNotFoundError) else exc)
        mapped = to_http_exception(error, "Backed-gradient " + operation)
        log.warning("Backed-gradient operation failed", extra={"event": "backed_gradient_operation_failed",
                    "operation": operation, "error_type": exc.error_type, "error_message": str(exc), "status_code": mapped.status_code})
        raise mapped from exc


@router.get("/backing-materials")
def list_independent_backings(store: BackedGradientStore = Depends(get_gradient_store)) -> dict:
    """List independently saved backing materials. / 列出独立保存的背板耗材。

    Args:
        store: Capture storage.（采集存储。）
    Returns:
        Names, readiness, and stable identities.（名称、完成状态和稳定身份。）
    """
    from core.backed_gradient_backing_store import list_backing_materials
    from core.black_white_material_profiles import black_white_archive_index

    fields = ("material_id", "version_id", "role", "name", "brand", "material_type", "dataset_id",
              "active_dataset_id", "opposite_material_id", "status", "reference_id", "created_at", "updated_at", "dataset_revision")
    def listing() -> list[dict]:
        archives = black_white_archive_index(store.root)
        items = []
        for item in list_backing_materials(store):
            item = {**item, "dataset_revision": item.get("snapshot", {}).get("dataset_revision")}
            profile = archives.get(item["material_id"])
            if item["status"] == "ready" and profile is None:
                continue
            if profile:
                item = {**item, "name": profile[1]["material_name"], "brand": profile[1].get("brand", ""),
                        "material_type": profile[1].get("material_type", "")}
            items.append({key: item[key] for key in fields if key in item})
        return items
    return {"backings": _perform("backing_materials", listing)}


@router.post("/backing-material-datasets")
def create_independent_backing(payload: BackingMaterialDatasetCreate,
                               store: BackedGradientStore = Depends(get_gradient_store)) -> dict:
    """Start one backing without requiring another completed capture.
    开始单个背板采集，不要求另一份资料同时完成。

    Args:
        payload: Own identity and actual sample backing.（自身身份及样片实际底材。）
        store: Capture storage.（采集存储。）
    Returns:
        Independent capture.（独立采集表。）
    """
    from core.backed_gradient_backing_store import create_backing_material_dataset

    dataset = _perform("backing_material_create", lambda: create_backing_material_dataset(store, payload.model_dump(exclude_none=True)))
    log.info("Independent backing capture created", extra={"event": "backed_gradient_backing_material_create_done", "dataset_id": dataset["dataset_id"]})
    return {"dataset": dataset}


@router.post("/black-white-pairs")
def create_black_white_materials(payload: BlackWhitePairCreate,
                                 store: BackedGradientStore = Depends(get_gradient_store)) -> dict:
    """Start the first black/white pair without requiring an existing archive.
    创建首组黑白耗材，无需已有档案。

    Args:
        payload: Both material identities.（两种耗材身份。）
        store: Capture storage.（采集存储。）
    Returns:
        First capture with its partner registered.（已关联另一耗材的首份采集。）
    """
    from core.backed_gradient_backing_store import create_black_white_pair

    dataset = _perform("backing_material_create", lambda: create_black_white_pair(store, payload.model_dump()))
    log.info("Black and white captures created", extra={"event": "backed_gradient_backing_material_create_done",
                                                      "dataset_id": dataset["dataset_id"]})
    return {"dataset": dataset}


@router.post("/backing-material-datasets/{dataset_id}/fit-runs")
async def create_independent_backing_fit(dataset_id: UUID, store: BackedGradientStore = Depends(get_gradient_store),
                                         pool: WorkerPoolManager = Depends(get_worker_pool)) -> dict:
    """Save and fit one independently captured backing. / 保存并拟合独立采集的单个背板。

    Args:
        dataset_id: This backing's capture.（本背板采集身份。）
        store: Capture storage.（采集存储。）
        pool: Calculation workers.（计算进程。）
    Returns:
        Durable job.（持久任务。）
    """
    run = _perform("backing_material_fit", lambda: start_backing_material_fit(store, pool, str(dataset_id)))
    log.info("Independent backing fitting queued", extra={"event": "backed_gradient_backing_material_fit_queue_done", "fit_id": run["fit_id"]})
    return {"run": run}


@router.get("/references")
def list_references(store: BackedGradientStore = Depends(get_gradient_store)) -> dict:
    """List named reusable backing setups. / 列出可复用背板设置。

    Args:
        store: Capture storage.（采集存储。）

    Returns:
        Saved references.（已存标定。）
    """
    return {"references": _perform("references", lambda: list_backing_references(store))}


@router.post("/material-datasets")
def create_material_capture(payload: MaterialDatasetCreate, store: BackedGradientStore = Depends(get_gradient_store)) -> dict:
    """Create one material capture. / 创建单耗材采集。

    Args:
        payload: Material and backing selection.（材料及背板选择。）
        store: Capture storage.（采集存储。）

    Returns:
        Created capture.（已创建采集。）
    """
    dataset = _perform("create", lambda: create_material_dataset(store, payload.model_dump(exclude_none=True)))
    log.info("Box material capture created", extra={"event": "backed_gradient_material_create_done", "dataset_id": dataset["dataset_id"]})
    return {"dataset": dataset}


@router.post("/backing-datasets")
def create_backing_capture(payload: BackingDatasetCreate, store: BackedGradientStore = Depends(get_gradient_store)) -> dict:
    """Create a shared backing setup. / 创建共享背板设置。

    Args:
        payload: Backing material names.（背板材料名称。）
        store: Capture storage.（采集存储。）

    Returns:
        Created capture.（已创建采集。）
    """
    dataset = _perform("create", lambda: create_backing_dataset(store, payload.model_dump()))
    log.info("Box backing capture created", extra={"event": "backed_gradient_backing_create_done", "dataset_id": dataset["dataset_id"]})
    return {"dataset": dataset}


@router.post("/material-datasets/{dataset_id}/fit-runs")
async def create_material_fit(dataset_id: UUID, payload: MaterialFitRequest,
                              store: BackedGradientStore = Depends(get_gradient_store),
                              pool: WorkerPoolManager = Depends(get_worker_pool)) -> dict:
    """Fit one material using its saved reference. / 使用已存标定拟合单耗材。

    Args:
        dataset_id: Capture identity.（采集身份。）
        payload: Optional historical material selection.（可选历史材料选择。）
        store: Capture storage.（采集存储。）
        pool: Managed CPU workers.（受管理计算进程。）

    Returns:
        Queued job.（已提交任务。）
    """
    run = _perform("fit", lambda: start_material_fit(store, pool, str(dataset_id), **payload.model_dump()))
    log.info("Box material fitting queued", extra={"event": "backed_gradient_material_fit_queue_done", "fit_id": run["fit_id"]})
    return {"run": run}


@router.post("/backing-datasets/{dataset_id}/fit-runs")
async def create_backing_fit(dataset_id: UUID, store: BackedGradientStore = Depends(get_gradient_store),
                             pool: WorkerPoolManager = Depends(get_worker_pool)) -> dict:
    """Fit reusable black/white backings. / 拟合可复用黑白背板。

    Args:
        dataset_id: Capture identity.（采集身份。）
        store: Capture storage.（采集存储。）
        pool: Managed CPU workers.（受管理计算进程。）

    Returns:
        Queued job.（已提交任务。）
    """
    run = _perform("fit", lambda: start_backing_fit(store, pool, str(dataset_id)))
    log.info("Box backing fitting queued", extra={"event": "backed_gradient_backing_fit_queue_done", "fit_id": run["fit_id"]})
    return {"run": run}


@router.post("/material-fit-runs/{fit_id}/archive")
def save_material_archive(fit_id: UUID, payload: MaterialArchiveSaveRequest,
                           store: BackedGradientStore = Depends(get_gradient_store)) -> dict:
    """Save a completed fit to the ordinary material library.
    将已完成拟合保存到常规耗材库。

    Args:
        fit_id: Completed material job.（已完成耗材任务。）
        payload: Archive name and overwrite choice.（档案名称及覆盖选择。）
        store: Capture and result storage.（采集及结果存储。）

    Returns:
        Saved material summary.（已存耗材摘要。）
    """
    from core.backed_gradient_archive import save_backed_gradient_material_archive
    from core.single_stage import invalidate_material_library_cache

    def save() -> dict:
        run = read_run(store, str(fit_id))
        if run["fit_mode"] != "material":
            raise CoreValidationError("Generate a material profile before saving to the library.")
        fit = read_result(store, str(fit_id))
        try:
            measurement = json.loads((store.results_root / str(fit_id) / "input.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CoreProcessingError("The original fitted readings could not be loaded.") from exc
        saved = save_backed_gradient_material_archive(
            material_name=payload.name, brand=payload.brand, material_type=payload.material_type,
            notes=payload.notes, measurement_payload=measurement, fit_payload=fit,
            overwrite=payload.overwrite, materials_dir=str(store.root),
        )
        invalidate_material_library_cache()
        return saved.material_summary

    material = _perform("archive_save", save)
    log.info("Box material archive saved", extra={"event": "backed_gradient_material_archive_save_done", "fit_id": str(fit_id),
                                                "directory_name": material["directory_name"]})
    return {"status": "ok", "message": "Material saved", "material": material}


@router.get("/datasets")
def list_datasets(store: BackedGradientStore = Depends(get_gradient_store)) -> dict[str, Any]:
    """List saved experiments. / 列出已保存实验。

    Args:
        store: Experiment storage.（实验存储。）

    Returns:
        Saved experiments and readings.（已保存实验及读数。）
    """
    return {"datasets": _perform("list", store.list)}


@router.post("/datasets")
def create_dataset(payload: GradientDatasetCreate, store: BackedGradientStore = Depends(get_gradient_store)) -> dict[str, Any]:
    """Create an experiment without modifying existing materials.
    创建实验，不修改现有材料。

    Args:
        payload: Experiment identity.（实验身份。）
        store: Independent storage.（独立存储。）

    Returns:
        Created experiment.（已创建实验。）
    """
    dataset = _perform("create", lambda: store.create(payload.model_dump()))
    log.info("Backed-gradient experiment created", extra={"event": "backed_gradient_dataset_create_done", "dataset_id": dataset["dataset_id"]})
    return {"dataset": dataset}


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: UUID, store: BackedGradientStore = Depends(get_gradient_store)) -> dict[str, Any]:
    """Restore all durable readings and choices. / 恢复全部持久读数及选择。

    Args:
        dataset_id: Experiment UUID.（实验UUID。）
        store: Independent storage.（独立存储。）

    Returns:
        Complete experiment.（完整实验。）
    """
    dataset = _perform("read", lambda: store.get(str(dataset_id)))
    workflow = dataset.get("workflow", {})
    if workflow.get("kind") == "material" and not workflow.get("backing_id"):
        from core.backed_gradient_product_store import backing_group_id

        workflow["backing_id"] = backing_group_id(workflow["backing_reference"]["reference"])
    return {"dataset": dataset}


@router.post("/datasets/{dataset_id}/captures")
def save_capture(dataset_id: UUID, payload: GradientCaptureRequest, store: BackedGradientStore = Depends(get_gradient_store)) -> dict[str, Any]:
    """Commit a frozen-target capture before USB acknowledgement.
    USB确认前提交固定目标读数。

    Args:
        dataset_id: Experiment UUID.（实验UUID。）
        payload: Device/manual reading.（设备或手动读数。）
        store: Independent storage.（独立存储。）

    Returns:
        Capture, duplicate status and updated experiment.（采集、重复状态及更新实验。）
    """
    record, duplicate, dataset = _perform("capture", lambda: store.save_capture(str(dataset_id), payload.model_dump(exclude_none=True)))
    log.info("Backed-gradient reading saved", extra={"event": "backed_gradient_capture_save_done", "dataset_id": str(dataset_id),
                                                   "record_id": record["record_id"], "deduplicated": duplicate})
    return {"record": record, "deduplicated": duplicate, "dataset": dataset}


@router.post("/datasets/{dataset_id}/selection")
def select_capture(dataset_id: UUID, payload: GradientSelectionRequest, store: BackedGradientStore = Depends(get_gradient_store)) -> dict[str, Any]:
    """Choose an unchanged historic reading. / 选择未被修改的历史读数。

    Args:
        dataset_id: Experiment UUID.（实验UUID。）
        payload: Saved reading ID.（已存读数ID。）
        store: Independent storage.（独立存储。）

    Returns:
        Updated experiment.（更新实验。）
    """
    dataset = _perform("select", lambda: store.select(str(dataset_id), payload.record_id))
    log.info("Backed-gradient selection saved", extra={"event": "backed_gradient_selection_save_done", "dataset_id": str(dataset_id)})
    return {"dataset": dataset}


@router.delete("/datasets/{dataset_id}/captures/{record_id}")
def delete_capture(dataset_id: UUID, record_id: UUID, store: BackedGradientStore = Depends(get_gradient_store)) -> dict[str, Any]:
    """Delete one capture, preserving its replay receipt. / 删除一条采集，保留重放回执。

    Args:
        dataset_id: Experiment UUID.（实验UUID。）
        record_id: Reading UUID.（读数UUID。）
        store: Independent storage.（独立存储。）

    Returns:
        Updated experiment.（更新实验。）
    """
    dataset = _perform("delete", lambda: store.delete_capture(str(dataset_id), str(record_id)))
    log.info("Backed-gradient reading deleted", extra={"event": "backed_gradient_capture_delete_done", "record_id": str(record_id)})
    return {"dataset": dataset}


@router.get("/datasets/{dataset_id}/export")
def export_dataset(dataset_id: UUID, store: BackedGradientStore = Depends(get_gradient_store)) -> JSONResponse:
    """Export original values and complete replay protection. / 导出原值及完整重放保护。

    Args:
        dataset_id: Experiment UUID.（实验UUID。）
        store: Independent storage.（独立存储。）

    Returns:
        Lossless JSON attachment.（无损JSON附件。）
    """
    document = _perform("export", lambda: store.export(str(dataset_id)))
    return JSONResponse(document, headers={"Content-Disposition": 'attachment; filename="lumina-box-backed-gradient.json"', "Cache-Control": "no-store"})


@router.post("/import")
def import_dataset(payload: dict[str, Any], store: BackedGradientStore = Depends(get_gradient_store)) -> dict[str, Any]:
    """Restore/merge an export with atomic identity checks.
    原子校验身份并恢复或合并导出数据。

    Args:
        payload: Portable experiment.（可携实验。）
        store: Independent storage.（独立存储。）

    Returns:
        Restored experiment.（已恢复实验。）
    """
    dataset = _perform("import", lambda: store.import_document(payload))
    log.info("Backed-gradient experiment imported", extra={"event": "backed_gradient_dataset_import_done", "dataset_id": dataset["dataset_id"]})
    return {"dataset": dataset}




@router.get("/datasets/{dataset_id}/fit-runs")
def list_fit_runs(dataset_id: UUID, store: BackedGradientStore = Depends(get_gradient_store)) -> dict[str, Any]:
    """Read immutable result history. / 读取不可变结果历史。

    Args:
        dataset_id: Experiment UUID.（实验UUID。）
        store: Experiment storage.（实验存储。）

    Returns:
        Persisted tasks.（持久任务。）
    """
    runs = _perform("fit_history", lambda: store.list_runs(str(dataset_id)))
    return {"runs": [_perform("fit_progress", lambda identity=run["fit_id"]: read_run(store, identity)) for run in runs]}


@router.get("/fit-runs/{fit_id}")
def get_fit_run(fit_id: UUID, store: BackedGradientStore = Depends(get_gradient_store)) -> dict[str, Any]:
    """Read fit progress without blocking capture. / 读取拟合进度，不阻塞采集。

    Args:
        fit_id: Task UUID.（任务UUID。）
        store: Experiment storage.（实验存储。）

    Returns:
        Current task state.（当前任务状态。）
    """
    return {"run": _perform("fit_progress", lambda: read_run(store, str(fit_id)))}


@router.get("/fit-runs/{fit_id}/result")
def get_fit_result(fit_id: UUID, store: BackedGradientStore = Depends(get_gradient_store)) -> dict[str, Any]:
    """Return a frozen model and comparison result. / 返回冻结模型及比对结果。

    Args:
        fit_id: Task UUID.（任务UUID。）
        store: Experiment storage.（实验存储。）

    Returns:
        Complete result.（完整结果。）
    """
    return {"result": _perform("fit_result", lambda: read_result(store, str(fit_id)))}


@router.get("/fit-runs/{fit_id}/exports/{format}")
def export_fit_result(fit_id: UUID, format: Literal["json", "csv", "png"],
                      store: BackedGradientStore = Depends(get_gradient_store),
                      registry: FileRegistry = Depends(get_file_registry)) -> FileResponse:
    """Export a TTL copy independent from the persistent fit/session.
    导出有存活期限的副本，独立于持久拟合及会话。

    Args:
        fit_id: Task UUID.（任务UUID。）
        format: JSON, CSV or PNG.（JSON、CSV或PNG。）
        store: Experiment storage.（实验存储。）
        registry: Download copy lifecycle owner.（下载副本生命周期管理者。）

    Returns:
        Downloadable temporary artifact.（可下载临时产物。）
    """
    result = _perform("fit_export", lambda: read_result(store, str(fit_id)))
    if format != "json" and result.get("comparison") is None:
        return _perform("fit_export", lambda: _missing_comparison())
    filename = "result.json" if format == "json" else f"comparison.{format}"
    path = store.results_root / str(fit_id) / filename
    try:
        file_id = registry.register_bytes(f"backed-gradient-export-{fit_id}", path.read_bytes(),
                                          f"lumina-box-backed-gradient-{fit_id}.{format}", ttl_seconds=3600,
                                          purpose="backed_gradient_export")
        resolved = registry.resolve(file_id)
        if resolved is None:
            raise CoreProcessingError("The export copy could not be registered.")
    except OSError as exc:
        return _perform("fit_export", lambda: _export_failed(exc))
    media = {"json": "application/json", "csv": "text/csv; charset=utf-8", "png": "image/png"}[format]
    return FileResponse(resolved[0], filename=resolved[1], media_type=media, headers={"Cache-Control": "no-store"})






def _missing_comparison() -> Any:
    raise CoreValidationError("Complete R/Y/B/W/K data are required for the 1024 comparison.")


def _export_failed(exc: OSError) -> Any:
    raise CoreProcessingError("Could not write the export copy. Check local storage and retry.") from exc
