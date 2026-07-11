"""Hot-path data provider for local material-archive + solver-cache access.
本地耗材档案与求解缓存访问的热路径数据提供者。

The staged pipeline calls this module instead of importing
``core.material_lut_synthesis`` / ``core.material_cache`` directly. It keeps
the useful local optimization from the split experiment: a process-local memo
cache keyed by request parameters and material archive mtimes, so repeated
loads within a preview/generate run hit memory while edits on disk invalidate
the memo automatically.

分阶段管线通过本模块访问耗材与求解缓存，而不是直接 import
``core.material_lut_synthesis`` / ``core.material_cache``。这里保留拆分实验中
有价值的本地优化：按请求参数和耗材档案 mtime 建键的进程内 memo 缓存，使一次
预览/生成内的重复加载命中内存，同时磁盘编辑会自动使 memo 失效。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from config import MATERIALS_DIR
from core import material_cache as _material_cache
from core import material_lut_synthesis as _material_lut_synthesis
from core.material_cache import DEFAULT_GRID_RESOLUTION
from core.material_candidate_cache import (
    MaterialCandidateCacheConfig,
    DEFAULT_PERSISTED_CANDIDATE_BUDGET,
    LEGACY_PERSISTED_CANDIDATE_BUDGET,
    MAX_PERSISTED_CANDIDATE_BUDGET,
    PREVIEW_SAFE_CANDIDATE_BUDGET,
    QUALITY_8M_CANDIDATE_BUDGET,
    build_material_candidate_runtime,
    load_material_candidate_runtime,
)
from core.material_color_solver import MaterialParams

if TYPE_CHECKING:
    from core.material_cache import MaterialSolverCache
    from core.material_candidate_cache import MaterialCandidateRuntime

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
    local edits and processes**: if another local tool, worker, or request
    imports/edits/deletes a material, the ``material.json`` /
    ``stage_A_parameters.json`` mtimes change, the key changes, and the main
    app reloads fresh data on the next request — without any explicit
    invalidation protocol. Missing files contribute ``0.0`` so a deletion
    still shifts the fingerprint.

    把它折进 memo 键，使缓存能对**本地编辑和跨进程写入自失效**：当其他本地工具、
    worker 或请求导入/编辑/删除耗材时，``material.json`` /
    ``stage_A_parameters.json`` 的 mtime 变化使键变化，主应用下次请求即重载最新
    数据，无需任何显式失效协议。文件缺失记为 ``0.0``，使删除同样改变指纹。

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
    return _material_cache.load_material_solver_cache_with_fallback(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        grid_resolution=grid_resolution,
        cache_root=cache_root,
    )


def load_solver_runtime(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    grid_resolution: int = DEFAULT_GRID_RESOLUTION,
    cache_root: str | Path | None = None,
    candidate_budget: int | None = None,
) -> tuple["MaterialSolverCache | MaterialCandidateRuntime | None", int | None]:
    """Load a lookup-compatible material solver runtime for hot paths.
    为热路径加载一个与求解缓存 ``lookup`` 兼容的运行时。

    Existing persisted :class:`MaterialSolverCache` files still take priority.
    When none is available, this builds a bounded
    :class:`MaterialCandidateRuntime` instead of falling back to the legacy
    low-grid exhaustive builder.

    已有持久化 ``MaterialSolverCache`` 优先；缺失时构建有候选数量上限的
    ``MaterialCandidateRuntime``，不再回退到旧的低 grid 穷举构建器。

    Args:
        materials: Palette to match. (调色板)
        layer_count: Number of layers per pixel. (每像素层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底)
        grid_resolution: Preferred legacy cache grid resolution. (旧缓存优先网格)
        cache_root: Optional legacy cache directory override. (旧缓存目录覆盖)
        candidate_budget: Optional runtime candidate budget override.
            (可选候选数量覆盖)

    Returns:
        tuple: ``(runtime, actual_grid)`` where runtime exposes ``lookup``.
            (运行时与实际诊断分辨率)
    """
    cache, actual_grid = load_solver_cache(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        grid_resolution=grid_resolution,
        cache_root=cache_root,
    )
    if cache is not None:
        return cache, actual_grid

    if candidate_budget is None:
        for budget in (
            MAX_PERSISTED_CANDIDATE_BUDGET,
            DEFAULT_PERSISTED_CANDIDATE_BUDGET,
            QUALITY_8M_CANDIDATE_BUDGET,
            LEGACY_PERSISTED_CANDIDATE_BUDGET,
            PREVIEW_SAFE_CANDIDATE_BUDGET,
        ):
            persisted_runtime = load_material_candidate_runtime(
                materials,
                layer_count,
                layer_height_mm,
                substrate,
                candidate_budget=int(budget),
                cache_root=cache_root,
            )
            if persisted_runtime is not None:
                return persisted_runtime, persisted_runtime.grid_resolution
        config = MaterialCandidateCacheConfig.preview_safe()
    else:
        config = MaterialCandidateCacheConfig.persisted_for_budget(
            int(candidate_budget)
        )
        persisted_runtime = load_material_candidate_runtime(
            materials,
            layer_count,
            layer_height_mm,
            substrate,
            candidate_budget=int(config.candidate_budget),
            cache_root=cache_root,
        )
        if persisted_runtime is not None:
            return persisted_runtime, persisted_runtime.grid_resolution

    runtime = build_material_candidate_runtime(
        materials=materials,
        layer_count=int(layer_count),
        layer_height_mm=float(layer_height_mm),
        substrate=str(substrate),
        config=config,
    )
    return runtime, runtime.grid_resolution


def load_dynamic_candidate_runtime(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    candidate_budget: int = PREVIEW_SAFE_CANDIDATE_BUDGET,
    cache_root: str | Path | None = None,
) -> tuple["MaterialCandidateRuntime", int | None]:
    """Load/build one pinned-budget candidate runtime for dynamic solving.

    为动态求解加载或构建一个固定预算的候选运行时。

    Unlike :func:`load_solver_runtime`, this function never probes a legacy
    fixed-grid :class:`MaterialSolverCache`. A single explicit candidate budget
    therefore identifies the same bounded universe at every effective layer,
    even if legacy cache files are added later.

    与 :func:`load_solver_runtime` 不同，本函数绝不探测旧的固定网格
    :class:`MaterialSolverCache`。因此同一个显式候选预算在每个有效层数上始终
    对应同一个有界候选宇宙，不会因后来新增旧缓存而改变。

    Args:
        materials: Material palette. 耗材调色板。
        layer_count: Effective recipe layer count. 有效配方层数。
        layer_height_mm: Physical layer height in millimeters. 物理层高。
        substrate: Optical substrate, ``white`` or ``black``. 光学基底。
        candidate_budget: Explicit candidate budget used for this layer.
            本层使用的显式候选预算。
        cache_root: Optional candidate-runtime cache root. 可选候选缓存根目录。

    Returns:
        tuple[MaterialCandidateRuntime, int | None]: Candidate runtime and its
        diagnostic grid resolution. 候选运行时及诊断网格分辨率。
    """

    config = MaterialCandidateCacheConfig.persisted_for_budget(
        int(candidate_budget)
    )
    persisted_runtime = load_material_candidate_runtime(
        materials,
        int(layer_count),
        float(layer_height_mm),
        str(substrate),
        candidate_budget=int(config.candidate_budget),
        cache_root=cache_root,
    )
    if persisted_runtime is not None:
        return persisted_runtime, persisted_runtime.grid_resolution

    runtime = build_material_candidate_runtime(
        materials=materials,
        layer_count=int(layer_count),
        layer_height_mm=float(layer_height_mm),
        substrate=str(substrate),
        config=config,
    )
    return runtime, runtime.grid_resolution


def clear_memo_caches() -> None:
    """Drop all process-local memo caches.
    清空所有进程内 memo 缓存。

    Call this when material archives change on disk during a process lifetime
    (imports, deletes, edits) so the next load re-reads fresh data.

    当进程生命周期内磁盘上的耗材档案发生变化（导入/删除/编辑）时调用，使下次
    加载读取最新数据。
    """
    with _materials_lock:
        _materials_memo.clear()
