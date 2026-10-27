"""Canonical Lumina entry points for native slicer 3MF export.

Lumina supplies geometry and product intent. FatCat owns native metadata;
Neroued performs the final package write. Historical Bambu module imports stay
available as compatibility paths to the same implementations.

Lumina 提供几何与产品意图，FatCat 负责原生元数据，Neroued 最终写包。
历史 Bambu 模块导入继续指向同一实现，保留调用兼容。
"""

from utils.bambu_3mf_writer import (
    Slicer3MFWriter,
    export_scene_with_slicer_metadata,
    load_export_project_settings,
    read_wipe_tower_placement_warnings,
)
from utils.merged_bambu_3mf_writer import (
    MaterialSlot,
    MergedItem,
    MergedSlicer3MFWriter,
    MergedWriteError,
)

__all__ = [
    "Slicer3MFWriter",
    "MergedSlicer3MFWriter",
    "MaterialSlot",
    "MergedItem",
    "MergedWriteError",
    "export_scene_with_slicer_metadata",
    "load_export_project_settings",
    "read_wipe_tower_placement_warnings",
]
