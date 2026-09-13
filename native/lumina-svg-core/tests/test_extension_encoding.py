"""Installed extension documentation must not depend on the OS code page."""

import importlib


def test_compensation_extension_preserves_utf8_documentation():
    module = importlib.import_module("lumina_svg_core._lumina_svg_compensation")

    assert "可选 SVG 毫米孔洞补偿" in module.__doc__
    assert "识别物理毫米坐标中的封闭孔洞" in module.find_holes_mm.__doc__
