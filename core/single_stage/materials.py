from __future__ import annotations

import json
import re
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


_INVALID_WINDOWS_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WARP_PIXELS_PER_MM = 20.0
_SAMPLE_INSET_RATIO = 0.18


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



def _sample_grid_means(warped_rgb: np.ndarray, spec: SingleStageSpec) -> np.ndarray:
    samples = np.zeros((spec.grid_rows, spec.grid_cols, 3), dtype=np.float64)
    pixels_per_mm_x = warped_rgb.shape[1] / spec.board_width_mm
    pixels_per_mm_y = warped_rgb.shape[0] / spec.board_height_mm
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
            roi = warped_rgb[sy0:sy1, sx0:sx1]
            samples[row, col] = roi.reshape(-1, 3).mean(axis=0)
    return samples



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
    lab = cv2.cvtColor(srgb_uint8.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB)
    return lab.reshape(-1, 3).astype(np.float64)



def _build_fit_payload(
    *,
    material_label: str,
    thickness_mm: np.ndarray,
    white_linear: np.ndarray,
    black_linear: np.ndarray,
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
    if overall_validation["mean_delta_e"] > 6.0:
        warnings.append("High Stage A fit error. Check image orientation and corner selection.")
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
        "thickness_layers": [int(round(value / spec.layer_height_mm)) for value in thickness_mm.tolist()],
        "white_zero_rgb": _linear_to_srgb_uint8(np.asarray([c0_white_values], dtype=np.float64))[0].tolist(),
        "black_zero_rgb": _linear_to_srgb_uint8(np.asarray([c0_black_values], dtype=np.float64))[0].tolist(),
        "estimated_rgb": _linear_to_srgb_uint8(np.asarray([e_values], dtype=np.float64))[0].tolist(),
        "estimated_k": [round(float(value), 6) for value in k_values],
    }
    return params_payload, fit_summary, material_summary, warnings



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
    white_warp_rgb = _warp_image(white_image_rgb, white_points, spec)
    black_warp_rgb = _warp_image(black_image_rgb, black_points, spec)
    white_samples_srgb = _sample_grid_means(white_warp_rgb, spec)
    black_samples_srgb = _sample_grid_means(black_warp_rgb, spec)
    white_linear = _srgb_to_linear(white_samples_srgb.reshape(-1, 3))
    black_linear = _srgb_to_linear(black_samples_srgb.reshape(-1, 3))
    step_layers = _canonical_step_layers(spec).reshape(-1)
    thickness_mm = step_layers * float(spec.layer_height_mm)
    material_label = str(manifest.get("material_default") or "Sample")
    params_payload, fit_summary, material_summary, warnings = _build_fit_payload(
        material_label=material_label,
        thickness_mm=thickness_mm,
        white_linear=white_linear,
        black_linear=black_linear,
        manifest=manifest,
        spec=spec,
    )
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



def save_stage_a_material_archive(
    *,
    material_name: str,
    params_payload: dict[str, Any],
    fit_summary: dict[str, Any],
    source_summary: dict[str, Any],
    material_summary: dict[str, Any],
    materials_dir: str | None = None,
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

    Returns:
        MaterialArchiveSaveResult: Saved archive information. (保存结果)
    """
    target_root = Path(materials_dir or MATERIALS_DIR)
    target_root.mkdir(parents=True, exist_ok=True)
    material_dir = _unique_material_dir(target_root, material_name)
    material_dir.mkdir(parents=True, exist_ok=True)

    payload = json.loads(json.dumps(params_payload, ensure_ascii=False))
    channels = (payload.get("parameters") or {}).get("channels") or []
    if channels and isinstance(channels[0], dict):
        channels[0]["color_name"] = material_name

    stage_a_params_path = material_dir / "stage_A_parameters.json"
    stage_a_params_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    archive_payload = {
        "schema_version": "1.0",
        "kind": "lumina_stage_a_material",
        "material_name": material_name,
        "created_at": _now_iso(),
        "stage_a_params_file": stage_a_params_path.name,
        "fit_summary": fit_summary,
        "material_summary": material_summary,
        "source": source_summary,
    }
    archive_path = material_dir / "material.json"
    archive_path.write_text(
        json.dumps(archive_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result_summary = {
        "material_name": material_name,
        "directory_name": material_dir.name,
        "archive_path": str(archive_path),
        "stage_a_params_path": str(stage_a_params_path),
    }
    return MaterialArchiveSaveResult(
        archive_path=str(archive_path),
        stage_a_params_path=str(stage_a_params_path),
        material_summary=result_summary,
    )
