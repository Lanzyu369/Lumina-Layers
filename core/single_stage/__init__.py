"""Single-stage calibration workflow helpers.

Utilities for generating single-stage calibration kits and consuming
single-stage datasets / Stage A parameter fitting.
"""

from .kit import (
    SINGLE_STAGE_SPEC,
    SingleStageKitResult,
    SingleStageSpec,
    generate_single_stage_kit,
)
from .materials import (
    GradientCardStageAResult,
    MaterialArchiveDeleteResult,
    MaterialArchiveExportResult,
    MaterialArchiveImportResult,
    MaterialArchiveSaveResult,
    MaterialArchiveUpdateResult,
    delete_saved_stage_a_material_archive,
    export_saved_stage_a_material_archives,
    extract_stage_a_material_from_gradient_cards,
    get_material_sync_status,
    get_material_usage,
    import_saved_stage_a_material_archives,
    list_saved_stage_a_material_archives,
    record_material_usage,
    refresh_material_sync_from_registry,
    resolve_saved_material_dir,
    save_stage_a_material_archive,
    update_saved_stage_a_material_archive_metadata,
)
from .processing import (
    StageAFitResult,
    SingleStageExtractResult,
    extract_single_stage_dataset,
    fit_stage_a_from_stage_json,
    resolve_single_stage_colorchecker_assets,
)

__all__ = [
    "SINGLE_STAGE_SPEC",
    "SingleStageKitResult",
    "SingleStageSpec",
    "GradientCardStageAResult",
    "MaterialArchiveDeleteResult",
    "MaterialArchiveExportResult",
    "MaterialArchiveImportResult",
    "MaterialArchiveSaveResult",
    "MaterialArchiveUpdateResult",
    "SingleStageExtractResult",
    "StageAFitResult",
    "delete_saved_stage_a_material_archive",
    "export_saved_stage_a_material_archives",
    "generate_single_stage_kit",
    "extract_stage_a_material_from_gradient_cards",
    "extract_single_stage_dataset",
    "fit_stage_a_from_stage_json",
    "get_material_sync_status",
    "get_material_usage",
    "import_saved_stage_a_material_archives",
    "list_saved_stage_a_material_archives",
    "record_material_usage",
    "refresh_material_sync_from_registry",
    "resolve_saved_material_dir",
    "save_stage_a_material_archive",
    "update_saved_stage_a_material_archive_metadata",
    "resolve_single_stage_colorchecker_assets",
]
