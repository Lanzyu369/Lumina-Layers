"""Vectorizer domain API router.
Vectorizer 领域 API 路由模块。

Provides endpoints for image-to-SVG vectorization using
the neroued_vectorizer library.
提供基于 neroued_vectorizer 库的图像转 SVG 矢量化端点。
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from api.dependencies import get_file_registry, get_worker_pool
from api.errors import to_http_exception
from api.file_bridge import ensure_png_tempfile
from api.file_registry import FileRegistry
from api.schemas.vectorizer import (
    VectorizeDefaultsResponse,
    VectorizeParams,
    VectorizeResponse,
)
from api.worker_pool import WorkerPoolManager
from api.workers.vectorizer_workers import worker_vectorize
from api.structured_logging import get_logger

router = APIRouter(prefix="/api/vectorize", tags=["Vectorizer"])
VECTORIZER_OUTPUT_TTL_SECONDS = 1200
log = get_logger(__name__)


def _palette_for_response(palette: object) -> list[str]:
    """Normalize worker palette entries to response hex strings."""

    if not isinstance(palette, list):
        return []
    normalized: list[str] = []
    for entry in palette:
        if isinstance(entry, str):
            normalized.append(entry)
            continue
        try:
            r, g, b = entry
            normalized.append(f"#{int(r):02x}{int(g):02x}{int(b):02x}")
        except (TypeError, ValueError):
            normalized.append(str(entry))
    return normalized


@router.get("/defaults")
def vectorize_defaults() -> VectorizeDefaultsResponse:
    """Return default vectorization parameters.
    返回默认矢量化参数。
    """
    return VectorizeDefaultsResponse()


@router.post("")
async def vectorize_image(
    image: UploadFile = File(...),
    params: str = Form("{}"),
    pool: WorkerPoolManager = Depends(get_worker_pool),
    registry: FileRegistry = Depends(get_file_registry),
) -> VectorizeResponse:
    """Vectorize an uploaded image to SVG.
    将上传的图像矢量化为 SVG。

    Accepts a multipart form with an image file and a JSON string
    of vectorization parameters. Runs the CPU-intensive vectorization
    in a worker process and returns the SVG download URL with statistics.
    接受包含图像文件和矢量化参数 JSON 字符串的 multipart 表单。
    在工作进程中运行 CPU 密集型矢量化，返回 SVG 下载 URL 和统计信息。

    Args:
        image: Uploaded image file. (上传的图像文件)
        params: JSON-encoded VectorizeParams. (JSON 编码的矢量化参数)
        pool: Worker pool dependency. (工作进程池)
        registry: File registry dependency. (文件注册表)

    Returns:
        VectorizeResponse with SVG URL and statistics. (包含 SVG URL 和统计信息的响应)
    """
    import json

    try:
        params_dict = json.loads(params)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"Invalid params JSON: {e}")

    try:
        validated = VectorizeParams(**params_dict)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())
    params_clean = validated.model_dump()

    image_path = await ensure_png_tempfile(image)

    try:
        result = await pool.submit(worker_vectorize, image_path, params_clean)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Vectorization timed out")
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as e:
        log.exception(
            "Vectorization failed",
            extra={
                "event": "vectorize_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise to_http_exception(e, "Vectorization")

    svg_file_id = registry.register_path(
        str(uuid.uuid4()),
        result["svg_path"],
        "output.svg",
        ttl_seconds=VECTORIZER_OUTPUT_TTL_SECONDS,
    )
    palette = result["palette"]
    palette_size = len(palette) if isinstance(palette, list) else 0

    log.info(
        "Image vectorized",
        extra={
            "event": "vectorize_image_done",
            "svg_file_id": svg_file_id,
            "num_shapes": result["num_shapes"],
            "num_colors": result["num_colors"],
            "width": result["width"],
            "height": result["height"],
            "palette_size": palette_size,
        },
    )

    return VectorizeResponse(
        status="ok",
        message=f"Vectorized: {result['num_shapes']} shapes, {result['num_colors']} colors",
        svg_url=f"/api/files/{svg_file_id}",
        width=result["width"],
        height=result["height"],
        num_shapes=result["num_shapes"],
        num_colors=result["num_colors"],
        palette=_palette_for_response(palette),
    )
