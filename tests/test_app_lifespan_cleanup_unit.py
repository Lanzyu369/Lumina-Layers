"""Unit tests for app lifespan cleanup behavior."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import _run_cleanup_pass
from api.dependencies import get_file_registry, get_session_store
from api.app import create_app
from api.file_registry import FileRegistry
from api.session_store import SessionStore


def _create_temp_file(content: bytes = b"test-data") -> str:
    """Create a real temporary file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".tmp")
    try:
        os.write(fd, content)
    finally:
        os.close(fd)
    return path


def test_cleanup_pass_reclaims_registry_files_for_expired_closing_session() -> None:
    """A later cleanup pass should reclaim registry files even if session close is still blocked."""
    store = SessionStore(ttl=10)
    registry = FileRegistry()
    blocked_path = _create_temp_file(b"blocked")
    registry_path = _create_temp_file(b"registry")

    try:
        with patch("api.session_store.time.time", return_value=100.0):
            session_id = store.create()
            store.register_temp_file(session_id, blocked_path)

        file_id = registry.register_path(session_id, registry_path, "preview.glb")

        def _remove(path: str) -> None:
            if path == blocked_path:
                raise PermissionError("locked")
            os.unlink(path)

        with patch("api.session_store.time.time", return_value=111.0), patch(
            "api.session_store.os.remove",
            side_effect=_remove,
        ):
            _run_cleanup_pass(store, registry)

        assert store.exists(session_id) is False
        assert session_id in store.get_inactive_session_ids()
        assert registry.get_entry(file_id) is None
        assert os.path.exists(blocked_path) is True
        assert os.path.exists(registry_path) is False
    finally:
        for path in (blocked_path, registry_path):
            if os.path.exists(path):
                os.unlink(path)


def test_cleanup_pass_reclaims_registry_files_for_retired_session_after_close_route_failure() -> None:
    """A later cleanup pass should reclaim registry files for retired sessions after close-route failure."""
    app = create_app()
    store = SessionStore(ttl=30)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    client = TestClient(app)
    registry_path = _create_temp_file(b"registry")

    try:
        session_id = store.create()
        file_id = registry.register_path(session_id, registry_path, "result.3mf")
        attempts = 0

        def _remove(path: str) -> None:
            nonlocal attempts
            attempts += 1
            if path == registry_path and attempts == 1:
                raise PermissionError("locked")
            os.unlink(path)

        with patch("api.file_registry.os.remove", side_effect=_remove):
            response = client.post("/api/session/close", json={"session_id": session_id})

        assert response.status_code == 200
        assert store.exists(session_id) is False
        assert registry.get_entry(file_id) is not None
        assert os.path.exists(registry_path) is True

        _run_cleanup_pass(store, registry)

        assert registry.get_entry(file_id) is None
        assert os.path.exists(registry_path) is False
    finally:
        app.dependency_overrides.clear()
        if os.path.exists(registry_path):
            os.unlink(registry_path)


def test_cleanup_expired_retries_failed_session_bound_entry_after_tombstone_expires() -> None:
    """cleanup_expired() should reclaim failed session-bound entries even after the session tombstone expires."""
    app = create_app()
    store = SessionStore(ttl=1)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    client = TestClient(app)
    registry_path = _create_temp_file(b"registry")

    try:
        with patch("api.session_store.time.time", return_value=100.0):
            session_id = store.create()

        with patch("api.file_registry.time.time", return_value=100.0):
            file_id = registry.register_path(session_id, registry_path, "result.3mf")

        with patch("api.session_store.time.time", return_value=101.0), patch(
            "api.file_registry.time.time",
            return_value=101.0,
        ), patch(
            "api.file_registry.os.remove",
            side_effect=PermissionError("locked"),
        ):
            response = client.post("/api/session/close", json={"session_id": session_id})

        assert response.status_code == 200
        failed_entry = registry.get_entry(file_id)
        assert failed_entry is not None
        assert failed_entry["expires_at"] == 101.0

        with patch("api.session_store.time.time", return_value=103.0):
            assert store.get_registry_cleanup_candidate_session_ids() == []

        with patch("api.file_registry.time.time", return_value=103.0):
            removed = registry.cleanup_expired()

        assert removed == 1
        assert registry.get_entry(file_id) is None
        assert os.path.exists(registry_path) is False
    finally:
        app.dependency_overrides.clear()
        if os.path.exists(registry_path):
            os.unlink(registry_path)


def test_lifespan_starts_material_sync_auto_refresh_tasks() -> None:
    """App lifespan should delegate material sync background refresh startup."""
    calls = 0

    def _fake_start_tasks() -> list:
        nonlocal calls
        calls += 1
        return []

    app = create_app()

    with patch(
        "api.app.start_material_sync_auto_refresh_tasks",
        side_effect=_fake_start_tasks,
    ):
        with TestClient(app) as client:
            response = client.get("/api/health")

    assert response.status_code == 200
    assert calls == 1
