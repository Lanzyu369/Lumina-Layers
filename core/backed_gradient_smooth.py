"""Fixed weak log-absorption curvature policy over unchanged spectral physics.
在不改变光谱传播物理与参数数量的前提下，固定弱吸收对数曲率约束。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from core.backed_gradient_transport import (
    BackedGradientTransport,
    SPECTRAL_FOUR_FLUX_FAMILY,
    SPECTRAL_FOUR_FLUX_MODEL_ID,
)
from core.errors import CoreValidationError

SPECTRAL_SMOOTH_FAMILY = "spectral_four_flux_smooth"
SPECTRAL_SMOOTH_MODEL_ID = "backed_gradient_spectral_four_flux_smooth/v3"
SPECTRAL_SMOOTH_OBJECTIVE_ID = "backed_gradient_xyz_fixed_weak_logk_curvature/v1"
SPECTRAL_CURVATURE_WEIGHT = .003
_REGULARIZATION = {
    "kind": "second_difference_log_absorption_four_nodes",
    "weight": SPECTRAL_CURVATURE_WEIGHT,
    "applies_to": "color_materials_only",
    "white_black_penalized": False,
    "additional_free_parameters": 0,
}


def spectral_curvature_residual(coefficients: Mapping[str, Sequence[float]]) -> np.ndarray:
    """Return the fixed weighted second differences for fitted colored materials.
    返回已拟合彩色材料的固定加权吸收对数二阶差分。

    Args:
        coefficients: Material parameter vectors using the unchanged spectral schema.
            （使用原光谱格式的材料参数向量。）

    Returns:
        Two residual values per colored material; W/K contribute no residuals.
            （每种彩色材料两项残差；白黑材料不生成约束残差。）
    """
    if not isinstance(coefficients, Mapping):
        raise CoreValidationError("Spectral curvature coefficients must be a material mapping")
    penalties = []
    for symbol, source in coefficients.items():
        if symbol in ("W", "K"):
            continue
        try:
            values = np.asarray(source, dtype=float)
        except (TypeError, ValueError) as error:
            raise CoreValidationError("Colored spectral curvature coefficients must be numeric") from error
        if values.shape != (7,) or not np.isfinite(values).all():
            raise CoreValidationError("Colored spectral curvature needs seven finite material coefficients")
        penalties.append(SPECTRAL_CURVATURE_WEIGHT * np.diff(values[:4], n=2))
    return np.concatenate(penalties) if penalties else np.empty(0)


@dataclass(frozen=True)
class BackedGradientSmoothTransport(BackedGradientTransport):
    """Version the fixed fitting policy while retaining all v2 propagation behavior.
    独立标记固定拟合约束，同时保留第二版全部光谱传播行为。

    Attributes:
        family: Independent smooth-spectral family identifier.
            （独立的平滑光谱模型家族标识。）
    """

    family: str = field(default=SPECTRAL_SMOOTH_FAMILY, init=False)

    def curvature_residual(self) -> np.ndarray:
        """Return the immutable fitting policy's residuals, without reading measurements.
        返回不可变拟合约束残差，不读取任何测量值。

        Returns:
            Fixed .003-weighted colored log-K curvature terms.
                （固定零点零零三加权的彩材吸收对数曲率项。）
        """
        return spectral_curvature_residual(self.coefficients)

    def to_parameters(self) -> dict:
        """Export v3 policy identity with the unchanged complete physical parameters.
        导出第三版约束标识，以及保持原样的完整物理参数。

        Returns:
            Portable spectral parameters with exact fixed objective provenance.
                （包含准确固定目标来源的可移植光谱参数。）
        """
        payload = super().to_parameters()
        payload.update(model_id=SPECTRAL_SMOOTH_MODEL_ID, objective_id=SPECTRAL_SMOOTH_OBJECTIVE_ID,
                       regularization=dict(_REGULARIZATION))
        return payload

    @classmethod
    def from_parameters(cls, payload: Mapping) -> BackedGradientSmoothTransport:
        """Restore only the fixed v3 policy and validate every inherited boundary.
        仅恢复固定第三版约束，并校验所有继承的传播边界。

        Args:
            payload: Complete versioned smooth-spectral coefficients.
                （完整带版本平滑光谱参数。）

        Returns:
            Validated independent v3 model.（通过校验的独立第三版模型。）
        """
        policy = payload.get("regularization") if isinstance(payload, Mapping) else None
        policy_matches = (isinstance(policy, Mapping) and set(policy) == set(_REGULARIZATION)
                          and all(type(policy[key]) is type(expected) and policy[key] == expected
                                  for key, expected in _REGULARIZATION.items()))
        if (not isinstance(payload, Mapping) or payload.get("family") != SPECTRAL_SMOOTH_FAMILY
                or payload.get("model_id") != SPECTRAL_SMOOTH_MODEL_ID
                or payload.get("objective_id") != SPECTRAL_SMOOTH_OBJECTIVE_ID
                or not policy_matches):
            raise CoreValidationError("Unsupported fixed smooth-spectral fitting policy")
        legacy = dict(payload)
        legacy.update(family=SPECTRAL_FOUR_FLUX_FAMILY, model_id=SPECTRAL_FOUR_FLUX_MODEL_ID)
        restored = BackedGradientTransport.from_parameters(legacy)
        return cls(restored.coefficients, restored.anchors, restored.total_mm, restored.fitted_materials)
