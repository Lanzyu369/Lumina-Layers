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
