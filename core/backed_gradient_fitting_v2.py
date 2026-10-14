"""Fit narrow-band propagation and hold out complete paired thicknesses.
拟合窄波段传播，并将同一厚度的黑白底样本成组留出。
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import time
from typing import Callable, Sequence

import numpy as np
from scipy.optimize import least_squares

from core import backed_gradient_fitting as shared
from core.backed_gradient_comparison import BLIND_RECIPES, build_comparison, prediction_envelope
from core.backed_gradient_models import BackedGradientModel
from core.backed_gradient_optics import CORE_MATERIAL_SYMBOLS
from core.backed_gradient_smooth import (
    BackedGradientSmoothTransport,
    SPECTRAL_SMOOTH_OBJECTIVE_ID,
)
from core.backed_gradient_transport import BackedGradientTransport
from core.errors import CoreValidationError

BACKED_GRADIENT_ALGORITHM_ID = "backed_gradient_narrow_band_pair_holdout/v2"
BACKED_GRADIENT_SMOOTH_ALGORITHM_ID = "backed_gradient_smooth_spectral_pair_holdout/v3"
FULL_STARTS = 2
CV_STARTS = 2
MAX_EVALUATIONS = 350
NEAR_EQUIVALENT_INCREASE_PP = .2
_SEED_ABSORPTION = {
    "R": (25., 20., 5., .1), "Y": (20., 8., .03, .02),
    "B": (.01, 1., 25., 25.), "C": (.03, .03, 8., 25.),
    "M": (1., 25., 20., .03), "G": (15., .1, 10., 25.),
}


def _slices(present: Sequence[str]) -> dict[str, slice]:
    result, offset = {}, 0
    for symbol in present:
        size = 5 if symbol == "W" else 4 if symbol == "K" else 7
        result[symbol] = slice(offset, offset + size)
        offset += size
    return result


def _initial(present: Sequence[str], seed: int) -> np.ndarray:
    factor, power, forward = ((1., 0., .7), (.4, 1., .85))[seed % 2]
    values = []
    for symbol in present:
        if symbol == "W":
            values.extend([np.log(.02), 0., np.log(1. if seed == 0 else 3.), 0., forward])
        elif symbol == "K":
            values.extend([np.log(20.), np.log(.05), 0., .7])
        else:
            values.extend([*np.log(np.asarray(_SEED_ABSORPTION[symbol]) * factor),
                           np.log((2. if symbol == "Y" else 1.) * factor), power, forward])
    return np.asarray(values)


def _bounds(present: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
    lower, upper = [], []
    for symbol in present:
        if symbol == "W":
            lower.extend([np.log(1e-6), -4., np.log(1e-6), 0., .05])
            upper.extend([np.log(200.), 4., np.log(200.), 4., .98])
        elif symbol == "K":
            lower.extend([np.log(1e-6), np.log(1e-6), 0., .05])
            upper.extend([np.log(200.), np.log(200.), 4., .98])
        else:
            lower.extend([np.log(1e-6)] * 5 + [0., .05])
            upper.extend([np.log(200.)] * 5 + [4., .98])
    return np.asarray(lower), np.asarray(upper)


def _operator(prepared: shared._Prepared, vector: np.ndarray, *, smooth: bool = False) -> BackedGradientTransport:
    model_class = BackedGradientSmoothTransport if smooth else BackedGradientTransport
    return model_class({symbol: vector[part] for symbol, part in _slices(prepared.present).items()},
                       prepared.anchors, prepared.total, prepared.present)


def _predict(model: BackedGradientModel, rows: Sequence[dict]) -> np.ndarray:
    if isinstance(model, BackedGradientTransport):
        return model.predict_samples([row["material_symbol"] for row in rows],
                                     [row["backing"] for row in rows],
                                     [row["overlay_mm"] for row in rows])
    return shared._predict_rows(model, rows)


def _spectral_residual(vector: np.ndarray, prepared: shared._Prepared, rows: Sequence[dict],
                       *, smooth: bool = False) -> np.ndarray:
    model = _operator(prepared, vector, smooth=smooth)
    return _model_residual(model, rows)


def _model_residual(model: BackedGradientModel, rows: Sequence[dict]) -> np.ndarray:
    observed = np.asarray([row["reflectance_percent_xyz"] for row in rows])
    data = ((_predict(model, rows) - observed) / 100.).ravel()
    if not isinstance(model, BackedGradientSmoothTransport):
        return data
    return np.concatenate((data, model.curvature_residual()))


def _objective_terms(residual: np.ndarray, data_count: int) -> dict:
    data_sse = float(np.dot(residual[:data_count], residual[:data_count]))
    prior_sse = float(np.dot(residual[data_count:], residual[data_count:]))
    objective_sse = data_sse + prior_sse
    return {"data_sse": data_sse, "prior_sse": prior_sse,
            "regularized_objective_sse": objective_sse,
            "regularized_rmse_pp": 100. * float(np.sqrt(objective_sse / data_count))}


def _optimise_spectral(prepared: shared._Prepared, rows: list[dict], initial: np.ndarray,
                       indices: Sequence[int], deadline: float, *, max_evaluations: int = MAX_EVALUATIONS,
                       smooth: bool = False) -> tuple[np.ndarray, dict]:
    observed = np.asarray([row["reflectance_percent_xyz"] for row in rows])
    coordinates = np.asarray(indices, dtype=int)
    low, high = _bounds(prepared.present)

    def residual(free: np.ndarray) -> np.ndarray:
        shared._deadline_check(deadline)
        vector = initial.copy()
        vector[coordinates] = free
        try:
            return _spectral_residual(vector, prepared, rows, smooth=smooth)
        except (CoreValidationError, FloatingPointError, np.linalg.LinAlgError):
            prior_count = 2 * sum(symbol not in ("W", "K") for symbol in prepared.present) if smooth else 0
            return np.full(observed.size + prior_count, 10.)

    solution = least_squares(residual, np.clip(initial[coordinates], low[coordinates], high[coordinates]),
                             bounds=(low[coordinates], high[coordinates]), x_scale="jac",
                             max_nfev=max_evaluations, ftol=1e-8, xtol=1e-8, gtol=1e-8)
    vector = initial.copy()
    vector[coordinates] = solution.x
    return vector, {"success": bool(solution.success), "nfev": int(solution.nfev), "message": str(solution.message)}


def _fit_spectral_operator(prepared: shared._Prepared, rows: list[dict], deadline: float,
                           *, starts: int = FULL_STARTS,
                           smooth: bool = False) -> tuple[BackedGradientModel, list[dict], list[BackedGradientModel]]:
    slices = _slices(prepared.present)
    # Bare-reference scaling makes reference-only spectral shapes weakly identified.
    # Initialize only two strengths; release all nine W/K parameters in the joint fit.
    wk_indices = [slices["W"].start + 2, slices["K"].start]
    wk_rows = [row for row in rows if row["material_symbol"] in ("W", "K")]
    attempts, endpoints, best = [], [], None
    for seed in range(starts):
        started = time.monotonic()
        try:
            vector = _initial(prepared.present, seed)
            vector, _ = _optimise_spectral(prepared, wk_rows, vector, wk_indices, deadline, max_evaluations=30, smooth=smooth)
            for symbol, part in slices.items():
                if symbol not in ("W", "K"):
                    material_rows = [row for row in rows if row["material_symbol"] == symbol]
                    vector, _ = _optimise_spectral(prepared, material_rows, vector, range(part.start, part.stop), deadline, max_evaluations=50, smooth=smooth)
            vector, status = _optimise_spectral(prepared, rows, vector, range(len(vector)), deadline, smooth=smooth)
            model = _operator(prepared, vector, smooth=smooth)
            metrics = shared._metrics(rows, _predict(model, rows))
        except (CoreValidationError, FloatingPointError, np.linalg.LinAlgError) as error:
            attempts.append({"seed": seed, "success": False, "error": str(error)})
            continue
        objective = (_objective_terms(_spectral_residual(vector, prepared, rows, smooth=True), len(rows) * 3)
                     if smooth else {})
        attempts.append({"seed": seed, **status, "seconds": time.monotonic() - started,
                         "rmse_pp": metrics["overall_rmse_pp"], **objective})
        endpoints.append(model)
        score = objective["regularized_objective_sse"] if smooth else metrics["overall_rmse_pp"]
        if best is None or score < best[0]:
            best = score, model
    if best is None:
        raise CoreValidationError("No feasible spectral backed-gradient solution")
    return best[1], attempts, endpoints


def _fit_family(family: str, prepared: shared._Prepared, rows: list[dict], deadline: float,
                *, starts: int, smooth: bool = False) -> tuple[BackedGradientModel, list[dict], list[BackedGradientModel]]:
    if family == "affine":
        from core.backed_gradient_rgb import fit_rgb_operator

        return fit_rgb_operator(prepared, rows, deadline, starts=starts)
    return _fit_spectral_operator(prepared, rows, deadline, starts=starts, smooth=smooth)


def _best_attempt(attempts: Sequence[dict]) -> dict:
    feasible = [attempt for attempt in attempts
                if isinstance(attempt.get("rmse_pp"), (int, float))
                and not isinstance(attempt["rmse_pp"], bool)
                and np.isfinite(attempt["rmse_pp"])]
    if not feasible:
        raise CoreValidationError("No finite backed-gradient optimization attempt")
    regularized = [attempt for attempt in feasible
                   if isinstance(attempt.get("regularized_objective_sse"), (int, float))
                   and not isinstance(attempt["regularized_objective_sse"], bool)
                   and np.isfinite(attempt["regularized_objective_sse"])]
    return min(regularized, key=lambda attempt: attempt["regularized_objective_sse"]) if regularized else min(feasible, key=lambda attempt: attempt["rmse_pp"])


def _cross_validation(family: str, prepared: shared._Prepared, deadline: float,
                      progress: Callable[[str, float], None], lower: float, upper: float,
                      *, smooth: bool = False) -> dict:
    thicknesses = sorted({row["overlay_mm"] for row in prepared.training})
    held_rows, held_predictions, folds = [], [], []
    for index, thickness in enumerate(thicknesses):
        training = [row for row in prepared.training if row["overlay_mm"] != thickness]
        held = [row for row in prepared.training if row["overlay_mm"] == thickness]
        policy = {"smooth": True} if smooth else {}
        model, attempts, _ = _fit_family(family, prepared, training, deadline, starts=CV_STARTS, **policy)
        prediction = _predict(model, held)
        held_rows.extend(held)
        held_predictions.extend(prediction)
        best_attempt = _best_attempt(attempts)
        folds.append({"held_overlay_mm": thickness, "optimizer_converged": best_attempt["success"],
                      "held_record_ids": [row["record_id"] for row in held],
                      "training_record_ids": [row["record_id"] for row in training],
                      "parameters": model.to_parameters(), "attempts": attempts,
                      "metrics": shared._metrics(held, prediction)})
        progress(f"{family}_cross_validation", lower + (upper - lower) * (index + 1) / len(thicknesses))
    return {**shared._metrics(held_rows, np.asarray(held_predictions)), "folds": folds,
            "sample_predictions": shared._record_predictions(held_rows, np.asarray(held_predictions), training=False),
            "optimizer_converged": all(fold["optimizer_converged"] for fold in folds),
            "all_material_background_pairs_held_together": True,
            "white_black_refit_each_fold": True, "validation_024_used": True,
            "initialization": "fixed_unobserved_deterministic_seeds",
            "independent_of_model_design": False}


def _spectral_profiles(model: BackedGradientTransport, prepared: shared._Prepared,
                       endpoints: Sequence[BackedGradientModel], deadline: float) -> tuple[list[BackedGradientModel], list[dict]]:
    smooth = isinstance(model, BackedGradientSmoothTransport)
    base = np.concatenate([model.coefficients[symbol] for symbol in prepared.present])
    low, high = _bounds(prepared.present)
    predicted = _predict(model, prepared.training)
    best_rmse = shared._metrics(prepared.training, predicted)["overall_rmse_pp"]
    base_residual = _model_residual(model, prepared.training) if smooth else predicted.ravel()
    base_objective = _objective_terms(base_residual, predicted.size) if smooth else {}
    jacobian = np.empty((base_residual.size, len(base)))
    for coordinate in range(len(base)):
        shared._deadline_check(deadline)
        moved = base.copy()
        step = 1e-4 if base[coordinate] + 1e-4 <= high[coordinate] else -1e-4
        moved[coordinate] += step
        candidate = _operator(prepared, moved, smooth=smooth)
        residual = _model_residual(candidate, prepared.training) if smooth else _predict(candidate, prepared.training).ravel()
        jacobian[:, coordinate] = (residual - base_residual) / step
    _, singular_values, directions = np.linalg.svd(jacobian, full_matrices=False)
    accepted = []
    for endpoint in endpoints:
        data_rmse = shared._metrics(prepared.training, _predict(endpoint, prepared.training))["overall_rmse_pp"]
        equivalent = data_rmse <= best_rmse + NEAR_EQUIVALENT_INCREASE_PP
        if smooth:
            equivalent = (equivalent and isinstance(endpoint, BackedGradientSmoothTransport)
                          and _objective_terms(_model_residual(endpoint, prepared.training), predicted.size)["regularized_rmse_pp"]
                          <= base_objective["regularized_rmse_pp"] + NEAR_EQUIVALENT_INCREASE_PP)
        if equivalent:
            accepted.append(endpoint)
    evaluations = []
    for direction_index in range(1, min(4, len(base))):
        direction = directions[-direction_index]
        direction /= max(float(np.max(np.abs(direction))), 1e-12)
        for magnitude in (-1.6, -.8, -.2, .2, .8, 1.6):
            shared._deadline_check(deadline)
            requested = base + magnitude * direction
            moved = np.clip(requested, low, high)
            displacement = moved - base
            actual_max_step = float(np.max(np.abs(displacement)))
            if actual_max_step <= 1e-12:
                continue
            candidate = _operator(prepared, moved, smooth=smooth)
            rmse = shared._metrics(prepared.training, _predict(candidate, prepared.training))["overall_rmse_pp"]
            equivalent = rmse <= best_rmse + NEAR_EQUIVALENT_INCREASE_PP
            objective = _objective_terms(_model_residual(candidate, prepared.training), predicted.size) if smooth else {}
            if smooth:
                equivalent = equivalent and objective["regularized_rmse_pp"] <= base_objective["regularized_rmse_pp"] + NEAR_EQUIVALENT_INCREASE_PP
            evaluations.append({"weak_direction_rank": direction_index, "step": magnitude,
                                "actual_max_step": actual_max_step,
                                "actual_step_norm": float(np.linalg.norm(displacement)),
                                "bounds_projected": bool(np.any(moved != requested)),
                                "singular_value": float(singular_values[-direction_index]),
                                "rmse_pp": rmse, "accepted": bool(equivalent), **objective})
            if equivalent:
                accepted.append(candidate)
    return accepted, evaluations


def _stability(models: dict, operators: dict, alternatives: dict, comparison: dict | None) -> None:
    for family, operator in operators.items():
        per_backing = {}
        for backing in ("W", "K"):
            envelope = (comparison["envelopes"][backing][family] if comparison else
                        prediction_envelope(operator, alternatives[family], backing))
            per_backing[backing] = {key: value for key, value in envelope.items() if key != "rows"}
        blind = prediction_envelope(operator, alternatives[family], "W", BLIND_RECIPES)
        stable = (all(value["xyz_width_p95_pp"] <= 2 and value["delta_e00_p95"] <= 2
                      and value["xyz_width_max_pp"] <= 5 and value["delta_e00_max"] <= 5
                      for value in per_backing.values())
                  and blind["xyz_width_max_pp"] <= 2 and blind["delta_e00_max"] <= 2)
        unstable_recipes = []
        if comparison:
            for backing in ("W", "K"):
                ordered = sorted(comparison["rows"], key=lambda row: row["backings"][backing]["stability"][family]["delta_e00_width"], reverse=True)
                unstable_recipes.extend({"recipe_visible_to_back": row["recipe_visible_to_back"], "backing": backing,
                                         **row["backings"][backing]["stability"][family]} for row in ordered[:8])
        models[family]["stability"].update(status="stable" if stable else "unstable", per_backing=per_backing,
                                          blind_recipe_envelope={key: value for key, value in blind.items() if key != "rows"},
                                          most_unstable_recipes=unstable_recipes)


def _fit_backed_gradient(snapshot: dict, *, progress: Callable[[str, float], None] | None = None,
                         time_budget_seconds: float = 840., smooth: bool = False) -> dict:
    """Fit all seven acquired thicknesses with explicit exploratory validation provenance.
    拟合已采集的全部七档，并明确记录本次试算的验证来源。

    Args:
        snapshot: Immutable selected XYZ readings and bare-three-mm references.
            （不可变选用XYZ读数与裸三毫米参考。）
        progress: Optional progress callback.（可选进度回调。）
        time_budget_seconds: Bounded fitting/validation allowance.（拟合与验证的总时限。）

    Returns:
        Portable result with new model identities, complete paired holdouts,
        and frozen mixed predictions.（含新模型标识、整档留出及冻结混色预测的可移植结果。）
    """
    if (isinstance(time_budget_seconds, bool) or not isinstance(time_budget_seconds, (int, float))
            or not np.isfinite(time_budget_seconds) or time_budget_seconds <= 0):
        raise CoreValidationError("Invalid backed-gradient fitting time allowance")
    prepared = shared._prepare(snapshot, True)
    callback = progress or (lambda _stage, _fraction: None)
    deadline = time.monotonic() + time_budget_seconds
    operators, models, alternatives = {}, {}, {}
    policy = {"smooth": True} if smooth else {}
    for index, family in enumerate(("affine", "two_flux")):
        lower = .01 + index * .45
        callback(f"{family}_full_fit", lower)
        operator, attempts, endpoints = _fit_family(family, prepared, prepared.training, deadline, starts=FULL_STARTS, **policy)
        cv = _cross_validation(family, prepared, deadline, callback, lower + .04, lower + .39, **policy)
        predictions = _predict(operator, prepared.training)
        best = _best_attempt(attempts)
        training_metrics = shared._metrics(prepared.training, predictions)
        accepted = [endpoint for endpoint in endpoints
                    if shared._metrics(prepared.training, _predict(endpoint, prepared.training))["overall_rmse_pp"]
                    <= training_metrics["overall_rmse_pp"] + NEAR_EQUIVALENT_INCREASE_PP]
        evaluations = []
        if isinstance(operator, BackedGradientTransport):
            callback("two_flux_parameter_profiles", .88)
            accepted, evaluations = _spectral_profiles(operator, prepared, endpoints, deadline)
        operators[family], alternatives[family] = operator, accepted
        parameters = operator.to_parameters()
        models[family] = {"model_id": parameters["model_id"], "status": "converged" if best["success"] else "exploratory",
                          "optimizer_converged": best["success"], "parameters": parameters,
                          "parameter_count": len(_initial(prepared.present, 0)) if family == "two_flux" else 6 * len(prepared.present) - 3,
                          "attempts": attempts, "training_metrics": training_metrics, "cv": cv,
                          "sample_predictions": shared._record_predictions(prepared.training, predictions, training=True),
                          "stability": {"status": "not_available", "accepted_parameter_sets": len(accepted),
                                        "near_equivalent_rmse_increase_pp": NEAR_EQUIVALENT_INCREASE_PP,
                                        "scope": "multistart_endpoints_and_weak_jacobian_directions_not_confidence_bounds" if family == "two_flux"
                                        else "multistart_endpoints_not_a_confidence_bound",
                                        "profile_evaluations": evaluations,
                                        "accepted_parameters": [model.to_parameters() for model in accepted]}}
        if isinstance(operator, BackedGradientSmoothTransport):
            models[family]["objective_id"] = SPECTRAL_SMOOTH_OBJECTIVE_ID
            models[family]["training_objective"] = _objective_terms(_model_residual(operator, prepared.training), predictions.size)
            models[family]["stability"].update(
                scope="multistart_endpoints_and_augmented_objective_weak_directions_not_confidence_bounds",
                near_equivalent_regularized_rmse_increase_pp=NEAR_EQUIVALENT_INCREASE_PP,
                equivalence_requires="data_and_regularized_rmse_budgets",
            )
    complete = set(CORE_MATERIAL_SYMBOLS).issubset(prepared.present)
    callback("building_comparison", .90)
    comparison = build_comparison(models, alternatives=alternatives) if complete else None
    if complete:
        _stability(models, operators, alternatives, comparison)
    controls = shared._control_summary(prepared.controls, operators, prepared.anchors)
    controls.update(rms_threshold_pp=2., consistent=controls["rms_deviation_pp"] is None or controls["rms_deviation_pp"] <= 2)
    selected, reason = shared._choose(models)
    if not complete:
        selected, reason = None, "missing_materials"
    elif selected and models[selected]["stability"]["status"] != "stable":
        selected, reason = None, "prediction_stability_failed"
    elif selected and not controls["consistent"]:
        selected, reason = None, "homogeneous_controls_failed"
    # The v2 structure was developed using this thickness series. It cannot turn
    # those same design-reused holdouts into a new independent acceptance claim.
    recommendation = {"model": None, "status": "exploratory", "reason": reason if selected is None else "independent_mixed_validation_pending",
                      "gradient_rule_candidate": selected}
    validation = {"status": "included_in_training", "used_for_training": True, "passed": None,
                  "independent_acceptance": False, "role": "design_reused_blocked_thickness_diagnostic", "metrics": {}}
    for family, model in models.items():
        fold = next((fold for fold in model["cv"]["folds"] if abs(fold["held_overlay_mm"] - .24) < 1e-8), None)
        if fold:
            validation["metrics"][family] = fold["metrics"]
    blind = comparison["blind_recipes"] if comparison else []
    blind_hash = hashlib.sha256(json.dumps(blind, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    callback("comparison_ready", .99)
    return {"schema_version": "3.0" if smooth else "2.0", "kind": "lumina_box_backed_gradient_fit",
            "algorithm_id": BACKED_GRADIENT_SMOOTH_ALGORITHM_ID if smooth else BACKED_GRADIENT_ALGORITHM_ID,
            "dataset_id": snapshot.get("dataset_id"), "dataset_revision": snapshot.get("dataset_revision"),
            "input_hash": snapshot.get("input_hash"), "training_input_hash": shared._training_digest(prepared), "fit_mode": "full_seven",
            "models": models, "recommendation": recommendation, "validation_024": validation, "controls": controls,
            "comparison": comparison, "missing_materials": [symbol for symbol in CORE_MATERIAL_SYMBOLS if symbol not in prepared.present],
            "conditions": deepcopy(snapshot.get("conditions", {})), "selected_record_ids": list(snapshot.get("selected_record_ids", [])),
            "pipeline": {"collected_thicknesses": "all_seven_together", "final_fit_includes_all_seven": True,
                         "validation_protocol": "whole_thickness_all_background_pairs", "independent_mixed_validation_pending": True},
            "mixed_validation": {"status": "frozen_predictions_awaiting_measurements", "prediction_hash": blind_hash,
                                 "used_for_training": False, "recipes": blind},
            "scope": "research_fitting_and_comparison_only", "conversion_enabled": False}


def fit_backed_gradient_v2(snapshot: dict, *, progress: Callable[[str, float], None] | None = None,
                           time_budget_seconds: float = 840.) -> dict:
    """Fit the unchanged v2 objective with complete paired thickness holdouts.
    使用保持原样的第二版目标拟合，并进行整厚度黑白底成组留出。

    Args:
        snapshot: Immutable gradient XYZ and bare reference readings.
            （不可变梯度 XYZ 与裸参考片读数。）
        progress: Optional bounded progress callback.（可选有界进度回调。）
        time_budget_seconds: Whole-task time allowance.（整个任务的时间额度。）

    Returns:
        Versioned v2 exploratory result.（带版本的第二版试算结果。）
    """
    return _fit_backed_gradient(snapshot, progress=progress, time_budget_seconds=time_budget_seconds)


def fit_backed_gradient_v3(snapshot: dict, *, progress: Callable[[str, float], None] | None = None,
                           time_budget_seconds: float = 840.) -> dict:
    """Fit the fixed .003 curvature policy without adding material parameters.
    使用固定零点零零三曲率约束拟合，不增加材料参数。

    Args:
        snapshot: Immutable gradient XYZ and bare reference readings.
            （不可变梯度 XYZ 与裸参考片读数。）
        progress: Optional bounded progress callback.（可选有界进度回调。）
        time_budget_seconds: Whole-task time allowance.（整个任务的时间额度。）

    Returns:
        Independent v3 exploratory result with data/prior objective provenance.
            （含数据与约束目标来源的独立第三版试算结果。）
    """
    return _fit_backed_gradient(snapshot, progress=progress, time_budget_seconds=time_budget_seconds, smooth=True)
