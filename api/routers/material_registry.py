"""Read-only material Registry API routes.
只读耗材 Registry API 路由。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse

from api.schemas.responses import MaterialRegistryCatalogResponse
from api.structured_logging import get_logger
from core.material_registry import (
    build_material_registry_catalog,
    material_registry_package_channels,
    normalize_material_registry_channels,
    resolve_material_registry_package_path,
    verify_material_registry_read_access,
)

router = APIRouter(prefix="/api/material-registry/v1", tags=["Material Registry"])
log = get_logger(__name__)


@router.get("/materials/catalog", response_model=MaterialRegistryCatalogResponse)
async def material_registry_catalog(
    channel: Annotated[list[str] | None, Query()] = None,
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
        catalog = build_material_registry_catalog(channels=channels)
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
        },
    )
    return MaterialRegistryCatalogResponse(**catalog)


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
