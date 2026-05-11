"""Converter router package."""

from fastapi import APIRouter

from .preview import router as preview_router
from .generate import router as generate_router
from .gradient_groups import router as gradient_groups_router
from .puzzle import router as puzzle_router
from .replace import router as replace_router
from .cleanup import router as cleanup_router
from .color_card import router as color_card_router

router = APIRouter(prefix="/api/convert", tags=["Converter"])
router.include_router(preview_router)
router.include_router(generate_router)
router.include_router(gradient_groups_router)
router.include_router(puzzle_router)
router.include_router(replace_router)
router.include_router(cleanup_router)
router.include_router(color_card_router)

__all__ = ["router"]
