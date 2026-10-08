"""Single-filament product capture, reference reuse, and durable job contracts."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api import backed_gradient_jobs
from api.dependencies import get_worker_pool
from api.routers.backed_gradient import get_gradient_store, router
from core.backed_gradient_fitting_v2 import _initial, _slices
from core.backed_gradient_product_store import save_backing_reference
from core.backed_gradient_smooth import BackedGradientSmoothTransport
from core.backed_gradient_store import BackedGradientConflictError, BackedGradientStore, THICKNESSES_MM


URL = "/api/extractor/lumina-box/backed-gradient"


def reference_fixture():
    from core.backed_gradient_material import reference_from_parameters

    vector = _initial(("W", "K"), 0)
    operator = BackedGradientSmoothTransport(
        {symbol: vector[part] for symbol, part in _slices(("W", "K")).items()},
        {"W": [97., 98., 100.5], "K": [0., 0., 0.]}, fitted_materials=("W", "K"),
    )
    return reference_from_parameters(operator.to_parameters(), source={"test": "product"})


class ProductPool:
    def __init__(self):
        self.requests = []

    async def submit(self, fn, input_path, directory, fit_mode):
        await asyncio.sleep(.001)
        snapshot = json.loads(Path(input_path).read_text(encoding="utf-8"))
        self.requests.append((fn.__name__, fit_mode, snapshot))
        result = {**{key: snapshot[key] for key in ("dataset_id", "dataset_revision", "input_hash")},
                  "fit_mode": fit_mode, "status": "converged", "rmse_pp": .2,
                  "reference": snapshot.get("reference") or reference_fixture().to_dict()}
        if fit_mode == "material":
            from core.backed_gradient_material import BackedGradientComponent

            result.update(optical_model_id="backed_gradient_spectral_four_flux_smooth/v3",
                          material_symbol=snapshot["material_symbol"],
                          component=BackedGradientComponent("color", tuple(_initial(("R",), 0))).to_dict())
        (Path(directory) / "result.json").write_text(json.dumps(result), encoding="utf-8")


@pytest.fixture
def context(tmp_path):
    store, pool = BackedGradientStore(tmp_path), ProductPool()
    reference = save_backing_reference(store, reference_fixture().to_dict(), "PETG backings")
    app = FastAPI()
    app.include_router(router, prefix="/api/extractor")
    app.dependency_overrides[get_gradient_store] = lambda: store
    app.dependency_overrides[get_worker_pool] = lambda: pool
    with TestClient(app) as client:
        yield client, store, reference, pool
        client.portal.call(backed_gradient_jobs.cancel_backed_gradient_jobs)


def capture(symbol, backing, thickness, values=None):
    return {"capture_id": "product-capture", "measurement_id": str(uuid4()),
            "material_symbol": symbol, "backing": backing, "overlay_mm": thickness,
            "sample_role": "coated" if thickness else "bare_backing",
            "reflectance_percent_xyz": values or [101., 20., 0.]}


def make_material(client, reference):
    response = client.post(URL + "/material-datasets", json={
        "name": "Red PETG", "brand": "Example", "material_symbol": "R",
        "reference_id": reference["reference_id"],
    })
    assert response.status_code == 200, response.text
    return response.json()["dataset"]


def fill_material(store, identity, symbol="R"):
    for backing in ("W", "K"):
        for thickness in THICKNESSES_MM:
            store.save_capture(identity, capture(symbol, backing, thickness))


def completed(client, fit_id):
    for _ in range(50):
        response = client.get(f"{URL}/fit-runs/{fit_id}")
        assert response.status_code == 200, response.text
        run = response.json()["run"]
        if run["status"] in ("complete", "failed"):
            assert run["status"] == "complete", run
            return run
    pytest.fail("Product job did not complete")


def test_single_material_needs_only_its_fourteen_readings(context):
    client, store, reference, pool = context
    dataset = make_material(client, reference)
    identity = dataset["dataset_id"]
    fill_material(store, identity)
    response = client.post(f"{URL}/material-datasets/{identity}/fit-runs", json={})
    assert response.status_code == 200, response.text
    run = completed(client, response.json()["run"]["fit_id"])
    assert run["material_symbol"] == "R"
    assert run["reference_id"] == reference["reference_id"]
    fn, mode, snapshot = pool.requests[0]
    assert fn == "fit_backed_gradient_product_worker" and mode == "material"
    assert len(snapshot["samples"]) == 14
    assert {row["material_symbol"] for row in snapshot["samples"]} == {"R"}
    assert any(row["overlay_mm"] == .24 for row in snapshot["samples"])
    assert snapshot["samples"][0]["reflectance_percent_xyz"] == [101., 20., 0.]
    frozen = client.get(f"{URL}/fit-runs/{run['fit_id']}/result").json()
    store.save_capture(identity, capture("R", "W", .08, [30., 20., 10.]))
    assert client.get(f"{URL}/fit-runs/{run['fit_id']}/result").json() == frozen
    assert len(BackedGradientStore(store.root).get(identity)["captures"]) == 15


@pytest.mark.parametrize("name", ["Apricot PETG", "Lavender PLA", "Warm gray", "Ivory", "Charcoal"])
def test_arbitrary_material_has_no_required_color_and_restores_its_backings(context, tmp_path, name):
    client, store, reference, pool = context
    response = client.post(URL + "/material-datasets", json={"name": name, "reference_id": reference["reference_id"]})
    assert response.status_code == 200, response.text
    dataset = response.json()["dataset"]
    assert dataset["materials"] == {"material": name}
    assert dataset["workflow"]["material_symbol"] == "material"
    fill_material(store, dataset["dataset_id"], "material")
    response = client.post(f"{URL}/material-datasets/{dataset['dataset_id']}/fit-runs", json={})
    assert response.status_code == 200, response.text
    run = completed(client, response.json()["run"]["fit_id"])
    assert pool.requests[0][2]["material_kind"] == "color"
    assert run["material_symbol"] == "material"
    assert len(pool.requests[0][2]["samples"]) == 14
    restored = BackedGradientStore(tmp_path / "restored")
    assert restored.import_document(store.export(dataset["dataset_id"])) == store.get(dataset["dataset_id"])


def test_each_material_capture_requires_its_explicit_backing_pair(context):
    client, store, reference, _ = context
    assert client.post(URL + "/material-datasets", json={"name": "Apricot"}).status_code == 422
    assert client.post(URL + "/material-datasets", json={"name": "Apricot", "reference_id": ""}).status_code == 422
    other = reference_fixture().to_dict()
    other["reference_id"] = "other-backing-reference"
    other["source"] = {"dataset_id": "other-backing-dataset", "materials": {"W": "Ivory base", "K": "Black base"}}
    other_reference = save_backing_reference(store, other, "Other pair")
    references = client.get(URL + "/references").json()["references"]
    assert references[0]["source_dataset_id"] == "other-backing-dataset"
    assert references[0]["white_name"] == "Ivory base"
    assert references[0]["black_name"] == "Black base"
    first = client.post(URL + "/material-datasets", json={"name": "Apricot", "reference_id": reference["reference_id"]}).json()["dataset"]
    second = client.post(URL + "/material-datasets", json={"name": "Apricot", "reference_id": other_reference["reference_id"]}).json()["dataset"]
    assert first["dataset_id"] != second["dataset_id"]
    assert first["workflow"]["backing_id"] != second["workflow"]["backing_id"]
    fill_material(store, first["dataset_id"], "material")
    before = store.export(first["dataset_id"])
    response = client.post(f"{URL}/material-datasets/{first['dataset_id']}/fit-runs", json={"reference_id": other_reference["reference_id"]})
    assert response.status_code == 409
    assert store.export(first["dataset_id"]) == before


def test_historical_capture_cannot_be_reassigned_to_another_backing_pair(context):
    client, store, reference, _ = context
    dataset = store.create({"name": "Historical full card"})
    fill_material(store, dataset["dataset_id"], "R")
    body = {"material_symbol": "R", "reference_id": reference["reference_id"]}
    endpoint = f"{URL}/material-datasets/{dataset['dataset_id']}/fit-runs"
    assert client.post(endpoint, json=body).status_code == 409
    original = reference_fixture().to_dict()
    original["reference_id"] = "historical-own-reference"
    original["source"] = {"dataset_id": dataset["dataset_id"]}
    own = save_backing_reference(store, original, "Original backings")
    response = client.post(endpoint, json={**body, "reference_id": own["reference_id"]})
    assert response.status_code == 200, response.text
    completed(client, response.json()["run"]["fit_id"])


def test_material_identity_blocks_cross_target_and_missing_pairs(context):
    client, store, reference, _ = context
    dataset = make_material(client, reference)
    identity = dataset["dataset_id"]
    assert client.post(f"{URL}/datasets/{identity}/captures", json=capture("B", "W", .08)).status_code == 409
    assert client.post(f"{URL}/material-datasets/{identity}/fit-runs", json={}).status_code == 422
    assert store.get(identity)["captures"] == []
    fill_material(store, identity)
    assert client.post(f"{URL}/material-datasets/{identity}/fit-runs", json={"material_symbol": "B"}).status_code == 409


@pytest.mark.parametrize("reference_version", [1, 3])
def test_export_restores_reference_history_and_replay_receipt(context, tmp_path, reference_version):
    client, store, reference, _ = context
    for version in range(2, reference_version + 1):
        evolved = deepcopy(reference["reference"])
        evolved["reference_id"] = f"backing-version-{version}"
        evolved["source"]["backing_id"] = reference["backing_id"]
        evolved["white"]["coefficients"][2] += .01
        reference = save_backing_reference(store, evolved, f"PETG backings {version}")
    assert reference["version"] == reference_version
    dataset = make_material(client, reference)
    body = capture("R", "K", .08)
    old, _, _ = store.save_capture(dataset["dataset_id"], body)
    store.save_capture(dataset["dataset_id"], capture("R", "K", .08))
    store.select(dataset["dataset_id"], old["record_id"])
    exported = store.export(dataset["dataset_id"])
    restored_store = BackedGradientStore(tmp_path / "other-library")
    restored = restored_store.import_document(exported)
    assert restored == store.get(dataset["dataset_id"])
    assert restored_store.save_capture(dataset["dataset_id"], body)[1] is True
    from core.backed_gradient_product_store import get_backing_reference

    assert get_backing_reference(restored_store, reference["reference_id"]) == reference
    changed = deepcopy(exported)
    changed["dataset"]["workflow"]["material_symbol"] = "B"
    with pytest.raises(BackedGradientConflictError, match="another material"):
        restored_store.import_document(changed)


@pytest.mark.parametrize("conflicting_parameters", [False, True])
def test_capture_import_preserves_existing_reference_metadata_and_checks_identity(context, tmp_path, conflicting_parameters):
    from core.backed_gradient_product_store import get_backing_reference

    client, store, reference, _ = context
    dataset = make_material(client, reference)
    exported = store.export(dataset["dataset_id"])
    restored_store = BackedGradientStore(tmp_path / "existing-reference")
    local_parameters = deepcopy(reference["reference"])
    if conflicting_parameters:
        local_parameters["white"]["coefficients"][2] += .1
    local = save_backing_reference(restored_store, local_parameters, "Local backing label")
    if conflicting_parameters:
        with pytest.raises(BackedGradientConflictError, match="different saved version"):
            restored_store.import_document(exported)
        assert restored_store.list() == []
    else:
        restored_store.import_document(exported)
    assert get_backing_reference(restored_store, reference["reference_id"]) == local


def test_first_backing_setup_uses_cross_pairs_and_bare_references(context):
    client, store, _, pool = context
    response = client.post(URL + "/backing-datasets", json={"name": "New backing pair", "white_name": "White", "black_name": "Black"})
    assert response.status_code == 200, response.text
    identity = response.json()["dataset"]["dataset_id"]
    for symbol, backing in (("W", "K"), ("K", "W")):
        for thickness in THICKNESSES_MM:
            store.save_capture(identity, capture(symbol, backing, thickness))
    for symbol, values in (("W", [97., 98., 100.5]), ("K", [0., 0., 0.])):
        store.save_capture(identity, capture(symbol, symbol, 0., values))
    response = client.post(f"{URL}/backing-datasets/{identity}/fit-runs", json={})
    assert response.status_code == 200, response.text
    run = completed(client, response.json()["run"]["fit_id"])
    assert run["fit_mode"] == "backing_reference"
    assert run["reference_id"]
    assert len(pool.requests[0][2]["samples"]) == 14
    assert len(store.get(identity)["captures"]) == 16


def test_save_archive_keeps_frozen_readings_after_capture_changes(context):
    client, store, reference, _ = context
    dataset = make_material(client, reference)
    identity = dataset["dataset_id"]
    fill_material(store, identity)
    response = client.post(f"{URL}/material-datasets/{identity}/fit-runs", json={})
    run = completed(client, response.json()["run"]["fit_id"])
    store.save_capture(identity, capture("R", "W", .08, [33., 22., 11.]))
    path = f"{URL}/material-fit-runs/{run['fit_id']}/archive"
    payload = {"name": "Red", "brand": "Example"}
    response = client.post(path, json=payload)
    assert response.status_code == 200, response.text
    material = response.json()["material"]
    assert material["capture_dataset_id"] == identity
    assert material["material_symbol"] == "R"
    from core.backed_gradient_archive import load_backed_gradient_archive

    _, measurements, fit = load_backed_gradient_archive(store.root / material["directory_name"])
    assert len(measurements["capture_history"]) == 14
    assert all(row["reflectance_percent_xyz"] == [101., 20., 0.] for row in measurements["samples"])
    assert fit["reference"]["reference_id"] == reference["reference_id"]
    assert client.post(path, json=payload).status_code == 409
