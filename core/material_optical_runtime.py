"""Shared optical-model contracts for material color prediction.

耗材颜色预测使用的共享光学模型契约。

This module deliberately depends only on plain material attributes so the
archive loader, forward solver, and cache layers can validate the same contract
without introducing import cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Sequence

import numpy as np

from core.km_xyz import (
    KM_XYZ_COLOR_BRIDGE_ID,
    KM_XYZ_MEASUREMENT_PROTOCOL_ID,
    KM_XYZ_MODEL_ID,
)
from core.lumina_box_spectral import (
    BoxWhiteReference,
    LUMINA_BOX_SPECTRAL_MODEL_ID,
    LuminaBoxModelError,
    LuminaBoxSpectralModel,
    SpectralMaterialParameters,
)
from core.backed_gradient_smooth import SPECTRAL_SMOOTH_MODEL_ID
from core.backed_gradient_material import (
    BACKED_GRADIENT_PROTOCOL_ID,
    BackedGradientComponent,
    BackedGradientReference,
)


BEER_LAMBERT_MODEL_ID = "beer_lambert/v1"
KM_COEFFICIENT_UNIT = "mm^-1"
RELATIVE_XYZ_MODEL_IDS = frozenset({KM_XYZ_MODEL_ID, LUMINA_BOX_SPECTRAL_MODEL_ID, SPECTRAL_SMOOTH_MODEL_ID})
PHYSICAL_BACKING_MODEL_IDS = frozenset({LUMINA_BOX_SPECTRAL_MODEL_ID, SPECTRAL_SMOOTH_MODEL_ID})


class MaterialOpticalCompatibilityError(ValueError):
    """Base error for incompatible material optical profiles.

    耗材光学档案无法在同一次求解中兼容时抛出。
    """

    error_type = "material_optical_compatibility_error"


class MaterialOpticalModelMismatchError(MaterialOpticalCompatibilityError):
    """Raised when a selected palette mixes optical model families.

    已选耗材混用了不同光学模型时抛出。
    """

    error_type = "material_optical_model_mismatch"


class MaterialMeasurementProtocolMismatchError(MaterialOpticalCompatibilityError):
    """Raised when KM profiles use incompatible measurement contracts.

    KM 耗材档案的测量协议或颜色桥接版本不兼容时抛出。
    """

    error_type = "material_measurement_protocol_mismatch"


class UnsupportedMaterialOpticalModelError(MaterialOpticalCompatibilityError):
    """Raised when a material names an optical model unknown to the runtime.

    耗材声明了运行时不支持的光学模型时抛出。
    """

    error_type = "material_optical_model_unsupported"


@dataclass(frozen=True)
class MaterialOpticalContract:
    """Validated shared contract for one selected material palette.

    一组已选耗材共同且已校验的光学契约。
    """

    model_id: str
    measurement_protocol_id: str | None = None
    color_bridge_id: str | None = None
    coefficient_unit: str | None = None
    reference_id: str | None = None


def is_relative_xyz_model(model_id: str) -> bool:
    """Identify models using the established relative-XYZ matching contract.
    判断模型是否使用既有的相对 XYZ 配色契约。

    Args:
        model_id: Versioned optical model identifier.（带版本的光学模型标识。）

    Returns:
        Whether matching retains relative XYZ.（是否保留相对 XYZ 进行配色。）
    """
    return model_id in RELATIVE_XYZ_MODEL_IDS


def material_optical_model_id(material: Any) -> str:
    """Return a material's model ID, preserving legacy default semantics.

    缺少模型字段的旧档案按 ``beer_lambert/v1`` 解释。
    """

    value = getattr(material, "optical_model_id", None)
    normalized = str(value or BEER_LAMBERT_MODEL_ID).strip()
    return normalized or BEER_LAMBERT_MODEL_ID


def _common_km_text(
    materials: Sequence[Any],
    attribute: str,
    default: str,
    label: str,
) -> str:
    values = {
        str(getattr(material, attribute, None) or default).strip()
        for material in materials
    }
    if len(values) != 1 or "" in values:
        raise MaterialMeasurementProtocolMismatchError(
            f"Selected KM materials use incompatible {label} values"
        )
    return next(iter(values))


def validate_material_optical_contract(
    materials: Sequence[Any],
) -> MaterialOpticalContract:
    """Validate model, KM coefficients, protocol, and bridge compatibility.

    校验已选耗材的模型、KM 系数、测量协议和颜色桥接兼容性。
    """

    if not materials:
        raise ValueError("At least one material must be provided")
    model_ids = {material_optical_model_id(material) for material in materials}
    if len(model_ids) != 1:
        raise MaterialOpticalModelMismatchError(
            "Selected materials must all use the same optical model"
        )
    model_id = next(iter(model_ids))
    if model_id == BEER_LAMBERT_MODEL_ID:
        return MaterialOpticalContract(model_id=model_id)
    if model_id == SPECTRAL_SMOOTH_MODEL_ID:
        return _validate_backed_gradient_palette(materials)
    if not is_relative_xyz_model(model_id):
        raise UnsupportedMaterialOpticalModelError(
            f"Unsupported material optical model: {model_id}"
        )

    protocol_id = _common_km_text(
        materials,
        "measurement_protocol_id",
        KM_XYZ_MEASUREMENT_PROTOCOL_ID,
        "measurement protocol",
    )
    if protocol_id != KM_XYZ_MEASUREMENT_PROTOCOL_ID:
        raise MaterialMeasurementProtocolMismatchError(
            "Unsupported KM measurement protocol "
            f"{protocol_id!r}; expected {KM_XYZ_MEASUREMENT_PROTOCOL_ID!r}"
        )
    color_bridge_id = _common_km_text(
        materials,
        "color_bridge_id",
        KM_XYZ_COLOR_BRIDGE_ID,
        "color bridge",
    )
    if color_bridge_id != KM_XYZ_COLOR_BRIDGE_ID:
        raise MaterialMeasurementProtocolMismatchError(
            "Unsupported KM color bridge "
            f"{color_bridge_id!r}; expected {KM_XYZ_COLOR_BRIDGE_ID!r}"
        )
    coefficient_unit = _common_km_text(
        materials,
        "coefficient_unit",
        KM_COEFFICIENT_UNIT,
        "coefficient unit",
    )
    if coefficient_unit != KM_COEFFICIENT_UNIT:
        raise MaterialMeasurementProtocolMismatchError(
            "Unsupported KM coefficient unit "
            f"{coefficient_unit!r}; expected {KM_COEFFICIENT_UNIT!r}"
        )

    if model_id == LUMINA_BOX_SPECTRAL_MODEL_ID:
        reference_id = _validate_spectral_palette(materials)
        return MaterialOpticalContract(
            model_id=model_id, measurement_protocol_id=protocol_id,
            color_bridge_id=color_bridge_id, coefficient_unit=coefficient_unit,
            reference_id=reference_id,
        )

    for material in materials:
        for attribute, label in (("km_K", "K"), ("km_S", "S")):
            try:
                values = np.asarray(getattr(material, attribute), dtype=np.float64)
            except (AttributeError, TypeError, ValueError) as exc:
                raise MaterialOpticalCompatibilityError(
                    f"KM material '{getattr(material, 'name', '')}' has invalid {label} coefficients"
                ) from exc
            if values.shape != (3,) or not np.all(np.isfinite(values)):
                raise MaterialOpticalCompatibilityError(
                    f"KM material '{getattr(material, 'name', '')}' must provide three finite {label} coefficients"
                )
            if np.any(values < 0.0):
                raise MaterialOpticalCompatibilityError(
                    f"KM material '{getattr(material, 'name', '')}' has negative {label} coefficients"
                )

    return MaterialOpticalContract(
        model_id=model_id,
        measurement_protocol_id=protocol_id,
        color_bridge_id=color_bridge_id,
        coefficient_unit=coefficient_unit,
    )


def _validate_backed_gradient_palette(materials: Sequence[Any]) -> MaterialOpticalContract:
    references: set[str] = set()
    for material in materials:
        component = getattr(material, "backed_gradient_component", None)
        reference = getattr(material, "backed_gradient_reference", None)
        if not isinstance(component, BackedGradientComponent) or not isinstance(reference, BackedGradientReference):
            raise MaterialOpticalCompatibilityError("Box material needs its saved black/white gradient parameters")
        references.add(reference.reference_id)
    if len(references) != 1:
        raise MaterialMeasurementProtocolMismatchError("Selected Box materials use different black/white references")
    protocol = _common_km_text(materials, "measurement_protocol_id", BACKED_GRADIENT_PROTOCOL_ID, "measurement protocol")
    bridge = _common_km_text(materials, "color_bridge_id", KM_XYZ_COLOR_BRIDGE_ID, "color bridge")
    if protocol != BACKED_GRADIENT_PROTOCOL_ID or bridge != KM_XYZ_COLOR_BRIDGE_ID:
        raise MaterialMeasurementProtocolMismatchError("Unsupported black/white gradient measurement contract")
    return MaterialOpticalContract(
        model_id=SPECTRAL_SMOOTH_MODEL_ID, measurement_protocol_id=protocol,
        color_bridge_id=bridge, coefficient_unit=KM_COEFFICIENT_UNIT,
        reference_id=next(iter(references)),
    )


def _validate_spectral_palette(materials: Sequence[Any]) -> str:
    references: set[str] = set()
    backing_contracts: set[tuple[Any, ...]] = set()
    for material in materials:
        parameters = getattr(material, "spectral_parameters", None)
        reference = getattr(material, "spectral_reference", None)
        if not isinstance(parameters, SpectralMaterialParameters) or not isinstance(reference, BoxWhiteReference):
            raise MaterialOpticalCompatibilityError(
                f"Box material '{getattr(material, 'name', '')}' needs complete spectral parameters and white reference"
            )
        try:
            LuminaBoxSpectralModel().validate_reference_physics(reference, require_constraint=True)
        except LuminaBoxModelError as exc:
            raise MaterialOpticalCompatibilityError(str(exc)) from exc
        references.add(reference.reference_id)
        backing = getattr(material, "spectral_backing_parameters", None)
        thickness = getattr(material, "spectral_backing_thickness_mm", 1.2)
        if not isinstance(thickness, (float, int)) or not np.isfinite(thickness) or thickness <= 0.0:
            raise MaterialOpticalCompatibilityError("Box backing thickness must be positive and finite")
        if backing is not None and not isinstance(backing, SpectralMaterialParameters):
            raise MaterialOpticalCompatibilityError("Box physical backing parameters are invalid")
        backing_contracts.add((None if backing is None else tuple(backing.values), float(thickness)))
    if len(references) != 1:
        raise MaterialMeasurementProtocolMismatchError(
            "Selected Box materials use different calibration whites; re-fit them with the same white reference"
        )
    if len(backing_contracts) != 1:
        raise MaterialOpticalCompatibilityError("Selected Box materials have inconsistent physical backing context")
    return next(iter(references))


def bind_material_backing(
    materials: Sequence[Any], backing_material_index: int, thickness_mm: float,
) -> list[Any]:
    """Bind the actual print backing without mutating loaded archive objects.
    绑定实际打印底板，并保留已加载档案对象不变。

    Args:
        materials: Validated material palette.（已校验耗材列表。）
        backing_material_index: Backing slot in user order.（用户顺序的底板槽位。）
        thickness_mm: Physical backing thickness.（实际底板厚度。）

    Returns:
        New contextualized spectral materials, or unchanged Stage-A/KM objects.
        （绑定底板后的新波段材料列表，或原有 Stage-A/KM 对象列表。）
    """
    contract = validate_material_optical_contract(materials)
    if contract.model_id not in PHYSICAL_BACKING_MODEL_IDS:
        return list(materials)
    if (
        isinstance(backing_material_index, bool) or not isinstance(backing_material_index, (int, np.integer))
        or not 0 <= backing_material_index < len(materials)
        or not np.isfinite(thickness_mm) or thickness_mm <= 0.0
    ):
        raise MaterialOpticalCompatibilityError("Invalid physical Box backing selection or thickness")
    if contract.model_id == SPECTRAL_SMOOTH_MODEL_ID:
        backing = materials[int(backing_material_index)].backed_gradient_component
        return [replace(material, backed_gradient_backing_component=backing,
                        backed_gradient_backing_thickness_mm=float(thickness_mm)) for material in materials]
    backing = materials[int(backing_material_index)].spectral_parameters
    return [replace(material, spectral_backing_parameters=backing,
                    spectral_backing_thickness_mm=float(thickness_mm)) for material in materials]


def bind_material_print_backing(
    materials: Sequence[Any],
    *,
    backing_material_index: int | None = None,
    thickness_mm: float = 1.2,
    layer_height_mm: float = 0.08,
    substrate: str = "white",
) -> list[Any]:
    """Resolve the Box backing and quantize its height as printed geometry does.
    解析 Box 实体底板，并按生成模型的层高量化其厚度。

    Args:
        materials: Validated palette.（已校验的耗材列表。）
        backing_material_index: Explicit backing slot, or inferred white/black.
            （明确选择的底板槽位；省略时按白色或黑色基底解析。）
        thickness_mm: Requested backing thickness.（请求的底板厚度。）
        layer_height_mm: Physical geometry layer height.（实际几何层高。）
        substrate: Default backing colour when no slot is specified.
            （未指定槽位时使用的默认底板颜色。）

    Returns:
        Copies carrying the physical backing; other optical families unchanged.
        （携带实体底板的副本；其他光学模型保持原状。）
    """
    contract = validate_material_optical_contract(materials)
    if contract.model_id not in PHYSICAL_BACKING_MODEL_IDS:
        return list(materials)
    if not np.isfinite(thickness_mm) or thickness_mm <= 0.0:
        raise MaterialOpticalCompatibilityError("Box backing thickness must be positive and finite")
    if not np.isfinite(layer_height_mm) or layer_height_mm <= 0.0:
        raise MaterialOpticalCompatibilityError("Box layer height must be positive and finite")
    physical_thickness = max(1, round(thickness_mm / layer_height_mm)) * layer_height_mm
    if backing_material_index is None:
        from core.material_color_solver import find_white_material_index

        if substrate == "white":
            backing_material_index = find_white_material_index(materials)
        elif substrate == "black":
            if contract.model_id == SPECTRAL_SMOOTH_MODEL_ID:
                backing_material_index = next((
                    index for index, material in enumerate(materials)
                    if material.backed_gradient_component.kind == "black"
                ), None)
            else:
                backing_material_index = next((
                    index for index, material in enumerate(materials)
                    if "black" in material.name.casefold() or "黑" in material.name
                ), None)
            if backing_material_index is None and contract.model_id != SPECTRAL_SMOOTH_MODEL_ID:
                raise MaterialOpticalCompatibilityError(
                    "Box black-substrate prediction requires an actual black backing material"
                )
        else:
            raise MaterialOpticalCompatibilityError("Box substrate must be white or black")
    if backing_material_index is not None:
        return bind_material_backing(materials, backing_material_index, physical_thickness)
    if contract.model_id == SPECTRAL_SMOOTH_MODEL_ID:
        reference = materials[0].backed_gradient_reference
        backing = reference.black if substrate == "black" else reference.white
        return [replace(material, backed_gradient_backing_component=backing,
                        backed_gradient_backing_thickness_mm=float(physical_thickness)) for material in materials]
    reference = materials[0].spectral_reference
    return [replace(material, spectral_backing_parameters=reference.white_parameters,
                    spectral_backing_thickness_mm=float(physical_thickness)) for material in materials]


def require_beer_lambert_materials(materials: Sequence[Any]) -> None:
    """Reject use of a Beer-Lambert-only algorithm for another model.

    防止 KM 档案误入仅适用于 Beer-Lambert 的仿射算法。
    """

    contract = validate_material_optical_contract(materials)
    if contract.model_id != BEER_LAMBERT_MODEL_ID:
        raise UnsupportedMaterialOpticalModelError(
            f"Algorithm requires {BEER_LAMBERT_MODEL_ID}, got {contract.model_id}"
        )


__all__ = [
    "BEER_LAMBERT_MODEL_ID",
    "KM_COEFFICIENT_UNIT",
    "MaterialMeasurementProtocolMismatchError",
    "MaterialOpticalCompatibilityError",
    "MaterialOpticalContract",
    "MaterialOpticalModelMismatchError",
    "UnsupportedMaterialOpticalModelError",
    "material_optical_model_id",
    "require_beer_lambert_materials",
    "validate_material_optical_contract",
    "is_relative_xyz_model",
    "bind_material_backing",
    "bind_material_print_backing",
]
