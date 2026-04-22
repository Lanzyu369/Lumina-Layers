"""Shared helpers for deriving preview colors from LUT metadata."""

from __future__ import annotations

import re
from typing import Any

_HEX_COLOR_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")
_CAMEL_CASE_RE = re.compile(r"([a-z])([A-Z])")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_PREFIX_RE = re.compile(r"^(?:slot|channel|material)\s*\d+\s*[:\-]?\s*", re.IGNORECASE)

# Lazy canonical name→rgba registry, built once from standard ColorSystem presets
# so a native ColorDB palette (whose entries typically carry no ``hex_color``)
# still resolves to stable colors even when the caller passes a stale
# ``color_conf`` belonging to a different, smaller color mode.
# 基于标准 ColorSystem 预设一次性构建的 "颜色名 → RGBA" 规范表，
# 用于在 native ColorDB 调色板 hex_color 缺省、且外部传入 color_conf
# 过旧（例如用户从传统 CMYW LUT 切换到反推 LUT 时 color_mode 未同步）
# 的情况下，保证每个常见颜色名都能解析到稳定且互不冲突的颜色。
_CANONICAL_COLOR_LOOKUP: dict[str, list[int]] | None = None


def _get_canonical_color_lookup() -> dict[str, list[int]]:
    """Return the cached canonical name→rgba lookup, building it on first use.

    Uses ``ColorSystem.EIGHT_COLOR`` as the primary source (widest palette),
    aliases bare "Blue" to "Deep Blue" to match the physical filament convention
    used by native ColorDB bundles, and falls back to legacy presets for any
    extra aliases. The lookup is keyed by normalized labels so it matches
    arbitrary capitalization / decoration.
    """
    global _CANONICAL_COLOR_LOOKUP
    if _CANONICAL_COLOR_LOOKUP is not None:
        return _CANONICAL_COLOR_LOOKUP

    from config import ColorSystem

    lookup: dict[str, list[int]] = {}

    def _absorb(conf: dict[str, Any]) -> None:
        preview = conf.get("preview") or {}
        slot_map = conf.get("map") or {}
        for name, slot_idx in slot_map.items():
            rgba = preview.get(slot_idx)
            if not rgba:
                continue
            normalized = _normalize_color_label(name)
            if normalized and normalized not in lookup:
                lookup[normalized] = list(rgba)

    # EIGHT_COLOR is the primary: it covers W / C / M / Y / K / Red / Deep Blue
    # / Green with the hex values native bundles actually print with.
    _absorb(ColorSystem.EIGHT_COLOR)

    # Alias bare "Blue" → Deep Blue BEFORE the legacy presets get a chance to
    # bind their own vivid-blue hex, so a native bundle palette that uses the
    # short "Blue" form keeps mapping to the 8-Color Deep Blue filament —
    # matching the previously-correct behaviour under ``color_mode='8-Color Max'``.
    # 将裸 "Blue" 别名为 Deep Blue，以匹配反推 LUT 调色板实际使用的深蓝耗材；
    # 必须放在吸收 SIX_COLOR_RYBW 之前，否则 RYBW 的鲜蓝 (#0064F0) 会抢先占位。
    deep_blue = lookup.get("deep blue")
    if deep_blue is not None:
        lookup.setdefault("blue", list(deep_blue))

    # Fill in remaining aliases from legacy presets (White/Cyan/etc. are shared
    # so these calls are mostly no-ops for standard names but keep exotic aliases
    # like BW's "Black" available on the off-chance EIGHT_COLOR skips them).
    _absorb(ColorSystem.SIX_COLOR_RYBW)
    _absorb(ColorSystem.SIX_COLOR)
    _absorb(ColorSystem.CMYW)
    _absorb(ColorSystem.RYBW)
    _absorb(ColorSystem.BW)

    _CANONICAL_COLOR_LOOKUP = lookup
    return lookup


def _lookup_canonical_rgba(entry: Any) -> list[int] | None:
    """Return the canonical RGBA for an entry's name, or None if unknown.

    根据调色板条目的 color / color_name / material 字段在规范表中查找 RGBA。
    """
    lookup = _get_canonical_color_lookup()
    for attr in ("color", "color_name", "material"):
        value = getattr(entry, attr, None)
        if not isinstance(value, str):
            continue
        normalized = _normalize_color_label(value)
        if normalized and normalized in lookup:
            return list(lookup[normalized])
    return None


def _normalize_color_label(value: Any) -> str:
    """Normalize a color label for fuzzy matching."""
    if not isinstance(value, str):
        return ""

    text = value.strip()
    if not text:
        return ""

    text = _CAMEL_CASE_RE.sub(r"\1 \2", text)
    text = _PREFIX_RE.sub("", text)

    paren_matches = re.findall(r"\(([^)]*)\)", text)
    if paren_matches:
        text = " ".join([text, *paren_matches])

    text = text.lower()
    text = _NON_ALNUM_RE.sub(" ", text)
    return " ".join(text.split())


def _hex_to_rgba(hex_color: str) -> list[int]:
    cleaned = hex_color.strip().lstrip("#")
    return [int(cleaned[0:2], 16), int(cleaned[2:4], 16), int(cleaned[4:6], 16), 255]


def _resolve_color_conf_preview(entry: Any, idx: int, color_conf: dict[str, Any]) -> list[int]:
    preview = color_conf.get("preview", {}) or {}
    slot_names = color_conf.get("slots", []) or []
    slot_map = color_conf.get("map", {}) or {}

    if isinstance(idx, int) and idx in preview:
        fallback_preview = preview[idx]
    else:
        fallback_preview = preview.get(0, [255, 255, 255, 255])

    if not slot_names or not slot_map:
        return list(fallback_preview)

    candidates = (
        getattr(entry, "color", None),
        getattr(entry, "color_name", None),
        getattr(entry, "material", None),
    )

    normalized_lookup: dict[str, int] = {}
    normalized_slots: list[tuple[str, int]] = []
    for idx, slot_name in enumerate(slot_names):
        slot_idx = slot_map.get(slot_name, idx if idx in preview else None)
        if slot_idx is None:
            continue
        normalized_slot = _normalize_color_label(slot_name)
        if normalized_slot and normalized_slot not in normalized_lookup:
            normalized_lookup[normalized_slot] = slot_idx
            normalized_slots.append((normalized_slot, slot_idx))

    for slot_name, slot_idx in slot_map.items():
        if slot_idx not in preview:
            continue
        normalized_slot = _normalize_color_label(slot_name)
        if normalized_slot and normalized_slot not in normalized_lookup:
            normalized_lookup[normalized_slot] = slot_idx
            normalized_slots.append((normalized_slot, slot_idx))

    for candidate in candidates:
        normalized_candidate = _normalize_color_label(candidate)
        if not normalized_candidate:
            continue

        if normalized_candidate in normalized_lookup:
            return list(preview.get(normalized_lookup[normalized_candidate], fallback_preview))

        candidate_tokens = set(normalized_candidate.split())
        if not candidate_tokens:
            continue

        best_idx = None
        best_score = 0
        for normalized_slot, slot_idx in normalized_slots:
            slot_tokens = set(normalized_slot.split())
            score = len(candidate_tokens & slot_tokens)
            if score > best_score:
                best_score = score
                best_idx = slot_idx

        if best_idx is not None and best_score > 0:
            return list(preview.get(best_idx, fallback_preview))

        candidate_flat = normalized_candidate.replace(" ", "")
        best_idx = None
        best_score = 0
        for normalized_slot, slot_idx in normalized_slots:
            slot_flat = normalized_slot.replace(" ", "")
            if not slot_flat:
                continue
            if candidate_flat == slot_flat:
                return list(preview.get(slot_idx, fallback_preview))
            if slot_flat in candidate_flat or candidate_flat in slot_flat:
                score = min(len(slot_flat), len(candidate_flat))
                if score > best_score:
                    best_score = score
                    best_idx = slot_idx

        if best_idx is not None:
            return list(preview.get(best_idx, fallback_preview))

    return list(fallback_preview)


def _resolve_entry_rgba(entry: Any, idx: int, color_conf: dict[str, Any]) -> list[int]:
    """Resolve an entry to RGBA with a deterministic priority order.

    按以下优先级解析调色板条目的 RGBA：
    1. ``entry.hex_color`` 有效时直接使用（调色板自带最权威）。
    2. ``entry.color`` 命中规范颜色名表时返回规范 RGBA（规避传入的
       ``color_conf`` 与调色板不匹配时的串色问题）。
    3. 否则回落到原有的 ``color_conf`` 模糊匹配逻辑（保留旧版兼容）。
    """
    hex_color = getattr(entry, "hex_color", None)
    if isinstance(hex_color, str) and _HEX_COLOR_RE.match(hex_color.strip()):
        return _hex_to_rgba(hex_color)

    canonical = _lookup_canonical_rgba(entry)
    if canonical is not None:
        return canonical

    return _resolve_color_conf_preview(entry, idx, color_conf)


def build_palette_preview_colors(palette: list[Any], color_conf: dict[str, Any]) -> tuple[list[str], dict[int, list[int]]]:
    """Build slot names and preview RGBA values from LUT metadata."""
    slot_names = [getattr(entry, "color", "") for entry in palette]
    preview_colors = {
        idx: _resolve_entry_rgba(entry, idx, color_conf)
        for idx, entry in enumerate(palette)
    }
    return slot_names, preview_colors
