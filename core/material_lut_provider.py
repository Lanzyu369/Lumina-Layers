"""Hot-path data provider for material-archive + solver-cache access.
耗材档案与求解缓存访问的热路径数据提供者。

Why this module exists (Route B)
--------------------------------
Decoupling material/LUT data ownership to the Material-LUT Studio (MLS)
service must never turn the converter hot path into per-pixel network calls.
The staged pipeline (``s02`` material loading, ``s03`` solver-cache lookup)
runs inside CPU-heavy NumPy code; a synchronous HTTP round-trip there would
wreck latency and robustness.

This provider is the **single chokepoint** the pipeline calls instead of
importing ``core.material_lut_synthesis`` / ``core.material_cache`` directly.
It adds two things on top of those pure loaders:

1. **Process-local memo cache** keyed by the request parameters, so repeated
   loads within a preview/generate run hit memory instead of re-reading disk.
2. **A stable seam** for Route B: today it reads the shared on-disk data
   (MLS and the main app point at the same roots); when MLS becomes the sole
   writer, only this module changes to prefetch from MLS into a local cache —
   pipeline code stays untouched.

为什么需要本模块（路线 B）：把耗材/LUT 数据所有权解耦到 MLS 服务，绝不能让
转换热路径变成逐像素网络调用。分阶段管线（``s02`` 加载耗材、``s03`` 查求解
缓存）运行在 CPU 密集的 NumPy 代码里，此处同步 HTTP 往返会摧毁延迟与健壮性。

本提供者是管线调用的**唯一收口**，取代直接 import
``core.material_lut_synthesis`` / ``core.material_cache``。它在纯加载器之上
增加：(1) 按请求参数建键的进程内 memo 缓存，使一次预览/生成内的重复加载命中
内存而非重复读盘；(2) 路线 B 的稳定接缝：当前读共享磁盘数据（MLS 与主应用指向
同一根目录），未来 MLS 成为唯一写入方时，只需改本模块从 MLS 预取到本地缓存，
管线代码无需改动。

Behavior is byte-for-byte identical to the direct loader calls so this is a
lossless refactor (AGENTS.md): the pipeline keeps passing the same arguments
and receiving the same objects.
行为与直接调用加载器逐字节一致，属无损重构：管线仍传相同参数、收相同对象。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from config import MATERIALS_DIR
from core import material_cache as _material_cache
from core import material_lut_synthesis as _material_lut_synthesis
from core.material_cache import DEFAULT_GRID_RESOLUTION
from core.material_color_solver import MaterialParams

if TYPE_CHECKING:
    from core.material_cache import MaterialSolverCache


def _mls_enabled() -> bool:
    """Whether hot-path data access should be routed to the MLS service.
    热路径数据访问是否应路由到 MLS 服务。

    Route B / 做法一. Reads the same ``LUMINA_MLS_ENABLED`` flag the management
    client uses, so flipping it switches both management and hot-path data
    sourcing together. Off by default keeps local-disk behavior (migration-safe).
    读取与管理客户端相同的 ``LUMINA_MLS_ENABLED`` 开关；默认关闭时保持本地读盘
    行为（迁移期安全）。

    Returns:
        bool: ``True`` when MLS routing is enabled. (启用 MLS 路由时为 True)
    """
    from api.clients.mls_client import MLSClient

    return MLSClient.is_enabled()

# ---------------------------------------------------------------------------
# Process-local memo caches
# 进程内 memo 缓存
# ---------------------------------------------------------------------------

_materials_lock = threading.Lock()
_materials_memo: dict[tuple[str, tuple[str, ...], tuple[float, ...]], list[MaterialParams]] = {}


def _material_archive_mtimes(
    directory_names: list[str],
    materials_dir: str | None,
) -> tuple[float, ...]:
    """Compute an mtime fingerprint of each material's on-disk archive files.
    计算每个耗材磁盘档案文件的 mtime 指纹。

    Folding this into the memo key makes the cache **self-invalidating across
    processes**: if MLS (a separate process) imports/edits/deletes a material,
    the ``material.json`` / ``stage_A_parameters.json`` mtimes change, the key
    changes, and the main app reloads fresh data on the next request — without
    any explicit cross-process invalidation protocol. Missing files contribute
    ``0.0`` so a deletion still shifts the fingerprint.

    把它折进 memo 键，使缓存能**跨进程自失效**：MLS（独立进程）导入/编辑/删除
    耗材时，``material.json`` / ``stage_A_parameters.json`` 的 mtime 变化使键变化，
    主应用下次请求即重载最新数据，无需任何显式跨进程失效协议。文件缺失记为
    ``0.0``，使删除同样改变指纹。

    Args:
        directory_names: Material directory names. (耗材目录名)
        materials_dir: Optional materials root override. (可选耗材根目录覆盖)

    Returns:
        tuple[float, ...]: Per-material mtime values, aligned to inputs.
            (与输入对齐的逐耗材 mtime 值)
    """
    root = Path(materials_dir or MATERIALS_DIR)
    fingerprints: list[float] = []
    for directory_name in directory_names:
        material_dir = root / directory_name
        mtime = 0.0
        for filename in ("material.json", "stage_A_parameters.json"):
            try:
                mtime = max(mtime, (material_dir / filename).stat().st_mtime)
            except OSError:
                # Missing/unreadable file contributes 0.0 so deletions and
                # renames still shift the fingerprint. 缺失文件记 0.0。
                continue
        fingerprints.append(mtime)
    return tuple(fingerprints)


def _materials_key(
    directory_names: list[str],
    materials_dir: str | None,
) -> tuple[str, tuple[str, ...], tuple[float, ...]]:
    """Build the memo key for a material-load request.
    为一次耗材加载请求构建 memo 键（含 mtime 指纹以支持自失效）。
    """
    return (
        str(materials_dir or ""),
        tuple(directory_names),
        _material_archive_mtimes(directory_names, materials_dir),
    )


def load_materials(
    directory_names: list[str],
    *,
    materials_dir: str | None = None,
    use_cache: bool = True,
) -> list[MaterialParams]:
    """Load material archives for the hot path (memoized).
    为热路径加载耗材档案（带 memo 缓存）。

    Mirrors :func:`core.material_lut_synthesis.load_multiple_materials` exactly,
    adding a process-local memo so repeated loads of the same palette within a
    request hit memory. The returned list and its :class:`MaterialParams` are
    treated as immutable by the pipeline; callers must not mutate them.

    精确镜像 ``load_multiple_materials``，叠加进程内 memo；返回的列表与
    ``MaterialParams`` 在管线中按不可变对待，调用方不得修改。

    Args:
        directory_names: Material directory names in user-selected order.
            (按用户选择顺序的耗材目录名)
        materials_dir: Optional materials root override. (可选耗材根目录覆盖)
        use_cache: Set ``False`` to bypass and refresh the memo. (是否使用缓存)

    Returns:
        list[MaterialParams]: Loaded material parameters in order. (按序的耗材参数)
    """
    # Remote mode (Route B): the converter runs on a separate server with no
    # shared material filesystem, so the local-mtime memo key is meaningless
    # (the files are absent → mtime 0.0 → a constant key). Memoizing there
    # would pin the first-fetched MaterialParams forever, serving stale
    # Beer-Lambert params after MLS edits/re-imports the same directories.
    # The materials payload is tiny (four length-3 vectors each) and is
    # fetched at most a handful of times per generate, so we simply bypass
    # the memo and always fetch fresh — correctness over a negligible cache.
    # 远程模式（路线 B）：转换器在独立服务器、无共享耗材文件系统，本地 mtime
    # memo 键无意义（文件缺失 → mtime 0.0 → 常量键）。在此 memo 会把首次取到的
    # MaterialParams 永久固定，导致 MLS 编辑/重导入后返回陈旧参数。耗材载荷极小
    # 且每次生成至多取数次，故直接绕过 memo 始终取新——正确性优先于可忽略的缓存。
    if _mls_enabled():
        from core.material_lut_remote import fetch_materials

        return fetch_materials(directory_names)

    key = _materials_key(directory_names, materials_dir)
    if use_cache:
        with _materials_lock:
            cached = _materials_memo.get(key)
        if cached is not None:
            return cached

    loaded = _material_lut_synthesis.load_multiple_materials(
        directory_names, materials_dir=materials_dir
    )

    with _materials_lock:
        _materials_memo[key] = loaded
    return loaded


def load_solver_cache(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    grid_resolution: int = DEFAULT_GRID_RESOLUTION,
    cache_root: str | Path | None = None,
) -> tuple["MaterialSolverCache | None", int | None]:
    """Load the persisted solver cache for the hot path.
    为热路径加载持久化求解缓存。

    Thin pass-through to
    :func:`core.material_cache.load_material_solver_cache_with_fallback`. It is
    intentionally NOT memoized: solver caches are large NumPy-backed objects
    and the fallback loader already does its own efficient disk resolution, so
    memoizing here would only add memory pressure without a latency win on the
    typical single-lookup-per-request path.

    透传到 ``load_material_solver_cache_with_fallback``。有意不做 memo：求解
    缓存是大型 NumPy 对象，回退加载器自身已高效解析磁盘，且典型路径每请求只查
    一次，memo 只会增加内存压力而无延迟收益。

    Args:
        materials: Palette to match. (调色板)
        layer_count: Number of layers per pixel. (每像素层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底)
        grid_resolution: Preferred Lab grid resolution to try first. (优先网格分辨率)
        cache_root: Optional cache directory override. (可选缓存根目录覆盖)

    Returns:
        ``(cache, actual_grid)`` — see the wrapped loader. (见被包装加载器)
    """
    if _mls_enabled():
        # Route B / 做法一: mirror the persisted solver cache from MLS into a
        # local cache_root, then load it with the unchanged fallback loader so
        # all fingerprint/shape validation is reused.
        # 做法一：从 MLS 镜像 solver 缓存到本地 cache_root，再用未改动的回退
        # 加载器加载，完整复用指纹/形状校验。
        from core.material_lut_remote import fetch_solver_cache_root

        directory_names = [m.directory_name for m in materials]
        local_root = fetch_solver_cache_root(
            directory_names,
            materials,
            int(layer_count),
            float(layer_height_mm),
            substrate,
            int(grid_resolution),
        )
        if local_root is None:
            return None, None
        return _material_cache.load_material_solver_cache_with_fallback(
            materials,
            layer_count,
            layer_height_mm,
            substrate,
            grid_resolution=grid_resolution,
            cache_root=local_root,
        )

    return _material_cache.load_material_solver_cache_with_fallback(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        grid_resolution=grid_resolution,
        cache_root=cache_root,
    )


def clear_memo_caches() -> None:
    """Drop all process-local memo caches.
    清空所有进程内 memo 缓存。

    Call this when material archives change on disk during a process lifetime
    (imports, deletes, edits) so the next load re-reads fresh data. This is the
    main app's local-cache invalidation hook for Route B; when MLS becomes the
    sole writer it will signal invalidation (version/fingerprint) and this is
    where the main app responds.

    当进程生命周期内磁盘上的耗材档案发生变化（导入/删除/编辑）时调用，使下次
    加载读取最新数据。这是路线 B 下主应用的本地缓存失效钩子。
    """
    with _materials_lock:
        _materials_memo.clear()
