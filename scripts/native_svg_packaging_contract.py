"""Pinned SVG runtime identity shared by both desktop build entry points.

两种桌面构建入口共同使用的 SVG 运行时版本合同。
"""

from __future__ import annotations

from typing import Any


NATIVE_SVG_REQUIRED_VERSION = "0.3.1"


def validate_native_svg_runtime_version(native_module: Any) -> None:
    """Reject an SVG runtime that differs from the application dependency pin.

    拒绝与主程序固定依赖版本不一致的 SVG 运行时。

    Args:
        native_module: Imported native package. 已导入的原生包。

    Raises:
        RuntimeError: The installed version is stale or unknown.
            已安装版本过旧或未知。
    """
    installed = getattr(native_module, "__version__", "unknown")
    if installed != NATIVE_SVG_REQUIRED_VERSION:
        raise RuntimeError(
            f"Install lumina-svg-core {NATIVE_SVG_REQUIRED_VERSION} with "
            "python -m pip install --upgrade -r requirements-native-svg.txt; "
            f"installed version is {installed}."
        )
