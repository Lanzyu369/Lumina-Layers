"""MLS — Converter data API (consumed by the main app's hot path).
MLS — 转换器数据 API（供主应用热路径消费）。

Route B / 做法一: the main converter runs on a *separate server* with no
shared disk, so it fetches the material/LUT data it needs over HTTP from MLS:

- ``GET  /api/mls/data/material-params``    — Beer-Lambert params for a palette
- ``POST /api/mls/data/material-params``     — same, for long palettes (JSON body)
- ``GET  /api/mls/data/lut-fingerprint``     — cheap content fingerprint of a LUT
- ``GET  /api/mls/data/lut-file``            — raw LUT bytes (npy/json/npz/msgpack)
- ``GET  /api/mls/data/solver-cache-file``   — raw solver-cache ``.npz`` bytes (or 404)

Material params are tiny (four length-3 vectors per material) so they ship as
JSON. LUT arrays and solver caches can be MB-scale, so they ship as raw file
bytes with a fingerprint the caller uses to cache locally and avoid refetching.

主转换器部署在**独立服务器**且不共享磁盘，因此通过 HTTP 从 MLS 取所需数据。
耗材参数很小（每种耗材四个长度 3 的向量），用 JSON 返回；LUT 数组与 solver
缓存可能是 MB 级，按原始文件字节返回，并带指纹供调用方本地缓存、避免重复拉取。
"""

from __future__ import annotations

import concurrent.futures
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .. import bootstrap

bootstrap.ensure_repo_on_path()

from api.structured_logging import get_logger  # noqa: E402
from core.material_cache import (  # noqa: E402
    DEFAULT_GRID_RESOLUTION,
    cache_file_path,
)
from core.material_lut_synthesis import load_multiple_materials  # noqa: E402
from utils.lut_manager import LUTManager  # noqa: E402

from .. import data_root  # noqa: E402

router = APIRouter(prefix="/api/mls/data", tags=["MLS Data"])
log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Process-level material cache (TTL-based)
# 进程级耗材缓存（TTL 淘汰）
#
# load_multiple_materials() reads archive files + allocates numpy arrays on
# every call.  Under concurrent requests this creates O(requests × BLAS)
# threads and accumulates unbounded memory.  A short TTL cache serves the
# hot path without ever holding stale data longer than _MATERIAL_CACHE_TTL.
# ---------------------------------------------------------------------------

_MATERIAL_CACHE_TTL: float = float(os.environ.get("MLS_MATERIAL_CACHE_TTL", "120"))
_MATERIAL_CACHE_MAX: int = 64  # evict LRU when over this many distinct keys

_material_cache: dict[tuple[str, ...], tuple[float, Any]] = {}
# Per-directory eviction epoch (not per-palette-key).  Keyed by a single
# directory_name string so evict_material_cache() works even when the palette
# key is not in _material_cache yet (cold-cache / TTL-expiry in-flight leader).
_material_epoch: dict[str, int] = {}
_material_cache_lock = threading.Lock()  # guards _material_cache and _material_epoch

# Single-flight: prevents concurrent misses for the same key from each
# triggering a separate load_multiple_materials() call (thundering herd).
# In-flight entries carry their material epoch snapshot so post-write readers
# do not join a pre-write load.


@dataclass(frozen=True)
class _InflightLoad:
    """In-flight material load plus the epoch snapshot it was started under."""

    future: concurrent.futures.Future
    epoch_snapshot: dict[str, int]


_inflight: dict[tuple[str, ...], _InflightLoad] = {}
_inflight_lock = threading.Lock()


def _snapshot_material_epochs(key: tuple[str, ...]) -> dict[str, int]:
    """Return the current per-directory epochs for *key*.

    Caller must hold ``_material_cache_lock``.
    """
    return {dn: _material_epoch.get(dn, 0) for dn in key}


def _material_epochs_match(
    key: tuple[str, ...],
    epoch_snapshot: dict[str, int],
) -> bool:
    """Return whether *key* still matches a prior epoch snapshot.

    Caller must hold ``_material_cache_lock``.
    """
    return all(_material_epoch.get(dn, 0) == epoch_snapshot[dn] for dn in key)


def _load_materials_cached(directory_names: list[str]) -> list:
    """Return MaterialParams for *directory_names*, loading from disk only on
    a cache miss or TTL expiry.  Concurrent requests for the same key share
    a single in-flight load (single-flight pattern).
    缓存命中时直接返回；未命中时只有一个 leader 真正加载，其余 waiter 等待
    同一个结果，避免并发 miss 重复分配 numpy 内存（thundering herd）。
    """
    key = tuple(directory_names)
    now = time.monotonic()

    with _material_cache_lock:
        entry = _material_cache.get(key)
        if entry is not None and now - entry[0] < _MATERIAL_CACHE_TTL:
            return entry[1]
        # Snapshot per-directory epochs before leaving the lock.  Using
        # per-directory (not per-tuple) granularity means evict_material_cache()
        # can bump the epoch even when this palette key isn't cached yet.
        epoch_snapshot = _snapshot_material_epochs(key)

    # Elect a leader for this key; waiters get the existing Future.
    with _inflight_lock:
        inflight = _inflight.get(key)
        if inflight is not None and inflight.epoch_snapshot == epoch_snapshot:
            future = inflight.future
            is_leader = False
        else:
            future = concurrent.futures.Future()
            _inflight[key] = _InflightLoad(
                future=future,
                epoch_snapshot=epoch_snapshot,
            )
            is_leader = True

    if not is_leader:
        # Blocks until leader calls set_result / set_exception; re-raises
        # any exception the leader encountered.
        return future.result()

    # Leader: load outside both locks so other keys aren't blocked.
    try:
        materials = load_multiple_materials(
            list(directory_names), materials_dir=str(data_root.materials_root())
        )
        with _material_cache_lock:
            # Skip the cache write if any constituent directory was evicted
            # while we were loading (PATCH / DELETE / import raced with us).
            if _material_epochs_match(key, epoch_snapshot):
                _material_cache[key] = (time.monotonic(), materials)
                if len(_material_cache) > _MATERIAL_CACHE_MAX:
                    oldest = min(_material_cache, key=lambda k: _material_cache[k][0])
                    _material_cache.pop(oldest, None)
        future.set_result(materials)
        return materials
    except Exception as exc:
        future.set_exception(exc)
        raise
    finally:
        with _inflight_lock:
            inflight = _inflight.get(key)
            if inflight is not None and inflight.future is future:
                _inflight.pop(key, None)


def evict_material_cache(directory_name: str) -> int:
    """Remove every cache entry whose key contains *directory_name* and bump
    the per-directory epoch so any in-flight leader for a palette that includes
    this directory discards its result — even if the key was not cached yet.
    删除包含指定目录名的缓存条目，并无条件递增该目录的 epoch，
    确保正在飞的 leader（冷缓存场景）也会放弃写入。

    Returns the number of cache entries evicted.
    """
    with _material_cache_lock:
        to_evict = [k for k in _material_cache if directory_name in k]
        for k in to_evict:
            del _material_cache[k]
        # Bump unconditionally: works whether the key is cached or not.
        _material_epoch[directory_name] = _material_epoch.get(directory_name, 0) + 1
    return len(to_evict)



# ---------------------------------------------------------------------------
# Material Beer-Lambert params
# 耗材 Beer-Lambert 参数
# ---------------------------------------------------------------------------


class MaterialParamsItem(BaseModel):
    """Serialized Beer-Lambert parameters for one material.
    单种耗材的可序列化 Beer-Lambert 参数。
    """

    name: str = Field(..., description="耗材名称")
    directory_name: str = Field(..., description="materials/ 下的目录名")
    E: list[float] = Field(..., min_length=3, max_length=3, description="平衡色 linear RGB")
    k: list[float] = Field(..., min_length=3, max_length=3, description="吸收系数")
    C0_white: list[float] = Field(..., min_length=3, max_length=3, description="白底零厚度 linear RGB")
    estimated_rgb: list[int] = Field(..., min_length=3, max_length=3, description="预览 sRGB uint8")


class MaterialParamsResponse(BaseModel):
    """Ordered Beer-Lambert params for a requested palette.
    所请求调色板的有序 Beer-Lambert 参数。
    """

    status: str = Field("ok", description="状态")
    materials: list[MaterialParamsItem] = Field(default_factory=list, description="按序的耗材参数")


class MaterialParamsRequest(BaseModel):
    """POST body for long palettes that don't fit comfortably in a query string.
    用于长调色板的 POST 请求体（避免查询串过长）。
    """

    directory_names: list[str] = Field(..., min_length=1, description="按用户顺序的耗材目录名")


def _serialize_materials(directory_names: list[str]) -> MaterialParamsResponse:
    """Load and serialize Beer-Lambert params for the given material dirs.
    加载并序列化给定耗材目录的 Beer-Lambert 参数。

    Args:
        directory_names: Material directory names in order. (按序的耗材目录名)

    Returns:
        MaterialParamsResponse: Serialized params. (序列化后的参数)

    Raises:
        HTTPException: 404 when a material is missing, 422 on invalid archives.
            （耗材缺失返回 404，档案无效返回 422）
    """
    try:
        materials = _load_materials_cached(directory_names)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    items = [
        MaterialParamsItem(
            name=mat.name,
            directory_name=mat.directory_name,
            E=[float(v) for v in mat.E.reshape(3).tolist()],
            k=[float(v) for v in mat.k.reshape(3).tolist()],
            C0_white=[float(v) for v in mat.C0_white.reshape(3).tolist()],
            estimated_rgb=[int(v) for v in mat.estimated_rgb.reshape(3).tolist()],
        )
        for mat in materials
    ]
    return MaterialParamsResponse(status="ok", materials=items)


@router.get("/material-params", response_model=MaterialParamsResponse)
def get_material_params(
    directory_names: list[str] = Query(..., description="耗材目录名（可重复）"),
) -> MaterialParamsResponse:
    """Return Beer-Lambert params for a palette (query-string form).
    返回调色板的 Beer-Lambert 参数（查询串形式）。
    """
    return _serialize_materials(list(directory_names))


@router.post("/material-params", response_model=MaterialParamsResponse)
def post_material_params(payload: MaterialParamsRequest) -> MaterialParamsResponse:
    """Return Beer-Lambert params for a palette (JSON-body form for long lists).
    返回调色板的 Beer-Lambert 参数（长列表用 JSON 体）。
    """
    return _serialize_materials(list(payload.directory_names))


# ---------------------------------------------------------------------------
# LUT raw data + fingerprint
# LUT 原始数据与指纹
# ---------------------------------------------------------------------------


def _resolve_lut_path_or_404(lut_name: str) -> str:
    """Resolve a LUT display name to an on-disk path or raise 404.
    将 LUT 显示名解析为磁盘路径，找不到则 404。
    """
    path = LUTManager.get_lut_path(lut_name)
    if path is None or not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")
    return path


class LutFingerprintResponse(BaseModel):
    """Content fingerprint + filename suffix for a named LUT.
    指定 LUT 的内容指纹与文件后缀。
    """

    status: str = Field("ok", description="状态")
    name: str = Field(..., description="LUT 显示名称")
    fingerprint: str = Field(..., description="内容指纹（缓存键）")
    suffix: str = Field(..., description="文件后缀，如 .json/.npy/.npz/.msgpack")


@router.get("/lut-fingerprint", response_model=LutFingerprintResponse)
def get_lut_fingerprint(name: str = Query(..., description="LUT 显示名称")) -> LutFingerprintResponse:
    """Return a LUT's content fingerprint so callers can cache by version.
    返回 LUT 的内容指纹，供调用方按版本缓存。
    """
    path = _resolve_lut_path_or_404(name)
    try:
        fingerprint = LUTManager.compute_fingerprint(path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fingerprint LUT: {exc}") from exc
    return LutFingerprintResponse(
        status="ok",
        name=name,
        fingerprint=fingerprint,
        suffix=Path(path).suffix.lower(),
    )


@router.get("/lut-file")
def get_lut_file(name: str = Query(..., description="LUT 显示名称")) -> FileResponse:
    """Stream the raw LUT file bytes for a named LUT.
    流式返回指定 LUT 的原始文件字节。

    The caller is expected to fingerprint first (``/lut-fingerprint``) and skip
    this fetch when its local cache already holds the same fingerprint.
    调用方应先取指纹，本地缓存命中同一指纹时跳过本次拉取。
    """
    path = _resolve_lut_path_or_404(name)
    filename = Path(path).name
    return FileResponse(path, filename=filename)


# ---------------------------------------------------------------------------
# Solver-cache raw file
# 求解器缓存原始文件
# ---------------------------------------------------------------------------


@router.get("/solver-cache-file")
def get_solver_cache_file(
    directory_names: list[str] = Query(..., description="耗材目录名（可重复）"),
    layer_count: int = Query(..., ge=1, description="叠色层数"),
    layer_height_mm: float = Query(..., gt=0.0, description="层高 mm"),
    substrate: str = Query("white", description="基底 white/black"),
    grid_resolution: int = Query(DEFAULT_GRID_RESOLUTION, description="网格分辨率"),
    which: str = Query("npz", description="要取的文件：npz 或 meta"),
):
    """Stream the persisted solver-cache file for a palette, or 404 if absent.
    流式返回调色板的持久化 solver 缓存文件；不存在则 404。

    ``which='npz'`` returns the array payload; ``which='meta'`` returns the
    ``.meta.json`` sidecar the loader validates against. Returns the exact-mode
    (grid=0) cache when present, else the requested grid. The caller mirrors
    both files locally and loads them with the standard cache loader.
    ``which='npz'`` 返回数组载荷；``which='meta'`` 返回加载器校验所需的
    ``.meta.json``。存在精确模式（grid=0）缓存时优先返回，否则返回请求网格。
    """
    if which not in ("npz", "meta"):
        raise HTTPException(status_code=422, detail="which must be 'npz' or 'meta'")
    try:
        materials = _load_materials_cached(directory_names)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # cache_file_path() appends ``_solver_cache`` to the cache_root, so pass the
    # materials root (not the _solver_cache dir itself).
    # cache_file_path() 会在 cache_root 下追加 ``_solver_cache``，因此传入耗材根目录。
    cache_root = str(data_root.materials_root())
    # Prefer exact-mode cache (grid=0) when it exists on disk.
    for grid in (0, int(grid_resolution)):
        npz_path = cache_file_path(
            materials,
            int(layer_count),
            float(layer_height_mm),
            substrate,
            grid_resolution=grid,
            cache_root=cache_root,
        )
        if npz_path.exists():
            if which == "npz":
                return FileResponse(str(npz_path), filename=npz_path.name)
            meta_path = npz_path.with_name(npz_path.stem + ".meta.json")
            if not meta_path.exists():
                raise HTTPException(
                    status_code=404,
                    detail="Solver cache meta sidecar missing for the given parameters",
                )
            return FileResponse(str(meta_path), filename=meta_path.name)

    raise HTTPException(status_code=404, detail="No solver cache found for the given parameters")
