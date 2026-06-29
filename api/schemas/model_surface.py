from __future__ import annotations

from pydantic import BaseModel, Field


class ModelSurfaceUploadResponse(BaseModel):
    """Response for model-surface source upload."""

    status: str
    model_file_id: str
    summary: dict
    preview_glb_url: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ModelSurfaceHitTriangle(BaseModel):
    """Triangle hit payload from the frontend model viewer."""

    face_index: int | None = None
    point: tuple[float, float, float] | None = None
    normal: tuple[float, float, float] | None = None
    vertices: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ] | None = None


class ModelSurfaceSelectRequest(BaseModel):
    """Request to select a printable planar model surface."""

    model_file_id: str
    hit: ModelSurfaceHitTriangle
    include_same_plane_disconnected: bool = False


class ModelSurfaceSelectResponse(BaseModel):
    """Response containing planar selection and projected footprint."""

    status: str
    selection_id: str
    selection: dict
    footprint: dict
    warnings: list[str] = Field(default_factory=list)
