"""MLS — LUT management router (thin adapter over the main router handlers).
MLS — LUT 管理路由（在主路由处理函数之上的薄适配层）。

Route B makes Material-LUT Studio own the LUT data, but the merge/compare/
info orchestration must not be copy-pasted: the main ``api/routers/lut.py``
handlers are session-free and are pinned as monkeypatch targets by canary
tests. We therefore reuse those handler callables directly and re-register
them under the ``/api/mls/lut`` prefix. Only the session-coupled
``/session/{id}/info`` endpoint is intentionally excluded — session state
stays owned by the main Lumina app.

路线 B 让 MLS 拥有 LUT 数据，但 merge/compare/info 等编排逻辑不能复制粘贴：
主 ``api/routers/lut.py`` 的处理函数是会话无关的，且被 canary 测试作为
monkeypatch 目标固定。因此这里直接复用那些处理函数，并以 ``/api/mls/lut``
前缀重新注册。唯一刻意排除的是会话耦合的 ``/session/{id}/info`` 端点——
会话状态仍归主 Lumina 应用所有。
"""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from api.routers import lut as main_lut
from api.schemas.lut import (
    CompareRequest,
    CompareResponse,
    LutDetailsCatalogResponse,
    LutDetailsResponse,
    LutInfoResponseV2,
    LutSourceCatalogResponse,
    MergeRequest,
    MergeResponse,
    RecipeColorPredictRequest,
    RecipeColorPredictResponse,
    RecipeSearchRequest,
    RecipeSearchResponse,
)
from api.schemas.responses import LUTListResponse, LutColorsResponse

router = APIRouter(prefix="/api/mls/lut", tags=["MLS LUT"])


@router.get("/list")
def list_luts() -> LUTListResponse:
    """List all available LUT presets. (列出所有可用 LUT 预设)"""
    return main_lut.list_luts()


@router.get("/catalog", response_model=LutSourceCatalogResponse)
def get_source_catalog() -> LutSourceCatalogResponse:
    """Return legacy and native source catalog groupings. (返回源目录分组)"""
    return main_lut.get_source_catalog()


@router.get("/details/catalog", response_model=LutDetailsCatalogResponse)
def get_lut_details_catalog() -> LutDetailsCatalogResponse:
    """Return the LUT details catalog grouped by manufacturer. (按厂商分组的详情目录)"""
    return main_lut.get_lut_details_catalog()


@router.post("/upload")
async def upload_lut(
    file: UploadFile = File(..., description="LUT 文件 (.npy/.json/.npz/.msgpack)"),
) -> dict:
    """Upload a LUT file to the Custom preset directory. (上传 LUT 到 Custom 目录)"""
    return await main_lut.upload_lut(file)


@router.post("/merge")
def merge_luts_endpoint(request: MergeRequest) -> MergeResponse:
    """Execute LUT merge: primary + multiple secondary LUTs. (执行 LUT 合并)"""
    return main_lut.merge_luts_endpoint(request)


@router.post("/compare")
def compare_luts_endpoint(request: CompareRequest) -> CompareResponse:
    """Compare two LUTs by shared recipe keys. (按共享配方比较两个 LUT)"""
    return main_lut.compare_luts_endpoint(request)


@router.get("/{lut_name}/colors")
def get_lut_colors(lut_name: str) -> LutColorsResponse:
    """Return all unique colors available in a LUT file. (返回 LUT 所有唯一颜色)"""
    return main_lut.get_lut_colors(lut_name)


@router.get("/{lut_name}/info")
def get_lut_info(lut_name: str) -> LutInfoResponseV2:
    """Return color mode and color count for a specific LUT. (返回 LUT 模式与颜色数)"""
    return main_lut.get_lut_info(lut_name)


@router.get("/{lut_name}/details", response_model=LutDetailsResponse)
def get_lut_details(lut_name: str) -> LutDetailsResponse:
    """Return the detailed LUT metadata and visualization payload. (返回详情可视化载荷)"""
    return main_lut.get_lut_details(lut_name)


@router.post("/{lut_name}/predict-recipe-color")
def predict_recipe_color_endpoint(
    lut_name: str,
    request: RecipeColorPredictRequest,
) -> RecipeColorPredictResponse:
    """Predict a custom recipe color for the selected source. (预测自定义配方颜色)"""
    return main_lut.predict_recipe_color_endpoint(lut_name, request)


@router.post("/{lut_name}/search-recipes")
def search_recipes_endpoint(
    lut_name: str,
    request: RecipeSearchRequest,
) -> RecipeSearchResponse:
    """Search predictive candidate recipes by a layer pattern. (按层序模式搜索配方)"""
    return main_lut.search_recipes_endpoint(lut_name, request)
