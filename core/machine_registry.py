from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


@dataclass(frozen=True)
class BuildPlateProfile:
    """One slicer-native build plate definition.

    单个切片软件原生打印板定义。项目、盘面和厂商 sidecar 可能使用不同值，
    因此三者保持为显式字段，禁止在写出阶段猜测。
    """

    id: str
    display_name: str
    display_name_zh: str
    project_value: str
    plate_value: str
    sidecar_value: str
    image: str
    source_path: str
    source_version: str
    revision: str


@dataclass(frozen=True)
class DeviceProfile:
    """Resolved Lumina device profile at slicer + machine + nozzle grain."""

    device_profile_id: str
    machine_profile_id: str
    slicer_id: str
    slicer_display_name: str
    source_version: str
    application_metadata: str
    client_version: str
    sidecar_policy: str
    display_name: str
    brand: str
    vendor_key: str
    bed_width: int
    bed_depth: int
    bed_height: int
    thumbnail: str
    nozzle_size: str
    source_profile_name: str
    template: str
    revision: str
    supported: bool
    build_plates: tuple[BuildPlateProfile, ...]
    default_build_plate_id: str


@dataclass(frozen=True)
class MachineRegistry:
    """In-memory index for generated Lumina machine registry data."""

    schema_version: int
    generated_at: str
    devices_by_id: dict[str, DeviceProfile]
    build_plates_by_device_id: dict[str, dict[str, BuildPlateProfile]]

    def get_device_profile(self, device_profile_id: str) -> DeviceProfile:
        return self.devices_by_id[device_profile_id]

    def resolve_build_plate(
        self,
        device_profile_id: str,
        build_plate_id: str | None = None,
    ) -> BuildPlateProfile:
        """Resolve and validate a build plate for one device profile.

        解析并校验设备配置对应的打印板。未传 ID 时使用机器的上游默认值。
        """

        device = self.get_device_profile(device_profile_id)
        selected_id = str(build_plate_id or device.default_build_plate_id).strip()
        if not selected_id:
            raise KeyError(f"Device profile has no build plate default: {device_profile_id}")
        try:
            return self.build_plates_by_device_id[device_profile_id][selected_id]
        except KeyError as exc:
            raise KeyError(
                f"Unsupported build plate {selected_id!r} for {device_profile_id}"
            ) from exc


class MachineRegistrySelectionError(ValueError):
    """Raised when an export device selection conflicts with the registry.

    导出设备选择与机器注册表冲突时抛出。
    """


def resolve_machine_registry_root() -> Path:
    """Resolve the single runtime machine-registry resource root.

    解析唯一的运行时机器注册表资源根目录。显式环境变量优先；冻结应用
    使用 PyInstaller 的 ``_MEIPASS``；源码运行使用仓库内置目录。
    """

    configured_root = os.environ.get("LUMINA_MACHINE_REGISTRY_DIR", "").strip()
    if configured_root:
        return Path(configured_root).expanduser().resolve()
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return (Path(sys._MEIPASS) / "machine_registry").resolve()
    return (Path(__file__).resolve().parents[1] / "machine_registry").resolve()


def _registry_printer_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def validate_device_profile_selection(
    registry: MachineRegistry,
    *,
    device_profile_id: str,
    printer_id: str,
    slicer: str,
    nozzle_size: str,
    build_plate_id: str | None = None,
) -> tuple[DeviceProfile, BuildPlateProfile | None]:
    """Validate one export device and optional build plate selection.

    校验一次导出的设备配置及可选打印板组合。

    Args:
        registry: Loaded machine registry. 已加载的机器注册表。
        device_profile_id: Stable device profile ID. 稳定设备配置 ID。
        printer_id: Requested Lumina printer ID. 请求的 Lumina 打印机 ID。
        slicer: Requested slicer ID. 请求的切片软件 ID。
        nozzle_size: Requested native nozzle size. 请求的原生喷嘴尺寸。
        build_plate_id: Optional slicer-native plate ID. 可选原生打印板 ID。

    Returns:
        The validated device profile and optional build plate.
        已校验的设备配置及可选打印板。

    Raises:
        MachineRegistrySelectionError: If any selection component conflicts.
            任一选择与注册表能力冲突时抛出。
    """
    from config import (
        PRINTER_PROFILES,
        format_native_nozzle_size,
        normalize_printer_profile_id,
        normalize_slicer_software_id,
    )

    try:
        profile = registry.get_device_profile(device_profile_id)
    except KeyError as exc:
        raise MachineRegistrySelectionError(
            f"Unknown machine registry device profile: {device_profile_id}"
        ) from exc

    if not profile.supported:
        raise MachineRegistrySelectionError(
            f"Machine registry device profile is not supported: {device_profile_id}"
        )

    normalized_slicer = normalize_slicer_software_id(str(slicer or ""))
    normalized_nozzle = format_native_nozzle_size(nozzle_size) or str(
        nozzle_size or ""
    ).strip()
    if (
        profile.slicer_id != normalized_slicer
        or profile.nozzle_size != normalized_nozzle
    ):
        raise MachineRegistrySelectionError(
            "Machine registry device profile does not match requested slicer/nozzle: "
            f"{device_profile_id} != {normalized_slicer}/{normalized_nozzle}"
        )

    normalized_printer_id = normalize_printer_profile_id(str(printer_id or ""))
    requested_printer = PRINTER_PROFILES.get(normalized_printer_id)
    if requested_printer is not None:
        printer_matches = (
            profile.display_name.casefold()
            == requested_printer.display_name.casefold()
            and profile.brand.casefold() == requested_printer.brand.casefold()
        )
    else:
        registry_printer_ids = {
            _registry_printer_slug(profile.display_name),
            _registry_printer_slug(f"{profile.brand}-{profile.display_name}"),
            profile.machine_profile_id.casefold(),
        }
        printer_matches = normalized_printer_id in registry_printer_ids
    if not printer_matches:
        raise MachineRegistrySelectionError(
            "Machine registry device profile does not match requested printer: "
            f"{device_profile_id} != {printer_id}"
        )

    plate = None
    selected_plate_id = str(build_plate_id or "").strip()
    if selected_plate_id:
        try:
            plate = registry.resolve_build_plate(device_profile_id, selected_plate_id)
        except KeyError as exc:
            raise MachineRegistrySelectionError(str(exc).strip("'")) from exc
    return profile, plate


def _require_mapping(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Machine registry {label} must be an object")
    return value


def load_machine_registry(path: str | Path) -> MachineRegistry:
    """Load a generated Lumina machine registry JSON file.

    Args:
        path: Path to ``machine_registry/registry.json``.

    Returns:
        MachineRegistry: Indexed registry keyed by ``device_profile_id``.
    """
    registry_path = Path(path)
    data = _require_mapping(json.loads(registry_path.read_text(encoding="utf-8")), label="root")
    devices: dict[str, DeviceProfile] = {}
    build_plates_by_device_id: dict[str, dict[str, BuildPlateProfile]] = {}

    for slicer_index, slicer_value in enumerate(data.get("slicers", [])):
        slicer = _require_mapping(slicer_value, label=f"slicers[{slicer_index}]")
        slicer_id = str(slicer["slicer_id"])
        slicer_build_plates: dict[str, BuildPlateProfile] = {}
        for plate_index, plate_value in enumerate(slicer.get("build_plates", [])):
            plate = _require_mapping(
                plate_value,
                label=f"slicers[{slicer_index}].build_plates[{plate_index}]",
            )
            build_plate = BuildPlateProfile(
                id=str(plate["id"]),
                display_name=str(plate["display_name"]),
                display_name_zh=str(
                    plate.get("display_name_zh") or plate["display_name"]
                ),
                project_value=str(plate["project_value"]),
                plate_value=str(plate["plate_value"]),
                sidecar_value=str(plate.get("sidecar_value") or ""),
                image=str(plate["image"]),
                source_path=str(plate["source_path"]),
                source_version=str(plate["source_version"]),
                revision=str(plate["revision"]),
            )
            if build_plate.id in slicer_build_plates:
                raise ValueError(
                    "Duplicate machine registry build plate: "
                    f"{slicer_id}:{build_plate.id}"
                )
            slicer_build_plates[build_plate.id] = build_plate
        for machine_index, machine_value in enumerate(slicer.get("machines", [])):
            machine = _require_mapping(machine_value, label=f"machines[{machine_index}]")
            supported_plate_ids = tuple(
                str(value) for value in machine.get("supported_build_plate_ids", [])
            )
            for build_plate_id in supported_plate_ids:
                if build_plate_id not in slicer_build_plates:
                    raise ValueError(
                        "Unknown machine registry build plate: "
                        f"{slicer_id}:{build_plate_id}"
                    )
            default_build_plate_id = str(
                machine.get("default_build_plate_id") or ""
            )
            if (
                default_build_plate_id
                and default_build_plate_id not in supported_plate_ids
            ):
                raise ValueError(
                    "Machine registry default build plate is not supported: "
                    f"{machine.get('machine_profile_id')}:{default_build_plate_id}"
                )
            machine_build_plates = tuple(
                slicer_build_plates[build_plate_id]
                for build_plate_id in supported_plate_ids
            )
            for nozzle_index, nozzle_value in enumerate(machine.get("nozzles", [])):
                nozzle = _require_mapping(nozzle_value, label=f"nozzles[{nozzle_index}]")
                device = DeviceProfile(
                    device_profile_id=str(nozzle["device_profile_id"]),
                    machine_profile_id=str(machine["machine_profile_id"]),
                    slicer_id=slicer_id,
                    slicer_display_name=str(slicer["display_name"]),
                    source_version=str(slicer["source_version"]),
                    application_metadata=str(slicer["application_metadata"]),
                    client_version=str(slicer.get("client_version") or ""),
                    sidecar_policy=str(slicer["sidecar_policy"]),
                    display_name=str(machine["display_name"]),
                    brand=str(machine["brand"]),
                    vendor_key=str(machine["vendor_key"]),
                    bed_width=int(machine["bed_width"]),
                    bed_depth=int(machine["bed_depth"]),
                    bed_height=int(machine["bed_height"]),
                    thumbnail=str(machine.get("thumbnail", "")),
                    nozzle_size=str(nozzle["nozzle_size"]),
                    source_profile_name=str(nozzle["source_profile_name"]),
                    template=str(nozzle["template"]),
                    revision=str(nozzle["revision"]),
                    supported=bool(nozzle.get("supported", True)),
                    build_plates=machine_build_plates,
                    default_build_plate_id=default_build_plate_id,
                )
                if device.device_profile_id in devices:
                    raise ValueError(
                        "Duplicate machine registry device profile: "
                        f"{device.device_profile_id}"
                    )
                devices[device.device_profile_id] = device
                build_plates_by_device_id[device.device_profile_id] = {
                    plate.id: plate for plate in machine_build_plates
                }

    return MachineRegistry(
        schema_version=int(data["schema_version"]),
        generated_at=str(data["generated_at"]),
        devices_by_id=devices,
        build_plates_by_device_id=build_plates_by_device_id,
    )
