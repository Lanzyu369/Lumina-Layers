from __future__ import annotations

from typing import Any

import numpy as np

from .color_metrics import delta_e_2000, gray_patch_metrics, linear_srgb_to_lab
from .color_models import apply_color_model


class InsufficientValidPatchesError(ValueError):
    def __init__(self, diagnostics: dict[str, object]) -> None:
        valid_count = int(diagnostics.get("valid_patch_count") or 0)
        patch_count = int(diagnostics.get("patch_count") or 0)
        required = int(diagnostics.get("minimum_valid_patch_count") or 6)
        pipeline = str(diagnostics.get("pipeline") or diagnostics.get("source_type") or "")
        exposure_action = "提高 RAW 曝光" if pipeline == "raw_strict" or pipeline == "raw" else "提高曝光"
        super().__init__(
            f"可用于拟合的有效色块不足：有效 {valid_count}/{patch_count}，至少需要 {required} 个。"
            f"请检查采样点是否落在色块中心、减小采样半径，或{exposure_action}。"
        )
        self.diagnostics = diagnostics


def round_list(values: np.ndarray, digits: int = 6) -> list[float]:
    return [round(float(v), digits) for v in np.asarray(values).reshape(-1).tolist()]


def clipping_reasons(sample: dict[str, Any], *, black_mode: str = "channel") -> list[str]:
    reasons: list[str] = []
    p99_rgb = np.asarray(sample.get("percentile_99_rgb"), dtype=np.float64)
    if p99_rgb.ndim == 1 and p99_rgb.size >= 3:
        p99_rgb = p99_rgb[:3]
        if black_mode == "luminance":
            p99_luminance = float(sample.get("percentile_99_luminance") or 0.0)
            if p99_luminance <= 0.000001:
                reasons.append("black_clipped")
        elif bool(np.any(p99_rgb <= 0.000001)):
            reasons.append("black_clipped")
        if bool(np.any(p99_rgb >= 0.995)):
            reasons.append("white_clipped")
    return reasons


def is_nonuniform(sample: dict[str, Any]) -> bool:
    mean_rgb = np.asarray(sample["mean_rgb"], dtype=np.float64)
    std_rgb = np.asarray(sample["std_rgb"], dtype=np.float64)
    luminance = float(np.mean(mean_rgb))
    if luminance < 1e-5:
        return True
    return bool(float(np.mean(std_rgb)) / luminance > 0.35)


def patch_diagnostic(detail: dict[str, object]) -> dict[str, object]:
    return {
        "index": detail.get("index"),
        "label": detail.get("label"),
        "fit_used": bool(detail.get("fit_used")),
        "exclude_reasons": list(detail.get("exclude_reasons") or []),
        "point": detail.get("point"),
        "measured_linear_rgb": detail.get("measured_linear_rgb"),
        "measured_linear_camera_rgb": detail.get("measured_linear_camera_rgb"),
        "sample_mean_rgb": detail.get("sample_mean_rgb"),
        "sample_min_rgb": detail.get("sample_min_rgb"),
        "sample_max_rgb": detail.get("sample_max_rgb"),
        "sample_percentile_1_rgb": detail.get("sample_percentile_1_rgb"),
        "sample_percentile_99_rgb": detail.get("sample_percentile_99_rgb"),
        "sample_mean_linear_camera_rgb": detail.get("sample_mean_linear_camera_rgb"),
        "sample_min_linear_camera_rgb": detail.get("sample_min_linear_camera_rgb"),
        "sample_max_linear_camera_rgb": detail.get("sample_max_linear_camera_rgb"),
        "sample_percentile_1_linear_camera_rgb": detail.get("sample_percentile_1_linear_camera_rgb"),
        "sample_percentile_99_linear_camera_rgb": detail.get("sample_percentile_99_linear_camera_rgb"),
        "sample_percentile_1_luminance": detail.get("sample_percentile_1_luminance"),
        "sample_percentile_99_luminance": detail.get("sample_percentile_99_luminance"),
        "sample_black_clipped_ratio": detail.get("sample_black_clipped_ratio"),
        "sample_white_clipped_ratio": detail.get("sample_white_clipped_ratio"),
        "sample_std_rgb": detail.get("sample_std_rgb"),
        "sample_std_linear_camera_rgb": detail.get("sample_std_linear_camera_rgb"),
        "sample_bounds": detail.get("sample_bounds"),
        "sample_pixel_count": detail.get("sample_pixel_count"),
    }


def patch_validity_report(patch_details: list[dict[str, object]]) -> dict[str, object]:
    valid = [patch_diagnostic(detail) for detail in patch_details if not detail.get("exclude_reasons")]
    invalid = [patch_diagnostic(detail) for detail in patch_details if detail.get("exclude_reasons")]
    reason_counts: dict[str, int] = {}
    for detail in invalid:
        for reason in detail.get("exclude_reasons") or []:
            reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + 1
    risk_level = "none"
    if invalid:
        risk_level = "high" if len(invalid) >= max(1, len(patch_details) // 4) else "warning"
    return {
        "patch_count": len(patch_details),
        "valid_patch_count": len(valid),
        "invalid_patch_count": len(invalid),
        "risk_level": risk_level,
        "reason_counts": reason_counts,
        "valid_patches": valid,
        "invalid_patches": invalid,
    }


def fit_patch_diagnostics(
    patch_details: list[dict[str, object]],
    *,
    minimum_valid_patch_count: int,
) -> dict[str, object]:
    validity = patch_validity_report(patch_details)
    return {
        "reason": "insufficient_valid_patches",
        "minimum_valid_patch_count": int(minimum_valid_patch_count),
        **validity,
    }


def patch_validity_warning(validity: dict[str, object], *, exposure_label: str = "exposure") -> str | None:
    invalid_count = int(validity.get("invalid_patch_count") or 0)
    patch_count = int(validity.get("patch_count") or 0)
    if invalid_count <= 0 or patch_count <= 0:
        return None
    reason_counts = validity.get("reason_counts")
    reason_text = ""
    if isinstance(reason_counts, dict) and reason_counts:
        reason_text = ", ".join(f"{reason}={count}" for reason, count in sorted(reason_counts.items()))
    detail = f" ({reason_text})" if reason_text else ""
    return (
        f"Patch validity risk: {invalid_count}/{patch_count} patches were excluded from fitting{detail}. "
        "The PNG was generated from the remaining patches only; check patch placement, orientation, "
        f"sample radius, and {exposure_label} before trusting the result."
    )


def _neutral_axis_level(rgb: np.ndarray) -> np.ndarray:
    return np.median(np.asarray(rgb, dtype=np.float64), axis=-1)


def _relative_luminance_y(linear_rgb: np.ndarray) -> np.ndarray:
    weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)
    return np.asarray(linear_rgb, dtype=np.float64) @ weights


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if abs(float(denominator)) <= 1e-12:
        return None
    return float(numerator) / float(denominator)


def _safe_pearson_r(x_values: np.ndarray, y_values: np.ndarray) -> float | None:
    x = np.asarray(x_values, dtype=np.float64).reshape(-1)
    y = np.asarray(y_values, dtype=np.float64).reshape(-1)
    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]
    y = y[finite]
    if x.size < 2:
        return None
    x_centered = x - float(np.mean(x))
    y_centered = y - float(np.mean(y))
    denominator = float(np.linalg.norm(x_centered) * np.linalg.norm(y_centered))
    if denominator <= 1e-14:
        return None
    return float(np.dot(x_centered, y_centered) / denominator)


def _round_optional(value: float | None, digits: int = 6) -> float | None:
    if value is None or not np.isfinite(float(value)):
        return None
    return round(float(value), digits)


def _luminance_correlations(
    reference_level: np.ndarray,
    captured_level: np.ndarray,
    normalized_level: np.ndarray,
    corrected_level: np.ndarray,
    rows: list[int],
) -> dict[str, float | None | int]:
    if not rows:
        return {
            "patch_count": 0,
            "reference_vs_captured_r": None,
            "reference_vs_normalized_r": None,
            "reference_vs_corrected_r": None,
        }
    row_arr = np.asarray(rows, dtype=np.int64)
    return {
        "patch_count": int(row_arr.size),
        "reference_vs_captured_r": _round_optional(_safe_pearson_r(reference_level[row_arr], captured_level[row_arr]), 6),
        "reference_vs_normalized_r": _round_optional(_safe_pearson_r(reference_level[row_arr], normalized_level[row_arr]), 6),
        "reference_vs_corrected_r": _round_optional(_safe_pearson_r(reference_level[row_arr], corrected_level[row_arr]), 6),
    }


def build_luminance_diagnostics(
    *,
    patch_details: list[dict[str, object]],
    reference_linear: np.ndarray,
    measured_wb: np.ndarray,
    measured_model_input: np.ndarray,
    corrected_patches: np.ndarray,
    fit_mask: np.ndarray,
    gray_rows: list[int],
    gray_affine: dict[str, object],
    captured_level_source: str = "neutral-axis coordinate in white-balanced camera RGB",
    normalized_level_source: str = "neutral-axis coordinate after gray affine normalization",
) -> dict[str, object]:
    reference_level = _relative_luminance_y(reference_linear)
    captured_level = _neutral_axis_level(measured_wb)
    normalized_level = _neutral_axis_level(measured_model_input)
    corrected_level = _relative_luminance_y(corrected_patches)
    valid_rows = [row for row, used in enumerate(fit_mask.tolist()) if bool(used)]
    valid_gray_rows = [row for row in gray_rows if 0 <= row < len(fit_mask) and bool(fit_mask[row])]
    gray_x = captured_level[valid_gray_rows] if valid_gray_rows else np.array([], dtype=np.float64)
    x_min = float(np.min(gray_x)) if gray_x.size else float(np.min(captured_level))
    x_max = float(np.max(gray_x)) if gray_x.size else float(np.max(captured_level))
    if abs(x_max - x_min) <= 1e-12:
        x_max = x_min + 1e-6
    scale = float(gray_affine.get("scale") or 1.0)
    offset = float(gray_affine.get("offset") or 0.0)

    patches: list[dict[str, object]] = []
    gray_row_set = set(valid_gray_rows)
    for row, detail in enumerate(patch_details):
        ref_value = float(reference_level[row])
        captured_value = float(captured_level[row])
        normalized_value = float(normalized_level[row])
        corrected_value = float(corrected_level[row])
        patches.append(
            {
                "index": int(detail.get("index") or row + 1),
                "label": str(detail.get("label") or row + 1),
                "fit_used": bool(fit_mask[row]),
                "is_gray_patch": bool(row in gray_row_set),
                "reference_level": _round_optional(ref_value, 8),
                "captured_level": _round_optional(captured_value, 8),
                "normalized_level": _round_optional(normalized_value, 8),
                "corrected_level": _round_optional(corrected_value, 8),
                "reference_over_captured_ratio": _round_optional(_safe_ratio(ref_value, captured_value), 8),
                "reference_over_normalized_ratio": _round_optional(_safe_ratio(ref_value, normalized_value), 8),
                "reference_over_corrected_ratio": _round_optional(_safe_ratio(ref_value, corrected_value), 8),
            }
        )

    return {
        "reference_level_source": "linear_srgb_relative_luminance_y",
        "captured_level_source": captured_level_source,
        "normalized_level_source": normalized_level_source,
        "corrected_level_source": "linear_srgb_relative_luminance_y_after_color_model",
        "plot_axes": {
            "x": "captured_or_corrected_level",
            "y": "reference_level",
        },
        "gray_fit": {
            "enabled": bool(gray_affine.get("enabled")),
            "scale": _round_optional(scale, 8),
            "offset": _round_optional(offset, 8),
            "intercept": _round_optional(float(gray_affine.get("intercept") or 0.0), 8),
            "line_points": [
                {
                    "captured_level": _round_optional(x_min, 8),
                    "fitted_reference_level": _round_optional(scale * (x_min - offset), 8),
                },
                {
                    "captured_level": _round_optional(x_max, 8),
                    "fitted_reference_level": _round_optional(scale * (x_max - offset), 8),
                },
            ],
        },
        "correlation": {
            "all_patches": _luminance_correlations(
                reference_level,
                captured_level,
                normalized_level,
                corrected_level,
                valid_rows,
            ),
            "gray_patches": _luminance_correlations(
                reference_level,
                captured_level,
                normalized_level,
                corrected_level,
                valid_gray_rows,
            ),
        },
        "patches": patches,
    }


def gray_affine_post_fit_failures(
    *,
    legacy_model_input: np.ndarray,
    affine_model_input: np.ndarray,
    reference_linear: np.ndarray,
    reference_lab: np.ndarray,
    fit_mask: np.ndarray,
    used_gray_indices: list[int],
    legacy_model: dict[str, object],
    affine_model: dict[str, object],
    target_white_point: str,
) -> list[str]:
    gray_rows = [idx - 1 for idx in used_gray_indices if 0 < idx <= len(fit_mask) and bool(fit_mask[idx - 1])]
    if not gray_rows:
        return []

    legacy_corrected = apply_color_model(legacy_model_input, legacy_model)
    affine_corrected = apply_color_model(affine_model_input, affine_model)
    legacy_lab = linear_srgb_to_lab(np.clip(legacy_corrected, 0.0, 1.0), target_white_point)
    affine_lab = linear_srgb_to_lab(np.clip(affine_corrected, 0.0, 1.0), target_white_point)
    legacy_gray_metrics = gray_patch_metrics(legacy_lab[gray_rows], [row + 1 for row in gray_rows])
    affine_gray_metrics = gray_patch_metrics(affine_lab[gray_rows], [row + 1 for row in gray_rows])

    failures: list[str] = []
    black_row = min(gray_rows, key=lambda row: float(np.median(reference_linear[row])))
    legacy_black_de = float(delta_e_2000(legacy_lab[black_row], reference_lab[black_row]))
    affine_black_de = float(delta_e_2000(affine_lab[black_row], reference_lab[black_row]))
    if affine_black_de > legacy_black_de + 0.5:
        failures.append(
            f"gray affine black patch DeltaE00 {affine_black_de:.4f} is worse than legacy 3x3 {legacy_black_de:.4f}"
        )

    if legacy_gray_metrics.get("l_monotonic") is True and affine_gray_metrics.get("l_monotonic") is False:
        failures.append("gray affine makes gray patch L* monotonicity worse than legacy 3x3")
    for key, label in (("a_abs_max", "|a*|"), ("b_abs_max", "|b*|")):
        legacy_value = legacy_gray_metrics.get(key)
        affine_value = affine_gray_metrics.get(key)
        if legacy_value is None or affine_value is None:
            continue
        if float(affine_value) > max(2.5, float(legacy_value) + 0.75):
            failures.append(
                f"gray affine makes neutral gray {label} worse: {float(affine_value):.4f} vs legacy {float(legacy_value):.4f}"
            )
    return failures
