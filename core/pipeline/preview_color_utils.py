"""Shared helpers for deriving preview colors from LUT metadata."""

from __future__ import annotations

import re
from typing import Any

_HEX_COLOR_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")
_CAMEL_CASE_RE = re.compile(r"([a-z])([A-Z])")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_PREFIX_RE = re.compile(r"^(?:slot|channel|material)\s*\d+\s*[:\-]?\s*", re.IGNORECASE)


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


def build_palette_preview_colors(palette: list[Any], color_conf: dict[str, Any]) -> tuple[list[str], dict[int, list[int]]]:
    """Build slot names and preview RGBA values from LUT metadata."""
    slot_names = [getattr(entry, "color", "") for entry in palette]
    preview_colors = {
        idx: (
            _hex_to_rgba(entry.hex_color)
            if isinstance(getattr(entry, "hex_color", None), str) and _HEX_COLOR_RE.match(entry.hex_color.strip())
            else _resolve_color_conf_preview(entry, idx, color_conf)
        )
        for idx, entry in enumerate(palette)
    }
    return slot_names, preview_colors
