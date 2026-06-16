"""Integration tests for slicer router structured log canaries."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.dependencies import get_file_registry
from api.file_registry import FileRegistry
from api.routers.slicer import _create_launch_copy
from core.slicer import DetectedSlicer


def _client_with_registry() -> tuple[TestClient, FileRegistry]:
    app = create_app()
    registry = FileRegistry()
    app.dependency_overrides[get_file_registry] = lambda: registry
    return TestClient(app), registry


def _capture_slicer_logger(caplog: pytest.LogCaptureFixture) -> logging.Logger:
    target_logger = logging.getLogger("lumina.api.routers.slicer")
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


class _RegisterPathFailingRegistry(FileRegistry):
    """Registry stub that records the launch copy path before failing."""

    def __init__(self) -> None:
        super().__init__()
        self.launch_copy_path: str | None = None

    def register_path(self, *args: object, **kwargs: object) -> str:
        path = kwargs.get("path")
        self.launch_copy_path = str(path) if path is not None else None
        raise RuntimeError("registry backend unavailable")


class TestSlicerLaunchCanary:
    """Slicer launch canary keeps subprocess execution mocked."""

    def test_create_launch_copy_cleans_copy_when_registry_fails(
        self,
        tmp_path: Path,
    ) -> None:
        source_path = tmp_path / "model.3mf"
        source_path.write_bytes(b"placeholder-3mf")
        registry = _RegisterPathFailingRegistry()

        try:
            with pytest.raises(RuntimeError, match="registry backend unavailable"):
                _create_launch_copy(str(source_path), registry)

            assert registry.launch_copy_path is not None
            assert not Path(registry.launch_copy_path).exists()
            assert source_path.exists()
        finally:
            if registry.launch_copy_path:
                Path(registry.launch_copy_path).unlink(missing_ok=True)

    def test_launch_slicer_emits_sessionless_contract_canary(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        source_path = tmp_path / "model.3mf"
        source_path.write_bytes(b"placeholder-3mf")
        fake_slicer = DetectedSlicer(
            id="bambu-studio",
            display_name="Bambu Studio",
            exe_path="C:/fake/BambuStudio.exe",
        )
        client, registry = _client_with_registry()
        target_logger = _capture_slicer_logger(caplog)
        try:
            with patch(
                "api.routers.slicer.detect_installed_slicers",
                return_value=[fake_slicer],
            ), patch(
                "api.routers.slicer.launch_slicer",
                return_value=(True, "launched"),
            ) as launch_mock:
                response = client.post(
                    "/api/slicer/launch",
                    json={
                        "slicer_id": "bambu-studio",
                        "file_path": str(source_path),
                    },
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        try:
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["status"] == "success"
            launch_mock.assert_called_once()

            records = _records_for_event(caplog, "slicer_launch_done")
            assert len(records) == 1
            record = records[0]
            assert record.levelno == logging.INFO
            assert "session_id" not in record.__dict__
            assert record.slicer_id == "bambu-studio"
            assert record.original_file_path == str(source_path)
            assert Path(record.launch_copy_path).is_file()
            assert record.launch_copy_filename == Path(record.launch_copy_path).name
            assert record.launch_message_length == len("launched")
        finally:
            registry.clear_all()
