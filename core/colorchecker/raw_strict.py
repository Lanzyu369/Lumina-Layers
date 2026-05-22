from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

try:
    import rawpy
except ImportError:  # pragma: no cover - depends on the local runtime
    rawpy = None

from .color_metrics import linear_to_srgb

RAW_DECODE_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    RuntimeError,
)
if rawpy is not None and hasattr(rawpy, "LibRawError"):
    RAW_DECODE_ERRORS = RAW_DECODE_ERRORS + (rawpy.LibRawError,)


@dataclass(frozen=True)
class StrictRawDecode:
    linear_rgb: np.ndarray
    preview_bgr: np.ndarray
    metadata: dict[str, Any]


def _rawpy_version() -> str | None:
    if rawpy is None:
        return None
    return str(getattr(rawpy, "__version__", "") or "")


def decode_strict_raw_bytes(raw: bytes, *, file_name: str = "") -> StrictRawDecode:
    if rawpy is None:
        raise ValueError("RAW strict 模式需要 rawpy，但当前环境未安装。")
    params: dict[str, object] = {
        "use_camera_wb": False,
        "use_auto_wb": False,
        "user_wb": [1.0, 1.0, 1.0, 1.0],
        "no_auto_bright": True,
        "bright": 1.0,
        "gamma": (1.0, 1.0),
        "output_bps": 16,
    }
    color_space = getattr(getattr(rawpy, "ColorSpace", None), "raw", None)
    if color_space is not None:
        params["output_color"] = color_space
    demosaic_algorithm = getattr(getattr(rawpy, "DemosaicAlgorithm", None), "AHD", None)
    if demosaic_algorithm is not None:
        params["demosaic_algorithm"] = demosaic_algorithm
    # rawpy/libraw supports no_auto_scale in modern versions. Keep a fallback
    # for older wheels so strict mode fails only on real decode issues.
    try_params = dict(params)
    try_params["no_auto_scale"] = True
    try:
        with rawpy.imread(io.BytesIO(raw)) as raw_image:
            metadata = _metadata(raw_image, file_name=file_name, params=try_params)
            rgb16 = raw_image.postprocess(**try_params)
    except TypeError:
        with rawpy.imread(io.BytesIO(raw)) as raw_image:
            metadata = _metadata(raw_image, file_name=file_name, params=params)
            rgb16 = raw_image.postprocess(**params)
    except RAW_DECODE_ERRORS as exc:
        raise ValueError(f"RAW strict 解码失败：{exc}") from exc
    if rgb16 is None or rgb16.size == 0:
        raise ValueError("RAW strict 解码失败：没有输出图像。")
    linear_rgb, denominator = _normalize_postprocess_rgb(rgb16, metadata)
    metadata["normalization_denominator"] = denominator
    if linear_rgb.ndim != 3 or linear_rgb.shape[2] < 3:
        raise ValueError("RAW strict 解码失败：输出不是 RGB 图像。")
    srgb = np.clip(linear_to_srgb(linear_rgb), 0.0, 1.0)
    preview_bgr = (srgb[..., ::-1] * 255.0 + 0.5).astype(np.uint8)
    clipping = {
        "black_ratio": round(float(np.mean(linear_rgb <= 0.0)), 8),
        "white_ratio": round(float(np.mean(linear_rgb >= 0.999)), 8),
        "pixel_count": int(linear_rgb.shape[0] * linear_rgb.shape[1]),
    }
    metadata["clipping"] = clipping
    return StrictRawDecode(linear_rgb=linear_rgb, preview_bgr=preview_bgr, metadata=metadata)


def _no_auto_scale_enabled(metadata: dict[str, Any]) -> bool:
    parameters = metadata.get("parameters")
    return isinstance(parameters, dict) and parameters.get("no_auto_scale") is True


def _normalization_white_level(metadata: dict[str, Any]) -> float:
    white_level = metadata.get("white_level")
    try:
        return float(white_level)
    except (TypeError, ValueError):
        return 0.0


def _normalization_black_rgb(metadata: dict[str, Any]) -> np.ndarray:
    black_level = metadata.get("black_level_per_channel")
    if not isinstance(black_level, (list, tuple)) or not black_level:
        return np.zeros(3, dtype=np.float32)
    try:
        levels = [float(value) for value in black_level]
    except (TypeError, ValueError):
        return np.zeros(3, dtype=np.float32)

    color_desc = str(metadata.get("color_desc") or "").upper()
    mapped: dict[str, list[float]] = {"R": [], "G": [], "B": []}
    for idx, level in enumerate(levels):
        channel = color_desc[idx] if idx < len(color_desc) else ""
        if channel in mapped:
            mapped[channel].append(level)
    if all(mapped[channel] for channel in ("R", "G", "B")):
        return np.asarray(
            [
                float(np.mean(mapped["R"])),
                float(np.mean(mapped["G"])),
                float(np.mean(mapped["B"])),
            ],
            dtype=np.float32,
        )

    fallback = float(np.mean(levels))
    return np.asarray([fallback, fallback, fallback], dtype=np.float32)


def _normalization_denominator(metadata: dict[str, Any]) -> float:
    if _no_auto_scale_enabled(metadata):
        white_level = _normalization_white_level(metadata)
        if white_level > 0.0:
            black_rgb = _normalization_black_rgb(metadata)
            denominators = white_level - black_rgb
            valid = denominators[denominators > 0.0]
            if valid.size:
                return float(np.max(valid))
    return 65535.0


def _normalize_postprocess_rgb(rgb16: object, metadata: dict[str, Any]) -> tuple[np.ndarray, float]:
    rgb = np.asarray(rgb16, dtype=np.float32)
    if rgb.ndim == 3 and rgb.shape[2] >= 3:
        rgb = rgb[..., :3]
    denominator = _normalization_denominator(metadata)
    if _no_auto_scale_enabled(metadata):
        white_level = _normalization_white_level(metadata)
        black_rgb = _normalization_black_rgb(metadata)
        denominators = white_level - black_rgb
        if white_level > 0.0 and bool(np.all(denominators > 0.0)):
            # LibRaw/rawpy postprocess output is already black-adjusted even
            # when auto scaling is disabled. Do not subtract sensor black a
            # second time; it crushes dark but usable RAW data to zero.
            linear_rgb = rgb / denominators.reshape((1, 1, 3))
            metadata["normalization_black_level_rgb"] = [float(v) for v in black_rgb.tolist()]
            metadata["normalization_denominator_rgb"] = [float(v) for v in denominators.tolist()]
            metadata["normalization_black_subtracted_by_decoder"] = True
            return np.clip(linear_rgb, 0.0, 1.0), denominator
    linear_rgb = rgb / denominator
    if linear_rgb.ndim == 3 and linear_rgb.shape[2] >= 3:
        linear_rgb = linear_rgb[..., :3]
    return np.clip(linear_rgb, 0.0, 1.0), denominator


def _metadata(raw_image: object, *, file_name: str, params: dict[str, object]) -> dict[str, Any]:
    black_level = getattr(raw_image, "black_level_per_channel", None)
    camera_wb = getattr(raw_image, "camera_whitebalance", None)
    color_desc = getattr(raw_image, "color_desc", b"")
    if isinstance(color_desc, bytes):
        color_desc_out = color_desc.decode("ascii", errors="replace")
    else:
        color_desc_out = str(color_desc)
    return {
        "file_name": file_name,
        "decoder": "rawpy/libraw",
        "rawpy_version": _rawpy_version(),
        "parameters": {
            key: _jsonable(value)
            for key, value in params.items()
            if key
            not in {
                "demosaic_algorithm",
                "output_color",
            }
        },
        "visible_size": [
            int(getattr(raw_image, "sizes").width),
            int(getattr(raw_image, "sizes").height),
        ],
        "raw_shape": [int(v) for v in getattr(raw_image, "raw_image_visible").shape],
        "black_level_per_channel": [int(v) for v in black_level] if black_level is not None else None,
        "white_level": int(getattr(raw_image, "white_level")) if getattr(raw_image, "white_level", None) is not None else None,
        "color_desc": color_desc_out,
        "camera_whitebalance": [float(v) for v in camera_wb] if camera_wb is not None else None,
        "strict_notes": [
            "linear camera RGB postprocess",
            "auto bright disabled",
            "gamma set to linear",
            "no sharpening or aesthetic enhancement",
        ],
    }


def _jsonable(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)


def gaussian_blur_linear_rgb(linear_rgb: np.ndarray, radius: float) -> np.ndarray:
    sigma = float(radius)
    if sigma <= 0.0:
        return linear_rgb
    return cv2.GaussianBlur(
        np.asarray(linear_rgb, dtype=np.float32),
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
        borderType=cv2.BORDER_REFLECT_101,
    )
