"""ColorChecker calibration adapter.

Two-step integration with the ``colorchecker`` package:

1. **Warp preview** (:func:`warp_colorchecker_preview`) – perspective-warp
   the ColorChecker region and auto-generate 24 patch sampling points.
2. **Calibrate** (:func:`apply_colorchecker_calibration`) – compute the
   3x3 CCM from (possibly user-adjusted) patch points and return the
   calibrated full image plus an overlay preview.

If the ``colorchecker`` package is not installed, public functions raise
:class:`ColorCheckerUnavailableError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from api.structured_logging import get_logger

log = get_logger(__name__)


class ColorCheckerUnavailableError(RuntimeError):
    """Raised when the colorchecker package is not installed."""


class ColorCheckerCalibrationError(RuntimeError):
    """Raised when calibration fails for any reason."""


def is_colorchecker_available() -> bool:
    """Return True if the colorchecker package can be imported."""
    try:
        import colorchecker  # noqa: F401
        return True
    except ImportError:
        return False


def _ensure_import():
    try:
        import colorchecker  # noqa: F401
    except ImportError as exc:
        raise ColorCheckerUnavailableError(
            "colorchecker package is not installed. "
            "Install with: pip install -e <path-to-ColorChecker-repo>"
        ) from exc


def _validate_image(image_bgr: np.ndarray) -> None:
    if image_bgr.ndim != 3 or image_bgr.shape[2] < 3:
        raise ColorCheckerCalibrationError(
            "Image must have shape (H, W, 3) or (H, W, 4)."
        )


def _validate_corners(corner_points: Sequence[Sequence[float]]) -> None:
    if len(corner_points) != 4:
        raise ColorCheckerCalibrationError(
            f"Exactly 4 corner points required, got {len(corner_points)}."
        )


def _to_dicts(points: Sequence[Sequence[float]]) -> list[dict[str, float]]:
    return [{"x": float(pt[0]), "y": float(pt[1])} for pt in points]


@dataclass(frozen=True)
class WarpPreviewResult:
    """Result of the warp-preview step."""
    preview_png: bytes
    preview_width: int
    preview_height: int
    auto_patch_points: list[dict[str, float]]


@dataclass(frozen=True)
class CalibrationResult:
    """Result of the full calibration step."""
    calibrated_image: np.ndarray
    calibrated_png: bytes
    overlay_png: bytes
    patch_points: list[dict[str, float]]


def warp_colorchecker_preview(
    image_bgr: np.ndarray,
    corner_points: Sequence[Sequence[float]],
    patch_layout: str = "4x6",
) -> WarpPreviewResult:
    """Warp the ColorChecker region and return preview + auto patch points.

    Args:
        image_bgr: BGR uint8 image.
        corner_points: 4 corner points ``[[x,y], ...]``.
        patch_layout: ``"4x6"`` or ``"3x8"``.

    Returns:
        :class:`WarpPreviewResult` with the warped preview PNG and the
        auto-generated 24 patch sampling points (in preview coordinates).
    """
    _validate_image(image_bgr)
    _validate_corners(corner_points)
    _ensure_import()

    from colorchecker.api import (
        DEFAULT_PREVIEW_HEIGHT,
        DEFAULT_PREVIEW_WIDTH,
        encode_png_bytes,
        generate_patch_points,
        warp_colorchecker_preview as _warp,
    )

    corners = _to_dicts(corner_points)
    pw, ph = int(DEFAULT_PREVIEW_WIDTH), int(DEFAULT_PREVIEW_HEIGHT)

    try:
        preview, _mask, _ordered = _warp(image_bgr, corners, pw, ph)
    except Exception as exc:
        raise ColorCheckerCalibrationError(
            f"Warp preview failed: {exc}"
        ) from exc

    auto_points = generate_patch_points(pw, ph, patch_layout=patch_layout)

    log.info(
        "ColorChecker warp preview generated",
        extra={
            "event": "colorchecker_warp_preview_done",
            "preview_size": [pw, ph],
            "patch_count": len(auto_points),
        },
    )

    return WarpPreviewResult(
        preview_png=encode_png_bytes(preview),
        preview_width=pw,
        preview_height=ph,
        auto_patch_points=auto_points,
    )


def apply_colorchecker_calibration(
    image_bgr: np.ndarray,
    corner_points: Sequence[Sequence[float]],
    patch_points: Sequence[Sequence[float]] | None = None,
    patch_layout: str = "4x6",
) -> CalibrationResult:
    """Compute CCM and apply calibration to the full image.

    Args:
        image_bgr: BGR uint8 image.
        corner_points: 4 corner points of the ColorChecker.
        patch_points: Optional 24 patch sampling points in warp-preview
            coordinates. If ``None``, auto-generated from *patch_layout*.
        patch_layout: ``"4x6"`` or ``"3x8"`` (only used when
            *patch_points* is ``None``).

    Returns:
        :class:`CalibrationResult` with calibrated image, overlay PNG,
        and the patch points that were used.
    """
    _validate_image(image_bgr)
    _validate_corners(corner_points)
    _ensure_import()

    from colorchecker import calibrate

    corners = _to_dicts(corner_points)
    pp = _to_dicts(patch_points) if patch_points is not None else None

    try:
        result = calibrate(
            image_bgr,
            corners=corners,
            patch_points=pp,
            input_color="bgr",
            patch_layout=patch_layout,
        )
    except Exception as exc:
        raise ColorCheckerCalibrationError(
            f"ColorChecker calibration failed: {exc}"
        ) from exc

    calibrated = result.calibrated_image
    if not isinstance(calibrated, np.ndarray):
        raise ColorCheckerCalibrationError(
            "Calibration did not return a valid image."
        )

    log.info(
        "ColorChecker calibration applied",
        extra={
            "event": "colorchecker_calibration_done",
            "input_shape": list(image_bgr.shape),
            "output_shape": list(calibrated.shape),
        },
    )

    return CalibrationResult(
        calibrated_image=calibrated,
        calibrated_png=result.calibrated_png,
        overlay_png=result.preview_overlay_png,
        patch_points=result.patch_points,
    )
