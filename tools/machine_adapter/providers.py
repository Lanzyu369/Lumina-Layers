from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MachineAdapterProvider:
    slicer_id: str
    display_name: str
    profile_format: str
    sidecar_policy: str
    default_vendor_keys: tuple[str, ...]


PROVIDERS: dict[str, MachineAdapterProvider] = {
    "BambuStudio": MachineAdapterProvider(
        slicer_id="BambuStudio",
        display_name="Bambu Studio",
        profile_format="bambu_orca",
        sidecar_policy="bambu_studio",
        default_vendor_keys=("BBL",),
    ),
    "OrcaSlicer": MachineAdapterProvider(
        slicer_id="OrcaSlicer",
        display_name="OrcaSlicer",
        profile_format="bambu_orca",
        sidecar_policy="orca_like",
        default_vendor_keys=("BBL", "Anycubic", "Elegoo", "Snapmaker"),
    ),
    "SnapmakerOrca": MachineAdapterProvider(
        slicer_id="SnapmakerOrca",
        display_name="Snapmaker Orca",
        profile_format="bambu_orca",
        sidecar_policy="orca_like",
        default_vendor_keys=("Snapmaker",),
    ),
    "ElegooSlicer": MachineAdapterProvider(
        slicer_id="ElegooSlicer",
        display_name="ElegooSlicer",
        profile_format="bambu_orca",
        sidecar_policy="orca_like",
        default_vendor_keys=("Elegoo",),
    ),
    "AnycubicSlicerNext": MachineAdapterProvider(
        slicer_id="AnycubicSlicerNext",
        display_name="Anycubic Slicer Next",
        profile_format="bambu_orca",
        sidecar_policy="anycubic_next",
        default_vendor_keys=("Anycubic",),
    ),
    "FlashStudio": MachineAdapterProvider(
        slicer_id="FlashStudio",
        display_name="Flash Studio Desktop",
        profile_format="bambu_orca",
        sidecar_policy="orca_like",
        default_vendor_keys=("Flashforge",),
    ),
}


def get_provider(slicer_id: str) -> MachineAdapterProvider:
    try:
        return PROVIDERS[slicer_id]
    except KeyError as exc:
        raise KeyError(f"Unsupported machine adapter provider: {slicer_id}") from exc
