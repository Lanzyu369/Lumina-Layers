"""Fit the adopted Box model to paired measurements with a shared white reference.
使用共同白参考，将已采用的 Box 模型拟合到成对实测数据。
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import time

import numpy as np
from scipy.optimize import OptimizeResult, least_squares, minimize, nnls

from core.km_xyz import KMChannelFitDiagnostics, KMFitDiagnostics, _deterministic_fit_starts
from core.lumina_box_spectral import (
    BoxWhiteReference,
    LUMINA_BOX_REFERENCE_REFLECTANCE,
    LUMINA_BOX_REFERENCE_THICKNESS_MM,
    LUMINA_BOX_CONSTRAINED_OBJECTIVE_ID,
    LUMINA_BOX_DEFAULT_REFERENCE_MIN_REFLECTANCE,
    LuminaBoxModelError,
    LuminaBoxSpectralModel,
    SpectralMaterialParameters,
    validate_reference_reflectance_minimum,
)


class LuminaBoxFitError(RuntimeError):
    """No adopted-model fit converged. 已采用模型的拟合未收敛。"""


class LuminaBoxFitTimeout(TimeoutError):
    """The bounded material fit exceeded its time limit. 耗材拟合超过时间限制。"""


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


def _white_parameters(values: np.ndarray) -> SpectralMaterialParameters:
    # Compatibility for frozen five-value research inputs, never a fit constraint.
    if len(values) == 8:
        return SpectralMaterialParameters(values)
    return SpectralMaterialParameters(np.r_[np.full(4, values[0]), values[1:]])


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


def _curvature(values: np.ndarray, anchors: np.ndarray) -> np.ndarray:
    spacing = np.diff(anchors)
    return 2.0 * np.diff(np.diff(values) / spacing) / (spacing[1:] + spacing[:-1]) * 10000.0


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise LuminaBoxFitTimeout("Lumina Box material fitting exceeded its time limit")


def _spectral_parameter_bounds(coupling_maximum: float) -> tuple[np.ndarray, np.ndarray]:
    lower = np.r_[np.full(5, np.log(1e-10)), 0.0, 0.05, 0.0]
    upper = np.r_[np.full(5, np.log(1e3)), 4.0, 0.98, coupling_maximum]
    return lower, upper


def _fit_white(
    model: LuminaBoxSpectralModel, data: _PairedData, deadline: float,
    minimum_reflectance: float | None = None,
) -> tuple[OptimizeResult, int]:
    cmax = 0.98 / model.basis.diffuser(data.backing).max()
    low, high = _spectral_parameter_bounds(cmax)
    norm = 1.0 / np.sqrt(6 * len(data.thicknesses))

    def residual(values: np.ndarray) -> np.ndarray:
        _check_deadline(deadline)
        parameters = SpectralMaterialParameters(values)
        try:
            reference = model.reference_xyz(parameters, data.backing)
            pt, pr = model.observe(parameters, data.thicknesses, data.backing, reference)
        except LuminaBoxModelError:
            return np.full(6 * len(data.thicknesses) + 2, 1e3)
        return np.r_[
            (pt - data.transmission).ravel() / 0.02,
            (pr - data.reflection).ravel() / 0.02,
            0.05 * _curvature(values[:4], model.basis.anchors),
        ] * norm

    def physical_constraint(values: np.ndarray) -> float:
        _check_deadline(deadline)
        assert minimum_reflectance is not None
        reflection, _, _ = model.reference_energy_xyz(SpectralMaterialParameters(values))
        return float(reflection[1] - minimum_reflectance)

    def scalar_objective(values: np.ndarray) -> float:
        errors = residual(values)
        return float(errors @ errors / 2.0)

    best: OptimizeResult | None = None
    sequence = 0
    for strength in (0.5, 1.5, 4.0, 10.0):
        for forward in (0.2, 0.7, 0.95):
            for coupling in (min(0.5, 0.8 * cmax), min(2.0, 0.8 * cmax)):
                absorption = np.log((0.0001, 0.03, 0.3)[sequence % 3])
                slope = (0.0, 1.0, -1.0)[sequence % 3]
                start = np.r_[
                    absorption + slope * np.linspace(-1.5, 1.5, 4),
                    np.log(strength), 1.5, forward, coupling,
                ]
                sequence += 1
                if minimum_reflectance is None:
                    # Unconstrained runs are available only to private diagnostics.
                    fitted = least_squares(
                        residual, start, bounds=(low, high), loss="linear", x_scale="jac", max_nfev=700
                    )
                    feasible = True
                else:
                    fitted = minimize(
                        scalar_objective, start, method="SLSQP", bounds=list(zip(low, high, strict=True)),
                        constraints=[{"type": "ineq", "fun": physical_constraint}],
                        options={"maxiter": 500, "ftol": 1e-10},
                    )
                    fitted.cost = float(fitted.fun)
                    feasible = physical_constraint(fitted.x) >= -1e-7
                valid = fitted.success and feasible and np.isfinite(fitted.cost) and fitted.cost < 100.0
                if valid and (best is None or fitted.cost < best.cost):
                    best = fitted
                    # A practically exact forward reconstruction cannot benefit
                    # from the remaining multistarts. No noisy fit takes this path.
                    if best.cost < 1e-10:
                        return best, sequence
    if best is None:
        raise LuminaBoxFitError(
            "White measurements did not produce a converged fit within the known reflectance bound; "
            "retain the measurements and review the model/data conflict"
        )
    return best, sequence


def _fit_colour(
    model: LuminaBoxSpectralModel, data: _PairedData, reference: BoxWhiteReference,
    deadline: float, starts_count: int,
) -> tuple[OptimizeResult, int]:
    basis = model.basis
    absolute_backing = data.backing * reference.relative_xyz / LUMINA_BOX_REFERENCE_REFLECTANCE
    cmax = 1.0 / basis.diffuser(absolute_backing).max()
    interpolation = basis.interpolation(np.array([450.0, 550.0, 650.0]))
    seed = np.array([nnls(basis.weights @ interpolation, row)[0] for row in data.transmission])
    # Only the log-based initializer needs a floor; linear residuals retain measured zeros.
    starts = _deterministic_fit_starts(data.thicknesses, np.clip(seed, 1e-8, 1.0), cmax)
    low, high = _spectral_parameter_bounds(cmax)
    norm = 1.0 / np.sqrt(6 * len(data.thicknesses))

    def residual(values: np.ndarray) -> np.ndarray:
        _check_deadline(deadline)
        pt, pr = model.observe(
            SpectralMaterialParameters(values), data.thicknesses, data.backing, reference.relative_xyz
        )
        curvature = _curvature(values[:4], basis.anchors)
        return np.r_[
            (pt - data.transmission).ravel() / 0.02,
            (pr - data.reflection).ravel() / 0.02,
            0.05 * curvature,
        ] * norm

    best: OptimizeResult | None = None
    for sequence, index in enumerate(np.linspace(0, 95, starts_count, dtype=int)):
        values = starts[index][:6].reshape(3, 2)
        initial = np.r_[
            np.interp(basis.anchors, [450, 550, 650], values[:, 0]), values[:, 1].mean(),
            (0.0, 1.5, 3.0)[sequence % 3], (0.3, 0.6, 0.85, 0.95)[sequence % 4], starts[index][6],
        ]
        fitted = least_squares(
            residual, initial, bounds=(low, high), loss="linear", x_scale="jac", max_nfev=650
        )
        if fitted.success and np.isfinite(fitted.cost) and (best is None or fitted.cost < best.cost):
            best = fitted
    if best is None:
        raise LuminaBoxFitError("Material measurements did not produce a converged spectral fit")
    return best, starts_count


def _diagnostics(
    fitted: OptimizeResult, starts: int, data: _PairedData, pt: np.ndarray, pr: np.ndarray,
    *, is_reference_white: bool, white_reference: BoxWhiteReference,
) -> KMFitDiagnostics:
    jacobian = np.asarray(fitted.jac)
    condition = float(np.linalg.cond(jacobian)) if jacobian.ndim == 2 else float("nan")
    channels = tuple(
        KMChannelFitDiagnostics(
            name, float(np.sqrt(np.mean((pt[:, index] - data.transmission[:, index]) ** 2))),
            float(np.sqrt(np.mean((pr[:, index] - data.reflection[:, index]) ** 2))), (),
        )
        for index, name in enumerate(("X", "Y", "Z"))
    )
    return KMFitDiagnostics(
        success=True, message=str(fitted.message), nfev=int(fitted.nfev), start_count=starts,
        robust_objective=float(fitted.cost), jacobian_condition=condition if np.isfinite(condition) else None,
        measurement_thickness_offset_mm=0.0, warnings=(), channels=channels,
        objective_id=LUMINA_BOX_CONSTRAINED_OBJECTIVE_ID,
        objective_config={
            "loss": "linear", "pair_weighting": "equal_absolute_xyz", "xyz_residual_scale": 0.02,
            "absorption_curvature_weight": 0.05,
            "material_parameter_count": 8,
            "absorption_parameterization": "independent_wavelength_anchors",
            "reference_thickness_mm": LUMINA_BOX_REFERENCE_THICKNESS_MM,
            "reference_reflectance": LUMINA_BOX_REFERENCE_REFLECTANCE,
            "reference_min_total_reflectance_y": white_reference.minimum_total_reflectance_y,
            "transmission_diffuser_return": True, "fitted_thickness_offset": False,
        },
    )


def fit_lumina_box_spectral(
    thicknesses_mm: np.ndarray,
    transmittance_xyz: np.ndarray,
    reflectance_xyz: np.ndarray,
    measurement_backing_xyz: np.ndarray,
    *,
    white_reference: BoxWhiteReference | None = None,
    is_reference_white: bool = False,
    starts_count: int = 24,
    timeout_seconds: float = 180.0,
    reference_min_reflectance: float = LUMINA_BOX_DEFAULT_REFERENCE_MIN_REFLECTANCE,
) -> LuminaBoxSpectralFitResult:
    """Fit paired ratios with wavelength-dependent material absorption, including white.
    使用随波长变化的材料吸收拟合成对比值，白色耗材也采用同一参数形式。

    Args:
        thicknesses_mm: Increasing physical sample thicknesses.（递增实际样片厚度。）
        transmittance_xyz: T ratios in [0, 1], shape N by 3; measured zeros remain zero.
            （N 行三通道透射比值，范围 [0, 1]，保留实测零值。）
        reflectance_xyz: Normalized R ratios, shape N by 3.（N 行三通道反射比值。）
        measurement_backing_xyz: Instrument diffuser ratios.（仪器匀光板比值。）
        white_reference: Previously fitted reference for ordinary materials.
            （普通耗材使用的已拟合白参考。）
        is_reference_white: This material is the instrument's calibration white.
            （当前耗材就是仪器的白色校准材料。）
        starts_count: Deterministic color starts; white uses up to 24 and may
            stop after a practically exact reconstruction.
            （彩料确定性起点数；白参考最多二十四个，达到数值精确回算时可提前结束。）
        timeout_seconds: Bounded wall-clock fitting time.（拟合耗时上限。）
        reference_min_reflectance: Operator's known minimum total white
            reflectance Y; this is a bound, not an exact calibration value.
            （操作者已知的白片总反射率 Y 下限，不是精确校准真值。）

    Returns:
        Complete fitted model and reconstruction diagnostics.（完整模型及测量回算诊断。）
    """
    data = _paired_data(thicknesses_mm, transmittance_xyz, reflectance_xyz, measurement_backing_xyz)
    if not isinstance(is_reference_white, bool) or not isinstance(starts_count, int) or not 1 <= starts_count <= 96:
        raise LuminaBoxModelError("Invalid fitting role or deterministic start count")
    if not np.isfinite(timeout_seconds) or timeout_seconds <= 0.0:
        raise LuminaBoxModelError("Fit timeout must be positive")
    minimum = validate_reference_reflectance_minimum(reference_min_reflectance)
    if is_reference_white:
        if white_reference is not None:
            raise LuminaBoxModelError("A reference-white fit cannot use another white reference")
        if not np.any(np.isclose(data.thicknesses, LUMINA_BOX_REFERENCE_THICKNESS_MM, atol=1e-9, rtol=0)):
            raise LuminaBoxModelError("The calibration white must include its 3 mm paired measurement")
    elif white_reference is None:
        raise LuminaBoxModelError("Save the calibration white first, then select it for this material")
    model = LuminaBoxSpectralModel()
    deadline = time.monotonic() + timeout_seconds
    if is_reference_white:
        fitted, starts = _fit_white(model, data, deadline, minimum)
        parameters = SpectralMaterialParameters(fitted.x)
        q = model.reference_xyz(parameters, data.backing)
        white_reference = BoxWhiteReference(parameters, q, data.backing, data.fingerprint(), minimum)
    else:
        assert white_reference is not None
        model.validate_reference_physics(white_reference, require_constraint=True)
        fitted, starts = _fit_colour(model, data, white_reference, deadline, starts_count)
        parameters = SpectralMaterialParameters(fitted.x)
    pt, pr = model.observe(parameters, data.thicknesses, data.backing, white_reference.relative_xyz)
    effective_backing = (
        parameters.values[7] * data.backing * white_reference.relative_xyz / LUMINA_BOX_REFERENCE_REFLECTANCE
    )
    return LuminaBoxSpectralFitResult(
        parameters=parameters, white_reference=white_reference, is_reference_white=is_reference_white,
        predicted_transmittance_xyz=pt, predicted_reflectance_xyz=pr,
        measurement_backing_base_relative_xyz=data.backing.copy(),
        measurement_backing_scale=float(parameters.values[7]),
        measurement_backing_effective_relative_xyz=effective_backing,
        diagnostics=_diagnostics(
            fitted, starts, data, pt, pr, is_reference_white=is_reference_white,
            white_reference=white_reference,
        ),
    )
