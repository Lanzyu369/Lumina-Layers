"""Contracts for independent measured stack captures. / 独立叠色实测采集契约。"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from core.errors import CoreValidationError
from core.lumina_box_stack_samples import normalize_stack_sample_payload


class StackSampleSaveRequest(BaseModel):
    """Accept sample provenance and an unchanged device frame. / 接收来源及原始设备帧。"""

    model_config = ConfigDict(extra="forbid")
    recipe_top_to_bottom: str
    capture_id: str
    measurement: dict[str, Any]
    received_at: str | None = None
    sample_name: str = ""
    notes: str = ""
    material_batch: str = ""
    reference_directory_name: str | None = None
    measurement_backing_percent_xyz: list[float] | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_capture(cls, value: Any) -> dict[str, Any]:
        """Apply the same validation at API and core entry points.
        在接口与核心入口应用相同校验。
        """
        try:
            return normalize_stack_sample_payload(value)
        except CoreValidationError as exc:
            raise ValueError(str(exc)) from exc


class StackSampleGeometry(BaseModel):
    """Describe the actual fixed print geometry. / 描述固定实际打印几何。"""

    upper_layer_count: int
    upper_layer_height_mm: Literal[0.08]
    first_layer_height_mm: Literal[0.2]
    total_layer_count: Literal[36]
    upper_mm: float
    white_base_mm: float
    total_mm: Literal[3.0]
    full_recipe_top_to_bottom: str
    layer_heights_mm_top_to_bottom: list[float]


class StackSampleReferenceContext(BaseModel):
    """Keep optional calibration provenance without requiring a fit.
    保留可选校准来源，无需成功拟合。
    """

    status: Literal["not_selected", "captured", "unavailable"]
    archive_id: str | None
    revision_id: str | None
    reference_id: str | None
    sidecar_sha256: dict[str, str]


class StackSampleRecord(BaseModel):
    """Expose real measured reflection and separate display colour.
    返回真实反射测量值及独立的显示颜色。
    """

    schema_version: Literal["1.0"]
    kind: Literal["lumina_box_stack_sample"]
    data_role: Literal["actual_measured_multimaterial_reflectance"]
    record_id: UUID
    created_at: str
    received_at: str
    capture_id: str
    recipe_top_to_bottom: str
    sample_name: str
    notes: str
    material_batch: str
    reference_directory_name: str | None
    measurement_backing_percent_xyz: list[float] | None
    geometry: StackSampleGeometry
    reflectance_percent_xyz: list[float]
    reflectance_relative_xyz: list[float]
    display_rgb: list[int]
    display_hex: str
    device_measurement: dict[str, Any]
    reference_context: StackSampleReferenceContext


class StackSampleRecordResponse(BaseModel):
    """Return the durable capture and replay result. / 返回持久采集及重放状态。"""

    status: Literal["success"] = "success"
    record: StackSampleRecord
    deduplicated: bool = False


class StackSampleListResponse(BaseModel):
    """Return captures without fitting summaries. / 返回采集记录，不附加拟合摘要。"""

    status: Literal["success"] = "success"
    records: list[StackSampleRecord]


class StackSampleDeleteResponse(BaseModel):
    """Identify the single deleted capture. / 标明唯一被删除的采集。"""

    status: Literal["success"] = "success"
    record_id: UUID
