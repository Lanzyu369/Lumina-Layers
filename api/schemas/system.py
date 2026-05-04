"""Lumina Studio API system schemas."""

from dataclasses import dataclass

from pydantic import BaseModel, StrictBool


class PrinterInfo(BaseModel):
    """Printer metadata exposed to frontend."""

    id: str
    display_name: str
    brand: str
    bed_width: int
    bed_depth: int
    bed_height: int
    supported_nozzle_sizes: list[str] = ["0.2", "0.4"]
    supported_slicers: list[str] = []


class PrinterListResponse(BaseModel):
    """Response for GET /api/system/printers."""

    status: str
    printers: list[PrinterInfo]


class CacheCleanupDetails(BaseModel):
    """Detailed cache cleanup statistics."""

    registry_cleaned: int
    sessions_cleaned: int
    output_files_cleaned: int


class ClearCacheResponse(BaseModel):
    """Response body for cache cleanup."""

    status: str
    message: str
    deleted_files: int
    freed_bytes: int
    details: CacheCleanupDetails


@dataclass
class ClearCacheResult:
    """Internal aggregate result for perform_cache_cleanup."""

    registry_cleaned: int
    sessions_cleaned: int
    output_files_cleaned: int
    total_freed_bytes: int


class UserSettings(BaseModel):
    """User settings persisted in user_settings.json."""

    last_lut: str = ""
    last_modeling_mode: str = "high-fidelity"
    last_color_mode: str = "4-Color (RYBW)"
    last_slicer: str = ""
    palette_mode: str = "swatch"
    enable_crop_modal: StrictBool = True
    printer_model: str = "bambu-h2d"
    slicer_software: str = "BambuStudio"
    custom_slicer_path: str = ""
    custom_slicer_id: str = ""
    nozzle_size: str = "0.4"
    enable_base_layer_height_modifier: StrictBool = True


class UserSettingsResponse(BaseModel):
    """Response for GET /api/system/settings."""

    status: str
    settings: UserSettings


class SaveSettingsResponse(BaseModel):
    """Response for POST /api/system/settings."""

    status: str
    message: str


class StatsResponse(BaseModel):
    """Response for GET /api/system/stats."""

    calibrations: int = 0
    extractions: int = 0
    conversions: int = 0


class SlicerInfo(BaseModel):
    """Slicer software metadata."""

    id: str
    display_name: str


class SlicerListResponse(BaseModel):
    """Response for GET /api/system/slicers."""

    status: str
    slicers: list[SlicerInfo]
