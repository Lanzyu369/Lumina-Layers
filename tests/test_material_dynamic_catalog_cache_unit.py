"""Unit tests for the persistent dynamic material candidate catalog.

动态耗材候选目录持久缓存单元测试。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

import core.material_dynamic_catalog_cache as catalog_cache
import core.material_dynamic_solver as dynamic_solver
import core.material_lut_provider as material_provider
from core.material_candidate_cache import (
    PREVIEW_SAFE_CANDIDATE_BUDGET,
    MaterialCandidateRuntime,
)
from core.material_color_solver import MaterialParams
from core.material_dynamic_catalog_cache import (
    DYNAMIC_CATALOG_ALGORITHM_VERSION,
    DynamicCatalogCacheCorruptionError,
    build_dynamic_catalog_cache_key,
    dynamic_catalog_cache_file_path,
    load_dynamic_candidate_catalog,
    load_or_build_dynamic_candidate_catalog,
    save_dynamic_candidate_catalog,
)
from core.material_dynamic_solver import build_dynamic_candidate_catalog


def _material(name: str, rgb: tuple[float, float, float]) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(rgb, dtype=np.float64),
        k=np.asarray([8.0, 8.0, 8.0], dtype=np.float64),
        C0_white=np.ones(3, dtype=np.float64),
        estimated_rgb=np.asarray(np.round(np.asarray(rgb) * 255), dtype=np.uint8),
    )


def _materials() -> list[MaterialParams]:
    return [
        _material("Red", (0.85, 0.08, 0.06)),
        _material("Blue", (0.05, 0.10, 0.85)),
    ]


def _catalog() -> dynamic_solver.DynamicCandidateCatalog:
    return build_dynamic_candidate_catalog(
        np.asarray([[12, 34, 56], [78, 90, 123]], dtype=np.uint8),
        np.asarray(
            [
                [0, 1, 1, 0, 1, 0],
                [1, 0, 1, 0, 0, 1],
            ],
            dtype=np.int32,
        ),
        np.asarray([5, 6], dtype=np.int16),
        6,
    )


def _key(
    materials: list[MaterialParams],
    *,
    backing_material_index: int = 0,
    min_layer_count: int = 5,
    max_layer_count: int = 6,
    candidate_budget: int = 2048,
    algorithm_version: str = DYNAMIC_CATALOG_ALGORITHM_VERSION,
):
    return build_dynamic_catalog_cache_key(
        materials,
        backing_material_index=backing_material_index,
        layer_height_mm=0.08,
        substrate="white",
        min_layer_count=min_layer_count,
        max_layer_count=max_layer_count,
        candidate_budget=candidate_budget,
        algorithm_version=algorithm_version,
    )


def _runtime(recipes: np.ndarray, layer_count: int) -> MaterialCandidateRuntime:
    rows = int(recipes.shape[0])
    return MaterialCandidateRuntime(
        candidate_recipes=np.asarray(recipes, dtype=np.uint8),
        achieved_srgb=np.full((rows, 3), 255, dtype=np.uint8),
        achieved_lab=np.zeros((rows, 3), dtype=np.float64),
        pinned_mask=np.zeros(rows, dtype=np.bool_),
        metadata={
            "layer_count": layer_count,
            "layer_height_mm": 0.08,
            "substrate": "white",
            "palette_hash": "test",
            "grid_resolution": 8,
        },
    )


def test_cache_key_covers_version_palette_backing_range_height_substrate_and_budget() -> None:
    materials = _materials()
    base = _key(materials)

    assert _key(list(reversed(materials)), backing_material_index=1) == base
    variants = {
        _key(materials, backing_material_index=1),
        _key(materials, min_layer_count=6),
        _key(materials, max_layer_count=7),
        _key(materials, candidate_budget=4096),
        _key(materials, algorithm_version="dynamic-ciede2000-v-next"),
        build_dynamic_catalog_cache_key(
            materials,
            backing_material_index=0,
            layer_height_mm=0.12,
            substrate="white",
            min_layer_count=5,
            max_layer_count=6,
            candidate_budget=2048,
        ),
        build_dynamic_catalog_cache_key(
            materials,
            backing_material_index=0,
            layer_height_mm=0.08,
            substrate="black",
            min_layer_count=5,
            max_layer_count=6,
            candidate_budget=2048,
        ),
    }
    assert base not in variants
    assert len(variants) == 7


def test_catalog_round_trip_rebinds_canonical_recipes_to_current_user_order(
    tmp_path: Path,
) -> None:
    materials = _materials()
    key = _key(materials)
    original = _catalog()
    save_dynamic_candidate_catalog(
        original,
        materials=materials,
        key=key,
        candidate_count_before_dedup=3,
        cache_root=tmp_path,
    )

    reversed_materials = list(reversed(materials))
    loaded = load_dynamic_candidate_catalog(
        materials=reversed_materials,
        key=_key(reversed_materials, backing_material_index=1),
        cache_root=tmp_path,
    )

    assert loaded is not None
    np.testing.assert_array_equal(loaded.catalog.score_srgb, original.score_srgb)
    np.testing.assert_array_equal(loaded.catalog.score_lab, original.score_lab)
    np.testing.assert_array_equal(
        loaded.catalog.print_recipes,
        1 - original.print_recipes,
    )
    assert loaded.candidate_count_before_dedup == 3


def test_cache_hit_is_bit_identical_to_fresh_build_and_does_not_rebuild(
    tmp_path: Path,
) -> None:
    materials = _materials()
    key = _key(materials)
    built = _catalog()
    build_calls = 0

    def builder() -> tuple[dynamic_solver.DynamicCandidateCatalog, int]:
        nonlocal build_calls
        build_calls += 1
        return built, 3

    first = load_or_build_dynamic_candidate_catalog(
        materials=materials,
        key=key,
        builder=builder,
        cache_root=tmp_path,
    )
    second = load_or_build_dynamic_candidate_catalog(
        materials=materials,
        key=key,
        builder=builder,
        cache_root=tmp_path,
    )

    assert build_calls == 1
    assert first.cache_hit is False
    assert second.cache_hit is True
    for field in (
        "score_srgb",
        "score_lab",
        "print_recipes",
        "minimum_actual_layer_counts",
        "max_layer_reachable",
        "source_indices",
    ):
        np.testing.assert_array_equal(
            getattr(first.catalog, field),
            getattr(second.catalog, field),
        )


def test_cache_write_is_one_atomic_npz_replace_without_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = _materials()
    key = _key(materials)
    replacements: list[tuple[Path, Path]] = []
    original_replace = os.replace

    def capture_replace(source: os.PathLike[str], target: os.PathLike[str]) -> None:
        replacements.append((Path(source), Path(target)))
        original_replace(source, target)

    monkeypatch.setattr(catalog_cache.os, "replace", capture_replace)
    path = save_dynamic_candidate_catalog(
        _catalog(),
        materials=materials,
        key=key,
        candidate_count_before_dedup=3,
        cache_root=tmp_path,
    )

    assert replacements == [(replacements[0][0], path)]
    assert len(replacements) == 1
    assert path.suffix == ".npz"
    assert list(path.parent.glob(path.stem + "*.json")) == []
    assert list(path.parent.glob("*.tmp-*")) == []


def test_corrupt_entry_is_removed_and_explicitly_rebuilt(tmp_path: Path) -> None:
    materials = _materials()
    key = _key(materials)
    path = dynamic_catalog_cache_file_path(key, cache_root=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not-an-npz")
    build_calls = 0

    def builder() -> tuple[dynamic_solver.DynamicCandidateCatalog, int]:
        nonlocal build_calls
        build_calls += 1
        return _catalog(), 3

    result = load_or_build_dynamic_candidate_catalog(
        materials=materials,
        key=key,
        builder=builder,
        cache_root=tmp_path,
    )

    assert build_calls == 1
    assert result.cache_hit is False
    assert result.rebuilt_corrupt is True
    assert path.exists()
    assert load_dynamic_candidate_catalog(
        materials=materials,
        key=key,
        cache_root=tmp_path,
    ) is not None


def test_invalid_payload_raises_corruption_instead_of_becoming_a_hit(
    tmp_path: Path,
) -> None:
    materials = _materials()
    key = _key(materials)
    path = dynamic_catalog_cache_file_path(key, cache_root=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        np.savez_compressed(
            handle,
            score_srgb=np.asarray([[1, 2, 3]], dtype=np.uint8),
            metadata_json=np.frombuffer(b"{}", dtype=np.uint8),
        )

    with pytest.raises(DynamicCatalogCacheCorruptionError):
        load_dynamic_candidate_catalog(
            materials=materials,
            key=key,
            cache_root=tmp_path,
        )


def test_persisted_payload_contains_catalog_only_and_never_target_results(
    tmp_path: Path,
) -> None:
    materials = _materials()
    key = _key(materials)
    path = save_dynamic_candidate_catalog(
        _catalog(),
        materials=materials,
        key=key,
        candidate_count_before_dedup=3,
        cache_root=tmp_path,
    )

    with np.load(path, allow_pickle=False) as payload:
        assert set(payload.files) == {
            "score_srgb",
            "score_lab",
            "print_recipes_canonical",
            "minimum_actual_layer_counts",
            "max_layer_reachable",
            "source_indices",
            "metadata_json",
        }
        metadata = json.loads(payload["metadata_json"].tobytes().decode("utf-8"))
    assert "target_srgb" not in metadata
    assert "matches" not in metadata
    assert "search" not in metadata


def test_production_solver_pins_candidate_budget_for_every_layer_and_skips_fixed_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = _materials()
    runtimes = {
        5: _runtime(np.asarray([[0, 0, 0, 0, 0]], dtype=np.uint8), 5),
        6: _runtime(np.asarray([[1, 1, 1, 1, 1, 1]], dtype=np.uint8), 6),
    }
    calls: list[tuple[int, int]] = []

    def dynamic_loader(
        _materials: list[MaterialParams],
        layer_count: int,
        layer_height_mm: float,
        substrate: str,
        *,
        candidate_budget: int,
        cache_root: str | Path | None = None,
    ) -> tuple[MaterialCandidateRuntime, int]:
        del layer_height_mm, substrate, cache_root
        calls.append((layer_count, candidate_budget))
        return runtimes[layer_count], 8

    monkeypatch.setattr(dynamic_solver, "load_dynamic_candidate_runtime", dynamic_loader)
    monkeypatch.setattr(
        "core.material_lut_provider.load_solver_cache",
        lambda *_args, **_kwargs: pytest.fail("legacy fixed cache must not be queried"),
    )

    dynamic_solver.solve_dynamic_material_colors(
        np.asarray([[120, 30, 40]], dtype=np.uint8),
        materials,
        backing_material_index=0,
        layer_height_mm=0.08,
        substrate="white",
        config=dynamic_solver.DynamicMaterialSolveConfig(5, 6, 0.5),
        catalog_cache_root=tmp_path,
    )

    assert calls == [
        (5, PREVIEW_SAFE_CANDIDATE_BUDGET),
        (6, PREVIEW_SAFE_CANDIDATE_BUDGET),
    ]


def test_dynamic_runtime_provider_bypasses_legacy_fixed_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = _materials()
    runtime = _runtime(np.asarray([[0, 0, 0, 0, 0]], dtype=np.uint8), 5)
    candidate_calls: list[int] = []
    monkeypatch.setattr(
        material_provider,
        "load_solver_cache",
        lambda *_args, **_kwargs: pytest.fail("fixed cache must not be probed"),
    )

    def load_candidate(*_args, candidate_budget: int, **_kwargs):
        candidate_calls.append(candidate_budget)
        return runtime

    monkeypatch.setattr(
        material_provider,
        "load_material_candidate_runtime",
        load_candidate,
    )

    loaded, diagnostic_grid = material_provider.load_dynamic_candidate_runtime(
        materials,
        5,
        0.08,
        "white",
        candidate_budget=PREVIEW_SAFE_CANDIDATE_BUDGET,
    )

    assert loaded is runtime
    assert diagnostic_grid == runtime.grid_resolution
    assert candidate_calls == [PREVIEW_SAFE_CANDIDATE_BUDGET]


def test_custom_runtime_loader_bypasses_persistent_catalog_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = _materials()
    runtime = _runtime(np.asarray([[0, 0, 0, 0, 0]], dtype=np.uint8), 5)
    monkeypatch.setattr(
        catalog_cache,
        "load_or_build_dynamic_candidate_catalog",
        lambda **_kwargs: pytest.fail("custom loaders must bypass persistence"),
    )

    result = dynamic_solver.solve_dynamic_material_colors(
        np.asarray([[120, 30, 40]], dtype=np.uint8),
        materials,
        backing_material_index=0,
        layer_height_mm=0.08,
        substrate="white",
        config=dynamic_solver.DynamicMaterialSolveConfig(5, 5, 0.5),
        runtime_loader=lambda _m, _k, _h, _s: (runtime, 8),
    )

    assert len(result.matches) == 1
