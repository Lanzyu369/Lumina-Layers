"""
S07 — Multi-material 3D mesh generation (parallel ThreadPoolExecutor).
S07 — 多材质 3D 网格生成（支持并行 ThreadPoolExecutor）。

从 converter.py 搬入的网格生成逻辑：
- get_mesher() 调用
- ThreadPoolExecutor 并行网格生成
- scene 构建与 transform 应用
"""

from api.structured_logging import get_logger
import os
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import trimesh
from shapely.geometry import Polygon

from config import PrinterConfig
from core.mesh_generators import get_mesher
from core.task_parallelism import resolve_task_parallelism

_log = get_logger(__name__)


def _timed_generate_mesh(mesher, full_matrix, mat_id, target_h):
    """Wrapper that returns (mesh, elapsed_s) measured inside the worker thread."""
    _t = time.perf_counter()
    result = mesher.generate_mesh(full_matrix, mat_id, target_h)
    return result, time.perf_counter() - _t


def _load_boundary_geometry(boundary_path: str | None):
    """Load optional puzzle boundary geometry from a JSON payload.
    从 JSON 载荷加载可选的拼图边界几何。
    """
    if not boundary_path:
        return None

    with open(boundary_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    polygon_px = payload.get("polygon_px") or []
    holes_px = payload.get("holes_px") or []
    if len(polygon_px) < 3:
        raise ValueError("piece_boundary_geometry_path is missing a valid polygon_px ring.")

    geometry = Polygon(polygon_px, holes=holes_px)
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    if geometry.is_empty:
        raise ValueError("Loaded piece boundary geometry is empty after normalization.")
    return geometry


def run(ctx: dict) -> dict:
    """Generate multi-material 3D meshes with optional parallel execution.
    生成多材质 3D 网格，支持可选的并行执行。

    PipelineContext 输入键 / Input keys:
        - full_matrix (np.ndarray): (Z, H, W) int 体素矩阵
        - slot_names (list[str]): 材料槽位名称列表
        - preview_colors (dict): 材料预览颜色
        - modeling_mode (ModelingMode): 建模模式
        - target_h (int): 图像高度（像素）
        - pixel_scale (float): mm/px 缩放因子

    PipelineContext 输出键 / Output keys:
        - scene (trimesh.Scene): 包含所有材质网格的 3D 场景
        - valid_slot_names (list[str]): 成功生成网格的材料名称列表
        - transform (np.ndarray): 4x4 变换矩阵（像素→mm）
    """
    full_matrix = ctx["full_matrix"]
    slot_names = ctx["slot_names"]
    preview_colors = ctx["preview_colors"]
    modeling_mode = ctx["modeling_mode"]
    target_h = ctx["target_h"]
    pixel_scale = ctx["pixel_scale"]
    piece_boundary_geometry_path = ctx.get("piece_boundary_geometry_path")
    disable_material_dilation = bool(ctx.get("disable_material_dilation", True))
    boundary_geometry = _load_boundary_geometry(piece_boundary_geometry_path)

    _bench_enabled = ctx.get("_bench_enabled", True)
    _mesh_t0 = time.perf_counter() if _bench_enabled else None

    # Build transform matrix: pixel/voxel coords → mm
    scene = trimesh.Scene()

    transform = np.eye(4)
    transform[0, 0] = pixel_scale
    transform[1, 1] = pixel_scale
    transform[2, 2] = PrinterConfig.LAYER_HEIGHT

    _log.debug(
        "Transform: XY=%smm/px, Z=%smm/layer",
        pixel_scale,
        PrinterConfig.LAYER_HEIGHT,
        extra={
            "event": "s07_transform_resolved",
            "pixel_scale": float(pixel_scale),
            "layer_height_mm": float(PrinterConfig.LAYER_HEIGHT),
        },
    )

    mesher = get_mesher(
        modeling_mode,
        disable_material_dilation=disable_material_dilation,
        boundary_geometry=boundary_geometry,
    )
    _log.debug(
        "Using mesher: %s",
        mesher.__class__.__name__,
        extra={"event": "s07_mesher_resolved", "mesher": mesher.__class__.__name__},
    )

    valid_slot_names = []
    num_materials = len(slot_names)
    _log.debug(
        "Generating meshes for %s materials...",
        num_materials,
        extra={"event": "s07_mesh_generation_started", "count": num_materials},
    )

    max_workers = resolve_task_parallelism(
        "raster",
        work_items=num_materials,
        min_parallel_items=2,
        hard_max_workers=4,
    )
    if os.getenv("LUMINA_DISABLE_PARALLEL_MESH", "0") == "1":
        max_workers = 1
    parallel_enabled = max_workers > 1
    mesh_results = {}
    mesh_errors = {}
    mat_timings = {}
    mesh_compute_elapsed = 0.0
    mesh_apply_elapsed = 0.0
    if parallel_enabled:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {
                pool.submit(_timed_generate_mesh, mesher, full_matrix, mat_id, target_h): mat_id
                for mat_id in range(num_materials)
            }
            for future in as_completed(future_map):
                mat_id = future_map[future]
                try:
                    mesh_results[mat_id], mat_timings[mat_id] = future.result()
                    mesh_compute_elapsed += mat_timings[mat_id]
                except (ValueError, TypeError, RuntimeError, OSError) as e:
                    mesh_errors[mat_id] = e
    else:
        for mat_id in range(num_materials):
            try:
                mesh_results[mat_id], mat_timings[mat_id] = _timed_generate_mesh(mesher, full_matrix, mat_id, target_h)
                mesh_compute_elapsed += mat_timings[mat_id]
            except (ValueError, TypeError, RuntimeError, OSError) as e:
                mesh_errors[mat_id] = e

    log_detail = num_materials <= 8
    preview_color_cache = {idx: preview_colors[idx] for idx in range(num_materials)}
    for mat_id in range(num_materials):
        if mat_id in mesh_errors:
            e = mesh_errors[mat_id]
            _log.warning(
                "Error generating mesh for material %s (%s): %s",
                mat_id,
                slot_names[mat_id],
                e,
                extra={
                    "event": "s07_material_mesh_failed",
                    "material_id": int(mat_id),
                    "material": slot_names[mat_id],
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            _log.debug("Continuing with other materials...")
            continue
        mesh = mesh_results.get(mat_id)
        if mesh:
            _apply_t0 = time.perf_counter()
            mesh.apply_transform(transform)
            mesh.visual.face_colors = preview_color_cache[mat_id]
            name = slot_names[mat_id]
            mesh.metadata["name"] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)
            mesh_apply_elapsed += time.perf_counter() - _apply_t0
            valid_slot_names.append(name)
            _mt = mat_timings.get(mat_id, 0.0)
            if log_detail:
                _log.debug(
                    "%s: %sv %sf  %.3fs",
                    name,
                    len(mesh.vertices),
                    len(mesh.faces),
                    _mt,
                    extra={
                        "event": "s07_material_mesh_generated",
                        "material_id": int(mat_id),
                        "material": name,
                        "vertex_count": int(len(mesh.vertices)),
                        "face_count": int(len(mesh.faces)),
                        "duration_ms": round(_mt * 1000, 3),
                    },
                )

    if _bench_enabled and _mesh_t0 is not None:
        _mesh_elapsed = time.perf_counter() - _mesh_t0
        _hifi_timings = ctx.setdefault("_hifi_timings", {})
        _hifi_timings["mesh_gen_s"] = _mesh_elapsed
        _hifi_timings["mesh_compute_s"] = mesh_compute_elapsed
        _hifi_timings["mesh_apply_transform_s"] = mesh_apply_elapsed
        _hifi_timings["mesh_parallelism_workers"] = int(max_workers)
        _log.debug(
            "mesh_gen done: %.3fs",
            _mesh_elapsed,
            extra={
                "event": "s07_mesh_gen_done",
                "duration_ms": round(_mesh_elapsed * 1000, 3),
                "count": len(valid_slot_names),
                "material_count": num_materials,
                "error_count": len(mesh_errors),
                "parallel_enabled": bool(parallel_enabled),
                "worker_count": int(max_workers),
            },
        )

    ctx["scene"] = scene
    ctx["valid_slot_names"] = valid_slot_names
    ctx["transform"] = transform
    ctx["mesher"] = mesher
    ctx["boundary_geometry"] = boundary_geometry
    ctx["disable_material_dilation"] = disable_material_dilation

    return ctx
