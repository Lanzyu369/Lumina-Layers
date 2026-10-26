"""Integration tests for converter preview router log canaries."""

from __future__ import annotations

import io
import logging
import os
import tempfile
from unittest.mock import patch

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from api.routers.converter import preview as preview_router


@pytest.fixture()
def preview_client() -> TestClient:
    """Create an isolated preview-router test client."""

    test_app = FastAPI()
    test_app.include_router(preview_router.router, prefix="/api/convert")
    with TestClient(test_app, raise_server_exceptions=False) as client:
        yield client


def _capture_preview_logger(caplog: pytest.LogCaptureFixture) -> logging.Logger:
    logger = logging.getLogger("lumina.api.routers.converter.preview")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=logger.name)
    return logger


def _make_png_upload(name: str = "colors.png") -> tuple[str, io.BytesIO, str]:
    image = Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return (name, buffer, "image/png")


class TestAutoDetectColorsCanary:
    """Sessionless endpoint canary verifies session_id is NOT in record extras."""

    def test_auto_detect_colors_emits_sessionless_contract_canary(
        self,
        preview_client: TestClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        target_logger = _capture_preview_logger(caplog)
        try:
            with patch(
                "api.routers.converter.preview.ImagePreprocessor.analyze_recommended_colors",
                return_value={
                    "recommended": 24,
                    "max_safe": 48,
                    "unique_colors": 12,
                    "complexity_score": 42,
                },
            ):
                response = preview_client.post(
                    "/api/convert/auto-detect-colors",
                    files={"image": _make_png_upload("colors.png")},
                    data={"target_width_mm": "60.0"},
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["recommended"] == 24

        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_auto_detect_colors_done"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.image_filename == "colors.png"
        assert record.target_width_mm == 60.0
        assert record.recommended == 24
        assert record.max_safe == 48
        assert record.unique_colors == 12
        assert record.complexity_score == 42

    def test_auto_detect_colors_failure_emits_public_detail_and_log_canary(
        self,
        preview_client: TestClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        target_logger = _capture_preview_logger(caplog)
        raw_error = "raw failure /Users/min/private/source.png Permission denied"
        try:
            with patch(
                "api.routers.converter.preview.ImagePreprocessor.analyze_recommended_colors",
                side_effect=RuntimeError(raw_error),
            ):
                response = preview_client.post(
                    "/api/convert/auto-detect-colors",
                    files={"image": _make_png_upload("colors.png")},
                    data={"target_width_mm": "60.0"},
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 422, response.text
        assert response.json()["detail"] == preview_router.AUTO_DETECT_COLORS_FAILED_DETAIL
        assert "raw failure" not in response.text
        assert "/Users/min" not in response.text
        assert "Permission denied" not in response.text

        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_auto_detect_colors_failed"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.WARNING
        assert "session_id" not in record.__dict__
        assert record.image_filename == "colors.png"
        assert record.target_width_mm == 60.0
        assert record.error_type == "RuntimeError"
        assert record.error_message == raw_error

    def test_auto_detect_colors_cleanup_failure_does_not_override_public_error(
        self,
        preview_client: TestClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        temp_fd, temp_path = tempfile.mkstemp(suffix=".png")
        os.close(temp_fd)
        raw_error = "raw failure /Users/min/private/source.png Permission denied"
        cleanup_error = "cleanup denied /Users/min/private/temp.png"
        target_logger = _capture_preview_logger(caplog)
        try:
            with (
                patch(
                    "api.routers.converter.preview.ensure_png_tempfile",
                    return_value=temp_path,
                ),
                patch(
                    "api.routers.converter.preview.ImagePreprocessor.analyze_recommended_colors",
                    side_effect=RuntimeError(raw_error),
                ),
                patch(
                    "api.routers.converter.preview.os.unlink",
                    side_effect=OSError(cleanup_error),
                ),
            ):
                response = preview_client.post(
                    "/api/convert/auto-detect-colors",
                    files={"image": _make_png_upload("colors.png")},
                    data={"target_width_mm": "60.0"},
                )
        finally:
            target_logger.removeHandler(caplog.handler)
            if os.path.exists(temp_path):
                os.unlink(temp_path)

        assert response.status_code == 422, response.text
        assert response.json()["detail"] == preview_router.AUTO_DETECT_COLORS_FAILED_DETAIL
        assert "raw failure" not in response.text
        assert "cleanup denied" not in response.text
        assert "/Users/min" not in response.text

        cleanup_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_auto_detect_temp_cleanup_failed"
        ]
        assert len(cleanup_records) == 1
        cleanup_record = cleanup_records[0]
        assert cleanup_record.levelno == logging.WARNING
        assert cleanup_record.path == temp_path
        assert cleanup_record.error_type == "OSError"
        assert cleanup_record.error_message == cleanup_error
