"""Durable actual-data and replay regression tests."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import pytest

from core.backed_gradient_store import (
    BackedGradientConflictError, BackedGradientStore, THICKNESSES_MM,
)
from core.errors import CoreValidationError


def capture(*, symbol="Y", backing="W", thickness=.08, measurement_id="manual-1", values=None):
    return {"capture_id": "batch-a", "material_symbol": symbol, "backing": backing,
            "sample_role": "bare_backing" if thickness == 0 else "coated", "overlay_mm": thickness,
            "measurement_id": measurement_id, "reflectance_percent_xyz": values or [101.250001, 0, 3.4]}


@pytest.fixture
def store(tmp_path):
    return BackedGradientStore(tmp_path)


@pytest.fixture
def dataset(store):
    return store.create({"name": "real-backed-cards", "brand": "KYNIX", "batch": "new", "materials": {"Y": "yellow"}})


def test_actual_geometry_zero_and_over_reference_are_lossless(store, dataset):
    for i, thickness in enumerate(THICKNESSES_MM):
        record, duplicate, _ = store.save_capture(dataset["dataset_id"], capture(thickness=thickness, measurement_id=f"m-{i}"))
        assert record["backing_mm"] == round(3 - thickness, 2)
        assert record["total_mm"] == 3
        assert record["reflectance_percent_xyz"] == [101.250001, 0, 3.4]
        assert record["capture_context"]["batch"] == "new"
        assert not duplicate
    assert len(BackedGradientStore(store.root).get(dataset["dataset_id"])["captures"]) == 7


def test_device_auto_raw_frame_and_bare_role_remain_separate(store, dataset):
    body = capture(symbol="K", backing="K", thickness=0)
    body.pop("measurement_id")
    body.pop("reflectance_percent_xyz")
    frame = {"protocol": "lumina-box", "version": 2, "type": "measurement", "measurement_id": "native-1",
             "mode": "auto", "thickness_mm": 1.28, "reflectance_xyz": [0, 0, 0],
             "transmittance_xyz": [0, 1, 100], "thickness_schedule_id": "backed_gradient_7/v1"}
    body["measurement"] = frame
    record, _, _ = store.save_capture(dataset["dataset_id"], body)
    assert record["device_measurement"] == frame
    assert record["overlay_mm"] == 0 and record["backing_mm"] == 3
    assert record["reflectance_percent_xyz"] == [0, 0, 0]


def test_replay_is_idempotent_and_never_replaces_selected_history(store, dataset):
    identity = dataset["dataset_id"]
    first = store.save_capture(identity, capture())[0]
    latest = store.save_capture(identity, capture(measurement_id="next", values=[80, 50, 10]))[0]
    assert len(store.get(identity)["captures"]) == 2
    store.select(identity, first["record_id"])
    assert store.save_capture(identity, capture(measurement_id="next", values=[80, 50, 10]))[1]
    assert store.get(identity)["selected_capture_ids"]["Y:W:0.08"] == first["record_id"]
    changed = capture(backing="K")
    with pytest.raises(BackedGradientConflictError):
        store.save_capture(identity, changed)
    store.delete_capture(identity, first["record_id"])
    assert store.get(identity)["selected_capture_ids"]["Y:W:0.08"] == latest["record_id"]
    with pytest.raises(BackedGradientConflictError):
        store.save_capture(identity, capture())


def test_simultaneous_replay_commits_exactly_once(store, dataset):
    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(lambda _: store.save_capture(dataset["dataset_id"], capture()), range(8)))
    assert sum(not outcome[1] for outcome in outcomes) == 1
    assert len(store.get(dataset["dataset_id"])["captures"]) == 1


@pytest.mark.parametrize("field,value", [
    ("overlay_mm", .4), ("overlay_mm", True), ("backing", "ideal_white"),
    ("material_symbol", "unknown"), ("reflectance_percent_xyz", [1, -1, 3]),
    ("reflectance_percent_xyz", [1, True, 3]), ("reflectance_percent_xyz", [1, "2", 3]),
    ("reflectance_percent_xyz", [1, float("inf"), 3]), ("received_at", "2026-10-06T10:00:00"),
])
def test_invalid_capture_does_not_change_revision(store, dataset, field, value):
    body = capture()
    body[field] = value
    with pytest.raises(CoreValidationError):
        store.save_capture(dataset["dataset_id"], body)
    assert store.get(dataset["dataset_id"])["revision"] == 0


def test_export_import_preserves_raw_history_selection_and_deleted_receipts(store, dataset, tmp_path):
    identity = dataset["dataset_id"]
    original = store.save_capture(identity, capture())[0]
    store.save_capture(identity, capture(measurement_id="next"))
    store.delete_capture(identity, original["record_id"])
    portable = store.export(identity)
    restored = BackedGradientStore(tmp_path / "other-library")
    imported = restored.import_document(portable)
    assert imported == store.get(identity)
    assert restored.import_document(portable) == imported
    with pytest.raises(BackedGradientConflictError):
        restored.save_capture(identity, capture())
    assert restored.save_capture(identity, capture(measurement_id="next"))[1]


def test_invalid_import_is_atomic_and_old_export_cannot_undo_current_choice(store, dataset, tmp_path):
    identity = dataset["dataset_id"]
    first = store.save_capture(identity, capture())[0]
    portable = store.export(identity)
    newest = store.save_capture(identity, capture(measurement_id="newer", values=[30, 20, 10]))[0]
    store.import_document(portable)
    assert store.get(identity)["selected_capture_ids"]["Y:W:0.08"] == newest["record_id"]
    altered = deepcopy(portable)
    altered["dataset"]["captures"][0]["backing_mm"] = 3
    with pytest.raises(CoreValidationError):
        store.import_document(altered)
    assert len(store.get(identity)["captures"]) == 2
    other = BackedGradientStore(tmp_path / "empty")
    with pytest.raises(CoreValidationError):
        other.import_document(altered)
    assert not other.database.exists()
    deleted_portable = deepcopy(portable)
    store.delete_capture(identity, first["record_id"])
    store.import_document(deleted_portable)
    assert all(record["record_id"] != first["record_id"] for record in store.get(identity)["captures"])


def test_snapshot_frozen_geometry_and_hash_change_only_on_selection(store, dataset):
    identity = dataset["dataset_id"]
    for symbol, values in [("W", [97, 98, 99]), ("K", [0, 0, .1])]:
        store.save_capture(identity, capture(symbol=symbol, backing=symbol, thickness=0, measurement_id=f"bare-{symbol}", values=values))
    store.save_capture(identity, capture(thickness=.24))
    frozen = store.snapshot(identity)
    assert frozen["reference_anchors"] == {"W": [97, 98, 99], "K": [0, 0, .1]}
    assert frozen["samples"][0]["overlay_mm"] == .24
    assert frozen["conditions"]["total_mm"] == 3
    assert store.snapshot(identity) == frozen
    store.save_capture(identity, capture(measurement_id="next"))
    assert store.snapshot(identity)["input_hash"] != frozen["input_hash"]
    assert len(frozen["samples"]) == 1


def test_late_progress_cannot_downgrade_terminal_job(store, dataset):
    run = {"fit_id": str(uuid4()), "dataset_id": dataset["dataset_id"], "status": "complete", "progress": 1}
    store.save_run(run)
    store.save_run({**run, "status": "running", "progress": .5})
    assert store.get_run(run["fit_id"])["status"] == "complete"
    store.save_run({**run, "status": "failed", "stage": "interrupted"})
    assert store.get_run(run["fit_id"])["status"] == "complete"


def test_invalid_unicode_is_rejected_before_storage(tmp_path):
    local = BackedGradientStore(tmp_path / "unused")
    with pytest.raises(CoreValidationError, match="UTF-8"):
        local.create({"name": "\ud800"})
    assert not local.database.exists()


def test_noncanonical_import_id_is_rejected(store, dataset):
    document = store.export(dataset["dataset_id"])
    document["dataset"]["dataset_id"] = dataset["dataset_id"].upper()
    with pytest.raises(CoreValidationError, match="canonical"):
        store.import_document(document)
