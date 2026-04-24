from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.routers.converter.preview import get_layer_images
from api.session_store import SessionStore

_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()


def setup_module(module) -> None:
    app.dependency_overrides[get_session_store] = lambda: _test_store
    app.dependency_overrides[get_file_registry] = lambda: _test_registry


def teardown_module(module) -> None:
    app.dependency_overrides.pop(get_session_store, None)
    app.dependency_overrides.pop(get_file_registry, None)


setup_module(None)
client: TestClient = TestClient(app)


def setup_function() -> None:
    global _test_store, _test_registry
    _test_store = SessionStore(ttl=1800)
    _test_registry = FileRegistry()


def _write_simple_lut(tmp_path: Path) -> str:
    lut_path = tmp_path / "simple_replace_sync_lut.npz"
    rgb = np.asarray(
        [
            [255, 0, 0],
            [0, 0, 255],
            [0, 255, 0],
        ],
        dtype=np.uint8,
    )
    stacks = np.asarray(
        [
            [0, 0],
            [1, 1],
            [2, 2],
        ],
        dtype=np.int16,
    )
    np.savez(lut_path, rgb=rgb, stacks=stacks)
    return str(lut_path)


def _decode_layer_png(url: str) -> np.ndarray:
    file_id = url.rsplit("/", 1)[-1]
    resolved = _test_registry.resolve(file_id)
    assert resolved is not None
    path, _filename = resolved
    with Image.open(path) as img:
        return np.asarray(img.convert("RGB"))


def _create_lut_session(tmp_path: Path) -> str:
    sid = _test_store.create()
    lut_path = _write_simple_lut(tmp_path)
    matched = np.zeros((3, 3, 3), dtype=np.uint8)
    matched[:, :] = [255, 0, 0]
    material_matrix = np.zeros((3, 3, 2), dtype=np.int16)
    mask_solid = np.ones((3, 3), dtype=bool)
    color_conf = {
        "preview": {
            0: [255, 0, 0, 255],
            1: [0, 0, 255, 255],
            2: [0, 255, 0, 255],
        },
        "slots": ["Red", "Blue"],
    }
    cache = {
        "matched_rgb": matched.copy(),
        "quantized_image": matched.copy(),
        "mask_solid": mask_solid,
        "material_matrix": material_matrix.copy(),
        "color_conf": color_conf,
        "preview_rgba": np.dstack(
            [matched.copy(), np.full((3, 3), 255, dtype=np.uint8)]
        ),
        "color_layers": 2,
        "layer_height_mm": 0.08,
    }
    _test_store.put(sid, "preview_cache", cache)
    _test_store.put(sid, "original_matched_rgb", matched.copy())
    _test_store.put(sid, "original_material_matrix", material_matrix.copy())
    _test_store.put(sid, "replacement_regions", [])
    _test_store.put(sid, "replacement_history", [])
    _test_store.put(sid, "lut_path", lut_path)
    _test_store.put(sid, "color_mode", "4-Color (RYBW)")
    _test_store.put(sid, "color_layers", 2)
    _test_store.put(sid, "layer_height_mm", 0.08)
    _test_store.put(sid, "material_source", "lut")
    return sid


class TestReplaceColorLayerSync:
    def test_replace_color_updates_material_matrix_and_layer_images(self, tmp_path: Path) -> None:
        sid = _create_lut_session(tmp_path)

        response = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        assert response.status_code == 200

        cache = _test_store.get(sid)["preview_cache"]
        expected_stack = np.asarray([1, 1], dtype=np.int16)
        np.testing.assert_array_equal(cache["material_matrix"][0, 0], expected_stack)
        np.testing.assert_array_equal(
            cache["matched_rgb"][0, 0],
            np.asarray([0, 0, 255], dtype=np.uint8),
        )

        layers = get_layer_images(session_id=sid, store=_test_store, registry=_test_registry)
        layer0 = _decode_layer_png(layers["layers"][0]["url"])
        layer1 = _decode_layer_png(layers["layers"][1]["url"])
        np.testing.assert_array_equal(layer0[0, 0], np.asarray([0, 0, 255], dtype=np.uint8))
        np.testing.assert_array_equal(layer1[0, 0], np.asarray([0, 0, 255], dtype=np.uint8))

    def test_region_replace_updates_material_matrix_for_selected_region(self, tmp_path: Path) -> None:
        sid = _create_lut_session(tmp_path)
        region_mask = np.zeros((3, 3), dtype=bool)
        region_mask[:2, :2] = True
        _test_store.put(sid, "selected_region_mask", region_mask)
        _test_store.put(sid, "selected_region_id", "region-a")

        response = client.post(
            "/api/convert/region-replace",
            json={
                "session_id": sid,
                "replacement_color": "#0000ff",
            },
        )
        assert response.status_code == 200

        cache = _test_store.get(sid)["preview_cache"]
        expected_stack = np.asarray([1, 1], dtype=np.int16)
        np.testing.assert_array_equal(cache["material_matrix"][0, 0], expected_stack)
        np.testing.assert_array_equal(cache["material_matrix"][2, 2], np.asarray([0, 0], dtype=np.int16))

    def test_reset_replacements_restores_original_material_matrix(self, tmp_path: Path) -> None:
        sid = _create_lut_session(tmp_path)

        replace_resp = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        assert replace_resp.status_code == 200
        changed_cache = _test_store.get(sid)["preview_cache"]
        assert int(changed_cache["material_matrix"][0, 0, 0]) == 1

        reset_resp = client.post(
            "/api/convert/reset-replacements",
            json={"session_id": sid},
        )
        assert reset_resp.status_code == 200
        reset_cache = _test_store.get(sid)["preview_cache"]
        np.testing.assert_array_equal(
            reset_cache["material_matrix"],
            _test_store.get(sid)["original_material_matrix"],
        )


class TestMaterialArchiveReplaceLayerSync:
    def test_replace_color_updates_material_matrix_with_material_solver(self, monkeypatch) -> None:
        sid = _test_store.create()
        matched = np.zeros((2, 2, 3), dtype=np.uint8)
        matched[:, :] = [10, 20, 30]
        material_matrix = np.zeros((2, 2, 5), dtype=np.int16)
        mask_solid = np.ones((2, 2), dtype=bool)
        cache = {
            "matched_rgb": matched.copy(),
            "quantized_image": matched.copy(),
            "mask_solid": mask_solid,
            "material_matrix": material_matrix.copy(),
            "preview_rgba": np.dstack(
                [matched.copy(), np.full((2, 2), 255, dtype=np.uint8)]
            ),
            "preview_colors": {
                0: [255, 0, 0, 255],
                1: [0, 255, 0, 255],
                2: [0, 0, 255, 255],
                3: [255, 255, 0, 255],
                4: [255, 255, 255, 255],
            },
            "slot_names": ["M0", "M1", "M2", "M3", "M4"],
            "color_layers": 5,
            "layer_height_mm": 0.08,
        }
        _test_store.put(sid, "preview_cache", cache)
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "replacement_history", [])
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "selected_materials", ["mat-a"])
        _test_store.put(sid, "material_layer_count", 5)
        _test_store.put(sid, "material_layer_height_mm", 0.08)

        monkeypatch.setattr(
            "api.routers.converter.replace.load_multiple_materials",
            lambda names: [object() for _ in names],
        )
        monkeypatch.setattr(
            "api.routers.converter.replace.load_material_solver_cache_with_fallback",
            lambda *args, **kwargs: (None, None),
        )
        monkeypatch.setattr(
            "api.routers.converter.replace.solve_image_colors_optimal",
            lambda targets, materials, layer_count, layer_height_mm, substrate: (
                np.asarray([[12, 34, 56]], dtype=np.uint8),
                np.asarray([[0, 1, 2, 3, 4]], dtype=np.int16),
                np.asarray([0.5], dtype=np.float64),
            ),
        )

        response = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#0a141e",
                "replacement_color": "#112233",
            },
        )
        assert response.status_code == 200

        updated_cache = _test_store.get(sid)["preview_cache"]
        np.testing.assert_array_equal(
            updated_cache["matched_rgb"][0, 0],
            np.asarray([12, 34, 56], dtype=np.uint8),
        )
        np.testing.assert_array_equal(
            updated_cache["material_matrix"][0, 0],
            np.asarray([4, 3, 2, 1, 0], dtype=np.int16),
        )
