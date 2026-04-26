"""
S04 — Debug preview image saving (optional step).
S04 — 调试预览图保存（可选步骤）。

从 converter.py 搬入的 _save_debug_preview 函数。
此步骤为 optional，失败不终止管道。
"""

from api.structured_logging import get_logger
import os
import time
import numpy as np
import cv2
from PIL import Image

from config import OUTPUT_DIR, ModelingMode

_log = get_logger(__name__)


def _save_debug_preview(debug_data, material_matrix, mask_solid, image_path, mode_name, num_materials=4):
    """Save high-fidelity mode debug preview image.
    保存高保真模式调试预览图。

    Shows the K-Means quantized image, which is the actual input the vectorizer receives.
    Optionally draws contours to show shape recognition results.

    Args:
        debug_data (dict): 调试数据字典，包含 quantized_image 和 num_colors
        material_matrix (np.ndarray): 材料矩阵
        mask_solid (np.ndarray): 实体掩码
        image_path (str): 原始图像路径
        mode_name (str): 模式名称
        num_materials (int): 材料数量 (4 或 6)，默认 4
    """
    quantized_image = debug_data["quantized_image"]
    num_colors = debug_data["num_colors"]

    _log.debug(f"Saving {mode_name} debug preview...")
    _log.debug(f"Quantized to {num_colors} colors")

    debug_img = quantized_image.copy()

    # Draw contours to show how the vectorizer interprets shapes
    try:
        contour_overlay = debug_img.copy()

        for mat_id in range(num_materials):
            mat_mask = np.zeros(material_matrix.shape[:2], dtype=np.uint8)
            for layer in range(material_matrix.shape[2]):
                mat_mask = np.logical_or(mat_mask, material_matrix[:, :, layer] == mat_id)

            mat_mask = np.logical_and(mat_mask, mask_solid).astype(np.uint8) * 255

            if not np.any(mat_mask):
                continue

            contours, _ = cv2.findContours(mat_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

            cv2.drawContours(contour_overlay, contours, -1, (0, 0, 0), 1)

        debug_img = contour_overlay
        _log.debug(f"Contours drawn on preview")

    except (cv2.error, ValueError, TypeError) as e:
        _log.warning(f"Could not draw contours: {e}")

    base_name = os.path.splitext(os.path.basename(image_path))[0]
    debug_path = os.path.join(OUTPUT_DIR, f"{base_name}_{mode_name}_Debug.png")

    debug_pil = Image.fromarray(debug_img, mode="RGB")
    debug_pil.save(debug_path, "PNG")

    _log.debug(f"Saved: {debug_path}")
    _log.debug(f"This is the EXACT image the vectorizer sees before meshing")


def run(ctx: dict) -> dict:
    """Save debug preview if in high-fidelity mode with debug data available.
    如果处于高保真模式且有调试数据，保存调试预览图。

    此步骤为 optional，失败不终止管道（仅打印警告）。

    PipelineContext 输入键 / Input keys:
        - debug_data (dict | None): 调试数据
        - material_matrix (np.ndarray): 材料矩阵
        - mask_solid (np.ndarray): 实体掩码
        - image_path (str): 原始图像路径
        - mode_info (dict): 模式信息（包含 'mode': ModelingMode）
        - slot_names (list): 材料槽名称列表

    PipelineContext 输出键 / Output keys:
        (无新键，仅副作用：写文件)
    """
    _t0 = time.perf_counter()
    debug_data = ctx.get("debug_data")
    mode_info = ctx["mode_info"]

    if debug_data is not None and mode_info["mode"] == ModelingMode.HIGH_FIDELITY:
        try:
            num_materials = len(ctx["slot_names"])
            _save_debug_preview(
                debug_data=debug_data,
                material_matrix=ctx["material_matrix"],
                mask_solid=ctx["mask_solid"],
                image_path=ctx["image_path"],
                mode_name=mode_info["mode"].get_display_name(),
                num_materials=num_materials,
            )
        except (OSError, ValueError, TypeError, cv2.error) as e:
            _log.warning(f"Failed to save debug preview: {e}")

    _elapsed = time.perf_counter() - _t0
    _hifi_timings = ctx.get("_hifi_timings", {})
    _hifi_timings["debug_preview_s"] = _elapsed
    ctx["_hifi_timings"] = _hifi_timings
    _log.info(f"debug_preview done: {_elapsed:.3f}s")
    return ctx
