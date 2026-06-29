"""Governance tests for the destructive system cache cleanup endpoint."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
from api.app import create_app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore


@dataclass
class _CacheScenario:
    client: TestClient
    registry: FileRegistry
    store: SessionStore
    session_id: str
    file_id: str
    final_path: Path

    def assert_artifact_available(self) -> None:
        response = self.client.get(f"/api/files/{self.file_id}")
        assert response.status_code == 200
        assert response.content == b"final artifact"
        assert self.final_path.exists()
        assert self.registry.get_entry(self.file_id) is not None
        assert self.store.get(self.session_id) is not None

    def assert_artifact_cleaned(self) -> None:
        response = self.client.get(f"/api/files/{self.file_id}")
        assert response.status_code == 404
        assert not self.final_path.exists()
        assert self.registry.get_entry(self.file_id) is None
        assert self.store.get(self.session_id) is None


@pytest.fixture()
def cache_scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> _CacheScenario:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    final_path = output_dir / "final.3mf"
    final_path.write_bytes(b"final artifact")

    registry = FileRegistry()
    store = SessionStore(ttl=3600)
    session_id = "session-clear-cache-origin"
    store.put(session_id, "ready", True)
    file_id = registry.register_path(
        session_id,
        str(final_path),
        "final.3mf",
        ttl_seconds=3600,
    )

    monkeypatch.setattr(config, "OUTPUT_DIR", str(output_dir))
    app = create_app()
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_session_store] = lambda: store
    return _CacheScenario(
        client=TestClient(app),
        registry=registry,
        store=store,
        session_id=session_id,
        file_id=file_id,
        final_path=final_path,
    )


def _capture_system_logger(caplog: pytest.LogCaptureFixture) -> logging.Logger:
    target_logger = logging.getLogger("lumina.api.routers.system")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=target_logger.name)
    return target_logger


def _release_system_logger(
    logger: logging.Logger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger.removeHandler(caplog.handler)


def _records_for_event(
    caplog: pytest.LogCaptureFixture,
    event: str,
) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == event
    ]


@pytest.mark.parametrize(
    ("origin", "host"),
    [
        ("https://example.invalid", "127.0.0.1:8000"),
        ("http://evil.test:8000", "evil.test:8000"),
        ("null", "127.0.0.1:8000"),
        ("not a url", "127.0.0.1:8000"),
        (None, "evil.test:8000"),
    ],
)
def test_clear_cache_allows_untrusted_origins(
    cache_scenario: _CacheScenario,
    caplog: pytest.LogCaptureFixture,
    origin: str | None,
    host: str,
) -> None:
    cache_scenario.assert_artifact_available()
    logger = _capture_system_logger(caplog)
    headers = {"Host": host}
    if origin is not None:
        headers["Origin"] = origin
    try:
        response = cache_scenario.client.post(
            "/api/system/clear-cache",
            headers=headers,
        )
    finally:
        _release_system_logger(logger, caplog)

    assert response.status_code == 200
    assert response.json()["details"]["registry_cleaned"] == 1
    assert response.json()["details"]["sessions_cleaned"] == 1
    cache_scenario.assert_artifact_cleaned()

    records = _records_for_event(caplog, "system_clear_cache_forbidden")
    assert records == []


def test_clear_cache_allows_direct_local_management_request(
    cache_scenario: _CacheScenario,
) -> None:
    cache_scenario.assert_artifact_available()

    response = cache_scenario.client.post(
        "/api/system/clear-cache",
        headers={"Host": "127.0.0.1:8000"},
    )

    assert response.status_code == 200
    assert response.json()["details"]["registry_cleaned"] == 1
    assert response.json()["details"]["sessions_cleaned"] == 1
    cache_scenario.assert_artifact_cleaned()


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:4174",
        "http://127.0.0.1:4174",
        "http://[::1]:4174",
    ],
)
def test_clear_cache_allows_local_frontend_origins(
    cache_scenario: _CacheScenario,
    origin: str,
) -> None:
    cache_scenario.assert_artifact_available()

    response = cache_scenario.client.post(
        "/api/system/clear-cache",
        headers={"Origin": origin, "Host": "127.0.0.1:8000"},
    )

    assert response.status_code == 200
    assert response.json()["details"]["registry_cleaned"] == 1
    assert response.json()["details"]["sessions_cleaned"] == 1
    cache_scenario.assert_artifact_cleaned()


def test_clear_cache_allows_any_frontend_port(
    cache_scenario: _CacheScenario,
) -> None:
    cache_scenario.assert_artifact_available()

    response = cache_scenario.client.post(
        "/api/system/clear-cache",
        headers={
            "Origin": "http://127.0.0.1:6123",
            "Host": "127.0.0.1:8000",
        },
    )

    assert response.status_code == 200
    assert response.json()["details"]["registry_cleaned"] == 1
    assert response.json()["details"]["sessions_cleaned"] == 1
    cache_scenario.assert_artifact_cleaned()
