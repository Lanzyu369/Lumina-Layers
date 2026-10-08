"""Public Lumina Box material-acquisition routes.
正式 Lumina Box 耗材采集接口。
"""
from fastapi import APIRouter

from api.routers.backed_gradient import router as backed_gradient_router


router = APIRouter(prefix="/api/extractor", tags=["Lumina Box"])
router.include_router(backed_gradient_router)
