"""Adapter for the local ColorChecker calibration core.

The implementation lives in :mod:`core.colorchecker`. This module keeps the
Lumina-Layers API surface small: decode uploads, run chart detection, generate
the warped 24-patch preview, and expose a compact calibration summary for the
frontend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence

import numpy as np

from api.structured_logging import get_logger

log = get_logger(__name__)

PointDict = dict[str, float]
PointInput = Sequence[float] | dict[str, float]


class ColorCheckerUnavailableError(RuntimeError):
    """Raised when the local ColorChecker core cannot be imported."""


class ColorCheckerCalibrationError(RuntimeError):
    """Raised when ColorChecker processing fails."""


@dataclass(frozen=True)
class DecodedColorCheckerImage:
    """Decoded uploaded image for ColorChecker processing.

    Args:
        image_bgr: Decoded BGR image array.
        source_type: ``"standard"``, ``"raw"``, or another source label from
            the core decoder.

    解码后的 ColorChecker 输入图。``image_bgr`` 使用 OpenCV 的 BGR 通道顺序。
    """

    image_bgr: np.ndarray
    source_type: str


@dataclass(frozen=True)
class ChartDetectionResult:
    """Automatic ColorChecker chart detection result.

    自动色卡定位结果；``corners`` 使用原图坐标。
    """

    detected: bool
    corners: list[PointDict]
    patch_orientation: str
    confidence: float
    score: float | None
    mode: str
    reason: str
    candidate_count: int

    def to_response(self) -> dict[str, object]:
        return {
            "detected": self.detected,
            "corners": self.corners,
            "patchOrientation": self.patch_orientation,
            "confidence": self.confidence,
            "score": self.score,
            "mode": self.mode,
            "reason": self.reason,
            "candidateCount": self.candidate_count,
        }


@dataclass(frozen=True)
class WarpPreviewResult:
    """Warped ColorChecker preview and auto-generated sampling points.

    透视展开后的 24 色卡预览，以及自动生成的 24 个采样点。
    """

    preview_png: bytes
    preview_width: int
    preview_height: int
    auto_patch_points: list[PointDict]


@dataclass(frozen=True)
class CalibrationResult:
    """Full ColorChecker calibration output.

    Args:
        calibrated_image: Calibrated BGR image array.
        calibrated_png: PNG bytes for the calibrated image.
        overlay_png: PNG bytes for the warped sampling overlay.
        patch_points: Sampling points used in the warped preview.
        report: Full core report for backend diagnostics.
        display_summary: Compact metrics safe for the frontend.

    ``display_summary`` 是前端展示用的精简指标，不暴露完整高级报告。
    """

    calibrated_image: np.ndarray
    calibrated_png: bytes
    overlay_png: bytes
    patch_points: list[PointDict]
    report: dict[str, Any]
    display_summary: dict[str, Any]


def is_colorchecker_available() -> bool:
    """Return ``True`` when the local ColorChecker core imports correctly.

    返回本仓库内置 ColorChecker 核心是否可导入。
    """

    try:
        _import_core()
        return True
    except ImportError:
        return False


def decode_colorchecker_upload(
    raw: bytes,
    *,
    file_name: str = "",
    mime_type: str = "application/octet-stream",
) -> DecodedColorCheckerImage:
    """Decode an uploaded ColorChecker image as BGR.

    Args:
        raw: Uploaded file bytes.
        file_name: Original upload filename for RAW/type detection.
        mime_type: Upload MIME type.

    Returns:
        Decoded image and source label.

    上传图片在这里统一解码，避免把 RGB 图像误当成 BGR 传入校色核心。
    """

    try:
        core = _import_core()
        image_bgr, source_type = core.decode_uploaded_bytes(
            raw,
            file_name=file_name,
            mime_type=mime_type,
        )
    except ImportError as exc:
        raise ColorCheckerUnavailableError(
            "Local core.colorchecker package cannot be imported."
        ) from exc
    except ValueError as exc:
        raise ColorCheckerCalibrationError(str(exc)) from exc
    _validate_image(image_bgr)
    return DecodedColorCheckerImage(image_bgr=image_bgr, source_type=source_type)


def detect_colorchecker_chart(
    image_bgr: np.ndarray,
    *,
    patch_layout: str = "4x6",
    assist_point: PointInput | None = None,
) -> ChartDetectionResult:
    """Detect the ColorChecker card corners in a decoded image.

    Args:
        image_bgr: BGR image array.
        patch_layout: ``"4x6"`` or ``"3x8"``.
        assist_point: Optional user click used to bias detection.

    Returns:
        Detection result with original-image corner coordinates.

    自动定位图片中的 24 色卡四角；失败时返回原因，供前端提示用户手动调整。
    """

    _validate_image(image_bgr)
    core = _import_core_or_raise()
    try:
        from core.colorchecker.detection import detect_colorchecker_chart as _detect

        brand = core.get_brand(None)
        result = _detect(
            image_bgr,
            brand["patches"],
            patch_layout=_validate_patch_layout(patch_layout),
            assist_point=_to_point_dict(assist_point) if assist_point else None,
        )
    except (ValueError, TypeError, RuntimeError, KeyError) as exc:
        raise ColorCheckerCalibrationError(
            f"ColorChecker auto detection failed: {exc}"
        ) from exc

    payload = result.to_dict()
    return ChartDetectionResult(
        detected=bool(payload.get("detected")),
        corners=_normalize_response_points(payload.get("corners")),
        patch_orientation=str(payload.get("patchOrientation") or "normal"),
        confidence=float(payload.get("confidence") or 0.0),
        score=(
            None
            if payload.get("score") is None
            else float(payload.get("score"))
        ),
        mode=str(payload.get("mode") or "auto"),
        reason=str(payload.get("reason") or ""),
        candidate_count=int(payload.get("candidateCount") or 0),
    )


def warp_colorchecker_preview(
    image_bgr: np.ndarray,
    corner_points: Sequence[PointInput],
    patch_layout: str = "4x6",
) -> WarpPreviewResult:
    """Warp the ColorChecker region and return preview + sampling points.

    Args:
        image_bgr: BGR image array.
        corner_points: Four chart corners in original-image coordinates.
        patch_layout: ``"4x6"`` or ``"3x8"``.

    Returns:
        PNG preview and auto-generated 24 patch sampling points.

    这是 24 色卡校色的预览步骤，不会修改原图。
    """

    _validate_image(image_bgr)
    _validate_corners(corner_points)
    core = _import_core_or_raise()

    corners = _normalize_points(corner_points, expected_count=4, name="corner_points")
    pw = int(core.DEFAULT_PREVIEW_WIDTH)
    ph = int(core.DEFAULT_PREVIEW_HEIGHT)

    try:
        preview, _mask, _ordered = core.warp_colorchecker_preview(
            image_bgr,
            corners,
            pw,
            ph,
        )
        auto_points = core.generate_patch_points(
            pw,
            ph,
            patch_layout=_validate_patch_layout(patch_layout),
        )
    except (ValueError, TypeError, RuntimeError) as exc:
        raise ColorCheckerCalibrationError(
            f"Warp preview failed: {exc}"
        ) from exc

    log.info(
        "ColorChecker warp preview generated",
        extra={
            "event": "colorchecker_warp_preview_done",
            "preview_size": [pw, ph],
            "patch_count": len(auto_points),
        },
    )

    return WarpPreviewResult(
        preview_png=core.encode_png_bytes(preview),
        preview_width=pw,
        preview_height=ph,
        auto_patch_points=auto_points,
    )


def apply_colorchecker_calibration(
    image: np.ndarray | bytes | bytearray,
    corner_points: Sequence[PointInput],
    patch_points: Sequence[PointInput] | None = None,
    patch_layout: str = "4x6",
    *,
    file_name: str = "",
    mime_type: str = "application/octet-stream",
    input_color: Literal["bgr", "rgb"] = "bgr",
) -> CalibrationResult:
    """Compute ColorChecker calibration and apply it to the image.

    Args:
        image: BGR/RGB image array or original upload bytes.
        corner_points: Four chart corners in original-image coordinates.
        patch_points: Optional 24 sampling points in warped-preview
            coordinates. If omitted, the core generates them from
            ``patch_layout``.
        patch_layout: ``"4x6"`` or ``"3x8"``.
        file_name: Original filename when ``image`` is bytes.
        mime_type: MIME type when ``image`` is bytes.
        input_color: Channel order for ndarray inputs.

    Returns:
        Calibrated image, overlay, sampling points, full report, and compact
        frontend display summary.

    若传入上传原始字节，本函数会交给内置核心自行解码，避免通道顺序错误。
    """

    if isinstance(image, np.ndarray):
        _validate_image(image)
    _validate_corners(corner_points)
    core = _import_core_or_raise()

    corners = _normalize_points(corner_points, expected_count=4, name="corner_points")
    pp = (
        _normalize_points(patch_points, expected_count=24, name="patch_points")
        if patch_points is not None
        else None
    )

    try:
        result = core.calibrate(
            bytes(image) if isinstance(image, bytearray) else image,
            corners=corners,
            patch_points=pp,
            file_name=file_name,
            mime_type=mime_type,
            input_color=input_color,
            patch_layout=_validate_patch_layout(patch_layout),
        )
    except (ValueError, TypeError, RuntimeError, KeyError, np.linalg.LinAlgError) as exc:
        raise ColorCheckerCalibrationError(
            f"ColorChecker calibration failed: {exc}"
        ) from exc

    calibrated = result.calibrated_image
    if not isinstance(calibrated, np.ndarray):
        raise ColorCheckerCalibrationError(
            "Calibration did not return a valid image."
        )

    display_summary = build_display_summary(result.report)

    log.info(
        "ColorChecker calibration applied",
        extra={
            "event": "colorchecker_calibration_done",
            "output_shape": list(calibrated.shape),
            "patch_count": len(result.patch_points),
        },
    )

    return CalibrationResult(
        calibrated_image=calibrated,
        calibrated_png=result.calibrated_png,
        overlay_png=result.preview_overlay_png,
        patch_points=result.patch_points,
        report=result.report,
        display_summary=display_summary,
    )


def build_display_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Build compact frontend metrics from the full ColorChecker report.

    从完整校色报告中提取前端需要的平均、中位、P95、最差 DeltaE 与亮度曲线。
    """

    delta = _find_delta_e00_summary(report)
    patches = report.get("patches")
    patch_list = patches if isinstance(patches, list) else []
    worst_patch = _find_worst_patch(patch_list)
    luminance = report.get("luminance_diagnostics")
    luminance_curve = _extract_luminance_curve(
        luminance if isinstance(luminance, dict) else {}
    )
    return {
        "deltaE00": delta,
        "worstPatch": worst_patch,
        "luminanceCurve": luminance_curve,
        "warnings": list(report.get("warnings") or []),
    }


def _import_core():
    import core.colorchecker as colorchecker_core

    return colorchecker_core


def _import_core_or_raise():
    try:
        return _import_core()
    except ImportError as exc:
        raise ColorCheckerUnavailableError(
            "Local core.colorchecker package cannot be imported."
        ) from exc


def _validate_image(image_bgr: np.ndarray) -> None:
    if image_bgr.ndim != 3 or image_bgr.shape[2] < 3:
        raise ColorCheckerCalibrationError(
            "Image must have shape (H, W, 3) or (H, W, 4)."
        )


def _validate_corners(corner_points: Sequence[PointInput]) -> None:
    if len(corner_points) != 4:
        raise ColorCheckerCalibrationError(
            f"Exactly 4 corner points required, got {len(corner_points)}."
        )


def _validate_patch_layout(patch_layout: str) -> Literal["4x6", "3x8"]:
    if patch_layout not in {"4x6", "3x8"}:
        raise ColorCheckerCalibrationError(
            f"Unsupported patch_layout '{patch_layout}'."
        )
    return patch_layout  # type: ignore[return-value]


def _to_point_dict(point: PointInput) -> PointDict:
    if isinstance(point, dict):
        return {"x": float(point["x"]), "y": float(point["y"])}
    return {"x": float(point[0]), "y": float(point[1])}


def _normalize_points(
    points: Sequence[PointInput],
    *,
    expected_count: int,
    name: str,
) -> list[PointDict]:
    if len(points) != expected_count:
        raise ColorCheckerCalibrationError(
            f"{name} must contain exactly {expected_count} points, got {len(points)}."
        )
    return [_to_point_dict(point) for point in points]


def _normalize_response_points(raw: object) -> list[PointDict]:
    if not isinstance(raw, list):
        return []
    points: list[PointDict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if "x" not in item or "y" not in item:
            continue
        points.append({"x": float(item["x"]), "y": float(item["y"])})
    return points


def _find_delta_e00_summary(report: dict[str, Any]) -> dict[str, float | None]:
    fit_metrics = report.get("fit_metrics")
    if isinstance(fit_metrics, dict) and isinstance(fit_metrics.get("delta_e00"), dict):
        return _copy_metric_summary(fit_metrics["delta_e00"])
    stats = report.get("stats")
    if isinstance(stats, dict) and isinstance(stats.get("delta_e00"), dict):
        return _copy_metric_summary(stats["delta_e00"])
    if isinstance(stats, dict):
        return {
            "mean": _optional_float(stats.get("mean_delta_e")),
            "median": _optional_float(stats.get("median_delta_e")),
            "p95": _optional_float(stats.get("p95_delta_e")),
            "max": _optional_float(stats.get("max_delta_e")),
        }
    return {"mean": None, "median": None, "p95": None, "max": None}


def _copy_metric_summary(raw: dict[str, object]) -> dict[str, float | None]:
    return {
        "mean": _optional_float(raw.get("mean")),
        "median": _optional_float(raw.get("median")),
        "p95": _optional_float(raw.get("p95")),
        "max": _optional_float(raw.get("max")),
    }


def _find_worst_patch(patches: list[object]) -> dict[str, object] | None:
    best: dict[str, object] | None = None
    best_delta = float("-inf")
    for patch in patches:
        if not isinstance(patch, dict):
            continue
        value = _optional_float(patch.get("deltaE00"))
        if value is None or value <= best_delta:
            continue
        best_delta = value
        best = {
            "index": int(patch.get("index") or 0),
            "label": str(patch.get("label") or ""),
            "deltaE00": value,
            "referenceSrgb": patch.get("reference_sRGB"),
            "correctedSrgb": patch.get("corrected_sRGB"),
        }
    return best


def _extract_luminance_curve(luminance: dict[str, object]) -> list[dict[str, object]]:
    patches = luminance.get("patches")
    if not isinstance(patches, list):
        return []
    curve: list[dict[str, object]] = []
    for item in patches:
        if not isinstance(item, dict):
            continue
        curve.append(
            {
                "index": int(item.get("index") or 0),
                "label": str(item.get("label") or ""),
                "reference": _optional_float(item.get("reference_level")),
                "captured": _optional_float(item.get("captured_level")),
                "normalized": _optional_float(item.get("normalized_level")),
                "corrected": _optional_float(item.get("corrected_level")),
                "fitUsed": bool(item.get("fit_used")),
                "grayPatch": bool(item.get("is_gray_patch")),
            }
        )
    return curve


def _optional_float(value: object) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not np.isfinite(result):
        return None
    return result
