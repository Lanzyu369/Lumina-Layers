from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Sequence
from urllib.parse import urljoin, urlsplit

import cv2
import numpy as np
from scipy.optimize import least_squares

from config import MATERIALS_DIR, TEMP_DIR
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
class MaterialArchiveSaveResult:
    """Persistent material archive save result.
    持久化耗材归档保存结果。

    Attributes:
        archive_path: Saved material archive JSON path. (保存后的耗材归档 JSON 路径)
        stage_a_params_path: Saved Stage A parameter JSON path. (保存后的 Stage A 参数 JSON 路径)
        material_summary: Archive summary for UI/API. (用于 UI/API 的归档摘要)
    """

    archive_path: str
    stage_a_params_path: str
    material_summary: dict[str, Any]


@dataclass(frozen=True)
class MaterialArchiveDeleteResult:
    """Persistent material archive delete result.
    持久化耗材归档删除结果。

    Attributes:
        directory_name: Deleted material directory name. (删除的耗材目录名)
        material_name: Deleted material name. (删除的耗材名称)
        deleted_path: Deleted material directory path. (删除的耗材目录路径)
    """

    directory_name: str
    material_name: str
    deleted_path: str


@dataclass(frozen=True)
class MaterialArchiveUpdateResult:
    """Persistent material archive metadata update result.
    持久化耗材归档元数据更新结果。

    Attributes:
        archive_path: Updated material archive JSON path. (更新后的耗材归档 JSON 路径)
        stage_a_params_path: Updated Stage A parameter JSON path. (更新后的 Stage A 参数 JSON 路径)
        material_summary: Archive summary for UI/API. (用于 UI/API 的归档摘要)
    """

    archive_path: str
    stage_a_params_path: str
    material_summary: dict[str, Any]


@dataclass(frozen=True)
class MaterialArchiveExportResult:
    """Persistent material archive export result.
    持久化耗材归档导出结果。

    Attributes:
        archive_path: Generated ZIP archive path. (生成的 ZIP 归档路径)
        download_filename: Suggested download filename. (建议下载文件名)
        exported_directory_names: Exported saved-material directory names. (导出的耗材目录名)
    """

    archive_path: str
    download_filename: str
    exported_directory_names: list[str]


@dataclass(frozen=True)
class MaterialArchiveImportResult:
    """Persistent material archive import result.
    持久化耗材归档导入结果。

    Attributes:
        imported_materials: Imported material summaries for UI/API. (用于 UI/API 的导入耗材摘要)
    """

    imported_materials: list[dict[str, Any]]


@dataclass(frozen=True)
class _WarpCandidate:
    orientation_label: str
    corner_order: tuple[int, int, int, int]
    ordered_points: np.ndarray
    warped_rgb: np.ndarray
    sample_boxes: list[dict[str, int]]
    linear_samples: np.ndarray


_INVALID_WINDOWS_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MATERIAL_EXPORT_MANIFEST_FILENAME = "lumina_material_export.json"
_MATERIAL_BUNDLE_MANIFEST_FILENAME = "lumina_material_bundle.json"
_MATERIAL_PACKAGE_SCHEMA_VERSION = "2.0"
_MATERIAL_SYNC_INDEX_SCHEMA_VERSION = "1.0"
_MATERIAL_SYNC_REFRESH_LOCK_FILENAME = "refresh.lock"
_MATERIAL_SYNC_LOCK_STALE_SECONDS = 2 * 60 * 60
_MATERIAL_SYNC_STATUS_CACHE_TTL_S = 5 * 60
_MATERIAL_LIBRARY_CACHE_TTL_S = 5 * 60
_MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE_TTL_S = 5 * 60
_MATERIAL_LOCAL_ONLY_FILENAMES = frozenset({"usage_stats.json"})
_MATERIAL_LOCAL_ONLY_DIRNAMES = frozenset({"_solver_cache"})
_MATERIAL_SYNC_STATUS_CACHE_LOCK = threading.RLock()
_MATERIAL_SYNC_STATUS_CACHE: dict[str, dict[str, Any]] = {}
_MATERIAL_LIBRARY_CACHE_LOCK = threading.RLock()
_MATERIAL_LIBRARY_CACHE: dict[str, dict[str, Any]] = {}
_MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE_LOCK = threading.RLock()
_MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE: dict[
    tuple[str, tuple[str, ...], str, Any, int | None, int, str],
    dict[str, Any],
] = {}
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



def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



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
            "generated_at": _now_iso(),
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
        output_path = str(Path(TEMP_DIR) / f"stage_a_material_{uuid.uuid4().hex}.json")
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



def _sanitize_material_dirname(material_name: str) -> str:
    cleaned = _INVALID_WINDOWS_FILENAME.sub("_", str(material_name)).strip().strip(". ")
    return cleaned or "material"



def _unique_material_dir(
    base_dir: Path,
    material_name: str,
    *,
    brand: str | None = None,
) -> Path:
    """Compute an unused material directory path, optionally under a brand subdir.
    计算未被占用的耗材目录路径，可选放入品牌子目录。
    """
    stem = _sanitize_material_dirname(material_name)
    parent = base_dir
    if brand is not None:
        brand_stem = _sanitize_material_dirname(brand)
        parent = base_dir / brand_stem
    candidate = parent / stem
    if not candidate.exists():
        return candidate
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    return parent / f"{stem}_{suffix}"




def _json_clone(payload: Any) -> Any:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _material_library_cache_key(target_root: Path) -> str:
    try:
        return str(target_root.resolve())
    except OSError:
        return str(target_root.absolute())


def _cached_material_library_items(target_root: Path) -> list[dict[str, Any]] | None:
    cache_key = _material_library_cache_key(target_root)
    now = time.monotonic()
    with _MATERIAL_LIBRARY_CACHE_LOCK:
        cached = _MATERIAL_LIBRARY_CACHE.get(cache_key)
        if not cached:
            return None
        cached_at = float(cached.get("cached_at") or 0.0)
        if now - cached_at > _MATERIAL_LIBRARY_CACHE_TTL_S:
            _MATERIAL_LIBRARY_CACHE.pop(cache_key, None)
            return None
        payload = cached.get("payload")
        if not isinstance(payload, list):
            return None
        return _json_clone(payload)


def _store_material_library_cache(target_root: Path, payload: list[dict[str, Any]]) -> None:
    cache_key = _material_library_cache_key(target_root)
    with _MATERIAL_LIBRARY_CACHE_LOCK:
        _MATERIAL_LIBRARY_CACHE[cache_key] = {
            "cached_at": time.monotonic(),
            "payload": _json_clone(payload),
        }


def _invalidate_material_library_cache(target_root: Path | None = None) -> None:
    with _MATERIAL_LIBRARY_CACHE_LOCK:
        if target_root is None:
            _MATERIAL_LIBRARY_CACHE.clear()
            return
        _MATERIAL_LIBRARY_CACHE.pop(_material_library_cache_key(target_root), None)



def _normalize_relative_directory_name(directory_name: str) -> str:
    """Normalize a user-provided material directory_name to a POSIX relative path.
    将用户提供的耗材 directory_name 归一化为 POSIX 相对路径。

    Accepts forward-slash or backslash separators for cross-platform tolerance,
    rejects empty / absolute / traversal inputs, and returns the canonical
    forward-slash form. Does not touch the filesystem.
    """
    raw = str(directory_name).strip().replace("\\", "/")
    if not raw or raw in {".", ".."}:
        raise ValueError("directory_name must reference a saved material directory")
    if raw.startswith("/"):
        raise ValueError("directory_name must be a relative path")
    parts = [segment for segment in raw.split("/") if segment]
    if not parts:
        raise ValueError("directory_name must reference a saved material directory")
    for segment in parts:
        if segment in {".", ".."}:
            raise ValueError("directory_name must not contain '.' or '..' segments")
    requested = Path(*parts)
    if requested.anchor:
        raise ValueError("directory_name must be a relative path")
    return "/".join(parts)



def resolve_saved_material_dir(base_dir: Path, directory_name: str) -> Path:
    """Safely resolve a saved-material directory under ``base_dir``.
    在 ``base_dir`` 之下安全解析已保存的耗材目录。

    Supports multi-segment relative directory names (e.g. ``"瑞贝思/瑞贝思 PLA 白"``)
    while preventing path traversal: the resolved path must remain inside
    ``base_dir``. Returns the existing directory as a ``Path``.
    """
    normalized = _normalize_relative_directory_name(directory_name)
    candidate = (base_dir / normalized)
    try:
        resolved = candidate.resolve()
        root_resolved = base_dir.resolve()
    except OSError as exc:
        raise FileNotFoundError(f"Saved material directory not found: {normalized}") from exc
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("directory_name escapes the materials directory") from exc
    if not resolved.is_dir():
        raise FileNotFoundError(f"Saved material directory not found: {normalized}")
    return resolved


def _resolve_material_dir(base_dir: Path, directory_name: str) -> Path:
    """Backward-compatible alias kept for internal call sites."""
    return resolve_saved_material_dir(base_dir, directory_name)


def _relative_directory_name(base_dir: Path, material_dir: Path) -> str:
    """Return POSIX-style relative directory name for a saved material."""
    try:
        rel = material_dir.resolve().relative_to(base_dir.resolve())
    except ValueError:
        rel = Path(material_dir.name)
    return rel.as_posix()


def _prune_empty_parents(start_dir: Path, stop_dir: Path) -> None:
    """Remove empty ancestor directories up to (but excluding) ``stop_dir``.
    向上清理空的祖先目录，遇到 ``stop_dir`` 即停止（不含）。

    Best-effort: any OSError (non-empty, permission, etc.) halts pruning.
    """
    try:
        stop = stop_dir.resolve()
        current = start_dir.resolve()
    except OSError:
        return
    while current != stop and stop in current.parents:
        try:
            if any(current.iterdir()):
                return
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _filter_nested_material_archive_paths(archive_paths: list[Path]) -> list[Path]:
    material_dirs_set = {path.parent.resolve() for path in archive_paths if path.is_file()}
    filtered_archive_paths: list[Path] = []
    for path in archive_paths:
        try:
            parent = path.parent.resolve()
        except OSError:
            continue
        ancestors = set(parent.parents) & material_dirs_set
        if ancestors:
            continue
        filtered_archive_paths.append(path)
    return filtered_archive_paths


def _load_json_object(path: Path, error_message: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(error_message) from exc
    if not isinstance(payload, dict):
        raise ValueError(error_message)
    return payload


def _resolve_stage_a_params_path(material_dir: Path, archive_payload: dict[str, Any]) -> Path:
    raw_value = str(archive_payload.get("stage_a_params_file") or "stage_A_parameters.json")
    normalized = raw_value.strip().replace("\\", "/")
    if not normalized:
        raise ValueError("stage_a_params_file must reference a file inside the material directory")
    path_parts = [segment for segment in normalized.split("/") if segment]
    if not path_parts or any(segment in {".", ".."} for segment in path_parts):
        raise ValueError("stage_a_params_file must reference a file inside the material directory")
    candidate = material_dir / Path(*path_parts)
    try:
        resolved = candidate.resolve()
        material_root = material_dir.resolve()
    except OSError as exc:
        raise ValueError("stage_a_params_file must reference a file inside the material directory") from exc
    try:
        resolved.relative_to(material_root)
    except ValueError as exc:
        raise ValueError("stage_a_params_file must reference a file inside the material directory") from exc
    return resolved


def _saved_material_brand_from_archive_payload(
    archive_payload: dict[str, Any],
    relative_directory_name: str,
) -> str | None:
    if "brand" in archive_payload:
        raw_brand = archive_payload.get("brand")
        if isinstance(raw_brand, str):
            cleaned_brand = raw_brand.strip()
            return cleaned_brand or None
        return None
    if "/" in relative_directory_name:
        return relative_directory_name.split("/", 1)[0]
    return None


def _material_summary_from_saved_archive(
    target_root: Path,
    material_dir: Path,
    archive_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    archive_path = material_dir / "material.json"
    payload = archive_payload or _load_json_object(
        archive_path,
        "Saved material archive is not valid UTF-8 JSON",
    )
    relative_directory_name = _relative_directory_name(target_root, material_dir)
    stage_a_params_path = _resolve_stage_a_params_path(material_dir, payload)
    if not stage_a_params_path.exists():
        raise FileNotFoundError(
            f"Saved Stage A parameters not found for material: {relative_directory_name}"
        )
    verification_runs = payload.get("verification_runs")
    try:
        verification_count = int(
            payload.get("verification_count")
            or (len(verification_runs) if isinstance(verification_runs, list) else 1)
            or 1
        )
    except (TypeError, ValueError):
        verification_count = len(verification_runs) if isinstance(verification_runs, list) and verification_runs else 1
    brand_value = _saved_material_brand_from_archive_payload(
        payload,
        relative_directory_name,
    )
    aggregation = payload.get("aggregation") if isinstance(payload.get("aggregation"), dict) else None
    aggregation_method: str | None = None
    aggregation_selection: dict[str, Any] | None = None
    if isinstance(aggregation, dict):
        method_value = aggregation.get("method")
        if isinstance(method_value, str):
            aggregation_method = method_value
        selection_value = aggregation.get("selection")
        if isinstance(selection_value, dict):
            aggregation_selection = _json_clone(selection_value)
    usage_payload = _load_usage_payload(material_dir)
    return {
        "material_name": str(payload.get("material_name") or material_dir.name),
        "directory_name": relative_directory_name,
        "brand": brand_value,
        "archive_path": str(archive_path),
        "stage_a_params_path": str(stage_a_params_path),
        "verification_count": verification_count,
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at") or payload.get("created_at"),
        # Aggregation diagnostics surfaced to the frontend so the user
        # can see which historical runs participated in the joint refit
        # and which were excluded by the bias filter / cross-val ranking.
        # (聚合诊断信息透传给前端用于"合并诊断"折叠区)
        "aggregation_method": aggregation_method,
        "aggregation_selection": aggregation_selection,
        "usage_total": int(usage_payload.get("total") or 0),
        "usage_by_color_mode": dict(usage_payload.get("by_color_mode") or {}),
        "usage_last_used_at": usage_payload.get("last_used_at"),
        "usage_last_used_color_mode": usage_payload.get("last_used_color_mode"),
    }


def _saved_material_library_item_from_archive(
    target_root: Path,
    material_dir: Path,
    archive_payload: dict[str, Any],
) -> dict[str, Any]:
    archive_path = material_dir / "material.json"
    try:
        stage_a_path = _resolve_stage_a_params_path(material_dir, archive_payload)
    except ValueError:
        stage_a_path = material_dir / "stage_A_parameters.json"
    fit_summary = archive_payload.get("fit_summary") or {}
    material_summary = archive_payload.get("material_summary") or {}
    overall_validation = fit_summary.get("overall_validation") or {}
    estimated_rgb = material_summary.get("estimated_rgb")
    if not isinstance(estimated_rgb, list):
        estimated_rgb = []
    try:
        estimated_rgb_values = [int(value) for value in estimated_rgb[:3]]
    except (TypeError, ValueError):
        estimated_rgb_values = []
    verification_runs = _load_existing_verification_runs(
        material_dir,
        archive_payload,
    )
    verification_history = _summarize_verification_runs(verification_runs)
    try:
        verification_count = int(
            archive_payload.get("verification_count")
            or len(verification_history)
            or 1
        )
    except (TypeError, ValueError):
        verification_count = len(verification_history) or 1

    relative_directory_name = _relative_directory_name(target_root, material_dir)
    brand_value = _saved_material_brand_from_archive_payload(
        archive_payload,
        relative_directory_name,
    )
    usage_payload = _load_usage_payload(material_dir)
    return {
        "material_name": str(
            archive_payload.get("material_name") or material_dir.name
        ),
        "directory_name": relative_directory_name,
        "brand": brand_value,
        "created_at": archive_payload.get("created_at"),
        "updated_at": archive_payload.get("updated_at")
        or archive_payload.get("created_at"),
        "archive_path": str(archive_path),
        "stage_a_params_path": (
            str(stage_a_path) if stage_a_path.exists() else None
        ),
        "estimated_rgb": estimated_rgb_values,
        "layer_height_mm": material_summary.get("layer_height_mm"),
        "mean_delta_e": overall_validation.get("mean_delta_e"),
        "verification_count": verification_count,
        "verification_history": verification_history,
        # Usage statistics (sidecar file, never gates main flow):
        # 使用次数（边车文件，缺失/损坏时回退为 0，不阻塞主流程）
        "usage_total": int(usage_payload.get("total") or 0),
        "usage_by_color_mode": dict(usage_payload.get("by_color_mode") or {}),
        "usage_last_used_at": usage_payload.get("last_used_at"),
        "usage_last_used_color_mode": usage_payload.get("last_used_color_mode"),
    }


def _normalize_material_directory_names(directory_names: list[str]) -> list[str]:
    normalized_names: list[str] = []
    seen: set[str] = set()
    for raw_name in directory_names:
        if not isinstance(raw_name, str):
            raise ValueError("directory_names must contain only strings")
        normalized = _normalize_relative_directory_name(raw_name)
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_names.append(normalized)
    if not normalized_names:
        raise ValueError("directory_names must contain at least one saved material directory")
    return normalized_names


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_local_only_material_file(relative_path: Path) -> bool:
    if relative_path.name in _MATERIAL_LOCAL_ONLY_FILENAMES:
        return True
    return any(part in _MATERIAL_LOCAL_ONLY_DIRNAMES for part in relative_path.parts)


def _material_bundle_file_role(relative_path: Path, stage_a_relative_path: Path) -> str:
    if relative_path.as_posix() == "material.json":
        return "material_archive"
    if relative_path.as_posix() == stage_a_relative_path.as_posix():
        return "stage_a_parameters"
    return "sidecar"


def _material_content_hash_from_file_records(
    file_records: list[dict[str, Any]],
) -> str:
    required_records = [
        record
        for record in file_records
        if str(record.get("role") or "") in {"material_archive", "stage_a_parameters"}
    ]
    logical_lines = []
    for record in sorted(required_records, key=lambda item: str(item.get("role") or "")):
        role = str(record.get("role") or "")
        logical_path = (
            "material.json"
            if role == "material_archive"
            else Path(str(record.get("path") or "")).name
        )
        logical_lines.append(f"{logical_path}:{record['sha256']}")
    return f"sha256:{_sha256_bytes(chr(10).join(logical_lines).encode('utf-8'))}"


def _material_package_identity(
    *,
    relative_directory_name: str,
    material_name: str,
    content_hash: str,
    existing_material_id: Any = None,
) -> tuple[str, str]:
    existing_id = str(existing_material_id or "").strip()
    if existing_id:
        material_id = existing_id
    else:
        material_seed = f"{relative_directory_name}\n{material_name}"
        material_id = f"mat_{_sha256_bytes(material_seed.encode('utf-8'))[:26]}"
    revision_id = f"rev_{content_hash.removeprefix('sha256:')[:26]}"
    return material_id, revision_id


def _display_payload_from_material_archive(
    archive_payload: dict[str, Any],
    relative_directory_name: str,
) -> dict[str, str]:
    path_parts = Path(relative_directory_name).parts
    fallback_brand = path_parts[0] if len(path_parts) > 1 else ""
    fallback_name = path_parts[-1] if path_parts else relative_directory_name
    display: dict[str, Any] = {
        "brand": str(archive_payload.get("brand") or fallback_brand),
        "material_name": str(archive_payload.get("material_name") or fallback_name),
    }
    for source_key, target_key in (
        ("material_type", "material_type"),
        ("color_name", "color_name"),
    ):
        value = archive_payload.get(source_key)
        if isinstance(value, str) and value.strip():
            display[target_key] = value.strip()
    material_summary = archive_payload.get("material_summary")
    if isinstance(material_summary, dict):
        estimated_rgb = _safe_rgb_triplet(material_summary.get("estimated_rgb"))
        if len(estimated_rgb) == 3 and all(0 <= channel <= 255 for channel in estimated_rgb):
            display["estimated_rgb"] = estimated_rgb
    return display


def _build_material_bundle_package_manifest(
    *,
    target_root: Path,
    material_dir: Path,
) -> tuple[dict[str, Any], list[tuple[Path, str]]]:
    relative_directory_name = _relative_directory_name(target_root, material_dir)
    material_archive_path = material_dir / "material.json"
    archive_payload = _load_json_object(
        material_archive_path,
        "Saved material archive is not valid UTF-8 JSON",
    )
    stage_a_params_path = _resolve_stage_a_params_path(material_dir, archive_payload)
    stage_a_relative_path = stage_a_params_path.relative_to(material_dir)
    file_records: list[dict[str, Any]] = []
    files_to_write: list[tuple[Path, str]] = []
    material_files = sorted(path for path in material_dir.rglob("*") if path.is_file())
    for file_path in material_files:
        material_relative_path = file_path.relative_to(material_dir)
        if _is_local_only_material_file(material_relative_path):
            continue
        zip_path = (
            Path("materials")
            .joinpath(relative_directory_name)
            .joinpath(material_relative_path)
            .as_posix()
        )
        role = _material_bundle_file_role(material_relative_path, stage_a_relative_path)
        file_records.append(
            {
                "path": zip_path,
                "role": role,
                "sha256": _sha256_file(file_path),
                "bytes": int(file_path.stat().st_size),
                "required": role in {"material_archive", "stage_a_parameters"},
            }
        )
        files_to_write.append((file_path, zip_path))

    roles = {str(record.get("role") or "") for record in file_records}
    if "material_archive" not in roles or "stage_a_parameters" not in roles:
        raise FileNotFoundError(
            f"Saved material archive is missing required files: {relative_directory_name}"
        )
    content_hash = _material_content_hash_from_file_records(file_records)
    display = _display_payload_from_material_archive(
        archive_payload,
        relative_directory_name,
    )
    material_id, revision_id = _material_package_identity(
        relative_directory_name=relative_directory_name,
        material_name=display["material_name"],
        content_hash=content_hash,
        existing_material_id=archive_payload.get("material_id"),
    )
    return (
        {
            "material_id": material_id,
            "revision_id": revision_id,
            "content_hash": content_hash,
            "channel": "manual",
            "visibility": "private",
            "local_directory": relative_directory_name,
            "display": display,
            "files": file_records,
            "compatibility": {
                "min_app_version": "0.0.0",
                "material_schema_version": str(
                    archive_payload.get("schema_version")
                    or archive_payload.get("material_schema_version")
                    or "1"
                ),
            },
        },
        files_to_write,
    )


def _safe_extract_material_zip(zip_path: str, dest_dir: Path) -> Path:
    resolved_dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            for member in archive.infolist():
                member_name = Path(member.filename)
                if member_name.is_absolute() or ".." in member_name.parts:
                    raise ValueError(f"Unsafe zip entry: {member.filename}")
                member_path = (resolved_dest_dir / member_name).resolve()
                try:
                    member_path.relative_to(resolved_dest_dir)
                except ValueError as exc:
                    raise ValueError(f"Unsafe zip entry: {member.filename}") from exc
            archive.extractall(resolved_dest_dir)
    except zipfile.BadZipFile as exc:
        raise ValueError("Malformed ZIP archive") from exc

    children = [p for p in resolved_dest_dir.iterdir() if p.is_dir()]
    if len(children) == 1 and not any(p.is_dir() for p in resolved_dest_dir.iterdir() if p != children[0]):
        return children[0]
    return resolved_dest_dir


def _load_material_export_manifest(extracted_root: Path) -> dict[str, Any] | None:
    manifest_path = extracted_root / _MATERIAL_EXPORT_MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    manifest = _load_json_object(
        manifest_path,
        "Material export manifest is not valid UTF-8 JSON",
    )
    if str(manifest.get("kind") or "") != "lumina_material_export":
        raise ValueError("Material export manifest is invalid")
    return manifest


def _load_material_bundle_manifest(extracted_root: Path) -> dict[str, Any] | None:
    manifest_path = extracted_root / _MATERIAL_BUNDLE_MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None
    manifest = _load_json_object(
        manifest_path,
        "Material bundle manifest is not valid UTF-8 JSON",
    )
    if str(manifest.get("kind") or "") != "lumina_material_bundle":
        raise ValueError("Material bundle manifest is invalid")
    if str(manifest.get("schema_version") or "") != _MATERIAL_PACKAGE_SCHEMA_VERSION:
        raise ValueError("Material bundle manifest schema_version is unsupported")
    packages = manifest.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("Material bundle manifest is missing packages")
    return manifest


def _safe_manifest_relative_path(raw_path: Any) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Material bundle file path must be a non-empty string")
    normalized = raw_path.strip().replace("\\", "/")
    windows_relative = PureWindowsPath(raw_path.strip())
    if (
        windows_relative.is_absolute()
        or windows_relative.drive
        or windows_relative.anchor
        or normalized.startswith("/")
    ):
        raise ValueError(f"Unsafe material bundle file path: {raw_path}")
    parts = [segment for segment in normalized.split("/") if segment]
    if not parts or any(segment in {".", ".."} for segment in parts):
        raise ValueError(f"Unsafe material bundle file path: {raw_path}")
    relative = Path(*parts)
    if (
        relative.is_absolute()
        or relative.drive
        or relative.anchor
        or ".." in relative.parts
    ):
        raise ValueError(f"Unsafe material bundle file path: {raw_path}")
    return relative


def _verify_material_bundle_package(
    *,
    extracted_root: Path,
    package: dict[str, Any],
) -> None:
    material_id = str(package.get("material_id") or "")
    revision_id = str(package.get("revision_id") or "")
    if not material_id or not revision_id:
        raise ValueError("Material bundle package is missing material_id or revision_id")
    files = package.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError(f"Material bundle package {material_id} is missing files")

    normalized_local_directory = _normalize_relative_directory_name(
        str(package.get("local_directory") or "")
    )
    material_dir_relative = Path("materials").joinpath(
        *normalized_local_directory.split("/")
    )
    expected_material_archive_path = material_dir_relative / "material.json"

    required_roles = {"material_archive", "stage_a_parameters"}
    parsed_records: list[tuple[dict[str, Any], Path, str]] = []
    required_role_paths: dict[str, Path] = {}
    for record in files:
        if not isinstance(record, dict):
            raise ValueError(f"Material bundle package {material_id} has invalid file record")
        relative_path = _safe_manifest_relative_path(record.get("path"))
        role = str(record.get("role") or "")
        if role in required_roles:
            if role in required_role_paths:
                raise ValueError(
                    f"Material bundle package {material_id} has duplicate required role: {role}"
                )
            required_role_paths[role] = relative_path
        parsed_records.append((record, relative_path, role))

    if required_roles - set(required_role_paths):
        raise ValueError(f"Material bundle package {material_id} is missing required roles")

    material_archive_role_path = required_role_paths["material_archive"]
    if material_archive_role_path.as_posix() != expected_material_archive_path.as_posix():
        raise ValueError(
            "Material bundle package "
            f"{material_id} material_archive role must point to "
            f"{expected_material_archive_path.as_posix()}"
        )

    material_archive_file_path = extracted_root / expected_material_archive_path
    if not material_archive_file_path.is_file():
        raise FileNotFoundError(
            "Material bundle file is missing: "
            f"{expected_material_archive_path.as_posix()}"
        )
    archive_payload = _load_json_object(
        material_archive_file_path,
        "Material bundle material archive is not valid UTF-8 JSON",
    )
    expected_stage_a_path = material_dir_relative / (
        _resolve_stage_a_params_path(
            material_archive_file_path.parent,
            archive_payload,
        ).relative_to(material_archive_file_path.parent)
    )
    stage_a_role_path = required_role_paths["stage_a_parameters"]
    if stage_a_role_path.as_posix() != expected_stage_a_path.as_posix():
        raise ValueError(
            "Material bundle package "
            f"{material_id} stage_a_parameters role must point to "
            f"{expected_stage_a_path.as_posix()}"
        )

    normalized_records: list[dict[str, Any]] = []
    for record, relative_path, role in parsed_records:
        file_path = extracted_root / relative_path
        if not file_path.is_file():
            raise FileNotFoundError(f"Material bundle file is missing: {relative_path.as_posix()}")
        expected_size = record.get("bytes")
        if expected_size is not None and int(expected_size) != int(file_path.stat().st_size):
            raise ValueError(f"Material bundle file size mismatch: {relative_path.as_posix()}")
        expected_hash = str(record.get("sha256") or "")
        actual_hash = _sha256_file(file_path)
        if expected_hash != actual_hash:
            raise ValueError(f"Material bundle file hash mismatch: {relative_path.as_posix()}")
        normalized_records.append(
            {
                "path": relative_path.as_posix(),
                "role": role,
                "sha256": actual_hash,
                "bytes": int(file_path.stat().st_size),
                "required": bool(record.get("required")),
            }
        )

    expected_content_hash = str(package.get("content_hash") or "")
    actual_content_hash = _material_content_hash_from_file_records(normalized_records)
    if expected_content_hash != actual_content_hash:
        raise ValueError(f"Material bundle content hash mismatch: {material_id}")


def validate_material_bundle_archive(*, archive_path: str) -> dict[str, Any]:
    """Validate a v2 material bundle ZIP without importing its contents.
    校验 v2 耗材 bundle ZIP，但不导入其中内容。

    Args:
        archive_path: ZIP archive path to validate. (要校验的 ZIP 路径)

    Returns:
        dict[str, Any]: Parsed bundle manifest. (解析后的 bundle manifest)
    """
    extract_root = Path(
        tempfile.mkdtemp(prefix="material_bundle_validate_", dir=TEMP_DIR)
    )
    try:
        extracted_root = _safe_extract_material_zip(archive_path, extract_root)
        manifest_root = extracted_root
        if not (manifest_root / _MATERIAL_BUNDLE_MANIFEST_FILENAME).is_file():
            if (extract_root / _MATERIAL_BUNDLE_MANIFEST_FILENAME).is_file():
                manifest_root = extract_root
        bundle_manifest = _load_material_bundle_manifest(manifest_root)
        if bundle_manifest is None:
            raise ValueError("Material bundle manifest is invalid")
        raw_packages = bundle_manifest["packages"]
        for raw_package in raw_packages:
            if not isinstance(raw_package, dict):
                raise ValueError("Material bundle manifest contains invalid package")
            _verify_material_bundle_package(
                extracted_root=manifest_root,
                package=raw_package,
            )
        return json.loads(json.dumps(bundle_manifest, ensure_ascii=False))
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)


def _empty_material_sync_index() -> dict[str, Any]:
    return {
        "schema_version": _MATERIAL_SYNC_INDEX_SCHEMA_VERSION,
        "last_sync_at": None,
        "registries": {},
        "installed": {},
        "revisions": {},
        "local_overrides": {},
    }


def _load_material_sync_index_with_state(target_root: Path) -> tuple[dict[str, Any], str]:
    index_path = target_root / "_sync" / "index.json"
    if not index_path.is_file():
        return _empty_material_sync_index(), "missing"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return _empty_material_sync_index(), "invalid"
    if not isinstance(index, dict):
        return _empty_material_sync_index(), "invalid"
    index.setdefault("schema_version", _MATERIAL_SYNC_INDEX_SCHEMA_VERSION)
    index.setdefault("registries", {})
    index.setdefault("installed", {})
    index.setdefault("revisions", {})
    index.setdefault("local_overrides", {})
    return index, "ready"


def _load_material_sync_index(target_root: Path) -> dict[str, Any]:
    index, _index_state = _load_material_sync_index_with_state(target_root)
    return index


def _material_sync_signature(entry: dict[str, Any]) -> tuple[str, str] | None:
    local_directory = str(entry.get("local_directory") or "").strip()
    content_hash = str(entry.get("content_hash") or "").strip()
    if not local_directory or not content_hash:
        return None
    try:
        local_directory = _normalize_relative_directory_name(local_directory)
    except ValueError:
        return None
    return local_directory, content_hash


def _local_material_sync_entries(target_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not target_root.exists():
        return entries
    root_resolved = target_root.resolve()
    for material_dir in _discover_saved_material_dirs(target_root):
        try:
            package_manifest, _files_to_write = _build_material_bundle_package_manifest(
                target_root=target_root,
                material_dir=material_dir,
            )
            local_directory = _normalize_relative_directory_name(
                str(package_manifest.get("local_directory") or "")
            )
            resolved_material_dir = (target_root / Path(local_directory)).resolve()
            resolved_material_dir.relative_to(root_resolved)
        except (
            FileNotFoundError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ):
            continue
        display = package_manifest.get("display")
        display_payload = display if isinstance(display, dict) else {}
        revision_id = str(package_manifest.get("revision_id") or "")
        entries.append(
            {
                "material_id": str(package_manifest.get("material_id") or ""),
                "revision_id": revision_id,
                "content_hash": str(package_manifest.get("content_hash") or ""),
                "channel": "local",
                "source": "local",
                "local_directory": local_directory,
                "display_brand": str(display_payload.get("brand") or ""),
                "display_name": str(display_payload.get("material_name") or material_dir.name),
                "installed_at": None,
                "updated_at": None,
                "local_exists": resolved_material_dir.is_dir(),
                "material_file_exists": (resolved_material_dir / "material.json").is_file(),
                "available_revisions": [revision_id] if revision_id else [],
            }
        )
    return entries


def _material_sync_status_cache_key(target_root: Path) -> str:
    try:
        return str(target_root.resolve())
    except OSError:
        return str(target_root.absolute())


def _material_sync_index_marker(target_root: Path) -> tuple[int, int]:
    index_path = target_root / "_sync" / "index.json"
    try:
        stat = index_path.stat()
    except OSError:
        return (0, -1)
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _cached_material_sync_status(
    target_root: Path,
    index_marker: tuple[int, int],
) -> dict[str, Any] | None:
    cache_key = _material_sync_status_cache_key(target_root)
    now = time.monotonic()
    with _MATERIAL_SYNC_STATUS_CACHE_LOCK:
        cached = _MATERIAL_SYNC_STATUS_CACHE.get(cache_key)
        if not cached:
            return None
        if cached.get("index_marker") != index_marker:
            return None
        cached_at = float(cached.get("cached_at") or 0.0)
        if now - cached_at > _MATERIAL_SYNC_STATUS_CACHE_TTL_S:
            return None
        payload = cached.get("payload")
        if not isinstance(payload, dict):
            return None
        return _json_clone(payload)


def _store_material_sync_status_cache(
    target_root: Path,
    index_marker: tuple[int, int],
    payload: dict[str, Any],
) -> None:
    cache_key = _material_sync_status_cache_key(target_root)
    with _MATERIAL_SYNC_STATUS_CACHE_LOCK:
        _MATERIAL_SYNC_STATUS_CACHE[cache_key] = {
            "cached_at": time.monotonic(),
            "index_marker": index_marker,
            "payload": _json_clone(payload),
        }


def _invalidate_material_sync_status_cache(target_root: Path) -> None:
    cache_key = _material_sync_status_cache_key(target_root)
    with _MATERIAL_SYNC_STATUS_CACHE_LOCK:
        _MATERIAL_SYNC_STATUS_CACHE.pop(cache_key, None)


def get_material_sync_status(*, materials_dir: str | None = None) -> dict[str, Any]:
    """Return local material sync-index status for API and future cloud sync.
    返回本地耗材同步索引状态，供 API 与后续云同步流程使用。

    Args:
        materials_dir: Optional materials root override. (可选的耗材根目录覆盖)

    Returns:
        dict[str, Any]: Stable status payload with index health and installed
            package presence flags. (包含索引健康状态和已安装包本地存在标记的稳定载荷)
    """
    target_root = Path(materials_dir or MATERIALS_DIR)
    index_marker = _material_sync_index_marker(target_root)
    cached_status = _cached_material_sync_status(target_root, index_marker)
    if cached_status is not None:
        return cached_status
    index, index_state = _load_material_sync_index_with_state(target_root)
    raw_installed = index.get("installed")
    installed_map = raw_installed if isinstance(raw_installed, dict) else {}
    raw_revisions = index.get("revisions")
    revision_map = raw_revisions if isinstance(raw_revisions, dict) else {}
    installed_entries: list[dict[str, Any]] = []
    seen_signatures: set[tuple[str, str]] = set()
    for raw_material_id, raw_entry in installed_map.items():
        if not isinstance(raw_entry, dict):
            continue
        material_id = str(raw_material_id)
        raw_local_directory = str(raw_entry.get("local_directory") or "").strip()
        local_directory = raw_local_directory
        local_exists = False
        material_file_exists = False
        if raw_local_directory:
            try:
                local_directory = _normalize_relative_directory_name(raw_local_directory)
                root_resolved = target_root.resolve()
                material_dir = (target_root / Path(local_directory)).resolve()
                material_dir.relative_to(root_resolved)
                local_exists = material_dir.is_dir()
                material_file_exists = (material_dir / "material.json").is_file()
            except (OSError, ValueError):
                local_exists = False
                material_file_exists = False
        entry = {
            "material_id": material_id,
            "revision_id": str(raw_entry.get("revision_id") or ""),
            "content_hash": str(raw_entry.get("content_hash") or ""),
            "channel": str(raw_entry.get("channel") or "manual"),
            "source": str(raw_entry.get("source") or "package"),
            "local_directory": local_directory,
            "display_brand": str(raw_entry.get("display_brand") or ""),
            "display_name": str(raw_entry.get("display_name") or ""),
            "installed_at": raw_entry.get("installed_at"),
            "updated_at": raw_entry.get("updated_at"),
            "local_exists": local_exists,
            "material_file_exists": material_file_exists,
            "available_revisions": sorted(
                str(revision_id)
                for revision_id in (
                    revision_map.get(material_id, {})
                    if isinstance(revision_map.get(material_id), dict)
                    else {}
                ).keys()
            ),
        }
        signature = _material_sync_signature(entry)
        if signature is not None:
            seen_signatures.add(signature)
        installed_entries.append(entry)

    for local_entry in _local_material_sync_entries(target_root):
        signature = _material_sync_signature(local_entry)
        if signature is not None and signature in seen_signatures:
            continue
        if signature is not None:
            seen_signatures.add(signature)
        installed_entries.append(local_entry)

    installed_entries.sort(
        key=lambda entry: (
            str(entry["display_brand"]).casefold(),
            str(entry["display_name"]).casefold(),
            str(entry["material_id"]),
        )
    )
    registries = index.get("registries") if isinstance(index.get("registries"), dict) else {}
    local_overrides = (
        index.get("local_overrides")
        if isinstance(index.get("local_overrides"), dict)
        else {}
    )
    status_payload = {
        "schema_version": str(index.get("schema_version") or _MATERIAL_SYNC_INDEX_SCHEMA_VERSION),
        "index_state": index_state,
        "last_sync_at": index.get("last_sync_at"),
        "registries": registries,
        "installed_count": sum(
            1
            for entry in installed_entries
            if bool(entry.get("local_exists")) and bool(entry.get("material_file_exists"))
        ),
        "installed": installed_entries,
        "local_overrides_count": len(local_overrides),
    }
    _store_material_sync_status_cache(target_root, index_marker, status_payload)
    return _json_clone(status_payload)


def _material_sync_metadata_by_directory(target_root: Path) -> dict[str, dict[str, Any]]:
    index = _load_material_sync_index(target_root)
    installed = index.get("installed")
    if not isinstance(installed, dict):
        return {}
    metadata: dict[str, dict[str, Any]] = {}
    for material_id, raw_entry in installed.items():
        if not isinstance(raw_entry, dict):
            continue
        local_directory_raw = str(raw_entry.get("local_directory") or "").strip()
        if not local_directory_raw:
            continue
        try:
            local_directory = _normalize_relative_directory_name(local_directory_raw)
        except ValueError:
            continue
        channel = str(raw_entry.get("channel") or "")
        metadata[local_directory] = {
            "sync_material_id": str(material_id),
            "sync_revision_id": str(raw_entry.get("revision_id") or ""),
            "sync_channel": channel,
            "sync_official": channel == "official",
        }
    return metadata


def invalidate_material_library_cache(materials_dir: str | None = None) -> None:
    """Clear cached saved-material library summaries.
    清理已保存耗材库摘要缓存。
    """
    if materials_dir is None:
        _invalidate_material_library_cache()
        return
    _invalidate_material_library_cache(Path(materials_dir or MATERIALS_DIR))


def _local_material_content_hash(
    material_dir: Path,
    archive_payload: dict[str, Any],
) -> str | None:
    archive_path = material_dir / "material.json"
    try:
        stage_a_path = _resolve_stage_a_params_path(material_dir, archive_payload)
    except ValueError:
        return None
    if not archive_path.is_file() or not stage_a_path.is_file():
        return None
    file_records = [
        {
            "path": archive_path.name,
            "role": "material_archive",
            "sha256": _sha256_file(archive_path),
        },
        {
            "path": stage_a_path.name,
            "role": "stage_a_parameters",
            "sha256": _sha256_file(stage_a_path),
        },
    ]
    return _material_content_hash_from_file_records(file_records)


def _official_material_registry_metadata_by_signature() -> dict[tuple[str, str], dict[str, Any]]:
    try:
        catalog = list_material_registry_catalog(
            channels=["official"],
            limit=None,
            offset=0,
        )
    except Exception:
        return {}
    metadata: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in _material_registry_catalog_entries(catalog):
        if str(entry.get("channel") or "") != "official":
            continue
        signature = _material_sync_signature(entry)
        if signature is None:
            continue
        metadata[signature] = {
            "sync_material_id": str(entry.get("material_id") or ""),
            "sync_revision_id": str(entry.get("revision_id") or ""),
            "sync_channel": "official",
            "sync_official": True,
        }
    return metadata


def _apply_official_registry_metadata(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    official_by_signature = _official_material_registry_metadata_by_signature()
    if not official_by_signature:
        return items
    for item in items:
        if bool(item.get("sync_official")):
            continue
        signature = _material_sync_signature(
            {
                "local_directory": item.get("directory_name"),
                "content_hash": item.get("content_hash"),
            }
        )
        if signature is None:
            continue
        official_metadata = official_by_signature.get(signature)
        if official_metadata:
            item.update(official_metadata)
    return items


def _write_material_sync_index(target_root: Path, index: dict[str, Any]) -> None:
    sync_dir = target_root / "_sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    index_path = sync_dir / "index.json"
    tmp_path = sync_dir / f"index.json.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    tmp_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(index_path)
    _invalidate_material_sync_status_cache(target_root)
    _invalidate_material_library_cache(target_root)


def _record_material_sync_entries(
    *,
    target_root: Path,
    installed_packages: list[tuple[dict[str, Any], Path]],
) -> None:
    if not installed_packages:
        return
    now = _now_iso()
    index = _load_material_sync_index(target_root)
    installed = index.setdefault("installed", {})
    if not isinstance(installed, dict):
        installed = {}
        index["installed"] = installed
    revisions = index.setdefault("revisions", {})
    if not isinstance(revisions, dict):
        revisions = {}
        index["revisions"] = revisions
    for package, destination_dir in installed_packages:
        material_id = str(package["material_id"])
        display = package.get("display") if isinstance(package.get("display"), dict) else {}
        material_revisions = revisions.setdefault(material_id, {})
        if not isinstance(material_revisions, dict):
            material_revisions = {}
            revisions[material_id] = material_revisions
        previous_entry = installed.get(material_id)
        if isinstance(previous_entry, dict):
            previous_revision_id = str(previous_entry.get("revision_id") or "")
            if previous_revision_id:
                material_revisions[previous_revision_id] = dict(previous_entry)
        next_entry = {
            "revision_id": str(package["revision_id"]),
            "content_hash": str(package["content_hash"]),
            "channel": str(package.get("channel") or "manual"),
            "source": "package",
            "local_directory": _relative_directory_name(target_root, destination_dir),
            "display_brand": str(display.get("brand") or ""),
            "display_name": str(display.get("material_name") or destination_dir.name),
            "installed_at": now,
            "updated_at": now,
        }
        material_revisions[str(next_entry["revision_id"])] = dict(next_entry)
        installed[material_id] = next_entry
    index["last_sync_at"] = now
    _write_material_sync_index(target_root, index)


def _record_material_registry_refresh(
    *,
    target_root: Path,
    registry_url: str,
    channels: list[str],
    cursor: Any,
    checked_count: int,
    installed_count: int,
    skipped_count: int,
    failed_count: int,
) -> None:
    now = _now_iso()
    index = _load_material_sync_index(target_root)
    registries = index.setdefault("registries", {})
    if not isinstance(registries, dict):
        registries = {}
        index["registries"] = registries
    registries[registry_url] = {
        "url": registry_url,
        "channels": list(channels),
        "last_refresh_at": now,
        "last_cursor": str(cursor) if cursor is not None else None,
        "checked_count": checked_count,
        "installed_count": installed_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
    }
    index["last_sync_at"] = now
    _write_material_sync_index(target_root, index)


def _installed_material_bundle_revision_path(
    *,
    target_root: Path,
    package: dict[str, Any],
    include_revision_history: bool = False,
) -> Path | None:
    material_id = str(package.get("material_id") or "")
    if not material_id:
        return None
    index = _load_material_sync_index(target_root)
    installed = index.get("installed")
    if not isinstance(installed, dict):
        return None
    entry = installed.get(material_id)
    if isinstance(entry, dict):
        material_dir = _material_sync_revision_entry_path(
            target_root=target_root,
            entry=entry,
            package=package,
        )
        if material_dir is not None:
            return material_dir
    if include_revision_history:
        revisions = index.get("revisions")
        material_revisions = (
            revisions.get(material_id)
            if isinstance(revisions, dict)
            else None
        )
        revision_entry = (
            material_revisions.get(str(package.get("revision_id") or ""))
            if isinstance(material_revisions, dict)
            else None
        )
        if isinstance(revision_entry, dict):
            material_dir = _material_sync_revision_entry_path(
                target_root=target_root,
                entry=revision_entry,
                package=package,
            )
            if material_dir is not None:
                return material_dir
    return None


def _material_sync_revision_entry_path(
    *,
    target_root: Path,
    entry: dict[str, Any],
    package: dict[str, Any],
) -> Path | None:
    if str(entry.get("revision_id") or "") != str(package.get("revision_id") or ""):
        return None
    if str(entry.get("content_hash") or "") != str(package.get("content_hash") or ""):
        return None
    local_directory = entry.get("local_directory")
    if not isinstance(local_directory, str) or not local_directory.strip():
        return None
    material_dir = target_root / _normalize_relative_directory_name(local_directory)
    if (material_dir / "material.json").is_file():
        return material_dir
    return None


class _MaterialSyncRefreshFileLock:
    """Best-effort cross-process lock for one materials root refresh.
    单个 materials 根目录刷新用的跨进程锁。
    """

    def __init__(self, target_root: Path) -> None:
        self._sync_dir = target_root / "_sync"
        self._lock_path = self._sync_dir / _MATERIAL_SYNC_REFRESH_LOCK_FILENAME
        self._fd: int | None = None

    def __enter__(self) -> "_MaterialSyncRefreshFileLock":
        self._sync_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(
                str(self._lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            if self._is_stale_lock():
                try:
                    self._lock_path.unlink()
                except OSError as unlink_exc:
                    raise RuntimeError(
                        "Material sync refresh is already running"
                    ) from unlink_exc
                return self.__enter__()
            raise RuntimeError("Material sync refresh is already running") from exc
        lock_payload = json.dumps(
            {"pid": os.getpid(), "created_at": _now_iso()},
            ensure_ascii=False,
        ).encode("utf-8")
        os.write(self._fd, lock_payload)
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None
        try:
            self._lock_path.unlink()
        except FileNotFoundError:
            pass

    def _is_stale_lock(self) -> bool:
        try:
            raw_stale_seconds = os.environ.get(
                "LUMINA_MATERIAL_SYNC_LOCK_STALE_S",
                str(_MATERIAL_SYNC_LOCK_STALE_SECONDS),
            )
            stale_seconds = max(1.0, float(raw_stale_seconds))
        except ValueError:
            stale_seconds = float(_MATERIAL_SYNC_LOCK_STALE_SECONDS)
        try:
            lock_age = datetime.now(timezone.utc).timestamp() - self._lock_path.stat().st_mtime
        except OSError:
            return False
        return lock_age > stale_seconds


def rollback_material_sync_revision(
    *,
    material_id: str,
    revision_id: str,
    materials_dir: str | None = None,
) -> dict[str, Any]:
    """Make a previously installed material revision current again.
    将历史耗材 revision 重新设为当前版本。

    Args:
        material_id: Stable synced material identity. (稳定耗材身份)
        revision_id: Revision to restore. (要恢复的 revision)
        materials_dir: Optional materials root override. (可选耗材根目录覆盖)

    Returns:
        dict[str, Any]: Current installed sync entry after rollback.
            回滚后的当前同步条目。
    """
    cleaned_material_id = str(material_id or "").strip()
    cleaned_revision_id = str(revision_id or "").strip()
    if not cleaned_material_id or not cleaned_revision_id:
        raise ValueError("material_id and revision_id are required")
    target_root = Path(materials_dir or MATERIALS_DIR)
    index = _load_material_sync_index(target_root)
    installed = index.setdefault("installed", {})
    revisions = index.setdefault("revisions", {})
    if not isinstance(installed, dict) or not isinstance(revisions, dict):
        raise ValueError("Material sync index is invalid")
    material_revisions = revisions.get(cleaned_material_id)
    if not isinstance(material_revisions, dict):
        raise FileNotFoundError(
            f"Material sync revision not found: {cleaned_material_id}/{cleaned_revision_id}"
        )
    target_entry = material_revisions.get(cleaned_revision_id)
    if not isinstance(target_entry, dict):
        raise FileNotFoundError(
            f"Material sync revision not found: {cleaned_material_id}/{cleaned_revision_id}"
        )
    local_directory = _normalize_relative_directory_name(
        str(target_entry.get("local_directory") or "")
    )
    material_dir = target_root / local_directory
    if not (material_dir / "material.json").is_file():
        raise FileNotFoundError(
            f"Material sync rollback target is missing material.json: {local_directory}"
        )

    current_entry = installed.get(cleaned_material_id)
    if isinstance(current_entry, dict):
        current_revision_id = str(current_entry.get("revision_id") or "")
        if current_revision_id:
            material_revisions[current_revision_id] = dict(current_entry)

    next_entry = dict(target_entry)
    next_entry["revision_id"] = cleaned_revision_id
    next_entry["updated_at"] = _now_iso()
    material_revisions[cleaned_revision_id] = dict(next_entry)
    installed[cleaned_material_id] = next_entry
    index["last_sync_at"] = next_entry["updated_at"]
    _write_material_sync_index(target_root, index)
    return {
        "material_id": cleaned_material_id,
        "revision_id": cleaned_revision_id,
        "content_hash": str(next_entry.get("content_hash") or ""),
        "channel": str(next_entry.get("channel") or ""),
        "local_directory": local_directory,
    }


def _copy_material_bundle_package_files(
    *,
    manifest_root: Path,
    staged_material_dir: Path,
    destination_dir: Path,
    package: dict[str, Any],
) -> None:
    destination_dir.mkdir(parents=True, exist_ok=False)
    raw_files = package.get("files")
    if not isinstance(raw_files, list):
        raise ValueError("Material bundle package files must be a list")
    for raw_record in raw_files:
        if not isinstance(raw_record, dict):
            raise ValueError("Material bundle package contains invalid file record")
        source_path = manifest_root / _safe_manifest_relative_path(raw_record.get("path"))
        try:
            material_relative_path = source_path.relative_to(staged_material_dir)
        except ValueError as exc:
            raise ValueError(
                f"Material bundle file is outside material directory: {raw_record.get('path')}"
            ) from exc
        if _is_local_only_material_file(material_relative_path):
            continue
        target_path = destination_dir / material_relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)


def _discover_saved_material_dirs(material_root: Path) -> list[Path]:
    archive_paths = [path for path in material_root.rglob("material.json") if path.is_file()]
    return [path.parent for path in _filter_nested_material_archive_paths(archive_paths)]


def _import_target_material_dir(target_root: Path, directory_name: str) -> Path:
    normalized = _normalize_relative_directory_name(directory_name)
    requested_path = target_root / normalized
    if not requested_path.exists():
        return requested_path
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    candidate = requested_path.parent / f"{requested_path.name}_{suffix}"
    collision_index = 2
    while candidate.exists():
        candidate = requested_path.parent / f"{requested_path.name}_{suffix}_{collision_index}"
        collision_index += 1
    return candidate


def _normalize_material_registry_url(registry_url: str | None) -> str:
    raw_url = str(
        registry_url
        if registry_url is not None
        else os.environ.get("LUMINA_MATERIAL_REGISTRY_URL", "")
    ).strip()
    if not raw_url:
        raise ValueError("Material registry URL is not configured")
    if not raw_url.startswith(("http://", "https://")):
        raise ValueError("Material registry URL must be http:// or https://")
    return raw_url.rstrip("/")


def _normalize_material_registry_channels(channels: Sequence[str] | None) -> list[str]:
    if channels is None:
        raw_channels = os.environ.get("LUMINA_MATERIAL_REGISTRY_CHANNELS", "official")
        candidates = re.split(r"[,;\s]+", raw_channels)
    else:
        candidates = [str(channel) for channel in channels]
    normalized: list[str] = []
    for raw_channel in candidates:
        channel = str(raw_channel).strip()
        if not channel:
            continue
        if not re.fullmatch(r"[a-z0-9_-]+", channel):
            raise ValueError(f"Material registry channel is invalid: {channel}")
        if channel not in normalized:
            normalized.append(channel)
    return normalized or ["official"]


def _sha256_hex_from_catalog(value: Any) -> str:
    raw_value = str(value or "").strip().lower()
    if raw_value.startswith("sha256:"):
        raw_value = raw_value.split(":", 1)[1]
    if not re.fullmatch(r"[0-9a-f]{64}", raw_value):
        raise ValueError("Material registry package_sha256 is invalid")
    return raw_value


def _material_registry_catalog_entries(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("Material registry catalog response must be a JSON object")
    entries = payload.get("materials")
    if entries is None:
        entries = payload.get("packages")
    if not isinstance(entries, list):
        raise ValueError("Material registry catalog response is missing materials")
    normalized_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Material registry catalog contains invalid entry")
        normalized_entries.append(entry)
    return normalized_entries


def _material_registry_catalog_url(registry_url: str) -> str:
    return f"{registry_url}/materials/catalog"


def _material_registry_url_origin_key(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    if port is None and scheme == "https":
        port = 443
    elif port is None and scheme == "http":
        port = 80
    return scheme, hostname, port


def _material_registry_package_url(registry_url: str, raw_package_url: Any) -> str:
    package_url = str(raw_package_url or "").strip()
    if not package_url:
        raise ValueError("Material registry catalog entry is missing package_url")
    resolved_url = urljoin(f"{registry_url}/", package_url)
    if not resolved_url.startswith(("http://", "https://")):
        raise ValueError("Material registry package_url must be http:// or https://")
    if _material_registry_url_origin_key(resolved_url) != _material_registry_url_origin_key(
        registry_url
    ):
        raise ValueError("Material registry package_url must use the same origin")
    return resolved_url


def _write_temp_material_registry_package(package_bytes: bytes) -> Path:
    temp_root = Path(TEMP_DIR)
    temp_root.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix="material_registry_package_",
        suffix=".zip",
        dir=temp_root,
    )
    with os.fdopen(fd, "wb") as handle:
        handle.write(package_bytes)
    return Path(temp_name)


def _material_registry_remote_catalog_cache_key(
    *,
    registry_url: str,
    channels: Sequence[str],
    token: str,
    transport: Any,
    limit: int | None,
    offset: int,
    query: str,
) -> tuple[str, tuple[str, ...], str, Any, int | None, int, str]:
    token_fingerprint = _sha256_bytes(token.encode("utf-8")) if token else ""
    transport_identity = transport if transport is not None else None
    return (
        registry_url,
        tuple(channels),
        token_fingerprint,
        transport_identity,
        limit,
        offset,
        query,
    )


def _normalize_material_registry_catalog_pagination(
    *,
    limit: int | None = None,
    offset: int | None = 0,
) -> tuple[int | None, int]:
    normalized_offset = 0 if offset is None else int(offset)
    if normalized_offset < 0:
        raise ValueError("Material registry catalog offset must be non-negative")
    if limit is None:
        return None, normalized_offset
    normalized_limit = int(limit)
    if normalized_limit <= 0:
        raise ValueError("Material registry catalog limit must be positive")
    return normalized_limit, normalized_offset


def _page_material_registry_catalog_entries(
    entries: list[dict[str, Any]],
    *,
    limit: int | None,
    offset: int,
) -> list[dict[str, Any]]:
    if limit is None:
        return entries[offset:]
    return entries[offset : offset + limit]


def _page_material_registry_catalog(
    catalog: dict[str, Any],
    *,
    limit: int | None,
    offset: int,
) -> dict[str, Any]:
    raw_entries = catalog.get("materials")
    entries = raw_entries if isinstance(raw_entries, list) else []
    paged_entries = _page_material_registry_catalog_entries(
        entries,
        limit=limit,
        offset=offset,
    )
    payload = dict(catalog)
    payload["count"] = len(paged_entries)
    payload["total_count"] = int(catalog.get("total_count") or len(entries))
    payload["offset"] = offset
    payload["limit"] = limit
    payload["materials"] = paged_entries
    return _json_clone(payload)


def _normalize_material_registry_catalog_query(query: str | None = None) -> str:
    return " ".join(str(query or "").casefold().split())


def _material_registry_catalog_entry_matches_query(
    entry: dict[str, Any],
    query: str,
) -> bool:
    if not query:
        return True
    searchable_values: list[str] = [
        str(entry.get("material_id") or ""),
        str(entry.get("revision_id") or ""),
        str(entry.get("content_hash") or ""),
        str(entry.get("channel") or ""),
        str(entry.get("visibility") or ""),
        str(entry.get("local_directory") or ""),
    ]
    for key in ("display", "compatibility"):
        value = entry.get(key)
        if isinstance(value, dict):
            searchable_values.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
    haystack = " ".join(searchable_values).casefold()
    return all(token in haystack for token in query.split())


def _filter_material_registry_catalog(
    catalog: dict[str, Any],
    *,
    query: str,
) -> dict[str, Any]:
    if not query:
        return _json_clone(catalog)
    raw_entries = catalog.get("materials")
    entries = raw_entries if isinstance(raw_entries, list) else []
    filtered_entries = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and _material_registry_catalog_entry_matches_query(entry, query)
    ]
    payload = dict(catalog)
    payload["materials"] = filtered_entries
    payload["count"] = len(filtered_entries)
    payload["total_count"] = len(filtered_entries)
    payload["offset"] = 0
    payload["limit"] = None
    return _json_clone(payload)


def _cached_material_registry_remote_catalog(
    *,
    registry_url: str,
    channels: Sequence[str],
    token: str,
    transport: Any,
    limit: int | None,
    offset: int,
    query: str,
) -> dict[str, Any] | None:
    cache_key = _material_registry_remote_catalog_cache_key(
        registry_url=registry_url,
        channels=channels,
        token=token,
        transport=transport,
        limit=limit,
        offset=offset,
        query=query,
    )
    now = time.monotonic()
    with _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE_LOCK:
        cached = _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE.get(cache_key)
        if not cached:
            return None
        cached_at = float(cached.get("cached_at") or 0.0)
        if now - cached_at > _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE_TTL_S:
            _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE.pop(cache_key, None)
            return None
        payload = cached.get("payload")
        if not isinstance(payload, dict):
            return None
        return _json_clone(payload)


def _store_material_registry_remote_catalog_cache(
    *,
    registry_url: str,
    channels: Sequence[str],
    token: str,
    transport: Any,
    limit: int | None,
    offset: int,
    query: str,
    payload: dict[str, Any],
) -> None:
    cache_key = _material_registry_remote_catalog_cache_key(
        registry_url=registry_url,
        channels=channels,
        token=token,
        transport=transport,
        limit=limit,
        offset=offset,
        query=query,
    )
    with _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE_LOCK:
        _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE[cache_key] = {
            "cached_at": time.monotonic(),
            "payload": _json_clone(payload),
        }


def invalidate_material_registry_remote_catalog_cache(
    *,
    registry_url: str | None = None,
) -> None:
    """Clear cached remote material Registry catalog payloads.
    清理远端耗材 Registry catalog 缓存。
    """
    normalized_registry_url = (
        _normalize_material_registry_url(registry_url)
        if registry_url is not None
        else None
    )
    with _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE_LOCK:
        if normalized_registry_url is None:
            _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE.clear()
            return
        stale_keys = [
            cache_key
            for cache_key in _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE
            if cache_key[0] == normalized_registry_url
        ]
        for cache_key in stale_keys:
            _MATERIAL_REGISTRY_REMOTE_CATALOG_CACHE.pop(cache_key, None)


def list_material_registry_catalog(
    *,
    registry_url: str | None = None,
    channels: Sequence[str] | None = None,
    query: str | None = None,
    token: str | None = None,
    timeout_s: float | None = None,
    transport: Any = None,
    use_cache: bool = True,
    limit: int | None = None,
    offset: int | None = 0,
) -> dict[str, Any]:
    """Fetch the remote material Registry catalog without installing packages.
    只读取远程耗材 Registry catalog，不安装任何耗材包。
    """
    import httpx

    normalized_registry_url = _normalize_material_registry_url(registry_url)
    normalized_channels = _normalize_material_registry_channels(channels)
    normalized_limit, normalized_offset = _normalize_material_registry_catalog_pagination(
        limit=limit,
        offset=offset,
    )
    normalized_query = _normalize_material_registry_catalog_query(query)
    auth_token = str(
        token
        if token is not None
        else os.environ.get("LUMINA_MATERIAL_REGISTRY_TOKEN", "")
    ).strip()
    if use_cache:
        cached_catalog = _cached_material_registry_remote_catalog(
            registry_url=normalized_registry_url,
            channels=normalized_channels,
            token=auth_token,
            transport=transport,
            limit=normalized_limit,
            offset=normalized_offset,
            query=normalized_query,
        )
        if cached_catalog is not None:
            return cached_catalog
        if normalized_limit is not None or normalized_offset:
            cached_full_catalog = _cached_material_registry_remote_catalog(
                registry_url=normalized_registry_url,
                channels=normalized_channels,
                token=auth_token,
                transport=transport,
                limit=None,
                offset=0,
                query=normalized_query,
            )
            if cached_full_catalog is not None:
                return _page_material_registry_catalog(
                    cached_full_catalog,
                    limit=normalized_limit,
                    offset=normalized_offset,
                )
        if normalized_query:
            cached_unfiltered_catalog = _cached_material_registry_remote_catalog(
                registry_url=normalized_registry_url,
                channels=normalized_channels,
                token=auth_token,
                transport=transport,
                limit=None,
                offset=0,
                query="",
            )
            if cached_unfiltered_catalog is not None:
                filtered_catalog = _filter_material_registry_catalog(
                    cached_unfiltered_catalog,
                    query=normalized_query,
                )
                _store_material_registry_remote_catalog_cache(
                    registry_url=normalized_registry_url,
                    channels=normalized_channels,
                    token=auth_token,
                    transport=transport,
                    limit=None,
                    offset=0,
                    query=normalized_query,
                    payload=filtered_catalog,
                )
                return _page_material_registry_catalog(
                    filtered_catalog,
                    limit=normalized_limit,
                    offset=normalized_offset,
                )

    if timeout_s is None:
        raw_timeout = os.environ.get("LUMINA_MATERIAL_REGISTRY_TIMEOUT_S", "30")
        try:
            timeout_s = float(raw_timeout)
        except ValueError:
            timeout_s = 30.0

    headers = {"User-Agent": "LuminaStudioMaterialSync/1"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    client_kwargs: dict[str, Any] = {
        "timeout": float(timeout_s),
        "follow_redirects": True,
    }
    if transport is not None:
        client_kwargs["transport"] = transport

    catalog_params: list[tuple[str, str | int]] = [
        ("channel", channel) for channel in normalized_channels
    ]
    if normalized_query:
        catalog_params.append(("q", normalized_query))
    if normalized_limit is not None or normalized_offset:
        catalog_params.append(("offset", normalized_offset))
    if normalized_limit is not None:
        catalog_params.append(("limit", normalized_limit))

    with httpx.Client(**client_kwargs) as client:
        try:
            catalog_response = client.get(
                _material_registry_catalog_url(normalized_registry_url),
                params=catalog_params,
                headers=headers,
            )
            catalog_response.raise_for_status()
            catalog_payload = catalog_response.json()
            catalog_entries = _material_registry_catalog_entries(catalog_payload)
        except httpx.HTTPError as exc:
            raise RuntimeError("Material registry catalog request failed") from exc
        except ValueError as exc:
            raise ValueError("Material registry catalog response is invalid") from exc

    remote_has_pagination = (
        isinstance(catalog_payload, dict)
        and (
            "total_count" in catalog_payload
            or "offset" in catalog_payload
            or "limit" in catalog_payload
        )
    )
    if remote_has_pagination:
        paged_entries = catalog_entries
        total_count = int(catalog_payload.get("total_count") or len(catalog_entries))
        response_offset = int(catalog_payload.get("offset") or normalized_offset)
        response_limit = (
            None
            if catalog_payload.get("limit") is None
            else int(catalog_payload.get("limit"))
        )
        catalog = {
            "schema_version": str(
                catalog_payload.get("schema_version")
                if isinstance(catalog_payload, dict)
                else "1.0"
            )
            or "1.0",
            "channels": normalized_channels,
            "count": len(paged_entries),
            "total_count": total_count,
            "offset": response_offset,
            "limit": response_limit,
            "materials": paged_entries,
        }
        if use_cache:
            _store_material_registry_remote_catalog_cache(
                registry_url=normalized_registry_url,
                channels=normalized_channels,
                token=auth_token,
                transport=transport,
                limit=normalized_limit,
                offset=normalized_offset,
                query=normalized_query,
                payload=catalog,
            )
        return _json_clone(catalog)

    full_catalog = {
        "schema_version": str(
            catalog_payload.get("schema_version")
            if isinstance(catalog_payload, dict)
            else "1.0"
        )
        or "1.0",
        "channels": normalized_channels,
        "count": len(catalog_entries),
        "total_count": len(catalog_entries),
        "offset": 0,
        "limit": None,
        "materials": catalog_entries,
    }
    filtered_full_catalog = _filter_material_registry_catalog(
        full_catalog,
        query=normalized_query,
    )
    if use_cache:
        _store_material_registry_remote_catalog_cache(
            registry_url=normalized_registry_url,
            channels=normalized_channels,
            token=auth_token,
            transport=transport,
            limit=None,
            offset=0,
            query=normalized_query,
            payload=filtered_full_catalog,
        )
    return _page_material_registry_catalog(
        filtered_full_catalog,
        limit=normalized_limit,
        offset=normalized_offset,
    )


def install_material_registry_package(
    *,
    package_url: str,
    package_sha256: str,
    material_id: str,
    revision_id: str,
    registry_url: str | None = None,
    token: str | None = None,
    materials_dir: str | None = None,
    timeout_s: float | None = None,
    transport: Any = None,
) -> dict[str, Any]:
    """Install one selected Registry package into the local material library.
    将用户选择的单个 Registry 耗材包安装到本地耗材库。
    """
    import httpx

    normalized_registry_url = _normalize_material_registry_url(registry_url)
    material_id = str(material_id or "").strip()
    revision_id = str(revision_id or "").strip()
    if not material_id or not revision_id:
        raise ValueError("Material registry package identity is required")
    resolved_package_url = _material_registry_package_url(
        normalized_registry_url,
        package_url,
    )
    expected_package_sha256 = _sha256_hex_from_catalog(package_sha256)
    auth_token = str(
        token
        if token is not None
        else os.environ.get("LUMINA_MATERIAL_REGISTRY_TOKEN", "")
    ).strip()
    if timeout_s is None:
        raw_timeout = os.environ.get("LUMINA_MATERIAL_REGISTRY_TIMEOUT_S", "30")
        try:
            timeout_s = float(raw_timeout)
        except ValueError:
            timeout_s = 30.0
    target_root = Path(materials_dir or MATERIALS_DIR)
    target_root.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": "LuminaStudioMaterialSync/1"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    client_kwargs: dict[str, Any] = {
        "timeout": float(timeout_s),
        "follow_redirects": True,
    }
    if transport is not None:
        client_kwargs["transport"] = transport

    with _MaterialSyncRefreshFileLock(target_root):
        with httpx.Client(**client_kwargs) as client:
            try:
                package_response = client.get(resolved_package_url, headers=headers)
                package_response.raise_for_status()
            except httpx.HTTPError as exc:
                raise RuntimeError("Material registry package request failed") from exc
            package_bytes = package_response.content
        actual_package_sha256 = _sha256_bytes(package_bytes)
        if actual_package_sha256 != expected_package_sha256:
            raise ValueError(
                "Material registry package_sha256 mismatch: "
                f"{material_id}/{revision_id}"
            )
        temp_package_path = _write_temp_material_registry_package(package_bytes)
        try:
            import_result = import_saved_stage_a_material_archives(
                archive_path=str(temp_package_path),
                materials_dir=str(target_root),
                selected_material_id=material_id,
                selected_revision_id=revision_id,
            )
        finally:
            try:
                temp_package_path.unlink()
            except OSError:
                pass

    return {
        "registry_url": normalized_registry_url,
        "material_id": material_id,
        "revision_id": revision_id,
        "installed_count": len(import_result.imported_materials),
        "installed_materials": import_result.imported_materials,
    }



def _extract_stage_a_vectors(
    params_payload: dict[str, Any],
) -> tuple[list[float], list[float], list[float], list[float]]:
    parameters = params_payload.get("parameters") or {}
    channels = parameters.get("channels") or []
    substrates = parameters.get("substrates") or []
    if not channels or not isinstance(channels[0], dict):
        raise ValueError("Stage A parameter payload is missing channel parameters")
    channel = channels[0]
    white_substrate = next(
        (
            substrate
            for substrate in substrates
            if isinstance(substrate, dict) and substrate.get("substrate_id") == "white"
        ),
        None,
    )
    black_substrate = next(
        (
            substrate
            for substrate in substrates
            if isinstance(substrate, dict) and substrate.get("substrate_id") == "black"
        ),
        None,
    )
    if not isinstance(white_substrate, dict) or not isinstance(black_substrate, dict):
        raise ValueError("Stage A parameter payload is missing white/black substrate parameters")

    try:
        e_values = [float(value) for value in list(channel.get("E") or [])]
        k_values = [float(value) for value in list(channel.get("k") or [])]
        white_c0_values = [float(value) for value in list(white_substrate.get("C0") or [])]
        black_c0_values = [float(value) for value in list(black_substrate.get("C0") or [])]
    except (TypeError, ValueError) as exc:
        raise ValueError("Stage A parameter payload contains non-numeric channel vectors") from exc

    vector_lengths = {len(e_values), len(k_values), len(white_c0_values), len(black_c0_values)}
    if vector_lengths != {3}:
        raise ValueError("Stage A parameter payload must contain 3-channel E/k/C0 vectors")
    return e_values, k_values, white_c0_values, black_c0_values


def _update_stage_a_payload_material_name(
    stage_a_payload: dict[str, Any],
    material_name: str,
) -> dict[str, Any]:
    updated_payload = _json_clone(stage_a_payload)
    parameters = updated_payload.get("parameters")
    if isinstance(parameters, dict):
        channels = parameters.get("channels")
        if isinstance(channels, list) and channels and isinstance(channels[0], dict):
            channels[0]["color_name"] = material_name
    meta = updated_payload.get("meta")
    if isinstance(meta, dict) and "material_name" in meta:
        meta["material_name"] = material_name
    return updated_payload


def _build_verification_run(
    *,
    params_payload: dict[str, Any],
    fit_summary: dict[str, Any],
    material_summary: dict[str, Any],
    source_summary: dict[str, Any],
    captured_at: str | None = None,
) -> dict[str, Any]:
    e_values, k_values, white_c0_values, black_c0_values = _extract_stage_a_vectors(params_payload)
    samples = _normalize_fit_samples_payload(material_summary.get("fit_samples"))
    run: dict[str, Any] = {
        "captured_at": captured_at or _now_iso(),
        "params": {
            "E": [round(float(value), 6) for value in e_values],
            "k": [round(float(value), 6) for value in k_values],
            "white_C0": [round(float(value), 6) for value in white_c0_values],
            "black_C0": [round(float(value), 6) for value in black_c0_values],
        },
        "fit_summary": _json_clone(fit_summary),
        "material_summary": _json_clone(material_summary),
        "source": _json_clone(source_summary),
    }
    if samples is not None:
        run["samples"] = samples
    return run


def _normalize_fit_samples_payload(value: Any) -> dict[str, Any] | None:
    """Validate and normalize a stored ``fit_samples`` block.
    校验并规范化已存储的 ``fit_samples`` 数据块。

    Returns ``None`` when the block is missing or malformed (so the caller
    falls back to parameter-mean aggregation). Returned dict carries
    plain lists ready to be JSON-serialized; numerical conversion happens
    here so downstream code can rely on shape and dtype.
    缺失或格式异常时返回 ``None``，调用方将回退到参数均值聚合；返回的
    字典统一为 JSON 安全的 list 形态，避免下游再做形状检查。
    """
    if not isinstance(value, dict):
        return None
    thickness_raw = value.get("thickness_mm")
    white_raw = value.get("white_linear")
    black_raw = value.get("black_linear")
    if not isinstance(thickness_raw, list) or not isinstance(white_raw, list) or not isinstance(black_raw, list):
        return None
    try:
        thickness_mm = [float(v) for v in thickness_raw]
    except (TypeError, ValueError):
        return None
    if not thickness_mm:
        return None

    def _normalize_matrix(rows: list[Any], expected_rows: int) -> list[list[float]] | None:
        if len(rows) != expected_rows:
            return None
        normalized: list[list[float]] = []
        for row in rows:
            if not isinstance(row, list) or len(row) != 3:
                return None
            try:
                normalized.append([float(v) for v in row])
            except (TypeError, ValueError):
                return None
        return normalized

    white_linear = _normalize_matrix(white_raw, len(thickness_mm))
    black_linear = _normalize_matrix(black_raw, len(thickness_mm))
    if white_linear is None or black_linear is None:
        return None
    return {
        "schema_version": str(value.get("schema_version") or "1.0"),
        "thickness_mm": thickness_mm,
        "white_linear": white_linear,
        "black_linear": black_linear,
    }



def _load_existing_verification_runs(
    material_dir: Path,
    archive_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    stored_runs = archive_payload.get("verification_runs")
    if isinstance(stored_runs, list) and stored_runs:
        return [_json_clone(run) for run in stored_runs if isinstance(run, dict)]

    stage_a_filename = str(archive_payload.get("stage_a_params_file") or "stage_A_parameters.json")
    stage_a_path = material_dir / stage_a_filename
    if not stage_a_path.exists():
        return []
    try:
        params_payload = json.loads(stage_a_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    try:
        seeded_run = _build_verification_run(
            params_payload=params_payload,
            fit_summary=archive_payload.get("fit_summary") or {},
            material_summary=archive_payload.get("material_summary") or {},
            source_summary=archive_payload.get("source") or {},
            captured_at=str(
                archive_payload.get("updated_at")
                or archive_payload.get("created_at")
                or _now_iso()
            ),
        )
    except ValueError:
        return []
    return [seeded_run]



def _average_numeric_vectors(vectors: list[list[float]], fallback: list[float]) -> list[float]:
    expected_length = len(fallback)
    normalized: list[list[float]] = []
    for vector in vectors:
        try:
            values = [float(value) for value in vector]
        except (TypeError, ValueError):
            continue
        if len(values) != expected_length:
            continue
        normalized.append(values)
    if not normalized:
        return [float(value) for value in fallback]
    return np.mean(np.asarray(normalized, dtype=np.float64), axis=0).tolist()


def _collect_combined_run_samples(
    verification_runs: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Concatenate ``samples`` from every run when *all* runs have them.
    若所有 run 都带样本则将其拼接。

    Returns ``None`` when any run is missing samples or has shape errors,
    forcing the caller to fall back to parameter-mean aggregation. We require
    completeness instead of mixing samples-vs-mean to keep the aggregation
    semantics single-method-per-archive (so ``aggregation_method`` is a
    truthful single value rather than a per-run patchwork).
    任何 run 缺样本或形状不一致时返回 ``None``，强制调用方使用参数均值；
    保持每次聚合采用单一方法，便于追踪 ``aggregation_method``。
    """
    if not verification_runs:
        return None
    thickness_chunks: list[np.ndarray] = []
    white_chunks: list[np.ndarray] = []
    black_chunks: list[np.ndarray] = []
    for run in verification_runs:
        samples = _normalize_fit_samples_payload(run.get("samples"))
        if samples is None:
            return None
        thickness = np.asarray(samples["thickness_mm"], dtype=np.float64)
        white = np.asarray(samples["white_linear"], dtype=np.float64)
        black = np.asarray(samples["black_linear"], dtype=np.float64)
        if thickness.ndim != 1 or thickness.size == 0:
            return None
        if white.shape != (thickness.size, 3) or black.shape != (thickness.size, 3):
            return None
        thickness_chunks.append(thickness)
        white_chunks.append(white)
        black_chunks.append(black)
    return (
        np.concatenate(thickness_chunks, axis=0),
        np.concatenate(white_chunks, axis=0),
        np.concatenate(black_chunks, axis=0),
    )


def _refit_combined_samples(
    thickness_mm: np.ndarray,
    white_linear: np.ndarray,
    black_linear: np.ndarray,
) -> tuple[
    list[float], list[float], list[float], list[float], list[float], dict[str, float]
]:
    """Run a fresh per-channel ``_fit_component`` on combined samples.
    在合并样本上重新执行逐通道 ``_fit_component`` 拟合。

    Statistical rationale: averaging Beer-Lambert ``(E, k)`` is invalid
    because the model is non-linear in ``k``. Concatenating samples and
    refitting is the correct generalization of "more data = tighter fit"
    and is the only way the verification count actually improves accuracy.
    Beer-Lambert 在 ``k`` 上是非线性的，对参数取均值无统计意义；合并样
    本重拟合才是"多次校准 = 更精确"的正确实现。

    Returns:
        ``(E, k, C0_white, C0_black, channel_rmse, overall_validation)``.
    """
    e_values: list[float] = []
    k_values: list[float] = []
    c0_white_values: list[float] = []
    c0_black_values: list[float] = []
    channel_rmse: list[float] = []
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

    e_arr = np.asarray(e_values, dtype=np.float64)
    k_arr = np.asarray(k_values, dtype=np.float64)
    c0w_arr = np.asarray(c0_white_values, dtype=np.float64)
    c0b_arr = np.asarray(c0_black_values, dtype=np.float64)
    decay = np.exp(-np.outer(thickness_mm, k_arr))
    pred_white = e_arr + (c0w_arr - e_arr) * decay
    pred_black = e_arr + (c0b_arr - e_arr) * decay
    observed_linear = np.vstack([white_linear, black_linear])
    predicted_linear = np.vstack([pred_white, pred_black])
    observed_srgb = _linear_to_srgb_uint8(observed_linear)
    predicted_srgb = _linear_to_srgb_uint8(predicted_linear)
    delta_e = np.linalg.norm(
        _rgb_to_lab_float(observed_srgb) - _rgb_to_lab_float(predicted_srgb), axis=1
    )
    overall_validation: dict[str, float] = {
        "mean_delta_e": float(np.mean(delta_e)) if delta_e.size else 0.0,
        "max_delta_e": float(np.max(delta_e)) if delta_e.size else 0.0,
        "rmse_linear": float(np.sqrt(np.mean(np.square(predicted_linear - observed_linear))))
        if observed_linear.size
        else 0.0,
    }
    return e_values, k_values, c0_white_values, c0_black_values, channel_rmse, overall_validation


def _coerce_image_source(value: Any) -> str | None:
    """Normalize a stored ``image_source`` value to a known tag or ``None``.
    将持久化的 ``image_source`` 标签归一化为已知值或 ``None``。

    Returns ``None`` for missing / non-string / unknown values so legacy
    archives written before the tag existed are treated as "unknown" and
    do not block re-verification merges. Known tags are normalized to
    lowercase to make matching case-insensitive.
    历史档案缺失该字段或为非法值时返回 ``None``，不阻塞合并；已知值统一
    转小写以做大小写无关匹配。
    """
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    if candidate not in _VALID_IMAGE_SOURCES:
        return None
    return candidate


def _collect_run_image_sources(
    verification_runs: list[dict[str, Any]],
) -> set[str]:
    """Return the set of known ``image_source`` tags across the given runs.
    提取已知 ``image_source`` 标签集合。

    Runs whose source lacks the tag (legacy archives) contribute nothing
    so the merge consistency check only fires when at least one run
    carries an explicit, recognised tag.
    """
    seen: set[str] = set()
    for run in verification_runs:
        source = run.get("source")
        if not isinstance(source, dict):
            continue
        tag = _coerce_image_source(source.get("image_source"))
        if tag is not None:
            seen.add(tag)
    return seen


def _collect_run_warnings(verification_runs: list[dict[str, Any]]) -> list[str]:
    """Union of all run-level fit warnings, deduplicated and sorted.
    汇总所有 run 的拟合警告并去重排序。
    """
    warning_values: list[str] = []
    for run in verification_runs:
        run_fit_summary = run.get("fit_summary") or {}
        if not isinstance(run_fit_summary, dict):
            continue
        run_warnings = run_fit_summary.get("warnings")
        if isinstance(run_warnings, list):
            warning_values.extend(str(value) for value in run_warnings if str(value).strip())
    return sorted(dict.fromkeys(warning_values))


# --- Multi-run selection: bias filter + cross-validation -----------------
#
# Why this exists: when more than one verification_run lives in an archive,
# blindly concatenating every run's samples lets a single biased capture
# (e.g. white-balanced input pushing C0_white to ~1.0) drag the joint LM
# fit toward physically wrong (E, k). The fit RMSE may even look BETTER
# under bias because the model bends to fit the biased data perfectly,
# which is exactly the trap "low ΔE != accurate" warned about during the
# 品红 calibration debugging session.
#
# The mitigation has two layers:
#
#   1. ``_score_run_bias`` flags KNOWN bias indicators on each run
#      (C0_white avg > 0.95, image_source=restored, flat substrate,
#      unreliable orientation). Scoring is independent of the run's own
#      fit metrics so a "self-consistently biased" run cannot hide.
#
#   2. ``_cross_val_score_runs`` (only when N>=3) measures how well each
#      run's ``(E, k)`` predicts the OTHER runs' samples. A biased run
#      fits itself but generalises poorly, so its cross-val mean ΔE is
#      high. This catches "unknown unknown" biases that 1) misses.
#
# ``_select_runs_for_refit`` composes the two: hard-filter by bias first,
# then optionally rank survivors by cross-val. The fresh run (last in the
# list) is ALWAYS kept regardless of its bias score because the user just
# captured it on purpose; we let the operator inspect the diagnostics
# instead of silently discarding their freshest input.
#
# 多 run 选择：偏置硬过滤 + 跨 run 交叉验证。低 ΔE 不等于准确，配合时既筛
# 掉已知偏置 run，又通过 N>=3 时的 cross-val 抓"未知偏置"。新 run（列表
# 末尾）始终保留，便于审计。
_BIAS_FLAG_C0_WHITE_HIGH = "c0_white_avg_gt_0_95"
_BIAS_FLAG_C0_WHITE_LOW = "c0_white_avg_lt_0_60"
_BIAS_FLAG_IMAGE_SOURCE_RESTORED = "image_source_restored"
_BIAS_FLAG_WHITE_SUBSTRATE_FLAT = "white_substrate_flat"
_BIAS_FLAG_BLACK_SUBSTRATE_FLAT = "black_substrate_flat"
_BIAS_FLAG_ORIENTATION_UNRELIABLE = "orientation_unreliable"
_BIAS_FLAG_MEAN_DE_HIGH = "mean_de_gt_3"
_BIAS_FLAG_C0_SESSION_OUTLIER = "c0_session_outlier"

# Single-run thresholds. Pinned at the module level so tests, frontend
# i18n and any future docs reference one canonical number.
# 单 run 阈值集中在模块级，避免散落在判定逻辑中难以维护。
_C0_WHITE_AVG_HIGH_THRESHOLD = 0.95
_C0_WHITE_AVG_LOW_THRESHOLD = 0.60
_MEAN_DELTA_E_HIGH_THRESHOLD = 3.0

# Cross-run pairwise threshold: two captures whose white_C0 averages
# differ by more than this multiplicative factor cannot share a single
# joint Beer-Lambert fit (the cost surface has no consistent (E, k) for
# both lighting environments). Ratio is computed as max/min so it is
# direction-agnostic.
# 跨 run 白底亮度比阈值；超过即视为光照环境不一致，无法共拟合。
_C0_WHITE_PAIRWISE_RATIO_THRESHOLD = 1.5

# Cross-material session reference thresholds. A run trips the session
# outlier flag when *any* of its three white_C0 channels is more than
# ``_C0_SESSION_OUTLIER_ABS_THRESHOLD`` (linear-RGB units, absolute) OR
# ``_C0_SESSION_OUTLIER_REL_THRESHOLD`` (proportional, vs the session
# median) away from the session median. Either guard is a hit so we
# catch both bright-room shifts (small relative, big absolute on dark
# channels) and dark-room shifts (small absolute, large relative).
# Default window is 24 h: the same operator-session timeframe.
# 跨材料 session 中位数比对阈值；任一通道超过绝对阈值或相对阈值即触发，
# 兼顾亮室漂移（绝对差大）与暗室漂移（相对差大）。默认 24 小时窗口。
_C0_SESSION_OUTLIER_ABS_THRESHOLD = 0.05
_C0_SESSION_OUTLIER_REL_THRESHOLD = 0.05
_C0_SESSION_WINDOW_HOURS = 24.0

# Structural-bias flags: each indicates the *physics* of the capture
# is compromised (white-balanced input, underexposed input, restored
# image, flat substrate, or fit metrics already untrustworthy), so
# dropping a strictly-worse-than-fresh run is justified.
# 结构性偏置标签：捕获本身的物理意义被破坏，可作为硬过滤依据。
_STRUCTURAL_BIAS_FLAGS = frozenset(
    {
        _BIAS_FLAG_C0_WHITE_HIGH,
        _BIAS_FLAG_C0_WHITE_LOW,
        _BIAS_FLAG_IMAGE_SOURCE_RESTORED,
        _BIAS_FLAG_WHITE_SUBSTRATE_FLAT,
        _BIAS_FLAG_BLACK_SUBSTRATE_FLAT,
        _BIAS_FLAG_MEAN_DE_HIGH,
        _BIAS_FLAG_C0_SESSION_OUTLIER,
    }
)
# Advisory flags: surfaced in the UI for awareness but not used for the
# strict-worse comparison. Orientation reliability depends on the
# ``delta_e_gap`` margin between top orientation candidates, which is
# stochastic in noisy captures — flagging a run for orientation alone
# would give false positives on otherwise-fine inputs.
# 提示性标签：仅在 UI 中展示，不参与硬过滤；朝向可靠性会随噪声波动，
# 单凭它丢 run 容易误伤。
_ADVISORY_BIAS_FLAGS = frozenset(
    {
        _BIAS_FLAG_ORIENTATION_UNRELIABLE,
    }
)


def _safe_mean(values: list[float] | None) -> float | None:
    if not values:
        return None
    try:
        arr = np.asarray([float(v) for v in values], dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if arr.size == 0:
        return None
    return float(np.mean(arr))


def _score_run_bias(run: dict[str, Any]) -> dict[str, Any]:
    """Compute bias indicators for a single verification run.
    为单个 verification run 计算偏置指标。

    Each detected indicator pushes the run toward exclusion from the joint
    refit. Indicators are intentionally *physical* / structural, never
    derived from the run's own fit ΔE: a self-consistently biased capture
    produces low ΔE precisely because the model bends to fit its biased
    data, so ΔE-based scores would silently approve those runs.
    每个指标都是物理 / 结构性的，**不**用 run 自身的 ΔE，因为"自我一致地
    偏置"的捕获 ΔE 反而会很低、骗过基于 ΔE 的打分器。

    Args:
        run: A single ``verification_runs[*]`` dict as persisted on disk.
            (磁盘上单条 verification_runs 字典)

    Returns:
        ``{"bias_flag_count": int, "bias_flags": list[str], "white_c0_avg":
        float | None, "image_source": str | None}``. ``bias_flags`` uses
        the stable ``_BIAS_FLAG_*`` codes so frontend i18n can map them
        to localised labels without parsing free text.
    """
    flags: list[str] = []
    params = run.get("params") if isinstance(run.get("params"), dict) else {}
    white_c0 = params.get("white_C0") if isinstance(params, dict) else None
    white_c0_avg = _safe_mean(white_c0 if isinstance(white_c0, list) else None)
    if white_c0_avg is not None and white_c0_avg > _C0_WHITE_AVG_HIGH_THRESHOLD:
        flags.append(_BIAS_FLAG_C0_WHITE_HIGH)
    # Mirror image of the high-white check: severely underexposed
    # captures land white_C0 below the typical PLA white substrate
    # band (0.85-0.92). Below 0.60 the dynamic range squeezes so much
    # that LM has to inflate ``k`` to bend exp through near-step data,
    # producing physically meaningless parameters.
    # 白底过暗（<0.60）会压扁动态范围导致拟合失真。
    if white_c0_avg is not None and white_c0_avg < _C0_WHITE_AVG_LOW_THRESHOLD:
        flags.append(_BIAS_FLAG_C0_WHITE_LOW)

    source = run.get("source") if isinstance(run.get("source"), dict) else {}
    image_source = source.get("image_source") if isinstance(source, dict) else None
    image_source_str = str(image_source) if isinstance(image_source, str) else None
    if image_source_str == "restored":
        flags.append(_BIAS_FLAG_IMAGE_SOURCE_RESTORED)

    fit_summary = run.get("fit_summary") if isinstance(run.get("fit_summary"), dict) else {}
    ranking = (
        fit_summary.get("orientation_ranking")
        if isinstance(fit_summary, dict)
        else None
    )

    if isinstance(ranking, dict):
        white_info = ranking.get("white_orientation_info")
        if isinstance(white_info, dict) and white_info.get("flat") is True:
            flags.append(_BIAS_FLAG_WHITE_SUBSTRATE_FLAT)
        black_info = ranking.get("black_orientation_info")
        if isinstance(black_info, dict) and black_info.get("flat") is True:
            flags.append(_BIAS_FLAG_BLACK_SUBSTRATE_FLAT)
        if ranking.get("orientation_reliable") is False:
            flags.append(_BIAS_FLAG_ORIENTATION_UNRELIABLE)

    # The run's own goodness-of-fit guards "garbage in, garbage out":
    # if a single capture's mean ΔE is already above 3.0 (the
    # printer-profile "borderline acceptable" line), feeding its
    # samples into a joint refit can only drag the merged (E, k)
    # toward this run's distorted fit.
    # 单 run mean_dE>3 表示拟合已不可信，禁止其参与联合重拟。
    overall_validation = (
        fit_summary.get("overall_validation")
        if isinstance(fit_summary, dict)
        else None
    )
    if isinstance(overall_validation, dict):
        mean_de = overall_validation.get("mean_delta_e")
        if (
            isinstance(mean_de, (int, float))
            and not isinstance(mean_de, bool)
            and float(mean_de) > _MEAN_DELTA_E_HIGH_THRESHOLD
        ):
            flags.append(_BIAS_FLAG_MEAN_DE_HIGH)

    structural_flags = [flag for flag in flags if flag in _STRUCTURAL_BIAS_FLAGS]
    return {
        "bias_flag_count": len(flags),
        "bias_flags": flags,
        # ``structural_flag_count`` drives the strict-worse comparison
        # in :func:`_select_runs_for_refit`; advisory flags such as
        # ``orientation_unreliable`` show up in ``bias_flags`` for UI
        # awareness but do NOT make a run "structurally biased".
        # 仅结构性标签参与硬过滤；提示性标签只在 UI 中展示。
        "structural_flag_count": len(structural_flags),
        "structural_flags": structural_flags,
        "white_c0_avg": white_c0_avg,
        "image_source": image_source_str,
    }


def _predict_substrate_linear(
    e_values: np.ndarray,
    k_values: np.ndarray,
    c0_values: np.ndarray,
    thickness_mm: np.ndarray,
) -> np.ndarray:
    """Forward Beer-Lambert: predict linear-RGB observations.
    Beer-Lambert 前向：根据 (E, k, C0) 预测线性 RGB 观测值。

    Vectorised over samples and channels: ``pred[s, c] = E[c] + (C0[c] -
    E[c]) * exp(-k[c] * t[s])``.
    """
    decay = np.exp(-k_values[None, :] * thickness_mm[:, None])
    return e_values[None, :] + (c0_values[None, :] - e_values[None, :]) * decay


def _cross_val_score_runs(
    verification_runs: list[dict[str, Any]],
    candidate_indices: list[int],
) -> dict[int, float]:
    """Score each candidate run by how well it predicts OTHER candidates.
    用每个候选 run 拟合的 (E, k) 预测其他候选 run 的样本，得分越低越好。

    Algorithm: for each candidate ``R`` in ``candidate_indices``, fit
    ``(E, k, C0_white, C0_black)`` per channel using only ``R``'s
    samples, then predict the union of all OTHER candidates' samples
    using ``R``'s parameters and report the linear-space RMSE.

    A biased run fits itself perfectly (low intra-run RMSE) but produces
    parameters that fail to explain other captures, yielding a HIGH
    cross-val RMSE. An unbiased run yields a low one. This generalises
    "low ΔE != accurate" detection beyond the hand-coded bias flags.

    Args:
        verification_runs: Full archive list (only the entries at
            ``candidate_indices`` are touched). (完整 verification_runs)
        candidate_indices: Indices to score. Need at least 2; with 1 the
            score is undefined and this function returns an empty dict.
            (候选索引列表，<2 时返回空 dict)

    Returns:
        Mapping from candidate index to cross-val RMSE in linear RGB
        space. Lower = more accurate / less biased.
        (候选索引 -> 线性 RGB 空间 cross-val RMSE 映射)
    """
    if len(candidate_indices) < 2:
        return {}

    samples_per_index: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for idx in candidate_indices:
        run = verification_runs[idx]
        normalized = _normalize_fit_samples_payload(run.get("samples"))
        if normalized is None:
            continue
        thickness = np.asarray(normalized["thickness_mm"], dtype=np.float64)
        white = np.asarray(normalized["white_linear"], dtype=np.float64)
        black = np.asarray(normalized["black_linear"], dtype=np.float64)
        if thickness.ndim != 1 or thickness.size == 0:
            continue
        if white.shape != (thickness.size, 3) or black.shape != (thickness.size, 3):
            continue
        samples_per_index[idx] = (thickness, white, black)

    if len(samples_per_index) < 2:
        return {}

    scores: dict[int, float] = {}
    for fit_idx, (fit_t, fit_white, fit_black) in samples_per_index.items():
        e_values: list[float] = []
        k_values: list[float] = []
        c0_white_values: list[float] = []
        c0_black_values: list[float] = []
        for channel in range(3):
            e_val, k_val, c0_white, c0_black, _rmse = _fit_component(
                fit_t,
                fit_white[:, channel],
                fit_black[:, channel],
            )
            e_values.append(e_val)
            k_values.append(k_val)
            c0_white_values.append(c0_white)
            c0_black_values.append(c0_black)
        e_arr = np.asarray(e_values, dtype=np.float64)
        k_arr = np.asarray(k_values, dtype=np.float64)
        c0w_arr = np.asarray(c0_white_values, dtype=np.float64)
        c0b_arr = np.asarray(c0_black_values, dtype=np.float64)

        residual_chunks: list[np.ndarray] = []
        for other_idx, (other_t, other_white, other_black) in samples_per_index.items():
            if other_idx == fit_idx:
                continue
            pred_white = _predict_substrate_linear(e_arr, k_arr, c0w_arr, other_t)
            pred_black = _predict_substrate_linear(e_arr, k_arr, c0b_arr, other_t)
            residual_chunks.append((pred_white - other_white).reshape(-1))
            residual_chunks.append((pred_black - other_black).reshape(-1))
        if not residual_chunks:
            continue
        residual = np.concatenate(residual_chunks, axis=0)
        scores[fit_idx] = float(np.sqrt(np.mean(np.square(residual))))

    return scores


# ---------------------------------------------------------------------------
# Cross-material session reference for white_C0 consistency
# 跨材料 session 级白底参考
# ---------------------------------------------------------------------------


def _parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp into a timezone-aware :class:`datetime`.
    将 ISO-8601 时间戳解析为带时区的 datetime。

    Returns ``None`` for any input that cannot be parsed (non-string,
    malformed, etc.) so the caller can simply skip rows whose
    ``captured_at`` is missing rather than abort the whole walk.
    解析失败返回 None，调用方按 row 级跳过即可。
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # ``datetime.fromisoformat`` only learned to accept the ``Z`` suffix
    # in 3.11; normalise to ``+00:00`` for older interpreters.
    # ``fromisoformat`` 在 3.11 之前不接受 ``Z`` 后缀；统一改写。
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _collect_session_white_c0_samples(
    materials_root: Path,
    *,
    image_source: str | None,
    captured_at: datetime | None,
    window_hours: float = _C0_SESSION_WINDOW_HOURS,
    exclude_directory: Path | None = None,
) -> list[dict[str, Any]]:
    """Collect ``white_C0`` readings from other materials in the same session.
    从同一 session 的其他材料里收集 ``white_C0`` 读数。

    A "session" is the set of captures sharing the same ``image_source``
    and falling within ``window_hours`` of ``captured_at``. The current
    material being saved (``exclude_directory``) is intentionally
    skipped so its own white reading does not anchor the median against
    which it will be compared.
    "session" 定义为同 ``image_source`` 且 ``captured_at`` 在窗口内的样本集合；
    保存中的材料目录会被显式排除，避免自我参照。

    Args:
        materials_root: Root directory containing saved material archives. (耗材根目录)
        image_source: Required match for each candidate run. ``None``
            matches runs that have no recorded image_source. (匹配 image_source)
        captured_at: Anchor timestamp; ``None`` disables the time-window
            filter (used for tests / batch revalidation). (锚定时间)
        window_hours: Half-window size in hours. (窗口半径，小时)
        exclude_directory: Material directory to skip during the walk. (排除目录)

    Returns:
        List of ``{"directory", "captured_at", "white_C0"}`` rows;
        empty when no qualifying samples were found. (匹配样本列表)
    """
    if not materials_root.exists():
        return []
    samples: list[dict[str, Any]] = []
    exclude_resolved = (
        exclude_directory.resolve() if exclude_directory is not None else None
    )
    delta_max = timedelta(hours=float(window_hours))
    for archive_path in materials_root.rglob("material.json"):
        try:
            if not archive_path.is_file():
                continue
            material_dir = archive_path.parent.resolve()
            if exclude_resolved is not None and material_dir == exclude_resolved:
                continue
            payload = json.loads(archive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            # Corrupt / unreadable archives are silently skipped: the
            # session check is opportunistic, not a load-time validator.
            # 损坏档案静默跳过；该层是机会性检查，不承担加载校验职责。
            continue
        runs = payload.get("verification_runs")
        if not isinstance(runs, list):
            continue
        archive_aggregation = (
            payload.get("aggregation")
            if isinstance(payload.get("aggregation"), dict)
            else {}
        )
        archive_image_source = (
            archive_aggregation.get("image_source")
            if isinstance(archive_aggregation, dict)
            else None
        )
        archive_image_source_str = (
            str(archive_image_source)
            if isinstance(archive_image_source, str)
            else None
        )
        for run in runs:
            if not isinstance(run, dict):
                continue
            run_source = (
                run.get("source") if isinstance(run.get("source"), dict) else {}
            )
            run_image_source_value = (
                run_source.get("image_source") if isinstance(run_source, dict) else None
            )
            run_image_source = (
                str(run_image_source_value)
                if isinstance(run_image_source_value, str)
                else archive_image_source_str
            )
            if image_source != run_image_source:
                continue
            run_captured = _parse_iso_datetime(run.get("captured_at"))
            if captured_at is not None:
                if run_captured is None:
                    continue
                if abs(run_captured - captured_at) > delta_max:
                    continue
            params = (
                run.get("params") if isinstance(run.get("params"), dict) else {}
            )
            white_c0_raw = params.get("white_C0") if isinstance(params, dict) else None
            if not isinstance(white_c0_raw, list) or len(white_c0_raw) != 3:
                continue
            try:
                values = [float(v) for v in white_c0_raw]
            except (TypeError, ValueError):
                continue
            samples.append(
                {
                    "directory": str(material_dir),
                    "captured_at": run.get("captured_at"),
                    "white_C0": values,
                }
            )
    return samples


def _compute_session_white_c0_reference(
    materials_root: Path | None,
    *,
    image_source: str | None,
    captured_at_iso: str | None,
    window_hours: float = _C0_SESSION_WINDOW_HOURS,
    exclude_directory: Path | None = None,
) -> dict[str, Any] | None:
    """Compute the per-channel median ``white_C0`` across the session.
    计算同一 session 内的 ``white_C0`` 逐通道中位数。

    Returns ``None`` when no qualifying samples exist (greenfield
    materials root, mismatched image source, archives outside the time
    window). The ``_select_runs_for_refit`` layer treats ``None`` as
    "skip the session check" so first-time calibrations don't trip on
    an empty reference.
    无可用样本时返回 None；selection 层视为"跳过本层"，避免在首次校准时
    把唯一的 fresh run 排除。
    """
    if materials_root is None:
        return None
    captured_at = _parse_iso_datetime(captured_at_iso)
    samples = _collect_session_white_c0_samples(
        materials_root,
        image_source=image_source,
        captured_at=captured_at,
        window_hours=window_hours,
        exclude_directory=exclude_directory,
    )
    if not samples:
        return None
    arr = np.asarray([s["white_C0"] for s in samples], dtype=np.float64)
    median = np.median(arr, axis=0)
    return {
        "median": [float(v) for v in median.tolist()],
        "sample_count": int(arr.shape[0]),
        "image_source": image_source,
        "window_hours": float(window_hours),
        "abs_threshold": _C0_SESSION_OUTLIER_ABS_THRESHOLD,
        "rel_threshold": _C0_SESSION_OUTLIER_REL_THRESHOLD,
        "captured_at_anchor": captured_at_iso,
    }


def _check_run_against_session_c0(
    run: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any] | None:
    """Test a single run's ``white_C0`` against the session reference.
    将单个 run 的 ``white_C0`` 与 session 中位数对比。

    Returns ``None`` when the run is within tolerance, or a diagnostic
    dict (``run_white_c0``, ``session_median``, ``max_abs_diff``,
    ``max_rel_diff``, thresholds, ``sample_count``) when it trips the
    outlier rule. The diagnostic is wired straight into the
    ``selection.excluded_runs`` audit list so the UI can render a
    concrete "your run vs session" comparison.
    通过返回 None；越界返回诊断字典直接拼到 ``excluded_runs`` 供前端展示。
    """
    params = run.get("params") if isinstance(run.get("params"), dict) else {}
    white_c0_raw = params.get("white_C0") if isinstance(params, dict) else None
    if not isinstance(white_c0_raw, list) or len(white_c0_raw) != 3:
        return None
    try:
        values = np.asarray([float(v) for v in white_c0_raw], dtype=np.float64)
    except (TypeError, ValueError):
        return None
    median_list = reference.get("median")
    if not isinstance(median_list, list) or len(median_list) != 3:
        return None
    try:
        median = np.asarray([float(v) for v in median_list], dtype=np.float64)
    except (TypeError, ValueError):
        return None
    abs_diff = np.abs(values - median)
    safe_denom = np.maximum(np.abs(median), 1e-6)
    rel_diff = abs_diff / safe_denom
    max_abs = float(abs_diff.max())
    max_rel = float(rel_diff.max())
    abs_threshold = float(
        reference.get("abs_threshold", _C0_SESSION_OUTLIER_ABS_THRESHOLD)
    )
    rel_threshold = float(
        reference.get("rel_threshold", _C0_SESSION_OUTLIER_REL_THRESHOLD)
    )
    if max_abs <= abs_threshold and max_rel <= rel_threshold:
        return None
    return {
        "run_white_c0": values.tolist(),
        "session_median": median.tolist(),
        "max_abs_diff": max_abs,
        "max_rel_diff": max_rel,
        "abs_threshold": abs_threshold,
        "rel_threshold": rel_threshold,
        "sample_count": int(reference.get("sample_count") or 0),
    }


def _select_runs_for_refit(
    verification_runs: list[dict[str, Any]],
    *,
    cross_val_threshold: int = 3,
    session_white_c0_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pick which runs participate in the joint refit.
    选择哪些 run 参与联合重拟合。

    Selection policy (two-layer):

    1. **Bias filter**: a historical run is dropped when it carries
       *strictly more* bias flags than the fresh run. Equal-or-fewer
       flags are kept so the joint refit can still benefit from extra
       samples when both the fresh capture and the historical share
       the same level of bias (e.g. both ``image_source=restored``).
       There is no "graceful degradation" that keeps a strictly-worse
       historical: if every historical is worse than the fresh run we
       fall back to a single-run refit on the fresh capture alone,
       because adding biased samples to the LM cost would corrupt
       ``(E, k)`` more than helping precision.
    2. **Cross-val ranking**: when ``cross_val_threshold`` or more
       historical runs survive the bias filter, score them by how well
       each predicts the others (lower RMSE = more accurate); keep the
       top ``ceil(N/2)`` (at least one). With N<threshold the cross-val
       tie-breaker is skipped — too few candidates to detect bias by
       mutual disagreement.

    The fresh run (assumed to be the LAST entry in ``verification_runs``)
    is always kept so the user's most recent capture cannot be silently
    discarded — surfacing it lets the operator see why their workflow
    is flagged instead of pretending the capture never happened.

    Args:
        verification_runs: Full chronological list as persisted on disk.
            (完整按时间排序的 verification_runs)
        cross_val_threshold: Minimum surviving historical count required
            to enable cross-val ranking. Defaults to 3 because cross-val
            on 2 runs only checks "do they agree", not "which is right".
            (启用 cross-val 的最小存活历史数量；2 个时只能查"是否一致")

    Returns:
        Dict with keys:
          - ``selected_indices``: sorted list of indices to refit on
          - ``excluded_runs``: list of dicts ``{index, reason, score?,
            bias_flags}`` for audit / UI display
          - ``selection_strategy``: stable string code identifying which
            policy ran (``bias_filter_v1`` vs ``bias_filter_v1+cross_val``)
          - ``run_scores``: per-run diagnostic dict (always present, lets
            UI show every run's bias flags + cross-val score even when no
            run was excluded)
          - ``fresh_index``: the index of the run that was force-kept
    """
    if not verification_runs:
        return {
            "selected_indices": [],
            "excluded_runs": [],
            "selection_strategy": "bias_filter_v1",
            "run_scores": [],
            "fresh_index": None,
        }

    fresh_index = len(verification_runs) - 1
    historical_indices = list(range(fresh_index))

    run_scores: list[dict[str, Any]] = []
    for idx, run in enumerate(verification_runs):
        bias = _score_run_bias(run)
        run_scores.append(
            {
                "index": idx,
                "is_fresh": idx == fresh_index,
                "bias_flag_count": bias["bias_flag_count"],
                "bias_flags": bias["bias_flags"],
                "structural_flag_count": bias["structural_flag_count"],
                "structural_flags": bias["structural_flags"],
                "white_c0_avg": bias["white_c0_avg"],
                "image_source": bias["image_source"],
                "cross_val_rmse": None,
            }
        )

    excluded: list[dict[str, Any]] = []

    # --- Layer 1: bias filter on historical runs ---
    # Drop historicals strictly worse (more *structural* flags) than the
    # fresh run. We use ``structural_flag_count``, not the broader
    # ``bias_flag_count``, because advisory flags like
    # ``orientation_unreliable`` are signal-to-noise driven and would
    # cause spurious drops on equally-good captures whose noise
    # happens to land just below the orientation_ranker threshold.
    # 仅按"结构性"偏置标签做硬过滤；提示性标签会在 UI 中展示但不参与丢
    # 弃决策，避免噪声驱动的朝向标志误伤同等水平的历史 run。
    fresh_struct_flags = run_scores[fresh_index]["structural_flag_count"]
    clean_historical = [
        i
        for i in historical_indices
        if run_scores[i]["structural_flag_count"] <= fresh_struct_flags
    ]
    for i in historical_indices:
        if i in clean_historical:
            continue
        excluded.append(
            {
                "index": i,
                "reason": "bias_filter",
                "bias_flags": list(run_scores[i]["bias_flags"]),
                "structural_flags": list(run_scores[i]["structural_flags"]),
            }
        )

    selection_strategy = "bias_filter_v1"

    # --- Layer 1.5: pairwise white_C0 mismatch vs fresh ---
    # Two runs whose white_C0 averages differ by more than
    # ``_C0_WHITE_PAIRWISE_RATIO_THRESHOLD`` cannot share a single
    # joint refit: the cost surface has no consistent (E, k) for both
    # lighting environments. The fresh run is the canonical reference
    # (the operator just captured it on purpose), so the historical
    # is the one excluded. We compute ratio = max/min so the rule is
    # symmetric whether the fresh is brighter or darker.
    # 跨 run 的成对白底比较：与新 run 偏离超过 1.5× 即视为光照不一致，
    # 剔除历史 run。
    fresh_white_c0 = run_scores[fresh_index]["white_c0_avg"]
    if (
        isinstance(fresh_white_c0, (int, float))
        and not isinstance(fresh_white_c0, bool)
        and fresh_white_c0 > 0.0
    ):
        survived_pairwise: list[int] = []
        for i in clean_historical:
            run_white_c0 = run_scores[i]["white_c0_avg"]
            if (
                not isinstance(run_white_c0, (int, float))
                or isinstance(run_white_c0, bool)
                or run_white_c0 <= 0.0
            ):
                # Cannot compare without a numeric reference; let
                # Layer 1's single-run filter speak for this run.
                survived_pairwise.append(i)
                continue
            ratio = max(run_white_c0, fresh_white_c0) / min(
                run_white_c0, fresh_white_c0
            )
            if ratio > _C0_WHITE_PAIRWISE_RATIO_THRESHOLD:
                excluded.append(
                    {
                        "index": i,
                        "reason": "c0_white_pairwise_mismatch",
                        "bias_flags": list(run_scores[i]["bias_flags"]),
                        "structural_flags": list(
                            run_scores[i]["structural_flags"]
                        ),
                        "fresh_white_c0_avg": float(fresh_white_c0),
                        "run_white_c0_avg": float(run_white_c0),
                        "ratio": float(ratio),
                    }
                )
            else:
                survived_pairwise.append(i)
        clean_historical = survived_pairwise

    # --- Layer 2: cross-val on surviving historicals (+ fresh) when N>=threshold ---
    if len(clean_historical) >= cross_val_threshold:
        cross_val_candidates = clean_historical + [fresh_index]
        cv_scores = _cross_val_score_runs(verification_runs, cross_val_candidates)
        for i in cross_val_candidates:
            if i in cv_scores:
                run_scores[i]["cross_val_rmse"] = cv_scores[i]
        if cv_scores:
            selection_strategy = "bias_filter_v1+cross_val"
            historical_with_score = [
                i for i in clean_historical if i in cv_scores
            ]
            if historical_with_score:
                historical_with_score.sort(key=lambda i: cv_scores[i])
                keep_count = max(1, (len(historical_with_score) + 1) // 2)
                kept_after_cv = set(historical_with_score[:keep_count])
                kept_after_cv.update(
                    i for i in clean_historical if i not in cv_scores
                )
                for i in clean_historical:
                    if i not in kept_after_cv:
                        excluded.append(
                            {
                                "index": i,
                                "reason": "cross_val",
                                "bias_flags": list(run_scores[i]["bias_flags"]),
                                "cross_val_rmse": cv_scores.get(i),
                            }
                        )
                clean_historical = sorted(kept_after_cv)

    selected_indices = sorted(set(clean_historical) | {fresh_index})

    # --- Layer 1.7: cross-material session-level white_C0 consistency ---
    # When a session reference is available, every selected run
    # (including ``fresh_index``) is compared against the session's
    # median white_C0. A run whose white_C0 deviates beyond either
    # threshold is excluded — even if it is fresh — because a wrong
    # white substrate sample cannot be salvaged by force-keeping: the
    # resulting (E, k) would absorb the lighting offset and bias every
    # downstream multi-material colour prediction. The earlier layers
    # are intentionally fresh-canonical (the operator's most recent
    # capture is trusted *relative to history*), but here the median of
    # other materials in the same session provides an objective
    # reference, so the fresh-keep contract is correctly weakened.
    # 跨材料 session-level 白底比对放在最后：用同 session 其他材料的
    # 中位数为客观参考，任意 selected run（含 fresh）越界即排除。该层有
    # 意识地不享受 fresh 强留，因为白底参照是物理客观，不存在"最近就一定
    # 对"的语义。
    if session_white_c0_reference is not None:
        survivors_after_session: list[int] = []
        any_session_outlier = False
        for i in selected_indices:
            outlier_diag = _check_run_against_session_c0(
                verification_runs[i],
                session_white_c0_reference,
            )
            if outlier_diag is None:
                survivors_after_session.append(i)
                continue
            # Fold the new structural flag into ``run_scores`` so the
            # UI's per-run badge list stays the single source of truth
            # for "what's wrong with this run". (将新标签合并进 run_scores)
            score = run_scores[i]
            if _BIAS_FLAG_C0_SESSION_OUTLIER not in score["bias_flags"]:
                score["bias_flags"].append(_BIAS_FLAG_C0_SESSION_OUTLIER)
                score["bias_flag_count"] = len(score["bias_flags"])
            if _BIAS_FLAG_C0_SESSION_OUTLIER not in score["structural_flags"]:
                score["structural_flags"].append(_BIAS_FLAG_C0_SESSION_OUTLIER)
                score["structural_flag_count"] = len(score["structural_flags"])
            excluded.append(
                {
                    "index": i,
                    "reason": "c0_session_outlier",
                    "bias_flags": list(score["bias_flags"]),
                    "structural_flags": list(score["structural_flags"]),
                    **outlier_diag,
                }
            )
            any_session_outlier = True
        selected_indices = survivors_after_session
        if any_session_outlier and "session_c0" not in selection_strategy:
            selection_strategy = f"{selection_strategy}+session_c0"

    return {
        "selected_indices": selected_indices,
        "excluded_runs": excluded,
        "selection_strategy": selection_strategy,
        "run_scores": run_scores,
        "fresh_index": fresh_index,
    }


def _aggregate_stage_a_runs(
    *,
    material_name: str,
    params_payload: dict[str, Any],
    fit_summary: dict[str, Any],
    material_summary: dict[str, Any],
    verification_runs: list[dict[str, Any]],
    session_white_c0_reference: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fallback_e_values, fallback_k_values, fallback_white_c0_values, fallback_black_c0_values = _extract_stage_a_vectors(params_payload)

    aggregated_warnings = _collect_run_warnings(verification_runs)

    # Decide which runs participate in the joint refit. Biased runs are
    # excluded so a single white-balanced capture cannot drag the LM fit
    # toward a model that "looks great" against its own biased samples
    # but predicts colour poorly in production. Selection metadata is
    # persisted later so the UI can explain *why* a run was dropped.
    # The optional session reference enables the cross-material white_C0
    # consistency check (Layer 1.7); ``None`` keeps legacy behaviour.
    # 选择哪些 run 参与联合重拟合，把已知偏置的 run 隔离掉；选择详情会写
    # 入 archive，便于前端解释为何某个 run 被排除。可选的 session 参考用于
    # 跨材料白底一致性检查（Layer 1.7），传 None 保持旧行为。
    selection = _select_runs_for_refit(
        verification_runs,
        session_white_c0_reference=session_white_c0_reference,
    )
    selected_runs = [verification_runs[i] for i in selection["selected_indices"]]

    combined = _collect_combined_run_samples(selected_runs)
    if combined is not None:
        # Preferred path: re-fit Beer-Lambert on the combined sample set.
        # Statistically valid; lets verification_count actually improve (E, k).
        # 合并样本重拟合：统计有效，验证次数能真正提升精度。
        thickness_mm, white_linear, black_linear = combined
        (
            agg_e_values,
            agg_k_values,
            agg_white_c0_values,
            agg_black_c0_values,
            channel_rmse,
            overall_validation_refit,
        ) = _refit_combined_samples(thickness_mm, white_linear, black_linear)
        aggregation_method = "refit_combined_samples"
        overall_validation: dict[str, Any] = dict(overall_validation_refit)
        overall_validation["channel_rmse"] = channel_rmse
        per_run_mean_de: list[float] = []
        for run in selected_runs:
            ov = (run.get("fit_summary") or {}).get("overall_validation") or {}
            try:
                per_run_mean_de.append(float(ov["mean_delta_e"]))
            except (KeyError, TypeError, ValueError):
                continue
        if per_run_mean_de:
            overall_validation["best_run_mean_delta_e"] = float(np.min(np.asarray(per_run_mean_de, dtype=np.float64)))
    else:
        # Fallback path: per-run parameter arithmetic mean. Used when any
        # historical run lacks ``samples`` (older archives) or when stored
        # samples failed schema validation. Aggregation is statistically
        # weaker but never worse than a single run, and preserves backwards
        # compatibility for archives saved before the samples field existed.
        # 历史档案缺 samples 或 schema 校验失败时回退到参数均值，保持向后兼容。
        # Mean fallback also operates only on selected_runs so the bias
        # filter applies regardless of which path the aggregator takes.
        # 参数均值兜底同样只对 selected_runs 平均，确保偏置过滤在两个路径上一致生效。
        agg_e_values = _average_numeric_vectors(
            [list((run.get("params") or {}).get("E") or []) for run in selected_runs],
            fallback_e_values,
        )
        agg_k_values = _average_numeric_vectors(
            [list((run.get("params") or {}).get("k") or []) for run in selected_runs],
            fallback_k_values,
        )
        agg_white_c0_values = _average_numeric_vectors(
            [list((run.get("params") or {}).get("white_C0") or []) for run in selected_runs],
            fallback_white_c0_values,
        )
        agg_black_c0_values = _average_numeric_vectors(
            [list((run.get("params") or {}).get("black_C0") or []) for run in selected_runs],
            fallback_black_c0_values,
        )
        aggregation_method = "mean"

        mean_delta_e_values: list[float] = []
        max_delta_e_values: list[float] = []
        rmse_linear_values: list[float] = []
        channel_rmse_values: list[list[float]] = []
        for run in selected_runs:
            run_fit_summary = run.get("fit_summary") or {}
            if not isinstance(run_fit_summary, dict):
                continue
            ov = run_fit_summary.get("overall_validation") or {}
            if not isinstance(ov, dict):
                ov = {}
            try:
                if "mean_delta_e" in ov:
                    mean_delta_e_values.append(float(ov["mean_delta_e"]))
                if "max_delta_e" in ov:
                    max_delta_e_values.append(float(ov["max_delta_e"]))
                if "rmse_linear" in ov:
                    rmse_linear_values.append(float(ov["rmse_linear"]))
            except (TypeError, ValueError):
                pass
            channel_rmse_per_run = ov.get("channel_rmse")
            if isinstance(channel_rmse_per_run, list):
                try:
                    channel_rmse_values.append([float(value) for value in channel_rmse_per_run])
                except (TypeError, ValueError):
                    pass

        overall_validation = _json_clone(fit_summary.get("overall_validation") or {})
        if mean_delta_e_values:
            overall_validation["mean_delta_e"] = float(np.mean(np.asarray(mean_delta_e_values, dtype=np.float64)))
            overall_validation["best_run_mean_delta_e"] = float(np.min(np.asarray(mean_delta_e_values, dtype=np.float64)))
        if max_delta_e_values:
            overall_validation["max_delta_e"] = float(np.max(np.asarray(max_delta_e_values, dtype=np.float64)))
        if rmse_linear_values:
            overall_validation["rmse_linear"] = float(np.mean(np.asarray(rmse_linear_values, dtype=np.float64)))
        if channel_rmse_values:
            overall_validation["channel_rmse"] = [
                float(value)
                for value in np.mean(np.asarray(channel_rmse_values, dtype=np.float64), axis=0).tolist()
            ]

    overall_validation["verification_count"] = len(verification_runs)
    overall_validation["aggregation_method"] = aggregation_method
    overall_validation["selected_run_count"] = len(selected_runs)
    overall_validation["selection_strategy"] = selection["selection_strategy"]

    aggregated_fit_summary = _json_clone(fit_summary)
    aggregated_fit_summary["colors"] = [material_name]
    aggregated_fit_summary["warnings"] = aggregated_warnings
    aggregated_fit_summary["overall_validation"] = overall_validation

    aggregated_material_summary = _json_clone(material_summary)
    aggregated_material_summary["white_zero_rgb"] = _linear_to_srgb_uint8(
        np.asarray([agg_white_c0_values], dtype=np.float64)
    )[0].tolist()
    aggregated_material_summary["black_zero_rgb"] = _linear_to_srgb_uint8(
        np.asarray([agg_black_c0_values], dtype=np.float64)
    )[0].tolist()
    aggregated_material_summary["estimated_rgb"] = _linear_to_srgb_uint8(
        np.asarray([agg_e_values], dtype=np.float64)
    )[0].tolist()
    aggregated_material_summary["estimated_k"] = [round(float(value), 6) for value in agg_k_values]
    aggregated_material_summary["verification_count"] = len(verification_runs)
    aggregated_material_summary["aggregation_method"] = aggregation_method
    aggregated_material_summary["selected_run_count"] = len(selected_runs)
    # Drop the per-run ``fit_samples`` from the aggregated material_summary.
    # The samples are preserved per-run inside ``verification_runs[*].samples``
    # so we don't need to keep a copy on the top-level summary, and removing
    # it keeps the archive footprint stable across multi-run aggregations.
    # 聚合后的 material_summary 不再保留 fit_samples（它们已存在每个 run 内），
    # 减少多次验证后档案体积膨胀。
    aggregated_material_summary.pop("fit_samples", None)

    aggregated_params_payload = _json_clone(params_payload)
    meta = aggregated_params_payload.setdefault("meta", {})
    meta["generated_at"] = _now_iso()
    meta["warnings"] = aggregated_warnings
    meta["verification_count"] = len(verification_runs)
    meta["aggregation_method"] = aggregation_method
    meta["selection"] = _json_clone(selection)
    parameters = aggregated_params_payload.setdefault("parameters", {})
    channels = parameters.get("channels") or []
    if channels and isinstance(channels[0], dict):
        channels[0]["color_name"] = material_name
        channels[0]["E"] = [round(float(value), 6) for value in agg_e_values]
        channels[0]["k"] = [round(float(value), 6) for value in agg_k_values]
    substrates = parameters.get("substrates") or []
    for substrate in substrates:
        if not isinstance(substrate, dict):
            continue
        if substrate.get("substrate_id") == "white":
            substrate["C0"] = [round(float(value), 6) for value in agg_white_c0_values]
        elif substrate.get("substrate_id") == "black":
            substrate["C0"] = [round(float(value), 6) for value in agg_black_c0_values]
    fitted_substrates = aggregated_params_payload.setdefault("fitted_substrates", {})
    fitted_substrates["white"] = {"C0": [round(float(value), 6) for value in agg_white_c0_values]}
    fitted_substrates["black"] = {"C0": [round(float(value), 6) for value in agg_black_c0_values]}
    validation = aggregated_params_payload.setdefault("validation", {})
    validation["overall"] = overall_validation
    return aggregated_params_payload, aggregated_fit_summary, aggregated_material_summary



def _safe_float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    try:
        return [float(entry) for entry in value]
    except (TypeError, ValueError):
        return []



def _safe_rgb_triplet(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    try:
        return [int(entry) for entry in value[:3]]
    except (TypeError, ValueError):
        return []



def _summarize_verification_runs(
    verification_runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    history_items: list[dict[str, Any]] = []
    for index, run in enumerate(verification_runs, start=1):
        run_fit_summary = run.get("fit_summary") or {}
        run_material_summary = run.get("material_summary") or {}
        run_source = run.get("source") or {}
        run_params = run.get("params") or {}
        if not isinstance(run_fit_summary, dict):
            run_fit_summary = {}
        if not isinstance(run_material_summary, dict):
            run_material_summary = {}
        if not isinstance(run_source, dict):
            run_source = {}
        if not isinstance(run_params, dict):
            run_params = {}
        overall_validation = run_fit_summary.get("overall_validation") or {}
        if not isinstance(overall_validation, dict):
            overall_validation = {}

        mean_delta_e: float | None = None
        rmse_linear: float | None = None
        try:
            if "mean_delta_e" in overall_validation:
                mean_delta_e = float(overall_validation["mean_delta_e"])
            if "rmse_linear" in overall_validation:
                rmse_linear = float(overall_validation["rmse_linear"])
        except (TypeError, ValueError):
            mean_delta_e = None if mean_delta_e is None else mean_delta_e
            rmse_linear = None if rmse_linear is None else rmse_linear

        history_items.append(
            {
                "verification_index": index,
                "captured_at": run.get("captured_at"),
                "mean_delta_e": mean_delta_e,
                "rmse_linear": rmse_linear,
                "estimated_rgb": _safe_rgb_triplet(run_material_summary.get("estimated_rgb")),
                "estimated_k": _safe_float_list(run_material_summary.get("estimated_k") or run_params.get("k")),
                "e_values": _safe_float_list(run_params.get("E")),
                "k_values": _safe_float_list(run_params.get("k")),
                "white_c0_values": _safe_float_list(run_params.get("white_C0")),
                "black_c0_values": _safe_float_list(run_params.get("black_C0")),
                "white_detected_orientation": run_source.get("white_detected_orientation"),
                "black_detected_orientation": run_source.get("black_detected_orientation"),
            }
        )
    return history_items



def save_stage_a_material_archive(
    *,
    material_name: str,
    params_payload: dict[str, Any],
    fit_summary: dict[str, Any],
    source_summary: dict[str, Any],
    material_summary: dict[str, Any],
    materials_dir: str | None = None,
    existing_directory_name: str | None = None,
    save_mode: str = "merge",
    brand: str | None = None,
) -> MaterialArchiveSaveResult:
    """Persist a Stage A material archive into the project materials directory.
    将 Stage A 耗材档案持久化保存到项目 materials 目录。

    Args:
        material_name: User-provided material name. (用户输入的耗材名称)
        params_payload: Stage A payload to persist. (待保存的 Stage A 数据)
        fit_summary: Stage A fit summary. (Stage A 拟合摘要)
        source_summary: Input-source metadata. (输入来源元数据)
        material_summary: Material extraction summary. (耗材提取摘要)
        materials_dir: Optional override output directory. (可选的输出目录覆盖)
        existing_directory_name: Optional existing material directory to update. (可选的已有耗材目录名)
        save_mode: ``"merge"`` to append to existing verification runs and
            aggregate, or ``"override"`` to replace all previous runs with the
            current result only. (合并已有验证或覆盖)
        brand: Optional brand sub-directory. When provided and creating a new
            material, the archive is stored under
            ``materials/<brand>/<material_name>/``. Ignored when
            ``existing_directory_name`` is provided. (可选的品牌子目录名称)

    Returns:
        MaterialArchiveSaveResult: Saved archive information. (保存结果)
    """
    if save_mode not in ("merge", "override"):
        raise ValueError(f"Invalid save_mode: {save_mode!r}, expected 'merge' or 'override'")
    target_root = Path(materials_dir or MATERIALS_DIR)
    target_root.mkdir(parents=True, exist_ok=True)
    archive_path: Path
    created_at: str
    final_material_name = material_name
    final_brand: str | None = None
    verification_runs: list[dict[str, Any]] = []
    if existing_directory_name:
        material_dir = _resolve_material_dir(target_root, existing_directory_name)
        archive_path = material_dir / "material.json"
        if not archive_path.exists():
            raise FileNotFoundError(f"Saved material archive not found: {existing_directory_name}")
        try:
            existing_archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Existing material archive is not valid UTF-8 JSON") from exc
        created_at = str(existing_archive_payload.get("created_at") or _now_iso())
        final_material_name = str(existing_archive_payload.get("material_name") or material_name)
        final_brand = _saved_material_brand_from_archive_payload(
            existing_archive_payload,
            _relative_directory_name(target_root, material_dir),
        )
        if save_mode == "merge":
            verification_runs = _load_existing_verification_runs(material_dir, existing_archive_payload)
    else:
        sanitized_brand = None
        if isinstance(brand, str) and brand.strip():
            sanitized_brand = brand.strip()
        final_brand = sanitized_brand
        material_dir = _unique_material_dir(
            target_root, material_name, brand=sanitized_brand
        )
        material_dir.mkdir(parents=True, exist_ok=True)
        archive_path = material_dir / "material.json"
        created_at = _now_iso()

    new_image_source = _coerce_image_source(source_summary.get("image_source"))
    if save_mode == "merge" and verification_runs:
        existing_image_sources = _collect_run_image_sources(verification_runs)
        # Two physically inconsistent sources cannot be safely merged: their
        # (E, k) live in different "white-balanced reference" frames so any
        # combined refit (or even a parameter mean) is meaningless.
        # Reject the merge with an actionable error so the user can either
        # re-shoot the new capture in the same mode or drop into ``override``.
        # 两种来源的样本不可混合聚合：它们的 (E, k) 处于不同的"白平衡参考系"，
        # 任何合并重拟合或参数均值都没有物理意义。明确拒绝并给出 actionable
        # 错误，让用户要么按相同来源重拍，要么改用 override 模式。
        if (
            existing_image_sources
            and new_image_source not in existing_image_sources
            and new_image_source is not None
        ):
            existing_label = ", ".join(sorted(existing_image_sources))
            raise ValueError(
                "Cannot merge gradient-card captures from different image "
                f"sources: existing runs use [{existing_label}] but the new "
                f"capture is tagged '{new_image_source}'. Re-capture the new "
                "card in the same mode, or use save_mode='override' to "
                "discard previous verification runs."
            )
    verification_runs.append(
        _build_verification_run(
            params_payload=params_payload,
            fit_summary=fit_summary,
            material_summary=material_summary,
            source_summary=source_summary,
        )
    )

    # Compute the cross-material session reference once per save call.
    # We anchor on the freshly appended run's ``captured_at`` and the
    # current ``image_source`` so the median is drawn only from captures
    # that share the same physical lighting/exposure context. The
    # current material directory is excluded from the walk so its own
    # historical reading does not anchor the median against which it
    # would later be compared (i.e. self-anchoring is forbidden).
    # When no qualifying samples exist (first calibration session,
    # mismatched image source, etc.) the helper returns ``None`` and
    # ``_aggregate_stage_a_runs`` falls back to legacy selection.
    # 一次保存只算一次 session 中位数；锚点是新 run 的捕获时间 + image_source。
    # 排除当前材料目录避免自我参照；无匹配样本时返回 None，落回旧逻辑。
    fresh_run_captured_at = (
        verification_runs[-1].get("captured_at")
        if verification_runs and isinstance(verification_runs[-1], dict)
        else None
    )
    session_white_c0_reference = _compute_session_white_c0_reference(
        target_root,
        image_source=new_image_source,
        captured_at_iso=(
            fresh_run_captured_at
            if isinstance(fresh_run_captured_at, str)
            else None
        ),
        exclude_directory=material_dir,
    )

    payload, aggregated_fit_summary, aggregated_material_summary = _aggregate_stage_a_runs(
        material_name=final_material_name,
        params_payload=params_payload,
        fit_summary=fit_summary,
        material_summary=material_summary,
        verification_runs=verification_runs,
        session_white_c0_reference=session_white_c0_reference,
    )

    stage_a_params_path = material_dir / "stage_A_parameters.json"
    stage_a_params_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    updated_at = _now_iso()
    archive_aggregation_method = str(
        ((payload.get("meta") or {}).get("aggregation_method"))
        or "mean"
    )
    archive_selection = (payload.get("meta") or {}).get("selection")
    if not isinstance(archive_selection, dict):
        archive_selection = None
    image_source_tags = _collect_run_image_sources(verification_runs)
    if not image_source_tags:
        image_source_label: str | None = None
    elif len(image_source_tags) == 1:
        image_source_label = next(iter(image_source_tags))
    else:
        # Cannot happen in normal flow because the merge-consistency check
        # rejects mixed sources earlier, but if it ever does (e.g. legacy
        # archive seeded with mixed sources), preserve the truth so audits
        # can flag it instead of silently picking one.
        # 正常流程不会触发；保留真实状态便于审计而非偷偷择一。
        image_source_label = "mixed"
    archive_payload = {
        "schema_version": "1.1",
        "kind": "lumina_stage_a_material",
        "material_name": final_material_name,
        "brand": final_brand,
        "created_at": created_at,
        "updated_at": updated_at,
        "stage_a_params_file": stage_a_params_path.name,
        "fit_summary": aggregated_fit_summary,
        "material_summary": aggregated_material_summary,
        "source": _json_clone(source_summary),
        "verification_count": len(verification_runs),
        "verification_runs": verification_runs,
        "aggregation": {
            "method": archive_aggregation_method,
            "aggregated_at": updated_at,
            "image_source": image_source_label,
            "selection": archive_selection,
        },
    }
    archive_path.write_text(
        json.dumps(archive_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result_summary = _material_summary_from_saved_archive(
        target_root,
        material_dir,
        archive_payload,
    )
    _invalidate_material_library_cache(target_root)
    return MaterialArchiveSaveResult(
        archive_path=str(archive_path),
        stage_a_params_path=str(stage_a_params_path),
        material_summary=result_summary,
    )


_ESTIMATED_RGB_UNSET: Any = object()


def _validate_estimated_rgb_override(value: Sequence[int]) -> list[int]:
    """Validate and normalize a user-supplied sRGB override triplet.
    校验并归一化用户提供的 sRGB 覆盖三元组。

    Args:
        value: Iterable of 3 integer channels in [0, 255]. (3 个 [0, 255] 内整数通道)

    Returns:
        Normalized ``[R, G, B]`` list of ints. (归一化后的 ``[R, G, B]`` 整数列表)

    Raises:
        ValueError: If the value is not a 3-length iterable of valid channels.
    """
    if isinstance(value, (str, bytes)) or not hasattr(value, "__iter__"):
        raise ValueError("estimated_rgb must be a 3-element sequence of integers")
    channels = list(value)
    if len(channels) != 3:
        raise ValueError("estimated_rgb must contain exactly 3 channels")
    normalized: list[int] = []
    for channel in channels:
        try:
            channel_int = int(channel)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "estimated_rgb channels must be integers in [0, 255]"
            ) from exc
        if not 0 <= channel_int <= 255:
            raise ValueError(
                "estimated_rgb channels must be integers in [0, 255]"
            )
        normalized.append(channel_int)
    return normalized


def update_saved_stage_a_material_archive_metadata(
    *,
    directory_name: str,
    material_name: str,
    brand: str | None = None,
    estimated_rgb: Sequence[int] | Any = _ESTIMATED_RGB_UNSET,
    materials_dir: str | None = None,
) -> MaterialArchiveUpdateResult:
    """Update editable metadata on a saved Stage A material archive.
    更新已保存 Stage A 耗材档案的可编辑元数据。

    Args:
        directory_name: Saved material directory name. (已保存的耗材目录名)
        material_name: Updated user-facing material name. (更新后的耗材名称)
        brand: Updated optional brand label. (更新后的可选品牌标签)
        estimated_rgb: Optional user-overridden display sRGB ``[R, G, B]``
            triplet. Pass ``_ESTIMATED_RGB_UNSET`` (default) to leave the
            previously stored value unchanged. (可选的用户覆盖显示 sRGB 三元组;
            默认 ``_ESTIMATED_RGB_UNSET`` 时保留原值不变)
        materials_dir: Optional materials root override. (可选的 materials 根目录覆盖)

    Returns:
        MaterialArchiveUpdateResult: Updated archive information. (更新结果)
    """
    cleaned_material_name = str(material_name).strip()
    if not cleaned_material_name:
        raise ValueError("material_name is required")
    cleaned_brand = None
    if isinstance(brand, str):
        stripped_brand = brand.strip()
        cleaned_brand = stripped_brand or None

    normalized_estimated_rgb: list[int] | None
    if estimated_rgb is _ESTIMATED_RGB_UNSET:
        normalized_estimated_rgb = None
    else:
        normalized_estimated_rgb = _validate_estimated_rgb_override(estimated_rgb)

    target_root = Path(materials_dir or MATERIALS_DIR)
    material_dir = _resolve_material_dir(target_root, directory_name)
    archive_path = material_dir / "material.json"
    if not archive_path.exists():
        raise FileNotFoundError(f"Saved material archive not found: {directory_name}")
    archive_payload = _load_json_object(
        archive_path,
        "Existing material archive is not valid UTF-8 JSON",
    )
    stage_a_params_path = _resolve_stage_a_params_path(material_dir, archive_payload)
    if not stage_a_params_path.exists():
        raise FileNotFoundError(
            f"Saved Stage A parameters not found for material: {directory_name}"
        )
    stage_a_payload = _load_json_object(
        stage_a_params_path,
        "Saved Stage A parameters are not valid UTF-8 JSON",
    )

    updated_at = _now_iso()
    archive_payload["material_name"] = cleaned_material_name
    archive_payload["brand"] = cleaned_brand
    archive_payload["updated_at"] = updated_at
    if normalized_estimated_rgb is not None:
        material_summary = archive_payload.get("material_summary")
        if not isinstance(material_summary, dict):
            material_summary = {}
            archive_payload["material_summary"] = material_summary
        material_summary["estimated_rgb"] = normalized_estimated_rgb
    fit_summary = archive_payload.get("fit_summary")
    if isinstance(fit_summary, dict):
        fit_summary["colors"] = [cleaned_material_name]
    archive_path.write_text(
        json.dumps(archive_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    updated_stage_a_payload = _update_stage_a_payload_material_name(
        stage_a_payload,
        cleaned_material_name,
    )
    stage_a_params_path.write_text(
        json.dumps(updated_stage_a_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _invalidate_material_library_cache(target_root)
    return MaterialArchiveUpdateResult(
        archive_path=str(archive_path),
        stage_a_params_path=str(stage_a_params_path),
        material_summary=_saved_material_library_item_from_archive(
            target_root,
            material_dir,
            archive_payload,
        ),
    )


def delete_saved_stage_a_material_archive(
    *,
    directory_name: str,
    materials_dir: str | None = None,
) -> MaterialArchiveDeleteResult:
    """Delete a saved Stage A material archive directory.
    删除已保存的 Stage A 耗材档案目录。

    Args:
        directory_name: Saved material directory name. (已保存的耗材目录名)
        materials_dir: Optional override output directory. (可选的输出目录覆盖)

    Returns:
        MaterialArchiveDeleteResult: Deleted archive information. (删除结果)
    """
    target_root = Path(materials_dir or MATERIALS_DIR)
    material_dir = _resolve_material_dir(target_root, directory_name)
    archive_path = material_dir / "material.json"
    material_name = material_dir.name
    if archive_path.exists():
        try:
            archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
            material_name = str(archive_payload.get("material_name") or material_name)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            material_name = material_dir.name
    relative_directory_name = _relative_directory_name(target_root, material_dir)
    deleted_path = str(material_dir)
    parent_dir = material_dir.parent
    shutil.rmtree(material_dir)
    _prune_empty_parents(parent_dir, target_root)
    _invalidate_material_library_cache(target_root)
    return MaterialArchiveDeleteResult(
        directory_name=relative_directory_name,
        material_name=material_name,
        deleted_path=deleted_path,
    )


def export_saved_stage_a_material_archives(
    *,
    directory_names: list[str],
    materials_dir: str | None = None,
    output_path: str | None = None,
) -> MaterialArchiveExportResult:
    """Export one or more saved Stage A material archives into a ZIP file.
    导出一个或多个已保存的 Stage A 耗材档案为 ZIP 文件。

    Args:
        directory_names: Saved material directory names to export. (要导出的耗材目录名)
        materials_dir: Optional materials root override. (可选的 materials 根目录覆盖)
        output_path: Optional ZIP output path override. (可选的 ZIP 输出路径覆盖)

    Returns:
        MaterialArchiveExportResult: Generated ZIP archive metadata. (生成的 ZIP 归档信息)
    """
    normalized_names = _normalize_material_directory_names(directory_names)
    target_root = Path(materials_dir or MATERIALS_DIR)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    download_filename = f"lumina_materials_{len(normalized_names)}_{timestamp}.zip"
    zip_output_path = (
        Path(output_path)
        if isinstance(output_path, str) and output_path.strip()
        else Path(TEMP_DIR) / f"lumina_material_export_{uuid.uuid4().hex}.zip"
    )
    zip_output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "kind": "lumina_material_export",
        "exported_at": _now_iso(),
        "directory_names": normalized_names,
        "material_count": len(normalized_names),
    }
    bundle_manifest = {
        "schema_version": _MATERIAL_PACKAGE_SCHEMA_VERSION,
        "kind": "lumina_material_bundle",
        "exported_at": manifest["exported_at"],
        "material_count": len(normalized_names),
        "packages": [],
    }
    try:
        with zipfile.ZipFile(
            zip_output_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr(
                _MATERIAL_EXPORT_MANIFEST_FILENAME,
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            for directory_name in normalized_names:
                material_dir = _resolve_material_dir(target_root, directory_name)
                material_archive_path = material_dir / "material.json"
                if not material_archive_path.is_file():
                    raise FileNotFoundError(
                        f"Saved material archive not found: {directory_name}"
                    )
                relative_directory_name = _relative_directory_name(
                    target_root,
                    material_dir,
                )
                package_manifest, files_to_write = (
                    _build_material_bundle_package_manifest(
                        target_root=target_root,
                        material_dir=material_dir,
                    )
                )
                bundle_manifest["packages"].append(package_manifest)
                for file_path, zip_path in files_to_write:
                    archive.write(file_path, zip_path)
            archive.writestr(
                _MATERIAL_BUNDLE_MANIFEST_FILENAME,
                json.dumps(bundle_manifest, ensure_ascii=False, indent=2),
            )
    except Exception:
        try:
            zip_output_path.unlink()
        except OSError:
            pass
        raise

    return MaterialArchiveExportResult(
        archive_path=str(zip_output_path),
        download_filename=download_filename,
        exported_directory_names=normalized_names,
    )


def import_saved_stage_a_material_archives(
    *,
    archive_path: str,
    materials_dir: str | None = None,
    selected_material_id: str | None = None,
    selected_revision_id: str | None = None,
) -> MaterialArchiveImportResult:
    """Import one ZIP file containing one or more saved Stage A material archives.
    导入一个包含一个或多个已保存 Stage A 耗材档案的 ZIP 文件。

    Args:
        archive_path: ZIP archive path to import. (要导入的 ZIP 归档路径)
        materials_dir: Optional materials root override. (可选的 materials 根目录覆盖)
        selected_material_id: Optional package material_id to import from a
            bundle. (可选：从 bundle 中只导入指定 material_id)
        selected_revision_id: Optional package revision_id to import from a
            bundle. (可选：从 bundle 中只导入指定 revision_id)

    Returns:
        MaterialArchiveImportResult: Imported material summaries. (导入后的耗材摘要)
    """
    selected_material_id = str(selected_material_id or "").strip()
    selected_revision_id = str(selected_revision_id or "").strip()
    if bool(selected_material_id) != bool(selected_revision_id):
        raise ValueError(
            "selected_material_id and selected_revision_id must be provided together"
        )
    target_root = Path(materials_dir or MATERIALS_DIR)
    target_root.mkdir(parents=True, exist_ok=True)
    extract_root = Path(
        tempfile.mkdtemp(prefix="material_archive_import_", dir=TEMP_DIR)
    )
    try:
        extracted_root = _safe_extract_material_zip(archive_path, extract_root)
        manifest_root = extracted_root
        if not (
            (manifest_root / _MATERIAL_BUNDLE_MANIFEST_FILENAME).is_file()
            or (manifest_root / _MATERIAL_EXPORT_MANIFEST_FILENAME).is_file()
        ):
            if (
                (extract_root / _MATERIAL_BUNDLE_MANIFEST_FILENAME).is_file()
                or (extract_root / _MATERIAL_EXPORT_MANIFEST_FILENAME).is_file()
            ):
                manifest_root = extract_root
        bundle_manifest = _load_material_bundle_manifest(manifest_root)
        manifest = _load_material_export_manifest(manifest_root)
        material_root = (
            extracted_root / "materials"
            if (extracted_root / "materials").is_dir()
            else extracted_root
        )
        package_by_directory: dict[str, dict[str, Any]] = {}
        if bundle_manifest is not None:
            raw_packages = bundle_manifest["packages"]
            normalized_directory_names = []
            selected_package_found = False
            for raw_package in raw_packages:
                if not isinstance(raw_package, dict):
                    raise ValueError("Material bundle manifest contains invalid package")
                raw_material_id = str(raw_package.get("material_id") or "").strip()
                raw_revision_id = str(raw_package.get("revision_id") or "").strip()
                if selected_material_id:
                    if (
                        raw_material_id != selected_material_id
                        or raw_revision_id != selected_revision_id
                    ):
                        continue
                    selected_package_found = True
                _verify_material_bundle_package(
                    extracted_root=manifest_root,
                    package=raw_package,
                )
                normalized_directory_name = _normalize_relative_directory_name(
                    str(raw_package.get("local_directory") or "")
                )
                normalized_directory_names.append(normalized_directory_name)
                package_by_directory[normalized_directory_name] = raw_package
            if selected_material_id and not selected_package_found:
                raise ValueError(
                    "Selected material bundle package not found: "
                    f"{selected_material_id}/{selected_revision_id}"
                )
            normalized_directory_names = _normalize_material_directory_names(
                normalized_directory_names
            )
            staged_material_dirs = [
                material_root / Path(directory_name)
                for directory_name in normalized_directory_names
            ]
        elif manifest is not None:
            raw_directory_names = manifest.get("directory_names")
            if not isinstance(raw_directory_names, list) or not raw_directory_names:
                raise ValueError(
                    "Material export manifest is missing directory_names"
                )
            normalized_directory_names = _normalize_material_directory_names(
                raw_directory_names
            )
            staged_material_dirs = [
                material_root / Path(directory_name)
                for directory_name in normalized_directory_names
            ]
        else:
            staged_material_dirs = sorted(
                _discover_saved_material_dirs(material_root),
                key=lambda path: path.as_posix(),
            )

        if not staged_material_dirs:
            raise ValueError(
                "Material archive ZIP does not contain any saved material directories"
            )

        imported_materials: list[dict[str, Any]] = []
        created_material_dirs: list[Path] = []
        installed_packages: list[tuple[dict[str, Any], Path]] = []
        try:
            for staged_material_dir in staged_material_dirs:
                relative_directory_name = _relative_directory_name(
                    material_root,
                    staged_material_dir,
                )
                package = package_by_directory.get(relative_directory_name)
                if package is not None and _installed_material_bundle_revision_path(
                    target_root=target_root,
                    package=package,
                ) is not None:
                    continue
                material_archive_path = staged_material_dir / "material.json"
                if not material_archive_path.is_file():
                    raise FileNotFoundError(
                        f"Saved material archive not found in ZIP: {relative_directory_name}"
                    )
                archive_payload = _load_json_object(
                    material_archive_path,
                    "Saved material archive is not valid UTF-8 JSON",
                )
                stage_a_params_path = _resolve_stage_a_params_path(
                    staged_material_dir,
                    archive_payload,
                )
                if not stage_a_params_path.is_file():
                    raise FileNotFoundError(
                        f"Saved Stage A parameters not found in ZIP: {relative_directory_name}"
                    )
                _load_json_object(
                    stage_a_params_path,
                    "Saved Stage A parameters are not valid UTF-8 JSON",
                )
                destination_dir = _import_target_material_dir(
                    target_root,
                    relative_directory_name,
                )
                try:
                    if package is not None:
                        _copy_material_bundle_package_files(
                            manifest_root=manifest_root,
                            staged_material_dir=staged_material_dir,
                            destination_dir=destination_dir,
                            package=package,
                        )
                    else:
                        shutil.copytree(staged_material_dir, destination_dir)
                except Exception:
                    if destination_dir.exists():
                        shutil.rmtree(destination_dir, ignore_errors=True)
                    raise
                created_material_dirs.append(destination_dir)
                if package is not None:
                    installed_packages.append((package, destination_dir))
                imported_materials.append(
                    _material_summary_from_saved_archive(
                        target_root,
                        destination_dir,
                        archive_payload,
                    )
                )
            _record_material_sync_entries(
                target_root=target_root,
                installed_packages=installed_packages,
            )
            _invalidate_material_library_cache(target_root)
        except Exception:
            for created_dir in reversed(created_material_dirs):
                parent_dir = created_dir.parent
                shutil.rmtree(created_dir, ignore_errors=True)
                _prune_empty_parents(parent_dir, target_root)
            raise

        return MaterialArchiveImportResult(imported_materials=imported_materials)
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)


def refresh_material_sync_from_registry(
    *,
    registry_url: str | None = None,
    channels: Sequence[str] | None = None,
    token: str | None = None,
    materials_dir: str | None = None,
    timeout_s: float | None = None,
    transport: Any = None,
) -> dict[str, Any]:
    """Pull read-only material package revisions from a configured Registry.
    从配置的 Registry 只读拉取耗材包 revision 并安装到本地库。

    The Registry is only a download source in this MVP: no publish/upload
    capability is exposed here, so ordinary clients remain read-only.
    MVP 阶段该 Registry 只作为下载源；这里不提供发布/上传能力，普通客户端保持只读。
    """
    import httpx

    normalized_registry_url = _normalize_material_registry_url(registry_url)
    normalized_channels = _normalize_material_registry_channels(channels)
    auth_token = str(
        token
        if token is not None
        else os.environ.get("LUMINA_MATERIAL_REGISTRY_TOKEN", "")
    ).strip()
    if timeout_s is None:
        raw_timeout = os.environ.get("LUMINA_MATERIAL_REGISTRY_TIMEOUT_S", "30")
        try:
            timeout_s = float(raw_timeout)
        except ValueError:
            timeout_s = 30.0
    target_root = Path(materials_dir or MATERIALS_DIR)
    target_root.mkdir(parents=True, exist_ok=True)
    with _MaterialSyncRefreshFileLock(target_root):
        headers = {"User-Agent": "LuminaStudioMaterialSync/1"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        client_kwargs: dict[str, Any] = {
            "timeout": float(timeout_s),
            "follow_redirects": True,
        }
        if transport is not None:
            client_kwargs["transport"] = transport

        with httpx.Client(**client_kwargs) as client:
            try:
                catalog_response = client.get(
                    _material_registry_catalog_url(normalized_registry_url),
                    params=[("channel", channel) for channel in normalized_channels],
                    headers=headers,
                )
                catalog_response.raise_for_status()
                catalog_payload = catalog_response.json()
                catalog_entries = _material_registry_catalog_entries(catalog_payload)
            except httpx.HTTPError as exc:
                raise RuntimeError("Material registry catalog request failed") from exc
            except ValueError as exc:
                raise ValueError("Material registry catalog response is invalid") from exc

            installed_materials: list[dict[str, Any]] = []
            failures: list[dict[str, str]] = []
            skipped_count = 0
            for entry in catalog_entries:
                material_id = str(entry.get("material_id") or "").strip()
                revision_id = str(entry.get("revision_id") or "").strip()
                package_url = str(entry.get("package_url") or "").strip()
                try:
                    content_hash = str(entry.get("content_hash") or "").strip()
                    if not material_id or not revision_id or not content_hash:
                        raise ValueError(
                            "Material registry catalog entry is missing material identity"
                        )
                    if _installed_material_bundle_revision_path(
                        target_root=target_root,
                        package={
                            "material_id": material_id,
                            "revision_id": revision_id,
                            "content_hash": content_hash,
                        },
                        include_revision_history=True,
                    ) is not None:
                        skipped_count += 1
                        continue

                    resolved_package_url = _material_registry_package_url(
                        normalized_registry_url,
                        package_url,
                    )
                    expected_package_sha256 = _sha256_hex_from_catalog(
                        entry.get("package_sha256")
                    )
                    package_response = client.get(resolved_package_url, headers=headers)
                    package_response.raise_for_status()
                    package_bytes = package_response.content
                    actual_package_sha256 = _sha256_bytes(package_bytes)
                    if actual_package_sha256 != expected_package_sha256:
                        raise ValueError(
                            "Material registry package_sha256 mismatch: "
                            f"{material_id}/{revision_id}"
                        )
                    temp_package_path = _write_temp_material_registry_package(package_bytes)
                    try:
                        import_result = import_saved_stage_a_material_archives(
                            archive_path=str(temp_package_path),
                            materials_dir=str(target_root),
                        )
                    finally:
                        try:
                            temp_package_path.unlink()
                        except OSError:
                            pass
                    installed_materials.extend(import_result.imported_materials)
                except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as exc:
                    failures.append(
                        {
                            "material_id": material_id,
                            "revision_id": revision_id,
                            "package_url": package_url,
                            "error": str(exc),
                        }
                    )

        checked_count = len(catalog_entries)
        installed_count = len(installed_materials)
        failed_count = len(failures)
        cursor = (
            catalog_payload.get("cursor")
            if isinstance(catalog_payload, dict)
            else None
        )
        _record_material_registry_refresh(
            target_root=target_root,
            registry_url=normalized_registry_url,
            channels=normalized_channels,
            cursor=cursor,
            checked_count=checked_count,
            installed_count=installed_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
        )
        return {
            "registry_url": normalized_registry_url,
            "channels": normalized_channels,
            "checked_count": checked_count,
            "installed_count": installed_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "installed_materials": installed_materials,
            "failures": failures,
        }


def list_saved_stage_a_material_archives(
    *,
    materials_dir: str | None = None,
) -> list[dict[str, Any]]:
    """List saved Stage A material archives from the project materials directory.
    列出项目 materials 目录中已保存的 Stage A 耗材档案。

    Args:
        materials_dir: Optional override output directory. (可选的输出目录覆盖)

    Returns:
        list[dict[str, Any]]: Material archive summaries sorted by recency. (按时间倒序的耗材档案摘要)
    """
    target_root = Path(materials_dir or MATERIALS_DIR)
    if not target_root.exists():
        return []
    cached_items = _cached_material_library_items(target_root)
    if cached_items is not None:
        return _apply_official_registry_metadata(cached_items)

    items: list[dict[str, Any]] = []
    archive_paths = [
        path for path in target_root.rglob("material.json") if path.is_file()
    ]
    filtered_archive_paths = _filter_nested_material_archive_paths(archive_paths)
    sync_metadata_by_directory = _material_sync_metadata_by_directory(target_root)

    for archive_path in sorted(
        filtered_archive_paths,
        key=lambda path: path.parent.stat().st_mtime,
        reverse=True,
    ):
        material_dir = archive_path.parent
        try:
            archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        item = _saved_material_library_item_from_archive(
            target_root,
            material_dir,
            archive_payload,
        )
        content_hash = _local_material_content_hash(material_dir, archive_payload)
        if content_hash:
            item["content_hash"] = content_hash
        item.update(sync_metadata_by_directory.get(item["directory_name"], {}))
        items.append(item)
    _apply_official_registry_metadata(items)
    _store_material_library_cache(target_root, items)
    return items


# ---------------------------------------------------------------------------
# Material usage tracking (per-material usage_stats.json sidecar)
# 耗材使用次数追踪（每个耗材目录下的 usage_stats.json 边车文件）
# ---------------------------------------------------------------------------

_MATERIAL_USAGE_FILENAME = "usage_stats.json"
_MATERIAL_USAGE_SCHEMA_VERSION = "1.0"
_MATERIAL_USAGE_HISTORY_LIMIT = 50
"""Maximum number of recent usage events kept in ``usage_stats.json``.
Older events are trimmed; aggregated counters in ``total`` / ``by_color_mode``
are never reset.
``usage_stats.json`` 中保留的最近使用事件数量上限；超出后旧事件会被裁剪，
但 ``total`` / ``by_color_mode`` 这些累计计数不会被重置。
"""


def _normalize_color_mode_for_usage(color_mode: Any) -> str:
    """Coerce a color_mode value to a clean string for usage bucketing.
    将 color_mode 值规范为用于使用次数分桶的干净字符串。

    Accepts enum members (with ``.value``), strings, and other primitives.
    Returns ``"unknown"`` for empty / non-stringifiable values.
    支持枚举（取 ``.value``）、字符串及其他基础类型；无效或空值返回 ``"unknown"``。
    """
    if color_mode is None:
        return "unknown"
    raw = getattr(color_mode, "value", color_mode)
    text = str(raw).strip()
    return text or "unknown"


def _empty_usage_payload() -> dict[str, Any]:
    """Build a fresh, zeroed usage_stats payload.
    构造一份初始化为零的 usage_stats 数据。
    """
    return {
        "schema_version": _MATERIAL_USAGE_SCHEMA_VERSION,
        "total": 0,
        "by_color_mode": {},
        "last_used_at": None,
        "last_used_color_mode": None,
        "history": [],
    }


def _load_usage_payload(material_dir: Path) -> dict[str, Any]:
    """Load and normalize ``usage_stats.json`` from a material directory.
    从耗材目录读取并规范化 ``usage_stats.json``。

    Tolerates missing / corrupt files by falling back to an empty payload —
    usage stats are diagnostics, never primary archive data, so a corrupted
    sidecar must not block the rest of the workflow.
    缺失或损坏的文件会回退为空 payload；usage 仅用于诊断展示，不应阻塞主流程。
    """
    usage_path = material_dir / _MATERIAL_USAGE_FILENAME
    if not usage_path.is_file():
        return _empty_usage_payload()
    try:
        raw = json.loads(usage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return _empty_usage_payload()
    if not isinstance(raw, dict):
        return _empty_usage_payload()

    normalized = _empty_usage_payload()
    try:
        normalized["total"] = max(0, int(raw.get("total") or 0))
    except (TypeError, ValueError):
        normalized["total"] = 0

    by_mode_raw = raw.get("by_color_mode")
    if isinstance(by_mode_raw, dict):
        cleaned: dict[str, int] = {}
        for key, value in by_mode_raw.items():
            try:
                count = int(value)
            except (TypeError, ValueError):
                continue
            if count <= 0:
                continue
            cleaned[str(key)] = count
        normalized["by_color_mode"] = cleaned

    last_at = raw.get("last_used_at")
    if isinstance(last_at, str) and last_at.strip():
        normalized["last_used_at"] = last_at
    last_mode = raw.get("last_used_color_mode")
    if isinstance(last_mode, str) and last_mode.strip():
        normalized["last_used_color_mode"] = last_mode

    history_raw = raw.get("history")
    if isinstance(history_raw, list):
        cleaned_history: list[dict[str, Any]] = []
        for entry in history_raw[-_MATERIAL_USAGE_HISTORY_LIMIT:]:
            if not isinstance(entry, dict):
                continue
            mode = entry.get("color_mode")
            used_at = entry.get("used_at")
            if not isinstance(mode, str) or not isinstance(used_at, str):
                continue
            cleaned_history.append({"color_mode": mode, "used_at": used_at})
        normalized["history"] = cleaned_history
    return normalized


def get_material_usage(material_dir: Path | str) -> dict[str, Any]:
    """Public read accessor for a material's usage statistics.
    对外暴露的耗材使用统计读取函数。

    Args:
        material_dir: Path to the saved-material directory containing
            ``material.json``. (耗材档案目录)

    Returns:
        Normalized usage payload (always a dict; counters default to 0).
        规范化后的 usage payload，计数缺省为 0。
    """
    return _load_usage_payload(Path(material_dir))


def record_material_usage(
    directory_names: Sequence[str],
    color_mode: Any,
    *,
    materials_dir: str | None = None,
    used_at: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Record one usage event for each given material directory.
    为每个给定的耗材目录追加一次使用记录。

    Increments ``total`` and ``by_color_mode[color_mode]`` for each material,
    appends a history entry, and writes the sidecar back atomically (best
    effort: a per-material I/O failure is logged into the result dict but
    does not raise — usage tracking is auxiliary).

    Args:
        directory_names: Material directory_name values used in the build.
            (本次生成中使用的耗材目录名)
        color_mode: Color mode the build was generated under (enum or string).
            (本次生成使用的颜色模式)
        materials_dir: Optional override for the materials root directory.
            (可选的 materials 根目录覆盖)
        used_at: Optional ISO-8601 timestamp; defaults to now (UTC).
            (可选的 ISO-8601 时间戳；默认 UTC 当前时间)

    Returns:
        Mapping ``{directory_name: updated_usage_payload | {"error": "..."}}``
        for diagnostic purposes. 仅用于诊断。
    """
    if not directory_names:
        return {}
    target_root = Path(materials_dir or MATERIALS_DIR)
    timestamp = used_at if isinstance(used_at, str) and used_at.strip() else _now_iso()
    color_mode_label = _normalize_color_mode_for_usage(color_mode)

    seen: set[str] = set()
    results: dict[str, dict[str, Any]] = {}
    for raw_name in directory_names:
        if not isinstance(raw_name, str):
            continue
        try:
            normalized_name = _normalize_relative_directory_name(raw_name)
        except ValueError:
            results[str(raw_name)] = {"error": "invalid_directory_name"}
            continue
        if normalized_name in seen:
            continue
        seen.add(normalized_name)
        try:
            material_dir = resolve_saved_material_dir(target_root, normalized_name)
        except (ValueError, FileNotFoundError):
            results[normalized_name] = {"error": "material_not_found"}
            continue
        if not (material_dir / "material.json").is_file():
            results[normalized_name] = {"error": "material_archive_missing"}
            continue

        payload = _load_usage_payload(material_dir)
        payload["total"] = int(payload.get("total") or 0) + 1
        by_mode = payload.setdefault("by_color_mode", {})
        by_mode[color_mode_label] = int(by_mode.get(color_mode_label, 0) or 0) + 1
        payload["last_used_at"] = timestamp
        payload["last_used_color_mode"] = color_mode_label
        history = payload.setdefault("history", [])
        history.append({"color_mode": color_mode_label, "used_at": timestamp})
        if len(history) > _MATERIAL_USAGE_HISTORY_LIMIT:
            del history[: len(history) - _MATERIAL_USAGE_HISTORY_LIMIT]
        payload["schema_version"] = _MATERIAL_USAGE_SCHEMA_VERSION

        usage_path = material_dir / _MATERIAL_USAGE_FILENAME
        try:
            usage_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            results[normalized_name] = payload
        except OSError as exc:
            # Auxiliary tracking must never break a successful generation.
            # 辅助统计写入失败时不应影响生成主流程。
            results[normalized_name] = {"error": f"write_failed: {exc}"}
    if any("error" not in payload for payload in results.values()):
        _invalidate_material_library_cache(target_root)
    return results
