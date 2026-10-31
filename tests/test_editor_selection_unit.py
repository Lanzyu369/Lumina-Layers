from __future__ import annotations

import numpy as np
import pytest

from api.preview_cache_artifacts import PREVIEW_CACHE_REVISION_KEY
from api.replacement_history import (
    push_replacement_checkpoint,
    restore_from_history,
    snapshot_replacement_state,
    snapshot_selection_state,
)
from api.selection_state import (
    get_selection_mask,
    get_selection_revision,
    mutate_brush_add,
    mutate_color_range_toggle,
    mutate_colors_set,
    mutate_point_remove,
    mutate_point_toggle,
    mutate_same_color_remove,
    mutate_same_color_toggle,
    persist_selection_mask,
    rasterize_brush_stroke,
    selection_summary,
)
from api.visible_region_cache import build_visible_region_component_cache, invalidate_visible_region_cache


class MemoryStore:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, object]] = {"session": {}}

    def put(self, session_id: str, key: str, value: object) -> None:
        self.data.setdefault(session_id, {})[key] = value

    def get(self, session_id: str) -> dict[str, object] | None:
        return self.data.get(session_id)


def _cache(rgb: np.ndarray) -> dict[str, object]:
    height, width = rgb.shape[:2]
    return {
        "matched_rgb": rgb.copy(),
        "mask_solid": np.ones((height, width), dtype=bool),
        "target_w": width,
        "target_width_mm": float(width),
    }


def _component_cache() -> tuple[dict[str, object], np.ndarray]:
    rgb = np.array(
        [
            [[255, 0, 0], [255, 0, 0], [0, 0, 255], [0, 0, 0]],
            [[255, 0, 0], [255, 0, 0], [0, 0, 255], [0, 0, 0]],
            [[0, 0, 0], [0, 0, 0], [0, 0, 0], [255, 0, 0]],
        ],
        dtype=np.uint8,
    )
    return build_visible_region_component_cache(_cache(rgb), generation=3), rgb


def test_point_toggle_is_exact_and_reversible() -> None:
    components, _rgb = _component_cache()
    empty = np.zeros((3, 4), dtype=bool)
    selected = mutate_point_toggle(components, empty, 0, 0)
    assert int(selected.sum()) == 4
    assert not bool(selected[2, 3])
    cleared = mutate_point_toggle(components, selected, 1, 1)
    assert not np.any(cleared)


def test_same_color_toggle_selects_all_disconnected_components() -> None:
    components, _rgb = _component_cache()
    selected = mutate_same_color_toggle(
        components,
        np.zeros((3, 4), dtype=bool),
        x=None,
        y=None,
        color_hex="#ff0000",
    )
    assert int(selected.sum()) == 5
    assert bool(selected[2, 3])


def test_brush_add_selects_whole_touched_components_only() -> None:
    components, _rgb = _component_cache()
    selected, hits = mutate_brush_add(
        components,
        np.zeros((3, 4), dtype=bool),
        [(2.0, 0.0)],
        0.6,
    )
    assert hits >= 1
    assert bool(selected[0, 2]) and bool(selected[1, 2])
    assert not bool(selected[2, 3])


def test_explicit_removal_preserves_unrelated_and_disconnected_selections() -> None:
    components, _rgb = _component_cache()
    selected = mutate_colors_set(components, ["#ff0000", "0000FF"])
    assert int(selected.sum()) == 7
    point_removed = mutate_point_remove(components, selected, 0, 0)
    assert int(point_removed.sum()) == 3
    assert point_removed[2, 3]
    assert np.array_equal(mutate_point_remove(components, point_removed, 0, 0), point_removed)
    color_removed = mutate_same_color_remove(
        components, selected, x=None, y=None, color_hex="#ff0000",
    )
    assert int(color_removed.sum()) == 2
    assert not color_removed[2, 3]
    assert np.array_equal(
        mutate_same_color_remove(components, color_removed, x=0, y=0, color_hex=None),
        color_removed,
    )


def test_brush_raster_interpolates_fast_strokes_without_gaps() -> None:
    mask = rasterize_brush_stroke((9, 20), [(1.0, 4.0), (18.0, 4.0)], 1.0)
    assert np.all(mask[4, 1:19])


def test_selection_summary_uses_union_boundary_without_shared_edge() -> None:
    components, rgb = _component_cache()
    store = MemoryStore()
    session = store.get("session")
    assert session is not None
    mask = np.zeros((3, 4), dtype=bool)
    mask[:2, :3] = True
    persist_selection_mask("session", store, session, mask, content_generation=3)
    summary = selection_summary(session, components, rgb)
    assert summary["selected_component_count"] == 2
    assert summary["selected_pixel_count"] == 6
    assert len(summary["contours"]) == 1
    assert len(summary["contours"][0]) == 4


def test_selection_history_is_cheap_and_survives_content_commit() -> None:
    store = MemoryStore()
    session = store.get("session")
    assert session is not None
    shape = (3, 4)
    first = snapshot_selection_state(session, label="selection_point_toggle")
    persist_selection_mask(
        "session", store, session, np.eye(3, 4, dtype=bool), content_generation=1
    )
    push_replacement_checkpoint("session", store, session, first)
    assert first["artifact_nbytes"] == 0
    assert "preview_cache_arrays" not in first
    second = snapshot_selection_state(session, label="selection_clear")
    persist_selection_mask(
        "session", store, session, np.zeros(shape, dtype=bool), content_generation=1
    )
    push_replacement_checkpoint("session", store, session, second)
    restored = restore_from_history("session", store, session, action="undo")
    assert restored["kind"] == "selection"
    assert int(get_selection_mask(session, shape).sum()) == 3
    content = snapshot_replacement_state(session, label="region_replace")
    push_replacement_checkpoint("session", store, session, content)
    undo_stack = session["replacement_undo_stack"]
    assert isinstance(undo_stack, list)
    assert undo_stack[-1]["kind"] == "content"
    assert [item["kind"] for item in undo_stack] == ["selection", "content"]
    before = get_selection_mask(session, shape)
    restored_content = restore_from_history("session", store, session, action="undo")
    assert restored_content["kind"] == "content"
    assert np.array_equal(get_selection_mask(session, shape), before)
    assert get_selection_revision(session) > 0
    revision = get_selection_revision(session)
    restore_from_history("session", store, session, action="undo")
    assert not np.any(get_selection_mask(session, shape))
    assert get_selection_revision(session) > revision
    assert session["editor_selection_content_generation"] == 1
    assert session["selected_region_masks"] == {}
    assert session["replacement_undo_stack"] == []
    restore_from_history("session", store, session, action="redo")
    assert np.array_equal(get_selection_mask(session, shape), before)
    assert list(session["selected_region_masks"]) == [
        f"__editor_selection__:{get_selection_revision(session)}"
    ]
    redo_selection = session["replacement_undo_stack"][-1]
    assert set(redo_selection["session_fields"]) <= {
        "editor_selection_mask", "editor_selection_revision", "editor_selection_content_generation",
    }


def test_content_history_restore_gets_a_fresh_preview_cache_revision() -> None:
    store = MemoryStore()
    session = store.get("session")
    assert session is not None
    rgb = np.full((2, 2, 3), 91, dtype=np.uint8)
    checkpoint_cache = _cache(rgb)
    checkpoint_cache[PREVIEW_CACHE_REVISION_KEY] = "checkpoint-revision"
    session["preview_cache"] = checkpoint_cache
    checkpoint = snapshot_replacement_state(session, label="before_replace")
    push_replacement_checkpoint("session", store, session, checkpoint)
    session["preview_cache"] = {
        **_cache(np.full((2, 2, 3), 19, dtype=np.uint8)),
        PREVIEW_CACHE_REVISION_KEY: "current-revision",
    }

    restore_from_history("session", store, session, action="undo")

    restored = session["preview_cache"]
    assert isinstance(restored, dict)
    assert restored[PREVIEW_CACHE_REVISION_KEY] not in {
        "checkpoint-revision",
        "current-revision",
    }


def test_clear_selection_allows_stale_content_revision_after_replace() -> None:
    from fastapi.testclient import TestClient

    from api.app import app
    from api.dependencies import get_session_store

    store = MemoryStore()
    session = store.get("session")
    assert session is not None
    rgb = np.array(
        [
            [[255, 0, 0], [255, 0, 0]],
            [[255, 0, 0], [0, 0, 255]],
        ],
        dtype=np.uint8,
    )
    session["preview_cache"] = _cache(rgb)
    session["visible_region_cache_generation"] = 3
    components = build_visible_region_component_cache(session["preview_cache"], generation=3)
    session["visible_region_component_cache"] = components
    mask = np.zeros((2, 2), dtype=bool)
    mask[:1, :] = True
    persist_selection_mask("session", store, session, mask, content_generation=3)

    invalidate_visible_region_cache("session", store, session)
    app.dependency_overrides[get_session_store] = lambda: store
    client = TestClient(app)
    try:
        response = client.post(
            "/api/convert/selection/mutate",
            json={
                "session_id": "session",
                "operation": "clear",
                "base_selection_revision": 1,
                "content_revision": 3,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["selected_pixel_count"] == 0
        assert body["content_revision"] == 4
        assert not np.any(get_selection_mask(session, (2, 2)))
    finally:
        app.dependency_overrides.pop(get_session_store, None)


def test_free_color_mutation_is_checkpointed() -> None:
    from fastapi.testclient import TestClient

    from api.app import app
    from api.dependencies import get_session_store

    store = MemoryStore()
    session = store.get("session")
    assert session is not None
    session["free_color_set"] = {"112233"}
    app.dependency_overrides[get_session_store] = lambda: store
    client = TestClient(app)
    try:
        response = client.post(
            "/api/convert/free-colors",
            json={
                "session_id": "session",
                "action": "toggle",
                "color_hexes": ["#112233", "#abcdef"],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["free_color_set"] == ["abcdef"]
        assert response.json()["can_undo"] is True
        checkpoint = restore_from_history("session", store, session, action="undo")
        assert checkpoint["kind"] == "content"
        assert session["free_color_set"] == {"112233"}
    finally:
        app.dependency_overrides.pop(get_session_store, None)


def test_free_color_replace_seeds_a_restored_project_session() -> None:
    from fastapi.testclient import TestClient

    from api.app import app
    from api.dependencies import get_session_store

    store = MemoryStore()
    session = store.get("session")
    assert session is not None
    session["free_color_set"] = {"112233"}
    app.dependency_overrides[get_session_store] = lambda: store
    client = TestClient(app)
    try:
        response = client.post(
            "/api/convert/free-colors",
            json={
                "session_id": "session",
                "action": "replace",
                "color_hexes": ["#abcdef", "ABCDEF", "#fedcba"],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["free_color_set"] == ["abcdef", "fedcba"]
        assert session["free_color_set"] == {"abcdef", "fedcba"}
        assert response.json()["can_undo"] is True

        restore_from_history("session", store, session, action="undo")
        assert session["free_color_set"] == {"112233"}
    finally:
        app.dependency_overrides.pop(get_session_store, None)


def test_repeated_free_color_toggle_preserves_serial_history() -> None:
    from fastapi.testclient import TestClient

    from api.app import app
    from api.dependencies import get_session_store

    store = MemoryStore()
    session = store.get("session")
    assert session is not None
    session["free_color_set"] = set()
    app.dependency_overrides[get_session_store] = lambda: store
    client = TestClient(app)
    request = {
        "session_id": "session",
        "action": "toggle",
        "color_hexes": ["#abcdef"],
    }
    try:
        first = client.post("/api/convert/free-colors", json=request)
        second = client.post("/api/convert/free-colors", json=request)

        assert first.status_code == 200, first.text
        assert first.json()["free_color_set"] == ["abcdef"]
        assert second.status_code == 200, second.text
        assert second.json()["free_color_set"] == []
        assert session["free_color_set"] == set()

        restore_from_history("session", store, session, action="undo")
        assert session["free_color_set"] == {"abcdef"}
        restore_from_history("session", store, session, action="undo")
        assert session["free_color_set"] == set()
    finally:
        app.dependency_overrides.pop(get_session_store, None)


def test_color_range_toggle_zero_tolerance_matches_same_colour() -> None:
    components, _rgb = _component_cache()
    empty = np.zeros((3, 4), dtype=bool)
    by_range = mutate_color_range_toggle(
        components, empty, x=0, y=0, color_hex=None, tolerance=0.0
    )
    by_color = mutate_same_color_toggle(
        components, empty, x=0, y=0, color_hex=None
    )
    assert np.array_equal(by_range, by_color)


def test_color_range_toggle_selects_near_shades_and_is_reversible() -> None:
    rgb = np.array(
        [
            [[200, 0, 0], [0, 0, 0], [204, 4, 2]],
            [[0, 0, 0], [0, 0, 0], [0, 0, 0]],
            [[0, 0, 200], [0, 0, 0], [200, 0, 0]],
        ],
        dtype=np.uint8,
    )
    components = build_visible_region_component_cache(_cache(rgb), generation=1)
    empty = np.zeros((3, 3), dtype=bool)
    selected = mutate_color_range_toggle(
        components, empty, x=None, y=None, color_hex="#c80000", tolerance=5.0
    )
    assert bool(selected[0, 0]) and bool(selected[0, 2]) and bool(selected[2, 2])
    assert not bool(selected[2, 0])
    assert not bool(selected[1, 1])
    cleared = mutate_color_range_toggle(
        components, selected, x=0, y=0, color_hex=None, tolerance=5.0
    )
    assert not np.any(cleared)


def test_color_range_toggle_requires_colour_or_point() -> None:
    components, _rgb = _component_cache()
    with pytest.raises(ValueError):
        mutate_color_range_toggle(
            components,
            np.zeros((3, 4), dtype=bool),
            x=None,
            y=None,
            color_hex=None,
            tolerance=3.0,
        )
