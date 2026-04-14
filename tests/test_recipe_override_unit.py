"""Unit tests for predictive custom recipe endpoints."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from config import LUTMetadata, PaletteEntry


_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()


def setup_module(module) -> None:
    app.dependency_overrides[get_session_store] = lambda: _test_store
    app.dependency_overrides[get_file_registry] = lambda: _test_registry


def teardown_module(module) -> None:
    app.dependency_overrides.pop(get_session_store, None)
    app.dependency_overrides.pop(get_file_registry, None)


setup_module(None)
client = TestClient(app)


def _make_metadata() -> LUTMetadata:
    return LUTMetadata(
        palette=[
            PaletteEntry(color="White", material="PLA Basic"),
            PaletteEntry(color="Red", material="PLA Basic"),
        ],
        color_mode="4-Color (RYBW)",
        max_color_layers=5,
        layer_height_mm=0.08,
        base_channel_idx=0,
        layer_order="Top2Bottom",
        capabilities=["predictive_match", "custom_recipe", "predictive_model", "dynamic_layer_count"],
    )


def _create_recipe_session(tmp_path: Path) -> tuple[str, str]:
    sid = _test_store.create()
    lut_path = tmp_path / "source.json"
    lut_path.write_text("{}", encoding="utf-8")
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    material_matrix = np.zeros((4, 4, 5), dtype=np.int32)
    mask = np.zeros((4, 4), dtype=bool)
    mask[:2, :2] = True
    _test_store.put(
        sid,
        "preview_cache",
        {
            "matched_rgb": matched_rgb,
            "material_matrix": material_matrix,
            "mask_solid": np.ones((4, 4), dtype=bool),
            "color_contours": {},
        },
    )
    _test_store.put(sid, "lut_path", str(lut_path))
    _test_store.put(sid, "selected_region_mask", mask)
    _test_store.put(sid, "selected_region_id", "region-a")
    _test_store.put(sid, "selected_region_masks", {"region-a": mask})
    return sid, str(lut_path)


def test_predict_recipe_endpoint(monkeypatch, tmp_path: Path) -> None:
    sid, lut_path = _create_recipe_session(tmp_path)
    metadata = _make_metadata()

    monkeypatch.setattr(
        "api.routers.converter.replace.LUTManager.load_lut_with_metadata",
        lambda path: (np.zeros((0, 3), dtype=np.uint8), None, metadata),
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.predict_recipe_color",
        lambda *args, **kwargs: {
            "rgb": [12, 34, 56],
            "lab": [10.0, 2.0, 3.0],
            "source": "stage_model",
            "runtime_mode_key": "0.08x5",
        },
    )

    response = client.post(
        "/api/convert/predict-recipe",
        json={
            "session_id": sid,
            "recipe": [1, 1, 0, 0, 0],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rgb"] == [12, 34, 56]
    assert body["runtime_mode_key"] == "0.08x5"


def test_apply_recipe_override_upgrades_cache(monkeypatch, tmp_path: Path) -> None:
    sid, lut_path = _create_recipe_session(tmp_path)
    metadata = _make_metadata()

    monkeypatch.setattr(
        "api.routers.converter.replace.LUTManager.load_lut_with_metadata",
        lambda path: (np.zeros((0, 3), dtype=np.uint8), None, metadata),
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.predict_recipe_color",
        lambda *args, **kwargs: {
            "rgb": [200, 100, 50],
            "lab": [60.0, 5.0, 10.0],
            "source": "stage_model",
            "runtime_mode_key": "0.08x6",
        },
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.generate_segmented_glb",
        lambda cache: None,
    )

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": sid,
            "region_ids": ["region-a"],
            "recipe": [1, 1, 1, 0, 0, 0],
            "layer_order": "Top2Bottom",
            "color_layers": 6,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["override_count"] == 1
    cache = _test_store.get(sid)["preview_cache"]
    assert cache["material_matrix"].shape[2] == 6
    assert cache["matched_rgb"][0, 0].tolist() == [200, 100, 50]
    assert _test_store.get(sid)["recipe_override_count"] == 1
    assert _test_store.get(sid)["recipe_overrides"] == [
        {
            "region_id": "region-a",
            "recipe": [1, 1, 1, 0, 0, 0],
            "layer_order": "Top2Bottom",
            "color_layers": 6,
            "layer_height_mm": 0.08,
        }
    ]
