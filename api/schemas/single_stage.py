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
