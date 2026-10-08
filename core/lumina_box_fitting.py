"""Legacy spectral record types and integrity checks for archive compatibility.
兼容历史档案所需的光谱记录类型与完整性校验。
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

import numpy as np

from core.km_xyz import KMFitDiagnostics
from core.lumina_box_spectral import BoxWhiteReference, LuminaBoxModelError, SpectralMaterialParameters


@dataclass(frozen=True)
class LuminaBoxSpectralFitResult:
    """Spectral coefficients, normalized predictions, and a portable reference.
    波段系数、归一化预测以及可迁移白参考。
    """

    parameters: SpectralMaterialParameters
    white_reference: BoxWhiteReference
    is_reference_white: bool
    predicted_transmittance_xyz: np.ndarray
    predicted_reflectance_xyz: np.ndarray
    measurement_backing_base_relative_xyz: np.ndarray
    measurement_backing_scale: float
    measurement_backing_effective_relative_xyz: np.ndarray
    diagnostics: KMFitDiagnostics
    measurement_thickness_offset_mm: float = 0.0


@dataclass(frozen=True)
class _PairedData:
    thicknesses: np.ndarray
    transmission: np.ndarray
    reflection: np.ndarray
    backing: np.ndarray

    def fingerprint(self) -> str:
        content = {
            "thickness_mm": self.thicknesses.tolist(),
            "transmission": self.transmission.tolist(),
            "reflection": self.reflection.tolist(),
            "backing": self.backing.tolist(),
        }
        data = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _paired_data(
    thicknesses_mm: np.ndarray, transmission: np.ndarray, reflection: np.ndarray,
    backing: np.ndarray,
) -> _PairedData:
    try:
        d, t, r, g = [np.asarray(value, dtype=np.float64) for value in (
            thicknesses_mm, transmission, reflection, backing,
        )]
    except (TypeError, ValueError) as exc:
        raise LuminaBoxModelError("Paired Box measurements must contain finite numbers") from exc
    if (
        d.ndim != 1 or len(d) < 3 or t.shape != (len(d), 3) or r.shape != t.shape
        or g.shape != (3,) or not all(np.isfinite(value).all() for value in (d, t, r, g))
        or np.any(d <= 0.0) or np.any(np.diff(d) <= 0.0)
        or np.any(t < 0.0) or np.any(t > 1.0) or np.any(r < 0.0) or np.any(r > 1.0)
        or np.any(g <= 0.0) or np.any(g > 1.0)
    ):
        raise LuminaBoxModelError(
            "Box fitting requires at least three increasing positive thicknesses, "
            "paired T in [0, 1], R in [0, 1], and diffuser XYZ in (0, 1]"
        )
    return _PairedData(d, t, r, g)


def box_measurement_fingerprint(
    thicknesses_mm: np.ndarray, transmittance_xyz: np.ndarray,
    reflectance_xyz: np.ndarray, measurement_backing_xyz: np.ndarray,
) -> str:
    """Hash normalized raw observations independently of archive names and dates.
    对归一化原始读数计算校验值，不受档案名称和日期影响。

    Args:
        thicknesses_mm: Increasing thicknesses.（递增厚度。）
        transmittance_xyz: Transmission ratios.（透射比值。）
        reflectance_xyz: Reflection ratios.（反射比值。）
        measurement_backing_xyz: Diffuser ratios.（匀光板比值。）

    Returns:
        Stable SHA-256 measurement identity.（稳定的测量 SHA-256 标识。）
    """
    return _paired_data(thicknesses_mm, transmittance_xyz, reflectance_xyz, measurement_backing_xyz).fingerprint()
