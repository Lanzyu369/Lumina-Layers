"""Single-stage calibration and material workflows.

Material owners: calibration (gradient-card fitting), runs (capture selection
and aggregation), files (local paths/cache/usage), library (archive operations),
package (bundle validation), sync (local index/history), and registry_client
(read-only remote synchronization). ``materials`` keeps old public imports.
"""

from .kit import (
    SINGLE_STAGE_SPEC,
    SingleStageKitResult,
    SingleStageSpec,
    generate_single_stage_kit,
)
from .material_calibration import (
    GradientCardStageAResult,
    extract_stage_a_material_from_gradient_cards,
)
from .material_files import (
    get_material_usage,
    invalidate_material_library_cache,
    record_material_usage,
    resolve_saved_material_dir,
)
from .material_library import (
    MaterialArchiveDeleteResult,
    MaterialArchiveExportResult,
    MaterialArchiveImportResult,
    MaterialArchiveSaveResult,
    MaterialArchiveUpdateResult,
    delete_saved_stage_a_material_archive,
    export_saved_stage_a_material_archives,
    import_saved_stage_a_material_archives,
    list_saved_stage_a_material_archives,
    save_stage_a_material_archive,
    update_saved_stage_a_material_archive_metadata,
)
from .material_package import (
    material_package_max_archive_bytes,
    validate_material_bundle_archive,
)
from .material_registry_client import (
    invalidate_material_registry_remote_catalog_cache,
    install_material_registry_package,
    list_material_registry_catalog,
    refresh_material_sync_from_registry,
)
from .material_sync import (
    get_material_sync_status,
    rollback_material_sync_revision,
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
    "invalidate_material_library_cache",
    "invalidate_material_registry_remote_catalog_cache",
    "install_material_registry_package",
    "list_material_registry_catalog",
    "list_saved_stage_a_material_archives",
    "material_package_max_archive_bytes",
    "record_material_usage",
    "refresh_material_sync_from_registry",
    "resolve_saved_material_dir",
    "rollback_material_sync_revision",
    "save_stage_a_material_archive",
    "update_saved_stage_a_material_archive_metadata",
    "validate_material_bundle_archive",
    "resolve_single_stage_colorchecker_assets",
]
