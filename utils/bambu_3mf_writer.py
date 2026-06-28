"""
Lumina Studio - BambuStudio 3MF Writer
Enhanced 3MF export with BambuStudio-compatible metadata and configurations.

Uses neroued-3mf (C++ streaming writer with Production Extension) for 3MF
packaging, and injects Bambu/Orca vendor metadata via CustomPart.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import os
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
import json
import copy
import re
from typing import Any, BinaryIO, Iterable, List, Dict, Optional
import numpy as np
from PIL import Image

from api.structured_logging import get_logger
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
    """Return configured machine registry root, defaulting to cwd/machine_registry.

    返回机器注册表根目录；未配置环境变量时使用当前工作目录下的
    ``machine_registry``，与系统设置 API 的默认读取位置保持一致。
    """
    raw_root = os.environ.get("LUMINA_MACHINE_REGISTRY_DIR", "").strip()
    return os.path.abspath(raw_root or "machine_registry")


def _registry_printer_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


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
    if overlay_machine_settings:
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
        overlay_machine_settings
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
    from config import PRINTER_PROFILES, normalize_printer_profile_id, normalize_slicer_software_id
    from core.machine_registry import load_machine_registry

    normalized_printer_id = normalize_printer_profile_id(str(printer_id or ""))
    requested_printer = PRINTER_PROFILES.get(normalized_printer_id)
    normalized_slicer = normalize_slicer_software_id(str(slicer or ""))
    registry = load_machine_registry(registry_path)
    try:
        profile = registry.get_device_profile(device_profile_id)
    except KeyError as exc:
        raise ValueError(f"Unknown machine registry device profile: {device_profile_id}") from exc

    if not profile.supported:
        raise ValueError(f"Machine registry device profile is not supported: {device_profile_id}")

    if profile.slicer_id != normalized_slicer or profile.nozzle_size != nozzle_size:
        raise ValueError(
            "Machine registry device profile does not match requested slicer/nozzle: "
            f"{device_profile_id} != {normalized_slicer}/{nozzle_size}"
        )
    if requested_printer is not None and (
        profile.display_name.casefold() != requested_printer.display_name.casefold()
        or profile.brand.casefold() != requested_printer.brand.casefold()
    ):
        raise ValueError(
            "Machine registry device profile does not match requested printer: "
            f"{device_profile_id} != {requested_printer.brand}/{requested_printer.display_name}"
        )
    if requested_printer is None:
        registry_printer_ids = {
            _registry_printer_slug(profile.display_name),
            _registry_printer_slug(f"{profile.brand}-{profile.display_name}"),
            profile.machine_profile_id.casefold(),
        }
        if normalized_printer_id not in registry_printer_ids:
            raise ValueError(
                "Machine registry device profile does not match requested printer: "
                f"{device_profile_id} != {printer_id}"
            )
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


def build_layer_config_ranges_xml(
    *,
    base_height_mm: float,
    color_height_mm: float,
    nozzle_mm: float,
    face: str,
    fine_layer_height_mm: float = 0.08,
    object_id: int = 1,
) -> bytes | None:
    """Build Metadata/layer_config_ranges.xml for base-plate coarse layer height.
    为底板粗层高生成 Metadata/layer_config_ranges.xml。

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
        object_id (int): One-based model-object index written into the XML payload.
            （写入 XML 载荷的模型对象序号，从 1 开始）

    Returns:
        bytes | None: UTF-8 XML bytes when a coarse-layer override is required, otherwise `None`.
            （当需要粗层高覆盖时返回 UTF-8 XML 字节，否则返回 `None`）

    Raises:
        ValueError: If numeric inputs cannot be converted to floats.
            （当数值输入无法转换为浮点数时抛出）
    """
    base_height = float(base_height_mm)
    color_height = float(color_height_mm)
    nozzle = float(nozzle_mm)
    fine_layer_height = float(fine_layer_height_mm)
    normalized_face = str(face).strip().lower()

    coarse_lh = nozzle * 0.5
    if base_height <= 0:
        return None
    if coarse_lh <= fine_layer_height:
        return None
    if color_height < 0 or nozzle <= 0:
        return None
    if normalized_face not in _VALID_LAYER_CONFIG_FACES:
        return None

    if normalized_face == "up":
        min_z = 0.0
        max_z = base_height
    else:
        min_z = color_height
        max_z = color_height + base_height

    xml_text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<objects>\n"
        f' <object id="{object_id}">\n'
        f'  <range min_z="{min_z:.17g}" max_z="{max_z:.17g}">\n'
        '   <option opt_key="extruder">0</option>\n'
        f'   <option opt_key="layer_height">{coarse_lh:.17g}</option>\n'
        "  </range>\n"
        " </object>\n"
        "</objects>\n"
    )
    return xml_text.encode("utf-8")


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
                normalized_nozzle_size,
            )
            overlay_printer_model = False
            overlay_machine_settings = False
            if legacy_template_entry is None:
                legacy_template_entry = _load_registry_compatibility_project_template_if_available(
                    profile,
                    normalized_slicer,
                    registry_nozzle_size,
                )
                overlay_printer_model = legacy_template_entry is not None
                overlay_machine_settings = legacy_template_entry is not None
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
                    source_version=profile.source_version,
                    overlay_printer_model=overlay_printer_model,
                    overlay_machine_settings=overlay_machine_settings,
                    align_default_filament_settings=_is_snapmaker_u1_registry_profile(profile),
                    retarget_profile_nozzle_labels=(
                        registry_nozzle_size != normalized_nozzle_size
                    ),
                    legacy_nozzle_size=normalized_nozzle_size,
                    registry_nozzle_size=registry_nozzle_size,
                )
            else:
                template = registry_template
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

    cache_key = f"{printer_id}:{normalized_slicer}:{normalized_nozzle_size}:legacy"
    if cache_key in _PRINTER_TEMPLATE_CACHE:
        return copy.deepcopy(_PRINTER_TEMPLATE_CACHE[cache_key])

    profile = get_printer_profile(printer_id)
    template_file = profile.get_template_file(normalized_slicer, nozzle_size=normalized_nozzle_size)

    # Resolve printer_profiles/ directory
    base_dir = _resource_base_dir()

    profile_path = os.path.join(base_dir, "printer_profiles", template_file)

    if os.path.exists(profile_path):
        with open(profile_path, "r", encoding="utf-8") as f:
            template = json.load(f)
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
        base_height_mm: float = 0.0,
        color_height_mm: float = 0.0,
        face_orientation: str = "down",
        cover_source: "str | bytes | Image.Image | None" = None,
        device_profile_id: Optional[str] = None,
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
            base_height_mm (float): Backing/base thickness used for coarse layer-height override.
                （用于粗层高覆盖的底板厚度）
            color_height_mm (float): Colored-region thickness used to place the override range.
                （用于定位覆盖区间的彩色区域厚度）
            face_orientation (str): Base orientation selector; invalid values fall back to "down".
                （底板朝向；非法值静默回退到 "down"）
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
        from config import format_native_nozzle_size, normalize_nozzle_size, normalize_slicer_software_id

        self.output_path = output_path
        self.settings = {**self.DEFAULT_SETTINGS, **(settings or {})}
        self.objects: list[_MeshExportEntry] = []
        self.color_mode = color_mode
        self.printer_id = printer_id
        self.slicer = normalize_slicer_software_id(slicer)
        self.device_profile_id = str(device_profile_id or "").strip() or None
        legacy_nozzle_size = normalize_nozzle_size(nozzle_size) or "0.4"
        self.nozzle_size = (
            format_native_nozzle_size(nozzle_size) or legacy_nozzle_size
            if self.device_profile_id
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
        self.watermark = watermark
        self.enable_base_layer_height_modifier = bool(enable_base_layer_height_modifier)
        self.base_height_mm = float(base_height_mm)
        self.color_height_mm = float(color_height_mm)
        normalized_face_orientation = str(face_orientation).strip().lower()
        if normalized_face_orientation not in _VALID_LAYER_CONFIG_FACES:
            normalized_face_orientation = "down"
        self.face_orientation = normalized_face_orientation
        self._project_slot_names: list[str] = []
        self._project_preview_colors: dict | None = None
        self.cover_source: "str | bytes | Image.Image | None" = cover_source
        self.cover_bundle: Optional[CoverPngBundle] = None
        self.preserve_template_filament_slots = preserve_template_filament_slots

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

    def _set_project_palette(self, slot_names: list[str], preview_colors: Dict) -> None:
        """Configure the project-wide palette used for exported metadata.

        配置导出元数据使用的项目级完整调色板。
        """

        self._project_slot_names = [str(name) for name in slot_names if str(name)]
        self._project_preview_colors = dict(preview_colors or {})

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
            "SnapmakerOrca": "BambuStudio-2.2.4",
            "ElegooSlicer": "ElegooSlicer-1.3.2.9",
            "OrcaSlicer": "BambuStudio-2.3.2-rc2",
            "AnycubicSlicerNext": "BambuStudio-1.3.9.4",
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
        if self.enable_base_layer_height_modifier:
            # Bambu/Orca layer_config_ranges keys are one-based model-object
            # indexes, not 3MF resource/build object ids. Lumina emits one
            # assembled model object here; puzzle exports strip this metadata.
            lcr_bytes = build_layer_config_ranges_xml(
                base_height_mm=self.base_height_mm,
                color_height_mm=self.color_height_mm,
                nozzle_mm=float(self.nozzle_size),
                face=self.face_orientation,
                object_id=1,
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
        if not self._is_anycubic_slicer():
            ET.SubElement(plate, "metadata", attrib={"key": "filament_map_mode", "value": "Auto For Flush"})
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

    def _build_project_settings_bytes(self) -> bytes:
        """Build project_settings.config JSON as bytes.
        构建 project_settings.config JSON（字节形式）。
        """
        material_palette, _ = self._build_material_palette()
        num_colors = len(material_palette)

        settings = self._get_base_config_template()
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
        settings.setdefault("enable_prime_tower", "1")

        applied_override_keys: list[str] = []
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
    base_height_mm: float = 0.0,
    color_height_mm: float = 0.0,
    face_orientation: str = "down",
    cover_source: "str | bytes | Image.Image | None" = None,
    device_profile_id: Optional[str] = None,
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
        base_height_mm (float): Backing/base thickness used for coarse layer-height override.
            （用于粗层高覆盖的底板厚度）
        color_height_mm (float): Colored-region thickness used to place the override range.
            （用于定位覆盖区间的彩色区域厚度）
        face_orientation (str): Base orientation selector passed to the writer.
            （透传给写入器的底板朝向）
        cover_source: Cover thumbnail image source. ``None`` uses silent
            placeholder (calibration / kit / recipe swatch / 既有调用方默认值);
            ``str`` is a filesystem path, ``bytes`` is encoded image bytes,
            ``PIL.Image.Image`` is a decoded image. Decode failures fall back
            to placeholder bytes plus one WARNING log per export.
            （封面缩略图图像源；``None`` 走静默占位，保持既有调用方零侵入）
        device_profile_id (Optional[str]): Slicer-scoped generated registry
            device profile ID used to select native machine metadata.
            （切片软件维度的注册表设备配置 ID，用于选择原生机型元数据）
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
        "preserve_template_filament_slots": preserve_template_filament_slots,
    }
    writer = BambuStudio3MFWriter(**writer_kwargs)
    writer.enable_base_layer_height_modifier = bool(enable_base_layer_height_modifier)
    writer.base_height_mm = float(base_height_mm)
    writer.color_height_mm = float(color_height_mm)
    normalized_face_orientation = str(face_orientation).strip().lower()
    if normalized_face_orientation not in _VALID_LAYER_CONFIG_FACES:
        normalized_face_orientation = "down"
    writer.face_orientation = normalized_face_orientation
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
