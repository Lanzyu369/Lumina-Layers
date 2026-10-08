"""The retained Lumina Box spectral model and its immutable calibration.
已保留的 Lumina Box 波段模型及不可变白参考。

This is the engineering adoption of equal_xyz_v1, not another optical trial.
本模块落实 equal_xyz_v1 的计算，不加入新的光学试验假设。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import nnls, root

from config import get_asset_path
from core.km_xyz import KM_XYZ_COLOR_BRIDGE_ID, KM_XYZ_MEASUREMENT_PROTOCOL_ID
from core.lumina_box_transport import (
    OpticalPort,
    combine_optical_layers,
    material_bulk_port,
    outer_surface_port,
    reverse_optical_port,
)

LUMINA_BOX_SPECTRAL_MODEL_ID = "box_reference_consistent_feedback/equal_xyz_v1"
LUMINA_BOX_SPECTRAL_BASIS_ID = "cie1931_d65_normalized_xyz_5nm/v1"
LUMINA_BOX_SPECTRAL_OBJECTIVE_ID = "box_spectral_paired_equal_xyz/v1"
LUMINA_BOX_GRAY_WHITE_OBJECTIVE_ID = "box_spectral_paired_physical_white/v2"
LUMINA_BOX_CONSTRAINED_OBJECTIVE_ID = "box_spectral_paired_spectral_white/v3"
LUMINA_BOX_PHYSICAL_WHITE_OBJECTIVE_IDS = frozenset({
    LUMINA_BOX_GRAY_WHITE_OBJECTIVE_ID, LUMINA_BOX_CONSTRAINED_OBJECTIVE_ID,
})
LUMINA_BOX_SUPPORTED_OBJECTIVE_IDS = frozenset({
    LUMINA_BOX_SPECTRAL_OBJECTIVE_ID, *LUMINA_BOX_PHYSICAL_WHITE_OBJECTIVE_IDS,
})
LUMINA_BOX_DEFAULT_REFERENCE_MIN_REFLECTANCE = 0.95
LUMINA_BOX_SPECTRAL_BOUNDARY_ID = "instrument_diffuser_recycled_white_reference/v1"
LUMINA_BOX_REFERENCE_THICKNESS_MM = 3.0
LUMINA_BOX_REFERENCE_REFLECTANCE = 0.98
LUMINA_BOX_DEFAULT_BASE_MM = 1.2
LUMINA_BOX_PREDICTION_BATCH_SIZE = 256


class LuminaBoxModelError(ValueError):
    """Invalid model inputs or incompatible reference data.
    模型输入或白参考数据无效。
    """


class LuminaBoxReferenceError(LuminaBoxModelError):
    """The measurement geometry has no physical white-reference solution.
    测量几何无法得到满足物理范围的白参考。
    """


def validate_reference_reflectance_minimum(value: Any) -> float:
    """Validate an operator-supplied lower bound, separate from the 98% scale.
    校验操作者提供的反射率下限，与设备的 98% 标定比例分开处理。

    Args:
        value: Known minimum total white reflectance Y as a ratio.
            （已知白片总反射率 Y 的最低比值。）

    Returns:
        A finite ratio in (0, 1].（范围 (0, 1] 内的有限比值。）
    """
    if (
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, (int, float, np.integer, np.floating))
        or not np.isfinite(value) or not 0.0 < value <= 1.0
    ):
        raise LuminaBoxModelError("Known minimum white reflectance must be in (0, 1]")
    return float(value)


def _finite_vector(value: Any, size: int, label: str) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise LuminaBoxModelError(f"{label} must contain {size} finite numbers") from exc
    if array.shape != (size,) or not np.isfinite(array).all():
        raise LuminaBoxModelError(f"{label} must contain {size} finite numbers")
    result = array.copy()
    result.setflags(write=False)
    return result


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SpectralMaterialParameters:
    """Frozen ordered coefficients used by the adopted eight-value model.
    已采用模型中顺序固定的八个系数。

    The first four values are log absorption at the fixed wavelength anchors;
    the next values are log scattering strength, scattering power, forward
    fraction, and measurement-only diffuser coupling.
    前四项为固定波长节点的吸收对数，其后为散射强度对数、散射指数、前向比例，
    最后一项为仅用于测量回算的匀光板耦合。
    """

    values: np.ndarray

    def __post_init__(self) -> None:
        values = _finite_vector(self.values, 8, "spectral parameters")
        if (
            np.any(values[:5] < np.log(1e-10) - 1e-9)
            or np.any(values[:5] > np.log(1e4) + 1e-9)
            or not 0.0 <= values[5] <= 4.0
            or not 0.05 <= values[6] <= 0.98
            or values[7] < 0.0
        ):
            raise LuminaBoxModelError("Spectral coefficients exceed the adopted model bounds")
        object.__setattr__(self, "values", values)

    def to_dict(self) -> dict[str, Any]:
        """Export explicitly named coefficients without an XYZ K/S surrogate.
        导出具名系数，不伪造 XYZ 通道的 K/S 替代值。

        Returns:
            Versioned, finite JSON parameter fields.（带版本的有限 JSON 系数字段。）
        """
        return {
            "parameterization": "log_absorption4_log_scattering_power_forward_coupling/v1",
            "log_absorption_anchors": self.values[:4].tolist(),
            "log_scattering_strength": float(self.values[4]),
            "scattering_power": float(self.values[5]),
            "forward_scattering_fraction": float(self.values[6]),
            "measurement_backing_scale": float(self.values[7]),
            "unit": "mm^-1",
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SpectralMaterialParameters:
        """Validate and load the complete versioned parameter record.
        校验并加载完整的带版本系数记录。

        Args:
            payload: Parameter record from a fit or archive.（拟合或档案中的系数记录。）

        Returns:
            Immutable validated coefficients.（不可变的已校验系数。）
        """
        if not isinstance(payload, Mapping) or set(payload) != {
            "parameterization", "log_absorption_anchors", "log_scattering_strength",
            "scattering_power", "forward_scattering_fraction", "measurement_backing_scale", "unit",
        }:
            raise LuminaBoxModelError("Spectral parameter record has an invalid shape")
        if (
            payload["parameterization"] != "log_absorption4_log_scattering_power_forward_coupling/v1"
            or payload["unit"] != "mm^-1"
        ):
            raise LuminaBoxModelError("Unsupported spectral parameter version or unit")
        anchors = _finite_vector(payload["log_absorption_anchors"], 4, "log absorption anchors")
        return cls(np.r_[anchors, [payload[key] for key in (
            "log_scattering_strength", "scattering_power", "forward_scattering_fraction",
            "measurement_backing_scale",
        )]])


@dataclass(frozen=True)
class BoxSpectralBasis:
    """Fixed, positive D65/CIE integration weights and absorption anchors.
    固定的正值 D65/CIE 积分权重与吸收节点。
    """

    wavelengths: np.ndarray
    weights: np.ndarray
    anchors: np.ndarray

    def __post_init__(self) -> None:
        wavelength = _finite_vector(self.wavelengths, 95, "wavelength grid")
        anchors = _finite_vector(self.anchors, 4, "absorption anchors")
        weights = np.asarray(self.weights, dtype=np.float64).copy()
        if (
            weights.shape != (3, 95)
            or not np.isfinite(weights).all()
            or np.any(weights < 0.0)
            or not np.array_equal(wavelength, np.arange(360.0, 835.0, 5.0))
            or not np.array_equal(anchors, np.linspace(450.0, 650.0, 4))
            or not np.allclose(weights.sum(axis=1), 1.0, atol=1e-12, rtol=0.0)
        ):
            raise LuminaBoxModelError("Invalid fixed Box spectral basis")
        weights.setflags(write=False)
        object.__setattr__(self, "wavelengths", wavelength)
        object.__setattr__(self, "anchors", anchors)
        object.__setattr__(self, "weights", weights)

    def interpolation(self, anchors: np.ndarray) -> np.ndarray:
        """Return linear wavelength interpolation weights.
        返回波长方向的线性插值权重。

        Args:
            anchors: Increasing wavelength anchors.（递增波长节点。）

        Returns:
            Wavelength-by-anchor interpolation matrix.（波长到节点的插值矩阵。）
        """
        return np.column_stack([
            np.interp(self.wavelengths, anchors, row) for row in np.eye(len(anchors))
        ])

    def optics(self, parameters: SpectralMaterialParameters) -> tuple[np.ndarray, np.ndarray]:
        """Expand the retained coefficients into wavelength-specific K/S.
        将已保留系数展开为各波长的吸收和散射。

        Args:
            parameters: Validated model coefficients.（已校验模型系数。）

        Returns:
            Absorption and scattering in inverse millimetres.（每毫米的吸收与散射。）
        """
        values = parameters.values
        absorption = np.exp(self.interpolation(self.anchors) @ values[:4])
        scattering = np.exp(values[4]) * (self.wavelengths / 550.0) ** (-values[5])
        return absorption, scattering

    def diffuser(self, relative_xyz: np.ndarray) -> np.ndarray:
        """Recover the fixed three-anchor measurement diffuser spectrum.
        按固定三个节点重建测量匀光板的波段响应。

        Args:
            relative_xyz: Physical, reference-corrected backing response.
                （已还原白参考的物理底板响应。）

        Returns:
            Non-negative spectral backing response.（非负波段底板响应。）
        """
        xyz = _finite_vector(relative_xyz, 3, "measurement backing")
        interpolation = self.interpolation(np.array([450.0, 550.0, 650.0]))
        amplitudes, _ = nnls(self.weights @ interpolation, xyz)
        response = interpolation @ amplitudes
        if response.max() <= 0.0 or not np.allclose(self.weights @ response, xyz, atol=1e-10):
            raise LuminaBoxModelError("The fixed diffuser model cannot represent its measured XYZ")
        return response


@lru_cache(maxsize=1)
def load_box_spectral_basis() -> BoxSpectralBasis:
    """Load the bundled, frozen basis without any experiment-folder dependency.
    加载随软件分发的固定积分权重，不依赖试验目录。

    Returns:
        Immutable adopted integration basis.（不可变的已采用积分基准。）
    """
    path = Path(get_asset_path("colorimetry/lumina_box_d65_5nm.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("basis_id") != LUMINA_BOX_SPECTRAL_BASIS_ID:
        raise LuminaBoxModelError("Unsupported Box spectral basis version")
    return BoxSpectralBasis(
        payload["wavelengths_nm"], payload["xyz_weights"], payload["absorption_anchors_nm"]
    )


@dataclass(frozen=True)
class BoxWhiteReference:
    """Portable white calibration shared by compatible material archives.
    兼容耗材档案共同使用的可迁移白参考。
    """

    white_parameters: SpectralMaterialParameters
    relative_xyz: np.ndarray
    backing_base_relative_xyz: np.ndarray
    measurement_sha256: str
    minimum_total_reflectance_y: float | None = None

    def __post_init__(self) -> None:
        xyz = _finite_vector(self.relative_xyz, 3, "white reference XYZ")
        backing = _finite_vector(self.backing_base_relative_xyz, 3, "white reference backing")
        if np.any(xyz <= 1e-8) or np.any(xyz > 1.0 + 1e-8):
            raise LuminaBoxModelError("White reference XYZ must be in (0, 1]")
        if np.any(backing <= 0.0) or np.any(backing > 1.0):
            raise LuminaBoxModelError("White reference backing must be in (0, 1]")
        if (
            not isinstance(self.measurement_sha256, str)
            or len(self.measurement_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.measurement_sha256)
        ):
            raise LuminaBoxModelError("White reference requires a measurement SHA-256")
        object.__setattr__(self, "relative_xyz", xyz)
        object.__setattr__(self, "backing_base_relative_xyz", backing)
        if self.minimum_total_reflectance_y is not None:
            minimum = validate_reference_reflectance_minimum(self.minimum_total_reflectance_y)
            object.__setattr__(self, "minimum_total_reflectance_y", minimum)
            LuminaBoxSpectralModel().validate_reference_physics(self)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the complete reference and a content-derived identity.
        序列化完整白参考及由内容决定的标识。

        Returns:
            Self-contained calibration data.（自包含的校准数据。）
        """
        payload = {
            "model_id": LUMINA_BOX_SPECTRAL_MODEL_ID,
            "basis_id": LUMINA_BOX_SPECTRAL_BASIS_ID,
            "white_parameters": self.white_parameters.to_dict(),
            "relative_xyz": self.relative_xyz.tolist(),
            "backing_base_relative_xyz": self.backing_base_relative_xyz.tolist(),
            "measurement_sha256": self.measurement_sha256,
            "thickness_mm": LUMINA_BOX_REFERENCE_THICKNESS_MM,
            "assigned_reflectance": LUMINA_BOX_REFERENCE_REFLECTANCE,
        }
        if self.minimum_total_reflectance_y is not None:
            payload["minimum_total_reflectance_y"] = self.minimum_total_reflectance_y
        return {**payload, "reference_id": _canonical_hash(payload)}

    @property
    def reference_id(self) -> str:
        """Return the stable shared-calibration identity. 返回稳定的共同校准标识。"""
        return self.to_dict()["reference_id"]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> BoxWhiteReference:
        """Validate a complete reference without loading another material archive.
        校验完整白参考，无需再次读取其他耗材档案。

        Args:
            payload: Serialized reference.（序列化白参考。）

        Returns:
            Validated immutable reference.（已校验的不可变白参考。）
        """
        expected = {
            "model_id", "basis_id", "white_parameters", "relative_xyz", "backing_base_relative_xyz",
            "measurement_sha256", "thickness_mm", "assigned_reflectance", "reference_id",
        }
        if not isinstance(payload, Mapping) or set(payload) not in (
            expected, expected | {"minimum_total_reflectance_y"},
        ):
            raise LuminaBoxModelError("Incomplete white reference record")
        result = cls(
            SpectralMaterialParameters.from_dict(payload["white_parameters"]),
            payload["relative_xyz"], payload["backing_base_relative_xyz"], payload["measurement_sha256"],
            payload.get("minimum_total_reflectance_y"),
        )
        if result.to_dict() != dict(payload):
            raise LuminaBoxModelError("White reference version or content identity does not match")
        return result


class LuminaBoxSpectralModel:
    """Shared measurement and touching-layer forward calculation.
    统一的测量回算及紧贴材料层正向计算。
    """

    def __init__(self, basis: BoxSpectralBasis | None = None) -> None:
        self.basis = basis or load_box_spectral_basis()
        self.reflection_boundary, self.reflection_cosine = outer_surface_port(45.0)
        self.transmission_boundary, self.transmission_cosine = outer_surface_port(0.0)

    def bulk(
        self, parameters: SpectralMaterialParameters, thickness_mm: np.ndarray | float,
        *, reflection: bool = True,
    ) -> OpticalPort:
        """Calculate material bulk with no inserted internal air surfaces.
        计算材料内部传播，不加入内部空气表面。

        Args:
            parameters: Validated material.（已校验材料。）
            thickness_mm: Physical thickness.（实际厚度。）
            reflection: Select the fixed observation direction.（选择固定观察方向。）

        Returns:
            Bulk transport port.（材料体光传输矩阵。）
        """
        k, s = self.basis.optics(parameters)
        cosine = self.reflection_cosine if reflection else self.transmission_cosine
        return material_bulk_port(k, s, float(parameters.values[6]), thickness_mm, cosine)

    def slab(
        self, parameters: SpectralMaterialParameters, thickness_mm: np.ndarray | float,
        *, reflection: bool = True,
    ) -> OpticalPort:
        """Add outside air/plastic surfaces around one continuous slab.
        在一整块连续材料的外侧加入空气与塑料界面。

        Args:
            parameters: Validated material.（已校验材料。）
            thickness_mm: Broadcastable physical thickness.（可广播实际厚度。）
            reflection: Select reflection or transmission geometry.（选择反射或透射几何。）

        Returns:
            Complete slab port.（完整样片矩阵。）
        """
        front = self.reflection_boundary if reflection else self.transmission_boundary
        bulk = self.bulk(parameters, thickness_mm, reflection=reflection)
        return combine_optical_layers(combine_optical_layers(front, bulk), reverse_optical_port(front))

    def reference_xyz(
        self, parameters: SpectralMaterialParameters, backing_base: np.ndarray,
    ) -> np.ndarray:
        """Solve the measured three-millimetre white reference self-consistently.
        自洽求解测量中的三毫米白片参考。

        Args:
            parameters: White-material parameters.（白色材料系数。）
            backing_base: Instrument-normalized diffuser ratios.（仪器归一化匀光板比值。）

        Returns:
            Physical reference response before reference normalization.
            （白参考归一化之前的物理响应。）
        """
        backing_base = _finite_vector(backing_base, 3, "measurement backing")
        r, rb, tf, tb = self.slab(parameters, np.array([[LUMINA_BOX_REFERENCE_THICKNESS_MM]]))
        intrinsic = r[0, :, 1, 0]
        factor = tb[0, :, 1, 1] * tf[0, :, :, 0].sum(axis=-1)
        return_r = rb[0, :, 1, 1]
        interpolation = self.basis.interpolation(np.array([450.0, 550.0, 650.0]))
        inverse = np.linalg.inv(self.basis.weights @ interpolation)
        coupling = (
            parameters.values[7] * interpolation @ inverse
            @ np.diag(backing_base / LUMINA_BOX_REFERENCE_REFLECTANCE)
        )

        def equation(q: np.ndarray) -> np.ndarray:
            backing = coupling @ q
            reflected = intrinsic + factor * backing / (1.0 - return_r * backing)
            return q - self.basis.weights @ reflected

        def jacobian(q: np.ndarray) -> np.ndarray:
            backing = coupling @ q
            derivative = factor / (1.0 - return_r * backing) ** 2
            return np.eye(3) - (self.basis.weights * derivative[None, :]) @ coupling

        solved = root(equation, np.full(3, 0.8), jac=jacobian, tol=1e-10)
        q = solved.x
        backing = coupling @ q
        if (
            not np.isfinite(q).all() or np.max(np.abs(equation(q))) > 1e-8
            or np.min(q) <= 1e-8 or np.max(q) > 1.0 + 1e-8
            or np.min(backing) < -1e-8 or np.max(backing) > 1.0 + 1e-8
        ):
            raise LuminaBoxReferenceError("No physical white-reference solution for these parameters")
        return q

    def reference_energy_xyz(
        self, parameters: SpectralMaterialParameters,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return bare-white total reflection, transmission, and absorption.
        返回裸白片的总反射、总透射和吸收，包含镜面反射且不含仪器底板。

        Args:
            parameters: White-material coefficients.（白色材料系数。）

        Returns:
            Physical XYZ ratios at the reference thickness and reflection
            illumination.（参考厚度、反射照明条件下的物理 XYZ 比值。）
        """
        reflected, _, transmitted, _ = self.slab(parameters, LUMINA_BOX_REFERENCE_THICKNESS_MM)
        reflection = reflected[..., :, 0].sum(axis=-1) @ self.basis.weights.T
        transmission = transmitted[..., :, 0].sum(axis=-1) @ self.basis.weights.T
        return reflection, transmission, 1.0 - reflection - transmission

    def validate_reference_physics(
        self, reference: BoxWhiteReference, *, require_constraint: bool = False,
    ) -> None:
        """Reject a calibration fit that violates its known white property.
        拒绝违反已知白片物性的校准拟合；历史记录可以保持只读兼容。

        Args:
            reference: Complete saved calibration.（完整保存的白参考。）
            require_constraint: Require the operator's lower bound for active
                fitting or prediction.（用于当前拟合或预测时要求物性下限。）
        """
        minimum = reference.minimum_total_reflectance_y
        if minimum is None:
            if require_constraint:
                raise LuminaBoxReferenceError(
                    "Refit the calibration white with its known reflectance lower bound, "
                    "then refit materials that use this reference"
                )
            return
        reflection, transmission, absorption = self.reference_energy_xyz(reference.white_parameters)
        if (
            not all(np.isfinite(value).all() for value in (reflection, transmission, absorption))
            or min(np.min(value) for value in (reflection, transmission, absorption)) < -1e-7
            or reflection[1] < minimum - 1e-7
        ):
            raise LuminaBoxReferenceError(
                "The fitted calibration white violates its known reflectance lower bound; "
                "do not use this fit as material parameters"
            )

    def observe(
        self, parameters: SpectralMaterialParameters, thicknesses_mm: np.ndarray,
        backing_base: np.ndarray, reference_xyz: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Reconstruct normalized T/R readings with measurement diffuser return.
        含测量匀光板回光地重建归一化透射与反射读数。

        Args:
            parameters: Material parameters.（材料系数。）
            thicknesses_mm: Actual sample thicknesses.（实际样片厚度。）
            backing_base: Instrument-normalized diffuser ratios.（匀光板归一化比值。）
            reference_xyz: Solved physical white-reference response.（已求得的物理白参考。）

        Returns:
            Predicted transmission and reflection ratios.（预测透射和反射比值。）
        """
        reference = _finite_vector(reference_xyz, 3, "white reference XYZ")
        if np.any(reference <= 0.0):
            raise LuminaBoxModelError("White reference must be positive")
        d = np.asarray(thicknesses_mm, dtype=np.float64)
        if d.ndim != 1 or not np.isfinite(d).all() or np.any(d < 0.0):
            raise LuminaBoxModelError("Sample thicknesses must be a finite non-negative vector")
        r, rb, tf, tb = self.slab(parameters, d[:, None])
        transmission_slab = self.slab(parameters, d[:, None], reflection=False)
        spectrum = parameters.values[7] * self.basis.diffuser(
            np.asarray(backing_base) * reference / LUMINA_BOX_REFERENCE_REFLECTANCE
        )
        if np.min(spectrum) < -1e-8 or np.max(spectrum) > 1.0 + 1e-8:
            raise LuminaBoxModelError("Measurement diffuser response exceeds physical bounds")
        backing = np.zeros((len(self.basis.wavelengths), 2, 2))
        backing[:, 1, :] = spectrum[:, None]
        down = np.linalg.solve(np.eye(2) - rb @ backing, tf)
        reflected = (r + tb @ backing @ down)[..., 1, 0]
        transmitted = np.linalg.solve(
            np.eye(2) - transmission_slab[1] @ backing, transmission_slab[2]
        )[..., :, 0].sum(axis=-1)
        return (
            transmitted @ self.basis.weights.T,
            (reflected @ self.basis.weights.T) * LUMINA_BOX_REFERENCE_REFLECTANCE / reference,
        )

    def predict_recipes(
        self, parameters: Sequence[SpectralMaterialParameters], recipes: np.ndarray,
        layer_height_mm: float, reference: BoxWhiteReference,
        *, base_parameters: SpectralMaterialParameters,
        base_thickness_mm: float = LUMINA_BOX_DEFAULT_BASE_MM,
    ) -> np.ndarray:
        """Predict printed recipes over a physical base with one white normalization.
        在实体底板上预测打印配方，并仅使用一次白参考归一化。

        Args:
            parameters: Palette in user order.（用户顺序的材料列表。）
            recipes: Integer bottom-to-top palette indices.（从底到顶的整数材料索引。）
            layer_height_mm: Thickness of each color layer.（每层彩色材料厚度。）
            reference: Shared measurement white reference.（共同测量白参考。）
            base_parameters: Actual selected backing material.（实际所选底板材料。）
            base_thickness_mm: Physical backing thickness.（实际底板厚度。）

        Returns:
            Reference-relative XYZ for every recipe.（各配方的白参考相对 XYZ。）
        """
        recipes = np.asarray(recipes)
        if (
            not parameters or recipes.ndim != 2
            or not np.issubdtype(recipes.dtype, np.integer)
            or np.any(recipes < 0) or np.any(recipes >= len(parameters))
            or not np.isfinite(layer_height_mm) or layer_height_mm <= 0.0
            or not np.isfinite(base_thickness_mm) or base_thickness_mm <= 0.0
        ):
            raise LuminaBoxModelError("Invalid recipe indices, layer thickness, or physical backing")
        output = np.empty((len(recipes), 3), dtype=np.float64)
        base = self.bulk(base_parameters, base_thickness_mm)
        layers = [self.bulk(material, layer_height_mm) for material in parameters]
        gathered = [np.asarray([layer[index] for layer in layers]) for index in range(4)]
        front = self.reflection_boundary
        rear = reverse_optical_port(front)
        for start in range(0, len(recipes), LUMINA_BOX_PREDICTION_BATCH_SIZE):
            batch = recipes[start:start + LUMINA_BOX_PREDICTION_BATCH_SIZE]
            port = tuple(np.broadcast_to(part, (len(batch), *part.shape)).copy() for part in base)
            for column in batch.T:
                port = combine_optical_layers(tuple(part[column] for part in gathered), port)
            port = combine_optical_layers(combine_optical_layers(front, port), rear)
            xyz = port[0][..., 1, 0] @ self.basis.weights.T
            output[start:start + len(batch)] = xyz * LUMINA_BOX_REFERENCE_REFLECTANCE / reference.relative_xyz
        return output
