"""Session-free LUT presentation helpers used by local API routers.
本地主应用 API 路由使用的、会话无关的 LUT 展示层辅助函数。

These helpers were previously private functions inside
``api/routers/lut.py``. They are pure (no FastAPI session/state dependency)
and stay shared within the main app so LUT endpoints keep identical response
shapes without copy-pasting the logic. The main router re-exports them to
preserve its existing module-level names (some are monkeypatched by canary
tests).

这些辅助函数原本是 ``api/routers/lut.py`` 内的私有函数。它们是纯函数（不依赖
FastAPI 会话/状态），现在作为主应用内部共享逻辑保留，避免 LUT 端点间复制
粘贴响应组装代码。主路由会再导出它们以保留原有的模块级名称（部分被 canary
测试 monkeypatch）。
"""

from __future__ import annotations

from functools import lru_cache
from uuid import uuid4
from pathlib import Path, PureWindowsPath
from typing import Any

import numpy as np

from api.schemas.lut import LutInfoResponseV2, PaletteEntrySchema
from config import LUTMetadata, get_capabilities, get_schema_version
from core.lut_merger import LUTMerger
from core.native_reference import (
    get_reference_db_root,
    get_reference_forward_model_root,
    get_reference_model_pack_root,
)
from utils.lut_manager import LUTManager

# Canonical hex for the well-known primary / secondary channel names used by
# ChromaPrint-style palettes. Applied as a last-resort fallback when neither
# ``palette[c].hex_color`` nor the LUT's pure-stack recipe yields a colour,
# so the custom recipe dialog's swatches never degrade to a neutral grey for
# standard primaries like Cyan / Magenta / Yellow / Black / White / RGB.
# 用于 ChromaPrint 风格调色板的通道规范色：当 palette 元数据没有 hex_color、
# 且 LUT 没有纯通道堆叠配方可供反查时作为兜底，保证对话框色块对常见原色
# （Cyan / Magenta / Yellow / Black / White / RGB）永远不是灰色。
_CANONICAL_PRIMARY_HEX: dict[str, str] = {
    "cyan": "#00B7EB",
    "magenta": "#E6007E",
    "yellow": "#FFD400",
    "black": "#111111",
    "white": "#F5F5F5",
    "red": "#E53935",
    "green": "#43A047",
    "blue": "#1E88E5",
    "orange": "#FB8C00",
    "purple": "#8E24AA",
    "pink": "#EC407A",
    "gray": "#9E9E9E",
    "grey": "#9E9E9E",
    "brown": "#795548",
}


def canonicalize_public_color_mode(color_mode: str | None) -> str | None:
    """Normalize legacy/internal color mode labels for public API responses.
    将旧版/内部颜色模式标签规范化为公开 API 使用的名称。

    Args:
        color_mode: Raw color-mode label, possibly legacy/internal. (原始颜色模式标签)

    Returns:
        Canonical public color-mode string, or the original value when it is
        not a string. (规范化后的颜色模式；非字符串时原样返回)
    """
    if not isinstance(color_mode, str):
        return color_mode
    return LUTManager._canonicalize_legacy_color_mode(color_mode) or color_mode.strip()


def canonicalize_source_catalog_color_modes(catalog: dict) -> dict:
    """Canonicalize color-mode fields inside a source-catalog dict.
    规范化源目录字典内的颜色模式字段。

    Args:
        catalog: Raw source catalog with ``legacy_groups`` and
            ``native_brand_groups``. (含传统分组与原生品牌分组的原始目录)

    Returns:
        New catalog dict with canonicalized ``color_mode`` fields.
            (颜色模式字段已规范化的新目录字典)
    """
    legacy_groups = [
        {
            **group,
            "items": [
                {
                    **item,
                    "color_mode": canonicalize_public_color_mode(item.get("color_mode")),
                }
                for item in group.get("items", [])
            ],
        }
        for group in catalog.get("legacy_groups", [])
    ]
    native_brand_groups = [
        {
            **group,
            "db_options": [
                {
                    **option,
                    "color_mode": canonicalize_public_color_mode(option.get("color_mode")),
                }
                for option in group.get("db_options", [])
            ],
        }
        for group in catalog.get("native_brand_groups", [])
    ]
    return {
        **catalog,
        "legacy_groups": legacy_groups,
        "native_brand_groups": native_brand_groups,
    }


def _public_lut_reference_roots() -> tuple[tuple[str, Path], ...]:
    return (
        ("lut-preset", Path(LUTManager.LUT_PRESET_DIR)),
        ("reference-db", get_reference_db_root()),
        ("reference-pack", get_reference_model_pack_root()),
        ("reference-model", get_reference_forward_model_root()),
    )


def _lut_reference_suffix(path_text: str) -> str:
    suffix = PureWindowsPath(path_text).suffix or Path(path_text).suffix
    return suffix.lower()


@lru_cache(maxsize=512)
def _opaque_lut_reference(path_text: str) -> str:
    return f"lut-ref/{uuid4().hex}{_lut_reference_suffix(path_text)}"


def _is_absolute_path_like(path_text: str) -> bool:
    windows_path = PureWindowsPath(path_text)
    normalized = path_text.strip()
    return (
        normalized.startswith(("/", "\\"))
        or Path(path_text).is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
    )


def _safe_relative_lut_reference(path_text: str) -> str | None:
    normalized = path_text.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    parts = tuple(part for part in normalized.split("/") if part and part != ".")
    if not parts or any(part == ".." or part.startswith("~") for part in parts):
        return None
    return "/".join(parts)


def public_lut_path_reference(path: str | Path | None) -> str:
    """Return a stable non-sensitive reference for public LUT API payloads.
    返回公开 LUT API 载荷使用的稳定非敏感引用。

    Args:
        path: Internal filesystem path or legacy relative path.
            (内部文件路径或旧版相对路径)

    Returns:
        A public reference that never exposes user directories or unknown
        absolute filenames. Known application roots are represented as
        relative catalog references; unknown absolute paths are opaque
        references. (不暴露用户目录或未知绝对文件名的公开引用)
    """
    path_text = str(path or "").strip()
    if not path_text:
        return ""

    try:
        resolved_path = Path(path_text).resolve(strict=False)
        for public_root, root_path in _public_lut_reference_roots():
            resolved_root = Path(root_path).resolve(strict=False)
            try:
                relative = resolved_path.relative_to(resolved_root)
            except ValueError:
                continue
            relative_text = relative.as_posix().strip("/")
            if relative_text:
                return f"{public_root}/{relative_text}"
    except (OSError, RuntimeError, ValueError):
        pass

    if _is_absolute_path_like(path_text):
        return _opaque_lut_reference(path_text)

    safe_relative = _safe_relative_lut_reference(path_text)
    if safe_relative is not None:
        return safe_relative
    return _opaque_lut_reference(path_text)


def public_lut_source_catalog_paths(catalog: dict) -> dict:
    """Replace source-catalog filesystem paths with public LUT references.
    将源目录中的文件系统路径替换为公开 LUT 引用。
    """
    legacy_groups = [
        {
            **group,
            "items": [
                {
                    **item,
                    "path": public_lut_path_reference(item.get("path")),
                }
                for item in group.get("items", [])
            ],
        }
        for group in catalog.get("legacy_groups", [])
    ]
    native_brand_groups = [
        {
            **group,
            "db_options": [
                {
                    **option,
                    "path": public_lut_path_reference(option.get("path")),
                }
                for option in group.get("db_options", [])
            ],
        }
        for group in catalog.get("native_brand_groups", [])
    ]
    return {
        **catalog,
        "legacy_groups": legacy_groups,
        "native_brand_groups": native_brand_groups,
    }


def canonicalize_public_color_mode_fields(value: Any) -> Any:
    """Recursively canonicalize every ``color_mode`` field in a payload.
    递归规范化载荷中的每个 ``color_mode`` 字段。

    Args:
        value: Arbitrary JSON-like value (dict/list/scalar). (任意 JSON 形态值)

    Returns:
        Same structure with all ``color_mode`` fields canonicalized.
            (所有 ``color_mode`` 字段已规范化的同构数据)
    """
    if isinstance(value, dict):
        return {
            key: (
                canonicalize_public_color_mode(item)
                if key == "color_mode"
                else canonicalize_public_color_mode_fields(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [canonicalize_public_color_mode_fields(item) for item in value]
    return value


def dedupe_warnings(warnings: list[str]) -> list[str]:
    """Preserve warning order while removing duplicates.
    保持警告顺序并移除重复项。

    Args:
        warnings: Ordered warning strings, possibly with duplicates. (含重复的有序警告)

    Returns:
        De-duplicated warnings in first-seen order. (按首次出现顺序去重的警告)
    """
    seen: set[str] = set()
    result: list[str] = []
    for warning in warnings:
        if warning and warning not in seen:
            seen.add(warning)
            result.append(warning)
    return result


def recipe_matches_pattern(
    recipe: list[int],
    palette_letters: list[str],
    pattern: str,
) -> bool:
    """Match a recipe's channel-letter sequence against a wildcard pattern.
    将配方的通道字母序列与通配模式进行匹配。

    Args:
        recipe: Channel indices of one recipe. (单条配方的通道索引)
        palette_letters: Per-channel single-letter labels. (各通道的单字母标签)
        pattern: Pattern using ``?`` (any one) and ``*`` (any run). (通配模式)

    Returns:
        ``True`` when the recipe matches the pattern. (匹配时返回 True)
    """
    normalized = pattern.replace("-", "").strip().upper()
    if not normalized:
        return True
    letters = [palette_letters[idx] if 0 <= idx < len(palette_letters) else "?" for idx in recipe]
    i = 0
    j = 0
    while i < len(normalized) and j < len(letters):
        token = normalized[i]
        if token == "*":
            if i == len(normalized) - 1:
                return True
            next_token = normalized[i + 1]
            while j < len(letters) and next_token not in ("?", letters[j]):
                j += 1
            i += 1
            continue
        if token != "?" and token != letters[j]:
            return False
        i += 1
        j += 1
    while i < len(normalized) and normalized[i] == "*":
        i += 1
    return i == len(normalized) and j == len(letters)


def canonical_primary_hex(color_name: str | None) -> str | None:
    """Return the canonical ``#RRGGBB`` for well-known primary channel names.
    返回常见原色通道名对应的规范 ``#RRGGBB``（大小写不敏感，找不到返回 ``None``）。

    Args:
        color_name: Channel color name, e.g. ``"Cyan"``. (通道颜色名)

    Returns:
        Canonical hex string, or ``None`` when unknown. (规范 hex；未知时为 None)
    """
    if not color_name:
        return None
    return _CANONICAL_PRIMARY_HEX.get(color_name.strip().lower())


def pure_channel_hex(
    rgb: np.ndarray | None,
    stacks: np.ndarray | None,
    channel_idx: int,
) -> str | None:
    """Derive ``#RRGGBB`` for a palette channel from its pure-stack recipe.
    从"纯通道"配方（每一层都是同一通道）反查 LUT 得到该通道的代表色 hex。

    Args:
        rgb: ``(N, 3)`` uint8 array of per-recipe RGB values, or ``None``.
            (每配方 RGB 数组)
        stacks: ``(N, layers)`` int array of per-recipe channel indices, or
            ``None``. (每配方通道索引数组)
        channel_idx: Palette channel index to resolve. (调色板通道索引)

    Returns:
        ``"#RRGGBB"`` when a pure-stack recipe exists, otherwise ``None``.
            (存在纯通道配方时返回 hex，否则 None)
    """
    if rgb is None or stacks is None:
        return None
    rgb_arr = np.asarray(rgb)
    stacks_arr = np.asarray(stacks)
    if rgb_arr.ndim != 2 or stacks_arr.ndim != 2:
        return None
    if stacks_arr.shape[0] != rgb_arr.shape[0] or stacks_arr.shape[1] == 0:
        return None
    target = np.full(stacks_arr.shape[1], channel_idx, dtype=stacks_arr.dtype)
    matches = np.where(np.all(stacks_arr == target, axis=1))[0]
    if matches.size == 0:
        return None
    row = rgb_arr[int(matches[0])]
    if row.shape[-1] < 3:
        return None
    r, g, b = (int(row[0]), int(row[1]), int(row[2]))
    return f"#{r:02X}{g:02X}{b:02X}"


def preview_color_to_hex(raw: object) -> str | None:
    """Convert a cached preview RGBA/RGB row to ``#RRGGBB``.
    将缓存中的 RGB/RGBA 行转换为 ``#RRGGBB``。

    Args:
        raw: A list/tuple with at least 3 numeric channels. (含至少3个数值通道的行)

    Returns:
        Hex string, or ``None`` when the row is invalid. (无效时返回 None)
    """
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    try:
        r, g, b = (int(raw[0]), int(raw[1]), int(raw[2]))
    except (TypeError, ValueError):
        return None
    if not all(0 <= value <= 255 for value in (r, g, b)):
        return None
    return f"#{r:02X}{g:02X}{b:02X}"


def cached_preview_color_hex(preview_colors: object, idx: int) -> str | None:
    """Read channel ``idx`` from ``preview_colors`` with int/string keys.
    使用整数/字符串键从 ``preview_colors`` 读取第 ``idx`` 通道。

    Args:
        preview_colors: Mapping of channel index to RGB(A) row. (通道索引到颜色行的映射)
        idx: Channel index to read. (要读取的通道索引)

    Returns:
        Hex string, or ``None`` when missing/invalid. (缺失或无效时返回 None)
    """
    if not isinstance(preview_colors, dict):
        return None
    raw = preview_colors.get(idx)
    if raw is None:
        raw = preview_colors.get(str(idx))
    return preview_color_to_hex(raw)


def build_lut_info_from_path(path: str, display_name: str) -> LutInfoResponseV2:
    """Assemble :class:`LutInfoResponseV2` from a LUT file on disk.
    从磁盘上的 LUT 文件组装 ``LutInfoResponseV2``。

    Shared by the named-LUT endpoint and the session-scoped endpoint so that
    material-archive / native bundle sessions expose the same channel palette
    shape as legacy LUTs.

    Args:
        path: Absolute path of a LUT file. (LUT 文件绝对路径)
        display_name: Name returned in the response ``name`` field.
            (响应 ``name`` 字段中的显示名称)

    Returns:
        LutInfoResponseV2: Channel palette + capability flags for the LUT.
            (LUT 的通道调色板与能力标志)
    """
    detected_mode, color_count = LUTMerger.detect_color_mode(path)
    inferred_mode = LUTManager.infer_color_mode(Path(path).name, path)
    color_mode = inferred_mode if detected_mode in {"4-Color", "6-Color"} else detected_mode
    color_mode = canonicalize_public_color_mode(color_mode)

    # 加载元数据（如果 load_lut_with_metadata 可用）
    metadata = LUTMetadata()
    _rgb: np.ndarray | None = None
    _stacks: np.ndarray | None = None
    try:
        _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)
    except (AttributeError, NotImplementedError, Exception):
        # load_lut_with_metadata() 尚未实现时回退使用默认空元数据
        pass

    palette_schema = [
        PaletteEntrySchema(
            color=e.color,
            material=e.material,
            hex_color=(
                e.hex_color
                or pure_channel_hex(_rgb, _stacks, channel_idx)
                or canonical_primary_hex(e.color_name)
                or canonical_primary_hex(e.color)
            ),
            color_name=e.color_name,
        )
        for channel_idx, e in enumerate(metadata.palette)
    ]

    return LutInfoResponseV2(
        name=display_name,
        color_mode=color_mode,
        color_count=color_count,
        palette=palette_schema,
        max_color_layers=metadata.max_color_layers,
        layer_height_mm=metadata.layer_height_mm,
        line_width_mm=metadata.line_width_mm,
        base_layers=metadata.base_layers,
        base_channel_idx=metadata.base_channel_idx,
        layer_order=metadata.layer_order,
        schema_version=get_schema_version(metadata),
        capabilities=get_capabilities(metadata),
        supports_predictive_match=metadata.supports_predictive_match(),
        supports_dynamic_layer_height=metadata.supports_dynamic_layer_height(),
        supports_dynamic_layer_count=metadata.supports_dynamic_layer_count(),
        supports_custom_recipe=metadata.supports_custom_recipe(),
        source_kind=metadata.get_source_kind(),
        supported_modes=metadata.get_supported_modes(),
    )
