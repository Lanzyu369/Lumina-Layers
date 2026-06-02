"""Structure contract tests for converter refactor stability."""

from __future__ import annotations

from pathlib import Path

from api.routers.converter import router as converter_router
from api.routers.extractor import router as extractor_router


def test_converter_router_prefix_and_key_paths() -> None:
    """Converter package router should preserve external route contract."""
    assert converter_router.prefix == "/api/convert"
    paths = {route.path for route in converter_router.routes}
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

    paths = {route.path for route in app.routes}
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


def test_converter_router_package_layout_present() -> None:
    """Monolith file should be removed and package layout should exist."""
    root = Path(__file__).resolve().parents[1]
    assert not (root / "api" / "routers" / "converter.py").exists()
    assert (root / "api" / "routers" / "converter" / "__init__.py").exists()
    assert (root / "api" / "routers" / "converter" / "preview.py").exists()
    assert (root / "api" / "routers" / "converter" / "generate.py").exists()
    assert (root / "api" / "routers" / "converter" / "replace.py").exists()
    assert (root / "api" / "routers" / "converter" / "cleanup.py").exists()


def test_no_legacy_frontend_converter_store_imports() -> None:
    """Frontend should no longer import legacy converterStore.ts path."""
    root = Path(__file__).resolve().parents[1]
    frontend_src = root / "frontend" / "src"
    for path in frontend_src.rglob("*.ts*"):
        text = path.read_text(encoding="utf-8")
        assert "stores/converterStore" not in text


def test_no_legacy_converter_patch_paths_in_tests() -> None:
    """Test patches should target converter submodules, not monolith symbols."""
    root = Path(__file__).resolve().parents[1]
    tests_dir = root / "tests"
    legacy_markers = (
        "api.routers.converter.LUTManager",
        "api.routers.converter.ensure_png_tempfile",
        "api.routers.converter.upload_to_tempfile",
        "api.routers.converter.generate_segmented_glb",
        "api.routers.converter.convert_preview",
        "api.routers.converter.convert_generate",
    )
    this_file = Path(__file__).resolve()
    for path in tests_dir.rglob("test_*.py"):
        if path.resolve() == this_file:
            continue
        text = path.read_text(encoding="utf-8")
        for marker in legacy_markers:
            assert marker not in text
