"""Read-only material Registry API routes.
只读耗材 Registry API 路由。
"""

from __future__ import annotations

from typing import Annotated

import os

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from api.file_bridge import upload_to_tempfile
from api.schemas.responses import (
    MaterialRegistryCatalogResponse,
    MaterialRegistryPackageMutationResponse,
)
from api.schemas.single_stage import MaterialRegistryApproveRequest
from api.structured_logging import get_logger
from core.material_registry import (
    approve_material_registry_package,
    build_material_registry_catalog,
    material_registry_package_channels,
    normalize_material_registry_channels,
    resolve_material_registry_package_path,
    upload_material_registry_package,
    verify_material_registry_read_access,
)
from core.single_stage import invalidate_material_registry_remote_catalog_cache

router = APIRouter(prefix="/api/material-registry/v1", tags=["Material Registry"])
log = get_logger(__name__)


@router.get("/materials/catalog", response_model=MaterialRegistryCatalogResponse)
async def material_registry_catalog(
    channel: Annotated[list[str] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    authorization: Annotated[str | None, Header()] = None,
) -> MaterialRegistryCatalogResponse:
    """Return a read-only catalog of published material package revisions.
    返回已发布耗材包 revision 的只读 catalog。
    """
    try:
        channels = normalize_material_registry_channels(channel)
        verify_material_registry_read_access(
            channels=channels,
            authorization=authorization,
        )
        catalog = build_material_registry_catalog(
            channels=channels,
            limit=limit,
            offset=offset,
            query=q,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    log.info(
        "Material registry catalog loaded",
        extra={
            "event": "material_registry_catalog_done",
            "channels": catalog["channels"],
            "material_count": catalog["count"],
            "total_count": catalog.get("total_count"),
            "offset": catalog.get("offset"),
            "limit": catalog.get("limit"),
            "query": q,
        },
    )
    return MaterialRegistryCatalogResponse(**catalog)


@router.post("/packages/upload", response_model=MaterialRegistryPackageMutationResponse)
async def material_registry_package_upload(
    archive: UploadFile = File(...),
) -> MaterialRegistryPackageMutationResponse:
    """Upload one package into the pending Registry channel.
    上传一个耗材包到 Registry pending 频道。
    """
    filename = archive.filename or ""
    if not filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=422,
            detail=f"Uploaded file must be a ZIP archive: {filename or '<unnamed>'}",
        )
    archive_path: str | None = None
    try:
        archive_path = await upload_to_tempfile(archive, suffix=".zip")
        result = upload_material_registry_package(archive_path=archive_path)
        invalidate_material_registry_remote_catalog_cache()
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if archive_path is not None:
            try:
                os.remove(archive_path)
            except OSError:
                pass

    log.info(
        "Material registry package uploaded",
        extra={
            "event": "material_registry_package_upload_done",
            "channel": result["channel"],
            "package_path": result["package_path"],
            "material_count": len(result["materials"]),
        },
    )
    return MaterialRegistryPackageMutationResponse(
        status="ok",
        message="Material package uploaded for review",
        **result,
    )


@router.post(
    "/packages/{package_path:path}/approve",
    response_model=MaterialRegistryPackageMutationResponse,
)
async def material_registry_package_approve(
    package_path: str,
    payload: MaterialRegistryApproveRequest,
) -> MaterialRegistryPackageMutationResponse:
    """Approve one Registry package into the official channel.
    将一个 Registry 耗材包审批进入 official 频道。
    """
    try:
        result = approve_material_registry_package(
            package_path=package_path,
            official_password=payload.official_password,
        )
        invalidate_material_registry_remote_catalog_cache()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    log.info(
        "Material registry package approved",
        extra={
            "event": "material_registry_package_approve_done",
            "channel": result["channel"],
            "package_path": result["package_path"],
            "material_count": len(result["materials"]),
        },
    )
    return MaterialRegistryPackageMutationResponse(
        status="ok",
        message="Material package approved as official",
        **result,
    )


@router.get("/packages/{package_path:path}")
async def material_registry_package_download(
    package_path: str,
    authorization: Annotated[str | None, Header()] = None,
) -> FileResponse:
    """Download one immutable material package ZIP.
    下载一个不可变耗材包 ZIP。
    """
    try:
        resolved_path = resolve_material_registry_package_path(package_path=package_path)
        channels = material_registry_package_channels(resolved_path)
        verify_material_registry_read_access(
            channels=channels,
            authorization=authorization,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    log.info(
        "Material registry package downloaded",
        extra={
            "event": "material_registry_package_download_done",
            "package_path": package_path,
            "bytes": int(resolved_path.stat().st_size),
        },
    )
    return FileResponse(
        path=resolved_path,
        filename=resolved_path.name,
        media_type="application/zip",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
