"""Restore independent backed-gradient model versions. / 恢复独立黑白底模型版本。"""
from __future__ import annotations

from typing import Mapping, Protocol, Sequence

import numpy as np

from core.backed_gradient_optics import BackedGradientOptics, MODEL_IDS
from core.errors import CoreValidationError


class BackedGradientModel(Protocol):
    """Portable whole-stack prediction contract. / 可移植完整层组预测契约。"""

    def predict_backed(self, material: str, backing: str,
                       overlay_mm: float | np.ndarray) -> np.ndarray: ...

    def predict_recipes(self, recipes_visible_to_back: Sequence[str], backing: str,
                        layer_mm: float = .08) -> np.ndarray: ...

    def to_parameters(self) -> dict: ...


def restore_backed_gradient_model(parameters: Mapping) -> BackedGradientModel:
    """Restore an exact model version without consulting active material archives.
    按准确模型版本恢复，不读取当前材料档案。

    Args:
        parameters: Complete versioned coefficients.（完整带版本参数。）

    Returns:
        Validated independent whole-stack model.（已校验的独立完整层组模型。）
    """
    if not isinstance(parameters, Mapping):
        raise CoreValidationError("Backed-gradient parameters must be an object")
    identity = parameters.get("model_id")
    if identity in MODEL_IDS.values():
        return BackedGradientOptics.from_parameters(parameters)
    from core.backed_gradient_transport import BackedGradientTransport, SPECTRAL_FOUR_FLUX_MODEL_ID

    if identity == SPECTRAL_FOUR_FLUX_MODEL_ID:
        return BackedGradientTransport.from_parameters(parameters)
    from core.backed_gradient_smooth import BackedGradientSmoothTransport, SPECTRAL_SMOOTH_MODEL_ID

    if identity == SPECTRAL_SMOOTH_MODEL_ID:
        return BackedGradientSmoothTransport.from_parameters(parameters)
    from core.backed_gradient_rgb import BackedGradientRGB, RGB_AFFINE_MODEL_ID

    if identity == RGB_AFFINE_MODEL_ID:
        return BackedGradientRGB.from_parameters(parameters)
    raise CoreValidationError("Unknown backed-gradient model version")
