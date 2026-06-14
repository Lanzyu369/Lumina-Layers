"""Five-Color Query — Pydantic 数据模型。
五色组合查询的请求与响应模型定义。
"""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


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
    combinations: Optional[list[list[int]]] = Field(
        None,
        description="所有合法的五色组合索引；null 表示不限制组合，空列表表示没有合法的五色组合",
    )


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
    reason: Optional[str] = Field(None, description="结构化原因码")


class FiveColorCardCoordinate(BaseModel):
    """匹配颜色在色卡布局中的坐标。"""

    card_index: int = Field(..., description="色卡索引，0-based")
    card_label: str = Field(..., description="色卡显示标签")
    page_index: int = Field(..., description="页面索引，0-based")
    page_label: str = Field(..., description="页面显示标签")
    grid_size: int = Field(..., description="色卡方阵尺寸")
    data_rows: int = Field(..., description="数据区行数")
    data_cols: int = Field(..., description="数据区列数")
    row: int = Field(..., description="行坐标，0-based")
    col: int = Field(..., description="列坐标，0-based")
    data_row: int = Field(..., description="数据区行坐标，0-based")
    data_col: int = Field(..., description="数据区列坐标，0-based")
    display_row: int = Field(..., description="显示行号，1-based")
    display_col: int = Field(..., description="显示列号，1-based")
    physical_row: int = Field(..., description="物理行坐标，0-based，含边框")
    physical_col: int = Field(..., description="物理列坐标，0-based，含边框")
    row_index: int = Field(..., description="LUT 行索引")


class FiveColorNeighborhoodCell(BaseModel):
    """虚拟小色卡中的单个格子。"""

    card_index: Optional[int] = Field(None, description="色卡索引，0-based；空格为 None")
    card_label: Optional[str] = Field(None, description="色卡显示标签；空格为 None")
    page_index: Optional[int] = Field(None, description="页面索引，0-based；空格为 None")
    page_label: Optional[str] = Field(None, description="页面显示标签；空格为 None")
    grid_size: Optional[int] = Field(None, description="色卡方阵尺寸；空格为 None")
    data_rows: Optional[int] = Field(None, description="数据区行数；空格为 None")
    data_cols: Optional[int] = Field(None, description="数据区列数；空格为 None")
    row: Optional[int] = Field(None, description="行坐标，0-based；空格为 None")
    col: Optional[int] = Field(None, description="列坐标，0-based；空格为 None")
    data_row: Optional[int] = Field(None, description="数据区行坐标，0-based；空格为 None")
    data_col: Optional[int] = Field(None, description="数据区列坐标，0-based；空格为 None")
    display_row: Optional[int] = Field(None, description="显示行号，1-based")
    display_col: Optional[int] = Field(None, description="显示列号，1-based")
    physical_row: Optional[int] = Field(None, description="物理行坐标，0-based，含边框")
    physical_col: Optional[int] = Field(None, description="物理列坐标，0-based，含边框")
    row_index: Optional[int] = Field(None, description="LUT 行索引；空格为 None")
    rgb: Optional[tuple[int, int, int]] = Field(None, description="格子 RGB")
    hex: Optional[str] = Field(None, description="格子 Hex")
    is_match: bool = Field(False, description="是否为当前匹配格")


class FiveColorMatchRequest(BaseModel):
    """按目标色值反查五层配方请求。"""

    lut_name: str = Field(..., description="LUT 显示名称")
    target_hex: str = Field(..., description="目标 Hex 颜色，例如 #FF8040")
    neighborhood_radius: int = Field(2, ge=0, le=4, description="虚拟小色卡邻域半径")

    @field_validator("target_hex")
    @classmethod
    def normalize_target_hex(cls, value: str) -> str:
        """Normalize and validate a #RRGGBB value."""
        normalized = value.strip().upper()
        if not normalized.startswith("#"):
            normalized = f"#{normalized}"
        if len(normalized) != 7:
            raise ValueError("target_hex must be #RRGGBB")
        try:
            int(normalized[1:], 16)
        except ValueError as exc:
            raise ValueError("target_hex must be #RRGGBB") from exc
        return normalized


class FiveColorMatchResponse(FiveColorQueryResponse):
    """按目标色值反查五层配方响应。"""

    target_rgb: tuple[int, int, int] = Field(..., description="目标 RGB")
    target_hex: str = Field(..., description="目标 Hex")
    matched_rgb: Optional[tuple[int, int, int]] = Field(None, description="匹配 RGB")
    matched_hex: Optional[str] = Field(None, description="匹配 Hex")
    delta_e: Optional[float] = Field(None, description="OpenCV Lab 最近邻距离")
    coordinate: FiveColorCardCoordinate = Field(..., description="匹配色卡坐标")
    neighborhood: list[list[FiveColorNeighborhoodCell]] = Field(..., description="虚拟小色卡")


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
    nozzle_size: str = Field("0.4", description="喷嘴尺寸")
    device_profile_id: str | None = Field(None, description="机器注册表设备配置 ID")


class RecipeSwatchResponse(BaseModel):
    """配方色块 3MF 生成响应。"""

    status: str = Field(..., description="状态")
    message: str = Field(..., description="状态消息")
    download_url: str = Field(..., description="3MF 下载 URL")
    preview_url: Optional[str] = Field(None, description="色卡图预览 URL")
    recipe_count: int = Field(..., description="已生成的配方数量")
