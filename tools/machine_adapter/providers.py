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
        sidecar_policy (str): 3MF sidecar emission policy.（3MF 附属文件策略）
        default_vendor_keys (tuple[str, ...]): Default vendor manifests.
            （默认厂商清单）
        default_application_metadata (str | None): Default 3MF Application
            identity when callers do not override it.（调用方未覆盖时使用的
            3MF Application 标识）
        default_client_version (str | None): Default native client header;
            an empty string is a meaningful value.（默认原生客户端版本头；
            空字符串也是有效值）
    """

    slicer_id: str
    display_name: str
    profile_format: str
    sidecar_policy: str
    default_vendor_keys: tuple[str, ...]
    default_application_metadata: str | None = None
    default_client_version: str | None = None


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
        default_application_metadata="AnycubicSlicerNext-1.4.1.2",
        default_client_version="1.4.1.2 20260604104233",
    ),
    "FlashStudio": MachineAdapterProvider(
        slicer_id="FlashStudio",
        display_name="Flash Studio Desktop",
        profile_format="bambu_orca",
        sidecar_policy="orca_like",
        default_vendor_keys=("Flashforge",),
        default_application_metadata="BambuStudio-2.3.2",
        default_client_version="",
    ),
}


def get_provider(slicer_id: str) -> MachineAdapterProvider:
    try:
        return PROVIDERS[slicer_id]
    except KeyError as exc:
        raise KeyError(f"Unsupported machine adapter provider: {slicer_id}") from exc
