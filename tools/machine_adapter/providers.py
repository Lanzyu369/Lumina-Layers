from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MachineAdapterProvider:
    """Describe one slicer's shared machine-profile import defaults.

    描述同一切片软件在所有机器配置导入入口中共享的默认值。

    Attributes:
        slicer_id (str): Canonical slicer identifier.（标准切片软件标识）
        display_name (str): User-facing slicer name.（面向用户的切片软件名称）
        profile_format (str): Native profile parser family.（原生配置解析格式）
        default_vendor_keys (tuple[str, ...]): Default vendor manifests.
            （默认厂商清单）
    """

    slicer_id: str
    display_name: str
    profile_format: str
    default_vendor_keys: tuple[str, ...]


PROVIDERS: dict[str, MachineAdapterProvider] = {
    "BambuStudio": MachineAdapterProvider(
        slicer_id="BambuStudio",
        display_name="Bambu Studio",
        profile_format="bambu_orca",
        default_vendor_keys=("BBL",),
    ),
    "OrcaSlicer": MachineAdapterProvider(
        slicer_id="OrcaSlicer",
        display_name="OrcaSlicer",
        profile_format="bambu_orca",
        default_vendor_keys=("BBL", "Anycubic", "Elegoo", "Snapmaker"),
    ),
    "SnapmakerOrca": MachineAdapterProvider(
        slicer_id="SnapmakerOrca",
        display_name="Snapmaker Orca",
        profile_format="bambu_orca",
        default_vendor_keys=("Snapmaker",),
    ),
    "ElegooSlicer": MachineAdapterProvider(
        slicer_id="ElegooSlicer",
        display_name="ElegooSlicer",
        profile_format="bambu_orca",
        default_vendor_keys=("Elegoo",),
    ),
    "AnycubicSlicerNext": MachineAdapterProvider(
        slicer_id="AnycubicSlicerNext",
        display_name="Anycubic Slicer Next",
        profile_format="bambu_orca",
        default_vendor_keys=("Anycubic",),
    ),
    "FlashStudio": MachineAdapterProvider(
        slicer_id="FlashStudio",
        display_name="Flash Studio Desktop",
        profile_format="bambu_orca",
        default_vendor_keys=("Flashforge",),
    ),
    "QIDIStudio": MachineAdapterProvider(
        slicer_id="QIDIStudio",
        display_name="QIDI Studio",
        profile_format="bambu_orca",
        default_vendor_keys=("Q Series", "X 4 Series", "X 5 Series"),
    ),
}


def get_provider(slicer_id: str) -> MachineAdapterProvider:
    try:
        return PROVIDERS[slicer_id]
    except KeyError as exc:
        raise KeyError(f"Unsupported machine adapter provider: {slicer_id}") from exc
