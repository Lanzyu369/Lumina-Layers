"""App Factory integration tests.
App Factory 集成测试，验证 Swagger UI、OpenAPI JSON 和 CORS 配置。

Tests cover:
- Swagger UI accessibility at ``/docs``
- OpenAPI JSON completeness at ``/openapi.json``
- CORS headers via preflight OPTIONS requests
- OpenAPI metadata (title, version)

_Requirements: 9.3, 9.4, 9.5_
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import pytest
from fastapi.testclient import TestClient

from api.app import create_app

# ---------------------------------------------------------------------------
# All 8 endpoint paths that must appear in the OpenAPI spec
# ---------------------------------------------------------------------------

EXPECTED_PATHS: List[str] = [
    "/api/convert/preview",
    "/api/convert/generate",
    "/api/convert/batch",
    "/api/convert/replace-color",
    "/api/convert/merge-colors",
]

# Material/LUT endpoints are part of the main development baseline again.
# 耗材/LUT 端点恢复为主应用开发基线的一部分。
MAIN_APP_MATERIAL_LUT_PREFIXES: List[str] = [
    "/api/extractor/",
    "/api/calibration/",
    "/api/five-color/",
]

MAIN_APP_SINGLE_STAGE_PATHS: List[str] = [
    "/api/extractor/gradient-card-materials",
    "/api/extractor/material-solver-cache/status",
]


@pytest.fixture()
def client() -> TestClient:
    """Create a fresh TestClient for each test.
    为每个测试创建独立的 TestClient。
    """
    return TestClient(create_app())


def test_frontend_dist_can_be_served_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Docker/local deployment can serve the built SPA from FastAPI.
    Docker/本地部署可由 FastAPI 服务已构建的前端 SPA。
    """
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text(
        '<!doctype html><script type="module" src="/assets/app.js"></script>',
        encoding="utf-8",
    )
    (assets_dir / "app.js").write_text("console.log('lumina-dist');", encoding="utf-8")
    (dist_dir / "favicon.ico").write_bytes(b"ico")
    hdr_dir = dist_dir / "hdr"
    hdr_dir.mkdir()
    (hdr_dir / "studio.hdr").write_bytes(b"hdr")

    monkeypatch.setenv("LUMINA_SERVE_FRONTEND_DIST", "1")
    monkeypatch.setenv("LUMINA_FRONTEND_DIST_DIR", str(dist_dir))

    local_client = TestClient(create_app())

    root_response = local_client.get("/")
    assert root_response.status_code == 200
    assert 'src="/assets/app.js"' in root_response.text

    route_response = local_client.get("/converter")
    assert route_response.status_code == 200
    assert 'src="/assets/app.js"' in route_response.text

    asset_response = local_client.get("/assets/app.js")
    assert asset_response.status_code == 200
    assert asset_response.text == "console.log('lumina-dist');"

    favicon_response = local_client.get("/favicon.ico")
    assert favicon_response.status_code == 200
    assert favicon_response.content == b"ico"

    nested_static_response = local_client.get("/hdr/studio.hdr")
    assert nested_static_response.status_code == 200
    assert nested_static_response.content == b"hdr"

    missing_api_response = local_client.get("/api/does-not-exist")
    assert missing_api_response.status_code == 404
    assert "lumina-dist" not in missing_api_response.text


# ===========================================================================
# Swagger UI accessibility
# ===========================================================================


class TestSwaggerUI:
    """Verify Swagger UI is accessible.
    验证 Swagger UI 可访问。
    """

    def test_docs_returns_200(self, client: TestClient) -> None:
        """GET /docs should return 200 (Swagger UI page).
        访问 /docs 应返回 200 状态码。

        _Requirements: 9.4_
        """
        resp = client.get("/docs")
        assert resp.status_code == 200


# ===========================================================================
# OpenAPI JSON completeness
# ===========================================================================


class TestOpenAPIJSON:
    """Verify OpenAPI JSON spec is complete and correct.
    验证 OpenAPI JSON 规范的完整性和正确性。
    """

    def test_openapi_json_returns_200(self, client: TestClient) -> None:
        """GET /openapi.json should return 200.
        访问 /openapi.json 应返回 200 状态码。

        _Requirements: 9.5_
        """
        resp = client.get("/openapi.json")
        assert resp.status_code == 200

    def test_openapi_json_contains_all_endpoints(self, client: TestClient) -> None:
        """OpenAPI JSON should contain all 8 registered endpoint paths.
        OpenAPI JSON 应包含所有 8 个已注册的端点路径。

        _Requirements: 9.5_
        """
        resp = client.get("/openapi.json")
        openapi: dict = resp.json()
        paths = openapi.get("paths", {})

        for expected_path in EXPECTED_PATHS:
            assert expected_path in paths, (
                f"Missing endpoint {expected_path!r} in OpenAPI paths. " f"Found: {sorted(paths.keys())}"
            )

    def test_material_lut_endpoints_present_on_main_app(self, client: TestClient) -> None:
        """Material/LUT extract/generate/query endpoints stay in the main app.
        提取/生成/查询端点恢复在主应用内暴露。
        """
        resp = client.get("/openapi.json")
        paths = resp.json().get("paths", {})
        for prefix in MAIN_APP_MATERIAL_LUT_PREFIXES:
            assert any(path.startswith(prefix) for path in paths), (
                f"Missing main-app Material/LUT endpoint prefix {prefix!r}. "
                f"Found: {sorted(paths.keys())}"
            )
        for expected_path in MAIN_APP_SINGLE_STAGE_PATHS:
            assert expected_path in paths, (
                f"Missing main-app single-stage endpoint {expected_path!r}. "
                f"Found: {sorted(paths.keys())}"
            )

    def test_openapi_json_has_correct_title(self, client: TestClient) -> None:
        """OpenAPI JSON should have title 'Lumina Studio API'.
        OpenAPI JSON 的 title 应为 'Lumina Studio API'。

        _Requirements: 9.1_
        """
        resp = client.get("/openapi.json")
        openapi: dict = resp.json()
        info = openapi.get("info", {})
        assert info.get("title") == "Lumina Studio API"

    def test_openapi_json_has_correct_version(self, client: TestClient) -> None:
        """OpenAPI JSON should have version '2.0'.
        OpenAPI JSON 的 version 应为 '2.0'。

        _Requirements: 9.1_
        """
        resp = client.get("/openapi.json")
        openapi: dict = resp.json()
        info = openapi.get("info", {})
        assert info.get("version") == "2.0"


# ===========================================================================
# CORS headers
# ===========================================================================


class TestCORSHeaders:
    """Verify CORS middleware is correctly configured.
    验证 CORS 中间件配置正确。

    _Requirements: 9.3_
    """

    def test_cors_allows_any_origin(self, client: TestClient) -> None:
        """OPTIONS preflight with an arbitrary Origin should return
        Access-Control-Allow-Origin header.
        带有任意 Origin 的 OPTIONS 预检请求应返回
        Access-Control-Allow-Origin 响应头。

        Note: Starlette CORSMiddleware with ``allow_origins=["*"]`` echoes
        back the requesting origin rather than a literal ``*``.
        """
        origin = "https://example.com"
        resp = client.options(
            "/api/convert/preview",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )
        allow_origin = resp.headers.get("access-control-allow-origin")
        assert allow_origin in ("*", origin), f"Expected '*' or '{origin}', got {allow_origin!r}"

    def test_cors_allows_all_methods(self, client: TestClient) -> None:
        """CORS preflight should indicate all HTTP methods are allowed.
        CORS 预检响应应表明允许所有 HTTP 方法。
        """
        resp = client.options(
            "/api/convert/preview",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "DELETE",
            },
        )
        allowed = resp.headers.get("access-control-allow-methods", "")
        assert "DELETE" in allowed

    def test_cors_allows_all_headers(self, client: TestClient) -> None:
        """CORS preflight requesting a custom header should be permitted.
        CORS 预检请求自定义 header 应被允许。
        """
        resp = client.options(
            "/api/extractor/extract",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-Custom-Header",
            },
        )
        allowed_headers = resp.headers.get("access-control-allow-headers", "")
        assert "X-Custom-Header" in allowed_headers or "*" in allowed_headers

    def test_cors_allows_credentials(self, client: TestClient) -> None:
        """CORS should indicate credentials are allowed.
        CORS 应表明允许携带凭证。
        """
        resp = client.options(
            "/api/calibration/generate",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-credentials") == "true"


class TestRequestIdHeader:
    """Verify request id generation/propagation contract."""

    def test_request_id_is_generated_when_missing(self, client: TestClient) -> None:
        resp = client.get("/openapi.json")
        request_id = resp.headers.get("x-request-id")
        assert request_id is not None
        assert len(request_id) >= 8

    def test_request_id_is_echoed_when_provided(self, client: TestClient) -> None:
        req_id = "test-request-id-123"
        resp = client.get("/openapi.json", headers={"X-Request-ID": req_id})
        assert resp.headers.get("x-request-id") == req_id


class TestClientLogEndpoint:
    """Verify frontend diagnostic logs are bounded before server logging."""

    def test_client_log_endpoint_sanitizes_large_payloads(
        self,
        client: TestClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        target_logger = logging.getLogger("lumina.api.app")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.DEBUG, logger=target_logger.name)

        response = client.post(
            "/api/client-log",
            json={
                "label": "x" * 300,
                "elapsed_ms": 12.34567,
                "scope": "preview",
                "phase": "request-sent",
                "details": {
                    "long": "y" * 1300,
                    **{f"k{index}": index for index in range(30)},
                },
            },
        )

        assert response.status_code == 200
        records = [
            record for record in caplog.records
            if getattr(record, "event", None) == "client_log"
        ]
        assert len(records) == 1
        assert records[0].client_label.endswith("...<truncated>")
        assert records[0].duration_ms == 12.346
        assert records[0].client_details["long"].endswith("...<truncated>")
        assert records[0].client_details["__truncated_keys"] == 7
