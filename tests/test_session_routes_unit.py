"""Unit tests for session heartbeat/close routes and file lease behavior."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store
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


@pytest.fixture()
def client_with_stores() -> Iterator[tuple[TestClient, SessionStore, FileRegistry]]:
    """Create a client with isolated session and file stores."""
    app = create_app()
    store = SessionStore(ttl=30)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    client = TestClient(app)
    try:
        yield client, store, registry
    finally:
        app.dependency_overrides.clear()


def test_session_heartbeat_renews_lease_and_returns_iso_expiry(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """POST /api/session/heartbeat should renew a known session lease."""
    client, store, _ = client_with_stores

    with patch("api.session_store.time.time", return_value=100.0):
        session_id = store.create()

    with patch("api.session_store.time.time", return_value=120.0):
        response = client.post("/api/session/heartbeat", json={"session_id": session_id})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    expires_at = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert expires_at == datetime.fromtimestamp(150.0, tz=timezone.utc)


def test_session_close_cleans_session_and_registry_files(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """POST /api/session/close should count unique deleted paths across session and registry cleanup."""
    client, store, registry = client_with_stores
    session_id = store.create()
    shared_path = _create_temp_file(b"shared-file")
    registry_only_path = _create_temp_file(b"registry-file")
    store.register_temp_file(session_id, shared_path)
    file_id = registry.register_path(session_id, shared_path, "result.bin")
    registry_only_file_id = registry.register_path(session_id, registry_only_path, "result-2.bin")

    response = client.post("/api/session/close", json={"session_id": session_id})

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "cleaned_files": 2}
    assert store.exists(session_id) is False
    assert registry.resolve(file_id) is None
    assert registry.resolve(registry_only_file_id) is None
    assert os.path.exists(shared_path) is False
    assert os.path.exists(registry_only_path) is False


def test_session_close_preserves_requested_file_ids(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """POST /api/session/close can release session data while preserving downloads."""
    client, store, registry = client_with_stores
    session_id = store.create()
    keep_path = _create_temp_file(b"download")
    delete_path = _create_temp_file(b"preview")
    store.register_temp_file(session_id, keep_path)
    store.register_temp_file(session_id, delete_path)
    keep_file_id = registry.register_path(session_id, keep_path, "download.3mf")
    delete_file_id = registry.register_path(session_id, delete_path, "preview.png")

    response = client.post(
        "/api/session/close",
        json={"session_id": session_id, "keep_file_ids": [keep_file_id]},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "cleaned_files": 1}
    assert store.exists(session_id) is False
    assert registry.resolve(keep_file_id) == (keep_path, "download.3mf")
    assert registry.resolve(delete_file_id) is None
    assert os.path.exists(keep_path) is True
    assert os.path.exists(delete_path) is False

    os.unlink(keep_path)


def test_session_close_preserved_file_ids_remain_downloadable(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """GET /api/files/{file_id} should still serve files explicitly kept on close."""
    client, store, registry = client_with_stores
    session_id = store.create()
    keep_path = _create_temp_file(b"download")
    store.register_temp_file(session_id, keep_path)
    keep_file_id = registry.register_path(session_id, keep_path, "download.3mf")

    try:
        close_response = client.post(
            "/api/session/close",
            json={"session_id": session_id, "keep_file_ids": [keep_file_id]},
        )

        assert close_response.status_code == 200
        assert store.exists(session_id) is False

        download_response = client.get(f"/api/files/{keep_file_id}")
        assert download_response.status_code == 200
        assert download_response.content == b"download"

        kept_entry = registry.get_entry(keep_file_id)
        assert kept_entry is not None
        assert kept_entry["lifecycle"] == "ephemeral"
        assert kept_entry["session_id"] is None
    finally:
        if os.path.exists(keep_path):
            os.unlink(keep_path)


def test_repeated_session_close_does_not_delete_preserved_file_ids(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """A later best-effort close without keep IDs must not reclaim detached kept files."""
    client, store, registry = client_with_stores
    session_id = store.create()
    keep_path = _create_temp_file(b"download")
    store.register_temp_file(session_id, keep_path)
    keep_file_id = registry.register_path(session_id, keep_path, "download.3mf")

    try:
        first_close = client.post(
            "/api/session/close",
            json={"session_id": session_id, "keep_file_ids": [keep_file_id]},
        )
        second_close = client.post(
            "/api/session/close",
            json={"session_id": session_id, "keep_file_ids": []},
        )

        assert first_close.status_code == 200
        assert second_close.status_code == 200
        assert os.path.exists(keep_path) is True
        assert registry.resolve(keep_file_id) == (keep_path, "download.3mf")

        download_response = client.get(f"/api/files/{keep_file_id}")
        assert download_response.status_code == 200
        assert download_response.content == b"download"
    finally:
        if os.path.exists(keep_path):
            os.unlink(keep_path)


def test_serve_file_allows_download_when_close_detaches_kept_file_mid_request(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """A close/detach race must not turn a kept download into a transient 404."""
    client, store, registry = client_with_stores
    session_id = store.create()
    keep_path = _create_temp_file(b"download")
    store.register_temp_file(session_id, keep_path)
    keep_file_id = registry.register_path(session_id, keep_path, "download.3mf")
    original_resolve = registry.resolve
    triggered = False

    def racing_resolve(file_id: str) -> tuple[str, str] | None:
        nonlocal triggered
        if file_id == keep_file_id and not triggered:
            triggered = True
            registry.detach_files({keep_file_id}, ttl_seconds=3600)
            store.close_except(session_id, keep_paths={keep_path})
        return original_resolve(file_id)

    try:
        with patch.object(registry, "resolve", side_effect=racing_resolve):
            response = client.get(f"/api/files/{keep_file_id}")

        assert response.status_code == 200
        assert response.content == b"download"
        kept_entry = registry.get_entry(keep_file_id)
        assert kept_entry is not None
        assert kept_entry["lifecycle"] == "ephemeral"
        assert kept_entry["session_id"] is None
        assert store.exists(session_id) is False
    finally:
        if os.path.exists(keep_path):
            os.unlink(keep_path)


def test_serve_file_recovers_when_close_detaches_kept_file_during_session_touch(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """The kept-file recovery also covers close races during session touch."""
    client, store, registry = client_with_stores
    session_id = store.create()
    keep_path = _create_temp_file(b"download")
    store.register_temp_file(session_id, keep_path)
    keep_file_id = registry.register_path(session_id, keep_path, "download.3mf")
    original_touch = store.touch
    triggered = False

    def racing_touch(touched_session_id: str) -> float | None:
        nonlocal triggered
        if touched_session_id == session_id and not triggered:
            triggered = True
            registry.detach_files({keep_file_id}, ttl_seconds=3600)
            store.close_except(session_id, keep_paths={keep_path})
            return None
        return original_touch(touched_session_id)

    try:
        with patch.object(store, "touch", side_effect=racing_touch):
            response = client.get(f"/api/files/{keep_file_id}")

        assert response.status_code == 200
        assert response.content == b"download"
        kept_entry = registry.get_entry(keep_file_id)
        assert kept_entry is not None
        assert kept_entry["lifecycle"] == "ephemeral"
        assert kept_entry["session_id"] is None
        assert store.exists(session_id) is False
    finally:
        if os.path.exists(keep_path):
            os.unlink(keep_path)


def test_serve_file_touches_session_bound_session_lease(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """GET /api/files/{file_id} should renew the owning session lease for session-bound files."""
    client, store, registry = client_with_stores
    path = _create_temp_file(b"payload")

    try:
        with patch("api.session_store.time.time", return_value=100.0):
            session_id = store.create()

        file_id = registry.register_path(session_id, path, "payload.bin")

        with patch("api.session_store.time.time", return_value=105.0), patch(
            "api.file_registry.time.time",
            return_value=105.0,
        ):
            response = client.get(f"/api/files/{file_id}")

        assert response.status_code == 200
        assert response.content == b"payload"

        with patch("api.session_store.time.time", return_value=131.0):
            assert store.cleanup_expired() == []

        with patch("api.session_store.time.time", return_value=136.0):
            assert store.cleanup_expired() == [session_id]
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_serve_file_returns_404_when_session_touch_fails_mid_request(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """GET /api/files/{file_id} must fail if session renewal cannot be committed."""
    client, store, registry = client_with_stores
    path = _create_temp_file(b"payload")

    try:
        session_id = store.create()
        file_id = registry.register_path(session_id, path, "payload.bin")

        with patch.object(store, "touch", return_value=None):
            response = client.get(f"/api/files/{file_id}")

        assert response.status_code == 404
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_serve_file_renews_ttl_file_on_access(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """GET /api/files/{file_id} should auto-renew TTL-backed files on successful access."""
    client, _, registry = client_with_stores
    path = _create_temp_file(b"ttl-payload")

    try:
        with patch("api.file_registry.time.time", return_value=100.0):
            file_id = registry.register_path("session-1", path, "lease.bin", ttl_seconds=10)

        with patch("api.file_registry.time.time", return_value=105.0):
            first_response = client.get(f"/api/files/{file_id}")

        with patch("api.file_registry.time.time", return_value=114.0):
            second_response = client.get(f"/api/files/{file_id}")

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert registry.get_entry(file_id) is not None
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_serve_large_glb_uses_gzip_when_client_accepts_it(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """GET /api/files/{file_id} should gzip large GLB previews for transport."""
    client, store, registry = client_with_stores
    session_id = store.create()
    payload = b"glTF" + (b"preview-model-payload" * 512)
    path = _create_temp_file(payload)
    glb_path = f"{path}.glb"
    os.replace(path, glb_path)
    file_id = registry.register_path(session_id, glb_path, "preview.glb")

    try:
        response = client.get(
            f"/api/files/{file_id}",
            headers={"Accept-Encoding": "gzip"},
        )

        assert response.status_code == 200
        assert response.headers["content-encoding"] == "gzip"
        assert response.headers["vary"] == "Accept-Encoding"
        assert response.headers["content-type"].startswith("model/gltf-binary")
        assert "content-length" not in response.headers
        assert response.content == payload
    finally:
        if os.path.exists(glb_path):
            os.unlink(glb_path)


def test_serve_glb_without_gzip_accept_encoding_uses_plain_file_response(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """GET /api/files/{file_id} should keep plain GLB responses when gzip is not accepted."""
    client, store, registry = client_with_stores
    session_id = store.create()
    payload = b"glTF" + (b"preview-model-payload" * 512)
    path = _create_temp_file(payload)
    glb_path = f"{path}.glb"
    os.replace(path, glb_path)
    file_id = registry.register_path(session_id, glb_path, "preview.glb")

    try:
        response = client.get(
            f"/api/files/{file_id}",
            headers={"Accept-Encoding": "identity"},
        )

        assert response.status_code == 200
        assert "content-encoding" not in response.headers
        assert response.headers["content-length"] == str(len(payload))
        assert response.content == payload
    finally:
        if os.path.exists(glb_path):
            os.unlink(glb_path)


def test_serve_non_glb_file_does_not_use_preview_gzip_path(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """GET /api/files/{file_id} should not gzip regular downloads through the GLB path."""
    client, store, registry = client_with_stores
    session_id = store.create()
    payload = b"3mf" + (b"download-payload" * 512)
    path = _create_temp_file(payload)
    model_path = f"{path}.3mf"
    os.replace(path, model_path)
    file_id = registry.register_path(session_id, model_path, "download.3mf")

    try:
        response = client.get(
            f"/api/files/{file_id}",
            headers={"Accept-Encoding": "gzip"},
        )

        assert response.status_code == 200
        assert "content-encoding" not in response.headers
        assert response.headers["content-length"] == str(len(payload))
        assert response.content == payload
    finally:
        if os.path.exists(model_path):
            os.unlink(model_path)


def test_cleanup_session_files_route_preserves_session_and_kept_registry_file(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """cleanup-session-files should preserve the session, ignore foreign keep IDs, and de-duplicate deleted paths."""
    client, store, registry = client_with_stores
    session_id = store.create()
    foreign_session_id = store.create()
    keep_path = _create_temp_file(b"keep")
    temp_path = _create_temp_file(b"temp")
    registry_only_path = _create_temp_file(b"registry-only")
    store.register_temp_file(session_id, keep_path)
    store.register_temp_file(session_id, temp_path)
    keep_file_id = registry.register_path(session_id, keep_path, "keep.bin")
    drop_file_id = registry.register_path(session_id, temp_path, "temp.bin")
    registry_only_file_id = registry.register_path(session_id, registry_only_path, "registry.bin")
    foreign_keep_path = _create_temp_file(b"foreign-keep")

    try:
        with patch("api.file_registry.time.time", return_value=100.0):
            foreign_keep_file_id = registry.register_path(
                foreign_session_id,
                foreign_keep_path,
                "foreign.bin",
                ttl_seconds=10,
            )

        response = client.post(
            "/api/convert/cleanup-session-files",
            json={
                "session_id": session_id,
                "keep_file_ids": [keep_file_id, foreign_keep_file_id],
            },
        )

        assert response.status_code == 200
        assert response.json() == {"status": "success", "cleaned": 2}
        assert store.exists(session_id) is True
        assert registry.resolve(keep_file_id) == (keep_path, "keep.bin")
        assert registry.resolve(drop_file_id) is None
        assert registry.resolve(registry_only_file_id) is None
        assert os.path.exists(keep_path) is True
        assert os.path.exists(temp_path) is False
        assert os.path.exists(registry_only_path) is False
        foreign_entry = registry.get_entry(foreign_keep_file_id)
        assert foreign_entry is not None
        assert foreign_entry["expires_at"] == 110.0
    finally:
        if os.path.exists(foreign_keep_path):
            os.unlink(foreign_keep_path)

    if os.path.exists(keep_path):
        os.unlink(keep_path)


def test_cleanup_session_files_preserves_regeneration_input_paths(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """cleanup-session-files must not delete inputs needed for a later generate call."""
    client, store, _ = client_with_stores
    session_id = store.create()
    image_path = _create_temp_file(b"image")
    lut_path = _create_temp_file(b"lut")
    intermediate_path = _create_temp_file(b"intermediate")
    store.put(session_id, "image_path", image_path)
    store.put(session_id, "lut_path", lut_path)
    store.register_temp_file(session_id, image_path)
    store.register_temp_file(session_id, lut_path)
    store.register_temp_file(session_id, intermediate_path)

    try:
        response = client.post(
            "/api/convert/cleanup-session-files",
            json={"session_id": session_id, "keep_file_ids": []},
        )

        assert response.status_code == 200
        assert store.exists(session_id) is True
        assert os.path.exists(image_path) is True
        assert os.path.exists(lut_path) is True
        assert os.path.exists(intermediate_path) is False
        assert image_path in store.get_temp_file_paths(session_id)
        assert lut_path in store.get_temp_file_paths(session_id)
    finally:
        for path in (image_path, lut_path, intermediate_path):
            if os.path.exists(path):
                os.unlink(path)


def test_serve_session_bound_file_returns_404_after_session_close_when_registry_cleanup_fails(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """GET /api/files/{file_id} must reject session-bound files whose session has already been closed."""
    client, store, registry = client_with_stores
    session_id = store.create()
    path = _create_temp_file(b"payload")
    file_id = registry.register_path(session_id, path, "payload.bin")

    try:
        with patch(
            "api.file_registry.os.remove",
            side_effect=PermissionError("locked"),
        ):
            close_response = client.post("/api/session/close", json={"session_id": session_id})

        assert close_response.status_code == 200
        assert close_response.json() == {"status": "ok", "cleaned_files": 0}
        assert store.exists(session_id) is False
        assert registry.get_entry(file_id) is not None

        response = client.get(f"/api/files/{file_id}")
        assert response.status_code == 404
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_serve_session_bound_file_returns_404_while_session_is_closing(
    client_with_stores: tuple[TestClient, SessionStore, FileRegistry],
) -> None:
    """GET /api/files/{file_id} must fail once the owning session is marked closing."""
    client, store, registry = client_with_stores
    session_id = store.create()
    path = _create_temp_file(b"payload")
    file_id = registry.register_path(session_id, path, "payload.bin")

    try:
        with store._lock:
            store._closing_sessions.add(session_id)

        response = client.get(f"/api/files/{file_id}")
        assert response.status_code == 404
    finally:
        if os.path.exists(path):
            os.unlink(path)
