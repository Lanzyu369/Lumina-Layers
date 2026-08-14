"""
Lumina Studio - BambuStudio 3MF Writer
Enhanced 3MF export with BambuStudio-compatible metadata and configurations.

Uses neroued-3mf (C++ streaming writer with Production Extension) for 3MF
packaging, and injects Bambu/Orca vendor metadata via CustomPart.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import math
import os
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
import json
import copy
import re
from typing import Any, BinaryIO, Iterable, List, Dict, Optional
import numpy as np
from PIL import Image

from api.structured_logging import get_logger
from core.backing_infill import (
    get_viewing_surface_solid_z_ranges,
    normalize_backing_infill_density_percent,
    resolve_effective_backing_infill_density_percent,
)
from core.wipe_tower_placement import (
    Rect,
    WIPE_TOWER_MANUAL_WARNING_CODE,
    WipeTowerPlacementRequest,
    WipeTowerPlacementResult,
    solve_wipe_tower_placement,
)
from utils.bambu_3mf_cover import (
    COVER_PLATE_SPECS,
    COVER_THUMBNAIL_SPECS,
    CoverPngBundle,
    CoverThumbnailBuilder,
)


log = get_logger(__name__)

# Lazy imports: avoid >60s startup cost when imported via API.
# Only loaded when export functions are actually called.
_trimesh = None
_n3mf = None
_PREVIEW_PLACEHOLDER_PNG_BYTES: Optional[bytes] = None
_RAW_ZIP_COPY_CHUNK_SIZE = 1024 * 1024
_LAYER_HEIGHT_GRID_MM = 0.02
_MAX_LAYER_HEIGHT_NOZZLE_RATIO = 0.7
_CREATOR_5_PRINTER_IDS = frozenset(
    {"flashforge-creator-5", "flashforge-creator-5-pro"}
)
_CREATOR_5_TOWER_MIN_FOOTPRINT_WIDTH_MM = 58.5
_CREATOR_5_TOWER_MIN_DEPTH_MM = 61.0
_CREATOR_5_MODEL_TOWER_CLEARANCE_MM = 7.5
_ANYCUBIC_TOWER_MIN_FOOTPRINT_WIDTH_MM = 50.0
_ANYCUBIC_TOWER_MIN_DEPTH_MM = 57.5
_ELEGOO_CC2_PREFERRED_TOP_EDGE_CLEARANCE_MM = 32.0


def _get_trimesh():
    global _trimesh
    if _trimesh is None:
        import trimesh as _tm

        _trimesh = _tm
    return _trimesh


def _get_n3mf():
    global _n3mf
    if _n3mf is None:
        import neroued_3mf as _n

        _n3mf = _n
    return _n3mf


_CONFIG_TEMPLATE_CACHE = None
_PRINTER_TEMPLATE_CACHE: dict[str, dict] = {}
_VALID_LAYER_CONFIG_FACES = frozenset({"up", "down", "double"})
_REGISTRY_PROJECT_TEMPLATE_OVERLAY_KEYS = frozenset(
    {
        "printer_settings_id",
        "printer_variant",
        "nozzle_diameter",
        "printable_area",
        "printable_height",
        "bed_exclude_area",
    }
)
_REGISTRY_MACHINE_PROJECT_OVERLAY_EXACT_KEYS = frozenset(
    {
        "best_object_pos",
        "change_filament_gcode",
        "default_filament_profile",
        "default_nozzle_volume_type",
        "default_print_profile",
        "default_wipe_tower_pos",
        "deretract_speed_extruder_change",
        "deretraction_speed",
        "extruder_colour",
        "fan_direction",
        "gcode_flavor",
        "grab_length",
        "group_algo_with_time",
        "head_wrap_detect_zone",
        "hotend_cooling_rate",
        "hotend_heating_rate",
        "layer_change_gcode",
        "long_retractions_when_cut",
        "master_extruder_id",
        "nozzle_diameter",
        "nozzle_flush_dataset",
        "nozzle_height",
        "nozzle_type",
        "nozzle_volume",
        "physical_extruder_map",
        "printable_area",
        "printable_height",
        "printer_extruder_id",
        "printer_extruder_variant",
        "printer_model",
        "printer_settings_id",
        "printer_structure",
        "printer_technology",
        "printer_variant",
        "retract_before_wipe",
        "retract_length_toolchange",
        "retract_lift_above",
        "retract_lift_below",
        "retract_restart_extra",
        "retract_restart_extra_toolchange",
        "retract_when_changing_layer",
        "retraction_distances_when_cut",
        "retraction_length",
        "retraction_minimum_travel",
        "retraction_speed",
        "scan_first_layer",
        "silent_mode",
        "single_extruder_multi_material",
        "support_air_filtration",
        "support_chamber_temp_control",
        "support_cooling_filter",
        "support_fast_purge_mode",
        "support_object_skip_flush",
        "time_lapse_gcode",
        "upward_compatible_machine",
        "wipe",
        "wipe_distance",
        "wrapping_detection_gcode",
        "wrapping_exclude_area",
        "z_hop",
        "z_hop_types",
    }
)
_REGISTRY_MACHINE_PROJECT_OVERLAY_PREFIXES = (
    "extruder_",
    "machine_",
)
_REGISTRY_PROJECT_PROFILE_EXACT_KEYS = frozenset(
    {
        "default_filament_profile",
        "default_print_profile",
    }
)
_REGISTRY_PROJECT_PROFILE_NOZZLE_LABEL_KEYS = frozenset(
    {
        "compatible_printers",
        "default_filament_profile",
        "default_print_profile",
        "filament_compatible_printers",
        "filament_settings_id",
        "inherits_group",
        "print_compatible_printers",
        "print_settings_id",
    }
)


@dataclass(frozen=True)
class _MeshExportEntry:
    """Internal 3MF mesh export descriptor.

    内部 3MF 网格导出描述。

    Attributes:
        mesh: Trimesh geometry to export. (待导出的 Trimesh 几何体)
        object_name: Unique object name stored in the 3MF object list.
            (写入 3MF 对象列表的唯一对象名)
        material_name: Shared material/slot name used for global filament tables.
            (用于全局耗材表的共享材料或槽位名)
        color_rgb: RGB tuple for the shared material. (共享材料的 RGB 颜色)
    """

    mesh: object
    object_name: str
    material_name: str
    color_rgb: tuple[int, int, int]


@dataclass(frozen=True)
class _FilamentProfile:
    family: str
    preset_label: str
    type_value: str


def _resolve_machine_registry_root() -> str:
    """Return the shared absolute machine-registry resource root.

    返回共享的机器注册表绝对资源根目录。
    """

    from core.machine_registry import resolve_machine_registry_root

    return str(resolve_machine_registry_root())


def _version_tuple(value: object) -> tuple[int, ...]:
    parts: list[int] = []
    for token in str(value or "").split("."):
        if not token.isdigit():
            return ()
        parts.append(int(token))
    return tuple(parts)


def _should_use_registry_source_version(current_version: object, source_version: object) -> bool:
    current = _version_tuple(current_version)
    source = _version_tuple(source_version)
    if not source:
        return False
    if not current:
        return True
    return source >= current


def _clean_registry_project_overlay_value(key: str, value: object) -> object:
    if key == "printable_area" and isinstance(value, list):
        return [str(item).strip() for item in value]
    return copy.deepcopy(value)


def _resource_base_dir() -> str:
    """Return the application resource root for bundled profile JSON files.

    返回内置配置资源根目录，用于读取 ``printer_profiles`` 等 JSON 文件。
    """

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.join(os.path.dirname(__file__), "..")


def _load_legacy_project_template_if_available(
    printer_id: str,
    slicer: str,
    nozzle_size: str,
) -> tuple[dict, str] | None:
    """Load the built-in project-level template for known Lumina printers.

    加载 Lumina 已内置机型的 project 级模板。该模板包含切片器打开 3MF 所需
    的打印、耗材与项目元数据；机器注册表的裸 machine preset 不能直接替代它。
    """

    from config import PRINTER_PROFILES, normalize_printer_profile_id

    normalized_printer_id = normalize_printer_profile_id(str(printer_id or ""))
    profile = PRINTER_PROFILES.get(normalized_printer_id)
    if profile is None:
        return None

    template_file = profile.get_template_file(slicer, nozzle_size=nozzle_size)
    profile_path = os.path.join(_resource_base_dir(), "printer_profiles", template_file)
    if not os.path.exists(profile_path):
        return None

    with open(profile_path, "r", encoding="utf-8") as f:
        return json.load(f), profile_path


def _align_registry_default_filament_settings_id(
    merged: dict[str, Any],
    registry_template: dict[str, Any],
) -> None:
    default_profiles = registry_template.get("filament_settings_id")
    if not default_profiles:
        default_profiles = registry_template.get("default_filament_profile")
    if isinstance(default_profiles, list) and default_profiles:
        default_profile = str(default_profiles[0] or "").strip()
    elif isinstance(default_profiles, str):
        default_profile = default_profiles.strip()
    else:
        default_profile = ""
    if not default_profile:
        return

    existing = merged.get("filament_settings_id")
    if isinstance(existing, list) and existing:
        merged["filament_settings_id"] = [default_profile] * len(existing)
    elif isinstance(existing, str) and existing.strip():
        merged["filament_settings_id"] = default_profile


def _is_snapmaker_u1_registry_profile(profile: Any) -> bool:
    return (
        str(getattr(profile, "brand", "")).casefold() == "snapmaker"
        and str(getattr(profile, "display_name", "")).casefold() == "snapmaker u1"
        and str(getattr(profile, "slicer_id", "")).strip()
        in {"OrcaSlicer", "SnapmakerOrca"}
    )


def _is_flashstudio_registry_profile(profile: Any) -> bool:
    return str(getattr(profile, "slicer_id", "")).strip() == "FlashStudio"


def _apply_snapmaker_u1_native_project_shape(
    settings: dict[str, Any],
    profile: Any,
) -> None:
    if not _is_snapmaker_u1_registry_profile(profile):
        return
    settings.pop("inherits_group", None)
    settings.pop("different_settings_to_system", None)


def _replace_nozzle_label(value: object, old_label: str, new_label: str) -> object:
    if isinstance(value, str):
        return value.replace(old_label, new_label)
    if isinstance(value, list):
        return [_replace_nozzle_label(item, old_label, new_label) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_nozzle_label(item, old_label, new_label)
            for key, item in value.items()
        }
    return copy.deepcopy(value)


def _retarget_registry_project_profile_nozzle_labels(
    merged: dict[str, Any],
    registry_template: dict[str, Any],
    *,
    legacy_nozzle_size: str,
    registry_nozzle_size: str,
) -> None:
    if legacy_nozzle_size == registry_nozzle_size:
        return
    printer_model = str(
        registry_template.get("printer_model") or merged.get("printer_model") or ""
    ).strip()
    if not printer_model:
        return

    for key in _REGISTRY_PROJECT_PROFILE_EXACT_KEYS:
        if key in registry_template:
            merged[key] = _clean_registry_project_overlay_value(key, registry_template[key])

    old_label = f"{printer_model} {legacy_nozzle_size} nozzle"
    new_label = f"{printer_model} {registry_nozzle_size} nozzle"
    for key in _REGISTRY_PROJECT_PROFILE_NOZZLE_LABEL_KEYS:
        if key in merged:
            merged[key] = _replace_nozzle_label(merged[key], old_label, new_label)
    _align_registry_default_filament_settings_id(merged, registry_template)


def _merge_registry_machine_template_into_project_template(
    legacy_template: dict[str, Any],
    registry_template: dict[str, Any],
    *,
    source_version: str,
    overlay_printer_model: bool = False,
    overlay_machine_settings: bool = False,
    overlay_all_native_settings: bool = False,
    align_default_filament_settings: bool = False,
    retarget_profile_nozzle_labels: bool = False,
    legacy_nozzle_size: str = "",
    registry_nozzle_size: str = "",
) -> dict[str, Any]:
    """Merge native machine identity into a Lumina project-level template.

    将原生切片器 machine preset 中的机型身份信息合入 Lumina 旧 project 模板。
    这样保留 Bambu/Orca 期望的 3MF project 元数据，同时允许机器注册表更新
    机型、喷嘴和版本。
    """

    merged = copy.deepcopy(legacy_template)
    for key in _REGISTRY_PROJECT_TEMPLATE_OVERLAY_KEYS:
        if key in registry_template:
            merged[key] = _clean_registry_project_overlay_value(key, registry_template[key])
    if overlay_all_native_settings:
        for key, value in registry_template.items():
            merged[key] = _clean_registry_project_overlay_value(key, value)
        if "different_settings_to_system" in registry_template:
            merged["different_settings_to_system"] = _normalize_difference_index(
                merged.get("different_settings_to_system"),
                _iter_difference_index_keys(registry_template.get("different_settings_to_system")),
            )
        _align_registry_default_filament_settings_id(merged, registry_template)
    elif overlay_machine_settings:
        for key, value in registry_template.items():
            if (
                key in _REGISTRY_MACHINE_PROJECT_OVERLAY_EXACT_KEYS
                or key.startswith(_REGISTRY_MACHINE_PROJECT_OVERLAY_PREFIXES)
            ):
                merged[key] = _clean_registry_project_overlay_value(key, value)
        if "different_settings_to_system" in registry_template:
            merged["different_settings_to_system"] = _normalize_difference_index(
                merged.get("different_settings_to_system"),
                _iter_difference_index_keys(registry_template.get("different_settings_to_system")),
            )
        _align_registry_default_filament_settings_id(merged, registry_template)
    elif align_default_filament_settings:
        for key in _REGISTRY_PROJECT_PROFILE_EXACT_KEYS:
            if key in registry_template:
                merged[key] = _clean_registry_project_overlay_value(
                    key,
                    registry_template[key],
                )
        _align_registry_default_filament_settings_id(merged, registry_template)
    if retarget_profile_nozzle_labels:
        _retarget_registry_project_profile_nozzle_labels(
            merged,
            registry_template,
            legacy_nozzle_size=legacy_nozzle_size,
            registry_nozzle_size=registry_nozzle_size,
        )
    if overlay_printer_model and "printer_model" in registry_template:
        merged["printer_model"] = copy.deepcopy(registry_template["printer_model"])

    if source_version and (
        overlay_machine_settings or overlay_all_native_settings
        or _should_use_registry_source_version(merged.get("version"), source_version)
    ):
        merged["version"] = source_version

    # A project_settings.config embedded in a 3MF must remain a project preset.
    # Native slicer machine JSON often carries system-preset-only markers; keep
    # those out of exported 3MF metadata because they can make Bambu Studio reject
    # the package as an invalid configuration file.
    for system_only_key in ("type", "instantiation", "inherits"):
        merged.pop(system_only_key, None)
    merged["name"] = "project_settings"
    merged["from"] = "project"
    return merged


def _load_registry_compatibility_project_template_if_available(
    profile: Any,
    slicer: str,
    nozzle_size: str,
) -> tuple[dict, str] | None:
    """Load a project-compatible base template for registry-only machines.

    为 registry-only 机型选择一个兼容的 project 级基底。避免把裸
    machine preset 直接写入 3MF，同时让新机型继承对应系列的 project
    工艺、擦料塔、耗材数组和切片器侧边栏元数据。
    """

    if str(getattr(profile, "brand", "")).casefold() != "bambu lab":
        return None

    display_name = str(getattr(profile, "display_name", "")).casefold()
    machine_profile_id = str(getattr(profile, "machine_profile_id", "")).casefold()
    if not any(token in display_name or token in machine_profile_id for token in ("h2", "x2")):
        if any(token in display_name or token in machine_profile_id for token in ("a2", "a1")):
            return _load_legacy_project_template_if_available(
                "bambu-a1-mini" if "mini" in display_name or "mini" in machine_profile_id else "bambu-a1",
                slicer,
                nozzle_size,
            )
        return None

    return _load_legacy_project_template_if_available(
        "bambu-h2d",
        slicer,
        nozzle_size,
    )


def _validate_registry_device_profile(
    *,
    device_profile_id: str,
    printer_id: str,
    slicer: str,
    nozzle_size: str,
    registry_path: str,
):
    """Load and validate a generated registry device profile.

    加载并校验生成的机器注册表设备配置，避免选择的切片器/喷嘴与实际
    3MF 模板混用。
    """
    from core.machine_registry import (
        MachineRegistrySelectionError,
        load_machine_registry,
        validate_device_profile_selection,
    )

    registry = load_machine_registry(registry_path)
    try:
        profile, _ = validate_device_profile_selection(
            registry,
            device_profile_id=device_profile_id,
            printer_id=printer_id,
            slicer=slicer,
            nozzle_size=nozzle_size,
        )
    except MachineRegistrySelectionError as exc:
        raise ValueError(str(exc)) from exc
    return profile


def _load_registry_device_profile_if_available(
    *,
    device_profile_id: str,
    printer_id: str,
    slicer: str,
    nozzle_size: str,
):
    """Return a validated registry device profile when registry data exists.

    存在机器注册表时返回已校验的设备配置；未显式配置环境变量且默认
    ``machine_registry`` 不存在时返回 ``None``，保持旧模板回退兼容。
    """
    registry_root = _resolve_machine_registry_root()
    registry_path = os.path.join(registry_root, "registry.json")
    if not os.path.exists(registry_path):
        if os.environ.get("LUMINA_MACHINE_REGISTRY_DIR"):
            raise ValueError(f"Machine registry not found: {registry_path}")
        return None
    return _validate_registry_device_profile(
        device_profile_id=device_profile_id,
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=nozzle_size,
        registry_path=registry_path,
    )


def _resolve_registry_template_path(*, registry_root: str, template: str) -> str:
    """Resolve a registry template path while rejecting path traversal."""
    registry_root_abs = os.path.abspath(registry_root)
    template_path_abs = os.path.abspath(os.path.normpath(os.path.join(registry_root_abs, template)))
    if os.path.commonpath([registry_root_abs, template_path_abs]) != registry_root_abs:
        raise ValueError(f"Machine registry template escapes registry root: {template}")
    if not os.path.exists(template_path_abs):
        raise ValueError(f"Machine registry template not found: {template}")
    return template_path_abs


_FILAMENT_RESIZABLE_ARRAY_KEYS = frozenset(
    [
        "nozzle_temperature",
        "nozzle_temperature_initial_layer",
        "nozzle_temperature_range_low",
        "nozzle_temperature_range_high",
        "bed_temperature",
        "bed_temperature_initial_layer",
        "activate_air_filtration",
        "additional_cooling_fan_speed",
        "additional_fan_full_speed_layer",
        "chamber_temperatures",
        "circle_compensation_speed",
        "close_additional_fan_first_x_layers",
        "close_fan_the_first_x_layers",
        "complete_print_exhaust_fan_speed",
        "cool_plate_temp",
        "cool_plate_temp_initial_layer",
        "cooling_perimeter_transition_distance",
        "cooling_slowdown_logic",
        "counter_coef_1",
        "counter_coef_2",
        "counter_coef_3",
        "counter_limit_max",
        "counter_limit_min",
        "default_filament_colour",
        "diameter_limit",
        "during_print_exhaust_fan_speed",
        "enable_overhang_bridge_fan",
        "enable_pressure_advance",
        "eng_plate_temp",
        "eng_plate_temp_initial_layer",
        "fan_cooling_layer_time",
        "fan_max_speed",
        "fan_min_speed",
        "first_x_layer_fan_speed",
        "first_x_layer_part_fan_speed",
        "full_fan_speed_layer",
        "hole_coef_1",
        "hole_coef_2",
        "hole_coef_3",
        "hole_limit_max",
        "hole_limit_min",
        "hot_plate_temp",
        "hot_plate_temp_initial_layer",
        "impact_strength_z",
        "ironing_fan_speed",
        "no_slow_down_for_cooling_on_outwalls",
        "overhang_fan_speed",
        "overhang_fan_threshold",
        "overhang_threshold_participating_cooling",
        "pre_start_fan_time",
        "pressure_advance",
        "reduce_fan_stop_start_freq",
        "required_nozzle_HRC",
        "slow_down_for_layer_cooling",
        "slow_down_layer_time",
        "supertack_plate_temp",
        "supertack_plate_temp_initial_layer",
        "temperature_vitrification",
        "textured_plate_temp",
        "textured_plate_temp_initial_layer",
    ]
)

_FILAMENT_LINEAR_GROUP_ARRAY_KEYS = frozenset(
    [
        "flush_volumes_vector",
    ]
)
_FILAMENT_SQUARE_GROUP_ARRAY_KEYS = frozenset(
    [
        "flush_volumes_matrix",
    ]
)
_CRITICAL_FILAMENT_ARRAY_KEYS = frozenset(
    [
        "filament_colour",
        "filament_multi_colour",
        "filament_settings_id",
        "filament_type",
    ]
)


_PETG_FALLBACK_VALUES = {
    "nozzle_temperature": "255",
    "nozzle_temperature_initial_layer": "245",
    "nozzle_temperature_range_low": "230",
    "nozzle_temperature_range_high": "270",
    "bed_temperature": "70",
    "bed_temperature_initial_layer": "70",
    "textured_plate_temp": "70",
    "textured_plate_temp_initial_layer": "70",
    "hot_plate_temp": "70",
    "hot_plate_temp_initial_layer": "70",
    "eng_plate_temp": "70",
    "eng_plate_temp_initial_layer": "70",
    "cool_plate_temp": "0",
    "cool_plate_temp_initial_layer": "0",
}

_CUT_RETRACTION_FILAMENT_OVERRIDE_KEYS = (
    "filament_long_retractions_when_cut",
    "filament_retraction_distances_when_cut",
)


def _infer_filament_profile(material_name: str) -> _FilamentProfile | None:
    normalized = str(material_name or "").upper()
    compact = re.sub(r"[^A-Z0-9]+", "", normalized)
    if "PETG" not in compact:
        return None
    if "PETGCF" in compact:
        return _FilamentProfile(family="PETG", preset_label="PETG-CF", type_value="PETG-CF")
    if "PETGHF" in compact:
        return _FilamentProfile(family="PETG", preset_label="PETG HF", type_value="PETG")
    if "TRANSLUCENT" in normalized or "TRANSPARENT" in normalized or "透明" in str(material_name or ""):
        return _FilamentProfile(family="PETG", preset_label="PETG Translucent", type_value="PETG")
    return _FilamentProfile(family="PETG", preset_label="PETG Basic", type_value="PETG")


def _template_filament_count(template_settings: dict) -> int:
    counts = []
    for key in ("filament_type", "filament_settings_id", "filament_vendor", "filament_ids"):
        value = template_settings.get(key)
        if isinstance(value, list):
            counts.append(len(value))
    return max(counts) if counts else 0


def _find_template_filament_index(template_settings: dict, profile: _FilamentProfile) -> int | None:
    for key in ("filament_type", "filament_settings_id"):
        value = template_settings.get(key)
        if not isinstance(value, list):
            continue
        for index, raw in enumerate(value):
            if profile.family in str(raw or "").upper():
                return index
    return None


def _mark_purge_chute_compensation_as_flush(template: dict[str, Any]) -> dict[str, Any]:
    """Exclude purge-chute extrusion from printable-bed path validation.

    将废料口补偿挤出标记为冲刷路径，避免切片器把机外废料口误判为热床外模型路径。
    """

    gcode = template.get("change_filament_gcode")
    marker = "Compensate for filament spillage during waiting temperature"
    if not isinstance(gcode, str) or marker not in gcode:
        return template

    normalized_lines: list[str] = []
    flush_active = False
    changed = False
    for line in gcode.splitlines(keepends=True):
        stripped = line.strip()
        if stripped == "; FLUSH_START":
            flush_active = True
        elif stripped == "; FLUSH_END":
            flush_active = False

        if marker in line and not flush_active:
            newline = "\r\n" if line.endswith("\r\n") else "\n"
            normalized_lines.append(f"; FLUSH_START{newline}")
            normalized_lines.append(line)
            normalized_lines.append(f"; FLUSH_END{newline}")
            changed = True
        else:
            normalized_lines.append(line)

    if not changed:
        return template
    normalized = copy.deepcopy(template)
    normalized["change_filament_gcode"] = "".join(normalized_lines)
    return normalized


def _find_template_default_filament_index(template_settings: dict) -> int:
    for key in ("filament_type", "filament_settings_id"):
        value = template_settings.get(key)
        if not isinstance(value, list):
            continue
        for index, raw in enumerate(value):
            normalized = str(raw or "").upper()
            if "PLA" in normalized and "PETG" not in normalized:
                return index
        for index, raw in enumerate(value):
            if "PETG" not in str(raw or "").upper():
                return index
    return 0


def _template_list_value(values: list, source_index: int, filament_count: int) -> object | None:
    if filament_count > 0 and len(values) == filament_count * 2:
        doubled_index = source_index * 2
        if doubled_index < len(values):
            return values[doubled_index]
    if source_index < len(values):
        return values[source_index]
    return None


def _template_default_list_value(values: list, template_settings: dict) -> object:
    source_index = _find_template_default_filament_index(template_settings)
    resolved = _template_list_value(values, source_index, _template_filament_count(template_settings))
    if resolved is not None:
        return resolved
    return values[0] if values else "0"


def _should_preserve_template_filament_slots(
    registry_profile: Any,
    template_settings: dict,
    material_count: int,
    explicit: Optional[bool] = None,
) -> bool:
    """Return whether registry exports should keep the slicer's native slot shape."""

    if explicit is not None:
        return bool(explicit)
    if registry_profile is None:
        return False
    if _is_snapmaker_u1_registry_profile(registry_profile):
        return False
    if _is_flashstudio_registry_profile(registry_profile):
        # A manually saved Flash Studio project contracts its filament arrays
        # to the active project palette, even when the source template carries
        # a wider generic palette. Preserve that project-level shape.
        return False
    return _template_filament_count(template_settings) > material_count


def _is_filament_linear_array_key(key: str) -> bool:
    return key.startswith("filament_") or key in _FILAMENT_RESIZABLE_ARRAY_KEYS


def _copy_template_group(
    values: list,
    *,
    template_count: int,
    source_index: int,
    group_size: int,
) -> list:
    if not values or template_count <= 0 or group_size <= 0:
        return []
    clamped_index = max(0, min(int(source_index), template_count - 1))
    start = clamped_index * group_size
    group = list(values[start : start + group_size])
    if len(group) == group_size:
        return [copy.deepcopy(item) for item in group]
    fallback = list(values[:group_size])
    return [copy.deepcopy(item) for item in fallback]


def _resize_filament_linear_array(
    key: str,
    values: list,
    *,
    template_settings: dict,
    material_count: int,
) -> list:
    if material_count <= 0:
        return []
    current = list(values)
    if len(current) == material_count:
        return current

    template_count = _template_filament_count(template_settings)
    preserves_group_shape = (
        template_count > 0
        and material_count <= template_count
        and (
            key in _FILAMENT_LINEAR_GROUP_ARRAY_KEYS
            or (
                key.startswith("filament_")
                and len(current) > template_count
                and len(current) % template_count == 0
            )
        )
    )
    if preserves_group_shape and template_count > 0 and len(current) % template_count == 0:
        group_size = max(1, len(current) // template_count)
        result: list = []
        for material_index in range(material_count):
            result.extend(
                _copy_template_group(
                    current,
                    template_count=template_count,
                    source_index=material_index,
                    group_size=group_size,
                )
            )
        return result

    template_value = _template_default_list_value(current, template_settings)
    return [copy.deepcopy(template_value) for _ in range(material_count)]


def _resize_filament_square_array(
    values: list,
    *,
    template_settings: dict,
    material_count: int,
) -> list:
    if material_count <= 0:
        return []
    current = list(values)
    template_count = _template_filament_count(template_settings)
    if template_count <= 0:
        return current
    if material_count > template_count:
        return current

    template_pair_count = template_count * template_count
    if template_pair_count <= 0 or len(current) % template_pair_count != 0:
        return current[: material_count * material_count]

    group_size = max(1, len(current) // template_pair_count)
    result: list = []
    for row in range(material_count):
        source_row = min(row, template_count - 1)
        for col in range(material_count):
            source_col = min(col, template_count - 1)
            source_index = source_row * template_count + source_col
            result.extend(
                _copy_template_group(
                    current,
                    template_count=template_pair_count,
                    source_index=source_index,
                    group_size=group_size,
                )
            )
    return result


def _validate_trimmed_project_filament_arrays(
    settings: dict,
    material_count: int,
    *,
    template_settings: dict,
) -> None:
    if material_count <= 0:
        raise ValueError("project filament palette is empty")

    for key in _CRITICAL_FILAMENT_ARRAY_KEYS:
        value = settings.get(key)
        if not isinstance(value, list):
            raise ValueError(f"project filament array '{key}' is missing")
        if len(value) != material_count:
            raise ValueError(
                f"project filament array '{key}' has {len(value)} entries; "
                f"expected {material_count}"
            )

    for key, value in settings.items():
        if not isinstance(value, list) or not value:
            continue
        if key in _FILAMENT_SQUARE_GROUP_ARRAY_KEYS:
            expected_base = material_count * material_count
            template_value = template_settings.get(key)
            template_length = len(template_value) if isinstance(template_value, list) else 0
            preserves_template_shape = template_length > 0 and len(value) == template_length
            if (
                not preserves_template_shape
                and (len(value) < expected_base or len(value) % expected_base != 0)
            ):
                raise ValueError(
                    f"project filament matrix '{key}' has {len(value)} entries; "
                    f"expected a multiple of {expected_base}"
                )
        elif key in _FILAMENT_LINEAR_GROUP_ARRAY_KEYS or _is_filament_linear_array_key(key):
            template_value = template_settings.get(key)
            template_length = len(template_value) if isinstance(template_value, list) else 0
            preserves_template_shape = template_length > 0 and len(value) == template_length
            if (
                not preserves_template_shape
                and (len(value) < material_count or len(value) % material_count != 0)
            ):
                raise ValueError(
                    f"project filament array '{key}' has {len(value)} entries; "
                    f"expected a multiple of {material_count}"
                )


def _collapse_orca_linear_arrays(
    settings: dict,
    material_count: int,
    *,
    template_settings: dict,
) -> None:
    """Collapse Orca's dual-variant arrays to one value per active slot.

    对 Orca 项目按实际启用槽位收敛双变体数组。Orca 的项目校验按实际耗材
    槽位解释这些数组；保留双变体长度会把未启用的变体当成越界项，导致
    5/6/8 色项目在切片前被温度保护拦截。
    """

    if material_count <= 0:
        return
    template_count = _template_filament_count(template_settings)
    if template_count <= 0 or material_count > template_count:
        return

    linear_keys = {
        "flush_volumes_vector",
        "long_retractions_when_ec",
        "retraction_distances_when_ec",
        "volumetric_speed_coefficients",
    }
    for key, value in list(settings.items()):
        if not isinstance(value, list) or len(value) <= material_count:
            continue
        if not (key.startswith("filament_") or key in linear_keys):
            continue
        if len(value) % material_count != 0:
            continue
        group_size = len(value) // material_count
        settings[key] = [
            copy.deepcopy(value[index * group_size])
            for index in range(material_count)
        ]


def _apply_filament_array_overrides(
    settings: dict,
    arrays: dict[str, list],
    *,
    preserve_template_slots: bool,
) -> None:
    if not preserve_template_slots:
        settings.update(arrays)
        if "filament_colour" in arrays:
            settings["filament_multi_colour"] = list(arrays["filament_colour"])
        return

    for key, values in arrays.items():
        existing = settings.get(key)
        if isinstance(existing, list) and len(existing) >= len(values):
            merged = list(existing)
            merged[: len(values)] = values
            settings[key] = merged
        else:
            settings[key] = values

        if key == "filament_colour":
            multi_colour = settings.get("filament_multi_colour")
            if isinstance(multi_colour, list) and len(multi_colour) >= len(values):
                merged_multi = list(multi_colour)
                merged_multi[: len(values)] = values
                settings["filament_multi_colour"] = merged_multi


def _apply_flashstudio_project_metadata(settings: dict, material_count: int) -> None:
    """Apply Flash Studio 2.3.2 routing metadata without changing process values.

    补齐 Flash Studio 2.3.2 的耗材路由元数据，但不修改 Lumina 工艺参数。
    """

    if material_count <= 0:
        return
    raw_variants = settings.get("printer_extruder_variant")
    variants = raw_variants if isinstance(raw_variants, list) else []
    default_variant = str(variants[0] if variants else "Direct Drive Standard")
    raw_volume_types = settings.get("default_nozzle_volume_type")
    volume_types = raw_volume_types if isinstance(raw_volume_types, list) else []
    default_volume_type = str(volume_types[0] if volume_types else "Standard")

    settings["default_bed_type"] = str(settings.get("default_bed_type") or "")
    settings["filament_colour_type"] = ["1"] * material_count
    settings["filament_extruder_variant"] = [default_variant] * material_count
    settings["filament_map"] = ["1"] * material_count
    settings["filament_map_mode"] = "Auto For Flush"
    settings["filament_printable"] = ["3"] * material_count
    settings["filament_self_index"] = [
        str(index) for index in range(1, material_count + 1)
    ]
    settings["nozzle_volume_type"] = [default_volume_type] * material_count
    settings["printer_agent"] = str(settings.get("printer_agent") or "")


def _iter_difference_index_keys(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif value is None:
        raw_items = []
    else:
        raw_items = [value]

    keys: list[str] = []
    for raw_item in raw_items:
        for token in str(raw_item).split(";"):
            normalized = token.strip()
            if normalized:
                keys.append(normalized)
    return keys


def _normalize_difference_index(value: Any, extra_keys: Iterable[str] = ()) -> list[str]:
    normalized_extra_keys = {str(key).strip() for key in extra_keys if str(key).strip()}
    if isinstance(value, list):
        normalized_slots = [str(item or "") for item in value]
        if not normalized_slots and not normalized_extra_keys:
            return []
        if not normalized_slots:
            normalized_slots = [""]
        first_slot_keys = {
            token.strip()
            for token in normalized_slots[0].split(";")
            if token.strip()
        }
        first_slot_keys.update(normalized_extra_keys)
        normalized_slots[0] = ";".join(sorted(first_slot_keys)) if first_slot_keys else ""
        return normalized_slots

    keys = set(_iter_difference_index_keys(value))
    keys.update(normalized_extra_keys)
    if not keys:
        return []
    return [";".join(sorted(keys))]


def _derive_filament_settings_id(existing: object, profile: _FilamentProfile) -> str:
    text = str(existing or "").strip()
    if not text:
        return profile.preset_label
    for token in (
        "PLA Basic",
        "PLA Matte",
        "PLA Silk",
        "PLA-CF",
        "PLA Metal",
        "PLA Marble",
        "PLA Wood",
        "PLA Glow",
        "PLA Galaxy",
        "PLA Aero",
        "PLA",
    ):
        if token in text:
            return text.replace(token, profile.preset_label, 1)
    return text


def _fallback_filament_value(key: str, current: object, profile: _FilamentProfile) -> object | None:
    if key == "filament_type":
        return profile.type_value
    if key == "filament_settings_id":
        return _derive_filament_settings_id(current, profile)
    if key == "filament_vendor":
        return str(current or "Bambu Lab")
    if key == "filament_ids":
        text = str(current or "")
        return "GFG00" if text.startswith("GF") else current
    if profile.family == "PETG":
        return _PETG_FALLBACK_VALUES.get(key)
    return None


def _apply_default_filament_profile(settings: dict, profiles: list[_FilamentProfile | None]) -> None:
    first_profile = next((profile for profile in profiles if profile is not None), None)
    if first_profile is None:
        return
    current = settings.get("default_filament_profile")
    if isinstance(current, list) and current:
        current[0] = _derive_filament_settings_id(current[0], first_profile)
    elif isinstance(current, str) and current.strip():
        settings["default_filament_profile"] = _derive_filament_settings_id(current, first_profile)


def _apply_material_filament_metadata(
    settings: dict,
    template_settings: dict,
    material_palette: list[tuple[str, tuple[int, int, int]]],
) -> None:
    profiles = [_infer_filament_profile(material_name) for material_name, _ in material_palette]
    if not any(profile is not None for profile in profiles):
        return

    filament_count = _template_filament_count(template_settings)
    template_indices: dict[_FilamentProfile, int | None] = {}
    num_colors = len(material_palette)
    for key in list(settings.keys()):
        if key == "filament_colour":
            continue
        if not (key.startswith("filament_") or key in _FILAMENT_RESIZABLE_ARRAY_KEYS):
            continue
        current_values = settings.get(key)
        if not isinstance(current_values, list):
            continue
        values = list(current_values)
        if len(values) < num_colors:
            fill_value = values[0] if values else ""
            values = [fill_value] * num_colors
        source_values = template_settings.get(key)
        for index, profile in enumerate(profiles):
            if profile is None:
                continue
            if profile not in template_indices:
                template_indices[profile] = _find_template_filament_index(template_settings, profile)
            source_index = template_indices[profile]
            resolved_value = None
            if isinstance(source_values, list) and source_index is not None:
                resolved_value = _template_list_value(source_values, source_index, filament_count)
            if resolved_value is None:
                current = values[index] if index < len(values) else ""
                resolved_value = _fallback_filament_value(key, current, profile)
            if resolved_value is not None and index < len(values):
                values[index] = resolved_value
        settings[key] = values

    _apply_default_filament_profile(settings, profiles)


def _disable_cut_retraction_filament_overrides(settings: dict, num_colors: int) -> None:
    for key in _CUT_RETRACTION_FILAMENT_OVERRIDE_KEYS:
        if key in settings:
            settings[key] = ["nil"] * num_colors
    long_retractions = settings.get("long_retractions_when_cut")
    if isinstance(long_retractions, list):
        settings["long_retractions_when_cut"] = ["0"] * len(long_retractions)


def _resolve_compatible_base_layer_height_mm(
    *,
    base_height_mm: float,
    nozzle_mm: float,
    fine_layer_height_mm: float,
    fixed_first_layer_height_mm: float = 0.0,
    min_layer_height_mm: float | None = None,
    max_layer_height_mm: float | None = None,
) -> float | None:
    """Return a safe coarse height that ends exactly at the backing boundary."""
    base_height = float(base_height_mm)
    nozzle = float(nozzle_mm)
    fine_layer_height = float(fine_layer_height_mm)
    fixed_first_layer_height = float(fixed_first_layer_height_mm)
    if not all(
        math.isfinite(value)
        for value in (base_height, nozzle, fine_layer_height, fixed_first_layer_height)
    ):
        return None
    if (
        base_height <= 0
        or nozzle <= 0
        or fine_layer_height < 0
        or fixed_first_layer_height < 0
        or fixed_first_layer_height >= base_height
    ):
        return None

    base_ticks = round(base_height / _LAYER_HEIGHT_GRID_MM)
    fixed_first_layer_ticks = round(fixed_first_layer_height / _LAYER_HEIGHT_GRID_MM)
    if base_ticks <= 0:
        return None
    if abs(base_height - base_ticks * _LAYER_HEIGHT_GRID_MM) > 1e-9:
        return None
    if abs(
        fixed_first_layer_height
        - fixed_first_layer_ticks * _LAYER_HEIGHT_GRID_MM
    ) > 1e-9:
        return None

    adjustable_ticks = base_ticks - fixed_first_layer_ticks
    minimum_adjustable_layers = 1 if fixed_first_layer_ticks else 2

    lower_bound = fine_layer_height
    if min_layer_height_mm is not None:
        minimum = float(min_layer_height_mm)
        if not math.isfinite(minimum) or minimum <= 0:
            return None
        lower_bound = max(lower_bound, minimum - 1e-9)

    upper_bound = nozzle * _MAX_LAYER_HEIGHT_NOZZLE_RATIO
    if max_layer_height_mm is not None:
        maximum = float(max_layer_height_mm)
        if not math.isfinite(maximum) or maximum <= 0:
            return None
        upper_bound = min(upper_bound, maximum)
    if upper_bound <= fine_layer_height:
        return None

    candidate_tick_values: list[int] = []
    for candidate_ticks in range(
        1,
        adjustable_ticks // minimum_adjustable_layers + 1,
    ):
        if adjustable_ticks % candidate_ticks:
            continue
        candidate = candidate_ticks * _LAYER_HEIGHT_GRID_MM
        if candidate <= fine_layer_height + 1e-9:
            continue
        if candidate < lower_bound - 1e-9 or candidate > upper_bound + 1e-9:
            continue
        candidate_tick_values.append(candidate_ticks)

    if not candidate_tick_values:
        return None
    nominal_ticks = nozzle * 0.5 / _LAYER_HEIGHT_GRID_MM
    selected_ticks = min(
        candidate_tick_values,
        key=lambda candidate_ticks: (abs(candidate_ticks - nominal_ticks), candidate_ticks),
    )
    return selected_ticks * _LAYER_HEIGHT_GRID_MM


def _strict_printer_layer_height_limits(template: dict) -> tuple[float | None, float | None]:
    """Return the strict limits shared by every nozzle in a printer template."""

    def positive_floats(raw_value: Any) -> list[float]:
        values = raw_value if isinstance(raw_value, (list, tuple)) else [raw_value]
        parsed: list[float] = []
        for value in values:
            try:
                candidate = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(candidate) and candidate > 0:
                parsed.append(candidate)
        return parsed

    minimums = positive_floats(template.get("min_layer_height"))
    maximums = positive_floats(template.get("max_layer_height"))
    return (max(minimums) if minimums else None, min(maximums) if maximums else None)


def build_layer_config_ranges_xml(
    *,
    base_height_mm: float,
    color_height_mm: float,
    nozzle_mm: float,
    face: str,
    fine_layer_height_mm: float = 0.08,
    initial_layer_height_mm: float | None = None,
    min_layer_height_mm: float | None = None,
    max_layer_height_mm: float | None = None,
    object_id: int = 1,
    enable_base_layer_height_modifier: bool = True,
    backing_infill_density_percent: int = 100,
    solid_depth_mm: float | None = None,
) -> bytes | None:
    """Build object-height process overrides for backing print settings.
    为底板打印设置生成对象高度范围覆盖。

    Args:
        base_height_mm (float): Backing/base thickness in millimetres.
            （底板厚度，单位为毫米）
        color_height_mm (float): Colored-region thickness in millimetres.
            （彩色区域厚度，单位为毫米）
        nozzle_mm (float): Nozzle diameter in millimetres.
            （喷嘴直径，单位为毫米）
        face (str): Face orientation selector: "up", "down", or "double".
            （朝向选择器："up"、"down" 或 "double"）
        fine_layer_height_mm (float): Fine printing layer height in millimetres.
            （细层高打印层高，单位为毫米）
        initial_layer_height_mm (float | None): Actual slicer first-layer height.
            Required for ``face="up"``; an unknown value safely skips the
            modifier.（切片器实际首层层高；``face="up"`` 时必须提供，
            未知时安全跳过修改器）
        min_layer_height_mm (float | None): Optional printer minimum layer height.
            （打印机允许的可选最小层高）
        max_layer_height_mm (float | None): Optional printer maximum layer height.
            （打印机允许的可选最大层高）
        object_id (int): One-based model-object index written into the XML payload.
            （写入 XML 载荷的模型对象序号，从 1 开始）
        enable_base_layer_height_modifier (bool): Whether to add the existing
            coarse backing layer-height override.（是否添加既有的底板粗层高覆盖）
        backing_infill_density_percent (int): Requested global backing infill
            density. Values below 100 add protected 100-percent ranges next to
            viewing surfaces when deeper backing remains sparse.
            （请求的全局底板填充率；低于 100 时，在仍有深层稀疏底板的前提下，
            为观赏面附近添加 100% 保护区间。）
        solid_depth_mm (float | None): Optional protected backing depth;
            ``None`` reads ``PrinterConfig.VIEWING_SURFACE_SOLID_DEPTH_MM``.
            （可选的受保护底板深度；``None`` 读取项目配置。）

    Returns:
        bytes | None: UTF-8 XML bytes when at least one process override is
            required, otherwise ``None``.（存在至少一个切片参数覆盖时返回 UTF-8
            XML 字节，否则返回 ``None``。）

    Raises:
        ValueError: If numeric inputs cannot be converted to floats.
            （当数值输入无法转换为浮点数时抛出）
    """
    base_height = float(base_height_mm)
    color_height = float(color_height_mm)
    nozzle = float(nozzle_mm)
    fine_layer_height = float(fine_layer_height_mm)
    initial_layer_height = (
        None
        if initial_layer_height_mm is None
        else float(initial_layer_height_mm)
    )
    normalized_face = str(face).strip().lower()

    if base_height <= 0:
        return None
    if color_height < 0 or nozzle <= 0:
        return None
    if normalized_face not in _VALID_LAYER_CONFIG_FACES:
        return None

    overrides: list[tuple[float, float, dict[str, str]]] = []
    if enable_base_layer_height_modifier and normalized_face != "double":
        has_valid_initial_layer = (
            initial_layer_height is not None
            and math.isfinite(initial_layer_height)
            and initial_layer_height > 0
        )
        if normalized_face != "up" or has_valid_initial_layer:
            coarse_lh = _resolve_compatible_base_layer_height_mm(
                base_height_mm=base_height,
                nozzle_mm=nozzle,
                fine_layer_height_mm=fine_layer_height,
                fixed_first_layer_height_mm=(
                    float(initial_layer_height)
                    if normalized_face == "up" and initial_layer_height is not None
                    else 0.0
                ),
                min_layer_height_mm=min_layer_height_mm,
                max_layer_height_mm=max_layer_height_mm,
            )
            if coarse_lh is not None:
                if normalized_face == "up":
                    coarse_min_z = 0.0
                    coarse_max_z = base_height
                else:
                    coarse_min_z = color_height
                    coarse_max_z = color_height + base_height
                overrides.append(
                    (
                        coarse_min_z,
                        coarse_max_z,
                        {
                            "extruder": "0",
                            "layer_height": f"{coarse_lh:.17g}",
                        },
                    )
                )

    effective_density = resolve_effective_backing_infill_density_percent(
        backing_infill_density_percent,
        base_height_mm=base_height,
        face=normalized_face,
        solid_depth_mm=solid_depth_mm,
    )
    if effective_density < 100:
        for min_z, max_z in get_viewing_surface_solid_z_ranges(
            base_height_mm=base_height,
            color_height_mm=color_height,
            face=normalized_face,
            solid_depth_mm=solid_depth_mm,
        ):
            overrides.append(
                (min_z, max_z, {"sparse_infill_density": "100%"})
            )

    segments = _split_layer_config_overrides(overrides)
    if not segments:
        return None
    # Bambu/Orca-family slicers require every explicit height range to carry a
    # layer height. A density-only range imports, but crashes them at slice
    # time. Preserve an existing coarse modifier and fill only missing values.
    segments = [
        (
            min_z,
            max_z,
            options
            if "layer_height" in options
            else {"layer_height": f"{fine_layer_height:.17g}", **options},
        )
        for min_z, max_z, options in segments
    ]

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<objects>",
        f' <object id="{object_id}">',
    ]
    for min_z, max_z, options in segments:
        lines.append(
            f'  <range min_z="{min_z:.17g}" max_z="{max_z:.17g}">'
        )
        for option_key, option_value in options.items():
            lines.append(
                f'   <option opt_key="{option_key}">{option_value}</option>'
            )
        lines.append("  </range>")
    lines.extend([" </object>", "</objects>", ""])
    return "\n".join(lines).encode("utf-8")


def _split_layer_config_overrides(
    overrides: list[tuple[float, float, dict[str, str]]],
) -> list[tuple[float, float, dict[str, str]]]:
    """Split overlapping Z overrides into deterministic non-overlapping ranges."""
    valid_overrides = [
        (float(start), float(end), dict(options))
        for start, end, options in overrides
        if end > start + 1e-9 and options
    ]
    if not valid_overrides:
        return []
    boundaries = sorted(
        {boundary for start, end, _options in valid_overrides for boundary in (start, end)}
    )
    segments: list[tuple[float, float, dict[str, str]]] = []
    for start, end in zip(boundaries, boundaries[1:]):
        if end <= start + 1e-9:
            continue
        active_options: dict[str, str] = {}
        for override_start, override_end, options in valid_overrides:
            if start >= override_start - 1e-9 and end <= override_end + 1e-9:
                active_options.update(options)
        if not active_options:
            continue
        if (
            segments
            and abs(segments[-1][1] - start) <= 1e-9
            and segments[-1][2] == active_options
        ):
            previous_start, _previous_end, previous_options = segments[-1]
            segments[-1] = (previous_start, end, previous_options)
        else:
            segments.append((start, end, active_options))
    return segments


def load_printer_template(
    printer_id: str,
    slicer: str = "BambuStudio",
    nozzle_size: Optional[str | float] = None,
    device_profile_id: Optional[str] = None,
) -> dict:
    """Load printer config template JSON for the given printer ID and slicer.
    加载指定机型和切片器的配置模板 JSON。

    Priority: generated machine registry when device_profile_id is provided,
    then printer_profiles/ directory, then bambu_config_template.json.
    优先使用指定 device_profile_id 对应的机器注册表模板，然后回退到
    printer_profiles/ 目录，最后回退到 bambu_config_template.json。

    Args:
        printer_id (str): Printer identifier, e.g. "bambu-h2d". (打印机标识)
        slicer (str): Slicer software identifier, e.g. "BambuStudio" or "OrcaSlicer". (切片器标识)
        nozzle_size (Optional[str | float]): Optional nozzle size variant, e.g. 0.2.
            Falls back to the base template when omitted or unavailable. (可选喷嘴尺寸变体)
        device_profile_id (Optional[str]): Slicer-scoped generated registry device profile ID.
            (可选的切片器作用域机器注册表设备配置 ID)

    Returns:
        dict: Parsed JSON configuration template. (解析后的 JSON 配置模板)
    """
    global _PRINTER_TEMPLATE_CACHE

    from config import (
        format_native_nozzle_size,
        get_printer_profile,
        normalize_nozzle_size,
        normalize_slicer_software_id,
    )

    normalized_slicer = normalize_slicer_software_id(str(slicer or ""))
    normalized_nozzle_size = normalize_nozzle_size(nozzle_size) or "0.4"
    registry_nozzle_size = format_native_nozzle_size(nozzle_size) or normalized_nozzle_size
    configured_profile = get_printer_profile(printer_id)
    if registry_nozzle_size in configured_profile.supported_nozzle_sizes:
        legacy_nozzle_size = registry_nozzle_size
    elif normalized_nozzle_size in configured_profile.supported_nozzle_sizes:
        legacy_nozzle_size = normalized_nozzle_size
    else:
        legacy_nozzle_size = "0.4"
    if device_profile_id:
        registry_root = _resolve_machine_registry_root()
        registry_path = os.path.join(registry_root, "registry.json")
        if os.path.exists(registry_path):
            profile = _validate_registry_device_profile(
                device_profile_id=device_profile_id,
                printer_id=printer_id,
                slicer=normalized_slicer,
                nozzle_size=registry_nozzle_size,
                registry_path=registry_path,
            )
            template_path_abs = _resolve_registry_template_path(
                registry_root=registry_root,
                template=profile.template,
            )
            template_stat = os.stat(template_path_abs)
            cache_key = (
                f"{printer_id}:{normalized_slicer}:{registry_nozzle_size}:registry:"
                f"{registry_root}:{device_profile_id}:{profile.revision}:"
                f"{template_path_abs}:{template_stat.st_mtime_ns}"
            )
            if cache_key in _PRINTER_TEMPLATE_CACHE:
                return copy.deepcopy(_PRINTER_TEMPLATE_CACHE[cache_key])

            with open(template_path_abs, "r", encoding="utf-8") as f:
                registry_template = json.load(f)
            legacy_template_entry = _load_legacy_project_template_if_available(
                printer_id,
                normalized_slicer,
                legacy_nozzle_size,
            )
            overlay_printer_model = False
            overlay_machine_settings = False
            overlay_all_native_settings = False
            if legacy_template_entry is None:
                legacy_template_entry = _load_registry_compatibility_project_template_if_available(
                    profile,
                    normalized_slicer,
                    registry_nozzle_size,
                )
                overlay_printer_model = legacy_template_entry is not None
                overlay_machine_settings = legacy_template_entry is not None
            if _is_flashstudio_registry_profile(profile):
                # Flash Studio resolves a complete native machine preset when
                # the user switches machines. Apply the same full machine
                # shape before Lumina's protected process values are emitted.
                overlay_all_native_settings = True
            if legacy_template_entry is not None:
                legacy_template, legacy_template_path = legacy_template_entry
                legacy_stat = os.stat(legacy_template_path)
                cache_key = (
                    f"{cache_key}:legacy_project:"
                    f"{legacy_template_path}:{legacy_stat.st_mtime_ns}"
                )
                if cache_key in _PRINTER_TEMPLATE_CACHE:
                    return copy.deepcopy(_PRINTER_TEMPLATE_CACHE[cache_key])
                template = _merge_registry_machine_template_into_project_template(
                    legacy_template,
                    registry_template,
                    source_version=(
                        ""
                        if _is_flashstudio_registry_profile(profile)
                        else profile.source_version
                    ),
                    overlay_printer_model=overlay_printer_model,
                    overlay_machine_settings=overlay_machine_settings,
                    overlay_all_native_settings=overlay_all_native_settings,
                    align_default_filament_settings=_is_snapmaker_u1_registry_profile(profile),
                    retarget_profile_nozzle_labels=(
                        registry_nozzle_size != legacy_nozzle_size
                    ),
                    legacy_nozzle_size=legacy_nozzle_size,
                    registry_nozzle_size=registry_nozzle_size,
                )
            else:
                template = registry_template
            template = _mark_purge_chute_compensation_as_flush(template)
            _PRINTER_TEMPLATE_CACHE[cache_key] = template
            log.debug(
                "Loaded printer template from machine registry",
                extra={
                    "event": "bambu_printer_template_registry_loaded",
                    "path": template_path_abs,
                    "printer_id": printer_id,
                    "slicer": normalized_slicer,
                    "nozzle_size": registry_nozzle_size,
                    "device_profile_id": device_profile_id,
                    "revision": profile.revision,
                },
            )
            return copy.deepcopy(template)
        if os.environ.get("LUMINA_MACHINE_REGISTRY_DIR"):
            raise ValueError(f"Machine registry not found: {registry_path}")

    cache_key = f"{printer_id}:{normalized_slicer}:{registry_nozzle_size}:legacy"
    if cache_key in _PRINTER_TEMPLATE_CACHE:
        return copy.deepcopy(_PRINTER_TEMPLATE_CACHE[cache_key])

    profile = configured_profile
    template_file = profile.get_template_file(normalized_slicer, nozzle_size=nozzle_size)

    # Resolve printer_profiles/ directory
    base_dir = _resource_base_dir()

    profile_path = os.path.join(base_dir, "printer_profiles", template_file)

    if os.path.exists(profile_path):
        with open(profile_path, "r", encoding="utf-8") as f:
            template = json.load(f)
        template = _mark_purge_chute_compensation_as_flush(template)
        _PRINTER_TEMPLATE_CACHE[cache_key] = template
        log.debug(
            "Loaded printer template",
            extra={
                "event": "bambu_printer_template_loaded",
                "path": profile_path,
                "printer_id": printer_id,
                "slicer": normalized_slicer,
                "nozzle_size": normalized_nozzle_size,
            },
        )
        return copy.deepcopy(template)

    # Fallback to legacy bambu_config_template.json
    fallback_path = os.path.join(base_dir, "bambu_config_template.json")
    if os.path.exists(fallback_path):
        with open(fallback_path, "r", encoding="utf-8") as f:
            template = json.load(f)
        template = _mark_purge_chute_compensation_as_flush(template)
        _PRINTER_TEMPLATE_CACHE[cache_key] = template
        log.warning(
            "Printer template not found; using fallback",
            extra={
                "event": "bambu_printer_template_fallback_used",
                "path": fallback_path,
                "printer_id": printer_id,
                "slicer": normalized_slicer,
                "nozzle_size": normalized_nozzle_size,
                "template_file": template_file,
            },
        )
        return copy.deepcopy(template)

    log.warning(
        "No printer template found",
        extra={
            "event": "bambu_printer_template_missing",
            "path": profile_path,
            "printer_id": printer_id,
            "slicer": normalized_slicer,
            "nozzle_size": normalized_nozzle_size,
            "template_file": template_file,
        },
    )
    return {}


class BambuStudio3MFWriter:
    """Enhanced 3MF writer with BambuStudio-compatible metadata.
    使用 neroued-3mf Production Extension 生成 Bambu 兼容 3MF。

    Features:
    - Embeds print settings (layer height, temperatures, speeds)
    - Adds color information to objects via BaseMaterial
    - Compatible with BambuStudio/OrcaSlicer/ElegooSlicer/SnapmakerOrca
    - C++ streaming XML serialisation with native ZIP64 support
    """

    DEFAULT_SETTINGS = {
        "layer_height": "0.08",
        "initial_layer_height": "0.08",
        "wall_loops": "1",
        "top_shell_layers": "0",
        "bottom_shell_layers": "1",
        "bottom_surface_pattern": "monotonicline",
        "elefant_foot_compensation": "0",
        "sparse_infill_density": "100%",
        "sparse_infill_pattern": "zig-zag",
        "nozzle_temperature": ["220", "220", "220", "220"],
        "bed_temperature": ["60", "60", "60", "60"],
        "filament_type": ["PLA", "PLA", "PLA", "PLA"],
        "print_speed": "100",
        "travel_speed": "150",
        "enable_support": "0",
        "brim_width": "5",
        "brim_type": "auto_brim",
    }

    def __init__(
        self,
        output_path: str,
        settings: Optional[Dict] = None,
        color_mode: str = "4-Color",
        printer_id: str = "bambu-h2d",
        slicer: str = "BambuStudio",
        nozzle_size: Optional[str | float] = None,
        watermark: str = "LuminaStudio",
        *,
        enable_base_layer_height_modifier: bool = True,
        enable_relief: bool = False,
        base_height_mm: float = 0.0,
        color_height_mm: float = 0.0,
        face_orientation: str = "down",
        backing_infill_density_percent: int = 100,
        cover_source: "str | bytes | Image.Image | None" = None,
        device_profile_id: Optional[str] = None,
        build_plate_id: Optional[str] = None,
        preserve_template_filament_slots: Optional[bool] = None,
    ):
        """Initialize 3MF writer with printer-specific template support.
        初始化 3MF 写入器，支持机型和切片器专属配置模板。

        Args:
            output_path (str): Output .3mf file path. (输出 .3mf 文件路径)
            settings (Optional[Dict]): Custom print settings overrides. (自定义打印设置覆盖)
            color_mode (str): Color mode ('4-Color', '6-Color', '8-Color', 'BW'). (颜色模式)
            printer_id (str): Printer identifier for template selection, default 'bambu-h2d'. (打印机标识)
            slicer (str): Slicer software identifier, default 'BambuStudio'. (切片器标识)
            nozzle_size (Optional[str | float]): Nozzle size variant used for template selection.
                (用于模板选择的喷嘴尺寸变体)
            watermark (str): Watermark text embedded in the 3MF ZIP structure. (嵌入 3MF ZIP 结构的水印文本)
            enable_base_layer_height_modifier (bool): Whether to emit layer_config_ranges.xml.
                （是否输出 layer_config_ranges.xml）
            enable_relief (bool): Whether variable-height relief geometry is enabled. Relief
                exports never emit ``layer_config_ranges.xml`` because no single global
                backing range is safe.（是否启用可变高度浮雕；浮雕不存在全局安全的
                底板区间，因此始终不输出 ``layer_config_ranges.xml``。）
            base_height_mm (float): Backing/base thickness used for coarse layer-height override.
                （用于粗层高覆盖的底板厚度）
            color_height_mm (float): Colored-region thickness used to place the override range.
                （用于定位覆盖区间的彩色区域厚度）
            face_orientation (str): Base orientation selector; invalid values fall back to "down".
                （底板朝向；非法值静默回退到 "down"）
            backing_infill_density_percent (int): Requested deep-backing infill
                percentage. Thin backing is promoted to 100 percent and deeper
                backing receives protected solid ranges next to viewing surfaces.
                （请求的深层底板填充百分比；薄底板会提升为 100%，较深底板会在
                观赏面附近写入实心保护区间。）
            cover_source: Cover thumbnail image source. ``None`` uses silent
                placeholder (calibration / kit / recipe swatch). ``str`` is
                treated as a filesystem path; ``bytes`` as encoded image bytes;
                ``PIL.Image.Image`` as a decoded image. Decode failures fall
                back to placeholder bytes plus one WARNING log per export.
                （封面缩略图图像源；``None`` 走静默占位）
            device_profile_id (Optional[str]): Slicer-scoped generated registry
                device profile ID used to select native machine metadata.
                （切片软件维度的注册表设备配置 ID，用于选择原生机型元数据）
            preserve_template_filament_slots (Optional[bool]): Override whether
                registry templates keep their native filament slot count. ``None``
                keeps the legacy automatic behaviour; ``False`` trims project
                filament arrays to the selected palette.（是否保留注册表模板的原生
                耗材槽数量；``None`` 保持旧自动逻辑，``False`` 按已选调色板裁剪。）
        """
        from config import (
            format_native_nozzle_size,
            get_printer_profile,
            normalize_nozzle_size,
            normalize_slicer_software_id,
        )

        self.output_path = output_path
        self.settings = {**self.DEFAULT_SETTINGS, **(settings or {})}
        self.objects: list[_MeshExportEntry] = []
        self.color_mode = color_mode
        self.printer_id = printer_id
        self.slicer = normalize_slicer_software_id(slicer)
        self.device_profile_id = str(device_profile_id or "").strip() or None
        self.build_plate_id = str(build_plate_id or "").strip() or None
        legacy_nozzle_size = normalize_nozzle_size(nozzle_size) or "0.4"
        native_nozzle_size = format_native_nozzle_size(nozzle_size) or legacy_nozzle_size
        configured_nozzle_sizes = get_printer_profile(printer_id).supported_nozzle_sizes
        self.nozzle_size = (
            native_nozzle_size
            if self.device_profile_id or native_nozzle_size in configured_nozzle_sizes
            else legacy_nozzle_size
        )
        self._registry_device_profile = (
            _load_registry_device_profile_if_available(
                device_profile_id=self.device_profile_id,
                printer_id=self.printer_id,
                slicer=self.slicer,
                nozzle_size=self.nozzle_size,
            )
            if self.device_profile_id
            else None
        )
        self._registry_build_plate = None
        if self.build_plate_id:
            if self._registry_device_profile is None or not self.device_profile_id:
                raise ValueError("Build plate selection requires a machine registry device profile")
            from core.machine_registry import load_machine_registry

            registry_path = os.path.join(
                _resolve_machine_registry_root(),
                "registry.json",
            )
            try:
                self._registry_build_plate = load_machine_registry(
                    registry_path
                ).resolve_build_plate(self.device_profile_id, self.build_plate_id)
            except KeyError as exc:
                raise ValueError(str(exc).strip("'")) from exc
        self.watermark = watermark
        self.enable_relief = bool(enable_relief)
        self.enable_base_layer_height_modifier = bool(
            enable_base_layer_height_modifier
        ) and not self.enable_relief
        self.base_height_mm = float(base_height_mm)
        self.color_height_mm = float(color_height_mm)
        normalized_face_orientation = str(face_orientation).strip().lower()
        if normalized_face_orientation not in _VALID_LAYER_CONFIG_FACES:
            normalized_face_orientation = "down"
        self.face_orientation = normalized_face_orientation
        self.requested_backing_infill_density_percent = (
            normalize_backing_infill_density_percent(
                backing_infill_density_percent
            )
        )
        if (
            self.enable_relief
            and self.requested_backing_infill_density_percent < 100
        ):
            raise ValueError(
                "Sparse backing infill is not supported for variable-height relief exports."
            )
        self.effective_backing_infill_density_percent = (
            resolve_effective_backing_infill_density_percent(
                self.requested_backing_infill_density_percent,
                base_height_mm=self.base_height_mm,
                face=self.face_orientation,
            )
        )
        self.settings["sparse_infill_density"] = (
            f"{self.effective_backing_infill_density_percent}%"
        )
        if self.effective_backing_infill_density_percent < 100:
            # A zero-layer top shell leaves the non-viewing face as exposed
            # sparse infill even when the template carries a thickness value.
            # Keep the template thickness contract and require one top skin.
            self.settings["top_shell_layers"] = str(
                max(1, int(self.settings.get("top_shell_layers", "0")))
            )
        self._project_slot_names: list[str] = []
        self._project_preview_colors: dict | None = None
        self.cover_source: "str | bytes | Image.Image | None" = cover_source
        self.cover_bundle: Optional[CoverPngBundle] = None
        self.preserve_template_filament_slots = preserve_template_filament_slots
        self._wipe_tower_placement_cache: WipeTowerPlacementResult | None = None

    def add_mesh(self, mesh: _get_trimesh().Trimesh, name: str, color_rgb: tuple):
        """Add a mesh object to the scene.
        将网格对象添加到场景中。

        Args:
            mesh: Trimesh object
            name: Object name (e.g., "White", "Cyan", "Magenta")
            color_rgb: RGB color tuple (0-255)
        """
        if mesh is None:
            raise ValueError(f"[BAMBU_3MF] Cannot add mesh '{name}': mesh is None")

        vertices = getattr(mesh, "vertices", None)
        faces = getattr(mesh, "faces", None)
        v_count = len(vertices) if vertices is not None else 0
        f_count = len(faces) if faces is not None else 0
        if v_count == 0 or f_count == 0:
            raise ValueError(f"[BAMBU_3MF] Cannot add mesh '{name}': empty geometry (v={v_count}, f={f_count})")

        metadata = getattr(mesh, "metadata", {}) or {}
        material_name = str(metadata.get("bambu_material_name") or name)
        self.objects.append(
            _MeshExportEntry(
                mesh=mesh,
                object_name=name,
                material_name=material_name,
                color_rgb=tuple(int(channel) for channel in color_rgb[:3]),
            )
        )
        self._wipe_tower_placement_cache = None

    def _set_project_palette(self, slot_names: list[str], preview_colors: Dict) -> None:
        """Configure the project-wide palette used for exported metadata.

        配置导出元数据使用的项目级完整调色板。
        """

        self._project_slot_names = [str(name) for name in slot_names if str(name)]
        self._project_preview_colors = dict(preview_colors or {})
        self._wipe_tower_placement_cache = None

    def _build_object_material_palette(self) -> tuple[list[tuple[str, tuple[int, int, int]]], dict[str, int]]:
        """Build the compact material palette from queued mesh objects only.

        从待导出的网格对象中构建仅包含实际对象的紧凑材料调色板。
        """

        palette: list[tuple[str, tuple[int, int, int]]] = []
        name_to_index: dict[str, int] = {}
        for entry in self.objects:
            if entry.material_name in name_to_index:
                continue
            name_to_index[entry.material_name] = len(palette)
            palette.append((entry.material_name, entry.color_rgb))
        return palette, name_to_index

    def _build_material_palette(self) -> tuple[list[tuple[str, tuple[int, int, int]]], dict[str, int]]:
        """Build the shared export palette for meshes and project metadata.

        构建用于网格与项目元数据的共享导出调色板。

        Returns:
            tuple[list[tuple[str, tuple[int, int, int]]], dict[str, int]]:
                Ordered shared-material palette and material-name to palette-index map.
                （有序共享材料调色板，以及材料名到调色板索引的映射）
        """

        object_palette, _ = self._build_object_material_palette()
        if not self._project_slot_names:
            return object_palette, {
                material_name: idx for idx, (material_name, _) in enumerate(object_palette)
            }

        palette: list[tuple[str, tuple[int, int, int]]] = []
        name_to_index: dict[str, int] = {}
        preview_colors = self._project_preview_colors or {}
        for slot_index, slot_name in enumerate(self._project_slot_names):
            if slot_name in name_to_index:
                continue
            color_rgb, _ = _resolve_preview_color_for_slot_name(
                slot_name=slot_name,
                slot_index=slot_index,
                preview_colors=preview_colors,
            )
            name_to_index[slot_name] = len(palette)
            palette.append((slot_name, color_rgb))

        for material_name, color_rgb in object_palette:
            if material_name in name_to_index:
                continue
            name_to_index[material_name] = len(palette)
            palette.append((material_name, color_rgb))
        return palette, name_to_index

    def export(self) -> str:
        """Export all meshes to a BambuStudio-compatible 3MF file.
        将所有网格导出为 BambuStudio 兼容的 3MF 文件。

        Returns:
            str: Path to the exported 3MF file
        """
        if len(self.objects) == 0:
            raise ValueError("[BAMBU_3MF] Refusing to export 3MF: no mesh objects were added")

        log.debug(
            "Exporting Bambu 3MF",
            extra={
                "event": "bambu_3mf_export_started",
                "path": self.output_path,
                "object_count": len(self.objects),
                "color_mode": self.color_mode,
                "printer_id": self.printer_id,
                "slicer": self.slicer,
                "nozzle_size": self.nozzle_size,
            },
        )
        _exp_t0 = time.perf_counter()

        n3mf = _get_n3mf()

        builder = n3mf.DocumentBuilder()
        builder.set_unit(n3mf.Unit.Millimeter)
        builder.set_language("en-US")

        builder.enable_production()
        builder.set_production_merge_objects(True)

        builder.add_namespace("BambuStudio", "http://schemas.bambulab.com/package/2021")
        builder.add_metadata("Application", self._get_app_version_str())
        orca_version = self._get_orca_slicer_version_tag()
        if orca_version:
            builder.add_metadata("OrcaSlicer", orca_version)
        builder.add_metadata("BambuStudio:3mfVersion", "1")
        if self.slicer == "FlashStudio":
            for key, value in (
                ("Copyright", ""),
                ("CreationDate", ""),
                ("Description", ""),
                ("Designer", ""),
                ("DesignerCover", ""),
                ("DesignerUserId", ""),
                ("License", ""),
                ("ModificationDate", ""),
                ("Origin", ""),
                (
                    "Thumbnail_Middle",
                    "/Auxiliaries/.thumbnails/thumbnail_middle.png",
                ),
                (
                    "Thumbnail_Small",
                    "/Auxiliaries/.thumbnails/thumbnail_small.png",
                ),
                ("Title", ""),
            ):
                builder.add_metadata(key, value)
        builder.add_external_model_metadata("BambuStudio:3mfVersion", "1")

        material_palette, material_indices = self._build_material_palette()
        materials = [
            n3mf.BaseMaterial(name, n3mf.Color(rgb[0], rgb[1], rgb[2]))
            for name, rgb in material_palette
        ]
        mat_group_id = builder.add_base_material_group(materials)

        object_ids: list[int] = []
        material_index_by_object: list[int] = []
        for entry in self.objects:
            n3mf_mesh = n3mf.Mesh.from_arrays(
                np.ascontiguousarray(entry.mesh.vertices, dtype=np.float64),
                np.ascontiguousarray(entry.mesh.faces, dtype=np.int64),
            )
            material_index = material_indices[entry.material_name]
            obj_id = builder.add_mesh_object(entry.object_name, n3mf_mesh, mat_group_id, material_index)
            builder.add_build_item(obj_id)
            object_ids.append(obj_id)
            material_index_by_object.append(material_index)

        assembly_id = object_ids[-1] + 1 if object_ids else mat_group_id + 1
        self._inject_metadata_parts(builder, object_ids, assembly_id, material_index_by_object)

        doc = builder.build()

        opts = n3mf.WriteOptions()
        opts.vertex_precision = 6
        opts.compact_xml = True
        if self.watermark and hasattr(n3mf, "WatermarkConfig"):
            opts.watermark = n3mf.WatermarkConfig(payload=self.watermark.encode("utf-8"))
        elif self.watermark:
            n3mf_version = getattr(n3mf, "__version__", "unknown")
            log.warning(
                "Watermark disabled because neroued_3mf does not provide WatermarkConfig",
                extra={
                    "event": "bambu_3mf_watermark_disabled",
                    "path": self.output_path,
                    "n3mf_version": n3mf_version,
                },
            )

        # Two-phase export: n3mf writes to an intermediate path, then we
        # rewrite _rels/.rels via stdlib zipfile to inject the three cover
        # thumbnail relationships. n3mf cannot mutate the package-level rels
        # directly (its add_custom_relationship attaches to part-level rels
        # like 3D/3dmodel.model). The intermediate file is removed in the
        # finally block; any IO/XML failure during postprocessing propagates
        # so callers see a fatal export error, while encoding-time cover
        # failures are already handled inside _ensure_cover_bundle (silent
        # placeholder + at most one WARNING).
        output_dir = os.path.dirname(self.output_path) or None
        fd, intermediate_path = tempfile.mkstemp(suffix=".3mf", dir=output_dir)
        os.close(fd)
        try:
            n3mf.write_to_file(intermediate_path, doc, opts)
            self._inject_cover_relationships_postprocess(
                intermediate_path, self.output_path
            )
        finally:
            try:
                if os.path.exists(intermediate_path):
                    os.unlink(intermediate_path)
            except OSError:
                pass

        log.debug(
            "Bambu 3MF export completed",
            extra={
                "event": "bambu_3mf_export_completed",
                "path": self.output_path,
                "object_count": len(self.objects),
                "duration_ms": round((time.perf_counter() - _exp_t0) * 1000, 3),
            },
        )
        return self.output_path
    # ------------------------------------------------------------------
    # Slicer version string
    # ------------------------------------------------------------------

    def _get_app_version_str(self) -> str:
        """Return slicer-appropriate Application version string.
        返回适配不同切片器的 Application 版本字符串。
        """
        registry_profile = getattr(self, "_registry_device_profile", None)
        if registry_profile is not None:
            application_metadata = str(registry_profile.application_metadata or "").strip()
            if application_metadata:
                return application_metadata
        _VERSION_MAP = {
            "SnapmakerOrca": "SnapmakerOrca-02.02.49.02",
            "ElegooSlicer": "ElegooSlicer-1.3.2.9",
            "OrcaSlicer": "BambuStudio-2.3.2-rc2",
            "AnycubicSlicerNext": "BambuStudio-1.3.9.4",
            "FlashStudio": "BambuStudio-2.3.2",
        }
        if self.slicer == "BambuStudio":
            return f"BambuStudio-{self._get_bambu_client_version()}"
        return _VERSION_MAP.get(self.slicer, "BambuStudio-02.02.01.04")

    def _get_bambu_client_version(self) -> str:
        """Return the BambuStudio client-version stamp for this printer/nozzle combination."""
        if self.nozzle_size != "0.2":
            return "02.05.00.66"
        h2_family = {"bambu-h2c", "bambu-h2d", "bambu-h2d-pro", "bambu-h2s"}
        if self.printer_id in h2_family:
            return "02.05.00.66"
        return "02.04.00.70"

    def _get_snapmaker_orca_client_version(self) -> str:
        """Return the Snapmaker Orca client-version stamp."""
        return "02.02.49.02"

    @staticmethod
    def _format_orca_slicer_version_tag(value: object) -> str:
        raw = str(value or "").strip()
        for prefix in ("OrcaSlicer-", "BambuStudio-"):
            if raw.startswith(prefix):
                raw = raw[len(prefix):]
                break
        if re.fullmatch(r"\d+(?:\.\d+){1,3}", raw):
            parts = [int(part) for part in raw.split(".")]
            while len(parts) > 3 and parts[-1] == 0:
                parts.pop()
            while len(parts) < 3:
                parts.append(0)
            return ".".join(str(part) for part in parts)
        return raw

    def _get_orca_slicer_version_tag(self) -> str | None:
        """Return the OrcaSlicer metadata tag used to avoid Bambu-project imports."""
        if self.slicer != "OrcaSlicer":
            return None
        raw_version = self._get_registry_source_version()
        if not raw_version:
            application_metadata = self._get_app_version_str()
            if application_metadata.startswith("OrcaSlicer-"):
                raw_version = application_metadata
        version_tag = self._format_orca_slicer_version_tag(raw_version)
        return version_tag or None

    def _get_registry_source_version(self) -> str | None:
        """Return source slicer version from generated machine registry if present."""
        registry_profile = getattr(self, "_registry_device_profile", None)
        if registry_profile is None:
            return None
        source_version = str(registry_profile.source_version or "").strip()
        if source_version:
            return source_version
        application_metadata = str(registry_profile.application_metadata or "").strip()
        if "-" in application_metadata:
            return application_metadata.split("-", 1)[1]
        return None

    def _get_registry_client_version(self) -> str | None:
        """Return exact slicer client-version stamp from machine registry if present."""
        registry_profile = getattr(self, "_registry_device_profile", None)
        if registry_profile is None:
            return None
        client_version = str(getattr(registry_profile, "client_version", "") or "").strip()
        return client_version or None

    def _get_anycubic_client_version(self) -> str:
        """Return the ACNext client-version stamp expected by Anycubic metadata."""
        registry_client_version = self._get_registry_client_version()
        if registry_client_version:
            return registry_client_version
        registry_source_version = self._get_registry_source_version()
        if registry_source_version and " " in registry_source_version:
            return registry_source_version
        if registry_source_version == "1.3.9.4" or not registry_source_version:
            return "1.3.9.4 20260319225535"
        return registry_source_version

    def _is_anycubic_slicer(self) -> bool:
        """Return whether the current export targets Anycubic Slicer Next.
        返回当前导出是否面向 Anycubic Slicer Next。
        """
        return self.slicer == "AnycubicSlicerNext"

    def _should_emit_bambu_aux_parts(self) -> bool:
        """Return whether the export should include Bambu-only aux metadata parts."""
        return self.slicer == "BambuStudio"

    @staticmethod
    def _format_number(value: float) -> str:
        """Format a float for stable metadata output.
        将浮点数格式化为稳定的元数据输出字符串。
        """
        return format(float(value), ".15g")

    @staticmethod
    def _parse_printable_area_point(value: object) -> tuple[float, float] | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        parts = re.split(r"[xX,;\\s]+", raw)
        if len(parts) < 2:
            return None
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            return None

    @staticmethod
    def _parse_config_float(value: object, default: float = 0.0) -> float:
        """Read the first numeric scalar from a slicer config value.

        从切片器配置值中读取首个数值标量。
        """

        candidate = value[0] if isinstance(value, list) and value else value
        try:
            return float(candidate)
        except (TypeError, ValueError):
            return float(default)

    @classmethod
    def _parse_config_percent_ratio(
        cls,
        value: object,
        default: float = 1.0,
    ) -> float:
        """Parse slicer percentages as a multiplier. / 将切片器百分比解析为倍率。"""

        candidate = value[0] if isinstance(value, list) and value else value
        text = str(candidate or "").strip()
        is_percent = text.endswith("%")
        if is_percent:
            text = text[:-1].strip()
        parsed = cls._parse_config_float(text, default)
        if is_percent or parsed > 10.0:
            parsed /= 100.0
        return max(0.01, parsed)

    @classmethod
    def _parse_config_polygon(cls, value: object) -> tuple[tuple[float, float], ...]:
        """Parse a flat ``["XxY", ...]`` polygon. / 解析扁平坐标多边形。"""

        if not isinstance(value, list):
            return ()
        return tuple(
            point
            for point in (cls._parse_printable_area_point(item) for item in value)
            if point is not None
        )

    @classmethod
    def _parse_bed_exclusion_polygons(
        cls,
        value: object,
    ) -> tuple[tuple[tuple[float, float], ...], ...]:
        """Parse rectangular bed-exclusion groups, ignoring degenerate sentinels.

        解析热床禁用矩形，并忽略 ``["0x0"]`` 一类退化占位值。
        """

        points = cls._parse_config_polygon(value)
        if len(points) < 3:
            return ()
        if len(points) <= 4:
            return (points,)
        if len(points) % 4 == 0:
            return tuple(
                tuple(points[index : index + 4])
                for index in range(0, len(points), 4)
            )
        return (points,)

    @classmethod
    def _parse_extruder_printable_polygons(
        cls,
        value: object,
    ) -> tuple[tuple[tuple[float, float], ...], ...]:
        """Parse per-extruder comma-separated printable polygons.

        解析每个挤出头以逗号分隔的可打印多边形。
        """

        if not isinstance(value, list):
            return ()
        polygons: list[tuple[tuple[float, float], ...]] = []
        for item in value:
            tokens = [token.strip() for token in str(item or "").split(",")]
            points = tuple(
                point
                for point in (cls._parse_printable_area_point(token) for token in tokens)
                if point is not None
            )
            if len(points) >= 3:
                polygons.append(points)
        return tuple(polygons)

    @staticmethod
    def _replace_first_config_number(value: object, number: float) -> object:
        """Preserve a config value's scalar/list shape while replacing slot zero.

        保留配置值的标量或列表形态，仅替换第一个槽位。
        """

        formatted = BambuStudio3MFWriter._format_number(number)
        if isinstance(value, list):
            result = list(value)
            if result:
                result[0] = formatted
            else:
                result.append(formatted)
            return result
        return formatted

    def _resolve_tower_purge_volume(self, template: dict[str, Any]) -> float:
        """Resolve the slicer-family purge scalar used for footprint planning.

        解析对应切片器用于占地估算的冲刷体积标量。
        """

        filament_prime_values = template.get("filament_prime_volume")

        def _positive_filament_prime_values() -> list[float]:
            if not isinstance(filament_prime_values, list):
                return []
            parsed = [
                self._parse_config_float(item, 0.0)
                for item in filament_prime_values
            ]
            return [value for value in parsed if value > 0.0]

        positive_filament_values = _positive_filament_prime_values()
        if self.slicer == "BambuStudio" and positive_filament_values:
            # These template values are not persisted as a project override,
            # so Bambu Studio resolves its native 45 mm3 material default when
            # the embedded value is lower. Plan against the effective sliced
            # value, not the under-sized project preview scalar.
            return max(45.0, max(positive_filament_values))

        prime_volume = self._parse_config_float(template.get("prime_volume"), -1.0)
        if prime_volume > 0.0:
            return prime_volume
        if positive_filament_values:
            return max(positive_filament_values)
        values = template.get("flush_volumes_vector")
        if isinstance(values, list):
            parsed = [
                self._parse_config_float(item, 0.0)
                for item in values
            ]
            positive = [value for value in parsed if value > 0.0]
            if positive:
                return max(positive)
        return 45.0

    def _resolve_tower_extruder_count(self, template: dict[str, Any]) -> int:
        nozzle_diameters = template.get("nozzle_diameter")
        if isinstance(nozzle_diameters, list) and nozzle_diameters:
            return len(nozzle_diameters)
        return 1

    def _resolve_filament_change_volume(self, template: dict[str, Any]) -> float:
        lengths = template.get("filament_change_length")
        length_values = lengths if isinstance(lengths, list) else [lengths]
        max_length = max(
            (self._parse_config_float(value, 0.0) for value in length_values),
            default=0.0,
        )
        diameters = template.get("filament_diameter")
        diameter_values = diameters if isinstance(diameters, list) else [diameters]
        max_diameter = max(
            (self._parse_config_float(value, 0.0) for value in diameter_values),
            default=1.75,
        )
        if max_diameter <= 0.0:
            max_diameter = 1.75
        return max_length * math.pi * max_diameter * max_diameter / 4.0

    def _resolve_tower_brim_width(
        self,
        template: dict[str, Any],
        model_height: float,
    ) -> float:
        """Resolve fixed or automatic prime-tower brim width.

        解析固定或自动计算的擦料塔裙边宽度。
        """

        brim = self._parse_config_float(template.get("prime_tower_brim_width"), 0.0)
        if brim >= 0.0:
            return brim
        return min(8.0, max(0.0, model_height) / 100.0 * 8.0)

    def _resolve_model_brim_width(self, template: dict[str, Any]) -> float:
        """Return the active model brim reservation. / 返回模型实际裙边预留。"""

        brim_type = str(
            self.settings.get("brim_type", template.get("brim_type", ""))
        ).strip().lower()
        if brim_type in {"no_brim", "none", "0"}:
            return 0.0
        brim_value = self.settings.get("brim_width", template.get("brim_width"))
        return max(0.0, self._parse_config_float(brim_value, 0.0))

    def _build_wipe_tower_placement_request(
        self,
        template: dict[str, Any],
        *,
        model_bounds: Rect,
        model_height: float,
        material_count: int,
    ) -> WipeTowerPlacementRequest | None:
        """Build one placement request from a template and arbitrary bounds.

        根据模板和任意模型包围盒构建一次擦料塔布局请求；单件导出和批量合并
        共用同一套机型/切片器边界规则。
        """

        printable_area = self._parse_config_polygon(template.get("printable_area"))
        if len(printable_area) < 3:
            return None

        uses_creator_5_tower_interface = (
            self.slicer == "FlashStudio"
            and self.printer_id in _CREATOR_5_PRINTER_IDS
        )
        uses_anycubic_tower_interface = self._is_anycubic_slicer()
        uses_native_tower_envelope = (
            uses_creator_5_tower_interface or uses_anycubic_tower_interface
        )
        tower_width = max(
            2.0,
            self._parse_config_float(template.get("prime_tower_width"), 35.0),
        )
        request = WipeTowerPlacementRequest(
            printable_area=printable_area,
            bed_exclusions=self._parse_bed_exclusion_polygons(
                template.get("bed_exclude_area")
            ),
            extruder_printable_areas=self._parse_extruder_printable_polygons(
                template.get("extruder_printable_area")
            ),
            model_bounds=model_bounds,
            model_height=max(0.0, float(model_height)),
            model_brim=self._resolve_model_brim_width(template),
            material_count=max(1, int(material_count)),
            layer_height=max(
                0.01,
                self._parse_config_float(
                    self.settings.get("layer_height"),
                    self._parse_config_float(template.get("layer_height"), 0.08),
                ),
            ),
            nozzle_diameter=max(0.1, self._parse_config_float(self.nozzle_size, 0.4)),
            purge_volume=self._resolve_tower_purge_volume(template),
            tower_x=self._parse_config_float(template.get("wipe_tower_x"), 15.0),
            tower_y=self._parse_config_float(template.get("wipe_tower_y"), 220.0),
            tower_width=tower_width,
            tower_rotation=self._parse_config_float(
                template.get("wipe_tower_rotation_angle"), 0.0
            ),
            tower_brim=(
                0.0
                if uses_native_tower_envelope
                else self._resolve_tower_brim_width(template, model_height)
            ),
            tower_infill_spacing_ratio=self._parse_config_percent_ratio(
                template.get("prime_tower_infill_gap"),
                1.0,
            ),
            extruder_count=self._resolve_tower_extruder_count(template),
            filament_change_volume=self._resolve_filament_change_volume(template),
            model_tower_clearance=(
                _CREATOR_5_MODEL_TOWER_CLEARANCE_MM
                if uses_creator_5_tower_interface
                else 8.0
            ),
            edge_clearance=(0.0 if uses_native_tower_envelope else 2.0),
            preferred_edge_clearance=4.0,
            preferred_top_edge_clearance=(
                _ELEGOO_CC2_PREFERRED_TOP_EDGE_CLEARANCE_MM
                if self.printer_id == "elegoo-cc2"
                else 0.0
            ),
            prefer_vertical_strip=(self.printer_id == "bambu-a1-mini"),
            minimum_tower_footprint_width=(
                _CREATOR_5_TOWER_MIN_FOOTPRINT_WIDTH_MM
                if uses_creator_5_tower_interface
                else (
                    _ANYCUBIC_TOWER_MIN_FOOTPRINT_WIDTH_MM
                    if uses_anycubic_tower_interface
                    else 0.0
                )
            ),
            minimum_tower_depth=(
                _CREATOR_5_TOWER_MIN_DEPTH_MM
                if uses_creator_5_tower_interface
                else (
                    _ANYCUBIC_TOWER_MIN_DEPTH_MM
                    if uses_anycubic_tower_interface
                    else 0.0
                )
            ),
        )
        return request

    def _get_wipe_tower_placement(self) -> WipeTowerPlacementResult | None:
        """Resolve and cache the joint model/tower placement.

        联合求解并缓存模型与擦料塔摆放结果；安全模板保持原样，无解时仅标记
        需要人工调整，绝不缩放模型或关闭擦料塔。
        """

        if self._wipe_tower_placement_cache is not None:
            return self._wipe_tower_placement_cache
        if not self.objects:
            return None

        template = self._get_base_config_template()
        bounds_min, bounds_max = self._get_mesh_bounds()
        request = self._build_wipe_tower_placement_request(
            template,
            model_bounds=Rect(
                float(bounds_min[0]),
                float(bounds_min[1]),
                float(bounds_max[0]),
                float(bounds_max[1]),
            ),
            model_height=float(bounds_max[2] - bounds_min[2]),
            material_count=len(self._build_material_palette()[0]),
        )
        if request is None:
            return None

        placement = solve_wipe_tower_placement(request)
        self._wipe_tower_placement_cache = placement
        if placement.requires_manual_adjustment:
            log.warning(
                "No collision-free model and wipe-tower layout fits the selected bed",
                extra={
                    "event": "wipe_tower_manual_adjustment_required",
                    "error_type": "WipeTowerPlacementUnavailable",
                    "error_message": (
                        "Generated without scaling the model or disabling the wipe tower; "
                        "manual slicer adjustment is required."
                    ),
                    "path": self.output_path,
                    "printer_id": self.printer_id,
                    "slicer": self.slicer,
                    "model_width_mm": round(request.model_bounds.width, 3),
                    "model_depth_mm": round(request.model_bounds.height, 3),
                },
            )
        else:
            log.debug(
                "Resolved model and wipe-tower placement",
                extra={
                    "event": "wipe_tower_placement_resolved",
                    "path": self.output_path,
                    "printer_id": self.printer_id,
                    "slicer": self.slicer,
                    "adapted": placement.adapted,
                    "tower_width_mm": round(placement.tower_width, 3),
                    "tower_rotation_deg": round(placement.tower_rotation, 3),
                },
            )
        return placement

    def _get_printable_area_center(self) -> tuple[float, float] | None:
        settings = self._get_base_config_template()
        raw_area = settings.get("printable_area")
        if not isinstance(raw_area, list):
            return None
        points = [
            point
            for point in (
                self._parse_printable_area_point(item) for item in raw_area
            )
            if point is not None
        ]
        if len(points) < 2:
            return None
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0

    def _get_mesh_bounds(self) -> tuple[np.ndarray, np.ndarray]:
        bounds: list[np.ndarray] = []
        for entry in self.objects:
            mesh_bounds = np.asarray(
                getattr(entry.mesh, "bounds", np.zeros((2, 3))),
                dtype=np.float64,
            )
            if mesh_bounds.shape == (2, 3):
                bounds.append(mesh_bounds)
        if not bounds:
            zeros = np.zeros(3, dtype=np.float64)
            return zeros, zeros
        stacked = np.stack(bounds, axis=0)
        return stacked[:, 0, :].min(axis=0), stacked[:, 1, :].max(axis=0)

    def _get_build_item_translation(self) -> tuple[float, float, float]:
        bounds_min, bounds_max = self._get_mesh_bounds()
        placement = self._get_wipe_tower_placement()
        if placement is not None:
            translate_x, translate_y = placement.model_translation
        else:
            model_center = (bounds_min + bounds_max) / 2.0
            bed_center = self._get_printable_area_center()
            if bed_center is None:
                translate_x = 0.0
                translate_y = 0.0
            else:
                translate_x = float(bed_center[0] - model_center[0])
                translate_y = float(bed_center[1] - model_center[1])
        translate_z = float(-bounds_min[2])
        return translate_x, translate_y, translate_z

    def _get_identify_id(self) -> str:
        """Return a slicer-specific plate identify_id value.
        返回切片器专属的 plate identify_id 值。
        """
        if self._is_anycubic_slicer():
            return "160"
        return "1"

    # ------------------------------------------------------------------
    # Bambu vendor metadata injection (CustomPart)
    # ------------------------------------------------------------------

    def _inject_metadata_parts(
        self,
        builder: _get_n3mf().DocumentBuilder,
        object_ids: list[int],
        assembly_id: int,
        material_index_by_object: list[int] | None = None,
    ) -> None:
        """Inject all Bambu vendor metadata files into the 3MF via CustomPart.
        通过 CustomPart 向 3MF 中注入所有 Bambu 厂商元数据。
        """
        parts = [
            (
                "Metadata/model_settings.config",
                "text/xml",
                self._build_model_settings_bytes(object_ids, assembly_id, material_index_by_object),
            ),
            ("Metadata/project_settings.config", "text/xml", self._build_project_settings_bytes()),
            ("Metadata/slice_info.config", "text/xml", self._build_slice_info_bytes()),
            (
                "Metadata/lumina_wipe_tower_placement.json",
                "application/json",
                self._build_wipe_tower_placement_metadata_bytes(),
            ),
        ]
        if self._is_anycubic_slicer():
            parts.append(
                ("Metadata/custom_gcode_per_layer.xml", "text/xml", self._build_custom_gcode_per_layer_bytes())
            )
        elif self._should_emit_bambu_aux_parts():
            parts.extend(
                [
                    ("Metadata/filament_sequence.json", "application/json", self._build_filament_sequence_bytes()),
                    (
                        "Metadata/cut_information.xml",
                        "text/xml",
                        self._build_cut_information_bytes(assembly_id),
                    ),
                ]
            )
        if (
            not self.enable_relief
            and (
                self.enable_base_layer_height_modifier
                or self.effective_backing_infill_density_percent < 100
            )
        ):
            # Bambu/Orca layer_config_ranges keys are one-based model-object
            # indexes, not 3MF resource/build object ids. Lumina emits one
            # assembled model object here; puzzle exports strip this metadata.
            template = self._get_base_config_template()
            min_layer_height, max_layer_height = _strict_printer_layer_height_limits(template)
            try:
                fine_layer_height = float(self.settings["layer_height"])
            except (KeyError, TypeError, ValueError):
                fine_layer_height = float(self.DEFAULT_SETTINGS["layer_height"])
            try:
                initial_layer_height = float(template["initial_layer_print_height"])
            except (KeyError, TypeError, ValueError):
                initial_layer_height = None
            lcr_bytes = build_layer_config_ranges_xml(
                base_height_mm=self.base_height_mm,
                color_height_mm=self.color_height_mm,
                nozzle_mm=float(self.nozzle_size),
                face=self.face_orientation,
                fine_layer_height_mm=fine_layer_height,
                initial_layer_height_mm=initial_layer_height,
                min_layer_height_mm=min_layer_height,
                max_layer_height_mm=max_layer_height,
                object_id=1,
                enable_base_layer_height_modifier=(
                    self.enable_base_layer_height_modifier
                ),
                backing_infill_density_percent=(
                    self.effective_backing_infill_density_percent
                ),
            )
            if lcr_bytes is not None:
                parts.append(("Metadata/layer_config_ranges.xml", "text/xml", lcr_bytes))
        self._ensure_cover_bundle()
        bundle = self.cover_bundle
        assert bundle is not None  # _ensure_cover_bundle always assigns
        placeholder_2x2 = self._build_preview_placeholder_png_bytes()
        parts.extend(
            [
                ("Metadata/plate_1.png", "image/png", bundle.plate_main),
                ("Metadata/plate_no_light_1.png", "image/png", bundle.plate_no_light),
                ("Metadata/top_1.png", "image/png", placeholder_2x2),
                ("Metadata/pick_1.png", "image/png", placeholder_2x2),
            ]
        )
        if self.slicer == "FlashStudio":
            parts.extend(
                [
                    (
                        "Metadata/plate_1_small.png",
                        "image/png",
                        self._build_flashstudio_plate_small_bytes(bundle.plate_main),
                    ),
                    (
                        "Metadata/plate_1.json",
                        "application/json",
                        self._build_flashstudio_plate_json_bytes(),
                    ),
                ]
            )
        # Auxiliaries/.thumbnails/* — package-level cover thumbnails referenced
        # from _rels/.rels (post-processed in _inject_cover_relationships_postprocess).
        cover_part_payloads = (
            (COVER_THUMBNAIL_SPECS[0], bundle.thumbnail_3mf),
            (COVER_THUMBNAIL_SPECS[1], bundle.thumbnail_middle),
            (COVER_THUMBNAIL_SPECS[2], bundle.thumbnail_small),
        )
        for spec, png_bytes in cover_part_payloads:
            parts.append((spec.zip_path, "image/png", png_bytes))
        for path, content_type, data in parts:
            builder.add_custom_part(_get_n3mf().CustomPart(path, content_type, data))

        builder.add_custom_content_type(_get_n3mf().CustomContentType("config", "text/xml"))
        builder.add_custom_content_type(_get_n3mf().CustomContentType("json", "application/json"))
        builder.add_custom_content_type(_get_n3mf().CustomContentType("xml", "text/xml"))
        builder.add_custom_content_type(_get_n3mf().CustomContentType("png", "image/png"))

        self._add_bambu_metadata_relationships(builder, [path for path, _, _ in parts])

    def _add_bambu_metadata_relationships(
        self,
        builder: _get_n3mf().DocumentBuilder,
        part_paths: list[str],
    ) -> None:
        """Attach slicer settings metadata to the root model relationship set.
        将切片器设置元数据挂到根模型的关系表上。
        """
        if not hasattr(builder, "add_custom_relationship"):
            return

        n3mf = _get_n3mf()
        relationship_type = "http://schemas.bambulab.com/package/2021/settings"
        if self._should_emit_bambu_aux_parts():
            related_paths = [
                path
                for path in part_paths
                if path.startswith("Metadata/")
                and not path.lower().endswith(".png")
            ]
        else:
            related_paths = [
                path
                for path in part_paths
                if path == "Metadata/layer_config_ranges.xml"
            ]
        for index, path in enumerate(related_paths):
            builder.add_custom_relationship(
                n3mf.CustomRelationship(
                    "3D/3dmodel.model",
                    f"bambuRel{index}",
                    relationship_type,
                    f"/{path}",
                )
            )

    # ------------------------------------------------------------------
    # Cover thumbnail bundle + package-level relationship post-processing
    # ------------------------------------------------------------------

    def _ensure_cover_bundle(self) -> None:
        """Lazily build ``self.cover_bundle`` and emit at most one WARNING.

        惰性构建封面缩略图字节集合；同一次 ``export()`` 内复用。仅当
        ``cover_source is not None`` 但解码 / 编码失败时才触发结构化
        WARNING ``bambu_3mf_cover_thumbnail_failed``，正常路径与
        ``cover_source is None`` 的静默占位场景都不发日志。
        """

        if self.cover_bundle is not None:
            return

        # Cover-source diagnostics (DEBUG only): describe what the writer
        # received before letting the builder decode it. Helps identify cases
        # where a path is wrong, missing, or unexpectedly None for a given
        # structure_mode without spending INFO budget.
        # 封面源诊断（仅 DEBUG）：在解码之前记录 writer 收到的 cover_source
        # 形态，方便复盘单面/双面差异且不消耗 INFO 配额。
        _src = self.cover_source
        if _src is None:
            _src_kind = "none"
            _src_repr = ""
            _src_exists = False
            _src_size = 0
        elif isinstance(_src, str):
            _src_kind = "path"
            _src_repr = _src[:1024]
            _src_exists = os.path.exists(_src)
            try:
                _src_size = os.path.getsize(_src) if _src_exists else 0
            except OSError:
                _src_size = -1
        elif isinstance(_src, (bytes, bytearray, memoryview)):
            _src_kind = "bytes"
            _src_repr = ""
            _src_exists = True
            _src_size = len(bytes(_src))
        else:
            _src_kind = type(_src).__name__
            _src_repr = ""
            _src_exists = True
            _src_size = -1
        log.debug(
            "Bambu 3MF cover source received",
            extra={
                "event": "bambu_3mf_cover_source_received",
                "path": str(self.output_path)[:1024],
                "cover_source_kind": _src_kind,
                "cover_source_path": _src_repr,
                "cover_source_exists": bool(_src_exists),
                "cover_source_size_bytes": int(_src_size),
            },
        )

        self.cover_bundle = CoverThumbnailBuilder().build(self.cover_source)

        # Cover-bundle diagnostics (DEBUG only): record the per-PNG byte sizes
        # plus the placeholder flag so we can tell at a glance whether the
        # decoded image actually flowed into the bundle for this 3MF.
        # 封面 bundle 诊断（仅 DEBUG）：输出每张缩略图字节数与是否走了占位，
        # 用于一眼判断该次 3MF 的缩略图是否真的来自源图。
        log.debug(
            "Bambu 3MF cover bundle built",
            extra={
                "event": "bambu_3mf_cover_bundle_built",
                "path": str(self.output_path)[:1024],
                "is_placeholder": bool(self.cover_bundle.is_placeholder),
                "thumbnail_3mf_bytes": len(self.cover_bundle.thumbnail_3mf),
                "thumbnail_middle_bytes": len(self.cover_bundle.thumbnail_middle),
                "thumbnail_small_bytes": len(self.cover_bundle.thumbnail_small),
                "plate_main_bytes": len(self.cover_bundle.plate_main),
                "plate_no_light_bytes": len(self.cover_bundle.plate_no_light),
                "warning_error_type": (
                    (self.cover_bundle.warning or {}).get("error_type", "")
                ),
            },
        )

        warning = self.cover_bundle.warning
        if warning is not None:
            extra = {
                "event": "bambu_3mf_cover_thumbnail_failed",
                "path": str(self.output_path)[:1024],
                "error_type": warning.get("error_type", ""),
                "error_message": warning.get("error_message", ""),
                "fallback_action": warning.get(
                    "fallback_action", "placeholder_written"
                ),
            }
            log.warning(
                "Bambu 3MF cover thumbnail generation failed; wrote placeholder",
                extra=extra,
            )

    def _inject_cover_relationships_postprocess(
        self,
        intermediate_path: str,
        output_path: str,
    ) -> None:
        """Rewrite the package-level ``_rels/.rels`` to include cover relationships.

        重写包根 ``_rels/.rels``，在保留既有 ``rel-1`` 的前提下追加三条 cover
        关系条目，并把中间产物原子搬到 ``output_path``。

        Algorithm:
        - Iterate the original ZIP entries in order. Unchanged members are
          copied as raw local-header + compressed-data spans so large model
          XML entries are not decompressed and recompressed.
        - When the entry path is ``_rels/.rels``, parse the XML, append three
          ``<Relationship>`` elements (Id ``cover-rel-1/2/3``, Type from
          ``COVER_THUMBNAIL_SPECS``, Target = ``"/" + spec.zip_path``), and
          write the serialized bytes instead of the original payload.
        - Use ``ET.register_namespace("", ...)`` to keep the default OPC
          relationships namespace and avoid ``ns0:`` prefixes in output.
        - Write to ``output_path + ".tmp"`` and finalize with
          ``os.replace`` for atomic publication. Any IO / XML failure
          deletes the partial ``.tmp`` and re-raises so the writer surfaces
          a fatal export error instead of leaving a half-baked 3MF.
        """

        rels_path = "_rels/.rels"
        rels_namespace = (
            "http://schemas.openxmlformats.org/package/2006/relationships"
        )
        ET.register_namespace("", rels_namespace)

        tmp_path = output_path + ".tmp"
        try:
            with zipfile.ZipFile(intermediate_path, "r") as src_zip, open(
                intermediate_path,
                "rb",
            ) as src_file:
                infos = src_zip.infolist()
                with zipfile.ZipFile(
                    tmp_path,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                ) as dst_zip:
                    for info in infos:
                        if info.filename == rels_path:
                            payload = src_zip.read(info.filename)
                            dst_info = self._clone_zipinfo_for_rewrite(info)
                            payload = self._rewrite_rels_xml(payload, rels_namespace)
                            dst_zip.writestr(dst_info, payload)
                        elif info.filename == "3D/3dmodel.model":
                            payload = src_zip.read(info.filename)
                            dst_info = self._clone_zipinfo_for_rewrite(info)
                            payload = self._rewrite_main_model_xml(payload)
                            dst_zip.writestr(dst_info, payload)
                        else:
                            self._raw_copy_zip_member(src_file, dst_zip, info)

            os.replace(tmp_path, output_path)
        except Exception:
            # Clean up the partial .tmp file before re-raising so callers do
            # not see a half-written 3MF on disk.
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _clone_zipinfo_for_rewrite(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
        """Copy stable metadata for an entry whose payload must be rewritten."""

        cloned = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
        cloned.compress_type = info.compress_type
        cloned.external_attr = info.external_attr
        cloned.extra = info.extra
        cloned.create_system = info.create_system
        cloned.create_version = info.create_version
        cloned.extract_version = info.extract_version
        cloned.internal_attr = info.internal_attr
        if info.comment:
            cloned.comment = info.comment
        return cloned

    @staticmethod
    def _clone_zipinfo_for_raw_copy(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
        """Copy central-directory metadata for an unchanged raw ZIP member."""

        cloned = BambuStudio3MFWriter._clone_zipinfo_for_rewrite(info)
        cloned.flag_bits = info.flag_bits
        cloned.CRC = info.CRC
        cloned.compress_size = info.compress_size
        cloned.file_size = info.file_size
        return cloned

    @staticmethod
    def _raw_copy_zip_member(
        src_file: BinaryIO,
        dst_zip: zipfile.ZipFile,
        info: zipfile.ZipInfo,
    ) -> None:
        """Append an unchanged ZIP member without decompressing its payload."""

        end_offset = getattr(info, "_end_offset", None)
        if not isinstance(end_offset, int) or end_offset < info.header_offset:
            raise RuntimeError(f"invalid ZIP member span for {info.filename!r}")

        dst_info = BambuStudio3MFWriter._clone_zipinfo_for_raw_copy(info)
        span_remaining = end_offset - info.header_offset

        # zipfile has no public raw-copy API. This mirrors ZipFile.open(..., 'w')
        # bookkeeping, then writes the already-compressed local entry bytes.
        with dst_zip._lock:
            if dst_zip.fp is None:
                raise ValueError(
                    "Attempt to write to ZIP archive that was already closed"
                )
            if dst_zip._writing:
                raise ValueError(
                    "Can't write to ZIP archive while another write is open"
                )
            if dst_zip._seekable:
                dst_zip.fp.seek(dst_zip.start_dir)
            dst_info.header_offset = dst_zip.fp.tell()
            dst_zip._writecheck(dst_info)
            dst_zip._didModify = True

            src_file.seek(info.header_offset)
            while span_remaining:
                chunk = src_file.read(min(_RAW_ZIP_COPY_CHUNK_SIZE, span_remaining))
                if not chunk:
                    raise RuntimeError(f"truncated ZIP member {info.filename!r}")
                dst_zip.fp.write(chunk)
                span_remaining -= len(chunk)

            dst_zip.filelist.append(dst_info)
            dst_zip.NameToInfo[dst_info.filename] = dst_info
            dst_zip.start_dir = dst_zip.fp.tell()

    @staticmethod
    def _rewrite_rels_xml(rels_bytes: bytes, rels_namespace: str) -> bytes:
        """Append three cover relationships to ``_rels/.rels`` XML payload.

        在 ``_rels/.rels`` XML 中追加三条 cover 关系（保留既有 ``rel-1``）。
        """

        ET.register_namespace("", rels_namespace)
        try:
            root = ET.fromstring(rels_bytes)
        except ET.ParseError as exc:
            raise RuntimeError(f"failed to parse _rels/.rels: {exc}") from exc

        existing_ids: set[str] = set()
        for rel in root.findall(f"{{{rels_namespace}}}Relationship"):
            rid = rel.get("Id")
            if rid:
                existing_ids.add(rid)
        # Also handle defensively in case the file omitted the default
        # namespace (some non-OPC writers do this).
        for rel in root.findall("Relationship"):
            rid = rel.get("Id")
            if rid:
                existing_ids.add(rid)

        cover_rel_ids: list[str] = []
        for index, spec in enumerate(COVER_THUMBNAIL_SPECS, start=1):
            candidate = f"cover-rel-{index}"
            # Defensive: if the synthetic ID collides with an existing one,
            # bump until unique. cover-rel-* should never overlap n3mf's
            # rel-* sequence in practice.
            suffix = 0
            while candidate in existing_ids:
                suffix += 1
                candidate = f"cover-rel-{index}-{suffix}"
            existing_ids.add(candidate)
            cover_rel_ids.append(candidate)
            ET.SubElement(
                root,
                f"{{{rels_namespace}}}Relationship",
                attrib={
                    "Id": candidate,
                    "Type": str(spec.relationship_type or ""),
                    "Target": "/" + spec.zip_path,
                },
            )

        buf = io.BytesIO()
        # Mirror n3mf-emitted rels: include XML declaration with UTF-8
        # encoding; ElementTree handles the namespace via register_namespace.
        ET.ElementTree(root).write(
            buf, encoding="utf-8", xml_declaration=True
        )
        return buf.getvalue()

    def _rewrite_main_model_xml(self, model_bytes: bytes) -> bytes:
        """Write build-item placement metadata expected by Bambu-family slicers."""

        core_namespace = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
        production_namespace = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
        ET.register_namespace("", core_namespace)
        ET.register_namespace("p", production_namespace)
        ET.register_namespace("BambuStudio", "http://schemas.bambulab.com/package/2021")

        try:
            root = ET.fromstring(model_bytes)
        except ET.ParseError as exc:
            raise RuntimeError(f"failed to parse 3D/3dmodel.model: {exc}") from exc

        build = root.find(f"{{{core_namespace}}}build")
        if build is not None:
            translate_x, translate_y, translate_z = self._get_build_item_translation()
            build_transform = (
                "1 0 0 0 1 0 0 0 1 "
                f"{self._format_number(translate_x)} "
                f"{self._format_number(translate_y)} "
                f"{self._format_number(translate_z)}"
            )
            for item in build.findall(f"{{{core_namespace}}}item"):
                item.attrib["transform"] = build_transform
                if self.slicer == "OrcaSlicer":
                    item.attrib.setdefault("auto_drop", "1")

        buf = io.BytesIO()
        ET.ElementTree(root).write(buf, encoding="utf-8", xml_declaration=True)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Individual metadata builders (return bytes, no filesystem I/O)
    # ------------------------------------------------------------------

    def _build_model_settings_bytes(
        self,
        object_ids: list[int],
        assembly_id: int,
        material_index_by_object: list[int] | None = None,
    ) -> bytes:
        """Build model_settings.config XML as bytes.
        构建 model_settings.config XML（字节形式）。
        """
        config = ET.Element("config")

        obj_elem = ET.SubElement(config, "object", attrib={"id": str(assembly_id)})
        if self.slicer == "FlashStudio":
            ET.SubElement(
                obj_elem,
                "metadata",
                attrib={
                    "key": "name",
                    "value": os.path.splitext(os.path.basename(self.output_path))[0],
                },
            )
        ET.SubElement(obj_elem, "metadata", attrib={"key": "extruder", "value": "1"})

        source_file = os.path.basename(self.output_path)
        if material_index_by_object is None:
            resolved_material_indices = list(range(len(self.objects)))
        else:
            resolved_material_indices = material_index_by_object

        for idx, (entry, obj_id, material_index) in enumerate(
            zip(self.objects, object_ids, resolved_material_indices)
        ):
            bounds = np.asarray(getattr(entry.mesh, "bounds", np.zeros((2, 3))), dtype=np.float64)
            if bounds.shape != (2, 3):
                bounds = np.zeros((2, 3), dtype=np.float64)
            center_x, center_y, center_z = bounds.mean(axis=0)
            max_x, max_y, max_z = bounds[1]
            matrix_value = (
                "1 0 0 "
                f"{self._format_number(max_x)} "
                "0 1 0 "
                f"{self._format_number(max_y)} "
                "0 0 1 "
                f"{self._format_number(max_z)} "
                "0 0 0 1"
            )
            part = ET.SubElement(obj_elem, "part", attrib={"id": str(obj_id), "subtype": "normal_part"})
            ET.SubElement(part, "metadata", attrib={"key": "name", "value": entry.object_name})
            ET.SubElement(part, "metadata", attrib={"key": "matrix", "value": matrix_value})
            ET.SubElement(part, "metadata", attrib={"key": "source_file", "value": source_file})
            ET.SubElement(part, "metadata", attrib={"key": "source_object_id", "value": "0"})
            ET.SubElement(part, "metadata", attrib={"key": "source_volume_id", "value": str(idx)})
            ET.SubElement(part, "metadata", attrib={"key": "source_offset_x", "value": self._format_number(center_x)})
            ET.SubElement(part, "metadata", attrib={"key": "source_offset_y", "value": self._format_number(center_y)})
            ET.SubElement(part, "metadata", attrib={"key": "source_offset_z", "value": self._format_number(center_z)})
            ET.SubElement(part, "metadata", attrib={"key": "extruder", "value": str(material_index + 1)})
            ET.SubElement(
                part,
                "mesh_stat",
                attrib={
                    "edges_fixed": "0",
                    "degenerate_facets": "0",
                    "facets_removed": "0",
                    "facets_reversed": "0",
                    "backwards_edges": "0",
                },
            )

        plate = ET.SubElement(config, "plate")
        ET.SubElement(plate, "metadata", attrib={"key": "plater_id", "value": "1"})
        ET.SubElement(plate, "metadata", attrib={"key": "plater_name", "value": ""})
        ET.SubElement(plate, "metadata", attrib={"key": "locked", "value": "false"})
        if self._registry_build_plate is not None:
            ET.SubElement(
                plate,
                "metadata",
                attrib={
                    "key": "bed_type",
                    "value": self._registry_build_plate.plate_value,
                },
            )
        if not self._is_anycubic_slicer():
            ET.SubElement(plate, "metadata", attrib={"key": "filament_map_mode", "value": "Auto For Flush"})
        if self.slicer == "FlashStudio":
            material_palette, _ = self._build_material_palette()
            ET.SubElement(
                plate,
                "metadata",
                attrib={
                    "key": "filament_maps",
                    "value": " ".join(
                        str(index) for index in range(1, len(material_palette) + 1)
                    ),
                },
            )
        ET.SubElement(plate, "metadata", attrib={"key": "thumbnail_file", "value": "Metadata/plate_1.png"})
        ET.SubElement(
            plate, "metadata", attrib={"key": "thumbnail_no_light_file", "value": "Metadata/plate_no_light_1.png"}
        )
        ET.SubElement(plate, "metadata", attrib={"key": "top_file", "value": "Metadata/top_1.png"})
        ET.SubElement(plate, "metadata", attrib={"key": "pick_file", "value": "Metadata/pick_1.png"})

        model_instance = ET.SubElement(plate, "model_instance")
        ET.SubElement(model_instance, "metadata", attrib={"key": "object_id", "value": str(assembly_id)})
        ET.SubElement(model_instance, "metadata", attrib={"key": "instance_id", "value": "0"})
        ET.SubElement(model_instance, "metadata", attrib={"key": "identify_id", "value": self._get_identify_id()})

        tree = ET.ElementTree(config)
        ET.indent(tree, space="  ")

        buf = io.BytesIO()
        buf.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(buf, encoding="utf-8", xml_declaration=False)
        return buf.getvalue()

    def _build_wipe_tower_placement_metadata_bytes(self) -> bytes:
        """Serialize Lumina's derived placement and manual-warning state.

        序列化 Lumina 推导出的摆放结果及人工调整警告状态。
        """

        placement = self._get_wipe_tower_placement()
        if placement is None:
            log.warning(
                "Printable area unavailable for wipe-tower validation",
                extra={
                    "event": "wipe_tower_manual_adjustment_required",
                    "error_type": "PrintableAreaUnavailable",
                    "error_message": (
                        "Generated without scaling the model or disabling the wipe tower; "
                        "manual slicer validation is required."
                    ),
                    "path": self.output_path,
                    "printer_id": self.printer_id,
                    "slicer": self.slicer,
                },
            )
            payload: dict[str, Any] = {
                "schema_version": 1,
                "available": False,
                "adapted": False,
                "requires_manual_adjustment": True,
                "warning_code": WIPE_TOWER_MANUAL_WARNING_CODE,
                "reason": "printable_area_unavailable",
            }
        else:
            payload = {
                "schema_version": 1,
                "available": True,
                "adapted": placement.adapted,
                "requires_manual_adjustment": placement.requires_manual_adjustment,
                "warning_code": placement.warning_code,
                "reason": placement.reason,
                "model_translation_mm": list(placement.model_translation),
                "model_bounds_mm": [
                    placement.model_bounds.left,
                    placement.model_bounds.bottom,
                    placement.model_bounds.right,
                    placement.model_bounds.top,
                ],
                "model_outer_bounds_mm": [
                    placement.model_outer_bounds.left,
                    placement.model_outer_bounds.bottom,
                    placement.model_outer_bounds.right,
                    placement.model_outer_bounds.top,
                ],
                "tower": {
                    "x_mm": placement.tower_x,
                    "y_mm": placement.tower_y,
                    "width_mm": placement.tower_width,
                    "estimated_depth_mm": placement.tower_depth,
                    "rotation_deg": placement.tower_rotation,
                    "outer_bounds_mm": [
                        placement.tower_outer_bounds.left,
                        placement.tower_outer_bounds.bottom,
                        placement.tower_outer_bounds.right,
                        placement.tower_outer_bounds.top,
                    ],
                },
            }
        return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    def _build_project_settings_bytes(self) -> bytes:
        """Build project_settings.config JSON as bytes.
        构建 project_settings.config JSON（字节形式）。
        """
        material_palette, _ = self._build_material_palette()
        num_colors = len(material_palette)

        settings = self._get_base_config_template()
        printer_settings_id = settings.get("printer_settings_id")
        if isinstance(printer_settings_id, str) and printer_settings_id.strip():
            # A project-scoped Lumina process must be valid for the machine
            # selected for this export. Stale template compatibility lists can
            # otherwise make Orca-family slicers reject the file before slicing.
            settings["print_compatible_printers"] = [printer_settings_id]
        template_settings = copy.deepcopy(settings)
        preserve_template_filament_slots = _should_preserve_template_filament_slots(
            self._registry_device_profile,
            template_settings,
            num_colors,
            self.preserve_template_filament_slots,
        )
        if "different_settings_to_system" in settings:
            settings["different_settings_to_system"] = _normalize_difference_index(
                settings.get("different_settings_to_system")
            )

        for key, value in settings.items():
            if isinstance(value, list) and len(value) > 0:
                if preserve_template_filament_slots:
                    continue
                if key in _FILAMENT_SQUARE_GROUP_ARRAY_KEYS:
                    settings[key] = _resize_filament_square_array(
                        value,
                        template_settings=template_settings,
                        material_count=num_colors,
                    )
                elif key in _FILAMENT_LINEAR_GROUP_ARRAY_KEYS or _is_filament_linear_array_key(key):
                    settings[key] = _resize_filament_linear_array(
                        key,
                        value,
                        template_settings=template_settings,
                        material_count=num_colors,
                    )

        _apply_filament_array_overrides(
            settings,
            self._build_filament_arrays(material_palette),
            preserve_template_slots=preserve_template_filament_slots,
        )
        _apply_material_filament_metadata(settings, template_settings, material_palette)
        if self.slicer == "OrcaSlicer":
            _collapse_orca_linear_arrays(
                settings,
                num_colors,
                template_settings=template_settings,
            )
        if self.slicer == "FlashStudio":
            _apply_flashstudio_project_metadata(settings, num_colors)
        if not preserve_template_filament_slots:
            filament_colour = settings.get("filament_colour")
            if isinstance(filament_colour, list):
                settings["filament_multi_colour"] = list(filament_colour)
            _disable_cut_retraction_filament_overrides(settings, num_colors)
            _validate_trimmed_project_filament_arrays(
                settings,
                num_colors,
                template_settings=template_settings,
            )

        settings.setdefault("single_extruder_multi_material", "1")
        # Product invariant: generated files never silently disable the tower.
        # 产品约束：生成文件绝不静默关闭擦料塔。
        settings["enable_prime_tower"] = "1"

        applied_override_keys: list[str] = ["enable_prime_tower"]
        if self.slicer == "OrcaSlicer":
            # Orca 2.4 may erase broad printable regions when its precise-wall
            # correction is combined with Lumina's Arachne one-wall artwork
            # process. Keep Arachne and the one-wall detail contract, but turn
            # off only that incompatible correction in the saved project.
            settings["precise_outer_wall"] = "0"
            applied_override_keys.append("precise_outer_wall")
        if self.settings:
            for key in [
                "layer_height",
                "initial_layer_height",
                "line_width",
                "initial_layer_line_width",
                "wall_loops",
                "top_shell_layers",
                "bottom_shell_layers",
                "bottom_surface_pattern",
                "elefant_foot_compensation",
                "sparse_infill_density",
                "sparse_infill_pattern",
                "print_speed",
                "travel_speed",
                "enable_support",
                "brim_width",
                "brim_type",
            ]:
                if key in self.settings:
                    settings[key] = self.settings[key]
                    applied_override_keys.append(key)

        placement = self._get_wipe_tower_placement()
        if placement is not None:
            settings["wipe_tower_x"] = self._replace_first_config_number(
                settings.get("wipe_tower_x"), placement.tower_x
            )
            settings["wipe_tower_y"] = self._replace_first_config_number(
                settings.get("wipe_tower_y"), placement.tower_y
            )
            settings["prime_tower_width"] = self._format_number(
                placement.tower_width
            )
            settings["wipe_tower_rotation_angle"] = self._format_number(
                placement.tower_rotation
            )
            if placement.adapted:
                applied_override_keys.extend(
                    (
                        "wipe_tower_x",
                        "wipe_tower_y",
                        "prime_tower_width",
                        "wipe_tower_rotation_angle",
                    )
                )

        # Ensure BambuStudio/Orca's "modified-from-system-default" index
        # includes every key we actually overrode; otherwise the slicer
        # may silently revert the override to the preset default on open.
        # 确保切片器的 "与系统默认不同" 索引包含所有被覆盖的 key，
        # 否则打开 3mf 时切片器可能会静默把覆盖值回退到预设默认值。
        if applied_override_keys:
            settings["different_settings_to_system"] = _normalize_difference_index(
                settings.get("different_settings_to_system"),
                applied_override_keys,
            )

        if self._registry_build_plate is not None:
            settings["curr_bed_type"] = self._registry_build_plate.project_value

        _apply_snapmaker_u1_native_project_shape(
            settings,
            self._registry_device_profile,
        )

        return json.dumps(settings, indent=4, ensure_ascii=False).encode("utf-8")

    def _build_slice_info_bytes(self) -> bytes:
        """Build slice_info.config XML as bytes.
        构建 slice_info.config XML（字节形式）。
        """
        config = ET.Element("config")
        header = ET.SubElement(config, "header")
        registry_source_version = self._get_registry_source_version()
        registry_client_version = self._get_registry_client_version() or registry_source_version
        if self._is_anycubic_slicer():
            ET.SubElement(header, "header_item", attrib={"key": "X-ACNext-Client-Type", "value": "slicer"})
            ET.SubElement(
                header,
                "header_item",
                attrib={
                    "key": "X-ACNext-Client-Version",
                    "value": self._get_anycubic_client_version(),
                },
            )
        else:
            ET.SubElement(header, "header_item", attrib={"key": "X-BBL-Client-Type", "value": "slicer"})
            if self.slicer == "BambuStudio":
                client_version = registry_client_version or self._get_bambu_client_version()
                ET.SubElement(header, "header_item", attrib={"key": "X-BBL-Client-Version", "value": client_version})
            elif self.slicer == "ElegooSlicer":
                ET.SubElement(
                    header,
                    "header_item",
                    attrib={"key": "X-BBL-Client-Version", "value": registry_client_version or "01.03.02.09"},
                )
                ET.SubElement(header, "header_item", attrib={"key": "X-BBL-Client-Name", "value": "ElegooSlicer"})
            elif self.slicer == "SnapmakerOrca":
                ET.SubElement(
                    header,
                    "header_item",
                    attrib={
                        "key": "X-BBL-Client-Version",
                        "value": registry_client_version or self._get_snapmaker_orca_client_version(),
                    },
                )
            elif self.slicer == "FlashStudio":
                ET.SubElement(
                    header,
                    "header_item",
                    attrib={
                        "key": "X-BBL-Client-Version",
                        "value": "",
                    },
                )
            else:
                ET.SubElement(
                    header,
                    "header_item",
                    attrib={"key": "X-BBL-Client-Version", "value": registry_client_version or ""},
                )
                orca_version = self._get_orca_slicer_version_tag()
                if orca_version:
                    ET.SubElement(
                        header,
                        "header_item",
                        attrib={"key": "OrcaSlicer-Version", "value": orca_version},
                    )

        if self.slicer == "FlashStudio":
            uuid_seed = ":".join(
                [
                    "lumina-flashstudio",
                    self.printer_id,
                    self.nozzle_size,
                    *(entry.object_name for entry in self.objects),
                ]
            )
            ET.SubElement(
                header,
                "uuid",
                attrib={"value": uuid.uuid5(uuid.NAMESPACE_URL, uuid_seed).hex},
            )

        tree = ET.ElementTree(config)
        ET.indent(tree, space="  ")

        buf = io.BytesIO()
        buf.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(buf, encoding="utf-8", xml_declaration=False)
        return buf.getvalue()

    @staticmethod
    def _build_filament_sequence_bytes() -> bytes:
        """Build filament_sequence.json as bytes.
        构建 filament_sequence.json（字节形式）。
        """
        data = {"plate_1": {"sequence": []}}
        return json.dumps(data, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _build_cut_information_bytes(object_id: int = 1) -> bytes:
        """Build cut_information.xml as bytes.
        构建 cut_information.xml（字节形式）。
        """
        config = ET.Element("objects")
        obj = ET.SubElement(config, "object", attrib={"id": str(int(object_id))})
        ET.SubElement(obj, "cut_id", attrib={"id": "0", "check_sum": "1", "connectors_cnt": "0"})

        tree = ET.ElementTree(config)
        ET.indent(tree, space=" ")

        buf = io.BytesIO()
        buf.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        tree.write(buf, encoding="utf-8", xml_declaration=False)
        return buf.getvalue()

    @staticmethod
    def _build_custom_gcode_per_layer_bytes() -> bytes:
        """Build Anycubic custom_gcode_per_layer.xml as bytes.
        构建 Anycubic 的 custom_gcode_per_layer.xml（字节形式）。
        """
        config = ET.Element("custom_gcodes_per_layer")
        plate = ET.SubElement(config, "plate")
        ET.SubElement(plate, "plate_info", attrib={"id": "1"})
        ET.SubElement(plate, "mode", attrib={"value": "MultiExtruder"})

        tree = ET.ElementTree(config)
        ET.indent(tree, space="  ")

        buf = io.BytesIO()
        buf.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        tree.write(buf, encoding="utf-8", xml_declaration=False)
        return buf.getvalue()

    @staticmethod
    def _build_preview_placeholder_png_bytes() -> bytes:
        """Build a tiny valid PNG payload for referenced plate preview assets.

        构建一个微型合法 PNG，用于未渲染时占位 ``Metadata/plate_*.png`` /
        ``top_*.png`` / ``pick_*.png`` 等预览资源。

        Returns:
            bytes: A Pillow-generated 2x2 opaque grey PNG, guaranteed to pass
                ``PIL.Image.verify()`` and any downstream PNG decoder. The
                result is cached at module level so repeated calls during a
                single export are free.
                （由 Pillow 生成的 2x2 不透明灰色 PNG，保证能通过
                ``PIL.Image.verify()`` 以及下游任意 PNG 解码器；模块级缓存，
                同一次导出多次调用零额外开销）

        Notes:
            The previous implementation was a hardcoded 68-byte payload whose
            ``IDAT`` chunk CRC was incorrect. Bambu Studio and Orca-family
            slicers silently ignore malformed thumbnails and render a blank
            tile, but Anycubic Slicer Next decodes every referenced
            ``Metadata/*.png`` eagerly on import and crashes on the bad CRC,
            producing a Windows ``Application Hang`` event.
            （此前硬编码的 68 字节占位 PNG 的 ``IDAT`` chunk CRC 错误；
            Bambu Studio 与 Orca 家族切片器对坏缩略图静默降级，
            但纵维立方切片软件 Anycubic Slicer Next 在导入时会预渲染每一张
            ``Metadata/*.png``，遇到坏 CRC 直接崩溃，在 Windows 事件日志中
            表现为 ``Application Hang``。）
        """
        global _PREVIEW_PLACEHOLDER_PNG_BYTES
        if _PREVIEW_PLACEHOLDER_PNG_BYTES is None:
            image = Image.new("RGBA", (2, 2), (128, 128, 128, 255))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            _PREVIEW_PLACEHOLDER_PNG_BYTES = buffer.getvalue()
        return _PREVIEW_PLACEHOLDER_PNG_BYTES

    @staticmethod
    def _build_flashstudio_plate_small_bytes(plate_main: bytes) -> bytes:
        """Build Flash Studio's native 128x128 plate preview.

        构建 Flash Studio 原生的 128x128 ``plate_1_small.png``。
        """

        with Image.open(io.BytesIO(plate_main)) as image:
            resized = image.convert("RGBA").resize(
                (128, 128),
                Image.Resampling.LANCZOS,
            )
            buffer = io.BytesIO()
            resized.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()

    def _build_flashstudio_plate_json_bytes(self) -> bytes:
        """Build Flash Studio plate summary while retaining Lumina process values.

        构建 Flash Studio 的盘面摘要；层高等工艺值继续读取 Lumina 设置，
        不复制参考 3MF 的具体切片任务数据。
        """

        translate_x, translate_y, _ = self._get_build_item_translation()
        all_boxes: list[tuple[float, float, float, float]] = []
        try:
            layer_height = float(self.settings.get("layer_height", "0.08"))
        except (TypeError, ValueError):
            layer_height = 0.08

        for entry in self.objects:
            bounds = np.asarray(
                getattr(entry.mesh, "bounds", np.zeros((2, 3))),
                dtype=np.float64,
            )
            if bounds.shape != (2, 3):
                continue
            bbox = (
                float(bounds[0, 0] + translate_x),
                float(bounds[0, 1] + translate_y),
                float(bounds[1, 0] + translate_x),
                float(bounds[1, 1] + translate_y),
            )
            all_boxes.append(bbox)

        if all_boxes:
            bbox_all = [
                min(box[0] for box in all_boxes),
                min(box[1] for box in all_boxes),
                max(box[2] for box in all_boxes),
                max(box[3] for box in all_boxes),
            ]
        else:
            bbox_all = [0.0, 0.0, 0.0, 0.0]

        object_entries: list[dict[str, Any]] = []
        if all_boxes:
            # Flash Studio summarizes a multi-part/material assembly as one
            # printable plate object. Wipe-tower and timing entries are added
            # by the slicer only after slicing and must not be fabricated here.
            object_entries.append(
                {
                    "area": max(0.0, bbox_all[2] - bbox_all[0])
                    * max(0.0, bbox_all[3] - bbox_all[1]),
                    "bbox": bbox_all,
                    "id": 1,
                    "layer_height": layer_height,
                    "name": os.path.splitext(os.path.basename(self.output_path))[0],
                }
            )

        payload = {
            "bbox_all": bbox_all,
            "bbox_objects": object_entries,
            "bed_type": (
                self._registry_build_plate.sidecar_value
                if self._registry_build_plate is not None
                and self._registry_build_plate.sidecar_value
                else "textured_plate"
            ),
            "filament_colors": [],
            "filament_ids": [],
            "first_extruder": 0,
            "first_layer_time": 0.0,
            "is_seq_print": False,
            "nozzle_diameter": float(self.nozzle_size),
            "version": 2,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    # ------------------------------------------------------------------
    # Config template & filament arrays (unchanged logic)
    # ------------------------------------------------------------------

    def _get_base_config_template(self) -> dict:
        """Get complete BambuStudio configuration template for the selected printer.
        获取所选机型的完整 BambuStudio 配置模板。

        Uses load_printer_template() to load printer-specific templates from
        printer_profiles/ directory, falling back to bambu_config_template.json.

        Returns:
            dict: Complete configuration template. (完整配置模板)
        """
        template = load_printer_template(
            self.printer_id,
            slicer=self.slicer,
            nozzle_size=self.nozzle_size,
            device_profile_id=self.device_profile_id,
        )
        if template:
            return template

        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            template_path = os.path.join(sys._MEIPASS, "bambu_config_template.json")
        else:
            template_path = os.path.join(os.path.dirname(__file__), "..", "bambu_config_template.json")

        global _CONFIG_TEMPLATE_CACHE
        if os.path.exists(template_path):
            if _CONFIG_TEMPLATE_CACHE is None:
                with open(template_path, "r", encoding="utf-8") as f:
                    _CONFIG_TEMPLATE_CACHE = json.load(f)
            return copy.deepcopy(_CONFIG_TEMPLATE_CACHE)
        else:
            log.warning(
                "Bambu config template not found; using minimal config",
                extra={
                    "event": "bambu_config_template_missing",
                    "path": template_path,
                    "printer_id": self.printer_id,
                    "slicer": self.slicer,
                },
            )
            return self._get_minimal_config_template()

    @staticmethod
    def _get_minimal_config_template() -> dict:
        """Fallback minimal configuration template."""
        return {
            "layer_height": "0.08",
            "initial_layer_height": "0.08",
            "wall_loops": "1",
            "top_shell_layers": "0",
            "bottom_shell_layers": "1",
            "bottom_surface_pattern": "monotonicline",
            "elefant_foot_compensation": "0",
            "sparse_infill_density": "100%",
            "sparse_infill_pattern": "zig-zag",
            "nozzle_temperature": ["220"] * 8,
            "nozzle_temperature_initial_layer": ["220"] * 8,
        }

    def _build_filament_arrays(self, material_palette: list[tuple[str, tuple[int, int, int]]]) -> dict:
        """Build filament-related arrays for the shared material palette.
        为共享材料调色板构建耗材相关数组。

        Args:
            material_palette: Ordered shared material palette.
                （有序的共享材料调色板）

        Returns:
            dict: Filament arrays with correct lengths.
                （长度正确的耗材数组）
        """
        arrays: dict[str, list] = {}

        arrays["filament_colour"] = []
        for _, color_rgb in material_palette:
            hex_color = f"#{color_rgb[0]:02X}{color_rgb[1]:02X}{color_rgb[2]:02X}"
            arrays["filament_colour"].append(hex_color)

        return arrays


# ======================================================================
# Public convenience function (signature unchanged from original)
# ======================================================================


def read_wipe_tower_placement_warnings(
    threemf_path: str | os.PathLike[str],
) -> list[str]:
    """Read stable wipe-tower warning codes embedded in a generated 3MF.

    读取生成 3MF 内嵌的稳定擦料塔警告代码。旧文件或无警告文件返回空列表。

    Args:
        threemf_path: Generated 3MF path. (生成的 3MF 路径)

    Returns:
        list[str]: Warning codes requiring user attention. (需要用户处理的警告代码)
    """

    metadata_path = "Metadata/lumina_wipe_tower_placement.json"
    try:
        with zipfile.ZipFile(os.fspath(threemf_path), "r") as package:
            if metadata_path not in package.namelist():
                return []
            payload = json.loads(package.read(metadata_path).decode("utf-8"))
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or not payload.get("requires_manual_adjustment"):
        return []
    warning_code = payload.get("warning_code")
    if not isinstance(warning_code, str) or not warning_code.strip():
        return []
    return [warning_code.strip()]


def export_scene_with_bambu_metadata(
    scene: _get_trimesh().Scene,
    output_path: str,
    slot_names: List[str],
    preview_colors: Dict,
    settings: Optional[Dict] = None,
    color_mode: str = "4-Color",
    printer_id: str = "bambu-h2d",
    slicer: str = "BambuStudio",
    nozzle_size: Optional[str | float] = None,
    watermark: str = "LuminaStudio",
    project_slot_names: Optional[List[str]] = None,
    *,
    enable_base_layer_height_modifier: bool = True,
    enable_relief: bool = False,
    base_height_mm: float = 0.0,
    color_height_mm: float = 0.0,
    face_orientation: str = "down",
    backing_infill_density_percent: int = 100,
    cover_source: "str | bytes | Image.Image | None" = None,
    device_profile_id: Optional[str] = None,
    build_plate_id: Optional[str] = None,
    preserve_template_filament_slots: Optional[bool] = None,
):
    """Export a Trimesh scene to BambuStudio/OrcaSlicer-compatible 3MF with metadata.
    将 Trimesh 场景导出为 BambuStudio/OrcaSlicer 兼容的 3MF 文件（含元数据）。

    Args:
        scene (_get_trimesh().Scene): Trimesh Scene containing all meshes. (包含所有网格的场景)
        output_path (str): Output .3mf file path. (输出 .3mf 文件路径)
        slot_names (List[str]): Actually used material names. (实际使用的材料名称列表)
        preview_colors (Dict): Material ID to RGBA color mapping. (材料 ID 到 RGBA 颜色映射)
        settings (Optional[Dict]): Custom print settings. (自定义打印设置)
        color_mode (str): Color mode ('4-Color', '6-Color', '8-Color', 'BW'). (颜色模式)
        printer_id (str): Printer identifier for template selection, default 'bambu-h2d'. (打印机标识)
        slicer (str): Slicer software identifier, default 'BambuStudio'. (切片器标识)
        nozzle_size (Optional[str | float]): Nozzle size variant used for template selection.
            (用于模板选择的喷嘴尺寸变体)
        watermark (str): Watermark text embedded in the 3MF ZIP structure. (嵌入 3MF ZIP 结构的水印文本)
        project_slot_names (Optional[List[str]]): Full selected source palette/material names to preserve
            in exported project metadata when available. (可选，导出项目元数据时应保留的完整来源调色板/材料名称)
        enable_base_layer_height_modifier (bool): Whether to emit layer_config_ranges.xml.
            （是否输出 layer_config_ranges.xml）
        enable_relief (bool): Whether variable-height relief geometry is enabled. Relief
            exports never emit ``layer_config_ranges.xml``.（是否启用可变高度浮雕；
            浮雕导出始终不输出 ``layer_config_ranges.xml``。）
        base_height_mm (float): Backing/base thickness used for coarse layer-height override.
            （用于粗层高覆盖的底板厚度）
        color_height_mm (float): Colored-region thickness used to place the override range.
            （用于定位覆盖区间的彩色区域厚度）
        face_orientation (str): Base orientation selector passed to the writer.
            （透传给写入器的底板朝向）
        backing_infill_density_percent (int): Requested deep-backing infill
            percentage. The writer promotes fully protected backing to 100 and
            emits viewing-surface solid ranges for deeper backing.
            （请求的深层底板填充百分比；写入器会把完全受保护的底板提升为 100%，
            并为较深底板输出观赏面实心区间。）
        cover_source: Cover thumbnail image source. ``None`` uses silent
            placeholder (calibration / kit / recipe swatch / 既有调用方默认值);
            ``str`` is a filesystem path, ``bytes`` is encoded image bytes,
            ``PIL.Image.Image`` is a decoded image. Decode failures fall back
            to placeholder bytes plus one WARNING log per export.
            （封面缩略图图像源；``None`` 走静默占位，保持既有调用方零侵入）
        device_profile_id (Optional[str]): Slicer-scoped generated registry
            device profile ID used to select native machine metadata.
            （切片软件维度的注册表设备配置 ID，用于选择原生机型元数据）
        build_plate_id (Optional[str]): Native build-plate identifier for the
            selected device profile.（所选设备配置的原生打印板 ID）
        preserve_template_filament_slots (Optional[bool]): Override whether a
            registry-backed project keeps the template's native filament slot
            count. ``False`` trims project filament arrays to the selected
            palette.（是否覆盖注册表模板原生耗材槽保留策略；``False`` 会按已选
            调色板裁剪项目耗材数组。）

    Returns:
        str: Path to the exported 3MF file. (导出的 3MF 文件路径)
    """
    if scene is None:
        raise ValueError("[BAMBU_3MF] Scene is None")
    if not slot_names:
        raise ValueError("[BAMBU_3MF] slot_names is empty - no exportable objects")

    resolved_project_slot_names = [str(name) for name in (project_slot_names or []) if str(name)]
    palette_color_count = len(resolved_project_slot_names) if resolved_project_slot_names else len(slot_names)

    if palette_color_count <= 2:
        actual_color_mode = "BW"
    elif palette_color_count <= 4:
        actual_color_mode = "4-Color"
    elif palette_color_count <= 6:
        actual_color_mode = "6-Color"
    else:
        actual_color_mode = "8-Color"

    log.debug(
        "Resolved Bambu 3MF color mode",
        extra={
            "event": "bambu_3mf_color_mode_resolved",
            "path": output_path,
            "input_color_mode": color_mode,
            "palette_color_count": palette_color_count,
            "actual_color_mode": actual_color_mode,
        },
    )

    writer_kwargs = {
        "output_path": output_path,
        "settings": settings,
        "color_mode": actual_color_mode,
        "printer_id": printer_id,
        "slicer": slicer,
        "nozzle_size": nozzle_size,
        "watermark": watermark,
        "cover_source": cover_source,
        "device_profile_id": device_profile_id,
        "build_plate_id": build_plate_id,
        "preserve_template_filament_slots": preserve_template_filament_slots,
        "enable_relief": bool(enable_relief),
        "enable_base_layer_height_modifier": bool(
            enable_base_layer_height_modifier
        ),
        "base_height_mm": float(base_height_mm),
        "color_height_mm": float(color_height_mm),
        "face_orientation": face_orientation,
        "backing_infill_density_percent": backing_infill_density_percent,
    }
    writer = BambuStudio3MFWriter(**writer_kwargs)
    if resolved_project_slot_names:
        writer._set_project_palette(resolved_project_slot_names, preview_colors)

    name_to_color: dict[str, tuple] = {}
    project_slot_indices = {name: idx for idx, name in enumerate(resolved_project_slot_names)}
    color_sources: dict[str, int] = {}
    for idx, slot_name in enumerate(slot_names):
        resolved_slot_index = project_slot_indices.get(slot_name, idx)
        color_rgb, source = _resolve_preview_color_for_slot_name(
            slot_name=slot_name,
            slot_index=resolved_slot_index,
            preview_colors=preview_colors,
        )
        name_to_color[slot_name] = color_rgb
        color_sources[source] = color_sources.get(source, 0) + 1
        log.debug(
            "Resolved Bambu 3MF slot color",
            extra={
                "event": "bambu_3mf_slot_color_resolved",
                "path": output_path,
                "slot_index": idx,
                "slot_name": slot_name,
                "color_rgb": color_rgb,
                "source": source,
            },
        )

    unmatched = []
    added_count = 0
    for idx, slot_name in enumerate(slot_names):
        mesh = scene.geometry.get(slot_name)
        if mesh is None:
            unmatched.append(slot_name)
            log.debug(
                "Slot mesh not found in scene",
                extra={
                    "event": "bambu_3mf_slot_mesh_missing",
                    "path": output_path,
                    "slot_index": idx,
                    "slot_name": slot_name,
                },
            )
            continue

        color_rgb = name_to_color.get(slot_name, (200, 200, 200))
        writer.add_mesh(mesh, slot_name, color_rgb)
        added_count += 1
        log.debug(
            "Added slot mesh to Bambu 3MF",
            extra={
                "event": "bambu_3mf_slot_mesh_added",
                "path": output_path,
                "slot_index": idx,
                "slot_name": slot_name,
                "color_rgb": color_rgb,
            },
        )

    if unmatched:
        raise ValueError("[BAMBU_3MF] Missing geometries for slot names: " + ", ".join(unmatched))

    log.debug(
        "Prepared Bambu 3MF scene",
        extra={
            "event": "bambu_3mf_scene_prepared",
            "path": output_path,
            "slot_count": len(slot_names),
            "added_count": added_count,
            "color_source_counts": color_sources,
        },
    )

    return writer.export()


def _resolve_preview_color_for_slot_name(
    slot_name: str,
    slot_index: int,
    preview_colors: Dict,
) -> tuple[tuple[int, int, int], str]:
    """Resolve a slot color from preview metadata.

    根据预览颜色元数据解析槽位颜色。

    Args:
        slot_name: User-facing slot/material name.
            用户可见的槽位或材料名称。
        slot_index: Compact slot index in the current export order.
            当前导出顺序中的紧凑槽位索引。
        preview_colors: Preview color mapping from the pipeline cache.
            来自流水线缓存的预览颜色映射。

    Returns:
        tuple[tuple[int, int, int], str]:
            Resolved RGB color and a short resolution source label.
            解析得到的 RGB 颜色，以及解析来源标记。
    """

    if slot_name in preview_colors:
        return _coerce_preview_rgb(preview_colors[slot_name]), "by name"

    slot_number = _parse_slot_number(slot_name)
    if slot_number is not None:
        slot_key = slot_number - 1
        if slot_key in preview_colors:
            return _coerce_preview_rgb(preview_colors[slot_key]), "by slot"
        slot_key_str = str(slot_key)
        if slot_key_str in preview_colors:
            return _coerce_preview_rgb(preview_colors[slot_key_str]), "by slot"

    if slot_index in preview_colors:
        return _coerce_preview_rgb(preview_colors[slot_index]), "by index"

    slot_index_str = str(slot_index)
    if slot_index_str in preview_colors:
        return _coerce_preview_rgb(preview_colors[slot_index_str]), "by index"

    return (200, 200, 200), "fallback"


def _parse_slot_number(slot_name: str) -> int | None:
    """Extract a 1-based slot number from a slot label when present.

    从槽位名称中提取 1-based 槽位编号。
    """

    match = re.match(r"Slot\s+(\d+)\b", slot_name)
    if match is None:
        return None
    return int(match.group(1))


def _coerce_preview_rgb(value: object) -> tuple[int, int, int]:
    """Coerce a preview-color value into an RGB tuple.

    将预览颜色值转换为 RGB 元组。
    """

    if isinstance(value, np.ndarray):
        channels = value.tolist()
    elif isinstance(value, (list, tuple)):
        channels = list(value)
    else:
        raise ValueError(f"Unsupported preview color value: {type(value)!r}")

    if len(channels) < 3:
        raise ValueError("Preview color value must have at least 3 channels.")
    return tuple(int(channel) for channel in channels[:3])
