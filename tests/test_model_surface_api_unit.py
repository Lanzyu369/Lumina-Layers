from __future__ import annotations

import pytest
import trimesh
from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_file_registry
from api.file_registry import FileRegistry


@pytest.fixture()
def client() -> TestClient:
    registry = FileRegistry()
    app.dependency_overrides[get_file_registry] = lambda: registry
    try:
        yield TestClient(app)
    finally:
        registry.clear_all()
        app.dependency_overrides.pop(get_file_registry, None)


def test_model_surface_upload_returns_summary(tmp_path, client: TestClient):
    model_path = tmp_path / "plate.stl"
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(model_path)

    with model_path.open("rb") as fh:
        response = client.post(
            "/api/convert/model-surface/upload",
            files={"model": ("plate.stl", fh, "application/octet-stream")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["model_file_id"]
    assert data["summary"]["extents_mm"] == [20.0, 10.0, 2.0]


def test_model_surface_upload_rejects_step_extension(tmp_path, client: TestClient):
    path = tmp_path / "plate.step"
    path.write_text("bad", encoding="utf-8")

    with path.open("rb") as fh:
        response = client.post(
            "/api/convert/model-surface/upload",
            files={"model": ("plate.step", fh, "application/octet-stream")},
        )

    assert response.status_code == 422


def test_model_surface_select_returns_footprint(tmp_path, client: TestClient):
    model_path = tmp_path / "plate.stl"
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(model_path)

    with model_path.open("rb") as fh:
        upload = client.post(
            "/api/convert/model-surface/upload",
            files={"model": ("plate.stl", fh, "application/octet-stream")},
        ).json()

    response = client.post(
        "/api/convert/model-surface/select",
        json={
            "model_file_id": upload["model_file_id"],
            "hit": {"face_index": 4},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["selection"]["face_count"] >= 1
    assert data["footprint"]["area_mm2"] > 0
