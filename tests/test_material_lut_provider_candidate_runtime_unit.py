"""Tests for material runtime resolver fallback behavior."""

from __future__ import annotations

import numpy as np

from core.material_candidate_cache import MaterialCandidateRuntime
from core.material_color_solver import MaterialParams


def _mat(
    name: str,
    E: tuple[float, float, float],
    k: tuple[float, float, float],
) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(E, dtype=np.float64),
        k=np.asarray(k, dtype=np.float64),
        C0_white=np.asarray((1.0, 1.0, 1.0), dtype=np.float64),
        estimated_rgb=np.asarray([int(round(255 * c)) for c in E], dtype=np.uint8),
    )


PALETTE = [
    _mat("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0)),
    _mat("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0)),
    _mat("White", E=(0.95, 0.95, 0.95), k=(0.5, 0.5, 0.5)),
]


def test_load_solver_runtime_returns_persisted_cache_when_available(monkeypatch) -> None:
    import core.material_lut_provider as provider

    sentinel = object()

    def fake_load_solver_cache(*args, **kwargs):
        return sentinel, 64

    def forbidden_candidate_build(*args, **kwargs):
        raise AssertionError("candidate runtime should not build on cache hit")

    monkeypatch.setattr(provider, "load_solver_cache", fake_load_solver_cache)
    monkeypatch.setattr(
        provider,
        "build_material_candidate_runtime",
        forbidden_candidate_build,
        raising=False,
    )

    runtime, actual_grid = provider.load_solver_runtime(
        PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
    )

    assert runtime is sentinel
    assert actual_grid == 64


def test_load_solver_runtime_builds_candidate_runtime_without_persisted_cache(
    monkeypatch,
) -> None:
    import core.material_lut_provider as provider

    monkeypatch.setattr(
        provider,
        "load_solver_cache",
        lambda *args, **kwargs: (None, None),
    )

    runtime, actual_grid = provider.load_solver_runtime(
        PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        candidate_budget=32,
    )

    assert isinstance(runtime, MaterialCandidateRuntime)
    assert runtime.valid_cell_count == 32
    assert actual_grid == runtime.grid_resolution


def test_load_solver_runtime_uses_persisted_candidate_before_building(
    tmp_path,
    monkeypatch,
) -> None:
    import core.material_lut_provider as provider
    from core.material_candidate_cache import (
        build_material_candidate_runtime,
        save_material_candidate_runtime,
    )

    saved_runtime = build_material_candidate_runtime(
        materials=PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=provider.MaterialCandidateCacheConfig(candidate_budget=32, seed=5),
    )
    save_material_candidate_runtime(saved_runtime, cache_root=tmp_path)

    monkeypatch.setattr(provider, "load_solver_cache", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(
        provider,
        "build_material_candidate_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("persisted candidate runtime should load before build")
        ),
    )

    runtime, actual_grid = provider.load_solver_runtime(
        PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        cache_root=tmp_path,
        candidate_budget=32,
    )

    assert isinstance(runtime, MaterialCandidateRuntime)
    assert runtime.valid_cell_count == saved_runtime.valid_cell_count
    assert actual_grid == runtime.grid_resolution
