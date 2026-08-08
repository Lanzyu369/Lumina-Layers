"""Unit tests for converter recipe prediction / override endpoints."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import externalize_preview_cache, hydrate_preview_cache
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from config import LUTMetadata
from core.material_color_solver import (
    MaterialParams,
    predict_material_recipe_srgb,
)


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


def test_predict_recipe_endpoint_keeps_runtime_package_exact_miss_as_422(
    monkeypatch,
    tmp_path: Path,
) -> None:
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

    def _raise_package_only_exact_miss(*_args, **_kwargs):
        raise ValueError(
            "Recipe is not present in the runtime package; "
            "exact prediction unavailable for package-only source"
        )

    monkeypatch.setattr(
        "api.routers.converter.replace.predict_recipe_color",
        _raise_package_only_exact_miss,
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

    assert response.status_code == 422
    assert "Recipe is not present in the runtime package" in response.json()["detail"]


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
        "quantized_image": matched_rgb.copy(),
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
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
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


def test_apply_recipe_override_redacts_unexpected_file_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
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
        "quantized_image": matched_rgb.copy(),
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
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    private_path = "/Users/min/private/secret.png"

    def _raise_private_path(*_args, **_kwargs):
        raise OSError(f"[Errno 13] Permission denied: '{private_path}'")

    monkeypatch.setattr(registry, "register_bytes", _raise_private_path)

    logger = logging.getLogger("lumina.api.routers.converter.replace")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.ERROR, logger=logger.name)
    try:
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
    finally:
        logger.removeHandler(caplog.handler)

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Recipe override could not be applied. Check the server log for details."
    )
    assert "Permission denied" not in response.text
    assert private_path not in response.text
    assert "Traceback" not in response.text

    session_data = store.get(session_id)
    assert session_data is not None
    assert "recipe_overrides" not in session_data
    assert "recipe_override_count" not in session_data
    current_cache = session_data["preview_cache"]
    assert np.array_equal(current_cache["matched_rgb"], matched_rgb)
    assert np.array_equal(current_cache["material_matrix"], material_matrix)

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "converter_apply_recipe_override_error"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.error_type == "OSError"
    assert record.status_code == 422
    assert "Permission denied" in record.error_message
    assert private_path in record.error_message
    assert "Traceback" not in record.getMessage()
    assert private_path not in record.getMessage()
    assert record.exc_info is None


def test_region_recipe_resolves_select_all_color_region_id() -> None:
    client, store, _registry = _client_with_state()

    session_id = store.create()
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    matched_rgb[0, 0] = [170, 0, 0]
    matched_rgb[1, 1] = [170, 0, 0]
    matched_rgb[2, 2] = [0, 170, 0]
    material_matrix = np.zeros((4, 4, 5), dtype=np.int32)
    material_matrix[0, 0] = [2, 2, 2, 2, 2]
    material_matrix[1, 1] = [2, 2, 2, 2, 2]
    preview_cache = {
        "matched_rgb": matched_rgb.copy(),
        "material_matrix": material_matrix.copy(),
        "mask_solid": np.ones((4, 4), dtype=bool),
        "color_layers": 5,
        "layer_height_mm": 0.08,
    }
    store.put(session_id, "preview_cache", preview_cache)

    response = client.post(
        "/api/convert/region-recipe",
        json={
            "session_id": session_id,
            "region_ids": ["__select_all_color__:aa0000"],
            "layer_order": "Top2Bottom",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recipes"] == [
        {
            "region_id": "__select_all_color__:aa0000",
            "recipe": [2, 2, 2, 2, 2],
            "color_layers": 5,
            "layer_height_mm": 0.08,
            "layer_order": "Top2Bottom",
        }
    ]
    session_data = store.get(session_id)
    assert session_data is not None
    stored_mask = session_data["selected_region_masks"]["__select_all_color__:aa0000"]
    assert int(np.count_nonzero(stored_mask)) == 2
    assert bool(stored_mask[0, 0])
    assert bool(stored_mask[1, 1])
    assert not bool(stored_mask[2, 2])


def test_apply_recipe_override_resolves_select_all_color_region_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, store, _registry = _client_with_state()
    lut_path = tmp_path / "ref.msgpack"
    lut_path.write_bytes(b"package")

    session_id = store.create()
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    matched_rgb[0, 0] = [170, 0, 0]
    matched_rgb[1, 1] = [170, 0, 0]
    matched_rgb[2, 2] = [0, 170, 0]
    material_matrix = np.zeros((4, 4, 5), dtype=np.int32)
    preview_cache = {
        "matched_rgb": matched_rgb.copy(),
        "material_matrix": material_matrix.copy(),
        "mask_solid": np.ones((4, 4), dtype=bool),
        "color_layers": 5,
        "layer_height_mm": 0.08,
    }
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "preview_cache", preview_cache)

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
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["__select_all_color__:aa0000"],
            "recipe": [1, 1, 1, 1, 1],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200
    session_data = store.get(session_id)
    assert session_data is not None
    updated_cache = session_data["preview_cache"]
    stored_mask = session_data["selected_region_masks"]["__select_all_color__:aa0000"]
    assert int(np.count_nonzero(stored_mask)) == 2
    assert np.all(updated_cache["matched_rgb"][stored_mask] == np.array([200, 100, 50], dtype=np.uint8))
    assert np.all(updated_cache["material_matrix"][stored_mask] == np.array([1, 1, 1, 1, 1], dtype=np.int32))
    assert np.all(updated_cache["matched_rgb"][2, 2] == np.array([0, 170, 0], dtype=np.uint8))
    assert session_data["recipe_overrides"] == [
        {
            "region_id": "__select_all_color__:aa0000",
            "recipe": [1, 1, 1, 1, 1],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        }
    ]


def test_apply_recipe_override_artifact_resolves_select_all_color_region_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, store, _registry = _client_with_state()
    lut_path = tmp_path / "ref.msgpack"
    lut_path.write_bytes(b"package")

    session_id = store.create()
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    matched_rgb[0, 0] = [170, 0, 0]
    matched_rgb[1, 1] = [170, 0, 0]
    matched_rgb[2, 2] = [0, 170, 0]
    material_matrix = np.zeros((4, 4, 5), dtype=np.int32)
    cache_ref = externalize_preview_cache(
        session_id,
        store,
        {
            "matched_rgb": matched_rgb.copy(),
            "material_matrix": material_matrix.copy(),
            "mask_solid": np.ones((4, 4), dtype=bool),
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
        root_dir=tmp_path,
    )
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "preview_cache", cache_ref)

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
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    with patch(
        "api.routers.converter.common.hydrate_preview_cache",
        side_effect=AssertionError("select-all recipe override must not fully hydrate artifact cache"),
    ):
        response = client.post(
            "/api/convert/apply-recipe-override",
            json={
                "session_id": session_id,
                "region_ids": ["__select_all_color__:aa0000"],
                "recipe": [1, 1, 1, 1, 1],
                "layer_order": "Top2Bottom",
                "color_layers": 5,
                "layer_height_mm": 0.08,
            },
        )

    assert response.status_code == 200, response.text
    session_data = store.get(session_id)
    assert session_data is not None
    stored_mask = session_data["selected_region_masks"]["__select_all_color__:aa0000"]
    assert int(np.count_nonzero(stored_mask)) == 2
    updated_cache = hydrate_preview_cache(
        session_data["preview_cache"],
        fields={"matched_rgb", "material_matrix"},
    )
    assert np.all(updated_cache["matched_rgb"][stored_mask] == np.array([200, 100, 50], dtype=np.uint8))
    assert np.all(updated_cache["material_matrix"][stored_mask] == np.array([1, 1, 1, 1, 1], dtype=np.int32))


def test_apply_recipe_override_falls_back_to_pure_stack_when_forward_model_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """When no predictive runtime is available, apply must still succeed using
    the LUT's pure-channel stack as the preview color.

    当 LUT 没有前向模型时，应用自定义配方仍应成功：使用"最顶层通道"的纯堆叠
    配方 RGB 作为预览兜底色，保证用户手动选材料的工作不被丢弃。
    """
    client, store, _registry = _client_with_state()
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

    # LUT with a pure-stack recipe for channel 2 -> RGB (10, 20, 30).
    fake_stacks = np.array(
        [
            [0, 0, 0, 0, 0],
            [1, 1, 1, 1, 1],
            [2, 2, 2, 2, 2],
        ],
        dtype=np.int32,
    )
    fake_rgb = np.array(
        [
            [0, 0, 0],
            [255, 255, 255],
            [10, 20, 30],
        ],
        dtype=np.uint8,
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.LUTManager.load_lut_with_metadata",
        lambda _path: (
            fake_rgb,
            fake_stacks,
            LUTMetadata(max_color_layers=5, layer_height_mm=0.08, base_channel_idx=0),
        ),
    )

    def _raise_no_runtime(*_args, **_kwargs):
        raise ValueError("No predictive runtime available for this source")

    monkeypatch.setattr(
        "api.routers.converter.replace.predict_recipe_color",
        _raise_no_runtime,
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            # Top layer (Top2Bottom -> recipe[0]) is channel 2 -> expected fallback color.
            "recipe": [2, 1, 0, 0, 0],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["rgb"] == [10, 20, 30]

    session_data = store.get(session_id)
    assert session_data is not None
    updated_cache = session_data["preview_cache"]
    assert np.all(
        updated_cache["matched_rgb"][mask] == np.array([10, 20, 30], dtype=np.uint8)
    )
    assert updated_cache["lut_match_info"]["match_mode"] == "pure_stack_fallback"
    assert updated_cache["lut_match_info"]["source"] == "pure_stack_fallback"


def test_apply_recipe_override_falls_back_when_runtime_package_lacks_recipe(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Package-only predictive LUTs must not block applying custom recipes.

    反推 LUT 的 runtime 包只能精确预测包内配方；自定义配方不在包内时，
    预览颜色可以报无法精确预测，但应用配方必须继续走纯色栈兜底。
    """
    client, store, _registry = _client_with_state()
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

    fake_stacks = np.array(
        [
            [0, 0, 0, 0, 0],
            [1, 1, 1, 1, 1],
            [2, 2, 2, 2, 2],
        ],
        dtype=np.int32,
    )
    fake_rgb = np.array(
        [
            [0, 0, 0],
            [255, 255, 255],
            [10, 20, 30],
        ],
        dtype=np.uint8,
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.LUTManager.load_lut_with_metadata",
        lambda _path: (
            fake_rgb,
            fake_stacks,
            LUTMetadata(max_color_layers=5, layer_height_mm=0.08, base_channel_idx=0),
        ),
    )

    def _raise_package_only_exact_miss(*_args, **_kwargs):
        raise ValueError(
            "Recipe is not present in the runtime package; "
            "exact prediction unavailable for package-only source"
        )

    monkeypatch.setattr(
        "api.routers.converter.replace.predict_recipe_color",
        _raise_package_only_exact_miss,
    )

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "recipe": [2, 1, 0, 0, 0],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["rgb"] == [10, 20, 30]

    session_data = store.get(session_id)
    assert session_data is not None
    updated_cache = session_data["preview_cache"]
    assert np.all(
        updated_cache["matched_rgb"][mask] == np.array([10, 20, 30], dtype=np.uint8)
    )
    assert np.all(
        updated_cache["material_matrix"][mask]
        == np.array([2, 1, 0, 0, 0], dtype=np.int32)
    )
    assert updated_cache["lut_match_info"]["match_mode"] == "runtime_package_fallback"
    assert updated_cache["lut_match_info"]["source"] == "runtime_package_fallback"
    assert session_data["recipe_overrides"] == [
        {
            "region_id": "region-1",
            "recipe": [2, 1, 0, 0, 0],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        }
    ]


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
        "target_w": 4,
        "target_h": 4,
        "target_width_mm": 60.0,
        "color_mode": "4-Color (RYBW)",
        "modeling_mode": "high-fidelity",
        "color_layers": 5,
        "layer_height_mm": 0.08,
        "quantize_colors": 48,
        "enable_cleanup": True,
        "hue_weight": 0.0,
        "chroma_gate": 15.0,
        "use_lut_constrained": False,
        "auto_dynamic_range": False,
        "model_enable": False,
        "model_only": False,
        "model_threshold": None,
        "model_margin": None,
        "svg_pixels_per_mm": 10.0,
        "material_source": "lut",
    }
    store.put(session_id, "image_path", str(image_path))
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "preview_cache", preview_cache)
    store.put(session_id, "color_layers", 5)
    store.put(session_id, "layer_height_mm", 0.08)
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
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
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
            "color_layers": 5,
        }
    ]


def test_apply_recipe_override_accepts_virtual_materials_and_extends_palette(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Applying a recipe with ``virtual_materials`` must extend the preview
    cache palette and paint the region with the user-declared hex.

    带 ``virtual_materials`` 应用自定义配方时，apply 端点应：
    - 在 ``preview_colors`` / ``slot_names`` / ``color_conf`` 里追加虚拟槽位；
    - 顶层是虚拟耗材时按其 hex 上色 (``match_mode == virtual_material``)；
    - 把 virtual_materials 持久化进 session 的 recipe_overrides。
    """
    client, store, _registry = _client_with_state()
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
        # Pre-seed the 4-channel CMYW palette the pipeline would build in p01.
        # 预置 CMYW 4 通道的调色板，模拟管线 p01 构建后的状态。
        "preview_colors": {
            0: [245, 245, 245, 255],
            1: [0, 183, 235, 255],
            2: [230, 0, 126, 255],
            3: [255, 212, 0, 255],
        },
        "slot_names": ["White", "Cyan", "Magenta", "Yellow"],
        "color_conf": {
            "preview": {
                0: [245, 245, 245, 255],
                1: [0, 183, 235, 255],
                2: [230, 0, 126, 255],
                3: [255, 212, 0, 255],
            },
            "slots": ["White", "Cyan", "Magenta", "Yellow"],
        },
    }
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "preview_cache", preview_cache)
    store.put(session_id, "selected_region_mask", mask)
    store.put(session_id, "selected_region_id", "region-1")
    store.put(session_id, "selected_region_masks", {"region-1": mask})

    # LUT metadata mirrors the cache: 4 real channels, no forward model.
    palette_entry_cls = type(
        "_PaletteEntry", (), {"__init__": lambda self, color: setattr(self, "color", color)}
    )
    metadata = LUTMetadata(
        max_color_layers=5, layer_height_mm=0.08, base_channel_idx=0
    )
    metadata.palette = [palette_entry_cls(name) for name in preview_cache["slot_names"]]
    metadata.layer_order = "Top2Bottom"
    monkeypatch.setattr(
        "api.routers.converter.replace.LUTManager.load_lut_with_metadata",
        lambda _path: (np.zeros((0, 3), dtype=np.uint8), None, metadata),
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            # Topmost layer (Top2Bottom -> recipe[0]) == virtual index 4
            # which is the first virtual material (Black).
            # 顶层（Top2Bottom -> recipe[0]）为虚拟索引 4，即首个虚拟耗材 Black。
            "recipe": [4, 4, 4, 4, 4],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
            "virtual_materials": [{"name": "Black", "hex": "#111111"}],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["rgb"] == [17, 17, 17], body
    assert body["source"] == "virtual_material"

    session_data = store.get(session_id)
    assert session_data is not None
    updated_cache = session_data["preview_cache"]
    # Region is painted with the user's intent hex, not a LUT substitute.
    assert np.all(
        updated_cache["matched_rgb"][mask] == np.array([17, 17, 17], dtype=np.uint8)
    )
    # material_matrix carries the virtual channel index (4 == LUT.N + 0).
    assert np.all(
        updated_cache["material_matrix"][mask] == np.array([4, 4, 4, 4, 4])
    )
    # Palette was extended with the declared virtual material.
    assert updated_cache["slot_names"][:5] == [
        "White",
        "Cyan",
        "Magenta",
        "Yellow",
        "Black",
    ]
    assert updated_cache["preview_colors"][4] == [17, 17, 17, 255]
    assert updated_cache["color_conf"]["preview"][4] == [17, 17, 17, 255]
    assert updated_cache["color_conf"]["slots"][4] == "Black"
    assert updated_cache["lut_match_info"]["match_mode"] == "virtual_material"
    # Session-persisted override round-trips the virtual_materials list.
    assert session_data["recipe_overrides"] == [
        {
            "region_id": "region-1",
            "recipe": [4, 4, 4, 4, 4],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
            "virtual_materials": [{"name": "Black", "hex": "#111111"}],
        }
    ]


def test_apply_recipe_override_preserves_high_virtual_material_indices(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, store, _registry = _client_with_state()
    lut_path = tmp_path / "ref.msgpack"
    lut_path.write_bytes(b"package")

    session_id = store.create()
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    material_matrix = np.zeros((4, 4, 2), dtype=np.int32)
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    preview_cache = {
        "matched_rgb": matched_rgb,
        "material_matrix": material_matrix,
        "mask_solid": np.ones((4, 4), dtype=bool),
        "color_layers": 2,
        "layer_height_mm": 0.08,
        "preview_colors": {0: [245, 245, 245, 255]},
        "slot_names": ["White"],
        "color_conf": {
            "preview": {0: [245, 245, 245, 255]},
            "slots": ["White"],
        },
    }
    preview_cache_ref = externalize_preview_cache(
        session_id,
        store,
        preview_cache,
        root_dir=tmp_path,
    )
    assert preview_cache_ref["fields"]["material_matrix"]["dtype"] == "int8"
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "preview_cache", preview_cache_ref)
    store.put(session_id, "selected_region_mask", mask)
    store.put(session_id, "selected_region_id", "region-1")
    store.put(session_id, "selected_region_masks", {"region-1": mask})

    palette_entry_cls = type(
        "_PaletteEntry", (), {"__init__": lambda self, color: setattr(self, "color", color)}
    )
    metadata = LUTMetadata(
        max_color_layers=2, layer_height_mm=0.08, base_channel_idx=0
    )
    metadata.palette = [palette_entry_cls(f"slot-{idx}") for idx in range(1024)]
    metadata.layer_order = "Top2Bottom"
    monkeypatch.setattr(
        "api.routers.converter.replace.LUTManager.load_lut_with_metadata",
        lambda _path: (np.zeros((0, 3), dtype=np.uint8), None, metadata),
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "recipe": [0, 1024],
            "layer_order": "Top2Bottom",
            "color_layers": 2,
            "layer_height_mm": 0.08,
            "virtual_materials": [{"name": "HighVirtual", "hex": "#222222"}],
        },
    )

    assert response.status_code == 200, response.text
    session_data = store.get(session_id)
    assert session_data is not None
    updated_cache = hydrate_preview_cache(
        session_data["preview_cache"],
        fields={"material_matrix"},
    )
    updated_matrix = updated_cache["material_matrix"]
    assert updated_matrix.dtype == np.dtype(np.int16)
    np.testing.assert_array_equal(
        updated_matrix[mask],
        np.tile(np.array([0, 1024], dtype=np.int16), (int(mask.sum()), 1)),
    )


def test_apply_recipe_override_does_not_pollute_shared_color_system(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Applying virtual materials must not mutate the shared ColorSystem dict.

    apply 端点里的 ``_extend_cache_palette_with_virtuals`` 之前直接在 cache
    内共享的 ColorSystem dict / 列表上 ``append``，导致后续所有请求都看到
    被污染的调色板（slot_names 变长、preview_colors 多出 key），表现为
    透明失效 / 模型变方块 / 非 override 区域丢配方。回归保证：apply 后
    ``ColorSystem.get(color_mode)`` 的 ``slots`` / ``preview`` / ``map`` 长度
    与调用前完全一致。
    """
    from config import ColorSystem

    client, store, _registry = _client_with_state()
    lut_path = tmp_path / "ref.msgpack"
    lut_path.write_bytes(b"package")

    # Snapshot the shared ColorSystem 4-Color dict BEFORE any apply runs.
    four_color = ColorSystem.get("4-Color")
    original_slots = list(four_color["slots"])
    original_preview_keys = sorted(four_color["preview"].keys())
    original_map = dict(four_color["map"])

    session_id = store.create()
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    material_matrix = np.zeros((4, 4, 5), dtype=np.int32)
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    # Wire the cache to reuse the shared ColorSystem refs so a naive helper
    # would mutate them in place (exactly how p04_cache_building + p01 do).
    # 按 p04/p01 的真实做法，让 cache 直接复用 ColorSystem 的共享 dict/list。
    preview_cache = {
        "matched_rgb": matched_rgb.copy(),
        "material_matrix": material_matrix.copy(),
        "mask_solid": np.ones((4, 4), dtype=bool),
        "color_layers": 5,
        "layer_height_mm": 0.08,
        "preview_colors": four_color["preview"],
        "slot_names": four_color["slots"],
        "color_conf": four_color,
    }
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "preview_cache", preview_cache)
    store.put(session_id, "selected_region_mask", mask)
    store.put(session_id, "selected_region_id", "region-1")
    store.put(session_id, "selected_region_masks", {"region-1": mask})

    palette_entry_cls = type(
        "_PaletteEntry", (), {"__init__": lambda self, color: setattr(self, "color", color)}
    )
    metadata = LUTMetadata(
        max_color_layers=5, layer_height_mm=0.08, base_channel_idx=0
    )
    metadata.palette = [palette_entry_cls(name) for name in original_slots]
    metadata.layer_order = "Top2Bottom"
    monkeypatch.setattr(
        "api.routers.converter.replace.LUTManager.load_lut_with_metadata",
        lambda _path: (np.zeros((0, 3), dtype=np.uint8), None, metadata),
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    lut_n = len(original_slots)
    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "recipe": [lut_n, lut_n, lut_n, lut_n, lut_n],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
            "virtual_materials": [{"name": "Black", "hex": "#111111"}],
        },
    )

    assert response.status_code == 200, response.text

    # ColorSystem global state must be byte-identical to the snapshot.
    four_color_after = ColorSystem.get("4-Color")
    assert four_color_after["slots"] == original_slots
    assert sorted(four_color_after["preview"].keys()) == original_preview_keys
    assert dict(four_color_after["map"]) == original_map

    # The cache, however, MUST carry the extended virtual slot (copy-on-write).
    session_data = store.get(session_id)
    assert session_data is not None
    cache_after = session_data["preview_cache"]
    assert cache_after["slot_names"][lut_n] == "Black"
    assert cache_after["preview_colors"][lut_n] == [17, 17, 17, 255]
    # Cache must own DISTINCT containers (not point back at ColorSystem).
    assert cache_after["slot_names"] is not four_color_after["slots"]
    assert cache_after["preview_colors"] is not four_color_after["preview"]
    assert cache_after["color_conf"] is not four_color_after


def test_apply_recipe_override_rejects_out_of_range_virtual_index(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Recipe indices beyond ``LUT.N + len(virtual_materials)`` must 422.

    ``virtual_materials`` 提供后，超出 ``LUT.N + 虚拟耗材数`` 的索引应 422 拒绝，
    避免坏值被静默写进 material_matrix。
    """
    client, store, _registry = _client_with_state()
    lut_path = tmp_path / "ref.msgpack"
    lut_path.write_bytes(b"package")

    session_id = store.create()
    preview_cache = {
        "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
        "material_matrix": np.zeros((4, 4, 5), dtype=np.int32),
        "mask_solid": np.ones((4, 4), dtype=bool),
        "color_layers": 5,
        "layer_height_mm": 0.08,
    }
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "preview_cache", preview_cache)
    store.put(session_id, "selected_region_mask", mask)
    store.put(session_id, "selected_region_id", "region-1")
    store.put(session_id, "selected_region_masks", {"region-1": mask})

    palette_entry_cls = type(
        "_PaletteEntry", (), {"__init__": lambda self, color: setattr(self, "color", color)}
    )
    metadata = LUTMetadata(
        max_color_layers=5, layer_height_mm=0.08, base_channel_idx=0
    )
    metadata.palette = [palette_entry_cls("White"), palette_entry_cls("Cyan")]
    metadata.layer_order = "Top2Bottom"
    monkeypatch.setattr(
        "api.routers.converter.replace.LUTManager.load_lut_with_metadata",
        lambda _path: (np.zeros((0, 3), dtype=np.uint8), None, metadata),
    )

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            # LUT has 2 channels + 1 virtual material -> allowed_upper == 3.
            # Index 5 is out of range; must 422 with a precise detail.
            # LUT 2 通道 + 1 虚拟 -> 上限 3；索引 5 越界，应 422 并附精确原因。
            "recipe": [5, 0, 0, 0, 0],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
            "virtual_materials": [{"name": "Black", "hex": "#111111"}],
        },
    )

    assert response.status_code == 422, response.text
    detail = response.json()
    message = detail.get("detail") if isinstance(detail, dict) else None
    assert isinstance(message, str)
    assert "recipe[0]=5" in message
    assert "out of range" in message


def test_apply_recipe_override_pads_grown_layers_with_mask_solid_aware_fill(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Growing color_layers needs BOTH air outside and base-fill inside.

    Regression for two linked bugs the user hit back-to-back when the custom
    recipe forces ``color_layers`` to exceed the cache's current layer count:

    (#1) Uniformly padding with ``base_channel_idx`` re-materialises every
    single pixel at the new layers — including the transparent background
    ``~mask_solid``. S06/S07 then emit a solid mesh ringing the model
    silhouette at the extended Z ("第 6 层被白矩形包裹 / 透明通道失效").

    (#2) Uniformly padding with ``-1`` (air) fixes #1 but now the mask-solid
    interior of every non-override pixel loses its material at the grown
    layers, so the user's 6th layer collapses into an empty silhouette
    outside the override ("第 6 层空层").

    The correct pad slab is ``-1`` everywhere except the ``mask_solid``
    interior, which gets ``base_channel_idx``. The override region is
    overwritten with the user's recipe afterwards.

    同时回归两个 bug：(1) 统一填 base_channel_idx 会把透明背景也实体化
    成白色矩形；(2) 统一填 -1 又会让第 6 层的非 override 区域变空层。
    正确的 pad slab：整体 -1，仅 mask_solid 内部写 base_channel_idx。
    """
    client, store, _registry = _client_with_state()
    lut_path = tmp_path / "ref.msgpack"
    lut_path.write_bytes(b"package")

    session_id = store.create()
    # Start from a 3-layer cache so the 6-layer request forces padding.
    material_matrix = np.zeros((4, 4, 3), dtype=np.int32)
    # Transparent border (p03-style): ``~mask_solid`` ring already marked -1.
    # 透明边框：p03 约定 ~mask_solid 的像素先标为 -1。
    mask_solid = np.zeros((4, 4), dtype=bool)
    mask_solid[1:3, :] = True  # interior rows are solid
    material_matrix[~mask_solid] = -1

    # Override region sits inside mask_solid (2x1 block); non-override solid
    # pixels and transparent pixels are exercised separately below.
    # override 区域落在 mask_solid 之内（2x1），然后分别验证 mask_solid 内
    # 的非 override 像素和 mask_solid 外的透明像素。
    override_mask = np.zeros((4, 4), dtype=bool)
    override_mask[1:3, 1] = True

    preview_cache = {
        "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
        "material_matrix": material_matrix.copy(),
        "mask_solid": mask_solid.copy(),
        "color_layers": 3,
        "layer_height_mm": 0.08,
    }
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "preview_cache", preview_cache)
    store.put(session_id, "selected_region_mask", override_mask)
    store.put(session_id, "selected_region_id", "region-1")
    store.put(session_id, "selected_region_masks", {"region-1": override_mask})

    metadata = LUTMetadata(
        max_color_layers=6, layer_height_mm=0.08, base_channel_idx=0
    )
    metadata.layer_order = "Top2Bottom"
    monkeypatch.setattr(
        "api.routers.converter.replace.LUTManager.load_lut_with_metadata",
        lambda _path: (np.zeros((0, 3), dtype=np.uint8), None, metadata),
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.predict_recipe_color",
        lambda metadata, recipe, layer_height_mm, color_layers, layer_order: {
            "rgb": [100, 50, 25],
            "lab": [35.0, 10.0, 20.0],
            "source": "stage_model",
            "runtime_mode_key": "0.08x6",
        },
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "recipe": [1, 1, 1, 1, 1, 1],
            "layer_order": "Top2Bottom",
            "color_layers": 6,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200, response.text

    session_data = store.get(session_id)
    assert session_data is not None
    cache_after = session_data["preview_cache"]
    updated_matrix = cache_after["material_matrix"]
    assert updated_matrix.shape == (4, 4, 6)

    # (1) Override region: all 6 layers carry the recipe (channel 1).
    assert np.all(updated_matrix[override_mask] == 1)

    # (2) Transparent background (``~mask_solid``) at the GROWN layers must
    # stay air (-1) so S07 does not emit a ring-shaped White mesh. Fixes
    # the "整块白矩形包裹 / 透明通道失效" regression.
    transparent_grown = updated_matrix[~mask_solid][:, 3:6]
    assert np.all(transparent_grown == -1), transparent_grown.tolist()

    # (3) Mask-solid INTERIOR non-override pixels at the GROWN layers must
    # be ``base_channel_idx`` (0 here — White on CMYW) so the extended
    # column stays continuous with the backing slab. Fixes the "第 6 层
    # 空层 / 丢失背板轮廓" regression.
    solid_non_override = mask_solid & ~override_mask
    solid_non_override_grown = updated_matrix[solid_non_override][:, 3:6]
    assert np.all(solid_non_override_grown == 0), solid_non_override_grown.tolist()

    # (4) Pre-existing layers are preserved bit-for-bit for non-override
    # pixels: transparent stays -1, solid stays 0.
    assert np.all(updated_matrix[~mask_solid][:, :3] == -1)
    assert np.all(updated_matrix[solid_non_override][:, :3] == 0)


def test_apply_recipe_override_material_archive_pads_grown_layers_with_white_slot(
    monkeypatch,
) -> None:
    client, store, _registry = _client_with_state()

    session_id = store.create()
    material_matrix = np.zeros((4, 4, 3), dtype=np.int32)
    mask_solid = np.zeros((4, 4), dtype=bool)
    mask_solid[1:3, :] = True
    material_matrix[~mask_solid] = -1
    override_mask = np.zeros((4, 4), dtype=bool)
    override_mask[1:3, 1] = True
    preview_cache = {
        "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
        "material_matrix": material_matrix.copy(),
        "mask_solid": mask_solid.copy(),
        "color_layers": 3,
        "layer_height_mm": 0.08,
        "slot_names": ["PLA Green", "PLA Yellow", "PLA White"],
        "preview_colors": {
            0: [67, 160, 71, 255],
            1: [255, 212, 0, 255],
            2: [245, 245, 245, 255],
        },
    }
    store.put(session_id, "material_source", "material_archive")
    store.put(session_id, "selected_materials", [
        "brand/pla-green",
        "brand/pla-yellow",
        "brand/pla-white",
    ])
    store.put(session_id, "material_layer_count", 10)
    store.put(session_id, "material_layer_height_mm", 0.08)
    store.put(session_id, "preview_cache", preview_cache)
    store.put(session_id, "selected_region_mask", override_mask)
    store.put(session_id, "selected_region_id", "region-1")
    store.put(session_id, "selected_region_masks", {"region-1": override_mask})

    monkeypatch.setattr(
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "recipe": [1] * 10,
            "layer_order": "Top2Bottom",
            "color_layers": 10,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["rgb"] == [255, 212, 0]

    session_data = store.get(session_id)
    assert session_data is not None
    cache_after = session_data["preview_cache"]
    updated_matrix = cache_after["material_matrix"]
    assert updated_matrix.shape == (4, 4, 10)
    assert np.all(updated_matrix[override_mask] == 1)
    assert np.all(updated_matrix[~mask_solid][:, 3:10] == -1)
    solid_non_override = mask_solid & ~override_mask
    assert np.all(updated_matrix[solid_non_override][:, 3:10] == 2)
    assert cache_after["lut_metadata"].base_channel_idx == 2


def test_apply_recipe_override_padding_survives_uint8_material_matrix(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """uint material_matrix must be promoted before writing ``-1`` pads.

    If the cache carries ``material_matrix`` as ``uint8`` (legacy / memory
    compact path), a pad slab written as ``-1`` would wrap into ``255`` and
    reintroduce the mesh-explosion bug under a different channel id for
    every transparent-background pixel. The endpoint must promote the
    array to a signed dtype before padding so ``~mask_solid`` genuinely
    stores ``-1`` (air), while ``mask_solid`` interior cells store
    ``base_channel_idx``.

    material_matrix 是 uint8 时，pad slab 写入 -1 会被回绕成 255，把同一个
    bug 换个 id 复现；扩展前必须升位到 signed。透明背景保留 -1 空气，
    mask_solid 内部写 base_channel_idx。
    """
    client, store, _registry = _client_with_state()
    lut_path = tmp_path / "ref.msgpack"
    lut_path.write_bytes(b"package")

    session_id = store.create()
    material_matrix = np.zeros((3, 3, 2), dtype=np.uint8)
    # mask_solid covers just the center — corners are transparent.
    # mask_solid 只覆盖中心像素，四角保持透明。
    mask_solid = np.zeros((3, 3), dtype=bool)
    mask_solid[1, 1] = True
    override_mask = np.zeros((3, 3), dtype=bool)
    override_mask[1, 1] = True
    preview_cache = {
        "matched_rgb": np.zeros((3, 3, 3), dtype=np.uint8),
        "material_matrix": material_matrix.copy(),
        "mask_solid": mask_solid.copy(),
        "color_layers": 2,
        "layer_height_mm": 0.08,
    }
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "preview_cache", preview_cache)
    store.put(session_id, "selected_region_mask", override_mask)
    store.put(session_id, "selected_region_id", "region-1")
    store.put(session_id, "selected_region_masks", {"region-1": override_mask})

    metadata = LUTMetadata(
        max_color_layers=4, layer_height_mm=0.08, base_channel_idx=0
    )
    metadata.layer_order = "Top2Bottom"
    monkeypatch.setattr(
        "api.routers.converter.replace.LUTManager.load_lut_with_metadata",
        lambda _path: (np.zeros((0, 3), dtype=np.uint8), None, metadata),
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.predict_recipe_color",
        lambda metadata, recipe, layer_height_mm, color_layers, layer_order: {
            "rgb": [100, 50, 25],
            "lab": [35.0, 10.0, 20.0],
            "source": "stage_model",
            "runtime_mode_key": "0.08x4",
        },
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "recipe": [1, 1, 1, 1],
            "layer_order": "Top2Bottom",
            "color_layers": 4,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200, response.text

    session_data = store.get(session_id)
    assert session_data is not None
    updated_matrix = session_data["preview_cache"]["material_matrix"]
    assert updated_matrix.shape == (3, 3, 4)
    # dtype must now accommodate the negative sentinel.
    assert np.issubdtype(updated_matrix.dtype, np.signedinteger), (
        updated_matrix.dtype
    )
    # Transparent-background cell stores the genuine ``-1``, not wrapped
    # ``255``. Grown layers on a transparent pixel.
    # 透明背景扩展层必须是真的 -1，不能是 255 环绕值。
    assert int(updated_matrix[0, 0, 3]) == -1
    assert int(updated_matrix[0, 0, 2]) == -1


def test_generate_worker_inputs_pads_grown_layers_with_mask_solid_aware_fill(
    tmp_path: Path,
) -> None:
    """``_prepare_recipe_override_worker_inputs`` mirrors apply-side semantics.

    The generate endpoint rebuilds ``material_matrix_override`` from the
    cached material_matrix for the worker pool. Same pad contract: the
    transparent background (``~mask_solid``) stays ``-1`` (air) so S07 does
    not emit a ring-shaped White mesh, while the ``mask_solid`` interior of
    non-override pixels keeps ``base_channel_idx`` so the user's 6th layer
    does not collapse outside the override.

    generate 端为 worker 重建 material_matrix_override 时沿用 apply 的
    pad 语义：~mask_solid 扩展层保留 -1 空气，mask_solid 内部非 override
    像素保留 base_channel_idx 以避免空层。
    """
    from api.routers.converter.generate import (
        _prepare_recipe_override_worker_inputs,
    )
    from api.schemas.converter import ConvertGenerateRequest

    store = SessionStore(ttl=1800)
    session_id = store.create()

    material_matrix = np.zeros((4, 4, 3), dtype=np.int32)
    mask_solid = np.zeros((4, 4), dtype=bool)
    mask_solid[1:3, :] = True  # middle rows are solid
    material_matrix[~mask_solid] = -1

    override_mask = np.zeros((4, 4), dtype=bool)
    override_mask[2, 2] = True

    cache = {"material_matrix": material_matrix, "mask_solid": mask_solid}
    session_data = {"selected_region_masks": {"region-1": override_mask}}

    cache["lut_metadata"] = LUTMetadata(
        max_color_layers=6, layer_height_mm=0.08, base_channel_idx=0
    )
    cache["lut_metadata"].layer_order = "Top2Bottom"

    request = ConvertGenerateRequest(
        lut_name="test-lut",
        color_layers=6,
        recipe_overrides=[
            {
                "region_id": "region-1",
                "recipe": [1, 1, 1, 1, 1, 1],
                "layer_order": "Top2Bottom",
            }
        ],
    )
    recipe_overrides = [
        {
            "region_id": "region-1",
            "recipe": [1, 1, 1, 1, 1, 1],
            "layer_order": "Top2Bottom",
        }
    ]

    mm_path, _masks_path = _prepare_recipe_override_worker_inputs(
        cache=cache,
        session_data=session_data,
        recipe_overrides=recipe_overrides,
        request=request,
        sid=session_id,
        store=store,
    )
    assert mm_path is not None

    written = np.load(mm_path)
    assert written.shape == (4, 4, 6)

    # (1) Override pixel: all 6 layers = recipe (1).
    assert np.all(written[2, 2, :] == 1)

    # (2) Transparent-background pixel (row 0, col 0): kept -1 at layers 0..2
    # (from the source matrix) AND -1 at grown layers 3..5.
    # 透明背景像素：原有层 0..2 保持 -1，扩展层 3..5 也必须是 -1。
    assert np.all(written[0, 0, :] == -1)

    # (3) Solid non-override pixel inside mask_solid (row 1, col 1): original
    # layers stay at 0, grown layers become ``base_channel_idx`` (0).
    # 实体非 override 像素：原有层 0..2 保持 0，扩展层 3..5 为 base_channel_idx。
    assert np.all(written[1, 1, :3] == 0)
    assert np.all(written[1, 1, 3:] == 0)


def test_generate_worker_inputs_preserve_high_virtual_material_indices(
    tmp_path: Path,
) -> None:
    from api.routers.converter.generate import (
        _prepare_recipe_override_worker_inputs,
    )
    from api.schemas.converter import ConvertGenerateRequest

    store = SessionStore(ttl=1800)
    session_id = store.create()
    material_matrix = np.zeros((4, 4, 2), dtype=np.int8)
    override_mask = np.zeros((4, 4), dtype=bool)
    override_mask[1:3, 1:3] = True
    cache = {
        "material_matrix": material_matrix,
        "mask_solid": np.ones((4, 4), dtype=bool),
        "lut_metadata": LUTMetadata(
            max_color_layers=2,
            layer_height_mm=0.08,
            base_channel_idx=0,
        ),
    }
    cache["lut_metadata"].layer_order = "Top2Bottom"
    session_data = {"selected_region_masks": {"region-1": override_mask}}
    recipe_overrides = [
        {
            "region_id": "region-1",
            "recipe": [0, 1024],
            "layer_order": "Top2Bottom",
        }
    ]
    request = ConvertGenerateRequest(
        lut_name="test-lut",
        color_layers=2,
        recipe_overrides=recipe_overrides,
    )

    mm_path, _masks_path = _prepare_recipe_override_worker_inputs(
        cache=cache,
        session_data=session_data,
        recipe_overrides=recipe_overrides,
        request=request,
        sid=session_id,
        store=store,
    )
    assert mm_path is not None

    written = np.load(mm_path)
    assert written.dtype == np.dtype(np.int16)
    np.testing.assert_array_equal(
        written[override_mask],
        np.tile(np.array([0, 1024], dtype=np.int16), (int(override_mask.sum()), 1)),
    )


def test_generate_worker_inputs_material_archive_pad_uses_inferred_base_channel(
    tmp_path: Path,
) -> None:
    """Material-archive sessions must pad grown layers with the inferred backing channel.

    Material-archive preview never produces an ``LUTMetadata``, so the
    previous ``getattr(lut_metadata, "base_channel_idx", 0)`` fallback
    quietly defaulted to channel 0. With a user palette like
    ``[red, white]``, this filled the user's added layers with red instead
    of the white backing slot, leaving the slicer with a coloured slab in
    the deeper layers and contributing to "外观面/底板缺色" reports.

    Regression: when ``session_data["material_source"] == "material_archive"``
    and ``cache["lut_metadata"]`` is ``None``, the function must derive
    the backing channel from ``selected_materials`` /
    ``cache["slot_names"]`` via ``infer_material_archive_base_channel_idx``.

    耗材档案模式不会有 LUTMetadata，旧版回退到 channel 0 会让加层用第一种
    用户耗材（比如红色）冒充背板色。修复后必须按 selected_materials 推断
    出真实白色通道，加层填充用该通道。
    """
    from api.routers.converter.generate import (
        _prepare_recipe_override_worker_inputs,
    )
    from api.schemas.converter import ConvertGenerateRequest

    store = SessionStore(ttl=1800)
    session_id = store.create()

    # ``material_matrix`` start: 4-layer, 4x4. Solid interior pixels carry
    # channel 0 (red), and the white channel index is 1.
    # material_matrix 起始：4 层 4x4。实体内部像素用 channel 0（红），
    # 白色（背板）通道索引为 1。
    material_matrix = np.zeros((4, 4, 4), dtype=np.int32)
    mask_solid = np.zeros((4, 4), dtype=bool)
    mask_solid[1:3, :] = True
    material_matrix[~mask_solid] = -1

    override_mask = np.zeros((4, 4), dtype=bool)
    override_mask[2, 2] = True

    cache = {
        "material_matrix": material_matrix,
        "mask_solid": mask_solid,
        "lut_metadata": None,
        "slot_names": ["PLA Red", "PLA White"],
        "preview_colors": {0: [200, 30, 30, 255], 1: [245, 245, 245, 255]},
    }
    session_data = {
        "material_source": "material_archive",
        "selected_materials": ["brand/pla-red", "brand/pla-white"],
        "selected_region_masks": {"region-1": override_mask},
    }

    # Target 6 layers (user added 2). Override region recipe length 6.
    request = ConvertGenerateRequest(
        lut_name="__material_archive__",
        color_layers=6,
        recipe_overrides=[
            {
                "region_id": "region-1",
                "recipe": [0, 0, 0, 0, 0, 0],
                "layer_order": "Top2Bottom",
            }
        ],
    )
    recipe_overrides = [
        {
            "region_id": "region-1",
            "recipe": [0, 0, 0, 0, 0, 0],
            "layer_order": "Top2Bottom",
        }
    ]

    mm_path, _masks_path = _prepare_recipe_override_worker_inputs(
        cache=cache,
        session_data=session_data,
        recipe_overrides=recipe_overrides,
        request=request,
        sid=session_id,
        store=store,
    )
    assert mm_path is not None

    written = np.load(mm_path)
    assert written.shape == (4, 4, 6)

    # Solid non-override pixel: layers 0..3 keep red (channel 0), grown
    # layers 4..5 must be the inferred white channel (1) — NOT channel 0.
    # 实体非 override 像素：原层 0..3 保持红色，扩展层 4..5 必须是推断出
    # 的白色背板通道（1），而不是错误的 channel 0。
    assert np.all(written[1, 1, :4] == 0)
    assert np.all(written[1, 1, 4:] == 1), (
        "Material-archive grown layers must use the inferred white "
        f"backing channel (1), got {written[1, 1, 4:].tolist()}"
    )

    # Transparent pixel grown layers stay -1 (air).
    # 透明像素扩展层保持 -1。
    assert np.all(written[0, 0, :] == -1)


def test_s03_upgrade_material_matrix_layers_mask_solid_aware_fill() -> None:
    """``_upgrade_material_matrix_layers`` pads according to ``mask_solid``.

    Direct unit test of the raster pipeline's layer extension helper. The
    helper now takes an optional ``mask_solid``: when supplied, the pad
    slab is ``-1`` everywhere and ``mask_solid`` interior cells receive
    ``base_channel_idx`` so s06/s07 get the right "no material outside
    the silhouette / base material inside" contract.

    直接单测核心管线的层扩展 helper：传入 mask_solid 时，扩展层 ~mask_solid
    保持 -1 空气、mask_solid 内部写 base_channel_idx。
    """
    from core.pipeline.s03_color_replacement import _upgrade_material_matrix_layers

    signed = np.zeros((3, 3, 3), dtype=np.int32)
    mask_solid = np.zeros((3, 3), dtype=bool)
    mask_solid[1, 1] = True  # single solid pixel in the middle
    signed[~mask_solid] = -1

    grown = _upgrade_material_matrix_layers(
        signed,
        5,
        base_channel_idx=0,
        layer_order="Top2Bottom",
        mask_solid=mask_solid,
    )
    assert grown.shape == (3, 3, 5)
    # Original layers preserved.
    assert np.all(grown[..., :3] == signed)
    # Grown layers: transparent stays -1, solid interior = base_channel_idx.
    transparent_grown = grown[~mask_solid][:, 3:]
    assert np.all(transparent_grown == -1), transparent_grown.tolist()
    solid_grown = grown[mask_solid][:, 3:]
    assert np.all(solid_grown == 0), solid_grown.tolist()

    # Bottom2Top: extension prepends in front of the original layers.
    grown_b2t = _upgrade_material_matrix_layers(
        signed,
        5,
        base_channel_idx=0,
        layer_order="Bottom2Top",
        mask_solid=mask_solid,
    )
    assert grown_b2t.shape == (3, 3, 5)
    transparent_prepend = grown_b2t[~mask_solid][:, :2]
    assert np.all(transparent_prepend == -1), transparent_prepend.tolist()
    solid_prepend = grown_b2t[mask_solid][:, :2]
    assert np.all(solid_prepend == 0), solid_prepend.tolist()

    # uint8 input must be promoted to a signed dtype so -1 does not wrap.
    unsigned = np.zeros((3, 3, 3), dtype=np.uint8)
    grown_u = _upgrade_material_matrix_layers(
        unsigned,
        5,
        base_channel_idx=0,
        layer_order="Top2Bottom",
        mask_solid=mask_solid,
    )
    assert np.issubdtype(grown_u.dtype, np.signedinteger), grown_u.dtype
    # Transparent-background cell at a grown layer: genuine -1, not 255.
    # 透明背景的扩展层：必须是真的 -1，不能是 255。
    assert int(grown_u[0, 0, 3]) == -1
    assert int(grown_u[0, 0, 4]) == -1
    # Solid cell at a grown layer: base_channel_idx.
    assert int(grown_u[1, 1, 3]) == 0

    # Legacy callers without ``mask_solid`` get the old base-only fill to
    # keep signature compatibility.
    # 旧调用方不传 mask_solid 时沿用整片 base_channel_idx 行为。
    grown_legacy = _upgrade_material_matrix_layers(
        np.zeros((2, 2, 2), dtype=np.int32),
        4,
        base_channel_idx=7,
        layer_order="Top2Bottom",
    )
    assert np.all(grown_legacy[..., 2:] == 7)


def test_apply_recipe_override_preserves_native_palette_for_layer_images(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Native palette must survive ``apply_recipe_override`` virtual extension.

    Standard color modes (CMYW / RYBW / BW) leave
    ``cache["preview_colors"]`` and ``cache["slot_names"]`` absent —
    ``p04_cache_building`` only populates those keys for merged LUTs and
    downstream readers fall back to ``cache["color_conf"]["preview"]`` /
    ``["slots"]``. The old ``_extend_cache_palette_with_virtuals`` created
    fresh empty dicts and wrote ONLY the virtual materials into them, so
    after apply the ``/layer-images`` endpoint (which reads
    ``preview_colors`` with priority) saw an incomplete virtuals-only
    mapping and rendered every native layer as the grey background
    (``220``). Users perceived this as "分层预览只显示改过配方的那几层，
    其它全是灰"。

    This regression locks the fix: seed ``preview_colors`` / ``slot_names``
    from ``color_conf.preview`` / ``color_conf.slots`` when missing so the
    full native+virtual palette survives apply and ``get_layer_images``
    paints native materials with their real colors at every layer.

    标准色模式（CMYW / RYBW / BW）下 cache 没有 preview_colors / slot_names，
    只有 Merged LUT 会预置。原本 _extend_cache_palette_with_virtuals 新建
    空字典只塞虚拟耗材，导致 /layer-images 从完整的 color_conf 兜底切换到
    残缺的 preview_colors，native 层全部渲染成灰色（"分层预览只显示改过
    配方的那几层"现象）。本测试锁定修复：preview_colors / slot_names 缺失
    时用 color_conf.preview / slots 做种子，apply 后完整的 native+虚拟
    调色板全部保留，get_layer_images 能正确给 native 层上色。
    """
    from api.routers.converter.preview import get_layer_images

    client, store, registry = _client_with_state()
    lut_path = tmp_path / "ref.msgpack"
    lut_path.write_bytes(b"package")

    session_id = store.create()
    # Single solid pixel at (1, 1) — native material 1 (red). Everything else
    # is transparent background so /layer-images has one real native pixel
    # to render and a background to diff against.
    matched_rgb = np.zeros((3, 3, 3), dtype=np.uint8)
    matched_rgb[1, 1] = [255, 0, 0]
    mask_solid = np.zeros((3, 3), dtype=bool)
    mask_solid[1, 1] = True
    material_matrix = np.full((3, 3, 3), -1, dtype=np.int32)
    material_matrix[1, 1, :] = 1  # native channel 1 = Red at every layer

    # Override on a second pixel (1, 2) with a virtual material.
    override_mask = np.zeros((3, 3), dtype=bool)
    override_mask[1, 2] = True
    # Extend mask_solid so the override pixel is also solid — otherwise apply
    # rejects the region for being entirely outside the silhouette.
    mask_solid[1, 2] = True

    # Cache mimicking CMYW standard mode: color_conf holds the native palette,
    # preview_colors / slot_names absent (populated only for merged LUTs).
    # cache 模拟 CMYW 标准模式：color_conf 里是 native 调色板，
    # preview_colors / slot_names 不存在（只有 Merged LUT 才会预置）。
    preview_cache = {
        "matched_rgb": matched_rgb.copy(),
        "material_matrix": material_matrix.copy(),
        "mask_solid": mask_solid.copy(),
        "color_layers": 3,
        "layer_height_mm": 0.08,
        "color_conf": {
            "preview": {
                0: [245, 245, 245, 255],  # White
                1: [255, 0, 0, 255],      # Red (native channel 1)
                2: [230, 0, 126, 255],    # Magenta
                3: [255, 212, 0, 255],    # Yellow
            },
            "slots": ["White", "Red", "Magenta", "Yellow"],
        },
    }
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "preview_cache", preview_cache)
    store.put(session_id, "selected_region_mask", override_mask)
    store.put(session_id, "selected_region_id", "region-1")
    store.put(session_id, "selected_region_masks", {"region-1": override_mask})

    palette_entry_cls = type(
        "_PaletteEntry", (), {"__init__": lambda self, color: setattr(self, "color", color)}
    )
    metadata = LUTMetadata(
        max_color_layers=3, layer_height_mm=0.08, base_channel_idx=0
    )
    metadata.palette = [palette_entry_cls(name) for name in ["White", "Red", "Magenta", "Yellow"]]
    metadata.layer_order = "Top2Bottom"
    monkeypatch.setattr(
        "api.routers.converter.replace.LUTManager.load_lut_with_metadata",
        lambda _path: (np.zeros((0, 3), dtype=np.uint8), None, metadata),
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    # Apply a recipe whose topmost layer is a virtual "Black" material
    # (index 4 = LUT.N + 0). Keep color_layers = 3 so we only test the
    # palette-seeding fix, not the layer-growth fix.
    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "recipe": [4, 4, 4],
            "layer_order": "Top2Bottom",
            "color_layers": 3,
            "layer_height_mm": 0.08,
            "virtual_materials": [{"name": "Black", "hex": "#111111"}],
        },
    )
    assert response.status_code == 200, response.text

    session_data = store.get(session_id)
    assert session_data is not None
    updated_cache = session_data["preview_cache"]

    # FIX INVARIANT 1: cache["preview_colors"] now carries BOTH the native
    # palette (seeded from color_conf.preview) AND the virtual material.
    # Pre-fix this dict held only {4: black} and the natives were lost.
    assert updated_cache["preview_colors"][0] == [245, 245, 245, 255]
    assert updated_cache["preview_colors"][1] == [255, 0, 0, 255]
    assert updated_cache["preview_colors"][2] == [230, 0, 126, 255]
    assert updated_cache["preview_colors"][3] == [255, 212, 0, 255]
    assert updated_cache["preview_colors"][4] == [17, 17, 17, 255]

    # FIX INVARIANT 2: cache["slot_names"] starts with the native slots and
    # appends the virtual slot. Pre-fix the list was padded with
    # ``"Slot_0"..."Slot_3"`` placeholders that lost the real names.
    assert updated_cache["slot_names"] == [
        "White",
        "Red",
        "Magenta",
        "Yellow",
        "Black",
    ]

    # FIX INVARIANT 3: /layer-images renders native material 1 (red) at the
    # native pixel for EVERY layer, not the background grey. Pre-fix this
    # pixel came back as (220, 220, 220) because preview_colors had no
    # entry for mat_id=1. This is the end-user symptom being regressed.
    layers = get_layer_images(
        session_id=session_id, store=store, registry=registry
    )
    assert len(layers["layers"]) == 3
    for layer_idx, layer in enumerate(layers["layers"]):
        file_id = layer["url"].rsplit("/", 1)[-1]
        resolved = registry.resolve(file_id)
        assert resolved is not None
        path, _filename = resolved
        with Image.open(path) as img:
            arr = np.asarray(img.convert("RGB"))
        # Native red pixel at (1, 1) stays red at every layer.
        np.testing.assert_array_equal(
            arr[1, 1],
            np.asarray([255, 0, 0], dtype=np.uint8),
            err_msg=f"layer {layer_idx} lost the native red pixel",
        )
        # Override pixel at (1, 2) painted with the virtual Black.
        np.testing.assert_array_equal(
            arr[1, 2],
            np.asarray([17, 17, 17], dtype=np.uint8),
            err_msg=f"layer {layer_idx} lost the virtual black pixel",
        )
        # Transparent-background pixel at (0, 0) stays the lightest grey
        # (non-solid fill, 240) — confirms mask_solid still masks air.
        np.testing.assert_array_equal(
            arr[0, 0],
            np.asarray([240, 240, 240], dtype=np.uint8),
            err_msg=f"layer {layer_idx} lost the transparent marker",
        )


def _seed_material_archive_session(
    store: SessionStore,
    *,
    preview_colors: dict[int, list[int]] | None = None,
    slot_names: list[str] | None = None,
    layer_count: int = 5,
) -> tuple[str, np.ndarray]:
    """Seed a material-archive-backed session with a populated preview cache.

    Mirrors what ``preview.py`` writes into the store after a material-archive
    ``/preview`` call: ``lut_path`` is the ``"__material_archive__"`` sentinel
    (no file on disk), ``selected_materials`` / ``material_layer_count`` /
    ``material_layer_height_mm`` drive the recipe-endpoint metadata stub, and
    the preview cache carries ``preview_colors`` / ``slot_names`` built from
    the material archive instead of a LUT.

    Returns the session id plus the region mask used to seed ``selected_region_masks``.
    """
    palette = preview_colors or {
        0: [255, 0, 0, 255],
        1: [0, 255, 0, 255],
        2: [0, 0, 255, 255],
        3: [255, 255, 0, 255],
        4: [0, 255, 255, 255],
    }
    slots = slot_names or ["PLA Red", "PLA Green", "PLA Blue", "PLA Yellow", "PLA Cyan"]
    session_id = store.create()
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    material_matrix = np.zeros((4, 4, layer_count), dtype=np.int32)
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    preview_cache = {
        "matched_rgb": matched_rgb.copy(),
        "quantized_image": matched_rgb.copy(),
        "material_matrix": material_matrix.copy(),
        "mask_solid": np.ones((4, 4), dtype=bool),
        "color_layers": layer_count,
        "layer_height_mm": 0.08,
        "preview_colors": dict(palette),
        "slot_names": list(slots),
    }
    store.put(session_id, "lut_path", "__material_archive__")
    store.put(session_id, "material_source", "material_archive")
    store.put(session_id, "selected_materials", [f"material-{i}" for i in range(len(slots))])
    store.put(session_id, "material_layer_count", layer_count)
    store.put(session_id, "material_layer_height_mm", 0.08)
    store.put(session_id, "preview_cache", preview_cache)
    store.put(session_id, "selected_region_mask", mask)
    store.put(session_id, "selected_region_id", "region-1")
    store.put(session_id, "selected_region_masks", {"region-1": mask})
    return session_id, mask


def _rounding_probe_material() -> MaterialParams:
    return MaterialParams(
        name="Rounding probe",
        directory_name="rounding-probe",
        E=np.asarray((0.2, 0.4, 0.6), dtype=np.float64),
        k=np.asarray((1.3, 1.1, 0.9), dtype=np.float64),
        C0_white=np.asarray((0.3, 0.4, 0.5), dtype=np.float64),
        estimated_rgb=np.asarray((120, 140, 160), dtype=np.uint8),
    )


def test_predict_material_archive_uses_canonical_rounded_rgb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store, _registry = _client_with_state()
    session_id, _mask = _seed_material_archive_session(
        store,
        preview_colors={0: [120, 140, 160, 255]},
        slot_names=["Rounding probe"],
    )
    material = _rounding_probe_material()
    monkeypatch.setattr(
        "api.routers.converter.replace.load_multiple_materials",
        lambda _paths: [material],
    )

    response = client.post(
        "/api/convert/predict-recipe",
        json={
            "session_id": session_id,
            "recipe": [0, 0, 0, 0, 0],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["rgb"] == [214, 229, 241]
    assert response.json()["source"] == "material_archive_forward_model"


def test_apply_material_archive_rounds_override_and_padded_pixels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store, _registry = _client_with_state()
    session_id, region_mask = _seed_material_archive_session(
        store,
        preview_colors={0: [120, 140, 160, 255]},
        slot_names=["Rounding probe"],
        layer_count=3,
    )
    store.put(session_id, "material_layer_count", 5)
    material = _rounding_probe_material()
    monkeypatch.setattr(
        "api.routers.converter.replace.load_multiple_materials",
        lambda _paths: [material],
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "recipe": [0, 0, 0, 0, 0],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
    )

    expected_rgb = predict_material_recipe_srgb(
        np.zeros(5, dtype=np.int32),
        [material],
        layer_height_mm=0.08,
    )
    assert expected_rgb.tolist() == [214, 229, 241]
    assert response.status_code == 200, response.text
    assert response.json()["rgb"] == expected_rgb.tolist()

    session_data = store.get(session_id)
    assert session_data is not None
    updated_rgb = session_data["preview_cache"]["matched_rgb"]
    non_override_mask = ~region_mask
    assert np.all(updated_rgb[region_mask] == expected_rgb)
    assert np.all(updated_rgb[non_override_mask] == expected_rgb)


def test_predict_recipe_endpoint_supports_material_archive_session(
    tmp_path: Path,
) -> None:
    """``/predict-recipe`` must accept material-archive sessions.

    Material-archive sessions have no LUT file on disk (``lut_path`` is the
    ``"__material_archive__"`` sentinel) so the old path unconditionally
    raised 409 "LUT/source file missing. Preview again first." even though
    the session was fully valid. This regression locks the fix: the endpoint
    now reads the topmost layer's preview RGB from ``cache["preview_colors"]``
    and returns ``source == "material_archive_preview"`` instead of
    hard-failing.

    耗材档案会话没有 LUT 文件，旧逻辑直接 409 "LUT/source file missing"。
    本测试锁定修复：predict 现在从 ``cache["preview_colors"]`` 读最顶层
    通道的预览色，返回 ``source == "material_archive_preview"``。
    """
    client, store, _registry = _client_with_state()
    session_id, _mask = _seed_material_archive_session(store)

    response = client.post(
        "/api/convert/predict-recipe",
        json={
            "session_id": session_id,
            # Topmost layer (Top2Bottom -> recipe[0]) is channel 2 (blue).
            "recipe": [2, 1, 0, 4, 3],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    # Preview colour comes straight from cache["preview_colors"][2] = blue.
    assert body["rgb"] == [0, 0, 255], body
    assert body["source"] == "material_archive_preview"
    assert body["runtime_mode_key"] is None


def test_apply_recipe_override_endpoint_supports_material_archive_session(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """``/apply-recipe-override`` must accept material-archive sessions.

    Regression for the user-reported 409 on POST /api/convert/apply-recipe-override
    in material-archive mode. Before the fix the endpoint hard-required a
    real ``lut_path`` file and called ``LUTManager.load_lut_with_metadata``,
    both of which fail on the ``"__material_archive__"`` sentinel. After the
    fix a stub :class:`LUTMetadata` is built from ``selected_materials`` /
    ``material_layer_count`` and the display colour is derived from
    ``cache["preview_colors"]`` — the ``material_matrix`` update, override
    persistence, and virtual-material cache extension all proceed normally.

    耗材档案模式下 ``lut_path`` 是 sentinel 字符串，旧 apply 端点
    ``os.path.exists(lut_path)`` + ``LUTManager.load_lut_with_metadata``
    都会失败，直接 409。修复后从 session 构造 stub metadata，兜底色取自
    ``cache["preview_colors"]``，material_matrix / recipe_overrides /
    虚拟耗材扩展都正常进行。
    """
    client, store, _registry = _client_with_state()
    session_id, mask = _seed_material_archive_session(store)
    # Short-circuit GLB regeneration — the material-archive mesh pipeline is
    # out of scope for this regression and requires a real solver state.
    monkeypatch.setattr(
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    # Recipe targets native channel 1 (green = [0, 255, 0]) at the topmost
    # layer; material archive has 5 native materials so no virtuals needed.
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

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    # Preview RGB comes from cache["preview_colors"][1] = green.
    assert body["rgb"] == [0, 255, 0], body
    assert body["source"] == "material_archive_preview"
    assert body["override_count"] == 1

    session_data = store.get(session_id)
    assert session_data is not None
    updated_cache = session_data["preview_cache"]
    # material_matrix region filled with the native channel 1.
    assert np.all(updated_cache["material_matrix"][mask] == 1)
    # matched_rgb region painted with the preview green.
    assert np.all(
        updated_cache["matched_rgb"][mask]
        == np.asarray([0, 255, 0], dtype=np.uint8)
    )
    # Session-persisted override survives for /generate handoff.
    assert session_data["recipe_overrides"] == [
        {
            "region_id": "region-1",
            "recipe": [1, 1, 1, 1, 1],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        }
    ]


def test_dynamic_material_override_pads_backing_and_persists_actual_recipe(
    monkeypatch,
) -> None:
    client, store, _registry = _client_with_state()
    session_id, mask = _seed_material_archive_session(store, layer_count=7)
    store.put(session_id, "material_dynamic_layer_count_enabled", True)
    store.put(session_id, "material_min_layer_count", 5)
    store.put(session_id, "material_max_layer_count", 7)
    store.put(session_id, "material_delta_e00_tolerance", 0.5)
    store.put(session_id, "material_backing_material_index", 4)

    seen_bottom_to_top: list[list[int]] = []

    def fake_prediction(
        recipe,
        materials,
        layer_height_mm,
        substrate="white",
    ):
        seen_bottom_to_top.append([int(value) for value in recipe])
        return np.asarray([137, 188, 225], dtype=np.uint8)

    monkeypatch.setattr(
        "api.routers.converter.replace.load_multiple_materials",
        lambda _paths: [object()] * 5,
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.predict_material_recipe_srgb",
        fake_prediction,
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "recipe": [2, 1, 0, 1, 1],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200, response.text
    assert seen_bottom_to_top == [[4, 4, 1, 1, 0, 1, 2]]
    session_data = store.get(session_id)
    updated_cache = session_data["preview_cache"]
    assert updated_cache["material_matrix"].shape[2] == 7
    assert np.all(
        updated_cache["material_matrix"][mask]
        == np.asarray([2, 1, 0, 1, 1, 4, 4], dtype=np.int32)
    )
    assert session_data["recipe_overrides"] == [
        {
            "region_id": "region-1",
            "recipe": [2, 1, 0, 1, 1],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
            "actual_recipe_top_to_bottom": [2, 1, 0, 1, 1],
            "print_recipe_top_to_bottom": [2, 1, 0, 1, 1, 4, 4],
            "actual_layer_count": 5,
            "padding_layer_count": 2,
        }
    ]


def test_dynamic_manual_override_reweights_curve_for_automatic_pixels_only(
    monkeypatch,
) -> None:
    """A manual target equal to an auto target must not dilute the auto curve."""

    client, store, _registry = _client_with_state()
    session_id, manual_mask = _seed_material_archive_session(store, layer_count=7)
    session_data = store.get(session_id)
    assert session_data is not None
    session_data.update(
        {
            "material_dynamic_layer_count_enabled": True,
            "material_min_layer_count": 5,
            "material_max_layer_count": 7,
            "material_delta_e00_tolerance": 0.5,
            "material_backing_material_index": 4,
        }
    )

    target_a = [10, 20, 30]
    target_b = [40, 50, 60]

    def dynamic_entry(target: list[int], delta: float) -> dict:
        actual = [0, 1, 2, 3, 0]
        printable = [*actual, 4, 4]
        return {
            "target_srgb": target,
            "matched_srgb": target,
            "actual_layer_count": 5,
            "padding_layer_count": 2,
            "actual_recipe_top_to_bottom": actual,
            "print_recipe_top_to_bottom": printable,
            "selected_delta_e00": delta,
            "best_range_delta_e00": delta,
            "fixed_max_delta_e00": delta,
            "delta_e00_sacrifice": 0.0,
            "layer_cap_options": [
                {
                    "max_effective_layer_count": cap,
                    "actual_layer_count": 5,
                    "matched_srgb": target,
                    "actual_recipe_top_to_bottom": actual,
                    "print_recipe_top_to_bottom": printable,
                    "delta_e00": delta,
                }
                for cap in (5, 6, 7)
            ],
        }

    cache = dict(session_data["preview_cache"])
    target_map = np.full((4, 4, 3), target_b, dtype=np.uint8)
    target_map[0, :, :] = target_a
    cache.update(
        {
            "matched_rgb": target_map.copy(),
            "quantized_image": target_map.copy(),
            "material_matrix": np.zeros((4, 4, 7), dtype=np.int32),
            "mask_solid": np.ones((4, 4), dtype=bool),
            "material_dynamic_layer_info": {
                "enabled": True,
                "min_layer_count": 5,
                "max_layer_count": 7,
                "delta_e00_tolerance": 0.5,
                "colors": [dynamic_entry(target_a, 1.0), dynamic_entry(target_b, 3.0)],
                "benefit_curve": [],
                "benefit_curve_scope": "all_printable_pixels",
                "benefit_curve_pixel_count": 16,
            },
        }
    )
    store.put(session_id, "preview_cache", cache)

    monkeypatch.setattr(
        "api.routers.converter.replace.load_multiple_materials",
        lambda _paths: [object()] * 5,
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.predict_material_recipe_srgb",
        lambda *_args, **_kwargs: np.asarray(target_b, dtype=np.uint8),
    )
    monkeypatch.setattr(
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "recipe": [2, 1, 0, 1, 1],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["material_layer_benefit_scope"] == "automatic_pixels"
    assert payload["material_layer_benefit_pixel_count"] == 12
    # The four manual B pixels would make the all-pixel mean 2.5. The curve
    # must only weight automatic pixels: 4 A at ΔE00=1 and 8 B at ΔE00=3.
    assert payload["material_layer_benefit_curve"][0][
        "weighted_mean_delta_e00"
    ] == pytest.approx(28.0 / 12.0)

    updated_cache = store.get(session_id)["preview_cache"]
    assert np.all(updated_cache["quantized_image"][manual_mask] == target_b)
    assert updated_cache["material_dynamic_layer_info"][
        "benefit_curve_pixel_count"
    ] == 12


def test_apply_recipe_override_material_archive_extends_palette_with_virtuals(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Virtual materials must still extend the palette in material-archive mode.

    The user's reported use case was "耗材档案模式下自定义配方" with a
    user-declared non-native primary (e.g. Black when their archive only has
    PLA Red/Green/Blue/Yellow/Cyan). The fix must thread ``virtual_materials``
    through the stub-metadata path so:

    1. The virtual index ``lut_palette_length + 0`` validates (no 422).
    2. ``cache["preview_colors"]`` gains the virtual entry after apply.
    3. The override region paints in the virtual material's user-intent hex
       (``match_mode == "virtual_material"``), not the material_archive cache
       preview fallback.
    4. ``recipe_overrides`` persists ``virtual_materials`` so ``/generate``
       can rebuild the extended palette in the worker.

    耗材档案模式的自定义配方也必须支持声明 LUT 不存在的虚拟耗材：虚拟
    索引验证通过、preview_colors 扩展、override 区域用虚拟 hex 上色、
    recipe_overrides 带上 virtual_materials 供 /generate 重建调色板。
    """
    client, store, _registry = _client_with_state()
    session_id, mask = _seed_material_archive_session(store)
    monkeypatch.setattr(
        "api.routers.converter.replace.schedule_glb_build",
        lambda *_args, **_kwargs: None,
    )

    # Virtual Black at index 5 = LUT.N (5) + 0 (first virtual offset).
    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "recipe": [5, 5, 5, 5, 5],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
            "virtual_materials": [{"name": "Black", "hex": "#111111"}],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # Virtual-material top layer: preview comes from the user's hex, not the
    # material-archive cache fallback.
    assert body["rgb"] == [17, 17, 17]
    assert body["source"] == "virtual_material"

    session_data = store.get(session_id)
    assert session_data is not None
    updated_cache = session_data["preview_cache"]
    # Virtual entry appended past LUT.N (= 5 selected materials).
    assert updated_cache["preview_colors"][5] == [17, 17, 17, 255]
    assert updated_cache["slot_names"][5] == "Black"
    # Native palette preserved (seeded from color_conf or preview_colors).
    assert updated_cache["preview_colors"][0] == [255, 0, 0, 255]
    assert updated_cache["preview_colors"][4] == [0, 255, 255, 255]
    # recipe_overrides carries virtual_materials for /generate to rebuild.
    assert session_data["recipe_overrides"] == [
        {
            "region_id": "region-1",
            "recipe": [5, 5, 5, 5, 5],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
            "virtual_materials": [{"name": "Black", "hex": "#111111"}],
        }
    ]


def test_region_recipe_endpoint_returns_current_stack_top2bottom() -> None:
    """``/region-recipe`` returns the region's current material stack.

    Regression for "自定义配方对话框默认永远是全白": the dialog pre-populates
    its per-layer dropdowns from this endpoint, so losing or reordering the
    sampled stack silently overwrites the user's real recipe on "Apply".
    ``material_matrix`` is stored Top2Bottom everywhere in the pipeline
    (layer 0 = viewing surface), so a Top2Bottom request must pass the
    stack through verbatim without any flip. 本回归锁定 Top2Bottom 请求时
    返回 material_matrix 原本的 Top2Bottom 堆叠，不做任何反转。
    """
    client, store, _registry = _client_with_state()
    session_id = store.create()
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    # Distinct per-layer stack so a silent reversal would fail loudly.
    material_matrix = np.zeros((4, 4, 5), dtype=np.int32)
    material_matrix[:, :] = [3, 2, 1, 0, 4]  # Top2Bottom: layer 0 = 3
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    preview_cache = {
        "matched_rgb": matched_rgb,
        "material_matrix": material_matrix,
        "mask_solid": np.ones((4, 4), dtype=bool),
        "color_layers": 5,
        "layer_height_mm": 0.08,
    }
    store.put(session_id, "preview_cache", preview_cache)
    store.put(session_id, "selected_region_masks", {"region-1": mask})
    store.put(session_id, "selected_region_id", "region-1")
    store.put(session_id, "selected_region_mask", mask)

    response = client.post(
        "/api/convert/region-recipe",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "layer_order": "Top2Bottom",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert len(body["recipes"]) == 1
    entry = body["recipes"][0]
    assert entry["region_id"] == "region-1"
    assert entry["recipe"] == [3, 2, 1, 0, 4]
    assert entry["color_layers"] == 5
    assert entry["layer_order"] == "Top2Bottom"


def test_dynamic_region_recipe_reads_saved_actual_depth_without_trimming_backing() -> None:
    client, store, _registry = _client_with_state()
    session_id = store.create()
    actual = [2, 1, 0, 1, 1]
    print_recipe = [2, 1, 0, 1, 1, 1, 1]
    material_matrix = np.zeros((2, 2, 7), dtype=np.int32)
    material_matrix[:, :] = print_recipe
    mask = np.ones((2, 2), dtype=bool)
    store.put(
        session_id,
        "preview_cache",
        {
            "material_matrix": material_matrix,
            "mask_solid": mask,
            "color_layers": 7,
            "layer_height_mm": 0.08,
            "material_dynamic_layer_info": {"colors": []},
        },
    )
    store.put(session_id, "material_dynamic_layer_count_enabled", True)
    store.put(session_id, "material_min_layer_count", 5)
    store.put(session_id, "material_max_layer_count", 7)
    store.put(session_id, "selected_materials", ["mat-a", "mat-b", "mat-c"])
    store.put(session_id, "material_backing_material_index", 1)
    store.put(session_id, "selected_region_masks", {"region-1": mask})
    store.put(
        session_id,
        "recipe_overrides",
        [
            {
                "region_id": "region-1",
                "recipe": actual,
                "layer_order": "Top2Bottom",
                "color_layers": 5,
                "actual_recipe_top_to_bottom": actual,
                "print_recipe_top_to_bottom": print_recipe,
                "actual_layer_count": 5,
                "padding_layer_count": 2,
            }
        ],
    )

    response = client.post(
        "/api/convert/region-recipe",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "layer_order": "Top2Bottom",
        },
    )

    assert response.status_code == 200, response.text
    entry = response.json()["recipes"][0]
    assert entry["recipe"] == actual
    assert entry["color_layers"] == 5


def test_region_recipe_artifact_cache_avoids_common_full_hydrate(tmp_path: Path) -> None:
    client, store, _registry = _client_with_state()
    session_id = store.create()
    material_matrix = np.zeros((4, 4, 5), dtype=np.int32)
    material_matrix[:, :] = [3, 2, 1, 0, 4]
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    cache_ref = externalize_preview_cache(
        session_id,
        store,
        {
            "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
            "material_matrix": material_matrix,
            "mask_solid": np.ones((4, 4), dtype=bool),
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
        root_dir=tmp_path,
    )
    store.put(session_id, "preview_cache", cache_ref)
    store.put(session_id, "selected_region_masks", {"region-1": mask})

    with patch(
        "api.routers.converter.common.hydrate_preview_cache",
        side_effect=AssertionError("region-recipe must not fully hydrate artifact cache"),
    ):
        response = client.post(
            "/api/convert/region-recipe",
            json={
                "session_id": session_id,
                "region_ids": ["region-1"],
                "layer_order": "Top2Bottom",
            },
        )

    assert response.status_code == 200, response.text
    entry = response.json()["recipes"][0]
    assert entry["recipe"] == [3, 2, 1, 0, 4]
    assert entry["layer_height_mm"] == 0.08


def test_region_recipe_endpoint_bottom2top_reverses_stack() -> None:
    """Bottom2Top request reverses the Top2Bottom-stored stack.

    The frontend passes ``layerOrder`` through from the LUT metadata; for
    Bottom2Top LUTs the dialog expects the recipe in Bottom2Top so its
    dropdowns align with the layer index the user sees. 后端 material_matrix
    恒为 Top2Bottom 存储，Bottom2Top 请求时需要反序，让前端拿到的配方顺
    序与下拉框从下到上的层号保持一致。
    """
    client, store, _registry = _client_with_state()
    session_id = store.create()
    material_matrix = np.zeros((2, 2, 4), dtype=np.int32)
    material_matrix[:, :] = [1, 2, 3, 4]  # Top2Bottom
    mask = np.ones((2, 2), dtype=bool)
    store.put(session_id, "preview_cache", {
        "matched_rgb": np.zeros((2, 2, 3), dtype=np.uint8),
        "material_matrix": material_matrix,
        "mask_solid": mask,
        "color_layers": 4,
        "layer_height_mm": 0.08,
    })
    store.put(session_id, "selected_region_masks", {"r1": mask})

    response = client.post(
        "/api/convert/region-recipe",
        json={
            "session_id": session_id,
            "region_ids": ["r1"],
            "layer_order": "Bottom2Top",
        },
    )
    assert response.status_code == 200, response.text
    entry = response.json()["recipes"][0]
    assert entry["recipe"] == [4, 3, 2, 1]
    assert entry["layer_order"] == "Bottom2Top"


def test_region_recipe_endpoint_strips_air_sentinels() -> None:
    """``-1`` air sentinels are stripped from the sampled recipe.

    Layers grown past the original depth mark ``mask_solid`` interior with
    ``base_channel_idx`` and the exterior with ``-1``. If the sampled pixel
    happens to sit outside ``mask_solid`` in the grown layer band we must
    not leak the sentinel into the dialog (it would break dropdown indexing
    and the downstream payload validation). 空气哨兵（-1）必须从返回的
    recipe 中剥离，避免泄漏到前端下拉索引里。
    """
    client, store, _registry = _client_with_state()
    session_id = store.create()
    material_matrix = np.zeros((2, 2, 4), dtype=np.int32)
    material_matrix[:, :] = [2, 1, -1, -1]  # only top two layers are solid
    mask = np.ones((2, 2), dtype=bool)
    store.put(session_id, "preview_cache", {
        "matched_rgb": np.zeros((2, 2, 3), dtype=np.uint8),
        "material_matrix": material_matrix,
        "mask_solid": mask,
        "color_layers": 4,
        "layer_height_mm": 0.08,
    })
    store.put(session_id, "selected_region_masks", {"r1": mask})

    response = client.post(
        "/api/convert/region-recipe",
        json={"session_id": session_id, "region_ids": ["r1"]},
    )
    assert response.status_code == 200, response.text
    entry = response.json()["recipes"][0]
    # Only the two solid layers survive; color_layers narrows to match.
    assert entry["recipe"] == [2, 1]
    assert entry["color_layers"] == 2


def test_region_recipe_endpoint_supports_material_archive_session() -> None:
    """Material-archive sessions must also work — no LUT file required.

    Mirrors the apply-side material-archive regression: the endpoint only
    reads ``cache["material_matrix"]`` + region masks, so it must succeed
    whether the session is LUT-backed or material-archive-backed. Pre-fix
    apply / predict 409'd in material-archive mode; region-recipe shares
    the same session shape so lock in the happy path here.
    耗材档案会话同样要能命中：端点只读 material_matrix + region mask，
    不依赖 LUT 文件；锁定耗材档案模式的 happy path。
    """
    client, store, _registry = _client_with_state()
    session_id, _mask = _seed_material_archive_session(store)
    # Seed a distinct stack so the test catches any silent default-fallback.
    # 写入一个特征明显的堆叠，防止默认兜底静默通过。
    session_data = store.get(session_id)
    assert session_data is not None
    session_data["preview_cache"]["material_matrix"][1:3, 1:3] = [4, 3, 2, 1, 0]
    store.put(session_id, "preview_cache", session_data["preview_cache"])

    response = client.post(
        "/api/convert/region-recipe",
        json={"session_id": session_id, "region_ids": ["region-1"]},
    )
    assert response.status_code == 200, response.text
    entry = response.json()["recipes"][0]
    assert entry["recipe"] == [4, 3, 2, 1, 0]
    assert entry["layer_order"] == "Top2Bottom"


def test_region_recipe_endpoint_missing_material_matrix_returns_409() -> None:
    """Preview cache without material_matrix must 409 with a clear hint."""
    client, store, _registry = _client_with_state()
    session_id = store.create()
    store.put(session_id, "preview_cache", {"matched_rgb": np.zeros((1, 1, 3), dtype=np.uint8)})
    store.put(session_id, "selected_region_masks", {"r1": np.ones((1, 1), dtype=bool)})

    response = client.post(
        "/api/convert/region-recipe",
        json={"session_id": session_id, "region_ids": ["r1"]},
    )
    assert response.status_code == 409
    assert "material_matrix" in response.json()["detail"]


def test_region_recipe_endpoint_no_regions_returns_409() -> None:
    """Empty ``region_ids`` (and no fallback region) must 409 with a hint.

    Matches the apply endpoint's "No selected regions available" contract
    so the Custom Recipe dialog can treat both endpoints identically.
    """
    client, store, _registry = _client_with_state()
    session_id = store.create()
    store.put(session_id, "preview_cache", {
        "matched_rgb": np.zeros((1, 1, 3), dtype=np.uint8),
        "material_matrix": np.zeros((1, 1, 1), dtype=np.int32),
    })

    response = client.post(
        "/api/convert/region-recipe",
        json={"session_id": session_id, "region_ids": []},
    )
    assert response.status_code == 409
    assert "regions" in response.json()["detail"].lower()


def test_apply_recipe_override_material_archive_missing_selected_materials_returns_409() -> None:
    """Missing ``selected_materials`` on a material-archive session is 409.

    Guards against regression where the material-archive branch silently
    builds an empty-palette stub and then 422s on recipe index validation
    instead of surfacing the real "preview again first" hint.
    """
    client, store, _registry = _client_with_state()
    session_id, _mask = _seed_material_archive_session(store)
    # Clear selected_materials to simulate a stale / mid-migration session.
    store.put(session_id, "selected_materials", [])

    response = client.post(
        "/api/convert/apply-recipe-override",
        json={
            "session_id": session_id,
            "region_ids": ["region-1"],
            "recipe": [0, 0, 0, 0, 0],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "layer_height_mm": 0.08,
        },
    )
    assert response.status_code == 409, response.text
    assert "selected_materials" in response.json()["detail"]
