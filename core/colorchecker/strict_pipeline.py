from __future__ import annotations

from dataclasses import dataclass
import cv2
import numpy as np
from .color_metrics import (
    delta_e_76,
    delta_e_94,
    delta_e_2000,
    delta_lch,
    gray_patch_metrics,
    lab_to_linear_srgb,
    linear_srgb_to_lab,
    linear_to_srgb,
    summarize_values,
)
from .color_models import (
    apply_color_model,
    check_affine_bias_gate,
    check_exposure_invariance,
    fit_color_model,
    normalize_calibration_mode,
)
from .diagnostics import (
    InsufficientValidPatchesError,
    build_luminance_diagnostics as _build_luminance_diagnostics,
    clipping_reasons as _clipping_reasons,
    fit_patch_diagnostics as _fit_patch_diagnostics,
    gray_affine_post_fit_failures as _gray_affine_post_fit_failures,
    is_nonuniform as _is_nonuniform,
    patch_validity_report as _patch_validity_report,
    patch_validity_warning as _patch_validity_warning,
    round_list as _round_list,
)
from .gray_normalization import (
    apply_gray_affine_mode,
    apply_gray_affine_normalization,
    disable_gray_affine_normalization,
    estimate_gray_affine_normalization,
    normalize_gray_affine_mode,
)
from .pipeline import render_preview_overlay, warp_colorchecker_preview
from .raw_strict import decode_strict_raw_bytes, gaussian_blur_linear_rgb
from .sampling import normalize_sampling_filter, sample_patch


@dataclass(frozen=True)
class StrictCalibrationRun:
    calibrated_image: np.ndarray
    preview_image: np.ndarray
    preview_overlay_image: np.ndarray
    report: dict[str, object]
    ordered_corners: list[dict[str, float]]
    patch_details: list[dict[str, object]]
    model: dict[str, object]


def _reference_arrays(reference_patches: list[dict[str, object]], target_white_point: str) -> tuple[np.ndarray, np.ndarray, list[str]]:
    labs: list[np.ndarray] = []
    linear: list[np.ndarray] = []
    labels: list[str] = []
    lab_key = "Lab_d50" if target_white_point.upper() == "D50" else "Lab_d65"
    for patch in reference_patches:
        lab_raw = patch.get(lab_key)
        if not isinstance(lab_raw, list) or len(lab_raw) < 3:
            raise ValueError(f"参考色块 {patch.get('index')} 缺少 {lab_key}。")
        lab = np.asarray(lab_raw[:3], dtype=np.float64)
        labs.append(lab)
        linear.append(lab_to_linear_srgb(lab, target_white_point))
        labels.append(str(patch.get("label") or patch.get("index")))
    return np.stack(linear, axis=0), np.stack(labs, axis=0), labels


def _image_to_bgr8(linear_rgb: np.ndarray) -> np.ndarray:
    srgb = np.clip(linear_to_srgb(np.clip(linear_rgb, 0.0, 1.0)), 0.0, 1.0)
    return (srgb[..., ::-1] * 255.0 + 0.5).astype(np.uint8)


def _estimate_white_balance(
    measured: np.ndarray,
    reference_linear: np.ndarray,
    details: list[dict[str, object]],
) -> tuple[np.ndarray, list[int], list[dict[str, object]]]:
    used: list[int] = []
    excluded: list[dict[str, object]] = []
    for row, detail in enumerate(details):
        patch_index = int(detail["index"])
        if patch_index < 19 or patch_index > 24:
            continue
        reasons = list(detail.get("exclude_reasons") or [])
        luminance = float(np.mean(measured[row]))
        if luminance < 1e-5 and "too_dark" not in reasons:
            reasons.append("too_dark")
        if reasons:
            excluded.append({"index": patch_index, "label": detail["label"], "reasons": reasons})
            continue
        used.append(row)
    if len(used) < 2:
        raise ValueError("RAW strict 模式可用灰阶色块不足，无法估计 white balance。")

    measured_gray = measured[used]
    reference_gray = np.clip(reference_linear[used], 1e-8, None)
    measured_chroma = measured_gray / np.maximum(np.mean(measured_gray, axis=1, keepdims=True), 1e-8)
    reference_chroma = reference_gray / np.maximum(np.mean(reference_gray, axis=1, keepdims=True), 1e-8)
    ratios = reference_chroma / np.maximum(measured_chroma, 1e-8)
    wb = np.median(ratios, axis=0)
    wb = wb / max(float(np.prod(np.maximum(wb, 1e-8)) ** (1.0 / 3.0)), 1e-8)
    return wb.astype(np.float64), [int(details[row]["index"]) for row in used], excluded


def _model_with_gates(
    measured_model_input: np.ndarray,
    reference_linear: np.ndarray,
    mode: str,
    forced: bool,
    base_model: dict[str, object] | None,
    gray_affine_enabled: bool = False,
) -> dict[str, object]:
    selected = fit_color_model(
        measured_model_input,
        reference_linear,
        model_type=mode,
        weights="perceptual",
        regularization=1e-3,
    )
    gate_failures: list[str] = []
    if mode == "matrix_3x4":
        bias_threshold = 0.01 if gray_affine_enabled else 0.025
        gate_failures.extend(check_affine_bias_gate(selected, threshold=bias_threshold))
        if gray_affine_enabled and gate_failures:
            gate_failures.append(
                "3x4 affine bias remains active after gray affine normalization; treat this expert result as untrusted unless the bias gate is resolved."
            )
        gate_failures.extend(check_exposure_invariance(measured_model_input, selected))
    elif mode == "root_polynomial":
        gate_failures.extend(check_exposure_invariance(measured_model_input, selected, threshold=0.04))
    selected["gate_failures"] = gate_failures
    if gate_failures:
        selected["warnings"] = [
            *(selected.get("warnings") or []),
            *gate_failures,
        ]
    if gate_failures and not forced and base_model is not None:
        fallback = dict(base_model)
        fallback["warnings"] = [
            *(fallback.get("warnings") or []),
            f"Auto fallback to 3x3 because {mode} failed model gates.",
        ]
        fallback["gate_failures"] = gate_failures
        return fallback
    return selected


def calibrate_strict_raw(
    raw_bytes: bytes,
    *,
    file_name: str,
    corners: list[dict[str, float]],
    patch_points: list[dict[str, float]],
    reference_patches: list[dict[str, object]],
    reference_source: dict[str, object],
    preview_width: int = 720,
    preview_height: int = 480,
    sample_radius: int = 12,
    sampling_filter: object = None,
    calibration_mode: object = "matrix_3x3",
    gray_affine_mode: object = "auto",
    blur_radius: float = 0.0,
    target_white_point: str = "D50",
) -> StrictCalibrationRun:
    if len(corners) != 4:
        raise ValueError("请先点击 4 个角点。")
    if len(patch_points) != len(reference_patches):
        raise ValueError(f"请按顺序完成 {len(reference_patches)} 个色块点击。")
    mode = normalize_calibration_mode(calibration_mode)
    gray_affine_mode_value = normalize_gray_affine_mode(gray_affine_mode)
    blur_radius = float(max(0.0, blur_radius))
    sampling_config = normalize_sampling_filter(sampling_filter)

    strict = decode_strict_raw_bytes(raw_bytes, file_name=file_name)
    chart_linear, _homography, ordered = warp_colorchecker_preview(
        strict.linear_rgb,
        corners,
        int(preview_width),
        int(preview_height),
    )
    chart_preview_bgr = _image_to_bgr8(chart_linear)
    reference_linear, reference_lab, _labels = _reference_arrays(reference_patches, target_white_point)

    measured: list[np.ndarray] = []
    patch_details: list[dict[str, object]] = []
    for point, reference in zip(patch_points, reference_patches):
        sample = sample_patch(chart_linear, point, int(sample_radius), sampling_config)
        rgb = np.asarray(sample["rgb"], dtype=np.float64)
        reasons: list[str] = _clipping_reasons(sample)
        if _is_nonuniform(sample):
            reasons.append("nonuniform_or_too_dark")
        measured.append(rgb)
        measured_srgb = np.clip(linear_to_srgb(np.clip(rgb, 0.0, 1.0)), 0.0, 1.0)
        patch_details.append(
            {
                "index": int(reference["index"]),
                "label": str(reference["label"]),
                "point": {"x": float(point["x"]), "y": float(point["y"])},
                "measured_linear_camera_rgb": _round_list(rgb),
                "measured_sRGB": [int(round(float(v * 255.0))) for v in measured_srgb.tolist()],
                "sample_mean_linear_camera_rgb": _round_list(np.asarray(sample["mean_rgb"])),
                "sample_min_linear_camera_rgb": _round_list(np.asarray(sample["min_rgb"])),
                "sample_max_linear_camera_rgb": _round_list(np.asarray(sample["max_rgb"])),
                "sample_percentile_1_linear_camera_rgb": _round_list(np.asarray(sample["percentile_1_rgb"])),
                "sample_percentile_99_linear_camera_rgb": _round_list(np.asarray(sample["percentile_99_rgb"])),
                "sample_percentile_1_luminance": round(float(sample["percentile_1_luminance"]), 8),
                "sample_percentile_99_luminance": round(float(sample["percentile_99_luminance"]), 8),
                "sample_black_clipped_ratio": round(float(sample["black_clipped_ratio"]), 8),
                "sample_white_clipped_ratio": round(float(sample["white_clipped_ratio"]), 8),
                "sample_std_linear_camera_rgb": _round_list(np.asarray(sample["std_rgb"])),
                "sample_bounds": sample["bounds"],
                "sample_pixel_count": int(sample["pixel_count"]),
                "sample_rejected_pixel_count": int(sample["rejected_pixel_count"]),
                "reference_sRGB": list(reference["sRGB"]),
                "reference_Lab_d50": list(reference["Lab_d50"]),
                "reference_Lab_d65": list(reference["Lab_d65"]),
                "exclude_reasons": reasons,
                "fit_used": not reasons,
            }
        )
    measured_arr = np.stack(measured, axis=0)
    fit_mask = np.asarray([not detail["exclude_reasons"] for detail in patch_details], dtype=bool)
    patch_validity = _patch_validity_report(patch_details)
    minimum_valid_patch_count = 6
    if np.count_nonzero(fit_mask) < minimum_valid_patch_count:
        diagnostics = _fit_patch_diagnostics(
            patch_details,
            minimum_valid_patch_count=minimum_valid_patch_count,
        )
        diagnostics["pipeline"] = "raw_strict"
        diagnostics["sampling_filter"] = sampling_config
        diagnostics["sample_radius"] = int(sample_radius)
        diagnostics["raw_decoder"] = strict.metadata
        raise InsufficientValidPatchesError(diagnostics)

    wb_multipliers, used_gray_indices, excluded_gray = _estimate_white_balance(
        measured_arr,
        reference_linear,
        patch_details,
    )
    measured_wb = measured_arr * wb_multipliers
    gray_rows = [idx - 1 for idx in used_gray_indices]
    gray_affine = estimate_gray_affine_normalization(
        measured_wb,
        reference_linear,
        patch_details=patch_details,
        used_gray_rows=gray_rows,
        min_valid_gray_patches=4,
    )
    gray_affine = apply_gray_affine_mode(gray_affine, gray_affine_mode_value)
    image_wb = strict.linear_rgb.astype(np.float64) * wb_multipliers
    legacy_exposure_scale = float(gray_affine.get("legacy_exposure_scale") or 1.0)
    legacy_model_input = measured_wb * legacy_exposure_scale
    measured_model_input = apply_gray_affine_normalization(measured_wb, gray_affine)
    image_model_input = apply_gray_affine_normalization(image_wb, gray_affine)
    gray_input_rows = [row for row in gray_rows if 0 <= row < measured_model_input.shape[0]]
    gray_negative_ratio = (
        float(np.mean(measured_model_input[gray_input_rows] < -1e-8)) if gray_input_rows else 0.0
    )
    gray_affine["gray_patch_negative_channel_ratio"] = round(gray_negative_ratio, 8)
    if bool(gray_affine.get("enabled")) and gray_negative_ratio > 0.0:
        failure = f"gray affine creates negative channels in gray patches ratio={gray_negative_ratio:.4%}"
        if gray_affine_mode_value == "auto":
            gray_affine = disable_gray_affine_normalization(gray_affine, [failure])
            measured_model_input = legacy_model_input
            image_model_input = image_wb * legacy_exposure_scale
        else:
            gray_affine["forced_negative_channel_failures"] = [failure]

    legacy_base_model = fit_color_model(
        legacy_model_input[fit_mask],
        reference_linear[fit_mask],
        model_type="matrix_3x3",
        weights="perceptual",
        regularization=1e-3,
    )
    base_model = fit_color_model(
        measured_model_input[fit_mask],
        reference_linear[fit_mask],
        model_type="matrix_3x3",
        weights="perceptual",
        regularization=1e-3,
    )
    if bool(gray_affine.get("enabled")):
        post_fit_failures = _gray_affine_post_fit_failures(
            legacy_model_input=legacy_model_input,
            affine_model_input=measured_model_input,
            reference_linear=reference_linear,
            reference_lab=reference_lab,
            fit_mask=fit_mask,
            used_gray_indices=used_gray_indices,
            legacy_model=legacy_base_model,
            affine_model=base_model,
            target_white_point=target_white_point,
        )
        if post_fit_failures:
            if gray_affine_mode_value == "auto":
                gray_affine = disable_gray_affine_normalization(gray_affine, post_fit_failures)
                measured_model_input = legacy_model_input
                image_model_input = image_wb * legacy_exposure_scale
                base_model = legacy_base_model
            else:
                gray_affine["forced_post_fit_failures"] = post_fit_failures
    if mode == "auto":
        model = dict(base_model)
        model["warnings"] = [
            *(model.get("warnings") or []),
            "Auto mode currently uses the recommended 3x3 matrix baseline.",
        ]
    elif mode == "matrix_3x3":
        model = base_model
    else:
        model = _model_with_gates(
            measured_model_input[fit_mask],
            reference_linear[fit_mask],
            mode,
            forced=True,
            base_model=base_model,
            gray_affine_enabled=bool(gray_affine.get("enabled")),
        )

    corrected_patches = apply_color_model(measured_model_input, model)
    corrected_lab = linear_srgb_to_lab(np.clip(corrected_patches, 0.0, 1.0), target_white_point)
    delta_e00 = delta_e_2000(corrected_lab[fit_mask], reference_lab[fit_mask])
    delta_e76 = delta_e_76(corrected_lab[fit_mask], reference_lab[fit_mask])
    delta_e94 = delta_e_94(reference_lab[fit_mask], corrected_lab[fit_mask])
    lch = delta_lch(reference_lab, corrected_lab)
    fit_summary = summarize_values(delta_e00.tolist())
    fit_summary_76 = summarize_values(delta_e76.tolist())
    fit_summary_94 = summarize_values(delta_e94.tolist())
    gray_metrics = gray_patch_metrics(corrected_lab[gray_rows], used_gray_indices)
    luminance_diagnostics = _build_luminance_diagnostics(
        patch_details=patch_details,
        reference_linear=reference_linear,
        measured_wb=measured_wb,
        measured_model_input=measured_model_input,
        corrected_patches=corrected_patches,
        fit_mask=fit_mask,
        gray_rows=gray_rows,
        gray_affine=gray_affine,
    )

    warnings: list[str] = list(model.get("warnings") or [])
    validity_warning = _patch_validity_warning(patch_validity, exposure_label="RAW exposure")
    if validity_warning:
        warnings.append(validity_warning)
    if fit_summary["mean"] is not None and float(fit_summary["mean"]) > 2.0:
        warnings.append(f"fit mean ΔE00 {fit_summary['mean']} exceeds suggested 2.0 threshold.")
    if fit_summary["median"] is not None and float(fit_summary["median"]) > 1.5:
        warnings.append(f"fit median ΔE00 {fit_summary['median']} exceeds suggested 1.5 threshold.")
    if fit_summary["p95"] is not None and float(fit_summary["p95"]) > 3.0:
        warnings.append(f"fit P95 ΔE00 {fit_summary['p95']} exceeds suggested 3.0 threshold.")
    if fit_summary["max"] is not None and float(fit_summary["max"]) > 4.0:
        warnings.append(f"fit max ΔE00 {fit_summary['max']} exceeds suggested 4.0 threshold.")
    if gray_metrics.get("l_monotonic") is False:
        warnings.append("Neutral gray L* values are not monotonic.")
    if gray_metrics.get("a_abs_max") is not None and float(gray_metrics["a_abs_max"]) > 1.5:
        warnings.append("Neutral gray |a*| exceeds suggested 1.5 threshold.")
    if gray_metrics.get("b_abs_max") is not None and float(gray_metrics["b_abs_max"]) > 1.5:
        warnings.append("Neutral gray |b*| exceeds suggested 1.5 threshold.")

    corrected_linear = apply_color_model(image_model_input, model)
    negative_ratio = float(np.mean(corrected_linear < 0.0))
    over_ratio = float(np.mean(corrected_linear > 1.0))
    if negative_ratio > 0.01:
        warnings.append(f"Corrected image negative channel ratio is {negative_ratio:.4%}.")
    if over_ratio > 0.01:
        warnings.append(f"Corrected image gamut clipping ratio is {over_ratio:.4%}.")
    output_linear = np.clip(corrected_linear, 0.0, 1.0)
    if blur_radius > 0.0:
        output_linear = np.clip(gaussian_blur_linear_rgb(output_linear, blur_radius), 0.0, 1.0)
    calibrated_bgr = _image_to_bgr8(output_linear)

    for row, detail in enumerate(patch_details):
        corrected = np.clip(corrected_patches[row], 0.0, 1.0)
        corrected_srgb = np.clip(linear_to_srgb(corrected), 0.0, 1.0)
        detail["white_balanced_linear_rgb"] = _round_list(measured_wb[row])
        detail["exposure_normalized_linear_rgb"] = _round_list(measured_model_input[row])
        detail["gray_affine_normalized_linear_rgb"] = _round_list(measured_model_input[row])
        detail["corrected_linear_rgb"] = _round_list(corrected)
        detail["corrected_sRGB"] = [int(round(float(v * 255.0))) for v in corrected_srgb.tolist()]
        detail[f"corrected_Lab_{target_white_point.lower()}"] = _round_list(corrected_lab[row], 4)
        detail["deltaE76"] = round(float(delta_e_76(corrected_lab[row], reference_lab[row])), 4)
        detail["deltaE94"] = round(float(delta_e_94(reference_lab[row], corrected_lab[row])), 4)
        detail["deltaE00"] = round(float(delta_e_2000(corrected_lab[row], reference_lab[row])), 4)
        detail["deltaL"] = round(float(lch["delta_l"][row]), 4)
        detail["deltaC"] = round(float(lch["delta_c"][row]), 4)
        detail["deltaH"] = round(float(lch["delta_h"][row]), 4)

    calibrated_chart_linear, _, _ = warp_colorchecker_preview(
        output_linear,
        corners,
        int(preview_width),
        int(preview_height),
    )
    calibrated_chart_bgr = _image_to_bgr8(calibrated_chart_linear)
    overlay = render_preview_overlay(calibrated_chart_bgr, patch_details, int(sample_radius))
    ordered_corners = [
        {"x": round(float(point[0]), 2), "y": round(float(point[1]), 2)}
        for point in ordered.tolist()
    ]
    report: dict[str, object] = {
        "pipeline": "raw_strict",
        "patch_count": len(patch_details),
        "sample_radius": int(sample_radius),
        "method": "strict_raw_linear",
        "sampling_filter": sampling_config,
        "blur_radius": blur_radius,
        "gray_affine_mode": gray_affine_mode_value,
        "corners": ordered_corners,
        "raw_decoder": strict.metadata,
        "reference_source": reference_source,
        "reference_serial_number": reference_source.get("serial_number"),
        "target_white_point": target_white_point.upper(),
        "black_level": strict.metadata.get("black_level_per_channel"),
        "white_level": strict.metadata.get("white_level"),
        "clipping": strict.metadata.get("clipping"),
        "white_balance": {
            "multipliers": _round_list(wb_multipliers, 8),
            "used_gray_patches": used_gray_indices,
            "excluded_gray_patches": excluded_gray,
        },
        "wb_multipliers": _round_list(wb_multipliers, 8),
        "exposure_scale": round(float(gray_affine.get("scale") or legacy_exposure_scale), 8),
        "legacy_exposure_scale": round(float(legacy_exposure_scale), 8),
        "gray_affine_normalization": gray_affine,
        "selected_model": model.get("model_type"),
        "model": model,
        "model_coefficients": model.get("coefficients"),
        "feature_definition": model.get("feature_definition"),
        "combined_transform": {
            "wb_multipliers": _round_list(wb_multipliers, 8),
            "exposure_scale": round(float(gray_affine.get("scale") or legacy_exposure_scale), 8),
            "gray_affine_normalization": {
                "enabled": bool(gray_affine.get("enabled")),
                "mode": gray_affine_mode_value,
                "scale": float(gray_affine.get("scale") or legacy_exposure_scale),
                "offset": float(gray_affine.get("offset") or 0.0),
            },
            "model_type": model.get("model_type"),
            "coefficients": model.get("coefficients"),
            "affine_matrix": model.get("affine_matrix"),
        },
        "fit_metrics": {
            "delta_e00": fit_summary,
            "delta_e76": fit_summary_76,
            "delta_e94": fit_summary_94,
            "patch_count": int(np.count_nonzero(fit_mask)),
        },
        "patch_validity": patch_validity,
        "stats": {
            "mean_delta_e": fit_summary["mean"],
            "median_delta_e": fit_summary["median"],
            "p95_delta_e": fit_summary["p95"],
            "max_delta_e": fit_summary["max"],
            "mean_delta_e76": fit_summary_76["mean"],
            "median_delta_e76": fit_summary_76["median"],
            "p95_delta_e76": fit_summary_76["p95"],
            "max_delta_e76": fit_summary_76["max"],
            "mean_delta_e94": fit_summary_94["mean"],
            "median_delta_e94": fit_summary_94["median"],
            "p95_delta_e94": fit_summary_94["p95"],
            "max_delta_e94": fit_summary_94["max"],
        },
        "gray_patch_metrics": gray_metrics,
        "luminance_diagnostics": luminance_diagnostics,
        "gamut_clipping": {
            "negative_channel_ratio": round(negative_ratio, 8),
            "over_one_channel_ratio": round(over_ratio, 8),
        },
        "highlight_rolloff": {
            "method": "none",
            "reason": "strict_raw_output_preserves_linear_calibration; bounded PNG export clips out-of-range values",
        },
        "warnings": warnings,
        "degradation_reason": "; ".join(warnings) if warnings else None,
        "output_generated": True,
        "patches": patch_details,
    }
    return StrictCalibrationRun(
        calibrated_image=calibrated_bgr,
        preview_image=chart_preview_bgr,
        preview_overlay_image=overlay,
        report=report,
        ordered_corners=ordered_corners,
        patch_details=patch_details,
        model=model,
    )
