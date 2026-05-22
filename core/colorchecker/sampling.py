from __future__ import annotations

from typing import Any

import cv2
import numpy as np


DEFAULT_SAMPLING_FILTER = {
    "strategy": "trimmed_mean",
    "trim_fraction": 0.1,
    "sigma": 2.5,
    "gaussian_radius": 0.0,
}
LUMINANCE_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)


def normalize_sampling_filter(config: object) -> dict[str, object]:
    if isinstance(config, str):
        config = {"strategy": config}
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError("sampling_filter must be a string or object.")
    strategy = str(config.get("strategy") or DEFAULT_SAMPLING_FILTER["strategy"]).strip().lower()
    if strategy not in {"none", "median", "trimmed_mean", "sigma_clipping", "gaussian"}:
        raise ValueError("sampling_filter strategy must be none, median, trimmed_mean, sigma_clipping, or gaussian.")
    trim_fraction = float(config.get("trim_fraction", DEFAULT_SAMPLING_FILTER["trim_fraction"]))
    sigma = float(config.get("sigma", DEFAULT_SAMPLING_FILTER["sigma"]))
    gaussian_radius = float(config.get("gaussian_radius", config.get("radius", DEFAULT_SAMPLING_FILTER["gaussian_radius"])))
    return {
        "strategy": strategy,
        "trim_fraction": float(np.clip(trim_fraction, 0.0, 0.45)),
        "sigma": float(np.clip(sigma, 0.5, 10.0)),
        "gaussian_radius": float(max(0.0, gaussian_radius)),
    }


def _roi(image: np.ndarray, point: dict[str, float], radius: int) -> tuple[np.ndarray, dict[str, int]]:
    h, w = image.shape[:2]
    x = int(round(float(point["x"])))
    y = int(round(float(point["y"])))
    safe_radius = max(0, int(radius))
    x0 = max(0, x - safe_radius)
    y0 = max(0, y - safe_radius)
    x1 = min(w, x + safe_radius + 1)
    y1 = min(h, y + safe_radius + 1)
    if x0 >= x1 or y0 >= y1:
        raise ValueError("Patch sampling point is outside the preview.")
    return image[y0:y1, x0:x1], {"x0": x0, "y0": y0, "x1": x1, "y1": y1}


def _trimmed_mean(values: np.ndarray, fraction: float) -> np.ndarray:
    if values.shape[0] < 3 or fraction <= 0.0:
        return np.mean(values, axis=0)
    count = values.shape[0]
    lower = int(np.floor(count * fraction))
    upper = count - lower
    if lower >= upper:
        return np.mean(values, axis=0)
    sorted_values = np.sort(values, axis=0)
    return np.mean(sorted_values[lower:upper], axis=0)


def _sigma_clipped_mean(values: np.ndarray, sigma: float) -> tuple[np.ndarray, int]:
    if values.shape[0] < 4:
        return np.mean(values, axis=0), 0
    center = np.median(values, axis=0)
    mad = np.median(np.abs(values - center), axis=0)
    robust_sigma = np.where(mad > 1e-9, 1.4826 * mad, np.std(values, axis=0))
    robust_sigma = np.where(robust_sigma > 1e-9, robust_sigma, 1.0)
    z = np.abs(values - center) / robust_sigma
    mask = np.all(z <= sigma, axis=1)
    if not np.any(mask):
        return np.mean(values, axis=0), 0
    return np.mean(values[mask], axis=0), int(values.shape[0] - np.count_nonzero(mask))


def sample_patch(
    image: np.ndarray,
    point: dict[str, float],
    radius: int,
    sampling_filter: object = None,
) -> dict[str, Any]:
    config = normalize_sampling_filter(sampling_filter)
    patch, bounds = _roi(np.asarray(image), point, int(radius))
    working = patch.astype(np.float64, copy=False)
    original_values = working.reshape(-1, working.shape[-1])
    strategy = str(config["strategy"])
    gaussian_applied = False
    clipped_count = 0
    if strategy == "gaussian":
        gaussian_radius = float(config["gaussian_radius"])
        max_allowed = max(0.0, int(radius) * 0.25)
        gaussian_radius = min(gaussian_radius, max_allowed)
        if gaussian_radius > 0.0:
            working = cv2.GaussianBlur(
                working.astype(np.float32),
                (0, 0),
                sigmaX=gaussian_radius,
                sigmaY=gaussian_radius,
                borderType=cv2.BORDER_REFLECT_101,
            ).astype(np.float64)
            gaussian_applied = True
        values = working.reshape(-1, working.shape[-1])
        measured = np.mean(values, axis=0)
    else:
        values = working.reshape(-1, working.shape[-1])
        if strategy == "median":
            measured = np.median(values, axis=0)
        elif strategy == "trimmed_mean":
            measured = _trimmed_mean(values, float(config["trim_fraction"]))
        elif strategy == "sigma_clipping":
            measured, clipped_count = _sigma_clipped_mean(values, float(config["sigma"]))
        else:
            measured = np.mean(values, axis=0)
    mean = np.mean(values, axis=0)
    std = np.std(values, axis=0)
    original_rgb = original_values[:, :3]
    luminance = original_rgb @ LUMINANCE_WEIGHTS
    return {
        "rgb": measured.astype(np.float64),
        "mean_rgb": mean.astype(np.float64),
        "std_rgb": std.astype(np.float64),
        "min_rgb": np.min(original_values, axis=0).astype(np.float64),
        "max_rgb": np.max(original_values, axis=0).astype(np.float64),
        "percentile_1_rgb": np.percentile(original_values, 1, axis=0).astype(np.float64),
        "percentile_99_rgb": np.percentile(original_values, 99, axis=0).astype(np.float64),
        "percentile_1_luminance": float(np.percentile(luminance, 1)),
        "percentile_99_luminance": float(np.percentile(luminance, 99)),
        "black_clipped_ratio": float(np.mean(luminance <= 0.000001)),
        "white_clipped_ratio": float(np.mean(np.any(original_rgb >= 0.995, axis=1))),
        "pixel_count": int(values.shape[0]),
        "rejected_pixel_count": int(clipped_count),
        "bounds": bounds,
        "filter": {
            **config,
            "gaussian_applied": gaussian_applied,
        },
    }
