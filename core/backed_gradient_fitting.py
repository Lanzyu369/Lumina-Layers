"""Bounded paired-background fitting, blocked thickness CV, and frozen validation.
有界双背景拟合、整厚度留出及冻结后的独立验证。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import time
from typing import Callable, Iterator, Sequence

import numpy as np
from scipy.optimize import least_squares

from core.backed_gradient_comparison import BLIND_RECIPES, build_comparison, prediction_envelope
from core.backed_gradient_optics import BackedGradientOptics, CORE_MATERIAL_SYMBOLS, MATERIAL_SYMBOLS, MODEL_IDS
from core.backed_gradient_models import restore_backed_gradient_model
from core.backed_gradient_store import THICKNESSES_MM
from core.errors import CoreValidationError

VALIDATION_THICKNESS_MM = .24
PROFILE_MULTIPLIERS = (.25, .5, 1., 2., 4.)
START_COUNT = 3
CV_START_COUNT = 2
MAX_EVALUATIONS = 100
PROFILE_MAX_EVALUATIONS = 60


class BackedGradientFitTimeout(TimeoutError):
    """The bounded research fit exhausted its caller-visible time allowance.
    有界研究拟合耗尽调用方可见的时间额度。
    """


@dataclass
class _Prepared:
    anchors: dict
    total: float
    training: list[dict]
    validation: list[dict]
    controls: list[dict]
    present: tuple[str, ...]


def _prepare(snapshot: dict, include_validation: bool) -> _Prepared:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("samples"), list):
        raise CoreValidationError("A backed-gradient snapshot must contain a sample list")
    if not isinstance(snapshot.get("conditions"), dict) or not isinstance(snapshot.get("reference_anchors"), dict):
        raise CoreValidationError("Snapshot conditions and bare anchors must be objects")
    if (snapshot["conditions"].get("observation_face") != "bed_contact"
            or snapshot["conditions"].get("diffuser_removed") is not True):
        raise CoreValidationError("This workflow requires the bed-contact face and removed diffuser")
    try:
        for values in snapshot["reference_anchors"].values():
            if not isinstance(values, (list, tuple)) or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
                raise CoreValidationError("Bare anchors must contain actual numeric XYZ values")
        anchors = {key: np.asarray(snapshot["reference_anchors"][key], float).tolist() for key in ("W", "K")}
        if isinstance(snapshot["conditions"]["total_mm"], bool):
            raise CoreValidationError("Total thickness must be numeric, not boolean")
        total = float(snapshot["conditions"]["total_mm"])
    except (KeyError, TypeError, ValueError) as error:
        raise CoreValidationError("The backed-gradient snapshot needs measured bare W/K anchors and thickness") from error
    if not np.isfinite(total) or abs(total - 3.) > 1e-8:
        raise CoreValidationError("This first backed-gradient workflow requires a complete three-mm sample")
    if (any(np.asarray(anchors[key]).shape != (3,) or not np.isfinite(anchors[key]).all() for key in ("W", "K"))
            or any(value < 0 for values in anchors.values() for value in values)
            or np.any(np.asarray(anchors["W"]) <= anchors["K"])):
        raise CoreValidationError("Measured bare white anchors must be finite and exceed nonnegative bare black anchors")
    training, validation, controls = [], [], []
    seen = set()
    for source in snapshot.get("samples", []):
        try:
            if (not isinstance(source, dict) or isinstance(source["overlay_mm"], bool)
                    or not isinstance(source["overlay_mm"], (int, float))
                    or not isinstance(source["reflectance_percent_xyz"], (list, tuple))
                    or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in source["reflectance_percent_xyz"])
                    or not isinstance(source.get("record_id"), str) or not source["record_id"].strip()):
                raise CoreValidationError("Samples need numeric thickness/XYZ and a record identity")
            row = {**source, "overlay_mm": float(source["overlay_mm"]),
                   "reflectance_percent_xyz": np.asarray(source["reflectance_percent_xyz"], float).tolist()}
            values = np.asarray(row["reflectance_percent_xyz"])
            symbol, backing = row["material_symbol"], row["backing"]
        except (KeyError, TypeError, ValueError) as error:
            raise CoreValidationError("A backed-gradient sample is incomplete") from error
        if (symbol not in MATERIAL_SYMBOLS or backing not in ("W", "K") or values.shape != (3,)
                or not np.isfinite(values).all() or np.any(values < 0)
                or not np.isfinite(row["overlay_mm"]) or not 0 <= row["overlay_mm"] <= total):
            raise CoreValidationError("Sample XYZ must be nonnegative finite readings with a valid finite backing")
        row["sample_role"] = source.get("sample_role", "coated")
        if row["sample_role"] not in ("coated", "bare_backing"):
            raise CoreValidationError("Unknown backed-gradient sample role")
        if row["sample_role"] == "bare_backing":
            if symbol != backing or row["overlay_mm"] != 0:
                raise CoreValidationError("A bare anchor must have zero overlay and its own backing material")
        else:
            canonical = next((point for point in THICKNESSES_MM if abs(row["overlay_mm"] - point) <= 1e-6), None)
            if canonical is None:
                raise CoreValidationError("The overlay must match one of the seven declared thicknesses")
            row["overlay_mm"] = canonical
        identity = symbol, backing, row["overlay_mm"]
        if identity in seen:
            raise CoreValidationError("Select one active record for each material/backing/thickness")
        seen.add(identity)
        if symbol == backing or row["sample_role"] != "coated" or row["overlay_mm"] == 0:
            controls.append(row)
        elif not include_validation and abs(row["overlay_mm"] - VALIDATION_THICKNESS_MM) < 1e-8:
            # Keep the raw record untouched; no validation XYZ enters optimizer arrays.
            validation.append(row)
        else:
            training.append(row)
    present = tuple(symbol for symbol in MATERIAL_SYMBOLS if any(row["material_symbol"] == symbol for row in training))
    if not {"W", "K"}.issubset(present):
        raise CoreValidationError("Joint white-on-black and black-on-white measurements are required")
    for symbol in present:
        rows = [row for row in training if row["material_symbol"] == symbol]
        if len({row["overlay_mm"] for row in rows}) < 3:
            raise CoreValidationError(f"Material {symbol} needs at least three non-validation thicknesses")
        if symbol not in ("W", "K"):
            grouped = defaultdict(set)
            for row in rows:
                grouped[round(row["overlay_mm"], 6)].add(row["backing"])
            if any(backings != {"W", "K"} for backings in grouped.values()):
                raise CoreValidationError(f"Material {symbol} needs paired W/K backgrounds at each thickness")
    return _Prepared(anchors, total, training, validation, controls, present)


def _predict_rows(operator: BackedGradientOptics, rows: Sequence[dict]) -> np.ndarray:
    output = np.empty((len(rows), 3))
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        groups[row["material_symbol"], row["backing"]].append(index)
    for (material, backing), indices in groups.items():
        thicknesses = np.array([rows[index]["overlay_mm"] for index in indices])
        output[indices] = operator.predict_backed(material, backing, thicknesses)
    return output


def _coordinates(family: str, present: Sequence[str]) -> list[tuple[int, int]]:
    return [(MATERIAL_SYMBOLS.index(symbol), column) for symbol in present for column in (0, 1)
            if not (family == "affine" and symbol == "W" and column == 1)]


def _seed_coefficients(family: str, seed: int) -> np.ndarray:
    result = np.ones((len(MATERIAL_SYMBOLS), 3, 2))
    if family == "affine":
        result[..., 0] = (2., 6., 15.)[seed % 3]
        result[..., 1] = .35
        result[3, :, 0] = (.5, 1.5, 4.)[seed % 3]
        result[3, :, 1] = 1.
        result[4, :, 0] = (3., 10., 25.)[seed % 3]
        result[4, :, 1] = (.01, .03, .08)[seed % 3]
    else:
        result[..., 0] = (1., 4., 12.)[seed % 3]
        result[..., 1] = (1., 3., 8.)[seed % 3]
        result[3, :, 0] = (.005, .03, .1)[seed % 3]
        result[3, :, 1] = (2., 5., 15.)[seed % 3]
        result[4, :, 0] = (3., 10., 25.)[seed % 3]
        result[4, :, 1] = (.05, .2, .5)[seed % 3]
    return result


def _bounds(family: str, coordinates: Sequence[tuple[int, int]]) -> tuple[np.ndarray, np.ndarray]:
    lower, upper = [], []
    for symbol, column in coordinates:
        lower.append(np.log(1e-5 if family == "affine" and column == 0 else 1e-7))
        upper.append(np.log(4. if family == "affine" and column == 1 else 200.))
    return np.array(lower), np.array(upper)


def _unpack(template: np.ndarray, channel: int, coordinates: Sequence[tuple[int, int]],
            values: np.ndarray) -> np.ndarray:
    result = template.copy()
    for value, (symbol, column) in zip(values, coordinates, strict=True):
        result[symbol, channel, column] = np.exp(value)
    return result


def _deadline_check(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise BackedGradientFitTimeout("Backed-gradient fitting exceeded its bounded time allowance")


def _optimise_channel(family: str, prepared: _Prepared, rows: list[dict], template: np.ndarray,
                      channel: int, coordinates: list[tuple[int, int]], deadline: float,
                      *, fixed: dict[tuple[int, int], float] | None = None,
                      max_evaluations: int = MAX_EVALUATIONS) -> tuple[np.ndarray, dict]:
    free = [coordinate for coordinate in coordinates if coordinate not in (fixed or {})]
    base = template.copy()
    for coordinate, value in (fixed or {}).items():
        base[coordinate[0], channel, coordinate[1]] = value
    initial = np.array([np.log(max(base[symbol, channel, column], 1e-7)) for symbol, column in free])
    low, high = _bounds(family, free)
    observed = np.array([row["reflectance_percent_xyz"][channel] for row in rows])

    def residual(values: np.ndarray) -> np.ndarray:
        _deadline_check(deadline)
        coefficients = _unpack(base, channel, free, values)
        try:
            operator = BackedGradientOptics(family, coefficients, prepared.anchors, prepared.total, prepared.present)
            return (_predict_rows(operator, rows)[:, channel] - observed) / 100
        except CoreValidationError:
            return np.full(len(rows), 10.)

    if not free:
        operator = BackedGradientOptics(family, base, prepared.anchors, prepared.total, prepared.present)
        error = _predict_rows(operator, rows)[:, channel] - observed
        return base, {"success": True, "nfev": 0, "rmse_pp": float(np.sqrt(np.mean(error ** 2))),
                      "message": "All profiled channel coordinates are fixed"}
    solution = least_squares(residual, np.clip(initial, low, high), bounds=(low, high),
                             max_nfev=max_evaluations, x_scale="jac", ftol=1e-9, xtol=1e-9, gtol=1e-9)
    coefficients = _unpack(base, channel, free, solution.x)
    operator = BackedGradientOptics(family, coefficients, prepared.anchors, prepared.total, prepared.present)
    error = _predict_rows(operator, rows)[:, channel] - observed
    return coefficients, {"success": bool(solution.success), "nfev": int(solution.nfev),
                          "rmse_pp": float(np.sqrt(np.mean(error ** 2))), "message": str(solution.message)}


def _fit_operator(family: str, prepared: _Prepared, rows: list[dict], deadline: float,
                  *, starts: int = START_COUNT) -> tuple[BackedGradientOptics, list[dict], list[BackedGradientOptics]]:
    present = tuple(symbol for symbol in prepared.present if any(row["material_symbol"] == symbol for row in rows))
    coordinates = _coordinates(family, present)
    white_black_rows = [row for row in rows if row["material_symbol"] in ("W", "K")]
    white_black_coordinates = _coordinates(family, ("W", "K"))
    best, attempts, endpoints = None, [], []
    observed = np.array([row["reflectance_percent_xyz"] for row in rows])
    for seed in range(starts):
        coefficients = _seed_coefficients(family, seed)
        channel_status = []
        try:
            for channel in range(3):
                # Refitted in every fold; no full-fit terminal or held reading is an initializer.
                coefficients, _ = _optimise_channel(family, prepared, white_black_rows, coefficients,
                                                     channel, white_black_coordinates, deadline)
                for symbol in present:
                    if symbol in ("W", "K"):
                        continue
                    material_rows = [row for row in rows if row["material_symbol"] == symbol]
                    coefficients, _ = _optimise_channel(family, prepared, material_rows, coefficients,
                                                         channel, _coordinates(family, (symbol,)), deadline)
                coefficients, status = _optimise_channel(family, prepared, rows, coefficients,
                                                         channel, coordinates, deadline)
                channel_status.append(status)
            operator = BackedGradientOptics(family, coefficients, prepared.anchors, prepared.total, prepared.present)
            error = _predict_rows(operator, rows) - observed
            rmse = float(np.sqrt(np.mean(error ** 2)))
            converged = all(item["success"] for item in channel_status)
            attempts.append({"seed": seed, "success": converged, "rmse_pp": rmse, "channels": channel_status})
            if np.isfinite(rmse):
                endpoints.append(operator)
                if best is None or rmse < best[0]:
                    best = rmse, operator
        except (CoreValidationError, FloatingPointError, np.linalg.LinAlgError) as error:
            attempts.append({"seed": seed, "success": False, "error": str(error)})
    if best is None:
        raise CoreValidationError(f"The {family} model did not find a finite feasible solution")
    return best[1], attempts, endpoints


def _metrics(rows: Sequence[dict], predictions: np.ndarray) -> dict:
    if not rows:
        return {"overall_rmse_pp": None, "per_material_rmse_pp": {}, "scalar_count": 0}
    error = predictions - np.array([row["reflectance_percent_xyz"] for row in rows])
    return {"overall_rmse_pp": float(np.sqrt(np.mean(error ** 2))),
            "per_material_rmse_pp": {symbol: float(np.sqrt(np.mean(error[[i for i, row in enumerate(rows)
                                                                           if row["material_symbol"] == symbol]] ** 2)))
                                     for symbol in MATERIAL_SYMBOLS if any(row["material_symbol"] == symbol for row in rows)},
            "scalar_count": int(error.size)}


def _record_predictions(rows: Sequence[dict], predictions: np.ndarray, *, training: bool) -> list[dict]:
    return [{"record_id": row["record_id"], "material_symbol": row["material_symbol"], "backing": row["backing"],
             "overlay_mm": row["overlay_mm"], "sample_role": row.get("sample_role", "coated"), "is_training": training,
             "observed_percent_xyz": row["reflectance_percent_xyz"], "predicted_percent_xyz": predicted.tolist(),
             "residual_percent_xyz": (predicted - row["reflectance_percent_xyz"]).tolist()}
            for row, predicted in zip(rows, predictions, strict=True)]


def _cross_validation(family: str, prepared: _Prepared, deadline: float,
                      progress: Callable[[str, float], None], lower: float, upper: float) -> dict:
    thicknesses = sorted({round(row["overlay_mm"], 6) for row in prepared.training})
    held_rows, held_predictions, folds = [], [], []
    for index, thickness in enumerate(thicknesses):
        training = [row for row in prepared.training if round(row["overlay_mm"], 6) != thickness]
        held = [row for row in prepared.training if round(row["overlay_mm"], 6) == thickness]
        if any(not any(row["material_symbol"] == symbol for row in training) for symbol in prepared.present):
            raise CoreValidationError("Every thickness fold must retain training data for all selected materials")
        operator, attempts, _ = _fit_operator(family, prepared, training, deadline, starts=CV_START_COUNT)
        prediction = _predict_rows(operator, held)
        held_rows.extend(held)
        held_predictions.extend(prediction)
        best_attempt = min((attempt for attempt in attempts if "rmse_pp" in attempt), key=lambda attempt: attempt["rmse_pp"])
        folds.append({"held_overlay_mm": thickness, "optimizer_converged": best_attempt["success"],
                      "held_record_ids": [row["record_id"] for row in held],
                      "training_record_ids": [row["record_id"] for row in training], "parameters": operator.to_parameters(),
                      "attempts": attempts, "metrics": _metrics(held, prediction)})
        progress(f"{family}_cross_validation", lower + (upper - lower) * (index + 1) / len(thicknesses))
    assert len(held_rows) == len(prepared.training)
    return {**_metrics(held_rows, np.asarray(held_predictions)), "folds": folds,
            "sample_predictions": _record_predictions(held_rows, np.asarray(held_predictions), training=False),
            "optimizer_converged": all(fold["optimizer_converged"] for fold in folds),
            "validation_024_used": any(abs(row["overlay_mm"] - VALIDATION_THICKNESS_MM) < 1e-8 for row in prepared.training),
            "white_black_refit_each_fold": True,
            "initialization": "fixed_unobserved_deterministic_seeds"}


def _profile_positions(operator: BackedGradientOptics) -> Iterator[tuple[int, dict, dict]]:
    for channel in range(3):
        for coordinate in _coordinates(operator.family, ("W", "K")):
            for factor in PROFILE_MULTIPLIERS:
                if factor == 1:
                    continue
                value = operator.coefficients[coordinate[0], channel, coordinate[1]] * factor
                yield channel, {coordinate: value}, {"channel": channel, "material": MATERIAL_SYMBOLS[coordinate[0]],
                                                     "coefficient": coordinate[1], "factor": factor}
    for channel in range(3):
        for direction in ("common_strength", "relative_ratio"):
            for factor in PROFILE_MULTIPLIERS:
                if factor == 1:
                    continue
                if operator.family == "two_flux":
                    fixed = {coordinate: operator.coefficients[coordinate[0], channel, coordinate[1]]
                             * (factor if direction == "common_strength" or coordinate[1] == 0 else 1 / factor)
                             for coordinate in _coordinates(operator.family, ("W", "K"))}
                else:
                    fixed = {(index, 0): operator.coefficients[index, channel, 0]
                             * (factor if direction == "common_strength" or index == 3 else 1 / factor)
                             for index in (3, 4)}
                yield channel, fixed, {"channel": channel, "joint_direction": direction, "factor": factor}


def _profiles(operator: BackedGradientOptics, prepared: _Prepared, endpoints: list[BackedGradientOptics],
              deadline: float) -> tuple[list[BackedGradientOptics], list[dict]]:
    observed = np.array([row["reflectance_percent_xyz"] for row in prepared.training])

    def error(operator: BackedGradientOptics) -> float:
        return float(np.sqrt(np.mean((_predict_rows(operator, prepared.training) - observed) ** 2)))

    budget = error(operator) + .2
    accepted = [endpoint for endpoint in endpoints if error(endpoint) <= budget]
    evaluations = []
    coordinates = _coordinates(operator.family, prepared.present)
    for channel, fixed, label in _profile_positions(operator):
        fixed_coordinates = list(fixed)
        lower, upper = _bounds(operator.family, fixed_coordinates)
        logged = np.log([fixed[coordinate] for coordinate in fixed_coordinates])
        if np.any(logged < lower) or np.any(logged > upper):
            continue
        try:
            coefficients, status = _optimise_channel(
                operator.family, prepared, prepared.training, operator.coefficients,
                channel, coordinates, deadline, fixed=fixed, max_evaluations=PROFILE_MAX_EVALUATIONS,
            )
            candidate = BackedGradientOptics(operator.family, coefficients, prepared.anchors, prepared.total, prepared.present)
            rmse = error(candidate)
            keep = status["success"] and rmse <= budget
            evaluations.append({**label, "rmse_pp": rmse, "accepted": keep})
            if keep:
                accepted.append(candidate)
        except (CoreValidationError, FloatingPointError, np.linalg.LinAlgError) as failure:
            evaluations.append({**label, "accepted": False, "error": str(failure)})
    return accepted, evaluations


def _training_digest(prepared: _Prepared) -> str:
    payload = {"anchors": prepared.anchors, "total_mm": prepared.total,
               "training": sorted(prepared.training, key=lambda row: row["record_id"])}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def score_backed_gradient_validation(result: dict, snapshot: dict) -> dict:
    """Score complete .24 rows with frozen parameters, never optimizing or changing selection.
    使用冻结参数评分完整零点二四毫米数据，不优化或改选模型。

    Args:
        result: Previously saved six-thickness fit.（先前保存的六档拟合。）
        snapshot: Current active records with the same training data and bare anchors.
            （包含新验证记录、相同训练数据及裸锚的当前快照。）

    Returns:
        Separate frozen validation artifact.（独立冻结验证产物。）
    """
    prepared = _prepare(snapshot, False)
    if result.get("fit_mode") != "frozen_six" or result.get("dataset_id") != snapshot.get("dataset_id"):
        raise CoreValidationError("Validation requires the matching frozen six-thickness fit")
    if result.get("training_input_hash") != _training_digest(prepared):
        raise CoreValidationError("Training records or calibration anchors changed after the frozen fit")
    present = set(prepared.present)
    available = {(row["material_symbol"], row["backing"]) for row in (*prepared.validation, *prepared.controls)
                 if abs(row["overlay_mm"] - VALIDATION_THICKNESS_MM) <= 1e-8}
    missing = sorted(f"{symbol}:{backing}" for symbol in present for backing in ("W", "K")
                     if (symbol, backing) not in available)
    if missing:
        raise CoreValidationError("Missing .24 validation pairs: " + ", ".join(missing))
    operators = {family: restore_backed_gradient_model(model["parameters"])
                 for family, model in result["models"].items() if model.get("parameters")}
    selected = result.get("validation_024", {}).get("selected_model_before_validation") or result.get("recommendation", {}).get("model")
    return _score_validation(operators, prepared, selected,
                             source_hash=result.get("input_hash"), current_hash=snapshot.get("input_hash"))


def _score_validation(operators: dict, prepared: _Prepared, selected: str | None,
                      *, source_hash: str | None, current_hash: str | None) -> dict:
    frozen = {family: [{"record_id": row["record_id"], "material_symbol": row["material_symbol"], "backing": row["backing"],
                        "overlay_mm": row["overlay_mm"], "predicted_percent_xyz": predicted.tolist()}
                       for row, predicted in zip(prepared.validation, _predict_rows(operator, prepared.validation), strict=True)]
              for family, operator in operators.items()}
    digest = hashlib.sha256(json.dumps(frozen, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    available = {(row["material_symbol"], row["backing"]) for row in (*prepared.validation, *prepared.controls)
                 if abs(row["overlay_mm"] - VALIDATION_THICKNESS_MM) <= 1e-8}
    missing = sorted(f"{symbol}:{backing}" for symbol in prepared.present for backing in ("W", "K")
                     if (symbol, backing) not in available)
    artifact = {"status": "frozen_and_scored", "used_for_training": False, "complete": not missing,
                "missing_pairs": missing,
                "selected_model_before_validation": selected, "prediction_hash": digest,
                "source_fit_input_hash": source_hash, "current_validation_input_hash": current_hash,
                "sample_record_ids": [row["record_id"] for row in prepared.validation],
                "predictions": {}, "metrics": {}, "passed": None}
    for family in operators:
        predicted = np.array([row["predicted_percent_xyz"] for row in frozen[family]])
        artifact["predictions"][family] = _record_predictions(prepared.validation, predicted, training=False)
        artifact["metrics"][family] = _metrics(prepared.validation, predicted)
    artifact["controls"] = _control_summary(
        [row for row in prepared.controls if abs(row["overlay_mm"] - VALIDATION_THICKNESS_MM) <= 1e-8],
        operators, prepared.anchors,
    )
    artifact["control_record_ids"] = [row["record_id"] for row in artifact["controls"]["rows"]]
    if selected in artifact["metrics"]:
        artifact["passed"] = not missing and all(value <= 2 for value in artifact["metrics"][selected]["per_material_rmse_pp"].values())
    return artifact


def _control_summary(rows: Sequence[dict], operators: dict, anchors: dict) -> dict:
    records, deviations = [], []
    for row in rows:
        observed = np.array(row["reflectance_percent_xyz"])
        predictions = {family: operator.predict_backed(row["material_symbol"], row["backing"], row["overlay_mm"]).tolist()
                       for family, operator in operators.items()}
        residuals = {family: (np.asarray(predicted) - observed).tolist() for family, predicted in predictions.items()}
        records.append({**row, "observed_percent_xyz": observed.tolist(),
                        "predicted_by_model": predictions, "residual_by_model": residuals})
        deviations.extend((observed - anchors[row["backing"]]).tolist())
    return {"count": len(records), "rows": records, "used_for_optimization": False,
            "rms_deviation_pp": float(np.sqrt(np.mean(np.square(deviations)))) if deviations else None,
            "max_abs_deviation_pp": float(np.max(np.abs(deviations))) if deviations else None}


def _assess_stability(models: dict, operators: dict, alternatives: dict, comparison: dict | None) -> None:
    for family, operator in operators.items():
        info = {}
        for backing in ("W", "K"):
            if comparison:
                info[backing] = comparison["envelopes"][backing][family]
            else:
                info[backing] = {key: value for key, value in prediction_envelope(operator, alternatives[family], backing).items()
                                 if key != "rows"}
        stable = all(value["xyz_width_p95_pp"] <= 2 and value["delta_e00_p95"] <= 2
                     and value["xyz_width_max_pp"] <= 5 and value["delta_e00_max"] <= 5 for value in info.values())
        blind = prediction_envelope(operator, alternatives[family], "W", BLIND_RECIPES)
        stable = stable and blind["xyz_width_max_pp"] <= 2 and blind["delta_e00_max"] <= 2
        models[family]["stability"].update(
            status="stable" if stable else "unstable", per_backing=info,
            blind_recipe_envelope={key: value for key, value in blind.items() if key != "rows"},
            thresholds={"p95_xyz_pp": 2., "p95_delta_e00": 2., "max_xyz_pp": 5.,
                        "max_delta_e00": 5., "blind_max_xyz_pp": 2., "blind_max_delta_e00": 2.},
        )
        if not stable:
            discriminating = []
            for backing in ("W", "K"):
                for thickness in (3 - value for value in THICKNESSES_MM):
                    predictions = np.array([candidate.report(candidate.latent_material(backing, thickness))
                                            for candidate in (operator, *alternatives[family])])
                    width = np.ptp(predictions, axis=0)
                    discriminating.append((float(width.max()), backing, thickness, width.tolist()))
            spread, backing, thickness, width = max(discriminating)
            models[family]["stability"]["next_measurement"] = {
                "sample_role": "backing_only_diagnostic", "material_symbol": backing,
                "thickness_mm": float(thickness), "predicted_xyz_width_pp": width,
                "selection": "largest_explored_backing_only_spread", "not_required_before_initial_capture": True,
            }


def _choose(models: dict) -> tuple[str | None, str]:
    if not models["affine"].get("cv"):
        return None, "incomplete_models"
    baseline, candidate = models["affine"]["cv"], models["two_flux"]["cv"]
    if (models["affine"]["status"] == "converged" and baseline["optimizer_converged"]
            and baseline["overall_rmse_pp"] <= 2 and all(value <= 2 for value in baseline["per_material_rmse_pp"].values())):
        return "affine", "baseline_within_tolerance"
    if not candidate or models["two_flux"]["status"] != "converged" or not candidate["optimizer_converged"]:
        return None, "incomplete_models"
    improvement = baseline["overall_rmse_pp"] - candidate["overall_rmse_pp"]
    if (all(value <= 2 for value in candidate["per_material_rmse_pp"].values()) and improvement >= .5
            and candidate["overall_rmse_pp"] <= .8 * baseline["overall_rmse_pp"]):
        return "two_flux", "candidate_improves_held_out"
    return None, "candidate_does_not_meet_quality"


def fit_backed_gradient(snapshot: dict, *, include_validation_thickness: bool = False,
                        progress: Callable[[str, float], None] | None = None,
                        time_budget_seconds: float = 240.) -> dict:
    """Fit paired finite backings and freeze unseen .24 predictions before scoring.
    拟合成对有限背板，并在评分前冻结未参与训练的零点二四毫米预测。

    Args:
        snapshot: Immutable selected input records and independent bare anchors.
            （选定输入快照和独立裸锚。）
        include_validation_thickness: Explicit separate full-seven run.
            （明确独立运行包含验证厚度的七点拟合。）
        progress: Optional bounded progress callback.（可选进度回调。）
        time_budget_seconds: Whole fit/CV/profile time allowance.（整体时间额度。）

    Returns:
        Portable pure-JSON research result, without changing active archives.
            （可移植纯 JSON 研究结果，不更改活动档案。）
    """
    if (not isinstance(include_validation_thickness, bool) or isinstance(time_budget_seconds, bool)
            or not isinstance(time_budget_seconds, (int, float))
            or not np.isfinite(time_budget_seconds) or time_budget_seconds <= 0):
        raise CoreValidationError("Invalid backed-gradient fitting options")
    callback = progress or (lambda _stage, _value: None)
    prepared = _prepare(snapshot, include_validation_thickness)
    deadline = time.monotonic() + time_budget_seconds
    models, alternatives, operators = {}, {}, {}
    for index, family in enumerate(MODEL_IDS):
        start = .02 + index * .4
        callback(f"{family}_full_fit", start)
        try:
            operator, attempts, endpoints = _fit_operator(family, prepared, prepared.training, deadline)
            cv = _cross_validation(family, prepared, deadline, callback, start + .05, start + .27)
            callback(f"{family}_parameter_profiles", start + .28)
            profile_models, evaluations = _profiles(operator, prepared, endpoints, deadline)
            operators[family] = operator
            alternatives[family] = profile_models
            best_attempt = min((attempt for attempt in attempts if "rmse_pp" in attempt), key=lambda attempt: attempt["rmse_pp"])
            models[family] = {"status": "converged" if best_attempt["success"] else "exploratory", "model_id": MODEL_IDS[family],
                              "optimizer_converged": best_attempt["success"],
                              "parameter_count": len(_coordinates(family, prepared.present)) * 3,
                              "parameters": operator.to_parameters(), "attempts": attempts, "cv": cv,
                              "sample_predictions": _record_predictions(prepared.training, _predict_rows(operator, prepared.training), training=True),
                              "training_metrics": _metrics(prepared.training, _predict_rows(operator, prepared.training)),
                              "stability": {"status": "not_available", "accepted_parameter_sets": len(profile_models),
                                            "profile_evaluations": evaluations, "near_equivalent_rmse_increase_pp": .2,
                                            "scope": "explored_coordinate_profiles_not_a_confidence_bound"}}
        except CoreValidationError as error:
            models[family] = {"status": "failed", "model_id": MODEL_IDS[family], "parameters": None, "cv": None,
                              "sample_predictions": [], "stability": {"status": "not_available"}, "error": str(error)}
    selected, reason = _choose(models)
    callback("freezing_validation", .85)
    validation = {"status": "included_in_training" if include_validation_thickness else "not_available",
                  "used_for_training": include_validation_thickness, "selected_model_before_validation": selected,
                  "prediction_hash": None, "predictions": {}, "metrics": {}, "passed": None}
    if prepared.validation:
        validation = _score_validation(operators, prepared, selected, source_hash=snapshot.get("input_hash"), current_hash=snapshot.get("input_hash"))
        if selected and not validation["passed"]:
            selected, reason = None, "validation_024_failed"
    complete = set(CORE_MATERIAL_SYMBOLS).issubset(prepared.present)
    comparison = build_comparison(models, alternatives=alternatives) if complete else None
    if complete:
        _assess_stability(models, operators, alternatives, comparison)
        if selected and models[selected]["stability"]["status"] != "stable":
            selected, reason = None, "prediction_stability_failed"
    else:
        selected, reason = None, "missing_materials"
    controls = _control_summary(prepared.controls, operators, prepared.anchors)
    controls["rms_threshold_pp"] = 2.
    controls["consistent"] = controls["rms_deviation_pp"] is None or controls["rms_deviation_pp"] <= 2
    if selected and not controls["consistent"]:
        selected, reason = None, "homogeneous_controls_failed"
    callback("comparison_ready", .99)
    return {"schema_version": "1.0", "kind": "lumina_box_backed_gradient_fit",
            "dataset_id": snapshot.get("dataset_id"), "dataset_revision": snapshot.get("dataset_revision"),
            "input_hash": snapshot.get("input_hash"), "training_input_hash": _training_digest(prepared),
            "fit_mode": "full_seven" if include_validation_thickness else "frozen_six",
            "models": models, "recommendation": {"model": selected, "status": "recommended" if selected else "exploratory", "reason": reason},
            "validation_024": validation, "controls": controls, "comparison": comparison,
            "missing_materials": [symbol for symbol in CORE_MATERIAL_SYMBOLS if symbol not in prepared.present],
            "conditions": snapshot.get("conditions", {}), "selected_record_ids": snapshot.get("selected_record_ids", []),
            "scope": "research_fitting_and_comparison_only", "conversion_enabled": False}
