"""Unit tests for the exact dynamic material candidate engine."""

from __future__ import annotations

import importlib
import importlib.util
import inspect

import numpy as np
import pytest

import core.material_dynamic_solver as dynamic_solver
from core.material_dynamic_solver import (
    DynamicCandidateCatalog,
    _delta_e00_numba_scalar,
    _delta_e00_numpy,
    _delta_e00_scalar,
    build_dynamic_candidate_catalog,
    search_dynamic_catalog_exact,
)
from core.material_color_solver import rgb_to_lab


SHARMA_CIEDE2000_PAIRS = (
    ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
    ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
    ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -1.1848, -84.8006), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -0.9009, -85.5211), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    ((50.0000, -1.0000, 2.0000), (50.0000, 0.0000, 0.0000), 2.3669),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0009), 7.1792),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0010), 7.1792),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0011), 7.2195),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0012), 7.2195),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0009, -2.4900), 4.8045),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0010, -2.4900), 4.8045),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0011, -2.4900), 4.7461),
    ((50.0000, 2.5000, 0.0000), (50.0000, 0.0000, -2.5000), 4.3065),
    ((50.0000, 2.5000, 0.0000), (73.0000, 25.0000, -18.0000), 27.1492),
    ((50.0000, 2.5000, 0.0000), (61.0000, -5.0000, 29.0000), 22.8977),
    ((50.0000, 2.5000, 0.0000), (56.0000, -27.0000, -3.0000), 31.9030),
    ((50.0000, 2.5000, 0.0000), (58.0000, 24.0000, 15.0000), 19.4535),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.1736, 0.5854), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2972, 0.0000), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 1.8634, 0.5757), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2592, 0.3350), 1.0000),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
    ((61.2901, 3.7196, -5.3901), (61.4292, 2.2480, -4.9620), 1.8731),
    ((35.0831, -44.1164, 3.7933), (35.0232, -40.0716, 1.5901), 1.8645),
    ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
    ((36.4612, 47.8580, 18.3852), (36.2715, 50.5065, 21.2231), 1.4146),
    ((90.8027, -2.0831, 1.4410), (91.1528, -1.6435, 0.0447), 1.4441),
    ((90.9257, -0.5406, -0.9208), (88.6381, -0.8985, -0.7239), 1.5381),
    ((6.7747, -0.2908, -2.4247), (5.8714, -0.0985, -2.2286), 0.6377),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
)


def test_dynamic_solver_module_and_public_api_exist() -> None:
    spec = importlib.util.find_spec("core.material_dynamic_solver")

    assert spec is not None
    module = importlib.import_module("core.material_dynamic_solver")
    for name in (
        "DynamicCandidateCatalog",
        "ExactDynamicSearchResult",
        "build_dynamic_candidate_catalog",
        "search_dynamic_catalog_exact",
        "_delta_e00_scalar",
        "_delta_e00_numpy",
        "_delta_e00_numba_scalar",
        "DynamicMaterialSolverError",
        "_search_exact_numpy",
        "_search_exact_numba_kernel",
    ):
        assert hasattr(module, name), name


@pytest.mark.parametrize(("lab1", "lab2", "expected"), SHARMA_CIEDE2000_PAIRS)
def test_delta_e00_implementations_match_sharma_reference_pairs(
    lab1: tuple[float, float, float],
    lab2: tuple[float, float, float],
    expected: float,
) -> None:
    first = np.asarray(lab1, dtype=np.float64)
    second = np.asarray(lab2, dtype=np.float64)

    scalar = _delta_e00_scalar(first, second)
    numpy_value = np.asarray(
        _delta_e00_numpy(first.reshape(1, 3), second.reshape(1, 3))
    ).reshape(-1)[0]
    numba_value = _delta_e00_numba_scalar(first, second)

    assert scalar == pytest.approx(expected, abs=5e-5)
    assert float(numpy_value) == pytest.approx(expected, abs=5e-5)
    assert numba_value == pytest.approx(expected, abs=5e-5)


def test_catalog_deduplicates_exact_rgb_by_shortest_stable_recipe() -> None:
    score_srgb = np.asarray(
        [
            [12, 34, 56],
            [12, 34, 56],
            [12, 34, 56],
            [12, 34, 56],
            [12, 34, 57],
            [12, 34, 57],
        ],
        dtype=np.int64,
    )
    recipes = np.asarray(
        [np.arange(7, dtype=np.int32) + row * 10 for row in range(6)]
    )
    actual_layer_counts = np.asarray([6, 5, 5, 7, 6, 7], dtype=np.int64)

    catalog = build_dynamic_candidate_catalog(
        score_srgb,
        recipes,
        actual_layer_counts,
        max_layer_count=7,
    )

    np.testing.assert_array_equal(
        catalog.score_srgb,
        np.asarray([[12, 34, 56], [12, 34, 57]], dtype=np.uint8),
    )
    assert catalog.score_srgb.dtype == np.uint8
    assert catalog.score_lab.dtype == np.float64
    np.testing.assert_allclose(catalog.score_lab, rgb_to_lab(catalog.score_srgb))
    np.testing.assert_array_equal(catalog.print_recipes, recipes[[1, 4]])
    np.testing.assert_array_equal(catalog.minimum_actual_layer_counts, [5, 6])
    np.testing.assert_array_equal(catalog.max_layer_reachable, [True, True])
    np.testing.assert_array_equal(catalog.source_indices, [1, 4])


def test_catalog_owns_read_only_array_storage() -> None:
    score_srgb = np.asarray([[1, 2, 3]], dtype=np.uint8)
    recipes = np.asarray([[0, 1, 2, 3, 4]], dtype=np.int32)
    catalog = build_dynamic_candidate_catalog(score_srgb, recipes, [5], 5)

    score_srgb[0, 0] = 99
    recipes[0, 0] = 99

    assert catalog.score_srgb[0, 0] == 1
    assert catalog.print_recipes[0, 0] == 0
    for value in (
        catalog.score_srgb,
        catalog.score_lab,
        catalog.print_recipes,
        catalog.minimum_actual_layer_counts,
        catalog.max_layer_reachable,
        catalog.source_indices,
    ):
        assert not value.flags.writeable


@pytest.mark.parametrize(
    ("score_srgb", "recipes", "counts", "max_layers"),
    (
        (np.asarray([1, 2, 3]), np.zeros((1, 5)), [5], 5),
        (np.zeros((1, 4)), np.zeros((1, 5)), [5], 5),
        (np.asarray([[256, 0, 0]]), np.zeros((1, 5)), [5], 5),
        (np.asarray([[1.5, 0, 0]]), np.zeros((1, 5)), [5], 5),
        (np.zeros((1, 3)), np.zeros((2, 5)), [5], 5),
        (np.zeros((1, 3)), np.zeros((1, 4)), [5], 5),
        (np.zeros((1, 3)), np.asarray([[0, 1, 2, 3, 4.5]]), [5], 5),
        (np.zeros((1, 3)), np.asarray([[0, 1, 2, 3, -1]]), [5], 5),
        (np.zeros((1, 3)), np.zeros((1, 5)), [[5]], 5),
        (np.zeros((1, 3)), np.zeros((1, 5)), [4], 5),
        (np.zeros((1, 3)), np.zeros((1, 5)), [6], 5),
        (np.zeros((1, 3)), np.zeros((1, 5)), [5], 4),
        (np.zeros((1, 3)), np.zeros((1, 5)), [5], 11),
    ),
)
def test_catalog_rejects_invalid_rows_and_layer_bounds(
    score_srgb: np.ndarray,
    recipes: np.ndarray,
    counts: object,
    max_layers: int,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        build_dynamic_candidate_catalog(
            score_srgb,
            recipes,
            counts,
            max_layers,
        )


def _make_random_search_fixture() -> tuple[np.ndarray, DynamicCandidateCatalog]:
    rng = np.random.default_rng(20260711)
    random_candidates = rng.integers(0, 256, size=(80, 3), dtype=np.uint8)
    candidates = np.vstack(
        [
            np.asarray(
                [
                    [0, 0, 0],
                    [255, 255, 255],
                    [255, 0, 0],
                    [0, 255, 0],
                    [0, 0, 255],
                    [255, 255, 0],
                ],
                dtype=np.uint8,
            ),
            random_candidates,
        ]
    )
    counts = rng.integers(5, 11, size=candidates.shape[0], dtype=np.int16)
    counts[:6] = np.arange(5, 11, dtype=np.int16)
    recipes = np.broadcast_to(
        np.arange(10, dtype=np.int32),
        (candidates.shape[0], 10),
    ).copy()
    catalog = build_dynamic_candidate_catalog(candidates, recipes, counts, 10)

    targets = np.vstack(
        [
            np.asarray(
                [[0, 0, 0], [255, 255, 255], [255, 0, 255]],
                dtype=np.uint8,
            ),
            rng.integers(0, 256, size=(29, 3), dtype=np.uint8),
        ]
    )
    return targets, catalog


def _brute_force_frontiers(
    targets: np.ndarray,
    catalog: DynamicCandidateCatalog,
    min_layers: int,
    max_layers: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    target_lab = rgb_to_lab(targets).astype(np.float64)
    distances = _delta_e00_numpy(
        target_lab[:, None, :],
        catalog.score_lab[None, :, :],
    )
    cap_count = max_layers - min_layers + 1
    indices = np.full((targets.shape[0], cap_count), -1, dtype=np.int64)
    values = np.full((targets.shape[0], cap_count), np.inf, dtype=np.float64)
    for cap_offset, layer_cap in enumerate(range(min_layers, max_layers + 1)):
        feasible = np.flatnonzero(
            catalog.minimum_actual_layer_counts <= layer_cap
        )
        local = np.argmin(distances[:, feasible], axis=1)
        indices[:, cap_offset] = feasible[local]
        values[:, cap_offset] = distances[
            np.arange(targets.shape[0]),
            indices[:, cap_offset],
        ]
    fixed_indices = np.flatnonzero(catalog.max_layer_reachable)
    fixed_local = np.argmin(distances[:, fixed_indices], axis=1)
    fixed = distances[
        np.arange(targets.shape[0]),
        fixed_indices[fixed_local],
    ]
    return indices, values, fixed


def test_exact_numpy_and_numba_match_exhaustive_random_frontiers() -> None:
    targets, catalog = _make_random_search_fixture()
    expected_indices, expected_values, expected_fixed = _brute_force_frontiers(
        targets,
        catalog,
        5,
        10,
    )

    numpy_result = search_dynamic_catalog_exact(
        targets,
        catalog,
        5,
        10,
        prefer_numba=False,
    )
    numba_result = search_dynamic_catalog_exact(
        targets,
        catalog,
        5,
        10,
        prefer_numba=True,
    )

    assert numpy_result.engine == "numpy"
    assert numba_result.engine == "numba"
    np.testing.assert_array_equal(
        numpy_result.cumulative_best_candidate_indices,
        expected_indices,
    )
    np.testing.assert_array_equal(
        numba_result.cumulative_best_candidate_indices,
        expected_indices,
    )
    np.testing.assert_allclose(
        numpy_result.cumulative_best_delta_e00,
        expected_values,
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        numba_result.cumulative_best_delta_e00,
        expected_values,
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        numpy_result.fixed_max_delta_e00,
        expected_fixed,
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        numba_result.fixed_max_delta_e00,
        expected_fixed,
        rtol=0.0,
        atol=1e-12,
    )


@pytest.mark.parametrize("prefer_numba", [False, True])
def test_exact_search_uses_stable_candidate_index_ties(prefer_numba: bool) -> None:
    target = np.asarray([[10, 10, 10]], dtype=np.uint8)
    tied_lab = np.broadcast_to(rgb_to_lab(target), (2, 3))
    catalog = DynamicCandidateCatalog(
        score_srgb=np.asarray([[10, 10, 10], [11, 11, 11]], dtype=np.uint8),
        score_lab=tied_lab,
        print_recipes=np.zeros((2, 6), dtype=np.int32),
        minimum_actual_layer_counts=np.asarray([6, 5]),
        max_layer_reachable=np.asarray([True, True]),
        source_indices=np.asarray([0, 1]),
    )

    result = search_dynamic_catalog_exact(
        target,
        catalog,
        5,
        6,
        prefer_numba=prefer_numba,
    )

    np.testing.assert_array_equal(
        result.cumulative_best_candidate_indices,
        [[1, 0]],
    )
    np.testing.assert_array_equal(result.cumulative_best_delta_e00, [[0.0, 0.0]])


def test_exact_search_uses_ciede2000_not_cie76_ordering() -> None:
    target = np.asarray([[223, 149, 167]], dtype=np.uint8)
    candidates = np.asarray([[184, 137, 148], [187, 141, 147]], dtype=np.uint8)
    catalog = build_dynamic_candidate_catalog(
        candidates,
        np.zeros((2, 5), dtype=np.int32),
        [5, 5],
        5,
    )
    target_lab = rgb_to_lab(target)[0]
    cie76 = np.linalg.norm(catalog.score_lab - target_lab, axis=1)
    ciede2000 = _delta_e00_numpy(
        np.broadcast_to(target_lab, catalog.score_lab.shape),
        catalog.score_lab,
    )
    assert int(np.argmin(cie76)) == 0
    assert int(np.argmin(ciede2000)) == 1

    result = search_dynamic_catalog_exact(target, catalog, 5, 5, prefer_numba=False)

    assert result.cumulative_best_candidate_indices[0, 0] == 1
    assert result.cumulative_best_delta_e00[0, 0] == pytest.approx(ciede2000[1])


def test_search_has_exact_frontier_interface_without_tolerance() -> None:
    signature = inspect.signature(search_dynamic_catalog_exact)

    assert list(signature.parameters) == [
        "target_srgb",
        "catalog",
        "min_layer_count",
        "max_layer_count",
        "prefer_numba",
    ]
    assert signature.parameters["prefer_numba"].default is True
    assert "tolerance" not in signature.parameters


def test_numba_kernel_uses_required_exact_parallel_options() -> None:
    options = getattr(dynamic_solver._search_exact_numba_kernel, "targetoptions", {})

    assert options.get("parallel") is True
    assert options.get("fastmath") is False


def test_numba_call_failure_falls_back_to_exact_numpy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets, catalog = _make_random_search_fixture()

    def fail_numba(*_args: object) -> object:
        raise RuntimeError("numba call failed")

    monkeypatch.setattr(dynamic_solver, "_search_exact_numba_kernel", fail_numba)

    fallback = search_dynamic_catalog_exact(
        targets[:2],
        catalog,
        5,
        10,
        prefer_numba=True,
    )
    expected = search_dynamic_catalog_exact(
        targets[:2],
        catalog,
        5,
        10,
        prefer_numba=False,
    )

    assert fallback.engine == "numpy"
    np.testing.assert_array_equal(
        fallback.cumulative_best_candidate_indices,
        expected.cumulative_best_candidate_indices,
    )
    np.testing.assert_allclose(
        fallback.cumulative_best_delta_e00,
        expected.cumulative_best_delta_e00,
    )
    np.testing.assert_allclose(
        fallback.fixed_max_delta_e00,
        expected.fixed_max_delta_e00,
    )


def test_both_engine_failures_raise_typed_core_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets, catalog = _make_random_search_fixture()

    def fail_engine(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("engine failed")

    monkeypatch.setattr(dynamic_solver, "_search_exact_numba_kernel", fail_engine)
    monkeypatch.setattr(dynamic_solver, "_search_exact_numpy", fail_engine)

    with pytest.raises(dynamic_solver.DynamicMaterialSolverError):
        search_dynamic_catalog_exact(
            targets[:1],
            catalog,
            5,
            10,
            prefer_numba=True,
        )


@pytest.mark.parametrize(
    ("target_srgb", "min_layers", "max_layers"),
    (
        (np.asarray([0, 0, 0]), 5, 10),
        (np.zeros((1, 4)), 5, 10),
        (np.asarray([[0, 0, 256]]), 5, 10),
        (np.asarray([[0, 0, 0.5]]), 5, 10),
        (np.zeros((1, 3)), 4, 10),
        (np.zeros((1, 3)), 5, 11),
        (np.zeros((1, 3)), 8, 7),
    ),
)
def test_search_rejects_invalid_targets_and_bounds(
    target_srgb: np.ndarray,
    min_layers: int,
    max_layers: int,
) -> None:
    _, catalog = _make_random_search_fixture()

    with pytest.raises((TypeError, ValueError)):
        search_dynamic_catalog_exact(
            target_srgb,
            catalog,
            min_layers,
            max_layers,
        )
