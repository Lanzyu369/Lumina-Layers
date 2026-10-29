"""Integration tests for converter replace endpoint log canaries."""

from __future__ import annotations

from contextlib import contextmanager
import io
import logging
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app
from api.dependencies import get_file_registry, get_session_store
from api.editor_commit import begin_editor_commit, publish_editor_commit
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import (
    PreviewCacheRevisionConflict,
    externalize_preview_cache,
    hydrate_preview_cache,
    is_preview_cache_artifact_ref,
)
from api.routers.converter import replace as replace_router
from api.session_store import SessionStore
from api.schemas.converter import EditorCommitStatusResponse

client: TestClient = TestClient(app)

_REPLACE_CACHE_CONFLICT_DETAIL = (
    "Preview cache changed while replacement tools were running. "
    "Re-run preview and try again."
)


@pytest.fixture(autouse=True)
def _isolate_dependency_overrides():
    """Isolate converter replace tests from global dependency overrides."""
    test_store = SessionStore()
    test_registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: test_store
    app.dependency_overrides[get_file_registry] = lambda: test_registry
    try:
        yield {"store": test_store, "registry": test_registry}
    finally:
        app.dependency_overrides.pop(get_session_store, None)
        app.dependency_overrides.pop(get_file_registry, None)


def _seed_preview_session(store: SessionStore) -> str:
    """Create a small valid preview cache for replace endpoint tests."""
    session_id = store.create()
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    matched_rgb[:2, :, :] = [255, 255, 255]
    matched_rgb[2:, :, :] = [255, 0, 0]
    mask_solid = np.ones((4, 4), dtype=bool)
    store.put(
        session_id,
        "preview_cache",
        {
            "matched_rgb": matched_rgb.copy(),
            "quantized_image": matched_rgb.copy(),
            "mask_solid": mask_solid,
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "color_palette": [],
        },
    )
    store.put(session_id, "original_matched_rgb", matched_rgb.copy())
    store.put(session_id, "material_source", "lut")
    return session_id


def test_selection_history_uses_fresh_revisions_for_clear_and_new_click(
    _isolate_dependency_overrides,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.selection_state import get_selection_mask

    store = _isolate_dependency_overrides["store"]
    session_id = _seed_preview_session(store)
    schedule_glb = []
    monkeypatch.setattr(
        replace_router, "_schedule_glb_build_best_effort",
        lambda *args, **kwargs: schedule_glb.append(True),
    )
    document = client.get(f"/api/convert/selection/{session_id}").json()
    revisions = [document["selection_revision"]]

    def mutate(operation: str, **fields: object) -> dict:
        nonlocal document
        response = client.post("/api/convert/selection/mutate", json={
            "session_id": session_id,
            "operation": operation,
            "base_selection_revision": document["selection_revision"],
            "content_revision": document["content_revision"],
            **fields,
        })
        assert response.status_code == 200, response.text
        document = response.json()
        revisions.append(document["selection_revision"])
        return document

    def history(action: str) -> dict:
        nonlocal document
        response = client.post("/api/convert/replacement-history", json={
            "session_id": session_id, "action": action,
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["entry_kind"] == "selection"
        assert body["editor_content_revision"] == 0
        document = body["selection"]
        assert body["can_undo"] == document["can_undo"]
        assert body["can_redo"] == document["can_redo"]
        revisions.append(document["selection_revision"])
        return document

    assert mutate("point-toggle", x=0, y=0)["selected_pixel_count"] == 8
    stale_revision = document["selection_revision"]
    assert mutate("point-toggle", x=0, y=3)["selected_pixel_count"] == 16
    assert history("undo")["selected_pixel_count"] == 8
    assert history("redo")["selected_pixel_count"] == 16
    assert mutate("clear")["selected_pixel_count"] == 0
    assert history("undo")["selected_pixel_count"] == 16
    assert mutate("point-toggle", x=0, y=3)["selected_pixel_count"] == 8
    assert document["can_redo"] is False
    assert mutate("point-toggle", x=0, y=3)["selected_pixel_count"] == 16
    assert all(later > earlier for earlier, later in zip(revisions, revisions[1:]))
    assert not schedule_glb
    session = store.get(session_id)
    assert np.all(get_selection_mask(session, (4, 4)))

    stale = client.post("/api/convert/selection/mutate", json={
        "session_id": session_id, "operation": "clear",
        "base_selection_revision": stale_revision,
        "content_revision": document["content_revision"],
    })
    assert stale.status_code == 409
    assert np.all(get_selection_mask(session, (4, 4)))


def test_unchanged_selection_preserves_redo_history(
    _isolate_dependency_overrides,
) -> None:
    store = _isolate_dependency_overrides["store"]
    session_id = _seed_preview_session(store)
    document = client.get(f"/api/convert/selection/{session_id}").json()

    def mutate(operation: str, **fields: object) -> dict:
        response = client.post("/api/convert/selection/mutate", json={
            "session_id": session_id, "operation": operation,
            "base_selection_revision": document["selection_revision"],
            "content_revision": document["content_revision"], **fields,
        })
        assert response.status_code == 200, response.text
        return response.json()

    def undo() -> dict:
        response = client.post("/api/convert/replacement-history", json={
            "session_id": session_id, "action": "undo",
        })
        assert response.status_code == 200, response.text
        return response.json()["selection"]

    document = mutate("point-toggle", x=0, y=0)
    document = mutate("point-toggle", x=0, y=3)
    document = undo()
    session = store.get(session_id)
    unchanged = mutate("brush-add", brush_points=[{"x": 0, "y": 0}], brush_radius=0.5)
    assert unchanged["selection_revision"] == document["selection_revision"]
    assert unchanged["selected_pixel_count"] == 8
    assert unchanged["can_redo"] is True
    assert len(session["replacement_undo_stack"]) == 1
    assert len(session["replacement_redo_stack"]) == 1

    document = undo()
    unchanged = mutate("clear")
    assert unchanged["selection_revision"] == document["selection_revision"]
    assert unchanged["selected_pixel_count"] == 0
    assert unchanged["can_undo"] is False
    assert unchanged["can_redo"] is True
    assert session["replacement_undo_stack"] == []
    assert len(session["replacement_redo_stack"]) == 2


def test_selection_and_replacement_history_round_trips_every_step(
    _isolate_dependency_overrides,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.selection_state import get_selection_mask, selection_region_id

    store = _isolate_dependency_overrides["store"]
    session_id = _seed_preview_session(store)
    monkeypatch.setattr(
        replace_router, "_schedule_or_run_overridden_glb_build", lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        replace_router, "_schedule_glb_build_best_effort", lambda *args, **kwargs: None,
    )
    document = client.get(f"/api/convert/selection/{session_id}").json()
    session = store.get(session_id)

    def capture() -> tuple[np.ndarray, np.ndarray]:
        cache = session["preview_cache"]
        if is_preview_cache_artifact_ref(cache):
            cache = hydrate_preview_cache(cache)
        return cache["matched_rgb"].copy(), get_selection_mask(session, (4, 4))

    def mutate(operation: str, **fields: object) -> None:
        nonlocal document
        response = client.post("/api/convert/selection/mutate", json={
            "session_id": session_id, "operation": operation,
            "base_selection_revision": document["selection_revision"],
            "content_revision": document["content_revision"], **fields,
        })
        assert response.status_code == 200, response.text
        document = response.json()

    states = [capture()]
    mutate("point-toggle", x=0, y=0)
    states.append(capture())
    replaced = client.post("/api/convert/region-replace", json={
        "session_id": session_id, "replacement_color": "#00ff00",
        "selection_revision": document["selection_revision"],
    })
    assert replaced.status_code == 200, replaced.text
    document = replaced.json()["selection"]
    states.append(capture())
    mutate("same-color-toggle", color_hex="#ff0000")
    states.append(capture())
    mutate("clear")
    states.append(capture())

    assert [item["kind"] for item in session["replacement_undo_stack"]] == [
        "selection", "content", "selection", "selection",
    ]
    previous_revision = document["selection_revision"]
    previous_generation = document["content_revision"]
    previous_content = document["editor_content_revision"]
    for action, indices in (("undo", range(3, -1, -1)), ("redo", range(1, 5))):
        for index in indices:
            response = client.post("/api/convert/replacement-history", json={
                "session_id": session_id, "action": action,
            })
            assert response.status_code == 200, response.text
            body = response.json()
            document = body["selection"]
            actual_rgb, actual_mask = capture()
            expected_rgb, expected_mask = states[index]
            assert np.array_equal(actual_rgb, expected_rgb)
            assert np.array_equal(actual_mask, expected_mask)
            assert document["selected_pixel_count"] == int(expected_mask.sum())
            assert document["selection_revision"] > previous_revision
            assert document["content_revision"] >= previous_generation
            expected_content = previous_content + (body["entry_kind"] == "content")
            assert document["editor_content_revision"] == expected_content
            assert body["editor_content_revision"] == expected_content
            assert body["can_undo"] == document["can_undo"] == (index > 0)
            assert body["can_redo"] == document["can_redo"] == (index < 4)
            if np.any(expected_mask):
                region_id = selection_region_id(document["selection_revision"])
                assert document["region_ids"] == [region_id]
                assert np.array_equal(session["selected_region_masks"][region_id], expected_mask)
            else:
                assert document["region_ids"] == []
            previous_revision = document["selection_revision"]
            previous_generation = document["content_revision"]
            previous_content = document["editor_content_revision"]

    # Returning through content history must leave the next ordinary gesture
    # usable with the versions the server just returned.
    for _ in range(3):
        response = client.post("/api/convert/replacement-history", json={
            "session_id": session_id, "action": "undo",
        })
        assert response.status_code == 200, response.text
        document = response.json()["selection"]
    assert response.json()["entry_kind"] == "content"
    mutate("point-toggle", x=0, y=3)
    assert document["selected_pixel_count"] == 16
    assert document["can_redo"] is False
    mutate("clear")
    assert document["selected_pixel_count"] == 0


@pytest.mark.parametrize("remove_fields", [
    {"operation": "point-remove", "x": 0, "y": 0},
    {"operation": "same-color-remove", "color_hex": "#ffffff"},
    {"operation": "same-color-remove", "x": 0, "y": 0},
])
def test_explicit_deselection_is_idempotent_and_preserves_redo(
    _isolate_dependency_overrides,
    remove_fields: dict,
) -> None:
    store = _isolate_dependency_overrides["store"]
    session_id = _seed_preview_session(store)
    document = client.get(f"/api/convert/selection/{session_id}").json()

    def mutate(fields: dict) -> dict:
        response = client.post("/api/convert/selection/mutate", json={
            "session_id": session_id,
            "base_selection_revision": document["selection_revision"],
            "content_revision": document["content_revision"], **fields,
        })
        assert response.status_code == 200, response.text
        return response.json()

    document = mutate({"operation": "colors-set", "color_hexes": ["#ffffff", "#ff0000"]})
    assert document["selected_pixel_count"] == 16
    document = mutate(remove_fields)
    assert document["selected_pixel_count"] == 8
    assert mutate(remove_fields)["selection_revision"] == document["selection_revision"]
    session = store.get(session_id)
    assert len(session["replacement_undo_stack"]) == 2
    for expected_pixels in (16, 0):
        response = client.post("/api/convert/replacement-history", json={
            "session_id": session_id, "action": "undo",
        })
        assert response.status_code == 200, response.text
        document = response.json()["selection"]
        assert document["selected_pixel_count"] == expected_pixels
    unchanged = mutate(remove_fields)
    assert unchanged["selection_revision"] == document["selection_revision"]
    assert unchanged["selected_pixel_count"] == 0
    assert unchanged["can_redo"] is True
    assert len(session["replacement_redo_stack"]) == 2
    assert session["replacement_undo_stack"] == []


def test_gradient_and_color_set_selection_use_exact_masks_and_one_history_step(
    _isolate_dependency_overrides,
) -> None:
    from api.selection_state import get_selection_mask

    store = _isolate_dependency_overrides["store"]
    session_id = _seed_preview_session(store)
    session = store.get(session_id)
    session["preview_cache"]["mask_solid"][0, 0] = False
    region_ids = np.zeros((4, 4), dtype=np.uint32)
    multiplier = replace_router.REGION_ID_ENCODING_MULTIPLIER
    region_ids[:2, 0] = multiplier + 1
    region_ids[:2, 1] = multiplier + 2
    region_ids[2:, 0] = 2 * multiplier + 1
    store.put(session_id, "gradient_region_id_map", region_ids)
    document = client.get(f"/api/convert/selection/{session_id}").json()

    def mutate(fields: dict) -> dict:
        response = client.post("/api/convert/selection/mutate", json={
            "session_id": session_id,
            "base_selection_revision": document["selection_revision"],
            "content_revision": document["content_revision"], **fields,
        })
        assert response.status_code == 200, response.text
        return response.json()

    document = mutate({
        "operation": "gradient-region-set", "gradient_group_index": 1,
        "gradient_region_index": 1,
    })
    assert document["selected_pixel_count"] == 1
    mask = get_selection_mask(session, (4, 4))
    assert mask[1, 0] and not mask[:, 1:].any()
    assert len(session["replacement_undo_stack"]) == 1
    missing_region = client.post("/api/convert/selection/mutate", json={
        "session_id": session_id, "operation": "gradient-region-set",
        "base_selection_revision": document["selection_revision"],
        "content_revision": document["content_revision"],
        "gradient_group_index": 1, "gradient_region_index": 99,
    })
    assert missing_region.status_code == 404
    assert np.array_equal(get_selection_mask(session, (4, 4)), mask)
    document = mutate({"operation": "gradient-region-set", "gradient_group_index": 1})
    assert document["selected_pixel_count"] == 3
    assert len(session["replacement_undo_stack"]) == 2
    response = client.post("/api/convert/replacement-history", json={
        "session_id": session_id, "action": "undo",
    })
    assert response.status_code == 200, response.text
    document = response.json()["selection"]
    assert document["selected_pixel_count"] == 1
    document = mutate({"operation": "colors-set", "color_hexes": ["FFFFFF", "#ffffff"]})
    assert document["selected_pixel_count"] == 7
    assert not get_selection_mask(session, (4, 4))[2:, :].any()
    assert len(session["replacement_undo_stack"]) == 2
    assert document["can_redo"] is False
    document = mutate({"operation": "colors-set", "color_hexes": []})
    assert document["selected_pixel_count"] == 0
    assert len(session["replacement_undo_stack"]) == 3
    response = client.post("/api/convert/replacement-history", json={
        "session_id": session_id, "action": "undo",
    })
    assert response.status_code == 200, response.text
    assert response.json()["selection"]["selected_pixel_count"] == 7


def test_brush_strokes_do_not_select_the_space_between_pen_lifts(
    _isolate_dependency_overrides,
) -> None:
    from api.selection_state import get_selection_mask

    store = _isolate_dependency_overrides["store"]
    session_id = _seed_preview_session(store)
    rgb = np.zeros((3, 9, 3), dtype=np.uint8)
    rgb[:, :3, 0] = 255
    rgb[:, 3:6, 1] = 255
    rgb[:, 6:, 2] = 255
    session = store.get(session_id)
    cache = session["preview_cache"]
    cache.update({
        "matched_rgb": rgb, "quantized_image": rgb.copy(),
        "mask_solid": np.ones((3, 9), dtype=bool), "target_w": 9, "target_h": 3,
    })
    document = client.get(f"/api/convert/selection/{session_id}").json()
    response = client.post("/api/convert/selection/mutate", json={
        "session_id": session_id, "operation": "brush-add",
        "base_selection_revision": document["selection_revision"],
        "content_revision": document["content_revision"], "brush_radius": 0.5,
        "brush_strokes": [[{"x": 0, "y": 1}], [{"x": 8, "y": 1}]],
    })
    assert response.status_code == 200, response.text
    assert response.json()["brush_hit_component_count"] == 2
    mask = get_selection_mask(session, (3, 9))
    assert mask[:, :3].all() and mask[:, 6:].all()
    assert not mask[:, 3:6].any()
    assert len(session["replacement_undo_stack"]) == 1
    for action, pixels in (("undo", 0), ("redo", 18)):
        response = client.post("/api/convert/replacement-history", json={
            "session_id": session_id, "action": action,
        })
        assert response.status_code == 200, response.text
        assert response.json()["selection"]["selected_pixel_count"] == pixels


@pytest.mark.parametrize("fields, status", [
    ({"operation": "point-remove"}, 400),
    ({"operation": "same-color-remove"}, 400),
    ({"operation": "colors-set"}, 400),
    ({"operation": "colors-set", "color_hexes": ["invalid"]}, 400),
    ({"operation": "gradient-region-set"}, 400),
    ({"operation": "gradient-region-set", "gradient_region_index": 1}, 400),
    ({"operation": "gradient-region-set", "gradient_group_index": 0}, 422),
    ({"operation": "gradient-region-set", "gradient_group_index": 1}, 409),
    ({"operation": "brush-add", "brush_radius": 1, "brush_strokes": []}, 400),
    ({"operation": "brush-add", "brush_radius": 1, "brush_strokes": [[]]}, 400),
])
def test_selection_set_operations_validate_missing_or_invalid_inputs(
    _isolate_dependency_overrides,
    fields: dict,
    status: int,
) -> None:
    store = _isolate_dependency_overrides["store"]
    session_id = _seed_preview_session(store)
    document = client.get(f"/api/convert/selection/{session_id}").json()
    response = client.post("/api/convert/selection/mutate", json={
        "session_id": session_id,
        "base_selection_revision": document["selection_revision"],
        "content_revision": document["content_revision"], **fields,
    })
    assert response.status_code == status, response.text
    after = client.get(f"/api/convert/selection/{session_id}").json()
    assert after["selection_revision"] == document["selection_revision"]
    assert after["selected_pixel_count"] == 0
    assert not after["can_undo"] and not after["can_redo"]


def _seed_transparent_region_session(store: SessionStore) -> str:
    """Create a preview cache whose transparent background keeps stale RGB."""
    session_id = store.create()
    matched_rgb = np.full((4, 4, 3), [48, 144, 184], dtype=np.uint8)
    matched_rgb[1:3, 1:3, :] = [255, 0, 0]
    mask_solid = np.zeros((4, 4), dtype=bool)
    mask_solid[1:3, 1:3] = True
    quantized_image = matched_rgb.copy()
    store.put(
        session_id,
        "preview_cache",
        {
            "matched_rgb": matched_rgb.copy(),
            "quantized_image": quantized_image,
            "mask_solid": mask_solid,
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "color_palette": [],
        },
    )
    store.put(session_id, "material_source", "lut")
    return session_id


def _seed_artifact_preview_session(store: SessionStore, tmp_path) -> str:
    """Create a preview-like artifact-backed session without top-level originals."""
    session_id = store.create()
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    matched_rgb[:2, :, :] = [255, 255, 255]
    matched_rgb[2:, :, :] = [255, 0, 0]
    mask_solid = np.ones((4, 4), dtype=bool)
    cache = {
        "matched_rgb": matched_rgb.copy(),
        "original_matched_rgb": matched_rgb.copy(),
        "quantized_image": matched_rgb.copy(),
        "mask_solid": mask_solid,
        "target_w": 4,
        "target_h": 4,
        "target_width_mm": 40.0,
        "color_palette": [],
    }
    ref = externalize_preview_cache(
        session_id,
        store,
        cache,
        root_dir=tmp_path,
    )
    store.put(session_id, "preview_cache", ref)
    store.put(session_id, "replacement_regions", [])
    store.put(session_id, "replacement_history", [])
    store.put(session_id, "material_source", "lut")
    return session_id


def _dynamic_layer_info_fixture() -> dict:
    """Return a small valid dynamic-material cache payload for receipt tests."""
    option = {
        "max_effective_layer_count": 5,
        "actual_layer_count": 5,
        "matched_srgb": [1, 2, 3],
        "actual_recipe_top_to_bottom": [0, 0, 0, 0, 0],
        "print_recipe_top_to_bottom": [0, 0, 0, 0, 0],
        "delta_e00": 0.0,
    }
    recipe = {
        "target_srgb": [1, 2, 3],
        "matched_srgb": [1, 2, 3],
        "actual_layer_count": 5,
        "padding_layer_count": 0,
        "actual_recipe_top_to_bottom": [0, 0, 0, 0, 0],
        "print_recipe_top_to_bottom": [0, 0, 0, 0, 0],
        "selected_delta_e00": 0.0,
        "best_range_delta_e00": 0.0,
        "fixed_max_delta_e00": 0.0,
        "delta_e00_sacrifice": 0.0,
        "layer_cap_options": [option],
    }
    return {
        "enabled": True,
        "colors": [recipe],
        "benefit_curve": [
            {
                "max_effective_layer_count": 5,
                "weighted_mean_delta_e00": 0.0,
                "marginal_delta_e00_reduction": 0.0,
            }
        ],
        "benefit_curve_scope": "automatic_pixels",
        "benefit_curve_pixel_count": 4,
    }


@pytest.mark.parametrize("item_count", [127, 128, 129])
def test_editor_commit_result_lists_round_trip_through_get_endpoint(
    _isolate_dependency_overrides,
    item_count: int,
) -> None:
    """Published business lists keep all entries through the response model."""

    store: SessionStore = _isolate_dependency_overrides["store"]
    session_id = store.create()
    session_data = store.get(session_id)
    assert session_data is not None
    operation_id = begin_editor_commit(
        session_id,
        store,
        session_data,
        operation_id=f"receipt-list-{item_count}",
        operation="apply_recipe_override",
    )
    result = {
        "replacement_regions": [
            {
                "quantized_hex": "#000000",
                "matched_hex": "#000000",
                "replacement_hex": f"#{index:06x}",
            }
            for index in range(item_count)
        ],
        "recipe_overrides": [
            {
                "region_id": f"region-{index}",
                "recipe": [0],
                "layer_order": "Top2Bottom",
            }
            for index in range(item_count)
        ],
        "recipe_override_count": item_count,
        "free_color_set": [f"{index:06x}" for index in range(item_count)],
    }
    publish_editor_commit(
        session_id,
        store,
        session_data,
        operation_id=operation_id,
        editor_content_revision=1,
        result=result,
    )

    response = client.get(
        f"/api/convert/editor-commit/{session_id}/{operation_id}"
    )

    assert response.status_code == 200, response.text
    parsed = EditorCommitStatusResponse.model_validate(response.json())
    assert parsed.result is not None
    assert parsed.result.recipe_override_count == item_count
    assert len(parsed.result.recipe_overrides or []) == item_count
    assert (parsed.result.recipe_overrides or [])[-1].region_id == (
        f"region-{item_count - 1}"
    )
    assert len(parsed.result.free_color_set or []) == item_count
    assert (parsed.result.free_color_set or [])[-1] == f"{item_count - 1:06x}"
    assert len(parsed.result.replacement_regions or []) == item_count
    assert (parsed.result.replacement_regions or [])[-1].replacement_hex == (
        f"#{item_count - 1:06x}"
    )


def test_editor_commit_result_reads_dynamic_fields_from_real_transaction_view(
    _isolate_dependency_overrides,
) -> None:
    """Receipt projection accepts the real MutableMapping transaction view."""

    store: SessionStore = _isolate_dependency_overrides["store"]
    session_id = _seed_preview_session(store)
    session_data = store.get(session_id)
    assert session_data is not None
    cache = session_data["preview_cache"]
    cache["material_dynamic_layer_info"] = _dynamic_layer_info_fixture()
    cache["color_layers"] = 10
    cache["layer_height_mm"] = 0.16
    store.put(session_id, "preview_cache", cache)
    store.put(session_id, "color_layers", 5)
    store.put(session_id, "layer_height_mm", 0.08)

    operation_id = begin_editor_commit(
        session_id,
        store,
        session_data,
        operation_id="receipt-dynamic-transaction",
        operation="apply_recipe_override",
    )
    with replace_router._preview_cache_transaction(
        session_id,
        store,
        session_data,
        fields={"matched_rgb"},
    ) as cache_view:
        result = replace_router._editor_commit_result(
            session_data,
            cache=cache_view,
            preview_url="/api/files/receipt-dynamic.png",
        )

    publish_editor_commit(
        session_id,
        store,
        session_data,
        operation_id=operation_id,
        editor_content_revision=1,
        result=result,
    )
    response = client.get(
        f"/api/convert/editor-commit/{session_id}/{operation_id}"
    )

    assert response.status_code == 200, response.text
    body = response.json()["result"]
    assert body["material_dynamic_recipes"]
    assert body["material_layer_benefit_curve"]
    assert body["material_layer_benefit_scope"] == "automatic_pixels"
    assert body["material_layer_benefit_pixel_count"] == 4
    assert body["color_layers"] == 5
    assert body["layer_height_mm"] == 0.08


def _delete_externalized_preview_cache_field(
    store: SessionStore,
    session_id: str,
    field_name: str,
) -> Path:
    cache_ref = store.get(session_id)["preview_cache"]
    field_path = Path(cache_ref["fields"][field_name]["path"])
    assert field_path.exists()
    field_path.unlink()
    assert not field_path.exists()
    return field_path


def _capture_replace_logger(caplog: pytest.LogCaptureFixture) -> logging.Logger:
    target_logger = logging.getLogger("lumina.api.routers.converter.replace")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=target_logger.name)
    return target_logger


def _single_record(caplog: pytest.LogCaptureFixture, event: str) -> logging.LogRecord:
    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == event
    ]
    assert len(records) == 1
    return records[0]


def _assert_actionable_warning(record: logging.LogRecord) -> None:
    from scripts.log_quality_check import _has_actionable_warning_error_field

    assert record.levelno == logging.WARNING
    assert _has_actionable_warning_error_field(record.__dict__) is True


def _force_region_group_one_map(store: SessionStore, session_id: str) -> None:
    session_data = store.get(session_id)
    assert session_data is not None
    cache = session_data["preview_cache"]
    height, width = np.asarray(cache["matched_rgb"]).shape[:2]
    region_id_map = np.zeros((height, width), dtype=np.uint32)
    region_id_map[4:12, 4:12] = np.uint32(
        int(replace_router.REGION_ID_ENCODING_MULTIPLIER) + 1
    )
    store.put(session_id, "gradient_region_id_map", region_id_map)




def _seed_region_requantize_session(store: SessionStore, tmp_path) -> str:
    session_id = store.create()
    height, width = 16, 16
    matched_rgb = np.full((height, width, 3), [10, 20, 30], dtype=np.uint8)
    matched_rgb[:, width // 2 :, :] = [200, 50, 80]
    mask_solid = np.ones((height, width), dtype=bool)
    source_rgb = np.zeros((height, width, 3), dtype=np.uint8)
    source_rgb[:, :, 0] = np.arange(width, dtype=np.uint8)
    source_path = tmp_path / "region-requantize-source.png"
    Image.fromarray(source_rgb).save(source_path)

    region_id_map = np.zeros((height, width), dtype=np.uint32)
    region_id_map[4:12, 4:12] = 1001
    store.put(
        session_id,
        "preview_cache",
        {
            "matched_rgb": matched_rgb,
            "quantized_image": matched_rgb.copy(),
            "mask_solid": mask_solid,
            "target_w": width,
            "target_h": height,
            "target_width_mm": 40.0,
            "color_layers": 10,
            "layer_height_mm": 0.08,
            "material_substrate": "white",
        },
    )
    store.put(session_id, "gradient_region_id_map", region_id_map)
    store.put(session_id, "image_path", str(source_path))
    store.put(session_id, "material_source", "material_archive")
    store.put(session_id, "selected_materials", ["fake/A", "fake/B"])
    store.put(session_id, "material_layer_count", 10)
    store.put(session_id, "material_layer_height_mm", 0.08)
    store.put(session_id, "lut_name", "__material_archive__")
    return session_id


def _seed_recipe_session(store: SessionStore) -> str:
    session_id = store.create()
    matched_rgb = np.full((4, 4, 3), [250, 250, 250], dtype=np.uint8)
    mask_solid = np.ones((4, 4), dtype=bool)
    material_matrix = np.zeros((4, 4, 3), dtype=np.int32)
    material_matrix[:, :, :] = [0, 1, 0]
    region_mask = np.zeros((4, 4), dtype=bool)
    region_mask[:2, :2] = True
    store.put(
        session_id,
        "preview_cache",
        {
            "matched_rgb": matched_rgb.copy(),
            "quantized_image": matched_rgb.copy(),
            "mask_solid": mask_solid,
            "material_matrix": material_matrix,
            "color_layers": 3,
            "layer_height_mm": 0.08,
            "preview_colors": {
                0: [250, 250, 250, 255],
                1: [220, 40, 80, 255],
            },
            "slot_names": ["fake/A", "fake/B"],
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
        },
    )
    store.put(session_id, "material_source", "material_archive")
    store.put(session_id, "selected_materials", ["fake/A", "fake/B"])
    store.put(session_id, "material_layer_count", 3)
    store.put(session_id, "material_layer_height_mm", 0.08)
    store.put(session_id, "lut_name", "__material_archive__")
    store.put(session_id, "selected_region_masks", {"region-1": region_mask})
    store.put(session_id, "selected_region_id", "region-1")
    store.put(session_id, "selected_region_mask", region_mask)
    return session_id


class TestReplaceColorCanary:
    """Successful replace-color requests emit the structured done canary."""

    def test_replace_color_cache_conflict_uses_safe_detail_and_logs_internal_reason(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        raw_detail = "Preview cache field 'matched_rgb' revision changed from 1 to 2"

        @contextmanager
        def _conflicting_transaction(*_args, **_kwargs):
            raise PreviewCacheRevisionConflict(raw_detail)
            yield

        target_logger = _capture_replace_logger(caplog)

        try:
            with patch.object(
                replace_router,
                "_preview_cache_transaction",
                _conflicting_transaction,
            ):
                response = client.post(
                    "/api/convert/replace-color",
                    json={
                        "session_id": session_id,
                        "selected_color": "#ffffff",
                        "replacement_color": "#0000ff",
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 409
        assert response.json()["detail"] == _REPLACE_CACHE_CONFLICT_DETAIL
        assert "matched_rgb" not in response.text
        assert "revision changed" not in response.text
        assert "from 1 to 2" not in response.text

        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_replace_cache_conflict"
        ]
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert records[0].session_id == session_id
        assert records[0].operation == "replace_color"
        assert records[0].status_code == 409
        assert records[0].error_type == "PreviewCacheRevisionConflict"
        assert records[0].error_message == raw_detail

    def test_replace_color_emits_converter_replace_color_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            with patch(
                "api.routers.converter.replace.schedule_glb_build",
                return_value="mock-glb-token",
            ):
                response = client.post(
                    "/api/convert/replace-color",
                    json={
                        "session_id": session_id,
                        "selected_color": "#ffffff",
                        "replacement_color": "#0000ff",
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["preview_url"]
        assert body["replacement_count"] >= 1
        receipt_response = client.get(
            f"/api/convert/editor-commit/{session_id}/{body['operation_id']}"
        )
        assert receipt_response.status_code == 200, receipt_response.text
        receipt_body = receipt_response.json()
        assert receipt_body["status"] == "committed"
        assert receipt_body["result"]["replacement_regions"][0] == {
            "quantized_hex": "#ffffff",
            "matched_hex": "#ffffff",
            "replacement_hex": "#0000ff",
        }

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_replace_color_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.selected_color == "#ffffff"
        assert record.replacement_color == "#0000ff"
        assert record.replacement_count == 1
        assert record.diff_pixel_count == 8

    def test_replace_color_keeps_committed_content_when_glb_scheduler_fails(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A post-commit derived-render failure must not roll back the edit."""

        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)

        with patch(
            "api.routers.converter.replace.schedule_glb_build",
            side_effect=RuntimeError("executor unavailable"),
        ), patch.object(replace_router.log, "warning") as warning_log:
            response = client.post(
                "/api/convert/replace-color",
                json={
                    "session_id": session_id,
                    "selected_color": "#ffffff",
                    "replacement_color": "#0000ff",
                },
            )

        assert response.status_code == 200, response.text
        cache = store.get(session_id)["preview_cache"]
        np.testing.assert_array_equal(
            np.asarray(cache["matched_rgb"])[0, 0],
            [0, 0, 255],
        )
        warning_log.assert_called_once()
        warning_fields = warning_log.call_args.kwargs["extra"]
        assert warning_fields["event"] == "converter_glb_schedule_failed"
        assert warning_fields["content_commit"] == "committed"

    def test_replace_color_post_commit_exception_keeps_in_memory_cache_published(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        """The shared transaction must not restore arrays after cache.commit()."""

        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        lut_path = tmp_path / "post_commit_replace_lut.npz"
        np.savez(
            lut_path,
            rgb=np.asarray([[255, 255, 255], [0, 0, 255]], dtype=np.uint8),
            stacks=np.asarray([[0, 0], [1, 1]], dtype=np.int16),
        )
        store.put(session_id, "lut_path", str(lut_path))
        store.put(session_id, "color_mode", "4-Color (RYBW)")
        store.put(session_id, "color_layers", 2)
        store.put(session_id, "layer_height_mm", 0.08)
        cache = store.get(session_id)["preview_cache"]
        cache["material_matrix"] = np.zeros((4, 4, 2), dtype=np.int16)
        cache["color_layers"] = 2
        cache["layer_height_mm"] = 0.08
        store.put(session_id, "preview_cache", cache)
        old_matrix = cache["material_matrix"].copy()

        real_publish = replace_router.publish_editor_commit

        def raise_after_publish(*args, **kwargs):
            real_publish(*args, **kwargs)
            raise HTTPException(
                status_code=422,
                detail="history convergence failed after publication",
            )

        with patch.object(
            replace_router,
            "publish_editor_commit",
            side_effect=raise_after_publish,
        ):
            response = client.post(
                "/api/convert/replace-color",
                json={
                    "session_id": session_id,
                    "selected_color": "#ffffff",
                    "replacement_color": "#0000ff",
                },
            )

        assert response.status_code == 422, response.text
        session_data = store.get(session_id)
        assert session_data is not None
        published_cache = session_data["preview_cache"]
        np.testing.assert_array_equal(
            np.asarray(published_cache["matched_rgb"])[0, 0],
            [0, 0, 255],
        )
        assert not np.array_equal(
            np.asarray(published_cache["material_matrix"]),
            old_matrix,
        )
        assert session_data["replacement_regions"] == [
            {
                "selected_color": "#ffffff",
                "replacement_color": "#0000ff",
            }
        ]
        assert session_data["editor_content_revision"] > 1
        receipt = next(iter(session_data["editor_commit_receipts"].values()))
        assert receipt["status"] == "committed"

    def test_replace_color_keeps_artifact_preview_cache_externalized(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_artifact_preview_session(store, tmp_path)

        with patch(
            "api.routers.converter.common.hydrate_preview_cache",
            side_effect=AssertionError("replace-color must not fully hydrate artifact cache"),
        ), patch(
            "api.routers.converter.replace.schedule_glb_build",
            return_value="mock-glb-token",
        ):
            response = client.post(
                "/api/convert/replace-color",
                json={
                    "session_id": session_id,
                    "selected_color": "#ffffff",
                    "replacement_color": "#0000ff",
                },
            )

        assert response.status_code == 200, response.text
        stored = store.get(session_id)["preview_cache"]
        assert is_preview_cache_artifact_ref(stored)
        assert "matched_rgb" not in stored["metadata"]
        assert stored["fields"]["matched_rgb"]["revision"] == 2
        hydrated = hydrate_preview_cache(
            stored,
            fields={"matched_rgb", "original_matched_rgb"},
        )
        assert int(np.all(hydrated["matched_rgb"] == [0, 0, 255], axis=-1).sum()) == 8
        assert int(
            np.all(hydrated["original_matched_rgb"] == [255, 255, 255], axis=-1).sum()
        ) == 8

    def test_replace_color_post_commit_exception_keeps_artifact_cache_published(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        """The artifact transaction observes the same published boundary."""

        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_artifact_preview_session(store, tmp_path)
        real_publish = replace_router.publish_editor_commit

        def raise_after_publish(*args, **kwargs):
            real_publish(*args, **kwargs)
            raise HTTPException(
                status_code=422,
                detail="history convergence failed after publication",
            )

        with patch.object(
            replace_router,
            "publish_editor_commit",
            side_effect=raise_after_publish,
        ):
            response = client.post(
                "/api/convert/replace-color",
                json={
                    "session_id": session_id,
                    "selected_color": "#ffffff",
                    "replacement_color": "#0000ff",
                },
            )

        assert response.status_code == 422, response.text
        session_data = store.get(session_id)
        assert session_data is not None
        cache_ref = session_data["preview_cache"]
        assert is_preview_cache_artifact_ref(cache_ref)
        hydrated = hydrate_preview_cache(cache_ref, fields={"matched_rgb"})
        np.testing.assert_array_equal(hydrated["matched_rgb"][0, 0], [0, 0, 255])
        assert session_data["replacement_regions"] == [
            {
                "selected_color": "#ffffff",
                "replacement_color": "#0000ff",
            }
        ]
        assert session_data["editor_content_revision"] > 1


class TestResetReplacementsCanary:
    """Successful reset-replacements requests emit the structured done canary."""

    def test_reset_replacements_emits_converter_reset_replacements_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        store.put(
            session_id,
            "replacement_regions",
            [{"selected_color": "#ffffff", "replacement_color": "#0000ff"}],
        )
        store.put(session_id, "replacement_history", [[{"selected_color": "#ffffff"}]])
        target_logger = _capture_replace_logger(caplog)

        try:
            with patch(
                "api.routers.converter.replace.schedule_glb_build",
                return_value="mock-glb-token",
            ):
                response = client.post(
                    "/api/convert/reset-replacements",
                    json={"session_id": session_id},
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["preview_url"]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_reset_replacements_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.regions_cleared == 1
        assert record.history_truncated == 0

    def test_reset_replacements_restores_artifact_original_snapshot(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_artifact_preview_session(store, tmp_path)

        with patch(
            "api.routers.converter.common.hydrate_preview_cache",
            side_effect=AssertionError("reset-replacements must not fully hydrate artifact cache"),
        ), patch(
            "api.routers.converter.replace.schedule_glb_build",
            return_value="mock-glb-token",
        ):
            replace_response = client.post(
                "/api/convert/replace-color",
                json={
                    "session_id": session_id,
                    "selected_color": "#ffffff",
                    "replacement_color": "#0000ff",
                },
            )
            reset_response = client.post(
                "/api/convert/reset-replacements",
                json={"session_id": session_id},
            )

        assert replace_response.status_code == 200, replace_response.text
        assert reset_response.status_code == 200, reset_response.text
        stored = store.get(session_id)["preview_cache"]
        assert is_preview_cache_artifact_ref(stored)
        assert "original_matched_rgb" not in store.get(session_id)
        hydrated = hydrate_preview_cache(
            stored,
            fields={"matched_rgb", "original_matched_rgb"},
        )
        np.testing.assert_array_equal(
            hydrated["matched_rgb"],
            hydrated["original_matched_rgb"],
        )


class TestSourceColorPickCanary:
    """Successful source-color-pick requests emit the structured done canary."""

    def test_stale_artifact_cache_returns_repreview_error(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_artifact_preview_session(store, tmp_path)
        stale_path = _delete_externalized_preview_cache_field(
            store,
            session_id,
            "matched_rgb",
        )

        response = client.post(
            "/api/convert/source-color-pick",
            json={"session_id": session_id, "x": 0, "y": 0},
        )

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "Re-run preview" in detail
        assert str(stale_path) not in detail

    def test_source_color_pick_emits_converter_source_color_pick_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/source-color-pick",
                json={"session_id": session_id, "x": 0, "y": 0},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source_matched_hex"] == "#ffffff"
        assert body["quantized_hex"] == "#ffffff"

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_source_color_pick_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.picked_color == "#ffffff"
        assert record.pick_x == 0
        assert record.pick_y == 0


class TestColorHighlightCanary:
    """Successful color-highlight requests emit the structured done canary."""

    def test_color_highlight_group_fallback_warning_has_actionable_fields(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_region_requantize_session(store, tmp_path)
        _force_region_group_one_map(store, session_id)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/color-highlight",
                json={
                    "session_id": session_id,
                    "color_hexes": ["#0a141e"],
                    "gradient_group_index": 1,
                    "gradient_region_index": 2,
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        record = _single_record(
            caplog,
            "color_highlight_region_unmapped_group_fallback",
        )
        _assert_actionable_warning(record)

    def test_color_highlight_emits_converter_color_highlight_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/color-highlight",
                json={"session_id": session_id, "color_hexes": ["#ffffff"]},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["preview_url"]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_color_highlight_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.highlighted_color == "#ffffff"
        assert record.highlighted_pixel_count == 8


class TestRegionDetectCanary:
    """Successful region-detect requests emit the structured done canary."""

    def test_region_detect_defaults_to_geometry_without_highlight_png(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/region-detect",
                json={"session_id": session_id, "x": 0, "y": 0},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["region_id"]
        assert body["color_hex"] == "#ffffff"
        assert body["pixel_count"] == 8
        assert body["preview_url"] is None
        assert body["contours"]
        assert body["bbox"] == [0, 0, 4, 2]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_region_detect_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.click_x == 0
        assert record.click_y == 0
        assert record.region_id == body["region_id"]
        assert record.component_cache_hit is False
        assert record.detected_pixel_count == 8
        assert record.detected_dominant_color == "#ffffff"
        assert record.contour_count == len(body["contours"])
        assert record.bbox == (0, 0, 4, 2)
        assert record.include_preview is False
        assert record.preview_png_ms == 0

    def test_region_detect_can_generate_highlight_png_when_explicitly_requested(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Legacy/debug callers may explicitly request a highlight PNG.
        旧调用或调试场景可显式请求高亮 PNG。
        """
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/region-detect",
                json={
                    "session_id": session_id,
                    "x": 0,
                    "y": 0,
                    "include_preview": True,
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["region_id"]
        assert body["color_hex"] == "#ffffff"
        assert body["pixel_count"] == 8
        assert body["preview_url"]
        assert body["contours"]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_region_detect_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.include_preview is True
        assert record.preview_png_ms >= 0
        assert record.detected_pixel_count == 8

    def test_region_detect_returns_stable_region_id_for_same_component(
        self,
        _isolate_dependency_overrides,
    ) -> None:
        """The same connected component gets the same ID on repeated clicks.
        同一连通区域重复点击应返回同一个 ID，便于前端二次点击取消选中。
        """
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)

        first = client.post(
            "/api/convert/region-detect",
            json={"session_id": session_id, "x": 0, "y": 0},
        )
        second = client.post(
            "/api/convert/region-detect",
            json={"session_id": session_id, "x": 1, "y": 0},
        )

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["region_id"] == second.json()["region_id"]

    def test_region_detect_returns_drawable_contour_for_single_pixel_region(
        self,
        _isolate_dependency_overrides,
    ) -> None:
        """Single-pixel regions still need a drawable outline.
        单像素区域也必须返回可绘制轮廓，避免前端看起来没有选中。
        """
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = store.create()
        matched_rgb = np.zeros((3, 3, 3), dtype=np.uint8)
        matched_rgb[:, :, :] = [0, 0, 0]
        matched_rgb[1, 1, :] = [255, 255, 255]
        mask_solid = np.ones((3, 3), dtype=bool)
        store.put(
            session_id,
            "preview_cache",
            {
                "matched_rgb": matched_rgb.copy(),
                "quantized_image": matched_rgb.copy(),
                "mask_solid": mask_solid,
                "target_w": 3,
                "target_h": 3,
                "target_width_mm": 30.0,
                "color_palette": [],
            },
        )
        store.put(session_id, "material_source", "lut")

        response = client.post(
            "/api/convert/region-detect",
            json={"session_id": session_id, "x": 1, "y": 1},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["pixel_count"] == 1
        assert body["preview_url"] is None
        assert body["contours"]
        assert len(body["contours"][0]) >= 3

    def test_region_detect_returns_full_region_contour_without_physical_width_metadata(
        self,
        _isolate_dependency_overrides,
    ) -> None:
        """Missing target_width_mm must not degrade selection to click pixel.
        缺少物理宽度元数据时，也必须返回整块连通区域轮廓。
        """
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = store.create()
        matched_rgb = np.full((5, 5, 3), [20, 20, 20], dtype=np.uint8)
        matched_rgb[:, :, :] = [0, 0, 0]
        matched_rgb[1:4, 1:4, :] = [255, 255, 255]
        mask_solid = np.ones((5, 5), dtype=bool)
        store.put(
            session_id,
            "preview_cache",
            {
                "matched_rgb": matched_rgb.copy(),
                "quantized_image": matched_rgb.copy(),
                "mask_solid": mask_solid,
                "target_w": 5,
                "target_h": 5,
                "color_palette": [],
            },
        )
        store.put(session_id, "material_source", "lut")

        response = client.post(
            "/api/convert/region-detect",
            json={"session_id": session_id, "x": 2, "y": 2},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["pixel_count"] == 9
        assert body["preview_url"] is None
        contours = body["contours"]
        assert contours
        xs = [point[0] for contour in contours for point in contour]
        ys = [point[1] for contour in contours for point in contour]
        assert body["bbox"] == [1, 1, 3, 3]
        assert max(xs) - min(xs) >= 3.0
        assert max(ys) - min(ys) >= 3.0

    def test_region_detect_selects_full_visible_matched_colour_component(
        self,
        _isolate_dependency_overrides,
    ) -> None:
        """Click selection follows the visible matched colour, not source islands.
        点击选区应跟随当前可见匹配色，而不是被上游量化原色拆成小块。
        """
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = store.create()
        matched_rgb = np.zeros((5, 5, 3), dtype=np.uint8)
        matched_rgb[1:4, 1:4, :] = [180, 180, 180]
        quantized_image = matched_rgb.copy()
        # Simulate several source-quantized colours that all matched to the
        # same visible/printed colour. The click should still select the
        # whole 3x3 visible block.
        quantized_image[1:4, 1:4, :] = [10, 10, 10]
        quantized_image[2, 2, :] = [240, 240, 240]
        quantized_image[1, 2, :] = [120, 120, 120]
        mask_solid = np.ones((5, 5), dtype=bool)
        store.put(
            session_id,
            "preview_cache",
            {
                "matched_rgb": matched_rgb.copy(),
                "quantized_image": quantized_image,
                "mask_solid": mask_solid,
                "target_w": 5,
                "target_h": 5,
                "target_width_mm": 50.0,
                "color_palette": [],
            },
        )
        store.put(session_id, "material_source", "lut")

        response = client.post(
            "/api/convert/region-detect",
            json={"session_id": session_id, "x": 2, "y": 2},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["color_hex"] == "#b4b4b4"
        assert body["pixel_count"] == 9
        assert body["contours"]

    def test_region_detect_returns_shape_outline_not_bbox_for_non_rectangular_region(
        self,
        _isolate_dependency_overrides,
    ) -> None:
        """Non-rectangular components must render their shape, not bbox.
        非矩形色块必须显示真实形状轮廓，而不是退化成 bbox 方框。
        """
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = store.create()
        matched_rgb = np.zeros((5, 5, 3), dtype=np.uint8)
        matched_rgb[1:4, 1, :] = [255, 255, 255]
        matched_rgb[3, 1:4, :] = [255, 255, 255]
        mask_solid = np.ones((5, 5), dtype=bool)
        store.put(
            session_id,
            "preview_cache",
            {
                "matched_rgb": matched_rgb.copy(),
                "quantized_image": matched_rgb.copy(),
                "mask_solid": mask_solid,
                "target_w": 5,
                "target_h": 5,
                "color_palette": [],
            },
        )
        store.put(session_id, "material_source", "lut")

        response = client.post(
            "/api/convert/region-detect",
            json={"session_id": session_id, "x": 1, "y": 1},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["pixel_count"] == 5
        assert body["bbox"] == [1, 1, 3, 3]
        contour = body["contours"][0]
        assert len(contour) > 4
        # The bbox rectangle would only have 4 vertices. The real L-shape
        # outline contains the concave turn at x=2, y=2 (pixel units).
        assert [2.0, 2.0] in contour
        xs = [point[0] for point in contour]
        ys = [point[1] for point in contour]
        assert max(xs) - min(xs) >= 3.0
        assert max(ys) - min(ys) >= 3.0

    def test_region_detect_reuses_visible_component_cache_for_repeated_clicks(
        self,
        _isolate_dependency_overrides,
    ) -> None:
        """Repeated clicks should use the cached visible-component index.
        重复点击应复用当前可见色块分块缓存，而不是每次重建。
        """
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)

        first = client.post(
            "/api/convert/region-detect",
            json={"session_id": session_id, "x": 0, "y": 0},
        )
        assert first.status_code == 200, first.text
        session = store.get(session_id)
        assert session is not None
        assert session.get("visible_region_component_cache") is not None
        assert session.get("selected_region_mask") is None

        with patch(
            "api.routers.converter.replace.build_visible_region_component_cache",
            side_effect=AssertionError("cached clicks must not rebuild components"),
        ):
            second = client.post(
                "/api/convert/region-detect",
                json={"session_id": session_id, "x": 1, "y": 0},
            )

        assert second.status_code == 200, second.text
        assert second.json()["region_id"] == first.json()["region_id"]
        assert second.json()["bbox"] == first.json()["bbox"]

    def test_region_replace_uses_cached_component_reference_after_detect(
        self,
        _isolate_dependency_overrides,
    ) -> None:
        """Region replace can rebuild the mask from a lightweight click ref.
        区域替换可从点击阶段的轻量分块引用恢复完整 mask。
        """
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)

        detect = client.post(
            "/api/convert/region-detect",
            json={"session_id": session_id, "x": 0, "y": 0},
        )
        assert detect.status_code == 200, detect.text
        assert store.get(session_id)["selected_region_mask"] is None

        with patch(
            "api.routers.converter.replace._schedule_or_run_overridden_glb_build",
            return_value=None,
        ):
            response = client.post(
                "/api/convert/region-replace",
                json={
                    "session_id": session_id,
                    "replacement_color": "#0000ff",
                },
            )

        assert response.status_code == 200, response.text
        cache = store.get(session_id)["preview_cache"]
        replaced_rgb = cache["matched_rgb"]
        replaced_mask = np.all(replaced_rgb == [0, 0, 255], axis=-1)
        assert int(np.count_nonzero(replaced_mask)) == 8
        assert replaced_mask[:2, :].all()

    def test_region_detect_preserves_transparent_background_alpha(
        self,
        _isolate_dependency_overrides,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_transparent_region_session(store)

        response = client.post(
            "/api/convert/region-detect",
            # 新架构默认不生成高亮 PNG（前端轮廓叠加），透明背景 canary
            # 需显式请求预览图。
            json={
                "session_id": session_id,
                "x": 1,
                "y": 1,
                "include_preview": True,
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        preview = client.get(body["preview_url"])
        assert preview.status_code == 200, preview.text
        img = Image.open(io.BytesIO(preview.content)).convert("RGBA")
        rgba = np.asarray(img, dtype=np.uint8)
        mask_solid = store.get(session_id)["preview_cache"]["mask_solid"]
        assert int((rgba[~mask_solid, 3] == 0).sum()) == int((~mask_solid).sum())
        assert int((rgba[mask_solid, 3] == 255).sum()) == int(mask_solid.sum())


class TestRegionRequantizeCanary:
    """Successful region-requantize requests expose the structured done fields."""

    def test_region_requantize_group_fallback_warning_has_actionable_fields(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_region_requantize_session(store, tmp_path)
        _force_region_group_one_map(store, session_id)
        target_logger = _capture_replace_logger(caplog)
        fallback_encoded_id = int(replace_router.REGION_ID_ENCODING_MULTIPLIER) + 2

        def _fake_requantize(*, matched_rgb, original_source_rgb, region_id_map, **_kwargs):
            assert original_source_rgb is not None
            updated = np.asarray(matched_rgb).copy()
            mask = np.asarray(region_id_map) == fallback_encoded_id
            assert int(mask.sum()) == 64
            updated[mask] = [1, 2, 3]
            return updated, int(mask.sum())

        try:
            with patch(
                "api.routers.converter.replace.load_multiple_materials",
                return_value=[],
            ), patch(
                "api.routers.converter.replace.load_material_solver_cache_with_fallback",
                return_value=(object(), 64),
            ), patch(
                "api.routers.converter.replace.requantize_gradient_regions",
                side_effect=_fake_requantize,
            ), patch(
                "api.routers.converter.replace._sync_material_matrix_after_rgb_change",
            ), patch(
                "api.routers.converter.replace.recompute_gradient_groups_into_session",
                return_value=[],
            ), patch(
                "api.routers.converter.replace.schedule_glb_build",
                return_value="mock-glb-token",
            ):
                response = client.post(
                    "/api/convert/region-requantize",
                    json={
                        "session_id": session_id,
                        "targets": [
                            {
                                "gradient_group_index": 1,
                                "gradient_region_index": 2,
                            }
                        ],
                        "local_quantize_colors": 12,
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        record = _single_record(
            caplog,
            "region_requantize_unmapped_target_group_fallback",
        )
        _assert_actionable_warning(record)

    def test_region_requantize_emits_converter_region_requantize_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_region_requantize_session(store, tmp_path)
        target_logger = _capture_replace_logger(caplog)

        def _fake_requantize(*, matched_rgb, original_source_rgb, region_id_map, **_kwargs):
            assert original_source_rgb is not None
            updated = np.asarray(matched_rgb).copy()
            mask = np.asarray(region_id_map) == 1001
            updated[mask] = [1, 2, 3]
            return updated, int(mask.sum())

        try:
            with patch(
                "api.routers.converter.replace.load_multiple_materials",
                return_value=[],
            ), patch(
                "api.routers.converter.replace.load_material_solver_cache_with_fallback",
                return_value=(object(), 64),
            ), patch(
                "api.routers.converter.replace.requantize_gradient_regions",
                side_effect=_fake_requantize,
            ), patch(
                "api.routers.converter.replace._sync_material_matrix_after_rgb_change",
            ), patch(
                "api.routers.converter.replace.recompute_gradient_groups_into_session",
                return_value=[],
            ), patch(
                "api.routers.converter.replace.schedule_glb_build",
                return_value="mock-glb-token",
            ):
                response = client.post(
                    "/api/convert/region-requantize",
                    json={
                        "session_id": session_id,
                        "targets": [
                            {
                                "gradient_group_index": 1,
                                "gradient_region_index": 1,
                            }
                        ],
                        "local_quantize_colors": 12,
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["preview_url"]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_region_requantize_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.target_lut == "__material_archive__"
        assert record.region_pixel_count == 64
        assert record.output_color_count >= 1

    def test_region_requantize_artifact_cache_avoids_common_full_hydrate(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_region_requantize_session(store, tmp_path)
        session_data = store.get(session_id)
        cache_ref = externalize_preview_cache(
            session_id,
            store,
            session_data["preview_cache"],
            root_dir=tmp_path,
        )
        store.put(session_id, "preview_cache", cache_ref)

        def _fake_requantize(*, matched_rgb, original_source_rgb, region_id_map, **_kwargs):
            assert original_source_rgb is not None
            updated = np.asarray(matched_rgb, dtype=np.uint8).copy()
            mask = np.asarray(region_id_map) == 1001
            updated[mask] = [90, 120, 150]
            return updated, int(mask.sum())

        with patch(
            "api.routers.converter.common.hydrate_preview_cache",
            side_effect=AssertionError("region-requantize must not fully hydrate artifact cache"),
        ), patch(
            "api.routers.converter.replace.load_multiple_materials",
            return_value=[],
        ), patch(
            "api.routers.converter.replace.load_material_solver_cache_with_fallback",
            return_value=(object(), 64),
        ), patch(
            "api.routers.converter.replace.requantize_gradient_regions",
            side_effect=_fake_requantize,
        ), patch(
            "api.routers.converter.replace._sync_material_matrix_after_rgb_change",
        ), patch(
            "api.routers.converter.replace.recompute_gradient_groups_into_session",
            return_value=[],
        ), patch(
            "api.routers.converter.replace.schedule_glb_build",
            return_value="mock-glb-token",
        ):
            response = client.post(
                "/api/convert/region-requantize",
                json={
                    "session_id": session_id,
                    "targets": [
                        {
                            "gradient_group_index": 1,
                            "gradient_region_index": 1,
                        }
                    ],
                    "local_quantize_colors": 12,
                },
            )

        assert response.status_code == 200, response.text
        stored = store.get(session_id)["preview_cache"]
        assert is_preview_cache_artifact_ref(stored)
        assert stored["fields"]["matched_rgb"]["revision"] == 2


class TestReplaceColorsBatchCanary:
    """Successful replace-colors-batch requests emit the structured done canary."""

    def test_replace_colors_batch_emits_converter_replace_colors_batch_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            with patch(
                "api.routers.converter.replace.schedule_glb_build",
                return_value="mock-glb-token",
            ):
                response = client.post(
                    "/api/convert/replace-colors-batch",
                    json={
                        "session_id": session_id,
                        "replacements": [
                            {
                                "selected_color": "#ffffff",
                                "replacement_color": "#0000ff",
                            },
                            {
                                "selected_color": "#ff0000",
                                "replacement_color": "#00ff00",
                            },
                        ],
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["preview_url"]
        assert body["replacement_count"] == 2

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_replace_colors_batch_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.pair_count == 2
        assert record.diff_pixel_count == 16
        assert record.replacement_count == 2

    def test_replace_colors_batch_artifact_cache_avoids_common_full_hydrate(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_artifact_preview_session(store, tmp_path)

        with patch(
            "api.routers.converter.common.hydrate_preview_cache",
            side_effect=AssertionError("replace-colors-batch must not fully hydrate artifact cache"),
        ), patch(
            "api.routers.converter.replace.schedule_glb_build",
            return_value="mock-glb-token",
        ):
            response = client.post(
                "/api/convert/replace-colors-batch",
                json={
                    "session_id": session_id,
                    "replacements": [
                        {
                            "selected_color": "#ffffff",
                            "replacement_color": "#0000ff",
                        },
                        {
                            "selected_color": "#ff0000",
                            "replacement_color": "#00ff00",
                        },
                    ],
                },
            )

        assert response.status_code == 200, response.text
        stored = store.get(session_id)["preview_cache"]
        assert is_preview_cache_artifact_ref(stored)
        assert stored["fields"]["matched_rgb"]["revision"] == 2


class TestRegionReplaceBatchCanary:
    """Successful region-replace-batch requests emit the structured done canary."""

    def test_region_replace_batch_emits_converter_region_replace_batch_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            with patch(
                "api.routers.converter.replace.schedule_glb_build",
                return_value="mock-glb-token",
            ):
                response = client.post(
                    "/api/convert/region-replace-batch",
                    json={
                        "session_id": session_id,
                        "items": [
                            {
                                "replacement_color": "#0000ff",
                                "click_x": 0,
                                "click_y": 0,
                            }
                        ],
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["preview_url"]
        assert "Batch replaced" in body["message"]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_region_replace_batch_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.item_count == 1
        assert record.diff_pixel_count == 8
        assert record.any_click_mask_used is True

    def test_region_replace_batch_artifact_cache_avoids_common_full_hydrate(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_artifact_preview_session(store, tmp_path)

        with patch(
            "api.routers.converter.common.hydrate_preview_cache",
            side_effect=AssertionError("region-replace-batch must not fully hydrate artifact cache"),
        ), patch(
            "api.routers.converter.replace.schedule_glb_build",
            return_value="mock-glb-token",
        ):
            response = client.post(
                "/api/convert/region-replace-batch",
                json={
                    "session_id": session_id,
                    "items": [
                        {
                            "replacement_color": "#0000ff",
                            "click_x": 0,
                            "click_y": 0,
                        }
                    ],
                },
            )

        assert response.status_code == 200, response.text
        stored = store.get(session_id)["preview_cache"]
        assert is_preview_cache_artifact_ref(stored)
        assert stored["fields"]["matched_rgb"]["revision"] == 2

    def test_region_replace_batch_click_uses_visible_matched_colour_component(
        self,
        _isolate_dependency_overrides,
    ) -> None:
        """Batch click replacement uses the same visible region as detection.
        批量点击替换应与点击检测一样，按当前可见色块计算整块区域。
        """
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = store.create()
        matched_rgb = np.full((5, 5, 3), [20, 20, 20], dtype=np.uint8)
        matched_rgb[1:4, 1:4, :] = [180, 180, 180]
        quantized_image = matched_rgb.copy()
        quantized_image[1:4, 1:4, :] = [10, 10, 10]
        quantized_image[2, 2, :] = [240, 240, 240]
        quantized_image[1, 2, :] = [120, 120, 120]
        mask_solid = np.ones((5, 5), dtype=bool)
        material_matrix = np.zeros((5, 5, 1), dtype=np.int32)
        store.put(
            session_id,
            "preview_cache",
            {
                "matched_rgb": matched_rgb.copy(),
                "quantized_image": quantized_image,
                "mask_solid": mask_solid,
                "material_matrix": material_matrix,
                "target_w": 5,
                "target_h": 5,
                "target_width_mm": 50.0,
                "color_palette": [],
            },
        )
        store.put(session_id, "material_source", "lut")

        with patch(
            "api.routers.converter.replace.schedule_glb_build",
            return_value="mock-glb-token",
        ):
            response = client.post(
                "/api/convert/region-replace-batch",
                json={
                    "session_id": session_id,
                    "items": [
                        {
                            "replacement_color": "#0000ff",
                            "click_x": 2,
                            "click_y": 2,
                        }
                    ],
                },
            )

        assert response.status_code == 200, response.text
        cache = store.get(session_id)["preview_cache"]
        replaced_rgb = cache["matched_rgb"]
        replaced_mask = np.all(replaced_rgb == [0, 0, 255], axis=-1)
        assert int(np.count_nonzero(replaced_mask)) == 9
        assert replaced_mask[1:4, 1:4].all()


class TestPredictRecipeCanary:
    """Material-archive predict-recipe fixtures avoid a real LUT file dependency."""

    def test_predict_recipe_emits_converter_predict_recipe_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_recipe_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/predict-recipe",
                json={
                    "session_id": session_id,
                    "recipe": [0, 1, 0],
                    "layer_height_mm": 0.08,
                    "color_layers": 3,
                    "layer_order": "Top2Bottom",
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert len(body["rgb"]) == 3
        assert body["source"] == "material_archive_preview"

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_predict_recipe_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.recipe_layer_count == 3
        assert record.prediction_source == "material_archive_preview"
        assert record.is_material_archive is True


class TestApplyRecipeOverrideCanary:
    """Successful apply-recipe-override requests emit the structured done canary."""

    def test_recipe_override_shape_mismatch_is_rejected_with_actionable_warning(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_recipe_session(store)
        store.put(
            session_id,
            "selected_region_masks",
            {"region-1": np.ones((2, 2), dtype=bool)},
        )
        target_logger = _capture_replace_logger(caplog)

        try:
            with patch(
                "api.routers.converter.replace.schedule_glb_build",
                return_value="mock-glb-token",
            ):
                response = client.post(
                    "/api/convert/apply-recipe-override",
                    json={
                        "session_id": session_id,
                        "region_ids": ["region-1"],
                        "recipe": [0, 1, 0],
                        "layer_height_mm": 0.08,
                        "color_layers": 3,
                        "layer_order": "Top2Bottom",
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 422, response.text
        record = _single_record(caplog, "recipe_override_shape_mismatch")
        _assert_actionable_warning(record)

    def test_apply_recipe_override_emits_converter_apply_recipe_override_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_recipe_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            with patch(
                "api.routers.converter.replace.schedule_glb_build",
                return_value="mock-glb-token",
            ):
                response = client.post(
                    "/api/convert/apply-recipe-override",
                    json={
                        "session_id": session_id,
                        "region_ids": ["region-1"],
                        "recipe": [0, 1, 0],
                        "layer_height_mm": 0.08,
                        "color_layers": 3,
                        "layer_order": "Top2Bottom",
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["preview_url"]
        assert body["override_count"] == 1

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_apply_recipe_override_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.region_count == 1
        assert record.recipe_layer_count == 3
        assert record.override_count == 1
        assert record.prediction_source == "material_archive_preview"

    def test_apply_recipe_override_artifact_cache_avoids_common_full_hydrate(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_recipe_session(store)
        session_data = store.get(session_id)
        cache_ref = externalize_preview_cache(
            session_id,
            store,
            session_data["preview_cache"],
            root_dir=tmp_path,
        )
        store.put(session_id, "preview_cache", cache_ref)

        with patch(
            "api.routers.converter.common.hydrate_preview_cache",
            side_effect=AssertionError("apply-recipe-override must not fully hydrate artifact cache"),
        ), patch(
            "api.routers.converter.replace.schedule_glb_build",
            return_value="mock-glb-token",
        ):
            response = client.post(
                "/api/convert/apply-recipe-override",
                json={
                    "session_id": session_id,
                    "region_ids": ["region-1"],
                    "recipe": [0, 1, 0],
                    "layer_height_mm": 0.08,
                    "color_layers": 3,
                    "layer_order": "Top2Bottom",
                },
            )

        assert response.status_code == 200, response.text
        stored = store.get(session_id)["preview_cache"]
        assert is_preview_cache_artifact_ref(stored)
        assert stored["fields"]["matched_rgb"]["revision"] == 2
        assert stored["fields"]["material_matrix"]["revision"] == 2


class TestRegionRecipeCanary:
    """Successful region-recipe requests emit the structured done canary."""

    def test_region_recipe_emits_converter_region_recipe_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_recipe_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/region-recipe",
                json={
                    "session_id": session_id,
                    "region_ids": ["region-1"],
                    "layer_order": "Top2Bottom",
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["recipes"]
        assert body["recipes"][0]["recipe"] == [0, 1, 0]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_region_recipe_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.requested_region_count == 1
        assert record.resolved_region_count == 1
        assert record.layer_order == "Top2Bottom"


class TestMergeColorsCanary:
    """Successful merge-colors requests emit the structured done canary."""

    def test_merge_colors_emits_converter_merge_colors_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/merge-colors",
                json={
                    "session_id": session_id,
                    "merge_enable": True,
                    "merge_threshold": 5.0,
                    "merge_max_distance": 20,
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["preview_url"]
        assert isinstance(body["colors_before"], int)
        assert isinstance(body["colors_after"], int)
        assert 0 <= body["quality_metric"] <= 100

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_merge_colors_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.merge_enabled is True
        assert record.colors_before == body["colors_before"]
        assert record.colors_after == body["colors_after"]
        assert record.merge_map_count == len(body["merge_map"])
        assert record.quality_metric == body["quality_metric"]

    def test_merge_colors_disabled_branch_preserves_payload_and_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/merge-colors",
                json={
                    "session_id": session_id,
                    "merge_enable": False,
                    "merge_threshold": 5.0,
                    "merge_max_distance": 20,
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["message"] == "Color merging disabled"
        assert body["preview_url"]
        assert body["merge_map"] == {}
        assert body["quality_metric"] == 100.0
        assert body["colors_before"] == body["colors_after"]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_merge_colors_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.merge_enabled is False
        assert record.merge_map_count == 0
        assert record.quality_metric == 100.0
