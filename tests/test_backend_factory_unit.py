"""Phase A4-1 backend factory contract tests.
Phase A4-1 后端工厂契约测试.

Pin three contracts after the ``LUMINA_BACKEND`` env switch lands in
``api/dependencies.py``:

1. Default (unset) and explicit ``"memory"`` yield working
   :class:`SessionStore` / :class:`FileRegistry` instances bit-equivalent
   to pre-A4 desktop behavior. Module-level singletons + ``get_*``
   factories continue to expose the same public API.
2. ``"postgres"`` raises :class:`NotImplementedError` with a pointer to
   PR A4-2 / A4-3 (the implementation PRs).
3. Any other value raises :class:`ValueError` (no silent fallback).

固定 LUMINA_BACKEND 环境开关落地后的三条契约: 默认 / memory 维持原行为,
postgres 抛 NotImplementedError 指向后续 PR, 其它值抛 ValueError.

These tests use the private ``_resolve_backend_name`` /
``_build_session_store`` / ``_build_file_registry`` helpers because the
module-level singletons are instantiated **once** at import time and
cannot be re-built without :mod:`importlib.reload`. The helpers expose
the env-dispatch logic in a per-call form that integrates cleanly with
``monkeypatch``.

测试通过私有 ``_build_*`` helper 验证 env 分发逻辑, 不重载模块.
"""

from __future__ import annotations

import pytest

import api.dependencies as deps_mod
from api.file_registry import FileRegistry
from api.session_store import SessionStore


# ─── _resolve_backend_name ────────────────────────────────────────────


class TestResolveBackendName:
    """Coverage for :func:`api.dependencies._resolve_backend_name`."""

    def test_unset_defaults_to_memory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing env var must resolve to ``"memory"``.
        环境变量未设时默认返回 ``"memory"``.
        """
        monkeypatch.delenv("LUMINA_BACKEND", raising=False)
        assert deps_mod._resolve_backend_name() == "memory"

    def test_blank_string_defaults_to_memory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Whitespace-only env var must resolve to ``"memory"``.
        空白字符串环境变量等同于未设置.
        """
        monkeypatch.setenv("LUMINA_BACKEND", "   ")
        assert deps_mod._resolve_backend_name() == "memory"

    def test_explicit_memory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit ``LUMINA_BACKEND=memory`` round-trips.
        显式 ``LUMINA_BACKEND=memory`` 原样返回.
        """
        monkeypatch.setenv("LUMINA_BACKEND", "memory")
        assert deps_mod._resolve_backend_name() == "memory"

    def test_explicit_postgres(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit ``LUMINA_BACKEND=postgres`` round-trips.
        显式 ``LUMINA_BACKEND=postgres`` 原样返回.
        """
        monkeypatch.setenv("LUMINA_BACKEND", "postgres")
        assert deps_mod._resolve_backend_name() == "postgres"

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Backend name matching must be case-insensitive.
        后端名称大小写不敏感.
        """
        monkeypatch.setenv("LUMINA_BACKEND", "POSTGRES")
        assert deps_mod._resolve_backend_name() == "postgres"

    def test_strips_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Surrounding whitespace must be stripped before validation.
        前后空白字符在校验前被剥除.
        """
        monkeypatch.setenv("LUMINA_BACKEND", "  memory  ")
        assert deps_mod._resolve_backend_name() == "memory"

    def test_invalid_value_raises_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unknown backend name must raise ``ValueError`` listing the
        accepted values, not silently fall back to the default.
        非法值必须抛 ValueError 并列出合法取值, 杜绝静默降级.
        """
        monkeypatch.setenv("LUMINA_BACKEND", "garbage")
        with pytest.raises(ValueError, match=r"LUMINA_BACKEND.*not supported"):
            deps_mod._resolve_backend_name()


# ─── _build_session_store ─────────────────────────────────────────────


class TestBuildSessionStore:
    """Coverage for :func:`api.dependencies._build_session_store`."""

    def test_memory_returns_session_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``memory`` backend must return a real :class:`SessionStore`.
        ``memory`` 后端返回真实 :class:`SessionStore` 实例.
        """
        monkeypatch.setenv("LUMINA_BACKEND", "memory")
        store = deps_mod._build_session_store()
        assert isinstance(store, SessionStore)

    def test_unset_returns_session_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unset env (the desktop default) must return a real store.
        未设环境变量 (桌面默认) 同样返回真实 store.
        """
        monkeypatch.delenv("LUMINA_BACKEND", raising=False)
        store = deps_mod._build_session_store()
        assert isinstance(store, SessionStore)

    def test_postgres_raises_not_implemented(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``postgres`` backend must raise ``NotImplementedError`` with
        a pointer to PR A4-2 (the actual implementation).
        ``postgres`` 后端抛 NotImplementedError 并指向 A4-2.
        """
        monkeypatch.setenv("LUMINA_BACKEND", "postgres")
        with pytest.raises(NotImplementedError, match=r"A4-2"):
            deps_mod._build_session_store()


# ─── _build_file_registry ─────────────────────────────────────────────


class TestBuildFileRegistry:
    """Coverage for :func:`api.dependencies._build_file_registry`."""

    def test_memory_returns_file_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``memory`` backend must return a real :class:`FileRegistry`.
        ``memory`` 后端返回真实 :class:`FileRegistry` 实例.
        """
        monkeypatch.setenv("LUMINA_BACKEND", "memory")
        registry = deps_mod._build_file_registry()
        assert isinstance(registry, FileRegistry)

    def test_unset_returns_file_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unset env (the desktop default) must return a real registry.
        未设环境变量 (桌面默认) 同样返回真实 registry.
        """
        monkeypatch.delenv("LUMINA_BACKEND", raising=False)
        registry = deps_mod._build_file_registry()
        assert isinstance(registry, FileRegistry)

    def test_postgres_raises_not_implemented(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``postgres`` backend must raise ``NotImplementedError`` with
        a pointer to PR A4-3 (the actual implementation).
        ``postgres`` 后端抛 NotImplementedError 并指向 A4-3.
        """
        monkeypatch.setenv("LUMINA_BACKEND", "postgres")
        with pytest.raises(NotImplementedError, match=r"A4-3"):
            deps_mod._build_file_registry()


# ─── Public API / module-level singletons unchanged ───────────────────


class TestExistingSingletonsSurvive:
    """Lossless-refactor guard: importing :mod:`api.dependencies` from
    pre-A4 callers must continue to expose the same singletons + factory
    functions with identical types.
    无损重构守门: A4 之前的调用路径继续可用, 类型与对象身份不变.
    """

    def test_module_singletons_alive(self) -> None:
        """``deps_mod.session_store`` and ``deps_mod.file_registry`` must
        be live instances of their respective classes.
        模块级单例存活, 类型符合.
        """
        assert isinstance(deps_mod.session_store, SessionStore)
        assert isinstance(deps_mod.file_registry, FileRegistry)

    def test_get_session_store_returns_same_singleton(self) -> None:
        """``get_session_store()`` must return the module singleton, not
        a freshly-built store (the FastAPI dependency contract).
        ``get_session_store()`` 返回的就是模块单例, 不是新建实例.
        """
        assert deps_mod.get_session_store() is deps_mod.session_store

    def test_get_file_registry_returns_same_singleton(self) -> None:
        """``get_file_registry()`` must return the module singleton.
        ``get_file_registry()`` 返回模块单例.
        """
        assert deps_mod.get_file_registry() is deps_mod.file_registry
