"""Portable editor checkpoints preserve editable data without session paths."""

from __future__ import annotations

import gzip
import json

import numpy as np
import pytest

from api.preview_cache_artifacts import externalize_preview_cache
from api.selection_state import pack_applied_region_mask, resolve_recipe_override_masks
from api.session_store import SessionStore
from config import LUTMetadata, PaletteEntry


def _session() -> dict:
    rgb = np.full((4, 6, 3), [210, 20, 30], dtype=np.uint8)
    matrix = np.zeros((4, 6, 3), dtype=np.int16)
    selected = np.zeros((4, 6), dtype=bool)
    selected[1, 1] = selected[2, 4] = True
    return {
        "material_source": "lut",
        "lut_source_kind": "legacy_single",
        "lut_name": "example",
        "lut_path": "/tmp/old-source-colours.npy",
        "preview_cache": {
            "matched_rgb": rgb,
            "material_matrix": matrix,
            "original_matched_rgb": rgb.copy(),
            "original_material_matrix": matrix.copy(),
            "mask_solid": np.ones((4, 6), dtype=bool),
            "quantized_image": rgb.copy(),
            "target_w": 6,
            "target_h": 4,
            "pixel_scale": 0.1,
            "lut_metadata": LUTMetadata(palette=[PaletteEntry("Red", "PETG")]),
            "vector_parse_clip_cache_path": "/tmp/old-source-geometry.pkl",
        },
        "editor_selection_mask": selected,
        "editor_selection_revision": 8,
        "editor_selection_content_generation": 3,
        "replacement_regions": [],
        "recipe_overrides": [],
        "free_color_set": set(),
        "region_replacement_count": 0,
    }


def test_portable_editor_restores_disjoint_pixels_selection_and_recipe() -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    source = _session()
    mask = source["editor_selection_mask"]
    source["preview_cache"]["matched_rgb"][mask] = [20, 210, 40]
    source["preview_cache"]["material_matrix"][mask] = [1, 0, 1]
    source["region_replacement_count"] = 1
    source["recipe_overrides"] = [{"region_id": "region-8", "recipe": [1, 0, 1], "layer_order": "Top2Bottom"}]
    source["recipe_override_applied_masks"] = {"region-8": pack_applied_region_mask(mask)}

    payload = build_editor_project(source)
    fresh = _session()
    fresh["preview_cache"]["vector_parse_clip_cache_path"] = "/tmp/new-geometry.pkl"
    checkpoint = decode_editor_project(payload, fresh)

    np.testing.assert_array_equal(checkpoint["preview_cache_arrays"]["matched_rgb"], source["preview_cache"]["matched_rgb"])
    np.testing.assert_array_equal(checkpoint["preview_cache_arrays"]["material_matrix"], source["preview_cache"]["material_matrix"])
    np.testing.assert_array_equal(checkpoint["session_fields"]["editor_selection_mask"], mask)
    resolved = resolve_recipe_override_masks(checkpoint["session_fields"], source["recipe_overrides"], mask.shape)
    np.testing.assert_array_equal(resolved["region-8"], mask)
    assert checkpoint["preview_cache_arrays"]["vector_parse_clip_cache_path"] == "/tmp/new-geometry.pkl"
    assert b"/tmp/old-" not in gzip.decompress(payload)


def test_editor_asset_survives_artifact_source_session_cleanup() -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    source = _session()
    store = SessionStore(ttl=1800)
    sid = store.create()
    source["preview_cache"] = externalize_preview_cache(sid, store, source["preview_cache"])
    try:
        payload = build_editor_project(source)
    finally:
        store.close(sid)
    restored = decode_editor_project(payload, _session())
    np.testing.assert_array_equal(restored["session_fields"]["editor_selection_mask"], _session()["editor_selection_mask"])


def test_material_project_binding_uses_source_channels_before_and_after_recipe_edit() -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    source = _session()
    source.update({
        "material_source": "material_archive",
        "selected_materials": ["red", "white"],
        "material_backing_material_index": 1,
    })
    source["preview_cache"]["slot_names"] = ["Red PETG", "White PETG", "Virtual Clear"]
    source["preview_cache"]["lut_metadata"] = LUTMetadata(
        palette=[PaletteEntry("Red PETG", "red"), PaletteEntry("White PETG", "white")],
        base_channel_idx=1,
    )
    fresh = _session()
    fresh.update({key: source[key] for key in (
        "material_source", "selected_materials", "material_backing_material_index",
    )})
    fresh["preview_cache"]["slot_names"] = ["Red PETG", "White PETG"]
    # Material previews acquire LUTMetadata only after a custom recipe is applied.
    fresh["preview_cache"].pop("lut_metadata")

    checkpoint = decode_editor_project(build_editor_project(source), fresh)

    np.testing.assert_array_equal(
        checkpoint["preview_cache_arrays"]["matched_rgb"],
        source["preview_cache"]["matched_rgb"],
    )


@pytest.mark.parametrize("mismatch", ["shape", "material"])
def test_editor_asset_rejects_an_incompatible_preview_without_mutation(mismatch: str) -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    payload = build_editor_project(_session())
    fresh = _session()
    if mismatch == "shape":
        fresh["preview_cache"]["target_w"] = 7
    else:
        fresh["preview_cache"]["lut_metadata"].palette[0].material = "PLA"
    before = fresh["preview_cache"]["matched_rgb"].copy()
    with pytest.raises(ValueError, match="match|compatible"):
        decode_editor_project(payload, fresh)
    np.testing.assert_array_equal(fresh["preview_cache"]["matched_rgb"], before)


def test_editor_export_rejects_missing_applied_recipe_mask() -> None:
    from api.editor_project import build_editor_project

    source = _session()
    source["recipe_overrides"] = [{"region_id": "missing", "recipe": [0, 0, 0], "layer_order": "Top2Bottom"}]
    source["recipe_override_applied_masks"] = {}
    with pytest.raises(ValueError, match="mask"):
        build_editor_project(source)


def test_editor_import_rejects_pickle_and_corrupt_compression() -> None:
    from api.editor_project import decode_editor_project

    unsafe = gzip.compress(json.dumps({"__lumina_session_type__": "pickle", "data": "AA=="}).encode())
    for payload in (unsafe, b"not gzip"):
        with pytest.raises(ValueError):
            decode_editor_project(payload, _session())


def test_editor_routes_restore_a_fresh_session_with_committed_selection(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from api.app import app
    from api.dependencies import get_file_registry, get_session_store
    from api.file_registry import FileRegistry

    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    source = _session()
    mask = source["editor_selection_mask"]
    source["preview_cache"]["matched_rgb"][mask] = [20, 210, 40]
    source["region_replacement_count"] = 1
    original = store.create()
    fresh = store.create()
    for key, value in source.items():
        store.put(original, key, value)
    for key, value in _session().items():
        store.put(fresh, key, value)
    store.put(fresh, "editor_selection_revision", 0)
    store.put(fresh, "editor_selection_mask", None)
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    monkeypatch.setattr("api.routers.converter.replace._schedule_or_run_overridden_glb_build", lambda *args, **kwargs: None)
    client = TestClient(app)
    try:
        exported = client.get(f"/api/convert/editor-project/{original}", params={"selection_revision": 8})
        assert exported.status_code == 200, exported.text
        store.close(original)
        restored = client.post(
            f"/api/convert/editor-project/{fresh}/restore",
            files={"file": ("editor.json.gz", exported.content, "application/gzip")},
            data={"operation_id": "restore-project-1"},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["status"] == "committed"
        assert restored.json()["result"]["region_replacement_count"] == 1
        selection = client.get(f"/api/convert/selection/{fresh}")
        assert selection.status_code == 200, selection.text
        assert selection.json()["selected_pixel_count"] == 2
        assert selection.json()["editor_content_revision"] == restored.json()["editor_content_revision"]
        assert selection.json()["editor_content_revision"] > 0
        again = client.post(
            f"/api/convert/editor-project/{fresh}/restore",
            files={"file": ("editor.json.gz", exported.content, "application/gzip")},
            data={"operation_id": "restore-project-2"},
        )
        assert again.status_code == 409
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        store.close(fresh)
        client.close()
