"""Single-material fitting against reusable black/white backing calibration.
使用可复用黑白背板标定拟合单个耗材。
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import time
from typing import Any, Callable, Mapping, Sequence

import numpy as np
from scipy.optimize import least_squares
from scipy.optimize._numdiff import approx_derivative, group_columns

from core import backed_gradient_fitting_v2 as joint
from core.backed_gradient_material import (
    BackedGradientComponent, BackedGradientReference, BackedGradientMaterialModel,
    reference_from_parameters,
)
from core.backed_gradient_smooth import SPECTRAL_CURVATURE_WEIGHT, SPECTRAL_SMOOTH_MODEL_ID, SPECTRAL_SMOOTH_OBJECTIVE_ID
from core.backed_gradient_store import THICKNESSES_MM
from core.errors import CoreValidationError
from core.km_xyz import km_relative_xyz_to_srgb_uint8

MATERIAL_FIT_ALGORITHM_ID = "backed_gradient_single_material_fixed_reference/v1"
REFERENCE_FIT_ALGORITHM_ID = "backed_gradient_shared_backing_calibration/v1"
GROUP_FIT_ALGORITHM_ID = "backed_gradient_incremental_joint_materials/v1"


def _source(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(snapshot[key]) for key in (
        "dataset_id", "dataset_revision", "input_hash", "name", "brand", "material_type", "notes",
        "material_symbol", "material_kind", "selected_record_ids",
        "backing_role",
        "backing_components", "backing_material_ids", "backing_material_id", "opposite_material_id",
        "backing_material_versions", "capture_backing_material_versions", "backing_documents",
        "opposite_component", "observation_reference_id",
    ) if key in snapshot}


def _versioned_reference(reference: BackedGradientReference) -> BackedGradientReference:
    identity = json.dumps({"parameters": reference.reference_id, "source": dict(reference.source)},
                          sort_keys=True, separators=(",", ":"), allow_nan=False)
    return replace(reference, reference_id=hashlib.sha256(identity.encode("utf-8")).hexdigest())


def _rows(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    for raw in snapshot.get("samples", []):
        if raw.get("sample_role", "coated") != "coated":
            continue
        try:
            backing = raw["backing"]
            thickness = float(raw["overlay_mm"])
            observed = np.asarray(raw["reflectance_percent_xyz"], dtype=float)
        except (KeyError, TypeError, ValueError) as error:
            raise CoreValidationError("A material reading needs backing, thickness, and XYZ") from error
        canonical = next((value for value in THICKNESSES_MM if abs(value - thickness) < 1e-6), None)
        key = backing, canonical
        if (backing not in ("W", "K") or canonical is None or key in seen
                or observed.shape != (3,) or not np.isfinite(observed).all() or np.any(observed < 0)):
            raise CoreValidationError("Choose one finite XYZ reading per black/white thickness")
        seen.add(key)
        rows.append({**raw, "overlay_mm": canonical, "reflectance_percent_xyz": observed.tolist()})
    if seen != {(backing, thickness) for backing in ("W", "K") for thickness in THICKNESSES_MM}:
        raise CoreValidationError("Complete this material's seven black-backed and seven white-backed readings")
    return rows


def _predict(model: BackedGradientMaterialModel, component: BackedGradientComponent,
             rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
    output = np.empty((len(rows), 3))
    for backing in ("W", "K"):
        indices = [index for index, row in enumerate(rows) if row["backing"] == backing]
        if indices:
            thicknesses = np.array([rows[index]["overlay_mm"] for index in indices])
            output[indices] = model.predict_backed(component, backing, thicknesses)
    return output


def _seed_symbol(kind: str, symbol: str) -> str:
    if kind == "white":
        return "W"
    if kind == "black":
        return "K"
    return symbol if symbol in joint._SEED_ABSORPTION else "material"


def _component_initial(symbol: str, seed: int) -> np.ndarray:
    if symbol != "material":
        return joint._initial((symbol,), seed)
    # Neutral starts cover different absorption strengths without assigning a
    # hue or using held-out readings to choose the starting spectrum.
    absorption, scattering, power, forward = ((.3, 1., 0., .7), (3., .4, 1., .85))[seed % 2]
    return np.array([np.log(absorption)] * 4 + [np.log(scattering), power, forward])


def _fit_component(model: BackedGradientMaterialModel, kind: str, symbol: str,
                   rows: list[dict[str, Any]], deadline: float) -> tuple[BackedGradientComponent, bool, list[dict[str, Any]]]:
    seed_symbol = _seed_symbol(kind, symbol)
    lower, upper = joint._bounds((seed_symbol,))
    observed = np.asarray([row["reflectance_percent_xyz"] for row in rows])

    def residual(values: np.ndarray) -> np.ndarray:
        joint.shared._deadline_check(deadline)
        component = BackedGradientComponent(kind, tuple(values))
        values = ((_predict(model, component, rows) - observed) / 100.).ravel()
        if kind == "color":
            values = np.r_[values, SPECTRAL_CURVATURE_WEIGHT * np.diff(component.coefficients[:4], n=2)]
        return values

    attempts = []
    solutions = []
    for seed in range(2):
        fit = least_squares(residual, _component_initial(seed_symbol, seed), bounds=(lower, upper),
                            x_scale="jac", max_nfev=350, ftol=1e-8, xtol=1e-8, gtol=1e-8)
        attempts.append({"converged": bool(fit.success), "nfev": int(fit.nfev), "objective": float(2. * fit.cost)})
        solutions.append((float(2. * fit.cost), BackedGradientComponent(kind, tuple(fit.x)), bool(fit.success)))
    _objective, component, converged = min(solutions, key=lambda item: item[0])
    return component, converged, attempts


def _summary(rows: Sequence[Mapping[str, Any]], predicted: np.ndarray) -> dict[str, Any]:
    observed = np.asarray([row["reflectance_percent_xyz"] for row in rows])
    residual = predicted - observed
    return {"rmse_pp": float(np.sqrt(np.mean(residual ** 2))),
            "channel_rmse_pp": np.sqrt(np.mean(residual ** 2, axis=0)).tolist(),
            "max_abs_error_pp": float(np.max(np.abs(residual)))}


def fit_backed_gradient_material(snapshot: Mapping[str, Any], reference: BackedGradientReference | Mapping[str, Any], *,
                                 progress: Callable[[str, float], None] | None = None,
                                 time_budget_seconds: float = 180.) -> dict[str, Any]:
    """Fit all fourteen material readings against a frozen shared reference.
    使用冻结的共享参考拟合当前耗材全部十四条读数。

    Args:
        snapshot: Selected readings, identity, and optional actual backing components.
            （选用读数、耗材身份及可选实际背板组件。）
        reference: Previously calibrated physical backings.（已标定实体背板。）
        progress: Worker progress callback.（工作进度回调。）
        time_budget_seconds: Worker time allowance.（任务时限。）
    Returns:
        Portable component, reference, predictions, and internal paired holdouts.
        （可移植组件、参考、预测和内部成对留出结果。）
    """
    if not np.isfinite(time_budget_seconds) or time_budget_seconds <= 0:
        raise CoreValidationError("Fitting time allowance must be positive")
    reference = reference if isinstance(reference, BackedGradientReference) else BackedGradientReference.from_dict(reference)
    rows = _rows(snapshot)
    symbol = str(snapshot.get("material_symbol", "material"))
    kind = str(snapshot.get("material_kind") or ("white" if symbol == "W" else "black" if symbol == "K" else "color"))
    if kind not in ("white", "black", "color"):
        raise CoreValidationError("Choose a color, white, or black material")
    callback = progress or (lambda _stage, _fraction: None)
    deadline = time.monotonic() + time_budget_seconds
    model = BackedGradientMaterialModel(reference, snapshot.get("backing_components"))
    callback("fitting", .03)
    component, converged, attempts = _fit_component(model, kind, symbol, rows, deadline)
    predicted = _predict(model, component, rows)
    folds, held_predictions, held_rows = [], [], []
    for index, thickness in enumerate(THICKNESSES_MM):
        callback("checking", .2 + .7 * index / len(THICKNESSES_MM))
        training = [row for row in rows if row["overlay_mm"] != thickness]
        held = [row for row in rows if row["overlay_mm"] == thickness]
        folded, fold_converged, _attempts = _fit_component(model, kind, symbol, training, deadline)
        forecast = _predict(model, folded, held)
        folds.append({"held_overlay_mm": thickness, "converged": fold_converged,
                      "training_record_ids": [row.get("record_id") for row in training],
                      "held_record_ids": [row.get("record_id") for row in held],
                      "predicted_percent_xyz": forecast.tolist(), **_summary(held, forecast)})
        held_rows.extend(held)
        held_predictions.extend(forecast)
    estimate = model.predict_backed(component, "W", 3.)
    callback("complete", 1.)
    return {"schema_version": "1.0", "kind": "lumina_box_backed_gradient_material_fit", **_source(snapshot),
            "optical_model_id": SPECTRAL_SMOOTH_MODEL_ID, "algorithm_id": MATERIAL_FIT_ALGORITHM_ID,
            "objective_id": SPECTRAL_SMOOTH_OBJECTIVE_ID, "component": component.to_dict(), "reference": reference.to_dict(),
            "status": "complete" if converged else "not_converged", "converged": converged, "attempts": attempts,
            "estimated_rgb": km_relative_xyz_to_srgb_uint8(estimate / 100.).tolist(),
            "estimated_xyz": (estimate / 100.).tolist(), **_summary(rows, predicted),
            "sample_predictions": [{"record_id": row.get("record_id"), "backing": row["backing"],
                                    "overlay_mm": row["overlay_mm"], "measured_percent_xyz": row["reflectance_percent_xyz"],
                                    "predicted_percent_xyz": values.tolist()}
                                   for row, values in zip(rows, predicted, strict=True)],
            "cv": {"reference_fixed": True, "whole_thickness_paired": True,
                   "converged": all(fold["converged"] for fold in folds),
                   "folds": folds, **_summary(held_rows, np.asarray(held_predictions))}}


def fit_backed_gradient_reference(snapshot: Mapping[str, Any], *,
                                  progress: Callable[[str, float], None] | None = None,
                                  time_budget_seconds: float = 300.) -> dict[str, Any]:
    """Initialize W/K strengths before sequential material collection refines them.
    初始化黑白背板强度，随后随单材采集联合完善标定。

    Args:
        snapshot: W/K readings, optional homogeneous controls, and bare anchors.
            （黑白读数、可选同材对照及裸底参考。）
        progress: Worker progress callback.（工作进度回调。）
        time_budget_seconds: Worker time allowance.（任务时限。）
    Returns:
        Shared reference with source readings and fit diagnostics.（共享参考、来源读数与拟合结果。）
    """
    if not np.isfinite(time_budget_seconds) or time_budget_seconds <= 0:
        raise CoreValidationError("Fitting time allowance must be positive")
    prepared = joint.shared._prepare(dict(snapshot), True)
    if set(prepared.present) != {"W", "K"}:
        raise CoreValidationError("A backing calibration contains only its white and black materials")
    expected = {(symbol, thickness) for symbol in ("W", "K") for thickness in THICKNESSES_MM}
    if {(row["material_symbol"], row["overlay_mm"]) for row in prepared.training} != expected:
        raise CoreValidationError("Complete all seven white-on-black and black-on-white samples")
    callback = progress or (lambda _stage, _fraction: None)
    deadline = time.monotonic() + time_budget_seconds
    callback("fitting", .02)
    operator, attempts = _reference_initialization(prepared, prepared.training, deadline)
    folds, held_rows, held_predictions = [], [], []
    for index, thickness in enumerate(THICKNESSES_MM):
        callback("checking", .2 + .7 * index / len(THICKNESSES_MM))
        training = [row for row in prepared.training if row["overlay_mm"] != thickness]
        held = [row for row in prepared.training if row["overlay_mm"] == thickness]
        fold_model, _attempts = _reference_initialization(prepared, training, deadline)
        forecast = joint._predict(fold_model, held)
        folds.append({"held_overlay_mm": thickness, "converged": bool(joint._best_attempt(_attempts)["success"]),
                      **_summary(held, forecast)})
        held_rows.extend(held)
        held_predictions.extend(forecast)
    cv = {"folds": folds, "converged": all(fold["converged"] for fold in folds),
          **_summary(held_rows, np.asarray(held_predictions))}
    predicted = joint._predict(operator, prepared.training)
    source = {**_source(snapshot), "samples": deepcopy(snapshot["samples"]),
              "backing_samples": deepcopy(snapshot["samples"]), "backing_id": snapshot.get("dataset_id"),
              "materials": {symbol: snapshot.get("materials", {}).get(symbol, symbol) for symbol in ("W", "K")},
              "capture_history": deepcopy(snapshot.get("capture_history", [])),
              "calibration_stage": "bootstrap", "established": False}
    reference = _versioned_reference(reference_from_parameters(operator.to_parameters(), source=source))
    best = joint._best_attempt(attempts)
    callback("complete", 1.)
    return {"schema_version": "1.0", "kind": "lumina_box_backed_gradient_reference_fit", **_source(snapshot),
            "optical_model_id": SPECTRAL_SMOOTH_MODEL_ID, "algorithm_id": REFERENCE_FIT_ALGORITHM_ID,
            "objective_id": SPECTRAL_SMOOTH_OBJECTIVE_ID, "reference": reference.to_dict(),
            "status": "complete" if best["success"] else "not_converged", "converged": bool(best["success"]),
            "attempts": attempts, "cv": cv, **_summary(prepared.training, predicted)}


def _reference_initialization(prepared: joint.shared._Prepared, rows: list[dict[str, Any]],
                              deadline: float) -> tuple[joint.BackedGradientTransport, list[dict[str, Any]]]:
    slices = joint._slices(prepared.present)
    indices = [slices["W"].start + 2, slices["K"].start]
    attempts, candidates = [], []
    for seed in range(2):
        vector, status = joint._optimise_spectral(prepared, rows, joint._initial(prepared.present, seed),
                                                indices, deadline, smooth=True)
        model = joint._operator(prepared, vector, smooth=True)
        rmse = _summary(rows, joint._predict(model, rows))["rmse_pp"]
        attempts.append({"seed": seed, **status, "rmse_pp": rmse})
        candidates.append((rmse, model))
    return min(candidates, key=lambda item: item[0])[1], attempts


class _GroupProblem:
    def __init__(self, snapshot: Mapping[str, Any]) -> None:
        self.reference = BackedGradientReference.from_dict(snapshot["reference"])
        self.materials = list(snapshot["materials"])
        if not self.materials:
            raise CoreValidationError("A joint fit needs at least one collected material")
        self.keys = [f"{entry['dataset_id']}:{entry['material_symbol']}" for entry in self.materials]
        if len(set(self.keys)) != len(self.keys):
            raise CoreValidationError("Each material may appear only once in a backing group")
        self.backing_samples = list(snapshot["backing_samples"])
        prepared = joint.shared._prepare({"reference_anchors": dict(self.reference.anchors),
                                         "conditions": {"total_mm": 3., "observation_face": "bed_contact", "diffuser_removed": True},
                                         "samples": self.backing_samples}, True)
        expected = {(symbol, thickness) for symbol in ("W", "K") for thickness in THICKNESSES_MM}
        if ({(row["material_symbol"], row["overlay_mm"]) for row in prepared.training} != expected):
            raise CoreValidationError("A backing group needs all seven opposite-backing samples")
        self.backing_rows = prepared.training
        self.material_rows = [_rows(entry) for entry in self.materials]
        self.rows = [*self.backing_rows, *(row for rows in self.material_rows for row in rows)]
        self.material_indices = np.array([-1] * len(self.backing_rows) + [index for index, rows in enumerate(self.material_rows) for _row in rows])
        self.seed_symbols = ["W", "K"]
        self.slices: list[slice] = []
        self.kinds = []
        self.backing_roles = []
        self._working_reference_key: tuple[float, ...] | None = None
        self._working_model: BackedGradientMaterialModel | None = None
        offset = 9
        for entry in self.materials:
            symbol = entry["material_symbol"]
            kind = entry.get("material_kind") or ("white" if symbol == "W" else "black" if symbol == "K" else "color")
            role = entry.get("backing_role")
            if role not in (None, "W", "K") or (role is not None and kind != ("white" if role == "W" else "black")):
                raise CoreValidationError("A shared backing material must retain its white or black role")
            self.backing_roles.append(role)
            if kind not in ("white", "black", "color"):
                raise CoreValidationError("Unsupported material parameter family")
            seed = _seed_symbol(kind, symbol)
            size = 5 if kind == "white" else 4 if kind == "black" else 7
            self.kinds.append(kind)
            if role is not None:
                self.slices.append(slice(0, 5) if role == "W" else slice(5, 9))
            else:
                self.slices.append(slice(offset, offset + size))
                self.seed_symbols.append(seed)
                offset += size
        bounds = [joint._bounds((symbol,)) for symbol in self.seed_symbols]
        self.bounds = tuple(np.concatenate([bound[index] for bound in bounds]) for index in range(2))
        self.observed = np.asarray([row["reflectance_percent_xyz"] for row in self.rows])
        self.training_indices = np.flatnonzero(np.array([index == -1 or self.backing_roles[index] is None
                                                        for index in self.material_indices]))

    def operator(self, vector: np.ndarray) -> tuple[BackedGradientMaterialModel, list[BackedGradientComponent]]:
        reference_key = tuple(vector[:9])
        if reference_key != self._working_reference_key:
            reference = BackedGradientReference("working", BackedGradientComponent("white", tuple(vector[:5])),
                                                BackedGradientComponent("black", tuple(vector[5:9])), self.reference.anchors)
            self._working_model = BackedGradientMaterialModel(reference)
            self._working_reference_key = reference_key
        model = self._working_model
        return model, [BackedGradientComponent(kind, tuple(vector[part])) for kind, part in zip(self.kinds, self.slices, strict=True)]

    def predict(self, vector: np.ndarray, indices: np.ndarray) -> np.ndarray:
        model, components = self.operator(vector)
        predicted = np.empty((len(indices), 3))
        for material_index in range(-1, len(self.materials)):
            positions = np.flatnonzero(self.material_indices[indices] == material_index)
            if not positions.size:
                continue
            selected_rows = [self.rows[int(indices[position])] for position in positions]
            if material_index >= 0:
                predicted[positions] = _predict(model, components[material_index], selected_rows)
            else:
                for symbol, component in (("W", model.reference.white), ("K", model.reference.black)):
                    own = [i for i, row in enumerate(selected_rows) if row["material_symbol"] == symbol]
                    predicted[positions[own]] = _predict(model, component, [selected_rows[i] for i in own])
        return predicted

    def residual(self, vector: np.ndarray, rows: np.ndarray) -> np.ndarray:
        data = ((self.predict(vector, rows) - self.observed[rows]) / 100.).ravel()
        penalties = [SPECTRAL_CURVATURE_WEIGHT * np.diff(vector[part][:4], n=2)
                     for kind, part in zip(self.kinds, self.slices, strict=True) if kind == "color"]
        return np.concatenate([data, *penalties])

    def optimize(self, initial: np.ndarray, rows: np.ndarray, coordinates: np.ndarray,
                 deadline: float, evaluations: int = 350) -> tuple[np.ndarray, Any]:
        def residual(values: np.ndarray) -> np.ndarray:
            joint.shared._deadline_check(deadline)
            vector = initial.copy()
            vector[coordinates] = values
            return self.residual(vector, rows)
        bounds = self.bounds[0][coordinates], self.bounds[1][coordinates]
        pattern = self.jacobian_pattern(rows)[:, coordinates]
        structure = (pattern, group_columns(pattern))

        def jacobian(values: np.ndarray) -> np.ndarray:
            # Independent material columns can be perturbed together. Keep the
            # original dense solver, objective, bounds, and convergence tolerances.
            return approx_derivative(residual, values, method="2-point", bounds=bounds,
                                     sparsity=structure).toarray()

        fit = least_squares(residual, initial[coordinates], bounds=bounds, jac=jacobian,
                            x_scale="jac", max_nfev=evaluations, ftol=1e-8, xtol=1e-8, gtol=1e-8)
        vector = initial.copy()
        vector[coordinates] = fit.x
        return vector, fit

    def jacobian_pattern(self, rows: np.ndarray) -> np.ndarray:
        prior_count = 2 * self.kinds.count("color")
        pattern = np.zeros((len(rows) * 3 + prior_count, len(self.bounds[0])), dtype=bool)
        pattern[:len(rows) * 3, :9] = True
        prior = len(rows) * 3
        for index, (kind, part) in enumerate(zip(self.kinds, self.slices, strict=True)):
            if self.backing_roles[index] is not None:
                continue
            positions = np.flatnonzero(self.material_indices[rows] == index)
            data_positions = (positions[:, None] * 3 + np.arange(3)).ravel()
            pattern[data_positions, part] = True
            if kind == "color":
                pattern[prior:prior + 2, part.start:part.start + 4] = True
                prior += 2
        return pattern

    def fit(self, rows: np.ndarray, deadline: float) -> tuple[np.ndarray, list[dict[str, Any]]]:
        attempts, candidates = [], []
        for seed in range(2):
            vector = np.concatenate([_component_initial(symbol, seed) for symbol in self.seed_symbols])
            backing_rows = rows[self.material_indices[rows] == -1]
            vector, _fit = self.optimize(vector, backing_rows, np.array([2, 5]), deadline, 30)
            for index, part in enumerate(self.slices):
                if self.backing_roles[index] is not None:
                    continue
                own = rows[self.material_indices[rows] == index]
                vector, _fit = self.optimize(vector, own, np.arange(part.start, part.stop), deadline, 50)
            vector, fit = self.optimize(vector, rows, np.arange(len(vector)), deadline)
            attempts.append({"converged": bool(fit.success), "nfev": int(fit.nfev), "objective": float(2. * fit.cost)})
            candidates.append((float(2. * fit.cost), vector))
        return min(candidates, key=lambda item: item[0])[1], attempts


def fit_backed_gradient_material_group(snapshot: Mapping[str, Any], *,
                                       progress: Callable[[str, float], None] | None = None,
                                       time_budget_seconds: float = 600.) -> dict[str, Any]:
    """Refine a backing group as individually collected materials become available.
    随着单个耗材逐步采集完成，联合完善其共享背板组。

    Args:
        snapshot: Reference, backing_samples, and a list of single-material snapshots.
            （参考、背板样本及单材快照列表。）
        progress: Worker progress callback.（工作进度回调。）
        time_budget_seconds: Total fitting allowance.（拟合总时限。）
    Returns:
        Shared reference and material_fits keyed by dataset_id:material_symbol.
        （共享参考和以数据集及耗材键索引的单材结果。）
    """
    if not np.isfinite(time_budget_seconds) or time_budget_seconds <= 0:
        raise CoreValidationError("Fitting time allowance must be positive")
    problem = _GroupProblem(snapshot)
    callback = progress or (lambda _stage, _fraction: None)
    deadline = time.monotonic() + time_budget_seconds
    indices = np.arange(len(problem.rows))
    callback("fitting", .02)
    vector, attempts = problem.fit(problem.training_indices, deadline)
    model, components = problem.operator(vector)
    forecast = problem.predict(vector, indices)
    folds = []
    held_predictions = np.empty_like(forecast)
    for index, thickness in enumerate(THICKNESSES_MM):
        callback("checking", .2 + .7 * index / len(THICKNESSES_MM))
        mask = np.asarray([row["overlay_mm"] == thickness for row in problem.rows])
        held_vector, fold_attempts = problem.fit(problem.training_indices[~mask[problem.training_indices]], deadline)
        held_predictions[mask] = problem.predict(held_vector, indices[mask])
        scored = problem.training_indices[mask[problem.training_indices]]
        folds.append({"held_overlay_mm": thickness, "attempts": fold_attempts,
                      "converged": bool(min(fold_attempts, key=lambda attempt: attempt["objective"])["converged"]),
                      **_summary([problem.rows[position] for position in scored], held_predictions[scored]),
                      "training_record_ids": [problem.rows[position].get("record_id") for position in problem.training_indices if not mask[position]],
                      "held_record_ids": [row.get("record_id") for row, held in zip(problem.rows, mask, strict=True) if held]})
    original_source = dict(problem.reference.source)
    independent_materials = {key for key, kind in zip(problem.keys, problem.kinds, strict=True) if kind == "color"}
    source = {**original_source, "backing_id": original_source.get("backing_id") or original_source.get("dataset_id") or problem.reference.reference_id,
              "group_input_hash": snapshot.get("input_hash"),
              "backing_samples": deepcopy(problem.backing_samples),
              "material_inputs": [{**_source(entry), "samples": deepcopy(entry["samples"])}
                                  for entry in problem.materials],
              "calibration_stage": "joint", "established": len(independent_materials) >= 3,
              "established_role": "prefer_fixed_reference_for_subsequent_fits_not_accuracy_acceptance"}
    reference = _versioned_reference(reference_from_parameters(model._reporter.to_parameters(), source=source))
    converged = min(attempts, key=lambda attempt: attempt["objective"])["converged"]
    fits = {}
    for index, (entry, component, key) in enumerate(zip(problem.materials, components, problem.keys, strict=True)):
        positions = np.flatnonzero(problem.material_indices == index)
        rows = problem.material_rows[index]
        estimate = model.predict_backed(component, "W", 3.) / 100.
        fits[key] = {"schema_version": "1.0", "kind": "lumina_box_backed_gradient_material_fit", **_source(entry),
                     "optical_model_id": SPECTRAL_SMOOTH_MODEL_ID, "algorithm_id": GROUP_FIT_ALGORITHM_ID,
                     "objective_id": SPECTRAL_SMOOTH_OBJECTIVE_ID, "component": component.to_dict(), "reference": reference.to_dict(),
                     "converged": converged, "status": "complete" if converged else "not_converged",
                     "estimated_xyz": estimate.tolist(), "estimated_rgb": km_relative_xyz_to_srgb_uint8(estimate).tolist(),
                     **_summary(rows, forecast[positions]),
                     "sample_predictions": [{"record_id": row.get("record_id"), "backing": row["backing"], "overlay_mm": row["overlay_mm"],
                                             "measured_percent_xyz": row["reflectance_percent_xyz"], "predicted_percent_xyz": values.tolist()}
                                            for row, values in zip(rows, forecast[positions], strict=True)],
                     "cv": {"reference_fixed": False, "whole_thickness_paired": True, "folds": folds,
                            "converged": all(fold["converged"] for fold in folds),
                            **_summary(rows, held_predictions[positions])}}
    callback("complete", 1.)
    return {"kind": "lumina_box_backed_gradient_group_fit", "algorithm_id": GROUP_FIT_ALGORITHM_ID,
            "input_hash": snapshot.get("input_hash"), "reference": reference.to_dict(), "material_fits": fits,
            "status": "complete" if converged else "not_converged", "converged": converged, "attempts": attempts,
            "cv": {"reference_fixed": False, "whole_thickness_paired": True, "folds": folds,
                   "converged": all(fold["converged"] for fold in folds),
                   **_summary([problem.rows[index] for index in problem.training_indices], held_predictions[problem.training_indices])},
            **_summary([problem.rows[index] for index in problem.training_indices], forecast[problem.training_indices])}
