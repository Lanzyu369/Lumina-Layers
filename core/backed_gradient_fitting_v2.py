"""Shared spectral optimizer primitives for production material calibration.
供正式耗材标定使用的共享光谱优化基础函数。
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
from scipy.optimize import least_squares

from core import backed_gradient_fitting as shared
from core.backed_gradient_models import BackedGradientModel
from core.backed_gradient_smooth import BackedGradientSmoothTransport
from core.backed_gradient_transport import BackedGradientTransport
from core.errors import CoreValidationError

MAX_EVALUATIONS = 350
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
