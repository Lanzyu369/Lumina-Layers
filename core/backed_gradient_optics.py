"""Finite printed backings and one calibrated observation map.
有限厚度打印背板与仅应用一次的共同测量映射。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np

from core.errors import CoreValidationError
from core.km_xyz import km_layer_rt

CORE_MATERIAL_SYMBOLS = ("R", "Y", "B", "W", "K")
MATERIAL_SYMBOLS = (*CORE_MATERIAL_SYMBOLS, "C", "M", "G")
MODEL_IDS = {
    "affine": "backed_gradient_affine_fixed_white_gauge/v1",
    "two_flux": "backed_gradient_effective_two_flux/v1",
}


def _xyz(value: object, label: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != (3,) or not np.isfinite(result).all():
        raise CoreValidationError(f"{label} must contain three finite XYZ values")
    return result.copy()


@dataclass(frozen=True)
class BackedGradientOptics:
    """Effective propagation with a finite W/K substrate, not free instrument gains.
    带有限白/黑背板的有效传播，不增加自由仪器增益。

    Attributes:
        family: ``affine`` or ``two_flux``.（有效仿射或双通量模型。）
        coefficients: Symbol-by-XYZ-by-two coefficient array.（材料、通道、系数数组。）
        anchors: Actual bare-three-mm reported percentages.（实际裸三毫米报告读数。）
        total_mm: Complete printed sample thickness.（完整打印样片厚度。）
    """

    family: str
    coefficients: np.ndarray
    anchors: Mapping[str, Sequence[float]]
    total_mm: float = 3.0
    fitted_materials: tuple[str, ...] = CORE_MATERIAL_SYMBOLS
    _white_latent: np.ndarray = field(init=False, repr=False, compare=False)
    _black_latent: np.ndarray = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.family not in MODEL_IDS:
            raise CoreValidationError("Unknown backed-gradient optical model")
        values = np.asarray(self.coefficients, dtype=float).copy()
        if values.shape != (len(MATERIAL_SYMBOLS), 3, 2) or not np.isfinite(values).all() or np.any(values < 0):
            raise CoreValidationError("Optical coefficients must be finite nonnegative symbol-by-XYZ-by-two values")
        if (len(set(self.fitted_materials)) != len(self.fitted_materials)
                or not {"W", "K"}.issubset(self.fitted_materials)
                or any(symbol not in MATERIAL_SYMBOLS for symbol in self.fitted_materials)):
            raise CoreValidationError("Fitted material symbols must be unique supported symbols including W/K")
        if self.family == "affine" and not np.array_equal(values[3, :, 1], np.ones(3)):
            raise CoreValidationError("The affine latent white gauge must equal one")
        if not np.isfinite(self.total_mm) or self.total_mm <= 0:
            raise CoreValidationError("Total printed thickness must be positive")
        if not isinstance(self.anchors, Mapping):
            raise CoreValidationError("Measured bare anchors must be a W/K mapping")
        anchors = {key: _xyz(self.anchors.get(key), f"Bare {key} anchor") for key in ("W", "K")}
        if np.any(anchors["K"] < 0) or np.any(anchors["W"] <= anchors["K"]):
            raise CoreValidationError("Bare white XYZ must exceed bare black XYZ")
        values.setflags(write=False)
        object.__setattr__(self, "coefficients", values)
        for value in anchors.values():
            value.setflags(write=False)
        object.__setattr__(self, "anchors", MappingProxyType(anchors))
        object.__setattr__(self, "fitted_materials", tuple(self.fitted_materials))
        white = self.latent_material("W", self.total_mm)
        black = self.latent_material("K", self.total_mm)
        white.setflags(write=False)
        black.setflags(write=False)
        object.__setattr__(self, "_white_latent", white)
        object.__setattr__(self, "_black_latent", black)
        span = white - black
        if np.any(span <= 1e-9):
            raise CoreValidationError("The model's latent white/black anchor contrast is singular")

    def latent_material(self, symbol: str, thickness_mm: float | np.ndarray) -> np.ndarray:
        """Compute one continuous material above a zero-return rear boundary.
        计算零返光后边界上的连续材料，保留有限厚度。

        Args:
            symbol: A fitted material code.（已拟合材料代码。）
            thickness_mm: Nonnegative material thickness.（非负材料厚度。）

        Returns:
            Effective latent XYZ response.（有效潜在 XYZ 响应。）
        """
        if symbol not in self.fitted_materials:
            raise CoreValidationError("Material is not fitted in this model")
        thickness = np.asarray(thickness_mm, dtype=float)
        if not np.isfinite(thickness).all() or np.any(thickness < 0):
            raise CoreValidationError("Material thickness must be finite and nonnegative")
        coefficient = self.coefficients[MATERIAL_SYMBOLS.index(symbol)]
        if self.family == "affine":
            return coefficient[:, 1] * (-np.expm1(-thickness[..., None] * coefficient[:, 0]))
        return km_layer_rt(coefficient[:, 0], coefficient[:, 1], thickness[..., None])[0]

    def add_material(self, symbol: str, thickness_mm: float | np.ndarray,
                     rear_response: np.ndarray) -> np.ndarray:
        """Add touching material without inserting an internal air surface.
        添加紧贴材料，不插入内部空气界面或重复镜面修正。

        Args:
            symbol: Fitted front material code.（已拟合前层材料代码。）
            thickness_mm: Front layer thickness.（前层厚度。）
            rear_response: Latent response of the lower stack.（下部层组潜在响应。）

        Returns:
            Combined latent XYZ response.（组合后的潜在 XYZ 响应。）
        """
        if symbol not in self.fitted_materials:
            raise CoreValidationError("Material is not fitted in this model")
        thickness = np.asarray(thickness_mm, dtype=float)
        rear = np.asarray(rear_response, dtype=float)
        if not np.isfinite(thickness).all() or np.any(thickness < 0) or not np.isfinite(rear).all():
            raise CoreValidationError("Layer thickness and rear response must be finite")
        coefficient = self.coefficients[MATERIAL_SYMBOLS.index(symbol)]
        if self.family == "affine":
            retention = np.exp(-thickness[..., None] * coefficient[:, 0])
            return coefficient[:, 1] * (1 - retention) + retention * rear
        reflection, transmission = km_layer_rt(coefficient[:, 0], coefficient[:, 1], thickness[..., None])
        denominator = 1 - reflection * rear
        if np.any(denominator <= 1e-12):
            raise CoreValidationError("The two-flux composition reached a singular return boundary")
        return reflection + transmission ** 2 * rear / denominator

    def report_unfloored(self, latent_response: np.ndarray) -> np.ndarray:
        """Apply the signed bare-anchor map before the instrument's known zero floor.
        应用带符号裸锚映射，暂不施加仪器已知零点下限。

        Args:
            latent_response: Whole-stack latent XYZ.（完整层组潜在 XYZ。）

        Returns:
            Signed report coordinates before the device floor.（设备下限之前的带符号报告坐标。）
        """
        latent = np.asarray(latent_response, dtype=float)
        if latent.shape[-1:] != (3,) or not np.isfinite(latent).all():
            raise CoreValidationError("Latent responses must have a finite XYZ last axis")
        white, black = self._white_latent, self._black_latent
        return self.anchors["K"] + (self.anchors["W"] - self.anchors["K"]) * (latent - black) / (white - black)

    def report(self, latent_response: np.ndarray) -> np.ndarray:
        """Apply the device's known black-subtraction floor, with no upper clipping.
        应用设备已知黑点扣除下限，不裁切超过一百的读数。

        Args:
            latent_response: Whole-stack latent XYZ.（完整层组潜在 XYZ。）

        Returns:
            Native nonnegative report percentages.（原生非负报告百分数。）
        """
        return np.maximum(self.report_unfloored(latent_response), 0.)

    def predict_backed(self, material: str, backing: str,
                       overlay_mm: float | np.ndarray) -> np.ndarray:
        """Predict overlay d on actual backing total-d in reported percent XYZ.
        预测覆层 d 与实际背板总厚减 d，输出报告百分数 XYZ。

        Args:
            material: Overlay material code.（覆层材料代码。）
            backing: Actual W/K substrate code.（实际白黑背板代码。）
            overlay_mm: Actual overlay thickness.（实际覆层厚度。）

        Returns:
            Reported XYZ percentages.（报告 XYZ 百分数。）
        """
        thickness = np.asarray(overlay_mm, dtype=float)
        if backing not in ("W", "K") or not np.isfinite(thickness).all() or np.any(thickness < 0) or np.any(thickness > self.total_mm):
            raise CoreValidationError("Backing must be W/K and overlay must stay within the complete sample")
        rear = self.latent_material(backing, self.total_mm - thickness)
        return self.report(self.add_material(material, thickness, rear))

    def predict_recipes(self, recipes_visible_to_back: Sequence[str], backing: str,
                        layer_mm: float = .08) -> np.ndarray:
        """Predict arbitrary visible-to-back recipes with a physical finite backing.
        预测可见面向内的配方，并计算剩余厚度的实体背板。

        Args:
            recipes_visible_to_back: Codes ordered from the visible face inward.
                （从可见面向内排列的配方代码。）
            backing: Actual W/K substrate.（实际白黑背板。）
            layer_mm: Each upper layer's thickness.（每个上部层的厚度。）

        Returns:
            One reported XYZ vector per recipe.（每个配方的报告 XYZ 向量。）
        """
        recipes = tuple(recipes_visible_to_back)
        if not recipes or len({len(recipe) for recipe in recipes}) != 1:
            raise CoreValidationError("Recipes must be nonempty and have the same layer count")
        if any(not recipe or any(code not in self.fitted_materials for code in recipe) for recipe in recipes):
            raise CoreValidationError("Recipe contains a material absent from the fitted model")
        if not np.isfinite(layer_mm) or layer_mm <= 0:
            raise CoreValidationError("Recipe layer height must be positive")
        base_mm = self.total_mm - len(recipes[0]) * layer_mm
        if base_mm <= 0 or backing not in ("W", "K"):
            raise CoreValidationError("A recipe must retain a positive W/K backing")
        response = np.broadcast_to(self.latent_material(backing, base_mm), (len(recipes), 3)).copy()
        for column in range(len(recipes[0]) - 1, -1, -1):
            for symbol in MATERIAL_SYMBOLS:
                indices = np.array([i for i, recipe in enumerate(recipes) if recipe[column] == symbol])
                if len(indices):
                    response[indices] = self.add_material(symbol, layer_mm, response[indices])
        return self.report(response)

    def to_parameters(self) -> dict:
        """Serialize effective coefficients with their model and observation boundaries.
        导出有效系数及模型、测量边界定义。

        Returns:
            Complete portable parameter payload.（完整可移植参数记录。）
        """
        fields = ("attenuation_xyz", "asymptote_xyz") if self.family == "affine" else ("absorption_xyz", "scattering_xyz")
        return {
            "family": self.family, "model_id": MODEL_IDS[self.family], "total_mm": self.total_mm,
            "reference_anchors": {key: value.tolist() for key, value in self.anchors.items()},
            "surface_model": "effective_bulk_no_separate_fresnel",
            "observation_mapping": "fixed_measured_bare_W3_K3_once/v1",
            "native_black_floor": True, "fitted_materials": list(self.fitted_materials),
            "materials": {symbol: {fields[0]: self.coefficients[i, :, 0].tolist(), fields[1]: self.coefficients[i, :, 1].tolist()}
                          for i, symbol in enumerate(MATERIAL_SYMBOLS) if symbol in self.fitted_materials},
        }

    @classmethod
    def from_parameters(cls, payload: Mapping) -> BackedGradientOptics:
        """Restore one complete parameter record without reading live material archives.
        恢复完整参数记录，不读取活动耗材档案。

        Args:
            payload: Complete versioned coefficients.（完整带版本系数。）

        Returns:
            Validated propagation operator.（通过校验的传播算子。）
        """
        family = payload.get("family")
        if family not in MODEL_IDS or payload.get("model_id") != MODEL_IDS[family]:
            raise CoreValidationError("Unknown backed-gradient parameter record")
        fields = ("attenuation_xyz", "asymptote_xyz") if family == "affine" else ("absorption_xyz", "scattering_xyz")
        coefficients = np.zeros((len(MATERIAL_SYMBOLS), 3, 2))
        try:
            fitted = tuple(payload["fitted_materials"])
            for symbol in fitted:
                index = MATERIAL_SYMBOLS.index(symbol)
                for column, field in enumerate(fields):
                    coefficients[index, :, column] = _xyz(payload["materials"][symbol][field], field)
            return cls(family, coefficients, payload["reference_anchors"], float(payload["total_mm"]), fitted)
        except (KeyError, TypeError, ValueError) as error:
            raise CoreValidationError("Incomplete backed-gradient coefficients") from error
