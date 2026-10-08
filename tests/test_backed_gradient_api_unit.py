"""Independent backed-gradient API and job lifecycle regression tests."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api import backed_gradient_jobs
from api.dependencies import get_file_registry, get_worker_pool
from api.file_registry import FileRegistry
from api.routers.backed_gradient import get_gradient_store, router
from core.backed_gradient_store import BackedGradientStore, THICKNESSES_MM


URL = "/api/extractor/lumina-box/backed-gradient"




@pytest.fixture
def context(tmp_path):
    store, registry = BackedGradientStore(tmp_path / "library"), FileRegistry()
    app = FastAPI()
    app.include_router(router, prefix="/api/extractor")
    app.dependency_overrides[get_gradient_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    with TestClient(app) as client:
        yield client, store, registry
        client.portal.call(backed_gradient_jobs.cancel_backed_gradient_jobs)
    registry.clear_all()


def create(client):
    response = client.post(URL + "/datasets", json={"name": "backed-card-data", "brand": "KYNIX"})
    assert response.status_code == 200, response.text
    return response.json()["dataset"]


def manual(symbol="Y", backing="W", thickness=.08, identity=None):
    return {"capture_id": "batch", "material_symbol": symbol, "backing": backing,
            "sample_role": "bare_backing" if thickness == 0 else "coated", "overlay_mm": thickness,
            "measurement_id": identity or str(uuid4()), "reflectance_percent_xyz": [101, 20, 0]}






def test_capture_history_selection_export_and_local_origin(context):
    client, store, registry = context
    dataset = create(client)
    path = f"{URL}/datasets/{dataset['dataset_id']}"
    body = manual(identity="stable-id")
    saved = client.post(path + "/captures", json=body)
    assert saved.status_code == 200, saved.text
    first = saved.json()["record"]
    assert first["reflectance_percent_xyz"] == [101, 20, 0]
    assert client.post(path + "/captures", json=body).json()["deduplicated"] is True
    changed = {**body, "backing": "K"}
    assert client.post(path + "/captures", json=changed).status_code == 409
    second = client.post(path + "/captures", json=manual()).json()["record"]
    assert client.post(path + "/selection", json={"record_id": first["record_id"]}).status_code == 200
    portable = client.get(path + "/export").json()
    assert client.post(URL + "/import", json=portable).status_code == 200
    assert client.delete(path + "/captures/" + first["record_id"]).status_code == 200
    assert client.post(path + "/captures", json=body).status_code == 409
    assert client.get(path).json()["dataset"]["selected_capture_ids"]["Y:W:0.08"] == second["record_id"]
    for method, target in [("get", path), ("post", URL + "/datasets"), ("get", path + "/export")]:
        assert getattr(client, method)(target, headers={"Origin": "https://example.com"}).status_code == 403


@pytest.mark.parametrize("update", [
    {"overlay_mm": .4}, {"overlay_mm": True}, {"reflectance_percent_xyz": [1, True, 3]},
    {"reflectance_percent_xyz": [1, "2", 3]}, {"reflectance_percent_xyz": [1, -2, 3]},
    {"unexpected": "ignored?"}, {"sample_role": "bare_backing"},
])
def test_invalid_input_is_rejected_without_mutating_experiment(context, update):
    client, store, _ = context
    dataset = create(client)
    response = client.post(f"{URL}/datasets/{dataset['dataset_id']}/captures", json={**manual(), **update})
    assert response.status_code == 422, response.text
    assert store.get(dataset["dataset_id"])["revision"] == 0
