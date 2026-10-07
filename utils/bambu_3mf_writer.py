"""
Lumina Studio - BambuStudio 3MF Writer
Enhanced 3MF export with BambuStudio-compatible metadata and configurations.

Uses neroued-3mf (C++ streaming writer with Production Extension) for 3MF
packaging, and injects Bambu/Orca vendor metadata via CustomPart.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import io
import math
import os
import time
import uuid
import zipfile
import json
import copy
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Dict, Mapping, Optional
import numpy as np
from PIL import Image

if TYPE_CHECKING:
    import trimesh

from api.structured_logging import get_logger
from core.mesh_export_parts import (
    MeshExportPartRange,
    get_mesh_export_part_ranges,
    mesh_export_parts_are_conditional,
)
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
    CoverPngBundle,
    CoverThumbnailBuilder,
)
from utils.fatcat_metadata import (
    MetadataTarget,
    build_builtin_project_settings_request,
    build_model_metadata_request,
    compose_builtin_project_settings,
    compose_model_metadata,
    compose_project_settings,
    metadata_resource_specs,
    native_project_source_catalog,
    native_source_for_target,
    process_setting_aliases,
    resolve_template_build_plate,
    select_metadata_target,
    select_user_template_metadata_target,
    patch_wipe_tower,
    read_project_layout,
    read_placement_warnings,
    serialize_layer_config_ranges,
    template_import_parts,
    validate_template_hardware,
)


log = get_logger(__name__)

# Lazy import: avoid loading the native 3MF extension until export is requested.
_n3mf = None
_PREVIEW_PLACEHOLDER_PNG_BYTES: Optional[bytes] = None
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


def _get_n3mf():
    global _n3mf
    if _n3mf is None:
        import neroued_3mf as _n

        _n3mf = _n
    return _n3mf


def _apply_root_model_metadata(builder: Any, root_model: dict[str, Any]) -> None:
    """Forward Fat Cat root metadata through its lazy neroued adapter."""

    from fatcat_metadata_neroued import apply_root_model_metadata

    apply_root_model_metadata(builder, root_model)


def _apply_metadata_components(
    builder: Any,
    description: Mapping[str, Any],
    resource_bytes: Mapping[str, bytes],
) -> None:
    """Forward Fat Cat parts and relationships through its lazy adapter.

    将 Fat Cat 描述的部件与关系通用登记到 writer；切片器规则不留在此适配层。
    """

    from fatcat_metadata_neroued import apply_metadata_components

    apply_metadata_components(builder, description, resource_bytes)


_VALID_LAYER_CONFIG_FACES = frozenset({"up", "down", "double"})
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
        part_range: Optional lazy view into one independently closed mesh leaf.
            (可选的独立闭合网格叶子延迟切片范围)
        contact_repair_ranges: Canonical shell ranges used only for bounded
            writer-domain contact separation. (仅用于有界写出域接触分离的规范
            壳体范围)
    """

    mesh: object
    object_name: str
    material_name: str
    color_rgb: tuple[int, int, int]
    part_range: MeshExportPartRange | None = None
    contact_repair_ranges: tuple[MeshExportPartRange, ...] = ()


def _expand_mesh_export_entries(
    *,
    mesh: object,
    object_name: str,
    material_name: str,
    color_rgb: tuple[int, int, int],
) -> list[_MeshExportEntry]:
    """Expose independently closed leaves without copying parent vertices.

    将合并网格中的独立闭合分片展开为 3MF 叶子对象，同时复用父网格顶点。
    """

    part_ranges = get_mesh_export_part_ranges(mesh)
    if not part_ranges:
        return [
            _MeshExportEntry(
                mesh=mesh,
                object_name=object_name,
                material_name=material_name,
                color_rgb=color_rgb,
            )
        ]

    if mesh_export_parts_are_conditional(mesh):
        return [
            _MeshExportEntry(
                mesh=mesh,
                object_name=object_name,
                material_name=material_name,
                color_rgb=color_rgb,
                contact_repair_ranges=part_ranges,
            )
        ]

    source_faces = np.asarray(getattr(mesh, "faces", None))
    expanded: list[_MeshExportEntry] = []
    for index, part in enumerate(part_ranges, start=1):
        source_part_faces = source_faces[part.face_start : part.face_stop]
        if (
            np.any(source_part_faces < part.vertex_start)
            or np.any(source_part_faces >= part.vertex_stop)
        ):
            raise ValueError("3MF mesh part references vertices outside its range")
        leaf_name = (
            object_name
            if len(part_ranges) == 1
            else f"{object_name}__part_{index}"
        )
        expanded.append(
            _MeshExportEntry(
                mesh=mesh,
                object_name=leaf_name,
                material_name=material_name,
                color_rgb=color_rgb,
                part_range=part,
            )
        )
    return expanded


def _mesh_rows_are_finite(values: np.ndarray) -> bool:
    for start in range(0, len(values), 65_536):
        if not np.all(np.isfinite(values[start:start + 65_536])):
            return False
    return True


def _mesh_indices_are_within(values: np.ndarray, minimum: int, maximum: int) -> bool:
    for start in range(0, len(values), 65_536):
        chunk = values[start:start + 65_536]
        if np.any(chunk < minimum) or np.any(chunk >= maximum):
            return False
    return True


def _materialize_n3mf_mesh_view_arrays(
    mesh: object,
    *,
    part_range: MeshExportPartRange | None = None,
    contact_repair_ranges: tuple[MeshExportPartRange, ...] = (),
) -> tuple[np.ndarray, np.ndarray]:
    """Materialize and validate the exact arrays consumed by the 3MF writer.
    只生成一次并校验 3MF 写入器实际消费的数组。
    """

    from core.vector_mesh_spill import copy_mesh_array

    source_vertices = np.asarray(getattr(mesh, "vertices", None))
    source_faces = np.asarray(getattr(mesh, "faces", None))
    if (
        source_vertices.ndim != 2
        or source_vertices.shape[1:] != (3,)
        or len(source_vertices) == 0
        or source_faces.ndim != 2
        or source_faces.shape[1:] != (3,)
        or len(source_faces) == 0
    ):
        raise ValueError("3MF mesh arrays must be non-empty Nx3 arrays")
    if not _mesh_rows_are_finite(source_vertices):
        raise ValueError("3MF mesh vertices must be finite")
    if not _mesh_indices_are_within(source_faces, 0, len(source_vertices)):
        raise ValueError("3MF mesh face index is out of range")
    if len(source_vertices) > np.iinfo(np.uint32).max:
        raise ValueError("3MF mesh exceeds uint32 vertex indices")

    export_vertices = source_vertices
    export_faces = source_faces
    face_offset = 0
    if part_range is not None and contact_repair_ranges:
        raise ValueError("3MF mesh cannot combine part slicing and contact repair")
    if part_range is not None:
        if (
            part_range.vertex_start < 0
            or part_range.face_start < 0
            or part_range.vertex_stop > len(source_vertices)
            or part_range.face_stop > len(source_faces)
            or part_range.vertex_stop <= part_range.vertex_start
            or part_range.face_stop <= part_range.face_start
        ):
            raise ValueError("3MF mesh part range is out of bounds")
        export_vertices = source_vertices[
            part_range.vertex_start : part_range.vertex_stop
        ]
        source_part_faces = source_faces[
            part_range.face_start : part_range.face_stop
        ]
        if not _mesh_indices_are_within(
            source_part_faces, part_range.vertex_start, part_range.vertex_stop,
        ):
            raise ValueError("3MF mesh part references vertices outside its range")
        export_faces = source_part_faces
        face_offset = part_range.vertex_start
    elif contact_repair_ranges:
        from core.mesh_writer_domain import (
            prepare_indexed_shells_for_float32_export,
        )

        export_vertices, export_faces = prepare_indexed_shells_for_float32_export(
            mesh,
            contact_repair_ranges,
        )

    vertices = copy_mesh_array(export_vertices, np.dtype(np.float32))
    faces = copy_mesh_array(export_faces, np.dtype(np.uint32), offset=face_offset)
    if not _mesh_rows_are_finite(vertices):
        raise ValueError(
            "3MF mesh vertices must remain finite after float32 conversion"
        )
    vertices.setflags(write=False)
    faces.setflags(write=False)
    return vertices, faces


def _queue_n3mf_mesh_object(
    *,
    builder: object,
    entry: _MeshExportEntry,
    material_group_id: int,
    material_index: int,
    retained_views: list[tuple[np.ndarray, np.ndarray]],
) -> int:
    """Queue one mesh through zero-copy arrays when the binding supports it."""

    vertices, faces = _materialize_n3mf_mesh_view_arrays(
        entry.mesh,
        part_range=entry.part_range,
        contact_repair_ranges=entry.contact_repair_ranges,
    )
    add_zero_copy = getattr(builder, "add_mesh_object_zero_copy", None)
    if not callable(add_zero_copy):
        raise RuntimeError(
            "neroued-3mf must provide add_mesh_object_zero_copy"
        )
    object_id = add_zero_copy(
        entry.object_name,
        vertices,
        faces,
        material_group_id,
        material_index,
    )
    retained_views.append((vertices, faces))
    return int(object_id)


def _resolve_machine_registry_root() -> str:
    """Return the shared absolute machine-registry resource root.

    返回共享的机器注册表绝对资源根目录。
    """

    from core.machine_registry import resolve_machine_registry_root

    return str(resolve_machine_registry_root())


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


def build_layer_config_ranges_data(
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
) -> dict[str, Any] | None:
    """Calculate object-height process overrides without choosing XML fields.
    计算对象高度工艺区间，不在业务计算层决定 XML 字段格式。

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
        object_id (int): One-based model-object index used by the slicer.
            （切片器使用的模型对象序号，从 1 开始）
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
        dict[str, Any] | None: Model index and ordered height ranges, or
            ``None`` when the current geometry/settings require no overrides.
            （返回模型序号与有序层高区间；当前几何/设置无需覆盖时返回 ``None``。）

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

    overrides: list[tuple[float, float, dict[str, float | int | bool]]] = []
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
                            "use_default_extruder": True,
                            "layer_height_mm": coarse_lh,
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
                (min_z, max_z, {"infill_density_percent": 100})
            )

    segments = _split_layer_config_overrides(overrides)
    if not segments:
        return None

    return {
        "model_index": int(object_id),
        "ranges": [
            {
                "min_z": min_z,
                "max_z": max_z,
                **business_fields,
            }
            for min_z, max_z, business_fields in segments
        ],
    }


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
    """Serialize shared layer-range geometry through Fat Cat.
    将共享业务计算得到的层高区间交给 Fat Cat 序列化。
    """

    data = build_layer_config_ranges_data(
        base_height_mm=base_height_mm,
        color_height_mm=color_height_mm,
        nozzle_mm=nozzle_mm,
        face=face,
        fine_layer_height_mm=fine_layer_height_mm,
        initial_layer_height_mm=initial_layer_height_mm,
        min_layer_height_mm=min_layer_height_mm,
        max_layer_height_mm=max_layer_height_mm,
        object_id=object_id,
        enable_base_layer_height_modifier=enable_base_layer_height_modifier,
        backing_infill_density_percent=backing_infill_density_percent,
        solid_depth_mm=solid_depth_mm,
    )
    if data is None:
        return None
    return serialize_layer_config_ranges(data, fine_layer_height_mm).encode("utf-8")


def _split_layer_config_overrides(
    overrides: list[tuple[float, float, dict[str, float | int | bool]]],
) -> list[tuple[float, float, dict[str, float | int | bool]]]:
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
    segments: list[tuple[float, float, dict[str, float | int | bool]]] = []
    for start, end in zip(boundaries, boundaries[1:]):
        if end <= start + 1e-9:
            continue
        active_options: dict[str, float | int | bool] = {}
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


def load_export_project_settings(
    printer_id: str,
    slicer: str = "BambuStudio",
    nozzle_size: Optional[str | float] = None,
    device_profile_id: Optional[str] = None,
    *,
    custom_3mf_template_id: Optional[str] = None,
) -> dict:
    """Resolve export settings from FatCat or a saved user project.

    从 Fat Cat 精确原生来源或用户保存的项目模板读取配置。

    Built-in targets use the installed Fat Cat source catalog; user templates
    keep their own project fields and are checked against native hardware facts.
    内置目标使用已安装 Fat Cat 来源目录；用户模板保留其项目字段，
    并按原生硬件事实校验。
    """

    from config import normalize_slicer_software_id
    from utils.fatcat_metadata import (
        build_builtin_project_settings_request,
        compose_builtin_project_settings,
        native_source_for_target,
    )

    selected_nozzle_size = nozzle_size
    if selected_nozzle_size is None and device_profile_id:
        from core.machine_registry import (
            load_machine_registry,
            resolve_machine_registry_root,
        )

        registry_path = resolve_machine_registry_root() / "registry.json"
        selected_nozzle_size = load_machine_registry(registry_path).get_device_profile(
            device_profile_id
        ).nozzle_size
    if selected_nozzle_size is None:
        selected_nozzle_size = "0.4"

    target = select_metadata_target(
        slicer=slicer,
        printer_id=printer_id,
        nozzle_size=selected_nozzle_size,
        device_profile_id=device_profile_id,
        build_plate_id=None,
    )
    source = native_source_for_target(target)
    if custom_3mf_template_id:
        from core.custom_3mf_templates import load_template

        template = load_template(custom_3mf_template_id)
        source_slicer = template.pop("_lumina_template_slicer")
        expected = dict(source.get("hardware_settings") or {})
        if target.slicer_id == "PrusaSlicer":
            # Native structured hardware is validated by FatCat against its
            # exact config, rather than a flattened nozzle/bed summary.
            native = compose_builtin_project_settings(
                build_builtin_project_settings_request({}, [{
                    "name": "PLA", "colour": "#808080", "material_type": "PLA",
                }], target=target)
            )
            expected = json.loads(native["project_settings_json"])
        if not expected:
            raise ValueError("Fat Cat source has no hardware facts for template validation")
        validate_template_hardware(
            template,
            expected,
            source_slicer,
            normalize_slicer_software_id(slicer),
        )
        return template

    request = build_builtin_project_settings_request(
        {}, [{"name": "PLA", "colour": "#808080", "material_type": "PLA"}],
        target=target,
    )
    composed = compose_builtin_project_settings(request)
    project_json = composed.get("project_settings_json")
    if not isinstance(project_json, str):
        raise RuntimeError("Fat Cat did not return built-in project settings JSON")
    try:
        return json.loads(project_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Fat Cat returned invalid built-in project settings JSON") from exc


def _resolve_export_device(
    *,
    printer_id: str,
    slicer: str,
    nozzle_size: object,
    device_profile_id: str | None,
    build_plate_id: str | None,
) -> tuple[str, Any, Any]:
    """Resolve nozzle formatting and validate explicit registry selections."""
    from config import (
        format_native_nozzle_size,
        get_printer_profile,
        normalize_nozzle_size,
    )

    legacy_nozzle_size = normalize_nozzle_size(nozzle_size) or "0.4"
    native_nozzle_size = format_native_nozzle_size(nozzle_size) or legacy_nozzle_size
    configured_nozzle_sizes = get_printer_profile(printer_id).supported_nozzle_sizes
    resolved_nozzle_size = (
        native_nozzle_size
        if device_profile_id or native_nozzle_size in configured_nozzle_sizes
        else legacy_nozzle_size
    )
    device_profile = (
        _load_registry_device_profile_if_available(
            device_profile_id=device_profile_id,
            printer_id=printer_id,
            slicer=slicer,
            nozzle_size=resolved_nozzle_size,
        )
        if device_profile_id
        else None
    )
    build_plate = None
    if build_plate_id:
        if device_profile is None or not device_profile_id:
            raise ValueError("Build plate selection requires a machine registry device profile")
        from core.machine_registry import load_machine_registry

        registry_path = os.path.join(
            _resolve_machine_registry_root(),
            "registry.json",
        )
        try:
            build_plate = load_machine_registry(
                registry_path
            ).resolve_build_plate(device_profile_id, build_plate_id)
        except KeyError as exc:
            raise ValueError(str(exc).strip("'")) from exc
    return resolved_nozzle_size, device_profile, build_plate


def _build_wipe_tower_placement_request(
    layout: Mapping[str, Any],
    *,
    model_bounds: Rect,
    model_height: float,
    material_count: int,
    printer_id: str,
    slicer: str,
    nozzle_size: str,
    process_layout: Mapping[str, Any] | None = None,
) -> WipeTowerPlacementRequest | None:
    """Build a placement request from decoded layout and geometry facts."""

    process = layout if process_layout is None else process_layout
    printable_area = tuple(tuple(point) for point in layout["printable_area"])
    if len(printable_area) < 3:
        return None

    uses_creator_5_tower_interface = (
        slicer == "FlashStudio"
        and printer_id in _CREATOR_5_PRINTER_IDS
    )
    uses_anycubic_tower_interface = slicer == "AnycubicSlicerNext"
    uses_native_tower_envelope = (
        uses_creator_5_tower_interface or uses_anycubic_tower_interface
    )
    uses_rib_wall = layout["uses_rib_wall"]
    tower_brim = (
        min(8.0, max(0.0, model_height) / 100.0 * 8.0)
        if layout["tower_brim_auto"] else layout["tower_brim_width"]
    )
    return WipeTowerPlacementRequest(
        printable_area=printable_area,
        bed_exclusions=tuple(
            tuple(tuple(point) for point in polygon)
            for polygon in layout["bed_exclusions"]
        ),
        extruder_printable_areas=tuple(
            tuple(tuple(point) for point in polygon)
            for polygon in layout["extruder_printable_areas"]
        ),
        model_bounds=model_bounds,
        model_height=max(0.0, float(model_height)),
        model_brim=process["model_brim"],
        material_count=max(1, int(material_count)),
        layer_height=process["layer_height"],
        nozzle_diameter=max(0.1, float(nozzle_size)),
        purge_volume=layout["purge_volume"],
        tower_x=layout["tower_x"],
        tower_y=layout["tower_y"],
        tower_width=layout["tower_width"],
        tower_rotation=layout["tower_rotation"],
        tower_brim=0.0 if uses_native_tower_envelope else tower_brim,
        tower_infill_spacing_ratio=layout["tower_infill_spacing_ratio"],
        cyclic_toolchanges=bool(layout.get("tower_cyclic_toolchanges", False)),
        tower_rib_width=(
            layout["tower_rib_width"]
            if uses_rib_wall and not uses_native_tower_envelope else 0.0
        ),
        tower_extra_rib_length=layout["tower_extra_rib_length"],
        tower_square_rib_body=(
            uses_rib_wall and (
                layout.get("tower_square_rib_body")
                if layout.get("tower_square_rib_body") is not None
                else printer_id.startswith("bambu-")
                and slicer in {"BambuStudio", "OrcaSlicer"}
            )
        ),
        tower_preview_x_guard_enabled=bool(
            layout.get("tower_preview_x_guard_enabled", False)
        ),
        tower_preview_x_guard_margin=max(
            0.0, float(layout.get("tower_preview_x_guard_margin") or 0.0)
        ),
        extruder_count=layout["extruder_count"],
        filament_change_volume=layout["filament_change_volume"],
        model_tower_clearance=(
            _CREATOR_5_MODEL_TOWER_CLEARANCE_MM
            if uses_creator_5_tower_interface else 8.0
        ),
        edge_clearance=0.0 if uses_native_tower_envelope else 2.0,
        preferred_edge_clearance=4.0,
        preferred_top_edge_clearance=(
            _ELEGOO_CC2_PREFERRED_TOP_EDGE_CLEARANCE_MM
            if printer_id == "elegoo-cc2" else 0.0
        ),
        prefer_vertical_strip=printer_id == "bambu-a1-mini",
        minimum_tower_footprint_width=(
            _CREATOR_5_TOWER_MIN_FOOTPRINT_WIDTH_MM
            if uses_creator_5_tower_interface
            else _ANYCUBIC_TOWER_MIN_FOOTPRINT_WIDTH_MM
            if uses_anycubic_tower_interface else 0.0
        ),
        minimum_tower_depth=(
            _CREATOR_5_TOWER_MIN_DEPTH_MM
            if uses_creator_5_tower_interface
            else _ANYCUBIC_TOWER_MIN_DEPTH_MM
            if uses_anycubic_tower_interface else 0.0
        ),
    )


def _build_wipe_tower_placement_metadata_payload(
    placement: WipeTowerPlacementResult | None,
    *,
    enabled: bool,
    output_path: str,
    printer_id: str,
    slicer: str,
) -> dict[str, Any]:
    """Describe Lumina's computed placement for Fat Cat to serialize.

    返回 Lumina 已计算的摆放结果，由 Fat Cat 负责最终 JSON 部件序列化。
    """

    if not enabled:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "enabled": False,
            "available": False,
            "adapted": False,
            "requires_manual_adjustment": False,
            "warning_code": None,
            "reason": "disabled_by_user",
        }
    elif placement is None:
        log.warning(
            "Printable area unavailable for wipe-tower validation",
            extra={
                "event": "wipe_tower_manual_adjustment_required",
                "error_type": "PrintableAreaUnavailable",
                "error_message": (
                    "Generated without scaling the model or disabling the wipe tower; "
                    "manual slicer validation is required."
                ),
                "path": output_path,
                "printer_id": printer_id,
                "slicer": slicer,
            },
        )
        payload = {
            "schema_version": 1,
            "enabled": True,
            "available": False,
            "adapted": False,
            "requires_manual_adjustment": True,
            "warning_code": WIPE_TOWER_MANUAL_WARNING_CODE,
            "reason": "printable_area_unavailable",
        }
    else:
        payload = {
            "schema_version": 1,
            "enabled": True,
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
    return payload


class BambuStudio3MFWriter:
    """Write geometry with FatCat's selected native slicer metadata.
    将几何与 FatCat 提供的目标切片软件原生元数据单次写包。

    The historical class name is retained for caller compatibility. FatCat
    selects native metadata and core/Production layout; Neroued writes the
    archive once. Lumina supplies meshes, materials and placement facts.
    保留历史类名以兼容调用方；FatCat 选择原生元数据及几何布局，
    Neroued 单次写包，Lumina 提供网格、材料选择和摆放事实。
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
        enable_wipe_tower_auto_placement: bool = True,
        enable_relief: bool = False,
        base_height_mm: float = 0.0,
        color_height_mm: float = 0.0,
        face_orientation: str = "down",
        backing_infill_density_percent: int = 100,
        cover_source: "str | bytes | Image.Image | None" = None,
        device_profile_id: Optional[str] = None,
        build_plate_id: Optional[str] = None,
        preserve_template_filament_slots: Optional[bool] = None,
        custom_3mf_template_id: Optional[str] = None,
        material_types: Mapping[str, str | None] | None = None,
    ):
        """Initialize a writer for an exact native target or saved user project.
        初始化使用精确原生目标或已保存用户项目的 3MF 写入器。

        Args:
            output_path (str): Output .3mf file path. (输出 .3mf 文件路径)
            settings (Optional[Dict]): Custom print settings overrides. (自定义打印设置覆盖)
            color_mode (str): Color mode ('4-Color', '6-Color', '8-Color', 'BW'). (颜色模式)
            printer_id (str): Lumina printer identifier, default 'bambu-h2d'. (Lumina 打印机标识)
            slicer (str): Slicer software identifier, default 'BambuStudio'. (切片器标识)
            nozzle_size (Optional[str | float]): Exact selected nozzle identity.
                (所选喷嘴的精确身份)
            watermark (str): Watermark text embedded in the 3MF ZIP structure. (嵌入 3MF ZIP 结构的水印文本)
            enable_base_layer_height_modifier (bool): Whether to emit layer_config_ranges.xml.
                （是否输出 layer_config_ranges.xml）
            enable_wipe_tower_auto_placement (bool): Whether to adapt the model and
                wipe-tower layout to the selected build area.（是否按所选打印区域自动
                调整模型与擦料塔的摆放和擦料塔尺寸。）
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
            preserve_template_filament_slots (Optional[bool]): Compatibility
                option controlling whether native project arrays keep their source
                slot count. ``None`` keeps the existing automatic behavior;
                ``False`` trims arrays to the selected palette.（兼容参数，用于控制
                是否保留原生项目的来源槽数；``None`` 保持现有自动行为，``False`` 按
                已选调色板裁剪；声明固定物理槽数的目标始终保留原生容量。）
            custom_3mf_template_id: Successfully loaded user template selects
                preserved tuning instead of target-native material defaults.
                成功加载的用户模板使用保留调校模式，不套用原生耗材默认值。
            material_types: Source material choices keyed by project material
                name. None retains the existing choice for legacy inputs;
                explicit types take precedence over display names. User templates
                preserve their own settings.（按项目材料名提供来源类型；None
                沿用旧输入的既有选择，明确类型优先于显示名；用户模板保留调校。）
        """
        from config import normalize_slicer_software_id
        from core.machine_process_overlay import merge_lumina_process_settings

        self.output_path = output_path
        self.objects: list[_MeshExportEntry] = []
        self.color_mode = color_mode
        self.printer_id = printer_id
        self.slicer = normalize_slicer_software_id(slicer)
        defaults = dict(self.DEFAULT_SETTINGS)
        if self.slicer == "PrusaSlicer":
            defaults["brim_type"] = "outer_only"
        self.settings = merge_lumina_process_settings(
            defaults, settings, aliases=process_setting_aliases(self.slicer),
        )
        self._material_types = dict(material_types or {})
        self.device_profile_id = str(device_profile_id or "").strip() or None
        self.build_plate_id = str(build_plate_id or "").strip() or None
        (
            self.nozzle_size,
            self._registry_device_profile,
            self._registry_build_plate,
        ) = _resolve_export_device(
            printer_id=self.printer_id,
            slicer=self.slicer,
            nozzle_size=nozzle_size,
            device_profile_id=self.device_profile_id,
            build_plate_id=self.build_plate_id,
        )
        self.watermark = watermark
        self.enable_relief = bool(enable_relief)
        self.enable_base_layer_height_modifier = bool(
            enable_base_layer_height_modifier
        ) and not self.enable_relief
        self.enable_wipe_tower_auto_placement = bool(
            enable_wipe_tower_auto_placement
        )
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
        aliases = process_setting_aliases(self.slicer)
        # The dedicated backing-density parameter owns this geometry setting.
        self.settings = merge_lumina_process_settings(
            self.settings,
            {"sparse_infill_density": f"{self.effective_backing_infill_density_percent}%"},
            aliases=aliases,
        )
        if self.effective_backing_infill_density_percent < 100:
            # A zero-layer top shell leaves the non-viewing face as exposed
            # sparse infill even when the template carries a thickness value.
            # Keep the template thickness contract and require one top skin.
            top_field = aliases.get("top_shell_layers", "top_shell_layers")
            top_values = {
                str(value) for key, value in self.settings.items()
                if aliases.get(key, key) == top_field and value is not None
            }
            # Keep conflicting explicit aliases intact for SDK validation.
            if len(top_values) <= 1:
                top_layers = max(1, int(next(iter(top_values), "0")))
                self.settings = merge_lumina_process_settings(
                    self.settings, {"top_shell_layers": str(top_layers)}, aliases=aliases,
                )
        self._project_slot_names: list[str] = []
        self._project_preview_colors: dict | None = None
        self.cover_source: "str | bytes | Image.Image | None" = cover_source
        self.cover_bundle: Optional[CoverPngBundle] = None
        self.preserve_template_filament_slots = preserve_template_filament_slots
        self._custom_template = (
            load_export_project_settings(
                self.printer_id, self.slicer, self.nozzle_size, self.device_profile_id,
                custom_3mf_template_id=custom_3mf_template_id,
            ) if custom_3mf_template_id else None
        )
        self._template_build_plate: dict[str, str] | None = None
        self._resolve_custom_template_build_plate()
        self._wipe_tower_placement_cache: WipeTowerPlacementResult | None = None

    def _resolve_custom_template_build_plate(self) -> None:
        """Keep a native single-plate override unless the caller reselects it."""
        if (
            self._custom_template is None or self.build_plate_id is not None
        ):
            return
        target = self._select_metadata_target()
        self._template_build_plate = resolve_template_build_plate(
            slicer_id=target.slicer_id,
            default_build_plate_uid=target.build_plate_uid,
            model_plate_value=self._custom_template.get("_lumina_template_plate_value"),
            sidecar_bed_value=self._custom_template.get("_lumina_template_sidecar_bed"),
            project_bed_value=read_project_layout(
                self._custom_template, slicer_id=self.slicer,
            )["bed_type"],
        )

    def add_mesh(self, mesh: trimesh.Trimesh, name: str, color_rgb: tuple):
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
        self.objects.extend(
            _expand_mesh_export_entries(
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

    def _select_metadata_target(self) -> MetadataTarget:
        """Select the shared Fat Cat route once for this export.

        为本次导出统一选择 Fat Cat 元数据目标。
        """

        if self._custom_template is not None:
            target = select_user_template_metadata_target(
                slicer=self.slicer,
                build_plate_id=self.build_plate_id,
            )
        else:
            target = select_metadata_target(
                slicer=self.slicer,
                printer_id=self.printer_id,
                nozzle_size=self.nozzle_size,
                device_profile_id=self.device_profile_id,
                build_plate_id=self.build_plate_id,
            )
        if self._template_build_plate is not None:
            return replace(target, build_plate_uid=self._template_build_plate["build_plate_uid"])
        return target

    def _build_fatcat_project_request(
        self,
        material_palette: list[tuple[str, tuple[int, int, int]]],
        target: MetadataTarget,
    ) -> dict[str, Any]:
        """Pass the selected source facts to Fat Cat's project policy.

        向 Fat Cat 传递已选来源事实，由 C++ 选择硬件、材料和槽位策略。
        """
        source_slot_colours = {
            str(index): "#{:02X}{:02X}{:02X}".format(*colour)
            for index, (_name, colour) in enumerate(material_palette)
        }
        slot_mode = (
            "auto" if self.preserve_template_filament_slots is None
            else "preserve" if self.preserve_template_filament_slots else "compact"
        )
        slot_policy = native_project_source_catalog(target.slicer_id).get(
            "filament_slot_policy"
        )
        if slot_policy == "preserve_native_capacity":
            slot_mode = "preserve"
        if self._custom_template is not None:
            aliases = process_setting_aliases(self.slicer)
            geometry_fields = {
                aliases.get(key, key) for key in (
                    "layer_height", "initial_layer_print_height", "initial_layer_height",
                    "line_width", "initial_layer_line_width", "wall_loops",
                    "top_shell_layers", "bottom_shell_layers", "sparse_infill_density",
                )
            }
            process = {
                key: value for key, value in self.settings.items()
                if aliases.get(key, key) in geometry_fields
            }
            profile = self._registry_device_profile
            request = {
                "hardware_mode": "auto",
                "slicer_id": target.slicer_id,
                "application_version": target.application_version,
                "material_mode": "preserve_template",
                "source_materials": [
                    {
                        "name": name,
                        "colour": f"#{red:02X}{green:02X}{blue:02X}",
                        "material_type": self._material_types.get(name),
                    }
                    for name, (red, green, blue) in material_palette
                ],
                "source_slot_colours": source_slot_colours,
                "process_settings": process,
                "preserve_source_material_settings": True,
                "filament_slot_mode": slot_mode,
                "source_profile": {
                    "registry": profile is not None,
                    "brand": getattr(profile, "brand", ""),
                    "display_name": getattr(profile, "display_name", ""),
                    "slicer_id": self.slicer,
                },
            }
            if self.build_plate_id is not None or self._template_build_plate is not None:
                request["build_plate_uid"] = target.build_plate_uid
            return request

        from core.machine_process_overlay import build_lumina_process_settings

        materials = [
            {
                "name": name,
                "colour": f"#{red:02X}{green:02X}{blue:02X}",
                "material_type": self._material_types.get(name),
            }
            for name, (red, green, blue) in material_palette
        ]
        request = build_builtin_project_settings_request(
            build_lumina_process_settings(
                self.settings, nozzle_size=self.nozzle_size, slicer_id=self.slicer,
                aliases=process_setting_aliases(self.slicer),
            ),
            materials,
            target=target,
            filament_slot_mode=slot_mode,
            source_slot_colours=source_slot_colours,
        )
        if self.build_plate_id is not None:
            request["build_plate_uid"] = target.build_plate_uid
        return request

    def export(self) -> str:
        """Export all meshes as the selected slicer's native 3MF project.
        将所有网格导出为所选切片软件的原生 3MF 工程。

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
        material_palette, material_indices = self._build_material_palette()
        metadata_target = self._select_metadata_target()
        project_request = self._build_fatcat_project_request(
            material_palette, metadata_target,
        )
        if self._custom_template is not None:
            base_project = {
                key: value for key, value in self._get_base_config_template().items()
                if not key.startswith("_lumina_template_")
            }
        else:
            base_project = None

        builder = n3mf.DocumentBuilder()
        builder.set_unit(n3mf.Unit.Millimeter)
        builder.set_language("en-US")

        required_production_methods = (
            "add_custom_relationship",
            "enable_production",
            "plan_production_layout",
            "set_production_build_uuid",
            "set_production_assembly_uuid",
            "set_object_uuid",
            "set_component_uuid",
            "set_component_transform",
        )
        missing_production_methods = [
            name
            for name in required_production_methods
            if not hasattr(builder, name)
        ]
        if missing_production_methods:
            raise RuntimeError(
                "Fat Cat requires patched neroued-3mf production UUID APIs: "
                + ", ".join(missing_production_methods)
            )

        materials = [
            n3mf.BaseMaterial(name, n3mf.Color(rgb[0], rgb[1], rgb[2]))
            for name, rgb in material_palette
        ]
        mat_group_id = builder.add_base_material_group(materials)

        object_ids: list[int] = []
        material_index_by_object: list[int] = []
        retained_mesh_views: list[tuple[np.ndarray, np.ndarray]] = []
        for entry in self.objects:
            material_index = material_indices[entry.material_name]
            obj_id = _queue_n3mf_mesh_object(
                builder=builder,
                entry=entry,
                material_group_id=mat_group_id,
                material_index=material_index,
                retained_views=retained_mesh_views,
            )
            object_ids.append(obj_id)
            material_index_by_object.append(material_index)

        composed_project = (
            compose_project_settings(base_project, project_request)
            if base_project is not None
            else compose_builtin_project_settings(project_request)
        )
        project_json = composed_project.get("project_settings_json")
        if not isinstance(project_json, str):
            raise RuntimeError(
                "Fat Cat C++ project composer returned no project settings JSON"
            )
        try:
            final_project = json.loads(project_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Fat Cat C++ project composer returned invalid project JSON"
            ) from exc

        # Layout consumes the exact project produced by the one C++ compose
        # call.  The placement result is then patched through Fat Cat's
        # existing explicit tower-field API instead of composing the whole
        # project a second time.
        project_layout = read_project_layout(final_project, slicer_id=self.slicer)
        effective_settings = composed_project["effective_settings"]
        placement = self._get_wipe_tower_placement(
            effective_settings=effective_settings,
            project_layout=project_layout,
        )
        # Patching tower fields preserves the bed and layer facts reused below.
        if placement is not None:
            final_project = patch_wipe_tower(
                final_project,
                {
                    "enabled": True,
                    "width_mm": placement.tower_width,
                    "rotation_deg": placement.tower_rotation,
                    "positions": [
                        {
                            "plate_index": 0,
                            "x_mm": placement.tower_x,
                            "y_mm": placement.tower_y,
                        }
                    ],
                },
                composed_project["wipe_tower_dialect"],
            )
        build_item_properties = composed_project.get("build_item_properties")
        if not isinstance(build_item_properties, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in build_item_properties.items()
        ):
            raise RuntimeError(
                "Fat Cat C++ project composer returned invalid build-item properties"
            )
        build_translation = self._get_build_item_translation(
            effective_settings=effective_settings,
            precomputed_placement=placement,
            placement_was_computed=True,
            project_layout=project_layout,
        )
        metadata_defaults = composed_project["metadata_defaults"]
        if metadata_defaults.get("geometry_layout") == "core":
            assembly_id = builder.add_component_object(
                Path(self.output_path).stem,
                [n3mf.Component(object_id, n3mf.Transform.identity()) for object_id in object_ids],
            )
            builder.add_build_item(
                assembly_id, n3mf.Transform.translation(*build_translation),
                **build_item_properties,
            )
        else:
            for obj_id in object_ids:
                builder.set_object_uuid(obj_id, str(uuid.uuid4()))
                builder.set_component_uuid(obj_id, str(uuid.uuid4()))
                builder.set_component_transform(obj_id, n3mf.Transform.identity())
            builder.enable_production(n3mf.Transform.translation(*build_translation))
            builder.set_production_merge_objects(True)
            builder.set_production_build_uuid(str(uuid.uuid4()))
            builder.set_production_assembly_uuid(str(uuid.uuid4()))
            for index, object_id in enumerate(object_ids):
                builder.add_build_item(
                    object_id, uuid=str(uuid.uuid4()) if index == 0 else "",
                    **build_item_properties,
                )
            plan = builder.plan_production_layout()
            planned_object_ids = tuple(
                int(item.object_id) for item in plan.external_objects
            )
            if planned_object_ids != tuple(object_ids):
                raise RuntimeError("Fat Cat writer layout plan does not match queued object IDs")
            assembly_id = int(plan.assembly_id)
        model_request = build_model_metadata_request(
            target=metadata_target,
            assembly_id=assembly_id,
            object_ids=object_ids,
            entries=self.objects,
            material_index_by_object=material_index_by_object,
            output_path=self.output_path,
            bed_type=metadata_defaults["plate_value"],
        )
        model_request["active_material_count"] = len(material_palette)
        model_request["identify_id"] = metadata_defaults["identify_id"]
        uuid_seed_prefix = metadata_defaults.get("slice_uuid_seed_prefix")
        if uuid_seed_prefix:
            uuid_seed = ":".join(
                [uuid_seed_prefix, self.printer_id, self.nozzle_size,
                 *(entry.object_name for entry in self.objects)]
            )
            model_request["slice_uuid"] = uuid.uuid5(uuid.NAMESPACE_URL, uuid_seed).hex
        component_inputs: dict[str, Any] = {
            "wipe_tower_placement": (
                _build_wipe_tower_placement_metadata_payload(
                    placement,
                    enabled=self.enable_wipe_tower_auto_placement,
                    output_path=self.output_path,
                    printer_id=self.printer_id,
                    slicer=self.slicer,
                )
            ),
        }
        if metadata_defaults["plate_summary"]:
            component_inputs["plate_summary"] = self._build_plate_summary_input(
                material_palette, build_translation,
                sidecar_bed_type=metadata_defaults["sidecar_bed_value"],
            )
        if (
            not self.enable_relief
            and (
                self.enable_base_layer_height_modifier
                or self.effective_backing_infill_density_percent < 100
            )
        ):
            limits = (
                project_layout["min_layer_height"],
                project_layout["max_layer_height"],
            )
            fine_layer_height = project_layout["layer_height"]
            initial_layer_height = project_layout["initial_layer_height"]
            layer_ranges = build_layer_config_ranges_data(
                base_height_mm=self.base_height_mm,
                color_height_mm=self.color_height_mm,
                nozzle_mm=float(self.nozzle_size),
                face=self.face_orientation,
                fine_layer_height_mm=fine_layer_height,
                initial_layer_height_mm=initial_layer_height,
                min_layer_height_mm=limits[0],
                max_layer_height_mm=limits[1],
                object_id=1,
                enable_base_layer_height_modifier=(
                    self.enable_base_layer_height_modifier
                ),
                backing_infill_density_percent=(
                    self.effective_backing_infill_density_percent
                ),
            )
            if layer_ranges is not None:
                component_inputs["layer_config_ranges"] = layer_ranges
        model_request["component_inputs"] = component_inputs
        self._ensure_cover_bundle()
        cover_bundle = self.cover_bundle
        if cover_bundle is None:
            raise RuntimeError("Lumina did not produce a cover resource bundle")
        placeholder_preview = self._build_preview_placeholder_png_bytes()
        fatcat_resource_bytes = {
            "plate_main": cover_bundle.plate_main,
            "plate_no_light": cover_bundle.plate_no_light,
            "top_preview": placeholder_preview,
            "pick_preview": placeholder_preview,
            "thumbnail_package": cover_bundle.thumbnail_3mf,
            "thumbnail_middle": cover_bundle.thumbnail_middle,
            "thumbnail_small": cover_bundle.thumbnail_small,
        }
        if "plate_small" in metadata_resource_specs(self.slicer):
            fatcat_resource_bytes["plate_small"] = (
                self._build_plate_small_bytes(cover_bundle.plate_main)
            )
        model_request["resource_roles"] = list(fatcat_resource_bytes)
        model_metadata = compose_model_metadata(final_project, model_request)
        root_model = model_metadata.get("root_model")
        if not isinstance(root_model, dict):
            raise RuntimeError(
                "Fat Cat C++ model composer returned no root model metadata"
            )
        _apply_root_model_metadata(builder, root_model)
        _apply_metadata_components(builder, model_metadata, fatcat_resource_bytes)

        doc = builder.build()

        opts = n3mf.WriteOptions()
        # ``neroued_3mf`` interprets this as significant-digit precision. At
        # bed-scale X/Y coordinates, six digits round independent vertices to
        # the same XML coordinate after the float32 storage boundary. Nine
        # significant digits are sufficient to round-trip every IEEE-754
        # float32 value while avoiding the file-size cost of an arbitrary
        # higher precision.
        # ``neroued_3mf`` 将此值按有效数字而非固定小数位处理。在打印床尺度的
        # X/Y 坐标下，六位会把 float32 边界之后本应独立的顶点写成同一 XML
        # 坐标。九位有效数字足以无歧义地往返任意 IEEE-754 float32，同时避免
        # 任意提高精度带来的文件体积成本。
        opts.vertex_precision = 9
        opts.compact_xml = True
        # Removing an individual face from an otherwise closed indexed shell
        # creates an open mesh. Vector geometry handles exact float32 collapse
        # locally, so the writer must preserve the final topology verbatim.
        opts.triangle_write_mode = n3mf.TriangleWriteMode.Keep
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

        n3mf.write_to_file(self.output_path, doc, opts)

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

    def _get_wipe_tower_placement(
        self,
        *,
        effective_settings: Mapping[str, Any] | None = None,
        project_layout: Mapping[str, Any] | None = None,
    ) -> WipeTowerPlacementResult | None:
        """Resolve and cache the joint model/tower placement.

        联合求解并缓存模型与擦料塔摆放结果；开启时始终按当前模型重新规划，
        无解时仅标记需要人工调整，绝不缩放模型或关闭擦料塔。
        """

        if not self.enable_wipe_tower_auto_placement:
            return None
        if self._wipe_tower_placement_cache is not None:
            return self._wipe_tower_placement_cache
        if not self.objects:
            return None

        template = (
            effective_settings
            if effective_settings is not None
            else self._get_base_config_template()
        )
        layout = (
            project_layout if project_layout is not None
            else read_project_layout(template, slicer_id=self.slicer)
        )
        process_layout = (
            layout if effective_settings is not None
            else read_project_layout({**template, **self.settings}, slicer_id=self.slicer)
        )
        bounds_min, bounds_max = self._get_mesh_bounds()
        request = _build_wipe_tower_placement_request(
            layout,
            model_bounds=Rect(
                float(bounds_min[0]),
                float(bounds_min[1]),
                float(bounds_max[0]),
                float(bounds_max[1]),
            ),
            model_height=float(bounds_max[2] - bounds_min[2]),
            material_count=len(self._build_material_palette()[0]),
            printer_id=self.printer_id,
            slicer=self.slicer,
            nozzle_size=self.nozzle_size,
            process_layout=process_layout,
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

    def _get_build_item_translation(
        self,
        effective_settings: Mapping[str, Any] | None = None,
        *,
        precomputed_placement: WipeTowerPlacementResult | None = None,
        placement_was_computed: bool = False,
        project_layout: Mapping[str, Any] | None = None,
    ) -> tuple[float, float, float]:
        bounds_min, bounds_max = self._get_mesh_bounds()
        placement = (
            precomputed_placement
            if placement_was_computed
            else self._get_wipe_tower_placement(
                effective_settings=effective_settings,
                project_layout=project_layout,
            )
        )
        if placement is not None:
            translate_x, translate_y = placement.model_translation
        else:
            model_center = (bounds_min + bounds_max) / 2.0
            if project_layout is None:
                settings = (
                    effective_settings if effective_settings is not None
                    else self._get_base_config_template()
                )
                project_layout = read_project_layout(settings, slicer_id=self.slicer)
            points = project_layout["printable_area"]
            if len(points) < 2:
                translate_x = 0.0
                translate_y = 0.0
            else:
                xs = [point[0] for point in points]
                ys = [point[1] for point in points]
                translate_x = float((min(xs) + max(xs)) / 2.0 - model_center[0])
                translate_y = float((min(ys) + max(ys)) / 2.0 - model_center[1])
        translate_z = float(-bounds_min[2])
        return translate_x, translate_y, translate_z

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
    def _build_plate_small_bytes(plate_main: bytes) -> bytes:
        """Build the native 128x128 plate preview.

        构建原生的 128x128 ``plate_1_small.png``。
        """

        with Image.open(io.BytesIO(plate_main)) as image:
            resized = image.convert("RGBA").resize(
                (128, 128),
                Image.Resampling.LANCZOS,
            )
            buffer = io.BytesIO()
            resized.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()

    def _build_plate_summary_input(
        self,
        material_palette: list[tuple[str, tuple[int, int, int]]],
        build_translation: tuple[float, float, float],
        *,
        sidecar_bed_type: str,
    ) -> dict[str, Any]:
        """Provide final geometry and palette values for the native plate part.

        向 Fat Cat 提供最终几何边界与调色板，由 Fat Cat 生成盘面部件。
        """

        translate_x, translate_y, _ = build_translation
        bounds = [np.asarray(entry.mesh.bounds, dtype=np.float64) for entry in self.objects]
        bbox_all = [
            float(min(box[0, 0] + translate_x for box in bounds)),
            float(min(box[0, 1] + translate_y for box in bounds)),
            float(max(box[1, 0] + translate_x for box in bounds)),
            float(max(box[1, 1] + translate_y for box in bounds)),
        ]
        return {
            "bbox_all": bbox_all,
            "filament_colors": [
                f"#{red:02X}{green:02X}{blue:02X}"
                for _, (red, green, blue) in material_palette
            ],
            "layer_height": float(self.settings.get("layer_height", "0.08")),
            "name": os.path.splitext(os.path.basename(self.output_path))[0],
            "nozzle_diameter": float(self.nozzle_size),
            "bed_type": sidecar_bed_type,
        }

    # ------------------------------------------------------------------
    # User project settings and filament arrays.
    # ------------------------------------------------------------------

    def _get_base_config_template(self) -> dict:
        """Return the current user project or a Fat Cat composed native project.

        返回当前用户项目，或由 Fat Cat 合成的原生项目配置。
        """
        if self._custom_template is not None:
            return {
                key: copy.deepcopy(value) for key, value in self._custom_template.items()
                if not key.startswith("_lumina_template_")
            }
        if not self.objects:
            raise ValueError("A built-in project needs at least one selected material")
        target = self._select_metadata_target()
        request = self._build_fatcat_project_request(
            self._build_material_palette()[0], target,
        )
        composed = compose_builtin_project_settings(request)
        project_json = composed.get("project_settings_json")
        if not isinstance(project_json, str):
            raise RuntimeError("Fat Cat did not return built-in project settings JSON")
        try:
            return json.loads(project_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Fat Cat returned invalid built-in project settings JSON") from exc


# ======================================================================
# Scene export entry and generated placement warnings.
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

    metadata_path = template_import_parts("BambuStudio")["wipe_tower_placement"]
    try:
        with zipfile.ZipFile(os.fspath(threemf_path), "r") as package:
            if metadata_path not in package.namelist():
                return []
            payload = package.read(metadata_path).decode("utf-8")
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError):
        return []
    return read_placement_warnings(payload)


def export_scene_with_bambu_metadata(
    scene: trimesh.Scene,
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
    enable_wipe_tower_auto_placement: bool = True,
    enable_relief: bool = False,
    base_height_mm: float = 0.0,
    color_height_mm: float = 0.0,
    face_orientation: str = "down",
    backing_infill_density_percent: int = 100,
    cover_source: "str | bytes | Image.Image | None" = None,
    device_profile_id: Optional[str] = None,
    build_plate_id: Optional[str] = None,
    preserve_template_filament_slots: Optional[bool] = None,
    custom_3mf_template_id: Optional[str] = None,
    material_types: Mapping[str, str | None] | None = None,
):
    """Export a Trimesh scene to BambuStudio/OrcaSlicer-compatible 3MF with metadata.
    将 Trimesh 场景导出为 BambuStudio/OrcaSlicer 兼容的 3MF 文件（含元数据）。

    Args:
        scene (trimesh.Scene): Trimesh Scene containing all meshes. (包含所有网格的场景)
        output_path (str): Output .3mf file path. (输出 .3mf 文件路径)
        slot_names (List[str]): Actually used material names. (实际使用的材料名称列表)
        preview_colors (Dict): Material ID to RGBA color mapping. (材料 ID 到 RGBA 颜色映射)
        settings (Optional[Dict]): Custom print settings. (自定义打印设置)
        color_mode (str): Color mode ('4-Color', '6-Color', '8-Color', 'BW'). (颜色模式)
        printer_id (str): Lumina printer identifier, default 'bambu-h2d'. (Lumina 打印机标识)
        slicer (str): Slicer software identifier, default 'BambuStudio'. (切片器标识)
        nozzle_size (Optional[str | float]): Exact selected nozzle identity.
            (所选喷嘴的精确身份)
        watermark (str): Watermark text embedded in the 3MF ZIP structure. (嵌入 3MF ZIP 结构的水印文本)
        project_slot_names (Optional[List[str]]): Full selected source palette/material names to preserve
            in exported project metadata when available. (可选，导出项目元数据时应保留的完整来源调色板/材料名称)
        enable_base_layer_height_modifier (bool): Whether to emit layer_config_ranges.xml.
            （是否输出 layer_config_ranges.xml）
        enable_wipe_tower_auto_placement (bool): Whether to adapt the model and
            wipe-tower layout to the selected build area.（是否按所选打印区域自动
            调整模型与擦料塔的摆放和擦料塔尺寸。）
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
        preserve_template_filament_slots (Optional[bool]): Compatibility option
            controlling whether native project arrays keep their source slot
            count. ``False`` trims arrays to the selected palette.（兼容参数，用于
            控制是否保留原生项目的来源槽数；``False`` 会按已选调色板裁剪。）
        custom_3mf_template_id: Stored user template to load without native
            material replacement.（加载已保存的用户模板并保留耗材调校。）
        material_types: Explicit source material choices keyed by project slot
            name, independent of display colours. None retains the legacy
            material choice; explicit values override display-name inference.
            （按项目槽名提供明确材料选择，与显示颜色分离；None 沿用旧输入的
            既有材料选择，明确值优先于显示名称推断。）

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
        "custom_3mf_template_id": custom_3mf_template_id,
        "material_types": material_types,
        "enable_relief": bool(enable_relief),
        "enable_base_layer_height_modifier": bool(
            enable_base_layer_height_modifier
        ),
        "enable_wipe_tower_auto_placement": bool(
            enable_wipe_tower_auto_placement
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
