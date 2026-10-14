"""Linear-RGB propagation followed by one measured XYZ observation map.
在线性 RGB 中传播，完成整片组合后仅应用一次实测 XYZ 映射。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence
import time

import numpy as np
from scipy.optimize import least_squares

from core.backed_gradient_optics import CORE_MATERIAL_SYMBOLS, MATERIAL_SYMBOLS
from core.errors import CoreValidationError

RGB_AFFINE_FAMILY = "rgb_affine"
RGB_AFFINE_MODEL_ID = "backed_gradient_rgb_affine/v2"
RGB_AFFINE_BASIS_ID = "fixed_linear_srgb_to_reference_relative_xyz/v1"
_WHITE_INDEX = MATERIAL_SYMBOLS.index("W")
_BLACK_INDEX = MATERIAL_SYMBOLS.index("K")
_RGB_TO_RELATIVE_XYZ = np.array([
    [.4124564, .3575761, .1804375],
    [.2126729, .7151522, .0721750],
    [.0193339, .1191920, .9503041],
], dtype=float)
_RGB_TO_RELATIVE_XYZ /= _RGB_TO_RELATIVE_XYZ.sum(axis=1, keepdims=True)
_RGB_TO_RELATIVE_XYZ.setflags(write=False)


class _FitContext(Protocol):
    anchors: Mapping[str, Sequence[float]]
    total: float
    present: Sequence[str]


def _xyz(value: object, label: str) -> np.ndarray:
    try:
        result = np.asarray(value, dtype=float).copy()
    except (TypeError, ValueError) as error:
        raise CoreValidationError(f"{label} must contain numeric XYZ values") from error
    if result.shape != (3,) or not np.isfinite(result).all() or np.any(result < 0):
        raise CoreValidationError(f"{label} must contain three finite nonnegative XYZ values")
    result.setflags(write=False)
    return result


def _thickness(value: object) -> np.ndarray:
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as error:
        raise CoreValidationError("Material thickness must be numeric") from error
    if not np.isfinite(result).all() or np.any(result < 0):
        raise CoreValidationError("Material thickness must be finite and nonnegative")
    return result


@dataclass(frozen=True)
class BackedGradientRGB:
    """Compose affine RGB layers before integrating the whole stack into XYZ.
    先组合线性 RGB 仿射层，再将完整层组转换为 XYZ。

    Attributes:
        coefficients: Material-by-RGB-by-(attenuation, asymptote) coefficients.
            （材料、RGB 通道、衰减与渐近值的系数数组。）
        anchors: Measured bare-three-mm W/K report percentages.
            （裸三毫米白黑片实测报告百分数。）
        total_mm: Fixed complete sample thickness of three mm.
            （完整样片固定三毫米。）
        fitted_materials: Material codes available for composition.
            （可用于组合的已拟合材料代码。）
    """

    coefficients: np.ndarray
    anchors: Mapping[str, Sequence[float]]
    total_mm: float = 3.
    fitted_materials: tuple[str, ...] = CORE_MATERIAL_SYMBOLS
    family: str = field(default=RGB_AFFINE_FAMILY, init=False)
    _white_latent: np.ndarray = field(init=False, repr=False, compare=False)
    _black_latent: np.ndarray = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            values = np.asarray(self.coefficients, dtype=float).copy()
        except (TypeError, ValueError) as error:
            raise CoreValidationError("RGB optical coefficients must be numeric") from error
        symbols = tuple(self.fitted_materials)
        if (values.shape != (len(MATERIAL_SYMBOLS), 3, 2) or not np.isfinite(values).all()
                or np.any(values < 0) or not np.array_equal(values[_WHITE_INDEX, :, 1], np.ones(3))):
            raise CoreValidationError("RGB coefficients must be finite nonnegative arrays with a unit white asymptote")
        if (len(set(symbols)) != len(symbols) or not {"W", "K"}.issubset(symbols)
                or any(symbol not in MATERIAL_SYMBOLS for symbol in symbols)):
            raise CoreValidationError("Fitted RGB materials must be unique supported codes including W/K")
        if (isinstance(self.total_mm, bool) or not isinstance(self.total_mm, (int, float))
                or not np.isfinite(self.total_mm) or abs(self.total_mm - 3.) > 1e-8):
            raise CoreValidationError("RGB backed-gradient samples must have a complete three-mm thickness")
        if not isinstance(self.anchors, Mapping):
            raise CoreValidationError("Measured RGB-model anchors must be a W/K XYZ mapping")
        anchors = {symbol: _xyz(self.anchors.get(symbol), f"Bare {symbol} anchor") for symbol in ("W", "K")}
        if np.any(anchors["W"] <= anchors["K"]):
            raise CoreValidationError("Measured bare white XYZ must exceed bare black XYZ")
        values.setflags(write=False)
        object.__setattr__(self, "coefficients", values)
        object.__setattr__(self, "fitted_materials", symbols)
        object.__setattr__(self, "anchors", MappingProxyType(anchors))
        white = self.latent_material("W", 3.) @ _RGB_TO_RELATIVE_XYZ.T
        black = self.latent_material("K", 3.) @ _RGB_TO_RELATIVE_XYZ.T
        if np.any(white - black <= 1e-9):
            raise CoreValidationError("RGB latent white/black anchor contrast is singular")
        white.setflags(write=False)
        black.setflags(write=False)
        object.__setattr__(self, "_white_latent", white)
        object.__setattr__(self, "_black_latent", black)

    def _material(self, symbol: str) -> np.ndarray:
        if symbol not in self.fitted_materials:
            raise CoreValidationError("Material is absent from this fitted RGB model")
        return self.coefficients[MATERIAL_SYMBOLS.index(symbol)]

    def latent_material(self, symbol: str, thickness_mm: float | np.ndarray) -> np.ndarray:
        """Compute a finite material above a zero-return rear boundary in RGB.
        在线性 RGB 中计算零返光后边界上的有限厚度材料。

        Args:
            symbol: Fitted material code.（已拟合材料代码。）
            thickness_mm: Nonnegative material thickness.（非负材料厚度。）

        Returns:
            Whole-material latent linear RGB.（完整材料的潜在线性 RGB。）
        """
        coefficient = self._material(symbol)
        thickness = _thickness(thickness_mm)
        return coefficient[:, 1] * (-np.expm1(-thickness[..., None] * coefficient[:, 0]))

    def add_material(self, symbol: str, thickness_mm: float | np.ndarray,
                     rear_response: np.ndarray) -> np.ndarray:
        """Add one touching RGB layer without an internal air interface.
        添加一层紧贴的 RGB 材料，内部不插入空气界面。

        Args:
            symbol: Fitted front material.（已拟合的前层材料。）
            thickness_mm: Nonnegative front-layer thickness.（非负前层厚度。）
            rear_response: Latent linear RGB of the rear stack.（后层组潜在线性 RGB。）

        Returns:
            Combined latent linear RGB.（组合后的潜在线性 RGB。）
        """
        coefficient = self._material(symbol)
        thickness = _thickness(thickness_mm)
        rear = np.asarray(rear_response, dtype=float)
        if rear.shape[-1:] != (3,) or not np.isfinite(rear).all():
            raise CoreValidationError("Rear latent RGB must contain three finite channels")
        retention = np.exp(-thickness[..., None] * coefficient[:, 0])
        return coefficient[:, 1] * (1. - retention) + retention * rear

    def report_unfloored(self, latent_rgb: np.ndarray) -> np.ndarray:
        """Integrate the whole RGB response and apply the fixed measured XYZ map.
        积分完整 RGB 响应，并应用固定的实测 XYZ 映射。

        Args:
            latent_rgb: Finite whole-stack latent RGB.（有限的整片潜在 RGB。）

        Returns:
            Signed reported XYZ percentages before the device zero floor.
                （设备零点下限之前的带符号 XYZ 报告百分数。）
        """
        response = np.asarray(latent_rgb, dtype=float)
        if response.shape[-1:] != (3,) or not np.isfinite(response).all():
            raise CoreValidationError("Whole-stack latent RGB must contain three finite channels")
        xyz = response @ _RGB_TO_RELATIVE_XYZ.T
        return self.anchors["K"] + (self.anchors["W"] - self.anchors["K"]) * (
            xyz - self._black_latent
        ) / (self._white_latent - self._black_latent)

    def report(self, latent_rgb: np.ndarray) -> np.ndarray:
        """Apply the native zero floor without clipping values above 100 percent.
        应用设备零点下限，不裁切超过一百的报告百分数。

        Args:
            latent_rgb: Whole-stack latent RGB.（整片潜在 RGB。）

        Returns:
            Nonnegative reported XYZ percentages.（非负 XYZ 报告百分数。）
        """
        return np.maximum(self.report_unfloored(latent_rgb), 0.)

    def predict_backed(self, material: str, backing: str,
                       overlay_mm: float | np.ndarray) -> np.ndarray:
        """Predict overlay d on the actual three-minus-d printed backing.
        预测覆层 d 与实际三毫米减 d 的打印背板。

        Args:
            material: Fitted overlay material.（已拟合覆层材料。）
            backing: W/K backing material.（白或黑背板材料。）
            overlay_mm: Actual overlay thickness.（实际覆层厚度。）

        Returns:
            Reported XYZ percentages after one observation map.
                （应用一次观测映射后的 XYZ 报告百分数。）
        """
        thickness = _thickness(overlay_mm)
        if backing not in ("W", "K") or np.any(thickness > self.total_mm):
            raise CoreValidationError("Backing must be W/K and overlay cannot exceed the complete thickness")
        rear = self.latent_material(backing, self.total_mm - thickness)
        return self.report(self.add_material(material, thickness, rear))

    def predict_recipes(self, recipes_visible_to_back: Sequence[str], backing: str,
                        layer_mm: float = .08, *, backing_mm: float | None = None) -> np.ndarray:
        """Compose recipes with an actual finite backing, retaining three-mm anchors.
        用实际有限厚度背板组合配方，裸参考锚始终保持三毫米。

        Args:
            recipes_visible_to_back: Codes ordered from the observed face inward.
                （从测量面向内排列的材料代码。）
            backing: Actual W/K backing.（实际白或黑背板。）
            layer_mm: Thickness of each color layer.（每个颜色层厚度。）
            backing_mm: Optional explicit historical printed backing thickness.
                （可选的历史实物背板厚度。）

        Returns:
            One reported XYZ vector per recipe.（每个配方对应一组 XYZ 报告值。）
        """
        recipes = tuple(recipes_visible_to_back)
        if (not recipes or any(not isinstance(recipe, str) or not recipe for recipe in recipes)
                or len({len(recipe) for recipe in recipes}) != 1
                or any(code not in self.fitted_materials for recipe in recipes for code in recipe)):
            raise CoreValidationError("RGB recipes must have equal nonzero length and contain fitted materials")
        if (isinstance(layer_mm, bool) or not isinstance(layer_mm, (int, float))
                or not np.isfinite(layer_mm) or layer_mm <= 0):
            raise CoreValidationError("RGB recipe layer thickness must be positive")
        if backing_mm is None:
            base = self.total_mm - len(recipes[0]) * layer_mm
        else:
            if isinstance(backing_mm, bool) or not isinstance(backing_mm, (int, float)):
                raise CoreValidationError("Explicit backing thickness must be numeric")
            base = float(backing_mm)
        if backing not in ("W", "K") or not np.isfinite(base) or base <= 0:
            raise CoreValidationError("RGB recipes require a positive finite W/K backing")
        response = np.broadcast_to(self.latent_material(backing, base), (len(recipes), 3)).copy()
        for column in range(len(recipes[0]) - 1, -1, -1):
            for symbol in self.fitted_materials:
                indices = np.array([i for i, recipe in enumerate(recipes) if recipe[column] == symbol], dtype=int)
                if indices.size:
                    response[indices] = self.add_material(symbol, layer_mm, response[indices])
        return self.report(response)

    def to_parameters(self) -> dict:
        """Serialize independent RGB coefficients and their fixed observation contract.
        导出独立 RGB 系数及固定观测契约。

        Returns:
            Portable RGB model parameters.（可移植的 RGB 模型参数。）
        """
        return {
            "family": self.family, "model_id": RGB_AFFINE_MODEL_ID,
            "propagation_space": "linear_rgb", "basis_id": RGB_AFFINE_BASIS_ID,
            "total_mm": self.total_mm, "fitted_materials": list(self.fitted_materials),
            "reference_anchors": {symbol: values.tolist() for symbol, values in self.anchors.items()},
            "white_asymptote_gauge": "unit_linear_rgb", "native_black_floor": True,
            "surface_model": "effective_bulk_no_separate_fresnel",
            "observation_mapping": "fixed_measured_bare_W3_K3_once/v1",
            "materials": {symbol: {"attenuation_rgb": self._material(symbol)[:, 0].tolist(),
                                   "asymptote_rgb": self._material(symbol)[:, 1].tolist()}
                          for symbol in self.fitted_materials},
        }

    @classmethod
    def from_parameters(cls, payload: Mapping) -> BackedGradientRGB:
        """Restore only the independent RGB schema, without loading old archives.
        仅恢复独立 RGB 格式，不加载旧耗材档案。

        Args:
            payload: Complete independent RGB parameters.（完整的独立 RGB 参数。）

        Returns:
            Validated RGB propagation model.（通过校验的 RGB 传播模型。）
        """
        if (not isinstance(payload, Mapping) or payload.get("family") != RGB_AFFINE_FAMILY
                or payload.get("model_id") != RGB_AFFINE_MODEL_ID
                or payload.get("basis_id") != RGB_AFFINE_BASIS_ID
                or payload.get("propagation_space") != "linear_rgb"):
            raise CoreValidationError("Unsupported backed-gradient RGB parameter record")
        try:
            fitted = tuple(payload["fitted_materials"])
            coefficients = np.zeros((len(MATERIAL_SYMBOLS), 3, 2))
            for symbol in fitted:
                index = MATERIAL_SYMBOLS.index(symbol)
                coefficients[index, :, 0] = payload["materials"][symbol]["attenuation_rgb"]
                coefficients[index, :, 1] = payload["materials"][symbol]["asymptote_rgb"]
            return cls(coefficients, payload["reference_anchors"], payload["total_mm"], fitted)
        except (KeyError, TypeError, ValueError) as error:
            raise CoreValidationError("Incomplete backed-gradient RGB coefficients") from error


def _coordinates(symbols: Sequence[str]) -> list[tuple[int, int, int]]:
    return [(MATERIAL_SYMBOLS.index(symbol), channel, kind) for symbol in symbols
            for channel in range(3) for kind in range(2) if not (symbol == "W" and kind == 1)]


def _seed_coefficients(seed: int) -> np.ndarray:
    factors = (1., .4, 2., 5.)
    coefficient = np.ones((len(MATERIAL_SYMBOLS), 3, 2))
    coefficient[..., 0] = np.array([
        [.8, 25., 25.], [.3, .3, 15.], [15., 12., .5], [1., 1., 1.],
        [20., 20., 20.], [20., .8, .8], [.8, 20., .8], [20., .8, 20.],
    ]) * factors[seed % len(factors)]
    coefficient[..., 1] = np.array([
        [.3, .003, .008], [.95, .85, .015], [.01, .03, .4], [1., 1., 1.],
        [.01, .01, .01], [.01, .4, .4], [.4, .01, .4], [.01, .4, .01],
    ])
    return coefficient


def _deadline_check(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("RGB backed-gradient fitting exceeded its time allowance")


def _predict_arrays(coefficients: np.ndarray, anchors: Mapping, total: float,
                    symbols: np.ndarray, backings: np.ndarray, thicknesses: np.ndarray) -> np.ndarray:
    rear = coefficients[backings, :, 1] * (-np.expm1(-coefficients[backings, :, 0] * (total - thicknesses[:, None])))
    retention = np.exp(-coefficients[symbols, :, 0] * thicknesses[:, None])
    rgb = coefficients[symbols, :, 1] * (1. - retention) + retention * rear
    bare = (coefficients[[_WHITE_INDEX, _BLACK_INDEX], :, 1] * (
        -np.expm1(-coefficients[[_WHITE_INDEX, _BLACK_INDEX], :, 0] * 3.)
    )) @ _RGB_TO_RELATIVE_XYZ.T
    span = bare[0] - bare[1]
    if np.any(span <= 1e-9):
        return np.full((len(symbols), 3), 1000.)
    return np.maximum(np.asarray(anchors["K"]) + (np.asarray(anchors["W"]) - anchors["K"]) * (
        rgb @ _RGB_TO_RELATIVE_XYZ.T - bare[1]
    ) / span, 0.)


def _optimise(template: np.ndarray, prepared: _FitContext, rows: Sequence[dict],
              coordinates: Sequence[tuple[int, int, int]], deadline: float) -> tuple[np.ndarray, dict]:
    symbols = np.array([MATERIAL_SYMBOLS.index(row["material_symbol"]) for row in rows])
    backings = np.array([MATERIAL_SYMBOLS.index(row["backing"]) for row in rows])
    thicknesses = np.array([row["overlay_mm"] for row in rows])
    observed = np.array([row["reflectance_percent_xyz"] for row in rows])
    initial = np.array([np.log(max(template[coordinate], 1e-7)) for coordinate in coordinates])
    lower = np.array([np.log(1e-6 if coordinate[2] == 0 else 1e-7) for coordinate in coordinates])
    upper = np.array([np.log(200. if coordinate[2] == 0 else 4.) for coordinate in coordinates])

    def unpack(values: np.ndarray) -> np.ndarray:
        coefficient = template.copy()
        for coordinate, value in zip(coordinates, values, strict=True):
            coefficient[coordinate] = np.exp(value)
        return coefficient

    def residual(values: np.ndarray) -> np.ndarray:
        _deadline_check(deadline)
        prediction = _predict_arrays(unpack(values), prepared.anchors, prepared.total, symbols, backings, thicknesses)
        return ((prediction - observed) / 100.).ravel()

    solution = least_squares(residual, np.clip(initial, lower, upper), bounds=(lower, upper),
                             max_nfev=300, x_scale="jac", ftol=1e-9, xtol=1e-9, gtol=1e-9)
    coefficient = unpack(solution.x)
    prediction = _predict_arrays(coefficient, prepared.anchors, prepared.total, symbols, backings, thicknesses)
    return coefficient, {"success": bool(solution.success), "nfev": int(solution.nfev),
                         "rmse_pp": float(np.sqrt(np.mean((prediction - observed) ** 2))),
                         "message": str(solution.message)}


def fit_rgb_operator(prepared: _FitContext, rows: Sequence[dict], deadline: float,
                     *, starts: int = 2) -> tuple[BackedGradientRGB, list[dict], list[BackedGradientRGB]]:
    """Fit only this batch's BOX XYZ using independent fixed seeds in every call.
    每次均从固定独立种子出发，只拟合本批 BOX XYZ。

    Args:
        prepared: Validated snapshot context with anchors, total and present materials.
            （含裸锚、总厚和材料列表的已校验快照上下文。）
        rows: Training rows; holdout records must already have been removed.
            （训练读数；留出记录须已移除。）
        deadline: Absolute monotonic-clock deadline.（单调时钟上的绝对截止时间。）
        starts: Number of fixed deterministic starts.（固定确定性初值数量。）

    Returns:
        Best operator, seed diagnostics and all finite endpoints.
            （最优模型、各初值诊断及所有有限解。）
    """
    if isinstance(starts, bool) or not isinstance(starts, int) or not 1 <= starts <= 4:
        raise CoreValidationError("RGB fitting requires one to four deterministic starts")
    if not rows or not np.isfinite(deadline):
        raise CoreValidationError("RGB fitting requires training rows and a finite deadline")
    present = tuple(symbol for symbol in prepared.present if any(row["material_symbol"] == symbol for row in rows))
    if not {"W", "K"}.issubset(present):
        raise CoreValidationError("RGB fitting requires joint white/black training rows")
    observed = np.array([row["reflectance_percent_xyz"] for row in rows])
    row_symbols = np.array([MATERIAL_SYMBOLS.index(row["material_symbol"]) for row in rows])
    row_backings = np.array([MATERIAL_SYMBOLS.index(row["backing"]) for row in rows])
    thicknesses = np.array([row["overlay_mm"] for row in rows])
    white_black = [row for row in rows if row["material_symbol"] in ("W", "K")]
    best, attempts, endpoints = None, [], []
    for seed in range(starts):
        _deadline_check(deadline)
        try:
            coefficient = _seed_coefficients(seed)
            coefficient, wb_status = _optimise(coefficient, prepared, white_black, _coordinates(("W", "K")), deadline)
            for symbol in present:
                if symbol not in ("W", "K"):
                    material_rows = [row for row in rows if row["material_symbol"] == symbol]
                    coefficient, _ = _optimise(coefficient, prepared, material_rows, _coordinates((symbol,)), deadline)
            coefficient, joint_status = _optimise(coefficient, prepared, rows, _coordinates(present), deadline)
            operator = BackedGradientRGB(coefficient, prepared.anchors, prepared.total, present)
            prediction = _predict_arrays(coefficient, prepared.anchors, prepared.total, row_symbols, row_backings, thicknesses)
            rmse = float(np.sqrt(np.mean((prediction - observed) ** 2)))
        except (CoreValidationError, FloatingPointError, np.linalg.LinAlgError) as error:
            attempts.append({"seed": seed, "success": False, "error": str(error)})
            continue
        attempts.append({"seed": seed, "success": joint_status["success"], "rmse_pp": rmse,
                         "white_black": wb_status, "joint": joint_status})
        if np.isfinite(rmse):
            endpoints.append(operator)
            if best is None or rmse < best[0]:
                best = rmse, operator
    if best is None:
        raise CoreValidationError("RGB backed-gradient fitting found no finite feasible solution")
    return best[1], attempts, endpoints
