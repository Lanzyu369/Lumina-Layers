from __future__ import annotations

from pydantic import BaseModel, Field


class ModelSurfaceUploadResponse(BaseModel):
    """Response for model-surface source upload."""

    status: str
    model_file_id: str
    summary: dict
    surface_candidates: list[dict] = Field(default_factory=list)
    preview_glb_url: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ModelSurfaceHitTriangle(BaseModel):
    """Triangle hit payload from the frontend model viewer."""

    face_index: int | None = None
    candidate_id: str | None = None
    point: tuple[float, float, float] | None = None
    normal: tuple[float, float, float] | None = None
    vertices: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ] | None = None


class ModelSurfaceModelRotation(BaseModel):
    """Rotation applied to the uploaded model in the surface editor.

    在覆面编辑器中应用到上传模型的旋转角度。
    """

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class ModelSurfaceModelTransform(BaseModel):
    """Model transform payload used to keep selection and generation aligned.

    用于保持选面和生成阶段一致的模型变换载荷。
    """

    rotation_deg: ModelSurfaceModelRotation = Field(
        default_factory=ModelSurfaceModelRotation
    )


class ModelSurfaceSelectRequest(BaseModel):
    """Request to select a printable planar model surface."""

    model_file_id: str
    hit: ModelSurfaceHitTriangle
    model_transform: ModelSurfaceModelTransform = Field(
        default_factory=ModelSurfaceModelTransform
    )
    include_same_plane_disconnected: bool = False


class ModelSurfaceSelectResponse(BaseModel):
    """Response containing planar selection and projected footprint."""

    status: str
    selection_id: str
    selection: dict
    footprint: dict
    warnings: list[str] = Field(default_factory=list)
