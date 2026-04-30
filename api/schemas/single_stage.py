"""Single-stage calibration request schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from api.schemas.lut import PaletteEntrySchema


class SingleStageKitGenerateRequest(BaseModel):
    """Request model for generating a single-stage kit."""

    palette: list[PaletteEntrySchema] = Field(
        ...,
        min_length=1,
        description="Palette entries to generate one single-stage job per color.",
    )
    substrate_id: str = Field("white", description="Stable substrate identifier")
    substrate_display_name: str = Field(
        "White",
        description="User-facing substrate display name",
    )
    material_default: str = Field(
        "PLA Basic",
        description="Default material label used when palette entries omit material",
    )
    layer_height_mm: float = Field(
        0.04,
        ge=0.04,
        le=0.3,
        description="Layer height in millimeters for generated single-stage jobs",
    )


class StageAFitRequest(BaseModel):
    """Request model for fitting Stage A from a stored extraction session."""

    session_id: str | None = Field(
        None,
        description="Extraction session id carrying a stage JSON output",
    )

    @model_validator(mode="after")
    def validate_any_source(self) -> "StageAFitRequest":
        if self.session_id is not None and not str(self.session_id).strip():
            raise ValueError("session_id cannot be blank")
        return self


class GradientCardMaterialUpdateRequest(BaseModel):
    """Request model for updating saved material metadata."""

    material_name: str = Field(
        ...,
        description="Updated user-facing material name.",
    )
    brand: str | None = Field(
        None,
        description="Updated optional brand label.",
    )
    estimated_rgb: list[int] | None = Field(
        None,
        description=(
            "Optional user-overridden display sRGB [R, G, B] triplet in [0, 255]. "
            "Leave null or omit to keep the previously stored display color."
        ),
    )

    @field_validator("material_name")
    @classmethod
    def validate_material_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("material_name is required")
        return cleaned

    @field_validator("brand")
    @classmethod
    def normalize_brand(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("estimated_rgb")
    @classmethod
    def validate_estimated_rgb(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if len(value) != 3:
            raise ValueError("estimated_rgb must contain exactly 3 channels")
        normalized: list[int] = []
        for channel in value:
            try:
                channel_int = int(channel)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "estimated_rgb channels must be integers in [0, 255]"
                ) from exc
            if not 0 <= channel_int <= 255:
                raise ValueError(
                    "estimated_rgb channels must be integers in [0, 255]"
                )
            normalized.append(channel_int)
        return normalized


class MaterialRecipePreviewRequest(BaseModel):
    """Forward-simulate the predicted color of a stacked-material recipe.
    正向模拟选定耗材按顺序叠层的预测颜色。

    Each entry in ``directory_names`` is one print layer (bottom -> top relative
    to the substrate). The endpoint loads the corresponding Stage A parameters
    and runs a Beer-Lambert forward pass; no LUT is consulted. The recipe
    length is intentionally unconstrained beyond a sane upper bound so users
    can preview any layer count, not just the 5-layer presets the inverse
    solver requires.

    每个 ``directory_names`` 元素代表一层打印（从基底向外）。后端会加载对应
    Stage A 参数，使用 Beer-Lambert 正向模型求解叠层颜色；不依赖任何 LUT。
    层数上限设得宽松，以便用户预览任意层数。
    """

    directory_names: list[str] = Field(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "Saved material directory names, in stacking order from substrate "
            "(index 0) to outermost visible layer (index -1)."
        ),
    )
    layer_height_mm: float = Field(
        0.08,
        gt=0.0,
        le=1.0,
        description="Per-layer thickness in millimeters used by the forward model.",
    )
    substrate: str = Field(
        "white",
        description="Substrate identifier; only 'white' is supported in v1.",
    )

    @field_validator("directory_names")
    @classmethod
    def validate_directory_names(cls, value: list[str]) -> list[str]:
        cleaned = [name.strip() for name in value if isinstance(name, str) and name.strip()]
        if len(cleaned) != len(value) or not cleaned:
            raise ValueError("directory_names must contain non-empty strings")
        return cleaned

    @field_validator("substrate")
    @classmethod
    def validate_substrate(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in ("white", "black"):
            raise ValueError("substrate must be 'white' or 'black'")
        return cleaned


class MaterialLibraryBulkExportRequest(BaseModel):
    """Request model for exporting multiple saved material archives."""

    directory_names: list[str] = Field(
        ...,
        min_length=1,
        description="Saved material directory names to export as one ZIP archive.",
    )

    @field_validator("directory_names")
    @classmethod
    def validate_directory_names(cls, value: list[str]) -> list[str]:
        cleaned = [name.strip() for name in value if isinstance(name, str) and name.strip()]
        if len(cleaned) != len(value) or not cleaned:
            raise ValueError("directory_names must contain non-empty strings")
        return cleaned
