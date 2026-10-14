"""Fit and publish independently captured backing materials.
拟合并发布独立采集的背板耗材。
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path

from api.worker_pool import WorkerPoolManager
from api.workers.backed_gradient_material_workers import fit_backed_gradient_product_worker
from core.black_white_material_profiles import publish_black_white_profiles
from core.backed_gradient_store import BackedGradientStore
from core.errors import CoreProcessingError


async def execute_backing_material_fit(store: BackedGradientStore, pool: WorkerPoolManager,
                                       run: dict, directory: Path) -> None:
    """Save one completed capture, fitting it when its physical reference is known.
    单独保存完整采集，并在实体参考可用时拟合。

    Args:
        store: Independent capture storage.（独立采集存储。）
        pool: Managed calculation workers.（受管理计算进程。）
        run: Current fit identity.（当前拟合身份。）
        directory: Frozen inputs and outputs.（冻结输入及输出目录。）
    """
    snapshot = json.loads((directory / "input.json").read_text(encoding="utf-8"))
    mode = "backing_material"
    if "reference" not in snapshot:
        opposite = snapshot.get("opposite", {}).get("snapshot", {})
        paired = (opposite.get("opposite_material_id") == snapshot["material_id"]
                  and len(opposite.get("samples", [])) == 8 and opposite.get("bare_xyz") is not None)
        if not paired:
            result = {key: deepcopy(snapshot[key]) for key in
                      ("dataset_id", "dataset_revision", "input_hash", "selected_record_ids")}
            result.update(status="awaiting_opposite", fit_mode="backing_material",
                          backing_material_id=snapshot["material_id"], opposite_material_id=snapshot["opposite_material_id"],
                          opposite_name=snapshot["opposite"]["name"])
            (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            return
        mode = "backing_material_bootstrap"
    await asyncio.wait_for(pool.submit(fit_backed_gradient_product_worker, str(directory / "input.json"),
                                       str(directory), mode), timeout=360.)


def publish_backing_material_fit(store: BackedGradientStore, run: dict, directory: Path, result: dict) -> None:
    """Publish each backing under its own identity, retaining the input versions.
    分别按独立身份发布背板，保留各自输入版本。

    Args:
        store: Independent capture storage.（独立采集存储。）
        run: Current fit identity.（当前拟合身份。）
        directory: Frozen input location.（冻结输入位置。）
        result: Validated worker output.（已校验计算结果。）
    """
    snapshot = json.loads((directory / "input.json").read_text(encoding="utf-8"))
    if result.get("converged") is False:
        raise CoreProcessingError("Backing fitting did not converge. The captured readings remain saved.")
    peer = result.pop("bootstrap_peer", None)
    entries = [(snapshot["opposite"]["snapshot"], peer)] if peer else []
    entries.append((snapshot, None if result["status"] == "awaiting_opposite" else result))
    for member, fitted in entries:
        if fitted is not None and (fitted.get("converged") is False or any(
                fitted.get(key) != member[key] for key in ("dataset_id", "dataset_revision", "input_hash"))):
            raise CoreProcessingError("A backing fit does not match its own frozen measurements.")
    if peer and peer.get("reference") != result.get("reference"):
        raise CoreProcessingError("Initial backing fits must share the same observation calibration.")
    saved = publish_black_white_profiles(store, entries)[-1]
    result.update(backing_material_id=saved["material_id"], backing_version_id=saved["version_id"])
    run["backing_material_id"] = saved["material_id"]
    if saved.get("reference_id"):
        result["reference_id"] = saved["reference_id"]
        run["fitted_reference_id"] = saved["reference_id"]
    (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
