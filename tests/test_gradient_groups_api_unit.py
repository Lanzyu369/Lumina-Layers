"""Unit tests for the gradient-groups read endpoint.

Validates:
- Missing session -> HTTP 404.
- Session without cached gradient groups -> status ``unavailable`` + empty list.
- Session with cached payload -> status ``ok`` + faithful round-trip.
- Malformed cached payload -> HTTP 500 with a structured log.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_session_store, get_file_registry
from api.file_registry import FileRegistry
from api.session_store import SessionStore


_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()


def setup_module(module):
    app.dependency_overrides[get_session_store] = lambda: _test_store
    app.dependency_overrides[get_file_registry] = lambda: _test_registry


def teardown_module(module):
    app.dependency_overrides.pop(get_session_store, None)
    app.dependency_overrides.pop(get_file_registry, None)


setup_module(None)
client: TestClient = TestClient(app)


def _sample_group_payload() -> list[dict]:
    return [
        {
            "group_index": 1,
            "total_pixel_count": 1000,
            "material_colour_count": 2,
            "material_colours": [
                {"hex": "#D2AEB4", "rgb": [210, 174, 180], "pixel_count": 600},
                {"hex": "#D0A3AC", "rgb": [208, 163, 172], "pixel_count": 400},
            ],
            "representative_hex": "#D2AEB4",
            "representative_rgb": [210, 174, 180],
            "boundary_pair_count": 1,
            "regions": [
                {
                    "region_index": 1,
                    "pixel_count": 1000,
                    "bbox": [0, 0, 40, 25],
                    "centroid": [20.0, 12.5],
                    "material_breakdown": [
                        {"hex": "#D2AEB4", "rgb": [210, 174, 180], "pixel_count": 600},
                        {"hex": "#D0A3AC", "rgb": [208, 163, 172], "pixel_count": 400},
                    ],
                }
            ],
        }
    ]


def test_unknown_session_returns_404() -> None:
    response = client.get("/api/convert/gradient-groups/does-not-exist")
    assert response.status_code == 404


def test_session_without_groups_returns_unavailable() -> None:
    sid = _test_store.create()
    try:
        response = client.get(f"/api/convert/gradient-groups/{sid}")
        assert response.status_code == 200
        body = response.json()
        assert body["session_id"] == sid
        assert body["status"] == "unavailable"
        assert body["groups"] == []
    finally:
        _test_store.close(sid)


def test_session_with_groups_returns_ok_and_roundtrips_payload() -> None:
    sid = _test_store.create()
    try:
        _test_store.put(sid, "gradient_groups", _sample_group_payload())
        response = client.get(f"/api/convert/gradient-groups/{sid}")
        assert response.status_code == 200
        body = response.json()
        assert body["session_id"] == sid
        assert body["status"] == "ok"
        assert len(body["groups"]) == 1
        g = body["groups"][0]
        assert g["group_index"] == 1
        assert g["representative_hex"] == "#D2AEB4"
        assert g["material_colour_count"] == 2
        assert len(g["regions"]) == 1
        assert g["regions"][0]["bbox"] == [0, 0, 40, 25]
        assert g["regions"][0]["centroid"] == [20.0, 12.5]
    finally:
        _test_store.close(sid)


def test_malformed_cached_payload_returns_500() -> None:
    sid = _test_store.create()
    try:
        # Missing required fields to trigger a Pydantic validation error.
        _test_store.put(
            sid,
            "gradient_groups",
            [{"group_index": 1, "total_pixel_count": "not-an-int"}],
        )
        response = client.get(f"/api/convert/gradient-groups/{sid}")
        assert response.status_code == 500
        body = response.json()
        assert "corrupted" in body.get("detail", "").lower()
    finally:
        _test_store.close(sid)
