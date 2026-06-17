from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import (
    externalize_preview_cache,
    is_preview_cache_artifact_ref,
    save_preview_cache_fields,
)
from api.routers.converter.preview import get_layer_images
from api.session_store import SessionStore
from api.structured_logging import bind_session_id, set_request_id

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
    _clear_logging_context()
    _test_store = SessionStore(ttl=1800)
    _test_registry = FileRegistry()


def teardown_function() -> None:
    _clear_logging_context()


def _clear_logging_context() -> None:
    set_request_id(None)
    bind_session_id(None)


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


def _create_artifact_lut_session(tmp_path: Path) -> str:
    sid = _create_lut_session(tmp_path)
    session_data = _test_store.get(sid)
    cache = session_data["preview_cache"]
    cache_ref = externalize_preview_cache(
        sid,
        _test_store,
        cache,
        root_dir=tmp_path,
    )
    _test_store.put(sid, "preview_cache", cache_ref)
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

    def test_region_replace_artifact_cache_avoids_common_full_hydrate(
        self,
        tmp_path: Path,
    ) -> None:
        sid = _create_artifact_lut_session(tmp_path)
        region_mask = np.zeros((3, 3), dtype=bool)
        region_mask[:2, :2] = True
        _test_store.put(sid, "selected_region_mask", region_mask)
        _test_store.put(sid, "selected_region_id", "region-a")

        from unittest.mock import patch

        with patch(
            "api.routers.converter.common.hydrate_preview_cache",
            side_effect=AssertionError("region-replace must not fully hydrate artifact cache"),
        ), patch(
            "api.routers.converter.replace.schedule_glb_build",
            return_value="mock-glb-token",
        ):
            response = client.post(
                "/api/convert/region-replace",
                json={
                    "session_id": sid,
                    "replacement_color": "#0000ff",
                },
            )

        assert response.status_code == 200, response.text
        cache_ref = _test_store.get(sid)["preview_cache"]
        assert is_preview_cache_artifact_ref(cache_ref)
        assert cache_ref["fields"]["matched_rgb"]["revision"] == 2
        assert cache_ref["fields"]["material_matrix"]["revision"] == 2

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

    def test_replace_color_trims_long_material_matrix_for_short_solver_recipe(self, monkeypatch) -> None:
        sid = _test_store.create()
        matched = np.zeros((2, 2, 3), dtype=np.uint8)
        matched[:, :] = [10, 20, 30]
        material_matrix = np.zeros((2, 2, 7), dtype=np.int16)
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
            "color_layers": 7,
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
        assert updated_cache["material_matrix"].shape == (2, 2, 5)
        assert updated_cache["color_layers"] == 5
        np.testing.assert_array_equal(
            updated_cache["material_matrix"][0, 0],
            np.asarray([4, 3, 2, 1, 0], dtype=np.int16),
        )


class TestLayerImagesCache:
    """Regression tests for the session-level /layer-images cache.

    The cache keys off ``material_matrix`` bytes + the palette so that when
    the user doesn't touch the replacement state, a second request bypasses
    the ~6s full PNG rebuild. Any structural change to the matrix has to
    invalidate the cache so stale layer images never leak.
    /layer-images 的 session 级缓存回归：matrix 不变时 PNG 字节必须完全
    相同（命中）；matrix 改动必须使缓存失效并重新编码（miss）。
    """

    def test_empty_palette_negative_material_ids_fall_back_to_body_grey(self) -> None:
        """Empty-palette previews should not crash on ``-1`` material ids."""
        sid = _test_store.create()
        material_matrix = np.full((2, 2, 1), -1, dtype=np.int16)
        cache = {
            "mask_solid": np.ones((2, 2), dtype=bool),
            "material_matrix": material_matrix,
            "color_conf": {"preview": {}, "slots": []},
            "preview_colors": {},
            "slot_names": [],
        }
        _test_store.put(sid, "preview_cache", cache)

        response = client.get(f"/api/convert/layer-images/{sid}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["session_id"] == sid
        assert len(payload["layers"]) == 1
        assert payload["layers"][0]["layer_index"] == 0
        assert payload["layers"][0]["name"] == "Layer 0"
        assert payload["layers"][0]["url"].startswith("/api/files/")
        layer = _decode_layer_png(payload["layers"][0]["url"])
        np.testing.assert_array_equal(
            layer[0, 0],
            np.asarray([220, 220, 220], dtype=np.uint8),
        )

    def test_second_call_returns_identical_png_bytes(self, tmp_path: Path) -> None:
        sid = _create_lut_session(tmp_path)

        first = get_layer_images(
            session_id=sid, store=_test_store, registry=_test_registry
        )
        first_bytes = [
            _read_bytes(entry["url"]) for entry in first["layers"]
        ]

        second = get_layer_images(
            session_id=sid, store=_test_store, registry=_test_registry
        )
        second_bytes = [
            _read_bytes(entry["url"]) for entry in second["layers"]
        ]

        assert [e["name"] for e in first["layers"]] == [
            e["name"] for e in second["layers"]
        ]
        assert first_bytes == second_bytes, (
            "cache hit must reuse encoded PNG bytes byte-for-byte"
        )

    def test_matrix_change_invalidates_cache(self, tmp_path: Path) -> None:
        sid = _create_lut_session(tmp_path)

        first = get_layer_images(
            session_id=sid, store=_test_store, registry=_test_registry
        )
        first_bytes = [
            _read_bytes(entry["url"]) for entry in first["layers"]
        ]

        # Mutate material_matrix in place so the next call triggers a miss.
        # 直接改 material_matrix，下一次请求应重新编码。
        cache = _test_store.get(sid)["preview_cache"]
        cache["material_matrix"][0, 0, 0] = 1
        _test_store.put(sid, "preview_cache", cache)

        second = get_layer_images(
            session_id=sid, store=_test_store, registry=_test_registry
        )
        second_bytes = [
            _read_bytes(entry["url"]) for entry in second["layers"]
        ]

        assert first_bytes != second_bytes, (
            "matrix mutation must invalidate the cache and re-encode layers"
        )

    def test_artifact_cache_hit_uses_private_png_paths_without_hydrating(
        self,
        tmp_path: Path,
    ) -> None:
        sid = _create_artifact_lut_session(tmp_path)

        first = get_layer_images(
            session_id=sid, store=_test_store, registry=_test_registry
        )
        first_bytes = [_read_bytes(entry["url"]) for entry in first["layers"]]

        cached_entry = _test_store.get(sid)["layer_images_cache"]
        tracked_paths = set(_test_store.get_temp_file_paths(sid))
        assert cached_entry["layers"]
        for item in cached_entry["layers"]:
            assert "png_bytes" not in item
            assert Path(item["path"]).exists()
            assert item["path"] in tracked_paths

        from unittest.mock import patch

        with patch(
            "api.routers.converter.preview.hydrate_preview_cache",
            side_effect=AssertionError("cache hit must not hydrate artifact arrays"),
        ):
            second = get_layer_images(
                session_id=sid, store=_test_store, registry=_test_registry
            )

        second_bytes = [_read_bytes(entry["url"]) for entry in second["layers"]]
        assert first_bytes == second_bytes

    @staticmethod
    def _delete_preview_cache_field_file(sid: str, field_name: str) -> str:
        cache_ref = _test_store.get(sid)["preview_cache"]
        field_path = cache_ref["fields"][field_name]["path"]
        Path(field_path).unlink()
        return field_path

    @pytest.mark.parametrize("field_name", ["material_matrix", "mask_solid"])
    def test_artifact_cache_stale_field_returns_repreview_error(
        self,
        field_name: str,
        tmp_path: Path,
    ) -> None:
        sid = _create_artifact_lut_session(tmp_path)
        stale_path = self._delete_preview_cache_field_file(sid, field_name)

        response = client.get(f"/api/convert/layer-images/{sid}")

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "Re-run preview" in detail
        assert stale_path not in detail

    def test_artifact_cache_hit_survives_stale_source_fields(
        self,
        tmp_path: Path,
    ) -> None:
        sid = _create_artifact_lut_session(tmp_path)

        first = get_layer_images(
            session_id=sid, store=_test_store, registry=_test_registry
        )
        first_bytes = [_read_bytes(entry["url"]) for entry in first["layers"]]
        self._delete_preview_cache_field_file(sid, "material_matrix")
        self._delete_preview_cache_field_file(sid, "mask_solid")

        from unittest.mock import patch

        with patch(
            "api.routers.converter.preview.hydrate_preview_cache",
            side_effect=AssertionError("cache hit must not hydrate artifact arrays"),
        ):
            second = client.get(f"/api/convert/layer-images/{sid}")

        assert second.status_code == 200
        second_bytes = [_read_bytes(entry["url"]) for entry in second.json()["layers"]]
        assert first_bytes == second_bytes

    def test_artifact_material_matrix_revision_invalidates_layer_cache(
        self,
        tmp_path: Path,
    ) -> None:
        sid = _create_artifact_lut_session(tmp_path)

        first = get_layer_images(
            session_id=sid, store=_test_store, registry=_test_registry
        )
        first_bytes = [_read_bytes(entry["url"]) for entry in first["layers"]]
        old_key = _test_store.get(sid)["layer_images_cache"]["key"]

        cache_ref = _test_store.get(sid)["preview_cache"]
        updated_matrix = np.zeros((3, 3, 2), dtype=np.int16)
        updated_matrix[0, 0, 0] = 1
        updated_ref = save_preview_cache_fields(
            sid,
            _test_store,
            cache_ref,
            {"material_matrix": updated_matrix},
        )
        _test_store.put(sid, "preview_cache", updated_ref)

        second = get_layer_images(
            session_id=sid, store=_test_store, registry=_test_registry
        )
        second_bytes = [_read_bytes(entry["url"]) for entry in second["layers"]]
        new_key = _test_store.get(sid)["layer_images_cache"]["key"]

        assert old_key != new_key
        assert first_bytes != second_bytes


def _read_bytes(url: str) -> bytes:
    """Read the PNG bytes served by a ``/api/files/<id>`` URL via the
    test FileRegistry, ignoring the HTTP layer.
    通过测试 FileRegistry 直接读取 /api/files/<id> 对应的 PNG 字节。
    """
    file_id = url.rsplit("/", 1)[-1]
    resolved = _test_registry.resolve(file_id)
    assert resolved is not None
    path, _filename = resolved
    return Path(path).read_bytes()
