"""Dynamic material replacement and editing contracts.

动态耗材替换与编辑契约。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import (
    externalize_preview_cache,
    hydrate_preview_cache,
    is_preview_cache_artifact_ref,
)
from api.session_store import SessionStore
from core.material_dynamic_solver import DynamicMaterialCandidateError


def test_automatic_dynamic_sync_uses_exact_solver_and_saves_metadata() -> None:
    from api.routers.converter import replace

    target = np.asarray([10, 20, 30], dtype=np.uint8)
    matched = np.asarray([[11, 22, 33]], dtype=np.uint8)
    print_recipe = np.asarray([[0, 2, 3, 4, 0, 1, 1]], dtype=np.int32)
    dynamic_info = {
        "enabled": True,
        "min_layer_count": 5,
        "max_layer_count": 7,
        "delta_e00_tolerance": 0.4,
        "engine": "numba",
        "colors": [
            {
                "target_srgb": target.tolist(),
                "matched_srgb": matched[0].tolist(),
                "actual_layer_count": 5,
                "padding_layer_count": 2,
                "actual_recipe_top_to_bottom": [0, 2, 3, 4, 0],
                "print_recipe_top_to_bottom": print_recipe[0].tolist(),
            }
        ],
        "benefit_curve": [],
    }
    solver_info = {"dynamic_engine": "numba"}
    session_data = {
        "material_source": "material_archive",
        "selected_materials": ["mat-a", "mat-b"],
        "material_backing_material_index": 1,
        "material_layer_height_mm": 0.08,
        "material_dynamic_layer_count_enabled": True,
        "material_min_layer_count": 5,
        "material_max_layer_count": 7,
        "material_delta_e00_tolerance": 0.4,
    }
    cache = {
        "material_matrix": np.zeros((1, 2, 7), dtype=np.int16),
        "mask_solid": np.ones((1, 2), dtype=bool),
        "quantized_image": np.asarray(
            [[[10, 20, 30], [1, 2, 3]]],
            dtype=np.uint8,
        ),
    }
    diff_mask = np.asarray([[True, False]])
    updated_rgb = np.asarray([[[10, 20, 30], [1, 2, 3]]], dtype=np.uint8)
    fixed_cache = MagicMock()
    fixed_cache.lookup.return_value = (
        matched,
        np.zeros((1, 7), dtype=np.int32),
        np.zeros((1,), dtype=np.float64),
    )

    with (
        patch.object(replace, "load_multiple_materials", return_value=[object(), object()]),
        patch.object(
            replace,
            "_solve_dynamic_material_targets",
            create=True,
            return_value=(
                matched,
                print_recipe,
                np.asarray([0.2]),
                dynamic_info,
                solver_info,
            ),
        ) as exact_solve,
        patch.object(
            replace,
            "load_material_solver_cache_with_fallback",
            return_value=(fixed_cache, 64),
        ),
    ):
        replace._sync_material_archive_matrix_for_diff(
            session_data,
            cache,
            diff_mask,
            updated_rgb,
        )

    exact_solve.assert_called_once()
    np.testing.assert_array_equal(updated_rgb[0, 0], matched[0])
    np.testing.assert_array_equal(cache["material_matrix"][0, 0], print_recipe[0])
    assert cache["material_dynamic_layer_info"] == dynamic_info
    assert cache["material_solver_info"] == solver_info


def test_manual_actual_top_to_bottom_recipe_pads_with_explicit_backing() -> None:
    from api.routers.converter import replace

    prepare = getattr(replace, "_prepare_dynamic_manual_recipe", None)
    assert callable(prepare), "dynamic manual recipe preparation is missing"

    result = prepare(
        session_data={
            "selected_materials": ["mat-a", "mat-b", "mat-c"],
            "material_backing_material_index": 1,
            "material_dynamic_layer_count_enabled": True,
            "material_min_layer_count": 5,
            "material_max_layer_count": 7,
        },
        recipe=[2, 1, 0, 2, 1],
        layer_order="Top2Bottom",
        color_layers=5,
    )

    assert result["actual_recipe_top_to_bottom"] == [2, 1, 0, 2, 1]
    assert result["print_recipe_top_to_bottom"] == [2, 1, 0, 2, 1, 1, 1]
    assert result["actual_layer_count"] == 5
    assert result["padding_layer_count"] == 2
    assert result["backing_material_index"] == 1


def test_manual_bottom_to_top_recipe_preserves_physical_order_before_padding() -> None:
    from api.routers.converter import replace

    result = replace._prepare_dynamic_manual_recipe(
        session_data={
            "selected_materials": ["mat-a", "mat-b", "mat-c"],
            "material_backing_material_index": 1,
            "material_dynamic_layer_count_enabled": True,
            "material_min_layer_count": 5,
            "material_max_layer_count": 7,
        },
        recipe=[1, 2, 0, 1, 2],
        layer_order="Bottom2Top",
        color_layers=5,
    )

    assert result["actual_recipe_top_to_bottom"] == [2, 1, 0, 2, 1]
    assert result["print_recipe_top_to_bottom"] == [2, 1, 0, 2, 1, 1, 1]


def test_region_read_uses_saved_actual_recipe_with_real_backing_layers() -> None:
    from api.routers.converter import replace

    resolve = getattr(replace, "_resolve_dynamic_region_actual_recipe", None)
    assert callable(resolve), "dynamic actual-recipe resolver is missing"

    actual_recipe = [2, 1, 0, 1, 1]
    print_recipe = [2, 1, 0, 1, 1, 1, 1]
    resolved = resolve(
        session_data={
            "material_dynamic_layer_count_enabled": True,
            "material_min_layer_count": 5,
            "material_max_layer_count": 7,
            "selected_materials": ["mat-a", "mat-b", "mat-c"],
            "material_backing_material_index": 1,
            "recipe_overrides": [
                {
                    "region_id": "region-1",
                    "recipe": actual_recipe,
                    "layer_order": "Top2Bottom",
                    "actual_recipe_top_to_bottom": actual_recipe,
                    "print_recipe_top_to_bottom": print_recipe,
                    "actual_layer_count": 5,
                    "padding_layer_count": 2,
                }
            ],
        },
        cache={"material_dynamic_layer_info": {"colors": []}},
        region_id="region-1",
        print_recipe_top_to_bottom=print_recipe,
    )

    assert resolved == actual_recipe


def test_region_read_rejects_non_backing_print_tail() -> None:
    from api.routers.converter import replace

    actual_recipe = [2, 1, 0, 1, 1]
    invalid_print = [2, 1, 0, 1, 1, 2, 2]
    with pytest.raises(HTTPException) as exc_info:
        replace._resolve_dynamic_region_actual_recipe(
            session_data={
                "material_dynamic_layer_count_enabled": True,
                "material_min_layer_count": 5,
                "material_max_layer_count": 7,
                "selected_materials": ["mat-a", "mat-b", "mat-c"],
                "material_backing_material_index": 1,
                "recipe_overrides": [
                    {
                        "region_id": "region-1",
                        "actual_recipe_top_to_bottom": actual_recipe,
                        "print_recipe_top_to_bottom": invalid_print,
                        "actual_layer_count": 5,
                        "padding_layer_count": 2,
                    }
                ],
            },
            cache={"material_dynamic_layer_info": {"colors": []}},
            region_id="region-1",
            print_recipe_top_to_bottom=invalid_print,
        )

    assert exc_info.value.status_code == 409


def test_region_read_rejects_missing_dynamic_actual_metadata() -> None:
    from api.routers.converter import replace

    with pytest.raises(HTTPException) as exc_info:
        replace._resolve_dynamic_region_actual_recipe(
            session_data={
                "material_min_layer_count": 5,
                "material_max_layer_count": 7,
                "selected_materials": ["mat-a", "mat-b"],
                "material_backing_material_index": 1,
                "recipe_overrides": [],
            },
            cache={"material_dynamic_layer_info": {"colors": []}},
            region_id="region-1",
            print_recipe_top_to_bottom=[2, 1, 0, 1, 1, 1, 1],
        )

    assert exc_info.value.status_code == 409


def test_automatic_sync_reuses_seen_target_merges_unseen_and_reweights_benefit() -> None:
    from api.routers.converter import replace

    seen_entry = {
        "target_srgb": [10, 20, 30],
        "matched_srgb": [11, 22, 33],
        "actual_layer_count": 5,
        "padding_layer_count": 2,
        "actual_recipe_top_to_bottom": [0, 2, 3, 4, 0],
        "print_recipe_top_to_bottom": [0, 2, 3, 4, 0, 1, 1],
        "layer_cap_options": [
            {"max_effective_layer_count": 5, "delta_e00": 1.0},
            {"max_effective_layer_count": 6, "delta_e00": 0.8},
            {"max_effective_layer_count": 7, "delta_e00": 0.7},
        ],
    }
    unseen_entry = {
        "target_srgb": [40, 50, 60],
        "matched_srgb": [44, 55, 66],
        "actual_layer_count": 6,
        "padding_layer_count": 1,
        "actual_recipe_top_to_bottom": [3, 2, 1, 0, 2, 3],
        "print_recipe_top_to_bottom": [3, 2, 1, 0, 2, 3, 1],
        "layer_cap_options": [
            {"max_effective_layer_count": 5, "delta_e00": 2.0},
            {"max_effective_layer_count": 6, "delta_e00": 1.5},
            {"max_effective_layer_count": 7, "delta_e00": 1.0},
        ],
    }
    session_data = {
        "material_source": "material_archive",
        "selected_materials": ["mat-a", "mat-b"],
        "material_backing_material_index": 1,
        "material_layer_height_mm": 0.08,
        "material_dynamic_layer_count_enabled": True,
        "material_min_layer_count": 5,
        "material_max_layer_count": 7,
        "material_delta_e00_tolerance": 0.4,
    }
    cache = {
        "material_matrix": np.zeros((1, 2, 7), dtype=np.int16),
        "mask_solid": np.ones((1, 2), dtype=bool),
        "quantized_image": np.asarray(
            [[[10, 20, 30], [40, 50, 60]]],
            dtype=np.uint8,
        ),
        "material_dynamic_layer_info": {
            "enabled": True,
            "min_layer_count": 5,
            "max_layer_count": 7,
            "delta_e00_tolerance": 0.4,
            "engine": "numba",
            "colors": [seen_entry],
            "benefit_curve": [],
        },
        "material_solver_info": {"dynamic_engine": "numba"},
    }
    updated_rgb = np.asarray(
        [[[10, 20, 30], [40, 50, 60]]],
        dtype=np.uint8,
    )
    diff_mask = np.ones((1, 2), dtype=bool)
    unseen_info = {
        "enabled": True,
        "min_layer_count": 5,
        "max_layer_count": 7,
        "delta_e00_tolerance": 0.4,
        "engine": "numba",
        "colors": [unseen_entry],
        "benefit_curve": [],
    }

    with (
        patch.object(replace, "load_multiple_materials", return_value=[object(), object()]),
        patch.object(
            replace,
            "_solve_dynamic_material_targets",
            return_value=(
                np.asarray([[44, 55, 66]], dtype=np.uint8),
                np.asarray(
                    [unseen_entry["print_recipe_top_to_bottom"]],
                    dtype=np.int32,
                ),
                np.asarray([1.0]),
                unseen_info,
                {"dynamic_engine": "numba"},
            ),
        ) as exact_solve,
    ):
        replace._sync_material_archive_matrix_for_diff(
            session_data,
            cache,
            diff_mask,
            updated_rgb,
        )

    solved_targets = exact_solve.call_args.kwargs["unique_colors"]
    np.testing.assert_array_equal(
        solved_targets,
        np.asarray([[40, 50, 60]], dtype=np.uint8),
    )
    assert [
        entry["target_srgb"]
        for entry in cache["material_dynamic_layer_info"]["colors"]
    ] == [[10, 20, 30], [40, 50, 60]]
    curve = cache["material_dynamic_layer_info"]["benefit_curve"]
    assert [point["weighted_mean_delta_e00"] for point in curve] == [
        1.5,
        1.15,
        0.85,
    ]
    assert [point["marginal_delta_e00_reduction"] for point in curve] == [
        0.0,
        0.35,
        0.3,
    ]


def test_api_benefit_weights_use_target_map_when_matched_colors_collide() -> None:
    from api.routers.converter import replace

    target_a = [10, 20, 30]
    target_b = [40, 50, 60]
    matched = [9, 9, 9]

    def entry(target, delta, recipe):
        return {
            "target_srgb": target,
            "matched_srgb": matched,
            "actual_layer_count": 5,
            "padding_layer_count": 2,
            "actual_recipe_top_to_bottom": recipe[:5],
            "print_recipe_top_to_bottom": recipe,
            "layer_cap_options": [
                {"max_effective_layer_count": cap, "delta_e00": delta}
                for cap in (5, 6, 7)
            ],
        }

    entries = [
        entry(target_a, 1.0, [0, 1, 0, 1, 0, 1, 1]),
        entry(target_b, 3.0, [1, 0, 1, 0, 1, 1, 1]),
    ]
    target_map = np.asarray(
        [[target_a, target_b, target_b, target_b]],
        dtype=np.uint8,
    )
    cache = {
        "material_matrix": np.zeros((1, 4, 7), dtype=np.int16),
        "mask_solid": np.ones((1, 4), dtype=bool),
        "quantized_image": target_map.copy(),
        "material_dynamic_layer_info": {
            "enabled": True,
            "min_layer_count": 5,
            "max_layer_count": 7,
            "delta_e00_tolerance": 0.5,
            "colors": entries,
            "benefit_curve": [],
        },
    }
    session_data = {
        "selected_materials": ["mat-a", "mat-b"],
        "material_backing_material_index": 1,
        "material_dynamic_layer_count_enabled": True,
        "material_min_layer_count": 5,
        "material_max_layer_count": 7,
        "material_delta_e00_tolerance": 0.5,
        "material_layer_height_mm": 0.08,
    }
    updated_rgb = target_map.copy()

    with patch.object(
        replace,
        "load_multiple_materials",
        return_value=[object(), object()],
    ), patch.object(
        replace,
        "_solve_dynamic_material_targets",
        side_effect=AssertionError("both exact targets should be reused"),
    ):
        replace._sync_material_archive_matrix_for_diff(
            session_data,
            cache,
            np.ones((1, 4), dtype=bool),
            updated_rgb,
        )

    curve = cache["material_dynamic_layer_info"]["benefit_curve"]
    assert curve[0]["weighted_mean_delta_e00"] == 2.5
    np.testing.assert_array_equal(cache["quantized_image"], target_map)


def test_dynamic_exact_failure_rolls_back_rgb_matrix_and_metadata() -> None:
    from api.routers.converter import replace

    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    client = TestClient(app)

    session_id = store.create()
    matched = np.full((2, 2, 3), [10, 20, 30], dtype=np.uint8)
    matrix = np.zeros((2, 2, 7), dtype=np.int16)
    dynamic_info = {
        "enabled": True,
        "min_layer_count": 5,
        "max_layer_count": 7,
        "delta_e00_tolerance": 0.5,
        "colors": [],
        "benefit_curve": [],
    }
    solver_info = {"path": "dynamic_exact", "dynamic_engine": "numba"}
    store.put(
        session_id,
        "preview_cache",
        {
            "matched_rgb": matched.copy(),
            "material_matrix": matrix.copy(),
            "quantized_image": matched.copy(),
            "mask_solid": np.ones((2, 2), dtype=bool),
            "preview_rgba": np.dstack(
                [matched.copy(), np.full((2, 2), 255, dtype=np.uint8)]
            ),
            "color_layers": 7,
            "layer_height_mm": 0.08,
            "material_dynamic_layer_info": dynamic_info,
            "material_solver_info": solver_info,
        },
    )
    for key, value in {
        "material_source": "material_archive",
        "selected_materials": ["mat-a", "mat-b"],
        "material_backing_material_index": 1,
        "material_dynamic_layer_count_enabled": True,
        "material_min_layer_count": 5,
        "material_max_layer_count": 7,
        "material_delta_e00_tolerance": 0.5,
        "material_layer_height_mm": 0.08,
        "replacement_regions": [],
        "replacement_history": [],
    }.items():
        store.put(session_id, key, value)

    failure = DynamicMaterialCandidateError(
        "no exact candidate",
        target_srgb=(40, 50, 60),
        layer_count=7,
        phase="exact_search",
    )
    with patch.object(
        replace,
        "load_multiple_materials",
        return_value=[object(), object()],
    ), patch.object(
        replace,
        "_solve_dynamic_material_targets",
        side_effect=failure,
    ):
        response = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": session_id,
                "selected_color": "#0a141e",
                "replacement_color": "#28323c",
            },
        )

    assert response.status_code == 409, response.text
    rolled_back = store.get(session_id)["preview_cache"]
    np.testing.assert_array_equal(rolled_back["matched_rgb"], matched)
    np.testing.assert_array_equal(rolled_back["material_matrix"], matrix)
    assert rolled_back["material_dynamic_layer_info"] == dynamic_info
    assert rolled_back["material_solver_info"] == solver_info
    assert store.get(session_id)["replacement_regions"] == []


def test_dynamic_exact_failure_keeps_artifact_cache_revisions_and_data(
    tmp_path,
) -> None:
    from api.routers.converter import replace

    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    client = TestClient(app)

    session_id = store.create()
    matched = np.full((2, 2, 3), [10, 20, 30], dtype=np.uint8)
    matrix = np.zeros((2, 2, 7), dtype=np.int16)
    dynamic_info = {
        "enabled": True,
        "min_layer_count": 5,
        "max_layer_count": 7,
        "delta_e00_tolerance": 0.5,
        "colors": [],
        "benefit_curve": [],
    }
    solver_info = {"path": "dynamic_exact", "dynamic_engine": "numba"}
    cache_ref = externalize_preview_cache(
        session_id,
        store,
        {
            "matched_rgb": matched.copy(),
            "material_matrix": matrix.copy(),
            "quantized_image": matched.copy(),
            "mask_solid": np.ones((2, 2), dtype=bool),
            "preview_rgba": np.dstack(
                [matched.copy(), np.full((2, 2), 255, dtype=np.uint8)]
            ),
            "color_layers": 7,
            "layer_height_mm": 0.08,
            "material_dynamic_layer_info": dynamic_info,
            "material_solver_info": solver_info,
        },
        root_dir=tmp_path,
    )
    store.put(session_id, "preview_cache", cache_ref)
    initial_revisions = {
        name: field["revision"] for name, field in cache_ref["fields"].items()
    }
    for key, value in {
        "material_source": "material_archive",
        "selected_materials": ["mat-a", "mat-b"],
        "material_backing_material_index": 1,
        "material_dynamic_layer_count_enabled": True,
        "material_min_layer_count": 5,
        "material_max_layer_count": 7,
        "material_delta_e00_tolerance": 0.5,
        "material_layer_height_mm": 0.08,
        "replacement_regions": [],
        "replacement_history": [],
    }.items():
        store.put(session_id, key, value)

    failure = DynamicMaterialCandidateError(
        "no exact candidate",
        target_srgb=(40, 50, 60),
        layer_count=7,
        phase="exact_search",
    )
    with patch.object(
        replace,
        "load_multiple_materials",
        return_value=[object(), object()],
    ), patch.object(
        replace,
        "_solve_dynamic_material_targets",
        side_effect=failure,
    ):
        response = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": session_id,
                "selected_color": "#0a141e",
                "replacement_color": "#28323c",
            },
        )

    assert response.status_code == 409, response.text
    persisted_ref = store.get(session_id)["preview_cache"]
    assert is_preview_cache_artifact_ref(persisted_ref)
    assert {
        name: field["revision"]
        for name, field in persisted_ref["fields"].items()
    } == initial_revisions
    hydrated = hydrate_preview_cache(
        persisted_ref,
        fields={"matched_rgb", "material_matrix", "quantized_image"},
    )
    np.testing.assert_array_equal(hydrated["matched_rgb"], matched)
    np.testing.assert_array_equal(hydrated["material_matrix"], matrix)
    np.testing.assert_array_equal(hydrated["quantized_image"], matched)
    assert hydrated["material_dynamic_layer_info"] == dynamic_info
    assert hydrated["material_solver_info"] == solver_info
