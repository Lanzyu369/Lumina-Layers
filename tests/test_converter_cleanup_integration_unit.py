"""Integration tests for converter cleanup router log canaries."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.routers.converter import cleanup as cleanup_router
from api.session_store import SessionStore


@pytest.fixture()
def cleanup_harness():
    """Create an isolated cleanup-router test client."""

    store = SessionStore(ttl=1800)
    registry = FileRegistry()

    test_app = FastAPI()
    test_app.include_router(cleanup_router.router, prefix="/api/convert")
    test_app.dependency_overrides[get_session_store] = lambda: store
    test_app.dependency_overrides[get_file_registry] = lambda: registry

    with TestClient(test_app, raise_server_exceptions=False) as client:
        yield {"client": client, "store": store, "registry": registry}

    store.clear_all()


def _capture_cleanup_logger(caplog: pytest.LogCaptureFixture) -> logging.Logger:
    logger = logging.getLogger("lumina.api.routers.converter.cleanup")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=logger.name)
    return logger


def _seed_cleanup_session(
    store: SessionStore,
    registry: FileRegistry,
    tmp_path,
) -> tuple[str, str]:
    session_id = store.create()
    image_path = tmp_path / "source.png"
    lut_path = tmp_path / "palette.npy"
    candidate_path = tmp_path / "preview.png"
    image_path.write_bytes(b"source")
    lut_path.write_bytes(b"lut")
    candidate_path.write_bytes(b"preview")
    store.put(session_id, "image_path", str(image_path))
    store.put(session_id, "lut_path", str(lut_path))
    store.register_temp_file(session_id, str(candidate_path))
    registry.register_path(session_id, str(candidate_path), filename="preview.png")
    return session_id, str(candidate_path)


class TestCleanupSessionFilesCanary:
    """Successful cleanup-session-files requests emit the structured done canary."""

    def test_cleanup_session_files_emits_contract_canary(
        self,
        cleanup_harness,
        tmp_path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = cleanup_harness["store"]
        registry: FileRegistry = cleanup_harness["registry"]
        client: TestClient = cleanup_harness["client"]
        session_id, candidate_path = _seed_cleanup_session(store, registry, tmp_path)

        target_logger = _capture_cleanup_logger(caplog)
        try:
            response = client.post(
                "/api/convert/cleanup-session-files",
                json={"session_id": session_id, "keep_file_ids": []},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "success"
        assert body["cleaned"] >= 0

        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_cleanup_session_files_done"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.cleaned == body["cleaned"]
        assert record.keep_file_id_count == 0
        assert record.keep_path_count == 2
        assert record.candidate_path_count == 1
        assert registry.get_session_entries(session_id) == {}
        assert not os.path.exists(candidate_path)
