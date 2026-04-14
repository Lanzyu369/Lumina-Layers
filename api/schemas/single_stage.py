"""Single-stage calibration request schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

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
