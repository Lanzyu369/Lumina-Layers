"""Five-Color Query — Pydantic 数据模型。
五色组合查询的请求与响应模型定义。
"""

from typing import Optional

from pydantic import BaseModel, Field


class BaseColorEntry(BaseModel):
    """单个基础颜色条目。"""

    index: int = Field(..., description="颜色索引 (0-based)")
    rgb: tuple[int, int, int] = Field(..., description="RGB 值")
    name: str = Field(..., description="颜色名称")
    hex: str = Field(..., description="Hex 颜色代码")


class BaseColorsResponse(BaseModel):
    """基础颜色列表响应。"""

    lut_name: str = Field(..., description="LUT 显示名称")
    color_count: int = Field(..., description="基础颜色数量")
    colors: list[BaseColorEntry] = Field(..., description="基础颜色列表")
    combinations: Optional[list[list[int]]] = Field(None, description="所有合法的五色组合索引，若为空则所有组合合法")


class FiveColorQueryRequest(BaseModel):
    """五色组合查询请求。"""

    lut_name: str = Field(..., description="LUT 显示名称")
    selected_indices: list[int] = Field(
        ..., min_length=5, max_length=5, description="5 个颜色索引"
    )


class FiveColorQueryResponse(BaseModel):
    """五色组合查询响应。"""

    found: bool = Field(..., description="是否找到匹配")
    selected_indices: list[int] = Field(..., description="用户选择的索引")
    result_rgb: Optional[tuple[int, int, int]] = Field(None, description="结果 RGB")
    result_hex: Optional[str] = Field(None, description="结果 Hex")
    row_index: int = Field(..., description="Stack LUT 行索引")
    message: str = Field(..., description="状态消息")
    source: str = Field("", description="来源标识")


# ========== Recipe Swatch Models ==========


class RecipeSwatchItemRequest(BaseModel):
    """单个配方色块请求。"""

    selected_indices: list[int] = Field(
        ..., min_length=5, max_length=5, description="5 个颜色索引序列"
    )
    result_hex: str = Field(..., description="混合结果 Hex 颜色")
    base_color_names: list[str] = Field(default_factory=list, description="各基础色名称（可省略，服务端将从 LUT 推导）")
    base_color_hexes: list[str] = Field(default_factory=list, description="各基础色 Hex（可省略，服务端将从 LUT 推导）")


class RecipeSwatchRequest(BaseModel):
    """配方色块 3MF 批量生成请求。"""

    lut_name: str = Field(..., description="LUT 显示名称")
    recipes: list[RecipeSwatchItemRequest] = Field(
        ..., min_length=1, max_length=100, description="配方列表"
    )
    block_size_mm: float = Field(15.0, ge=5.0, le=50.0, description="色块尺寸 (mm)")
    gap_mm: float = Field(2.0, ge=0.5, le=10.0, description="白色网格线宽 (mm)")
    cols: int = Field(0, ge=0, le=20, description="每行列数; 0 = 自动")
    structure_mode: str = Field("Single-sided", description="结构模式: Single-sided / Double-sided")
    printer_id: str = Field("bambu-h2d", description="打印机配置 ID")
    slicer: str = Field("BambuStudio", description="切片软件 ID")


class RecipeSwatchResponse(BaseModel):
    """配方色块 3MF 生成响应。"""

    status: str = Field(..., description="状态")
    message: str = Field(..., description="状态消息")
    download_url: str = Field(..., description="3MF 下载 URL")
    preview_url: Optional[str] = Field(None, description="色卡图预览 URL")
    recipe_count: int = Field(..., description="已生成的配方数量")
