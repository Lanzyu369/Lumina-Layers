"""Portable editor checkpoints preserve editable data without session paths."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from api.preview_cache_artifacts import externalize_preview_cache
from api.selection_state import pack_applied_region_mask, resolve_recipe_override_masks
from api.session_store import SessionStore
from config import LUTMetadata, PaletteEntry


@pytest.fixture
def source_image(tmp_path: Path) -> Path:
    path = tmp_path / "source.png"
    Image.new("RGB", (6, 4), (210, 20, 30)).save(path)
    return path


def _session(image_path: Path | None = None) -> dict:
    rgb = np.full((4, 6, 3), [210, 20, 30], dtype=np.uint8)
    matrix = np.zeros((4, 6, 3), dtype=np.int16)
    selected = np.zeros((4, 6), dtype=bool)
    selected[1, 1] = selected[2, 4] = True
    return {
        "image_path": str(image_path) if image_path is not None else None,
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
            "target_width_mm": 0.6,
            "pixel_scale": 0.1,
            "modeling_mode": "high-fidelity",
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


def test_portable_editor_restores_disjoint_pixels_selection_and_recipe(source_image: Path) -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    source = _session(source_image)
    mask = source["editor_selection_mask"]
    source["preview_cache"]["matched_rgb"][mask] = [20, 210, 40]
    source["preview_cache"]["material_matrix"][mask] = [1, 0, 1]
    source["region_replacement_count"] = 1
    source["recipe_overrides"] = [{"region_id": "region-8", "recipe": [1, 0, 1], "layer_order": "Top2Bottom"}]
    source["recipe_override_applied_masks"] = {"region-8": pack_applied_region_mask(mask)}

    payload = build_editor_project(source)
    fresh = _session(source_image)
    fresh["preview_cache"]["vector_parse_clip_cache_path"] = "/tmp/new-geometry.pkl"
    checkpoint = decode_editor_project(payload, fresh)

    np.testing.assert_array_equal(checkpoint["preview_cache_arrays"]["matched_rgb"], source["preview_cache"]["matched_rgb"])
    np.testing.assert_array_equal(checkpoint["preview_cache_arrays"]["material_matrix"], source["preview_cache"]["material_matrix"])
    np.testing.assert_array_equal(checkpoint["session_fields"]["editor_selection_mask"], mask)
    resolved = resolve_recipe_override_masks(checkpoint["session_fields"], source["recipe_overrides"], mask.shape)
    np.testing.assert_array_equal(resolved["region-8"], mask)
    assert checkpoint["preview_cache_arrays"]["vector_parse_clip_cache_path"] == "/tmp/new-geometry.pkl"
    assert b"/tmp/old-" not in gzip.decompress(payload)


def test_editor_asset_survives_artifact_source_session_cleanup(source_image: Path) -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    source = _session(source_image)
    fresh_source = source_image.with_name("fresh-source.png")
    fresh_source.write_bytes(source_image.read_bytes())
    store = SessionStore(ttl=1800)
    sid = store.create()
    store.register_temp_file(sid, str(source_image))
    source["preview_cache"] = externalize_preview_cache(sid, store, source["preview_cache"])
    try:
        payload = build_editor_project(source)
    finally:
        store.close(sid)
    assert not source_image.exists()
    restored = decode_editor_project(payload, _session(fresh_source))
    np.testing.assert_array_equal(
        restored["session_fields"]["editor_selection_mask"], _session(fresh_source)["editor_selection_mask"],
    )


def test_material_project_binding_uses_source_channels_before_and_after_recipe_edit(source_image: Path) -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    source = _session(source_image)
    source.update({
        "material_source": "material_archive",
        "selected_materials": ["red", "white"],
        "material_backing_material_index": 1,
    })
    source["preview_cache"]["slot_names"] = ["Red PETG", "White PETG", "Virtual Clear"]
    source["preview_cache"]["lut_metadata"] = LUTMetadata(
        palette=[
            PaletteEntry("Red PETG", "red"), PaletteEntry("White PETG", "white"),
            PaletteEntry("Virtual Clear", "virtual"),
        ],
        base_channel_idx=1,
    )
    source["recipe_overrides"] = [{
        "region_id": "virtual", "recipe": [2, 0, 1], "layer_order": "Top2Bottom",
    }]
    source["recipe_override_applied_masks"] = {
        "virtual": pack_applied_region_mask(source["editor_selection_mask"]),
    }
    source["preview_cache"]["material_matrix"][source["editor_selection_mask"]] = [2, 0, 1]
    fresh = _session(source_image)
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
    assert checkpoint["session_fields"]["recipe_overrides"] == source["recipe_overrides"]


@pytest.mark.parametrize("suffix", ["png", "svg"])
def test_editor_project_binds_source_content_independently_of_path(
    tmp_path: Path, suffix: str,
) -> None:
    from api.editor_project import build_editor_project, decode_editor_project
    from api.session_value_codec import encode_session_value

    original = tmp_path / f"original.{suffix}"
    renamed = tmp_path / f"renamed.{suffix}"
    different = tmp_path / "elsewhere" / original.name
    different.parent.mkdir()
    if suffix == "png":
        Image.new("RGB", (6, 4), (210, 20, 30)).save(original)
        Image.new("RGB", (6, 4), (10, 40, 220)).save(different)
    else:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="6" height="4">'
            '<path d="M0 0H6V4H0Z" fill="{}"/></svg>'
        )
        original.write_text(svg.format("#d2141e"), encoding="utf-8")
        different.write_text(svg.format("#0a28dc"), encoding="utf-8")
    renamed.write_bytes(original.read_bytes())
    source = _session(original)
    source["preview_cache"]["matched_rgb"][source["editor_selection_mask"]] = [110, 30, 125]
    payload = build_editor_project(source)

    restored = decode_editor_project(payload, _session(renamed))
    np.testing.assert_array_equal(
        restored["preview_cache_arrays"]["matched_rgb"], source["preview_cache"]["matched_rgb"],
    )
    fresh = _session(different)
    before = encode_session_value(fresh)
    with pytest.raises(ValueError, match="source.*match"):
        decode_editor_project(payload, fresh)
    assert encode_session_value(fresh) == before


@pytest.mark.parametrize("transform", ["rotate", "crop"])
def test_editor_project_rejects_changed_working_source_transform(
    source_image: Path, transform: str,
) -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    with Image.open(source_image) as image:
        image.putpixel((0, 0), (10, 40, 220))
        image.save(source_image)
        changed = (
            image.rotate(180) if transform == "rotate"
            else image.crop((1, 0, 6, 4)).resize(image.size)
        )
    payload = build_editor_project(_session(source_image))
    # The name and preview dimensions stay the same; only the working input changes.
    changed.save(source_image)
    with pytest.raises(ValueError, match="source.*match"):
        decode_editor_project(payload, _session(source_image))


@pytest.mark.parametrize("field,value", [
    ("target_width_mm", 0.7), ("pixel_scale", 0.2), ("modeling_mode", "vector"),
])
def test_editor_project_rejects_changed_working_grid(
    source_image: Path, field: str, value: object,
) -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    payload = build_editor_project(_session(source_image))
    fresh = _session(source_image)
    fresh["preview_cache"][field] = value
    with pytest.raises(ValueError, match="coordinates.*match"):
        decode_editor_project(payload, fresh)


@pytest.mark.parametrize("missing", [False, True])
def test_editor_project_requires_available_source_content(source_image: Path, missing: bool) -> None:
    from api.editor_project import build_editor_project

    source = _session(source_image if missing else None)
    if missing:
        source_image.unlink()
    with pytest.raises(ValueError, match="source.*unavailable"):
        build_editor_project(source)


@pytest.mark.parametrize("mismatch", ["shape", "material"])
def test_editor_asset_rejects_an_incompatible_preview_without_mutation(source_image: Path, mismatch: str) -> None:
    from api.editor_project import build_editor_project, decode_editor_project

    payload = build_editor_project(_session(source_image))
    fresh = _session(source_image)
    if mismatch == "shape":
        fresh["preview_cache"]["target_w"] = 7
    else:
        fresh["preview_cache"]["lut_metadata"].palette[0].material = "PLA"
    before = fresh["preview_cache"]["matched_rgb"].copy()
    with pytest.raises(ValueError, match="match|compatible"):
        decode_editor_project(payload, fresh)
    np.testing.assert_array_equal(fresh["preview_cache"]["matched_rgb"], before)


def test_editor_export_rejects_missing_applied_recipe_mask(source_image: Path) -> None:
    from api.editor_project import build_editor_project

    source = _session(source_image)
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


def test_editor_routes_restore_a_fresh_session_with_committed_selection(source_image: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from api.app import app
    from api.dependencies import get_file_registry, get_session_store
    from api.file_registry import FileRegistry

    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    source = _session(source_image)
    mask = source["editor_selection_mask"]
    source["preview_cache"]["matched_rgb"][mask] = [20, 210, 40]
    source["region_replacement_count"] = 1
    original = store.create()
    fresh = store.create()
    for key, value in source.items():
        store.put(original, key, value)
    for key, value in _session(source_image).items():
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


def test_editor_restore_route_rejects_different_source_before_session_mutation(source_image: Path) -> None:
    from fastapi.testclient import TestClient
    from api.app import app
    from api.dependencies import get_session_store
    from api.editor_project import build_editor_project
    from api.session_value_codec import encode_session_value

    payload = build_editor_project(_session(source_image))
    different = source_image.with_name("different.png")
    Image.new("RGB", (6, 4), (10, 40, 220)).save(different)
    fresh = _session(different)
    fresh["editor_selection_revision"] = 0
    fresh["editor_selection_mask"] = None
    store = SessionStore(ttl=1800)
    sid = store.create()
    for key, value in fresh.items():
        store.put(sid, key, value)
    before = encode_session_value(store.get(sid))
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_session_store] = lambda: store
    client = TestClient(app)
    try:
        response = client.post(
            f"/api/convert/editor-project/{sid}/restore",
            files={"file": ("editor.json.gz", payload, "application/gzip")},
            data={"operation_id": "wrong-source"},
        )
        assert response.status_code == 422, response.text
        assert "source" in response.json()["detail"]
        assert encode_session_value(store.get(sid)) == before
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        store.close(sid)
        client.close()
