from __future__ import annotations

import json
import re
import shutil
import uuid
import zipfile
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
class _WarpCandidate:
    orientation_label: str
    corner_order: tuple[int, int, int, int]
    ordered_points: np.ndarray
    warped_rgb: np.ndarray
    sample_boxes: list[dict[str, int]]
    linear_samples: np.ndarray


_INVALID_WINDOWS_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WARP_PIXELS_PER_MM = 20.0
_SAMPLE_INSET_RATIO = 0.18
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



def _sample_grid_means(
    warped_rgb: np.ndarray,
    spec: SingleStageSpec,
    sample_boxes: list[dict[str, int]] | None = None,
) -> np.ndarray:
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
        samples[row, col] = roi.reshape(-1, 3).mean(axis=0)
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
        srgb_samples = _sample_grid_means(warped_rgb, spec, sample_boxes)
        linear_samples = _srgb_to_linear(srgb_samples.reshape(-1, 3))
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
    zero_mask = thickness_mm == float(np.min(thickness_mm))
    max_mask = thickness_mm == float(np.max(thickness_mm))
    c0_white_init = float(np.mean(white_obs[zero_mask]))
    c0_black_init = float(np.mean(black_obs[zero_mask]))
    e_init = float(np.mean(np.concatenate([white_obs[max_mask], black_obs[max_mask]])))
    e_init = float(np.clip(e_init, 0.0, 1.0))
    k_init = 3.0
    for c0_init, obs in ((c0_white_init, white_obs), (c0_black_init, black_obs)):
        valid = (thickness_mm > 0) & (np.abs(c0_init - e_init) > 1e-6) & (np.abs(obs - e_init) > 1e-6)
        if not np.any(valid):
            continue
        ratio = (obs[valid] - e_init) / (c0_init - e_init)
        ratio = ratio[np.isfinite(ratio)]
        ratio = ratio[(ratio > 1e-6) & (ratio < 0.999999)]
        if ratio.size == 0:
            continue
        t_valid = thickness_mm[valid][: ratio.size]
        estimates = -np.log(ratio) / np.maximum(t_valid, 1e-6)
        estimates = estimates[np.isfinite(estimates) & (estimates > 1e-6)]
        if estimates.size:
            k_init = float(np.median(estimates))
            break
    init = np.array([
        e_init,
        float(np.clip(k_init, 1e-4, 200.0)),
        float(np.clip(c0_white_init, 0.0, 1.0)),
        float(np.clip(c0_black_init, 0.0, 1.0)),
    ])

    def _residuals(x: np.ndarray) -> np.ndarray:
        e, k, c0_white, c0_black = x
        pred_white = e + (c0_white - e) * np.exp(-k * thickness_mm)
        pred_black = e + (c0_black - e) * np.exp(-k * thickness_mm)
        return np.concatenate([pred_white - white_obs, pred_black - black_obs])

    result = least_squares(
        _residuals,
        init,
        bounds=(np.array([0.0, 1e-6, 0.0, 0.0]), np.array([1.0, 200.0, 1.0, 1.0])),
        method="trf",
        max_nfev=2000,
    )
    residual = _residuals(result.x)
    rmse = float(np.sqrt(np.mean(np.square(residual)))) if residual.size else 0.0
    e, k, c0_white, c0_black = result.x
    return float(e), float(k), float(c0_white), float(c0_black), rmse



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

    Returns:
        GradientCardStageAResult: Extraction result bundle. (提取结果)
    """
    manifest = _load_manifest_from_zip(dataset_zip_path)
    spec = _coerce_spec(manifest)
    white_points = _coerce_points(white_corner_points)
    black_points = _coerce_points(black_corner_points)
    white_candidates = _build_warp_candidates(white_image_rgb, white_points, spec)
    black_candidates = _build_warp_candidates(black_image_rgb, black_points, spec)
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
    if orientation_ranking["orientation_reliable"] is False:
        warnings.append("方向检测置信度较低，最优与次优方向的 ΔE 差距很小，请确认角点和图片方向。")
    fit_summary["orientation_ranking"] = orientation_ranking
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
        "orientation_ranking": orientation_ranking,
        "spec": asdict(spec),
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



def _unique_material_dir(base_dir: Path, material_name: str) -> Path:
    stem = _sanitize_material_dirname(material_name)
    candidate = base_dir / stem
    if not candidate.exists():
        return candidate
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    return base_dir / f"{stem}_{suffix}"



def _json_clone(payload: Any) -> Any:
    return json.loads(json.dumps(payload, ensure_ascii=False))



def _resolve_material_dir(base_dir: Path, directory_name: str) -> Path:
    normalized = str(directory_name).strip()
    requested = Path(normalized)
    if (
        not normalized
        or normalized in {".", ".."}
        or requested.name != normalized
        or requested.anchor
        or any(part in {".", ".."} for part in requested.parts)
    ):
        raise ValueError("directory_name must reference a single saved material directory")
    candidate = base_dir / normalized
    if not candidate.is_dir():
        raise FileNotFoundError(f"Saved material directory not found: {normalized}")
    return candidate



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



def _build_verification_run(
    *,
    params_payload: dict[str, Any],
    fit_summary: dict[str, Any],
    material_summary: dict[str, Any],
    source_summary: dict[str, Any],
    captured_at: str | None = None,
) -> dict[str, Any]:
    e_values, k_values, white_c0_values, black_c0_values = _extract_stage_a_vectors(params_payload)
    return {
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



def _aggregate_stage_a_runs(
    *,
    material_name: str,
    params_payload: dict[str, Any],
    fit_summary: dict[str, Any],
    material_summary: dict[str, Any],
    verification_runs: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fallback_e_values, fallback_k_values, fallback_white_c0_values, fallback_black_c0_values = _extract_stage_a_vectors(params_payload)
    mean_e_values = _average_numeric_vectors(
        [list((run.get("params") or {}).get("E") or []) for run in verification_runs],
        fallback_e_values,
    )
    mean_k_values = _average_numeric_vectors(
        [list((run.get("params") or {}).get("k") or []) for run in verification_runs],
        fallback_k_values,
    )
    mean_white_c0_values = _average_numeric_vectors(
        [list((run.get("params") or {}).get("white_C0") or []) for run in verification_runs],
        fallback_white_c0_values,
    )
    mean_black_c0_values = _average_numeric_vectors(
        [list((run.get("params") or {}).get("black_C0") or []) for run in verification_runs],
        fallback_black_c0_values,
    )

    mean_delta_e_values: list[float] = []
    max_delta_e_values: list[float] = []
    rmse_linear_values: list[float] = []
    channel_rmse_values: list[list[float]] = []
    warning_values: list[str] = []
    for run in verification_runs:
        run_fit_summary = run.get("fit_summary") or {}
        if not isinstance(run_fit_summary, dict):
            continue
        overall_validation = run_fit_summary.get("overall_validation") or {}
        if not isinstance(overall_validation, dict):
            overall_validation = {}
        try:
            if "mean_delta_e" in overall_validation:
                mean_delta_e_values.append(float(overall_validation["mean_delta_e"]))
            if "max_delta_e" in overall_validation:
                max_delta_e_values.append(float(overall_validation["max_delta_e"]))
            if "rmse_linear" in overall_validation:
                rmse_linear_values.append(float(overall_validation["rmse_linear"]))
        except (TypeError, ValueError):
            pass
        channel_rmse = overall_validation.get("channel_rmse")
        if isinstance(channel_rmse, list):
            try:
                channel_rmse_values.append([float(value) for value in channel_rmse])
            except (TypeError, ValueError):
                pass
        run_warnings = run_fit_summary.get("warnings")
        if isinstance(run_warnings, list):
            warning_values.extend(str(value) for value in run_warnings if str(value).strip())

    aggregated_fit_summary = _json_clone(fit_summary)
    aggregated_fit_summary["colors"] = [material_name]
    aggregated_fit_summary["warnings"] = sorted(dict.fromkeys(warning_values))
    overall_validation = _json_clone(aggregated_fit_summary.get("overall_validation") or {})
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
    aggregated_fit_summary["overall_validation"] = overall_validation

    aggregated_material_summary = _json_clone(material_summary)
    aggregated_material_summary["white_zero_rgb"] = _linear_to_srgb_uint8(
        np.asarray([mean_white_c0_values], dtype=np.float64)
    )[0].tolist()
    aggregated_material_summary["black_zero_rgb"] = _linear_to_srgb_uint8(
        np.asarray([mean_black_c0_values], dtype=np.float64)
    )[0].tolist()
    aggregated_material_summary["estimated_rgb"] = _linear_to_srgb_uint8(
        np.asarray([mean_e_values], dtype=np.float64)
    )[0].tolist()
    aggregated_material_summary["estimated_k"] = [round(float(value), 6) for value in mean_k_values]
    aggregated_material_summary["verification_count"] = len(verification_runs)

    aggregated_params_payload = _json_clone(params_payload)
    meta = aggregated_params_payload.setdefault("meta", {})
    meta["generated_at"] = _now_iso()
    meta["warnings"] = aggregated_fit_summary["warnings"]
    meta["verification_count"] = len(verification_runs)
    meta["aggregation_method"] = "mean"
    parameters = aggregated_params_payload.setdefault("parameters", {})
    channels = parameters.get("channels") or []
    if channels and isinstance(channels[0], dict):
        channels[0]["color_name"] = material_name
        channels[0]["E"] = [round(float(value), 6) for value in mean_e_values]
        channels[0]["k"] = [round(float(value), 6) for value in mean_k_values]
    substrates = parameters.get("substrates") or []
    for substrate in substrates:
        if not isinstance(substrate, dict):
            continue
        if substrate.get("substrate_id") == "white":
            substrate["C0"] = [round(float(value), 6) for value in mean_white_c0_values]
        elif substrate.get("substrate_id") == "black":
            substrate["C0"] = [round(float(value), 6) for value in mean_black_c0_values]
    fitted_substrates = aggregated_params_payload.setdefault("fitted_substrates", {})
    fitted_substrates["white"] = {"C0": [round(float(value), 6) for value in mean_white_c0_values]}
    fitted_substrates["black"] = {"C0": [round(float(value), 6) for value in mean_black_c0_values]}
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
        if save_mode == "merge":
            verification_runs = _load_existing_verification_runs(material_dir, existing_archive_payload)
    else:
        material_dir = _unique_material_dir(target_root, material_name)
        material_dir.mkdir(parents=True, exist_ok=True)
        archive_path = material_dir / "material.json"
        created_at = _now_iso()

    verification_runs.append(
        _build_verification_run(
            params_payload=params_payload,
            fit_summary=fit_summary,
            material_summary=material_summary,
            source_summary=source_summary,
        )
    )
    payload, aggregated_fit_summary, aggregated_material_summary = _aggregate_stage_a_runs(
        material_name=final_material_name,
        params_payload=params_payload,
        fit_summary=fit_summary,
        material_summary=material_summary,
        verification_runs=verification_runs,
    )

    stage_a_params_path = material_dir / "stage_A_parameters.json"
    stage_a_params_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    updated_at = _now_iso()
    archive_payload = {
        "schema_version": "1.1",
        "kind": "lumina_stage_a_material",
        "material_name": final_material_name,
        "created_at": created_at,
        "updated_at": updated_at,
        "stage_a_params_file": stage_a_params_path.name,
        "fit_summary": aggregated_fit_summary,
        "material_summary": aggregated_material_summary,
        "source": _json_clone(source_summary),
        "verification_count": len(verification_runs),
        "verification_runs": verification_runs,
        "aggregation": {
            "method": "mean",
            "aggregated_at": updated_at,
        },
    }
    archive_path.write_text(
        json.dumps(archive_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result_summary = {
        "material_name": final_material_name,
        "directory_name": material_dir.name,
        "archive_path": str(archive_path),
        "stage_a_params_path": str(stage_a_params_path),
        "verification_count": len(verification_runs),
        "created_at": created_at,
        "updated_at": updated_at,
    }
    return MaterialArchiveSaveResult(
        archive_path=str(archive_path),
        stage_a_params_path=str(stage_a_params_path),
        material_summary=result_summary,
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
    shutil.rmtree(material_dir)
    return MaterialArchiveDeleteResult(
        directory_name=material_dir.name,
        material_name=material_name,
        deleted_path=str(material_dir),
    )



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

    items: list[dict[str, Any]] = []
    for material_dir in sorted(
        (path for path in target_root.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ):
        archive_path = material_dir / "material.json"
        if not archive_path.exists():
            continue
        try:
            archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue

        stage_a_filename = str(archive_payload.get("stage_a_params_file") or "stage_A_parameters.json")
        stage_a_path = material_dir / stage_a_filename
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
        verification_runs = _load_existing_verification_runs(material_dir, archive_payload)
        verification_history = _summarize_verification_runs(verification_runs)
        try:
            verification_count = int(
                archive_payload.get("verification_count")
                or len(verification_history)
                or 1
            )
        except (TypeError, ValueError):
            verification_count = len(verification_history) or 1

        items.append(
            {
                "material_name": str(archive_payload.get("material_name") or material_dir.name),
                "directory_name": material_dir.name,
                "created_at": archive_payload.get("created_at"),
                "updated_at": archive_payload.get("updated_at") or archive_payload.get("created_at"),
                "archive_path": str(archive_path),
                "stage_a_params_path": str(stage_a_path) if stage_a_path.exists() else None,
                "estimated_rgb": estimated_rgb_values,
                "layer_height_mm": material_summary.get("layer_height_mm"),
                "mean_delta_e": overall_validation.get("mean_delta_e"),
                "verification_count": verification_count,
                "verification_history": verification_history,
            }
        )
    return items
