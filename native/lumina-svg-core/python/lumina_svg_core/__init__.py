"""Public Python package for the native SVG geometry engine."""

from __future__ import annotations

from ._lumina_svg_core import (
    PaintCommand,
    PaintStrokeStyle,
    RecorderResult,
    record_paint_commands,
    record_paint_commands_svg,
)

__version__ = "0.1.0"


__all__ = [
    "PaintCommand",
    "PaintStrokeStyle",
    "RecorderResult",
    "__version__",
    "record_paint_commands",
    "record_paint_commands_svg",
]
