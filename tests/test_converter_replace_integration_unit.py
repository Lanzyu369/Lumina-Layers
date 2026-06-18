"""Integration tests for converter replace endpoint log canaries."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import (
    externalize_preview_cache,
    hydrate_preview_cache,
    is_preview_cache_artifact_ref,
)
from api.session_store import SessionStore

client: TestClient = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_dependency_overrides():
    """Isolate converter replace tests from global dependency overrides."""
    test_store = SessionStore()
    test_registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: test_store
    app.dependency_overrides[get_file_registry] = lambda: test_registry
    try:
        yield {"store": test_store, "registry": test_registry}
    finally:
        app.dependency_overrides.pop(get_session_store, None)
        app.dependency_overrides.pop(get_file_registry, None)


def _seed_preview_session(store: SessionStore) -> str:
    """Create a small valid preview cache for replace endpoint tests."""
    session_id = store.create()
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    matched_rgb[:2, :, :] = [255, 255, 255]
    matched_rgb[2:, :, :] = [255, 0, 0]
    mask_solid = np.ones((4, 4), dtype=bool)
    store.put(
        session_id,
        "preview_cache",
        {
            "matched_rgb": matched_rgb.copy(),
            "quantized_image": matched_rgb.copy(),
            "mask_solid": mask_solid,
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "color_palette": [],
        },
    )
    store.put(session_id, "original_matched_rgb", matched_rgb.copy())
    store.put(session_id, "material_source", "lut")
    return session_id


def _seed_artifact_preview_session(store: SessionStore, tmp_path) -> str:
    """Create a preview-like artifact-backed session without top-level originals."""
    session_id = store.create()
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    matched_rgb[:2, :, :] = [255, 255, 255]
    matched_rgb[2:, :, :] = [255, 0, 0]
    mask_solid = np.ones((4, 4), dtype=bool)
    cache = {
        "matched_rgb": matched_rgb.copy(),
        "original_matched_rgb": matched_rgb.copy(),
        "quantized_image": matched_rgb.copy(),
        "mask_solid": mask_solid,
        "target_w": 4,
        "target_h": 4,
        "target_width_mm": 40.0,
        "color_palette": [],
    }
    ref = externalize_preview_cache(
        session_id,
        store,
        cache,
        root_dir=tmp_path,
    )
    store.put(session_id, "preview_cache", ref)
    store.put(session_id, "replacement_regions", [])
    store.put(session_id, "replacement_history", [])
    store.put(session_id, "material_source", "lut")
    return session_id


def _delete_externalized_preview_cache_field(
    store: SessionStore,
    session_id: str,
    field_name: str,
) -> Path:
    cache_ref = store.get(session_id)["preview_cache"]
    field_path = Path(cache_ref["fields"][field_name]["path"])
    assert field_path.exists()
    field_path.unlink()
    assert not field_path.exists()
    return field_path


def _capture_replace_logger(caplog: pytest.LogCaptureFixture) -> logging.Logger:
    target_logger = logging.getLogger("lumina.api.routers.converter.replace")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=target_logger.name)
    return target_logger


def _seed_region_requantize_session(store: SessionStore, tmp_path) -> str:
    session_id = store.create()
    height, width = 16, 16
    matched_rgb = np.full((height, width, 3), [10, 20, 30], dtype=np.uint8)
    matched_rgb[:, width // 2 :, :] = [200, 50, 80]
    mask_solid = np.ones((height, width), dtype=bool)
    source_rgb = np.zeros((height, width, 3), dtype=np.uint8)
    source_rgb[:, :, 0] = np.arange(width, dtype=np.uint8)
    source_path = tmp_path / "region-requantize-source.png"
    Image.fromarray(source_rgb).save(source_path)

    region_id_map = np.zeros((height, width), dtype=np.uint32)
    region_id_map[4:12, 4:12] = 1001
    store.put(
        session_id,
        "preview_cache",
        {
            "matched_rgb": matched_rgb,
            "quantized_image": matched_rgb.copy(),
            "mask_solid": mask_solid,
            "target_w": width,
            "target_h": height,
            "target_width_mm": 40.0,
            "color_layers": 10,
            "layer_height_mm": 0.08,
            "material_substrate": "white",
        },
    )
    store.put(session_id, "gradient_region_id_map", region_id_map)
    store.put(session_id, "image_path", str(source_path))
    store.put(session_id, "material_source", "material_archive")
    store.put(session_id, "selected_materials", ["fake/A", "fake/B"])
    store.put(session_id, "material_layer_count", 10)
    store.put(session_id, "material_layer_height_mm", 0.08)
    store.put(session_id, "lut_name", "__material_archive__")
    return session_id


def _seed_recipe_session(store: SessionStore) -> str:
    session_id = store.create()
    matched_rgb = np.full((4, 4, 3), [250, 250, 250], dtype=np.uint8)
    mask_solid = np.ones((4, 4), dtype=bool)
    material_matrix = np.zeros((4, 4, 3), dtype=np.int32)
    material_matrix[:, :, :] = [0, 1, 0]
    region_mask = np.zeros((4, 4), dtype=bool)
    region_mask[:2, :2] = True
    store.put(
        session_id,
        "preview_cache",
        {
            "matched_rgb": matched_rgb.copy(),
            "quantized_image": matched_rgb.copy(),
            "mask_solid": mask_solid,
            "material_matrix": material_matrix,
            "color_layers": 3,
            "layer_height_mm": 0.08,
            "preview_colors": {
                0: [250, 250, 250, 255],
                1: [220, 40, 80, 255],
            },
            "slot_names": ["fake/A", "fake/B"],
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
        },
    )
    store.put(session_id, "material_source", "material_archive")
    store.put(session_id, "selected_materials", ["fake/A", "fake/B"])
    store.put(session_id, "material_layer_count", 3)
    store.put(session_id, "material_layer_height_mm", 0.08)
    store.put(session_id, "lut_name", "__material_archive__")
    store.put(session_id, "selected_region_masks", {"region-1": region_mask})
    store.put(session_id, "selected_region_id", "region-1")
    store.put(session_id, "selected_region_mask", region_mask)
    return session_id


class TestReplaceColorCanary:
    """Successful replace-color requests emit the structured done canary."""

    def test_replace_color_emits_converter_replace_color_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            with patch(
                "api.routers.converter.replace.schedule_glb_build",
                return_value="mock-glb-token",
            ):
                response = client.post(
                    "/api/convert/replace-color",
                    json={
                        "session_id": session_id,
                        "selected_color": "#ffffff",
                        "replacement_color": "#0000ff",
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["preview_url"]
        assert body["replacement_count"] >= 1

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_replace_color_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.selected_color == "#ffffff"
        assert record.replacement_color == "#0000ff"
        assert record.replacement_count == 1
        assert record.diff_pixel_count == 8

    def test_replace_color_keeps_artifact_preview_cache_externalized(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_artifact_preview_session(store, tmp_path)

        with patch(
            "api.routers.converter.common.hydrate_preview_cache",
            side_effect=AssertionError("replace-color must not fully hydrate artifact cache"),
        ), patch(
            "api.routers.converter.replace.schedule_glb_build",
            return_value="mock-glb-token",
        ):
            response = client.post(
                "/api/convert/replace-color",
                json={
                    "session_id": session_id,
                    "selected_color": "#ffffff",
                    "replacement_color": "#0000ff",
                },
            )

        assert response.status_code == 200, response.text
        stored = store.get(session_id)["preview_cache"]
        assert is_preview_cache_artifact_ref(stored)
        assert "matched_rgb" not in stored["metadata"]
        assert stored["fields"]["matched_rgb"]["revision"] == 2
        hydrated = hydrate_preview_cache(
            stored,
            fields={"matched_rgb", "original_matched_rgb"},
        )
        assert int(np.all(hydrated["matched_rgb"] == [0, 0, 255], axis=-1).sum()) == 8
        assert int(
            np.all(hydrated["original_matched_rgb"] == [255, 255, 255], axis=-1).sum()
        ) == 8


class TestResetReplacementsCanary:
    """Successful reset-replacements requests emit the structured done canary."""

    def test_reset_replacements_emits_converter_reset_replacements_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        store.put(
            session_id,
            "replacement_regions",
            [{"selected_color": "#ffffff", "replacement_color": "#0000ff"}],
        )
        store.put(session_id, "replacement_history", [[{"selected_color": "#ffffff"}]])
        target_logger = _capture_replace_logger(caplog)

        try:
            with patch(
                "api.routers.converter.replace.schedule_glb_build",
                return_value="mock-glb-token",
            ):
                response = client.post(
                    "/api/convert/reset-replacements",
                    json={"session_id": session_id},
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["preview_url"]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_reset_replacements_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.regions_cleared == 1
        assert record.history_truncated == 0

    def test_reset_replacements_restores_artifact_original_snapshot(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_artifact_preview_session(store, tmp_path)

        with patch(
            "api.routers.converter.common.hydrate_preview_cache",
            side_effect=AssertionError("reset-replacements must not fully hydrate artifact cache"),
        ), patch(
            "api.routers.converter.replace.schedule_glb_build",
            return_value="mock-glb-token",
        ):
            replace_response = client.post(
                "/api/convert/replace-color",
                json={
                    "session_id": session_id,
                    "selected_color": "#ffffff",
                    "replacement_color": "#0000ff",
                },
            )
            reset_response = client.post(
                "/api/convert/reset-replacements",
                json={"session_id": session_id},
            )

        assert replace_response.status_code == 200, replace_response.text
        assert reset_response.status_code == 200, reset_response.text
        stored = store.get(session_id)["preview_cache"]
        assert is_preview_cache_artifact_ref(stored)
        assert "original_matched_rgb" not in store.get(session_id)
        hydrated = hydrate_preview_cache(
            stored,
            fields={"matched_rgb", "original_matched_rgb"},
        )
        np.testing.assert_array_equal(
            hydrated["matched_rgb"],
            hydrated["original_matched_rgb"],
        )


class TestSourceColorPickCanary:
    """Successful source-color-pick requests emit the structured done canary."""

    def test_stale_artifact_cache_returns_repreview_error(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_artifact_preview_session(store, tmp_path)
        stale_path = _delete_externalized_preview_cache_field(
            store,
            session_id,
            "matched_rgb",
        )

        response = client.post(
            "/api/convert/source-color-pick",
            json={"session_id": session_id, "x": 0, "y": 0},
        )

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "Re-run preview" in detail
        assert str(stale_path) not in detail

    def test_source_color_pick_emits_converter_source_color_pick_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/source-color-pick",
                json={"session_id": session_id, "x": 0, "y": 0},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source_matched_hex"] == "#ffffff"
        assert body["quantized_hex"] == "#ffffff"

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_source_color_pick_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.picked_color == "#ffffff"
        assert record.pick_x == 0
        assert record.pick_y == 0


class TestColorHighlightCanary:
    """Successful color-highlight requests emit the structured done canary."""

    def test_color_highlight_emits_converter_color_highlight_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/color-highlight",
                json={"session_id": session_id, "color_hexes": ["#ffffff"]},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["preview_url"]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_color_highlight_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.highlighted_color == "#ffffff"
        assert record.highlighted_pixel_count == 8


class TestRegionDetectCanary:
    """Successful region-detect requests emit the structured done canary."""

    def test_region_detect_emits_converter_region_detect_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/region-detect",
                json={"session_id": session_id, "x": 0, "y": 0},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["region_id"]
        assert body["color_hex"] == "#ffffff"
        assert body["pixel_count"] == 8
        assert body["preview_url"]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_region_detect_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.click_x == 0
        assert record.click_y == 0
        assert record.detected_pixel_count == 8
        assert record.detected_dominant_color == "#ffffff"


class TestRegionRequantizeCanary:
    """Successful region-requantize requests expose the structured done fields."""

    def test_region_requantize_emits_converter_region_requantize_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_region_requantize_session(store, tmp_path)
        target_logger = _capture_replace_logger(caplog)

        def _fake_requantize(*, matched_rgb, original_source_rgb, region_id_map, **_kwargs):
            assert original_source_rgb is not None
            updated = np.asarray(matched_rgb).copy()
            mask = np.asarray(region_id_map) == 1001
            updated[mask] = [1, 2, 3]
            return updated, int(mask.sum())

        try:
            with patch(
                "api.routers.converter.replace.load_multiple_materials",
                return_value=[],
            ), patch(
                "api.routers.converter.replace.load_material_solver_cache_with_fallback",
                return_value=(object(), 64),
            ), patch(
                "api.routers.converter.replace.requantize_gradient_regions",
                side_effect=_fake_requantize,
            ), patch(
                "api.routers.converter.replace._sync_material_matrix_after_rgb_change",
            ), patch(
                "api.routers.converter.replace.recompute_gradient_groups_into_session",
                return_value=[],
            ), patch(
                "api.routers.converter.replace.schedule_glb_build",
                return_value="mock-glb-token",
            ):
                response = client.post(
                    "/api/convert/region-requantize",
                    json={
                        "session_id": session_id,
                        "targets": [
                            {
                                "gradient_group_index": 1,
                                "gradient_region_index": 1,
                            }
                        ],
                        "local_quantize_colors": 12,
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["preview_url"]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_region_requantize_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.target_lut == "__material_archive__"
        assert record.region_pixel_count == 64
        assert record.output_color_count >= 1

    def test_region_requantize_artifact_cache_avoids_common_full_hydrate(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_region_requantize_session(store, tmp_path)
        session_data = store.get(session_id)
        cache_ref = externalize_preview_cache(
            session_id,
            store,
            session_data["preview_cache"],
            root_dir=tmp_path,
        )
        store.put(session_id, "preview_cache", cache_ref)

        def _fake_requantize(*, matched_rgb, original_source_rgb, region_id_map, **_kwargs):
            assert original_source_rgb is not None
            updated = np.asarray(matched_rgb, dtype=np.uint8).copy()
            mask = np.asarray(region_id_map) == 1001
            updated[mask] = [90, 120, 150]
            return updated, int(mask.sum())

        with patch(
            "api.routers.converter.common.hydrate_preview_cache",
            side_effect=AssertionError("region-requantize must not fully hydrate artifact cache"),
        ), patch(
            "api.routers.converter.replace.load_multiple_materials",
            return_value=[],
        ), patch(
            "api.routers.converter.replace.load_material_solver_cache_with_fallback",
            return_value=(object(), 64),
        ), patch(
            "api.routers.converter.replace.requantize_gradient_regions",
            side_effect=_fake_requantize,
        ), patch(
            "api.routers.converter.replace._sync_material_matrix_after_rgb_change",
        ), patch(
            "api.routers.converter.replace.recompute_gradient_groups_into_session",
            return_value=[],
        ), patch(
            "api.routers.converter.replace.schedule_glb_build",
            return_value="mock-glb-token",
        ):
            response = client.post(
                "/api/convert/region-requantize",
                json={
                    "session_id": session_id,
                    "targets": [
                        {
                            "gradient_group_index": 1,
                            "gradient_region_index": 1,
                        }
                    ],
                    "local_quantize_colors": 12,
                },
            )

        assert response.status_code == 200, response.text
        stored = store.get(session_id)["preview_cache"]
        assert is_preview_cache_artifact_ref(stored)
        assert stored["fields"]["matched_rgb"]["revision"] == 2


class TestReplaceColorsBatchCanary:
    """Successful replace-colors-batch requests emit the structured done canary."""

    def test_replace_colors_batch_emits_converter_replace_colors_batch_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            with patch(
                "api.routers.converter.replace.schedule_glb_build",
                return_value="mock-glb-token",
            ):
                response = client.post(
                    "/api/convert/replace-colors-batch",
                    json={
                        "session_id": session_id,
                        "replacements": [
                            {
                                "selected_color": "#ffffff",
                                "replacement_color": "#0000ff",
                            },
                            {
                                "selected_color": "#ff0000",
                                "replacement_color": "#00ff00",
                            },
                        ],
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["preview_url"]
        assert body["replacement_count"] == 2

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_replace_colors_batch_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.pair_count == 2
        assert record.diff_pixel_count == 16
        assert record.replacement_count == 2

    def test_replace_colors_batch_artifact_cache_avoids_common_full_hydrate(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_artifact_preview_session(store, tmp_path)

        with patch(
            "api.routers.converter.common.hydrate_preview_cache",
            side_effect=AssertionError("replace-colors-batch must not fully hydrate artifact cache"),
        ), patch(
            "api.routers.converter.replace.schedule_glb_build",
            return_value="mock-glb-token",
        ):
            response = client.post(
                "/api/convert/replace-colors-batch",
                json={
                    "session_id": session_id,
                    "replacements": [
                        {
                            "selected_color": "#ffffff",
                            "replacement_color": "#0000ff",
                        },
                        {
                            "selected_color": "#ff0000",
                            "replacement_color": "#00ff00",
                        },
                    ],
                },
            )

        assert response.status_code == 200, response.text
        stored = store.get(session_id)["preview_cache"]
        assert is_preview_cache_artifact_ref(stored)
        assert stored["fields"]["matched_rgb"]["revision"] == 2


class TestRegionReplaceBatchCanary:
    """Successful region-replace-batch requests emit the structured done canary."""

    def test_region_replace_batch_emits_converter_region_replace_batch_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            with patch(
                "api.routers.converter.replace.schedule_glb_build",
                return_value="mock-glb-token",
            ):
                response = client.post(
                    "/api/convert/region-replace-batch",
                    json={
                        "session_id": session_id,
                        "items": [
                            {
                                "replacement_color": "#0000ff",
                                "click_x": 0,
                                "click_y": 0,
                            }
                        ],
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["preview_url"]
        assert "Batch replaced" in body["message"]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_region_replace_batch_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.item_count == 1
        assert record.diff_pixel_count == 8
        assert record.any_click_mask_used is True

    def test_region_replace_batch_artifact_cache_avoids_common_full_hydrate(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_artifact_preview_session(store, tmp_path)

        with patch(
            "api.routers.converter.common.hydrate_preview_cache",
            side_effect=AssertionError("region-replace-batch must not fully hydrate artifact cache"),
        ), patch(
            "api.routers.converter.replace.schedule_glb_build",
            return_value="mock-glb-token",
        ):
            response = client.post(
                "/api/convert/region-replace-batch",
                json={
                    "session_id": session_id,
                    "items": [
                        {
                            "replacement_color": "#0000ff",
                            "click_x": 0,
                            "click_y": 0,
                        }
                    ],
                },
            )

        assert response.status_code == 200, response.text
        stored = store.get(session_id)["preview_cache"]
        assert is_preview_cache_artifact_ref(stored)
        assert stored["fields"]["matched_rgb"]["revision"] == 2


class TestPredictRecipeCanary:
    """Material-archive predict-recipe fixtures avoid a real LUT file dependency."""

    def test_predict_recipe_emits_converter_predict_recipe_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_recipe_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/predict-recipe",
                json={
                    "session_id": session_id,
                    "recipe": [0, 1, 0],
                    "layer_height_mm": 0.08,
                    "color_layers": 3,
                    "layer_order": "Top2Bottom",
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert len(body["rgb"]) == 3
        assert body["source"] == "material_archive_preview"

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_predict_recipe_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.recipe_layer_count == 3
        assert record.prediction_source == "material_archive_preview"
        assert record.is_material_archive is True


class TestApplyRecipeOverrideCanary:
    """Successful apply-recipe-override requests emit the structured done canary."""

    def test_apply_recipe_override_emits_converter_apply_recipe_override_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_recipe_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            with patch(
                "api.routers.converter.replace.schedule_glb_build",
                return_value="mock-glb-token",
            ):
                response = client.post(
                    "/api/convert/apply-recipe-override",
                    json={
                        "session_id": session_id,
                        "region_ids": ["region-1"],
                        "recipe": [0, 1, 0],
                        "layer_height_mm": 0.08,
                        "color_layers": 3,
                        "layer_order": "Top2Bottom",
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["preview_url"]
        assert body["override_count"] == 1

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_apply_recipe_override_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.region_count == 1
        assert record.recipe_layer_count == 3
        assert record.override_count == 1
        assert record.prediction_source == "material_archive_preview"

    def test_apply_recipe_override_artifact_cache_avoids_common_full_hydrate(
        self,
        _isolate_dependency_overrides,
        tmp_path,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_recipe_session(store)
        session_data = store.get(session_id)
        cache_ref = externalize_preview_cache(
            session_id,
            store,
            session_data["preview_cache"],
            root_dir=tmp_path,
        )
        store.put(session_id, "preview_cache", cache_ref)

        with patch(
            "api.routers.converter.common.hydrate_preview_cache",
            side_effect=AssertionError("apply-recipe-override must not fully hydrate artifact cache"),
        ), patch(
            "api.routers.converter.replace.schedule_glb_build",
            return_value="mock-glb-token",
        ):
            response = client.post(
                "/api/convert/apply-recipe-override",
                json={
                    "session_id": session_id,
                    "region_ids": ["region-1"],
                    "recipe": [0, 1, 0],
                    "layer_height_mm": 0.08,
                    "color_layers": 3,
                    "layer_order": "Top2Bottom",
                },
            )

        assert response.status_code == 200, response.text
        stored = store.get(session_id)["preview_cache"]
        assert is_preview_cache_artifact_ref(stored)
        assert stored["fields"]["matched_rgb"]["revision"] == 2
        assert stored["fields"]["material_matrix"]["revision"] == 2


class TestRegionRecipeCanary:
    """Successful region-recipe requests emit the structured done canary."""

    def test_region_recipe_emits_converter_region_recipe_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_recipe_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/region-recipe",
                json={
                    "session_id": session_id,
                    "region_ids": ["region-1"],
                    "layer_order": "Top2Bottom",
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["recipes"]
        assert body["recipes"][0]["recipe"] == [0, 1, 0]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_region_recipe_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.requested_region_count == 1
        assert record.resolved_region_count == 1
        assert record.layer_order == "Top2Bottom"


class TestMergeColorsCanary:
    """Successful merge-colors requests emit the structured done canary."""

    def test_merge_colors_emits_converter_merge_colors_done_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/merge-colors",
                json={
                    "session_id": session_id,
                    "merge_enable": True,
                    "merge_threshold": 5.0,
                    "merge_max_distance": 20,
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["preview_url"]
        assert isinstance(body["colors_before"], int)
        assert isinstance(body["colors_after"], int)
        assert 0 <= body["quality_metric"] <= 100

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_merge_colors_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.merge_enabled is True
        assert record.colors_before == body["colors_before"]
        assert record.colors_after == body["colors_after"]
        assert record.merge_map_count == len(body["merge_map"])
        assert record.quality_metric == body["quality_metric"]

    def test_merge_colors_disabled_branch_preserves_payload_and_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = _isolate_dependency_overrides["store"]
        session_id = _seed_preview_session(store)
        target_logger = _capture_replace_logger(caplog)

        try:
            response = client.post(
                "/api/convert/merge-colors",
                json={
                    "session_id": session_id,
                    "merge_enable": False,
                    "merge_threshold": 5.0,
                    "merge_max_distance": 20,
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["message"] == "Color merging disabled"
        assert body["preview_url"]
        assert body["merge_map"] == {}
        assert body["quality_metric"] == 100.0
        assert body["colors_before"] == body["colors_after"]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_merge_colors_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.merge_enabled is False
        assert record.merge_map_count == 0
        assert record.quality_metric == 100.0
