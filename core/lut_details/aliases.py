"""Alias resolution for LUT details search.
LUT 详情搜索的别名解析。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Iterable


def normalize_lookup_token(value: str) -> str:
    """Normalize a free-form token for lookup and prefix matching.
    规范化自由输入 token，用于查找和前缀匹配。

    Args:
        value: Raw input string. (原始输入字符串)

    Returns:
        Normalized token with separators removed. (移除分隔符后的规范化 token)
    """

    raw = str(value or "").casefold().strip()
    return "".join(ch for ch in raw if not ch.isspace() and ch not in "-_&/\\")


def _iter_token_variants(value: str) -> tuple[str, ...]:
    text = str(value or "").strip()
    if not text:
        return ()

    variants = [normalize_lookup_token(text)]
    for part in re.split(r"[\s\-_&/\\]+", text):
        token = normalize_lookup_token(part)
        if token:
            variants.append(token)

    ordered: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        if variant and variant not in seen:
            seen.add(variant)
            ordered.append(variant)
    return tuple(ordered)


@dataclass(frozen=True)
class AliasResolver:
    """Resolve canonical manufacturer/material names and search tokens.
    解析标准化的厂商/材质名称与搜索 token。

    Args:
        manufacturers: Canonical manufacturer -> aliases. (标准厂商 -> 别名列表)
        materials: Canonical material -> aliases. (标准材质 -> 别名列表)
    """

    manufacturers: dict[str, tuple[str, ...]]
    materials: dict[str, tuple[str, ...]]

    @classmethod
    def from_file(cls, path: Path) -> "AliasResolver":
        """Load alias resolver data from JSON file.
        从 JSON 文件加载别名解析器。

        Args:
            path: Alias config path. (别名配置文件路径)

        Returns:
            AliasResolver: Loaded resolver. (已加载的解析器)
        """

        data = json.loads(path.read_text(encoding="utf-8"))
        manufacturers = {
            str(key): tuple(str(item) for item in value)
            for key, value in dict(data.get("manufacturers", {})).items()
            if isinstance(value, list)
        }
        materials = {
            str(key): tuple(str(item) for item in value)
            for key, value in dict(data.get("materials", {})).items()
            if isinstance(value, list)
        }
        return cls(manufacturers=manufacturers, materials=materials)

    def aliases_for_manufacturer(self, canonical: str) -> tuple[str, ...]:
        """Return aliases for one canonical manufacturer.
        返回某个标准厂商的全部别名。
        """

        return self.manufacturers.get(canonical, ())

    def aliases_for_material(self, canonical: str) -> tuple[str, ...]:
        """Return aliases for one canonical material.
        返回某个标准材质的全部别名。
        """

        return self.materials.get(canonical, ())

    def canonicalize_manufacturer(self, raw_value: str) -> str:
        """Canonicalize one manufacturer string.
        标准化一个厂商字符串。
        """

        return self._canonicalize(raw_value, self.manufacturers)

    def canonicalize_material(self, raw_value: str) -> str:
        """Canonicalize one material string.
        标准化一个材质字符串。
        """

        return self._canonicalize(raw_value, self.materials)

    def build_search_tokens(
        self,
        *,
        canonical: str,
        raw_values: Iterable[str] | None = None,
        aliases: Iterable[str] | None = None,
    ) -> list[str]:
        """Build normalized search tokens for frontend filtering.
        构建供前端过滤使用的规范化搜索 token。

        Args:
            canonical: Canonical display value. (标准显示值)
            raw_values: Raw discovered values. (原始发现值)
            aliases: Alias values from config. (配置中的别名)

        Returns:
            list[str]: Unique normalized tokens. (去重后的规范化 token 列表)
        """

        ordered: list[str] = []
        seen: set[str] = set()
        for value in [canonical, *(raw_values or ()), *(aliases or ())]:
            for token in _iter_token_variants(str(value)):
                if token and token not in seen:
                    seen.add(token)
                    ordered.append(token)
        return ordered

    def _canonicalize(self, raw_value: str, mapping: dict[str, tuple[str, ...]]) -> str:
        token = normalize_lookup_token(raw_value)
        if not token:
            return str(raw_value or "")
        for canonical, aliases in mapping.items():
            if normalize_lookup_token(canonical) == token:
                return canonical
            if any(normalize_lookup_token(alias) == token for alias in aliases):
                return canonical
        return str(raw_value or "")
