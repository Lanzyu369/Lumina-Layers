from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from core.model_surface.types import LoadedSurfaceMesh, MeshSummary, ModelSurfaceError
from core.model_surface.validation import MODEL_SURFACE_EMPTY_GEOMETRY

SUPPORTED_MODEL_EXTENSIONS = {".stl", ".obj"}


def load_model_surface_mesh(path: str | Path) -> LoadedSurfaceMesh:
    """Load an STL/OBJ model and return geometry with a quality summary.

    载入 STL/OBJ 模型，并返回几何体和质量摘要。

    Args:
        path: STL or OBJ file path.
            STL 或 OBJ 文件路径。

    Returns:
        Loaded mesh and a millimeter-based quality summary.
        已加载网格以及基于毫米单位的质量摘要。

    Raises:
        ModelSurfaceError: If the file is missing, unsupported, empty, or cannot
            be converted into a triangle mesh.
            当文件缺失、格式不支持、为空或无法转换为三角网格时抛出。
    """

    model_path = Path(path)
    suffix = model_path.suffix.lower()
    if suffix not in SUPPORTED_MODEL_EXTENSIONS:
        raise ModelSurfaceError("Only STL and OBJ model files are supported.")
    if not model_path.exists():
        raise ModelSurfaceError(f"Model file does not exist: {model_path}")

    try:
        loaded: Any = trimesh.load_mesh(model_path, process=True, force="mesh")
    except Exception as exc:  # pragma: no cover - delegated parser failures vary
        raise ModelSurfaceError(f"Could not load model file: {exc}") from exc

    mesh = _coerce_trimesh(loaded)
    if mesh.vertices.size == 0 or mesh.faces.size == 0:
        raise ModelSurfaceError(MODEL_SURFACE_EMPTY_GEOMETRY)

    bounds = np.asarray(mesh.bounds, dtype=float)
    extents = np.asarray(mesh.extents, dtype=float)
    if bounds.shape != (2, 3) or extents.shape != (3,) or not np.all(np.isfinite(bounds)):
        raise ModelSurfaceError("Model bounds are invalid.")

    summary = MeshSummary(
        vertex_count=int(len(mesh.vertices)),
        face_count=int(len(mesh.faces)),
        bounds_min_mm=_as_float_tuple(bounds[0]),
        bounds_max_mm=_as_float_tuple(bounds[1]),
        extents_mm=_as_float_tuple(extents),
        is_watertight=bool(mesh.is_watertight),
        is_winding_consistent=bool(mesh.is_winding_consistent),
        body_count=_count_mesh_bodies(mesh),
        unit_warning=_infer_unit_warning(extents),
    )
    return LoadedSurfaceMesh(path=model_path, mesh=mesh, summary=summary)


def _coerce_trimesh(loaded: Any) -> trimesh.Trimesh:
    if isinstance(loaded, trimesh.Trimesh):
        return loaded
    if isinstance(loaded, trimesh.Scene):
        meshes = [
            geometry
            for geometry in loaded.geometry.values()
            if isinstance(geometry, trimesh.Trimesh) and len(geometry.faces) > 0
        ]
        if meshes:
            return trimesh.util.concatenate(meshes)
    raise ModelSurfaceError(MODEL_SURFACE_EMPTY_GEOMETRY)


def _count_mesh_bodies(mesh: trimesh.Trimesh) -> int:
    try:
        parts = mesh.split(only_watertight=False)
    except Exception:
        return 1
    return max(1, len(parts))


def _infer_unit_warning(extents: np.ndarray) -> str | None:
    positive = extents[extents > 0.0]
    if positive.size == 0:
        return None
    longest = float(np.max(positive))
    shortest = float(np.min(positive))
    if longest <= 12.0 and shortest > 0.01:
        return "model_dimensions_look_like_inches"
    if longest >= 1200.0:
        return "model_dimensions_look_too_large_for_mm"
    return None


def _as_float_tuple(values: np.ndarray) -> tuple[float, float, float]:
    return tuple(float(value) for value in values[:3])
