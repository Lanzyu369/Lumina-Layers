"""Backed-gradient input contracts. / 黑白底梯度输入契约。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.backed_gradient_store import _dataset_payload, normalize_gradient_capture
from core.errors import CoreValidationError

CaptureMaterialSymbol = Literal["R", "Y", "B", "W", "K", "C", "M", "G", "material"]


class GradientDatasetCreate(BaseModel):
    """Create a fixed-identity experiment. / 创建固定身份实验。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    name: str
    brand: str = ""
    material_type: str = "PETG"
    batch: str = ""
    notes: str = ""
    materials: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def validate_identity(cls, value: Any) -> Any:
        """Check input before opening storage. / 打开存储前校验输入。

        Args:
            value: Original request.（原始请求。）

        Returns:
            Validated identity.（已校验身份。）
        """
        try:
            return _dataset_payload(value)
        except CoreValidationError as exc:
            raise ValueError(str(exc)) from exc


class GradientCaptureRequest(BaseModel):
    """Freeze a manual/device reading's target. / 固定手动或设备读数目标。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    capture_id: str
    material_symbol: CaptureMaterialSymbol
    backing: Literal["W", "K"]
    sample_role: Literal["coated", "bare_backing"]
    overlay_mm: float
    measurement: dict[str, Any] | None = None
    reflectance_percent_xyz: list[float] | None = None
    measurement_id: str | None = None
    received_at: str | None = None
    sample_name: str = ""
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def validate_capture(cls, value: Any) -> Any:
        """Check raw values and geometry before storage. / 存储前校验原值及几何。

        Args:
            value: Original request.（原始请求。）

        Returns:
            Original validated request.（已校验原始请求。）
        """
        try:
            normalize_gradient_capture(value)
        except CoreValidationError as exc:
            raise ValueError(str(exc)) from exc
        return value


class GradientSelectionRequest(BaseModel):
    """Choose one saved reading. / 选择一个已保存读数。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    record_id: str


class MaterialDatasetCreate(BaseModel):
    """One filament and its saved backing setup. / 一种耗材及已存背板设置。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=200)
    brand: str = ""
    material_type: str = "PETG"
    batch: str = ""
    notes: str = ""
    material_symbol: CaptureMaterialSymbol = "material"
    reference_id: str | None = Field(default=None, min_length=1)
    white_backing_id: str | None = Field(default=None, min_length=1)
    black_backing_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_backings(self) -> "MaterialDatasetCreate":
        """Require two chosen materials or an existing frozen reference.
        要求明确选择两个底材，或沿用已有冻结参考。

        Returns:
            Validated capture identity.（已校验采集身份。）
        """
        if self.reference_id:
            if self.white_backing_id or self.black_backing_id:
                raise ValueError("Choose backing materials without also supplying a reference.")
        elif not self.white_backing_id or not self.black_backing_id:
            raise ValueError("Choose the actual white and black backing materials.")
        return self


class BackingMaterialDatasetCreate(BaseModel):
    """Create one backing's independent measurements. / 创建单个背板耗材的独立采集。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=200)
    brand: str = ""
    material_type: str = "PETG"
    role: Literal["W", "K"]
    opposite_material_id: str | None = Field(default=None, min_length=1)
    opposite_name: str | None = Field(default=None, min_length=1, max_length=200)
    material_id: str | None = Field(default=None, min_length=1)


class BackingDatasetCreate(BaseModel):
    """Names for a reusable black/white backing setup. / 可复用黑白背板名称。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=200)
    brand: str = ""
    material_type: str = "PETG"
    white_name: str = Field(min_length=1, max_length=200)
    black_name: str = Field(min_length=1, max_length=200)


class MaterialFitRequest(BaseModel):
    """Optional material selection when reusing earlier full captures.
    复用旧整套采集时的可选材料选择。
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    material_symbol: CaptureMaterialSymbol | None = None
    reference_id: str | None = None


class MaterialArchiveSaveRequest(BaseModel):
    """User-editable archive identity only. / 仅接收可编辑档案身份。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=200)
    brand: str = ""
    material_type: str = "PETG"
    notes: str = ""
    overwrite: bool = False
