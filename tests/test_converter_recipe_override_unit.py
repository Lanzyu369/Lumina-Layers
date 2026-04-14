"""Unit tests for converter recipe prediction / override endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from config import LUTMetadata


def _client_with_state() -> tuple[TestClient, SessionStore, FileRegistry]:
    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    return TestClient(app), store, registry


def test_predict_recipe_endpoint_returns_prediction(monkeypatch, tmp_path: Path) -> None:
    client, store, _registry = _client_with_state()
    lut_path = tmp_path / "ref.msgpack"
    lut_path.write_bytes(b"package")

    session_id = store.create()
    store.put(session_id, "lut_path", str(lut_path))

    monkeypatch.setattr(
        "api.routers.converter.replace.LUTManager.load_lut_with_metadata",
        lambda _path: (
            np.zeros((0, 3), dtype=np.uint8),
            None,
            LUTMetadata(max_color_layers=10, layer_height_mm=0.08),
        ),
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.predict_recipe_color",
        lambda metadata, recipe, layer_height_mm, color_layers, layer_order: {
            "rgb": [12, 34, 56],
            "lab": [45.0, 1.0, -2.0],
            "source": "stage_model",
            "runtime_mode_key": "0.08x5",
        },
    )

    response = client.post(
        "/api/convert/predict-recipe",
        json={
            "session_id": session_id,
            "recipe": [0, 1, 2, 3, 4],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["rgb"] == [12, 34, 56]
    assert body["runtime_mode_key"] == "0.08x5"


def test_apply_recipe_override_endpoint_updates_preview_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, store, registry = _client_with_state()
    lut_path = tmp_path / "ref.msgpack"
    lut_path.write_bytes(b"package")

    session_id = store.create()
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    material_matrix = np.zeros((4, 4, 5), dtype=np.int32)
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    preview_cache = {
        "matched_rgb": matched_rgb.copy(),
        "material_matrix": material_matrix.copy(),
        "mask_solid": np.ones((4, 4), dtype=bool),
        "color_layers": 5,
        "layer_height_mm": 0.08,
    }
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "preview_cache", preview_cache)
    store.put(session_id, "selected_region_mask", mask)
    store.put(session_id, "selected_region_id", "region-1")
    store.put(session_id, "selected_region_masks", {"region-1": mask})

    monkeypatch.setattr(
        "api.routers.converter.replace.LUTManager.load_lut_with_metadata",
        lambda _path: (
            np.zeros((0, 3), dtype=np.uint8),
            None,
            LUTMetadata(max_color_layers=5, layer_height_mm=0.08, base_channel_idx=0),
        ),
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.predict_recipe_color",
        lambda metadata, recipe, layer_height_mm, color_layers, layer_order: {
            "rgb": [200, 100, 50],
            "lab": [55.0, 2.0, 3.0],
            "source": "stage_model",
            "runtime_mode_key": "0.08x5",
        },
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.generate_segmented_glb",
        lambda cache: None,
    )

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "recipe": [1, 1, 1, 1, 1],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["rgb"] == [200, 100, 50]
    assert body["override_count"] == 1

    session_data = store.get(session_id)
    assert session_data is not None
    updated_cache = session_data["preview_cache"]
    assert np.all(updated_cache["matched_rgb"][mask] == np.array([200, 100, 50], dtype=np.uint8))
    assert np.all(updated_cache["material_matrix"][mask] == np.array([1, 1, 1, 1, 1], dtype=np.int32))
    assert session_data["recipe_overrides"] == [
        {
            "region_id": "region-1",
            "recipe": [1, 1, 1, 1, 1],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        }
    ]

    file_id = body["preview_url"].split("/")[-1]
    assert registry.resolve(file_id) is not None


def test_apply_recipe_override_handoff_to_generate_uses_session_persisted_region_items(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    mock_pool: MagicMock = MagicMock(spec=WorkerPoolManager)
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: mock_pool
    client = TestClient(app)

    lut_path = tmp_path / "ref.msgpack"
    lut_path.write_bytes(b"package")
    image_path = tmp_path / "input.png"
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)

    session_id = store.create()
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    material_matrix = np.zeros((4, 4, 5), dtype=np.int32)
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    preview_cache = {
        "matched_rgb": matched_rgb.copy(),
        "material_matrix": material_matrix.copy(),
        "mask_solid": np.ones((4, 4), dtype=bool),
        "color_layers": 5,
        "layer_height_mm": 0.08,
    }
    store.put(session_id, "image_path", str(image_path))
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "preview_cache", preview_cache)
    store.put(session_id, "selected_region_mask", mask)
    store.put(session_id, "selected_region_id", "region-1")
    store.put(session_id, "selected_region_masks", {"region-1": mask})

    monkeypatch.setattr(
        "api.routers.converter.replace.LUTManager.load_lut_with_metadata",
        lambda _path: (
            np.zeros((0, 3), dtype=np.uint8),
            None,
            LUTMetadata(max_color_layers=5, layer_height_mm=0.08, base_channel_idx=0),
        ),
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.predict_recipe_color",
        lambda metadata, recipe, layer_height_mm, color_layers, layer_order: {
            "rgb": [200, 100, 50],
            "lab": [55.0, 2.0, 3.0],
            "source": "stage_model",
            "runtime_mode_key": "0.08x5",
        },
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.generate_segmented_glb",
        lambda cache: None,
    )

    apply_response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "recipe": [1, 1, 1, 1, 1],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
    )

    assert apply_response.status_code == 200

    out_3mf = tmp_path / "generated.3mf"
    out_3mf.write_bytes(b"3mf")
    out_glb = tmp_path / "generated.glb"
    out_glb.write_bytes(b"glb")
    mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": str(out_3mf),
            "glb_path": str(out_glb),
            "status_msg": "OK",
        }
    )

    generate_response = client.post(
        "/api/convert/generate",
        json={
            "session_id": session_id,
            "params": {
                "lut_name": "test_lut",
                "use_cached_matched_rgb": True,
            },
        },
    )

    assert generate_response.status_code == 200
    submitted_params = mock_pool.submit.call_args.args[3]
    assert submitted_params["recipe_overrides"] == [
        {
            "region_id": "region-1",
            "recipe": [1, 1, 1, 1, 1],
            "layer_order": "Top2Bottom",
        }
    ]
