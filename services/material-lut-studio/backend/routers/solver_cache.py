"""MLS — Material solver-cache management router (thin adapter).
MLS — 耗材求解器缓存管理路由（薄适配层）。

Solver-cache endpoints (list / status / build / delete / suggest-colors) are
fully session-free: they validate Form params and call ``core.material_cache``
/ ``core.material_color_solver`` pure functions. They are reused directly from
the main app's ``api/routers/single_stage.py`` handlers and re-registered
under the ``/api/mls/solver-cache`` prefix, so the build/lookup algorithm is
never copy-pasted.

求解缓存端点（list / status / build / delete / suggest-colors）完全会话无关：
仅校验 Form 参数并调用 ``core.material_cache`` / ``core.material_color_solver``
的纯函数。这里直接复用主应用 ``single_stage.py`` 的处理函数，并以
``/api/mls/solver-cache`` 前缀重新注册，构建/查询算法绝不复制粘贴。
"""

from __future__ import annotations

from fastapi import APIRouter, Form

from .. import bootstrap

bootstrap.ensure_repo_on_path()

from api.routers import single_stage as main_single_stage  # noqa: E402
from api.schemas.responses import (  # noqa: E402
    MaterialColorSuggestionsResponse,
    MaterialSolverCacheBuildResponse,
    MaterialSolverCacheDeleteResponse,
    MaterialSolverCacheListResponse,
    MaterialSolverCacheStatusResponse,
)
from core.material_cache import DEFAULT_GRID_RESOLUTION  # noqa: E402
from core.material_color_solver import (  # noqa: E402
    DEFAULT_SUGGEST_MAX_COMBINATIONS,
    DEFAULT_SUGGEST_MIN_SPACING,
    DEFAULT_SUGGEST_TOP_K,
)

router = APIRouter(prefix="/api/mls/solver-cache", tags=["MLS Solver Cache"])


@router.get("")
async def list_caches() -> MaterialSolverCacheListResponse:
    """List every persisted solver-cache entry with metadata. (列出全部缓存条目)"""
    return await main_single_stage.material_solver_cache_list()


@router.post("/status")
async def cache_status(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    grid_resolution: int = Form(DEFAULT_GRID_RESOLUTION),
) -> MaterialSolverCacheStatusResponse:
    """Check whether a cache exists for the palette & parameters. (查询缓存是否存在)"""
    return await main_single_stage.material_solver_cache_status(
        material_directory_names=material_directory_names,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        grid_resolution=grid_resolution,
    )


@router.post("/build")
async def cache_build(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    grid_resolution: int = Form(DEFAULT_GRID_RESOLUTION),
) -> MaterialSolverCacheBuildResponse:
    """Build and persist a solver cache synchronously. (同步构建并持久化缓存)"""
    return await main_single_stage.material_solver_cache_build(
        material_directory_names=material_directory_names,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        grid_resolution=grid_resolution,
    )


@router.post("/delete")
async def cache_delete(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    grid_resolution: int = Form(DEFAULT_GRID_RESOLUTION),
) -> MaterialSolverCacheDeleteResponse:
    """Delete a persisted solver cache entry. (删除已持久化的缓存条目)"""
    return await main_single_stage.material_solver_cache_delete(
        material_directory_names=material_directory_names,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        grid_resolution=grid_resolution,
    )


@router.post("/suggest-colors")
async def cache_suggest_colors(
    material_directory_names: str = Form(...),
    layer_count: int = Form(...),
    layer_height_mm: float = Form(...),
    substrate: str = Form("white"),
    target_hex: str = Form(...),
    top_k: int = Form(DEFAULT_SUGGEST_TOP_K),
    min_spacing: float = Form(DEFAULT_SUGGEST_MIN_SPACING),
    max_combinations: int = Form(DEFAULT_SUGGEST_MAX_COMBINATIONS),
    grid_resolution: int = Form(DEFAULT_GRID_RESOLUTION),
) -> MaterialColorSuggestionsResponse:
    """Return up to ``top_k`` achievable colors near ``target_hex``. (返回近似可达色)"""
    return await main_single_stage.material_solver_cache_suggest_colors(
        material_directory_names=material_directory_names,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        target_hex=target_hex,
        top_k=top_k,
        min_spacing=min_spacing,
        max_combinations=max_combinations,
        grid_resolution=grid_resolution,
    )
