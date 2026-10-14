"""Lumina Box paired T/R manual-measurement API schemas.

The transport contract records one percent-scale transmittance/reflectance
pair at every physical thickness. Optical fitting remains in ``core``; this
module only owns the strict HTTP payload and response shapes.
"""

from __future__ import annotations

import math
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.km_xyz import (
    KM_XYZ_COLOR_BRIDGE_ID,
    KM_XYZ_MEASUREMENT_PROTOCOL_ID,
)
from core.lumina_box_spectral import (
    LUMINA_BOX_SPECTRAL_MODEL_ID, LUMINA_BOX_SPECTRAL_BOUNDARY_ID,
    LUMINA_BOX_DEFAULT_REFERENCE_MIN_REFLECTANCE,
)


LUMINA_BOX_PROTOCOL_ID = KM_XYZ_MEASUREMENT_PROTOCOL_ID
"""Paired acquisition identifier retained independently of the optical model."""

LUMINA_BOX_OPTICAL_MODEL_ID = LUMINA_BOX_SPECTRAL_MODEL_ID
"""The only model used by new Lumina Box fits and saves."""

LUMINA_BOX_COLOR_BRIDGE_ID = KM_XYZ_COLOR_BRIDGE_ID
"""Versioned D65 10°/2° display bridge retained by the adopted model."""

LUMINA_BOX_MEASUREMENT_REFLECTION_BOUNDARY_ID = (
    LUMINA_BOX_SPECTRAL_BOUNDARY_ID
)
"""Versioned diffuser recycling and calibration-white boundary."""

LUMINA_BOX_VALUE_SCALE = "percent_0_100"
"""Only externally visible scale for paired Lumina Box observations."""


def _validate_percent_xyz(
    value: Any,
    *,
    field_name: str,
) -> list[float]:
    """Validate one finite XYZ percent triplet without coercing booleans."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{field_name} must contain exactly 3 channels")
    normalized: list[float] = []
    for channel in value:
        if isinstance(channel, bool):
            raise ValueError(
                f"{field_name} channels must be finite numbers in [0, 100]"
            )
        try:
            numeric = float(channel)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{field_name} channels must be finite numbers in [0, 100]"
            ) from exc
        if not math.isfinite(numeric) or not 0.0 <= numeric <= 100.0:
            raise ValueError(
                f"{field_name} channels must be finite numbers in [0, 100]"
            )
        normalized.append(numeric)
    return normalized


def _validate_measurement_backing_percent_xyz(value: Any) -> list[float]:
    """Validate the required instrument diffuser base without string coercion."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("measurement_backing_percent_xyz must contain exactly 3 channels")
    normalized: list[float] = []
    for channel in value:
        if isinstance(channel, bool) or not isinstance(channel, (int, float)):
            raise ValueError(
                "measurement_backing_percent_xyz channels must be finite numbers in (0, 100]"
            )
        numeric = float(channel)
        if not math.isfinite(numeric) or not 0.0 < numeric <= 100.0:
            raise ValueError(
                "measurement_backing_percent_xyz channels must be finite numbers in (0, 100]"
            )
        normalized.append(numeric)
    return normalized


class LuminaBoxPairedSampleRequest(BaseModel):
    """One percent-scale T/R measurement pair at a known physical thickness."""

    model_config = ConfigDict(extra="forbid")

    thickness_mm: float = Field(
        ...,
        description="Physical sample thickness in millimeters.",
    )
    transmittance_percent_xyz: list[float] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="XYZ transmittance percentages in the inclusive range [0, 100].",
    )
    reflectance_percent_xyz: list[float] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="XYZ reflectance percentages in the inclusive range [0, 100].",
    )

    @field_validator("thickness_mm", mode="before")
    @classmethod
    def validate_thickness_mm(cls, value: Any) -> float:
        if isinstance(value, bool):
            raise ValueError("thickness_mm must be a finite positive number")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("thickness_mm must be a finite positive number") from exc
        if not math.isfinite(numeric) or numeric <= 0.0:
            raise ValueError("thickness_mm must be a finite positive number")
        return numeric

    @field_validator("transmittance_percent_xyz", mode="before")
    @classmethod
    def validate_transmittance_percent_xyz(cls, value: Any) -> list[float]:
        return _validate_percent_xyz(
            value,
            field_name="transmittance_percent_xyz",
        )

    @field_validator("reflectance_percent_xyz", mode="before")
    @classmethod
    def validate_reflectance_percent_xyz(cls, value: Any) -> list[float]:
        return _validate_percent_xyz(
            value,
            field_name="reflectance_percent_xyz",
        )


class LuminaBoxFitRequest(BaseModel):
    """Paired percent samples and explicit calibration-white selection.
    配对百分数样本与明确的校准白色选择。
    """

    model_config = ConfigDict(extra="forbid")

    is_reference_white: bool = False
    reference_directory_name: str | None = Field(None, max_length=512)
    reference_min_reflectance_percent: float = Field(
        LUMINA_BOX_DEFAULT_REFERENCE_MIN_REFLECTANCE * 100.0, gt=0.0, le=100.0,
        description="Known lower bound for total calibration-white reflectance Y, not its exact value.",
    )

    @field_validator("reference_min_reflectance_percent", mode="before")
    @classmethod
    def validate_reference_minimum(cls, value: Any) -> Any:
        """Reject booleans before numerical percentage validation.
        在百分数校验前拒绝布尔值，避免将其当作反射率下限。

        Args:
            value: Submitted lower bound.（提交的反射率下限。）

        Returns:
            Input for the field's finite-range validation.（交给字段范围校验的输入。）
        """
        if isinstance(value, bool):
            raise ValueError("Known minimum white reflectance must be a percentage, not a boolean")
        return value

    protocol_id: Literal[LUMINA_BOX_PROTOCOL_ID] = Field(
        ...,
        description="Canonical paired Lumina Box measurement protocol identifier.",
    )
    value_scale: Literal[LUMINA_BOX_VALUE_SCALE] = Field(
        ...,
        description="The externally visible percent scale for every XYZ sample.",
    )
    measurement_backing_percent_xyz: list[float] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Instrument diffuser-base XYZ percentages in the range (0, 100].",
    )
    samples: list[LuminaBoxPairedSampleRequest] = Field(
        ...,
        min_length=3,
        description="At least three paired T/R samples, sorted by thickness.",
    )

    @model_validator(mode="after")
    def normalize_sample_order_and_validate_thicknesses(self) -> "LuminaBoxFitRequest":
        thicknesses = [sample.thickness_mm for sample in self.samples]
        if len(set(thicknesses)) != len(thicknesses):
            raise ValueError("samples must not repeat a thickness_mm value")
        self.samples.sort(key=lambda sample: sample.thickness_mm)
        reference = (self.reference_directory_name or "").strip()
        if self.is_reference_white:
            if reference:
                raise ValueError("A calibration-white fit must not select a different reference")
            if not any(abs(thickness - 3.0) <= 1e-9 for thickness in thicknesses):
                raise ValueError("The calibration white requires its 3 mm paired sample")
        elif not reference:
            raise ValueError("Select the saved calibration white for this material")
        self.reference_directory_name = reference or None
        return self

    @field_validator("measurement_backing_percent_xyz", mode="before")
    @classmethod
    def validate_measurement_backing_percent_xyz(cls, value: Any) -> list[float]:
        return _validate_measurement_backing_percent_xyz(value)


class LuminaBoxRawMeasurementRow(BaseModel):
    """Unmodified input text; optical fitting rules do not apply here.
    未修改的输入原文，不在此处应用光学拟合限制。
    """

    model_config = ConfigDict(extra="forbid")
    thickness_mm: str = Field(max_length=128)
    reflectance_percent_xyz: list[str] = Field(min_length=3, max_length=3)
    transmittance_percent_xyz: list[str] = Field(min_length=3, max_length=3)


class LuminaBoxRawMeasurementsRequest(BaseModel):
    """A raw capture that can be saved before or after any fitting attempt.
    无论是否进行或完成拟合，都可保存的原始采集记录。
    """

    model_config = ConfigDict(extra="forbid")
    material_name: str = Field(default="", max_length=256)
    brand: str = Field(default="", max_length=256)
    material_type: str = Field(default="", max_length=256)
    notes: str = Field(default="", max_length=8192)
    is_reference_white: bool = False
    reference_directory_name: str | None = Field(None, max_length=512)
    reference_min_reflectance_percent: str = Field(
        default=f"{LUMINA_BOX_DEFAULT_REFERENCE_MIN_REFLECTANCE * 100:g}", max_length=128,
    )
    measurement_backing_percent_xyz: list[str] = Field(min_length=3, max_length=3)
    samples: list[LuminaBoxRawMeasurementRow] = Field(max_length=512)


class LuminaBoxMeasurementRecord(LuminaBoxRawMeasurementsRequest):
    """Durable capture with its identity and timestamp.
    带有编号和时间的持久采集记录。
    """

    schema_version: str = "1.0"
    kind: Literal["lumina_box_measurements"] = "lumina_box_measurements"
    record_id: UUID
    created_at: str


class LuminaBoxMeasurementSummary(BaseModel):
    """A saved capture's display information.（采集记录的展示信息）"""

    record_id: UUID
    created_at: str
    material_name: str
    brand: str
    sample_count: int


class LuminaBoxMeasurementRecordResponse(BaseModel):
    """One durable measurement record.（一份持久保存的测量记录）"""

    status: Literal["ok"] = "ok"
    record: LuminaBoxMeasurementRecord


class LuminaBoxMeasurementListResponse(BaseModel):
    """Saved measurement summaries.（已保存的测量记录摘要）"""

    status: Literal["ok"] = "ok"
    records: list[LuminaBoxMeasurementSummary]


class LuminaBoxSaveRequest(BaseModel):
    """Persist a completed Lumina Box fit held only on the server session."""

    model_config = ConfigDict(extra="forbid")

    fit_session_id: UUID = Field(
        ...,
        description="UUID of the temporary server-side Lumina Box fit session.",
    )
    material_name: str = Field(..., description="User-facing material name.")
    brand: str | None = Field(None, description="Optional material brand.")
    material_type: str | None = Field(
        None,
        description="Optional material family, for example PLA.",
    )
    notes: str | None = Field(
        None,
        description="Optional operator note saved with the measurement.",
    )
    overwrite: bool = Field(
        False,
        description="Replace the same Lumina Box brand/name archive atomically.",
    )

    @field_validator("material_name")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{info.field_name} is required")
        return cleaned

    @field_validator("brand", "material_type", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class LuminaBoxSpectralParametersResponse(BaseModel):
    """Named coefficients for the adopted spectral model.
    已采用波段模型的具名系数。
    """

    model_config = ConfigDict(extra="forbid")
    parameterization: Literal["log_absorption4_log_scattering_power_forward_coupling/v1"]
    log_absorption_anchors: list[float] = Field(..., min_length=4, max_length=4)
    log_scattering_strength: float
    scattering_power: float
    forward_scattering_fraction: float
    measurement_backing_scale: float
    unit: Literal["mm^-1"] = "mm^-1"


class LuminaBoxModalityPredictionResponse(BaseModel):
    """Measured, reconstructed, and signed percent-residual XYZ for one mode."""

    model_config = ConfigDict(extra="forbid")

    measured_percent_xyz: list[float] = Field(..., min_length=3, max_length=3)
    predicted_percent_xyz: list[float] = Field(..., min_length=3, max_length=3)
    residual_percentage_points_xyz: list[float] = Field(
        ...,
        min_length=3,
        max_length=3,
    )


class LuminaBoxSamplePredictionResponse(BaseModel):
    """Paired T/R predictions for one measured thickness."""

    model_config = ConfigDict(extra="forbid")

    thickness_mm: float
    transmittance: LuminaBoxModalityPredictionResponse
    reflectance: LuminaBoxModalityPredictionResponse


class LuminaBoxMaxAbsLocationResponse(BaseModel):
    """Stable first location of the largest signed T/R reconstruction residual."""

    model_config = ConfigDict(extra="forbid")

    thickness_mm: float
    modality: Literal["transmittance", "reflectance"]
    channel: Literal["X", "Y", "Z"]
    signed_residual_percentage_points: float


class LuminaBoxResidualSummaryResponse(BaseModel):
    """Percentage-point residual metrics across complete paired samples."""

    model_config = ConfigDict(extra="forbid")

    transmittance_channel_rmse_percentage_points_xyz: list[float] = Field(
        ...,
        min_length=3,
        max_length=3,
    )
    reflectance_channel_rmse_percentage_points_xyz: list[float] = Field(
        ...,
        min_length=3,
        max_length=3,
    )
    channel_rmse_percentage_points_xyz: list[float] = Field(
        ...,
        min_length=3,
        max_length=3,
    )
    transmittance_rmse_percentage_points: float
    reflectance_rmse_percentage_points: float
    overall_rmse_percentage_points: float
    max_abs_residual_percentage_points: float
    max_abs_location: LuminaBoxMaxAbsLocationResponse


class LuminaBoxChannelDiagnosticsResponse(BaseModel):
    """Core optimizer diagnostics for one effective XYZ channel."""

    model_config = ConfigDict(extra="forbid")

    channel: Literal["X", "Y", "Z"]
    transmittance_rmse: float
    reflectance_rmse: float
    warnings: list[str] = Field(default_factory=list)


class LuminaBoxFitDiagnosticsResponse(BaseModel):
    """Versioned core objective and channel-level fit diagnostics."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    message: str
    nfev: int
    start_count: int
    robust_objective: float
    jacobian_condition: float | None = None
    measurement_thickness_offset_mm: float
    objective_id: str
    objective_config: dict[str, Any]
    channels: list[LuminaBoxChannelDiagnosticsResponse]
    warnings: list[str] = Field(default_factory=list)


class LuminaBoxFitQualityResponse(BaseModel):
    """Archive eligibility and diagnostic warnings, not an accuracy guarantee.
    档案可保存状态及诊断警告，不代表配色精度保证。
    """

    model_config = ConfigDict(extra="forbid")

    savable: bool
    reasons: list[str] = Field(default_factory=list)
    thresholds: dict[str, float]


class LuminaBoxReferencePhysicsResponse(BaseModel):
    """Known white bound and modeled energy, separate from instrument scaling.
    白片已知下限及模型能量分配，与仪器标定比例分开显示。
    """

    model_config = ConfigDict(extra="forbid")
    minimum_total_reflectance_percent_y: float
    total_reflectance_percent_xyz: list[float] = Field(min_length=3, max_length=3)
    total_transmittance_percent_xyz: list[float] = Field(min_length=3, max_length=3)
    absorption_percent_xyz: list[float] = Field(min_length=3, max_length=3)
    lower_bound_active: bool
    assigned_calibration_percent: float
    exact_white_reflectance_measured: Literal[False] = False


class LuminaBoxFitResponse(BaseModel):
    """Server-owned spectral fit and its complete reference identity.
    服务器持有的波段拟合结果与完整参考身份。
    """

    model_config = ConfigDict(extra="forbid")
    reference_physics: LuminaBoxReferencePhysicsResponse | None = None

    status: Literal["ok"] = "ok"
    message: str
    fit_session_id: UUID
    model_id: Literal[LUMINA_BOX_OPTICAL_MODEL_ID] = LUMINA_BOX_OPTICAL_MODEL_ID
    optical_model_id: Literal[LUMINA_BOX_OPTICAL_MODEL_ID] = LUMINA_BOX_OPTICAL_MODEL_ID
    measurement_protocol_id: Literal[LUMINA_BOX_PROTOCOL_ID] = LUMINA_BOX_PROTOCOL_ID
    color_bridge_id: Literal[LUMINA_BOX_COLOR_BRIDGE_ID] = LUMINA_BOX_COLOR_BRIDGE_ID
    value_scale: Literal[LUMINA_BOX_VALUE_SCALE] = LUMINA_BOX_VALUE_SCALE
    residual_unit: Literal["percentage_point"] = "percentage_point"
    parameters: LuminaBoxSpectralParametersResponse
    reference_id: str
    is_reference_white: bool
    sample_predictions: list[LuminaBoxSamplePredictionResponse]
    residual_summary: LuminaBoxResidualSummaryResponse
    diagnostics: LuminaBoxFitDiagnosticsResponse
    measurement_backing_base_percent_xyz: list[float] = Field(
        ...,
        min_length=3,
        max_length=3,
    )
    measurement_backing_scale: float
    measurement_thickness_offset_mm: float
    measurement_backing_effective_percent_xyz: list[float] = Field(
        ...,
        min_length=3,
        max_length=3,
    )
    measurement_reflection_boundary_id: Literal[
        LUMINA_BOX_MEASUREMENT_REFLECTION_BOUNDARY_ID
    ] = LUMINA_BOX_MEASUREMENT_REFLECTION_BOUNDARY_ID
    fit_quality: LuminaBoxFitQualityResponse
    estimated_effective_d65_10_xyz_relative: list[float] = Field(
        ...,
        min_length=3,
        max_length=3,
    )
    estimated_reflectance_thickness_mm: float
    estimated_srgb: list[float] = Field(..., min_length=3, max_length=3)
    warnings: list[str] = Field(default_factory=list)


class LuminaBoxSavedMaterialResponse(BaseModel):
    """Public summary of one persisted spectral Lumina Box material archive.
    已保存新版 Lumina Box 波段耗材档案的公开摘要。
    """

    material_name: str
    directory_name: str
    brand: str | None = None
    material_type: str | None = None
    notes: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    profile_kind: Literal["lumina_box"] = "lumina_box"
    acquisition_source: Literal["lumina_box"] = "lumina_box"
    optical_model: Literal[LUMINA_BOX_OPTICAL_MODEL_ID] = LUMINA_BOX_OPTICAL_MODEL_ID
    optical_model_id: Literal[LUMINA_BOX_OPTICAL_MODEL_ID] = LUMINA_BOX_OPTICAL_MODEL_ID
    measurement_protocol_id: Literal[LUMINA_BOX_PROTOCOL_ID] = LUMINA_BOX_PROTOCOL_ID
    color_bridge_id: Literal[LUMINA_BOX_COLOR_BRIDGE_ID] = LUMINA_BOX_COLOR_BRIDGE_ID
    measurement_backing_base_percent_xyz: list[float] = Field(default_factory=list)
    measurement_backing_scale: float | None = None
    measurement_thickness_offset_mm: float | None = None
    measurement_backing_effective_percent_xyz: list[float] = Field(default_factory=list)
    measurement_reflection_boundary_id: Literal[
        LUMINA_BOX_MEASUREMENT_REFLECTION_BOUNDARY_ID
    ] = LUMINA_BOX_MEASUREMENT_REFLECTION_BOUNDARY_ID
    estimated_effective_d65_10_xyz_relative: list[float] = Field(default_factory=list)
    estimated_reflectance_thickness_mm: float | None = None
    estimated_rgb: list[int] = Field(default_factory=list)
    is_reference_white: bool = False
    reference_id: str | None = None


class LuminaBoxSaveResponse(BaseModel):
    """Response returned after a Lumina Box material archive has been saved."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    message: str
    material: LuminaBoxSavedMaterialResponse


class LuminaBoxMaterialLibraryResponse(BaseModel):
    """List response for persisted Lumina Box archives."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    message: str
    materials: list[LuminaBoxSavedMaterialResponse] = Field(default_factory=list)
    outdated_count: int = 0
