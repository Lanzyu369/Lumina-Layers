"""Gradient-card extraction, image orientation, and Stage A fitting."""

from __future__ import annotations

import json
import uuid
import zipfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from scipy.optimize import least_squares

from . import material_files
from .kit import SINGLE_STAGE_SPEC, SingleStageSpec


@dataclass(frozen=True)
class GradientCardStageAResult:
    """Result for extracting Stage A material data from dual gradient-card images.
    从白底/黑底双图中提取 Stage A 耗材参数后的结果。

    Attributes:
        params_path: Temporary Stage A JSON path. (临时 Stage A JSON 路径)
        params_payload: Parsed Stage A payload. (解析后的 Stage A 数据)
        fit_summary: Summary for UI/API responses. (用于 UI/API 的拟合摘要)
        material_summary: Material extraction summary. (耗材提取摘要)
        source_summary: Source metadata captured from inputs. (输入来源摘要)
        warnings: Non-fatal warnings. (非致命警告)
        white_warp_rgb: Warped white-substrate RGB image. (白底透视矫正 RGB 图)
        black_warp_rgb: Warped black-substrate RGB image. (黑底透视矫正 RGB 图)
    """

    params_path: str
    params_payload: dict[str, Any]
    fit_summary: dict[str, Any]
    material_summary: dict[str, Any]
    source_summary: dict[str, Any]
    warnings: list[str]
    white_warp_rgb: np.ndarray
    black_warp_rgb: np.ndarray


@dataclass(frozen=True)
class _WarpCandidate:
    orientation_label: str
    corner_order: tuple[int, int, int, int]
    ordered_points: np.ndarray
    warped_rgb: np.ndarray
    sample_boxes: list[dict[str, int]]
    linear_samples: np.ndarray


_WARP_PIXELS_PER_MM = 20.0

_SAMPLE_INSET_RATIO = 0.18

_C0_WHITE_OVERBRIGHT_THRESHOLD: float = 0.95


"""Linear-RGB threshold above which the zero-thickness ``C0_white``
samples are treated as suspiciously close to ideal white (= 1.0). When
exceeded, the sampled Stage A area likely suffered highlight clipping or
overbright normalization; the resulting ``(E, k)`` will be biased away
from the true physical attenuation.
线性 RGB 阈值，超过该值则零厚度白底采样过于接近理想纯白，输入图像
采样区域可能发生高光裁切或过亮归一化，会导致 (E, k) 偏离真实物理值。
"""


_VALID_IMAGE_SOURCES: frozenset[str] = frozenset({"raw", "restored"})


"""Allowed values for the gradient-card capture origin tag.
``raw`` = camera/scanner output without white-balance/restoration;
``restored`` = card image that has already been color-normalized or
geometrically restored. The fitter accepts both and records the tag so
raw/restored captures are not mixed silently; clipping risk is judged by
the sampled ``C0_white`` and other diagnostics.
``raw`` 表示相机/扫描仪原图；``restored`` 表示已经做过色彩校正或几何还原
的图。两者都允许拟合，但会记录来源以避免原图与校正/还原图静默混合；
裁切风险由采样得到的 C0_white 等诊断判断。
"""


_CORNER_ORIENTATION_CANDIDATES: tuple[tuple[str, tuple[int, int, int, int]], ...] = (
    ("identity", (0, 1, 2, 3)),
    ("rotate_90_cw", (1, 2, 3, 0)),
    ("rotate_180", (2, 3, 0, 1)),
    ("rotate_90_ccw", (3, 0, 1, 2)),
    ("flip_horizontal", (1, 0, 3, 2)),
    ("flip_vertical", (3, 2, 1, 0)),
    ("transpose", (0, 3, 2, 1)),
    ("transverse", (2, 1, 0, 3)),
)


def _srgb_to_linear(arr: np.ndarray) -> np.ndarray:
    c = arr.astype(np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb_float(arr: np.ndarray) -> np.ndarray:
    c = np.clip(arr.astype(np.float64), 0.0, 1.0)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


def _linear_to_srgb_uint8(arr: np.ndarray) -> np.ndarray:
    srgb = _linear_to_srgb_float(arr)
    return np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)


def _load_manifest_from_zip(dataset_zip_path: str) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(dataset_zip_path, "r") as archive:
            with archive.open("manifest.json", "r") as fh:
                return json.loads(fh.read().decode("utf-8"))
    except KeyError as exc:
        raise ValueError("Gradient card kit zip must contain manifest.json") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError("Malformed ZIP archive") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("manifest.json is not valid UTF-8 JSON") from exc


def _coerce_spec(manifest: dict[str, Any]) -> SingleStageSpec:
    payload = manifest.get("spec")
    if not isinstance(payload, dict):
        return SINGLE_STAGE_SPEC
    allowed = {field.name for field in fields(SingleStageSpec)}
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in allowed:
            continue
        if key == "step_layers" and isinstance(value, list):
            normalized[key] = tuple(int(item) for item in value)
        else:
            normalized[key] = value
    try:
        return SingleStageSpec(**normalized)
    except TypeError:
        return SINGLE_STAGE_SPEC


def _coerce_points(points: list[tuple[float, float]] | list[list[float]]) -> np.ndarray:
    arr = np.asarray(points, dtype=np.float32)
    if arr.shape != (4, 2):
        raise ValueError("corner points must contain exactly 4 [x, y] pairs")
    return arr


def _warp_image(image_rgb: np.ndarray, points: np.ndarray, spec: SingleStageSpec) -> np.ndarray:
    target_width = max(int(round(spec.board_width_mm * _WARP_PIXELS_PER_MM)), 64)
    target_height = max(int(round(spec.board_height_mm * _WARP_PIXELS_PER_MM)), 64)
    src = points.astype(np.float32)
    dst = np.array(
        [
            [0.0, 0.0],
            [target_width - 1.0, 0.0],
            [target_width - 1.0, target_height - 1.0],
            [0.0, target_height - 1.0],
        ],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(
        image_rgb,
        matrix,
        (target_width, target_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return warped.astype(np.uint8)


def _build_sample_boxes(warped_rgb: np.ndarray, spec: SingleStageSpec) -> list[dict[str, int]]:
    boxes: list[dict[str, int]] = []
    pixels_per_mm_x = warped_rgb.shape[1] / spec.board_width_mm
    pixels_per_mm_y = warped_rgb.shape[0] / spec.board_height_mm
    step_layers = _canonical_step_layers(spec)
    for row in range(spec.grid_rows):
        for col in range(spec.grid_cols):
            x0_mm = spec.margin_mm + col * (spec.block_mm + spec.gap_mm)
            y0_mm = spec.margin_mm + row * (spec.block_mm + spec.gap_mm)
            x1_mm = x0_mm + spec.block_mm
            y1_mm = y0_mm + spec.block_mm
            inset_x_mm = spec.block_mm * _SAMPLE_INSET_RATIO
            inset_y_mm = spec.block_mm * _SAMPLE_INSET_RATIO
            sx0 = int(round((x0_mm + inset_x_mm) * pixels_per_mm_x))
            sy0 = int(round((y0_mm + inset_y_mm) * pixels_per_mm_y))
            sx1 = int(round((x1_mm - inset_x_mm) * pixels_per_mm_x))
            sy1 = int(round((y1_mm - inset_y_mm) * pixels_per_mm_y))
            sx0 = max(0, min(sx0, warped_rgb.shape[1] - 1))
            sy0 = max(0, min(sy0, warped_rgb.shape[0] - 1))
            sx1 = max(sx0 + 1, min(sx1, warped_rgb.shape[1]))
            sy1 = max(sy0 + 1, min(sy1, warped_rgb.shape[0]))
            boxes.append(
                {
                    "row": int(row),
                    "col": int(col),
                    "x": int(sx0),
                    "y": int(sy0),
                    "width": int(sx1 - sx0),
                    "height": int(sy1 - sy0),
                    "thickness_layers": int(step_layers[row, col]),
                }
            )
    return boxes


def _sample_grid_linear_means(
    warped_rgb: np.ndarray,
    spec: SingleStageSpec,
    sample_boxes: list[dict[str, int]] | None = None,
) -> np.ndarray:
    """Compute per-grid-cell representative colors in **linear RGB** space.
    在线性 RGB 空间计算每个栅格中心的代表颜色。

    Uses the per-channel median of the linearized ROI pixels. Median (instead
    of mean) rejects print-defect/dust outliers; linear-space aggregation
    avoids the ~5-10% gamma bias caused by averaging in sRGB (gamma-encoded)
    space before linearization.

    中位数替代均值可剔除打印瑕疵/灰尘等异常像素；在线性空间聚合可避免
    在 sRGB（伽马编码）空间求均值再线性化导致的 5-10% 伽马偏差。

    Args:
        warped_rgb: Rectified sRGB image in uint8. (已矫正的 sRGB uint8 图像)
        spec: Calibration grid specification. (标定栅格规格)
        sample_boxes: Pre-computed sampling rectangles. (预计算的采样框)

    Returns:
        Array of shape ``(grid_rows, grid_cols, 3)`` in **linear RGB** [0, 1].
    """
    samples = np.zeros((spec.grid_rows, spec.grid_cols, 3), dtype=np.float64)
    boxes = sample_boxes or _build_sample_boxes(warped_rgb, spec)
    for box in boxes:
        row = int(box["row"])
        col = int(box["col"])
        sx0 = int(box["x"])
        sy0 = int(box["y"])
        sx1 = sx0 + int(box["width"])
        sy1 = sy0 + int(box["height"])
        roi = warped_rgb[sy0:sy1, sx0:sx1]
        if roi.size == 0:
            continue
        roi_linear = _srgb_to_linear(roi.reshape(-1, 3))
        samples[row, col] = np.median(roi_linear, axis=0)
    return samples


def _build_warp_candidates(
    image_rgb: np.ndarray,
    points: np.ndarray,
    spec: SingleStageSpec,
) -> list[_WarpCandidate]:
    candidates: list[_WarpCandidate] = []
    for orientation_label, corner_order in _CORNER_ORIENTATION_CANDIDATES:
        ordered_points = points[np.asarray(corner_order, dtype=np.intp)]
        warped_rgb = _warp_image(image_rgb, ordered_points, spec)
        sample_boxes = _build_sample_boxes(warped_rgb, spec)
        linear_grid = _sample_grid_linear_means(warped_rgb, spec, sample_boxes)
        linear_samples = linear_grid.reshape(-1, 3)
        candidates.append(
            _WarpCandidate(
                orientation_label=orientation_label,
                corner_order=corner_order,
                ordered_points=ordered_points,
                warped_rgb=warped_rgb,
                sample_boxes=sample_boxes,
                linear_samples=linear_samples,
            )
        )
    return candidates


def _canonical_step_layers(spec: SingleStageSpec) -> np.ndarray:
    return np.asarray(spec.step_layers, dtype=np.float64).reshape(
        spec.grid_rows,
        spec.grid_cols,
    )


def _fit_component(
    thickness_mm: np.ndarray,
    white_obs: np.ndarray,
    black_obs: np.ndarray,
) -> tuple[float, float, float, float, float]:
    """Fit Beer-Lambert ``E`` and ``k`` against white/black substrate observations.
    基于白底/黑底观测拟合 Beer-Lambert 模型的 ``E`` 和 ``k``。

    Physical model per channel:
        ``pred(t, C0) = E + (C0 - E) * exp(-k * t)``

    Design choices (precision-oriented):
      - ``C0_white``/``C0_black`` are locked to the measured zero-thickness
        samples instead of being free variables. Letting the optimizer drift
        ``C0`` away from its direct measurement merely absorbs model noise
        into C0 and biases ``E``/``k``. (C0 采用零厚度格的实测值而非自由参数)
      - The initial ``k`` estimate applies a single aligned mask to both
        ``ratio`` and its corresponding ``thickness_mm`` — previously the
        filter masks got out of sync, causing a misalignment that produced
        noisy initial ``k`` values. (修复 k 初值估计时 ratio 与 t 错位的 bug)

    Args:
        thickness_mm: Per-sample thickness in mm, shape (N,). (每个样本的厚度 mm)
        white_obs: Linear RGB observations on white substrate, shape (N,). (白底线性观测)
        black_obs: Linear RGB observations on black substrate, shape (N,). (黑底线性观测)

    Returns:
        ``(E, k, C0_white, C0_black, rmse_linear)``. ``C0_*`` are the
        measured zero-thickness samples (not fitted). (C0 为实测值，非拟合结果)
    """
    zero_mask = thickness_mm == float(np.min(thickness_mm))
    max_mask = thickness_mm == float(np.max(thickness_mm))
    # Lock C0 to measured zero-thickness samples (may be multiple; use mean).
    c0_white = float(np.clip(np.mean(white_obs[zero_mask]), 0.0, 1.0))
    c0_black = float(np.clip(np.mean(black_obs[zero_mask]), 0.0, 1.0))
    # Initial E from maximum-thickness samples (closest to equilibrium color).
    e_init = float(
        np.clip(
            np.mean(np.concatenate([white_obs[max_mask], black_obs[max_mask]])),
            0.0,
            1.0,
        )
    )

    # Initial k: estimate from the closed-form ratio for each positive-thickness
    # sample. Apply filter masks consistently across ``ratio`` and ``t`` so
    # indices stay aligned (previously broken).
    k_init = 3.0
    for c0_value, obs in ((c0_white, white_obs), (c0_black, black_obs)):
        base_mask = (
            (thickness_mm > 0)
            & (np.abs(c0_value - e_init) > 1e-6)
            & (np.abs(obs - e_init) > 1e-6)
        )
        if not np.any(base_mask):
            continue
        obs_valid = obs[base_mask]
        t_valid = thickness_mm[base_mask]
        ratio = (obs_valid - e_init) / (c0_value - e_init)
        keep = np.isfinite(ratio) & (ratio > 1e-6) & (ratio < 0.999999)
        ratio = ratio[keep]
        t_valid = t_valid[keep]
        if ratio.size == 0:
            continue
        estimates = -np.log(ratio) / np.maximum(t_valid, 1e-6)
        estimates = estimates[np.isfinite(estimates) & (estimates > 1e-6)]
        if estimates.size:
            k_init = float(np.median(estimates))
            break

    init = np.array(
        [
            e_init,
            float(np.clip(k_init, 1e-4, 200.0)),
        ]
    )

    def _residuals(x: np.ndarray) -> np.ndarray:
        e, k = x
        decay = np.exp(-k * thickness_mm)
        pred_white = e + (c0_white - e) * decay
        pred_black = e + (c0_black - e) * decay
        return np.concatenate([pred_white - white_obs, pred_black - black_obs])

    result = least_squares(
        _residuals,
        init,
        bounds=(np.array([0.0, 1e-6]), np.array([1.0, 200.0])),
        method="trf",
        max_nfev=2000,
    )
    residual = _residuals(result.x)
    rmse = float(np.sqrt(np.mean(np.square(residual)))) if residual.size else 0.0
    e, k = result.x
    return float(e), float(k), c0_white, c0_black, rmse


def _rgb_to_lab_float(srgb_uint8: np.ndarray) -> np.ndarray:
    srgb_f32 = srgb_uint8.astype(np.float32) / 255.0
    lab = cv2.cvtColor(srgb_f32.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB)
    return lab.reshape(-1, 3).astype(np.float64)


def _build_fit_payload(
    *,
    material_label: str,
    thickness_mm: np.ndarray,
    white_linear: np.ndarray,
    black_linear: np.ndarray,
    sample_boxes: list[dict[str, int]],
    warp_width_px: int,
    warp_height_px: int,
    manifest: dict[str, Any],
    spec: SingleStageSpec,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[str]]:
    e_values: list[float] = []
    k_values: list[float] = []
    c0_white_values: list[float] = []
    c0_black_values: list[float] = []
    channel_rmse: list[float] = []
    warnings: list[str] = []
    for channel_idx in range(3):
        e_val, k_val, c0_white, c0_black, rmse = _fit_component(
            thickness_mm,
            white_linear[:, channel_idx],
            black_linear[:, channel_idx],
        )
        e_values.append(e_val)
        k_values.append(k_val)
        c0_white_values.append(c0_white)
        c0_black_values.append(c0_black)
        channel_rmse.append(rmse)
    pred_white = np.asarray(e_values) + (np.asarray(c0_white_values) - np.asarray(e_values)) * np.exp(
        -np.outer(thickness_mm, np.asarray(k_values))
    )
    pred_black = np.asarray(e_values) + (np.asarray(c0_black_values) - np.asarray(e_values)) * np.exp(
        -np.outer(thickness_mm, np.asarray(k_values))
    )
    observed_linear = np.vstack([white_linear, black_linear])
    predicted_linear = np.vstack([pred_white, pred_black])
    observed_srgb = _linear_to_srgb_uint8(observed_linear)
    predicted_srgb = _linear_to_srgb_uint8(predicted_linear)
    delta_e = np.linalg.norm(_rgb_to_lab_float(observed_srgb) - _rgb_to_lab_float(predicted_srgb), axis=1)
    overall_validation = {
        "mean_delta_e": float(np.mean(delta_e)) if delta_e.size else 0.0,
        "max_delta_e": float(np.max(delta_e)) if delta_e.size else 0.0,
        "rmse_linear": float(np.sqrt(np.mean(np.square(predicted_linear - observed_linear)))) if observed_linear.size else 0.0,
        "channel_rmse": channel_rmse,
    }
    if overall_validation["mean_delta_e"] > 3.0:
        warnings.append("Stage A 拟合误差较高，请检查图像方向和角点选择。")
    c0_white_mean = float(np.mean(np.asarray(c0_white_values, dtype=np.float64)))
    if c0_white_mean > _C0_WHITE_OVERBRIGHT_THRESHOLD:
        warnings.append(
            "零厚度白底采样接近纯白（C0_white 均值 "
            f"{c0_white_mean:.3f} > {_C0_WHITE_OVERBRIGHT_THRESHOLD:.2f}），"
            "说明 Stage A 采样区域可能发生高光裁切或过亮归一化。"
            "裁切会让拟合得到的 (E, k) 偏离真实物理值；"
            "请重新拍摄或调整曝光/校色设置，使用未裁切的输入重新提取。"
        )
    params_payload: dict[str, Any] = {
        "param_type": "stage_A",
        "meta": {
            "schema_version": "1.0",
            "generated_at": material_files._now_iso(),
            "source": "lumina_gradient_card_extract",
            "workflow": str(manifest.get("workflow", "single-stage-kit")),
            "warnings": warnings,
        },
        "parameters": {
            "channels": [
                {
                    "channel_index": 0,
                    "color_name": material_label,
                    "E": [round(float(value), 6) for value in e_values],
                    "k": [round(float(value), 6) for value in k_values],
                }
            ],
            "substrates": [
                {
                    "substrate_idx": 0,
                    "substrate_id": "white",
                    "display_name": "White",
                    "C0": [round(float(value), 6) for value in c0_white_values],
                },
                {
                    "substrate_idx": 1,
                    "substrate_id": "black",
                    "display_name": "Black",
                    "C0": [round(float(value), 6) for value in c0_black_values],
                },
            ],
        },
        "fitted_substrates": {
            "white": {"C0": [round(float(value), 6) for value in c0_white_values]},
            "black": {"C0": [round(float(value), 6) for value in c0_black_values]},
        },
        "validation": {"overall": overall_validation},
        "source": {
            "spec": asdict(spec),
            "manifest": {
                "schema_version": manifest.get("schema_version"),
                "workflow": manifest.get("workflow"),
                "material_default": manifest.get("material_default"),
                "substrate_id": manifest.get("substrate_id"),
                "substrate_display_name": manifest.get("substrate_display_name"),
            },
        },
    }
    fit_summary = {
        "substrate_count": 2,
        "channel_count": 1,
        "substrates": ["black", "white"],
        "colors": [material_label],
        "overall_validation": overall_validation,
        "warnings": warnings,
    }
    material_summary = {
        "sample_count": int(thickness_mm.size * 2),
        "per_substrate_sample_count": int(thickness_mm.size),
        "grid_rows": int(spec.grid_rows),
        "grid_cols": int(spec.grid_cols),
        "layer_height_mm": float(spec.layer_height_mm),
        "warp_width_px": int(warp_width_px),
        "warp_height_px": int(warp_height_px),
        "thickness_layers": [int(round(value / spec.layer_height_mm)) for value in thickness_mm.tolist()],
        "sample_boxes": sample_boxes,
        "white_zero_rgb": _linear_to_srgb_uint8(np.asarray([c0_white_values], dtype=np.float64))[0].tolist(),
        "black_zero_rgb": _linear_to_srgb_uint8(np.asarray([c0_black_values], dtype=np.float64))[0].tolist(),
        "estimated_rgb": _linear_to_srgb_uint8(np.asarray([e_values], dtype=np.float64))[0].tolist(),
        "estimated_k": [round(float(value), 6) for value in k_values],
        # Persist the linear-RGB sample matrices (one row per sampled grid
        # cell, three channels per row) and matching thickness_mm vector so
        # multi-run "再次验证" aggregation can re-fit on the *combined* sample
        # set instead of averaging per-run parameters. Averaging non-linear
        # Beer-Lambert parameters is statistically unsound; combined-sample
        # refitting is the only way "more captures = more accurate (E, k)"
        # holds true.
        # 持久化线性 RGB 样本矩阵与厚度向量，使"再次验证"聚合时能基于
        # 合并样本重新拟合（而非对参数做算术平均），让"多次校准 = 更精确"
        # 在统计上成立。
        "fit_samples": {
            "schema_version": "1.0",
            "thickness_mm": [float(value) for value in thickness_mm.tolist()],
            "white_linear": [
                [float(value) for value in row]
                for row in np.asarray(white_linear, dtype=np.float64).tolist()
            ],
            "black_linear": [
                [float(value) for value in row]
                for row in np.asarray(black_linear, dtype=np.float64).tolist()
            ],
        },
    }
    return params_payload, fit_summary, material_summary, warnings


def _fit_score(fit_summary: dict[str, Any]) -> tuple[float, float, float]:
    validation = fit_summary.get("overall_validation", {})
    return (
        float(validation.get("mean_delta_e", float("inf"))),
        float(validation.get("rmse_linear", float("inf"))),
        float(validation.get("max_delta_e", float("inf"))),
    )


def _substrate_anchor_penalty(
    candidate: _WarpCandidate,
    spec: SingleStageSpec,
    substrate: str,
) -> float:
    """Compute a penalty based on how far the zero-thickness sample deviates
    from the expected substrate color.
    计算零厚度采样点偏离基底色的惩罚值。

    For a white substrate, the zero-thickness sample (grid[0,0]) should be
    near pure white (linear ≈ 1.0). For black, near pure black (linear ≈ 0.0).
    Returns the mean squared deviation from the expected color across RGB channels.
    """
    step_layers = np.asarray(spec.step_layers, dtype=np.float64)
    zero_mask = step_layers == 0.0
    if not np.any(zero_mask):
        return 0.0
    zero_samples = candidate.linear_samples[zero_mask]
    if substrate == "white":
        target = 1.0
    elif substrate == "black":
        target = 0.0
    else:
        return 0.0
    return float(np.mean(np.square(zero_samples - target)))


_ORIENTATION_RELIABLE_DELTA_E_GAP = 0.3


# Per-substrate signal-strength threshold below which the substrate is
# considered "flat" (no usable orientation gradient). Used only for
# diagnostic reporting and warning messages — NOT for restricting the
# candidate set, since real-world materials with low absorption can produce
# legitimately small per-cell variance even when the orientation IS
# determinable. Empirically: white-on-white captures sit around 0.005, while
# even low-contrast colored materials produce >0.02. We pick 0.015 as the
# diagnostic boundary. (仅用于诊断与提示，不再用于强制收缩候选集)
_FLAT_SUBSTRATE_SIGNAL_THRESHOLD = 0.015

_VALID_ORIENTATION_LABELS: frozenset[str] = frozenset(
    label for label, _ in _CORNER_ORIENTATION_CANDIDATES
)


def _candidate_signal_strength(candidate: _WarpCandidate) -> float:
    """Per-substrate signal strength = std of linear samples across cells.
    单基底"信号强度" = 各采样格线性 RGB 的标准差。

    Used to diagnose when the orientation gradient is too weak to be
    distinguishable from noise (e.g. a white material on a white substrate).
    用于诊断"梯度信号是否过弱"（如白底拍白色耗材），仅作为警示，不直接收缩候选集。
    """
    samples = candidate.linear_samples
    if samples.size == 0:
        return 0.0
    return float(np.std(samples))


def _select_candidates(
    candidates: list[_WarpCandidate],
    *,
    manual_label: str | None,
    signal_threshold: float = _FLAT_SUBSTRATE_SIGNAL_THRESHOLD,
) -> tuple[list[_WarpCandidate], dict[str, Any]]:
    """Filter the candidate set for one substrate.
    针对单一基底过滤方向候选集合。

    Resolution order (优先级):
      1. ``manual_label`` (if set and valid) wins absolutely — restricts the
         candidate set to that single orientation.
      2. Otherwise the full candidate set is returned. Signal strength is
         still computed and surfaced as diagnostic info, but is *not* used
         to restrict candidates (low signal can be a legitimate property
         of low-absorption materials, not necessarily an orientation
         ambiguity).

    Returns:
        ``(filtered_candidates, info)`` where ``info`` is a dict with
        ``signal_strength``, ``flat``, ``manual_override``, ``locked_to``.
    """
    if not candidates:
        return [], {"signal_strength": 0.0, "flat": False, "manual_override": None, "locked_to": None}

    # MAX over all 8 candidates: the "wrong" orientations distort cell layout
    # (e.g. a rotated capture warped under identity gets squished and mixes
    # adjacent cells, deflating the per-orientation std). Only the
    # best-aligned orientation reflects the true substrate gradient.
    # 取所有候选方向中 std 的最大值，仅最佳对齐方向能反映真实梯度幅度。
    signal = max((_candidate_signal_strength(c) for c in candidates), default=0.0)
    flat = signal < signal_threshold

    info: dict[str, Any] = {
        "signal_strength": round(signal, 6),
        "flat": flat,
        "manual_override": None,
        "locked_to": None,
    }

    if manual_label:
        if manual_label not in _VALID_ORIENTATION_LABELS:
            valid = ", ".join(sorted(_VALID_ORIENTATION_LABELS))
            raise ValueError(
                f"Invalid orientation label {manual_label!r}; expected one of: {valid}"
            )
        chosen = [c for c in candidates if c.orientation_label == manual_label]
        if chosen:
            info["manual_override"] = manual_label
            info["locked_to"] = manual_label
            return chosen, info

    return candidates, info


def _build_orientation_ranking(
    sorted_results: list[tuple[Any, ...]],
    *,
    top_n: int = 5,
) -> dict[str, Any]:
    """Build a ranking summary of the top orientation candidates.
    构建最优方向候选的排名摘要。

    Args:
        sorted_results: All candidate results sorted by score ascending.
            (按得分升序排列的全部候选结果)
        top_n: Number of top candidates to include in the ranking. (排名条目数)

    Returns:
        dict with ``orientation_reliable``, ``delta_e_gap``, and ``top_candidates``.
    """
    top = sorted_results[:top_n]
    entries: list[dict[str, Any]] = []
    for result in top:
        score, white_cand, black_cand = result[0], result[1], result[2]
        entries.append({
            "white_orientation": white_cand.orientation_label,
            "black_orientation": black_cand.orientation_label,
            "anchor_penalty": round(score[0], 6),
            "mean_delta_e": round(score[1], 4),
            "rmse_linear": round(score[2], 6),
            "max_delta_e": round(score[3], 4),
        })
    best_de = entries[0]["mean_delta_e"] if entries else float("inf")
    second_de = entries[1]["mean_delta_e"] if len(entries) >= 2 else float("inf")
    gap = round(second_de - best_de, 4)
    return {
        "orientation_reliable": gap >= _ORIENTATION_RELIABLE_DELTA_E_GAP,
        "delta_e_gap": gap,
        "top_candidates": entries,
    }


def extract_stage_a_material_from_gradient_cards(
    white_image_rgb: np.ndarray,
    black_image_rgb: np.ndarray,
    white_corner_points: list[tuple[float, float]] | list[list[float]],
    black_corner_points: list[tuple[float, float]] | list[list[float]],
    dataset_zip_path: str,
    output_path: str | None = None,
    *,
    manual_white_orientation: str | None = None,
    manual_black_orientation: str | None = None,
    image_source: str | None = None,
) -> GradientCardStageAResult:
    """Extract Stage A material data from white/black gradient-card images.
    从白底/黑底梯度卡图像中提取 Stage A 耗材参数。

    Args:
        white_image_rgb: White-substrate source image in RGB uint8. (白底源图，RGB uint8)
        black_image_rgb: Black-substrate source image in RGB uint8. (黑底源图，RGB uint8)
        white_corner_points: White image corners in TL/TR/BR/BL order. (白底图四角，顺序 TL/TR/BR/BL)
        black_corner_points: Black image corners in TL/TR/BR/BL order. (黑底图四角，顺序 TL/TR/BR/BL)
        dataset_zip_path: Generated gradient-card kit zip path. (梯度卡套件 ZIP 路径)
        output_path: Optional temporary Stage A JSON output path. (可选的临时 Stage A JSON 输出路径)
        manual_white_orientation: Optional manual orientation label for the
            white capture, bypassing auto-detection. Must be one of
            ``identity``, ``rotate_90_cw``, ``rotate_180``, ``rotate_90_ccw``,
            ``flip_horizontal``, ``flip_vertical``, ``transpose``,
            ``transverse``. (可选：手动指定白底方向，覆盖自动检测)
        manual_black_orientation: Same for the black capture. (黑底方向，同上)
        image_source: Optional capture origin tag, one of ``"raw"`` or
            ``"restored"``. ``"raw"`` (default) means the input is a direct
            camera/scanner capture; ``"restored"`` means the image has been
            ColorChecker-corrected or geometrically restored. The tag is
            persisted in
            ``source_summary["image_source"]`` so the multi-run aggregator
            can refuse to mix raw/restored captures.
            可选的图像来源标签：``"raw"`` 为相机/扫描原图（默认），
            ``"restored"`` 为已 ColorChecker 校正或几何还原过的图（会阻止
            与原图样本静默混合聚合）。

    Returns:
        GradientCardStageAResult: Extraction result bundle. (提取结果)
    """
    image_source_tag: str = "raw" if image_source is None else str(image_source).strip().lower()
    if image_source_tag not in _VALID_IMAGE_SOURCES:
        raise ValueError(
            f"image_source must be one of {sorted(_VALID_IMAGE_SOURCES)}, "
            f"got {image_source!r}"
        )
    manifest = _load_manifest_from_zip(dataset_zip_path)
    spec = _coerce_spec(manifest)
    white_points = _coerce_points(white_corner_points)
    black_points = _coerce_points(black_corner_points)
    all_white_candidates = _build_warp_candidates(white_image_rgb, white_points, spec)
    all_black_candidates = _build_warp_candidates(black_image_rgb, black_points, spec)
    white_candidates, white_orientation_info = _select_candidates(
        all_white_candidates,
        manual_label=manual_white_orientation,
    )
    black_candidates, black_orientation_info = _select_candidates(
        all_black_candidates,
        manual_label=manual_black_orientation,
    )
    step_layers = _canonical_step_layers(spec).reshape(-1)
    thickness_mm = step_layers * float(spec.layer_height_mm)
    material_label = str(manifest.get("material_default") or "Sample")
    _CandidateResult = tuple[
        tuple[float, float, float, float],
        _WarpCandidate,
        _WarpCandidate,
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        list[str],
    ]
    all_results: list[_CandidateResult] = []
    for white_candidate in white_candidates:
        for black_candidate in black_candidates:
            params_payload, fit_summary, material_summary, warnings = _build_fit_payload(
                material_label=material_label,
                thickness_mm=thickness_mm,
                white_linear=white_candidate.linear_samples,
                black_linear=black_candidate.linear_samples,
                sample_boxes=white_candidate.sample_boxes,
                warp_width_px=int(white_candidate.warped_rgb.shape[1]),
                warp_height_px=int(white_candidate.warped_rgb.shape[0]),
                manifest=manifest,
                spec=spec,
            )
            fit_score = _fit_score(fit_summary)
            anchor = (
                _substrate_anchor_penalty(white_candidate, spec, "white")
                + _substrate_anchor_penalty(black_candidate, spec, "black")
            )
            score = (anchor, fit_score[0], fit_score[1], fit_score[2])
            all_results.append((
                score,
                white_candidate,
                black_candidate,
                params_payload,
                fit_summary,
                material_summary,
                warnings,
            ))
    if not all_results:
        raise ValueError("Unable to determine gradient card orientation")
    all_results.sort(key=lambda r: r[0])
    best = all_results[0]
    _, white_candidate, black_candidate, params_payload, fit_summary, material_summary, warnings = best
    orientation_ranking = _build_orientation_ranking(all_results)
    orientation_ranking["white_signal_strength"] = white_orientation_info["signal_strength"]
    orientation_ranking["black_signal_strength"] = black_orientation_info["signal_strength"]
    orientation_ranking["white_orientation_info"] = white_orientation_info
    orientation_ranking["black_orientation_info"] = black_orientation_info
    # The "delta_e_gap" reliability check is meaningful only when more than
    # one combination was actually evaluated; when manual override or flat-
    # substrate fallback collapses one side to a single candidate, the gap is
    # an artefact of that collapse, not a real ambiguity signal.
    # 候选集合被收紧到 1 个时，gap 不再代表真实的方向歧义，跳过该警告。
    multi_combination_search = len(all_results) >= 2
    if multi_combination_search and orientation_ranking["orientation_reliable"] is False:
        warnings.append("方向检测置信度较低，最优与次优方向的 ΔE 差距很小，请确认角点和图片方向。")
    # Soft warnings when a substrate has near-zero gradient signal AND was
    # not manually pinned. The auto-detector's choice may be unreliable —
    # nudge the user toward the manual override path.
    if white_orientation_info["flat"] and white_orientation_info["manual_override"] is None:
        warnings.append(
            "白底采样格颜色变化极小（疑似白色耗材打白底），自动方向检测可能不可靠；"
            "如发现拟合误差偏高，请使用界面的“纯色块位置”选项手动指定方向。"
        )
    if black_orientation_info["flat"] and black_orientation_info["manual_override"] is None:
        warnings.append(
            "黑底采样格颜色变化极小，自动方向检测可能不可靠；"
            "如发现拟合误差偏高，请使用界面的“纯色块位置”选项手动指定方向。"
        )
    fit_summary["orientation_ranking"] = orientation_ranking
    if image_source_tag == "restored":
        # ``warnings`` is the same list object held by ``fit_summary["warnings"]``
        # and ``params_payload["meta"]["warnings"]`` (set inside _build_fit_payload),
        # so this single append surfaces the warning everywhere.
        # 该 list 同时被 fit_summary 与 params_meta 引用，append 一次即可在三处可见。
        warnings.append(
            "已选择 ColorChecker 校正/还原后的梯度卡图作为 Stage A 输入。"
            "色卡校正可减少相机色差，通常有利于拟合；请保持白底图、黑底图"
            "来自同一相机、曝光、白平衡和校色设置，并确认 Stage A 采样区域"
            "未发生高光/阴影裁切。风险判断以“零厚度白底采样接近纯白”"
            "等已有采样警告为准；若出现该类警告，请重新拍摄或调整曝光/校色"
            "设置后再提取。"
        )
    # Persist the image-source tag in params meta so external tooling
    # (audit scripts, downstream consumers) can read the tag straight from
    # the JSON payload without having to reconstruct it from source_summary.
    # 把 image_source 写入 params meta，使审计脚本/下游消费者无需重建
    # source_summary 即可直接读到来源标签。
    params_meta = params_payload.setdefault("meta", {})
    params_meta["image_source"] = image_source_tag
    white_warp_rgb = white_candidate.warped_rgb
    black_warp_rgb = black_candidate.warped_rgb
    if output_path is None:
        output_path = str(Path(material_files.TEMP_DIR) / f"stage_a_material_{uuid.uuid4().hex}.json")
    Path(output_path).write_text(
        json.dumps(params_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    source_summary = {
        "kit_manifest": manifest,
        "white_corner_points": [[int(round(value)) for value in point] for point in white_points.tolist()],
        "black_corner_points": [[int(round(value)) for value in point] for point in black_points.tolist()],
        "white_detected_orientation": white_candidate.orientation_label,
        "black_detected_orientation": black_candidate.orientation_label,
        "white_detected_corner_order": [int(value) for value in white_candidate.corner_order],
        "black_detected_corner_order": [int(value) for value in black_candidate.corner_order],
        "white_orientation_info": white_orientation_info,
        "black_orientation_info": black_orientation_info,
        "orientation_ranking": orientation_ranking,
        "spec": asdict(spec),
        "image_source": image_source_tag,
    }
    return GradientCardStageAResult(
        params_path=str(output_path),
        params_payload=params_payload,
        fit_summary=fit_summary,
        material_summary=material_summary,
        source_summary=source_summary,
        warnings=warnings,
        white_warp_rgb=white_warp_rgb,
        black_warp_rgb=black_warp_rgb,
    )
