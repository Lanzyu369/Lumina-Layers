"""Calibration domain API router.
Calibration 领域 API 路由模块。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_file_registry
from api.file_bridge import pil_to_png_bytes
from api.file_registry import FileRegistry
from api.schemas.calibration import CalibrationGenerateRequest
from api.schemas.responses import CalibrationResponse, SingleStageKitResponse
from api.schemas.single_stage import SingleStageKitGenerateRequest
from config import PaletteEntry
from core.calibration import (
    generate_5color_extended_batch_zip,
    generate_8color_batch_zip,
    generate_bw_calibration_board,
    generate_calibration_board,
    generate_smart_board,
    generate_smart_board_rybw,
)
from core.single_stage import generate_single_stage_kit

router = APIRouter(prefix="/api/calibration", tags=["Calibration"])


def _handle_core_error(e: Exception, context: str) -> None:
    """将 core 模块异常转换为 HTTP 500 错误。"""
    print(f"[API] {context} error: {e}")
    raise HTTPException(status_code=500, detail=f"{context} failed: {str(e)}")


@router.post("/generate")
def calibration_generate(
    request: CalibrationGenerateRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> CalibrationResponse:
    """Generate a printable calibration board.
    生成可打印的校准板。
    """
    mode = request.color_mode.value
    try:
        if mode == "BW (Black & White)":
            path, preview_img, status = generate_bw_calibration_board(
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
                backing_color=request.backing.value,
            )
        elif mode == "4-Color (RYBW)":
            path, preview_img, status = generate_calibration_board(
                color_mode="RYBW",
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
                backing_color=request.backing.value,
            )
        elif mode == "4-Color (CMYW)":
            path, preview_img, status = generate_calibration_board(
                color_mode="CMYW",
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
                backing_color=request.backing.value,
            )
        elif mode == "6-Color (CMYWGK 1296)":
            path, preview_img, status = generate_smart_board(
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
            )
        elif mode == "6-Color (RYBWGK 1296)":
            path, preview_img, status = generate_smart_board_rybw(
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
            )
        elif mode == "8-Color Max":
            path, preview_img, status = generate_8color_batch_zip(
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
            )
        elif mode == "5-Color Extended (1444)":
            path, preview_img, status = generate_5color_extended_batch_zip(
                block_size_mm=float(request.block_size),
                gap_mm=request.gap,
            )
        else:
            raise HTTPException(
                status_code=422, detail=f"Unsupported color mode: {mode}"
            )
    except HTTPException:
        raise
    except Exception as e:
        _handle_core_error(e, "Calibration generation")

    # Register files via FileRegistry
    sid = "calibration"  # Stateless endpoint uses fixed session identifier
    download_id = registry.register_path(sid, path)
    preview_bytes = pil_to_png_bytes(preview_img)
    preview_id = registry.register_bytes(sid, preview_bytes, "preview.png")

    return CalibrationResponse(
        status="ok",
        message=status,
        download_url=f"/api/files/{download_id}",
        preview_url=f"/api/files/{preview_id}",
    )


@router.post("/generate-single-stage-kit")
def calibration_generate_single_stage_kit(
    request: SingleStageKitGenerateRequest,
    registry: FileRegistry = Depends(get_file_registry),
) -> SingleStageKitResponse:
    """Generate a ChromaPrint3D-compatible single-stage kit."""
    try:
        palette = [
            PaletteEntry(
                color=entry.color,
                material=entry.material,
                hex_color=entry.hex_color,
                color_name=entry.color_name,
            )
            for entry in request.palette
        ]
        result = generate_single_stage_kit(
            palette=palette,
            substrate_id=request.substrate_id,
            substrate_display_name=request.substrate_display_name,
            material_default=request.material_default,
        )
    except Exception as e:
        _handle_core_error(e, "Single-stage kit generation")

    sid = "calibration"
    kit_id = registry.register_path(sid, result.zip_path)
    manifest_id = registry.register_path(sid, result.manifest_path)
    preview_id = registry.register_bytes(
        sid,
        pil_to_png_bytes(result.preview_image),
        "single_stage_preview.png",
    )
    return SingleStageKitResponse(
        status="ok",
        message=result.message,
        kit_download_url=f"/api/files/{kit_id}",
        preview_url=f"/api/files/{preview_id}",
        manifest_url=f"/api/files/{manifest_id}",
        jobs=result.jobs,
    )
