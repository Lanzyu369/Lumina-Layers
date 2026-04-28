"""Integration tests for system router structured log canaries."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.dependencies import get_file_registry
from api.file_registry import FileRegistry
from api.schemas.system import UserSettings


def _client_with_registry() -> tuple[TestClient, FileRegistry]:
    app = create_app()
    registry = FileRegistry()
    app.dependency_overrides[get_file_registry] = lambda: registry
    return TestClient(app), registry


def _capture_system_logger(caplog: pytest.LogCaptureFixture) -> logging.Logger:
    target_logger = logging.getLogger("lumina.api.routers.system")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=target_logger.name)
    return target_logger


def _records_for_event(
    caplog: pytest.LogCaptureFixture,
    event_name: str,
) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == event_name
    ]


def _png_bytes(width: int = 4, height: int = 4) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


class TestSystemImagePreviewCanary:
    """Sessionless endpoint canary verifies session_id is not bound."""

    def test_image_preview_emits_sessionless_contract_canary(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, registry = _client_with_registry()
        target_logger = _capture_system_logger(caplog)
        try:
            response = client.post(
                "/api/system/image-preview",
                files={"file": ("preview_input.png", _png_bytes(6, 5), "image/png")},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["preview_url"].startswith("/api/files/")
        assert body["width"] == 6
        assert body["height"] == 5

        records = _records_for_event(caplog, "system_image_preview_done")
        assert len(records) == 1
        record = records[0]
        file_id = body["preview_url"].rsplit("/", 1)[-1]
        registered = registry.get_entry(file_id)

        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.original_filename == "preview_input.png"
        assert record.file_id == file_id
        assert record.image_width == 6
        assert record.image_height == 5
        assert registered is not None
        assert record.file_size_bytes == Path(str(registered["path"])).stat().st_size


class TestSystemSaveSettingsCanary:
    """Settings persistence canary isolates the real user settings file."""

    def test_save_settings_emits_sessionless_contract_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        settings_path = tmp_path / "settings.json"
        monkeypatch.setattr("api.routers.system.SETTINGS_FILE", settings_path)
        client, _registry = _client_with_registry()
        payload = UserSettings().model_dump()
        serialized = json.dumps(payload, indent=2, ensure_ascii=False)

        target_logger = _capture_system_logger(caplog)
        try:
            response = client.post("/api/system/settings", json=payload)
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "success"
        assert settings_path.read_text(encoding="utf-8") == serialized

        records = _records_for_event(caplog, "system_save_settings_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.settings_field_count == 10
        assert record.bytes_written == len(serialized.encode("utf-8"))
        assert record.settings_path == str(settings_path)
