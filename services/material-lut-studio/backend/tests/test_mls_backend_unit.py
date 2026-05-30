"""MLS backend — router registration and thin-adapter contract tests.
MLS 后端 — 路由注册与薄适配契约测试。

These tests pin three properties of the decoupled service (Route B):

1. **Route surface.** Every management endpoint is registered under the
   ``/api/mls/...`` prefix and the session-coupled ``/session/{id}/info``
   endpoint is intentionally absent.
2. **Thin-adapter contract.** The MLS LUT / solver-cache routers delegate to
   the main app handlers rather than re-implementing logic, so a monkeypatched
   main handler is observed through the MLS route.
3. **File serving.** MLS issues ephemeral download URLs from its own
   FileRegistry and serves them without session coupling.

这些测试固定解耦服务（路线 B）的三项性质：路由面、薄适配契约、文件下载。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.dependencies import get_file_registry


def _client() -> TestClient:
    """Build a TestClient over a fresh MLS app. (基于全新 MLS 应用构建测试客户端)"""
    return TestClient(create_app())


class TestRouteSurface:
    """Pin the registered MLS route surface. (固定 MLS 路由面)"""

    def test_health_reports_data_roots(self) -> None:
        """Health returns ``ok`` plus the resolved data roots. (健康返回数据根)"""
        resp = _client().get("/api/mls/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "material-lut-studio"
        assert set(body["data_roots"]) == {"materials", "solver_cache", "lut_preset"}

    def test_management_endpoints_registered(self) -> None:
        """All management endpoints live under ``/api/mls``. (管理端点均在 /api/mls 下)"""
        paths = {route.path for route in create_app().routes}
        for expected in (
            "/api/mls/lut/list",
            "/api/mls/lut/merge",
            "/api/mls/lut/compare",
            "/api/mls/lut/{lut_name}/info",
            "/api/mls/materials",
            "/api/mls/materials/export",
            "/api/mls/materials/import",
            "/api/mls/solver-cache",
            "/api/mls/solver-cache/build",
            "/api/files/{file_id}",
        ):
            assert expected in paths, f"missing route: {expected}"

    def test_session_coupled_lut_info_runs_on_mls_session_store(self) -> None:
        """Session-scoped LUT info routes through MLS's own SessionStore.
        会话耦合的 LUT info 在 MLS 自有 SessionStore 上运行（与主 app 共用处理函数，
        但通过 dependency_overrides 切到 MLS 的会话存储）。

        Earlier this endpoint was excluded from the MLS service to avoid
        cross-process session sharing. After bringing the legacy
        ``/api/lut/...`` paths back onto MLS so the standalone frontend can
        reach them via its Vite proxy, this endpoint comes along — but
        ``app.dependency_overrides`` rewires its ``get_session_store``
        dependency to the MLS-local singleton, so it is still single-tenant.
        """
        app = create_app()
        paths = {route.path for route in app.routes}
        assert "/api/lut/session/{session_id}/info" in paths

        # The override must point the session dependency at the MLS-local
        # SessionStore, not the main app's. (会话依赖必须重定向到 MLS 进程内)
        from api.dependencies import get_session_store as main_get_session_store
        from backend.dependencies import get_session_store as mls_get_session_store
        assert app.dependency_overrides.get(main_get_session_store) is mls_get_session_store


class TestThinAdapterContract:
    """MLS routers delegate to main handlers, not re-implementations.
    MLS 路由委托主处理函数，而非重新实现。
    """

    def test_lut_list_delegates_to_main_handler(self, monkeypatch) -> None:
        """A patched main ``list_luts`` is observed via the MLS route.
        被 monkeypatch 的主 ``list_luts`` 能透过 MLS 路由观察到。
        """
        from api.routers import lut as main_lut
        from api.schemas.responses import LUTListResponse, LutInfo

        sentinel = LUTListResponse(
            luts=[LutInfo(name="__sentinel__", color_mode="BW", path="/x", fingerprint="abc")]
        )
        monkeypatch.setattr(main_lut, "list_luts", lambda: sentinel)

        resp = _client().get("/api/mls/lut/list")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["luts"]) == 1
        assert body["luts"][0]["name"] == "__sentinel__"

    def test_lut_info_not_found_propagates_404(self, monkeypatch) -> None:
        """Unknown LUT name yields the main handler's 404. (未知 LUT 透传 404)"""
        from api.routers import lut as main_lut

        monkeypatch.setattr(main_lut.LUTManager, "get_lut_path", lambda _name: None)
        resp = _client().get("/api/mls/lut/does-not-exist/info")
        assert resp.status_code == 404

    def test_solver_cache_list_delegates_to_main_handler(self, monkeypatch) -> None:
        """A patched main solver-cache list is observed via the MLS route.
        被 monkeypatch 的主求解缓存列表能透过 MLS 路由观察到。
        """
        from api.routers import single_stage as main_single_stage
        from api.schemas.responses import MaterialSolverCacheListResponse

        async def _fake_list() -> MaterialSolverCacheListResponse:
            return MaterialSolverCacheListResponse(
                status="ok", message="patched", entries=[]
            )

        monkeypatch.setattr(main_single_stage, "material_solver_cache_list", _fake_list)
        resp = _client().get("/api/mls/solver-cache")
        assert resp.status_code == 200
        assert resp.json()["message"] == "patched"


class TestFileServing:
    """MLS serves ephemeral download URLs from its own registry.
    MLS 从自有 registry 提供临时下载 URL。
    """

    def test_unknown_file_id_returns_404(self) -> None:
        """Unknown file id returns 404. (未知 file_id 返回 404)"""
        resp = _client().get("/api/files/nonexistent-id")
        assert resp.status_code == 404

    def test_registered_file_is_served(self, tmp_path) -> None:
        """A registered file resolves and downloads with HTTP 200. (已注册文件可下载)"""
        target = tmp_path / "sample.json"
        target.write_text('{"ok": true}', encoding="utf-8")
        registry = get_file_registry()
        file_id = registry.register_path("mls-test", str(target), ttl_seconds=600)

        resp = _client().get(f"/api/files/{file_id}")
        assert resp.status_code == 200
