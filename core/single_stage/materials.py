"""Compatibility imports for the material workflows.

New code uses the owning modules; existing material API imports stay valid.
"""

from .material_calibration import (
    GradientCardStageAResult,
    extract_stage_a_material_from_gradient_cards,
)
from .material_files import (
    MATERIALS_DIR,
    TEMP_DIR,
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
    DEFAULT_MATERIAL_PACKAGE_MAX_ARCHIVE_BYTES,
    DEFAULT_MATERIAL_PACKAGE_MAX_COMPRESSION_RATIO,
    DEFAULT_MATERIAL_PACKAGE_MAX_UNCOMPRESSED_BYTES,
    DEFAULT_MATERIAL_PACKAGE_MAX_ZIP_ENTRIES,
    DEFAULT_MATERIAL_PACKAGE_MAX_ZIP_ENTRY_BYTES,
    material_package_max_archive_bytes,
    validate_material_bundle_archive,
)
from .material_registry_client import (
    install_material_registry_package,
    invalidate_material_registry_remote_catalog_cache,
    list_material_registry_catalog,
    refresh_material_sync_from_registry,
)
from .material_sync import (
    get_material_sync_status,
    rollback_material_sync_revision,
)

__all__ = [
    "MATERIALS_DIR",
    "TEMP_DIR",
    "DEFAULT_MATERIAL_PACKAGE_MAX_ARCHIVE_BYTES",
    "DEFAULT_MATERIAL_PACKAGE_MAX_COMPRESSION_RATIO",
    "DEFAULT_MATERIAL_PACKAGE_MAX_UNCOMPRESSED_BYTES",
    "DEFAULT_MATERIAL_PACKAGE_MAX_ZIP_ENTRIES",
    "DEFAULT_MATERIAL_PACKAGE_MAX_ZIP_ENTRY_BYTES",
    "GradientCardStageAResult",
    "MaterialArchiveDeleteResult",
    "MaterialArchiveExportResult",
    "MaterialArchiveImportResult",
    "MaterialArchiveSaveResult",
    "MaterialArchiveUpdateResult",
    "delete_saved_stage_a_material_archive",
    "export_saved_stage_a_material_archives",
    "extract_stage_a_material_from_gradient_cards",
    "get_material_sync_status",
    "get_material_usage",
    "import_saved_stage_a_material_archives",
    "install_material_registry_package",
    "invalidate_material_library_cache",
    "invalidate_material_registry_remote_catalog_cache",
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
]
