"""Shared input-validation helpers for S01 (raster) and P01 (preview).
S01（光栅生成）与 P01（预览）输入验证共享辅助函数。

This module hosts the bits of validation logic that ``s01_input_validation``
and ``p01_preview_validation`` previously duplicated verbatim — most notably
the entire ``material_archive`` branch (~50 LOC) plus the small LUT-path
resolution and quantize-colors clamp helpers — extracted in Phase 0 Sub-PR C
(see design doc §14.2.3).

Helpers do **not** emit structured-logging events directly with hard-coded
names; they accept the caller's logger and an ``event_prefix`` so the
caller's existing event taxonomy (``s01_*`` vs ``p01_*``) is preserved
so raster and preview diagnostics remain searchable by their workflow.

公共点：
- ``_validate_vector_svg_input(ctx, *, image_path, modeling_mode)``
- ``_resolve_lut_path_or_error(ctx, *, error_prefix)``
- ``_apply_material_archive_branch(ctx, *, log, event_prefix, ...)``
- ``_clamp_quantize_colors(value)``
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from config import MATERIALS_DIR, ModelingMode, PrinterConfig
from core.material_cache import ALLOWED_GRID_RESOLUTIONS, DEFAULT_GRID_RESOLUTION, describe_palette
from core.material_lut_provider import load_materials
from core.material_lut_synthesis import (
    build_material_preview_colors,
    build_material_slot_names,
    infer_material_archive_base_channel_idx,
)
from core.lumina_box_archive import validate_lumina_box_material_archive
from core.material_optical_runtime import (
    BEER_LAMBERT_MODEL_ID,
    MaterialOpticalCompatibilityError,
    bind_material_print_backing,
    validate_material_optical_contract,
)
from core.backed_gradient_smooth import SPECTRAL_SMOOTH_MODEL_ID
from core.single_stage import resolve_saved_material_dir


__all__ = [
    "VECTOR_NATIVE_REQUIRES_SVG_DETAIL",
    "_clamp_quantize_colors",
    "_resolve_lut_path_or_error",
    "_apply_material_archive_branch",
    "MaterialArchiveProfileError",
    "load_and_validate_material_archive_profile",
    "normalize_material_archive_profile_kind",
    "_validate_vector_svg_input",
]


VECTOR_NATIVE_REQUIRES_SVG_DETAIL = (
    "⚠️ Vector Native mode requires SVG files!\n\n"
    "Your file is not an SVG. Please either:\n"
    "• Upload an SVG file, or\n"
    "• Switch to 'High-Fidelity' or 'Pixel Art' mode"
)

_MATERIAL_ARCHIVE_PROFILE_KINDS = frozenset({"stage_a", "lumina_box"})
_PROFILE_KIND_OPTICAL_MODELS = {
    "stage_a": BEER_LAMBERT_MODEL_ID,
    "lumina_box": SPECTRAL_SMOOTH_MODEL_ID,
}


class MaterialArchiveProfileError(ValueError):
    """Raised when a selected archive conflicts with its requested profile kind.

    在用户选择的耗材档案与请求的档案类型不一致时抛出。
    """

    error_type = "material_profile_kind_mismatch"


def normalize_material_archive_profile_kind(value: object | None) -> str:
    """Return the canonical archive kind, defaulting legacy requests to Stage A.

    规范化耗材档案光学类型；旧请求缺失该字段时保持 Stage A 语义。

    ``material_profile_kind`` was introduced after existing material-archive
    requests. Missing values therefore retain the legacy Stage A semantics,
    while callers that opt into Lumina Box must send ``"lumina_box"``.
    """

    if value is None:
        return "stage_a"
    normalized = str(value).strip().lower()
    if normalized in _MATERIAL_ARCHIVE_PROFILE_KINDS:
        return normalized
    accepted = ", ".join(sorted(_MATERIAL_ARCHIVE_PROFILE_KINDS))
    raise MaterialArchiveProfileError(
        "material_profile_kind must be one of: " + accepted + "."
    )


def _archive_profile_kind_from_payload(
    archive_payload: dict[str, Any],
    *,
    directory_name: str,
) -> str:
    """Read the archive-declared profile kind with legacy Stage A fallback."""

    raw_value = archive_payload.get("profile_kind")
    if raw_value is None or not str(raw_value).strip():
        return "stage_a"
    normalized = str(raw_value).strip().lower()
    if normalized not in _MATERIAL_ARCHIVE_PROFILE_KINDS:
        accepted = ", ".join(sorted(_MATERIAL_ARCHIVE_PROFILE_KINDS))
        raise MaterialArchiveProfileError(
            f"Selected material '{directory_name}' has unsupported profile_kind "
            f"{normalized!r}; expected one of: {accepted}."
        )
    return normalized


def _validate_material_params_profile_kind(
    materials: list[Any],
    *,
    profile_kind: str,
) -> None:
    """Validate optical model/protocol data against one requested archive kind."""

    try:
        contract = validate_material_optical_contract(materials)
    except MaterialOpticalCompatibilityError as exc:
        raise MaterialArchiveProfileError(
            "Selected materials have incompatible optical model or measurement "
            f"protocol: {exc}"
        ) from exc

    expected_model_id = _PROFILE_KIND_OPTICAL_MODELS[profile_kind]
    if contract.model_id != expected_model_id:
        raise MaterialArchiveProfileError(
            f"material_profile_kind={profile_kind!r} requires {expected_model_id}, "
            f"but the selected materials use {contract.model_id}. "
            "Upgrade legacy Lumina Box archives from their original measurements before conversion."
        )


def load_and_validate_material_archive_profile(
    selected_materials: list[str],
    *,
    profile_kind: object | None,
) -> tuple[str, list[Any]]:
    """Load one archive palette and verify its profile and optical contract.

    读取一组耗材档案，并校验其档案类型、光学模型和 Lumina Box 测量契约。

    This is intentionally shared by API workers and the staged pipeline. It
    blocks a Stage A/Lumina Box mix before cache construction or geometry work
    begins, and validates that every Lumina Box item shares the spectral model
    and calibration-white reference required by the optical runtime.
    """

    normalized_kind = normalize_material_archive_profile_kind(profile_kind)
    if not selected_materials:
        raise MaterialArchiveProfileError(
            "material_archive mode requires at least one selected material."
        )

    materials_root = Path(MATERIALS_DIR)
    for directory_name in selected_materials:
        if not isinstance(directory_name, str) or not directory_name.strip():
            raise MaterialArchiveProfileError(
                "selected_materials must contain non-empty archive directory names."
            )
        try:
            material_dir = resolve_saved_material_dir(materials_root, directory_name)
            material_path = material_dir / "material.json"
            archive_payload = json.loads(material_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise MaterialArchiveProfileError(
                f"Selected material archive '{directory_name}' cannot be read."
            ) from exc
        if not isinstance(archive_payload, dict):
            raise MaterialArchiveProfileError(
                f"Selected material archive '{directory_name}' is not a JSON object."
            )
        declared_kind = _archive_profile_kind_from_payload(
            archive_payload,
            directory_name=directory_name,
        )
        if declared_kind != normalized_kind:
            raise MaterialArchiveProfileError(
                f"Selected material '{directory_name}' is {declared_kind!r}, but "
                f"material_profile_kind is {normalized_kind!r}."
            )
        if normalized_kind == "lumina_box" and not validate_lumina_box_material_archive(
            material_dir,
            archive_payload,
        ):
            # The generic material loader intentionally supports legacy
            # archives and may fill absent optical metadata with historical
            # defaults. Lumina Box is a three-file protocol, so conversion
            # must require its persisted bridge and consistency metadata
            # before that compatibility path runs.
            raise MaterialArchiveProfileError(
                f"Selected Lumina Box material '{directory_name}' failed "
                "archive bridge/integrity validation."
            )

    try:
        materials = load_materials(selected_materials)
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise MaterialArchiveProfileError(
            "Selected material archives could not be loaded for optical matching."
        ) from exc
    _validate_material_params_profile_kind(materials, profile_kind=normalized_kind)
    return normalized_kind, materials


def _validate_vector_svg_input(
    ctx: dict,
    *,
    image_path: object,
    modeling_mode: ModelingMode,
) -> bool:
    """Validate and record whether an input can use native vector modeling.
    校验并记录输入是否可以使用原生矢量建模。

    Args:
        ctx: Pipeline context updated with ``is_svg_vector`` and, on mismatch,
            a user-facing ``error``.
        image_path: Source image path.
        modeling_mode: Normalized modeling mode.

    Returns:
        Whether the input is an SVG using native vector mode.
    """
    is_svg_vector = (
        modeling_mode == ModelingMode.VECTOR
        and isinstance(image_path, str)
        and image_path.lower().endswith(".svg")
    )
    ctx["is_svg_vector"] = is_svg_vector
    if (
        modeling_mode == ModelingMode.VECTOR
        and not is_svg_vector
        and isinstance(image_path, str)
        and not image_path.lower().endswith(".svg")
    ):
        ctx["error"] = VECTOR_NATIVE_REQUIRES_SVG_DETAIL
    return is_svg_vector


def _clamp_quantize_colors(value: int) -> int:
    """Clamp the K-Means colour count to the supported [8, 8192] range.
    将量化颜色数夹紧到支持的 [8, 8192] 范围内。

    The ceiling matches ``ConvertPreviewRequest.quantize_colors`` /
    ``ConvertGenerateRequest.quantize_colors`` (``le=8192``) and the
    frontend "unlock quantize colors" slider upper bound, so an unlocked
    request is no longer silently compressed back to 256.
    上限与 Pydantic 请求模型（``le=8192``）及前端"解锁量化颜色数"滑条
    对齐，勾选解锁后不会再被静默压回 256。

    Args:
        value: Requested K-Means colour count.

    Returns:
        Clamped integer in [8, 8192].
    """
    return max(8, min(8192, int(value)))


def _resolve_lut_path_or_error(
    ctx: dict,
    *,
    error_prefix: str,
) -> tuple[str | None, str | None]:
    """Resolve ``ctx['lut_path']`` to an actual filesystem path string.
    将 ``ctx['lut_path']`` 规整为实际的文件系统路径字符串。

    Accepts:
        - ``None`` -> returns ``(None, "<error_prefix>... select or upload ...")``.
        - ``str`` -> returns ``(value, None)``.
        - file-like with ``.name`` attribute -> returns ``(value.name, None)``.
        - anything else -> returns ``(None, "[ERROR] Invalid LUT file format")``.

    Args:
        ctx: Pipeline context carrying ``lut_path``.
        error_prefix: Caller-specific prefix for the "no path provided" error
            message. ``s01`` historically used
            ``"[WARNING] Please select or upload a .npy calibration file!"``;
            ``p01`` used ``"[WARNING] Please select or upload calibration file"``.
            Pass the literal full string the caller wants.

    Returns:
        Tuple ``(actual_lut_path, error_message)``. Exactly one is non-None.
    """
    lut_path = ctx.get("lut_path")
    if lut_path is None:
        return None, error_prefix
    if isinstance(lut_path, str):
        return lut_path, None
    if hasattr(lut_path, "name"):
        return lut_path.name, None
    return None, "[ERROR] Invalid LUT file format"


def _apply_material_archive_branch(
    ctx: dict,
    *,
    log: logging.Logger,
    event_prefix: str,
    default_layer_count: int = 5,
    default_layer_height_mm: float = 0.08,
) -> dict | str | None:
    """Apply the shared ``material_source == "material_archive"`` validation block.
    处理共享的 ``material_source == "material_archive"`` 验证分支。

    On success this updates ``ctx`` in place with the canonical material-archive
    keys (``actual_lut_path`` = ``"__material_archive__"``, ``color_conf``,
    ``slot_names``, ``preview_colors``, ``color_layers``, ``layer_height_mm``,
    ``_material_params``, ``material_source``, ``grid_resolution``) and emits a
    single ``f"{event_prefix}_material_archive_validated"`` debug event so the
    caller's existing event taxonomy is preserved byte-for-byte.

    On error this writes ``ctx['error']`` and returns ``"error"`` so the caller
    can early-return.

    Args:
        ctx: Pipeline context updated in place.
        log: Caller's structured logger (so log records carry the caller's
            module name, e.g. ``lumina.core.pipeline.s01_input_validation``).
        event_prefix: ``"s01"`` or ``"p01"``; used to compose event names.
        default_layer_count: Fallback color-layer count when not specified.
        default_layer_height_mm: Fallback layer height when not specified.

    Returns:
        - ``"error"`` if validation failed (``ctx['error']`` written).
        - ``"validated"`` if the material-archive branch was applied successfully.

        Note that this helper never returns ``None``; the typed signature is
        ``str`` for both outcomes so the caller can branch with a single check.
    """
    selected_materials = ctx.get("selected_materials") or []
    if not selected_materials:
        ctx["error"] = "[ERROR] No materials selected for material-archive mode"
        return "error"

    try:
        profile_kind, materials = load_and_validate_material_archive_profile(
            list(selected_materials),
            profile_kind=ctx.get("material_profile_kind"),
        )
    except (FileNotFoundError, OSError, ValueError, TypeError) as exc:
        ctx["error"] = f"[ERROR] Failed to load materials: {exc}"
        return "error"

    slot_names = build_material_slot_names(materials)
    preview_colors = build_material_preview_colors(materials)
    base_channel_idx = infer_material_archive_base_channel_idx(
        selected_materials,
        slot_names,
        preview_colors,
    )
    if profile_kind == "lumina_box":
        base_channel_idx = next((
            index for index, material in enumerate(materials)
            if material.backed_gradient_component.kind == "white"
        ), base_channel_idx)
    color_conf = {
        "name": "Material",
        "slots": slot_names,
        "preview": preview_colors,
        "map": {name: idx for idx, name in enumerate(slot_names)},
    }
    fixed_material_layer_count = int(
        ctx.get("material_layer_count") or default_layer_count
    )
    material_layer_count = (
        int(ctx.get("material_max_layer_count") or 10)
        if bool(ctx.get("material_dynamic_layer_count_enabled", False))
        else fixed_material_layer_count
    )
    material_layer_height = float(ctx.get("material_layer_height_mm") or default_layer_height_mm)

    if profile_kind == "lumina_box":
        if not ctx.get("is_svg_vector") and abs(material_layer_height - PrinterConfig.LAYER_HEIGHT) > 1e-9:
            ctx["error"] = (
                "Lumina Box raster conversion currently requires 0.08 mm layers. "
                "Choose 0.08 mm, or use native SVG vector mode for another layer height."
            )
            return "error"
        backing_index = ctx.get("material_backing_material_index")
        if backing_index is None:
            backing_index = base_channel_idx
        try:
            materials = bind_material_print_backing(
                materials,
                backing_material_index=backing_index,
                thickness_mm=float(ctx.get("spacer_thick", 1.2)),
                layer_height_mm=material_layer_height,
            )
            ctx["material_optical_context"] = {
                "optical_model_id": SPECTRAL_SMOOTH_MODEL_ID,
                "reference_id": materials[0].backed_gradient_reference.reference_id,
                "canonical_materials": describe_palette(materials),
                "backing_material_index": int(backing_index),
                "backing_thickness_mm": materials[0].backed_gradient_backing_thickness_mm,
            }
        except (TypeError, ValueError) as exc:
            ctx["error"] = f"Invalid Lumina Box backing: {exc}"
            return "error"

    ctx["actual_lut_path"] = "__material_archive__"
    ctx["color_conf"] = color_conf
    ctx["slot_names"] = slot_names
    ctx["material_types"] = {
        name: material.material_type
        for name, material in zip(slot_names, materials)
    }
    ctx["preview_colors"] = preview_colors
    ctx["color_layers"] = material_layer_count
    ctx["layer_height_mm"] = material_layer_height
    ctx["material_base_channel_idx"] = base_channel_idx
    ctx["_material_params"] = materials
    ctx["material_source"] = "material_archive"
    ctx["material_profile_kind"] = profile_kind

    # Normalise the opt-in exhaustive-cache grid_resolution onto the ctx.
    # 将选入式穷举缓存网格分辨率规整进 ctx：None 或未知值回落到默认；
    # 非白名单值同样回落并打印告警，避免用不能构建的分辨率跑整条流程。
    requested_grid: Any = ctx.get("material_grid_resolution")
    if requested_grid is None:
        resolved_grid = int(DEFAULT_GRID_RESOLUTION)
    else:
        try:
            requested_grid_int = int(requested_grid)
        except (TypeError, ValueError):
            requested_grid_int = None
        if requested_grid_int in ALLOWED_GRID_RESOLUTIONS:
            resolved_grid = requested_grid_int
        else:
            log.warning(
                "material_archive mode: ignoring unsupported "
                "material_grid_resolution=%r, falling back to default=%d",
                requested_grid,
                int(DEFAULT_GRID_RESOLUTION),
            )
            resolved_grid = int(DEFAULT_GRID_RESOLUTION)
    ctx["grid_resolution"] = resolved_grid

    log.debug(
        "material_archive mode: %d materials, %d layers, %.2f mm/layer, grid=%d",
        len(materials),
        material_layer_count,
        material_layer_height,
        resolved_grid,
        extra={
            "event": f"{event_prefix}_material_archive_validated",
            "count": len(materials),
            "layer_count": material_layer_count,
            "layer_height_mm": material_layer_height,
            "grid_resolution": resolved_grid,
        },
    )
    return "validated"
