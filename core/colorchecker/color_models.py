from __future__ import annotations

from typing import Literal

import numpy as np


CalibrationMode = Literal["matrix_3x3", "matrix_3x4", "root_polynomial", "auto"]

MODEL_LABELS = {
    "matrix_3x3": "3x3 matrix",
    "matrix_3x4": "3x4 affine matrix",
    "root_polynomial": "degree-2 root-polynomial",
    "auto": "Auto / recommended",
}

ROOT_POLYNOMIAL_DEGREE2_FEATURES = [
    "R",
    "G",
    "B",
    "sqrt(R*G)",
    "sqrt(R*B)",
    "sqrt(G*B)",
]


def normalize_calibration_mode(mode: object) -> CalibrationMode:
    value = str(mode or "matrix_3x3").strip().lower().replace("-", "_")
    aliases = {
        "3x3": "matrix_3x3",
        "linear": "matrix_3x3",
        "matrix": "matrix_3x3",
        "3x4": "matrix_3x4",
        "affine": "matrix_3x4",
        "root_poly": "root_polynomial",
        "root_polynomial_degree2": "root_polynomial",
    }
    value = aliases.get(value, value)
    if value not in {"matrix_3x3", "matrix_3x4", "root_polynomial", "auto"}:
        raise ValueError("calibration_mode must be matrix_3x3, matrix_3x4, root_polynomial, or auto.")
    return value  # type: ignore[return-value]


def root_polynomial_features(rgb: np.ndarray) -> np.ndarray:
    arr = np.maximum(np.asarray(rgb, dtype=np.float64), 0.0)
    R = arr[..., 0]
    G = arr[..., 1]
    B = arr[..., 2]
    return np.stack(
        [
            R,
            G,
            B,
            np.sqrt(R * G),
            np.sqrt(R * B),
            np.sqrt(G * B),
        ],
        axis=-1,
    )


def feature_matrix(rgb: np.ndarray, model_type: str) -> tuple[np.ndarray, list[str], bool]:
    arr = np.asarray(rgb, dtype=np.float64)
    if model_type == "matrix_3x3":
        return arr, ["R", "G", "B"], False
    if model_type == "matrix_3x4":
        ones = np.ones((arr.shape[0], 1), dtype=np.float64)
        return np.hstack([arr, ones]), ["R", "G", "B", "bias"], True
    if model_type == "root_polynomial":
        return root_polynomial_features(arr), ROOT_POLYNOMIAL_DEGREE2_FEATURES.copy(), False
    raise ValueError(f"Unsupported color model: {model_type}")


def _perceptual_weights(target_linear_rgb: np.ndarray) -> np.ndarray:
    target = np.asarray(target_linear_rgb, dtype=np.float64)
    lum = 0.2126 * target[:, 0] + 0.7152 * target[:, 1] + 0.0722 * target[:, 2]
    weights = 1.0 / np.cbrt(np.maximum(lum, 0.05))
    return weights / np.mean(weights)


def fit_color_model(
    measured_linear_rgb: np.ndarray,
    target_linear_rgb: np.ndarray,
    *,
    model_type: str,
    weights: np.ndarray | str | None = "perceptual",
    regularization: float = 1e-3,
) -> dict[str, object]:
    model_type = normalize_calibration_mode(model_type)
    if model_type == "auto":
        model_type = "matrix_3x3"
    measured = np.asarray(measured_linear_rgb, dtype=np.float64)
    target = np.asarray(target_linear_rgb, dtype=np.float64)
    if measured.ndim != 2 or measured.shape[1] != 3:
        raise ValueError("measured_linear_rgb must have shape Nx3.")
    if target.shape != measured.shape:
        raise ValueError("target_linear_rgb must have the same Nx3 shape.")
    if measured.shape[0] < 3:
        raise ValueError("At least 3 patches are required to fit a color model.")
    if regularization < 0.0:
        raise ValueError("regularization must be non-negative.")

    features, feature_names, has_bias = feature_matrix(measured, model_type)
    if isinstance(weights, str):
        if weights == "perceptual":
            weight_vec = _perceptual_weights(target)
        elif weights == "uniform":
            weight_vec = np.ones(measured.shape[0], dtype=np.float64)
        else:
            raise ValueError("weights must be perceptual, uniform, an array, or None.")
    elif weights is None:
        weight_vec = np.ones(measured.shape[0], dtype=np.float64)
    else:
        weight_vec = np.asarray(weights, dtype=np.float64)
        if weight_vec.shape != (measured.shape[0],):
            raise ValueError("weights array must have shape N.")

    w_sqrt = np.sqrt(weight_vec)[:, None]
    design = features * w_sqrt
    rhs = target * w_sqrt
    if regularization > 0.0:
        reg = np.sqrt(float(regularization)) * np.eye(features.shape[1], dtype=np.float64)
        if has_bias:
            reg[-1, -1] = 0.0
        design = np.vstack([design, reg])
        rhs = np.vstack([rhs, np.zeros((features.shape[1], 3), dtype=np.float64)])
    coefficients, *_ = np.linalg.lstsq(design, rhs, rcond=None)
    fitted = features @ coefficients
    residual = fitted - target
    rms = float(np.sqrt(np.mean(residual ** 2)))
    coefficient_rows = [[float(v) for v in row] for row in coefficients.tolist()]
    affine_matrix = None
    if model_type == "matrix_3x4":
        # Public report form follows target = M * [R, G, B, 1], so bias is
        # the fourth column. Internal application uses row-vector features.
        affine_matrix = [[float(v) for v in row] for row in coefficients.T.tolist()]
    return {
        "model_type": model_type,
        "display_name": MODEL_LABELS[model_type],
        "coefficients": coefficient_rows,
        "matrix": coefficient_rows[:3] if model_type == "matrix_3x3" else None,
        "bias": coefficient_rows[3] if model_type == "matrix_3x4" else None,
        "affine_matrix": affine_matrix,
        "feature_definition": feature_names,
        "regularization": float(regularization),
        "fit_metrics": {
            "linear_rgb_rms": round(rms, 8),
            "patch_count": int(measured.shape[0]),
        },
        "warnings": [],
        "gate_failures": [],
    }


def apply_color_model(linear_rgb: np.ndarray, model: dict[str, object]) -> np.ndarray:
    model_type = str(model.get("model_type") or "matrix_3x3")
    coefficients = np.asarray(model.get("coefficients"), dtype=np.float64)
    if coefficients.ndim != 2 or coefficients.shape[1] != 3:
        raise ValueError("Invalid model coefficients.")
    arr = np.asarray(linear_rgb, dtype=np.float64)
    original_shape = arr.shape
    flat = arr.reshape(-1, 3)
    features, _names, _has_bias = feature_matrix(flat, model_type)
    corrected = features @ coefficients
    return corrected.reshape(original_shape)


def check_affine_bias_gate(model: dict[str, object], *, threshold: float = 0.025) -> list[str]:
    if str(model.get("model_type")) != "matrix_3x4":
        return []
    bias = np.asarray(model.get("bias") or [0.0, 0.0, 0.0], dtype=np.float64)
    failures: list[str] = []
    max_abs = float(np.max(np.abs(bias)))
    if max_abs > threshold:
        failures.append(
            f"3x4 affine bias max_abs={max_abs:.4f} exceeds {threshold:.4f}; black point may drift."
        )
    return failures


def check_exposure_invariance(
    samples: np.ndarray,
    model: dict[str, object],
    *,
    scales: tuple[float, ...] = (0.5, 2.0),
    threshold: float = 0.035,
) -> list[str]:
    model_type = str(model.get("model_type") or "")
    if model_type == "matrix_3x3":
        return []
    arr = np.asarray(samples, dtype=np.float64)
    failures: list[str] = []
    base = apply_color_model(arr, model)
    for scale in scales:
        scaled = apply_color_model(arr * scale, model) / max(scale, 1e-9)
        drift = float(np.mean(np.linalg.norm(base - scaled, axis=1)))
        if drift > threshold:
            failures.append(
                f"{model_type} exposure-scale drift={drift:.4f} at scale={scale:g}; hue/chroma may change with exposure."
            )
    return failures
