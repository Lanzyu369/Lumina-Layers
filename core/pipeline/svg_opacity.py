"""SVG opacity detection helpers for vector/raster routing.
SVG 透明度检测辅助函数，用于矢量/光栅路径选择。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


_OPACITY_PROPERTIES = frozenset({"opacity", "fill-opacity", "stroke-opacity"})
_COLOR_PROPERTIES = frozenset({"fill", "stroke"})
_STYLE_DECL_RE = re.compile(r"([A-Za-z-]+)\s*:\s*([^;{}]+)")
_FUNCTION_ALPHA_RE = re.compile(r"(?i)\b(?:rgba|hsla)\s*\(([^)]*)\)")


def _local_name(name: str) -> str:
    if "}" in name:
        return name.rsplit("}", 1)[1]
    return name


def _parse_alpha_value(value: object) -> float | None:
    text = str(value).strip().lower()
    if not text:
        return None
    if "!important" in text:
        text = text.replace("!important", "").strip()
    if text.endswith("%"):
        try:
            return float(text[:-1].strip()) / 100.0
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def _is_partial_alpha(value: object) -> bool:
    alpha = _parse_alpha_value(value)
    return alpha is not None and 0.0 <= alpha < 1.0


def _color_has_partial_alpha(value: object) -> bool:
    text = str(value).strip()
    if not text:
        return False

    lowered = text.lower()
    if lowered.startswith("#"):
        hex_digits = lowered[1:]
        if len(hex_digits) == 4:
            try:
                return int(hex_digits[3], 16) < 15
            except ValueError:
                return False
        if len(hex_digits) == 8:
            try:
                return int(hex_digits[6:8], 16) < 255
            except ValueError:
                return False

    match = _FUNCTION_ALPHA_RE.search(text)
    if match is None:
        return False

    args = match.group(1).strip()
    if "/" in args:
        alpha_text = args.rsplit("/", 1)[1].strip()
    elif "," in args:
        alpha_text = args.rsplit(",", 1)[1].strip()
    else:
        return False
    return _is_partial_alpha(alpha_text)


def _style_uses_partial_opacity(style: object) -> bool:
    text = str(style or "")
    for name, value in _STYLE_DECL_RE.findall(text):
        key = name.strip().lower()
        if key in _OPACITY_PROPERTIES and _is_partial_alpha(value):
            return True
        if key in _COLOR_PROPERTIES and _color_has_partial_alpha(value):
            return True
    return False


def _element_uses_partial_opacity(element: ET.Element) -> bool:
    for raw_name, value in element.attrib.items():
        name = _local_name(raw_name).lower()
        if name in _OPACITY_PROPERTIES and _is_partial_alpha(value):
            return True
        if name in _COLOR_PROPERTIES and _color_has_partial_alpha(value):
            return True
        if name == "style" and _style_uses_partial_opacity(value):
            return True
    return False


def _stylesheet_uses_partial_opacity(root: ET.Element) -> bool:
    for element in root.iter():
        if _local_name(str(element.tag)).lower() != "style":
            continue
        if _style_uses_partial_opacity(element.text or ""):
            return True
    return False


def svg_uses_partial_opacity(svg_path: str) -> bool:
    """Return whether an SVG declares partial opacity that native vector cannot compose.
    判断 SVG 是否声明了原生矢量路径无法正确合成的半透明信息。

    Args:
        svg_path: Path to the SVG file. (SVG 文件路径)

    Returns:
        bool: ``True`` when element/style opacity is between 0 and 1.
            (当元素或样式透明度位于 0 和 1 之间时返回 ``True``)
    """
    try:
        root = ET.parse(svg_path).getroot()
    except (ET.ParseError, OSError, TypeError, ValueError):
        return False

    if _stylesheet_uses_partial_opacity(root):
        return True
    return any(_element_uses_partial_opacity(element) for element in root.iter())


def is_five_color_extended_mode(color_mode: object) -> bool:
    """Return whether a color mode value denotes 5-Color Extended.
    判断颜色模式值是否表示 5 色扩展模式。
    """
    text = str(getattr(color_mode, "value", color_mode) or "").lower()
    return "5" in text and "color" in text and "extended" in text


def should_use_opacity_safe_svg_raster_fallback(
    *,
    image_path: object,
    color_mode: object,
    modeling_mode: object,
) -> bool:
    """Return whether a 5-Color vector SVG should route through raster compositing.
    判断 5 色矢量 SVG 是否应改走保留透明合成的光栅路径。
    """
    mode_value = str(getattr(modeling_mode, "value", modeling_mode) or "")
    if mode_value != "vector":
        return False
    if not isinstance(image_path, str) or not image_path.lower().endswith(".svg"):
        return False
    if not is_five_color_extended_mode(color_mode):
        return False
    return svg_uses_partial_opacity(str(Path(image_path)))
