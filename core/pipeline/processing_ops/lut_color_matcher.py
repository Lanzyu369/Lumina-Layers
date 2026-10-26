"""
LUT 颜色匹配模块（LUT Color Matcher）

支持传统 DB 匹配、预测式运行时匹配，以及原生 reference source 的
DB-first + model fallback 语义。
"""

from __future__ import annotations

import time

import cv2
import numpy as np
from scipy.spatial import KDTree

from api.structured_logging import get_logger
from core.native_reference import SOURCE_KIND_PACKAGE, SOURCE_KIND_STAGE_MODEL
from core.predictive_lut import _rgb_to_runtime_opencv_lab, match_unique_colors_with_runtime

_log = get_logger(__name__)
_TIE_DISTANCE_ATOL = 1e-12
_NEUTRAL_INPUT_CHROMA_MAX = 4.0
_NEUTRAL_CANDIDATE_CHROMA_MAX = 8.0
_NEUTRAL_QUERY_K = 128
_NEUTRAL_LIGHTNESS_SLACK = 72.0
_NEUTRAL_DISTANCE_RATIO = 3.0
_NEUTRAL_DISTANCE_SLACK = 16.0
_NEUTRAL_CHROMA_SCORE_WEIGHT = 4.0


def _rgb_to_lab(rgb_array: np.ndarray) -> np.ndarray:
    """将 RGB 数组转换为 CIELAB 空间。"""
    original_shape = rgb_array.shape
    if rgb_array.ndim == 2:
        rgb_3d = rgb_array.reshape(1, -1, 3).astype(np.uint8)
    else:
        rgb_3d = rgb_array.astype(np.uint8)
    bgr = cv2.cvtColor(rgb_3d, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64)
    if len(original_shape) == 2:
        return lab.reshape(original_shape)
    return lab


def _lab_to_lch(lab_array: np.ndarray) -> np.ndarray:
    """Convert OpenCV LAB values to LCH for achromatic candidate checks."""
    lab = np.asarray(lab_array, dtype=np.float64)
    lightness = lab[..., 0]
    a = lab[..., 1] - 128.0
    b = lab[..., 2] - 128.0
    chroma = np.sqrt((a * a) + (b * b))
    hue = np.degrees(np.arctan2(b, a)) % 360.0
    return np.stack([lightness, chroma, hue], axis=-1)


def _break_nearest_ties_by_rgb_distance(
    unique_colors: np.ndarray,
    unique_lab: np.ndarray,
    lut_lab: np.ndarray,
    lut_rgb: np.ndarray | None,
    kdtree: KDTree,
    distances: np.ndarray,
    indices: np.ndarray,
) -> np.ndarray:
    if len(lut_lab) <= 1 or len(unique_lab) == 0:
        return indices

    neighbour_distances, _neighbour_indices = kdtree.query(unique_lab, k=2)
    tie_rows = np.flatnonzero(
        np.isfinite(neighbour_distances[:, 1])
        & np.isclose(
            neighbour_distances[:, 1],
            distances,
            rtol=0.0,
            atol=_TIE_DISTANCE_ATOL,
        )
    )
    if tie_rows.size == 0:
        return indices

    resolved = np.asarray(indices, dtype=np.int32).copy()
    has_rgb = lut_rgb is not None and lut_rgb.size > 0 and lut_rgb.reshape(-1, 3).shape[0] == len(lut_lab)
    flat_lut_rgb = lut_rgb.reshape(-1, 3) if has_rgb else None

    for row in tie_rows:
        candidates = np.asarray(
            kdtree.query_ball_point(unique_lab[row], float(distances[row] + _TIE_DISTANCE_ATOL)),
            dtype=np.int32,
        )
        if candidates.size <= 1:
            continue

        candidate_distances = np.linalg.norm(lut_lab[candidates] - unique_lab[row], axis=1)
        tied = candidates[
            np.isclose(
                candidate_distances,
                distances[row],
                rtol=0.0,
                atol=_TIE_DISTANCE_ATOL,
            )
        ]
        if tied.size <= 1:
            continue

        if flat_lut_rgb is not None:
            rgb_delta = flat_lut_rgb[tied].astype(np.int32) - unique_colors[row].astype(np.int32)
            rgb_distances = np.sum(rgb_delta * rgb_delta, axis=1)
            tied = tied[rgb_distances == np.min(rgb_distances)]

        resolved[row] = int(np.min(tied))

    return resolved


def _prefer_achromatic_matches_for_neutral_inputs(
    unique_lab: np.ndarray,
    lut_lab: np.ndarray,
    kdtree: KDTree,
    distances: np.ndarray,
    indices: np.ndarray,
) -> np.ndarray:
    """Prefer nearby achromatic LUT entries for grayscale source colours."""
    if len(lut_lab) <= 1 or len(unique_lab) == 0:
        return indices

    input_lch = _lab_to_lch(unique_lab)
    neutral_rows = np.flatnonzero(input_lch[:, 1] <= _NEUTRAL_INPUT_CHROMA_MAX)
    if neutral_rows.size == 0:
        return indices

    k = min(_NEUTRAL_QUERY_K, len(lut_lab))
    neighbour_distances, neighbour_indices = kdtree.query(unique_lab[neutral_rows], k=k)
    if k == 1:
        neighbour_distances = neighbour_distances.reshape(-1, 1)
        neighbour_indices = neighbour_indices.reshape(-1, 1)

    candidate_lch = _lab_to_lch(lut_lab[neighbour_indices])
    input_lightness = input_lch[neutral_rows, 0][:, np.newaxis]
    lightness_delta = np.abs(candidate_lch[:, :, 0] - input_lightness)

    current_distance = np.asarray(distances, dtype=np.float64)[neutral_rows]
    allowed_lightness_delta = np.maximum(
        _NEUTRAL_LIGHTNESS_SLACK,
        current_distance[:, np.newaxis] * _NEUTRAL_DISTANCE_RATIO,
    )
    allowed_distance = (
        current_distance[:, np.newaxis] * _NEUTRAL_DISTANCE_RATIO
        + _NEUTRAL_DISTANCE_SLACK
    )

    acceptable = (
        (candidate_lch[:, :, 1] <= _NEUTRAL_CANDIDATE_CHROMA_MAX)
        & (lightness_delta <= allowed_lightness_delta)
        & (neighbour_distances <= allowed_distance)
    )
    if not np.any(acceptable):
        return indices

    resolved = np.asarray(indices, dtype=np.int32).copy()
    neutral_scores = neighbour_distances + (
        candidate_lch[:, :, 1] * _NEUTRAL_CHROMA_SCORE_WEIGHT
    )
    masked_scores = np.where(acceptable, neutral_scores, np.inf)
    best_local = np.argmin(masked_scores, axis=1)
    has_candidate = np.isfinite(masked_scores[np.arange(len(neutral_rows)), best_local])
    if np.any(has_candidate):
        selected_rows = neutral_rows[has_candidate]
        selected_local = best_local[has_candidate]
        resolved[selected_rows] = neighbour_indices[has_candidate, selected_local].astype(np.int32)

    return resolved


def _match_colors_to_db(
    unique_colors: np.ndarray,
    lut_lab: np.ndarray,
    kdtree: KDTree | None,
    hue_matcher=None,
    *,
    lut_rgb: np.ndarray | None = None,
    predictive_runtime=None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return DB LUT indices and their Lab-space distances."""
    if unique_colors.size == 0:
        return np.zeros((0,), dtype=np.int32), np.zeros((0,), dtype=np.float32)

    if predictive_runtime is not None:
        if lut_rgb is None or lut_rgb.size == 0:
            raise ValueError("lut_rgb is required for native DB matching in runtime Lab space")
        unique_lab = _rgb_to_runtime_opencv_lab(unique_colors, predictive_runtime.pred_lab)
        db_lab = _rgb_to_runtime_opencv_lab(lut_rgb, predictive_runtime.pred_lab).astype(np.float32, copy=False)
        db_tree = KDTree(db_lab)
        distances, indices = db_tree.query(unique_lab)
        indices = _break_nearest_ties_by_rgb_distance(unique_colors, unique_lab, db_lab, lut_rgb, db_tree, distances, indices)
        return np.asarray(indices, dtype=np.int32), np.asarray(distances, dtype=np.float32)

    unique_lab = _rgb_to_lab(unique_colors)
    if hue_matcher is not None:
        _log.debug("Hue-aware matching enabled")
        indices = np.asarray(hue_matcher.match_colors_batch(unique_colors, k=32), dtype=np.int32)
        selected_lab = lut_lab[indices].astype(np.float64, copy=False)
        distances = np.linalg.norm(unique_lab - selected_lab, axis=1).astype(np.float32, copy=False)
        return indices, distances

    if kdtree is None:
        raise ValueError("KDTree is required for DB LUT matching")

    distances, indices = kdtree.query(unique_lab)
    indices = _break_nearest_ties_by_rgb_distance(unique_colors, unique_lab, lut_lab, lut_rgb, kdtree, distances, indices)
    indices = _prefer_achromatic_matches_for_neutral_inputs(unique_lab, lut_lab, kdtree, distances, indices)
    return np.asarray(indices, dtype=np.int32), np.asarray(distances, dtype=np.float32)


def _native_model_assisted_match(
    unique_colors: np.ndarray,
    lut_rgb: np.ndarray,
    lut_lab: np.ndarray,
    ref_stacks: np.ndarray | None,
    kdtree: KDTree | None,
    predictive_runtime,
    *,
    hue_matcher=None,
    model_enable: bool = False,
    model_only: bool = False,
) -> np.ndarray | dict[str, object]:
    """Apply DB-first + model fallback semantics for native predictive sources."""
    if predictive_runtime is None:
        return _match_colors_to_db(unique_colors, lut_lab, kdtree, hue_matcher, lut_rgb=lut_rgb)[0]

    model_result = match_unique_colors_with_runtime(unique_colors, predictive_runtime)

    if model_only:
        return model_result

    has_db_baseline = (
        lut_rgb is not None
        and lut_rgb.size > 0
        and ref_stacks is not None
        and isinstance(ref_stacks, np.ndarray)
        and ref_stacks.ndim == 2
        and ref_stacks.shape[0] == lut_rgb.reshape(-1, 3).shape[0]
    )
    if not has_db_baseline:
        runtime_only = dict(model_result)
        runtime_only["db_baseline_available"] = False
        return runtime_only

    db_indices, db_distances = _match_colors_to_db(
        unique_colors,
        lut_lab,
        kdtree,
        hue_matcher,
        lut_rgb=lut_rgb,
        predictive_runtime=predictive_runtime,
    )
    if not model_enable:
        return db_indices

    model_distances = np.asarray(model_result["distances"], dtype=np.float32)
    threshold = float(model_result["threshold"])
    margin = float(model_result["margin"])
    use_model = (db_distances > threshold) & ((model_distances + margin) < db_distances)
    if not np.any(use_model):
        return db_indices

    matched_rgb = lut_rgb[db_indices].astype(np.uint8, copy=True)
    recipes = ref_stacks[db_indices].astype(np.int32, copy=True)
    matched_rgb[use_model] = np.asarray(model_result["matched_rgb"], dtype=np.uint8)[use_model]
    recipes[use_model] = np.asarray(model_result["recipes"], dtype=np.int32)[use_model]

    return {
        "match_mode": "predictive",
        "runtime_mode_key": model_result.get("runtime_mode_key"),
        "matched_rgb": matched_rgb,
        "recipes": recipes,
        "distances": np.where(use_model, model_distances, db_distances).astype(np.float32, copy=False),
        "db_distances": db_distances,
        "model_distances": model_distances,
        "db_overrides": use_model.tolist(),
        "db_baseline_available": True,
        "threshold": threshold,
        "margin": margin,
        "within_threshold": np.where(use_model, model_distances <= threshold, db_distances <= threshold),
    }


def match_colors_to_lut(
    unique_colors: np.ndarray,
    lut_rgb: np.ndarray,
    lut_lab: np.ndarray,
    kdtree: KDTree | None,
    hue_matcher=None,
    predictive_runtime=None,
    *,
    source_kind: str = "legacy_lookup",
    native_reference_source: bool = False,
    model_enable: bool = False,
    model_only: bool = False,
    ref_stacks: np.ndarray | None = None,
) -> np.ndarray | dict[str, object]:
    """Match unique colors using legacy DB lookup or native model-assisted fallback."""
    t0 = time.time()
    native_predictive_source = native_reference_source and source_kind in (SOURCE_KIND_PACKAGE, SOURCE_KIND_STAGE_MODEL)

    if native_predictive_source:
        result = _native_model_assisted_match(
            unique_colors,
            lut_rgb,
            lut_lab,
            ref_stacks,
            kdtree,
            predictive_runtime,
            hue_matcher=hue_matcher,
            model_enable=model_enable,
            model_only=model_only,
        )
    elif predictive_runtime is not None:
        result = match_unique_colors_with_runtime(unique_colors, predictive_runtime)
    else:
        result = _match_colors_to_db(unique_colors, lut_lab, kdtree, hue_matcher, lut_rgb=lut_rgb)[0]

    if isinstance(result, dict):
        _log.debug(
            "Predictive LUT matching: %.2fs, mode=%s",
            time.time() - t0,
            result.get("runtime_mode_key", "unknown"),
        )
    else:
        _log.debug("LUT matching: %.2fs", time.time() - t0)
    return result


def map_pixels_to_lut(
    quantized_image: np.ndarray,
    unique_colors: np.ndarray,
    unique_match: np.ndarray | dict[str, object],
    lut_rgb: np.ndarray,
    ref_stacks: np.ndarray,
    target_h: int,
    target_w: int,
    layer_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Map all pixels to LUT or predictive/runtime-derived recipes."""
    t0 = time.time()
    _log.debug("Building color lookup table...")

    is_predictive = isinstance(unique_match, dict) and unique_match.get("match_mode") == "predictive"

    unique_codes = (
        unique_colors[:, 0].astype(np.int32) * 65536
        + unique_colors[:, 1].astype(np.int32) * 256
        + unique_colors[:, 2].astype(np.int32)
    )

    sort_idx = np.argsort(unique_codes)
    sorted_codes = unique_codes[sort_idx]
    if is_predictive:
        matched_rgb_unique = np.asarray(unique_match["matched_rgb"], dtype=np.uint8)[sort_idx]
        recipe_unique = np.asarray(unique_match["recipes"], dtype=np.int32)[sort_idx]
        layer_count = int(recipe_unique.shape[1]) if recipe_unique.ndim == 2 else int(layer_count)
    else:
        sorted_lut_indices = np.asarray(unique_match, dtype=np.int32)[sort_idx]

    flat_quantized = quantized_image.reshape(-1, 3)
    pixel_codes = (
        flat_quantized[:, 0].astype(np.int32) * 65536
        + flat_quantized[:, 1].astype(np.int32) * 256
        + flat_quantized[:, 2].astype(np.int32)
    )

    insert_positions = np.searchsorted(sorted_codes, pixel_codes)
    if is_predictive:
        matched_rgb = matched_rgb_unique[insert_positions].reshape(target_h, target_w, 3)
        material_matrix = recipe_unique[insert_positions].reshape(target_h, target_w, layer_count)
    else:
        lut_indices_for_pixels = sorted_lut_indices[insert_positions]
        matched_rgb = lut_rgb[lut_indices_for_pixels].reshape(target_h, target_w, 3)
        material_matrix = ref_stacks[lut_indices_for_pixels].reshape(target_h, target_w, layer_count)

    _log.debug("Color mapping: %.2fs", time.time() - t0)
    return matched_rgb, material_matrix
