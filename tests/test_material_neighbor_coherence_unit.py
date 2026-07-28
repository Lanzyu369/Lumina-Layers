"""Exactness tests for bounded material-neighbor coherence helpers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from scipy.spatial.distance import cdist

import core.material_cache as material_cache_module
from core.material_cache import (
    _find_neighbor_pairs,
    _neighbor_coherence_refine,
    _top_k_candidate_rows_blockwise,
)
from core.material_color_solver import rgb_to_lab


def _legacy_neighbor_pairs(
    target_lab: np.ndarray,
    threshold: float,
) -> np.ndarray:
    distances = cdist(target_lab, target_lab, metric="euclidean")
    pairs = [
        (row_index, column_index)
        for row_index in range(target_lab.shape[0])
        for column_index in range(row_index + 1, target_lab.shape[0])
        if distances[row_index, column_index] < threshold
    ]
    return np.asarray(pairs, dtype=np.intp).reshape(-1, 2)


def _legacy_top_k(
    target_lab: np.ndarray,
    candidate_lab: np.ndarray,
    top_k: int,
) -> tuple[np.ndarray, np.ndarray]:
    full_distances = cdist(target_lab, candidate_lab, metric="euclidean")
    candidate_count = candidate_lab.shape[0]
    effective_top_k = min(int(top_k), candidate_count)
    if effective_top_k >= candidate_count:
        indices = np.broadcast_to(
            np.arange(candidate_count, dtype=np.intp)[None, :],
            (target_lab.shape[0], candidate_count),
        ).copy()
    else:
        indices = np.argpartition(
            full_distances,
            effective_top_k,
            axis=1,
        )[:, :effective_top_k]
    distances = np.take_along_axis(full_distances, indices, axis=1)
    return indices, distances


@pytest.mark.parametrize("seed", [0, 7, 2026])
def test_neighbor_pairs_match_legacy_full_distance_matrix(seed: int) -> None:
    rng = np.random.default_rng(seed)
    target_lab = rng.normal(
        loc=np.asarray([50.0, 0.0, 0.0]),
        scale=np.asarray([18.0, 35.0, 35.0]),
        size=(41, 3),
    )

    expected = _legacy_neighbor_pairs(target_lab, threshold=20.0)
    actual = _find_neighbor_pairs(target_lab, threshold=20.0)

    np.testing.assert_array_equal(actual, expected)


def test_neighbor_pairs_use_strict_threshold_and_lexicographic_order() -> None:
    target_lab = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [20.0, 0.0, 0.0],
            [19.999999, 0.0, 0.0],
            [0.0, 19.0, 0.0],
            [0.0, 0.0, 19.0],
        ],
        dtype=np.float64,
    )

    expected = _legacy_neighbor_pairs(target_lab, threshold=20.0)
    actual = _find_neighbor_pairs(target_lab, threshold=20.0)

    np.testing.assert_array_equal(actual, expected)
    assert (0, 1) not in [tuple(pair) for pair in actual]
    assert [tuple(pair) for pair in actual] == sorted(
        tuple(pair) for pair in actual
    )


def test_dense_neighbor_pairs_do_not_use_quadratic_query_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_tree = material_cache_module.cKDTree

    class _RowQueryTree:
        def __init__(self, data: np.ndarray) -> None:
            self._tree = real_tree(data)

        def query_ball_point(
            self,
            point: np.ndarray,
            radius: float,
        ) -> list[int]:
            return self._tree.query_ball_point(point, radius)

        def query_pairs(self, *_args: object, **_kwargs: object) -> None:
            pytest.fail("dense neighbor discovery must not materialize query_pairs")

    monkeypatch.setattr(material_cache_module, "cKDTree", _RowQueryTree)
    target_lab = np.zeros((128, 3), dtype=np.float64)

    pairs = _find_neighbor_pairs(target_lab, threshold=20.0)

    assert pairs.shape == (128 * 127 // 2, 2)
    np.testing.assert_array_equal(pairs[0], np.asarray([0, 1]))
    np.testing.assert_array_equal(pairs[-1], np.asarray([126, 127]))


@pytest.mark.parametrize(
    ("target_count", "candidate_count", "top_k", "block_size"),
    [
        (7, 13, 8, 1),
        (7, 13, 8, 3),
        (7, 13, 8, 4),
        (5, 5, 8, 2),
        (5, 3, 3, 4),
    ],
)
@pytest.mark.parametrize("parallelism", [1, 2, 4])
def test_blockwise_top_k_matches_legacy_full_matrix(
    target_count: int,
    candidate_count: int,
    top_k: int,
    block_size: int,
    parallelism: int,
) -> None:
    rng = np.random.default_rng(
        target_count * 10_000
        + candidate_count * 100
        + top_k * 10
        + block_size,
    )
    target_lab = rng.normal(size=(target_count, 3))
    candidate_lab = rng.normal(size=(candidate_count, 3))
    expected_indices, expected_distances = _legacy_top_k(
        target_lab,
        candidate_lab,
        top_k,
    )

    actual_indices, actual_distances = _top_k_candidate_rows_blockwise(
        target_lab=target_lab,
        candidate_lab=candidate_lab,
        top_k=top_k,
        block_size=block_size,
        parallelism=parallelism,
    )

    np.testing.assert_array_equal(actual_indices, expected_indices)
    np.testing.assert_array_equal(actual_distances, expected_distances)


@pytest.mark.parametrize("parallelism", [1, 2, 4])
def test_blockwise_top_k_preserves_duplicate_ties_across_k_boundary(
    parallelism: int,
) -> None:
    """Exact ties must retain NumPy's legacy argpartition row semantics."""

    target_lab = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [0.0, 2.0, 0.0],
        ],
        dtype=np.float64,
    )
    candidate_lab = np.asarray(
        [
            [1.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, -1.0, 0.0],
            [1.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
        ],
        dtype=np.float64,
    )
    expected_indices, expected_distances = _legacy_top_k(
        target_lab,
        candidate_lab,
        top_k=3,
    )

    actual_indices, actual_distances = _top_k_candidate_rows_blockwise(
        target_lab=target_lab,
        candidate_lab=candidate_lab,
        top_k=3,
        block_size=1,
        parallelism=parallelism,
    )

    np.testing.assert_array_equal(actual_indices, expected_indices)
    np.testing.assert_array_equal(actual_distances, expected_distances)


def test_blockwise_top_k_caps_workers_to_total_distance_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_workers: list[int] = []

    class _RecordingExecutor(ThreadPoolExecutor):
        def __init__(self, max_workers: int) -> None:
            observed_workers.append(max_workers)
            super().__init__(max_workers=max_workers)

    monkeypatch.setattr(
        material_cache_module,
        "ThreadPoolExecutor",
        _RecordingExecutor,
    )
    rng = np.random.default_rng(20260728)
    target_lab = rng.normal(size=(4, 3))
    candidate_lab = rng.normal(size=(32, 3))
    expected_indices, expected_distances = _legacy_top_k(
        target_lab,
        candidate_lab,
        top_k=8,
    )

    actual_indices, actual_distances = _top_k_candidate_rows_blockwise(
        target_lab=target_lab,
        candidate_lab=candidate_lab,
        top_k=8,
        parallelism=4,
        memory_budget_bytes=512,
    )

    # One distance row is 32 * float64 = 256 bytes, so a 512-byte total
    # budget permits at most two concurrent workers.
    assert observed_workers == [2]
    np.testing.assert_array_equal(actual_indices, expected_indices)
    np.testing.assert_array_equal(actual_distances, expected_distances)


def _coherence_fixture() -> dict[str, np.ndarray | float | int | None]:
    target_srgb = np.asarray(
        [
            [72, 92, 118],
            [78, 96, 122],
            [84, 100, 126],
            [90, 104, 130],
            [96, 108, 134],
            [102, 112, 138],
            [108, 116, 142],
        ],
        dtype=np.uint8,
    )
    all_srgb = np.asarray(
        [
            [70 + red_offset, 88 + green_offset, 112 + blue_offset]
            for red_offset in range(0, 49, 8)
            for green_offset, blue_offset in ((0, 0), (5, 9), (10, 3))
        ],
        dtype=np.uint8,
    )
    target_lab = rgb_to_lab(target_srgb).astype(np.float64)
    all_lab = rgb_to_lab(all_srgb).astype(np.float64)
    matched_rows = np.asarray([0, 5, 2, 11, 8, 17, 14], dtype=np.intp)
    matched_rgb = all_srgb[matched_rows]
    matched_lab = all_lab[matched_rows]
    delta_e = np.linalg.norm(matched_lab - target_lab, axis=1)
    layer_count = 4
    material_count = 4
    all_recipes = (
        np.arange(all_srgb.shape[0] * layer_count, dtype=np.int32)
        .reshape(all_srgb.shape[0], layer_count)
        % material_count
    )
    return {
        "target_lab": target_lab,
        "matched_rgb": matched_rgb,
        "recipes_user_order": all_recipes[matched_rows],
        "delta_e": delta_e,
        "all_lab": all_lab,
        "all_srgb": all_srgb,
        "all_recipes": all_recipes,
        "user_mapping": np.arange(material_count, dtype=np.int32),
        "coherence_weight": 0.8,
        "layer_count": layer_count,
        "uniform_lab": None,
        "uniform_srgb": None,
        "uniform_recipes": None,
    }


@pytest.mark.parametrize(
    ("block_size", "parallelism"),
    [(1, 1), (2, 2), (5, 4), (100, 4)],
)
def test_complete_coherence_output_is_stable_across_blocks_and_workers(
    block_size: int,
    parallelism: int,
) -> None:
    fixture = _coherence_fixture()
    expected = _neighbor_coherence_refine(
        **fixture,
        candidate_block_size=3,
        parallelism=1,
    )

    actual = _neighbor_coherence_refine(
        **fixture,
        candidate_block_size=block_size,
        parallelism=parallelism,
    )

    for actual_array, expected_array in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(actual_array, expected_array)
