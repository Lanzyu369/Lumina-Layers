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
    MaterialArchiveSaveResult,
    extract_stage_a_material_from_gradient_cards,
    save_stage_a_material_archive,
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
    "MaterialArchiveSaveResult",
    "SingleStageExtractResult",
    "StageAFitResult",
    "generate_single_stage_kit",
    "extract_stage_a_material_from_gradient_cards",
    "extract_single_stage_dataset",
    "fit_stage_a_from_stage_json",
    "save_stage_a_material_archive",
    "resolve_single_stage_colorchecker_assets",
]
