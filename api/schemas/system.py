"""Lumina Studio API system schemas."""

from dataclasses import dataclass
import math
from typing import Any, Literal

from pydantic import BaseModel, Field, StrictBool, field_validator


_DEFAULT_MEASUREMENT_BACKING_PERCENT_XYZ = (19.8, 19.7, 24.7)


def _default_measurement_backing_percent_xyz() -> list[float]:
    """Return an independent default XYZ triplet for each settings instance."""
    return list(_DEFAULT_MEASUREMENT_BACKING_PERCENT_XYZ)


class DeviceProfileInfo(BaseModel):
    """Slicer-scoped machine registry device profile metadata."""

    device_profile_id: str
    machine_profile_id: str
    slicer_id: str
    nozzle_size: str
    source_profile_name: str
    revision: str
    supported: bool = True
    build_plates: list["BuildPlateInfo"] = Field(default_factory=list)
    default_build_plate_id: str = ""


class BuildPlateInfo(BaseModel):
    """Slicer-native build plate available for one machine."""

    id: str
    display_name: str
    display_name_zh: str = ""
    image_url: str


class PrinterInfo(BaseModel):
    """Printer metadata exposed to frontend."""

    id: str
    display_name: str
    brand: str
    bed_width: int
    bed_depth: int
    bed_height: int
    supported_nozzle_sizes: list[str] = Field(default_factory=lambda: ["0.2", "0.4"])
    supported_slicers: list[str] = Field(default_factory=list)
    thumbnail: str = ""
    device_profiles: list[DeviceProfileInfo] = Field(default_factory=list)


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

    language: Literal["zh", "en"] = "zh"
    theme: Literal["light", "dark"] = "light"
    last_lut: str = ""
    last_modeling_mode: str = "high-fidelity"
    last_color_mode: str = "4-Color (RYBW)"
    last_slicer: str = ""
    last_bed_label: str = "256×256 mm"
    palette_mode: str = "swatch"
    enable_crop_modal: StrictBool = True
    enable_blur: StrictBool = True
    enable_fancy_loading: StrictBool = True
    enable_witty_loading: StrictBool = True
    enable_completion_notifications: StrictBool = False
    enable_smooth_vector_preview: StrictBool = True
    preserve_upload_filename_for_3mf: StrictBool = False
    printer_model: str = "bambu-h2d"
    slicer_software: str = "BambuStudio"
    custom_3mf_template_id: str | None = None
    device_profile_id: str = "BambuStudio:bbl:bambu-lab-h2d:0.4"
    build_plate_id: str = ""
    build_plate_selections: dict[str, str] = Field(default_factory=dict)
    custom_slicer_path: str = ""
    custom_slicer_id: str = ""
    nozzle_size: str = "0.4"
    enable_base_layer_height_modifier: StrictBool = True
    enable_wipe_tower_auto_placement: StrictBool = True
    enable_solver_cache_grid_selection: StrictBool = False
    solver_cache_grid_resolution: Literal[64, 128, 256, 512, 1024, 2048] = 64
    svg_pixels_per_mm: float = Field(default=10.0, ge=2.0, le=50.0)
    material_delta_e00_tolerance: float = Field(default=0.5, ge=0.0, le=5.0)
    auto_replace_gradient_banding: StrictBool = False
    generated_file_directory: str = Field(default="", max_length=1024)
    measurement_backing_percent_xyz: list[float] = Field(
        default_factory=_default_measurement_backing_percent_xyz,
        description="Instrument diffuser XYZ percentages; all zeros select diffuser-free capture.",
    )

    @field_validator("measurement_backing_percent_xyz", mode="before")
    @classmethod
    def validate_measurement_backing_percent_xyz(cls, value: Any) -> list[float]:
        """Accept positive diffuser XYZ or an all-zero capture marker.
        接受正数匀光板 XYZ，或表示无匀光板采集的全零标记。
        """
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValueError(
                "measurement_backing_percent_xyz must contain exactly 3 channels"
            )

        normalized: list[float] = []
        for channel in value:
            if isinstance(channel, bool) or not isinstance(channel, (int, float)):
                raise ValueError(
                    "measurement_backing_percent_xyz channels must be finite numbers in [0, 100]"
                )
            numeric = float(channel)
            if not math.isfinite(numeric) or not 0.0 <= numeric <= 100.0:
                raise ValueError(
                    "measurement_backing_percent_xyz channels must be finite numbers in [0, 100]"
                )
            normalized.append(numeric)
        if any(channel == 0.0 for channel in normalized) and any(
            channel > 0.0 for channel in normalized
        ):
            raise ValueError(
                "measurement_backing_percent_xyz must be all positive, or all zero for diffuser-free capture"
            )
        return normalized


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
