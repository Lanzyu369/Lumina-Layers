"""Material Registry API routes.
耗材 Registry API 路由。
"""

from __future__ import annotations

from typing import Annotated, NoReturn

import os

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from api.file_bridge import UploadTooLargeError, upload_to_tempfile
from api.schemas.responses import (
    MaterialRegistryCatalogResponse,
    MaterialRegistryPackageMutationResponse,
)
from api.schemas.single_stage import (
    MaterialRegistryApproveRequest,
    MaterialRegistryLocalUploadRequest,
)
from api.structured_logging import get_logger
from core.material_registry import (
    MaterialRegistryDuplicateError,
    approve_material_registry_package,
    build_material_registry_catalog,
    material_registry_package_channels,
    normalize_material_registry_channels,
    resolve_material_registry_package_path,
    upload_material_registry_package,
    verify_material_registry_read_access,
    verify_material_registry_write_access,
)
from core.single_stage import (
    export_saved_stage_a_material_archives,
    invalidate_material_library_cache,
    invalidate_material_registry_remote_catalog_cache,
    material_package_max_archive_bytes,
)

router = APIRouter(prefix="/api/material-registry/v1", tags=["Material Registry"])
log = get_logger(__name__)

MATERIAL_REGISTRY_ACCESS_DENIED_DETAIL = (
    "Material Registry access is not authorized for this channel."
)
MATERIAL_REGISTRY_WRITE_ACCESS_DENIED_DETAIL = (
    "Material Registry write access is not authorized or is not configured."
)
MATERIAL_REGISTRY_STORAGE_UNAVAILABLE_DETAIL = (
    "Material Registry storage is not available. Check the Registry service configuration."
)
MATERIAL_REGISTRY_CATALOG_INVALID_DETAIL = (
    "Material Registry catalog request is invalid. Check the channel and pagination values."
)
MATERIAL_REGISTRY_PACKAGE_INVALID_DETAIL = (
    "The material package is invalid. Export it again from Lumina and upload the new ZIP."
)
MATERIAL_REGISTRY_UPLOAD_ZIP_REQUIRED_DETAIL = "Uploaded file must be a ZIP archive."
MATERIAL_REGISTRY_UPLOAD_TOO_LARGE_DETAIL = (
    "The material package ZIP is too large for this Registry service."
)
MATERIAL_REGISTRY_PACKAGE_PATH_INVALID_DETAIL = (
    "The requested material package path is invalid."
)
MATERIAL_REGISTRY_PACKAGE_NOT_FOUND_DETAIL = (
    "The requested material package was not found."
)
MATERIAL_REGISTRY_DUPLICATE_DETAIL = (
    "This material package revision already exists in the Registry."
)
MATERIAL_REGISTRY_LOCAL_PACKAGE_INVALID_DETAIL = (
    "The local material package could not be prepared. Check that the saved material exists and is valid."
)


def _material_registry_storage_unavailable(exc: Exception) -> bool:
    message = str(exc).casefold()
    return "material registry packages directory" in message


def _material_registry_package_path_invalid(exc: Exception) -> bool:
    message = str(exc).casefold()
    return (
        "unsafe material registry package path" in message
        or "material registry package path must reference a zip file" in message
    )


def _catalog_error_detail(exc: Exception) -> str:
    if _material_registry_storage_unavailable(exc):
        return MATERIAL_REGISTRY_STORAGE_UNAVAILABLE_DETAIL
    return MATERIAL_REGISTRY_CATALOG_INVALID_DETAIL


def _package_error_detail(exc: Exception) -> str:
    if _material_registry_storage_unavailable(exc):
        return MATERIAL_REGISTRY_STORAGE_UNAVAILABLE_DETAIL
    if _material_registry_package_path_invalid(exc):
        return MATERIAL_REGISTRY_PACKAGE_PATH_INVALID_DETAIL
    return MATERIAL_REGISTRY_PACKAGE_INVALID_DETAIL


def _local_package_error_detail(exc: Exception) -> str:
    if _material_registry_storage_unavailable(exc):
        return MATERIAL_REGISTRY_STORAGE_UNAVAILABLE_DETAIL
    return MATERIAL_REGISTRY_LOCAL_PACKAGE_INVALID_DETAIL


def _raise_material_registry_error(
    *,
    event: str,
    exc: Exception,
    status_code: int,
    detail: str,
    **fields: object,
) -> NoReturn:
    log.warning(
        "Material Registry request failed",
        extra={
            "event": event,
            "status_code": status_code,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            **fields,
        },
    )
    raise HTTPException(status_code=status_code, detail=detail) from exc


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
        _raise_material_registry_error(
            event="material_registry_catalog_failed",
            exc=exc,
            status_code=403,
            detail=MATERIAL_REGISTRY_ACCESS_DENIED_DETAIL,
            channels=channel,
            query=q,
        )
    except ValueError as exc:
        _raise_material_registry_error(
            event="material_registry_catalog_failed",
            exc=exc,
            status_code=422,
            detail=_catalog_error_detail(exc),
            channels=channel,
            query=q,
        )

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
    official_password: Annotated[
        str | None,
        Header(alias="X-Lumina-Material-Registry-Official-Password"),
    ] = None,
) -> MaterialRegistryPackageMutationResponse:
    """Upload one package into the pending Registry channel.
    上传一个耗材包到 Registry pending 频道。
    """
    filename = archive.filename or ""
    if not filename.lower().endswith(".zip"):
        _raise_material_registry_error(
            event="material_registry_package_upload_failed",
            exc=ValueError("Uploaded file must be a ZIP archive"),
            status_code=422,
            detail=MATERIAL_REGISTRY_UPLOAD_ZIP_REQUIRED_DETAIL,
            upload_filename=filename,
        )
    archive_path: str | None = None
    try:
        verify_material_registry_write_access(official_password=official_password)
        archive_path = await upload_to_tempfile(
            archive,
            suffix=".zip",
            max_bytes=material_package_max_archive_bytes(),
        )
        result = upload_material_registry_package(archive_path=archive_path)
        invalidate_material_registry_remote_catalog_cache()
    except PermissionError as exc:
        _raise_material_registry_error(
            event="material_registry_package_upload_failed",
            exc=exc,
            status_code=403,
            detail=MATERIAL_REGISTRY_WRITE_ACCESS_DENIED_DETAIL,
            upload_filename=filename,
        )
    except UploadTooLargeError as exc:
        _raise_material_registry_error(
            event="material_registry_package_upload_failed",
            exc=exc,
            status_code=413,
            detail=MATERIAL_REGISTRY_UPLOAD_TOO_LARGE_DETAIL,
            upload_filename=filename,
        )
    except MaterialRegistryDuplicateError as exc:
        _raise_material_registry_error(
            event="material_registry_package_upload_failed",
            exc=exc,
            status_code=409,
            detail=MATERIAL_REGISTRY_DUPLICATE_DETAIL,
            upload_filename=filename,
        )
    except (ValueError, OSError) as exc:
        _raise_material_registry_error(
            event="material_registry_package_upload_failed",
            exc=exc,
            status_code=422,
            detail=_package_error_detail(exc),
            upload_filename=filename,
        )
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


@router.post("/packages/upload-local", response_model=MaterialRegistryPackageMutationResponse)
async def material_registry_local_package_upload(
    payload: MaterialRegistryLocalUploadRequest,
    official_password: Annotated[
        str | None,
        Header(alias="X-Lumina-Material-Registry-Official-Password"),
    ] = None,
) -> MaterialRegistryPackageMutationResponse:
    """Export one local material and upload it to the pending Registry channel.
    导出一个本地耗材并上传到 Registry pending 频道。
    """
    archive_path: str | None = None
    try:
        verify_material_registry_write_access(official_password=official_password)
        export_result = export_saved_stage_a_material_archives(
            directory_names=[payload.directory_name],
        )
        archive_path = export_result.archive_path
        result = upload_material_registry_package(archive_path=archive_path)
        invalidate_material_registry_remote_catalog_cache()
    except PermissionError as exc:
        _raise_material_registry_error(
            event="material_registry_local_package_upload_failed",
            exc=exc,
            status_code=403,
            detail=MATERIAL_REGISTRY_WRITE_ACCESS_DENIED_DETAIL,
            directory_name=payload.directory_name,
        )
    except MaterialRegistryDuplicateError as exc:
        _raise_material_registry_error(
            event="material_registry_local_package_upload_failed",
            exc=exc,
            status_code=409,
            detail=MATERIAL_REGISTRY_DUPLICATE_DETAIL,
            directory_name=payload.directory_name,
        )
    except FileNotFoundError as exc:
        _raise_material_registry_error(
            event="material_registry_local_package_upload_failed",
            exc=exc,
            status_code=404,
            detail=MATERIAL_REGISTRY_LOCAL_PACKAGE_INVALID_DETAIL,
            directory_name=payload.directory_name,
        )
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        _raise_material_registry_error(
            event="material_registry_local_package_upload_failed",
            exc=exc,
            status_code=422,
            detail=_local_package_error_detail(exc),
            directory_name=payload.directory_name,
        )
    finally:
        if archive_path is not None:
            try:
                os.remove(archive_path)
            except OSError:
                pass

    log.info(
        "Local material registry package uploaded",
        extra={
            "event": "material_registry_local_package_upload_done",
            "channel": result["channel"],
            "package_path": result["package_path"],
            "material_count": len(result["materials"]),
            "directory_name": payload.directory_name,
        },
    )
    return MaterialRegistryPackageMutationResponse(
        status="ok",
        message="Local material package uploaded for review",
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
        invalidate_material_library_cache()
    except PermissionError as exc:
        _raise_material_registry_error(
            event="material_registry_package_approve_failed",
            exc=exc,
            status_code=403,
            detail=MATERIAL_REGISTRY_WRITE_ACCESS_DENIED_DETAIL,
            package_path=package_path,
        )
    except FileNotFoundError as exc:
        _raise_material_registry_error(
            event="material_registry_package_approve_failed",
            exc=exc,
            status_code=404,
            detail=MATERIAL_REGISTRY_PACKAGE_NOT_FOUND_DETAIL,
            package_path=package_path,
        )
    except (ValueError, OSError) as exc:
        _raise_material_registry_error(
            event="material_registry_package_approve_failed",
            exc=exc,
            status_code=422,
            detail=_package_error_detail(exc),
            package_path=package_path,
        )

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
        _raise_material_registry_error(
            event="material_registry_package_download_failed",
            exc=exc,
            status_code=403,
            detail=MATERIAL_REGISTRY_ACCESS_DENIED_DETAIL,
            package_path=package_path,
        )
    except FileNotFoundError as exc:
        _raise_material_registry_error(
            event="material_registry_package_download_failed",
            exc=exc,
            status_code=404,
            detail=MATERIAL_REGISTRY_PACKAGE_NOT_FOUND_DETAIL,
            package_path=package_path,
        )
    except ValueError as exc:
        _raise_material_registry_error(
            event="material_registry_package_download_failed",
            exc=exc,
            status_code=422,
            detail=_package_error_detail(exc),
            package_path=package_path,
        )

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
