"""Tests for source-color picking from the converter preview cache."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.dependencies import get_session_store
from api.preview_cache_artifacts import externalize_preview_cache
from api.session_store import SessionStore


@pytest.fixture()
def client_with_store() -> Iterator[tuple[TestClient, SessionStore]]:
    app = create_app()
    store = SessionStore(ttl=1800)
    app.dependency_overrides[get_session_store] = lambda: store
    client = TestClient(app)
    try:
        yield client, store
    finally:
        app.dependency_overrides.clear()


def _seed_preview_session(
    store: SessionStore,
    *,
    include_quantized: bool = True,
    include_mask: bool = True,
) -> str:
    sid = store.create()
    original = np.zeros((3, 3, 3), dtype=np.uint8)
    original[:, :] = [255, 0, 0]

    replaced = original.copy()
    replaced[1, 1] = [0, 0, 255]

    quantized = np.zeros((3, 3, 3), dtype=np.uint8)
    quantized[:, :] = [240, 8, 8]

    mask_solid = np.ones((3, 3), dtype=bool)

    cache: dict[str, np.ndarray] = {"matched_rgb": replaced}
    if include_quantized:
        cache["quantized_image"] = quantized
    if include_mask:
        cache["mask_solid"] = mask_solid

    store.put(sid, "preview_cache", cache)
    store.put(sid, "original_matched_rgb", original)
    return sid


def _seed_artifact_preview_session(store: SessionStore, tmp_path) -> str:
    sid = store.create()
    original = np.zeros((3, 3, 3), dtype=np.uint8)
    original[:, :] = [255, 0, 0]
    replaced = original.copy()
    replaced[1, 1] = [0, 0, 255]
    quantized = np.zeros((3, 3, 3), dtype=np.uint8)
    quantized[:, :] = [240, 8, 8]
    cache = {
        "matched_rgb": replaced,
        "original_matched_rgb": original,
        "quantized_image": quantized,
        "mask_solid": np.ones((3, 3), dtype=bool),
    }
    ref = externalize_preview_cache(sid, store, cache, root_dir=tmp_path)
    store.put(sid, "preview_cache", ref)
    return sid


def test_source_color_pick_returns_original_source_color_after_replacement(
    client_with_store: tuple[TestClient, SessionStore],
) -> None:
    client, store = client_with_store
    sid = _seed_preview_session(store)

    response = client.post(
        "/api/convert/source-color-pick",
        json={"session_id": sid, "x": 1, "y": 1},
    )

    assert response.status_code == 200
    assert response.json() == {
        "source_matched_hex": "#ff0000",
        "quantized_hex": "#f00808",
    }


def test_source_color_pick_reads_original_from_artifact_cache(
    client_with_store: tuple[TestClient, SessionStore],
    tmp_path,
) -> None:
    client, store = client_with_store
    sid = _seed_artifact_preview_session(store, tmp_path)

    from unittest.mock import patch

    with patch(
        "api.routers.converter.common.hydrate_preview_cache",
        side_effect=AssertionError("source-color-pick must not fully hydrate artifact cache"),
    ):
        response = client.post(
            "/api/convert/source-color-pick",
            json={"session_id": sid, "x": 1, "y": 1},
        )

    assert response.status_code == 200
    assert response.json() == {
        "source_matched_hex": "#ff0000",
        "quantized_hex": "#f00808",
    }


def test_source_color_pick_rejects_background_click(
    client_with_store: tuple[TestClient, SessionStore],
) -> None:
    client, store = client_with_store
    sid = _seed_preview_session(store)
    data = store.get(sid)
    data["preview_cache"]["mask_solid"][1, 1] = False

    response = client.post(
        "/api/convert/source-color-pick",
        json={"session_id": sid, "x": 1, "y": 1},
    )

    assert response.status_code == 400
    assert "background" in response.json()["detail"].lower()


def test_source_color_pick_unknown_session_returns_404(
    client_with_store: tuple[TestClient, SessionStore],
) -> None:
    client, _store = client_with_store

    response = client.post(
        "/api/convert/source-color-pick",
        json={"session_id": "missing", "x": 0, "y": 0},
    )

    assert response.status_code == 404


def test_source_color_pick_missing_cache_returns_409(
    client_with_store: tuple[TestClient, SessionStore],
) -> None:
    client, store = client_with_store
    sid = _seed_preview_session(store, include_quantized=False)

    response = client.post(
        "/api/convert/source-color-pick",
        json={"session_id": sid, "x": 1, "y": 1},
    )

    assert response.status_code == 409
