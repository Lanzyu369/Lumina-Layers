from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DeviceProfile:
    """Resolved Lumina device profile at slicer + machine + nozzle grain."""

    device_profile_id: str
    machine_profile_id: str
    slicer_id: str
    slicer_display_name: str
    source_version: str
    application_metadata: str
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


@dataclass(frozen=True)
class MachineRegistry:
    """In-memory index for generated Lumina machine registry data."""

    schema_version: int
    generated_at: str
    devices_by_id: dict[str, DeviceProfile]

    def get_device_profile(self, device_profile_id: str) -> DeviceProfile:
        return self.devices_by_id[device_profile_id]


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

    for slicer_index, slicer_value in enumerate(data.get("slicers", [])):
        slicer = _require_mapping(slicer_value, label=f"slicers[{slicer_index}]")
        slicer_id = str(slicer["slicer_id"])
        for machine_index, machine_value in enumerate(slicer.get("machines", [])):
            machine = _require_mapping(machine_value, label=f"machines[{machine_index}]")
            for nozzle_index, nozzle_value in enumerate(machine.get("nozzles", [])):
                nozzle = _require_mapping(nozzle_value, label=f"nozzles[{nozzle_index}]")
                device = DeviceProfile(
                    device_profile_id=str(nozzle["device_profile_id"]),
                    machine_profile_id=str(machine["machine_profile_id"]),
                    slicer_id=slicer_id,
                    slicer_display_name=str(slicer["display_name"]),
                    source_version=str(slicer["source_version"]),
                    application_metadata=str(slicer["application_metadata"]),
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
                )
                devices[device.device_profile_id] = device

    return MachineRegistry(
        schema_version=int(data["schema_version"]),
        generated_at=str(data["generated_at"]),
        devices_by_id=devices,
    )
