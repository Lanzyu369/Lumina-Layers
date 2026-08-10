"""Shared helpers for deriving preview colors from LUT metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
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


@dataclass(frozen=True)
class MaterialPreviewResolution:
    """Resolved preview style for one authoritative material ID.
    单个权威材料 ID 的预览样式解析结果。

    Attributes:
        material_id: Original material ID, never clamped or renumbered.
            原始材料 ID，不做截断或重编号。
        material_name: Exact name from ``slot_names[material_id]``.
            来自 ``slot_names[material_id]`` 的精确材料名。
        rgba: Resolved RGBA tuple, or ``None`` when no exact color is usable.
            解析后的 RGBA；无可用精确颜色时为 ``None``。
        source: Fixed machine-readable resolution source.
            固定、机器可读的解析来源。
        attempts: Fixed source labels attempted in order; never contains
            material names or mapping keys.（按顺序尝试的固定来源标签，不含
            材料名或映射键。）
    """

    material_id: int
    material_name: str | None
    rgba: tuple[int, int, int, int] | None
    source: str
    attempts: tuple[str, ...]

    @property
    def is_resolved(self) -> bool:
        """Return whether both material identity and preview color resolved.
        返回材料身份与预览颜色是否均已解析。
        """

        return self.material_name is not None and self.rgba is not None


def _coerce_material_rgba(value: Any) -> tuple[int, int, int, int] | None:
    """Coerce supported preview metadata to a validated RGBA tuple."""

    if isinstance(value, str):
        stripped = value.strip()
        if _HEX_COLOR_RE.match(stripped):
            return tuple(_hex_to_rgba(stripped))
        return None

    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    if len(value) < 3:
        return None

    raw_channels = list(value[:4])
    if len(raw_channels) == 3:
        raw_channels.append(255)

    channels: list[int] = []
    for channel in raw_channels:
        try:
            numeric = float(channel)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric) or numeric < 0 or numeric > 255:
            return None
        channels.append(int(round(numeric)))
    return tuple(channels)  # type: ignore[return-value]


def resolve_material_preview(
    *,
    material_id: int,
    slot_names: Sequence[object] | None,
    preview_colors: Mapping[object, object] | None,
    color_conf: Mapping[str, Any] | None,
) -> MaterialPreviewResolution:
    """Resolve one material ID without changing its filament identity.
    在不改变耗材身份的前提下解析一个材料 ID。

    ``slot_names`` is the sole source of material identity. Preview colors are
    resolved by integer ID, string ID, and exact material-name key before the
    compatible ``color_conf.preview`` and canonical-name fallbacks are tried.
    Missing or invalid metadata returns an unresolved result; callers decide
    whether a display-only fallback is acceptable or model generation must
    stop.

    ``slot_names`` 是材料身份的唯一来源。颜色依次按整数 ID、字符串 ID、
    精确材料名键解析，再尝试兼容的 ``color_conf.preview`` 与规范颜色名。
    元数据缺失或非法时返回未解析结果，由调用方决定仅显示降级还是停止生成。

    Args:
        material_id: Material ID selected from ``material_matrix``.
            从 ``material_matrix`` 选出的材料 ID。
        slot_names: Authoritative ordered material names.
            权威的有序材料名称。
        preview_colors: Runtime preview-color mapping aligned to ``slot_names``.
            与 ``slot_names`` 对齐的运行时预览颜色映射。
        color_conf: Compatibility color-system configuration.
            兼容用颜色系统配置。

    Returns:
        MaterialPreviewResolution: Identity, color, source, and fixed attempt
            labels.（材料身份、颜色、来源及固定尝试标签。）
    """

    try:
        resolved_id = int(material_id)
    except (TypeError, ValueError):
        return MaterialPreviewResolution(
            material_id=-1,
            material_name=None,
            rgba=None,
            source="invalid_material_id",
            attempts=(),
        )

    material_name: str | None = None
    if (
        resolved_id >= 0
        and isinstance(slot_names, Sequence)
        and not isinstance(slot_names, (str, bytes))
        and resolved_id < len(slot_names)
    ):
        candidate_name = str(slot_names[resolved_id]).strip()
        if candidate_name:
            material_name = candidate_name

    if material_name is None:
        return MaterialPreviewResolution(
            material_id=resolved_id,
            material_name=None,
            rgba=None,
            source="invalid_material_id",
            attempts=(),
        )

    attempts: list[str] = []

    def _try(mapping: object, key: object, label: str) -> tuple[int, int, int, int] | None:
        attempts.append(label)
        if not isinstance(mapping, Mapping) or key not in mapping:
            return None
        return _coerce_material_rgba(mapping[key])

    for mapping, key, label in (
        (preview_colors, resolved_id, "preview_int"),
        (preview_colors, str(resolved_id), "preview_str"),
        (preview_colors, material_name, "preview_name"),
    ):
        rgba = _try(mapping, key, label)
        if rgba is not None:
            return MaterialPreviewResolution(
                material_id=resolved_id,
                material_name=material_name,
                rgba=rgba,
                source=label,
                attempts=tuple(attempts),
            )

    conf_preview = color_conf.get("preview") if isinstance(color_conf, Mapping) else None
    conf_slots = color_conf.get("slots") if isinstance(color_conf, Mapping) else None
    conf_slot_aligned = (
        isinstance(conf_slots, Sequence)
        and not isinstance(conf_slots, (str, bytes))
        and 0 <= resolved_id < len(conf_slots)
        and str(conf_slots[resolved_id]).strip() == material_name
    )
    conf_candidates: list[tuple[object, str]] = []
    if conf_slot_aligned:
        conf_candidates.extend(
            (
                (resolved_id, "color_conf_int"),
                (str(resolved_id), "color_conf_str"),
            )
        )
    conf_candidates.append((material_name, "color_conf_name"))
    for key, label in conf_candidates:
        rgba = _try(conf_preview, key, label)
        if rgba is not None:
            return MaterialPreviewResolution(
                material_id=resolved_id,
                material_name=material_name,
                rgba=rgba,
                source=label,
                attempts=tuple(attempts),
            )

    attempts.append("canonical_name")
    canonical = _get_canonical_color_lookup().get(
        _normalize_color_label(material_name)
    )
    rgba = _coerce_material_rgba(canonical)
    if rgba is not None:
        return MaterialPreviewResolution(
            material_id=resolved_id,
            material_name=material_name,
            rgba=rgba,
            source="canonical_name",
            attempts=tuple(attempts),
        )

    return MaterialPreviewResolution(
        material_id=resolved_id,
        material_name=material_name,
        rgba=None,
        source="unresolved_color",
        attempts=tuple(attempts),
    )


def build_material_preview_warning_extra(
    resolution: MaterialPreviewResolution,
    *,
    slot_names: Sequence[object] | None,
    preview_colors: Mapping[object, object] | None,
    color_conf: Mapping[str, Any] | None,
    material_source: object,
) -> dict[str, Any]:
    """Build privacy-safe structured fields for an unresolved material.
    为未解析材料构建不泄露隐私的结构化日志字段。

    Args:
        resolution: Failed material preview resolution.
            未成功的材料预览解析结果。
        slot_names: Authoritative slot sequence; names are counted but never
            logged.（权威槽位序列；仅计数，不记录名称。）
        preview_colors: Runtime preview mapping; only numeric IDs and count are
            logged.（运行时预览映射；仅记录数字 ID 与数量。）
        color_conf: Compatibility color configuration; only preview count is
            logged.（兼容颜色配置；仅记录预览映射数量。）
        material_source: Fixed source family such as ``lut`` or
            ``material_archive``.（固定来源类型。）

    Returns:
        dict[str, Any]: Structured WARNING fields with no path or material
            name.（不含路径或材料名称的结构化 WARNING 字段。）
    """

    available_material_ids: set[int] = set()
    if isinstance(preview_colors, Mapping):
        for key in preview_colors:
            try:
                candidate_id = int(key)
            except (TypeError, ValueError):
                continue
            if candidate_id >= 0 and str(candidate_id) == str(key):
                available_material_ids.add(candidate_id)

    conf_preview = color_conf.get("preview") if isinstance(color_conf, Mapping) else None
    slot_count = (
        len(slot_names)
        if isinstance(slot_names, Sequence)
        and not isinstance(slot_names, (str, bytes))
        else 0
    )
    return {
        "event": "loop_material_preview_unresolved",
        "error_type": "LoopMaterialResolutionError",
        "error_message": (
            "Loop material identity or preview color could not be resolved"
        ),
        "reason": resolution.source,
        "material_id": resolution.material_id,
        "material_source": str(material_source or "lut"),
        "slot_count": slot_count,
        "preview_color_count": (
            len(preview_colors) if isinstance(preview_colors, Mapping) else 0
        ),
        "color_conf_preview_count": (
            len(conf_preview) if isinstance(conf_preview, Mapping) else 0
        ),
        "available_material_ids": sorted(available_material_ids),
        "resolution_attempts": list(resolution.attempts),
    }


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
