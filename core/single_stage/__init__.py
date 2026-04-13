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
    "SingleStageExtractResult",
    "StageAFitResult",
    "generate_single_stage_kit",
    "extract_single_stage_dataset",
    "fit_stage_a_from_stage_json",
    "resolve_single_stage_colorchecker_assets",
]
