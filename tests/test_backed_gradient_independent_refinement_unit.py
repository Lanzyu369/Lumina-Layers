"""Initial independent backings refine together without changing other combinations."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import shutil
import zipfile
from uuid import uuid4

import pytest

from api import backed_gradient_product_jobs as jobs
from core.backed_gradient_archive import load_backed_gradient_archive, save_backed_gradient_material_archive
from core.backed_gradient_backing_store import (
    create_black_white_pair, backing_material_snapshot, create_backing_material_dataset, get_backing_material,
    save_backing_material_result, save_backing_material_results,
)
from core.backed_gradient_fitting_v2 import _initial
from core.backed_gradient_material import BackedGradientMaterialModel, reference_from_parameters
from core.backed_gradient_product_store import (
    create_material_dataset, get_backing_reference, list_backing_references, material_group_snapshot,
    material_snapshot, uses_reference_backings,
)
from core.backed_gradient_smooth import BackedGradientSmoothTransport, SPECTRAL_SMOOTH_MODEL_ID
from core.backed_gradient_store import BackedGradientStore, THICKNESSES_MM
from core.errors import CoreProcessingError, CoreValidationError


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _capture(store, dataset, symbol, backing, thickness, xyz, *, bare=False):
    return store.save_capture(dataset["dataset_id"], {
        "capture_id": str(uuid4()), "measurement_id": str(uuid4()), "material_symbol": symbol,
        "backing": backing, "overlay_mm": thickness, "sample_role": "bare_backing" if bare else "coated",
        "reflectance_percent_xyz": xyz,
    })[0]


def _backing_samples(store, dataset, model):
    role = dataset["workflow"]["role"]
    opposite = "K" if role == "W" else "W"
    component = model.reference.white if role == "W" else model.reference.black
    for thickness in THICKNESSES_MM:
        _capture(store, dataset, role, opposite, thickness, model.predict_backed(component, opposite, thickness).tolist())
    _capture(store, dataset, role, role, 0., list(model.reference.anchors[role]), bare=True)


def _fit(snapshot, reference):
    return {**{key: snapshot[key] for key in ("dataset_id", "dataset_revision", "input_hash", "material_symbol")},
            "optical_model_id": SPECTRAL_SMOOTH_MODEL_ID, "fit_mode": "material", "converged": True,
            "component": {"kind": "color", "coefficients": _initial(("R",), 0).tolist()},
            "reference": deepcopy(reference), "rmse_pp": .2}


@pytest.fixture
def initial_group(tmp_path):
    store = BackedGradientStore(tmp_path / "library")
    vector = _initial(("W", "K"), 0)
    operator = BackedGradientSmoothTransport({"W": vector[:5], "K": vector[5:]},
                                            {"W": [97., 98., 99.], "K": [0., 0., 0.]}, fitted_materials=("W", "K"))
    model = BackedGradientMaterialModel(reference_from_parameters(operator.to_parameters()))
    white_capture = create_black_white_pair(store, {"white": {"name": "White A"}, "black": {"name": "Black B"}})
    _backing_samples(store, white_capture, model)
    white_snapshot = backing_material_snapshot(store, white_capture["dataset_id"])
    white = save_backing_material_result(store, white_snapshot, None)
    black_capture = create_backing_material_dataset(store, {"name": "Black B", "role": "K", "material_id": white["opposite_material_id"]})
    _backing_samples(store, black_capture, model)
    black_snapshot = backing_material_snapshot(store, black_capture["dataset_id"])
    snapshots = {"W": white_snapshot, "K": black_snapshot}
    reference = reference_from_parameters(operator.to_parameters(), source={
        "dataset_id": black_capture["dataset_id"], "backing_id": black_capture["dataset_id"],
        "independent_backings": True, "established": False, "calibration_stage": "bootstrap",
        "backing_material_ids": {role: value["material_id"] for role, value in snapshots.items()},
        "backing_samples": [row for value in snapshots.values() for row in value["samples"] if row["sample_role"] == "coated"],
    }).to_dict()
    pair = {item["role"]: item for item in save_backing_material_results(store, [
        (value, {"component": reference["white" if role == "W" else "black"], "reference": reference})
        for role, value in snapshots.items()
    ])}
    members = []
    for name in ("Yellow", "Orange"):
        dataset = create_material_dataset(store, {"name": name, "white_backing_id": pair["W"]["material_id"],
                                                  "black_backing_id": pair["K"]["material_id"]})
        for backing in ("W", "K"):
            for thickness in THICKNESSES_MM:
                _capture(store, dataset, "material", backing, thickness, [30., 20., 10.])
        members.append(material_snapshot(store, dataset["dataset_id"]))
    archive = save_backed_gradient_material_archive(material_name="Yellow", measurement_payload=members[0],
                                                     fit_payload=_fit(members[0], reference), materials_dir=str(store.root))
    selected = members[-1]
    grouped, frozen_members = material_group_snapshot(store, selected)
    directory = store.results_root / str(uuid4())
    _write(directory / "input.json", {**selected, "group": grouped, "group_material_snapshots": frozen_members})
    newer = deepcopy(reference)
    newer["reference_id"] = "refined-independent-observation"
    newer["white"]["coefficients"][2] += .2
    newer["black"]["coefficients"][0] += .1
    newer["source"]["calibration_stage"] = "joint"
    fits = {f"{item['dataset_id']}:{item['material_symbol']}": _fit(item, newer) for item in frozen_members}
    result = {**fits[f"{selected['dataset_id']}:material"], "group_fits": fits, "group_input_hash": grouped["input_hash"]}
    run = {"fit_id": directory.name, "fit_mode": "material", "status": "running",
           **{key: selected[key] for key in ("dataset_id", "dataset_revision", "input_hash", "material_symbol", "backing_id")},
           "reference_id": reference["reference_id"], "capture_reference_id": reference["reference_id"]}
    store.save_run(run)
    return store, pair, members, Path(archive.archive_path).parent, run, directory, result


@pytest.mark.parametrize("established,rmse,modes", [(False, .2, ["material_group"]),
    (True, .2, ["material"]), (True, 4.42, ["material", "material_group"])])
def test_initial_pair_can_refine_and_retains_established_fast_path(initial_group, established, rmse, modes):
    store, _, _, _, run, directory, result = initial_group
    frozen = json.loads((directory / "input.json").read_text(encoding="utf-8"))
    frozen["reference"]["source"]["established"] = established
    _write(directory / "input.json", frozen)
    actual_modes = []

    class Pool:
        async def submit(self, function, input_path, output, mode):
            actual_modes.append(mode)
            _write(Path(output) / "result.json", {**result, "rmse_pp": rmse})

    asyncio.run(jobs.execute_product_fit(store, Pool(), run, directory))
    assert actual_modes == modes


@pytest.mark.parametrize("changed", ["identity", "coefficients", "generic_same_identity"])
def test_different_actual_backings_never_enter_initial_joint_fit(initial_group, changed):
    store, _, _, _, run, directory, result = initial_group
    frozen = json.loads((directory / "input.json").read_text(encoding="utf-8"))
    if changed == "identity":
        frozen["backing_material_ids"]["W"] = str(uuid4())
    elif changed == "coefficients":
        frozen["backing_components"]["W"]["coefficients"][2] += .2
    else:
        frozen["backing_components"]["W"] = {"kind": "color", "coefficients": [-4., -4., -4., -4., 1., 0., .7]}
    assert not uses_reference_backings(frozen)
    assert material_group_snapshot(store, frozen) == (None, [])
    _write(directory / "input.json", frozen)
    modes = []

    class Pool:
        async def submit(self, function, input_path, output, mode):
            modes.append(mode)
            _write(Path(output) / "result.json", {**result, "rmse_pp": 12.})

    asyncio.run(jobs.execute_product_fit(store, Pool(), run, directory))
    assert modes == ["material"]


def test_joint_publication_versions_both_backings_and_preserves_capture_history(initial_group):
    store, pair, members, archive, run, directory, result = initial_group
    pending = create_backing_material_dataset(store, {"name": "White A", "role": "W", "material_id": pair["W"]["material_id"]})
    captured = [store.get(item["dataset_id"]) for item in members]
    jobs.publish_group_materials(store, run, directory, result)
    for role, prior in pair.items():
        current = get_backing_material(store, prior["material_id"])
        assert current["material_id"] == prior["material_id"] and current["version_id"] != prior["version_id"]
        assert current["reference_id"] == result["reference"]["reference_id"]
        assert current["component"] == result["reference"]["white" if role == "W" else "black"]
        assert current["snapshot"]["samples"] == prior["snapshot"]["samples"]
        assert get_backing_material(store, prior["material_id"], version_id=prior["version_id"]) == prior
        if role == "W":
            assert current["active_dataset_id"] == pending["dataset_id"]
    for before, member in zip(captured, members, strict=True):
        assert store.get(member["dataset_id"]) == before
        resumed = material_snapshot(store, member["dataset_id"])
        assert resumed["capture_reference_id"] == member["capture_reference_id"]
        assert resumed["reference_id"] == result["reference"]["reference_id"]
        assert resumed["capture_backing_material_versions"] == member["backing_material_versions"]
        assert resumed["backing_components"] == {"W": result["reference"]["white"], "K": result["reference"]["black"]}
        assert uses_reference_backings(resumed)
    fitted = load_backed_gradient_archive(archive)[2]
    assert fitted["backing_components"] == result["backing_components"]
    assert fitted["reference"]["reference_id"] == result["reference"]["reference_id"]


def test_archive_swap_failure_rolls_back_both_backing_versions(initial_group, monkeypatch):
    store, pair, _, archive, run, directory, result = initial_group
    before = {file.name: file.read_bytes() for file in archive.iterdir() if file.is_file()}
    original_replace = jobs.os.replace

    def fail_swap(source, target):
        if "materials" in Path(source).parts and Path(target) == archive:
            raise OSError("Injected final archive swap failure")
        return original_replace(source, target)

    monkeypatch.setattr(jobs.os, "replace", fail_swap)
    with pytest.raises(CoreProcessingError, match="storage"):
        jobs.publish_group_materials(store, run, directory, result)
    assert {file.name: file.read_bytes() for file in archive.iterdir() if file.is_file()} == before
    assert len(list_backing_references(store)) == 1
    assert store.get_run(run["fit_id"])["status"] == "running"
    for prior in pair.values():
        assert get_backing_material(store, prior["material_id"]) == prior
    with store._connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM gradient_backing_material_versions").fetchone()[0] == 3


def test_first_pair_keeps_separate_brands_and_material_types(tmp_path):
    store = BackedGradientStore(tmp_path)
    dataset = create_black_white_pair(store, {"white": {"name": "White A", "brand": "Brand A", "material_type": "PETG"},
                                                  "black": {"name": "Black B", "brand": "Brand B", "material_type": "PLA"}})
    opposite = get_backing_material(store, dataset["workflow"]["opposite_material_id"])
    assert opposite["name"] == "Black B" and opposite["brand"] == "Brand B" and opposite["material_type"] == "PLA"


def test_joint_refinement_updates_black_white_library_profiles_without_treating_them_as_fourteen_reading_colors(initial_group):
    from core.black_white_material_profiles import publish_black_white_profiles

    store, pair, members, _, run, directory, result = initial_group
    publish_black_white_profiles(store, [(item["snapshot"], item["fit"]) for item in pair.values()])
    group, snapshots = material_group_snapshot(store, members[-1])
    assert len(group["materials"]) == len(snapshots) == 2
    jobs.publish_group_materials(store, run, directory, result)
    for role, item in pair.items():
        main, measurements, fit = load_backed_gradient_archive(store.root / item["name"])
        assert main["backing_material_id"] == item["material_id"]
        assert len(measurements["samples"]) == 8
        assert fit["reference"] == result["reference"]
        assert fit["component"] == result["reference"]["white" if role == "W" else "black"]


def test_recollected_same_id_keeps_its_own_model_and_archives_outside_initial_refinement(initial_group):
    store, pair, members, _, run, directory, result = initial_group
    component = {"kind": "color", "coefficients": [-4., -4., -4., -4., 1., 0., .7]}
    white = save_backing_material_result(store, pair["W"]["snapshot"],
                                         {"component": component, "reference": pair["W"]["reference"]})
    dataset = create_material_dataset(store, {"name": "Recollected combination", "white_backing_id": white["material_id"],
                                              "black_backing_id": pair["K"]["material_id"]})
    for backing in ("W", "K"):
        for thickness in THICKNESSES_MM:
            _capture(store, dataset, "material", backing, thickness, [30., 20., 10.])
    custom = material_snapshot(store, dataset["dataset_id"])
    assert not uses_reference_backings(custom)
    archive = save_backed_gradient_material_archive(material_name=custom["name"], measurement_payload=custom,
                                                     fit_payload=_fit(custom, custom["reference"]), materials_dir=str(store.root))
    archive_path = Path(archive.archive_path).parent
    before = {file.name: file.read_bytes() for file in archive_path.iterdir() if file.is_file()}
    grouped, gathered = material_group_snapshot(store, members[-1])
    assert len(gathered) == 2 and all(item["dataset_id"] != dataset["dataset_id"] for item in gathered)
    assert len(grouped["materials"]) == 2
    jobs.publish_group_materials(store, run, directory, result)
    assert get_backing_material(store, white["material_id"]) == white
    assert material_snapshot(store, dataset["dataset_id"]) == custom
    assert {file.name: file.read_bytes() for file in archive_path.iterdir() if file.is_file()} == before
    assert material_snapshot(store, members[-1]["dataset_id"])["reference_id"] == result["reference"]["reference_id"]


@pytest.mark.parametrize("standalone", [False, True])
def test_exported_independent_material_restores_backings_and_can_continue(initial_group, tmp_path, standalone):
    from core.backed_gradient_backing_store import list_backing_materials
    from core.single_stage.materials import (
        export_saved_stage_a_material_archives, import_saved_stage_a_material_archives,
    )

    store, pair, members, archive, run, directory, result = initial_group
    jobs.publish_group_materials(store, run, directory, result)
    source = store.root
    relative = archive.relative_to(store.root)
    if standalone:
        source = tmp_path / "standalone"
        shutil.copytree(archive, source / relative)
    exported = export_saved_stage_a_material_archives(
        directory_names=[relative.as_posix()], materials_dir=str(source), output_path=str(tmp_path / "portable.zip"),
    )
    restored = BackedGradientStore(tmp_path / "restored")
    imported = import_saved_stage_a_material_archives(archive_path=exported.archive_path, materials_dir=str(restored.root))
    assert len(imported.imported_materials) == 1
    assert {item["material_id"] for item in list_backing_materials(restored)} == {item["material_id"] for item in pair.values()}
    for role, prior in pair.items():
        assert get_backing_material(restored, prior["material_id"], version_id=prior["version_id"]) == prior
        current = get_backing_material(restored, prior["material_id"])
        assert current["reference_id"] == result["reference"]["reference_id"]
        assert restored.get(current["dataset_id"])["captures"]
    original = members[0]
    before = material_snapshot(restored, original["dataset_id"])
    dataset = restored.get(original["dataset_id"])
    _capture(restored, dataset, "material", "W", .08, [31., 21., 11.])
    continued = material_snapshot(restored, original["dataset_id"])
    assert continued["dataset_revision"] == before["dataset_revision"] + 1
    assert len(continued["capture_history"]) == 15
    assert continued["reference_id"] == result["reference"]["reference_id"]
    assert continued["backing_components"] == result["backing_components"]
    next_dataset = create_material_dataset(restored, {
        "name": "Next filament", "white_backing_id": pair["W"]["material_id"], "black_backing_id": pair["K"]["material_id"],
    })
    assert next_dataset["workflow"]["reference_id"] == continued["reference_id"]


@pytest.mark.parametrize("source_available", [True, False])
def test_older_archives_export_real_backing_versions_when_source_is_available(initial_group, tmp_path, source_available):
    from core.backed_gradient_backing_store import list_backing_materials
    from core.single_stage.materials import export_saved_stage_a_material_archives, import_saved_stage_a_material_archives

    store, _, members, archive, run, directory, result = initial_group
    jobs.publish_group_materials(store, run, directory, result)
    main, measurements, fit = load_backed_gradient_archive(archive)
    measurements.pop("backing_documents", None)
    fit.pop("backing_documents", None)
    saved = save_backed_gradient_material_archive(material_name="Old Yellow", measurement_payload=measurements,
                                                   fit_payload=fit, materials_dir=str(store.root))
    archive = Path(saved.archive_path).parent
    original_bytes = {path.name: path.read_bytes() for path in archive.iterdir() if path.is_file()}
    source = store.root
    relative = archive.relative_to(source)
    if not source_available:
        source = tmp_path / "old-standalone"
        shutil.copytree(archive, source / relative)
    exported = export_saved_stage_a_material_archives(directory_names=[relative.as_posix()], materials_dir=str(source),
                                                      output_path=str(tmp_path / "old.zip"))
    assert {path.name: path.read_bytes() for path in archive.iterdir() if path.is_file()} == original_bytes
    with zipfile.ZipFile(exported.archive_path) as package:
        manifest = json.loads(package.read("lumina_material_bundle.json"))
    assert bool(manifest["packages"][0].get("backed_gradient_backing_documents")) == source_available
    restored = BackedGradientStore(tmp_path / "old-restored")
    imported = import_saved_stage_a_material_archives(archive_path=exported.archive_path, materials_dir=str(restored.root))
    loaded = load_backed_gradient_archive(restored.root / imported.imported_materials[0]["directory_name"])
    assert loaded[2] == fit
    if source_available:
        assert len(list_backing_materials(restored)) == 2
        assert material_snapshot(restored, members[0]["dataset_id"])["reference_id"] == fit["reference"]["reference_id"]
    else:
        assert list_backing_materials(restored) == []
        assert len(restored.get(members[0]["dataset_id"])["captures"]) == 14
        with pytest.raises(CoreValidationError, match="Re-export the material from the source computer"):
            material_snapshot(restored, members[0]["dataset_id"])


def test_conflicting_backing_version_rolls_back_the_whole_archive_import(initial_group, tmp_path):
    from core.backed_gradient_store import BackedGradientConflictError, _json
    from core.single_stage.materials import export_saved_stage_a_material_archives, import_saved_stage_a_material_archives

    store, pair, _, archive, run, directory, result = initial_group
    jobs.publish_group_materials(store, run, directory, result)
    exported = export_saved_stage_a_material_archives(directory_names=[archive.relative_to(store.root).as_posix()],
        materials_dir=str(store.root), output_path=str(tmp_path / "conflict.zip"))
    restored = BackedGradientStore(tmp_path / "conflicted")
    conflicting = {**pair["W"], "name": "Locally different immutable data"}
    with restored._connection(write=True) as connection:
        connection.execute("INSERT INTO gradient_backing_material_versions VALUES (?,?,?)",
                           (conflicting["version_id"], conflicting["material_id"], _json(conflicting)))
    before = {path.relative_to(restored.root) for path in restored.root.rglob("*") if path.is_file()}
    with pytest.raises(BackedGradientConflictError, match="different saved data"):
        import_saved_stage_a_material_archives(archive_path=exported.archive_path, materials_dir=str(restored.root))
    with restored._connection() as connection:
        for table in ("gradient_datasets", "gradient_captures", "gradient_references", "gradient_backing_materials"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert connection.execute("SELECT document FROM gradient_backing_material_versions").fetchall() == [(_json(conflicting),)]
    assert {path.relative_to(restored.root) for path in restored.root.rglob("*") if path.is_file()} == before


def test_imported_history_preserves_local_backing_recollection_and_selection(initial_group, tmp_path):
    from core.backed_gradient_backing_transfer import restore_material_captures
    from core.single_stage.materials import export_saved_stage_a_material_archives, import_saved_stage_a_material_archives

    store, pair, _, archive, run, directory, result = initial_group
    jobs.publish_group_materials(store, run, directory, result)
    _, measurements, fit = load_backed_gradient_archive(archive)
    restored = BackedGradientStore(tmp_path / "existing")
    restore_material_captures(restored, [(measurements, fit, [])])
    original = get_backing_material(restored, pair["W"]["material_id"])
    newer_component = {"kind": "color", "coefficients": [-4., -4., -4., -4., 1., 0., .7]}
    newer = save_backing_material_result(restored, original["snapshot"],
                                        {"component": newer_component, "reference": original["reference"]})
    pending = create_backing_material_dataset(restored, {"name": "White A", "role": "W", "material_id": newer["material_id"]})
    backing_capture = restored.get(original["dataset_id"])
    selected = _capture(restored, backing_capture, "W", "K", .08, [31., 21., 11.])
    current = get_backing_material(restored, newer["material_id"])
    exported = export_saved_stage_a_material_archives(directory_names=[archive.relative_to(store.root).as_posix()],
        materials_dir=str(store.root), output_path=str(tmp_path / "history.zip"))
    import_saved_stage_a_material_archives(archive_path=exported.archive_path, materials_dir=str(restored.root))
    assert get_backing_material(restored, newer["material_id"]) == current
    assert current["active_dataset_id"] == pending["dataset_id"]
    assert restored.get(original["dataset_id"])["selected_capture_ids"]["W:K:0.08"] == selected["record_id"]


def test_changed_frozen_backing_readings_are_rejected_before_import(initial_group, tmp_path):
    from core.backed_gradient_backing_transfer import restore_material_captures
    from core.backed_gradient_store import _digest

    store, _, _, archive, run, directory, result = initial_group
    jobs.publish_group_materials(store, run, directory, result)
    _, measurements, fit = load_backed_gradient_archive(archive)
    altered = deepcopy(measurements)
    document = altered["backing_documents"][0]
    document["snapshot"]["samples"][0]["reflectance_percent_xyz"][0] += 1.
    document["version_id"] = _digest({key: value for key, value in document.items()
                                      if key not in ("version_id", "updated_at", "active_dataset_id")})
    restored = BackedGradientStore(tmp_path / "invalid-readings")
    with pytest.raises(CoreValidationError, match="selected original readings"):
        restore_material_captures(restored, [(altered, fit, [])])
    assert restored.list() == []
