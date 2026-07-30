#!/usr/bin/env python3
"""Profile single-task converter workloads without changing output quality.

在不改变输出质量的前提下分析转换器单任务工作负载。
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import math
import os
import pickle
import platform
import pstats
import statistics
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Literal

import numpy as np
import psutil
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import ModelingMode
from core.pipeline.coordinator import run_preview_pipeline, run_raster_pipeline


_BASE_EIGHT = [
    "纵维立方/纵维立方PLA白色",
    "纵维立方/纵维立方PLA黑色",
    "纵维立方/纵维立方PLA红色",
    "纵维立方/纵维立方PLA黄色",
    "纵维立方/纵维立方PLA蓝色",
    "纵维立方/纵维立方PLA绿色",
    "纵维立方/纵维立方PLA青色",
    "纵维立方/纵维立方PLA品红色",
]
_EXTRA_SEVEN = [
    "Karvax/Karvax PLA 晴山蓝",
    "Karvax/Karvax PLA 流光蓝",
    "Karvax/Karvax PLA 烟笼紫霞",
    "Karvax/Karvax PLA 暖黄",
    "Karvax/Karvax PLA 朱砂红",
    "Karvax/Karvax PLA 拓竹绿",
    "Karvax/Karvax PLA 耀石黑",
]
MATERIAL_PALETTES = {
    8: list(_BASE_EIGHT),
    12: [*_BASE_EIGHT, *_EXTRA_SEVEN[:4]],
    15: [*_BASE_EIGHT, *_EXTRA_SEVEN],
}
_NUMERIC_RUN_METRICS = (
    "total_s",
    "queue_wait_s",
    "worker_execution_s",
    "cpu_s",
    "average_cpu_percent",
    "rss_at_start_mb",
    "peak_rss_mb",
    "peak_rss_increase_mb",
    "peak_thread_count",
    "peak_child_process_count",
)
_THREAD_ENVIRONMENT_KEYS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "BLIS_NUM_THREADS",
)
_CANONICAL_TRIANGLE_CHUNK_FACES = 250_000
OverrideScenario = Literal["none", "matched-rgb", "recipe", "combined"]


@dataclass(frozen=True)
class ProfileCase:
    """Describe one deterministic converter profiling case.

    描述一个确定性的转换器性能分析案例。

    Attributes:
        name: Stable case identifier. 稳定的案例标识。
        kind: Raster or vector workflow. 位图或矢量工作流。
        input_path: Source asset path. 输入素材路径。
        target_width_mm: Requested model width. 目标模型宽度。
        material_count: Material Archive palette size. 耗材档案颜色数量。
    """

    name: str
    kind: Literal["raster", "vector"]
    input_path: Path
    target_width_mm: float
    material_count: Literal[8, 12, 15] = 12
    override_scenario: OverrideScenario = "none"


def build_pipeline_context(case: ProfileCase) -> dict[str, Any]:
    """Build a quality-locked pipeline context for a profile case.

    为性能分析案例构建质量参数锁定的流水线上下文。

    Args:
        case: Deterministic profile case. 确定性的性能分析案例。

    Returns:
        Context accepted by the raster or vector pipeline.
        位图或矢量流水线可接受的上下文字典。
    """

    modeling_mode = (
        ModelingMode.VECTOR
        if case.kind == "vector"
        else ModelingMode.HIGH_FIDELITY
    )
    return {
        "image_path": str(case.input_path),
        "lut_path": "__material_archive__",
        "target_width_mm": float(case.target_width_mm),
        "spacer_thick": 1.2,
        "structure_mode": "single-sided",
        "color_mode": "4-Color (RYBW)",
        "add_loop": False,
        "loop_width": 4.0,
        "loop_length": 8.0,
        "loop_hole": 2.5,
        "loop_pos": None,
        "modeling_mode": modeling_mode,
        "color_layers": 10,
        "layer_height_mm": 0.08,
        "quantize_colors": 64,
        "color_replacements": None,
        "replacement_regions": None,
        "backing_color_id": 0,
        "separate_backing": False,
        "enable_relief": False,
        "color_height_map": None,
        "height_mode": "color",
        "heightmap_path": None,
        "heightmap_max_height": None,
        "enable_cleanup": True,
        "enable_outline": False,
        "outline_width": 2.0,
        "enable_cloisonne": False,
        "wire_width_mm": 0.4,
        "wire_height_mm": 0.4,
        "free_color_set": None,
        "enable_coating": False,
        "coating_height_mm": 0.08,
        "hue_weight": 0.5,
        "chroma_gate": 15.0,
        "matched_rgb_path": None,
        "loop_angle": 0.0,
        "loop_offset_x": 0.0,
        "loop_offset_y": 0.0,
        "loop_position_preset": "top-center",
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "nozzle_size": "0.4",
        "relief_global_max_height": None,
        "progress": None,
        "need_2d_preview": False,
        "material_source": "material_archive",
        "selected_materials": list(MATERIAL_PALETTES[case.material_count]),
        "material_layer_count": 10,
        "material_layer_height_mm": 0.08,
        "material_grid_resolution": 64,
        "material_backing_material_index": 0,
        "use_lut_constrained": False,
        "auto_dynamic_range": False,
        "high_precision_3d_preview": False,
        "retain_scene_for_profile": True,
    }


def _build_vector_override_context(
    preview_result: dict[str, Any],
    *,
    output_dir: Path,
    scenario: OverrideScenario,
) -> dict[str, Any]:
    """Persist a deterministic, private vector override fixture.

    The returned paths are temporary inputs for one profiling session. No
    source path, RGB payload, or material matrix is copied into the report.
    为一次性能会话保存确定性的私有覆盖输入，报告中不写入颜色矩阵。
    """
    if scenario not in {"matched-rgb", "recipe", "combined"}:
        raise ValueError("override scenario must require an override")
    cache = preview_result.get("cache")
    if not isinstance(cache, dict):
        raise ValueError("vector preview result has no cache")

    matched_rgb = np.asarray(cache.get("matched_rgb")).copy()
    material_matrix = np.asarray(cache.get("material_matrix")).copy()
    raw_mask = np.asarray(cache.get("mask_solid"))
    mask_solid = raw_mask.astype(bool, copy=True)
    raw_identity = cache.get(
        "height_identity_rgb",
        cache.get("original_matched_rgb", matched_rgb),
    )
    height_identity_rgb = np.asarray(raw_identity).copy()
    if (
        matched_rgb.ndim != 3
        or matched_rgb.shape[2] != 3
        or matched_rgb.dtype != np.uint8
    ):
        raise ValueError("vector preview matched_rgb is not (H,W,3) uint8")
    if (
        height_identity_rgb.shape != matched_rgb.shape
        or height_identity_rgb.dtype != np.uint8
    ):
        raise ValueError("vector preview height identity grid is incompatible")
    if (
        mask_solid.shape != matched_rgb.shape[:2]
        or raw_mask.dtype != np.dtype(np.bool_)
    ):
        raise ValueError("vector preview mask_solid is incompatible")
    if (
        material_matrix.ndim != 3
        or material_matrix.shape[:2] != matched_rgb.shape[:2]
        or material_matrix.shape[2] <= 0
        or not np.issubdtype(material_matrix.dtype, np.integer)
    ):
        raise ValueError("vector preview material_matrix is incompatible")

    solid_positions = np.argwhere(mask_solid)
    if solid_positions.size == 0:
        raise ValueError("vector preview has no solid pixels to override")
    height, width = mask_solid.shape
    yy, xx = np.indices((height, width), dtype=np.int32)
    block_height = max(1, height // 9)
    block_width = max(1, width // 9)
    selected = mask_solid & (
        ((yy // block_height) + (xx // block_width)) % 3 == 0
    )
    if not np.any(selected):
        first_y, first_x = solid_positions[0]
        selected[int(first_y), int(first_x)] = True

    rgb_codes = (
        matched_rgb[..., 0].astype(np.uint32) * np.uint32(65536)
        + matched_rgb[..., 1].astype(np.uint32) * np.uint32(256)
        + matched_rgb[..., 2].astype(np.uint32)
    )
    solid_codes = np.unique(rgb_codes[mask_solid])
    selected_codes = rgb_codes[selected]
    target_code = min(
        (
            int(np.count_nonzero(selected_codes == code)),
            int(code),
        )
        for code in solid_codes
    )[1]
    target_positions = np.argwhere(mask_solid & (rgb_codes == target_code))
    target_y, target_x = (int(value) for value in target_positions[0])
    target_rgb = matched_rgb[target_y, target_x].copy()
    target_stack = material_matrix[target_y, target_x].copy()

    original_matched = matched_rgb.copy()
    original_material = material_matrix.copy()
    if scenario in {"matched-rgb", "combined"}:
        matched_rgb[selected] = target_rgb
        material_matrix[selected] = target_stack

    output_dir.mkdir(parents=True, exist_ok=True)
    array_paths = {
        "matched_rgb_path": output_dir / "matched-rgb.npy",
        "height_identity_rgb_path": output_dir / "height-identity-rgb.npy",
        "material_matrix_path": output_dir / "material-matrix.npy",
        "mask_solid_path": output_dir / "mask-solid.npy",
    }
    for key, array in (
        ("matched_rgb_path", matched_rgb),
        ("height_identity_rgb_path", height_identity_rgb),
        ("material_matrix_path", material_matrix),
        ("mask_solid_path", mask_solid),
    ):
        np.save(array_paths[key], array, allow_pickle=False)

    parse_cache_blob = cache.get("vector_parse_clip_cache_blob")
    if not isinstance(parse_cache_blob, (bytes, bytearray)):
        raise ValueError("vector preview has no parse/clip cache artifact")
    parse_cache_path = output_dir / "vector-parse-clip-cache.pkl"
    parse_cache_path.write_bytes(bytes(parse_cache_blob))

    recipe_overrides = None
    recipe_override_masks_path = None
    if scenario in {"recipe", "combined"}:
        recipe_overrides = [
            {
                "region_id": "profile-override-region",
                "recipe": [int(value) for value in target_stack.tolist()],
                "layer_order": "Top2Bottom",
            }
        ]
        recipe_override_masks_path = output_dir / "recipe-override-masks.pkl"
        with recipe_override_masks_path.open("wb") as handle:
            pickle.dump(
                {"profile-override-region": selected},
                handle,
                protocol=pickle.HIGHEST_PROTOCOL,
            )

    from core.preview_analysis_cache import REQUIRED_PREVIEW_ANALYSIS_REUSE

    return {
        **{
            key: str(path)
            for key, path in array_paths.items()
        },
        "vector_parse_clip_cache_path": str(parse_cache_path),
        "recipe_overrides": recipe_overrides,
        "recipe_override_masks_path": (
            str(recipe_override_masks_path)
            if recipe_override_masks_path is not None
            else None
        ),
        "reuse_preview_analysis": REQUIRED_PREVIEW_ANALYSIS_REUSE,
        "profile_override_fixture": {
            "scenario": scenario,
            "grid_shape": [int(height), int(width)],
            "selected_pixel_count": int(np.count_nonzero(selected)),
            "matched_rgb_changed_pixel_count": int(
                np.count_nonzero(
                    np.any(matched_rgb != original_matched, axis=2)
                )
            ),
            "material_changed_pixel_count": int(
                np.count_nonzero(
                    np.any(material_matrix != original_material, axis=2)
                )
            ),
            "material_layer_count": int(material_matrix.shape[2]),
        },
    }


def _prepare_vector_override_context(
    case: ProfileCase,
    *,
    output_dir: Path,
) -> dict[str, Any]:
    """Build an untimed preview and persist its deterministic override inputs."""
    preview_result = run_preview_pipeline(build_pipeline_context(case))
    try:
        if preview_result.get("error"):
            raise RuntimeError(str(preview_result["error"]))
        return _build_vector_override_context(
            preview_result,
            output_dir=output_dir,
            scenario=case.override_scenario,
        )
    finally:
        _cleanup_result_files(preview_result)


def _array_summary(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    array = np.ascontiguousarray(np.asarray(value))
    digest = hashlib.sha256()
    digest.update(array.dtype.str.encode("ascii"))
    digest.update(repr(tuple(int(item) for item in array.shape)).encode("ascii"))
    digest.update(memoryview(array).cast("B"))
    return {
        "shape": [int(item) for item in array.shape],
        "dtype": array.dtype.str,
        "sha256": digest.hexdigest(),
    }


def _canonical_oriented_triangle_rows(
    mesh: trimesh.Trimesh,
) -> tuple[np.ndarray, np.ndarray]:
    """Return winding-preserving triangle rows and their cyclic rotations."""

    vertices = np.round(np.asarray(mesh.vertices, dtype=np.float64), 9)
    vertices[vertices == 0.0] = 0.0
    faces = np.asarray(mesh.faces, dtype=np.int64)
    flattened = np.empty((faces.shape[0], 9), dtype=np.float64)
    rotations = np.zeros((faces.shape[0],), dtype=np.uint8)

    # A triangle may start at any of its three vertices without changing its
    # directed face. Only canonicalize over cyclic rotations: sorting all
    # vertices would also erase winding and could hide flipped normals.
    # Process bounded chunks so multi-million-face exports do not retain three
    # full triangle tensors at once during post-run quality verification.
    chunk_size = max(1, int(_CANONICAL_TRIANGLE_CHUNK_FACES))
    for start in range(0, faces.shape[0], chunk_size):
        end = min(start + chunk_size, faces.shape[0])
        triangles = vertices[faces[start:end]]
        canonical_chunk = np.ascontiguousarray(
            triangles.reshape((-1, 9)),
        ).copy()
        for vertex_order in ((1, 2, 0), (2, 0, 1)):
            candidate = np.ascontiguousarray(
                triangles[:, vertex_order, :].reshape((-1, 9)),
            )
            candidate_is_less = np.zeros(
                (candidate.shape[0],),
                dtype=bool,
            )
            columns_are_equal = np.ones(
                (candidate.shape[0],),
                dtype=bool,
            )
            for column_index in range(candidate.shape[1]):
                candidate_column = candidate[:, column_index]
                current_column = canonical_chunk[:, column_index]
                is_less = candidate_column < current_column
                is_greater = candidate_column > current_column
                candidate_is_less |= columns_are_equal & is_less
                columns_are_equal &= ~(is_less | is_greater)
            canonical_chunk[candidate_is_less] = candidate[
                candidate_is_less
            ]
            rotations[start:end][candidate_is_less] = vertex_order[0]
        flattened[start:end] = canonical_chunk
    return flattened, rotations


def _semantic_record_order(
    triangle_rows: np.ndarray,
    payload_rows: np.ndarray | None = None,
) -> np.ndarray:
    """Return stable lexicographic order for geometry-bound semantic rows."""

    columns = [triangle_rows[:, index] for index in range(triangle_rows.shape[1])]
    if payload_rows is not None:
        payload = np.asarray(payload_rows)
        if payload.ndim == 1:
            payload = payload[:, None]
        columns.extend(payload[:, index] for index in range(payload.shape[1]))
    return np.lexsort(
        tuple(reversed(columns)),
    )


def _canonical_triangle_sha256(mesh: trimesh.Trimesh) -> str:
    triangle_rows, _rotations = _canonical_oriented_triangle_rows(mesh)
    face_order = _semantic_record_order(triangle_rows)
    canonical = np.ascontiguousarray(triangle_rows[face_order])
    return hashlib.sha256(memoryview(canonical).cast("B")).hexdigest()


def _semantic_payload_summary(
    triangle_rows: np.ndarray,
    payload_rows: np.ndarray,
) -> dict[str, object]:
    """Hash values jointly with the canonical geometry elements they affect."""

    payload = np.asarray(payload_rows)
    if payload.ndim == 1:
        payload = payload[:, None]
    if payload.shape[0] != triangle_rows.shape[0]:
        raise ValueError("visual payload row count does not match mesh faces")
    order = _semantic_record_order(triangle_rows, payload)
    canonical_triangles = np.ascontiguousarray(triangle_rows[order])
    canonical_payload = np.ascontiguousarray(payload[order])
    digest = hashlib.sha256()
    digest.update(canonical_triangles.dtype.str.encode("ascii"))
    digest.update(memoryview(canonical_triangles).cast("B"))
    digest.update(canonical_payload.dtype.str.encode("ascii"))
    digest.update(repr(tuple(int(item) for item in canonical_payload.shape)).encode("ascii"))
    digest.update(memoryview(canonical_payload).cast("B"))
    return {
        "shape": [int(item) for item in canonical_payload.shape],
        "dtype": canonical_payload.dtype.str,
        "canonical_sha256": digest.hexdigest(),
    }


def _canonical_corner_payload_rows(
    mesh: trimesh.Trimesh,
    vertex_values: np.ndarray,
    rotations: np.ndarray,
) -> np.ndarray:
    """Bind vertex values to oriented triangle corners in canonical rotation."""

    values = np.asarray(vertex_values)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if values.ndim == 1:
        values = values[:, None]
    if values.shape[0] != len(mesh.vertices):
        raise ValueError("vertex visual row count does not match mesh vertices")
    corners = values[faces]
    rotated = corners.copy()
    for rotation, vertex_order in (
        (1, (1, 2, 0)),
        (2, (2, 0, 1)),
    ):
        mask = rotations == rotation
        if np.any(mask):
            rotated[mask] = corners[mask][:, vertex_order, :]
    return rotated.reshape((faces.shape[0], -1))


def _texture_image_summary(value: object) -> dict[str, object] | None:
    """Return exact texture pixels, failing closed for unsupported values."""

    if value is None:
        return None
    image_array = np.asarray(value)
    if image_array.dtype == object or image_array.ndim < 2:
        raise ValueError("unsupported texture image payload")
    return _array_summary(image_array)


def _mesh_visual_summary(
    mesh: trimesh.Trimesh,
    *,
    triangle_rows: np.ndarray,
    rotations: np.ndarray,
) -> dict[str, object]:
    """Summarize visible colors bound to canonical geometry elements."""

    visual = mesh.visual
    kind = str(getattr(visual, "kind", None) or "none")
    summary: dict[str, object] = {"kind": kind}
    if kind == "face":
        summary["face_colors"] = _semantic_payload_summary(
            triangle_rows,
            np.asarray(visual.face_colors),
        )
    elif kind == "vertex":
        corner_colors = _canonical_corner_payload_rows(
            mesh,
            np.asarray(visual.vertex_colors),
            rotations,
        )
        summary["vertex_colors"] = _semantic_payload_summary(
            triangle_rows,
            corner_colors,
        )
    elif kind == "texture":
        uv = getattr(visual, "uv", None)
        material = getattr(visual, "material", None)
        texture_summaries: dict[str, object] = {}
        if material is not None:
            for attribute in (
                "baseColorFactor",
                "diffuse",
                "main_color",
                "name",
            ):
                value = getattr(material, attribute, None)
                if value is None:
                    continue
                if isinstance(value, str):
                    summary[f"material_{attribute}"] = value
                    continue
                try:
                    summary[f"material_{attribute}"] = _array_summary(value)
                except (TypeError, ValueError):
                    summary[f"material_{attribute}"] = str(value)
            for texture_attribute in (
                "image",
                "baseColorTexture",
                "metallicRoughnessTexture",
                "normalTexture",
                "emissiveTexture",
                "occlusionTexture",
            ):
                texture = getattr(material, texture_attribute, None)
                texture_summary = _texture_image_summary(texture)
                if texture_summary is not None:
                    texture_summaries[
                        f"material_{texture_attribute}"
                    ] = texture_summary
        if uv is None:
            if texture_summaries:
                raise ValueError(
                    "textured material has image payloads but no UV coordinates"
                )
            summary["uv"] = None
        else:
            corner_uv = _canonical_corner_payload_rows(
                mesh,
                np.asarray(uv),
                rotations,
            )
            summary["uv"] = _semantic_payload_summary(
                triangle_rows,
                corner_uv,
            )
        summary.update(texture_summaries)
    return summary


def _mesh_summary(
    mesh: trimesh.Trimesh,
    *,
    visual_source: trimesh.Trimesh | None = None,
) -> dict[str, object]:
    triangle_rows, rotations = _canonical_oriented_triangle_rows(mesh)
    face_order = _semantic_record_order(triangle_rows)
    canonical_triangles = np.ascontiguousarray(triangle_rows[face_order])
    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    source = visual_source if visual_source is not None else mesh
    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "bounds": np.round(bounds, 9).tolist(),
        "area": round(float(mesh.area), 9),
        "volume": round(float(mesh.volume), 9),
        "watertight": bool(mesh.is_watertight),
        "euler_number": int(mesh.euler_number),
        "degenerate_faces": int(
            np.count_nonzero(np.asarray(mesh.area_faces) <= 1e-12)
        ),
        "canonical_triangle_sha256": hashlib.sha256(
            memoryview(canonical_triangles).cast("B"),
        ).hexdigest(),
        "visual": _mesh_visual_summary(
            source,
            triangle_rows=triangle_rows,
            rotations=rotations,
        ),
    }


def _scene_instance_summaries(
    scene: trimesh.Scene,
    geometry_summaries: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """Summarize every named geometry instance in world coordinates."""

    summaries: list[dict[str, object]] = []
    reusable_summaries = geometry_summaries or {}
    for node_name in sorted(scene.graph.nodes_geometry, key=str):
        transform, geometry_name = scene.graph[node_name]
        raw = scene.geometry.get(geometry_name)
        if not isinstance(raw, trimesh.Trimesh):
            continue
        world_transform = np.asarray(transform, dtype=np.float64)
        geometry_key = str(geometry_name)
        if (
            np.array_equal(world_transform, np.eye(4, dtype=np.float64))
            and geometry_key in reusable_summaries
        ):
            summaries.append(
                {
                    "geometry": geometry_key,
                    "world": reusable_summaries[geometry_key],
                }
            )
            continue
        if np.array_equal(world_transform, np.eye(4, dtype=np.float64)):
            world_mesh = raw
        else:
            world_mesh = trimesh.Trimesh(
                vertices=trimesh.transform_points(
                    np.asarray(raw.vertices, dtype=np.float64),
                    world_transform,
                ),
                faces=np.asarray(raw.faces, dtype=np.int64),
                process=False,
            )
        world_summary = _mesh_summary(world_mesh, visual_source=raw)
        summaries.append(
            {
                "geometry": geometry_key,
                "world": world_summary,
            }
        )

    # Node names and insertion order are serialization details. Geometry names
    # carry stable material identity, so retain them while preserving duplicate
    # entries for repeated instances.
    return sorted(
        summaries,
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
    )


def _load_exported_scene(
    ctx: dict[str, Any],
) -> tuple[trimesh.Scene | None, str | None]:
    result_tuple = ctx.get("result_tuple")
    if not isinstance(result_tuple, (list, tuple)):
        return None, None
    for index in (0, 1):
        if index >= len(result_tuple) or not result_tuple[index]:
            continue
        artifact_path = Path(str(result_tuple[index]))
        if not artifact_path.is_file():
            continue
        try:
            scene = trimesh.load_scene(artifact_path, process=False)
        except Exception:
            # Optional profile boundary: one unreadable artifact must not hide
            # array semantics from an otherwise successful pipeline run.
            continue
        if scene.geometry:
            return scene, f"artifact:{artifact_path.suffix.lower()}"
    return None, None


def _export_artifact_summaries(
    ctx: dict[str, Any],
) -> dict[str, object]:
    """Hash final artifacts while ignoring ZIP compression and timestamps."""

    result_tuple = ctx.get("result_tuple")
    tuple_values = (
        list(result_tuple)
        if isinstance(result_tuple, (list, tuple))
        else []
    )
    candidates = (
        (
            "model",
            tuple_values[0] if len(tuple_values) > 0 else ctx.get("out_path"),
        ),
        (
            "preview",
            tuple_values[1] if len(tuple_values) > 1 else ctx.get("glb_path"),
        ),
        (
            "recipe",
            tuple_values[4]
            if len(tuple_values) > 4
            else ctx.get("color_recipe_path"),
        ),
    )
    summaries: dict[str, object] = {}
    for role, raw_path in candidates:
        if not raw_path:
            continue
        path = Path(str(raw_path))
        if not path.is_file():
            raise ValueError(f"profile output artifact is missing for role {role}")
        suffix = path.suffix.lower()
        if suffix in {".3mf", ".zip"}:
            try:
                with zipfile.ZipFile(path, "r") as archive:
                    members = []
                    for member_name in sorted(archive.namelist()):
                        if member_name.endswith("/"):
                            continue
                        member_info = archive.getinfo(member_name)
                        digest = hashlib.sha256()
                        size_bytes = 0
                        canonicalization = "raw_member"
                        if (
                            member_name == "Metadata/model_settings.config"
                            and member_info.file_size <= 16 * 1024 * 1024
                        ):
                            with archive.open(member_name, "r") as member:
                                payload = member.read()
                            root = ET.fromstring(payload)
                            for element in root.iter():
                                if (
                                    element.tag.rsplit("}", 1)[-1] == "metadata"
                                    and element.attrib.get("key") == "source_file"
                                ):
                                    element.attrib["value"] = (
                                        "<profile-source-file>"
                                    )
                                sorted_attributes = sorted(
                                    element.attrib.items()
                                )
                                element.attrib.clear()
                                element.attrib.update(sorted_attributes)
                                if (
                                    element.text is not None
                                    and not element.text.strip()
                                ):
                                    element.text = None
                                if (
                                    element.tail is not None
                                    and not element.tail.strip()
                                ):
                                    element.tail = None
                            canonical_payload = ET.tostring(
                                root,
                                encoding="utf-8",
                            )
                            digest.update(canonical_payload)
                            size_bytes = len(canonical_payload)
                            canonicalization = (
                                "xml_without_source_filename"
                            )
                        else:
                            with archive.open(member_name, "r") as member:
                                for chunk in iter(
                                    lambda: member.read(1024 * 1024),
                                    b"",
                                ):
                                    digest.update(chunk)
                                    size_bytes += len(chunk)
                        members.append(
                            {
                                "name": member_name,
                                "size_bytes": size_bytes,
                                "sha256": digest.hexdigest(),
                                "canonicalization": canonicalization,
                            }
                        )
            except (OSError, zipfile.BadZipFile, KeyError) as exc:
                raise ValueError(
                    f"profile output archive is unreadable for role {role}"
                ) from exc
            summaries[role] = {
                "kind": "zip_members",
                "suffix": suffix,
                "members": members,
            }
        else:
            summaries[role] = {
                "kind": "file",
                "suffix": suffix,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
    return summaries


def _semantic_array_value(
    ctx: dict[str, Any],
    payload: dict[str, Any],
    key: str,
) -> object:
    """Resolve an in-memory array or its private temporary ``.npy`` path."""
    value = payload.get(key)
    if value is None and payload is not ctx:
        value = ctx.get(key)
    if value is not None:
        return value
    raw_path = ctx.get(f"{key}_path")
    if raw_path is None and payload is not ctx:
        raw_path = payload.get(f"{key}_path")
    if raw_path is None:
        return None
    path = Path(str(raw_path))
    if not path.is_file():
        raise ValueError(f"profile semantic array is missing: {key}")
    return np.load(path, allow_pickle=False)


def semantic_snapshot(ctx: dict[str, Any]) -> dict[str, object]:
    """Summarize output arrays and geometry using deterministic semantics.

    以确定性语义摘要记录输出数组与几何结果。

    Args:
        ctx: Completed pipeline context. 已完成的流水线上下文。

    Returns:
        Order-independent semantic snapshot. 与顺序无关的语义快照。
    """

    cache = ctx.get("cache")
    payload = cache if isinstance(cache, dict) else ctx
    scene = ctx.get("scene")
    if scene is None:
        scene = payload.get("scene")
    geometry_source = "context" if isinstance(scene, trimesh.Scene) else None
    if not isinstance(scene, trimesh.Scene):
        scene, geometry_source = _load_exported_scene(ctx)
    geometry: dict[str, object] = {}
    scene_instances: list[dict[str, object]] = []
    if isinstance(scene, trimesh.Scene):
        for name in sorted(scene.geometry):
            raw = scene.geometry[name]
            if isinstance(raw, trimesh.Trimesh):
                geometry[str(name)] = _mesh_summary(raw)
        scene_instances = _scene_instance_summaries(scene, geometry)
    return {
        "matched_rgb": _array_summary(
            _semantic_array_value(ctx, payload, "matched_rgb")
        ),
        "height_identity_rgb": _array_summary(
            _semantic_array_value(ctx, payload, "height_identity_rgb")
        ),
        "material_matrix": _array_summary(
            _semantic_array_value(ctx, payload, "material_matrix")
        ),
        "mask_solid": _array_summary(
            _semantic_array_value(ctx, payload, "mask_solid")
        ),
        "slot_names": [str(item) for item in payload.get("slot_names") or []],
        "geometry_source": geometry_source,
        "geometry": geometry,
        "scene_instances": scene_instances,
        "artifacts": _export_artifact_summaries(ctx),
    }


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("values must not be empty")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, object]:
    """Summarize cold, warm, percentile, and peak profile metrics.

    汇总冷启动、热启动、分位数和峰值性能指标。

    Args:
        runs: Chronological profiling runs. 按时间顺序排列的分析结果。

    Returns:
        Numeric summary while retaining the complete cold run.
        保留完整冷启动结果的数值汇总。

    Raises:
        ValueError: If no run is provided. 未提供运行结果时抛出。
    """

    if not runs:
        raise ValueError("runs must not be empty")
    keys = [
        key
        for key in _NUMERIC_RUN_METRICS
        if any(key in run for run in runs)
    ]
    warm = runs[1:] or runs

    def values_for(key: str, candidates: list[dict[str, Any]]) -> list[float]:
        values = [float(run[key]) for run in candidates if key in run]
        return values or [float(run[key]) for run in runs if key in run]

    return {
        "cold": dict(runs[0]),
        "warm_median": {
            key: statistics.median(values_for(key, warm))
            for key in keys
        },
        "p90": {
            key: _percentile(values_for(key, warm), 0.90)
            for key in keys
        },
        "peak": {
            key: max(values_for(key, runs))
            for key in keys
        },
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_report(
    case: ProfileCase,
    runs: list[dict[str, Any]],
) -> dict[str, object]:
    """Build a report that excludes private absolute input/material paths.

    构建不包含私有输入绝对路径和耗材目录名的报告。

    Args:
        case: Profile case metadata. 性能分析案例元数据。
        runs: Raw per-run measurements. 每轮原始测量结果。

    Returns:
        Sanitized, JSON-serializable report. 已脱敏且可序列化的报告。

    Raises:
        ValueError: If measured semantic snapshots differ between runs.
            多轮测量的语义快照不一致时抛出。
    """

    semantic_snapshots = [
        run["semantic_snapshot"]
        for run in runs
        if "semantic_snapshot" in run
    ]
    semantic_snapshot_count = len(semantic_snapshots)
    semantic_snapshots_available = (
        bool(semantic_snapshots)
        and semantic_snapshot_count == len(runs)
    )
    semantic_snapshots_consistent = (
        semantic_snapshots_available
        and all(
            snapshot == semantic_snapshots[0]
            for snapshot in semantic_snapshots[1:]
        )
    )
    semantic_snapshots_equal = (
        semantic_snapshot_count >= 2
        and semantic_snapshots_consistent
    )
    if (
        semantic_snapshots_available
        and semantic_snapshot_count >= 2
        and not semantic_snapshots_consistent
    ):
        raise ValueError("Profile run semantic snapshots differ")
    reference_sha256 = None
    if semantic_snapshots_consistent:
        reference_payload = json.dumps(
            semantic_snapshots[0],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        reference_sha256 = hashlib.sha256(reference_payload).hexdigest()

    return {
        "schema": "lumina_converter_multicore_profile_v2",
        "machine": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "visible_cpu": os.cpu_count(),
        },
        "thread_environment": {
            key: os.getenv(key)
            for key in _THREAD_ENVIRONMENT_KEYS
        },
        "input": {
            "name": case.input_path.name,
            "sha256": _sha256_file(case.input_path),
            "kind": case.kind,
            "target_width_mm": case.target_width_mm,
            "override_scenario": case.override_scenario,
        },
        "materials": {
            "count": case.material_count,
            "palette_sha256": hashlib.sha256(
                "\n".join(MATERIAL_PALETTES[case.material_count]).encode("utf-8")
            ).hexdigest(),
        },
        "quality": {
            "semantic_snapshot_count": semantic_snapshot_count,
            "semantic_snapshots_available": semantic_snapshots_available,
            "semantic_snapshots_equal": semantic_snapshots_equal,
            "reference_sha256": reference_sha256,
        },
        "override": {
            "scenario": case.override_scenario,
        },
        "runs": runs,
        "summary": summarize_runs(runs),
    }


def _assert_semantic_reference(
    reference_report: dict[str, object],
    candidate_report: dict[str, object],
) -> str:
    """Fail unless two reports carry the same complete semantic snapshot hash."""

    if reference_report.get("schema") != candidate_report.get("schema"):
        raise ValueError("Semantic reference schema does not match candidate")
    for metadata_key in ("input", "materials", "phase"):
        if reference_report.get(metadata_key) != candidate_report.get(metadata_key):
            raise ValueError(
                f"Semantic reference {metadata_key} does not match candidate"
            )
    reference_quality = reference_report.get("quality")
    candidate_quality = candidate_report.get("quality")
    if not isinstance(reference_quality, dict) or not isinstance(
        candidate_quality,
        dict,
    ):
        raise ValueError("Semantic reference report has no quality metadata")
    reference_hash = reference_quality.get("reference_sha256")
    candidate_hash = candidate_quality.get("reference_sha256")
    if not isinstance(reference_hash, str) or not isinstance(candidate_hash, str):
        raise ValueError("Semantic reference comparison requires captured snapshots")
    if reference_hash != candidate_hash:
        raise ValueError("Candidate semantic snapshot differs from reference")
    return candidate_hash


class _ResourceSampler:
    def __init__(self, process: psutil.Process, interval_s: float = 0.25) -> None:
        self._process = process
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.initial_rss_bytes = 0
        self.peak_rss_bytes = 0
        self.peak_thread_count = 0
        self.peak_child_process_count = 0

    def _sample(self) -> int | None:
        try:
            children = self._process.children(recursive=True)
            processes = [self._process, *children]
            rss_bytes = 0
            thread_count = 0
            for process in processes:
                try:
                    rss_bytes += process.memory_info().rss
                    thread_count += process.num_threads()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self.peak_rss_bytes = max(self.peak_rss_bytes, rss_bytes)
            self.peak_thread_count = max(self.peak_thread_count, thread_count)
            self.peak_child_process_count = max(
                self.peak_child_process_count,
                len(children),
            )
            return rss_bytes
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def _run(self) -> None:
        while not self._stop.wait(self._interval_s):
            self._sample()

    def __enter__(self) -> "_ResourceSampler":
        initial_rss_bytes = self._sample()
        if initial_rss_bytes is not None:
            self.initial_rss_bytes = initial_rss_bytes
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._sample()


def _cleanup_result_files(result: dict[str, Any]) -> None:
    raw_paths = [
        result.get("out_path"),
        result.get("glb_path"),
        result.get("color_recipe_path"),
    ]
    result_tuple = result.get("result_tuple")
    if isinstance(result_tuple, (list, tuple)):
        raw_paths.extend(
            result_tuple[index]
            for index in (0, 1, 4)
            if index < len(result_tuple)
        )
    for raw_path in raw_paths:
        if not raw_path:
            continue
        path = Path(str(raw_path))
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            continue


def _extract_vector_timings(result: dict[str, Any]) -> dict[str, Any]:
    return dict(
        result.get("vector_timing")
        or result.get("_vector_timings")
        or {}
    )


def _parallelism_metadata(
    kind: Literal["raster", "vector"],
    *,
    hifi_timings: dict[str, Any],
    vector_timings: dict[str, Any],
) -> dict[str, object]:
    """Return requested and observed worker counts for one profile run."""

    env_var = (
        "LUMINA_RASTER_PARALLELISM"
        if kind == "raster"
        else "LUMINA_VECTOR_PARALLELISM"
    )
    raw_requested = os.getenv(env_var)
    requested = "auto" if raw_requested is None else raw_requested.strip()
    if requested == "":
        requested = "<empty>"
    raw_effective = (
        hifi_timings.get("mesh_parallelism_workers")
        if kind == "raster"
        else vector_timings.get("material_parallelism_workers")
    )
    effective_workers: int | None
    try:
        effective_workers = (
            None
            if raw_effective is None
            else max(1, int(float(raw_effective)))
        )
    except (TypeError, ValueError):
        effective_workers = None
    return {
        "env_var": env_var,
        "requested": requested,
        "effective_workers": effective_workers,
    }


def execute_case(
    case: ProfileCase,
    phase: Literal["preview", "generate"],
    *,
    enable_cprofile: bool = True,
    capture_semantics: bool = True,
    context_overrides: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Execute and profile one quality-locked conversion phase.

    执行并分析一次质量参数锁定的转换阶段。

    Args:
        case: Deterministic profile case. 确定性的性能分析案例。
        phase: Preview or generation phase. 预览或生成阶段。
        enable_cprofile: Enable deterministic call profiling. 是否启用调用分析。
        capture_semantics: Hash arrays and world-space geometry after timing.
            计时后是否对数组及世界坐标几何执行哈希。
        context_overrides: Prepared private override fixture paths.
            已准备好的私有覆盖输入路径。

    Returns:
        Timings, resource peaks, semantic snapshot, and cProfile text.
        计时、资源峰值、语义快照和 cProfile 文本。

    Raises:
        RuntimeError: If the pipeline reports an error. 流水线报错时抛出。
    """

    ctx = build_pipeline_context(case)
    if context_overrides:
        ctx.update(context_overrides)
    profile = cProfile.Profile()
    process = psutil.Process()
    cpu_before = process.cpu_times()
    started = time.perf_counter()
    with _ResourceSampler(process) as resources:
        if enable_cprofile:
            profile.enable()
        try:
            result = (
                run_preview_pipeline(ctx)
                if phase == "preview"
                else run_raster_pipeline(ctx)
            )
        finally:
            if enable_cprofile:
                profile.disable()
    elapsed = time.perf_counter() - started
    cpu_after = process.cpu_times()
    if result.get("error"):
        _cleanup_result_files(result)
        raise RuntimeError(str(result["error"]))
    cprofile_text = ""
    if enable_cprofile:
        stream = StringIO()
        (
            pstats.Stats(profile, stream=stream)
            .strip_dirs()
            .sort_stats("cumulative")
            .print_stats(80)
        )
        cprofile_text = stream.getvalue()
    cpu_s = (
        cpu_after.user
        + cpu_after.system
        - cpu_before.user
        - cpu_before.system
    )
    try:
        snapshot = semantic_snapshot(result) if capture_semantics else None
        hifi_timings = dict(result.get("_hifi_timings") or {})
        vector_timings = _extract_vector_timings(result)
        metrics = {
            "total_s": elapsed,
            "queue_wait_s": 0.0,
            "worker_execution_s": elapsed,
            "cpu_s": cpu_s,
            "average_cpu_percent": (cpu_s / elapsed * 100.0) if elapsed else 0.0,
            "rss_at_start_mb": resources.initial_rss_bytes / (1024 * 1024),
            "peak_rss_mb": resources.peak_rss_bytes / (1024 * 1024),
            "peak_rss_increase_mb": max(
                0,
                resources.peak_rss_bytes - resources.initial_rss_bytes,
            )
            / (1024 * 1024),
            "peak_thread_count": resources.peak_thread_count,
            "peak_child_process_count": resources.peak_child_process_count,
            "step_timings": dict(
                result.get("_preview_step_timings")
                or result.get("_step_timings")
                or {}
            ),
            "preview_timings": dict(result.get("_preview_timings") or {}),
            "hifi_timings": hifi_timings,
            "vector_timings": vector_timings,
            "parallelism": _parallelism_metadata(
                case.kind,
                hifi_timings=hifi_timings,
                vector_timings=vector_timings,
            ),
            "override_fixture": dict(
                result.get("profile_override_fixture") or {}
            ),
            "override_metrics": dict(
                result.get("matched_rgb_override_metrics") or {}
            ),
            "cprofile_enabled": enable_cprofile,
            "cprofile": cprofile_text,
        }
        if capture_semantics:
            metrics["semantic_snapshot"] = snapshot
        return metrics
    finally:
        _cleanup_result_files(result)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile one Lumina converter preview or generate task."
    )
    parser.add_argument("--kind", choices=("raster", "vector"), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--phase",
        choices=("preview", "generate"),
        required=True,
    )
    parser.add_argument("--target-width-mm", type=float, default=299.0)
    parser.add_argument(
        "--material-count",
        type=int,
        choices=(8, 12, 15),
        default=12,
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument(
        "--no-cprofile",
        action="store_true",
        help="Disable cProfile when an external sampler such as py-spy is used.",
    )
    parser.add_argument(
        "--timing-only",
        action="store_true",
        help=(
            "Skip post-run semantic hashing. Use only for supplemental timing "
            "after a separate quality-locked reference has passed."
        ),
    )
    parser.add_argument(
        "--reference-report",
        type=Path,
        help=(
            "Fail unless this run's semantic hash matches a prior profile.json "
            "reference. Incompatible with --timing-only."
        ),
    )
    parser.add_argument(
        "--override-scenario",
        choices=("none", "matched-rgb", "recipe", "combined"),
        default="none",
        help=(
            "Prepare an untimed vector preview cache and profile generate with "
            "a deterministic cached override."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".scratch/converter-multicore"),
    )
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be >= 1")
    if args.target_width_mm <= 0:
        parser.error("--target-width-mm must be > 0")
    if not args.input.is_file():
        parser.error(f"--input is not a file: {args.input}")
    expected_suffix = ".svg" if args.kind == "vector" else None
    if expected_suffix and args.input.suffix.lower() != expected_suffix:
        parser.error("--kind vector requires an SVG input")
    if args.reference_report is not None and not args.reference_report.is_file():
        parser.error("--reference-report must name an existing profile.json")
    if args.reference_report is not None and args.timing_only:
        parser.error("--reference-report cannot be used with --timing-only")
    if args.override_scenario != "none" and (
        args.kind != "vector" or args.phase != "generate"
    ):
        parser.error(
            "--override-scenario requires --kind vector --phase generate"
        )
    return args


def _render_markdown(report: dict[str, object]) -> str:
    summary = report["summary"]
    input_meta = report["input"]
    materials = report["materials"]
    quality = report["quality"]
    assert isinstance(summary, dict)
    assert isinstance(input_meta, dict)
    assert isinstance(materials, dict)
    assert isinstance(quality, dict)
    cold = summary["cold"]
    assert isinstance(cold, dict)
    if quality.get("external_reference_match") is True:
        quality_label = "exact match to external semantic reference"
    elif (
        quality.get("semantic_snapshots_available") is True
        and quality.get("semantic_snapshots_equal") is True
    ):
        quality_label = "exact semantic snapshots"
    elif quality.get("semantic_snapshot_count") == 1:
        quality_label = "semantic snapshot captured (not internally compared)"
    else:
        quality_label = "timing only (no semantic evidence)"
    return "\n".join(
        [
            "# Converter Multicore Profile",
            "",
            f"- Kind: `{input_meta['kind']}`",
            f"- Input: `{input_meta['name']}`",
            f"- Input SHA-256: `{input_meta['sha256']}`",
            f"- Phase: `{report['phase']}`",
            f"- Materials: `{materials['count']}`",
            f"- Target width: `{input_meta['target_width_mm']} mm`",
            f"- Override scenario: `{input_meta['override_scenario']}`",
            f"- Quality evidence: `{quality_label}`",
            f"- Cold total: `{float(cold['total_s']):.3f} s`",
            f"- Queue wait: `{float(cold.get('queue_wait_s', 0.0)):.3f} s`",
            (
                "- Worker execution: "
                f"`{float(cold.get('worker_execution_s', cold['total_s'])):.3f} s`"
            ),
            (
                "- RSS at timing start: "
                f"`{float(cold.get('rss_at_start_mb', 0.0)):.2f} MiB`"
            ),
            f"- Cold peak RSS: `{float(cold['peak_rss_mb']):.2f} MiB`",
            (
                "- Cold peak RSS increase: "
                f"`{float(cold.get('peak_rss_increase_mb', 0.0)):.2f} MiB`"
            ),
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    """Run the converter profiling command.

    运行转换器性能分析命令。

    Args:
        argv: Optional command-line arguments. 可选命令行参数。

    Returns:
        Process exit code. 进程退出码。
    """

    args = _parse_args(argv)
    case = ProfileCase(
        name=f"{args.kind}-{args.material_count}",
        kind=args.kind,
        input_path=args.input,
        target_width_mm=args.target_width_mm,
        material_count=args.material_count,
        override_scenario=args.override_scenario,
    )
    runs: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(
        prefix="lumina-vector-override-profile-",
    ) as temporary_root:
        context_overrides = None
        if case.override_scenario != "none":
            print(
                "[profile] preparing untimed vector override fixture",
                flush=True,
            )
            context_overrides = _prepare_vector_override_context(
                case,
                output_dir=Path(temporary_root),
            )
        for index in range(1, args.runs + 1):
            print(
                f"[profile] {case.name} {args.phase} run "
                f"{index}/{args.runs}",
                flush=True,
            )
            run = execute_case(
                case,
                args.phase,
                enable_cprofile=not args.no_cprofile,
                capture_semantics=not args.timing_only,
                context_overrides=context_overrides,
            )
            runs.append(run)
            print(
                f"[profile] total={float(run['total_s']):.3f}s "
                f"peak_rss={float(run['peak_rss_mb']):.2f}MiB",
                flush=True,
            )
    report = build_report(case, runs)
    report["phase"] = args.phase
    if args.reference_report is not None:
        reference_report = json.loads(
            args.reference_report.read_text(encoding="utf-8"),
        )
        if not isinstance(reference_report, dict):
            raise ValueError("Semantic reference report must be a JSON object")
        matched_hash = _assert_semantic_reference(reference_report, report)
        quality = report["quality"]
        assert isinstance(quality, dict)
        quality["external_reference_match"] = True
        quality["external_reference_sha256"] = matched_hash
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "profile.json"
    markdown_path = args.output_dir / "profile.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    print(f"[profile] json={json_path}", flush=True)
    print(f"[profile] markdown={markdown_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
