"""Lightweight package exports for the staged pipeline.

This module intentionally avoids eager imports of all step modules to prevent
import cycles (for example, image_processing -> processing_ops -> pipeline).
"""

from importlib import import_module
from typing import Any

_STEP_MODULE_NAMES = {
    # raster pipeline
    "s01_input_validation",
    "s02_image_processing",
    "s03_color_replacement",
    "s04_debug_preview",
    "s05_preview_generation",
    "s06_voxel_building",
    "s07_mesh_generation",
    "s08_auxiliary_meshes",
    "s09_export_3mf",
    "s10_color_recipe",
    "s11_glb_preview",
    "s12_result_assembly",
    # preview pipeline
    "p01_preview_validation",
    "p02_lut_metadata",
    "p03_core_processing",
    "p04_cache_building",
    "p05_palette_extraction",
    "p06_bed_rendering",
}

__all__ = sorted(_STEP_MODULE_NAMES) + ["run_raster_pipeline", "run_preview_pipeline"]


def __getattr__(name: str) -> Any:
    """Lazy-load step modules and coordinator entry points on first access."""
    if name in _STEP_MODULE_NAMES:
        module = import_module(f"core.pipeline.{name}")
        globals()[name] = module
        return module
    if name in {"run_raster_pipeline", "run_preview_pipeline"}:
        coordinator = import_module("core.pipeline.coordinator")
        value = getattr(coordinator, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'core.pipeline' has no attribute '{name}'")
