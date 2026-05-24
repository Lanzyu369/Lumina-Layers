from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np

from .calibration_core import (
    linear_to_srgb,
    srgb_to_linear,
)
from .color_metrics import (
    delta_e_76,
    delta_e_94,
    delta_e_2000,
    delta_lch,
    gray_patch_metrics,
    linear_srgb_to_lab,
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
    build_luminance_diagnostics,
    clipping_reasons,
    fit_patch_diagnostics,
    gray_reference_delta_metrics,
    gray_reference_delta_warnings,
    gray_affine_post_fit_failures,
    is_nonuniform,
    patch_validity_report,
    patch_validity_warning,
    round_list,
)
from .gray_normalization import (
    apply_gray_affine_mode,
    apply_gray_affine_normalization,
    disable_gray_affine_normalization,
    estimate_gray_affine_normalization,
    normalize_gray_affine_mode,
)
from .image_io import image_to_uint8_display
from .sampling import normalize_sampling_filter, sample_patch

DEFAULT_PREVIEW_WIDTH = 720
DEFAULT_PREVIEW_HEIGHT = 480


@dataclass(frozen=True)
class CalibrationRun:
    calibrated_image: np.ndarray
    preview_image: np.ndarray
    preview_overlay_image: np.ndarray
    report: dict[str, object]
    ccm: np.ndarray
    ordered_corners: list[dict[str, float]]
    patch_details: list[dict[str, object]]


def order_quad(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    ordered = np.zeros((4, 2), dtype=np.float32)
    ordered[0] = pts[np.argmin(s)]
    ordered[2] = pts[np.argmax(s)]
    ordered[1] = pts[np.argmin(diff)]
    ordered[3] = pts[np.argmax(diff)]
    return ordered


def generate_patch_points(
    preview_width: int = DEFAULT_PREVIEW_WIDTH,
    preview_height: int = DEFAULT_PREVIEW_HEIGHT,
    *,
    patch_layout: Literal["4x6", "3x8"] = "4x6",
    patch_count: int = 24,
) -> list[dict[str, float]]:
    if patch_layout == "3x8":
        rows, cols = 3, 8
    elif patch_layout == "4x6":
        rows, cols = 4, 6
    else:
        raise ValueError("patch_layout must be '4x6' or '3x8'.")
    step_x = float(preview_width) / cols
    step_y = float(preview_height) / rows
    points = []
    for row in range(rows):
        for col in range(cols):
            points.append(
                {
                    "x": round((col + 0.5) * step_x, 2),
                    "y": round((row + 0.5) * step_y, 2),
                }
            )
    return points[:patch_count]


def orient_patch_points(
    patch_points: list[dict[str, float]],
    *,
    patch_layout: Literal["4x6", "3x8"] = "4x6",
    orientation: str = "normal",
) -> list[dict[str, float]]:
    if patch_layout == "3x8":
        rows, cols = 3, 8
    elif patch_layout == "4x6":
        rows, cols = 4, 6
    else:
        raise ValueError("patch_layout must be '4x6' or '3x8'.")
    if len(patch_points) != rows * cols:
        return patch_points
    orientation = (orientation or "normal").strip().lower()
    if orientation not in {"normal", "rotate_180", "flip_horizontal", "flip_vertical"}:
        raise ValueError("patchOrientation must be normal, rotate_180, flip_horizontal, or flip_vertical.")

    def physical_index(row: int, col: int) -> int:
        if orientation == "rotate_180":
            return (rows - 1 - row) * cols + (cols - 1 - col)
        if orientation == "flip_horizontal":
            return row * cols + (cols - 1 - col)
        if orientation == "flip_vertical":
            return (rows - 1 - row) * cols + col
        return row * cols + col

    oriented: list[dict[str, float]] = []
    for ref_row in range(rows):
        for ref_col in range(cols):
            oriented.append(dict(patch_points[physical_index(ref_row, ref_col)]))
    return oriented


def warp_colorchecker_preview(
    image: np.ndarray,
    corners: list[dict[str, float]],
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ordered = order_quad(np.array([[p["x"], p["y"]] for p in corners], dtype=np.float32))
    target = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    homography = cv2.getPerspectiveTransform(ordered, target)
    warped = cv2.warpPerspective(image, homography, (width, height))
    return warped, homography, ordered


def sample_patch_bgr(
    image: np.ndarray,
    point: dict[str, float],
    radius: int,
    method: str,
) -> np.ndarray:
    h, w = image.shape[:2]
    x = int(round(float(point["x"])))
    y = int(round(float(point["y"])))
    x0 = max(0, x - radius)
    y0 = max(0, y - radius)
    x1 = min(w, x + radius + 1)
    y1 = min(h, y + radius + 1)
    if x0 >= x1 or y0 >= y1:
        raise ValueError("色块采样点超出预览范围。")
    patch = image[y0:y1, x0:x1]
    if patch.size == 0:
        raise ValueError("色块采样区域为空。")
    if method == "median":
        return np.median(patch.reshape(-1, 3), axis=0)
    return patch.reshape(-1, 3).mean(axis=0)


def build_patch_measurements(
    preview: np.ndarray,
    patch_points: list[dict[str, float]],
    radius: int,
    method: str,
    reference_patches: list[dict[str, object]],
    sampling_filter: object | None = None,
) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    max_val = 65535.0 if preview.dtype == np.uint16 else 255.0
    sampling_config = normalize_sampling_filter(
        sampling_filter
        if sampling_filter is not None
        else {"strategy": "median" if method == "median" else "none"}
    )
    preview_rgb_norm = np.clip(preview[..., ::-1].astype(np.float32) / max_val, 0.0, 1.0)
    patch_colors: dict[str, dict[str, object]] = {}
    details: list[dict[str, object]] = []
    for point, reference in zip(patch_points, reference_patches):
        label = str(reference["label"])
        sample = sample_patch(preview_rgb_norm, point, radius, sampling_config)
        rgb_norm = np.clip(np.asarray(sample["rgb"], dtype=np.float32), 0.0, 1.0)
        reasons = clipping_reasons(sample, black_mode="luminance")
        if is_nonuniform(sample):
            reasons.append("nonuniform_or_too_dark")
        rgb_linear = srgb_to_linear(rgb_norm)
        rgb_u8 = [
            int(round(float(np.clip(v * 255.0, 0.0, 255.0))))
            for v in rgb_norm.tolist()
        ]
        patch_colors[label] = {
            "index": int(reference["index"]),
            "sRGB": rgb_u8,
            "linear_rgb": [float(v) for v in rgb_linear.tolist()],
            "exclude_reasons": reasons,
            "fit_used": not reasons,
        }
        details.append(
            {
                "index": int(reference["index"]),
                "label": label,
                "point": {"x": float(point["x"]), "y": float(point["y"])},
                "measured_sRGB": rgb_u8,
                "measured_linear_rgb": [round(float(v), 6) for v in rgb_linear.tolist()],
                "sample_mean_rgb": round_list(np.asarray(sample["mean_rgb"])),
                "sample_min_rgb": round_list(np.asarray(sample["min_rgb"])),
                "sample_max_rgb": round_list(np.asarray(sample["max_rgb"])),
                "sample_percentile_1_rgb": round_list(np.asarray(sample["percentile_1_rgb"])),
                "sample_percentile_99_rgb": round_list(np.asarray(sample["percentile_99_rgb"])),
                "sample_percentile_1_luminance": round(float(sample["percentile_1_luminance"]), 8),
                "sample_percentile_99_luminance": round(float(sample["percentile_99_luminance"]), 8),
                "sample_black_clipped_ratio": round(float(sample["black_clipped_ratio"]), 8),
                "sample_white_clipped_ratio": round(float(sample["white_clipped_ratio"]), 8),
                "sample_std_rgb": round_list(np.asarray(sample["std_rgb"])),
                "sample_bounds": sample["bounds"],
                "sample_pixel_count": int(sample["pixel_count"]),
                "sample_rejected_pixel_count": int(sample["rejected_pixel_count"]),
                "reference_sRGB": list(reference["sRGB"]),
                "reference_Lab_d65": list(reference["Lab_d65"]),
                "exclude_reasons": reasons,
                "fit_used": not reasons,
            }
        )
    return patch_colors, details


def enrich_patch_details(
    details: list[dict[str, object]],
    ccm: np.ndarray,
) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []
    for item in details:
        lin = item.get("measured_linear_rgb")
        if lin is not None:
            measured_linear = np.asarray(lin, dtype=np.float32)
        else:
            measured = np.asarray(item["measured_sRGB"], dtype=np.float32) / 255.0
            measured_linear = srgb_to_linear(measured)
        corrected_linear = np.clip(measured_linear @ ccm, 0.0, 1.0)
        corrected_srgb = [
            int(round(float(np.clip(v * 255.0, 0.0, 255.0))))
            for v in linear_to_srgb(corrected_linear).tolist()
        ]
        corrected_lab = np.asarray(linear_srgb_to_lab(corrected_linear, "D65"), dtype=np.float64)
        ref_lab = np.asarray(item["reference_Lab_d65"], dtype=np.float32)
        delta_e = float(np.linalg.norm(corrected_lab - ref_lab))
        delta_e00 = float(delta_e_2000(corrected_lab, ref_lab))
        enriched_item = dict(item)
        enriched_item["corrected_sRGB"] = corrected_srgb
        enriched_item["corrected_Lab_d65"] = [round(float(v), 2) for v in corrected_lab.tolist()]
        enriched_item["deltaE_d65"] = round(delta_e, 4)
        enriched_item["deltaE00"] = round(delta_e00, 4)
        enriched.append(enriched_item)
    return enriched


def enrich_patch_details_with_model(
    details: list[dict[str, object]],
    corrected_linear: np.ndarray,
    reference_lab: np.ndarray,
    *,
    metric_mask: np.ndarray | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    corrected_clipped = np.clip(corrected_linear, 0.0, 1.0)
    corrected_lab = linear_srgb_to_lab(corrected_clipped, "D65")
    delta_e00 = delta_e_2000(corrected_lab, reference_lab)
    delta_e76 = delta_e_76(corrected_lab, reference_lab)
    delta_e94 = delta_e_94(reference_lab, corrected_lab)
    delta_e_d65 = np.linalg.norm(corrected_lab - reference_lab, axis=-1)
    lch = delta_lch(reference_lab, corrected_lab)
    if metric_mask is None:
        metric_mask_arr = np.ones(delta_e00.shape[0], dtype=bool)
    else:
        metric_mask_arr = np.asarray(metric_mask, dtype=bool)
    enriched: list[dict[str, object]] = []
    for row, item in enumerate(details):
        corrected_srgb = [
            int(round(float(np.clip(v * 255.0, 0.0, 255.0))))
            for v in linear_to_srgb(corrected_clipped[row]).tolist()
        ]
        enriched_item = dict(item)
        enriched_item["corrected_sRGB"] = corrected_srgb
        enriched_item["corrected_Lab_d65"] = [round(float(v), 2) for v in corrected_lab[row].tolist()]
        enriched_item["deltaE00"] = round(float(delta_e00[row]), 4)
        enriched_item["deltaE76"] = round(float(delta_e76[row]), 4)
        enriched_item["deltaE94"] = round(float(delta_e94[row]), 4)
        enriched_item["deltaE_d65"] = round(float(delta_e_d65[row]), 4)
        enriched_item["deltaL"] = round(float(lch["delta_l"][row]), 4)
        enriched_item["deltaC"] = round(float(lch["delta_c"][row]), 4)
        enriched_item["deltaH"] = round(float(lch["delta_h"][row]), 4)
        enriched.append(enriched_item)
    return enriched, {
        "delta_e00": summarize_values(delta_e00[metric_mask_arr].tolist()),
        "delta_e76": summarize_values(delta_e76[metric_mask_arr].tolist()),
        "delta_e94": summarize_values(delta_e94[metric_mask_arr].tolist()),
        "delta_e_d65": summarize_values(delta_e_d65[metric_mask_arr].tolist()),
    }


def _legacy_delta_e_stats(patch_count: int, summary: dict[str, float | None]) -> dict[str, object]:
    return {
        "patch_count": int(patch_count),
        "mean_delta_e": summary["mean"],
        "median_delta_e": summary["median"],
        "p95_delta_e": summary["p95"],
        "max_delta_e": summary["max"],
    }


def apply_color_model_to_image_bgr(
    image_bgr: np.ndarray,
    model: dict[str, object],
    *,
    gray_affine_normalization: dict[str, object] | None = None,
    blur_radius: float = 0.0,
    chunk_rows: int = 512,
) -> np.ndarray:
    max_val = 65535.0 if image_bgr.dtype == np.uint16 else 255.0
    rgb = image_bgr[..., ::-1].astype(np.float32) / max_val
    linear_rgb = srgb_to_linear(rgb)
    if gray_affine_normalization is not None:
        linear_rgb = apply_gray_affine_normalization(linear_rgb, gray_affine_normalization)
    corrected = np.empty_like(linear_rgb, dtype=np.float64)
    for y0 in range(0, linear_rgb.shape[0], max(1, int(chunk_rows))):
        y1 = min(y0 + int(chunk_rows), linear_rgb.shape[0])
        corrected[y0:y1] = apply_color_model(linear_rgb[y0:y1], model)
    corrected = np.clip(corrected, 0.0, 1.0)
    if blur_radius > 0.0:
        corrected = cv2.GaussianBlur(
            corrected.astype(np.float32),
            (0, 0),
            sigmaX=float(blur_radius),
            sigmaY=float(blur_radius),
            borderType=cv2.BORDER_REFLECT_101,
        )
    srgb = linear_to_srgb(np.clip(corrected, 0.0, 1.0))
    return np.clip(srgb[..., ::-1] * 255.0, 0, 255).astype(np.uint8)


def apply_ccm_to_image_bgr(
    image_bgr: np.ndarray,
    ccm: np.ndarray,
    *,
    blur_radius: float = 0.0,
) -> np.ndarray:
    max_val = 65535.0 if image_bgr.dtype == np.uint16 else 255.0
    rgb = image_bgr[..., ::-1].astype(np.float32) / max_val
    linear_rgb = srgb_to_linear(rgb)
    corrected = np.clip(linear_rgb @ ccm, 0.0, 1.0).astype(np.float32)
    if blur_radius > 0.0:
        corrected = cv2.GaussianBlur(
            corrected,
            (0, 0),
            sigmaX=float(blur_radius),
            sigmaY=float(blur_radius),
            borderType=cv2.BORDER_REFLECT_101,
        )
    srgb = linear_to_srgb(np.clip(corrected, 0.0, 1.0))
    return np.clip(srgb[..., ::-1] * 255.0, 0, 255).astype(np.uint8)


def rgb_to_bgr(rgb: list[int]) -> tuple[int, int, int]:
    r, g, b = [int(np.clip(v, 0, 255)) for v in rgb]
    return b, g, r


def render_preview_overlay(
    preview: np.ndarray,
    details: list[dict[str, object]],
    radius: int,
) -> np.ndarray:
    overlay = image_to_uint8_display(preview).copy()
    font = cv2.FONT_HERSHEY_SIMPLEX
    height, width = overlay.shape[:2]
    sample_half = max(int(radius), 4)
    reference_swatch_half = max(int(round(radius * 0.25)), 3)
    corrected_swatch_half = max(int(round(radius * 0.33)), 4)
    swatch_gap = max(int(round(radius * 0.17)), 2)
    for item in details:
        point = item["point"]
        x = int(round(float(point["x"])))
        y = int(round(float(point["y"])))
        outer_left = max(0, x - sample_half)
        outer_top = max(0, y - sample_half)
        outer_right = min(width - 1, x + sample_half)
        outer_bottom = min(height - 1, y + sample_half)
        cv2.rectangle(
            overlay,
            (outer_left, outer_top),
            (outer_right, outer_bottom),
            (0, 0, 0),
            3,
            cv2.LINE_AA,
        )
        cv2.rectangle(
            overlay,
            (outer_left, outer_top),
            (outer_right, outer_bottom),
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )

        def draw_color_swatch(rgb: object, center_x: int, half: int) -> None:
            if not isinstance(rgb, list):
                return
            left = max(0, center_x - half)
            top = max(0, y - half)
            right = min(width - 1, center_x + half)
            bottom = min(height - 1, y + half)
            if left >= right or top >= bottom:
                return
            cv2.rectangle(
                overlay,
                (left, top),
                (right, bottom),
                rgb_to_bgr(rgb),
                -1,
                cv2.LINE_AA,
            )

        reference_rgb = item.get("reference_sRGB")
        corrected_rgb = item.get("corrected_sRGB")
        draw_color_swatch(
            reference_rgb,
            x - reference_swatch_half - swatch_gap,
            reference_swatch_half,
        )
        draw_color_swatch(
            corrected_rgb,
            x + corrected_swatch_half + swatch_gap,
            corrected_swatch_half,
        )

        label_x = outer_left + 4
        label_y = outer_top - 8
        if label_y < 16:
            label_y = min(height - 6, outer_bottom + 18)
        cv2.putText(
            overlay,
            str(item["index"]),
            (label_x, label_y),
            font,
            0.45,
            (0, 0, 0),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            overlay,
            str(item["index"]),
            (label_x, label_y),
            font,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return overlay


def build_report(
    patch_details: list[dict[str, object]],
    stats: dict[str, object],
    ccm: np.ndarray,
    corners: list[dict[str, float]],
    sample_radius: int,
    method: str,
) -> dict[str, object]:
    matrix = [[round(float(v), 8) for v in row] for row in ccm.tolist()]
    return {
        "patch_count": len(patch_details),
        "sample_radius": sample_radius,
        "method": method,
        "corners": corners,
        "stats": stats,
        "ccm": matrix,
        "profile": {
            "model": "linear",
            "wb_gain": [1.0, 1.0, 1.0],
            "black_level": [0.0, 0.0, 0.0],
            "matrix": matrix,
            "offset": [0.0, 0.0, 0.0],
            "output_gain": 1.0,
        },
        "patches": patch_details,
    }


def _profile_from_color_model(model_report: dict[str, object]) -> dict[str, object]:
    profile: dict[str, object] = {
        "model": model_report.get("model_type"),
        "model_type": model_report.get("model_type"),
        "display_name": model_report.get("display_name"),
        "coefficients": model_report.get("coefficients"),
        "feature_definition": model_report.get("feature_definition"),
        "regularization": model_report.get("regularization"),
    }
    for key in ("matrix", "bias", "affine_matrix"):
        value = model_report.get(key)
        if value is not None:
            profile[key] = value
    return profile


def calibrate_image_bgr(
    image_bgr: np.ndarray,
    corners: list[dict[str, float]],
    patch_points: list[dict[str, float]],
    reference_patches: list[dict[str, object]],
    reference_color_map: dict[str, dict[str, list[float]]],
    *,
    preview_width: int = DEFAULT_PREVIEW_WIDTH,
    preview_height: int = DEFAULT_PREVIEW_HEIGHT,
    sample_radius: int = 12,
    method: Literal["mean", "median"] = "mean",
    calibration_mode: str = "matrix_3x3",
    gray_affine_mode: object = "auto",
    sampling_filter: object | None = None,
    blur_radius: float = 0.0,
) -> CalibrationRun:
    if method not in {"mean", "median"}:
        raise ValueError("不支持的采样方式。")
    if len(corners) != 4:
        raise ValueError("请先点击 4 个角点。")
    if len(patch_points) != len(reference_patches):
        raise ValueError(f"请按顺序完成 {len(reference_patches)} 个色块点击。")

    preview, _, ordered = warp_colorchecker_preview(
        image_bgr,
        corners,
        int(preview_width),
        int(preview_height),
    )
    sampling_config = normalize_sampling_filter(
        sampling_filter
        if sampling_filter is not None
        else {"strategy": "median" if method == "median" else "none"}
    )
    patch_colors, patch_details = build_patch_measurements(
        preview,
        patch_points,
        int(sample_radius),
        method,
        reference_patches,
        sampling_config,
    )
    mode = normalize_calibration_mode(calibration_mode)
    gray_affine_mode_value = normalize_gray_affine_mode(gray_affine_mode)
    if mode == "auto":
        mode = "matrix_3x3"

    labels = [str(patch["label"]) for patch in reference_patches]
    measured_arr = np.stack(
        [np.asarray(patch_colors[label]["linear_rgb"], dtype=np.float64) for label in labels],
        axis=0,
    )
    reference_arr = np.stack(
        [
            srgb_to_linear(np.asarray(reference_color_map[label]["sRGB"], dtype=np.float64)[:3] / 255.0)
            for label in labels
        ],
        axis=0,
    )
    reference_lab = np.stack(
        [np.asarray(reference_color_map[label]["Lab_d65"], dtype=np.float64)[:3] for label in labels],
        axis=0,
    )
    fit_mask = np.asarray([not detail.get("exclude_reasons") for detail in patch_details], dtype=bool)
    patch_validity = patch_validity_report(patch_details)
    minimum_valid_patch_count = 6
    if np.count_nonzero(fit_mask) < minimum_valid_patch_count:
        diagnostics = fit_patch_diagnostics(
            patch_details,
            minimum_valid_patch_count=minimum_valid_patch_count,
        )
        diagnostics["pipeline"] = "standard"
        diagnostics["sampling_filter"] = sampling_config
        diagnostics["sample_radius"] = int(sample_radius)
        raise InsufficientValidPatchesError(diagnostics)

    wb_multipliers = np.ones(3, dtype=np.float64)
    measured_wb = measured_arr * wb_multipliers
    gray_rows = [
        row
        for row, detail in enumerate(patch_details)
        if 19 <= int(detail.get("index") or 0) <= 24 and bool(fit_mask[row])
    ]
    used_gray_indices = [int(patch_details[row]["index"]) for row in gray_rows]
    excluded_gray = [
        {
            "index": int(detail.get("index") or 0),
            "label": detail.get("label"),
            "reasons": list(detail.get("exclude_reasons") or []),
        }
        for detail in patch_details
        if 19 <= int(detail.get("index") or 0) <= 24 and detail.get("exclude_reasons")
    ]
    gray_affine = estimate_gray_affine_normalization(
        measured_wb,
        reference_arr,
        patch_details=patch_details,
        used_gray_rows=gray_rows,
        min_valid_gray_patches=4,
    )
    gray_affine = apply_gray_affine_mode(gray_affine, gray_affine_mode_value)
    gray_affine["input_space"] = "linear_srgb_no_white_balance"
    gray_affine["input_coordinate"] = "neutral-axis coordinate in linear sRGB without white balance"
    legacy_exposure_scale = float(gray_affine.get("legacy_exposure_scale") or 1.0)
    legacy_model_input = measured_wb * legacy_exposure_scale
    measured_model_input = apply_gray_affine_normalization(measured_wb, gray_affine)
    gray_negative_ratio = (
        float(np.mean(measured_model_input[gray_rows] < -1e-8)) if gray_rows else 0.0
    )
    gray_affine["gray_patch_negative_channel_ratio"] = round(gray_negative_ratio, 8)
    if bool(gray_affine.get("enabled")) and gray_negative_ratio > 0.0:
        failure = f"gray affine creates negative channels in gray patches ratio={gray_negative_ratio:.4%}"
        if gray_affine_mode_value == "auto":
            gray_affine = disable_gray_affine_normalization(gray_affine, [failure])
            measured_model_input = legacy_model_input
        else:
            gray_affine["forced_negative_channel_failures"] = [failure]

    legacy_base_model = fit_color_model(
        legacy_model_input[fit_mask],
        reference_arr[fit_mask],
        model_type="matrix_3x3",
        weights="perceptual",
        regularization=0.0,
    )
    base_model = fit_color_model(
        measured_model_input[fit_mask],
        reference_arr[fit_mask],
        model_type="matrix_3x3",
        weights="perceptual",
        regularization=0.0,
    )
    if bool(gray_affine.get("enabled")):
        post_fit_failures = gray_affine_post_fit_failures(
            legacy_model_input=legacy_model_input,
            affine_model_input=measured_model_input,
            reference_linear=reference_arr,
            reference_lab=reference_lab,
            fit_mask=fit_mask,
            used_gray_indices=used_gray_indices,
            legacy_model=legacy_base_model,
            affine_model=base_model,
            target_white_point="D65",
        )
        if post_fit_failures:
            if gray_affine_mode_value == "auto":
                gray_affine = disable_gray_affine_normalization(gray_affine, post_fit_failures)
                measured_model_input = legacy_model_input
                base_model = legacy_base_model
            else:
                gray_affine["forced_post_fit_failures"] = post_fit_failures

    if mode == "matrix_3x3":
        model_report = base_model
    else:
        model_report = fit_color_model(
            measured_model_input[fit_mask],
            reference_arr[fit_mask],
            model_type=mode,
            weights="perceptual",
            regularization=1e-3,
        )
        gate_failures: list[str] = []
        if mode == "matrix_3x4":
            bias_threshold = 0.01 if bool(gray_affine.get("enabled")) else 0.025
            gate_failures.extend(check_affine_bias_gate(model_report, threshold=bias_threshold))
            if bool(gray_affine.get("enabled")) and gate_failures:
                gate_failures.append(
                    "3x4 affine bias remains active after gray affine normalization; treat this expert result as untrusted unless the bias gate is resolved."
                )
            gate_failures.extend(check_exposure_invariance(measured_model_input[fit_mask], model_report))
        elif mode == "root_polynomial":
            gate_failures.extend(check_exposure_invariance(measured_model_input[fit_mask], model_report, threshold=0.04))
        warnings = list(model_report.get("warnings") or [])
        if gate_failures:
            warnings.extend(gate_failures)
        model_report["warnings"] = warnings
        model_report["gate_failures"] = gate_failures

    corrected_patches = apply_color_model(measured_model_input, model_report)
    corrected_lab = linear_srgb_to_lab(np.clip(corrected_patches, 0.0, 1.0), "D65")
    patch_details, metric_report = enrich_patch_details_with_model(
        patch_details,
        corrected_patches,
        reference_lab,
        metric_mask=fit_mask,
    )
    for row, detail in enumerate(patch_details):
        detail["exposure_normalized_linear_rgb"] = round_list(measured_model_input[row])
        detail["gray_affine_normalized_linear_rgb"] = round_list(measured_model_input[row])
    stats = _legacy_delta_e_stats(int(np.count_nonzero(fit_mask)), metric_report["delta_e_d65"])
    stats["delta_e00"] = metric_report["delta_e00"]
    stats["delta_e76"] = metric_report["delta_e76"]
    stats["delta_e94"] = metric_report["delta_e94"]
    model_fit_metrics = dict(model_report.get("fit_metrics") or {})
    model_fit_metrics["delta_e00"] = metric_report["delta_e00"]
    model_fit_metrics["delta_e76"] = metric_report["delta_e76"]
    model_fit_metrics["delta_e94"] = metric_report["delta_e94"]
    model_fit_metrics["patch_count"] = int(np.count_nonzero(fit_mask))
    model_report["fit_metrics"] = model_fit_metrics
    ccm = np.asarray(model_report["coefficients"], dtype=np.float32)
    gray_metrics = gray_patch_metrics(corrected_lab[gray_rows], used_gray_indices)
    luminance_diagnostics = build_luminance_diagnostics(
        patch_details=patch_details,
        reference_linear=reference_arr,
        measured_wb=measured_wb,
        measured_model_input=measured_model_input,
        corrected_patches=corrected_patches,
        fit_mask=fit_mask,
        gray_rows=gray_rows,
        gray_affine=gray_affine,
        captured_level_source="neutral-axis coordinate in linear sRGB without white balance",
        normalized_level_source="neutral-axis coordinate after gray affine normalization",
    )
    warnings = list(model_report.get("warnings") or [])
    validity_warning = patch_validity_warning(patch_validity)
    if validity_warning:
        warnings.append(validity_warning)
    if gray_metrics.get("l_monotonic") is False:
        warnings.append("Neutral gray L* values are not monotonic.")
    gray_delta_metrics = gray_reference_delta_metrics(
        corrected_lab[gray_rows],
        reference_lab[gray_rows],
        used_gray_indices,
        [str(patch_details[row].get("label") or used_gray_indices[pos]) for pos, row in enumerate(gray_rows)],
    )
    gray_metrics["reference_delta"] = gray_delta_metrics
    warnings.extend(gray_reference_delta_warnings(gray_delta_metrics))
    model_report["warnings"] = warnings
    calibrated = apply_color_model_to_image_bgr(
        image_bgr,
        model_report,
        gray_affine_normalization=gray_affine,
        blur_radius=float(blur_radius),
    )
    calibrated_preview, _, _ = warp_colorchecker_preview(
        calibrated,
        corners,
        int(preview_width),
        int(preview_height),
    )
    overlay = render_preview_overlay(calibrated_preview, patch_details, int(sample_radius))
    ordered_corners = [
        {"x": round(float(point[0]), 2), "y": round(float(point[1]), 2)}
        for point in ordered.tolist()
    ]
    report = build_report(
        patch_details,
        stats,
        ccm,
        ordered_corners,
        int(sample_radius),
        method,
    )
    report["selected_model"] = model_report.get("model_type")
    report["model"] = model_report
    report["model_coefficients"] = model_report.get("coefficients")
    report["feature_definition"] = model_report.get("feature_definition")
    report["fit_metrics"] = model_report.get("fit_metrics", {})
    report["pipeline"] = "standard"
    report["gray_affine_mode"] = gray_affine_mode_value
    report["gray_affine_normalization"] = gray_affine
    report["patch_validity"] = patch_validity
    report["white_balance"] = {
        "multipliers": [1.0, 1.0, 1.0],
        "used_gray_patches": [],
        "excluded_gray_patches": excluded_gray,
        "applied": False,
        "reason": "standard image pipeline preserves uploaded white balance",
    }
    report["wb_multipliers"] = [1.0, 1.0, 1.0]
    report["exposure_scale"] = round(float(gray_affine.get("scale") or legacy_exposure_scale), 8)
    report["legacy_exposure_scale"] = round(float(legacy_exposure_scale), 8)
    report["combined_transform"] = {
        "wb_multipliers": [1.0, 1.0, 1.0],
        "exposure_scale": round(float(gray_affine.get("scale") or legacy_exposure_scale), 8),
        "gray_affine_normalization": {
            "enabled": bool(gray_affine.get("enabled")),
            "mode": gray_affine_mode_value,
            "scale": float(gray_affine.get("scale") or legacy_exposure_scale),
            "offset": float(gray_affine.get("offset") or 0.0),
        },
        "model_type": model_report.get("model_type"),
        "coefficients": model_report.get("coefficients"),
        "affine_matrix": model_report.get("affine_matrix"),
    }
    report["gray_patch_metrics"] = gray_metrics
    report["luminance_diagnostics"] = luminance_diagnostics
    if model_report.get("model_type") != "matrix_3x3":
        report["profile"] = _profile_from_color_model(model_report)
    if isinstance(report.get("profile"), dict):
        report["profile"]["gray_affine_normalization"] = {
            "enabled": bool(gray_affine.get("enabled")),
            "mode": gray_affine_mode_value,
            "scale": float(gray_affine.get("scale") or legacy_exposure_scale),
            "offset": float(gray_affine.get("offset") or 0.0),
        }
    report["warnings"] = list(model_report.get("warnings") or [])
    if sampling_filter is not None:
        report["sampling_filter"] = sampling_config
    report["blur_radius"] = float(blur_radius)
    report["output_generated"] = True
    return CalibrationRun(
        calibrated_image=calibrated,
        preview_image=preview,
        preview_overlay_image=overlay,
        report=report,
        ccm=ccm,
        ordered_corners=ordered_corners,
        patch_details=patch_details,
    )
