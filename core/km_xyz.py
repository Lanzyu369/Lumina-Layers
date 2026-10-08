"""Effective XYZ Kubelka-Munk optics for Lumina Box material profiles.
Lumina Box 耗材档案使用的有效 XYZ Kubelka-Munk 光学模型。

The model treats the instrument-provided X, Y, and Z transmittance/reflectance
ratios as three independent effective two-flux channels.  It intentionally does
not consume white/black calibration readings: those readings are measurement
context, while inputs to this module are already normalized ratios.

Recipes use the project's canonical bottom-to-top print order.  The optical
recurrence therefore starts at the backing and adds each recipe layer above the
current stack.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.optimize import least_squares

from core.colorchecker.color_metrics import (
    linear_to_srgb,
    linear_srgb_to_xyz,
    xyz_to_linear_srgb,
)
from core.errors import CoreValidationError


KM_XYZ_MODEL_ID = "km_xyz/v1"
KM_XYZ_MEASUREMENT_PROTOCOL_ID = "lumina_box_xyz_paired_diffuser_km/v2"
KM_XYZ_FIT_OBJECTIVE_ID = (
    "km_xyz_paired_linear_tr_diffuser_offset_soft_l1/v3"
)
KM_XYZ_COLOR_BRIDGE_ID = "d65_10_to_d65_2_diagonal/v1"
KM_XYZ_ILLUMINANT = "D65"
KM_XYZ_OBSERVER = "CIE 1964 10deg"
KM_XYZ_MEASUREMENT_GEOMETRY = "45:0"
KM_XYZ_MEASUREMENT_REFLECTION_BOUNDARY_ID = "instrument_diffuser_scaled/v1"
KM_XYZ_MEASUREMENT_THICKNESS_OFFSET_MAX_MM = 0.4
KM_XYZ_VALUE_SCALE = "0..1"

# CIE standard illuminant D65 tristimulus values, normalized to Y = 1.
D65_2_WHITE_XYZ = np.array([0.95047, 1.0, 1.08883], dtype=np.float64)
D65_10_WHITE_XYZ = np.array([0.94811, 1.0, 1.07304], dtype=np.float64)

_CHANNEL_NAMES = ("X", "Y", "Z")
_FIT_PARAMETER_MIN = 1.0e-10
_FIT_PARAMETER_MAX = 1.0e4
_FIT_TRANSMITTANCE_SCALE = 0.02
_FIT_REFLECTANCE_SCALE = 0.02
_FIT_START_COUNT = 96
_FIT_MAX_NFEV = 1500
_FIT_BACKING_SCALE_BOUND_FRACTION = 0.01
_FIT_THICKNESS_OFFSET_BOUND_FRACTION = 0.01
_LAB_DELTA = 6.0 / 29.0
_LAB_DELTA_CUBED = _LAB_DELTA**3
_LAB_LINEAR_SCALE = 1.0 / (3.0 * _LAB_DELTA**2)


class KMValidationError(CoreValidationError):
    """Raised when KM-XYZ inputs violate the public data contract.
    当 KM-XYZ 输入不满足公开数据约定时抛出。
    """


class KMFitError(RuntimeError):
    """Raised when no deterministic fitting start produces a finite result.
    当全部确定性拟合起点都无法产生有限结果时抛出。
    """


@dataclass(frozen=True)
class KMXYZParameters:
    """Per-channel Kubelka-Munk coefficients in inverse millimetres.
    XYZ 三通道的 Kubelka-Munk 系数，单位为每毫米。

    Attributes:
        K: Effective absorption coefficients ``(K_X, K_Y, K_Z)`` in mm^-1.
            （有效吸收系数，单位 mm^-1）
        S: Effective scattering coefficients ``(S_X, S_Y, S_Z)`` in mm^-1.
            （有效散射系数，单位 mm^-1）
    """

    K: np.ndarray
    S: np.ndarray

    def __post_init__(self) -> None:
        absorption = _validated_xyz_vector(self.K, "K", lower=0.0)
        scattering = _validated_xyz_vector(self.S, "S", lower=0.0)
        object.__setattr__(self, "K", absorption.copy())
        object.__setattr__(self, "S", scattering.copy())


@dataclass(frozen=True)
class KMChannelFitDiagnostics:
    """Per-channel quality metrics from the joint XYZ/backing fit.
    XYZ 与匀光板联合拟合中的逐通道质量指标。
    """

    channel: str
    transmittance_rmse: float
    reflectance_rmse: float
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class KMFitDiagnostics:
    """Aggregate diagnostics for a joint XYZ/backing Kubelka-Munk fit.
    XYZ 与匀光板 Kubelka-Munk 联合拟合的汇总诊断。
    """

    success: bool
    message: str
    nfev: int
    start_count: int
    robust_objective: float
    jacobian_condition: float | None
    measurement_thickness_offset_mm: float
    warnings: tuple[str, ...]
    channels: tuple[KMChannelFitDiagnostics, ...]
    objective_id: str
    objective_config: dict[str, object]


@dataclass(frozen=True)
class KMXYZFitResult:
    """Fitted runtime K/S, acquisition backing, predictions, and diagnostics.
    单种耗材的运行时 K/S、采集匀光板、预测值与诊断信息。
    """

    parameters: KMXYZParameters
    predicted_transmittance_xyz: np.ndarray
    predicted_reflectance_xyz: np.ndarray
    measurement_backing_base_relative_xyz: np.ndarray
    measurement_backing_scale: float
    measurement_backing_effective_relative_xyz: np.ndarray
    measurement_thickness_offset_mm: float
    diagnostics: KMFitDiagnostics


def _as_finite_array(value: object, name: str) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise KMValidationError(f"{name} must contain numeric values") from exc
    if not np.all(np.isfinite(array)):
        raise KMValidationError(f"{name} must contain only finite values")
    return array


def _validated_xyz_vector(
    value: object,
    name: str,
    *,
    lower: float | None = None,
    upper: float | None = None,
) -> np.ndarray:
    array = _as_finite_array(value, name)
    if array.shape != (3,):
        raise KMValidationError(f"{name} must have shape (3,)")
    if lower is not None and np.any(array < lower):
        raise KMValidationError(f"{name} values must be >= {lower}")
    if upper is not None and np.any(array > upper):
        raise KMValidationError(f"{name} values must be <= {upper}")
    return array


def km_layer_rt(
    absorption_k: float | np.ndarray,
    scattering_s: float | np.ndarray,
    thickness_mm: float | np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return intrinsic reflectance and transmittance of one KM layer.
    返回单层 KM 材料的本征反射率与透射率。

    The implementation evaluates the finite-thickness two-flux solution with
    non-negative ``K`` and ``S``.  An ``expm1`` form avoids cancellation for
    optically thin layers, while explicit pure-scattering limits avoid the
    otherwise singular ``K = 0`` case.

    Args:
        absorption_k: Absorption coefficient(s), in mm^-1.（吸收系数）
        scattering_s: Scattering coefficient(s), in mm^-1.（散射系数）
        thickness_mm: Physical layer thickness, in mm.（物理厚度）

    Returns:
        ``(reflectance, transmittance)`` arrays with broadcast input shape.
        （广播后形状一致的反射率与透射率数组）

    Raises:
        KMValidationError: If an input is non-finite or negative.
            （输入非有限或为负数）
    """
    absorption = _as_finite_array(absorption_k, "absorption_k")
    scattering = _as_finite_array(scattering_s, "scattering_s")
    thickness = _as_finite_array(thickness_mm, "thickness_mm")
    try:
        absorption, scattering, thickness = np.broadcast_arrays(
            absorption,
            scattering,
            thickness,
        )
    except ValueError as exc:
        raise KMValidationError(
            "absorption_k, scattering_s, and thickness_mm must be broadcast-compatible"
        ) from exc
    if np.any(absorption < 0.0):
        raise KMValidationError("absorption_k values must be non-negative")
    if np.any(scattering < 0.0):
        raise KMValidationError("scattering_s values must be non-negative")
    if np.any(thickness < 0.0):
        raise KMValidationError("thickness_mm values must be non-negative")

    reflectance = np.empty(absorption.shape, dtype=np.float64)
    transmittance = np.empty(absorption.shape, dtype=np.float64)
    pure_scattering = absorption == 0.0

    if np.any(pure_scattering):
        with np.errstate(over="ignore", invalid="ignore"):
            optical_depth = scattering[pure_scattering] * thickness[pure_scattering]
        inverse_scale = np.divide(
            1.0,
            optical_depth,
            out=np.full_like(optical_depth, np.inf),
            where=optical_depth != 0.0,
        )
        large_depth = optical_depth > 1.0
        pure_r = np.empty_like(optical_depth)
        pure_t = np.empty_like(optical_depth)
        pure_r[~large_depth] = optical_depth[~large_depth] / (
            1.0 + optical_depth[~large_depth]
        )
        pure_t[~large_depth] = 1.0 / (1.0 + optical_depth[~large_depth])
        pure_r[large_depth] = 1.0 / (1.0 + inverse_scale[large_depth])
        pure_t[large_depth] = inverse_scale[large_depth] / (
            1.0 + inverse_scale[large_depth]
        )
        reflectance[pure_scattering] = pure_r
        transmittance[pure_scattering] = pure_t

    regular = ~pure_scattering
    if np.any(regular):
        k = absorption[regular]
        s = scattering[regular]
        d = thickness[regular]
        # Normalize K/S before evaluating sqrt(K * (K + 2S)).  This keeps the
        # ratio terms finite even when valid inputs are close to float limits.
        coefficient_scale = np.maximum(k, s)
        normalized_k = k / coefficient_scale
        normalized_s = s / coefficient_scale
        # Evaluate gamma / scale as
        # sqrt(K) / sqrt(scale) * sqrt((K + 2S) / scale).  Computing the
        # mathematically equivalent K / scale product first can underflow to
        # zero for a valid pair such as K=1e-300, S=1e300, even though the
        # physical attenuation gamma=sqrt(K*(K+2S)) is finite.
        normalized_sum = normalized_k + 2.0 * normalized_s
        sqrt_k = np.sqrt(k)
        sqrt_scale = np.sqrt(coefficient_scale)
        normalized_attenuation = (
            sqrt_k / sqrt_scale * np.sqrt(normalized_sum)
        )
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            attenuation = sqrt_k * sqrt_scale * np.sqrt(normalized_sum)
            optical_depth = attenuation * d
            optical_depth = np.where(d == 0.0, 0.0, optical_depth)
            exp_minus_depth = np.exp(-optical_depth)
            one_minus_exp_twice = -np.expm1(-2.0 * optical_depth)
        one_plus_exp_twice = 2.0 - one_minus_exp_twice
        denominator = (
            normalized_attenuation * one_plus_exp_twice
            + (normalized_k + normalized_s) * one_minus_exp_twice
        )
        reflectance[regular] = (
            normalized_s * one_minus_exp_twice / denominator
        )
        transmittance[regular] = (
            2.0 * normalized_attenuation * exp_minus_depth / denominator
        )

    return reflectance, transmittance


def km_stack_reflectance(
    absorption_k: np.ndarray,
    scattering_s: np.ndarray,
    thickness_mm: float | Iterable[float] | np.ndarray,
    substrate_reflectance_xyz: np.ndarray,
) -> np.ndarray:
    """Compose a bottom-to-top KM recipe above an optical backing.
    在给定光学底边界上按“底层到顶层”顺序组合 KM 配方。

    Each row of ``absorption_k``/``scattering_s`` is one XYZ layer.  Row zero
    is the printed bottom layer; the last row is the viewing-side top layer.
    For example, a two-row input ``[blue, yellow]`` represents blue below
    yellow.  The recurrence adds each new row above the current stack.

    Args:
        absorption_k: ``(N, 3)`` absorption coefficients in mm^-1.
            （N 层 XYZ 吸收系数）
        scattering_s: ``(N, 3)`` scattering coefficients in mm^-1.
            （N 层 XYZ 散射系数）
        thickness_mm: One common thickness or ``(N,)`` per-layer thicknesses.
            （统一层厚或逐层厚度）
        substrate_reflectance_xyz: ``(3,)`` optical backing response in [0, 1].
            （光学底边界响应）

    Returns:
        ``(3,)`` effective XYZ reflectance viewed from the top.
        （从顶面观察的有效 XYZ 反射率）
    """
    absorption = _as_finite_array(absorption_k, "absorption_k")
    scattering = _as_finite_array(scattering_s, "scattering_s")
    if absorption.ndim != 2 or absorption.shape[1] != 3:
        raise KMValidationError("absorption_k must have shape (N, 3)")
    if scattering.shape != absorption.shape:
        raise KMValidationError("scattering_s must match absorption_k shape")
    if np.any(absorption < 0.0) or np.any(scattering < 0.0):
        raise KMValidationError("K and S coefficients must be non-negative")

    layer_count = absorption.shape[0]
    thickness = _as_finite_array(thickness_mm, "thickness_mm")
    if thickness.ndim == 0:
        thickness = np.full(layer_count, float(thickness), dtype=np.float64)
    elif thickness.shape != (layer_count,):
        raise KMValidationError("thickness_mm must be scalar or have shape (N,)")
    if np.any(thickness < 0.0):
        raise KMValidationError("thickness_mm values must be non-negative")

    current = _validated_xyz_vector(
        substrate_reflectance_xyz,
        "substrate_reflectance_xyz",
        lower=0.0,
        upper=1.0,
    ).copy()
    for layer_index in range(layer_count):
        layer_r, layer_t = km_layer_rt(
            absorption[layer_index],
            scattering[layer_index],
            thickness[layer_index],
        )
        denominator = 1.0 - layer_r * current
        # A positive denominator remains usable even when it is at machine
        # precision.  In particular, a highly scattering conservative layer
        # above a white backing has 1-rR ~= t and converges exactly to R=1.
        # Treat only the rounded 0/0 endpoint as the saturated limit.
        regular = denominator > 0.0
        saturated_limit = (
            ~regular
            & (layer_r >= 1.0 - np.finfo(np.float64).eps)
            & (current >= 1.0 - np.finfo(np.float64).eps)
        )
        if (
            np.any(~regular & ~saturated_limit)
            or not np.all(np.isfinite(denominator))
        ):
            raise KMValidationError(
                "KM stack recurrence reached a singular optical boundary"
            )
        next_reflectance = layer_r.copy()
        next_reflectance[regular] += (
            layer_t[regular] * layer_t[regular] * current[regular]
        ) / denominator[regular]
        next_reflectance[saturated_limit] = 1.0
        current = next_reflectance
    return current


def relative_xyz_to_effective_d65_10(relative_xyz: np.ndarray) -> np.ndarray:
    """Scale relative KM responses to effective D65/CIE 1964 10° XYZ.
    将相对 KM 响应缩放为有效 D65/CIE 1964 10° XYZ。
    """
    values = _validated_xyz_last_axis(relative_xyz, "relative_xyz")
    return values * D65_10_WHITE_XYZ


def effective_d65_10_to_relative_xyz(effective_xyz: np.ndarray) -> np.ndarray:
    """Convert effective D65/10° XYZ to relative KM channel responses.
    将有效 D65/10° XYZ 转换为相对 KM 通道响应。
    """
    values = _validated_xyz_last_axis(effective_xyz, "effective_xyz")
    return values / D65_10_WHITE_XYZ


def xyz_d65_2_to_effective_d65_10(xyz_d65_2: np.ndarray) -> np.ndarray:
    """Apply the versioned diagonal D65 2° to effective D65 10° bridge.
    应用版本化的 D65 2° 到有效 D65 10° 对角白点桥接。
    """
    values = _validated_xyz_last_axis(xyz_d65_2, "xyz_d65_2")
    return values * (D65_10_WHITE_XYZ / D65_2_WHITE_XYZ)


def effective_d65_10_to_xyz_d65_2(effective_xyz: np.ndarray) -> np.ndarray:
    """Apply the inverse effective D65 10° to D65 2° white-point bridge.
    应用有效 D65 10° 到 D65 2° 的反向白点桥接。
    """
    values = _validated_xyz_last_axis(effective_xyz, "effective_xyz")
    return values * (D65_2_WHITE_XYZ / D65_10_WHITE_XYZ)


def linear_srgb_to_km_relative_xyz(linear_rgb: np.ndarray) -> np.ndarray:
    """Map linear sRGB into the effective relative XYZ matching space.
    将线性 sRGB 映射到有效相对 XYZ 匹配空间。

    Values are not clipped; callers retain control over gamut policy.
    （不执行裁切，色域策略由调用方决定）
    """
    values = _validated_xyz_last_axis(linear_rgb, "linear_rgb")
    xyz_d65_2 = linear_srgb_to_xyz(values)
    effective_xyz = xyz_d65_2_to_effective_d65_10(xyz_d65_2)
    return effective_d65_10_to_relative_xyz(effective_xyz)


def km_relative_xyz_to_linear_srgb(relative_xyz: np.ndarray) -> np.ndarray:
    """Map relative KM XYZ responses into un-clipped linear sRGB.
    将相对 KM XYZ 响应映射为未裁切的线性 sRGB。
    """
    effective_xyz = relative_xyz_to_effective_d65_10(relative_xyz)
    xyz_d65_2 = effective_d65_10_to_xyz_d65_2(effective_xyz)
    return xyz_to_linear_srgb(xyz_d65_2)


def km_relative_xyz_to_lab(relative_xyz: np.ndarray) -> np.ndarray:
    """Convert relative KM XYZ responses to Lab under D65/CIE 1964 10°.
    将相对 KM XYZ 响应转换为 D65/CIE 1964 10° 下的 Lab。
    """
    effective_xyz = relative_xyz_to_effective_d65_10(relative_xyz)
    normalized = effective_xyz / D65_10_WHITE_XYZ
    f = np.where(
        normalized > _LAB_DELTA_CUBED,
        np.cbrt(np.maximum(normalized, 0.0)),
        normalized * _LAB_LINEAR_SCALE + 4.0 / 29.0,
    )
    lightness = 116.0 * f[..., 1] - 16.0
    a_axis = 500.0 * (f[..., 0] - f[..., 1])
    b_axis = 200.0 * (f[..., 1] - f[..., 2])
    return np.stack([lightness, a_axis, b_axis], axis=-1)


def km_relative_xyz_to_srgb_uint8(relative_xyz: np.ndarray) -> np.ndarray:
    """Convert relative KM XYZ responses to clipped display sRGB uint8.
    将相对 KM XYZ 响应转换为经裁切的显示用 sRGB uint8。

    This is the explicitly lossy display endpoint; optical and matching code
    should retain float XYZ/Lab values instead.（这是明确有损的显示端点；光学
    与匹配逻辑应继续保留浮点 XYZ/Lab。）
    """
    linear_rgb = km_relative_xyz_to_linear_srgb(relative_xyz)
    srgb = linear_to_srgb(np.clip(linear_rgb, 0.0, 1.0))
    return np.rint(np.clip(srgb, 0.0, 1.0) * 255.0).astype(np.uint8)


def _validated_xyz_last_axis(value: object, name: str) -> np.ndarray:
    values = _as_finite_array(value, name)
    if values.ndim == 0 or values.shape[-1] != 3:
        raise KMValidationError(f"{name} must have a final dimension of 3")
    return values


def _unpack_joint_fit_parameters(
    fit_parameters: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    optical_parameters = np.exp(fit_parameters[:6]).reshape(3, 2)
    return (
        optical_parameters[:, 0],
        optical_parameters[:, 1],
        float(fit_parameters[6]),
        float(fit_parameters[7]),
    )


def _predict_paired_measurements(
    fit_parameters: np.ndarray,
    thicknesses_mm: np.ndarray,
    measurement_backing_base_xyz: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Predict linear T and diffuser-backed R for the joint eight-parameter fit."""
    (
        absorption,
        scattering,
        backing_scale,
        thickness_offset,
    ) = _unpack_joint_fit_parameters(fit_parameters)
    with np.errstate(over="ignore", invalid="ignore"):
        effective_thicknesses = thicknesses_mm + thickness_offset
    if not np.all(np.isfinite(effective_thicknesses)):
        raise FloatingPointError(
            "measurement thickness plus acquisition offset must remain finite"
        )
    intrinsic_reflectance, transmittance = km_layer_rt(
        absorption[np.newaxis, :],
        scattering[np.newaxis, :],
        effective_thicknesses[:, np.newaxis],
    )
    backing_reflectance = measurement_backing_base_xyz * backing_scale
    denominator = 1.0 - intrinsic_reflectance * backing_reflectance
    measured_reflectance = np.empty_like(intrinsic_reflectance)
    regular = denominator > 0.0
    measured_reflectance[regular] = intrinsic_reflectance[regular] + (
        transmittance[regular] ** 2
        * np.broadcast_to(backing_reflectance, denominator.shape)[regular]
        / denominator[regular]
    )
    saturated = (
        ~regular
        & (intrinsic_reflectance >= 1.0 - np.finfo(np.float64).eps)
        & (
            np.broadcast_to(backing_reflectance, denominator.shape)
            >= 1.0 - np.finfo(np.float64).eps
        )
    )
    if np.any(~regular & ~saturated) or not np.all(np.isfinite(denominator)):
        raise FloatingPointError(
            "diffuser-backed KM reflection reached a singular optical boundary"
        )
    measured_reflectance[saturated] = 1.0
    return transmittance, measured_reflectance


def _fit_residuals(
    fit_parameters: np.ndarray,
    thicknesses_mm: np.ndarray,
    observed_transmittance: np.ndarray,
    observed_reflectance: np.ndarray,
    measurement_backing_base_xyz: np.ndarray,
) -> np.ndarray:
    predicted_transmittance, predicted_reflectance = _predict_paired_measurements(
        fit_parameters,
        thicknesses_mm,
        measurement_backing_base_xyz,
    )
    transmission_residuals = (
        predicted_transmittance - observed_transmittance
    ) / _FIT_TRANSMITTANCE_SCALE
    reflection_residuals = (
        predicted_reflectance - observed_reflectance
    ) / _FIT_REFLECTANCE_SCALE
    pair_normalization = np.sqrt(6.0 * float(thicknesses_mm.size))
    return np.concatenate(
        [transmission_residuals.ravel(), reflection_residuals.ravel()]
    ) / pair_normalization


def _deterministic_fit_starts(
    thicknesses_mm: np.ndarray,
    observed_transmittance: np.ndarray,
    backing_scale_max: float,
) -> tuple[np.ndarray, ...]:
    apparent_attenuation = -np.log(observed_transmittance) / thicknesses_mm[:, None]
    channel_scales: list[float] = []
    for channel_index in range(3):
        channel_attenuation = apparent_attenuation[:, channel_index]
        positive = channel_attenuation[
            np.isfinite(channel_attenuation) & (channel_attenuation > 0.0)
        ]
        if positive.size:
            scale = float(np.median(positive))
        else:
            scale = 1.0 / float(np.max(thicknesses_mm))
        channel_scales.append(float(np.clip(scale, 1.0e-4, 1.0e3)))
    ratios = (
        (1.0, 0.01),
        (1.0, 0.1),
        (1.0, 1.0),
        (0.3, 3.0),
        (0.1, 10.0),
        (3.0, 0.1),
        (0.03, 30.0),
        (10.0, 0.03),
    )
    backing_scale_fractions = (0.05, 0.2, 0.4, 0.6, 0.8, 0.95)
    thickness_offset_seeds_mm = (0.0, 0.04, 0.12, 0.24)
    starts: list[np.ndarray] = []
    base_start_index = 0
    for multiplier in (0.25, 1.0, 4.0):
        for k_ratio, s_ratio in ratios:
            optical_parameters = np.clip(
                [
                    [scale * multiplier * k_ratio, scale * multiplier * s_ratio]
                    for scale in channel_scales
                ],
                _FIT_PARAMETER_MIN * 10.0,
                _FIT_PARAMETER_MAX / 10.0,
            )
            backing_fraction = backing_scale_fractions[
                base_start_index % len(backing_scale_fractions)
            ]
            for thickness_offset in thickness_offset_seeds_mm:
                starts.append(
                    np.concatenate(
                        [
                            np.log(optical_parameters).ravel(),
                            [
                                backing_fraction * backing_scale_max,
                                thickness_offset,
                            ],
                        ]
                    )
                )
            base_start_index += 1
    if len(starts) != _FIT_START_COUNT:
        raise AssertionError("deterministic KM start grid must contain 96 starts")
    return tuple(starts)


def _fit_objective_config(
    sample_count: int,
    measurement_backing_base_xyz: np.ndarray,
    backing_scale_max: float,
) -> dict[str, object]:
    residual_normalization = 1.0 / np.sqrt(6.0 * float(sample_count))
    return {
        "transmittance_residual": "linear",
        "reflectance_residual": "linear_diffuser_backed",
        "transmittance_scale": _FIT_TRANSMITTANCE_SCALE,
        "reflectance_scale": _FIT_REFLECTANCE_SCALE,
        "modality_weights": {
            "transmittance": 0.5,
            "reflectance": 0.5,
        },
        "pair_weighting": "equal",
        "residual_normalization": float(residual_normalization),
        "loss": "soft_l1",
        "f_scale": float(residual_normalization),
        "measurement_backing": {
            "model": "shared_scaled_diffuser",
            "reflection_boundary_id": (
                KM_XYZ_MEASUREMENT_REFLECTION_BOUNDARY_ID
            ),
            "base_relative_xyz": measurement_backing_base_xyz.tolist(),
            "scale_bounds": [
                0.0,
                backing_scale_max,
            ],
            "scale_near_bound_fraction": _FIT_BACKING_SCALE_BOUND_FRACTION,
            "effective_relative_formula": "scale_times_base_relative",
        },
        "measurement_thickness": {
            "model": "shared_nonnegative_acquisition_offset",
            "effective_formula": "thickness_mm_plus_offset_mm",
            "offset_bounds_mm": [
                0.0,
                KM_XYZ_MEASUREMENT_THICKNESS_OFFSET_MAX_MM,
            ],
            "offset_near_bound_fraction": (
                _FIT_THICKNESS_OFFSET_BOUND_FRACTION
            ),
        },
        "solver": {
            "parameterization": (
                "log_k_log_s_direct_backing_scale_direct_thickness_offset"
            ),
            "optical_parameter_bounds": [
                _FIT_PARAMETER_MIN,
                _FIT_PARAMETER_MAX,
            ],
            "method": "trf",
            "x_scale": "jac",
            "max_nfev": _FIT_MAX_NFEV,
            "start_count": _FIT_START_COUNT,
        },
    }


def _jacobian_condition(jacobian: np.ndarray) -> float | None:
    if jacobian.ndim != 2 or jacobian.shape[1] == 0:
        return None
    singular_values = np.linalg.svd(jacobian, compute_uv=False)
    if singular_values.size < 2 or not np.all(np.isfinite(singular_values)):
        return None
    if singular_values[-1] <= np.finfo(np.float64).eps * singular_values[0]:
        return float("inf")
    return float(singular_values[0] / singular_values[-1])


def _run_joint_fit(
    thicknesses_mm: np.ndarray,
    observed_transmittance: np.ndarray,
    observed_reflectance: np.ndarray,
    measurement_backing_base_xyz: np.ndarray,
    backing_scale_max: float,
) -> tuple[object, float, int, np.ndarray, np.ndarray]:
    lower_bounds = np.concatenate(
        [np.full(6, np.log(_FIT_PARAMETER_MIN)), [0.0, 0.0]]
    )
    upper_bounds = np.concatenate(
        [
            np.full(6, np.log(_FIT_PARAMETER_MAX)),
            [
                backing_scale_max,
                KM_XYZ_MEASUREMENT_THICKNESS_OFFSET_MAX_MM,
            ],
        ]
    )
    best_result = None
    best_robust_objective = float("inf")
    failures: list[str] = []
    residual_normalization = 1.0 / np.sqrt(6.0 * float(thicknesses_mm.size))
    starts = _deterministic_fit_starts(
        thicknesses_mm,
        observed_transmittance,
        backing_scale_max,
    )

    for start in starts:
        try:
            result = least_squares(
                _fit_residuals,
                start,
                bounds=(lower_bounds, upper_bounds),
                args=(
                    thicknesses_mm,
                    observed_transmittance,
                    observed_reflectance,
                    measurement_backing_base_xyz,
                ),
                method="trf",
                loss="soft_l1",
                f_scale=residual_normalization,
                x_scale="jac",
                max_nfev=_FIT_MAX_NFEV,
            )
        except (FloatingPointError, KMValidationError, ValueError) as exc:
            failures.append(str(exc))
            continue
        if (
            not np.all(np.isfinite(result.x))
            or not np.all(np.isfinite(result.fun))
            or not np.isfinite(result.cost)
        ):
            continue
        robust_objective = float(result.cost)
        if robust_objective < best_robust_objective:
            best_robust_objective = robust_objective
            best_result = result

    if best_result is None:
        detail = f": {failures[-1]}" if failures else ""
        raise KMFitError(f"joint KM fit failed{detail}")
    return (
        best_result,
        best_robust_objective,
        len(starts),
        lower_bounds,
        upper_bounds,
    )


def fit_paired_km_xyz(
    thicknesses_mm: Iterable[float] | np.ndarray,
    transmittance_xyz: np.ndarray,
    reflectance_xyz: np.ndarray,
    measurement_backing_base_xyz: np.ndarray,
) -> KMXYZFitResult:
    """Jointly fit XYZ KM coefficients and shared acquisition nuisances.
    联合拟合 XYZ KM 系数与共享采集干扰参数。

    The transmittance and reflectance inputs are the instrument's already
    normalized 0..1 ratios.  White and black reference XYZ readings must not be
    applied again.  Reflection is modeled above an instrument-provided diffuser
    base ``Rg = c * base``.  The model also fits one non-negative acquisition
    thickness offset ``d0`` and predicts measurements at ``d + d0``.  The
    shared ``c`` and ``d0`` nuisances are not part of runtime K/S or layer
    stacking.  Linear T and R modalities receive equal total objective weight.

    Args:
        thicknesses_mm: ``(N,)`` positive, unique paired-sample thicknesses.
            （N 个互不重复的成对样品正厚度，单位 mm）
        transmittance_xyz: ``(N, 3)`` XYZ transmittance ratios in (0, 1].
            （XYZ 透过率）
        reflectance_xyz: ``(N, 3)`` paired diffuser-backed XYZ reflectance ratios
            in [0, 1].（逐厚度配对的 XYZ 反射率）
        measurement_backing_base_xyz: Instrument diffuser base, normalized
            ``(3,)`` with every value in (0, 1].（仪器匀光板归一化 XYZ 基准。）

    Returns:
        Fitted K/S parameters, predictions at every measured thickness, and
        convergence/quality diagnostics.（参数、逐点预测和拟合诊断）

    Raises:
        KMValidationError: If shapes, ranges, or thicknesses are invalid.
            （形状、范围或厚度非法）
        KMFitError: If no deterministic start produces a finite fit.
            （所有确定性起点都无法得到有限拟合结果）
    """
    thicknesses = _as_finite_array(thicknesses_mm, "thicknesses_mm")
    if thicknesses.ndim != 1:
        raise KMValidationError("thicknesses_mm must have shape (N,)")
    if thicknesses.size < 3:
        raise KMValidationError("at least three paired thicknesses are required")
    if np.any(thicknesses <= 0.0):
        raise KMValidationError("paired thicknesses must be positive")
    if np.unique(thicknesses).size != thicknesses.size:
        raise KMValidationError("paired thicknesses must be unique")

    transmittance = _as_finite_array(transmittance_xyz, "transmittance_xyz")
    if transmittance.shape != (thicknesses.size, 3):
        raise KMValidationError("transmittance_xyz must have shape (N, 3)")
    if np.any(transmittance <= 0.0):
        raise KMValidationError("transmittance_xyz values must be > 0")
    if np.any(transmittance > 1.0):
        raise KMValidationError("transmittance_xyz values must be <= 1.0")
    reflectance = _as_finite_array(reflectance_xyz, "reflectance_xyz")
    if reflectance.shape != (thicknesses.size, 3):
        raise KMValidationError("reflectance_xyz must have shape (N, 3)")
    if np.any((reflectance < 0.0) | (reflectance > 1.0)):
        raise KMValidationError("reflectance_xyz values must be in [0, 1]")
    measurement_backing_base = _validated_xyz_vector(
        measurement_backing_base_xyz,
        "measurement_backing_base_xyz",
        upper=1.0,
    )
    if np.any(measurement_backing_base <= 0.0):
        raise KMValidationError(
            "measurement_backing_base_xyz values must be > 0"
        )
    maximum_backing_base = float(np.max(measurement_backing_base))
    backing_scale_max = float(1.0 / maximum_backing_base)
    if not np.isfinite(backing_scale_max):
        raise KMValidationError(
            "measurement_backing_base_xyz is too small for a finite scale bound"
        )

    (
        best_result,
        best_robust_objective,
        start_count,
        lower_bounds,
        upper_bounds,
    ) = _run_joint_fit(
        thicknesses,
        transmittance,
        reflectance,
        measurement_backing_base,
        backing_scale_max,
    )
    (
        absorption,
        scattering,
        backing_scale,
        thickness_offset,
    ) = _unpack_joint_fit_parameters(best_result.x)
    predicted_transmission, predicted_reflection = _predict_paired_measurements(
        best_result.x,
        thicknesses,
        measurement_backing_base,
    )

    channel_diagnostics: list[KMChannelFitDiagnostics] = []
    for channel_index, channel_name in enumerate(_CHANNEL_NAMES):
        transmission_error = (
            predicted_transmission[:, channel_index]
            - transmittance[:, channel_index]
        )
        reflection_error = (
            predicted_reflection[:, channel_index]
            - reflectance[:, channel_index]
        )
        transmission_rmse = float(np.sqrt(np.mean(transmission_error**2)))
        reflection_rmse = float(np.sqrt(np.mean(reflection_error**2)))
        channel_warnings: list[str] = []
        sorted_transmittance = transmittance[:, channel_index][
            np.argsort(thicknesses)
        ]
        if np.any(np.diff(sorted_transmittance) > 0.01):
            channel_warnings.append("transmittance_non_monotonic")
        if transmission_rmse > 0.02 or reflection_rmse > 0.02:
            channel_warnings.append("fit_residual_high")
        parameter_slice = slice(2 * channel_index, 2 * channel_index + 2)
        optical_bound_distance = np.minimum(
            best_result.x[parameter_slice] - lower_bounds[parameter_slice],
            upper_bounds[parameter_slice] - best_result.x[parameter_slice],
        )
        if np.any(optical_bound_distance < 0.1):
            channel_warnings.append("parameter_near_bound")
        channel_diagnostics.append(
            KMChannelFitDiagnostics(
                channel=channel_name,
                transmittance_rmse=transmission_rmse,
                reflectance_rmse=reflection_rmse,
                warnings=tuple(channel_warnings),
            )
        )

    condition = _jacobian_condition(best_result.jac)
    aggregate_warning_values: list[str] = []
    if not best_result.success:
        aggregate_warning_values.append("optimizer_not_converged")
    if condition is None or condition > 1.0e8:
        aggregate_warning_values.append("weakly_identifiable")
    backing_fraction = backing_scale / backing_scale_max
    if min(backing_fraction, 1.0 - backing_fraction) <= (
        _FIT_BACKING_SCALE_BOUND_FRACTION
    ):
        aggregate_warning_values.append("measurement_backing_scale_near_bound")
    thickness_offset_fraction = (
        thickness_offset / KM_XYZ_MEASUREMENT_THICKNESS_OFFSET_MAX_MM
    )
    if min(thickness_offset_fraction, 1.0 - thickness_offset_fraction) <= (
        _FIT_THICKNESS_OFFSET_BOUND_FRACTION
    ):
        aggregate_warning_values.append(
            "measurement_thickness_offset_near_bound"
        )
    aggregate_warning_values.extend(
        f"{diagnostic.channel}:{warning}"
        for diagnostic in channel_diagnostics
        for warning in diagnostic.warnings
    )
    aggregate_diagnostics = KMFitDiagnostics(
        success=bool(best_result.success),
        message=str(best_result.message),
        nfev=int(best_result.nfev),
        start_count=start_count,
        robust_objective=best_robust_objective,
        jacobian_condition=condition,
        measurement_thickness_offset_mm=thickness_offset,
        warnings=tuple(aggregate_warning_values),
        channels=tuple(channel_diagnostics),
        objective_id=KM_XYZ_FIT_OBJECTIVE_ID,
        objective_config=_fit_objective_config(
            thicknesses.size,
            measurement_backing_base,
            backing_scale_max,
        ),
    )
    effective_backing = measurement_backing_base * backing_scale
    return KMXYZFitResult(
        parameters=KMXYZParameters(
            K=absorption,
            S=scattering,
        ),
        predicted_transmittance_xyz=predicted_transmission,
        predicted_reflectance_xyz=predicted_reflection,
        measurement_backing_base_relative_xyz=measurement_backing_base.copy(),
        measurement_backing_scale=backing_scale,
        measurement_backing_effective_relative_xyz=effective_backing,
        measurement_thickness_offset_mm=thickness_offset,
        diagnostics=aggregate_diagnostics,
    )


__all__ = [
    "D65_2_WHITE_XYZ",
    "D65_10_WHITE_XYZ",
    "KMChannelFitDiagnostics",
    "KMFitDiagnostics",
    "KMFitError",
    "KMValidationError",
    "KMXYZFitResult",
    "KMXYZParameters",
    "KM_XYZ_COLOR_BRIDGE_ID",
    "KM_XYZ_FIT_OBJECTIVE_ID",
    "KM_XYZ_ILLUMINANT",
    "KM_XYZ_MEASUREMENT_GEOMETRY",
    "KM_XYZ_MEASUREMENT_PROTOCOL_ID",
    "KM_XYZ_MODEL_ID",
    "KM_XYZ_OBSERVER",
    "KM_XYZ_MEASUREMENT_THICKNESS_OFFSET_MAX_MM",
    "KM_XYZ_MEASUREMENT_REFLECTION_BOUNDARY_ID",
    "KM_XYZ_VALUE_SCALE",
    "effective_d65_10_to_relative_xyz",
    "effective_d65_10_to_xyz_d65_2",
    "fit_paired_km_xyz",
    "km_layer_rt",
    "km_relative_xyz_to_lab",
    "km_relative_xyz_to_linear_srgb",
    "km_relative_xyz_to_srgb_uint8",
    "km_stack_reflectance",
    "linear_srgb_to_km_relative_xyz",
    "relative_xyz_to_effective_d65_10",
    "xyz_d65_2_to_effective_d65_10",
]
