"""MLS write-auth — gating, status, verify, and middleware tests.
MLS 写入鉴权 — 门禁、状态、校验与中间件测试。

These tests pin five properties of the read-only-by-default service:

1. **Open mode by default.** With no password configured, both ``status``
   and ``verify`` report ``write_enabled=true`` and write requests pass.
2. **Status reflects header.** With a password configured, ``status`` is
   ``write_enabled=false`` without the header, ``true`` with the right one,
   and still ``false`` with a wrong header.
3. **Verify validates the candidate.** ``verify`` returns ``ok=true`` only
   for a matching ``X-MLS-Password`` header.
4. **Mutating endpoints gated.** Without the header, ``DELETE``/``PATCH`` /
   ``POST`` operations on the write allowlist return ``401`` with a
   structured body.
5. **Read endpoints stay open.** ``GET /api/mls/materials`` and the
   public auth endpoints succeed even in protected mode.

这些测试固定五项性质：默认开放、状态反映请求头、verify 校验候选密码、写端点被门禁、
读端点始终开放。
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend import auth as auth_module


def _client() -> TestClient:
    """Build a TestClient over a fresh MLS app. (基于全新 MLS 应用构建测试客户端)"""
    return TestClient(create_app())


@pytest.fixture
def open_mode(monkeypatch) -> Iterator[None]:
    """Force the auth state into "no password configured" for the test.
    将鉴权状态强制设为"未配置密码"。
    """
    state = auth_module.get_auth_state()
    monkeypatch.setattr(state, "_password", None, raising=False)
    monkeypatch.setattr(state, "_loaded", True, raising=False)
    yield


@pytest.fixture
def protected_mode(monkeypatch) -> Iterator[str]:
    """Force the auth state into "password configured" with a fixed value.
    将鉴权状态强制设为"已配置固定密码"。
    """
    state = auth_module.get_auth_state()
    monkeypatch.setattr(state, "_password", "lumina-mls-pw", raising=False)
    monkeypatch.setattr(state, "_loaded", True, raising=False)
    yield "lumina-mls-pw"


class TestOpenMode:
    """When no password is configured, MLS is fully open.
    未配置密码时 MLS 完全开放。
    """

    def test_status_reports_open(self, open_mode) -> None:
        """``status`` shows password_required=False and write_enabled=True.
        状态显示无需密码且已启用写入。
        """
        resp = _client().get("/api/mls/auth/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["password_required"] is False
        assert body["write_enabled"] is True

    def test_verify_always_ok(self, open_mode) -> None:
        """``verify`` returns ok=True regardless of the supplied header.
        verify 无论请求头如何均返回 ok=True。
        """
        client = _client()
        resp1 = client.post("/api/mls/auth/verify")
        resp2 = client.post(
            "/api/mls/auth/verify", headers={"X-MLS-Password": "anything"}
        )
        assert resp1.status_code == 200 and resp1.json()["ok"] is True
        assert resp2.status_code == 200 and resp2.json()["ok"] is True


class TestProtectedMode:
    """When a password is configured, mutating endpoints are gated.
    配置密码时写端点被门禁拦截。
    """

    def test_status_without_header_is_read_only(self, protected_mode) -> None:
        """No header -> password_required=True and write_enabled=False.
        无请求头 -> 需要密码且当前未启用写入。
        """
        resp = _client().get("/api/mls/auth/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["password_required"] is True
        assert body["write_enabled"] is False

    def test_status_with_correct_header_unlocks(self, protected_mode) -> None:
        """Correct ``X-MLS-Password`` flips ``write_enabled`` to True.
        正确密码使 write_enabled 变为 True。
        """
        resp = _client().get(
            "/api/mls/auth/status", headers={"X-MLS-Password": protected_mode}
        )
        assert resp.json()["write_enabled"] is True

    def test_status_with_wrong_header_stays_locked(self, protected_mode) -> None:
        """Wrong ``X-MLS-Password`` keeps ``write_enabled`` False.
        错误密码 write_enabled 仍为 False。
        """
        resp = _client().get(
            "/api/mls/auth/status", headers={"X-MLS-Password": "wrong"}
        )
        assert resp.json()["write_enabled"] is False

    def test_verify_validates_candidate(self, protected_mode) -> None:
        """``verify`` returns ok=True only for the correct password.
        verify 仅在密码正确时 ok=True。
        """
        client = _client()
        ok_resp = client.post(
            "/api/mls/auth/verify", headers={"X-MLS-Password": protected_mode}
        )
        bad_resp = client.post(
            "/api/mls/auth/verify", headers={"X-MLS-Password": "wrong"}
        )
        no_hdr_resp = client.post("/api/mls/auth/verify")
        assert ok_resp.status_code == 200 and ok_resp.json()["ok"] is True
        assert bad_resp.status_code == 200 and bad_resp.json()["ok"] is False
        assert no_hdr_resp.status_code == 200 and no_hdr_resp.json()["ok"] is False

    def test_mutating_endpoint_blocked_without_header(self, protected_mode) -> None:
        """A DELETE on the write allowlist returns 401 without the header.
        无密码请求头时白名单 DELETE 返回 401。
        """
        resp = _client().delete("/api/mls/materials/some-fake-name")
        assert resp.status_code == 401
        body = resp.json()
        assert body.get("error_code") == "mls_write_password_required"

    def test_mutating_endpoint_blocked_with_wrong_header(self, protected_mode) -> None:
        """Wrong ``X-MLS-Password`` still returns 401 on writes.
        错误密码写请求仍返回 401。
        """
        resp = _client().delete(
            "/api/mls/materials/some-fake-name",
            headers={"X-MLS-Password": "wrong"},
        )
        assert resp.status_code == 401

    def test_mutating_endpoint_passes_with_correct_header(self, protected_mode) -> None:
        """Correct header lets the write request through to the handler.
        正确密码使写请求通过中间件，进入处理函数。
        """
        # The target material does not exist, so the handler will return 404
        # (not 401). The point is that the auth middleware did not short-circuit.
        # 目标耗材不存在，处理函数返回 404；证明中间件未短路。
        resp = _client().delete(
            "/api/mls/materials/some-fake-name",
            headers={"X-MLS-Password": protected_mode},
        )
        assert resp.status_code != 401

    def test_read_endpoint_stays_open(self, protected_mode) -> None:
        """``GET /api/mls/materials`` is reachable without a password.
        ``GET /api/mls/materials`` 在无密码时也可访问。
        """
        resp = _client().get("/api/mls/materials")
        # The endpoint responds successfully (or with a 5xx if storage isn't
        # available), but not with 401: read paths are never gated.
        # 端点返回 200 或 5xx，绝不是 401：读路径从不被门禁拦截。
        assert resp.status_code != 401


class TestWriteOperationDetection:
    """Direct tests for :func:`is_write_protected_request`.
    直接测试 :func:`is_write_protected_request`。
    """

    def test_get_is_never_protected(self) -> None:
        """All GET requests are read-only. (所有 GET 均为只读)"""
        assert auth_module.is_write_protected_request("GET", "/api/mls/materials") is False
        assert auth_module.is_write_protected_request("GET", "/api/mls/lut/list") is False

    def test_options_is_never_protected(self) -> None:
        """Preflight is never gated. (预检请求不门禁)"""
        assert auth_module.is_write_protected_request("OPTIONS", "/api/mls/materials") is False

    def test_known_writes_are_protected(self) -> None:
        """Allowlisted writes are protected. (白名单写操作被保护)"""
        assert auth_module.is_write_protected_request("DELETE", "/api/mls/materials/red") is True
        assert auth_module.is_write_protected_request("POST", "/api/mls/materials/import") is True
        assert auth_module.is_write_protected_request("PATCH", "/api/mls/materials/x/y") is True

    def test_unknown_post_is_treated_as_read(self) -> None:
        """Endpoints outside the write allowlist are treated as reads.
        白名单外的端点视为读操作。
        """
        # ``status`` is a read-only POST that lists cache state for given
        # materials; correctly classified as read so it works in read-only mode.
        # ``status`` 是只读 POST，正确分类为读以便在只读模式下可用。
        assert (
            auth_module.is_write_protected_request(
                "POST", "/api/extractor/material-solver-cache/status"
            )
            is False
        )

    def test_sibling_prefix_does_not_match_an_exact_path_entry(self) -> None:
        """A path that *starts with* an exact-write entry but isn't it stays read.
        以精确写端点开头但不相等的路径仍视为读，避免兄弟端点误判。

        Regression for the path-prefix sibling risk: with the older
        ``startswith`` matcher, ``POST /api/mls/lut/uploaded-something``
        would have matched ``("POST", "/api/mls/lut/upload")``. The split
        between exact paths and prefix paths (where the latter must end in
        ``/``) prevents this.
        """
        assert (
            auth_module.is_write_protected_request(
                "POST", "/api/mls/lut/uploaded-something"
            )
            is False
        )
        assert (
            auth_module.is_write_protected_request(
                "POST", "/api/mls/materials/import-status"
            )
            is False
        )

    def test_prefix_entries_match_actual_subpaths(self) -> None:
        """Prefix entries match real path-segment children, not just literal prefixes.
        前缀条目正确匹配真实的子路径段。
        """
        assert (
            auth_module.is_write_protected_request(
                "DELETE", "/api/mls/materials/brand_a/red"
            )
            is True
        )
        assert (
            auth_module.is_write_protected_request(
                "PATCH", "/api/extractor/gradient-card-materials/blue"
            )
            is True
        )
