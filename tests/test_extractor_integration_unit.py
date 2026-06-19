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

from api.app import app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from utils.lut_manager import LUTManager

client: TestClient = TestClient(app)

# Shared mock return value: (vis_img, preview_img, lut_path, status_msg)
_mock_vis: np.ndarray = np.zeros((10, 10, 3), dtype=np.uint8)
_mock_preview: np.ndarray = np.zeros((10, 10, 3), dtype=np.uint8)


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


def _write_keyed_lut(
    path: Path,
    rgb_rows: list[list[int]],
    *,
    color_mode: str = "4-Color (RYBW)",
) -> bytes:
    """Write a small keyed JSON LUT and return its exact bytes."""
    rgb = np.array(rgb_rows, dtype=np.uint8)
    stacks = np.zeros((len(rgb), 0), dtype=np.int32)
    metadata = LUTManager.infer_default_metadata(
        path.stem,
        str(path),
        len(rgb),
        color_mode=color_mode,
    )
    LUTManager.save_keyed_json(str(path), rgb, stacks, metadata)
    return path.read_bytes()


def _assert_download_survives_session_close(download_url: str, session_id: str) -> bytes:
    before_close = client.get(download_url)
    assert before_close.status_code == 200

    close_response = client.post("/api/session/close", json={"session_id": session_id})
    assert close_response.status_code == 200

    after_close = client.get(download_url)
    assert after_close.status_code == 200
    assert after_close.content == before_close.content
    return after_close.content


class _FailingLutDownloadRegistry(FileRegistry):
    """Registry stub that fails after the route creates a LUT download copy."""

    def __init__(self) -> None:
        super().__init__()
        self.registered_paths: list[str] = []

    def register_path(self, *args: object, **kwargs: object) -> str:
        path = kwargs.get("path")
        if path is None and len(args) >= 2:
            path = args[1]
        if path is not None:
            self.registered_paths.append(str(path))
        raise RuntimeError(
            "registry backend unavailable for /Users/min/private/file-registry.db"
        )


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

    def test_extract_stores_session_state(
        self,
        _isolate_dependency_overrides,
        tmp_path: Path,
    ) -> None:
        """Mock run_extraction, verify session contains lut_path and color_mode."""
        buf = _make_test_image_buf()
        lut_path = tmp_path / "test-lut.json"
        _write_keyed_lut(
            lut_path,
            [[255, 255, 255], [255, 0, 0], [0, 0, 0]],
        )
        with patch(
            "api.routers.extractor.run_extraction",
            return_value=(_mock_vis, _mock_preview, str(lut_path), "OK"),
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
        assert Path(session_data["lut_path"]).read_bytes() == lut_path.read_bytes()
        assert session_data["color_mode"] == "4-Color (RYBW)"

    def test_extract_lut_download_survives_source_session_close(
        self,
        tmp_path: Path,
    ) -> None:
        """The extractor final LUT download remains available after close."""
        lut_path = tmp_path / "extract-lut.json"
        expected_bytes = _write_keyed_lut(
            lut_path,
            [[255, 255, 255], [255, 0, 0], [0, 0, 0]],
        )
        buf = _make_test_image_buf()
        vis_img = np.zeros((4, 4, 3), dtype=np.uint8)
        preview_img = np.zeros((4, 4, 3), dtype=np.uint8)

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
                    "distortion": "0.0",
                    "vignette_correction": "false",
                },
            )

        assert response.status_code == 200
        body = response.json()
        downloaded = _assert_download_survives_session_close(
            body["lut_download_url"],
            body["session_id"],
        )
        assert downloaded == expected_bytes

    def test_extract_lut_download_registration_failure_is_bounded(
        self,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
        _isolate_dependency_overrides,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Failed final LUT registration should not leak a temp copy."""
        lut_path = tmp_path / "extract-lut.json"
        _write_keyed_lut(
            lut_path,
            [[255, 255, 255], [255, 0, 0], [0, 0, 0]],
        )
        buf = _make_test_image_buf()
        vis_img = np.zeros((4, 4, 3), dtype=np.uint8)
        preview_img = np.zeros((4, 4, 3), dtype=np.uint8)
        registry = _FailingLutDownloadRegistry()
        app.dependency_overrides[get_file_registry] = lambda: registry
        monkeypatch.setattr("api.routers.extractor.TEMP_DIR", str(tmp_path))

        extractor_logger = logging.getLogger("lumina.api.routers.extractor")
        app_logger = logging.getLogger("lumina.api.app")
        extractor_logger.addHandler(caplog.handler)
        app_logger.addHandler(caplog.handler)
        caplog.set_level(logging.ERROR, logger=extractor_logger.name)
        caplog.set_level(logging.ERROR, logger=app_logger.name)
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
                        "distortion": "0.0",
                        "vignette_correction": "false",
                    },
                )
        finally:
            extractor_logger.removeHandler(caplog.handler)
            app_logger.removeHandler(caplog.handler)

        assert response.status_code == 500
        assert response.json()["detail"] == (
            "Extractor LUT download could not be prepared. Try the extraction again."
        )
        assert "/Users/min/private" not in response.text
        assert registry.registered_paths
        assert list(tmp_path.glob("extractor_lut_*")) == []

        extractor_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "extractor_lut_download_registration_failed"
        ]
        assert len(extractor_records) == 1
        extractor_record = extractor_records[0]
        assert extractor_record.levelno == logging.ERROR
        assert extractor_record.status_code == 500
        assert extractor_record.error_type == "RuntimeError"
        assert extractor_record.lut_filename == "extract-lut.json"
        assert extractor_record.ttl_seconds == 8 * 60 * 60
        assert "/Users/min/private/file-registry.db" in extractor_record.error_message

        http_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "api_http_error"
        ]
        assert len(http_records) == 1
        assert http_records[0].error_message == response.json()["detail"]
        assert "/Users/min/private" not in http_records[0].error_message
        assert [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "api_unhandled_exception"
        ] == []

    def test_merge_5color_lut_download_survives_source_session_close(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The 5-color merged LUT download is independent of its session."""
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        merged_lut_path = tmp_path / "lumina_lut.json"
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("config.LUT_FILE_PATH", str(merged_lut_path))
        _write_keyed_lut(
            assets_dir / "temp_5c_ext_page_1.json",
            [[255, 255, 255], [255, 0, 0]],
            color_mode="5-Color Extended",
        )
        _write_keyed_lut(
            assets_dir / "temp_5c_ext_page_2.json",
            [[255, 255, 0], [0, 0, 0]],
            color_mode="5-Color Extended",
        )

        response = client.post("/api/extractor/merge-5color-extended", json={})

        assert response.status_code == 200
        body = response.json()
        _assert_download_survives_session_close(
            body["lut_download_url"],
            body["session_id"],
        )

    def test_merge_8color_lut_download_survives_source_session_close(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The 8-color merged LUT download is independent of its session."""
        merged_lut_path = tmp_path / "lumina_lut.json"
        monkeypatch.setattr("api.routers.extractor._get_assets_dir", lambda: str(tmp_path))
        monkeypatch.setattr("config.LUT_FILE_PATH", str(merged_lut_path))
        _write_keyed_lut(
            tmp_path / "temp_8c_page_1.json",
            [[255, 255, 255], [255, 0, 0]],
            color_mode="8-Color Max",
        )
        _write_keyed_lut(
            tmp_path / "temp_8c_page_2.json",
            [[255, 255, 0], [0, 128, 255]],
            color_mode="8-Color Max",
        )

        response = client.post(
            "/api/extractor/merge-8color",
            json={"eight_color_full_export": False},
        )

        assert response.status_code == 200
        body = response.json()
        _assert_download_survives_session_close(
            body["lut_download_url"],
            body["session_id"],
        )

    def test_merge_5color_lut_download_keeps_original_content_after_later_merge(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A returned merge download URL is not overwritten by later merges."""
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        merged_lut_path = tmp_path / "lumina_lut.json"
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("config.LUT_FILE_PATH", str(merged_lut_path))

        _write_keyed_lut(
            assets_dir / "temp_5c_ext_page_1.json",
            [[255, 255, 255], [255, 0, 0]],
            color_mode="5-Color Extended",
        )
        _write_keyed_lut(
            assets_dir / "temp_5c_ext_page_2.json",
            [[255, 255, 0], [0, 0, 0]],
            color_mode="5-Color Extended",
        )
        first_response = client.post("/api/extractor/merge-5color-extended", json={})
        assert first_response.status_code == 200
        first_url = first_response.json()["lut_download_url"]
        first_bytes = client.get(first_url).content

        _write_keyed_lut(
            assets_dir / "temp_5c_ext_page_1.json",
            [[1, 2, 3], [4, 5, 6]],
            color_mode="5-Color Extended",
        )
        _write_keyed_lut(
            assets_dir / "temp_5c_ext_page_2.json",
            [[7, 8, 9], [10, 11, 12]],
            color_mode="5-Color Extended",
        )
        second_response = client.post("/api/extractor/merge-5color-extended", json={})
        assert second_response.status_code == 200

        assert client.get(first_url).content == first_bytes

    def test_merge_5color_preserves_manual_fix_after_download_snapshot(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Manual fixes on an extracted page must be included in the merged LUT."""
        merged_lut_path = tmp_path / "lumina_lut.json"
        page_1_lut_path = tmp_path / "page-1-source.json"
        page_2_lut_path = tmp_path / "page-2-source.json"
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("config.LUT_FILE_PATH", str(merged_lut_path))
        _write_keyed_lut(
            page_1_lut_path,
            [[10, 10, 10], [20, 20, 20]],
            color_mode="5-Color Extended",
        )
        _write_keyed_lut(
            page_2_lut_path,
            [[30, 30, 30], [40, 40, 40]],
            color_mode="5-Color Extended",
        )

        def _extract_page(lut_path: Path) -> str:
            buf = _make_test_image_buf()
            with patch(
                "api.routers.extractor.run_extraction",
                return_value=(_mock_vis, _mock_preview, str(lut_path), "OK"),
            ):
                response = client.post(
                    "/api/extractor/extract",
                    files={"image": ("test.png", buf, "image/png")},
                    data={
                        "corner_points": json.dumps(
                            [[0, 0], [100, 0], [100, 100], [0, 100]]
                        ),
                        "color_mode": "5-Color Extended",
                        "page": "Page 1" if lut_path == page_1_lut_path else "Page 2",
                        "distortion": "0.0",
                        "vignette_correction": "false",
                    },
                )
            assert response.status_code == 200
            return str(response.json()["session_id"])

        page_1_session_id = _extract_page(page_1_lut_path)
        _extract_page(page_2_lut_path)

        manual_response = client.post(
            "/api/extractor/manual-fix",
            json={
                "session_id": page_1_session_id,
                "row_index": 0,
                "override_color": "#010203",
            },
        )
        assert manual_response.status_code == 200

        merge_response = client.post("/api/extractor/merge-5color-extended", json={})
        assert merge_response.status_code == 200
        merged_rgb, _merged_stacks, _metadata = LUTManager.load_lut_with_metadata(
            str(merged_lut_path)
        )
        assert merged_rgb.reshape(-1, 3)[0].tolist() == [1, 2, 3]

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

    def test_extract_field_name_mapping(self, tmp_path: Path) -> None:
        """Verify distortion->barrel, vignette_correction->bright, and 8-color full flag forwarding."""
        buf = _make_test_image_buf()
        lut_path = tmp_path / "field-mapping-lut.json"
        _write_keyed_lut(
            lut_path,
            [[255, 255, 255], [255, 0, 0], [0, 0, 0]],
        )
        with patch(
            "api.routers.extractor.run_extraction",
            return_value=(_mock_vis, _mock_preview, str(lut_path), "OK"),
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
