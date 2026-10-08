"""Canonical fit records shared by Box fitting, migration, and archive validation.
供 Box 拟合、迁移及档案校验共同使用的标准拟合记录。
"""

from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any, Mapping

import numpy as np

from core.km_xyz import km_relative_xyz_to_srgb_uint8
from core.lumina_box_archive import evaluate_lumina_box_fit_quality
from core.lumina_box_fitting import LuminaBoxSpectralFitResult
from core.lumina_box_spectral import (
    LUMINA_BOX_PHYSICAL_WHITE_OBJECTIVE_IDS,
    LUMINA_BOX_REFERENCE_REFLECTANCE,
    LUMINA_BOX_SPECTRAL_BOUNDARY_ID,
    LUMINA_BOX_SPECTRAL_MODEL_ID,
    LuminaBoxSpectralModel,
)


def paired_residual_summary(
    thicknesses_mm: np.ndarray, transmission_residual: np.ndarray, reflection_residual: np.ndarray,
) -> dict[str, Any]:
    """Summarize paired percentage-point errors with a stable maximum location.
    汇总成对百分点误差，并稳定定位最大偏差。

    Args:
        thicknesses_mm: Ordered sample thicknesses.（有序样片厚度。）
        transmission_residual: Predicted minus measured T, in percentage points.
            （预测减实测的透射百分点误差。）
        reflection_residual: Predicted minus measured R, in percentage points.
            （预测减实测的反射百分点误差。）

    Returns:
        Public residual metrics.（公开残差指标。）
    """
    d = np.asarray(thicknesses_mm, dtype=np.float64)
    t = np.asarray(transmission_residual, dtype=np.float64)
    r = np.asarray(reflection_residual, dtype=np.float64)
    if len(d) == 0 or t.shape != (len(d), 3) or r.shape != t.shape:
        raise ValueError("Paired residual inputs must have shape N by 3")
    errors = np.stack([t, r], axis=1)
    sample, mode, channel = np.unravel_index(np.argmax(np.abs(errors)), errors.shape)
    together = np.concatenate([t, r], axis=0)
    return {
        "transmittance_channel_rmse_percentage_points_xyz": np.sqrt(np.mean(t**2, axis=0)).tolist(),
        "reflectance_channel_rmse_percentage_points_xyz": np.sqrt(np.mean(r**2, axis=0)).tolist(),
        "channel_rmse_percentage_points_xyz": np.sqrt(np.mean(together**2, axis=0)).tolist(),
        "transmittance_rmse_percentage_points": float(np.sqrt(np.mean(t**2))),
        "reflectance_rmse_percentage_points": float(np.sqrt(np.mean(r**2))),
        "overall_rmse_percentage_points": float(np.sqrt(np.mean(together**2))),
        "max_abs_residual_percentage_points": float(np.abs(errors[sample, mode, channel])),
        "max_abs_location": {
            "thickness_mm": float(d[sample]),
            "modality": ("transmittance", "reflectance")[mode],
            "channel": ("X", "Y", "Z")[channel],
            "signed_residual_percentage_points": float(errors[sample, mode, channel]),
        },
    }


def _modality(measured: list[float], predicted: np.ndarray) -> dict[str, list[float]]:
    return {
        "measured_percent_xyz": list(measured),
        "predicted_percent_xyz": predicted.tolist(),
        "residual_percentage_points_xyz": (predicted - measured).tolist(),
    }


def build_spectral_fit_payload(
    result: LuminaBoxSpectralFitResult, measurements: Mapping[str, Any],
) -> dict[str, Any]:
    """Create the single authoritative payload for saving and API responses.
    构建保存和接口响应共同使用的唯一权威数据。

    Args:
        result: Completed spectral fit.（完成的波段拟合。）
        measurements: Original normalized-order percentage records.
            （按厚度排列的原始百分比记录。）

    Returns:
        Self-contained fit, reference, and diagnostic data.（完整拟合、参考和诊断数据。）
    """
    samples = measurements["samples"]
    thicknesses = np.array([row["thickness_mm"] for row in samples])
    measured_t = np.array([row["transmittance_percent_xyz"] for row in samples])
    measured_r = np.array([row["reflectance_percent_xyz"] for row in samples])
    predicted_t = result.predicted_transmittance_xyz * 100.0
    predicted_r = result.predicted_reflectance_xyz * 100.0
    summary = paired_residual_summary(thicknesses, predicted_t - measured_t, predicted_r - measured_r)
    diagnostics = json.loads(json.dumps(asdict(result.diagnostics), allow_nan=False))
    physics: dict[str, Any] | None = None
    if result.diagnostics.objective_id in LUMINA_BOX_PHYSICAL_WHITE_OBJECTIVE_IDS:
        reference = result.white_reference
        model = LuminaBoxSpectralModel()
        model.validate_reference_physics(reference, require_constraint=True)
        reflection, transmission, absorption = model.reference_energy_xyz(reference.white_parameters)
        minimum = reference.minimum_total_reflectance_y
        assert minimum is not None
        physics = {
            "minimum_total_reflectance_percent_y": 100.0 * minimum,
            "total_reflectance_percent_xyz": (100.0 * reflection).tolist(),
            "total_transmittance_percent_xyz": (100.0 * transmission).tolist(),
            "absorption_percent_xyz": (100.0 * absorption).tolist(),
            "lower_bound_active": bool(reflection[1] <= minimum + 1e-4),
            "assigned_calibration_percent": 100.0 * LUMINA_BOX_REFERENCE_REFLECTANCE,
            "exact_white_reflectance_measured": False,
        }
    quality = evaluate_lumina_box_fit_quality(
        diagnostics=diagnostics, residual_summary=summary, reference_physics=physics,
    )
    estimated = result.predicted_reflectance_xyz[-1]
    payload = {
        "optical_model_id": LUMINA_BOX_SPECTRAL_MODEL_ID,
        "parameters": result.parameters.to_dict(),
        "white_reference": result.white_reference.to_dict(),
        "is_reference_white": result.is_reference_white,
        "sample_predictions": [
            {"thickness_mm": float(sample["thickness_mm"]),
             "transmittance": _modality(sample["transmittance_percent_xyz"], pt),
             "reflectance": _modality(sample["reflectance_percent_xyz"], pr)}
            for sample, pt, pr in zip(samples, predicted_t, predicted_r, strict=True)
        ],
        "residual_summary": summary,
        "diagnostics": diagnostics,
        "measurement_backing_base_percent_xyz": list(measurements["measurement_backing_percent_xyz"]),
        "measurement_backing_scale": result.measurement_backing_scale,
        "measurement_thickness_offset_mm": 0.0,
        "measurement_backing_effective_percent_xyz": (result.measurement_backing_effective_relative_xyz * 100).tolist(),
        "measurement_reflection_boundary_id": LUMINA_BOX_SPECTRAL_BOUNDARY_ID,
        "fit_quality": quality,
        "estimated_effective_d65_10_xyz_relative": estimated.tolist(),
        "estimated_reflectance_thickness_mm": float(thicknesses[-1]),
        "estimated_rgb": km_relative_xyz_to_srgb_uint8(estimated).tolist(),
        "warnings": list(result.diagnostics.warnings),
    }
    if physics is not None:
        payload["reference_physics"] = physics
    return payload
