"""Pure dynamic-material rebuild service for post-preview colour edits.
预览后颜色编辑所用的纯动态耗材重建服务。
"""

from dataclasses import dataclass
from typing import Callable

import numpy as np

from core.material_color_solver import MaterialParams
from core.material_dynamic_solver import DynamicMaterialCandidateError
from core.pipeline.material_dynamic_layers import (
    recompute_dynamic_material_benefit_curve,
    solve_dynamic_material_targets,
)


@dataclass(frozen=True)
class DynamicMaterialReplacementResult:
    """Complete cache payload produced by one dynamic replacement rebuild.
    单次动态替换重建生成的完整缓存负载。
    """

    matched_rgb: np.ndarray
    material_matrix: np.ndarray
    target_rgb_map: np.ndarray
    dynamic_layer_info: dict
    solver_info: dict


DynamicTargetSolver = Callable[
    ..., tuple[np.ndarray, np.ndarray, np.ndarray, dict, dict]
]


def rebuild_dynamic_material_after_replacement(
    *,
    updated_rgb: np.ndarray,
    diff_mask: np.ndarray,
    target_rgb_map: np.ndarray,
    solid_mask: np.ndarray,
    material_matrix: np.ndarray,
    materials: list[MaterialParams],
    backing_material_index: int,
    layer_height_mm: float,
    substrate: str,
    min_layer_count: int,
    max_layer_count: int,
    delta_e00_tolerance: float,
    region_masks: dict[str, np.ndarray] | None = None,
    recipe_overrides: list[dict] | None = None,
    existing_solver_info: dict | None = None,
    solver: DynamicTargetSolver = solve_dynamic_material_targets,
) -> DynamicMaterialReplacementResult:
    """Re-solve automatic targets while preserving manual region recipes.
    重新求解自动目标，同时保留手动区域配方。

    Args:
        updated_rgb: Post-edit matched RGB image. 编辑后的匹配 RGB 图。
        diff_mask: Pixels changed by the edit. 本次编辑改变的像素掩码。
        target_rgb_map: Pre-edit target-ownership RGB map. 编辑前目标色归属图。
        solid_mask: Printable-pixel mask. 可打印像素掩码。
        material_matrix: Existing fixed-width print recipe matrix. 现有定宽打印配方矩阵。
        materials: Material palette in user order. 用户顺序的耗材列表。
        backing_material_index: Backing index in user order. 用户顺序中的底板索引。
        layer_height_mm: Physical layer height. 物理层高。
        substrate: Optical substrate identifier. 光学基底标识。
        min_layer_count: Minimum effective layer count. 最小有效层数。
        max_layer_count: Maximum and printed layer count. 最大及打印层数。
        delta_e00_tolerance: Allowed exact-match sacrifice. 允许的精确色差牺牲。
        region_masks: Manual-region masks keyed by region id. 按区域 ID 保存的手动掩码。
        recipe_overrides: Stored manual recipe overrides. 已保存的手动配方覆盖。
        existing_solver_info: Solver metadata to preserve. 需要保留的求解元数据。
        solver: Public exact target solver seam for tests. 测试可注入的公开求解器接缝。

    Returns:
        DynamicMaterialReplacementResult: Rebuilt RGB, recipe matrix, target
            map, dynamic metadata, and solver metadata. 重建后的 RGB、配方矩阵、
            目标图、动态元数据和求解元数据。

    Raises:
        DynamicMaterialCandidateError: If inputs or solver output are
            inconsistent. 输入或求解结果不一致时抛出。
    """
    matched = np.asarray(updated_rgb, dtype=np.uint8).copy()
    changed = np.asarray(diff_mask, dtype=bool)
    targets = np.asarray(target_rgb_map, dtype=np.uint8)
    solid = np.asarray(solid_mask, dtype=bool)
    matrix = np.asarray(material_matrix)
    if matched.shape != targets.shape or matched.shape[:2] != changed.shape:
        raise DynamicMaterialCandidateError(
            "dynamic replacement RGB maps are inconsistent",
            layer_count=max_layer_count,
            phase="target_map",
        )
    if solid.shape != changed.shape or matrix.shape[:2] != changed.shape:
        raise DynamicMaterialCandidateError(
            "dynamic replacement masks or material matrix are inconsistent",
            layer_count=max_layer_count,
            phase="target_map",
        )
    if matrix.ndim != 3 or matrix.shape[2] != max_layer_count:
        raise DynamicMaterialCandidateError(
            "dynamic material matrix width does not match configured maximum",
            layer_count=max_layer_count,
            phase="result_validation",
        )

    updated_target_map = targets.copy()
    updated_target_map[changed] = matched[changed]
    target_rgbs, target_pixel_counts = np.unique(
        updated_target_map[solid], axis=0, return_counts=True
    )
    if target_rgbs.shape[0] == 0:
        raise DynamicMaterialCandidateError(
            "dynamic replacement target image contains no printable colours",
            layer_count=max_layer_count,
            phase="target_map",
        )

    _, _, _, new_info, new_solver_info = solver(
        unique_colors=np.asarray(target_rgbs, dtype=np.uint8),
        pixel_counts=np.asarray(target_pixel_counts, dtype=np.int64),
        materials=materials,
        backing_material_index=backing_material_index,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        min_layer_count=min_layer_count,
        max_layer_count=max_layer_count,
        delta_e00_tolerance=delta_e00_tolerance,
    )
    entries_by_target: dict[tuple[int, int, int], dict] = {}
    new_colors = new_info.get("colors") if isinstance(new_info, dict) else None
    for entry in new_colors if isinstance(new_colors, list) else []:
        if not isinstance(entry, dict):
            continue
        raw_target = entry.get("target_srgb")
        if not isinstance(raw_target, (list, tuple)) or len(raw_target) != 3:
            continue
        entries_by_target[tuple(int(value) for value in raw_target)] = entry

    manual_mask = np.zeros(solid.shape, dtype=bool)
    masks = region_masks if isinstance(region_masks, dict) else {}
    for override in recipe_overrides or []:
        if not isinstance(override, dict):
            raise DynamicMaterialCandidateError(
                "dynamic recipe override entry is invalid",
                layer_count=max_layer_count,
                phase="manual_mask",
            )
        region_id = str(override.get("region_id") or "")
        region_mask = masks.get(region_id)
        if not isinstance(region_mask, np.ndarray) or region_mask.shape != solid.shape:
            raise DynamicMaterialCandidateError(
                "dynamic recipe override mask is missing or inconsistent",
                layer_count=max_layer_count,
                phase="manual_mask",
            )
        normalized_region_mask = np.asarray(region_mask, dtype=bool)
        if not np.any(normalized_region_mask):
            raise DynamicMaterialCandidateError(
                "dynamic recipe override mask is empty",
                layer_count=max_layer_count,
                phase="manual_mask",
            )
        manual_mask |= normalized_region_mask
    automatic_mask = solid & ~manual_mask

    rebuilt_matrix = matrix.copy()
    for color in target_rgbs:
        key = tuple(int(value) for value in color)
        entry = entries_by_target.get(key)
        if entry is None:
            raise DynamicMaterialCandidateError(
                "no dynamic metadata entry is available for a replacement target",
                target_srgb=key,
                layer_count=max_layer_count,
                phase="exact_search",
            )
        matched_values = entry.get("matched_srgb")
        print_values = entry.get("print_recipe_top_to_bottom")
        if (
            not isinstance(matched_values, (list, tuple))
            or len(matched_values) != 3
            or not isinstance(print_values, (list, tuple))
            or len(print_values) != max_layer_count
        ):
            raise DynamicMaterialCandidateError(
                "dynamic replacement metadata is inconsistent",
                target_srgb=key,
                layer_count=max_layer_count,
                phase="result_validation",
            )
        color_mask = np.all(updated_target_map == color, axis=-1) & automatic_mask
        if not np.any(color_mask):
            continue
        matched[color_mask] = np.asarray(matched_values, dtype=np.uint8)
        rebuilt_matrix[color_mask] = np.asarray(print_values).astype(
            rebuilt_matrix.dtype, copy=False
        )

    dynamic_info = dict(new_info)
    dynamic_info["benefit_curve"] = recompute_dynamic_material_benefit_curve(
        new_colors if isinstance(new_colors, list) else [],
        updated_target_map,
        automatic_mask,
    )
    # A stale region mask may include transparent pixels. It should neither
    # switch the curve label nor claim that printable automatic coverage was
    # reduced unless it actually intersects the printable preview.
    has_manual_coverage = bool(np.any(manual_mask & solid))
    dynamic_info["benefit_curve_scope"] = (
        "automatic_pixels" if has_manual_coverage else "all_printable_pixels"
    )
    dynamic_info["benefit_curve_pixel_count"] = int(np.count_nonzero(automatic_mask))

    solver_info = dict(existing_solver_info or {})
    solver_info.update(new_solver_info)
    return DynamicMaterialReplacementResult(
        matched_rgb=matched,
        material_matrix=rebuilt_matrix,
        target_rgb_map=updated_target_map,
        dynamic_layer_info=dynamic_info,
        solver_info=solver_info,
    )
