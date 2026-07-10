"""Exact dynamic-layer material candidate search.

动态层数耗材候选的精确搜索。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from numba import njit, prange

from core.colorchecker.color_metrics import delta_e_2000
from core.material_color_solver import rgb_to_lab


MIN_DYNAMIC_LAYER_COUNT = 5
MAX_DYNAMIC_LAYER_COUNT = 10
_NUMPY_CANDIDATE_CHUNK_SIZE = 65_536


class DynamicMaterialSolverError(RuntimeError):
    """Raised when every exact dynamic search engine fails.

    当所有动态精确搜索引擎均失败时抛出。
    """


@dataclass(frozen=True)
class DynamicCandidateCatalog:
    """Lossless catalog of scored material candidates.

    已评分耗材候选的无损目录。
    """

    score_srgb: np.ndarray
    score_lab: np.ndarray
    print_recipes: np.ndarray
    minimum_actual_layer_counts: np.ndarray
    max_layer_reachable: np.ndarray
    source_indices: np.ndarray

    def __post_init__(self) -> None:
        arrays = (
            ("score_srgb", self.score_srgb, np.uint8),
            ("score_lab", self.score_lab, np.float64),
            ("print_recipes", self.print_recipes, np.int32),
            (
                "minimum_actual_layer_counts",
                self.minimum_actual_layer_counts,
                np.int16,
            ),
            ("max_layer_reachable", self.max_layer_reachable, np.bool_),
            ("source_indices", self.source_indices, np.int64),
        )
        for name, value, dtype in arrays:
            frozen = np.array(value, dtype=dtype, order="C", copy=True)
            frozen.setflags(write=False)
            object.__setattr__(self, name, frozen)

        row_count = self.score_srgb.shape[0]
        if self.score_srgb.ndim != 2 or self.score_srgb.shape[1] != 3:
            raise ValueError("score_srgb must have shape (U, 3)")
        if self.score_lab.shape != (row_count, 3):
            raise ValueError("score_lab must have shape (U, 3)")
        if self.print_recipes.ndim != 2 or self.print_recipes.shape[0] != row_count:
            raise ValueError("print_recipes must have shape (U, max_layer_count)")
        for name in (
            "minimum_actual_layer_counts",
            "max_layer_reachable",
            "source_indices",
        ):
            if getattr(self, name).shape != (row_count,):
                raise ValueError(f"{name} must have shape (U,)")

    @property
    def stable_source_indices(self) -> np.ndarray:
        """Return retained source rows in stable catalog order.

        返回按稳定目录顺序保留的源行索引。
        """
        return self.source_indices


@dataclass(frozen=True)
class ExactDynamicSearchResult:
    """Exact per-layer-cap search results.

    每个层数上限对应的精确搜索结果。
    """

    cumulative_best_candidate_indices: np.ndarray
    cumulative_best_delta_e00: np.ndarray
    fixed_max_delta_e00: np.ndarray
    engine: str

    def __post_init__(self) -> None:
        indices = np.array(
            self.cumulative_best_candidate_indices,
            dtype=np.int64,
            order="C",
            copy=True,
        )
        values = np.array(
            self.cumulative_best_delta_e00,
            dtype=np.float64,
            order="C",
            copy=True,
        )
        fixed = np.array(
            self.fixed_max_delta_e00,
            dtype=np.float64,
            order="C",
            copy=True,
        )
        if indices.ndim != 2:
            raise ValueError("cumulative_best_candidate_indices must be two-dimensional")
        if values.shape != indices.shape:
            raise ValueError("cumulative Delta-E00 values must match candidate indices")
        if fixed.shape != (indices.shape[0],):
            raise ValueError("fixed_max_delta_e00 must have shape (T,)")
        if self.engine not in {"numba", "numpy"}:
            raise ValueError("engine must be 'numba' or 'numpy'")
        for array in (indices, values, fixed):
            array.setflags(write=False)
        object.__setattr__(self, "cumulative_best_candidate_indices", indices)
        object.__setattr__(self, "cumulative_best_delta_e00", values)
        object.__setattr__(self, "fixed_max_delta_e00", fixed)

    @property
    def best_candidate_indices(self) -> np.ndarray:
        """Return exact cumulative candidate indices by layer cap.

        返回按层数上限排列的精确累计候选索引。
        """
        return self.cumulative_best_candidate_indices

    @property
    def best_delta_e00(self) -> np.ndarray:
        """Return exact cumulative Delta-E00 values by layer cap.

        返回按层数上限排列的精确累计 Delta-E00 值。
        """
        return self.cumulative_best_delta_e00

    @property
    def fixed_max_delta_e00_values(self) -> np.ndarray:
        """Return exact fixed-maximum baseline values.

        返回精确的固定最大层数基线值。
        """
        return self.fixed_max_delta_e00

    @property
    def engine_name(self) -> str:
        """Return the engine that produced the result.

        返回生成结果的引擎名称。
        """
        return self.engine


def _delta_e00_scalar_components(
    lightness1: float,
    a1: float,
    b1: float,
    lightness2: float,
    a2: float,
    b2: float,
) -> float:
    chroma1 = math.sqrt(a1 * a1 + b1 * b1)
    chroma2 = math.sqrt(a2 * a2 + b2 * b2)
    mean_chroma = (chroma1 + chroma2) / 2.0
    mean_chroma_seventh = mean_chroma**7
    compensation = 0.5 * (
        1.0
        - math.sqrt(
            mean_chroma_seventh / (mean_chroma_seventh + 25.0**7)
        )
    )

    adjusted_a1 = a1 * (1.0 + compensation)
    adjusted_a2 = a2 * (1.0 + compensation)
    adjusted_chroma1 = math.sqrt(adjusted_a1**2 + b1**2)
    adjusted_chroma2 = math.sqrt(adjusted_a2**2 + b2**2)
    hue1 = math.degrees(math.atan2(b1, adjusted_a1)) % 360.0
    hue2 = math.degrees(math.atan2(b2, adjusted_a2)) % 360.0

    delta_lightness = lightness2 - lightness1
    delta_chroma = adjusted_chroma2 - adjusted_chroma1
    if adjusted_chroma1 * adjusted_chroma2 == 0.0:
        delta_hue_degrees = 0.0
    elif abs(hue2 - hue1) <= 180.0:
        delta_hue_degrees = hue2 - hue1
    elif hue2 - hue1 > 180.0:
        delta_hue_degrees = hue2 - hue1 - 360.0
    else:
        delta_hue_degrees = hue2 - hue1 + 360.0
    delta_hue = (
        2.0
        * math.sqrt(adjusted_chroma1 * adjusted_chroma2)
        * math.sin(math.radians(delta_hue_degrees / 2.0))
    )

    mean_lightness = (lightness1 + lightness2) / 2.0
    mean_adjusted_chroma = (adjusted_chroma1 + adjusted_chroma2) / 2.0
    if adjusted_chroma1 * adjusted_chroma2 == 0.0:
        mean_hue = hue1 + hue2
    elif abs(hue1 - hue2) <= 180.0:
        mean_hue = (hue1 + hue2) / 2.0
    elif hue1 + hue2 < 360.0:
        mean_hue = (hue1 + hue2 + 360.0) / 2.0
    else:
        mean_hue = (hue1 + hue2 - 360.0) / 2.0

    hue_rotation = (
        1.0
        - 0.17 * math.cos(math.radians(mean_hue - 30.0))
        + 0.24 * math.cos(math.radians(2.0 * mean_hue))
        + 0.32 * math.cos(math.radians(3.0 * mean_hue + 6.0))
        - 0.20 * math.cos(math.radians(4.0 * mean_hue - 63.0))
    )
    lightness_scale = 1.0 + (
        0.015 * (mean_lightness - 50.0) ** 2
        / math.sqrt(20.0 + (mean_lightness - 50.0) ** 2)
    )
    chroma_scale = 1.0 + 0.045 * mean_adjusted_chroma
    hue_scale = 1.0 + 0.015 * mean_adjusted_chroma * hue_rotation

    mean_adjusted_chroma_seventh = mean_adjusted_chroma**7
    rotation_chroma = 2.0 * math.sqrt(
        mean_adjusted_chroma_seventh
        / (mean_adjusted_chroma_seventh + 25.0**7)
    )
    rotation_angle = 30.0 * math.exp(-((mean_hue - 275.0) / 25.0) ** 2)
    rotation_term = -math.sin(math.radians(2.0 * rotation_angle)) * rotation_chroma

    lightness_term = delta_lightness / lightness_scale
    chroma_term = delta_chroma / chroma_scale
    hue_term = delta_hue / hue_scale
    return math.sqrt(
        lightness_term**2
        + chroma_term**2
        + hue_term**2
        + rotation_term * chroma_term * hue_term
    )


_delta_e00_numba_components = njit(cache=True, fastmath=False)(
    _delta_e00_scalar_components
)


def _delta_e00_scalar(lab1: np.ndarray, lab2: np.ndarray) -> float:
    first = np.asarray(lab1, dtype=np.float64)
    second = np.asarray(lab2, dtype=np.float64)
    return _delta_e00_scalar_components(
        float(first[0]),
        float(first[1]),
        float(first[2]),
        float(second[0]),
        float(second[1]),
        float(second[2]),
    )


def _delta_e00_numpy(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    return np.asarray(delta_e_2000(lab1, lab2), dtype=np.float64)


@njit(cache=True, fastmath=False)
def _delta_e00_numba_scalar(lab1: np.ndarray, lab2: np.ndarray) -> float:
    return _delta_e00_numba_components(
        lab1[0],
        lab1[1],
        lab1[2],
        lab2[0],
        lab2[1],
        lab2[2],
    )


def _search_exact_numpy(
    target_lab: np.ndarray,
    candidate_lab: np.ndarray,
    minimum_actual_layer_counts: np.ndarray,
    max_layer_reachable: np.ndarray,
    min_layer_count: int,
    max_layer_count: int,
    candidate_chunk_size: int = _NUMPY_CANDIDATE_CHUNK_SIZE,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    target_count = target_lab.shape[0]
    candidate_count = candidate_lab.shape[0]
    cap_count = max_layer_count - min_layer_count + 1
    best_indices = np.full((target_count, cap_count), -1, dtype=np.int64)
    best_values = np.full((target_count, cap_count), np.inf, dtype=np.float64)
    fixed_max_values = np.full(target_count, np.inf, dtype=np.float64)

    if candidate_chunk_size <= 0:
        raise ValueError("candidate_chunk_size must be positive")

    layer_caps = np.arange(
        min_layer_count,
        max_layer_count + 1,
        dtype=np.int16,
    )
    for target_index in range(target_count):
        target = target_lab[target_index]
        for chunk_start in range(0, candidate_count, candidate_chunk_size):
            chunk_end = min(chunk_start + candidate_chunk_size, candidate_count)
            chunk_lab = candidate_lab[chunk_start:chunk_end]
            distances = _delta_e00_numpy(
                np.broadcast_to(target, chunk_lab.shape),
                chunk_lab,
            )
            chunk_counts = minimum_actual_layer_counts[chunk_start:chunk_end]

            for cap_index, layer_cap in enumerate(layer_caps):
                feasible = np.flatnonzero(chunk_counts <= layer_cap)
                if feasible.size == 0:
                    continue
                local_offset = int(np.argmin(distances[feasible]))
                local_index = int(feasible[local_offset])
                candidate_index = chunk_start + local_index
                candidate_value = float(distances[local_index])
                current_value = best_values[target_index, cap_index]
                current_index = best_indices[target_index, cap_index]
                if candidate_value < current_value or (
                    candidate_value == current_value
                    and (current_index < 0 or candidate_index < current_index)
                ):
                    best_values[target_index, cap_index] = candidate_value
                    best_indices[target_index, cap_index] = candidate_index

            fixed_feasible = np.flatnonzero(
                max_layer_reachable[chunk_start:chunk_end]
            )
            if fixed_feasible.size:
                local_offset = int(np.argmin(distances[fixed_feasible]))
                local_index = int(fixed_feasible[local_offset])
                candidate_value = float(distances[local_index])
                if candidate_value < fixed_max_values[target_index]:
                    fixed_max_values[target_index] = candidate_value

    return best_indices, best_values, fixed_max_values


@njit(parallel=True, fastmath=False, cache=True)
def _search_exact_numba_kernel(
    target_lab: np.ndarray,
    candidate_lab: np.ndarray,
    minimum_actual_layer_counts: np.ndarray,
    max_layer_reachable: np.ndarray,
    min_layer_count: int,
    max_layer_count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    target_count = target_lab.shape[0]
    candidate_count = candidate_lab.shape[0]
    cap_count = max_layer_count - min_layer_count + 1
    best_indices = np.full((target_count, cap_count), -1, dtype=np.int64)
    best_values = np.full((target_count, cap_count), np.inf, dtype=np.float64)
    fixed_max_values = np.full(target_count, np.inf, dtype=np.float64)

    for target_index in prange(target_count):
        target_lightness = target_lab[target_index, 0]
        target_a = target_lab[target_index, 1]
        target_b = target_lab[target_index, 2]
        for candidate_index in range(candidate_count):
            candidate_value = _delta_e00_numba_components(
                target_lightness,
                target_a,
                target_b,
                candidate_lab[candidate_index, 0],
                candidate_lab[candidate_index, 1],
                candidate_lab[candidate_index, 2],
            )
            first_cap = minimum_actual_layer_counts[candidate_index]
            if first_cap < min_layer_count:
                first_cap = min_layer_count
            first_cap_offset = first_cap - min_layer_count
            for cap_index in range(first_cap_offset, cap_count):
                current_value = best_values[target_index, cap_index]
                current_index = best_indices[target_index, cap_index]
                if candidate_value < current_value or (
                    candidate_value == current_value
                    and (current_index < 0 or candidate_index < current_index)
                ):
                    best_values[target_index, cap_index] = candidate_value
                    best_indices[target_index, cap_index] = candidate_index

            if (
                max_layer_reachable[candidate_index]
                and candidate_value < fixed_max_values[target_index]
            ):
                fixed_max_values[target_index] = candidate_value

    return best_indices, best_values, fixed_max_values


def _validate_layer_bound(value: Any, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if not MIN_DYNAMIC_LAYER_COUNT <= normalized <= MAX_DYNAMIC_LAYER_COUNT:
        raise ValueError(
            f"{name} must be between {MIN_DYNAMIC_LAYER_COUNT} and "
            f"{MAX_DYNAMIC_LAYER_COUNT}"
        )
    return normalized


def _coerce_integral_array(
    value: Any,
    *,
    name: str,
    dtype: np.dtype[Any] | type[np.generic],
    minimum: int,
    maximum: int,
) -> np.ndarray:
    array = np.asarray(value)
    if not (
        np.issubdtype(array.dtype, np.integer)
        or np.issubdtype(array.dtype, np.floating)
    ):
        raise TypeError(f"{name} must contain numeric integer-compatible values")
    numeric = array.astype(np.float64, copy=False)
    if not np.all(np.isfinite(numeric)):
        raise ValueError(f"{name} must contain finite values")
    if np.any(numeric != np.floor(numeric)):
        raise ValueError(f"{name} must contain integer-compatible values")
    if np.any(numeric < minimum) or np.any(numeric > maximum):
        raise ValueError(f"{name} values must be between {minimum} and {maximum}")
    return np.asarray(numeric, dtype=dtype)


def build_dynamic_candidate_catalog(
    score_srgb: np.ndarray,
    print_recipes_bottom_to_top: np.ndarray,
    actual_layer_counts: np.ndarray,
    max_layer_count: int,
) -> DynamicCandidateCatalog:
    """Build a losslessly deduplicated candidate catalog.

    构建无损去重的候选目录。
    """
    normalized_max = _validate_layer_bound(max_layer_count, "max_layer_count")

    rgb_input = np.asarray(score_srgb)
    if rgb_input.ndim != 2 or rgb_input.shape[1] != 3:
        raise ValueError("score_srgb must have shape (N, 3)")
    if rgb_input.shape[0] == 0:
        raise ValueError("score_srgb must contain at least one row")
    rgb = _coerce_integral_array(
        rgb_input,
        name="score_srgb",
        dtype=np.uint8,
        minimum=0,
        maximum=255,
    )

    recipe_input = np.asarray(print_recipes_bottom_to_top)
    expected_recipe_shape = (rgb.shape[0], normalized_max)
    if recipe_input.shape != expected_recipe_shape:
        raise ValueError(
            "print_recipes_bottom_to_top must have shape "
            f"{expected_recipe_shape}"
        )
    recipes = _coerce_integral_array(
        recipe_input,
        name="print_recipes_bottom_to_top",
        dtype=np.int32,
        minimum=0,
        maximum=np.iinfo(np.int32).max,
    )

    count_input = np.asarray(actual_layer_counts)
    if count_input.shape != (rgb.shape[0],):
        raise ValueError("actual_layer_counts must have shape (N,)")
    counts = _coerce_integral_array(
        count_input,
        name="actual_layer_counts",
        dtype=np.int16,
        minimum=MIN_DYNAMIC_LAYER_COUNT,
        maximum=normalized_max,
    )

    packed = (
        (rgb[:, 0].astype(np.uint32) << 16)
        | (rgb[:, 1].astype(np.uint32) << 8)
        | rgb[:, 2].astype(np.uint32)
    )
    catalog_positions: dict[int, int] = {}
    retained_sources: list[int] = []
    minimum_counts: list[int] = []
    max_reachable: list[bool] = []
    for source_index, packed_rgb in enumerate(packed):
        key = int(packed_rgb)
        catalog_index = catalog_positions.get(key)
        actual_count = int(counts[source_index])
        if catalog_index is None:
            catalog_positions[key] = len(retained_sources)
            retained_sources.append(source_index)
            minimum_counts.append(actual_count)
            max_reachable.append(actual_count == normalized_max)
            continue

        if actual_count == normalized_max:
            max_reachable[catalog_index] = True
        if actual_count < minimum_counts[catalog_index]:
            retained_sources[catalog_index] = source_index
            minimum_counts[catalog_index] = actual_count

    source_indices = np.asarray(retained_sources, dtype=np.int64)
    retained_rgb = np.asarray(rgb[source_indices], dtype=np.uint8)
    return DynamicCandidateCatalog(
        score_srgb=retained_rgb,
        score_lab=np.asarray(rgb_to_lab(retained_rgb), dtype=np.float64),
        print_recipes=np.asarray(recipes[source_indices], dtype=np.int32),
        minimum_actual_layer_counts=np.asarray(minimum_counts, dtype=np.int16),
        max_layer_reachable=np.asarray(max_reachable, dtype=np.bool_),
        source_indices=source_indices,
    )


def search_dynamic_catalog_exact(
    target_srgb: np.ndarray,
    catalog: DynamicCandidateCatalog,
    min_layer_count: int,
    max_layer_count: int,
    prefer_numba: bool = True,
) -> ExactDynamicSearchResult:
    """Search a candidate catalog with exhaustive CIEDE2000 scoring.

    使用穷举 CIEDE2000 评分搜索候选目录。
    """
    normalized_min = _validate_layer_bound(min_layer_count, "min_layer_count")
    normalized_max = _validate_layer_bound(max_layer_count, "max_layer_count")
    if normalized_min > normalized_max:
        raise ValueError("min_layer_count must not exceed max_layer_count")
    if not isinstance(catalog, DynamicCandidateCatalog):
        raise TypeError("catalog must be a DynamicCandidateCatalog")
    if catalog.score_srgb.shape[0] == 0:
        raise ValueError("catalog must contain at least one candidate")
    catalog_max_layer_count = catalog.print_recipes.shape[1]
    if normalized_max > catalog_max_layer_count:
        raise ValueError("max_layer_count exceeds the catalog recipe width")
    if np.any(catalog.minimum_actual_layer_counts < MIN_DYNAMIC_LAYER_COUNT) or np.any(
        catalog.minimum_actual_layer_counts > catalog_max_layer_count
    ):
        raise ValueError("catalog minimum layer counts are outside its recipe bounds")

    target_input = np.asarray(target_srgb)
    if target_input.ndim != 2 or target_input.shape[1] != 3:
        raise ValueError("target_srgb must have shape (T, 3)")
    targets = _coerce_integral_array(
        target_input,
        name="target_srgb",
        dtype=np.uint8,
        minimum=0,
        maximum=255,
    )
    if targets.shape[0] == 0:
        target_lab = np.empty((0, 3), dtype=np.float64)
    else:
        target_lab = np.asarray(rgb_to_lab(targets), dtype=np.float64)

    kernel_arguments = (
        target_lab,
        catalog.score_lab,
        catalog.minimum_actual_layer_counts,
        catalog.max_layer_reachable,
        normalized_min,
        normalized_max,
    )
    numba_error: Exception | None = None
    if prefer_numba:
        try:
            indices, values, fixed = _search_exact_numba_kernel(*kernel_arguments)
            return ExactDynamicSearchResult(
                cumulative_best_candidate_indices=indices,
                cumulative_best_delta_e00=values,
                fixed_max_delta_e00=fixed,
                engine="numba",
            )
        except Exception as exc:
            numba_error = exc

    try:
        indices, values, fixed = _search_exact_numpy(*kernel_arguments)
        return ExactDynamicSearchResult(
            cumulative_best_candidate_indices=indices,
            cumulative_best_delta_e00=values,
            fixed_max_delta_e00=fixed,
            engine="numpy",
        )
    except Exception as exc:
        if numba_error is not None:
            message = "exact dynamic search failed in both numba and numpy engines"
        else:
            message = "exact dynamic search failed in the numpy engine"
        raise DynamicMaterialSolverError(message) from exc
