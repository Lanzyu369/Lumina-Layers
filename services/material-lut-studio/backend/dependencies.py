"""MLS backend dependency injection.
MLS 后端依赖注入。

The MLS service is a separate process from the main Lumina app, so it owns
its own :class:`FileRegistry` instance for issuing ephemeral download URLs
(material exports, archive files). It deliberately reuses the main
repository's :class:`api.file_registry.FileRegistry` class instead of
re-implementing TTL/registry semantics, keeping a single source of truth for
the download-URL contract.

MLS 服务与主 Lumina 应用是不同进程，因此自带一个 :class:`FileRegistry` 实例，
用于签发临时下载 URL（耗材导出、档案文件）。它有意复用主仓库的
:class:`api.file_registry.FileRegistry` 类，而非重新实现 TTL/注册语义，
保证下载 URL 契约只有一个事实来源。
"""

from __future__ import annotations

from . import bootstrap

bootstrap.ensure_repo_on_path()

from api.file_registry import FileRegistry  # noqa: E402
from api.session_store import SessionStore  # noqa: E402

# Process-local singleton. The MLS service is single-tenant per process, so an
# in-memory registry matches the main app's default (``LUMINA_BACKEND=memory``).
# 进程内单例。MLS 服务每进程单租户，内存版 registry 与主应用默认行为一致。
_file_registry: FileRegistry = FileRegistry()

# Process-local SessionStore for the multi-step extraction flows (single-stage
# dataset -> Stage A fit, gradient-card capture -> Stage A material). These are
# stateful tool sessions owned by MLS now that extraction lives here.
# 进程内 SessionStore，承载多步提取流程（单段数据集→Stage A 拟合、梯度卡采集→
# Stage A 耗材）。提取迁移到 MLS 后，这些有状态工具会话归 MLS 所有。
_session_store: SessionStore = SessionStore(ttl=1800)


def get_file_registry() -> FileRegistry:
    """FastAPI dependency: return the MLS-local FileRegistry singleton.
    FastAPI 依赖：返回 MLS 进程内的 FileRegistry 单例。

    Returns:
        FileRegistry: The process-local registry instance. (进程内 registry 实例)
    """
    return _file_registry


def get_session_store() -> SessionStore:
    """FastAPI dependency: return the MLS-local SessionStore singleton.
    FastAPI 依赖：返回 MLS 进程内的 SessionStore 单例。

    Returns:
        SessionStore: The process-local session store instance. (进程内会话存储实例)
    """
    return _session_store
