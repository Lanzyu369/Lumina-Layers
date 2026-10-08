"""Managed backed-gradient fit jobs. / 受管理的黑白底梯度拟合任务。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from api.structured_logging import get_logger
from api.worker_pool import WorkerPoolManager
from core.backed_gradient_store import (
    BackedGradientConflictError, BackedGradientStore, _uuid,
)
from core.errors import CoreError, CoreProcessingError, CoreValidationError


log = get_logger(__name__)
_tasks: dict[str, asyncio.Task[None]] = {}
_backing_tasks: dict[str, str] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()






async def _execute(store: BackedGradientStore, pool: WorkerPoolManager, run: dict[str, Any], directory: Path) -> None:
    run.update(status="running", stage="fitting", progress=.01, updated_at=_now())
    try:
        store.save_run(run)
        if run["fit_mode"] == "backing_material":
            from api.backed_gradient_independent_jobs import execute_backing_material_fit

            await execute_backing_material_fit(store, pool, run, directory)
        elif run["fit_mode"] in ("material", "backing_reference"):
            from api.backed_gradient_product_jobs import execute_product_fit

            await execute_product_fit(store, pool, run, directory)
        else:
            raise CoreValidationError("Unsupported backed-gradient production fit mode.")
        if not (directory / "result.json").is_file():
            raise CoreProcessingError("The fit worker did not produce a complete result.")
        result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
        if result.get("input_hash") != run["input_hash"] or result.get("dataset_id") != run["dataset_id"]:
            raise CoreProcessingError("The fit worker result does not match its frozen experiment.")
        if run.get("fitting_algorithm_id") and result.get("algorithm_id") != run["fitting_algorithm_id"]:
            raise CoreProcessingError("The fit worker result does not match the requested model version.")
        if run["fit_mode"] in ("material", "backing_reference") and result.get("converged") is False:
            raise CoreProcessingError("Fitting did not converge. Check the saved readings and generate again.")
        if run["fit_mode"] == "backing_material":
            from api.backed_gradient_independent_jobs import publish_backing_material_fit

            publish_backing_material_fit(store, run, directory, result)
        elif run["fit_mode"] == "backing_reference":
            from core.backed_gradient_product_store import save_backing_reference

            reference = save_backing_reference(store, result["reference"], run["name"])
            run["reference_id"] = reference["reference_id"]
        elif run["fit_mode"] == "material":
            from api.backed_gradient_product_jobs import publish_group_materials

            publication = asyncio.create_task(asyncio.to_thread(publish_group_materials, store, run, directory, result))
            try:
                await asyncio.shield(publication)
            except asyncio.CancelledError:
                # A directory/database publication must finish or roll back before shutdown.
                await publication
                raise
        run.update(status="complete", stage="complete", progress=1., updated_at=_now())
        store.save_run(run)
        log.info("Backed-gradient fit completed", extra={"event": "backed_gradient_fit_done", "fit_id": run["fit_id"],
                                                         "dataset_id": run["dataset_id"], "input_hash": run["input_hash"]})
    except asyncio.CancelledError:
        if run["status"] != "complete":
            run.update(status="failed", stage="interrupted", error="Fitting was interrupted. The original data remain saved.", updated_at=_now())
            store.save_run(run)
        raise
    except (CoreError, RuntimeError, ValueError, TypeError, OSError, ImportError, LookupError, ArithmeticError) as exc:
        # The job boundary persists domain, worker, numeric and storage failures.
        message = "Fitting timed out. The original data remain saved." if isinstance(exc, asyncio.TimeoutError) else str(exc)
        run.update(status="failed", stage="failed", error=message, updated_at=_now())
        store.save_run(run)
        log.warning("Backed-gradient fit failed", extra={"event": "backed_gradient_fit_failed", "fit_id": run["fit_id"],
                                                        "error_type": type(exc).__name__, "error_message": message})




def start_material_fit(store: BackedGradientStore, pool: WorkerPoolManager, dataset_id: str,
                       *, material_symbol: str | None = None, reference_id: str | None = None) -> dict:
    """Queue one independently captured material. / 提交独立采集耗材的拟合。

    Args:
        store: Capture storage.（采集存储。）
        pool: CPU workers.（计算进程池。）
        dataset_id: Capture identity.（采集身份。）
        material_symbol: Selection in an earlier multi-material capture.（历史采集的材料选择。）
        reference_id: Saved backing reference.（已存背板标定。）

    Returns:
        Persistent job state.（持久任务状态。）
    """
    from core.backed_gradient_product_store import material_snapshot

    snapshot = material_snapshot(store, dataset_id, material_symbol=material_symbol, reference_id=reference_id)
    return _queue_fit(store, pool, snapshot, "material", {
        "material_symbol": snapshot["material_symbol"], "reference_id": snapshot["capture_reference_id"],
        "capture_reference_id": snapshot["capture_reference_id"], "backing_id": snapshot["backing_id"],
        "fitted_reference_id": snapshot["reference_id"],
        "name": snapshot["name"],
    })


def start_backing_fit(store: BackedGradientStore, pool: WorkerPoolManager, dataset_id: str) -> dict:
    """Queue a shared black/white backing calibration. / 提交共享黑白背板标定。

    Args:
        store: Capture storage.（采集存储。）
        pool: CPU workers.（计算进程池。）
        dataset_id: Backing capture identity.（背板采集身份。）

    Returns:
        Persistent job state.（持久任务状态。）
    """
    from core.backed_gradient_product_store import backing_snapshot

    snapshot = backing_snapshot(store, dataset_id)
    return _queue_fit(store, pool, snapshot, "backing_reference", {"name": snapshot["name"], "backing_id": dataset_id})


def start_backing_material_fit(store: BackedGradientStore, pool: WorkerPoolManager, dataset_id: str) -> dict:
    """Queue one backing independently. / 独立提交一个背板的保存与拟合。

    Args:
        store: Capture storage.（采集存储。）
        pool: Calculation workers.（计算进程。）
        dataset_id: This backing's capture identity.（本背板采集身份。）
    Returns:
        Persistent job.（持久任务。）
    """
    from core.backed_gradient_backing_store import backing_material_snapshot

    snapshot = backing_material_snapshot(store, dataset_id)
    pair_key = ":".join(sorted((snapshot["material_id"], snapshot["opposite_material_id"])))
    return _queue_fit(store, pool, snapshot, "backing_material", {
        "name": snapshot["name"], "backing_material_id": snapshot["material_id"], "backing_id": pair_key,
    })


def _queue_fit(store: BackedGradientStore, pool: WorkerPoolManager, snapshot: dict,
               fit_mode: str, metadata: dict) -> dict:
    backing_id = metadata.get("backing_id")
    if backing_id and _backing_tasks.get(backing_id) in _tasks:
        raise BackedGradientConflictError("These materials share a backing calibration that is being updated. Wait for the current result.")
    history = store.list_runs(snapshot["dataset_id"])
    if any(run["status"] in ("queued", "running") and run["fit_id"] in _tasks for run in history):
        raise BackedGradientConflictError("An experiment fit is already running. Wait for its result.")
    stamp, identity = _now(), str(uuid4())
    run = {"fit_id": identity, "dataset_id": snapshot["dataset_id"], "dataset_revision": snapshot["dataset_revision"],
           "input_hash": snapshot["input_hash"], "fit_mode": fit_mode, "status": "queued",
           "progress": 0., "stage": "queued", "error": None, "created_at": stamp, "updated_at": stamp,
           **metadata}
    directory = store.results_root / identity
    try:
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "input.json").write_text(json.dumps(snapshot, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        store.save_run(run)
    except OSError as exc:
        raise CoreProcessingError("Could not prepare fit storage. Check local storage and retry.") from exc
    task = asyncio.create_task(_execute(store, pool, dict(run), directory))
    _tasks[identity] = task
    if backing_id:
        _backing_tasks[backing_id] = identity

    def finished(_task: asyncio.Task) -> None:
        _tasks.pop(identity, None)
        if backing_id and _backing_tasks.get(backing_id) == identity:
            _backing_tasks.pop(backing_id, None)

    task.add_done_callback(finished)
    return run


def read_run(store: BackedGradientStore, fit_id: str) -> dict[str, Any]:
    """Refresh progress or identify a job interrupted by backend restart.
    刷新进度，或识别后端重启中断的任务。

    Args:
        store: Experiment store.（实验库。）
        fit_id: Task UUID.（任务UUID。）

    Returns:
        Current persisted task state.（当前持久任务状态。）
    """
    run = store.get_run(fit_id)
    if run["status"] not in ("queued", "running"):
        return run
    if fit_id not in _tasks:
        run.update(status="failed", stage="interrupted", error="Backend restarted during fitting. Start a new fit; readings remain saved.", updated_at=_now())
    else:
        path = store.results_root / _uuid(fit_id) / "progress.json"
        try:
            progress = json.loads(path.read_text(encoding="utf-8"))
            fraction = float(progress["progress"])
            if not 0 <= fraction <= 1:
                raise ValueError("Invalid progress")
            run.update(progress=fraction, stage=str(progress["stage"]), updated_at=_now())
        except (OSError, ValueError, KeyError, TypeError):
            return run
    store.save_run(run)
    return store.get_run(fit_id)


def read_result(store: BackedGradientStore, fit_id: str) -> dict[str, Any]:
    """Read a frozen result independent of UI/source session lifetime.
    读取冻结结果，不依赖界面或源会话生命周期。

    Args:
        store: Independent result store.（独立结果库。）
        fit_id: Task UUID.（任务UUID。）

    Returns:
        Complete model result.（完整模型结果。）
    """
    run = read_run(store, fit_id)
    if run["status"] != "complete":
        raise BackedGradientConflictError("This fit has not completed successfully.")
    try:
        result = json.loads((store.results_root / _uuid(fit_id) / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CoreProcessingError("The saved fit result is unavailable. The original readings remain saved.") from exc
    if result.get("input_hash") != run["input_hash"]:
        raise CoreProcessingError("The saved result does not match its frozen input.")
    return result






async def cancel_backed_gradient_jobs() -> None:
    """Cancel detached job owners before stopping the process pool.
    停止进程池前取消独立任务持有者。
    """
    tasks = list(_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
