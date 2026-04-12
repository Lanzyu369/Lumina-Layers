"""Unit tests for the Five-Color Query API endpoints.
五色组合查询 API 端点的单元测试。

Tests cover:
- NPZ file loading returns correct base colors (Req 1.2)
- NPY file loading returns correct base colors (Req 1.3)
- Non-existent LUT returns 404 (Req 1.4)
- Successful query returns correct result (Req 2.1)
- Query with no match returns found=false (Req 2.4)
- Swatch generation derives canonical LUT metadata server-side
- Swatch generation isolates file registry sessions per request
"""

from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from types import SimpleNamespace

from api.app import create_app
from api.dependencies import get_file_registry
from api.routers.five_color import _engine_cache

client = TestClient(create_app())


@pytest.fixture(autouse=True)
def _clear_engine_cache():
    """Clear the five-color engine cache before each test."""
    _engine_cache.clear()
    yield
    _engine_cache.clear()

# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

def _make_npz_data():
    """Create synthetic NPZ-style stack_lut and rgb_data arrays."""
    stack_lut = np.array(
        [[0, 1, 2, 3, 4], [1, 2, 3, 4, 0], [0, 0, 0, 0, 0]],
        dtype=np.int64,
    )
    rgb_data = np.array(
        [[255, 128, 64], [100, 200, 50], [10, 20, 30]],
        dtype=np.int64,
    )
    return stack_lut, rgb_data


class _FakeSwatchEngine:
    """Test double exposing canonical LUT metadata for swatch generation."""

    def __init__(self) -> None:
        self.color_count = 6
        self._base_colors = [
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (255, 255, 0),
            (255, 0, 255),
            (0, 255, 255),
        ]
        self._color_names = ["Red", "Green", "Blue", "Yellow", "Magenta", "Cyan"]
        self._query_results = {
            (0, 1, 2, 3, 4): SimpleNamespace(
                found=True,
                selected_indices=[0, 1, 2, 3, 4],
                result_rgb=(1, 2, 3),
                row_index=0,
                message="ok",
                source="",
            )
        }

    def get_base_colors(self):
        return self._base_colors

    def get_color_names(self):
        return self._color_names

    def query(self, selected_indices):
        return self._query_results.get(
            tuple(selected_indices),
            SimpleNamespace(
                found=False,
                selected_indices=list(selected_indices),
                result_rgb=None,
                row_index=-1,
                message="missing",
                source="",
            ),
        )


class _FakeRegistry:
    """Capture registry writes without touching disk."""

    def __init__(self) -> None:
        self.path_calls: list[dict[str, str | None]] = []
        self.bytes_calls: list[dict[str, str | None]] = []
        self._counter = 0

    def register_path(
        self,
        session_id: str,
        path: str,
        filename: str | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        self.path_calls.append(
            {
                "session_id": session_id,
                "path": path,
                "filename": filename,
                "ttl_seconds": None if ttl_seconds is None else str(ttl_seconds),
            }
        )
        self._counter += 1
        return f"path-{self._counter}"

    def register_bytes(
        self,
        session_id: str,
        data: bytes,
        filename: str,
        ttl_seconds: int | None = None,
    ) -> str:
        self.bytes_calls.append(
            {
                "session_id": session_id,
                "filename": filename,
                "ttl_seconds": None if ttl_seconds is None else str(ttl_seconds),
            }
        )
        self._counter += 1
        return f"bytes-{self._counter}"


# ---------------------------------------------------------------------------
# GET /api/five-color/base-colors
# ---------------------------------------------------------------------------

def test_get_base_colors_npz():
    """NPZ file loading returns correct base colors."""
    stack_lut, rgb_data = _make_npz_data()

    with (
        patch(
            "api.routers.five_color.LUTManager.get_lut_path",
            return_value="/fake/path/test.npz",
        ),
        patch(
            "api.routers.five_color.StackLUTLoader.load_npz_file",
            return_value=(True, "ok", stack_lut, rgb_data),
        ),
    ):
        resp = client.get("/api/five-color/base-colors", params={"lut_name": "test_lut"})

    assert resp.status_code == 200
    body = resp.json()
    # ColorQueryEngine infers color_count from max(stack_lut)+1 = 5
    assert body["color_count"] == 5
    assert len(body["colors"]) == 5

    first = body["colors"][0]
    assert first["index"] == 0
    assert first["rgb"] == [255, 128, 64]
    assert first["hex"] == "#FF8040"


def test_get_base_colors_npy():
    """NPY file loading returns correct base colors."""
    rgb_data = np.array(
        [[200, 50, 50], [50, 200, 50], [50, 50, 200], [240, 240, 240]] * 256,
        dtype=np.uint8,
    )  # 1024 rows → detected as 4-color

    with (
        patch(
            "api.routers.five_color.LUTManager.get_lut_path",
            return_value="/fake/path/test.npy",
        ),
        patch(
            "api.routers.five_color.StackLUTLoader.load_lut_rgb",
            return_value=(True, "ok", rgb_data),
        ),
        patch(
            "api.routers.five_color.ColorCountDetector.detect_color_count",
            return_value=(4, 1024),
        ),
        patch(
            "api.routers.five_color.StackFileManager.find_stack_file",
            return_value=None,
        ),
    ):
        resp = client.get("/api/five-color/base-colors", params={"lut_name": "test_lut"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["color_count"] == 4
    assert len(body["colors"]) == 4


def test_get_base_colors_not_found():
    """Non-existent LUT returns 404."""
    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=None,
    ):
        resp = client.get("/api/five-color/base-colors", params={"lut_name": "nonexistent"})

    assert resp.status_code == 404
    assert "LUT not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/five-color/query
# ---------------------------------------------------------------------------

def test_query_success():
    """Successful query returns correct RGB and hex."""
    stack_lut, rgb_data = _make_npz_data()

    with (
        patch(
            "api.routers.five_color.LUTManager.get_lut_path",
            return_value="/fake/path/test.npz",
        ),
        patch(
            "api.routers.five_color.StackLUTLoader.load_npz_file",
            return_value=(True, "ok", stack_lut, rgb_data),
        ),
    ):
        resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "test_lut", "selected_indices": [0, 1, 2, 3, 4]},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["result_rgb"] == [255, 128, 64]
    assert body["result_hex"] == "#FF8040"


def test_query_no_match():
    """Query with non-matching indices returns found=false."""
    stack_lut, rgb_data = _make_npz_data()

    with (
        patch(
            "api.routers.five_color.LUTManager.get_lut_path",
            return_value="/fake/path/test.npz",
        ),
        patch(
            "api.routers.five_color.StackLUTLoader.load_npz_file",
            return_value=(True, "ok", stack_lut, rgb_data),
        ),
    ):
        resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "test_lut", "selected_indices": [4, 4, 4, 4, 4]},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False


# ---------------------------------------------------------------------------
# POST /api/five-color/generate-swatch
# ---------------------------------------------------------------------------

def test_generate_swatch_uses_canonical_lut_metadata_instead_of_client_payload():
    """Swatch generation must derive base color metadata and result hex from the LUT."""
    engine = _FakeSwatchEngine()
    captured: dict[str, object] = {}

    def _fake_generate_recipe_swatch(*, recipes, **kwargs):
        captured["recipes"] = recipes
        captured["kwargs"] = kwargs
        return ("E:/tmp/generated_swatch.3mf", None, "ok")

    with (
        patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")),
        patch(
            "core.recipe_swatch.generate_recipe_swatch",
            side_effect=_fake_generate_recipe_swatch,
        ),
    ):
        resp = client.post(
            "/api/five-color/generate-swatch",
            json={
                "lut_name": "test_lut",
                "recipes": [
                    {
                        "selected_indices": [0, 1, 2, 3, 4],
                        "result_hex": "#123456",
                        "base_color_names": ["tampered"] * 6,
                        "base_color_hexes": ["#000000"] * 6,
                    }
                ],
            },
        )

    assert resp.status_code == 200
    swatch_item = captured["recipes"][0]
    assert swatch_item.selected_indices == [0, 1, 2, 3, 4]
    assert swatch_item.result_hex == "#010203"
    assert swatch_item.base_color_names == ["Red", "Green", "Blue", "Yellow", "Magenta", "Cyan"]
    assert swatch_item.base_color_hexes == [
        "#FF0000",
        "#00FF00",
        "#0000FF",
        "#FFFF00",
        "#FF00FF",
        "#00FFFF",
    ]


def test_generate_swatch_rejects_selected_indices_out_of_range():
    """Swatch generation should reject recipe indices outside the LUT range."""
    engine = _FakeSwatchEngine()

    with (
        patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")),
        patch("core.recipe_swatch.generate_recipe_swatch") as generate_mock,
    ):
        resp = client.post(
            "/api/five-color/generate-swatch",
            json={
                "lut_name": "test_lut",
                "recipes": [
                    {
                        "selected_indices": [0, 1, 2, 3, 6],
                        "result_hex": "#123456",
                        "base_color_names": ["ignored"] * 6,
                        "base_color_hexes": ["#000000"] * 6,
                    }
                ],
            },
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Index 6 out of range [0, 6)"
    generate_mock.assert_not_called()


def test_generate_swatch_rejects_recipe_without_matching_lut_result():
    """Swatch generation should reject recipes not found in the LUT."""
    engine = _FakeSwatchEngine()

    with (
        patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")),
        patch("core.recipe_swatch.generate_recipe_swatch") as generate_mock,
    ):
        resp = client.post(
            "/api/five-color/generate-swatch",
            json={
                "lut_name": "test_lut",
                "recipes": [
                    {
                        "selected_indices": [4, 4, 4, 4, 4],
                        "result_hex": "#ABCDEF",
                        "base_color_names": ["ignored"] * 6,
                        "base_color_hexes": ["#000000"] * 6,
                    }
                ],
            },
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "No LUT match for selected indices: [4, 4, 4, 4, 4]"
    generate_mock.assert_not_called()


def test_generate_swatch_uses_request_scoped_registry_session_id():
    """Swatch output registrations must be isolated per request lifecycle."""
    engine = _FakeSwatchEngine()
    fake_registry = _FakeRegistry()

    def _fake_generate_recipe_swatch(*, recipes, **kwargs):
        return (
            "E:/tmp/generated_swatch.3mf",
            Image.new("RGB", (1, 1), (255, 255, 255)),
            "ok",
        )

    client.app.dependency_overrides[get_file_registry] = lambda: fake_registry
    try:
        with (
            patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")),
            patch(
                "core.recipe_swatch.generate_recipe_swatch",
                side_effect=_fake_generate_recipe_swatch,
            ),
            patch("api.file_bridge.pil_to_png_bytes", return_value=b"png-bytes"),
        ):
            request_body = {
                "lut_name": "test_lut",
                "recipes": [
                    {
                        "selected_indices": [0, 1, 2, 3, 4],
                        "result_hex": "#123456",
                        "base_color_names": ["ignored"] * 6,
                        "base_color_hexes": ["#000000"] * 6,
                    }
                ],
            }
            resp_one = client.post(
                "/api/five-color/generate-swatch",
                headers={"X-Request-ID": "req-one"},
                json=request_body,
            )
            resp_two = client.post(
                "/api/five-color/generate-swatch",
                headers={"X-Request-ID": "req-two"},
                json=request_body,
            )
    finally:
        client.app.dependency_overrides.clear()

    assert resp_one.status_code == 200
    assert resp_two.status_code == 200
    path_session_ids = [call["session_id"] for call in fake_registry.path_calls]
    bytes_session_ids = [call["session_id"] for call in fake_registry.bytes_calls]
    assert len(set(path_session_ids)) == 2
    assert len(set(bytes_session_ids)) == 2
    assert path_session_ids[0].startswith("recipe-swatch:req-one:")
    assert path_session_ids[1].startswith("recipe-swatch:req-two:")
    assert bytes_session_ids[0].startswith("recipe-swatch:req-one:")
    assert bytes_session_ids[1].startswith("recipe-swatch:req-two:")


def test_generate_swatch_registry_session_id_is_unique_even_with_same_request_id():
    """Swatch registry session ids must not collide when the same request header is reused."""
    engine = _FakeSwatchEngine()
    fake_registry = _FakeRegistry()

    def _fake_generate_recipe_swatch(*, recipes, **kwargs):
        return (
            "E:/tmp/generated_swatch.3mf",
            Image.new("RGB", (1, 1), (255, 255, 255)),
            "ok",
        )

    client.app.dependency_overrides[get_file_registry] = lambda: fake_registry
    try:
        with (
            patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")),
            patch(
                "core.recipe_swatch.generate_recipe_swatch",
                side_effect=_fake_generate_recipe_swatch,
            ),
            patch("api.file_bridge.pil_to_png_bytes", return_value=b"png-bytes"),
        ):
            request_body = {
                "lut_name": "test_lut",
                "recipes": [
                    {
                        "selected_indices": [0, 1, 2, 3, 4],
                        "result_hex": "#123456",
                        "base_color_names": ["ignored"] * 6,
                        "base_color_hexes": ["#000000"] * 6,
                    }
                ],
            }
            resp_one = client.post(
                "/api/five-color/generate-swatch",
                headers={"X-Request-ID": "req-repeat"},
                json=request_body,
            )
            resp_two = client.post(
                "/api/five-color/generate-swatch",
                headers={"X-Request-ID": "req-repeat"},
                json=request_body,
            )
    finally:
        client.app.dependency_overrides.clear()

    assert resp_one.status_code == 200
    assert resp_two.status_code == 200
    path_session_ids = [call["session_id"] for call in fake_registry.path_calls]
    bytes_session_ids = [call["session_id"] for call in fake_registry.bytes_calls]
    assert len(set(path_session_ids)) == 2
    assert len(set(bytes_session_ids)) == 2
    assert all(session_id.startswith("recipe-swatch:req-repeat:") for session_id in path_session_ids)
    assert all(session_id.startswith("recipe-swatch:req-repeat:") for session_id in bytes_session_ids)
