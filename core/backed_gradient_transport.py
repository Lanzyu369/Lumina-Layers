"""Spectral direct/diffuse propagation for finite printed black/white backings.
有限黑白打印背板的分波段直射与漫射传播。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np

from core.backed_gradient_optics import CORE_MATERIAL_SYMBOLS, MATERIAL_SYMBOLS
from core.errors import CoreValidationError
from core.lumina_box_spectral import (
    BoxSpectralBasis,
    LUMINA_BOX_SPECTRAL_BASIS_ID,
    load_box_spectral_basis,
)
from core.lumina_box_transport import (
    OpticalPort,
    combine_optical_layers,
    material_bulk_port,
    outer_surface_port,
    reverse_optical_port,
)

SPECTRAL_FOUR_FLUX_MODEL_ID = "backed_gradient_spectral_four_flux/v2"
SPECTRAL_FOUR_FLUX_FAMILY = "spectral_four_flux"
SPECTRAL_PARAMETERIZATION_ID = "color_k4_white_k_power_black_gray_s_power_forward/v1"
SPECTRAL_SURFACE_MODEL_ID = "fixed_n1p5_air45_front_air0_rear_once/v1"
SPECTRAL_INTERNAL_INTERFACES_ID = "touching_no_air"
SPECTRAL_OBSERVATION_MAPPING_ID = "fixed_measured_bare_W3_K3_once/v1"
_LOG_LOWER = np.log(1e-6)
_LOG_UPPER = np.log(200.)
_COLOR_FIELDS = (
    "log_absorption_450_nm", "log_absorption_516_67_nm",
    "log_absorption_583_33_nm", "log_absorption_650_nm",
    "log_scattering_550_nm", "scattering_power", "forward_fraction",
)
_WHITE_FIELDS = (
    "log_absorption_550_nm", "absorption_power", "log_scattering_550_nm",
    "scattering_power", "forward_fraction",
)
_BLACK_FIELDS = (
    "log_absorption_550_nm", "log_scattering_550_nm", "scattering_power", "forward_fraction",
)


def _parameter_fields(symbol: str) -> tuple[str, ...]:
    return _WHITE_FIELDS if symbol == "W" else _BLACK_FIELDS if symbol == "K" else _COLOR_FIELDS


def _validate_coefficients(symbol: str, source: Sequence[float]) -> np.ndarray:
    fields = _parameter_fields(symbol)
    try:
        values = np.asarray(source, dtype=float).copy()
    except (TypeError, ValueError) as error:
        raise CoreValidationError(f"Spectral material {symbol} coefficients must be numeric") from error
    if values.shape != (len(fields),) or not np.isfinite(values).all():
        raise CoreValidationError(f"Spectral material {symbol} needs {len(fields)} finite coefficients")
    for value, name in zip(values, fields, strict=True):
        lower, upper = (_LOG_LOWER, _LOG_UPPER) if name.startswith("log_") else (
            (-4., 4.) if name == "absorption_power" else (.05, .98) if name == "forward_fraction" else (0., 4.)
        )
        if value < lower - 1e-10 or value > upper + 1e-10:
            raise CoreValidationError(f"Spectral material {symbol} coefficient {name} is outside its fixed bounds")
    values.setflags(write=False)
    return values


def _xyz(source: Sequence[float], label: str) -> np.ndarray:
    try:
        values = np.asarray(source, dtype=float).copy()
    except (TypeError, ValueError) as error:
        raise CoreValidationError(f"{label} XYZ readings must be numeric") from error
    if values.shape != (3,) or not np.isfinite(values).all() or np.any(values < 0):
        raise CoreValidationError(f"{label} must contain three finite nonnegative XYZ readings")
    values.setflags(write=False)
    return values


@dataclass(frozen=True)
class BackedGradientTransport:
    """Propagate spectral direct/diffuse light before one measured-anchor map.
    先传播各波段的直射与漫射光，再应用一次实测裸底映射。

    Attributes:
        coefficients: R/Y/B/C/M/G use seven coefficients, W five, K four.
            （彩色材料七项系数、白色五项、黑色四项。）
        anchors: Measured bare-three-mm W/K report percentages.
            （裸三毫米白黑片实测报告百分数。）
        total_mm: Complete printed thickness, fixed at three mm.
            （完整打印厚度，固定三毫米。）
        fitted_materials: Materials available to recipe propagation.
            （可用于配方传播的已拟合材料。）
    """

    coefficients: Mapping[str, Sequence[float]]
    anchors: Mapping[str, Sequence[float]]
    total_mm: float = 3.
    fitted_materials: tuple[str, ...] = CORE_MATERIAL_SYMBOLS
    family: str = field(default=SPECTRAL_FOUR_FLUX_FAMILY, init=False)
    _basis: BoxSpectralBasis = field(init=False, repr=False, compare=False)
    _spectra: Mapping[str, tuple[np.ndarray, np.ndarray, float]] = field(init=False, repr=False, compare=False)
    _white_latent: np.ndarray = field(init=False, repr=False, compare=False)
    _black_latent: np.ndarray = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (not isinstance(self.coefficients, Mapping) or not isinstance(self.anchors, Mapping)
                or isinstance(self.total_mm, bool) or not isinstance(self.total_mm, (int, float))
                or not np.isfinite(self.total_mm)
                or abs(self.total_mm - 3.) > 1e-8):
            raise CoreValidationError("Spectral backed-gradient transport needs material coefficients and a three-mm sample")
        symbols = tuple(self.fitted_materials)
        if (len(set(symbols)) != len(symbols) or not {"W", "K"}.issubset(symbols)
                or any(symbol not in MATERIAL_SYMBOLS for symbol in symbols)
                or set(self.coefficients) != set(symbols)):
            raise CoreValidationError("Spectral coefficients must match unique fitted materials including W/K")
        coefficients = {symbol: _validate_coefficients(symbol, self.coefficients[symbol]) for symbol in symbols}
        try:
            anchors = {symbol: _xyz(self.anchors[symbol], f"Bare {symbol} anchor") for symbol in ("W", "K")}
        except KeyError as error:
            raise CoreValidationError("Both measured bare W/K anchors are required") from error
        if np.any(anchors["W"] <= anchors["K"]):
            raise CoreValidationError("Measured bare white XYZ must exceed bare black XYZ")
        basis = load_box_spectral_basis()
        object.__setattr__(self, "coefficients", MappingProxyType(coefficients))
        object.__setattr__(self, "anchors", MappingProxyType(anchors))
        object.__setattr__(self, "fitted_materials", symbols)
        object.__setattr__(self, "_basis", basis)
        object.__setattr__(self, "_spectra", MappingProxyType(self._expand_spectra()))
        white = self._whole_response(self._bulk_port("W", self.total_mm))
        black = self._whole_response(self._bulk_port("K", self.total_mm))
        if not np.isfinite(white).all() or not np.isfinite(black).all() or np.any(white - black <= 1e-9):
            raise CoreValidationError("Spectral latent bare-white/black contrast is singular")
        white.setflags(write=False)
        black.setflags(write=False)
        object.__setattr__(self, "_white_latent", white)
        object.__setattr__(self, "_black_latent", black)

    def _expand_spectra(self) -> dict[str, tuple[np.ndarray, np.ndarray, float]]:
        interpolation = self._basis.interpolation(self._basis.anchors)
        wavelength_ratio = self._basis.wavelengths / 550.
        result = {}
        for symbol, values in self.coefficients.items():
            if symbol == "W":
                absorption = np.exp(values[0]) * wavelength_ratio ** -values[1]
                scattering_log, scattering_power, forward = values[2:]
            elif symbol == "K":
                absorption = np.full(len(wavelength_ratio), np.exp(values[0]))
                scattering_log, scattering_power, forward = values[1:]
            else:
                absorption = np.exp(interpolation @ values[:4])
                scattering_log, scattering_power, forward = values[4:]
            scattering = np.exp(scattering_log) * wavelength_ratio ** -scattering_power
            absorption.setflags(write=False)
            scattering.setflags(write=False)
            result[symbol] = absorption, scattering, float(forward)
        return result

    def _bulk_port(self, symbol: str, thickness_mm: float | np.ndarray) -> OpticalPort:
        if symbol not in self.fitted_materials:
            raise CoreValidationError("Material is not fitted in this spectral model")
        thickness = np.asarray(thickness_mm, dtype=float)
        if not np.isfinite(thickness).all() or np.any(thickness < 0):
            raise CoreValidationError("Material thickness must be finite and nonnegative")
        absorption, scattering, forward = self._spectra[symbol]
        cosine = outer_surface_port(45.)[1]
        return material_bulk_port(absorption, scattering, forward, thickness[..., None], cosine)

    def _whole_response(self, bulk: OpticalPort) -> np.ndarray:
        front = outer_surface_port(45.)[0]
        rear = reverse_optical_port(outer_surface_port(0.)[0])
        whole = combine_optical_layers(combine_optical_layers(front, bulk), rear)
        return whole[0][..., 1, 0] @ self._basis.weights.T

    def _bulk_ports(self, materials: Sequence[str], thicknesses: np.ndarray) -> OpticalPort:
        shape = (len(materials), len(self._basis.wavelengths), 2, 2)
        result = tuple(np.empty(shape) for _ in range(4))
        symbols = np.asarray(materials)
        for symbol in self.fitted_materials:
            indices = np.flatnonzero(symbols == symbol)
            if indices.size:
                port = self._bulk_port(symbol, thicknesses[indices])
                for destination, value in zip(result, port, strict=True):
                    destination[indices] = value
        return result

    def _report(self, bulk: OpticalPort) -> np.ndarray:
        response = self._whole_response(bulk)
        white, black = self._white_latent, self._black_latent
        observed = self.anchors["K"] + (self.anchors["W"] - self.anchors["K"]) * (response - black) / (white - black)
        return np.maximum(observed, 0.)

    def predict_backed(self, material: str, backing: str,
                       overlay_mm: float | np.ndarray) -> np.ndarray:
        """Predict overlay d with its actual total-d printed backing.
        预测覆层 d 与实际总厚减 d 的实体打印背板。

        Args:
            material: Fitted overlay material.（已拟合覆层材料。）
            backing: W/K backing material.（白或黑背板材料。）
            overlay_mm: Nonnegative actual overlay thickness.（实际非负覆层厚度。）

        Returns:
            Whole-stack native percent XYZ with no upper clipping.
                （完整层组的设备 XYZ 百分数，不裁切上限。）
        """
        thickness = np.asarray(overlay_mm, dtype=float)
        if (backing not in ("W", "K") or not np.isfinite(thickness).all()
                or np.any(thickness < 0) or np.any(thickness > self.total_mm)):
            raise CoreValidationError("Backing must be W/K and overlay must remain within the complete sample")
        bulk = combine_optical_layers(self._bulk_port(material, thickness), self._bulk_port(backing, self.total_mm - thickness))
        return self._report(bulk)

    def predict_samples(self, materials: Sequence[str], backings: Sequence[str],
                        overlay_mm: Sequence[float] | np.ndarray) -> np.ndarray:
        """Predict varied samples with one batched whole-stack observation operation.
        以一次批量完整层组观测计算不同材料、底色和厚度的样片。

        Args:
            materials: Fitted overlay material for each sample.（每张样片的已拟合覆层材料。）
            backings: Actual W/K backing for each sample.（每张样片的实际白黑背板。）
            overlay_mm: Actual overlay thickness for each sample.（每张样片的实际覆层厚度。）

        Returns:
            Sample-by-three native percent XYZ.（样片数量乘三个通道的设备 XYZ 百分数。）
        """
        symbols, rear_symbols = tuple(materials), tuple(backings)
        try:
            thicknesses = np.asarray(overlay_mm, dtype=float)
        except (TypeError, ValueError) as error:
            raise CoreValidationError("Batched sample thicknesses must be numeric") from error
        if (thicknesses.shape != (len(symbols),) or len(rear_symbols) != len(symbols)
                or not np.isfinite(thicknesses).all() or np.any(thicknesses < 0)
                or np.any(thicknesses > self.total_mm)
                or any(symbol not in self.fitted_materials for symbol in symbols)
                or any(symbol not in ("W", "K") for symbol in rear_symbols)):
            raise CoreValidationError("Batched samples need matching fitted materials, W/K backings, and valid thicknesses")
        if not symbols:
            return np.empty((0, 3))
        bulk = combine_optical_layers(
            self._bulk_ports(symbols, thicknesses), self._bulk_ports(rear_symbols, self.total_mm - thicknesses),
        )
        return self._report(bulk)

    def predict_recipes(self, recipes_visible_to_back: Sequence[str], backing: str,
                        layer_mm: float = .08, *, backing_mm: float | None = None) -> np.ndarray:
        """Compose touching layers from the backing toward the observed face.
        从实体背板向测量面逐层组合，紧贴层间不插入空气界面。

        Args:
            recipes_visible_to_back: Material codes ordered from the observed face inward.
                （从测量面向内排列的材料代码。）
            backing: Actual W/K backing.（实际白黑背板。）
            layer_mm: Each upper layer thickness.（每个上部颜色层的厚度。）
            backing_mm: Optional actual backing for an independently specified printed object;
                bare anchors always remain three mm.（可选独立打印物体的实际背板厚度；裸锚仍为三毫米。）

        Returns:
            One whole-stack native percent XYZ per recipe.
                （每个配方对应的完整层组设备 XYZ 百分数。）
        """
        recipes = tuple(recipes_visible_to_back)
        if (not recipes or any(not isinstance(recipe, str) or not recipe for recipe in recipes)
                or len({len(recipe) for recipe in recipes}) != 1
                or any(code not in self.fitted_materials for recipe in recipes for code in recipe)):
            raise CoreValidationError("Recipes must have equal nonzero length and contain fitted materials")
        if isinstance(layer_mm, bool) or not np.isfinite(layer_mm) or layer_mm <= 0:
            raise CoreValidationError("Recipe layer thickness must be positive")
        actual_backing_mm = self.total_mm - len(recipes[0]) * layer_mm if backing_mm is None else backing_mm
        if (isinstance(actual_backing_mm, bool) or not isinstance(actual_backing_mm, (int, float))
                or not np.isfinite(actual_backing_mm) or actual_backing_mm <= 0 or backing not in ("W", "K")):
            raise CoreValidationError("A recipe must retain a positive W/K backing")
        shape = (len(recipes), len(self._basis.wavelengths), 2, 2)
        port = tuple(np.broadcast_to(value, shape).copy() for value in self._bulk_port(backing, actual_backing_mm))
        for column in range(len(recipes[0]) - 1, -1, -1):
            for symbol in self.fitted_materials:
                indices = np.array([index for index, recipe in enumerate(recipes) if recipe[column] == symbol], dtype=int)
                if indices.size:
                    rear = tuple(value[indices] for value in port)
                    combined = combine_optical_layers(self._bulk_port(symbol, layer_mm), rear)
                    for destination, value in zip(port, combined, strict=True):
                        destination[indices] = value
        return self._report(port)

    def to_parameters(self) -> dict:
        """Export the independent spectral schema and fixed observation boundaries.
        导出独立光谱参数格式以及固定测量边界。

        Returns:
            Portable versioned parameters, without pretending to be XYZ K/S.
                （可移植带版本光谱参数，不冒充 XYZ 吸收散射系数。）
        """
        span = self._white_latent - self._black_latent
        return {
            "family": self.family, "model_id": SPECTRAL_FOUR_FLUX_MODEL_ID,
            "parameterization": SPECTRAL_PARAMETERIZATION_ID,
            "basis_id": LUMINA_BOX_SPECTRAL_BASIS_ID, "total_mm": self.total_mm,
            "fitted_materials": list(self.fitted_materials),
            "materials": {symbol: dict(zip(_parameter_fields(symbol), values.tolist(), strict=True))
                          for symbol, values in self.coefficients.items()},
            "reference_anchors": {symbol: values.tolist() for symbol, values in self.anchors.items()},
            "surface_model": SPECTRAL_SURFACE_MODEL_ID,
            "internal_interfaces": SPECTRAL_INTERNAL_INTERFACES_ID,
            "observation_mapping": SPECTRAL_OBSERVATION_MAPPING_ID,
            "native_black_floor": True,
            "latent_reference_xyz": {"W": self._white_latent.tolist(), "K": self._black_latent.tolist()},
            "observation_scale_gain_pp": ((self.anchors["W"] - self.anchors["K"]) / span).tolist(),
        }

    @classmethod
    def from_parameters(cls, payload: Mapping) -> BackedGradientTransport:
        """Restore only this spectral version without consulting active material archives.
        仅恢复当前光谱版本，不读取活动耗材档案。

        Args:
            payload: Complete versioned spectral coefficients.（完整带版本光谱参数。）

        Returns:
            Validated independent propagation model.（通过校验的独立传播模型。）
        """
        if (not isinstance(payload, Mapping) or payload.get("family") != SPECTRAL_FOUR_FLUX_FAMILY
                or payload.get("model_id") != SPECTRAL_FOUR_FLUX_MODEL_ID
                or payload.get("parameterization") != SPECTRAL_PARAMETERIZATION_ID
                or payload.get("basis_id") != LUMINA_BOX_SPECTRAL_BASIS_ID
                or payload.get("surface_model") != SPECTRAL_SURFACE_MODEL_ID
                or payload.get("internal_interfaces") != SPECTRAL_INTERNAL_INTERFACES_ID
                or payload.get("observation_mapping") != SPECTRAL_OBSERVATION_MAPPING_ID
                or payload.get("native_black_floor") is not True):
            raise CoreValidationError("Unsupported backed-gradient spectral parameter record")
        try:
            if not isinstance(payload["fitted_materials"], (list, tuple)) or not isinstance(payload["materials"], Mapping):
                raise CoreValidationError("Spectral materials must be declared explicitly")
            symbols = tuple(payload["fitted_materials"])
            if set(payload["materials"]) != set(symbols):
                raise CoreValidationError("Declared spectral materials do not match their coefficient records")
            if any(not isinstance(payload["materials"][symbol], Mapping)
                   or set(payload["materials"][symbol]) != set(_parameter_fields(symbol)) for symbol in symbols):
                raise CoreValidationError("Spectral material coefficient fields do not match this version")
            coefficients = {symbol: [payload["materials"][symbol][name] for name in _parameter_fields(symbol)] for symbol in symbols}
            return cls(coefficients, payload["reference_anchors"], float(payload["total_mm"]), symbols)
        except (KeyError, TypeError, ValueError) as error:
            raise CoreValidationError("Incomplete backed-gradient spectral coefficients") from error
