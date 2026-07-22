from pathlib import Path

import numpy as np
import pytest

from api import preview_cache_artifacts
from api.preview_cache_artifacts import (
    ARTIFACT_SCHEMA,
    PreviewCacheRevisionConflict,
    estimate_preview_cache_bytes,
    externalize_preview_cache,
    get_preview_cache_max_bytes,
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
        stored = np.load(field_path)
        assert field_ref["nbytes"] == stored.nbytes
        assert field_ref["sha256"]
        np.testing.assert_array_equal(stored, cache[field_name])


def test_externalize_preview_cache_reuses_artifact_for_same_array_object(
    tmp_path: Path,
) -> None:
    store = SessionStore()
    session_id = store.create("sid-artifact-alias")
    cache = _make_cache()
    cache["original_matched_rgb"] = cache["matched_rgb"]
    cache["height_identity_rgb"] = cache["matched_rgb"]
    cache["original_material_matrix"] = cache["material_matrix"]

    ref = externalize_preview_cache(
        session_id,
        store,
        cache,
        root_dir=tmp_path,
    )

    assert ref["fields"]["original_matched_rgb"]["path"] == (
        ref["fields"]["matched_rgb"]["path"]
    )
    assert ref["fields"]["height_identity_rgb"]["path"] == (
        ref["fields"]["original_matched_rgb"]["path"]
    )
    assert ref["fields"]["original_material_matrix"]["path"] == (
        ref["fields"]["material_matrix"]["path"]
    )
    assert len(store.get_temp_file_paths(session_id)) == 3


def test_replaced_cache_separates_current_but_aliases_pristine_identity(
    tmp_path: Path,
) -> None:
    """Artifact bytes match the guard when only current replacement arrays split."""

    store = SessionStore()
    session_id = store.create("sid-artifact-replaced-alias")
    cache = _make_cache()
    pristine_rgb = cache["matched_rgb"]
    pristine_matrix = cache["material_matrix"]
    cache["matched_rgb"] = np.full_like(pristine_rgb, 42)
    cache["material_matrix"] = np.full_like(pristine_matrix, 2)
    cache["original_matched_rgb"] = pristine_rgb
    cache["height_identity_rgb"] = pristine_rgb
    cache["original_material_matrix"] = pristine_matrix
    cache["preview_rgba"] = np.zeros((2, 2, 4), dtype=np.uint8)

    ref = externalize_preview_cache(
        session_id,
        store,
        cache,
        root_dir=tmp_path,
    )

    fields = ref["fields"]
    assert fields["matched_rgb"]["path"] != fields["original_matched_rgb"]["path"]
    assert fields["height_identity_rgb"]["path"] == fields["original_matched_rgb"]["path"]
    assert fields["material_matrix"]["path"] != fields["original_material_matrix"]["path"]
    unique_refs = {
        field_ref["path"]: field_ref
        for field_ref in fields.values()
    }
    actual_bytes = sum(int(field_ref["nbytes"]) for field_ref in unique_refs.values())
    assert actual_bytes == estimate_preview_cache_bytes(
        width=2,
        height=2,
        layers=2,
        include_original=True,
        matrix_itemsize=1,
    )

    store.put(session_id, "preview_cache", ref)
    session_data = store.get(session_id)
    new_rgb = np.full((2, 2, 3), 21, dtype=np.uint8)
    original_rgb_path = ref["fields"]["original_matched_rgb"]["path"]

    with preview_cache_transaction(
        session_id,
        store,
        session_data,
        fields={"matched_rgb"},
    ) as transaction:
        transaction["matched_rgb"] = new_rgb
        transaction.commit({"matched_rgb"})

    stored = store.get(session_id)["preview_cache"]
    assert stored["fields"]["matched_rgb"]["path"] != original_rgb_path
    assert stored["fields"]["original_matched_rgb"]["path"] == original_rgb_path
    np.testing.assert_array_equal(
        np.load(stored["fields"]["matched_rgb"]["path"]),
        new_rgb,
    )
    np.testing.assert_array_equal(
        np.load(stored["fields"]["original_matched_rgb"]["path"]),
        pristine_rgb,
    )


def test_externalize_preview_cache_compacts_material_matrix_artifacts(
    tmp_path: Path,
) -> None:
    store = SessionStore()
    session_id = store.create("sid-artifact-compact-material")
    material_matrix = np.array(
        [
            [[-1, 0], [1, 2]],
            [[3, 4], [5, 7]],
        ],
        dtype=np.int32,
    )
    cache = {
        "matched_rgb": np.zeros((2, 2, 3), dtype=np.uint8),
        "material_matrix": material_matrix,
        "original_material_matrix": material_matrix,
        "mask_solid": np.ones((2, 2), dtype=bool),
        "target_w": 2,
        "target_h": 2,
    }

    ref = externalize_preview_cache(
        session_id,
        store,
        cache,
        root_dir=tmp_path,
    )

    material_ref = ref["fields"]["material_matrix"]
    original_ref = ref["fields"]["original_material_matrix"]
    assert material_ref["path"] == original_ref["path"]
    assert material_ref["dtype"] == "int8"
    assert material_ref["nbytes"] == material_matrix.size
    stored = np.load(material_ref["path"])
    assert stored.dtype == np.dtype(np.int8)
    np.testing.assert_array_equal(stored, material_matrix.astype(np.int8))


def test_externalize_preview_cache_preserves_material_archive_index_capacity(
    tmp_path: Path,
) -> None:
    store = SessionStore()
    session_id = store.create("sid-artifact-material-archive-capacity")
    material_matrix = np.zeros((2, 2, 2), dtype=np.int32)
    cache = {
        "matched_rgb": np.zeros((2, 2, 3), dtype=np.uint8),
        "material_matrix": material_matrix,
        "mask_solid": np.ones((2, 2), dtype=bool),
        "target_w": 2,
        "target_h": 2,
        "material_source": "material_archive",
        "selected_material_count": 200,
    }

    ref = externalize_preview_cache(
        session_id,
        store,
        cache,
        root_dir=tmp_path,
    )

    material_ref = ref["fields"]["material_matrix"]
    assert material_ref["dtype"] == "int16"
    stored = np.load(material_ref["path"])
    assert stored.dtype == np.dtype(np.int16)

    stored[0, 0] = np.array([0, 199], dtype=stored.dtype)
    assert stored[0, 0].tolist() == [0, 199]


def test_externalize_preview_cache_cleans_partial_artifacts_on_write_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original_write = preview_cache_artifacts._write_new_array_field
    write_count = 0

    def fail_after_first_array(
        field_name: str,
        array: np.ndarray,
        artifact_dir: Path,
        *,
        revision: int = 1,
    ) -> tuple[str, dict]:
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            raise OSError("simulated artifact write failure")
        return original_write(
            field_name,
            array,
            artifact_dir,
            revision=revision,
        )

    monkeypatch.setattr(
        preview_cache_artifacts,
        "_write_new_array_field",
        fail_after_first_array,
    )

    try:
        preview_cache_artifacts.externalize_preview_cache_to_artifacts(
            _make_cache(),
            root_dir=tmp_path,
        )
    except OSError as exc:
        assert "simulated artifact write failure" in str(exc)
    else:
        raise AssertionError("Expected artifact write failure")

    assert list(tmp_path.iterdir()) == []


def test_externalize_preview_cache_cleans_artifact_when_ref_build_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_hash(array: np.ndarray) -> str:
        raise RuntimeError("simulated artifact hash failure")

    monkeypatch.setattr(preview_cache_artifacts, "_array_sha256", fail_hash)

    try:
        preview_cache_artifacts.externalize_preview_cache_to_artifacts(
            _make_cache(),
            root_dir=tmp_path,
        )
    except RuntimeError as exc:
        assert "simulated artifact hash failure" in str(exc)
    else:
        raise AssertionError("Expected artifact hash failure")

    assert list(tmp_path.iterdir()) == []


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


def test_estimate_preview_cache_bytes_accepts_compact_matrix_itemsize() -> None:
    legacy_int32 = estimate_preview_cache_bytes(
        width=10,
        height=5,
        layers=3,
        include_original=True,
    )
    compact_int16 = estimate_preview_cache_bytes(
        width=10,
        height=5,
        layers=3,
        include_original=True,
        matrix_itemsize=2,
    )

    assert legacy_int32 == 1750
    assert compact_int16 == 1150


def test_preview_cache_max_bytes_disabled_by_default(monkeypatch) -> None:
    """Preview cache guardrail is opt-in; unset env disables rejection."""
    monkeypatch.delenv("LUMINA_PREVIEW_CACHE_MAX_BYTES", raising=False)

    assert get_preview_cache_max_bytes() is None


def test_preview_cache_max_bytes_disabled_for_invalid_or_non_positive_env(
    monkeypatch,
) -> None:
    """Invalid, zero, and negative values disable the optional guardrail."""
    for raw in ("", "not-a-number", "0", "-1"):
        monkeypatch.setenv("LUMINA_PREVIEW_CACHE_MAX_BYTES", raw)
        assert get_preview_cache_max_bytes() is None


def test_preview_cache_max_bytes_uses_positive_env(monkeypatch) -> None:
    """A positive env value explicitly enables the guardrail."""
    monkeypatch.setenv("LUMINA_PREVIEW_CACHE_MAX_BYTES", "1073741824")

    assert get_preview_cache_max_bytes() == 1073741824


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


def test_in_memory_preview_cache_transactions_are_isolated_and_use_cas() -> None:
    store = SessionStore()
    session_id = store.create()
    original = {
        "matched_rgb": np.zeros((1, 1, 3), dtype=np.uint8),
        "material_dynamic_layer_info": {"colors": [{"target_srgb": [1, 2, 3]}]},
    }
    store.put(session_id, "preview_cache", original)
    session_data = store.get(session_id)
    assert session_data is not None

    first_context = preview_cache_transaction(
        session_id,
        store,
        session_data,
        fields={"matched_rgb"},
    )
    second_context = preview_cache_transaction(
        session_id,
        store,
        session_data,
        fields={"matched_rgb"},
    )
    first = first_context.__enter__()
    second = second_context.__enter__()
    try:
        first["matched_rgb"][0, 0] = [10, 20, 30]
        first["material_dynamic_layer_info"]["colors"][0]["target_srgb"] = [4, 5, 6]
        assert original["matched_rgb"][0, 0].tolist() == [0, 0, 0]
        assert original["material_dynamic_layer_info"]["colors"][0][
            "target_srgb"
        ] == [1, 2, 3]
        first.commit({"matched_rgb"})

        second["matched_rgb"][0, 0] = [99, 99, 99]
        with pytest.raises(PreviewCacheRevisionConflict):
            second.commit({"matched_rgb"})
    finally:
        first_context.__exit__(None, None, None)
        second_context.__exit__(None, None, None)

    committed = store.get(session_id)["preview_cache"]
    assert committed["matched_rgb"][0, 0].tolist() == [10, 20, 30]
    assert committed["material_dynamic_layer_info"]["colors"][0][
        "target_srgb"
    ] == [4, 5, 6]
