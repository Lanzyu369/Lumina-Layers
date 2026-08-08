from __future__ import annotations

import trimesh

from core.model_surface.types import ModelSurfaceError

MODEL_SURFACE_MESH_NOT_WATERTIGHT = "model_surface_mesh_not_watertight"
MODEL_SURFACE_MESH_NOT_VOLUME = "model_surface_mesh_not_volume"
MODEL_SURFACE_EMPTY_GEOMETRY = "model_surface_empty_geometry"
MODEL_SURFACE_INVALID_FILE = "model_surface_invalid_file"
MODEL_SURFACE_THICKNESS_UNKNOWN = "model_surface_thickness_unknown"
MODEL_SURFACE_INSUFFICIENT_THICKNESS = "model_surface_insufficient_thickness"
MODEL_SURFACE_BOOLEAN_FAILED = "model_surface_boolean_failed"


def validate_model_surface_mesh_for_boolean(mesh: trimesh.Trimesh) -> None:
    """Validate that a model-surface mesh is safe for solid booleans.

    验证模型覆面网格能否安全参与实体布尔运算。

    Args:
        mesh: Triangle mesh to validate.
            待验证的三角网格。

    Raises:
        ModelSurfaceError: If the mesh is open, empty, inconsistently wound,
            or does not represent a volume.
            当网格开放、为空、绕序不一致或不构成实体时抛出。
    """

    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ModelSurfaceError(MODEL_SURFACE_MESH_NOT_VOLUME)
    if not mesh.is_watertight:
        raise ModelSurfaceError(MODEL_SURFACE_MESH_NOT_WATERTIGHT)
    if not mesh.is_winding_consistent or not mesh.is_volume:
        raise ModelSurfaceError(MODEL_SURFACE_MESH_NOT_VOLUME)


def prepare_model_surface_mesh_for_boolean(
    mesh: trimesh.Trimesh,
) -> trimesh.Trimesh:
    """Return a validated single-volume mesh for model-surface booleans.

    返回经验证、可用于模型覆面布尔运算的单实体网格。

    Args:
        mesh: Source triangle mesh. Independent positive volumes are unioned;
            reversed inner shells are preserved as cavity geometry.
            源三角网格；独立正体积会合并，反向内壳则保留为空腔几何。

    Returns:
        A copied or unioned volume mesh with source metadata preserved.
        保留源元数据的复制实体或合并实体。

    Raises:
        ModelSurfaceError: If validation or the safe union fails.
            当几何验证或安全合并失败时抛出。
    """

    validate_model_surface_mesh_for_boolean(mesh)
    parts = list(mesh.split(only_watertight=True))
    if len(parts) <= 1:
        return mesh.copy()
    if not all(part.is_volume for part in parts):
        return mesh.copy()

    try:
        result = trimesh.boolean.union(parts, engine="manifold")
    except Exception as exc:
        raise ModelSurfaceError(MODEL_SURFACE_BOOLEAN_FAILED) from exc
    if not isinstance(result, trimesh.Trimesh) or not result.is_volume:
        raise ModelSurfaceError(MODEL_SURFACE_BOOLEAN_FAILED)

    result.metadata.update(mesh.metadata or {})
    return result
