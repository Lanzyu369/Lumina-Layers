"""Public converter and material/LUT route contracts."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from api.routers.converter import router as converter_router
from api.routers.extractor import router as extractor_router


def _router_openapi_paths(router: APIRouter) -> set[str]:
    """Return mounted paths without depending on FastAPI route internals."""
    probe_app = FastAPI()
    probe_app.include_router(router)
    return set(probe_app.openapi()["paths"])


def test_converter_router_prefix_and_key_paths() -> None:
    """Converter package router should preserve external route contract."""
    assert converter_router.prefix == "/api/convert"
    paths = _router_openapi_paths(converter_router)
    assert "/api/convert/preview" in paths
    assert "/api/convert/generate" in paths
    assert "/api/convert/batch" in paths
    assert "/api/convert/replace-color" in paths
    assert "/api/convert/cleanup-session-files" in paths


def test_extractor_router_prefix_and_key_paths() -> None:
    """Extractor router should preserve external route contract."""
    assert extractor_router.prefix == "/api/extractor"
    paths = {route.path for route in extractor_router.routes}
    assert "/api/extractor/extract" in paths
    assert "/api/extractor/manual-fix" in paths
    assert "/api/extractor/merge-5color-extended" in paths
    assert "/api/extractor/merge-8color" in paths
    assert "/api/extractor/confirm-palette" in paths


def test_converter_and_material_lut_paths_mounted_in_main_app() -> None:
    """Converter and Material/LUT paths stay mounted in the main app.
    转换器与耗材/LUT 路径均挂载在主应用。
    """
    from api.app import app

    paths = set(app.openapi()["paths"])
    assert "/api/convert/preview" in paths
    assert "/api/convert/generate" in paths
    assert "/api/convert/replace-color" in paths
    # These routes are part of the local development baseline, even if the
    # team also keeps a separate hosted material/LUT service for shared use.
    # 这些路由属于本地开发基线；即使团队另有共享耗材/LUT 服务，也不能从主应用移除。
    assert any(p.startswith("/api/extractor/") for p in paths)
    assert any(p.startswith("/api/calibration/") for p in paths)
    assert any(p.startswith("/api/five-color/") for p in paths)
    assert "/api/extractor/gradient-card-materials" in paths
    assert "/api/extractor/material-solver-cache/status" in paths
