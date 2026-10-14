"""File-only worker entrypoint for backed-gradient models. / 仅通过文件传参的梯度拟合入口。"""

from __future__ import annotations

import json
import math
from pathlib import Path


def _model_quality_failure(result: dict, selected: str) -> str | None:
    model = result["models"].get(selected, {})
    if model.get("status") != "converged" or model.get("optimizer_converged") is not True:
        return "optimizer_not_converged"
    cv = model.get("cv") or {}
    if cv.get("optimizer_converged") is not True:
        return "cross_validation_not_converged"
    errors = cv.get("per_material_rmse_pp") or {}
    if not errors or any(isinstance(value, bool) or not isinstance(value, (int, float))
                         or not math.isfinite(value) or not 0 <= value <= 2 for value in errors.values()):
        return "cross_validation_above_tolerance"
    if model.get("stability", {}).get("status") != "stable":
        return "prediction_stability_failed"
    if result.get("controls", {}).get("consistent") is not True:
        return "homogeneous_controls_failed"
    return None


def _retain_frozen_family(frozen: dict, result: dict) -> dict:
    recommendation = frozen["recommendation"]
    selected = recommendation.get("model")
    validation = frozen["validation_024"]
    frozen_failure = _model_quality_failure(frozen, selected) if selected else None
    failure_stage, failure_reason = None, None
    if not selected or recommendation.get("status") != "recommended":
        failure_stage, failure_reason = "frozen_six", recommendation.get("reason", "no_frozen_family")
    elif frozen_failure:
        failure_stage, failure_reason = "frozen_six", frozen_failure
    elif (validation.get("passed") is not True or validation.get("complete") is not True
          or validation.get("used_for_training") is not False
          or validation.get("selected_model_before_validation") != selected
          or not validation.get("prediction_hash")):
        failure_stage, failure_reason = "frozen_validation_024", "validation_024_failed"
    else:
        failure_reason = _model_quality_failure(result, selected)
        if failure_reason:
            failure_stage = "full_refit"
    if failure_stage:
        reason = ("full_refit_quality_failed" if failure_stage == "full_refit"
                  else "frozen_validation_024_failed_before_refit")
        return {"model": None, "status": "exploratory", "reason": reason,
                "failure_stage": failure_stage, "failure_reason": failure_reason}
    return {"model": selected, "status": "recommended", "reason": "frozen_family_retained_after_full_refit"}


def fit_backed_gradient_worker(input_path: str, output_directory: str, include_validation_thickness: bool) -> str:
    """Fit a frozen input and write persistent comparison artifacts.
    拟合冻结输入并写出持久比对产物。

    Args:
        input_path: Frozen JSON file.（冻结JSON文件。）
        output_directory: Server-owned fit folder.（服务器持有的拟合目录。）
        include_validation_thickness: Run frozen validation then a seven-point refit.
            （是否先冻结验证，再执行七档重拟合。）

    Returns:
        Complete result path.（完整结果路径。）
    """
    from core.backed_gradient_fitting import fit_backed_gradient
    from core.backed_gradient_comparison import export_comparison

    directory = Path(output_directory)
    snapshot = json.loads(Path(input_path).read_text(encoding="utf-8"))

    def progress(stage: str, fraction: float) -> None:
        temporary = directory / "progress.tmp"
        temporary.write_text(json.dumps({"stage": stage, "progress": float(fraction)}, allow_nan=False), encoding="utf-8")
        temporary.replace(directory / "progress.json")

    progress("fitting", 0.01)
    if snapshot.get("fitting_algorithm_id"):
        from core.backed_gradient_fitting_v2 import (
            BACKED_GRADIENT_ALGORITHM_ID, BACKED_GRADIENT_SMOOTH_ALGORITHM_ID,
            fit_backed_gradient_v2, fit_backed_gradient_v3,
        )

        fitters = {BACKED_GRADIENT_ALGORITHM_ID: fit_backed_gradient_v2,
                   BACKED_GRADIENT_SMOOTH_ALGORITHM_ID: fit_backed_gradient_v3}
        if snapshot["fitting_algorithm_id"] not in fitters or not include_validation_thickness:
            raise ValueError("Unsupported backed-gradient fitting algorithm")
        result = fitters[snapshot["fitting_algorithm_id"]](snapshot, progress=progress)
    elif include_validation_thickness:
        frozen = fit_backed_gradient(snapshot, include_validation_thickness=False,
                                     progress=lambda stage, fraction: progress("validation_" + stage, fraction * .45))
        frozen_path = directory / "frozen-six.json"
        frozen_path.write_text(json.dumps(frozen, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        result = fit_backed_gradient(snapshot, include_validation_thickness=True,
                                     progress=lambda stage, fraction: progress("final_" + stage, .5 + fraction * .49))
        validation = frozen["validation_024"]
        result["frozen_validation_before_refit"] = validation
        result["frozen_six_recommendation"] = frozen["recommendation"]
        result["validation_024"] = validation
        result["full_data_recommendation_before_frozen_gate"] = result["recommendation"]
        result["recommendation"] = _retain_frozen_family(frozen, result)
        result["pipeline"] = {"collected_thicknesses": "all_seven_together", "internal_validation_thickness_mm": .24,
                              "frozen_six_file": "frozen-six.json", "final_fit_includes_all_seven": True}
    else:
        result = fit_backed_gradient(snapshot, include_validation_thickness=False, progress=progress)
    export_comparison(result, directory)
    temporary = directory / "result.tmp"
    temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(directory / "result.json")
    progress("complete", 1.0)
    return str(directory / "result.json")
