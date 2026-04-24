"""Material LUT synthesis — material loading, pipeline helpers, and re-exports.
耗材 LUT 合成 — 耗材加载、管线辅助函数及算法再导出。

This module provides:
- Disk I/O for loading saved material archives (``load_material_params``,
  ``load_multiple_materials``)
- Pipeline integration helpers (``build_material_slot_names``,
  ``build_material_preview_colors``)

The pure color-solving algorithm lives in ``core.material_color_solver``.
All solver symbols are re-exported here for backward compatibility.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from config import MATERIALS_DIR

# Re-export solver symbols so existing imports keep working
from core.material_color_solver import (  # noqa: F401
    ALLOWED_LAYER_HEIGHTS_MM,
    DEFAULT_BEAM_WIDTH,
    DEFAULT_LAYER_COUNT,
    DEFAULT_LAYER_HEIGHT_MM,
    MAX_LAYER_COUNT,
    MIN_LAYER_COUNT,
    MaterialParams,
    beer_lambert_layer as _beer_lambert_layer,
    ensure_not_worse_than_smaller_N,
    forward_model,
    linear_to_srgb_uint8 as _linear_to_srgb_uint8,
    map_pixels_to_materials,
    srgb_to_linear as _srgb_to_linear,
    solve_image_colors,
    solve_image_colors_optimal,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Material loading
# ---------------------------------------------------------------------------


def load_material_params(
    directory_name: str,
    *,
    materials_dir: str | None = None,
) -> MaterialParams:
    """Load a saved material archive and extract Beer-Lambert parameters.
    加载保存的耗材档案并提取 Beer-Lambert 参数。

    Args:
        directory_name: Name of the material directory under ``materials/``.
            (materials/ 下的耗材目录名)
        materials_dir: Override materials root path. (可选的材料根目录覆盖)

    Returns:
        MaterialParams with E, k, C0_white vectors loaded.
    """
    from core.single_stage import resolve_saved_material_dir

    root = Path(materials_dir or MATERIALS_DIR)
    try:
        material_dir = resolve_saved_material_dir(root, directory_name)
    except FileNotFoundError:
        raise FileNotFoundError(f"Material directory not found: {directory_name}")

    archive_path = material_dir / "material.json"
    if not archive_path.exists():
        raise FileNotFoundError(f"material.json not found in {directory_name}")

    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    material_name = str(archive.get("material_name") or directory_name)

    # Load stage_A_parameters.json for E and k
    stage_a_filename = str(archive.get("stage_a_params_file") or "stage_A_parameters.json")
    stage_a_path = material_dir / stage_a_filename
    if not stage_a_path.exists():
        raise FileNotFoundError(f"Stage A parameters not found: {stage_a_filename}")

    stage_a = json.loads(stage_a_path.read_text(encoding="utf-8"))
    parameters = stage_a.get("parameters") or {}
    channels = parameters.get("channels") or []
    if not channels:
        raise ValueError(f"No channels in Stage A parameters for {directory_name}")

    channel0 = channels[0]
    E = np.asarray(channel0["E"], dtype=np.float64)
    k = np.asarray(channel0["k"], dtype=np.float64)
    if E.shape != (3,) or k.shape != (3,):
        raise ValueError(f"E/k must be length-3 vectors, got E={E.shape}, k={k.shape}")

    # Extract C0_white from substrates
    substrates = parameters.get("substrates") or []
    C0_white: np.ndarray | None = None
    for sub in substrates:
        if sub.get("substrate_id") == "white":
            C0_white = np.asarray(sub["C0"], dtype=np.float64)
            break
    # Fallback to fitted_substrates
    if C0_white is None:
        fitted = stage_a.get("fitted_substrates") or {}
        white_fitted = fitted.get("white") or {}
        if "C0" in white_fitted:
            C0_white = np.asarray(white_fitted["C0"], dtype=np.float64)
    if C0_white is None:
        raise ValueError(f"No white substrate C0 found for {directory_name}")
    if C0_white.shape != (3,):
        raise ValueError(f"C0_white must be length-3, got {C0_white.shape}")

    # Estimated sRGB for preview
    material_summary = archive.get("material_summary") or {}
    estimated_rgb_raw = material_summary.get("estimated_rgb")
    if isinstance(estimated_rgb_raw, list) and len(estimated_rgb_raw) >= 3:
        estimated_rgb = np.asarray(estimated_rgb_raw[:3], dtype=np.uint8)
    else:
        estimated_rgb = _linear_to_srgb_uint8(E.reshape(1, 3))[0]

    return MaterialParams(
        name=material_name,
        directory_name=directory_name,
        E=E,
        k=k,
        C0_white=C0_white,
        estimated_rgb=estimated_rgb,
    )


def load_multiple_materials(
    directory_names: list[str],
    *,
    materials_dir: str | None = None,
) -> list[MaterialParams]:
    """Load multiple material archives by directory name.
    批量加载耗材档案。

    Args:
        directory_names: List of material directory names. (耗材目录名列表)
        materials_dir: Override materials root path. (可选的材料根目录覆盖)

    Returns:
        List of MaterialParams in the same order. (按顺序的耗材参数列表)
    """
    if not directory_names:
        raise ValueError("At least one material must be selected")
    materials = []
    for dir_name in directory_names:
        materials.append(load_material_params(dir_name, materials_dir=materials_dir))
    return materials


# ---------------------------------------------------------------------------
# Preview-color / slot-name helpers for pipeline integration
# ---------------------------------------------------------------------------


def build_material_slot_names(materials: list[MaterialParams]) -> list[str]:
    """Build slot_names list from material params — used as mesh/object names in 3MF.
    从耗材参数构建槽位名列表 — 作为 3MF 中的网格/对象名。

    Args:
        materials: List of selected materials. (已选耗材列表)

    Returns:
        List of material names. (耗材名列表)
    """
    return [m.name for m in materials]


def build_material_preview_colors(
    materials: list[MaterialParams],
) -> dict[int, list[int]]:
    """Build preview_colors mapping from material params.
    从耗材参数构建预览颜色映射。

    Args:
        materials: List of selected materials. (已选耗材列表)

    Returns:
        Dict mapping material_id (int) to [R, G, B, A] list. (材料ID到RGBA映射)
    """
    preview: dict[int, list[int]] = {}
    for idx, mat in enumerate(materials):
        rgb = mat.estimated_rgb.tolist()
        preview[idx] = [int(rgb[0]), int(rgb[1]), int(rgb[2]), 255]
    return preview
