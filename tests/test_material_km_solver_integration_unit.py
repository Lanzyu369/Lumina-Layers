"""Focused integration coverage for KM material solving and caches."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from core.km_xyz import (
    KM_XYZ_COLOR_BRIDGE_ID,
    KM_XYZ_MEASUREMENT_PROTOCOL_ID,
    KM_XYZ_MODEL_ID,
    km_relative_xyz_to_linear_srgb,
    km_stack_reflectance,
)
from core.material_cache import canonical_palette_order, describe_palette
from core.material_candidate_cache import (
    MaterialCandidateCacheConfig,
    build_material_candidate_runtime,
    candidate_cache_file_path,
    load_material_candidate_runtime,
    save_material_candidate_runtime,
)
from core.material_color_solver import (
    MaterialParams,
    forward_batch_model,
    forward_model,
    predict_material_recipes_colorimetry,
)
from core.material_dynamic_solver import (
    DynamicMaterialSolveConfig,
    solve_dynamic_material_colors,
)
from core.material_lut_synthesis import load_material_params, load_multiple_materials
from core.material_optical_runtime import (
    BEER_LAMBERT_MODEL_ID,
    MaterialMeasurementProtocolMismatchError,
    MaterialOpticalModelMismatchError,
    validate_material_optical_contract,
)


def _km_material(
    name: str,
    absorption: tuple[float, float, float],
    scattering: tuple[float, float, float],
    *,
    protocol: str = KM_XYZ_MEASUREMENT_PROTOCOL_ID,
    color_bridge: str = KM_XYZ_COLOR_BRIDGE_ID,
    coefficient_unit: str = "mm^-1",
    revision: str = "revision-1",
) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.casefold(),
        E=np.zeros(3, dtype=np.float64),
        k=np.zeros(3, dtype=np.float64),
        C0_white=np.ones(3, dtype=np.float64),
        estimated_rgb=np.asarray([128, 128, 128], dtype=np.uint8),
        optical_model_id=KM_XYZ_MODEL_ID,
        km_K=np.asarray(absorption, dtype=np.float64),
        km_S=np.asarray(scattering, dtype=np.float64),
        coefficient_unit=coefficient_unit,
        measurement_protocol_id=protocol,
        color_bridge_id=color_bridge,
        archive_revision_id=revision,
    )


def _bl_material(name: str = "legacy") -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name,
        E=np.asarray([0.4, 0.3, 0.2], dtype=np.float64),
        k=np.asarray([2.0, 3.0, 4.0], dtype=np.float64),
        C0_white=np.ones(3, dtype=np.float64),
        estimated_rgb=np.asarray([120, 100, 80], dtype=np.uint8),
    )


@pytest.fixture
def km_materials() -> list[MaterialParams]:
    return [
        _km_material("A", (1.0, 2.0, 3.0), (2.0, 1.0, 0.5)),
        _km_material("B", (0.5, 0.2, 0.1), (0.4, 1.0, 2.0)),
    ]


def test_palette_rejects_mixed_models_and_incompatible_km_protocols(
    km_materials: list[MaterialParams],
) -> None:
    with pytest.raises(MaterialOpticalModelMismatchError):
        validate_material_optical_contract([km_materials[0], _bl_material()])

    incompatible = _km_material(
        "C",
        (0.7, 0.8, 0.9),
        (1.0, 1.1, 1.2),
        protocol="another-protocol/v1",
    )
    with pytest.raises(MaterialMeasurementProtocolMismatchError):
        validate_material_optical_contract([km_materials[0], incompatible])


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"protocol": "unknown-protocol/v1"},
            "Unsupported KM measurement protocol",
        ),
        (
            {"color_bridge": "unknown-bridge/v1"},
            "Unsupported KM color bridge",
        ),
        (
            {"coefficient_unit": "cm^-1"},
            "Unsupported KM coefficient unit",
        ),
    ],
)
def test_single_km_material_rejects_unknown_optical_contract_values(
    overrides: dict[str, str],
    message: str,
) -> None:
    material = _km_material(
        "UnknownContract",
        (0.7, 0.8, 0.9),
        (1.0, 1.1, 1.2),
        **overrides,
    )
    with pytest.raises(MaterialMeasurementProtocolMismatchError, match=message):
        validate_material_optical_contract([material])


def test_km_forward_is_bottom_to_top_and_batch_matches_direct(
    km_materials: list[MaterialParams],
) -> None:
    recipe = np.asarray([0, 1], dtype=np.int32)
    reverse = recipe[::-1].copy()
    expected_xyz = km_stack_reflectance(
        np.stack([km_materials[index].km_K for index in recipe]),
        np.stack([km_materials[index].km_S for index in recipe]),
        0.08,
        np.ones(3, dtype=np.float64),
    )
    expected_linear = km_relative_xyz_to_linear_srgb(expected_xyz)

    np.testing.assert_allclose(
        forward_model(recipe, km_materials, 0.08),
        expected_linear,
        rtol=0.0,
        atol=1e-12,
    )
    batch = forward_batch_model(
        np.stack([recipe, reverse]),
        km_materials,
        0.08,
    )
    np.testing.assert_allclose(batch[0], expected_linear, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(
        batch,
        np.stack(
            [
                forward_model(recipe, km_materials, 0.08),
                forward_model(reverse, km_materials, 0.08),
            ]
        ),
        rtol=0.0,
        atol=1e-12,
    )
    assert not np.allclose(batch[0], batch[1])


def test_km_exact_candidate_runtime_keeps_float_xyz_and_matches_prediction(
    km_materials: list[MaterialParams],
) -> None:
    runtime = build_material_candidate_runtime(
        materials=km_materials,
        layer_count=5,
        layer_height_mm=0.08,
        config=MaterialCandidateCacheConfig(
            candidate_budget=64,
            candidate_pool_multiplier=1,
            build_worker_count=1,
        ),
    )
    assert runtime.exact_recipe_space is True
    assert runtime.valid_cell_count == 2**5
    assert runtime.achieved_xyz is not None
    assert runtime.achieved_xyz.dtype == np.float64
    assert runtime.metadata["inverse_refinement"]["enabled"] is False

    canonical = [km_materials[index] for index in canonical_palette_order(km_materials)]
    prediction = predict_material_recipes_colorimetry(
        runtime.candidate_recipes,
        canonical,
        0.08,
    )
    np.testing.assert_allclose(runtime.achieved_xyz, prediction.matching_xyz)
    np.testing.assert_allclose(runtime.achieved_lab, prediction.lab, atol=1e-5)
    np.testing.assert_array_equal(runtime.achieved_srgb, prediction.display_srgb)


def test_km_large_candidate_runtime_is_deterministic(
    km_materials: list[MaterialParams],
) -> None:
    materials = km_materials + [
        _km_material("C", (0.2, 0.7, 1.4), (1.5, 0.8, 0.3))
    ]
    config = MaterialCandidateCacheConfig(
        candidate_budget=32,
        candidate_pool_multiplier=1,
        build_worker_count=1,
        seed=17,
    )
    first = build_material_candidate_runtime(
        materials=materials,
        layer_count=5,
        layer_height_mm=0.08,
        config=config,
    )
    second = build_material_candidate_runtime(
        materials=materials,
        layer_count=5,
        layer_height_mm=0.08,
        config=config,
    )
    assert first.exact_recipe_space is False
    np.testing.assert_array_equal(first.candidate_recipes, second.candidate_recipes)
    np.testing.assert_allclose(first.achieved_xyz, second.achieved_xyz)


@pytest.mark.parametrize("candidate_budget", [12, 16, 20])
def test_km_large_candidate_runtime_fills_budget_with_unique_recipes(
    km_materials: list[MaterialParams],
    candidate_budget: int,
) -> None:
    config = MaterialCandidateCacheConfig(
        candidate_budget=candidate_budget,
        candidate_pool_multiplier=1,
        build_worker_count=1,
        seed=17,
    )
    first = build_material_candidate_runtime(
        materials=km_materials,
        layer_count=5,
        layer_height_mm=0.08,
        config=config,
    )
    second = build_material_candidate_runtime(
        materials=km_materials,
        layer_count=5,
        layer_height_mm=0.08,
        config=config,
    )

    assert first.exact_recipe_space is False
    assert first.valid_cell_count == min(candidate_budget, 2**5)
    assert np.unique(first.candidate_recipes, axis=0).shape[0] == candidate_budget
    np.testing.assert_array_equal(first.candidate_recipes, second.candidate_recipes)
    np.testing.assert_allclose(first.achieved_xyz, second.achieved_xyz)




def test_km_cache_namespace_persists_xyz_and_revision_invalidates(
    tmp_path: Path,
    km_materials: list[MaterialParams],
) -> None:
    config = MaterialCandidateCacheConfig(
        candidate_budget=64,
        candidate_pool_multiplier=1,
        build_worker_count=1,
    )
    runtime = build_material_candidate_runtime(
        materials=km_materials,
        layer_count=5,
        layer_height_mm=0.08,
        config=config,
    )
    path = save_material_candidate_runtime(runtime, cache_root=tmp_path)
    assert path.name.startswith("candidate-")
    assert runtime.metadata["algorithm_version"] == "km-xyz-hybrid-v2"
    loaded = load_material_candidate_runtime(
        km_materials,
        5,
        0.08,
        candidate_budget=64,
        cache_root=tmp_path,
        config=config,
    )
    assert loaded is not None
    np.testing.assert_allclose(loaded.achieved_xyz, runtime.achieved_xyz)

    changed = [
        _km_material(
            material.name,
            tuple(float(value) for value in material.km_K),
            tuple(float(value) for value in material.km_S),
            revision="revision-2",
        )
        for material in km_materials
    ]
    changed_path = candidate_cache_file_path(
        changed,
        5,
        0.08,
        "white",
        candidate_budget=64,
        cache_root=tmp_path,
    )
    assert changed_path != path
    assert (
        load_material_candidate_runtime(
            changed,
            5,
            0.08,
            candidate_budget=64,
            cache_root=tmp_path,
        )
        is None
    )


@pytest.mark.parametrize("corruption", ["recipe", "lab", "xyz"])
def test_km_cache_rejects_corrupt_recipe_and_colorimetry_arrays(
    tmp_path: Path,
    km_materials: list[MaterialParams],
    corruption: str,
) -> None:
    runtime = build_material_candidate_runtime(
        materials=km_materials,
        layer_count=5,
        layer_height_mm=0.08,
        config=MaterialCandidateCacheConfig(
            candidate_budget=16,
            candidate_pool_multiplier=1,
            build_worker_count=1,
        ),
    )
    path = save_material_candidate_runtime(runtime, cache_root=tmp_path)
    with np.load(path) as loaded:
        arrays = {name: loaded[name].copy() for name in loaded.files}

    if corruption == "recipe":
        arrays["candidate_recipes"][0, 0] = len(km_materials)
    elif corruption == "lab":
        arrays["achieved_lab"][0, 0] = np.nan
    else:
        arrays["achieved_xyz"][0, 0] = np.inf
    with path.open("wb") as handle:
        np.savez_compressed(handle, **arrays)

    assert (
        load_material_candidate_runtime(
            km_materials,
            5,
            0.08,
            candidate_budget=16,
            cache_root=tmp_path,
        )
        is None
    )


def test_dynamic_km_keeps_float_distinct_candidates_and_backing_padding(
    km_materials: list[MaterialParams],
) -> None:
    def loader(
        materials: list[MaterialParams],
        layer_count: int,
        height: float,
        substrate: str,
    ) -> tuple[object, int]:
        return (
            build_material_candidate_runtime(
                materials=materials,
                layer_count=layer_count,
                layer_height_mm=height,
                substrate=substrate,
                config=MaterialCandidateCacheConfig(
                    candidate_budget=64,
                    candidate_pool_multiplier=1,
                    build_worker_count=1,
                ),
            ),
            8,
        )

    result = solve_dynamic_material_colors(
        np.asarray([[245, 205, 195]], dtype=np.uint8),
        km_materials,
        backing_material_index=0,
        layer_height_mm=0.08,
        substrate="white",
        config=DynamicMaterialSolveConfig(5, 6, 0.5),
        runtime_loader=loader,
    )
    assert result.candidate_count_before_dedup == result.candidate_count_after_dedup
    selected = result.matches[0].selected
    assert len(selected.actual_recipe_bottom_to_top) == selected.actual_layer_count
    assert len(selected.print_recipe_bottom_to_top) == 6
    padding = 6 - selected.actual_layer_count
    assert selected.print_recipe_bottom_to_top[:padding] == (0,) * padding


def test_loader_defaults_legacy_and_loads_explicit_km_profile(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / "material.json").write_text(
        json.dumps(
            {
                "material_name": "Legacy",
                "stage_a_params_file": "stage_A_parameters.json",
            }
        ),
        encoding="utf-8",
    )
    (legacy_dir / "stage_A_parameters.json").write_text(
        json.dumps(
            {
                "parameters": {
                    "channels": [{"E": [0.4, 0.3, 0.2], "k": [2.0, 3.0, 4.0]}],
                    "substrates": [
                        {"substrate_id": "white", "C0": [1.0, 1.0, 1.0]}
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    km_dir = tmp_path / "km"
    km_dir.mkdir()
    (km_dir / "material.json").write_text(
        json.dumps(
            {
                "material_name": "KM",
                "optical_model": KM_XYZ_MODEL_ID,
                "measurement_protocol": KM_XYZ_MEASUREMENT_PROTOCOL_ID,
                "km_xyz_parameters_file": "km_xyz_parameters.json",
                "estimated_rgb": [100, 110, 120],
                "archive_consistency": {"revision_id": "revision-1"},
            }
        ),
        encoding="utf-8",
    )
    (km_dir / "km_xyz_parameters.json").write_text(
        json.dumps(
            {
                "optical_model": KM_XYZ_MODEL_ID,
                "coefficient_unit": "mm^-1",
                "protocol": KM_XYZ_MEASUREMENT_PROTOCOL_ID,
                "parameters": {
                    "K": [0.5, 0.6, 0.7],
                    "S": [1.0, 1.1, 1.2],
                    "unit": "mm^-1",
                },
            }
        ),
        encoding="utf-8",
    )

    legacy = load_material_params("legacy", materials_dir=str(tmp_path))
    km = load_material_params("km", materials_dir=str(tmp_path))
    assert legacy.optical_model_id == BEER_LAMBERT_MODEL_ID
    assert km.optical_model_id == KM_XYZ_MODEL_ID
    np.testing.assert_allclose(km.km_K, [0.5, 0.6, 0.7])
    np.testing.assert_allclose(km.km_S, [1.0, 1.1, 1.2])
    with pytest.raises(MaterialOpticalModelMismatchError):
        load_multiple_materials(["legacy", "km"], materials_dir=str(tmp_path))


def test_explicit_legacy_model_keeps_historical_fingerprint() -> None:
    implicit = _bl_material("same")
    explicit = MaterialParams(
        name=implicit.name,
        directory_name=implicit.directory_name,
        E=implicit.E,
        k=implicit.k,
        C0_white=implicit.C0_white,
        estimated_rgb=implicit.estimated_rgb,
        optical_model_id=BEER_LAMBERT_MODEL_ID,
    )
    assert describe_palette([implicit]) == describe_palette([explicit])


def test_beer_lambert_candidate_sampling_remains_unchanged() -> None:
    materials = [
        _bl_material("a"),
        MaterialParams(
            name="b",
            directory_name="b",
            E=np.asarray([0.2, 0.5, 0.6], dtype=np.float64),
            k=np.asarray([1.0, 2.0, 3.0], dtype=np.float64),
            C0_white=np.ones(3, dtype=np.float64),
            estimated_rgb=np.asarray([100, 100, 100], dtype=np.uint8),
        ),
    ]
    runtime = build_material_candidate_runtime(
        materials=materials,
        layer_count=5,
        layer_height_mm=0.08,
        config=MaterialCandidateCacheConfig(
            candidate_budget=16,
            candidate_pool_multiplier=1,
            build_worker_count=1,
            seed=17,
        ),
    )
    expected = np.asarray(
        [
            [0, 0, 0, 0, 0],
            [1, 1, 1, 1, 1],
            [0, 0, 0, 0, 1],
            [0, 0, 0, 1, 1],
            [0, 0, 1, 1, 1],
            [0, 1, 0, 1, 0],
            [1, 1, 1, 1, 0],
            [1, 1, 1, 0, 0],
            [1, 1, 0, 0, 0],
            [1, 0, 1, 0, 1],
            [1, 1, 0, 0, 1],
            [0, 0, 1, 1, 0],
            [0, 1, 0, 0, 0],
            [1, 0, 1, 1, 1],
            [1, 1, 1, 1, 1],
            [0, 0, 0, 0, 0],
        ],
        dtype=runtime.candidate_recipes.dtype,
    )
    np.testing.assert_array_equal(runtime.candidate_recipes, expected)
