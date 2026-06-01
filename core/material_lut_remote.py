"""Remote (MLS-backed) material/LUT data fetch with a fingerprinted cache.
基于 MLS 的远程耗材/LUT 数据获取，带指纹本地缓存。

Route B / 做法一: when the converter runs on a separate server from the
Material-LUT Studio (MLS) service, the hot path cannot read material/LUT data
from local disk. This module fetches that data over the MLS data API and
caches large artifacts (LUT files, solver-cache ``.npz``) on local disk keyed
by a content fingerprint, so a given version is downloaded at most once.

当转换器与 MLS 部署在不同服务器、无共享磁盘时，热路径无法本地读盘。本模块经
MLS 数据 API 获取数据，并把大文件（LUT、solver 缓存 ``.npz``）按内容指纹缓存到
本地磁盘，使同一版本至多下载一次。

This module is only used when ``LUMINA_MLS_ENABLED`` is truthy; otherwise the
provider reads local disk exactly as before (migration-safe default).
仅当 ``LUMINA_MLS_ENABLED`` 为真时启用；否则提供者照旧读本地磁盘（迁移期安全默认）。
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

import numpy as np

from api.clients.mls_client import MLSClient
from api.structured_logging import get_logger
from config import TEMP_DIR
from core.material_color_solver import MaterialParams

log = get_logger(__name__)

_CACHE_DIRNAME = "mls_cache"
_lut_cache_lock = threading.Lock()


def _cache_dir() -> Path:
    """Return (and create) the local cache directory for MLS artifacts.
    返回（并创建）MLS 工件的本地缓存目录。
    """
    path = Path(TEMP_DIR) / _CACHE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def fetch_materials(
    directory_names: list[str],
    *,
    client: MLSClient | None = None,
) -> list[MaterialParams]:
    """Fetch Beer-Lambert params for a palette from MLS and rebuild MaterialParams.
    从 MLS 获取调色板 Beer-Lambert 参数并重建 MaterialParams。

    Args:
        directory_names: Material directory names in order. (按序的耗材目录名)
        client: Optional injected client (tests). (可注入客户端，便于测试)

    Returns:
        list[MaterialParams]: The rebuilt material params, in the same shape
            the local loader returns. The converter's hot-path provider does
            NOT memoize remote results (the materials payload is tiny and
            ships in this same response), so a remote edit/re-import is picked
            up on the very next fetch with no extra invalidation protocol.
            （重建的耗材参数，形状与本地加载器一致。热路径提供者在远程模式下不做
            memo：载荷极小且随本响应返回，远程编辑/重导入会在下次取数即生效，
            无需额外失效协议。）

    Raises:
        RuntimeError: When MLS returns an unusable payload. (MLS 返回不可用载荷)
    """
    cli = client or MLSClient()
    payload = cli.get_material_params(list(directory_names))
    raw_items = payload.get("materials") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list) or len(raw_items) != len(directory_names):
        raise RuntimeError(
            "MLS material-params response did not match the requested palette"
        )
    materials: list[MaterialParams] = []
    for item in raw_items:
        materials.append(
            MaterialParams(
                name=str(item["name"]),
                directory_name=str(item["directory_name"]),
                E=np.asarray(item["E"], dtype=np.float64).reshape(3),
                k=np.asarray(item["k"], dtype=np.float64).reshape(3),
                C0_white=np.asarray(item["C0_white"], dtype=np.float64).reshape(3),
                estimated_rgb=np.asarray(item["estimated_rgb"], dtype=np.uint8).reshape(3),
            )
        )
    return materials


def fetch_lut_path(
    lut_name: str,
    *,
    client: MLSClient | None = None,
) -> str:
    """Resolve a LUT name to a locally-cached file path, downloading if needed.
    将 LUT 名解析为本地缓存文件路径，必要时下载。

    The local copy is keyed by the MLS content fingerprint so a new version
    (different fingerprint) is re-downloaded while an unchanged LUT is served
    from cache.

    本地副本按 MLS 内容指纹建键：版本变化（指纹不同）会重新下载，未变则命中缓存。

    Args:
        lut_name: LUT display name. (LUT 显示名称)
        client: Optional injected client. (可注入客户端)

    Returns:
        str: Absolute path to the locally-cached LUT file. (本地缓存的 LUT 文件路径)
    """
    cli = client or MLSClient()
    info = cli.get_lut_fingerprint(lut_name)
    fingerprint = str(info["fingerprint"])
    suffix = str(info.get("suffix") or "")
    key = hashlib.sha256(f"{lut_name}:{fingerprint}".encode("utf-8")).hexdigest()[:32]
    dest = _cache_dir() / f"lut_{key}{suffix}"

    with _lut_cache_lock:
        if dest.exists() and dest.stat().st_size > 0:
            return str(dest)
        tmp = dest.with_suffix(dest.suffix + ".part")
        cli.download_lut_file(lut_name, str(tmp))
        os.replace(tmp, dest)
    log.info(
        "Fetched LUT from MLS",
        extra={
            "event": "mls_lut_fetched",
            "lut_name": lut_name,
            "fingerprint": fingerprint,
            "cached_path": str(dest),
        },
    )
    return str(dest)


def fetch_solver_cache_root(
    directory_names: list[str],
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    grid_resolution: int,
    *,
    client: MLSClient | None = None,
) -> str | None:
    """Mirror the persisted solver cache from MLS into a local cache_root.
    将 MLS 上的持久化 solver 缓存镜像到本地 cache_root。

    Downloads the ``.npz`` payload and its ``.meta.json`` sidecar from MLS and
    writes them under a local ``<cache_root>/_solver_cache/`` directory using
    the canonical filenames the standard loader expects. The provider then
    loads from that root with the unchanged
    :func:`core.material_cache.load_material_solver_cache_with_fallback`, so all
    fingerprint/shape validation is reused untouched.

    从 MLS 下载 ``.npz`` 及其 ``.meta.json`` 边车，按标准加载器期望的规范文件名
    写入本地 ``<cache_root>/_solver_cache/``。提供者随后用未改动的
    ``load_material_solver_cache_with_fallback`` 从该根加载，完整复用校验逻辑。

    Args:
        directory_names: Material directory names (for the MLS query). (耗材目录名)
        materials: Loaded MaterialParams (to compute canonical filenames). (耗材参数)
        layer_count: Layers per pixel. (每像素层数)
        layer_height_mm: Layer thickness mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底)
        grid_resolution: Requested Lab grid resolution. (请求网格分辨率)
        client: Optional injected client. (可注入客户端)

    Returns:
        str | None: Local cache_root to pass to the loader, or ``None`` when
            MLS has no matching cache. (本地 cache_root；无缓存时 None)
    """
    from core.material_cache import cache_file_path, fingerprint_palette

    cli = client or MLSClient()
    palette_fingerprint = fingerprint_palette(materials)
    key_src = (
        f"{palette_fingerprint}:N{layer_count}:t{layer_height_mm}:"
        f"{substrate}:g{grid_resolution}"
    )
    key = hashlib.sha256(key_src.encode("utf-8")).hexdigest()[:32]
    cache_root = _cache_dir() / f"solver_{key}"
    solver_dir = cache_root / "_solver_cache"

    with _lut_cache_lock:
        # The canonical loader tries grid=0 (exact) first, then the requested
        # grid; mirror under the requested grid's canonical name which the
        # loader will also find via its own fallback. We write the npz the
        # server selected (exact-mode preferred) under the requested-grid name
        # so a single (root) load resolves it.
        npz_path = cache_file_path(
            materials,
            int(layer_count),
            float(layer_height_mm),
            substrate,
            grid_resolution=int(grid_resolution),
            cache_root=str(cache_root),
        )
        meta_path = npz_path.with_name(npz_path.stem + ".meta.json")
        if npz_path.exists() and meta_path.exists() and npz_path.stat().st_size > 0:
            return str(cache_root)

        solver_dir.mkdir(parents=True, exist_ok=True)
        npz_tmp = npz_path.with_suffix(".npz.part")
        found = cli.download_solver_cache_file(
            list(directory_names),
            int(layer_count),
            float(layer_height_mm),
            substrate,
            int(grid_resolution),
            str(npz_tmp),
            which="npz",
        )
        if not found:
            if npz_tmp.exists():
                try:
                    npz_tmp.unlink()
                except OSError:
                    pass
            return None
        meta_tmp = meta_path.with_suffix(".json.part")
        meta_found = cli.download_solver_cache_file(
            list(directory_names),
            int(layer_count),
            float(layer_height_mm),
            substrate,
            int(grid_resolution),
            str(meta_tmp),
            which="meta",
        )
        if not meta_found:
            for leftover in (npz_tmp, meta_tmp):
                if leftover.exists():
                    try:
                        leftover.unlink()
                    except OSError:
                        pass
            return None
        os.replace(npz_tmp, npz_path)
        os.replace(meta_tmp, meta_path)

    log.info(
        "Fetched solver cache from MLS",
        extra={
            "event": "mls_solver_cache_fetched",
            "palette_fingerprint": palette_fingerprint,
            "layer_count": int(layer_count),
            "substrate": substrate,
            "cached_root": str(cache_root),
        },
    )
    return str(cache_root)
