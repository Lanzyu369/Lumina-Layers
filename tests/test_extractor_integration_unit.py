"""Unit tests for Extractor endpoint integration.

Validates:
- Corner points count validation returns 422 (Requirement 4.5)
- Session state persistence after extraction (Requirement 4.4)
- Field name mapping: distortion->barrel, vignette_correction->bright (Requirement 4.2)
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests._migrated_app import app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from utils.lut_manager import LUTManager

client: TestClient = TestClient(app)

# Shared mock return value: (vis_img, preview_img, lut_path, status_msg)
_mock_vis: np.ndarray = np.zeros((10, 10, 3), dtype=np.uint8)
_mock_preview: np.ndarray = np.zeros((10, 10, 3), dtype=np.uint8)
_mock_return = (_mock_vis, _mock_preview, "/tmp/test.npy", "OK")


@pytest.fixture(autouse=True)
def _isolate_dependency_overrides():
    """Isolate extractor integration tests from global override pollution."""
    test_store = SessionStore()
    test_registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: test_store
    app.dependency_overrides[get_file_registry] = lambda: test_registry
    try:
        yield {"store": test_store, "registry": test_registry}
    finally:
        app.dependency_overrides.pop(get_session_store, None)
        app.dependency_overrides.pop(get_file_registry, None)


def _make_test_image_buf() -> io.BytesIO:
    """Create a minimal PNG image buffer for upload."""
    img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# =========================================================================
# 1. Corner points validation - Requirement 4.5
# =========================================================================


class TestCornerPointsValidation:
    """Verify corner_points count != 4 returns HTTP 422."""

    def test_extract_invalid_corner_points_count_returns_422(self) -> None:
        """Send corner_points with 3 points, expect 422."""
        buf = _make_test_image_buf()
        response = client.post(
            "/api/extractor/extract",
            files={"image": ("test.png", buf, "image/png")},
            data={
                "corner_points": json.dumps([[0, 0], [100, 0], [100, 100]]),
                "color_mode": "4-Color",
                "distortion": "0.0",
                "vignette_correction": "false",
            },
        )
        assert response.status_code == 422
        assert "4 points" in response.json()["detail"]


# =========================================================================
# 2. Session state persistence - Requirement 4.4
# =========================================================================


class TestSessionStatePersistence:
    """Verify extraction stores session state with lut_path and color_mode."""

    def test_extract_stores_session_state(self, _isolate_dependency_overrides) -> None:
        """Mock run_extraction, verify session contains lut_path and color_mode."""
        buf = _make_test_image_buf()
        with patch(
            "api.routers.extractor.run_extraction",
            return_value=_mock_return,
        ):
            response = client.post(
                "/api/extractor/extract",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "corner_points": json.dumps([[0, 0], [100, 0], [100, 100], [0, 100]]),
                    "color_mode": "4-Color",
                    "distortion": "0.0",
                    "vignette_correction": "false",
                },
            )
        assert response.status_code == 200
        body = response.json()
        session_id: str = body["session_id"]
        assert session_id

        # Verify session data in store
        session_data = _isolate_dependency_overrides["store"].get(session_id)
        assert session_data is not None
        assert session_data["lut_path"] == "/tmp/test.npy"
        assert session_data["color_mode"] == "4-Color (RYBW)"

    def test_extract_endpoint_emits_canary_on_success(
        self,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
    ) -> None:
        """Successful extraction emits one structured INFO canary event."""
        buf = _make_test_image_buf()
        lut_path = tmp_path / "extract-lut.json"
        lut_path.write_text("{}", encoding="utf-8")
        vis_img = np.zeros((4, 4, 3), dtype=np.uint8)
        preview_img = np.zeros((4, 4, 3), dtype=np.uint8)
        target_logger = logging.getLogger("lumina.api.routers.extractor")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.INFO, logger=target_logger.name)

        try:
            with patch(
                "api.routers.extractor.run_extraction",
                return_value=(vis_img, preview_img, str(lut_path), "OK"),
            ):
                response = client.post(
                    "/api/extractor/extract",
                    files={"image": ("test.png", buf, "image/png")},
                    data={
                        "corner_points": json.dumps(
                            [[0, 0], [100, 0], [100, 100], [0, 100]]
                        ),
                        "color_mode": "4-Color",
                        "page": "Page 2",
                        "eight_color_full_export": "true",
                        "distortion": "0.0",
                        "vignette_correction": "false",
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "extractor_extract_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.color_mode == "4-Color (RYBW)"
        assert record.page == "Page 2"
        assert record.eight_color_full_export is True
        assert record.lut_path == str(lut_path)
        assert isinstance(record.extract_ms, float)
        assert record.extract_ms >= 0.0

    def test_merge_8color_emits_extractor_merge_8color_done_canary(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Successful 8-color merge emits one structured INFO canary event."""
        merged_lut_path = tmp_path / "merged-lut.json"
        monkeypatch.setattr("api.routers.extractor._get_assets_dir", lambda: str(tmp_path))
        monkeypatch.setattr("config.LUT_FILE_PATH", str(merged_lut_path))
        stacks = np.array(
            [[0, 1, 2, 3, 4, 5, 6, 7], [7, 6, 5, 4, 3, 2, 1, 0]],
            dtype=np.int32,
        )
        for page_index in (1, 2):
            page_path = tmp_path / f"temp_8c_page_{page_index}.json"
            rgb = np.array(
                [[255, 255, 255], [255, 0, 0] if page_index == 1 else [0, 128, 255]],
                dtype=np.uint8,
            )
            metadata = LUTManager.infer_default_metadata(
                page_path.stem,
                str(page_path),
                len(rgb),
                color_mode="8-Color Max",
            )
            LUTManager.save_keyed_json(str(page_path), rgb, stacks, metadata)

        target_logger = logging.getLogger("lumina.api.routers.extractor")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.INFO, logger=target_logger.name)

        try:
            response = client.post(
                "/api/extractor/merge-8color",
                json={"eight_color_full_export": False},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["session_id"]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "extractor_merge_8color_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.eight_color_full_export is False
        assert record.total_pages == 2 and isinstance(record.total_pages, int)
        assert record.merged_rgb_count == 4 and isinstance(record.merged_rgb_count, int)
        assert record.stacks_compatible is True and isinstance(record.stacks_compatible, bool)
        assert isinstance(record.merge_ms, float)
        assert record.merge_ms >= 0.0

    def test_merge_5color_extended_emits_canary(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Successful 5-color extended merge emits one structured INFO canary."""
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        merged_lut_path = tmp_path / "merged-lut.json"
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("config.LUT_FILE_PATH", str(merged_lut_path))
        stacks = np.array(
            [[0, 1, 2, 3, 4], [4, 3, 2, 1, 0]],
            dtype=np.int32,
        )
        for page_index in (1, 2):
            page_path = assets_dir / f"temp_5c_ext_page_{page_index}.json"
            rgb = np.array(
                [[255, 255, 255], [255, 0, 0] if page_index == 1 else [0, 0, 0]],
                dtype=np.uint8,
            )
            metadata = LUTManager.infer_default_metadata(
                page_path.stem,
                str(page_path),
                len(rgb),
                color_mode="5-Color Extended",
            )
            LUTManager.save_keyed_json(str(page_path), rgb, stacks, metadata)

        target_logger = logging.getLogger("lumina.api.routers.extractor")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.INFO, logger=target_logger.name)

        try:
            response = client.post("/api/extractor/merge-5color-extended", json={})
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["session_id"]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "extractor_merge_5color_extended_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.merged_rgb_count == 4 and isinstance(record.merged_rgb_count, int)
        assert record.stacks_compatible is True and isinstance(record.stacks_compatible, bool)
        assert isinstance(record.merge_ms, float)
        assert record.merge_ms >= 0.0

    def test_manual_fix_emits_canary(
        self,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
    ) -> None:
        """Successful manual fix emits one structured INFO canary event."""
        lut_path = tmp_path / "manual-fix-lut.json"
        rgb = np.array(
            [
                [255, 255, 255],
                [255, 255, 0],
                [0, 128, 255],
                [0, 0, 0],
            ],
            dtype=np.uint8,
        )
        stacks = np.zeros((4, 0), dtype=np.int32)
        metadata = LUTManager.infer_default_metadata(
            lut_path.stem,
            str(lut_path),
            len(rgb),
            color_mode="4-Color (RYBW)",
        )
        LUTManager.save_keyed_json(str(lut_path), rgb, stacks, metadata)

        target_logger = logging.getLogger("lumina.api.routers.extractor")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.INFO, logger=target_logger.name)

        try:
            response = client.post(
                "/api/extractor/manual-fix",
                json={
                    "lut_path": str(lut_path),
                    "cell_coord": [0, 0],
                    "override_color": "#ff0000",
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["lut_preview_url"]

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "extractor_manual_fix_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.cell_coord_row == 0 and isinstance(record.cell_coord_row, int)
        assert record.cell_coord_col == 0 and isinstance(record.cell_coord_col, int)
        assert record.override_color == "#ff0000"
        assert record.has_session is False and isinstance(record.has_session, bool)
        assert isinstance(record.manual_fix_ms, float)
        assert record.manual_fix_ms >= 0.0

    def test_preview_wb_emits_canary(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Successful white-balance preview emits one structured INFO canary event."""
        image = np.full((32, 32, 3), [128, 130, 132], dtype=np.uint8)
        buf = io.BytesIO()
        Image.fromarray(image, mode="RGB").save(buf, format="PNG")
        buf.seek(0)

        target_logger = logging.getLogger("lumina.api.routers.extractor")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.INFO, logger=target_logger.name)

        try:
            response = client.post(
                "/api/extractor/preview-wb",
                files={"image": ("wb.png", buf, "image/png")},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["preview_url"]
        assert body["width"] == 32
        assert body["height"] == 32

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "extractor_preview_wb_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.output_width == 32 and isinstance(record.output_width, int)
        assert record.output_height == 32 and isinstance(record.output_height, int)
        assert isinstance(record.wb_ms, float)
        assert record.wb_ms >= 0.0

    def test_rotate_emits_canary(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Successful rotate emits one structured INFO canary event."""
        image = np.full((16, 32, 3), [128, 130, 132], dtype=np.uint8)
        buf = io.BytesIO()
        Image.fromarray(image, mode="RGB").save(buf, format="PNG")
        buf.seek(0)

        target_logger = logging.getLogger("lumina.api.routers.extractor")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.INFO, logger=target_logger.name)

        try:
            response = client.post(
                "/api/extractor/rotate?direction=ccw",
                files={"image": ("rotate.png", buf, "image/png")},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["preview_url"]
        assert body["width"] == 16
        assert body["height"] == 32

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "extractor_rotate_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.direction == "ccw"
        assert record.output_width == 16 and isinstance(record.output_width, int)
        assert record.output_height == 32 and isinstance(record.output_height, int)
        assert isinstance(record.rotate_ms, float)
        assert record.rotate_ms >= 0.0

    def test_confirm_palette_emits_canary(
        self,
        _isolate_dependency_overrides,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
    ) -> None:
        """Successful palette confirmation emits one structured INFO canary."""
        store: SessionStore = _isolate_dependency_overrides["store"]
        lut_path = tmp_path / "confirm-palette-lut.json"
        rgb = np.array(
            [
                [255, 255, 255],
                [255, 0, 0],
                [255, 255, 0],
                [0, 128, 255],
            ],
            dtype=np.uint8,
        )
        stacks = np.zeros((4, 0), dtype=np.int32)
        metadata = LUTManager.infer_default_metadata(
            lut_path.stem,
            str(lut_path),
            len(rgb),
            color_mode="4-Color (RYBW)",
        )
        LUTManager.save_keyed_json(str(lut_path), rgb, stacks, metadata)
        session_id = store.create()
        store.put(session_id, "lut_path", str(lut_path))
        store.put(session_id, "color_mode", "4-Color (RYBW)")

        target_logger = logging.getLogger("lumina.api.routers.extractor")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.INFO, logger=target_logger.name)

        try:
            response = client.post(
                "/api/extractor/confirm-palette",
                json={
                    "session_id": session_id,
                    "manufacturer": "TestMfg",
                    "type": "PLA",
                    "palette": [
                        {
                            "color": "Red",
                            "material": "PLA Basic",
                            "hex_color": "#ff0000",
                            "color_name": "Red",
                        },
                        {
                            "color": "White",
                            "material": "PLA Basic",
                            "hex_color": "#ffffff",
                            "color_name": "White",
                        },
                    ],
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        canary_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "extractor_confirm_palette_done"
        ]
        assert len(canary_records) == 1

        record = canary_records[0]
        assert record.levelno == logging.INFO
        assert record.palette_size == 2 and isinstance(record.palette_size, int)
        assert record.manufacturer == "TestMfg"
        assert record.lut_type == "PLA"
        assert record.persisted_to_disk is True
        assert isinstance(record.confirm_ms, float)
        assert record.confirm_ms >= 0.0


# =========================================================================
# 3. Field name mapping - Requirement 4.2
# =========================================================================


class TestFieldNameMapping:
    """Verify API field names map to core function parameter names."""

    def test_extract_field_name_mapping(self) -> None:
        """Verify distortion->barrel, vignette_correction->bright, and 8-color full flag forwarding."""
        buf = _make_test_image_buf()
        with patch(
            "api.routers.extractor.run_extraction",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/extractor/extract",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "corner_points": json.dumps([[0, 0], [100, 0], [100, 100], [0, 100]]),
                    "color_mode": "4-Color",
                    "page": "Page 3",
                    "eight_color_full_export": "true",
                    "distortion": "0.1",
                    "vignette_correction": "true",
                },
            )
        assert response.status_code == 200
        mock_fn.assert_called_once()
        call_kwargs = mock_fn.call_args.kwargs
        # distortion -> barrel
        assert call_kwargs["barrel"] == 0.1
        # vignette_correction -> bright
        assert call_kwargs["bright"] is True
        # eight_color_full_export passthrough
        assert call_kwargs["eight_color_full_export"] is True
        assert call_kwargs["page_choice"] == "Page 3"
