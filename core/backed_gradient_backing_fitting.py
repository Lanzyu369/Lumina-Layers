"""Fit one independently captured backing against a known opposite material.
使用已知对侧底材，拟合独立采集的单份背板。
"""
from __future__ import annotations

from copy import deepcopy
import time
from typing import Any, Callable, Mapping

import numpy as np

from core import backed_gradient_material_fitting as material_fitting
from core.backed_gradient_material import BackedGradientComponent, BackedGradientMaterialModel, BackedGradientReference
from core.backed_gradient_smooth import SPECTRAL_SMOOTH_MODEL_ID, SPECTRAL_SMOOTH_OBJECTIVE_ID
from core.backed_gradient_store import THICKNESSES_MM
from core.errors import CoreValidationError
from core.km_xyz import km_relative_xyz_to_srgb_uint8

BACKING_MATERIAL_FIT_ALGORITHM_ID = "backed_gradient_single_backing_fixed_reference/v1"


def _backing_rows(snapshot: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    role = snapshot.get("backing_role") or snapshot.get("role") or snapshot.get("material_symbol")
    if role not in ("W", "K") or snapshot.get("material_symbol", role) != role:
        raise CoreValidationError("Choose whether this material is the white or black backing")
    opposite_role = "K" if role == "W" else "W"
    originals, rows, seen = [], [], set()
    for raw in snapshot.get("samples", []):
        try:
            sample_role = raw.get("sample_role", "coated")
            thickness = float(raw["overlay_mm"])
            observed = np.asarray(raw["reflectance_percent_xyz"], dtype=float)
            backing = raw["backing"]
        except (KeyError, TypeError, ValueError) as error:
            raise CoreValidationError("A backing reading needs its sample, thickness, and XYZ") from error
        if (observed.shape != (3,) or not np.isfinite(observed).all() or np.any(observed < 0)
                or raw.get("material_symbol", role) != role):
            raise CoreValidationError("Backing XYZ must contain three finite nonnegative readings")
        if sample_role == "bare_backing" and thickness == 0. and backing == role:
            canonical = 3.
        elif sample_role == "coated" and backing == opposite_role:
            canonical = next((value for value in THICKNESSES_MM if abs(value - thickness) < 1e-6), None)
        else:
            canonical = None
        if canonical is None or canonical in seen:
            raise CoreValidationError("Measure this backing once at each thickness on its actual opposite material")
        seen.add(canonical)
        originals.append(deepcopy(raw))
        # The device's bare capture uses overlay zero; the optical object is a
        # homogeneous three-mm slab. Keep the original record unchanged.
        rows.append({**deepcopy(raw), "overlay_mm": canonical, "reflectance_percent_xyz": observed.tolist()})
    if seen != {*THICKNESSES_MM, 3.}:
        raise CoreValidationError("Complete this backing's seven thicknesses and its bare three-mm sample")
    return role, rows, originals


def fit_backed_gradient_backing_material(snapshot: Mapping[str, Any], *,
                                        progress: Callable[[str, float], None] | None = None,
                                        time_budget_seconds: float = 180.) -> dict[str, Any]:
    """Fit one backing without changing the shared observation calibration.
    拟合单份背板，保持共同观测标定不变。

    Args:
        snapshot: Eight selected samples, identity, observation reference, and the
            actual opposite component.（八条选用样本、身份、观测参考及实际对侧组件。）
        progress: Worker progress callback.（工作进度回调。）
        time_budget_seconds: Worker time allowance.（任务时限。）
    Returns:
        Independent component, unchanged reference, raw capture history, predictions,
        and seven thickness holdouts.（独立组件、原参考、原始采集历史、预测与七档留出结果。）
    """
    if not np.isfinite(time_budget_seconds) or time_budget_seconds <= 0:
        raise CoreValidationError("Fitting time allowance must be positive")
    role, rows, originals = _backing_rows(snapshot)
    try:
        reference = BackedGradientReference.from_dict(snapshot["reference"])
        opposite = BackedGradientComponent.from_dict(snapshot["opposite_component"])
    except (KeyError, TypeError) as error:
        raise CoreValidationError("Choose a calibrated opposite backing before fitting this material") from error
    opposite_role = "K" if role == "W" else "W"
    backings = {"W": reference.white, "K": reference.black, opposite_role: opposite}
    model = BackedGradientMaterialModel(reference, backings)
    deadline = time.monotonic() + time_budget_seconds
    callback = progress or (lambda _stage, _fraction: None)
    callback("fitting", .03)
    component, converged, attempts = material_fitting._fit_component(model, "color", "material", rows, deadline)
    predicted = material_fitting._predict(model, component, rows)
    folds, held_predictions, held_rows = [], [], []
    for index, thickness in enumerate(THICKNESSES_MM):
        callback("checking", .2 + .7 * index / len(THICKNESSES_MM))
        training = [row for row in rows if row["overlay_mm"] != thickness]
        held = [row for row in rows if row["overlay_mm"] == thickness]
        folded, fold_converged, _attempts = material_fitting._fit_component(
            model, "color", "material", training, deadline)
        forecast = material_fitting._predict(model, folded, held)
        folds.append({"held_overlay_mm": thickness, "converged": fold_converged,
                      "training_record_ids": [row.get("record_id") for row in training],
                      "held_record_ids": [row.get("record_id") for row in held],
                      "predicted_percent_xyz": forecast.tolist(), **material_fitting._summary(held, forecast)})
        held_rows.extend(held)
        held_predictions.extend(forecast)
    estimate = model.predict_backed(component, role, 3.)
    callback("complete", 1.)
    return {
        "schema_version": "1.0", "kind": "lumina_box_backed_gradient_material_fit",
        **material_fitting._source(snapshot), "material_kind": "color", "material_symbol": role, "backing_role": role,
        "optical_model_id": SPECTRAL_SMOOTH_MODEL_ID, "algorithm_id": BACKING_MATERIAL_FIT_ALGORITHM_ID,
        "objective_id": SPECTRAL_SMOOTH_OBJECTIVE_ID, "component": component.to_dict(), "reference": reference.to_dict(),
        "opposite_component": opposite.to_dict(),
        "status": "complete" if converged else "not_converged", "converged": converged, "attempts": attempts,
        "estimated_rgb": km_relative_xyz_to_srgb_uint8(estimate / 100.).tolist(),
        "estimated_xyz": (estimate / 100.).tolist(), **material_fitting._summary(rows, predicted),
        "capture_history": deepcopy(snapshot.get("capture_history", originals)),
        "sample_predictions": [
            {"record_id": raw.get("record_id"), "sample_role": raw.get("sample_role", "coated"),
             "backing": raw["backing"], "overlay_mm": raw["overlay_mm"],
             "measured_percent_xyz": raw["reflectance_percent_xyz"], "predicted_percent_xyz": value.tolist()}
            for raw, value in zip(originals, predicted, strict=True)
        ],
        "cv": {"reference_fixed": True, "opposite_component_fixed": True, "whole_thickness_paired": False,
               "converged": all(fold["converged"] for fold in folds),
               "folds": folds, **material_fitting._summary(held_rows, np.asarray(held_predictions))},
    }
