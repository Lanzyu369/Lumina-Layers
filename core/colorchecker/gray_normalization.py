from __future__ import annotations

from typing import Iterable, Literal

import numpy as np


GRAY_PATCH_MIN_INDEX = 19
GRAY_PATCH_MAX_INDEX = 24
GrayAffineMode = Literal["auto", "enabled", "fallback"]


def _round_float(value: float | None, digits: int = 8) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _neutral_axis_level(rgb: np.ndarray, method: str) -> np.ndarray:
    arr = np.asarray(rgb, dtype=np.float64)
    if method == "mean":
        return np.mean(arr, axis=-1)
    if method == "median":
        return np.median(arr, axis=-1)
    raise ValueError("neutral_axis_method must be median or mean.")


def _weighted_rmse(actual: np.ndarray, predicted: np.ndarray, weights: np.ndarray) -> float:
    residual = np.asarray(actual, dtype=np.float64) - np.asarray(predicted, dtype=np.float64)
    return float(np.sqrt(np.average(residual * residual, weights=weights)))


def _weighted_r2(actual: np.ndarray, predicted: np.ndarray, weights: np.ndarray) -> float:
    actual_arr = np.asarray(actual, dtype=np.float64)
    predicted_arr = np.asarray(predicted, dtype=np.float64)
    mean = float(np.average(actual_arr, weights=weights))
    ss_tot = float(np.sum(weights * (actual_arr - mean) ** 2))
    ss_res = float(np.sum(weights * (actual_arr - predicted_arr) ** 2))
    if ss_tot <= 1e-14:
        return 1.0 if ss_res <= 1e-14 else 0.0
    return float(1.0 - ss_res / ss_tot)


def _ratio_span(reference: np.ndarray, measured: np.ndarray) -> float | None:
    measured_safe = np.asarray(measured, dtype=np.float64)
    if bool(np.any(measured_safe <= 1e-10)):
        return None
    ratios = np.asarray(reference, dtype=np.float64) / measured_safe
    if ratios.size == 0 or not bool(np.all(np.isfinite(ratios))):
        return None
    return float(np.max(ratios) - np.min(ratios))


def normalize_gray_affine_mode(mode: object) -> GrayAffineMode:
    value = str(mode or "auto").strip().lower().replace("-", "_")
    aliases = {
        "": "auto",
        "default": "auto",
        "on": "enabled",
        "enable": "enabled",
        "force_enabled": "enabled",
        "forced_enabled": "enabled",
        "true": "enabled",
        "开启": "enabled",
        "off": "fallback",
        "disable": "fallback",
        "disabled": "fallback",
        "force_fallback": "fallback",
        "forced_fallback": "fallback",
        "false": "fallback",
        "回退": "fallback",
    }
    value = aliases.get(value, value)
    if value not in {"auto", "enabled", "fallback"}:
        raise ValueError("gray_affine_mode must be auto, enabled, or fallback.")
    return value  # type: ignore[return-value]


def _finite_float(value: object, fallback: float) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float(fallback)
    return parsed if np.isfinite(parsed) else float(fallback)


def _fit_through_origin(measured: np.ndarray, reference: np.ndarray, weights: np.ndarray) -> float:
    denominator = float(np.sum(weights * measured * measured))
    if denominator <= 1e-14:
        return 1.0
    return float(np.clip(np.sum(weights * measured * reference) / denominator, 0.05, 20.0))


def _fit_affine(measured: np.ndarray, reference: np.ndarray, weights: np.ndarray) -> tuple[float, float]:
    design = np.column_stack([measured, np.ones_like(measured)])
    weighted_design = design * np.sqrt(weights)[:, None]
    weighted_reference = reference * np.sqrt(weights)
    coefficients, *_ = np.linalg.lstsq(weighted_design, weighted_reference, rcond=None)
    return float(coefficients[0]), float(coefficients[1])


def _rows_from_patch_details(patch_details: list[dict[str, object]] | None) -> list[int]:
    if not patch_details:
        return []
    rows: list[int] = []
    for row, detail in enumerate(patch_details):
        patch_index = int(detail.get("index") or 0)
        if patch_index < GRAY_PATCH_MIN_INDEX or patch_index > GRAY_PATCH_MAX_INDEX:
            continue
        if detail.get("exclude_reasons"):
            continue
        rows.append(row)
    return rows


def _patch_indices_for_rows(rows: Iterable[int], patch_details: list[dict[str, object]] | None) -> list[int]:
    indices: list[int] = []
    for row in rows:
        if patch_details and 0 <= row < len(patch_details):
            indices.append(int(patch_details[row].get("index") or row + 1))
        else:
            indices.append(int(row + 1))
    return indices


def _is_monotonic_like_reference(values: np.ndarray, reference: np.ndarray, tolerance: float = 1e-8) -> bool:
    value_diff = np.diff(np.asarray(values, dtype=np.float64))
    reference_diff = np.diff(np.asarray(reference, dtype=np.float64))
    reference_direction = float(np.sum(reference_diff))
    if abs(reference_direction) <= tolerance:
        return True
    if reference_direction < 0.0:
        return bool(np.all(value_diff <= tolerance))
    return bool(np.all(value_diff >= -tolerance))


def disable_gray_affine_normalization(
    normalization: dict[str, object],
    failures: list[str],
) -> dict[str, object]:
    updated = dict(normalization)
    legacy_scale = float(updated.get("legacy_exposure_scale") or updated.get("scale") or 1.0)
    existing_failures = []
    gates = updated.get("gates")
    if isinstance(gates, dict):
        existing_failures = [str(item) for item in gates.get("failures") or []]
    merged_failures = [*existing_failures]
    for failure in failures:
        if failure not in merged_failures:
            merged_failures.append(failure)
    updated["enabled"] = False
    updated["scale"] = float(legacy_scale)
    updated["offset"] = 0.0
    updated["intercept"] = 0.0
    updated["gates"] = {"passed": False, "failures": merged_failures}
    updated["fallback_reason"] = "; ".join(merged_failures) if merged_failures else "gray_affine_disabled"
    return updated


def apply_gray_affine_mode(
    normalization: dict[str, object],
    mode: GrayAffineMode,
) -> dict[str, object]:
    if mode == "auto":
        updated = dict(normalization)
        updated["mode"] = "auto"
        updated["requested_mode"] = "auto"
        updated["forced"] = False
        return updated

    if mode == "fallback":
        updated = disable_gray_affine_normalization(
            normalization,
            ["gray affine fallback forced by user mode"],
        )
        updated["mode"] = "fallback"
        updated["requested_mode"] = "fallback"
        updated["forced"] = True
        return updated

    updated = dict(normalization)
    fallback_scale = _finite_float(
        updated.get("scale"),
        _finite_float(updated.get("legacy_exposure_scale"), 1.0),
    )
    scale = _finite_float(updated.get("estimated_scale"), fallback_scale)
    offset = _finite_float(updated.get("estimated_offset"), _finite_float(updated.get("offset"), 0.0))
    intercept = _finite_float(updated.get("estimated_intercept"), -scale * offset)
    gates = updated.get("gates")
    failures = []
    if isinstance(gates, dict):
        failures = [str(item) for item in gates.get("failures") or []]

    updated["mode"] = "enabled"
    updated["requested_mode"] = "enabled"
    updated["forced"] = True
    updated["enabled"] = True
    updated["scale"] = float(scale)
    updated["offset"] = float(offset)
    updated["intercept"] = float(intercept)
    updated["fallback_reason"] = None
    updated["gates"] = {
        "passed": len(failures) == 0,
        "failures": failures,
        "overridden_by_mode": len(failures) > 0,
    }
    return updated


def estimate_gray_affine_normalization(
    measured_wb: np.ndarray,
    reference_linear_rgb: np.ndarray,
    *,
    patch_details: list[dict[str, object]] | None = None,
    used_gray_rows: list[int] | None = None,
    min_valid_gray_patches: int = 4,
    neutral_axis_method: str = "median",
    max_offset_black_level_ratio: float = 0.85,
) -> dict[str, object]:
    measured_arr = np.asarray(measured_wb, dtype=np.float64)
    reference_arr = np.asarray(reference_linear_rgb, dtype=np.float64)
    if measured_arr.ndim != 2 or measured_arr.shape[1] != 3:
        raise ValueError("measured_wb must have shape Nx3.")
    if reference_arr.shape != measured_arr.shape:
        raise ValueError("reference_linear_rgb must have the same Nx3 shape.")

    rows = list(used_gray_rows or _rows_from_patch_details(patch_details))
    rows = [row for row in rows if 0 <= row < measured_arr.shape[0]]
    patch_indices = _patch_indices_for_rows(rows, patch_details)
    failures: list[str] = []

    if len(rows) < min_valid_gray_patches:
        failures.append(
            f"insufficient valid gray patches: {len(rows)}/{min_valid_gray_patches}"
        )

    if not rows:
        return {
            "mode": "auto",
            "enabled": False,
            "method": "neutral_gray_affine",
            "scale": 1.0,
            "offset": 0.0,
            "intercept": 0.0,
            "legacy_exposure_scale": 1.0,
            "input_space": "white_balanced_linear_camera_rgb",
            "input_coordinate": "neutral-axis coordinate in white-balanced camera RGB",
            "neutral_axis_method": neutral_axis_method,
            "reference_gray_level_source": "reference_linear_rgb_neutral_axis",
            "applied_before": "color_model",
            "used_gray_patches": patch_indices,
            "min_valid_gray_patches": int(min_valid_gray_patches),
            "fit": {
                "affine_r2": None,
                "through_origin_r2_before": None,
                "pure_gain_rmse": None,
                "affine_rmse": None,
                "affine_vs_gain_improvement": None,
                "ratio_span_before": None,
                "ratio_span_after": None,
            },
            "gates": {"passed": False, "failures": failures},
            "fallback_reason": "; ".join(failures) if failures else "no_valid_gray_patches",
        }

    measured_level = _neutral_axis_level(measured_arr[rows], neutral_axis_method)
    reference_level = np.clip(_neutral_axis_level(reference_arr[rows], neutral_axis_method), 1e-10, None)
    weights = np.ones_like(reference_level, dtype=np.float64)

    pure_gain = _fit_through_origin(measured_level, reference_level, weights)
    pure_predicted = pure_gain * measured_level
    estimated_scale, estimated_intercept = _fit_affine(measured_level, reference_level, weights)
    estimated_offset = -estimated_intercept / estimated_scale if abs(estimated_scale) > 1e-14 else 0.0

    black_level = float(np.min(measured_level)) if measured_level.size else 0.0
    max_offset = black_level * float(max_offset_black_level_ratio)
    offset_capped = bool(np.isfinite(estimated_offset) and estimated_offset > max_offset)

    candidates: list[tuple[float, float, float, np.ndarray, np.ndarray, float, float | None]] = []

    def add_candidate(offset_value: float) -> None:
        shifted_measured = measured_level - float(offset_value)
        if bool(np.any(shifted_measured <= 1e-10)):
            return
        scale_value = _fit_through_origin(shifted_measured, reference_level, weights)
        intercept_value = -scale_value * float(offset_value)
        predicted_value = scale_value * shifted_measured
        rmse_value = _weighted_rmse(reference_level, predicted_value, weights)
        span_value = _ratio_span(reference_level, predicted_value)
        candidates.append(
            (
                float(offset_value),
                float(scale_value),
                float(intercept_value),
                predicted_value,
                scale_value * shifted_measured,
                float(rmse_value),
                span_value,
            )
        )

    add_candidate(0.0)
    if np.isfinite(estimated_offset) and 0.0 <= estimated_offset <= max_offset:
        add_candidate(float(estimated_offset))
    if max_offset > 0.0:
        for offset_value in np.linspace(0.0, max_offset, 81):
            add_candidate(float(offset_value))

    if candidates:
        affine_offset, affine_scale, affine_intercept, affine_predicted, normalized_level, affine_rmse, ratio_after = min(
            candidates,
            key=lambda candidate: (
                float("inf") if candidate[6] is None else float(candidate[6]),
                candidate[5],
            ),
        )
    else:
        affine_offset = 0.0
        affine_scale = pure_gain
        affine_intercept = 0.0
        affine_predicted = pure_predicted
        normalized_level = pure_predicted
        affine_rmse = _weighted_rmse(reference_level, pure_predicted, weights)
        ratio_after = _ratio_span(reference_level, normalized_level)
    affine_predicted = affine_scale * measured_level + affine_intercept
    normalized_level = affine_scale * (measured_level - affine_offset)

    pure_rmse = _weighted_rmse(reference_level, pure_predicted, weights)
    affine_rmse = _weighted_rmse(reference_level, affine_predicted, weights)
    improvement = 0.0 if pure_rmse <= 1e-14 else float((pure_rmse - affine_rmse) / pure_rmse)
    ratio_before = _ratio_span(reference_level, measured_level)
    ratio_after = _ratio_span(reference_level, normalized_level)

    if not np.isfinite(estimated_scale) or estimated_scale <= 0.0:
        failures.append(f"affine scale must be positive; got {estimated_scale:.6g}")
    if not np.isfinite(estimated_offset):
        failures.append("affine offset is not finite")
    elif estimated_offset < -1e-6:
        failures.append(f"affine offset must be non-negative; got {estimated_offset:.6g}")
    if offset_capped and not bool(np.all(measured_level - affine_offset > 1e-10)):
        failures.append(
            f"bounded affine offset {affine_offset:.6g} leaves non-positive measured gray levels"
        )
    if not _is_monotonic_like_reference(normalized_level, reference_level):
        failures.append("normalized gray levels are not monotonic with reference gray levels")
    if bool(np.any(normalized_level <= 1e-8)):
        failures.append("normalized gray levels include non-positive values")
    if affine_rmse > pure_rmse + 1e-8:
        failures.append("affine gray fit is worse than pure gain baseline")

    enabled = not failures
    scale = affine_scale if enabled else pure_gain
    offset = affine_offset if enabled else 0.0
    intercept = affine_intercept if enabled else 0.0
    return {
        "mode": "auto",
        "enabled": bool(enabled),
        "method": "neutral_gray_affine",
        "scale": float(scale),
        "offset": float(offset),
        "intercept": float(intercept),
        "estimated_scale": float(affine_scale),
        "estimated_offset": float(affine_offset),
        "estimated_intercept": float(affine_intercept),
        "unbounded_estimated_scale": float(estimated_scale),
        "unbounded_estimated_offset": float(estimated_offset),
        "unbounded_estimated_intercept": float(estimated_intercept),
        "legacy_exposure_scale": float(pure_gain),
        "input_space": "white_balanced_linear_camera_rgb",
        "input_coordinate": "neutral-axis coordinate in white-balanced camera RGB",
        "neutral_axis_method": neutral_axis_method,
        "reference_gray_level_source": "reference_linear_rgb_neutral_axis",
        "applied_before": "color_model",
        "used_gray_patches": patch_indices,
        "min_valid_gray_patches": int(min_valid_gray_patches),
        "constraints": {
            "max_offset_black_level_ratio": float(max_offset_black_level_ratio),
            "measured_black_gray_level": float(black_level),
            "max_offset": float(max_offset),
            "offset_capped": bool(offset_capped),
        },
        "fit": {
            "affine_r2": _round_float(_weighted_r2(reference_level, affine_predicted, weights), 8),
            "through_origin_r2_before": _round_float(_weighted_r2(reference_level, pure_predicted, weights), 8),
            "pure_gain_rmse": _round_float(pure_rmse, 8),
            "affine_rmse": _round_float(affine_rmse, 8),
            "affine_vs_gain_improvement": _round_float(improvement, 8),
            "ratio_span_before": _round_float(ratio_before, 8),
            "ratio_span_after": _round_float(ratio_after, 8),
        },
        "gates": {"passed": bool(enabled), "failures": failures},
        "fallback_reason": None if enabled else "; ".join(failures),
    }


def apply_gray_affine_normalization(linear_rgb: np.ndarray, normalization: dict[str, object]) -> np.ndarray:
    arr = np.asarray(linear_rgb, dtype=np.float64)
    scale = float(normalization.get("scale") or 1.0)
    offset = float(normalization.get("offset") or 0.0)
    return scale * (arr - offset)
