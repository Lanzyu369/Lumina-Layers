"""Unit tests for the Material-LUT Studio HTTP client.
Material-LUT Studio HTTP 客户端的单元测试。

Verifies base-URL resolution, the enabled flag, and that management calls
issue the expected requests against a mocked transport (no live MLS needed).
"""

from __future__ import annotations

import httpx
import pytest

from api.clients.mls_client import MLSClient, get_mls_client


def _client_with_transport(handler) -> MLSClient:
    """Build an MLSClient whose internal httpx.Client uses a mock transport.
    构建一个内部 httpx.Client 使用 mock transport 的 MLSClient。
    """
    client = MLSClient(base_url="http://mls.test:8100")
    transport = httpx.MockTransport(handler)

    # Patch the client's request path by swapping httpx.Client for one bound to
    # the mock transport. We do this by overriding the private _get to inject
    # the transport-backed client.
    def _get(path: str):
        url = f"{client.base_url}{path}"
        with httpx.Client(transport=transport, timeout=5.0) as c:
            response = c.get(url)
            response.raise_for_status()
            return response.json()

    client._get = _get  # type: ignore[method-assign]
    return client


class TestConfiguration:
    """Base URL + enabled-flag resolution. (基地址与启用标志解析)"""

    def test_default_base_url(self, monkeypatch):
        monkeypatch.delenv("LUMINA_MLS_BASE_URL", raising=False)
        assert get_mls_client().base_url == "http://127.0.0.1:8100"

    def test_env_overrides_base_url(self, monkeypatch):
        monkeypatch.setenv("LUMINA_MLS_BASE_URL", "http://example.test:9000/")
        assert get_mls_client().base_url == "http://example.test:9000"

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("1", True), ("true", True), ("YES", True), ("on", True), ("0", False), ("", False)],
    )
    def test_is_enabled(self, monkeypatch, value, expected):
        monkeypatch.setenv("LUMINA_MLS_ENABLED", value)
        assert MLSClient.is_enabled() is expected

    def test_is_enabled_unset(self, monkeypatch):
        monkeypatch.delenv("LUMINA_MLS_ENABLED", raising=False)
        assert MLSClient.is_enabled() is False


class TestManagementCalls:
    """Management endpoints issue the right requests. (管理端点发出正确请求)"""

    def test_list_luts_path(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"luts": []})

        client = _client_with_transport(handler)
        result = client.list_luts()
        assert result == {"luts": []}
        assert seen["url"] == "http://mls.test:8100/api/mls/lut/list"

    def test_health_raises_on_5xx(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "down"})

        client = _client_with_transport(handler)
        with pytest.raises(httpx.HTTPStatusError):
            client.health()

    def test_list_materials_and_caches_paths(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json={"ok": True})

        client = _client_with_transport(handler)
        client.list_materials()
        client.list_solver_caches()
        assert seen == [
            "http://mls.test:8100/api/mls/materials",
            "http://mls.test:8100/api/mls/solver-cache",
        ]
