"""Public Python package for the native SVG geometry engine."""

from __future__ import annotations

from ._lumina_svg_core import (
    GeometryCollection,
    NativeResult,
    PaintCommand,
    PaintStrokeStyle,
    RECORDER_SCHEMA_VERSION,
    RESULT_SCHEMA_VERSION,
    RecorderResult,
    UnprintableFragmentCollection,
    analyze_svg,
    analyze_svg_svg,
    canonicalize_grid_regions,
    project_regions_to_grid,
    record_paint_commands,
    record_paint_commands_svg,
)

__version__ = "0.3.0"


__all__ = [
    "PaintCommand",
    "PaintStrokeStyle",
    "GeometryCollection",
    "NativeResult",
    "RecorderResult",
    "UnprintableFragmentCollection",
    "RECORDER_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION",
    "__version__",
    "analyze_svg",
    "analyze_svg_svg",
    "canonicalize_grid_regions",
    "project_regions_to_grid",
    "record_paint_commands",
    "record_paint_commands_svg",
]
