from pathlib import Path

import numpy as np

from api.preview_cache_artifacts import (
    ARTIFACT_SCHEMA,
    PreviewCacheRevisionConflict,
    estimate_preview_cache_bytes,
    externalize_preview_cache,
    hydrate_preview_cache,
    hydrate_preview_cache_for_worker,
    is_preview_cache_artifact_ref,
    merge_preview_cache_metadata,
    persist_preview_cache,
    preview_cache_transaction,
    save_preview_cache_fields,
)
from api.session_store import SessionStore


def _make_cache() -> dict:
    matched_rgb = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)
    material_matrix = np.ones((2, 2, 2), dtype=np.int16)
    return {
        "matched_rgb": matched_rgb,
        "material_matrix": material_matrix,
        "mask_solid": np.ones((2, 2), dtype=bool),
        "target_w": 2,
        "target_h": 2,
        "color_palette": [{"hex": "#ffffff"}],
        "slot_names": ["white", "black"],
    }


def _make_cache_with_nested_metadata() -> dict:
    cache = _make_cache()
    cache["color_conf"] = {
        "slots": ["white", "black"],
        "preview": {"white": [255, 255, 255, 255]},
    }
    return cache


def test_externalize_preview_cache_writes_arrays_and_manifest(
    tmp_path: Path,
) -> None:
    store = SessionStore()
    session_id = store.create("sid-artifact")
    cache = _make_cache()

    ref = externalize_preview_cache(
        session_id,
        store,
        cache,
        root_dir=tmp_path,
    )

    assert is_preview_cache_artifact_ref(ref)
    assert ref["schema"] == ARTIFACT_SCHEMA
    assert ref["manifest_revision"] == 1
    assert set(ref["fields"]) == {
        "matched_rgb",
        "material_matrix",
        "mask_solid",
    }
    assert ref["metadata"]["target_w"] == 2
    assert ref["metadata"]["target_h"] == 2
    assert "matched_rgb" not in ref["metadata"]
    assert "material_matrix" not in ref["metadata"]

    tracked_paths = set(store.get_temp_file_paths(session_id))
    for field_name, field_ref in ref["fields"].items():
        field_path = Path(field_ref["path"])
        assert field_path.exists()
        assert field_path.parent == tmp_path
        assert str(field_path) in tracked_paths
        assert field_ref["revision"] == 1
        assert field_ref["nbytes"] == cache[field_name].nbytes
        assert field_ref["sha256"]
        np.testing.assert_array_equal(np.load(field_path), cache[field_name])


def test_save_preview_cache_fields_updates_only_dirty_field(
    tmp_path: Path,
) -> None:
    store = SessionStore()
    session_id = store.create("sid-dirty")
    ref = externalize_preview_cache(
        session_id,
        store,
        _make_cache(),
        root_dir=tmp_path,
    )
    original_matrix_field = dict(ref["fields"]["material_matrix"])
    new_rgb = np.full((2, 2, 3), 7, dtype=np.uint8)

    updated = save_preview_cache_fields(
        session_id,
        store,
        ref,
        {"matched_rgb": new_rgb},
    )

    assert updated["manifest_revision"] == 2
    assert updated["fields"]["matched_rgb"]["revision"] == 2
    assert updated["fields"]["matched_rgb"]["path"] != ref["fields"]["matched_rgb"]["path"]
    assert updated["fields"]["material_matrix"] == original_matrix_field
    np.testing.assert_array_equal(
        np.load(updated["fields"]["matched_rgb"]["path"]),
        new_rgb,
    )


def test_save_preview_cache_fields_preserves_old_path_while_mmap_reader_lives(
    tmp_path: Path,
) -> None:
    store = SessionStore()
    session_id = store.create("sid-dirty-mmap")
    cache = _make_cache()
    ref = externalize_preview_cache(
        session_id,
        store,
        cache,
        root_dir=tmp_path,
    )
    old_path = ref["fields"]["matched_rgb"]["path"]
    old_reader = np.load(old_path, mmap_mode="r", allow_pickle=False)
    new_rgb = np.full((2, 2, 3), 7, dtype=np.uint8)

    try:
        updated = save_preview_cache_fields(
            session_id,
            store,
            ref,
            {"matched_rgb": new_rgb},
        )

        new_path = updated["fields"]["matched_rgb"]["path"]
        assert new_path != old_path
        tracked_paths = set(store.get_temp_file_paths(session_id))
        assert old_path in tracked_paths
        assert new_path in tracked_paths
        np.testing.assert_array_equal(old_reader, cache["matched_rgb"])
        np.testing.assert_array_equal(
            np.load(old_path, allow_pickle=False),
            cache["matched_rgb"],
        )
        np.testing.assert_array_equal(
            np.load(new_path, allow_pickle=False),
            new_rgb,
        )
    finally:
        mmap_handle = getattr(old_reader, "_mmap", None)
        if mmap_handle is not None:
            mmap_handle.close()


def test_hydrate_preview_cache_loads_requested_fields_only(
    tmp_path: Path,
) -> None:
    store = SessionStore()
    session_id = store.create("sid-hydrate")
    cache = _make_cache()
    ref = externalize_preview_cache(
        session_id,
        store,
        cache,
        root_dir=tmp_path,
    )

    hydrated = hydrate_preview_cache(ref, fields={"matched_rgb"})

    assert hydrated["target_w"] == 2
    assert hydrated["target_h"] == 2
    assert "matched_rgb" in hydrated
    assert "material_matrix" not in hydrated
    np.testing.assert_array_equal(hydrated["matched_rgb"], cache["matched_rgb"])


def test_hydrate_preview_cache_deep_copies_nested_metadata(
    tmp_path: Path,
) -> None:
    store = SessionStore()
    session_id = store.create("sid-hydrate-metadata")
    ref = externalize_preview_cache(
        session_id,
        store,
        _make_cache_with_nested_metadata(),
        root_dir=tmp_path,
    )
    store.put(session_id, "preview_cache", ref)

    hydrated = hydrate_preview_cache(ref, fields=set())
    hydrated["slot_names"].append("red")
    hydrated["color_conf"]["slots"].append("red")
    hydrated["color_conf"]["preview"]["white"].append(0)

    stored_metadata = store.get(session_id)["preview_cache"]["metadata"]
    assert stored_metadata["slot_names"] == ["white", "black"]
    assert stored_metadata["color_conf"]["slots"] == ["white", "black"]
    assert stored_metadata["color_conf"]["preview"]["white"] == [
        255,
        255,
        255,
        255,
    ]


def test_hydrate_preview_cache_for_worker_uses_mmap_for_artifacts(
    tmp_path: Path,
) -> None:
    store = SessionStore()
    session_id = store.create("sid-worker-hydrate")
    cache = _make_cache()
    ref = externalize_preview_cache(
        session_id,
        store,
        cache,
        root_dir=tmp_path,
    )

    hydrated = hydrate_preview_cache_for_worker(ref)

    assert isinstance(hydrated["matched_rgb"], np.memmap)
    np.testing.assert_array_equal(hydrated["matched_rgb"], cache["matched_rgb"])


def test_estimate_preview_cache_bytes_includes_original_snapshots() -> None:
    assert estimate_preview_cache_bytes(
        width=10,
        height=5,
        layers=3,
        include_original=True,
    ) == 1750


def test_persist_preview_cache_keeps_artifact_session_externalized(
    tmp_path: Path,
) -> None:
    store = SessionStore()
    session_id = store.create("sid-persist")
    ref = externalize_preview_cache(
        session_id,
        store,
        _make_cache(),
        root_dir=tmp_path,
    )
    store.put(session_id, "preview_cache", ref)
    hydrated = hydrate_preview_cache(ref)
    hydrated["matched_rgb"] = np.full((2, 2, 3), 9, dtype=np.uint8)
    hydrated["glb_url"] = "/api/files/current"

    persisted = persist_preview_cache(session_id, store, hydrated)
    stored = store.get(session_id)["preview_cache"]

    assert is_preview_cache_artifact_ref(persisted)
    assert is_preview_cache_artifact_ref(stored)
    assert stored["metadata"]["glb_url"] == "/api/files/current"
    assert stored["fields"]["matched_rgb"]["revision"] == 2
    assert "matched_rgb" not in stored["metadata"]
    np.testing.assert_array_equal(
        np.load(stored["fields"]["matched_rgb"]["path"]),
        hydrated["matched_rgb"],
    )


def test_persist_preview_cache_preserves_legacy_session_shape() -> None:
    store = SessionStore()
    session_id = store.create("sid-legacy")
    cache = _make_cache()
    store.put(session_id, "preview_cache", cache)

    persisted = persist_preview_cache(session_id, store, cache)

    assert persisted is cache
    assert store.get(session_id)["preview_cache"] is cache


def test_preview_cache_transaction_hydrates_requested_fields_and_commits_dirty_only(
    tmp_path: Path,
) -> None:
    store = SessionStore()
    session_id = store.create("sid-transaction")
    ref = externalize_preview_cache(
        session_id,
        store,
        _make_cache(),
        root_dir=tmp_path,
    )
    store.put(session_id, "preview_cache", ref)
    session_data = store.get(session_id)
    new_rgb = np.full((2, 2, 3), 11, dtype=np.uint8)

    with preview_cache_transaction(
        session_id,
        store,
        session_data,
        fields={"matched_rgb"},
    ) as cache:
        assert "matched_rgb" in cache
        assert "material_matrix" not in cache
        cache["matched_rgb"] = new_rgb
        updated = cache.commit({"matched_rgb"})

    stored = store.get(session_id)["preview_cache"]
    assert stored == updated
    assert stored["fields"]["matched_rgb"]["revision"] == 2
    assert stored["fields"]["material_matrix"]["revision"] == 1
    np.testing.assert_array_equal(
        np.load(stored["fields"]["matched_rgb"]["path"]),
        new_rgb,
    )


def test_preview_cache_transaction_preserves_concurrent_metadata(
    tmp_path: Path,
) -> None:
    store = SessionStore()
    session_id = store.create("sid-transaction-metadata")
    ref = externalize_preview_cache(
        session_id,
        store,
        _make_cache(),
        root_dir=tmp_path,
    )
    store.put(session_id, "preview_cache", ref)
    session_data = store.get(session_id)

    with preview_cache_transaction(
        session_id,
        store,
        session_data,
        fields={"matched_rgb"},
    ) as cache:
        latest_ref = store.get(session_id)["preview_cache"]
        store.put(
            session_id,
            "preview_cache",
            merge_preview_cache_metadata(
                latest_ref,
                {"glb_url": "/api/files/glb-current"},
            ),
        )
        cache["matched_rgb"] = np.full((2, 2, 3), 13, dtype=np.uint8)
        updated = cache.commit({"matched_rgb"})

    assert updated["metadata"]["glb_url"] == "/api/files/glb-current"
    assert store.get(session_id)["preview_cache"]["metadata"]["glb_url"] == (
        "/api/files/glb-current"
    )


def test_preview_cache_transaction_commits_explicit_metadata_fields(
    tmp_path: Path,
) -> None:
    store = SessionStore()
    session_id = store.create("sid-transaction-explicit-metadata")
    ref = externalize_preview_cache(
        session_id,
        store,
        _make_cache(),
        root_dir=tmp_path,
    )
    store.put(session_id, "preview_cache", ref)
    session_data = store.get(session_id)

    with preview_cache_transaction(
        session_id,
        store,
        session_data,
        fields={"matched_rgb"},
    ) as cache:
        latest_ref = store.get(session_id)["preview_cache"]
        store.put(
            session_id,
            "preview_cache",
            merge_preview_cache_metadata(
                latest_ref,
                {"glb_job_token": "job-1"},
            ),
        )
        cache["matched_rgb"] = np.full((2, 2, 3), 23, dtype=np.uint8)
        cache["color_palette"] = [{"hex": "#171717"}]
        updated = cache.commit(
            {"matched_rgb"},
            metadata_fields={"color_palette"},
        )

    assert updated["metadata"]["glb_job_token"] == "job-1"
    assert updated["metadata"]["color_palette"] == [{"hex": "#171717"}]


def test_preview_cache_transaction_rejects_dirty_field_revision_conflict(
    tmp_path: Path,
) -> None:
    store = SessionStore()
    session_id = store.create("sid-transaction-conflict")
    ref = externalize_preview_cache(
        session_id,
        store,
        _make_cache(),
        root_dir=tmp_path,
    )
    store.put(session_id, "preview_cache", ref)
    session_data = store.get(session_id)
    concurrent_rgb = np.full((2, 2, 3), 17, dtype=np.uint8)

    with preview_cache_transaction(
        session_id,
        store,
        session_data,
        fields={"matched_rgb"},
    ) as cache:
        latest_ref = store.get(session_id)["preview_cache"]
        concurrent_ref = save_preview_cache_fields(
            session_id,
            store,
            latest_ref,
            {"matched_rgb": concurrent_rgb},
        )
        store.put(session_id, "preview_cache", concurrent_ref)
        cache["matched_rgb"] = np.full((2, 2, 3), 19, dtype=np.uint8)

        try:
            cache.commit({"matched_rgb"})
        except PreviewCacheRevisionConflict as exc:
            assert "matched_rgb" in str(exc)
        else:
            raise AssertionError("Expected matched_rgb revision conflict")

    stored = store.get(session_id)["preview_cache"]
    assert stored["fields"]["matched_rgb"]["revision"] == 2
    np.testing.assert_array_equal(
        np.load(stored["fields"]["matched_rgb"]["path"]),
        concurrent_rgb,
    )


def test_preview_cache_transaction_conflict_does_not_leak_nested_metadata(
    tmp_path: Path,
) -> None:
    store = SessionStore()
    session_id = store.create("sid-transaction-metadata-conflict")
    ref = externalize_preview_cache(
        session_id,
        store,
        _make_cache_with_nested_metadata(),
        root_dir=tmp_path,
    )
    store.put(session_id, "preview_cache", ref)
    session_data = store.get(session_id)
    concurrent_rgb = np.full((2, 2, 3), 17, dtype=np.uint8)

    with preview_cache_transaction(
        session_id,
        store,
        session_data,
        fields={"matched_rgb"},
    ) as cache:
        latest_ref = store.get(session_id)["preview_cache"]
        concurrent_ref = save_preview_cache_fields(
            session_id,
            store,
            latest_ref,
            {"matched_rgb": concurrent_rgb},
        )
        store.put(session_id, "preview_cache", concurrent_ref)
        cache["matched_rgb"] = np.full((2, 2, 3), 19, dtype=np.uint8)
        cache["color_conf"]["slots"].append("red")

        try:
            cache.commit(
                {"matched_rgb"},
                metadata_fields={"color_conf"},
            )
        except PreviewCacheRevisionConflict:
            pass
        else:
            raise AssertionError("Expected matched_rgb revision conflict")

    stored_metadata = store.get(session_id)["preview_cache"]["metadata"]
    assert stored_metadata["color_conf"]["slots"] == ["white", "black"]
