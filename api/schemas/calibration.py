"""Calibration domain Pydantic schemas and enums.
Calibration 领域的 Pydantic 数据模型与枚举定义。

This module defines the request model for calibration board generation,
including backing thickness and block sizing parameters. The backing
plate color is hard-coded to white in the calibration workflow, so the
``BackingColor`` enum is retained only for backward compatibility with
existing tests and downstream callers.
本模块定义校准板生成 API 的请求模型，包含底板厚度与色块尺寸参数。
校准流程中底板颜色固定为白色，``BackingColor`` 枚举仅为向后兼容保留。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from api.schemas.extractor import CalibrationColorMode
from config import (
    DEFAULT_PRINTER_ID,
    DEFAULT_SLICER_ID,
    format_native_nozzle_size,
    normalize_nozzle_size,
    normalize_printer_profile_id,
    normalize_slicer_software_id,
)


# ========== Constants ==========

#: Default backing thickness in mm (matches ``PrinterConfig.BACKING_MM``).
#: 默认底板厚度（毫米），与 ``PrinterConfig.BACKING_MM`` 保持一致。
DEFAULT_BACKING_THICKNESS_MM: float = 1.2

#: Minimum backing thickness exposed to the calibration UI (mm).
#: 校准 UI 暴露的底板最小厚度（毫米）。
MIN_BACKING_THICKNESS_MM: float = 0.4

#: Maximum backing thickness exposed to the calibration UI (mm). Mirrors the
#: image-converter limit defined in ``api.schemas.converter``.
#: 校准 UI 暴露的底板最大厚度（毫米），与图像转换器配置保持一致。
MAX_BACKING_THICKNESS_MM: float = 3.5


# ========== Enums ==========


class BackingColor(str, Enum):
    """Backing plate color for calibration board generation.
    校准板底板颜色（保留枚举以保持向后兼容）。

    Attributes:
        WHITE: White backing plate.
            白色底板。
        CYAN: Cyan backing plate.
            青色底板。
        MAGENTA: Magenta backing plate.
            品红色底板。
        YELLOW: Yellow backing plate.
            黄色底板。
        RED: Red backing plate.
            红色底板。
        BLUE: Blue backing plate.
            蓝色底板。
    """

    WHITE = "White"
    CYAN = "Cyan"
    MAGENTA = "Magenta"
    YELLOW = "Yellow"
    RED = "Red"
    BLUE = "Blue"


# ========== Models ==========


class CalibrationGenerateRequest(BaseModel):
    """Request model for generating a calibration board.
    生成校准板的请求模型。

    Used by ``POST /api/calibration/generate`` to create a printable
    calibration board with specified color mode, block size, spacing,
    and backing thickness. The backing plate color is fixed to white.
    用于 ``POST /api/calibration/generate``，按指定颜色模式、色块尺寸、
    间距和底板厚度生成可打印的校准板。底板颜色固定为白色。

    Attributes:
        color_mode: Calibration color system mode.
            校准颜色模式。
        block_size: Block size in millimeters (3-10).
            色块尺寸 (mm)。
        gap: Gap between blocks in millimeters (0.4-2.0).
            色块间距 (mm)。
        backing_thickness: Backing layer thickness in millimeters
            (``MIN_BACKING_THICKNESS_MM``-``MAX_BACKING_THICKNESS_MM``).
            底板厚度 (mm)。
        eight_color_full_export: Whether 8-color mode exports the exhaustive
            multi-page ZIP package instead of the compact two-page kit.
            8 色模式是否导出全量多页 ZIP，而不是默认的精简双页套件。
    """

    color_mode: CalibrationColorMode = Field(
        CalibrationColorMode.FOUR_COLOR_RYBW, description="校准颜色模式"
    )
    block_size: float = Field(5.0, ge=3, le=10, description="色块尺寸 (mm)")
    gap: float = Field(0.84, ge=0.4, le=2.0, description="色块间距 (mm)")
    backing_thickness: float = Field(
        DEFAULT_BACKING_THICKNESS_MM,
        ge=MIN_BACKING_THICKNESS_MM,
        le=MAX_BACKING_THICKNESS_MM,
        description="底板厚度 (mm)",
    )
    eight_color_full_export: bool = Field(False, description="8 色是否导出全量分页包")
    printer_id: str = Field(DEFAULT_PRINTER_ID, description="打印机配置 ID")
    slicer: str = Field(DEFAULT_SLICER_ID, description="切片软件 ID")
    device_profile_id: str | None = Field(None, description="机器注册表设备配置 ID")
    build_plate_id: str | None = Field(None, description="打印板配置 ID")
    nozzle_size: str = Field("0.4", description="喷嘴直径")

    @field_validator("printer_id", mode="before")
    @classmethod
    def normalize_printer_id(cls, value: object) -> str:
        normalized = normalize_printer_profile_id(str(value or ""))
        return normalized or DEFAULT_PRINTER_ID

    @field_validator("slicer", mode="before")
    @classmethod
    def normalize_slicer(cls, value: object) -> str:
        normalized = normalize_slicer_software_id(str(value or ""))
        return normalized or DEFAULT_SLICER_ID

    @field_validator("nozzle_size", mode="before")
    @classmethod
    def normalize_nozzle(cls, value: object, info: ValidationInfo) -> str:
        if str(info.data.get("device_profile_id") or "").strip():
            return format_native_nozzle_size(value) or "0.4"
        return normalize_nozzle_size(value) or "0.4"
