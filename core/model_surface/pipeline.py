from __future__ import annotations

import numpy as np

from config import PrinterConfig
from core.converter import build_image_model_context
from core.model_surface.assembly import (
    MODEL_SURFACE_DISPLAY_LAYER_HEIGHTS_KEY,
    MODEL_SURFACE_DISPLAY_Z_BOUNDS_KEY,
    OverlaySceneResult,
    apply_model_transform_to_overlay_scene,
    build_embedded_overlay_scene,
)
from core.model_surface.loader import load_model_surface_mesh
from core.model_surface.slot_meshing import build_slot_box_scene_from_voxels
from core.model_surface.types import ModelSurfaceError, SurfaceFootprint


def build_surface_overlay_scene(
    *,
    model_path: str,
    artwork_image_path: str,
    lut_path: str,
    converter_params: dict,
    footprint: SurfaceFootprint,
    pocket_depth_mm: float,
    model_transform: dict | None = None,
) -> OverlaySceneResult:
    """Build a model-surface overlay scene by reusing the image converter.

    复用图片转换器构建模型覆面装配场景。
    """

    loaded = load_model_surface_mesh(model_path)
    surface_converter_params = dict(converter_params)
    surface_converter_params["structure_mode"] = "Single-sided"
    ctx = build_image_model_context(
        stop_after_step="S08",
        image_path=artwork_image_path,
        lut_path=lut_path,
        **surface_converter_params,
    )
    if ctx.get("error"):
        raise ModelSurfaceError(str(ctx["error"]))
    pattern_scene = _build_pattern_scene(ctx)
    if len(pattern_scene.geometry) == 0:
        raise ModelSurfaceError("Converter did not produce an overlay pattern scene.")
    overlay = build_embedded_overlay_scene(
        base_mesh=loaded.mesh,
        pattern_scene=pattern_scene,
        footprint=footprint,
        pocket_depth_mm=pocket_depth_mm,
        base_slot_name="surface_base",
        base_color=(245, 245, 245),
    )
    return apply_model_transform_to_overlay_scene(overlay, model_transform)


def _build_pattern_scene(ctx: dict):
    full_matrix = ctx.get("full_matrix")
    slot_names = ctx.get("slot_names")
    preview_colors = ctx.get("preview_colors")
    target_h = ctx.get("target_h")
    pixel_scale = ctx.get("pixel_scale")
    if (
        full_matrix is not None
        and slot_names is not None
        and preview_colors is not None
        and target_h is not None
        and pixel_scale is not None
    ):
        pattern_matrix, layer_heights_mm = _resolve_surface_display_stack(
            ctx,
            np.asarray(full_matrix),
        )
        pattern_scene = build_slot_box_scene_from_voxels(
            full_matrix=pattern_matrix,
            slot_names=slot_names,
            preview_colors=preview_colors,
            target_h=int(target_h),
            pixel_scale=float(pixel_scale),
            layer_heights_mm=layer_heights_mm,
        )
        pattern_scene.metadata[MODEL_SURFACE_DISPLAY_Z_BOUNDS_KEY] = (
            0.0,
            float(sum(layer_heights_mm)),
        )
        pattern_scene.metadata[MODEL_SURFACE_DISPLAY_LAYER_HEIGHTS_KEY] = (
            layer_heights_mm
        )
        return pattern_scene
    raise ModelSurfaceError("Converter did not produce a display voxel stack.")


def _resolve_surface_display_stack(
    ctx: dict,
    full_matrix: np.ndarray,
) -> tuple[np.ndarray, tuple[float, ...]]:
    """Return display-only voxels ordered from model interior to viewing face.

    返回从模型内侧到观赏面的纯展示体素及其逐层物理厚度。
    """

    if full_matrix.ndim != 3:
        raise ModelSurfaceError("Converter produced an invalid voxel matrix.")

    material_matrix = ctx.get("material_matrix")
    if isinstance(material_matrix, np.ndarray) and material_matrix.ndim == 3:
        display_layer_count = int(material_matrix.shape[2])
    else:
        try:
            display_layer_count = int(ctx.get("color_layers"))
        except (TypeError, ValueError) as exc:
            raise ModelSurfaceError("Converter did not report display layer count.") from exc
    if display_layer_count <= 0 or display_layer_count > full_matrix.shape[0]:
        raise ModelSurfaceError("Converter produced an invalid display layer count.")

    canonical_heights_raw = ctx.get("display_layer_heights_mm")
    if canonical_heights_raw is None:
        uniform_height_raw = ctx.get("layer_height_mm")
        if uniform_height_raw is None:
            uniform_height_raw = PrinterConfig.LAYER_HEIGHT
        try:
            uniform_height_mm = float(uniform_height_raw)
        except (TypeError, ValueError) as exc:
            raise ModelSurfaceError("Converter produced an invalid display layer height.") from exc
        canonical_heights = np.full(
            display_layer_count,
            uniform_height_mm,
            dtype=np.float64,
        )
    else:
        try:
            canonical_heights = np.asarray(
                canonical_heights_raw,
                dtype=np.float64,
            )
        except (TypeError, ValueError) as exc:
            raise ModelSurfaceError("Converter produced invalid display layer heights.") from exc

    if canonical_heights.shape != (display_layer_count,):
        raise ModelSurfaceError("Converter display layer heights do not match its layer count.")
    if not np.all(np.isfinite(canonical_heights)) or np.any(canonical_heights <= 0.0):
        raise ModelSurfaceError("Converter display layer heights must be positive and finite.")

    face_orientation = str(ctx.get("bambu_face_orientation", "down") or "down").lower()
    if face_orientation == "down":
        display_matrix = np.flip(full_matrix[:display_layer_count], axis=0)
    elif face_orientation == "up":
        display_matrix = full_matrix[-display_layer_count:]
    else:
        raise ModelSurfaceError("Model-surface overlay requires a single display face.")

    return (
        np.ascontiguousarray(display_matrix),
        tuple(float(value) for value in canonical_heights[::-1]),
    )
