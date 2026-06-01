"""HTTP client for the Material-LUT Studio (MLS) service.
Material-LUT Studio (MLS) 服务的 HTTP 客户端。

The main Lumina app uses this client for **management-class** operations
against the decoupled MLS service (listing/merging/comparing LUTs, listing
materials, managing solver caches). It is intentionally NOT used on the
converter hot path — see :mod:`core.material_lut_provider` for the
prefetch + local-cache boundary that hot-path code uses instead.

主 Lumina 应用用此客户端对解耦后的 MLS 服务执行**管理类**操作（列出/合并/
对比 LUT、列出耗材、管理求解缓存）。它有意不用于转换热路径——热路径改用
:mod:`core.material_lut_provider` 的预取+本地缓存边界。

Configuration (配置):
    LUMINA_MLS_BASE_URL: Base URL of the MLS service. (MLS 服务基地址)
        Defaults to ``http://127.0.0.1:8100``.
    LUMINA_MLS_ENABLED: ``"1"``/``"true"`` to route management calls to MLS.
        When unset/false the client reports itself disabled so callers can
        fall back to in-process handlers during the migration window.
        （是否启用 MLS 路由；迁移期未启用时调用方回退进程内处理）
    LUMINA_MLS_TIMEOUT_SECONDS: Per-request timeout. (单请求超时，默认 30s)
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from api.structured_logging import get_logger

log = get_logger(__name__)

_DEFAULT_BASE_URL = "http://127.0.0.1:8100"
_DEFAULT_TIMEOUT_SECONDS = 30.0


def _truthy(value: str | None) -> bool:
    """Return ``True`` for common truthy string spellings.
    将常见的真值字符串拼写解析为 ``True``。
    """
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class MLSClient:
    """Thin HTTP client over the MLS management API.
    MLS 管理 API 之上的薄 HTTP 客户端。

    Args:
        base_url: Override the service base URL. (覆盖服务基地址)
        timeout_seconds: Override the per-request timeout. (覆盖单请求超时)
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._base_url = (base_url or os.environ.get("LUMINA_MLS_BASE_URL") or _DEFAULT_BASE_URL).rstrip("/")
        self._timeout = float(
            timeout_seconds
            if timeout_seconds is not None
            else os.environ.get("LUMINA_MLS_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)
        )

    @property
    def base_url(self) -> str:
        """Resolved MLS base URL. (已解析的 MLS 基地址)"""
        return self._base_url

    @staticmethod
    def is_enabled() -> bool:
        """Whether management calls should be routed to MLS.
        是否应将管理类调用路由到 MLS。

        Returns:
            bool: ``True`` when ``LUMINA_MLS_ENABLED`` is truthy. (启用标志)
        """
        return _truthy(os.environ.get("LUMINA_MLS_ENABLED"))

    def health(self) -> dict[str, Any]:
        """Fetch the MLS health snapshot.
        获取 MLS 健康快照。

        Returns:
            dict: Parsed ``/api/mls/health`` JSON payload. (健康端点 JSON)

        Raises:
            httpx.HTTPError: On transport failure or non-2xx status.
                （传输失败或非 2xx 状态时抛出）
        """
        return self._get("/api/mls/health")

    def list_luts(self) -> dict[str, Any]:
        """List available LUT presets via MLS. (经 MLS 列出 LUT 预设)"""
        return self._get("/api/mls/lut/list")

    def list_materials(self) -> dict[str, Any]:
        """List saved material archives via MLS. (经 MLS 列出耗材档案)"""
        return self._get("/api/mls/materials")

    def list_solver_caches(self) -> dict[str, Any]:
        """List persisted solver caches via MLS. (经 MLS 列出求解缓存)"""
        return self._get("/api/mls/solver-cache")

    # ------------------------------------------------------------------
    # Converter data API (hot path) — 转换器数据 API（热路径）
    # ------------------------------------------------------------------

    def get_material_params(self, directory_names: list[str]) -> dict[str, Any]:
        """Fetch Beer-Lambert params for a palette (JSON, small payload).
        获取调色板的 Beer-Lambert 参数（JSON，小载荷）。

        Args:
            directory_names: Material directory names in order. (按序的耗材目录名)

        Returns:
            dict: Parsed ``/api/mls/data/material-params`` payload. (耗材参数载荷)
        """
        url = f"{self._base_url}/api/mls/data/material-params"
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(url, json={"directory_names": list(directory_names)})
            response.raise_for_status()
            return response.json()

    def get_lut_fingerprint(self, name: str) -> dict[str, Any]:
        """Fetch a LUT's content fingerprint + suffix. (获取 LUT 指纹与后缀)"""
        url = f"{self._base_url}/api/mls/data/lut-fingerprint"
        with httpx.Client(timeout=self._timeout) as client:
            response = client.get(url, params={"name": name})
            response.raise_for_status()
            return response.json()

    def download_lut_file(self, name: str, dest_path: str) -> None:
        """Stream the raw LUT file to ``dest_path``.
        将原始 LUT 文件流式下载到 ``dest_path``。

        Args:
            name: LUT display name. (LUT 显示名称)
            dest_path: Local path to write the bytes to. (本地写入路径)

        Raises:
            httpx.HTTPError: On transport failure or non-2xx status.
        """
        url = f"{self._base_url}/api/mls/data/lut-file"
        with httpx.Client(timeout=self._timeout) as client:
            with client.stream("GET", url, params={"name": name}) as response:
                response.raise_for_status()
                with open(dest_path, "wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)

    def download_solver_cache_file(
        self,
        directory_names: list[str],
        layer_count: int,
        layer_height_mm: float,
        substrate: str,
        grid_resolution: int,
        dest_path: str,
        which: str = "npz",
    ) -> bool:
        """Stream the persisted solver-cache file (npz or meta) to ``dest_path``.
        将持久化 solver 缓存文件（npz 或 meta）流式下载到 ``dest_path``。

        Args:
            which: ``"npz"`` for the array payload or ``"meta"`` for the
                ``.meta.json`` sidecar. (取数组载荷或 meta 边车)

        Returns:
            bool: ``True`` if a file existed and was written; ``False`` on 404.
                （存在并写入返回 True；404 返回 False）

        Raises:
            httpx.HTTPError: On transport failure or non-404 error status.
        """
        url = f"{self._base_url}/api/mls/data/solver-cache-file"
        params = {
            "directory_names": list(directory_names),
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "substrate": substrate,
            "grid_resolution": grid_resolution,
            "which": which,
        }
        with httpx.Client(timeout=self._timeout) as client:
            with client.stream("GET", url, params=params) as response:
                if response.status_code == 404:
                    response.close()
                    return False
                response.raise_for_status()
                with open(dest_path, "wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
        return True

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        with httpx.Client(timeout=self._timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()


def get_mls_client() -> MLSClient:
    """Construct an :class:`MLSClient` from the current environment.
    根据当前环境变量构造 :class:`MLSClient`。

    Returns:
        MLSClient: A configured client instance. (已配置的客户端实例)
    """
    return MLSClient()
