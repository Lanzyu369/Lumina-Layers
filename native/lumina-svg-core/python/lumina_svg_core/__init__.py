"""Public Python package for the native SVG geometry engine."""

from __future__ import annotations

from ._lumina_svg_core import (
    GeometryCollection,
    NativeResult,
    PaintCommand,
    PaintStrokeStyle,
    RecorderResult,
    analyze_svg,
    analyze_svg_svg,
    record_paint_commands,
    record_paint_commands_svg,
)

__version__ = "0.1.0"


__all__ = [
    "PaintCommand",
    "PaintStrokeStyle",
    "GeometryCollection",
    "NativeResult",
    "RecorderResult",
    "__version__",
    "analyze_svg",
    "analyze_svg_svg",
    "record_paint_commands",
    "record_paint_commands_svg",
]
