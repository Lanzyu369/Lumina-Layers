"""Shared LUT identity normalization helpers.
LUT 身份信息规范化工具。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from core.lut_details.aliases import AliasResolver


@lru_cache(maxsize=1)
def _default_alias_resolver() -> AliasResolver:
    """Load the default LUT alias resolver once per process.
    每个进程只加载一次默认 LUT 别名解析器。
    """

    alias_path = Path(__file__).resolve().parents[2] / "assets" / "lut_details_aliases.json"
    return AliasResolver.from_file(alias_path)


def canonicalize_lut_manufacturer(value: str | None) -> str:
    """Return the canonical manufacturer name used by LUT catalogs.
    返回 LUT 目录使用的规范厂商名称。
    """

    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    return _default_alias_resolver().canonicalize_manufacturer(raw_value).strip()
