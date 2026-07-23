from __future__ import annotations

import json
import os
import pickle
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient
from fastapi import HTTPException
from PIL import Image

from api.app import app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.routers.converter.model_surface import resolve_surface_preview_config
from api.session_store import SessionStore


@pytest.fixture()
def preview_state():
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    pool = type("FakePool", (), {})()
    previous = {
        get_session_store: app.dependency_overrides.get(get_session_store),
        get_file_registry: app.dependency_overrides.get(get_file_registry),
        get_worker_pool: app.dependency_overrides.get(get_worker_pool),
    }
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: pool
    try:
        yield store, registry, pool
    finally:
        store.clear_all()
        registry.clear_all()
        for dependency, old_override in previous.items():
            if old_override is None:
                app.dependency_overrides.pop(dependency, None)
            else:
                app.dependency_overrides[dependency] = old_override


def test_preview_attaches_model_surface_config(monkeypatch, tmp_path, preview_state):
    store, _registry, pool = preview_state
    model_path = tmp_path / "plate.stl"
    image_path = tmp_path / "art.png"
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(model_path)
    Image.new("RGB", (40, 20), (255, 0, 0)).save(image_path)
    client = TestClient(app, raise_server_exceptions=False)

    with model_path.open("rb") as fh:
        upload = client.post(
            "/api/convert/model-surface/upload",
            files={"model": ("plate.stl", fh, "application/octet-stream")},
        ).json()
    selected = client.post(
        "/api/convert/model-surface/select",
        json={
            "model_file_id": upload["model_file_id"],
            "hit": {"candidate_id": upload["surface_candidates"][0]["id"]},
        },
    ).json()

    async def fake_submit(fn, *args):
        return _fake_worker_result(tmp_path)

    pool.submit = AsyncMock(side_effect=fake_submit)

    with (
        patch(
            "api.routers.converter.preview.LUTManager.resolve_source_selection",
            return_value=("/tmp/fake.npy", "Fake LUT"),
        ),
        patch(
            "api.routers.converter.preview.generate_segmented_glb",
            return_value=None,
        ),
    ):
        with image_path.open("rb") as fh:
            response = client.post(
                "/api/convert/preview",
                files={"image": ("art.png", fh, "image/png")},
                data={
                    "lut_name": "default",
                    "target_width_mm": "20",
                    "color_mode": "4-Color (RYBW)",
                    "modeling_mode": "high-fidelity",
                    "quantize_colors": "8",
                    "enable_cleanup": "true",
                    "surface_model_file_id": upload["model_file_id"],
                    "surface_selection_json": json.dumps(selected["selection"]),
                    "surface_footprint_json": json.dumps(
                        {
                            "bounds_width_mm": 2000,
                            "bounds_height_mm": 1000,
                            "outer": [[-1000, -500], [1000, -500], [1000, 500], [-1000, 500]],
                            "holes": [],
                            "frame": {
                                "origin": [0, 0, 1],
                                "normal": [0, 0, 1],
                                "u_axis": [1, 0, 0],
                                "v_axis": [0, 1, 0],
                            },
                        }
                    ),
                    "surface_placement_json": json.dumps(
                        {
                            "mode": "edge_to_edge",
                            "offset_x_mm": 5,
                            "offset_y_mm": 0,
                            "scale": 0.5,
                            "rotation_deg": 0,
                            "inset_mm": 0,
                        }
                    ),
                    "surface_model_transform_json": json.dumps(
                        {
                            "rotation_deg": {
                                "x": 10,
                                "y": 20,
                                "z": 30,
                            }
                        }
                    ),
                },
            )

    assert response.status_code == 200, response.text
    session = store.get(response.json()["session_id"])
    assert session is not None
    assert session["surface_model_path"].endswith(".stl")
    assert session["surface_overlay_enabled"] is True
    assert session["surface_model_transform"] == {
        "rotation_deg": {
            "x": 10,
            "y": 20,
            "z": 30,
        }
    }
    assert session["surface_placement"] == {
        "mode": "edge_to_edge",
        "offset_x_mm": 5.0,
        "offset_y_mm": 0.0,
        "scale": 0.5,
        "rotation_deg": 0.0,
        "inset_mm": 0.0,
    }
    assert Path(session["surface_artwork_path"]).exists()
    assert session["surface_footprint"]["bounds_width_mm"] == pytest.approx(
        selected["footprint"]["bounds_width_mm"]
    )
    assert session["surface_footprint"]["bounds_height_mm"] == pytest.approx(
        selected["footprint"]["bounds_height_mm"]
    )
    assert session["image_path"] == session["surface_artwork_path"]
    with Image.open(session["surface_artwork_path"]) as rendered:
        assert rendered.mode == "RGBA"
        assert rendered.size == (120, 60)
        assert rendered.getpixel((10, 30))[3] == 0
        assert rendered.getpixel((90, 30))[3] == 255


def test_preview_rejects_selection_from_a_different_uploaded_model(
    tmp_path,
    preview_state,
):
    _store, registry, _pool = preview_state
    first_model = tmp_path / "first.stl"
    second_model = tmp_path / "second.stl"
    image_path = tmp_path / "art.png"
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(first_model)
    trimesh.creation.box(extents=(30.0, 12.0, 3.0)).export(second_model)
    Image.new("RGB", (40, 20), (255, 0, 0)).save(image_path)
    client = TestClient(app, raise_server_exceptions=False)

    def upload(path: Path) -> dict:
        with path.open("rb") as handle:
            return client.post(
                "/api/convert/model-surface/upload",
                files={"model": (path.name, handle, "application/octet-stream")},
            ).json()

    first = upload(first_model)
    second = upload(second_model)
    selected = client.post(
        "/api/convert/model-surface/select",
        json={
            "model_file_id": first["model_file_id"],
            "hit": {"candidate_id": first["surface_candidates"][0]["id"]},
        },
    ).json()

    with pytest.raises(HTTPException, match="Invalid model surface preview"):
        resolve_surface_preview_config(
            registry=registry,
            model_file_id=second["model_file_id"],
            selection_json=json.dumps(selected["selection"]),
            footprint_json=json.dumps(selected["footprint"]),
            placement_json=json.dumps(
                {
                    "mode": "edge_to_edge",
                    "offset_x_mm": 0,
                    "offset_y_mm": 0,
                    "scale": 1,
                    "rotation_deg": 0,
                    "inset_mm": 0,
                }
            ),
            source_path=str(image_path),
        )


def _fake_worker_result(tmp_path) -> dict:
    preview_path = tmp_path / "preview.png"
    Image.new("RGBA", (20, 10), (255, 0, 0, 255)).save(preview_path)
    cache = {
        "matched_rgb": np.zeros((10, 20, 3), dtype=np.uint8),
        "mask_solid": np.ones((10, 20), dtype=bool),
        "quantized_image": np.zeros((10, 20, 3), dtype=np.uint8),
        "preview_rgba": np.zeros((10, 20, 4), dtype=np.uint8),
        "color_palette": [
            {
                "hex": "#ff0000",
                "color": (255, 0, 0),
                "count": 200,
                "percentage": 100.0,
            }
        ],
        "target_w": 20,
        "target_h": 10,
    }
    fd, cache_path = tempfile.mkstemp(suffix=".pkl", dir=tmp_path)
    os.close(fd)
    with open(cache_path, "wb") as handle:
        pickle.dump(cache, handle)
    return {
        "preview_png_path": str(preview_path),
        "cache_data_path": str(cache_path),
        "status_msg": "ok",
    }
