from __future__ import annotations

import pytest
import trimesh
from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_file_registry
from api.file_registry import FileRegistry
from api.routers.converter import model_surface as model_surface_router
from core.model_surface.types import ModelSurfaceError


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
    candidates = data["surface_candidates"]
    assert len(candidates) >= 6
    assert candidates[0]["area_mm2"] >= candidates[-1]["area_mm2"]
    assert candidates[0]["face_index"] >= 0
    assert candidates[0]["footprint"]["area_mm2"] > 0


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


def test_model_surface_select_accepts_surface_candidate_id(tmp_path, client: TestClient):
    model_path = tmp_path / "plate.stl"
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(model_path)

    with model_path.open("rb") as fh:
        upload = client.post(
            "/api/convert/model-surface/upload",
            files={"model": ("plate.stl", fh, "application/octet-stream")},
        ).json()

    candidate = upload["surface_candidates"][0]
    response = client.post(
        "/api/convert/model-surface/select",
        json={
            "model_file_id": upload["model_file_id"],
            "hit": {"candidate_id": candidate["id"]},
            "model_transform": {
                "rotation_deg": {
                    "x": 10,
                    "y": 20,
                    "z": 30,
                }
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["selection"]["face_count"] == candidate["face_count"]
    assert data["footprint"]["area_mm2"] == pytest.approx(
        candidate["footprint"]["area_mm2"]
    )


def test_model_surface_select_candidate_id_uses_uploaded_candidate(
    tmp_path,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    model_path = tmp_path / "plate.stl"
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(model_path)

    with model_path.open("rb") as fh:
        upload = client.post(
            "/api/convert/model-surface/upload",
            files={"model": ("plate.stl", fh, "application/octet-stream")},
        ).json()

    candidate = upload["surface_candidates"][0]

    def fail_if_seed_face_selection_is_used(*_args, **_kwargs):
        raise ModelSurfaceError("candidate selection should not reselect a seed face")

    monkeypatch.setattr(
        model_surface_router,
        "select_planar_component",
        fail_if_seed_face_selection_is_used,
    )

    response = client.post(
        "/api/convert/model-surface/select",
        json={
            "model_file_id": upload["model_file_id"],
            "hit": {"candidate_id": candidate["id"]},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["selection"]["face_count"] == candidate["face_count"]
    assert data["footprint"]["area_mm2"] == pytest.approx(
        candidate["footprint"]["area_mm2"]
    )


def test_model_surface_select_candidate_id_uses_cached_candidate_without_reloading_mesh(
    tmp_path,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    model_path = tmp_path / "plate.stl"
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(model_path)

    with model_path.open("rb") as fh:
        upload = client.post(
            "/api/convert/model-surface/upload",
            files={"model": ("plate.stl", fh, "application/octet-stream")},
        ).json()

    candidate = upload["surface_candidates"][0]

    def fail_if_mesh_is_reloaded(*_args, **_kwargs):
        raise ModelSurfaceError("cached candidate selection should not reload mesh")

    monkeypatch.setattr(
        model_surface_router,
        "load_model_surface_mesh",
        fail_if_mesh_is_reloaded,
    )

    response = client.post(
        "/api/convert/model-surface/select",
        json={
            "model_file_id": upload["model_file_id"],
            "hit": {"candidate_id": candidate["id"]},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["selection"]["face_count"] == candidate["face_count"]
    assert data["footprint"]["area_mm2"] == pytest.approx(
        candidate["footprint"]["area_mm2"]
    )
