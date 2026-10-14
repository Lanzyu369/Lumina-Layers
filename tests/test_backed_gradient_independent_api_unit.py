"""Independent backing capture, first-use setup, and actual fitting contracts."""
import asyncio
from copy import deepcopy
import json
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api import backed_gradient_jobs
from api.dependencies import get_worker_pool
from api.routers.backed_gradient import router, get_gradient_store
from core.backed_gradient_material import BackedGradientComponent, BackedGradientMaterialModel
from core.backed_gradient_product_store import save_backing_reference
from core.backed_gradient_store import BackedGradientStore, THICKNESSES_MM
from tests.test_backed_gradient_product_api_unit import reference_fixture

URL = "/api/extractor/lumina-box/backed-gradient"


class RealWorker:
    async def submit(self, fn, *args):
        return await asyncio.to_thread(fn, *args)


@pytest.fixture
def context(tmp_path):
    store = BackedGradientStore(tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/api/extractor")
    app.dependency_overrides[get_gradient_store] = lambda: store
    app.dependency_overrides[get_worker_pool] = lambda: RealWorker()
    with TestClient(app) as client:
        yield client, store
        client.portal.call(backed_gradient_jobs.cancel_backed_gradient_jobs)


def _create(client, **body):
    response = client.post(URL + "/backing-material-datasets", json=body)
    assert response.status_code == 200, response.text
    return response.json()["dataset"]


def _fill(client, dataset, reference, component):
    role = dataset["workflow"]["material_symbol"]
    opposite = "K" if role == "W" else "W"
    model = BackedGradientMaterialModel(reference)
    for thickness in (*THICKNESSES_MM, 0.):
        body = {"capture_id": str(uuid4()), "measurement_id": str(uuid4()),
                "material_symbol": role, "backing": opposite if thickness else role,
                "sample_role": "coated" if thickness else "bare_backing", "overlay_mm": thickness,
                "reflectance_percent_xyz": model.predict_backed(component, opposite, thickness or 3.).tolist()}
        response = client.post(f"{URL}/datasets/{dataset['dataset_id']}/captures", json=body)
        assert response.status_code == 200, response.text


def _finish(client, dataset):
    response = client.post(f"{URL}/backing-material-datasets/{dataset['dataset_id']}/fit-runs", json={})
    assert response.status_code == 200, response.text
    identity = response.json()["run"]["fit_id"]
    for _ in range(600):
        run = client.get(f"{URL}/fit-runs/{identity}").json()["run"]
        if run["status"] in ("complete", "failed"):
            assert run["status"] == "complete", run
            return client.get(f"{URL}/fit-runs/{identity}/result").json()["result"]
        client.portal.call(asyncio.sleep, .05)
    pytest.fail("Independent backing job did not finish")


def test_new_backing_fits_without_recollecting_or_changing_the_other_material(context):
    client, store = context
    calibration = reference_fixture()
    from tests.support.black_white_materials import register_black_white
    register_black_white(store, calibration.to_dict())
    choices = client.get(URL + "/backing-materials").json()["backings"]
    black = next(item for item in choices if item["role"] == "K")
    initial = deepcopy(choices)
    dataset = _create(client, name="Independent ivory", role="W", opposite_material_id=black["material_id"])
    component = BackedGradientComponent("color", (-4., -4.1, -4.2, -4.3, .7, 1., .6))
    _fill(client, dataset, calibration, component)
    result = _finish(client, dataset)
    assert result["status"] == "complete" and result["rmse_pp"] < .1
    assert len(result["selected_record_ids"]) == 8
    assert result["reference_id"] == calibration.reference_id
    choices = client.get(URL + "/backing-materials").json()["backings"]
    assert all(item in choices for item in initial)
    ivory = next(item for item in choices if item["name"] == "Independent ivory")
    assert ivory["status"] == "ready"
    material = client.post(URL + "/material-datasets", json={"name": "Orange", "white_backing_id": ivory["material_id"],
                                                            "black_backing_id": black["material_id"]})
    assert material.status_code == 200, material.text
    workflow = material.json()["dataset"]["workflow"]
    assert workflow["reference_id"] == calibration.reference_id
    assert workflow["backing_components"]["W"] == result["component"]
    assert len(store.get(dataset["dataset_id"])["captures"]) == 8


def test_first_backings_save_separately_then_obtain_a_common_calibration(context):
    client, store = context
    calibration = reference_fixture()
    response = client.post(URL + "/black-white-pairs", json={"white": {"name": "First white"}, "black": {"name": "First black"}})
    assert response.status_code == 200, response.text
    white = response.json()["dataset"]
    from core.backed_gradient_backing_store import get_backing_material
    black_id = get_backing_material(store, white["workflow"]["opposite_material_id"])["active_dataset_id"]
    black = store.get(black_id)
    _fill(client, black, calibration, calibration.black)
    first = _finish(client, black)
    assert first["status"] == "awaiting_opposite"
    entities = client.get(URL + "/backing-materials").json()["backings"]
    assert {item["status"] for item in entities} == {"draft", "measured"}
    _fill(client, white, calibration, calibration.white)
    second = _finish(client, white)
    assert second["status"] == "complete"
    entities = client.get(URL + "/backing-materials").json()["backings"]
    assert len(entities) == 2 and all(item["status"] == "ready" for item in entities)
    assert len({item["reference_id"] for item in entities}) == 1
    assert len(store.get(black["dataset_id"])["captures"]) == 8
    assert len(store.get(white["dataset_id"])["captures"]) == 8


@pytest.mark.parametrize("field", ["dataset_id", "dataset_revision", "input_hash"])
def test_initial_peer_result_cannot_publish_under_another_input(context, tmp_path, monkeypatch, field):
    from api import backed_gradient_independent_jobs as jobs
    from core.errors import CoreProcessingError

    _, store = context
    own = {"dataset_id": "own", "dataset_revision": 8, "input_hash": "own-input"}
    peer = {"dataset_id": "peer", "dataset_revision": 8, "input_hash": "peer-input"}
    (tmp_path / "input.json").write_text(json.dumps({**own, "opposite": {"snapshot": peer}}), encoding="utf-8")
    calls = []
    monkeypatch.setattr(jobs, "publish_black_white_profiles", lambda *args: calls.append(args))
    result = {**own, "status": "complete", "converged": True, "reference": {"reference_id": "common"},
              "bootstrap_peer": {**peer, "converged": True, "reference": {"reference_id": "common"}, field: "wrong-input"}}
    with pytest.raises(CoreProcessingError, match="frozen measurements"):
        jobs.publish_backing_material_fit(store, {}, tmp_path, result)
    assert calls == []
