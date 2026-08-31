"""Shared source-coordinate contracts for Lumina vector geometry."""


# The legacy SVG parser applies this threshold before its source geometry is
# scaled into millimetres. Keep native and legacy component census identical.
LEGACY_MIN_COMPONENT_AREA_SOURCE_UNITS_SQUARED = 0.01
