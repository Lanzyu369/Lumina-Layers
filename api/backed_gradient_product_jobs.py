"""Coordinate independent material jobs and shared backing updates.
协调独立耗材任务及共享背板更新。
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
from uuid import uuid4

from api.worker_pool import WorkerPoolManager
from api.workers.backed_gradient_material_workers import fit_backed_gradient_product_worker
from core.backed_gradient_product_store import (
    _save_backing_reference, backing_group_id, get_backing_reference, material_group_snapshot, uses_reference_backings,
)
from core.backed_gradient_store import BackedGradientStore, _json
from core.errors import CoreError, CoreProcessingError, CoreValidationError

FIXED_REFERENCE_MAX_RMSE_PP = 2.0


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _prepare_group(store: BackedGradientStore, snapshot: dict, directory: Path) -> None:
    group, members = material_group_snapshot(store, snapshot)
    if group is None:
        raise CoreValidationError("The saved black/white backing readings are unavailable. Import the original backing measurements and try again.")
    snapshot["group"] = group
    snapshot["group_material_snapshots"] = deepcopy(members)
    _write_json(directory / "input.json", snapshot)


async def execute_product_fit(store: BackedGradientStore, pool: WorkerPoolManager,
                              run: dict, directory: Path) -> dict:
    """Keep established references fast and refine bootstrap/incompatible groups.
    优先快速复用已建立参考，联合完善初建或不兼容的背板组。

    Args:
        store: Durable capture store.（持久采集库。）
        pool: Managed CPU workers.（受管理计算进程池。）
        run: Material/backing job identity.（耗材或背板任务身份。）
        directory: Frozen inputs and result files.（冻结输入及结果目录。）
    Returns:
        Standard material or backing result.（标准单材或背板结果。）
    """
    snapshot = json.loads((directory / "input.json").read_text(encoding="utf-8"))
    mode = run["fit_mode"]
    can_refine = uses_reference_backings(snapshot)
    if mode == "material" and can_refine and (snapshot["reference"].get("source", {}).get("established") is False or snapshot.get("backing_role")):
        _prepare_group(store, snapshot, directory)
        mode = "material_group"

    async def submit(selected_mode: str) -> dict:
        timeout = 780. if selected_mode == "material_group" else 360. if selected_mode == "backing_reference" else 240.
        await asyncio.wait_for(pool.submit(fit_backed_gradient_product_worker, str(directory / "input.json"),
                                           str(directory), selected_mode), timeout=timeout)
        if not (directory / "result.json").is_file():
            raise CoreProcessingError("The fit worker did not produce a complete result.")
        return json.loads((directory / "result.json").read_text(encoding="utf-8"))

    result = await submit(mode)
    if mode == "material" and can_refine and (result.get("converged") is False or float(result.get("rmse_pp", 0.)) > FIXED_REFERENCE_MAX_RMSE_PP):
        previous_rmse = result.get("rmse_pp")
        _prepare_group(store, snapshot, directory)
        result = await submit("material_group")
        result["fixed_reference_rmse_pp"] = previous_rmse
        _write_json(directory / "result.json", result)
    return result


def publish_group_materials(store: BackedGradientStore, run: dict, directory: Path, result: dict) -> None:
    """Save related results and refresh only already-saved materials in this group.
    保存相关结果，仅更新该背板组中已保存的耗材。

    Args:
        store: Durable capture store.（持久采集库。）
        run: Requested material job.（当前耗材任务。）
        directory: Frozen group input directory.（冻结组输入目录。）
        result: Completed shared fit with independent material results.（已完成组拟合及独立单材结果。）
    """
    from core.lumina_box_archive import _ARCHIVE_WRITE_LOCK
    from core.single_stage import invalidate_material_library_cache

    fits = result.get("group_fits")
    if not isinstance(fits, dict):
        run["fitted_reference_id"] = result["reference"]["reference_id"]
        return
    snapshot = json.loads((directory / "input.json").read_text(encoding="utf-8"))
    if result.get("group_input_hash") != snapshot["group"]["input_hash"]:
        raise CoreProcessingError("The shared fit does not match its frozen material inputs.")
    group_id = run["backing_id"]
    members = {f"{item['dataset_id']}:{item['material_symbol']}": item for item in snapshot["group_material_snapshots"]}
    if set(fits) != set(members) or any(fit.get("converged") is False for fit in fits.values()):
        raise CoreProcessingError("The shared fit did not complete for every material.")
    if backing_group_id(result["reference"]) != group_id:
        raise CoreProcessingError("The shared fit belongs to a different backing group.")
    for key, fit in fits.items():
        member = members[key]
        if fit.get("input_hash") != member["input_hash"] or fit["reference"]["reference_id"] != result["reference"]["reference_id"]:
            raise CoreProcessingError("A material result does not match the shared fit inputs.")
        fit.update(capture_reference_id=member["capture_reference_id"], backing_id=group_id, fit_mode="material")

    original = get_backing_reference(store, run["capture_reference_id"])
    backing_documents = _refined_backing_documents(store, snapshot, result["reference"], run["fit_id"])
    if backing_documents:
        from core.backed_gradient_backing_transfer import collect_backing_documents

        versions = {item["role"]: item["version_id"] for item in backing_documents}
        components = {item["role"]: deepcopy(item["component"]) for item in backing_documents}
        for key, fit in fits.items():
            if members[key].get("backing_components"):
                fit.update(backing_material_ids=deepcopy(members[key]["backing_material_ids"]),
                           capture_backing_material_versions=deepcopy(members[key].get("capture_backing_material_versions")
                                                                      or members[key]["backing_material_versions"]),
                           backing_material_versions=deepcopy(versions), backing_components=deepcopy(components))
                fit["backing_documents"] = collect_backing_documents(
                    store, [members[key], {**fit, "backing_documents": backing_documents}])
        own_key = f"{run['dataset_id']}:{run['material_symbol']}"
        result.update({key: deepcopy(fits[own_key][key]) for key in (
            "backing_material_ids", "capture_backing_material_versions", "backing_material_versions", "backing_components", "backing_documents")
            if key in fits[own_key]})
    with _ARCHIVE_WRITE_LOCK, TemporaryDirectory(prefix=".publication-", dir=directory) as temporary:
        staging = Path(temporary)
        candidates = _stage_group_archives(store, staging, group_id, members, fits, backing_documents)
        sibling_runs = _stage_group_runs(store, staging, run, members, fits, result["reference"]["reference_id"])
        updated_archives = [relative.as_posix() for relative in candidates]
        result.update(updated_materials=updated_archives)
        _write_json(directory / "result.json", result)
        _publish_group(store, staging, candidates, sibling_runs, run, result["reference"], original["name"],
                       updated_archives, backing_documents,
                       {identity: snapshot["backing_material_versions"][role]
                        for role, identity in snapshot.get("backing_material_ids", {}).items()})
    invalidate_material_library_cache(str(store.root))


def _refined_backing_documents(store: BackedGradientStore, snapshot: dict, reference: dict, fit_id: str) -> list[dict]:
    if not snapshot.get("backing_components"):
        return []
    from core.backed_gradient_backing_store import _prepare_backing_material_result, get_backing_material

    if (not uses_reference_backings(snapshot)
            or reference.get("source", {}).get("backing_material_ids") != snapshot["backing_material_ids"]):
        raise CoreProcessingError("The joint fit does not use the captured initial backing materials.")
    documents = []
    for role, identity in snapshot["backing_material_ids"].items():
        previous = get_backing_material(store, identity, version_id=snapshot["backing_material_versions"][role])
        own_result = {"component": deepcopy(reference["white" if role == "W" else "black"]),
                      "reference": deepcopy(reference), "converged": True, "initial_calibration": False,
                      "group_fit_id": fit_id}
        documents.append(_prepare_backing_material_result(store, previous["snapshot"], own_result))
    return documents


def _stage_group_archives(store: BackedGradientStore, staging: Path, group_id: str,
                          members: dict, fits: dict, backing_documents: list[dict] | None = None) -> list[Path]:
    from core.backed_gradient_archive import load_backed_gradient_archive, save_backed_gradient_material_archive
    from core.backed_gradient_smooth import SPECTRAL_SMOOTH_MODEL_ID

    candidates = []
    for path in list(store.root.rglob("material.json")):
        if any(part.startswith(".") for part in path.relative_to(store.root).parts):
            continue
        main = json.loads(path.read_text(encoding="utf-8"))
        if main.get("optical_model") != SPECTRAL_SMOOTH_MODEL_ID:
            continue
        _, measurements, previous = load_backed_gradient_archive(path.parent, main)
        if backing_group_id(previous["reference"]) != group_id:
            continue
        key = f"{previous['dataset_id']}:{previous['material_symbol']}"
        backing = next((item for item in backing_documents or [] if item["material_id"] == main.get("backing_material_id")), None)
        if backing:
            member = {**deepcopy(backing["snapshot"]), "backing_material_id": backing["material_id"],
                      "material_symbol": backing["role"], "backing_documents": deepcopy(backing_documents)}
            fitted = {**deepcopy(backing["fit"]), "optical_model_id": SPECTRAL_SMOOTH_MODEL_ID,
                      "material_symbol": backing["role"], "status": "complete",
                      **{field: member[field] for field in ("dataset_id", "dataset_revision", "input_hash")}}
        elif key not in fits:
            if main.get("backing_material_id"):
                continue
            if not uses_reference_backings(measurements):
                continue
            raise CoreProcessingError("A saved material is missing from its backing group's fitted inputs.")
        else:
            member, fitted = members[key], fits[key]
        relative = path.parent.relative_to(store.root)
        shutil.copytree(path.parent, staging / "materials" / relative)
        saved = save_backed_gradient_material_archive(
            material_name=main["material_name"], brand=main.get("brand"), material_type=main.get("material_type"),
            notes=main.get("notes"), measurement_payload=member, fit_payload=fitted,
            overwrite=True, materials_dir=str(staging / "materials"),
        )
        updated = json.loads(Path(saved.archive_path).read_text(encoding="utf-8"))
        extras = {name: value for name, value in main.items() if name not in updated}
        if extras:
            _write_json(Path(saved.archive_path), {**extras, **updated})
        candidates.append(relative)
    return candidates


def _stage_group_runs(store: BackedGradientStore, staging: Path, run: dict, members: dict,
                     fits: dict, reference_id: str) -> list[dict]:
    runs = []
    available_datasets = {item["dataset_id"] for item in store.list()}
    now = datetime.now(timezone.utc).isoformat()
    for key, fit in fits.items():
        member = members[key]
        if key == f"{run['dataset_id']}:{run['material_symbol']}" or member["dataset_id"] not in available_datasets:
            continue
        identity = str(uuid4())
        target = staging / "runs" / identity
        target.mkdir(parents=True, exist_ok=False)
        _write_json(target / "input.json", member)
        _write_json(target / "result.json", fit)
        runs.append({"fit_id": identity, "dataset_id": member["dataset_id"],
                        "dataset_revision": member["dataset_revision"], "input_hash": member["input_hash"],
                        "fit_mode": "material", "material_symbol": member["material_symbol"], "name": member["name"],
                        "reference_id": member["capture_reference_id"], "capture_reference_id": member["capture_reference_id"],
                        "fitted_reference_id": reference_id, "backing_id": run["backing_id"],
                        "status": "complete", "stage": "complete", "progress": 1., "error": None,
                        "created_at": now, "updated_at": now, "group_fit_id": run["fit_id"]})
    return runs


def _publish_group(store: BackedGradientStore, staging: Path, candidates: list[Path],
                   sibling_runs: list[dict], run: dict, reference: dict, name: str,
                   updated_archives: list[str], backing_documents: list[dict],
                   expected_backing_versions: dict[str, str]) -> None:
    from core.backed_gradient_backing_store import _write_backing_material_results

    swapped: list[Path] = []
    published_runs: list[Path] = []
    try:
        with store._connection(write=True) as connection:
            saved_reference = _save_backing_reference(connection, reference, name)
            _write_backing_material_results(connection, backing_documents,
                                            expected_current_versions=expected_backing_versions)
            for relative in candidates:
                target, backup = store.root / relative, staging / "originals" / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
                swapped.append(relative)
                os.replace(staging / "materials" / relative, target)
            for sibling in sibling_runs:
                target = store.results_root / sibling["fit_id"]
                os.replace(staging / "runs" / sibling["fit_id"], target)
                published_runs.append(target)
                connection.execute("INSERT INTO gradient_fit_runs VALUES (?,?,?)",
                                   (sibling["fit_id"], sibling["dataset_id"], _json(sibling)))
            run.update(fitted_reference_id=saved_reference["reference_id"], updated_materials=updated_archives,
                       status="complete", stage="complete", progress=1., updated_at=datetime.now(timezone.utc).isoformat())
            connection.execute("INSERT OR REPLACE INTO gradient_fit_runs VALUES (?,?,?)",
                               (run["fit_id"], run["dataset_id"], _json(run)))
    except (CoreError, OSError, ValueError, TypeError, sqlite3.Error):
        # Roll back this group if any archive swap or database commit fails.
        for relative in reversed(swapped):
            target, backup = store.root / relative, staging / "originals" / relative
            if target.exists():
                shutil.rmtree(target)
            os.replace(backup, target)
        for target in published_runs:
            shutil.rmtree(target)
        raise
