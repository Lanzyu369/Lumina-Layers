"""File-based single-material and backing calibration jobs.
通过文件执行单耗材拟合与背板标定。
"""

from __future__ import annotations

import json
from pathlib import Path


def fit_backed_gradient_product_worker(input_path: str, output_directory: str, fit_mode: str) -> str:
    """Fit the chosen material or shared backing without research comparisons.
    拟合所选材料或共享背板，不运行研究对照任务。

    Args:
        input_path: Frozen server-owned input.（服务器冻结输入。）
        output_directory: Persistent result directory.（持久结果目录。）
        fit_mode: Material, independent backing, or initial calibration.（耗材、独立背板或初次标定。）

    Returns:
        Saved result path.（已存结果路径。）
    """
    from core.backed_gradient_material import BackedGradientReference
    from core.backed_gradient_material_fitting import (
        fit_backed_gradient_material, fit_backed_gradient_reference, fit_backed_gradient_material_group,
    )

    snapshot = json.loads(Path(input_path).read_text(encoding="utf-8"))
    directory = Path(output_directory)

    def progress(stage: str, fraction: float) -> None:
        temporary = directory / "progress.tmp"
        temporary.write_text(json.dumps({"stage": stage, "progress": fraction}), encoding="utf-8")
        temporary.replace(directory / "progress.json")

    if fit_mode == "material":
        result = fit_backed_gradient_material(snapshot, BackedGradientReference.from_dict(snapshot["reference"]),
                                             progress=progress, time_budget_seconds=180.)
    elif fit_mode == "material_group":
        group = fit_backed_gradient_material_group(snapshot["group"], progress=progress, time_budget_seconds=720.)
        key = f"{snapshot['dataset_id']}:{snapshot['material_symbol']}"
        result = dict(group["material_fits"][key])
        result.update(group_fits=group["material_fits"], group_input_hash=group["input_hash"])
    elif fit_mode == "backing_reference":
        result = fit_backed_gradient_reference(snapshot, progress=progress, time_budget_seconds=300.)
    elif fit_mode == "backing_material":
        from core.backed_gradient_backing_fitting import fit_backed_gradient_backing_material

        result = fit_backed_gradient_backing_material(snapshot, progress=progress, time_budget_seconds=300.)
    elif fit_mode == "backing_material_bootstrap":
        result = _fit_initial_independent_backings(snapshot, progress)
    else:
        raise ValueError("Unsupported backed-gradient product job")
    result.update({key: snapshot[key] for key in ("dataset_id", "dataset_revision", "input_hash")})
    result["fit_mode"] = ("material" if fit_mode == "material_group" else
                          "backing_material" if fit_mode == "backing_material_bootstrap" else fit_mode)
    result.update({key: snapshot[key] for key in ("capture_reference_id", "backing_id") if key in snapshot})
    temporary = directory / "result.tmp"
    temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(directory / "result.json")
    progress("complete", 1.)
    return str(directory / "result.json")


def _fit_initial_independent_backings(snapshot: dict, progress) -> dict:
    from copy import deepcopy

    from core.backed_gradient_material_fitting import fit_backed_gradient_reference
    from core.backed_gradient_store import _digest
    from core.km_xyz import km_relative_xyz_to_srgb_uint8
    import numpy as np

    peer = snapshot["opposite"]["snapshot"]
    materials = {snapshot["role"]: snapshot, peer["role"]: peer}
    merged = {
        "dataset_id": snapshot["dataset_id"], "dataset_revision": snapshot["dataset_revision"],
        "name": snapshot["name"], "conditions": snapshot["conditions"],
        "materials": {role: item["name"] for role, item in materials.items()},
        "reference_anchors": {role: item["bare_xyz"] for role, item in materials.items()},
        "samples": [row for item in materials.values() for row in item["samples"] if row["sample_role"] == "coated"],
        "capture_history": [row for item in materials.values() for row in item["capture_history"]],
        "selected_record_ids": sorted(identity for item in materials.values() for identity in item["selected_record_ids"]),
    }
    merged["input_hash"] = _digest(merged)
    fitted = fit_backed_gradient_reference(merged, progress=progress, time_budget_seconds=300.)
    reference = fitted["reference"]
    reference["source"].update(independent_backings=True,
                               backing_material_ids={role: item["material_id"] for role, item in materials.items()})
    reference["reference_id"] = _digest({key: value for key, value in reference.items() if key != "reference_id"})

    def own_result(item: dict) -> dict:
        xyz = np.asarray(item["bare_xyz"]) / 100.
        return {"schema_version": "1.0", "kind": "lumina_box_backed_gradient_backing_fit",
                **{key: item[key] for key in ("dataset_id", "dataset_revision", "input_hash", "selected_record_ids")},
                "status": fitted["status"], "converged": fitted["converged"],
                "component": deepcopy(reference["white" if item["role"] == "W" else "black"]),
                "reference": deepcopy(reference), "estimated_xyz": xyz.tolist(),
                "estimated_rgb": km_relative_xyz_to_srgb_uint8(xyz).tolist(),
                "rmse_pp": fitted["rmse_pp"], "cv": deepcopy(fitted["cv"]), "initial_calibration": True}

    result = own_result(snapshot)
    result["bootstrap_peer"] = own_result(peer)
    return result
