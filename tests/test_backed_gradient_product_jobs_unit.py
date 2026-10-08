"""Shared backing publication, recovery, and per-group job coordination."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import threading
from uuid import uuid4

import pytest

from api import backed_gradient_jobs as jobs
from api import backed_gradient_product_jobs as product_jobs
from core.backed_gradient_archive import load_backed_gradient_archive, save_backed_gradient_material_archive
from core.backed_gradient_fitting_v2 import _initial, _slices
from core.backed_gradient_material import BackedGradientComponent, reference_from_parameters
from core.backed_gradient_product_store import (
    create_backing_dataset, create_material_dataset, get_backing_reference, latest_backing_reference,
    list_backing_references, material_group_snapshot, material_snapshot, save_backing_reference,
)
from core.backed_gradient_smooth import BackedGradientSmoothTransport, SPECTRAL_SMOOTH_MODEL_ID
from core.backed_gradient_store import BackedGradientConflictError, BackedGradientStore, THICKNESSES_MM
from core.errors import CoreProcessingError


def _write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def _capture(store, dataset_id, symbol, backing, thickness):
    return store.save_capture(dataset_id, {
        "capture_id": "group-test", "measurement_id": str(uuid4()), "material_symbol": symbol,
        "backing": backing, "overlay_mm": thickness, "sample_role": "coated",
        "reflectance_percent_xyz": [30., 20., 10.],
    })[0]


def _fit(snapshot, reference):
    return {**{key: snapshot[key] for key in ("dataset_id", "dataset_revision", "input_hash", "material_symbol")},
            "optical_model_id": SPECTRAL_SMOOTH_MODEL_ID, "fit_mode": "material", "converged": True,
            "component": BackedGradientComponent("color", tuple(_initial(("R",), 0))).to_dict(),
            "reference": deepcopy(reference), "rmse_pp": .2}


@pytest.fixture
def group(tmp_path):
    store = BackedGradientStore(tmp_path / "library")
    backing = create_backing_dataset(store, {"name": "Backings", "white_name": "White", "black_name": "Black"})
    rows = [_capture(store, backing["dataset_id"], symbol, backing_symbol, thickness)
            for symbol, backing_symbol in (("W", "K"), ("K", "W")) for thickness in THICKNESSES_MM]
    vector = _initial(("W", "K"), 0)
    operator = BackedGradientSmoothTransport(
        {symbol: vector[part] for symbol, part in _slices(("W", "K")).items()},
        {"W": [97., 98., 99.], "K": [0., 0., 0.]}, fitted_materials=("W", "K"),
    )
    reference = reference_from_parameters(operator.to_parameters(), source={
        "dataset_id": backing["dataset_id"], "backing_id": backing["dataset_id"],
        "backing_samples": rows, "established": False,
    }).to_dict()
    saved = save_backing_reference(store, reference, "Backings")
    snapshots, archives = [], []
    for index, symbol in enumerate(("R", "B", "Y")):
        dataset = create_material_dataset(store, {"name": symbol, "brand": "Test", "material_symbol": symbol,
                                                   "reference_id": saved["reference_id"]})
        for backing_symbol in ("W", "K"):
            for thickness in THICKNESSES_MM:
                _capture(store, dataset["dataset_id"], symbol, backing_symbol, thickness)
        snapshot = material_snapshot(store, dataset["dataset_id"])
        snapshots.append(snapshot)
        if index < 2:
            archive = save_backed_gradient_material_archive(
                material_name=symbol, brand="Test", measurement_payload=snapshot,
                fit_payload=_fit(snapshot, reference), materials_dir=str(store.root),
            )
            archives.append(Path(archive.archive_path).parent)
    selected = snapshots[-1]
    grouped, members = material_group_snapshot(store, selected)
    directory = store.results_root / str(uuid4())
    frozen = {**selected, "group": grouped, "group_material_snapshots": members}
    _write(directory / "input.json", frozen)
    newer = deepcopy(reference)
    newer["reference_id"] = "new-reference-version"
    newer["source"]["material_inputs"] = [
        {key: snapshot[key] for key in ("dataset_id", "material_symbol", "capture_reference_id")}
        for snapshot in members
    ]
    fits = {f"{member['dataset_id']}:{member['material_symbol']}": _fit(member, newer) for member in members}
    result = {**fits[f"{selected['dataset_id']}:{selected['material_symbol']}"], "group_fits": fits,
              "group_input_hash": grouped["input_hash"]}
    run = {"fit_id": directory.name, "fit_mode": "material", "status": "running",
           **{key: selected[key] for key in ("dataset_id", "dataset_revision", "input_hash", "material_symbol", "backing_id")},
           "reference_id": saved["reference_id"], "capture_reference_id": saved["reference_id"]}
    store.save_run(run)
    return store, saved, snapshots, archives, run, directory, result


def _library_bytes(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*")
            if path.is_file() and not any(part.startswith(".") for part in path.relative_to(root).parts)}


def test_group_publishes_saved_members_only_and_restores_old_capture_reference(group):
    store, original, snapshots, archives, run, directory, result = group
    photo = store.root / "Photo" / "material.json"
    _write(photo, {"material_name": "Photo", "optical_model": "gradient", "notes": "camera data"})
    original_photo = photo.read_bytes()
    other_reference = deepcopy(original["reference"])
    other_reference["reference_id"] = "other-backing-reference"
    other_reference["source"]["backing_id"] = "other-physical-backings"
    other_archive = save_backed_gradient_material_archive(
        material_name="Other Red", brand="Other", measurement_payload=snapshots[0],
        fit_payload=_fit(snapshots[0], other_reference), materials_dir=str(store.root),
    )
    other_directory = Path(other_archive.archive_path).parent
    other_before = _library_bytes(other_directory)
    main = json.loads((archives[0] / "material.json").read_text(encoding="utf-8"))
    main["user_metadata"] = {"kept": True}
    _write(archives[0] / "material.json", main)
    before = [load_backed_gradient_archive(path)[2] for path in archives]

    product_jobs.publish_group_materials(store, run, directory, result)

    assert len(list_backing_references(store)) == 1
    newest = list_backing_references(store)[0]
    assert newest["reference_id"] == "new-reference-version" and newest["version"] == 2
    assert newest["backing_id"] == original["backing_id"]
    assert get_backing_reference(store, original["reference_id"]) == original
    assert latest_backing_reference(store, original["reference_id"]) == newest
    assert photo.read_bytes() == original_photo
    assert _library_bytes(other_directory) == other_before
    assert not (store.root / "Test" / "Y").exists()
    assert len(run["updated_materials"]) == 2
    for index, path in enumerate(archives):
        main, _, fitted = load_backed_gradient_archive(path)
        assert fitted["reference"]["reference_id"] == newest["reference_id"]
        history = list((path / ".history").glob("*/lumina_box_backed_gradient_parameters.json"))
        assert len(history) == 1
        assert json.loads(history[0].read_text(encoding="utf-8"))["fit"] == before[index]
        if index == 0:
            assert main["user_metadata"] == {"kept": True}
    restored_store = BackedGradientStore(store.root)
    for snapshot in snapshots:
        restored = material_snapshot(restored_store, snapshot["dataset_id"])
        assert restored["capture_reference_id"] == original["reference_id"]
        assert restored["reference_id"] == newest["reference_id"]
        latest = restored_store.list_runs(snapshot["dataset_id"])[0]
        assert latest["reference_id"] == original["reference_id"]
        assert latest["capture_reference_id"] == original["reference_id"]
        assert latest["fitted_reference_id"] == newest["reference_id"]


@pytest.mark.parametrize("failure", ["invalid_fit", "stage", "swap"])
def test_failed_group_publication_keeps_all_prior_archives_and_reference(group, monkeypatch, failure):
    store, original, snapshots, _, run, directory, result = group
    before = _library_bytes(store.root)
    if failure == "invalid_fit":
        next(iter(result["group_fits"].values()))["converged"] = False
    elif failure == "stage":
        from core import backed_gradient_archive
        real_save = backed_gradient_archive.save_backed_gradient_material_archive
        count = 0

        def failing_save(**kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("simulated disk failure")
            return real_save(**kwargs)

        monkeypatch.setattr(backed_gradient_archive, "save_backed_gradient_material_archive", failing_save)
    else:
        real_replace = product_jobs.os.replace
        count = 0

        def failing_swap(source, target):
            nonlocal count
            if "materials" in Path(source).parts and Path(target).parent == store.root / "Test":
                count += 1
                if count == 2:
                    raise OSError("simulated group swap failure")
            return real_replace(source, target)

        monkeypatch.setattr(product_jobs.os, "replace", failing_swap)
    with pytest.raises((OSError, CoreProcessingError)):
        product_jobs.publish_group_materials(store, run, directory, result)
    assert _library_bytes(store.root) == before
    assert list_backing_references(store) == [original]
    assert store.get_run(run["fit_id"])["status"] == "running"
    assert all(not store.list_runs(snapshot["dataset_id"]) for snapshot in snapshots[:-1])


def test_same_reference_identity_cannot_overwrite_saved_contents(group):
    store, original, *_ = group
    changed = deepcopy(original["reference"])
    changed["anchors"]["W"][0] -= 1.
    with pytest.raises(BackedGradientConflictError, match="different saved version"):
        save_backing_reference(store, changed, original["name"])
    assert get_backing_reference(store, original["reference_id"]) == original


def test_same_backing_jobs_are_serialized_and_lock_released_after_cancel(group):
    store, _, snapshots, *_ = group

    class WaitingPool:
        async def submit(self, *args):
            await asyncio.Event().wait()

    async def scenario():
        first = jobs.start_material_fit(store, WaitingPool(), snapshots[0]["dataset_id"])
        with pytest.raises(BackedGradientConflictError, match="share a backing"):
            jobs.start_material_fit(store, WaitingPool(), snapshots[1]["dataset_id"])
        await asyncio.sleep(0)
        await jobs.cancel_backed_gradient_jobs()
        assert store.get_run(first["fit_id"])["status"] == "failed"
        next_run = jobs.start_material_fit(store, WaitingPool(), snapshots[1]["dataset_id"])
        await asyncio.sleep(0)
        await jobs.cancel_backed_gradient_jobs()
        assert store.get_run(next_run["fit_id"])["status"] == "failed"

    asyncio.run(scenario())


def test_shutdown_waits_for_group_publication_and_preserves_completed_state(group, monkeypatch):
    store, _, _, archives, run, directory, result = group
    real_publish = product_jobs.publish_group_materials
    release = threading.Event()

    async def scenario():
        entered = asyncio.Event()
        loop = asyncio.get_running_loop()

        async def fitted(*args):
            _write(directory / "result.json", result)
            return result

        def delayed_publish(*args):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5.)
            return real_publish(*args)

        monkeypatch.setattr(product_jobs, "execute_product_fit", fitted)
        monkeypatch.setattr(product_jobs, "publish_group_materials", delayed_publish)
        task = asyncio.create_task(jobs._execute(store, None, run, directory))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2.)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert store.get_run(run["fit_id"])["status"] == "complete"
    assert list_backing_references(store)[0]["reference_id"] == "new-reference-version"
    assert all(load_backed_gradient_archive(path)[2]["reference"]["reference_id"] == "new-reference-version" for path in archives)


def test_failed_fit_records_failure_without_publishing_group(group, monkeypatch):
    store, original, _, _, run, directory, result = group
    before = _library_bytes(store.root)
    result["converged"] = False

    async def unsuccessful(*args):
        _write(directory / "result.json", result)
        return result

    monkeypatch.setattr(product_jobs, "execute_product_fit", unsuccessful)
    asyncio.run(jobs._execute(store, None, run, directory))
    assert store.get_run(run["fit_id"])["status"] == "failed"
    assert list_backing_references(store) == [original]
    assert _library_bytes(store.root) == before


@pytest.mark.parametrize("established,rmse,expected", [
    (False, .2, ["material_group"]), (True, .2, ["material"]), (True, 2.5, ["material", "material_group"]),
])
def test_existing_references_keep_fast_path_and_bootstrap_or_mismatch_refine_group(group, established, rmse, expected):
    store, _, _, _, run, directory, result = group
    frozen = json.loads((directory / "input.json").read_text(encoding="utf-8"))
    frozen["reference"]["source"]["established"] = established
    _write(directory / "input.json", frozen)
    modes = []

    class ModesPool:
        async def submit(self, function, input_path, output, mode):
            modes.append(mode)
            payload = deepcopy(result)
            payload["rmse_pp"] = rmse if mode == "material" else .2
            _write(Path(output) / "result.json", payload)

    asyncio.run(product_jobs.execute_product_fit(store, ModesPool(), run, directory))
    assert modes == expected
