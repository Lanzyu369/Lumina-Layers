from __future__ import annotations

from core.converter import build_image_model_context
from core.model_surface.assembly import OverlaySceneResult, build_embedded_overlay_scene
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
) -> OverlaySceneResult:
    """Build a model-surface overlay scene by reusing the image converter.

    复用图片转换器构建模型覆面装配场景。
    """

    loaded = load_model_surface_mesh(model_path)
    ctx = build_image_model_context(
        stop_after_step="S08",
        image_path=artwork_image_path,
        lut_path=lut_path,
        **converter_params,
    )
    if ctx.get("error"):
        raise ModelSurfaceError(str(ctx["error"]))
    pattern_scene = _build_pattern_scene(ctx)
    if len(pattern_scene.geometry) == 0:
        raise ModelSurfaceError("Converter did not produce an overlay pattern scene.")
    return build_embedded_overlay_scene(
        base_mesh=loaded.mesh,
        pattern_scene=pattern_scene,
        footprint=footprint,
        pocket_depth_mm=pocket_depth_mm,
        base_slot_name="surface_base",
        base_color=(245, 245, 245),
    )


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
        return build_slot_box_scene_from_voxels(
            full_matrix=full_matrix,
            slot_names=slot_names,
            preview_colors=preview_colors,
            target_h=int(target_h),
            pixel_scale=float(pixel_scale),
        )
    if "scene" not in ctx:
        raise ModelSurfaceError("Converter did not produce an overlay pattern scene.")
    return ctx["scene"]
