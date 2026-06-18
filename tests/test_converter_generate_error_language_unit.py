"""Regression tests for user-safe converter generate failure details."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager


def _seed_generate_session(store: SessionStore, tmp_path: Path) -> str:
    """Create a minimal preview-ready session for /api/convert/generate."""

    image_path = tmp_path / "source.png"
    lut_path = tmp_path / "palette.npy"
    Image.new("RGB", (8, 8), (255, 0, 0)).save(image_path)
    np.save(lut_path, np.zeros((1, 3), dtype=np.uint8))

    session_id = store.create()
    store.put(
        session_id,
        "preview_cache",
        {
            "target_w": 8,
            "target_h": 8,
            "target_width_mm": 40.0,
        },
    )
    store.put(session_id, "image_path", str(image_path))
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "replacement_regions", [])
    store.put(session_id, "free_color_set", set())
    return session_id


def _post_generate_with_pool(tmp_path: Path, pool: MagicMock):
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    session_id = _seed_generate_session(store, tmp_path)

    previous_overrides = {
        get_session_store: app.dependency_overrides.get(get_session_store),
        get_file_registry: app.dependency_overrides.get(get_file_registry),
        get_worker_pool: app.dependency_overrides.get(get_worker_pool),
    }
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: pool

    try:
        client = TestClient(app, raise_server_exceptions=False)
        return client.post(
            "/api/convert/generate",
            json={
                "session_id": session_id,
                "params": {"lut_name": "test_lut"},
            },
        )
    finally:
        for dependency, previous in previous_overrides.items():
            if previous is None:
                app.dependency_overrides.pop(dependency, None)
            else:
                app.dependency_overrides[dependency] = previous
        registry.clear_all()
        store.clear_all()


def test_generate_worker_exception_uses_public_error_language(tmp_path: Path) -> None:
    private_path = "/Users/min/private/source.png"
    pool = MagicMock(spec=WorkerPoolManager)
    pool.submit = AsyncMock(
        side_effect=RuntimeError(f"cannot read {private_path}: decode failed")
    )

    response = _post_generate_with_pool(tmp_path, pool)

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "3MF generation failed. Re-run preview and try generating the model again."
    )
    assert private_path not in response.text
    assert "decode failed" not in response.text


def test_generate_missing_worker_output_uses_public_error_language(tmp_path: Path) -> None:
    private_path = "/Users/min/private/model.3mf"
    pool = MagicMock(spec=WorkerPoolManager)
    pool.submit = AsyncMock(
        return_value={
            "threemf_path": private_path,
            "glb_path": None,
            "status_msg": f"cannot write {private_path}: permission denied",
        }
    )

    response = _post_generate_with_pool(tmp_path, pool)

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "3MF generation failed. Re-run preview and try generating the model again."
    )
    assert private_path not in response.text
    assert "permission denied" not in response.text
