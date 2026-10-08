"""Independent material components using the retained v3 optical physics.
独立耗材组件，沿用第三版黑白底光学传播。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import json
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence

import numpy as np

from core.backed_gradient_smooth import BackedGradientSmoothTransport, SPECTRAL_SMOOTH_MODEL_ID
from core.backed_gradient_transport import _validate_coefficients
from core.errors import CoreValidationError
from core.lumina_box_spectral import load_box_spectral_basis
from core.lumina_box_transport import OpticalPort, combine_optical_layers, material_bulk_port, outer_surface_port

BACKED_GRADIENT_PROTOCOL_ID = "lumina_box_backed_gradient/v1"
_KIND_SYMBOL = {"color": "R", "white": "W", "black": "K"}


@dataclass(frozen=True)
class BackedGradientComponent:
    """One material's coefficients, independent of palette slot or backing role.
    单个耗材的系数，与调色板槽位和背板身份无关。

    Attributes:
        kind: Physical parameter family.（物理参数类型。）
        coefficients: V3 coefficients in their original order.（原顺序的第三版系数。）
    """

    kind: Literal["color", "white", "black"]
    coefficients: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.kind not in _KIND_SYMBOL:
            raise CoreValidationError("Choose a color, white, or black material")
        values = _validate_coefficients(_KIND_SYMBOL[self.kind], self.coefficients)
        object.__setattr__(self, "coefficients", tuple(float(value) for value in values))

    def to_dict(self) -> dict[str, Any]:
        """Serialize one portable component. / 序列化单个可移植组件。

        Returns:
            Kind and ordered coefficients.（类型与有序系数。）
        """
        return {"kind": self.kind, "coefficients": list(self.coefficients)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> BackedGradientComponent:
        """Restore one component. / 恢复单个组件。

        Args:
            payload: Saved component.（已保存组件。）
        Returns:
            Immutable component.（不可变组件。）
        """
        try:
            return cls(payload["kind"], tuple(payload["coefficients"]))
        except (KeyError, TypeError, ValueError) as error:
            raise CoreValidationError("Invalid backed-gradient material coefficients") from error


@dataclass(frozen=True)
class BackedGradientReference:
    """Reusable physical backings and a common measured observation scale.
    可复用的实体背板和共同实测观测尺度。

    Attributes:
        reference_id: Immutable calibration identity.（不可变标定标识。）
        white: Actual white backing.（实际白背板。）
        black: Actual black backing.（实际黑背板。）
        anchors: Measured three-mm bare W/K XYZ percentages.（三毫米裸底 XYZ 百分数。）
        source: Original calibration provenance and readings.（标定来源与原始读数。）
    """

    reference_id: str
    white: BackedGradientComponent
    black: BackedGradientComponent
    anchors: Mapping[str, Sequence[float]]
    source: Mapping[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self) -> None:
        if not self.reference_id or self.white.kind != "white" or self.black.kind != "black":
            raise CoreValidationError("A backing calibration needs its saved white and black materials")
        try:
            anchors = {key: tuple(float(v) for v in self.anchors[key]) for key in ("W", "K")}
            values = np.asarray([anchors["W"], anchors["K"]])
        except (KeyError, TypeError, ValueError) as error:
            raise CoreValidationError("A backing calibration needs both bare XYZ references") from error
        if (values.shape != (2, 3) or not np.isfinite(values).all() or np.any(values < 0)
                or np.any(values[0] <= values[1])):
            raise CoreValidationError("Bare white XYZ must exceed finite nonnegative bare black XYZ")
        object.__setattr__(self, "anchors", MappingProxyType(anchors))
        object.__setattr__(self, "source", MappingProxyType(json.loads(json.dumps(dict(self.source), allow_nan=False))))

    def to_dict(self) -> dict[str, Any]:
        """Export a self-contained calibration. / 导出自包含标定。

        Returns:
            Physical reference and provenance.（实体参考与来源。）
        """
        return {"schema_version": "1.0", "model_id": SPECTRAL_SMOOTH_MODEL_ID,
                "reference_id": self.reference_id, "white": self.white.to_dict(), "black": self.black.to_dict(),
                "anchors": {key: list(value) for key, value in self.anchors.items()},
                "source": json.loads(json.dumps(dict(self.source), allow_nan=False))}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> BackedGradientReference:
        """Restore the saved physical calibration. / 恢复保存的实体标定。

        Args:
            payload: Portable reference.（可移植参考。）
        Returns:
            Independent immutable reference.（独立不可变参考。）
        """
        try:
            if payload["model_id"] != SPECTRAL_SMOOTH_MODEL_ID or payload["schema_version"] != "1.0":
                raise CoreValidationError("Unsupported backed-gradient calibration")
            return cls(payload["reference_id"], BackedGradientComponent.from_dict(payload["white"]),
                       BackedGradientComponent.from_dict(payload["black"]), payload["anchors"], payload.get("source", {}))
        except (KeyError, TypeError, ValueError) as error:
            raise CoreValidationError("Incomplete backed-gradient calibration") from error


def reference_from_parameters(parameters: Mapping[str, Any], *, source: Mapping[str, Any] | None = None) -> BackedGradientReference:
    """Freeze the W/K calibration of an existing complete v3 result.
    冻结已有完整第三版结果的黑白背板标定。

    Args:
        parameters: Existing v3 parameters.（已有第三版参数。）
        source: Retained input provenance.（保留的输入来源。）
    Returns:
        Shared calibration with unchanged physics.（物理参数不变的共享标定。）
    """
    model = BackedGradientSmoothTransport.from_parameters(parameters)
    white = BackedGradientComponent("white", tuple(model.coefficients["W"]))
    black = BackedGradientComponent("black", tuple(model.coefficients["K"]))
    anchors = {key: values.tolist() for key, values in model.anchors.items()}
    identity = {"model_id": SPECTRAL_SMOOTH_MODEL_ID, "white": white.to_dict(), "black": black.to_dict(), "anchors": anchors}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    provenance = dict(source or {})
    provenance.setdefault("calibration_stage", "joint")
    provenance.setdefault("established", True)
    return BackedGradientReference(digest, white, black, anchors, provenance)


def component_from_parameters(parameters: Mapping[str, Any], material_symbol: str) -> BackedGradientComponent:
    """Extract a material without refitting. / 提取耗材，不重新拟合。

    Args:
        parameters: Existing v3 parameters.（已有第三版参数。）
        material_symbol: Original material key.（原耗材键。）
    Returns:
        Independent component.（独立组件。）
    """
    model = BackedGradientSmoothTransport.from_parameters(parameters)
    if material_symbol not in model.coefficients:
        raise CoreValidationError("Material is missing from the saved fit")
    kind = "white" if material_symbol == "W" else "black" if material_symbol == "K" else "color"
    return BackedGradientComponent(kind, tuple(model.coefficients[material_symbol]))


@lru_cache(maxsize=256)
def _spectra(component: BackedGradientComponent) -> tuple[np.ndarray, np.ndarray, float]:
    basis = load_box_spectral_basis()
    values = np.asarray(component.coefficients)
    ratio = basis.wavelengths / 550.
    if component.kind == "white":
        absorption = np.exp(values[0]) * ratio ** -values[1]
        scattering_log, power, forward = values[2:]
    elif component.kind == "black":
        absorption = np.full(len(ratio), np.exp(values[0]))
        scattering_log, power, forward = values[1:]
    else:
        absorption = np.exp(basis.interpolation(basis.anchors) @ values[:4])
        scattering_log, power, forward = values[4:]
    scattering = np.exp(scattering_log) * ratio ** -power
    absorption.setflags(write=False)
    scattering.setflags(write=False)
    return absorption, scattering, float(forward)


@lru_cache(maxsize=128)
def _cached_bulk(component: BackedGradientComponent, shape: tuple[int, ...], values: tuple[float, ...]) -> OpticalPort:
    absorption, scattering, forward = _spectra(component)
    thickness = np.asarray(values).reshape(shape)
    port = material_bulk_port(absorption, scattering, forward, thickness[..., None], outer_surface_port(45.)[1])
    for value in port:
        value.setflags(write=False)
    return port


def _bulk(component: BackedGradientComponent, thickness: float | np.ndarray) -> OpticalPort:
    values = np.asarray(thickness, dtype=float)
    return _cached_bulk(component, values.shape, tuple(values.ravel()))


class BackedGradientMaterialModel:
    """Compose independently saved materials by slot with one shared observation map.
    按槽位组合独立耗材，只应用一次共同观测映射。

    Args:
        reference: Shared physical backing calibration.（共享实体背板标定。）
        backings: Optional actual backing components, independent of the observation
            calibration.（可选实际背板组件，与观测标定分开保存。）
    """

    def __init__(self, reference: BackedGradientReference,
                 backings: Mapping[str, BackedGradientComponent | Mapping[str, Any]] | None = None) -> None:
        self.reference = reference
        if backings is None:
            actual_backings = {"W": reference.white, "K": reference.black}
        else:
            if not isinstance(backings, Mapping) or set(backings) != {"W", "K"}:
                raise CoreValidationError("Choose the actual white and black backing materials")
            actual_backings = {
                role: value if isinstance(value, BackedGradientComponent) else BackedGradientComponent.from_dict(value)
                for role, value in backings.items()
            }
        self.backings = MappingProxyType(actual_backings)
        self._reporter = BackedGradientSmoothTransport(
            {"W": reference.white.coefficients, "K": reference.black.coefficients},
            reference.anchors, fitted_materials=("W", "K"),
        )
        self._backing_ports: dict[tuple[str, tuple[int, ...], tuple[float, ...]], OpticalPort] = {}

    def predict_backed(self, component: BackedGradientComponent, backing: str,
                       overlay_mm: float | np.ndarray) -> np.ndarray:
        """Predict an overlay on its actual three-minus-overlay backing.
        预测覆层及实际三毫米减覆层厚度的背板。

        Args:
            component: Overlay material.（覆层耗材。）
            backing: W or K actual selected backing.（实际选用的白或黑背板。）
            overlay_mm: Actual overlay thickness.（实际覆层厚度。）
        Returns:
            Native percent XYZ, without upper clipping.（原始百分比 XYZ，不裁切上限。）
        """
        thickness = np.asarray(overlay_mm, dtype=float)
        if backing not in ("W", "K") or not np.isfinite(thickness).all() or np.any(thickness < 0) or np.any(thickness > 3):
            raise CoreValidationError("Overlay thickness must remain within the three-mm black/white sample")
        key = (backing, thickness.shape, tuple(thickness.ravel()))
        if key not in self._backing_ports:
            material = self.backings[backing]
            self._backing_ports[key] = _bulk(material, 3. - thickness)
        return self._reporter._report(combine_optical_layers(_bulk(component, thickness), self._backing_ports[key]))

    def predict_recipes(self, materials: Sequence[BackedGradientComponent], recipes: np.ndarray,
                        layer_mm: float, *, backing: BackedGradientComponent, backing_mm: float) -> np.ndarray:
        """Predict bottom-to-top recipes, batching and reusing repeated prefixes.
        预测由底至面的配方，批量复用重复的层组前缀。

        Args:
            materials: Components in user slot order.（用户槽位顺序的组件。）
            recipes: Integer recipe matrix, first column adjacent to backing.（整数配方矩阵，首列贴背板。）
            layer_mm: Physical color-layer height.（实际颜色层厚。）
            backing: Actual printed backing component.（实际打印背板组件。）
            backing_mm: Physical backing thickness.（实际背板厚度。）
        Returns:
            Floating percent XYZ per recipe.（每个配方的浮点百分比 XYZ。）
        """
        rows = np.asarray(recipes)
        if (rows.ndim != 2 or rows.dtype.kind not in "iu" or not materials
                or np.any(rows < 0) or np.any(rows >= len(materials))):
            raise CoreValidationError("Recipes must contain valid material slot indices")
        rows = rows.astype(np.intp, copy=False)
        if not np.isfinite([layer_mm, backing_mm]).all() or layer_mm <= 0 or backing_mm <= 0:
            raise CoreValidationError("Printed layer and backing thickness must be positive")
        output = np.empty((len(rows), 3))
        layers = [_bulk(material, float(layer_mm)) for material in materials]
        layer_ports = tuple(np.stack([port[index] for port in layers]) for index in range(4))
        base = _bulk(backing, float(backing_mm))
        for start in range(0, len(rows), 2048):
            block = rows[start:start + 2048]
            prefix = np.zeros(len(block), dtype=np.int64)
            ports = tuple(value[None, ...] for value in base)
            for column in range(block.shape[1]):
                codes, inverse = np.unique(prefix * len(materials) + block[:, column], return_inverse=True)
                rear = tuple(value[codes // len(materials)] for value in ports)
                front = tuple(value[codes % len(materials)] for value in layer_ports)
                ports = combine_optical_layers(front, rear)
                prefix = inverse
            output[start:start + len(block)] = self._reporter._report(ports)[prefix]
        return output
