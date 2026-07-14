"""Dynamic material solver adapter for the P03 pipeline boundary.

P03 管线边界的动态耗材求解适配器。
"""

from __future__ import annotations

import numpy as np


_RGB_COUNT_CHUNK_PIXELS = 32_768


def _pack_rgb24_rows(rgb_rows: np.ndarray) -> np.ndarray:
    """Pack ``(N, 3)`` uint8 RGB rows into collision-free uint32 keys."""
    packed = rgb_rows[:, 0].astype(np.uint32)
    np.left_shift(packed, np.uint32(16), out=packed)
    green = rgb_rows[:, 1].astype(np.uint32)
    np.left_shift(green, np.uint32(8), out=green)
    np.bitwise_or(packed, green, out=packed)
    np.bitwise_or(packed, rgb_rows[:, 2], out=packed)
    return packed


def _count_target_keys_in_chunks(
    rgb: np.ndarray,
    solid: np.ndarray,
    target_keys: np.ndarray,
) -> np.ndarray:
    """Count exact target RGB keys without allocating a full-image key array."""
    counts = np.zeros(target_keys.size, dtype=np.int64)
    if target_keys.size == 0 or rgb.size == 0:
        return counts

    search_keys = np.empty(target_keys.size + 1, dtype=np.uint32)
    search_keys[:-1] = target_keys
    search_keys[-1] = np.uint32(0xFFFFFFFF)
    height, width = rgb.shape[:2]
    rows_per_chunk = max(1, _RGB_COUNT_CHUNK_PIXELS // max(1, width))
    for row_start in range(0, height, rows_per_chunk):
        row_end = min(height, row_start + rows_per_chunk)
        row_count = row_end - row_start
        columns_per_chunk = max(1, _RGB_COUNT_CHUNK_PIXELS // row_count)
        for column_start in range(0, width, columns_per_chunk):
            column_end = min(width, column_start + columns_per_chunk)
            rgb_rows = rgb[
                row_start:row_end,
                column_start:column_end,
            ].reshape(-1, 3)
            solid_rows = solid[
                row_start:row_end,
                column_start:column_end,
            ].reshape(-1)
            if not np.any(solid_rows):
                continue
            visible_rows = (
                rgb_rows if np.all(solid_rows) else rgb_rows[solid_rows]
            )
            packed = _pack_rgb24_rows(visible_rows)
            positions = np.searchsorted(search_keys, packed)
            matches = search_keys[positions] == packed
            if not np.any(matches):
                continue
            counts += np.bincount(
                positions[matches],
                minlength=target_keys.size,
            )
    return counts


def recompute_dynamic_material_benefit_curve(
    color_entries: list[dict],
    target_rgb_map: np.ndarray,
    mask_solid: np.ndarray | None,
) -> list[dict]:
    """Reweight saved exact layer results for the final target ownership map.

    按最终目标色归属图重新加权已保存的逐层精确结果。
    """
    rgb = np.asarray(target_rgb_map, dtype=np.uint8)
    solid = (
        np.asarray(mask_solid, dtype=bool)
        if isinstance(mask_solid, np.ndarray)
        else np.ones(rgb.shape[:2], dtype=bool)
    )
    solid = np.broadcast_to(solid, rgb.shape[:2])
    parsed_entries: list[tuple[int, dict[int, float]]] = []
    for entry in color_entries:
        if not isinstance(entry, dict):
            continue
        target = entry.get("target_srgb")
        options = entry.get("layer_cap_options")
        if (
            not isinstance(target, (list, tuple))
            or len(target) != 3
            or not isinstance(options, list)
            or not options
        ):
            continue
        option_map: dict[int, float] = {}
        for option in options:
            if not isinstance(option, dict):
                continue
            try:
                layer_cap = int(option["max_effective_layer_count"])
                delta_e00 = float(option["delta_e00"])
            except (KeyError, TypeError, ValueError):
                continue
            option_map[layer_cap] = delta_e00
        if not option_map:
            continue
        target_row = np.asarray(target, dtype=np.uint8)
        target_key = (
            (int(target_row[0]) << 16)
            | (int(target_row[1]) << 8)
            | int(target_row[2])
        )
        parsed_entries.append((target_key, option_map))

    if not parsed_entries:
        return []

    entry_keys = np.fromiter(
        (target_key for target_key, _options in parsed_entries),
        dtype=np.uint32,
        count=len(parsed_entries),
    )
    target_keys = np.unique(entry_keys)
    target_counts = _count_target_keys_in_chunks(rgb, solid, target_keys)
    entry_positions = np.searchsorted(target_keys, entry_keys)
    entry_counts = target_counts[entry_positions]

    all_layer_caps: set[int] = set()
    for pixel_count_raw, (_target_key, option_map) in zip(
        entry_counts,
        parsed_entries,
    ):
        if int(pixel_count_raw) > 0:
            all_layer_caps.update(option_map)

    if not all_layer_caps:
        return []

    benefit_curve: list[dict] = []
    previous_mean: float | None = None
    for layer_cap in sorted(all_layer_caps):
        total_pixels = sum(
            int(pixel_count_raw)
            for pixel_count_raw, (_target_key, options) in zip(
                entry_counts,
                parsed_entries,
            )
            if int(pixel_count_raw) > 0 and layer_cap in options
        )
        weighted_mean = sum(
            int(pixel_count_raw) * options[layer_cap]
            for pixel_count_raw, (_target_key, options) in zip(
                entry_counts,
                parsed_entries,
            )
            if int(pixel_count_raw) > 0 and layer_cap in options
        ) / total_pixels
        marginal = (
            0.0
            if previous_mean is None
            else max(0.0, previous_mean - weighted_mean)
        )
        benefit_curve.append(
            {
                "max_effective_layer_count": int(layer_cap),
                "weighted_mean_delta_e00": round(float(weighted_mean), 12),
                "marginal_delta_e00_reduction": round(float(marginal), 12),
            }
        )
        previous_mean = weighted_mean
    return benefit_curve


def _dynamic_option_metadata(option) -> dict:
    """Serialize one solver option in the pipeline Top-to-Bottom convention.
    按管线自顶向下层序序列化单个动态求解选项。
    """
    return {
        "max_effective_layer_count": int(option.max_effective_layer_count),
        "actual_layer_count": int(option.actual_layer_count),
        "matched_srgb": [int(value) for value in option.matched_srgb],
        "actual_recipe_top_to_bottom": [
            int(value) for value in reversed(option.actual_recipe_bottom_to_top)
        ],
        "print_recipe_top_to_bottom": [
            int(value) for value in reversed(option.print_recipe_bottom_to_top)
        ],
        "delta_e00": float(option.delta_e00),
    }


def _solve_dynamic_material_targets(
    *,
    unique_colors: np.ndarray,
    pixel_counts: np.ndarray,
    materials: list,
    backing_material_index: int,
    layer_height_mm: float,
    substrate: str,
    min_layer_count: int,
    max_layer_count: int,
    delta_e00_tolerance: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict, dict]:
    """Solve dynamic material targets and build serializable pipeline metadata.
    求解动态耗材目标，并构建可序列化的管线元数据。

    The exact solver owns Bottom-to-Top domain recipes. This boundary reverses
    each selected recipe once so every downstream consumer receives the
    pipeline's Top-to-Bottom convention.

    精确求解器持有自底向上的领域配方；本边界仅反转一次，使所有下游消费者
    获得管线统一的自顶向下层序。
    """
    from core import material_dynamic_solver as dynamic_solver

    config = dynamic_solver.DynamicMaterialSolveConfig(
        min_layer_count=min_layer_count,
        max_layer_count=max_layer_count,
        delta_e00_tolerance=delta_e00_tolerance,
    )
    if isinstance(backing_material_index, (bool, np.bool_)) or not isinstance(
        backing_material_index,
        (int, np.integer),
    ):
        raise dynamic_solver.DynamicMaterialCandidateError(
            "backing material index must be an integer",
            layer_count=config.max_layer_count,
            phase="backing_material",
        )
    backing_index = int(backing_material_index)
    if not 0 <= backing_index < len(materials):
        raise dynamic_solver.DynamicMaterialCandidateError(
            "backing material index is outside the material palette",
            layer_count=config.max_layer_count,
            phase="backing_material",
        )

    if unique_colors.shape[0] == 0:
        dynamic_info = {
            "enabled": True,
            "min_layer_count": config.min_layer_count,
            "max_layer_count": config.max_layer_count,
            "delta_e00_tolerance": config.delta_e00_tolerance,
            "engine": "none",
            "candidate_count_before_dedup": 0,
            "candidate_count_after_dedup": 0,
            "colors": [],
            "benefit_curve": [],
        }
        solver_meta = {
            "dynamic_engine": "none",
            "dynamic_min_layer_count": config.min_layer_count,
            "dynamic_max_layer_count": config.max_layer_count,
            "dynamic_delta_e00_tolerance": config.delta_e00_tolerance,
            "dynamic_candidate_count_before_dedup": 0,
            "dynamic_candidate_count_after_dedup": 0,
        }
        return (
            np.zeros((0, 3), dtype=np.uint8),
            np.zeros((0, config.max_layer_count), dtype=np.int32),
            np.zeros((0,), dtype=np.float64),
            dynamic_info,
            solver_meta,
        )

    solve_result = dynamic_solver.solve_dynamic_material_colors(
        target_srgb=unique_colors,
        materials=materials,
        backing_material_index=backing_index,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        config=config,
    )
    if len(solve_result.matches) != int(unique_colors.shape[0]):
        raise dynamic_solver.DynamicMaterialCandidateError(
            "solver result count does not match target count",
            layer_count=config.max_layer_count,
            phase="result_validation",
        )

    matched_rows: list[list[int]] = []
    print_rows_top_to_bottom: list[list[int]] = []
    selected_delta_e00: list[float] = []
    color_entries: list[dict] = []
    for target_row, match in zip(unique_colors, solve_result.matches):
        target = tuple(int(value) for value in target_row)
        if tuple(match.target_srgb) != target:
            raise dynamic_solver.DynamicMaterialCandidateError(
                "solver target order does not match sorted unique colors",
                layer_count=config.max_layer_count,
                phase="result_validation",
            )
        selected = match.selected
        actual_count = int(selected.actual_layer_count)
        padding_count = config.max_layer_count - actual_count
        actual_bottom_to_top = tuple(
            int(value) for value in selected.actual_recipe_bottom_to_top
        )
        print_bottom_to_top = tuple(
            int(value) for value in selected.print_recipe_bottom_to_top
        )
        if (
            len(actual_bottom_to_top) != actual_count
            or len(print_bottom_to_top) != config.max_layer_count
            or print_bottom_to_top[padding_count:] != actual_bottom_to_top
            or any(
                value != backing_index
                for value in print_bottom_to_top[:padding_count]
            )
        ):
            raise dynamic_solver.DynamicMaterialCandidateError(
                "solver returned an invalid padded print recipe",
                layer_count=config.max_layer_count,
                phase="result_validation",
            )
        selected_meta = _dynamic_option_metadata(selected)
        cap_options = [
            _dynamic_option_metadata(option)
            for option in match.layer_cap_options
        ]
        matched_rows.append(selected_meta["matched_srgb"])
        print_rows_top_to_bottom.append(selected_meta["print_recipe_top_to_bottom"])
        selected_delta_e00.append(float(selected.delta_e00))
        color_entries.append(
            {
                "target_srgb": list(target),
                "matched_srgb": selected_meta["matched_srgb"],
                "actual_layer_count": actual_count,
                "padding_layer_count": padding_count,
                "actual_recipe_top_to_bottom": selected_meta[
                    "actual_recipe_top_to_bottom"
                ],
                "print_recipe_top_to_bottom": selected_meta[
                    "print_recipe_top_to_bottom"
                ],
                "selected_delta_e00": float(selected.delta_e00),
                "best_range_delta_e00": float(match.best_range.delta_e00),
                "fixed_max_delta_e00": float(match.fixed_max_delta_e00),
                "delta_e00_sacrifice": float(match.delta_e00_sacrifice),
                "layer_cap_options": cap_options,
            }
        )

    benefit_points = dynamic_solver.build_material_layer_benefit_curve(
        solve_result.matches,
        [int(value) for value in pixel_counts],
    )
    benefit_curve = [
        {
            "max_effective_layer_count": int(point.max_effective_layer_count),
            "weighted_mean_delta_e00": float(point.weighted_mean_delta_e00),
            "marginal_delta_e00_reduction": float(
                point.marginal_delta_e00_reduction
            ),
        }
        for point in benefit_points
    ]
    dynamic_info = {
        "enabled": True,
        "min_layer_count": config.min_layer_count,
        "max_layer_count": config.max_layer_count,
        "delta_e00_tolerance": config.delta_e00_tolerance,
        "engine": str(solve_result.engine),
        "candidate_count_before_dedup": int(
            solve_result.candidate_count_before_dedup
        ),
        "candidate_count_after_dedup": int(
            solve_result.candidate_count_after_dedup
        ),
        "colors": color_entries,
        "benefit_curve": benefit_curve,
    }
    solver_meta = {
        "dynamic_engine": str(solve_result.engine),
        "dynamic_min_layer_count": config.min_layer_count,
        "dynamic_max_layer_count": config.max_layer_count,
        "dynamic_delta_e00_tolerance": config.delta_e00_tolerance,
        "dynamic_candidate_count_before_dedup": int(
            solve_result.candidate_count_before_dedup
        ),
        "dynamic_candidate_count_after_dedup": int(
            solve_result.candidate_count_after_dedup
        ),
    }
    return (
        np.asarray(matched_rows, dtype=np.uint8),
        np.asarray(print_rows_top_to_bottom, dtype=np.int32),
        np.asarray(selected_delta_e00, dtype=np.float64),
        dynamic_info,
        solver_meta,
    )


def _record_dynamic_material_error(ctx: dict, exc: Exception) -> dict:
    """Record a typed dynamic failure without publishing partial solve output.
    记录带类型的动态失败，且不发布部分求解输出。
    """
    phase = str(getattr(exc, "phase", "dynamic_solve"))
    layer_count = getattr(exc, "layer_count", None)
    ctx["material_dynamic_layer_error"] = {
        "exception": exc,
        "error_type": type(exc).__name__,
        "message": str(exc),
        "layer_count": int(layer_count) if layer_count is not None else None,
        "phase": phase,
    }
    ctx["error"] = (
        "[P03] 动态耗材层数求解失败。"
        " / Dynamic material layer solve failed."
    )
    return ctx
