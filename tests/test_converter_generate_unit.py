"""Unit tests for Converter Generate endpoint integration.
Converter Generate 端点集成单元测试。

Validates:
- Generate endpoint offloads CPU work to worker pool (Requirement 1.2, 2.1)
- Worker receives only file paths and scalar params dict (Requirement 2.4)
- Session not found returns 404
- No preview_cache returns 409
- Missing image_path returns 409
- asyncio.TimeoutError → HTTP 504
- General Exception → HTTP 500
"""

from __future__ import annotations

import asyncio
import json
import os
import pickle
import tempfile
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest

from api.app import app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.routers.converter.generate import _generate_large_format_raster
from api.routers.converter.generate import _resolve_recipe_overrides
from api.routers.converter.generate import _resolve_large_format_source_basename
from api.schemas.converter import ConvertGenerateRequest, LargeFormatConvertGenerateRequest, ModelingMode
from api.schemas.system import UserSettings
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from config import ModelingMode as CoreModelingMode

_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()
_mock_pool: MagicMock = MagicMock(spec=WorkerPoolManager)

def setup_module(module):
    """Re-apply dependency overrides before this module's tests run.
    在本模块测试运行前重新设置依赖覆盖，确保跨文件测试隔离。
    """
    app.dependency_overrides[get_session_store] = lambda: _test_store
    app.dependency_overrides[get_file_registry] = lambda: _test_registry
    app.dependency_overrides[get_worker_pool] = lambda: _mock_pool


def teardown_module(module):
    """Remove this module's dependency overrides after all tests complete.
    本模块所有测试完成后移除依赖覆盖。
    """
    app.dependency_overrides.pop(get_session_store, None)
    app.dependency_overrides.pop(get_file_registry, None)
    app.dependency_overrides.pop(get_worker_pool, None)


# Apply overrides immediately for module-level client creation
setup_module(None)


client: TestClient = TestClient(app)


def _create_session_with_preview_and_files(store: SessionStore) -> str:
    """Create a session pre-populated with preview_cache and file paths."""
    sid: str = store.create()
    store.put(
        sid,
        "preview_cache",
        {
            "some": "data",
            "target_w": 120,
            "target_h": 80,
            "target_width_mm": 60.0,
        },
    )
    store.put(sid, "image_path", "/tmp/test_image.png")
    store.put(sid, "source_basename", "test-image")
    store.put(sid, "lut_path", "/tmp/test_lut.npy")
    store.put(sid, "replacement_regions", [])
    store.put(sid, "free_color_set", set())
    return sid


def _create_svg_session(
    store: SessionStore,
    *,
    native_tiling_supported: bool,
    warnings: list[str] | None = None,
) -> tuple[str, str, str]:
    """Create a session for SVG large-format tests with real temp files."""
    fd_svg, svg_path = tempfile.mkstemp(suffix=".svg")
    fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
    try:
        with open(fd_svg, "w", encoding="utf-8", closefd=False) as svg_file:
            svg_file.write(
                '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">'
                '<rect x="0" y="0" width="120" height="80" fill="#ff0000"/>'
                "</svg>"
            )
        with open(fd_lut, "wb", closefd=False) as lut_file:
            lut_file.write(b"lut")
    finally:
        import os

        os.close(fd_svg)
        os.close(fd_lut)

    sid = store.create()
    store.put(
        sid,
        "preview_cache",
        {
            "target_w": 120,
            "target_h": 80,
            "target_width_mm": 60.0,
        },
    )
    store.put(sid, "image_path", svg_path)
    store.put(sid, "source_basename", "source-artwork")
    store.put(sid, "lut_path", lut_path)
    store.put(sid, "replacement_regions", [])
    store.put(sid, "free_color_set", set())
    store.put(
        sid,
        "svg_large_format_policy",
        {
            "native_tiling_supported": native_tiling_supported,
            "warnings": list(warnings or []),
            "inspection_source": "preview-vector-svg",
        },
    )
    return sid, svg_path, lut_path


def _create_raster_large_format_session(store: SessionStore) -> tuple[str, str, str]:
    """Create a PNG-backed session for large-format route tests."""
    fd_img, image_path = tempfile.mkstemp(suffix=".png")
    fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
    try:
        Image.fromarray(np.zeros((20, 20, 3), dtype=np.uint8)).save(image_path)
        with open(lut_path, "wb") as lut_file:
            lut_file.write(b"lut")
    finally:
        os.close(fd_img)
        os.close(fd_lut)

    sid = store.create()
    store.put(
        sid,
        "preview_cache",
        {
            "target_w": 120,
            "target_h": 80,
            "target_width_mm": 60.0,
            "material_matrix": np.zeros((4, 4, 5), dtype=np.uint8),
            "lut_metadata": SimpleNamespace(layer_order="Top2Bottom", base_channel_idx=0),
        },
    )
    store.put(sid, "image_path", image_path)
    store.put(sid, "source_basename", "poster")
    store.put(sid, "lut_path", lut_path)
    store.put(sid, "replacement_regions", [])
    store.put(sid, "free_color_set", set())
    store.put(
        sid,
        "selected_region_masks",
        {"region-1": np.ones((4, 4), dtype=bool)},
    )
    store.put(
        sid,
        "recipe_overrides",
        [{"region_id": "region-1", "recipe": [1, 1, 1, 1, 1], "layer_order": "Top2Bottom"}],
    )
    return sid, image_path, lut_path


# =========================================================================
# 1. Session not found returns 404
# =========================================================================


class TestGenerateSessionNotFound:
    """Verify unknown session_id returns HTTP 404."""

    def test_generate_unknown_session_returns_404(self) -> None:
        payload = {
            "session_id": "nonexistent-session-id",
            "params": {"lut_name": "test_lut"},
        }
        response = client.post("/api/convert/generate", json=payload)
        assert response.status_code == 404
        assert "Session" in response.json()["detail"]


# =========================================================================
# 2. No preview_cache returns 409
# =========================================================================


class TestGenerateNoPreviewCache:
    """Verify missing preview_cache returns HTTP 409."""

    def test_generate_no_preview_cache_returns_409(self) -> None:
        sid: str = _test_store.create()
        payload = {
            "session_id": sid,
            "params": {"lut_name": "test_lut"},
        }
        response = client.post("/api/convert/generate", json=payload)
        assert response.status_code == 409
        assert "preview" in response.json()["detail"].lower()


# =========================================================================
# 3. Missing image_path returns 409
# =========================================================================


class TestGenerateMissingImagePath:
    """Verify missing or non-existent image_path returns HTTP 409."""

    def test_generate_missing_image_path_returns_409(self) -> None:
        sid: str = _test_store.create()
        _test_store.put(sid, "preview_cache", {"some": "data"})
        payload = {
            "session_id": sid,
            "params": {"lut_name": "test_lut"},
        }
        response = client.post("/api/convert/generate", json=payload)
        assert response.status_code == 409
        assert "Image file missing" in response.json()["detail"]

    def test_generate_nonexistent_image_file_returns_409(self) -> None:
        sid: str = _test_store.create()
        _test_store.put(sid, "preview_cache", {"some": "data"})
        _test_store.put(sid, "image_path", "/tmp/does_not_exist_12345.png")
        _test_store.put(sid, "lut_path", "/tmp/test_lut.npy")
        payload = {
            "session_id": sid,
            "params": {"lut_name": "test_lut"},
        }
        response = client.post("/api/convert/generate", json=payload)
        assert response.status_code == 409


# =========================================================================
# 4. Parameter completeness via worker pool - Requirement 1.2, 2.1, 2.4
# =========================================================================


class TestGenerateParameterCompleteness:
    """Verify all parameters are correctly collected and passed to worker_generate_model via pool.submit."""

    def test_generate_passes_all_advanced_params(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)
        expected_fridge_magnets = [
            {
                "id": "magnet-round",
                "shape": "round",
                "preset_key": "round-18",
                "diameter_mm": 18.0,
                "width_mm": None,
                "height_mm": None,
                "thickness_mm": 2.0,
                "center_x_mm": 20.0,
                "center_y_mm": 25.0,
            },
            {
                "id": "magnet-rect",
                "shape": "rect",
                "preset_key": "rect-20x10",
                "diameter_mm": None,
                "width_mm": 20.0,
                "height_mm": 10.0,
                "thickness_mm": 2.5,
                "center_x_mm": 40.0,
                "center_y_mm": 15.0,
            },
        ]

        payload = {
            "session_id": sid,
            "params": {
                "lut_name": "test_lut",
                "target_width_mm": 80.0,
                "spacer_thick": 1.5,
                "structure_mode": "Single-sided",
                "auto_bg": True,
                "bg_tol": 60,
                "color_mode": "4-Color (RYBW)",
                "modeling_mode": "high-fidelity",
                "model_enable": True,
                "model_only": False,
                "model_threshold": 6.5,
                "model_margin": 0.9,
                "quantize_colors": 64,
                "enable_cleanup": False,
                "separate_backing": True,
                "add_loop": True,
                "loop_width": 5.0,
                "loop_length": 10.0,
                "loop_hole": 3.0,
                "loop_pos": [50.0, 50.0],
                "enable_fridge_magnet": True,
                "fridge_magnets": expected_fridge_magnets,
                "enable_relief": True,
                "color_height_map": {"#ff0000": 2.0},
                "heightmap_max_height": 8.0,
                "enable_outline": True,
                "outline_width": 3.0,
                "enable_cloisonne": True,
                "wire_width_mm": 0.6,
                "wire_height_mm": 0.5,
                "enable_coating": True,
                "coating_height_mm": 0.1,
                "printer_id": "orca-p1s",
                "slicer": "OrcaSlicer",
                "nozzle_size": "0.2",
            },
        }

        # Mock pool.submit to return worker-style dict result
        worker_result = {
            "threemf_path": "/tmp/out.3mf",
            "glb_path": "/tmp/out.glb",
            "status_msg": "OK",
        }
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with patch("os.path.exists", return_value=True):
            response = client.post("/api/convert/generate", json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["download_url"].startswith("/api/files/")
        assert body["preview_3d_url"].startswith("/api/files/")

        # Verify pool.submit was called exactly once
        _mock_pool.submit.assert_called_once()

        # Extract positional args: (worker_fn, image_path, lut_path, params_dict)
        call_args = _mock_pool.submit.call_args
        worker_fn = call_args.args[0]
        submitted_image_path = call_args.args[1]
        submitted_lut_path = call_args.args[2]
        submitted_params = call_args.args[3]

        # Verify worker function identity
        from api.workers.converter_workers import worker_generate_model
        assert worker_fn is worker_generate_model

        # Verify file paths from session
        assert submitted_image_path == "/tmp/test_image.png"
        assert submitted_lut_path == "/tmp/test_lut.npy"

        # Verify params dict contains all scalar parameters
        assert submitted_params["target_width_mm"] == 80.0
        assert submitted_params["spacer_thick"] == 1.5
        assert submitted_params["structure_mode"] == "Single-sided"
        assert submitted_params["auto_bg"] is True
        assert submitted_params["bg_tol"] == 60
        assert submitted_params["color_mode"] == "4-Color (RYBW)"
        assert submitted_params["model_enable"] is True
        assert submitted_params["model_only"] is False
        assert submitted_params["model_threshold"] == 6.5
        assert submitted_params["model_margin"] == 0.9
        assert submitted_params["quantize_colors"] == 64
        assert submitted_params["enable_cleanup"] is False
        assert submitted_params["separate_backing"] is True
        assert submitted_params["nozzle_size"] == "0.2"

        # Verify modeling_mode is converted to core enum
        assert submitted_params["modeling_mode"] == CoreModelingMode("high-fidelity")

        # Verify keychain loop parameters
        assert submitted_params["add_loop"] is True
        assert submitted_params["loop_width"] == 5.0
        assert submitted_params["loop_length"] == 10.0
        assert submitted_params["loop_hole"] == 3.0
        assert submitted_params["loop_pos"] == (50.0, 50.0)
        assert submitted_params["enable_fridge_magnet"] is True
        assert submitted_params["fridge_magnets"] == expected_fridge_magnets

        # Verify relief parameters
        assert submitted_params["enable_relief"] is True
        assert submitted_params["color_height_map"] == {"#ff0000": 2.0}
        assert submitted_params["heightmap_max_height"] == 8.0

        # Verify outline parameters
        assert submitted_params["enable_outline"] is True
        assert submitted_params["outline_width"] == 3.0

        # Verify cloisonne parameters
        assert submitted_params["enable_cloisonne"] is True
        assert submitted_params["wire_width_mm"] == 0.6
        assert submitted_params["wire_height_mm"] == 0.5

        # Verify coating parameters
        assert submitted_params["enable_coating"] is True
        assert submitted_params["coating_height_mm"] == 0.1

        # Verify session-derived parameters (empty → None)
        assert submitted_params["replacement_regions"] is None
        assert submitted_params["free_color_set"] is None
        assert submitted_params["enable_base_layer_height_modifier"] is True

    def test_generate_passes_replacement_regions_from_request(self) -> None:
        """Verify replacement_regions from request body override session data."""
        sid: str = _create_session_with_preview_and_files(_test_store)

        payload = {
            "session_id": sid,
            "params": {
                "lut_name": "test_lut",
                "replacement_regions": [
                    {
                        "quantized_hex": "#ff0000",
                        "matched_hex": "#ee0000",
                        "replacement_hex": "#00ff00",
                    }
                ],
            },
        }

        worker_result = {
            "threemf_path": "/tmp/out.3mf",
            "glb_path": "/tmp/out.glb",
            "status_msg": "OK",
        }
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with patch("os.path.exists", return_value=True):
            response = client.post("/api/convert/generate", json=payload)

        assert response.status_code == 200
        submitted_params = _mock_pool.submit.call_args.args[3]
        regions = submitted_params["replacement_regions"]
        assert len(regions) == 1
        assert regions[0]["quantized_hex"] == "#ff0000"
        assert regions[0]["matched_hex"] == "#ee0000"
        assert regions[0]["replacement_hex"] == "#00ff00"

    def test_generate_passes_enable_base_layer_modifier_false(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)

        payload = {
            "session_id": sid,
            "params": {
                "lut_name": "test_lut",
                "enable_base_layer_height_modifier": False,
            },
        }

        worker_result = {
            "threemf_path": "/tmp/out.3mf",
            "glb_path": "/tmp/out.glb",
            "status_msg": "OK",
        }
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with patch("os.path.exists", return_value=True):
            response = client.post("/api/convert/generate", json=payload)

        assert response.status_code == 200
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["enable_base_layer_height_modifier"] is False

    def test_generate_defaults_enable_base_layer_modifier_true_when_field_missing(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)

        payload = {
            "session_id": sid,
            "params": {
                "lut_name": "test_lut",
            },
        }

        worker_result = {
            "threemf_path": "/tmp/out.3mf",
            "glb_path": "/tmp/out.glb",
            "status_msg": "OK",
        }
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with patch("os.path.exists", return_value=True):
            response = client.post("/api/convert/generate", json=payload)

        assert response.status_code == 200
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["enable_base_layer_height_modifier"] is True


# =========================================================================
# 5. Timeout → HTTP 504 - Requirement 2.3
# =========================================================================


class TestGenerateTimeout:
    """Verify asyncio.TimeoutError from pool.submit returns HTTP 504."""

    def test_generate_timeout_returns_504(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)

        payload = {
            "session_id": sid,
            "params": {"lut_name": "test_lut"},
        }

        _mock_pool.submit = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("os.path.exists", return_value=True):
            response = client.post("/api/convert/generate", json=payload)

        assert response.status_code == 504
        assert "timed out" in response.json()["detail"].lower()


# =========================================================================
# 6. Worker exception → HTTP 500 - Requirement 1.4
# =========================================================================


class TestGenerateWorkerException:
    """Verify general Exception from pool.submit returns HTTP 500."""

    def test_generate_worker_exception_returns_500(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)

        payload = {
            "session_id": sid,
            "params": {"lut_name": "test_lut"},
        }

        _mock_pool.submit = AsyncMock(side_effect=RuntimeError("Worker crashed"))

        with patch("os.path.exists", return_value=True):
            response = client.post("/api/convert/generate", json=payload)

        assert response.status_code == 500
        assert "Worker crashed" in response.json()["detail"]


class TestLargeFormatFridgeMagnetValidation:
    """Verify unsupported fridge-magnet combinations fail deterministically."""

    def test_large_format_rejects_fridge_magnet_mode(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 80.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "enable_fridge_magnet": True,
                    "fridge_magnets": [
                        {
                            "id": "magnet-round",
                            "shape": "round",
                            "preset_key": "round-18",
                            "diameter_mm": 18.0,
                            "width_mm": None,
                            "height_mm": None,
                            "thickness_mm": 2.0,
                            "center_x_mm": 0.0,
                            "center_y_mm": 0.0,
                        }
                    ],
                },
            },
        }

        response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 422
        assert "fridge magnet" in response.json()["detail"].lower()


class TestLargeFormatDimensionsAndRouting:
    """Verify large-format ratio resolution and SVG routing behavior."""

    def test_large_format_source_basename_falls_back_to_image_path_when_session_value_missing(self) -> None:
        resolved = _resolve_large_format_source_basename({}, "/tmp/tmpabcd1234_poster-art.png")

        assert resolved == "poster-art"

    def test_large_format_source_basename_re_normalizes_unsafe_session_value(self) -> None:
        resolved = _resolve_large_format_source_basename(
            {"source_basename": " bad:name* "},
            "/tmp/ignored.png",
        )

        assert resolved == "bad_name"

    def test_large_format_svg_width_only_derives_height_and_uses_native_path(self) -> None:
        sid, svg_path, lut_path = _create_svg_session(_test_store, native_tiling_supported=True)

        payload = {
            "session_id": sid,
            "params": {
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                },
            },
        }

        native_response = {
            "status": "ok",
            "message": "native",
            "download_url": "/api/files/native",
            "tile_count": 4,
            "grid_cols": 2,
            "grid_rows": 2,
            "warnings": [],
        }

        with (
            patch("api.routers.converter.generate.Image.open", side_effect=AssertionError("raster path should not open SVG")),
            patch("api.routers.converter.generate._generate_large_format_svg_native", return_value=native_response) as native_helper,
        ):
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 200
        assert response.json()["warnings"] == []
        native_helper.assert_called_once()
        assert native_helper.call_args.kwargs["image_path"] == svg_path
        assert native_helper.call_args.kwargs["lut_path"] == lut_path
        assert native_helper.call_args.kwargs["source_basename"] == "source-artwork"
        assert native_helper.call_args.kwargs["total_width_mm"] == 90.0
        assert native_helper.call_args.kwargs["total_height_mm"] == 60.0

    def test_large_format_svg_height_only_derives_width(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=True)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 100.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                },
            },
        }

        native_response = {
            "status": "ok",
            "message": "native",
            "download_url": "/api/files/native",
            "tile_count": 6,
            "grid_cols": 3,
            "grid_rows": 2,
            "warnings": [],
        }

        with patch(
            "api.routers.converter.generate._generate_large_format_svg_native",
            return_value=native_response,
        ) as native_helper:
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 200
        assert native_helper.call_args.kwargs["source_basename"] == "source-artwork"
        assert native_helper.call_args.kwargs["total_width_mm"] == 150.0
        assert native_helper.call_args.kwargs["total_height_mm"] == 100.0

    def test_large_format_rejects_missing_both_dimensions(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=True)

        payload = {
            "session_id": sid,
            "params": {
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                },
            },
        }

        response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 422
        assert "width" in response.json()["detail"].lower()
        assert "height" in response.json()["detail"].lower()

    def test_large_format_rejects_dimensions_inconsistent_with_preview_ratio(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=True)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 90.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 100.0,
                },
            },
        }

        with patch("api.routers.converter.generate._generate_large_format_svg_native") as native_helper:
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 422
        assert "aspect ratio" in response.json()["detail"].lower()
        native_helper.assert_not_called()

    def test_large_format_svg_unsupported_falls_back_to_raster_with_warning(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=False,
            warnings=["Native vector large-format is unavailable because the SVG uses text elements."],
        )

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                },
            },
        }

        fallback_response = {
            "status": "ok",
            "message": "fallback",
            "download_url": "/api/files/raster",
            "tile_count": 4,
            "grid_cols": 2,
            "grid_rows": 2,
            "warnings": [
                "Native vector large-format is unavailable because the SVG uses text elements.",
                "Raster fallback was used for this large-format SVG request.",
            ],
        }

        with (
            patch(
                "api.routers.converter.generate._generate_large_format_svg_native",
            ) as native_helper,
            patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=fallback_response,
            ) as raster_helper,
        ):
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 200
        body = response.json()
        assert native_helper.call_count == 0
        raster_helper.assert_called_once()
        assert raster_helper.call_args.kwargs["source_basename"] == "source-artwork"
        assert any("raster fallback" in warning.lower() for warning in body["warnings"])

    def test_large_format_route_passes_recipe_override_artifacts_to_raster_helper(self) -> None:
        sid, image_path, lut_path = _create_raster_large_format_session(_test_store)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "high-fidelity",
                    "target_width_mm": 90.0,
                    "recipe_overrides": [
                        {
                            "region_id": "region-1",
                            "recipe": [1, 1, 1, 1, 1],
                            "layer_order": "Top2Bottom",
                        }
                    ],
                },
            },
        }

        raster_response = {
            "status": "ok",
            "message": "raster",
            "download_url": "/api/files/raster",
            "tile_count": 4,
            "grid_cols": 2,
            "grid_rows": 2,
            "warnings": [],
        }

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=raster_response,
            ) as raster_helper:
                response = client.post("/api/convert/generate-large-format", json=payload)

            assert response.status_code == 200
            raster_helper.assert_called_once()
            kwargs = raster_helper.call_args.kwargs
            assert kwargs["image_path"] == image_path
            assert kwargs["lut_path"] == lut_path
            assert kwargs["recipe_overrides"] == [
                {
                    "region_id": "region-1",
                    "recipe": [1, 1, 1, 1, 1],
                    "layer_order": "Top2Bottom",
                }
            ]
            assert kwargs["material_matrix_path"] is not None
            assert os.path.exists(kwargs["material_matrix_path"])
            assert kwargs["recipe_override_masks_path"] is not None
            assert os.path.exists(kwargs["recipe_override_masks_path"])
        finally:
            _test_store.clear_all()

    def test_large_format_svg_with_recipe_overrides_uses_raster_path_even_when_native_supported(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=True)
        session_data = _test_store.get(sid)
        assert session_data is not None
        session_data["preview_cache"]["material_matrix"] = np.zeros((4, 4, 5), dtype=np.uint8)
        session_data["preview_cache"]["lut_metadata"] = SimpleNamespace(layer_order="Top2Bottom", base_channel_idx=0)
        session_data["selected_region_masks"] = {"region-1": np.ones((4, 4), dtype=bool)}

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                    "recipe_overrides": [
                        {
                            "region_id": "region-1",
                            "recipe": [1, 1, 1, 1, 1],
                            "layer_order": "Top2Bottom",
                        }
                    ],
                },
            },
        }

        raster_response = {
            "status": "ok",
            "message": "raster",
            "download_url": "/api/files/raster",
            "tile_count": 4,
            "grid_cols": 2,
            "grid_rows": 2,
            "warnings": ["Raster fallback was used for this large-format SVG request."],
        }

        with (
            patch("api.routers.converter.generate._generate_large_format_svg_native") as native_helper,
            patch("api.routers.converter.generate._generate_large_format_raster", return_value=raster_response) as raster_helper,
        ):
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 200
        native_helper.assert_not_called()
        raster_helper.assert_called_once()
        assert any("raster fallback" in warning.lower() for warning in response.json()["warnings"])

    def test_large_format_reinspects_unmarked_svg_policy_before_using_native_path(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=True)
        session_data = _test_store.get(sid)
        assert session_data is not None
        session_data["svg_large_format_policy"] = {
            "native_tiling_supported": True,
            "warnings": [],
            "unsupported_features": [],
        }

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                },
            },
        }

        fallback_response = {
            "status": "ok",
            "message": "fallback",
            "download_url": "/api/files/raster",
            "tile_count": 4,
            "grid_cols": 2,
            "grid_rows": 2,
            "warnings": [
                "Native vector large-format is unavailable for this SVG; large-format generation will fall back to raster tiling. Unsupported features: text.",
                "Raster fallback was used for this large-format SVG request.",
            ],
        }

        with (
            patch(
                "api.routers.converter.generate.inspect_svg_large_format_support",
                return_value={
                    "native_tiling_supported": False,
                    "warnings": [
                        "Native vector large-format is unavailable for this SVG; large-format generation will fall back to raster tiling. Unsupported features: text."
                    ],
                    "unsupported_features": ["text"],
                },
            ) as inspect_helper,
            patch(
                "api.routers.converter.generate._generate_large_format_svg_native",
            ) as native_helper,
            patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=fallback_response,
            ) as raster_helper,
        ):
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 200
        inspect_helper.assert_called_once()
        native_helper.assert_not_called()
        raster_helper.assert_called_once()
        assert raster_helper.call_args.kwargs["source_basename"] == "source-artwork"
        updated_policy = _test_store.get(sid)["svg_large_format_policy"]
        assert updated_policy["inspection_source"] == "generate-large-format"
        assert updated_policy["native_tiling_supported"] is False

    def test_large_format_reuses_preview_svg_policy_without_reinspection(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=True)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                },
            },
        }

        native_response = {
            "status": "ok",
            "message": "native",
            "download_url": "/api/files/native",
            "tile_count": 4,
            "grid_cols": 2,
            "grid_rows": 2,
            "warnings": [],
        }

        with (
            patch(
                "api.routers.converter.generate.inspect_svg_large_format_support",
                side_effect=AssertionError("stored preview policy should be reused"),
            ),
            patch(
                "api.routers.converter.generate._generate_large_format_svg_native",
                return_value=native_response,
            ) as native_helper,
        ):
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 200
        native_helper.assert_called_once()

    def test_large_format_svg_native_timeout_returns_504(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=True)
        _mock_pool.submit = AsyncMock(side_effect=asyncio.TimeoutError())

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                },
            },
        }

        response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 504
        assert "timed out" in response.json()["detail"].lower()

    def test_large_format_svg_native_worker_error_returns_500(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=True)
        _mock_pool.submit = AsyncMock(side_effect=ValueError("tile analysis failed"))

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                },
            },
        }

        response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 500
        assert "large-format svg generation failed" in response.json()["detail"].lower()
        assert "tile analysis failed" in response.json()["detail"].lower()

    def test_large_format_raster_helper_writes_sanitized_zip_entry_names(self) -> None:
        fd_img, image_path = tempfile.mkstemp(suffix=".png")
        os.close(fd_img)
        fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
        os.close(fd_lut)
        fd_3mf, threemf_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_3mf)

        Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8)).save(image_path)
        with open(lut_path, "wb") as lut_file:
            lut_file.write(b"lut")
        with open(threemf_path, "wb") as threemf_file:
            threemf_file.write(b"3mf")

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        sid = store.create()
        mock_pool = MagicMock(spec=WorkerPoolManager)
        mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": threemf_path,
                "status_msg": "ok",
            }
        )
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )

        try:
            result = asyncio.run(
                _generate_large_format_raster(
                    image_path=image_path,
                    lut_path=lut_path,
                    source_basename=" bad:name* ",
                    recipe_overrides=None,
                    recipe_override_masks_path=None,
                    material_matrix_path=None,
                    total_width_mm=40.0,
                    total_height_mm=40.0,
                    tile_width_mm=40.0,
                    tile_height_mm=40.0,
                    request=request,
                    session_data={},
                    sid=sid,
                    store=store,
                    registry=registry,
                    pool=mock_pool,
                )
            )

            download_id = result["download_url"].rsplit("/", 1)[-1]
            zip_path, _filename = registry.resolve(download_id)
            with zipfile.ZipFile(zip_path, "r") as archive:
                assert archive.namelist() == ["bad_name_R1C1.3mf"]
        finally:
            store.clear_all()
            for path in (image_path, lut_path, threemf_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_raster_helper_slices_recipe_override_artifacts_per_tile(self) -> None:
        fd_img, image_path = tempfile.mkstemp(suffix=".png")
        os.close(fd_img)
        fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
        os.close(fd_lut)
        fd_mm, material_matrix_path = tempfile.mkstemp(suffix=".npy")
        os.close(fd_mm)
        fd_masks, recipe_override_masks_path = tempfile.mkstemp(suffix=".pkl")
        os.close(fd_masks)
        fd_3mf, threemf_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_3mf)

        Image.fromarray(np.zeros((20, 20, 3), dtype=np.uint8)).save(image_path)
        with open(lut_path, "wb") as lut_file:
            lut_file.write(b"lut")
        np.save(material_matrix_path, np.zeros((4, 8, 5), dtype=np.uint8))
        with open(recipe_override_masks_path, "wb") as mask_file:
            pickle.dump({"region-1": np.ones((4, 8), dtype=bool)}, mask_file)
        with open(threemf_path, "wb") as threemf_file:
            threemf_file.write(b"3mf")

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        sid = store.create()
        store.put(sid, "preview_cache", {"target_w": 8, "target_h": 4})
        store.put(sid, "heightmap_grayscale", np.arange(20 * 20, dtype=np.uint8).reshape(20, 20))
        mock_pool = MagicMock(spec=WorkerPoolManager)
        captured_paths: list[str] = []
        captured_shapes: dict[str, tuple[int, ...]] = {}

        async def _mock_submit(_fn, _tile_path, _lut_path, tile_params):
            matrix_path = tile_params["material_matrix_path"]
            masks_path = tile_params["recipe_override_masks_path"]
            heightmap_path = tile_params["heightmap_path"]
            captured_paths.extend(
                [
                    _tile_path,
                    heightmap_path,
                    matrix_path,
                    masks_path,
                ]
            )
            captured_shapes["matrix"] = tuple(np.load(matrix_path).shape)
            with open(masks_path, "rb") as mask_file:
                sliced_masks = pickle.load(mask_file)
            captured_shapes["mask"] = tuple(sliced_masks["region-1"].shape)
            with Image.open(heightmap_path) as hm_img:
                captured_shapes["heightmap"] = hm_img.size
            with Image.open(_tile_path) as tile_img:
                captured_shapes["tile"] = tile_img.size
            return {
                "threemf_path": threemf_path,
                "status_msg": "ok",
            }

        mock_pool.submit = AsyncMock(side_effect=_mock_submit)
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
            enable_relief=True,
            height_mode="heightmap",
        )

        try:
            result = asyncio.run(
                _generate_large_format_raster(
                    image_path=image_path,
                    lut_path=lut_path,
                    source_basename="poster",
                    recipe_overrides=[
                        {
                            "region_id": "region-1",
                            "recipe": [1, 1, 1, 1, 1],
                            "layer_order": "Top2Bottom",
                        }
                    ],
                    recipe_override_masks_path=recipe_override_masks_path,
                    material_matrix_path=material_matrix_path,
                    total_width_mm=80.0,
                    total_height_mm=40.0,
                    tile_width_mm=40.0,
                    tile_height_mm=40.0,
                    request=request,
                    session_data={
                        "preview_cache": {"target_w": 8, "target_h": 4},
                        "heightmap_grayscale": np.arange(20 * 20, dtype=np.uint8).reshape(20, 20),
                    },
                    sid=sid,
                    store=store,
                    registry=registry,
                    pool=mock_pool,
                )
            )

            download_id = result["download_url"].rsplit("/", 1)[-1]
            zip_path, _filename = registry.resolve(download_id)
            assert os.path.exists(zip_path)
            assert captured_shapes["matrix"] == (4, 4, 5)
            assert captured_shapes["mask"] == (4, 4)
            assert captured_shapes["tile"] == (10, 20)
            assert captured_shapes["heightmap"] == (10, 20)
            assert captured_paths
            assert all(not os.path.exists(path) for path in captured_paths)
            assert set(store.get_temp_file_paths(sid)) == {zip_path}
        finally:
            store.clear_all()
            for path in (image_path, lut_path, material_matrix_path, recipe_override_masks_path, threemf_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_svg_fallback_success_cleans_route_local_png(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=False)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                },
            },
        }

        raster_response = {
            "status": "ok",
            "message": "raster",
            "download_url": "/api/files/raster",
            "tile_count": 4,
            "grid_cols": 2,
            "grid_rows": 2,
            "warnings": ["Raster fallback was used for this large-format SVG request."],
        }
        captured = {"fallback_path": None}

        def _fake_raster_helper(**kwargs):
            captured["fallback_path"] = kwargs["image_path"]
            assert os.path.exists(kwargs["image_path"])
            return raster_response

        with patch(
            "api.routers.converter.generate._generate_large_format_raster",
            side_effect=_fake_raster_helper,
        ):
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 200
        assert captured["fallback_path"] is not None
        assert not os.path.exists(captured["fallback_path"])

    def test_large_format_raster_helper_deletes_tile_3mf_and_glb_after_packaging(self) -> None:
        fd_img, image_path = tempfile.mkstemp(suffix=".png")
        os.close(fd_img)
        fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
        os.close(fd_lut)
        fd_3mf, threemf_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_3mf)
        fd_glb, glb_path = tempfile.mkstemp(suffix=".glb")
        os.close(fd_glb)

        Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8)).save(image_path)
        with open(lut_path, "wb") as lut_file:
            lut_file.write(b"lut")
        with open(threemf_path, "wb") as threemf_file:
            threemf_file.write(b"3mf")
        with open(glb_path, "wb") as glb_file:
            glb_file.write(b"glb")

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        sid = store.create()
        mock_pool = MagicMock(spec=WorkerPoolManager)
        mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": threemf_path,
                "glb_path": glb_path,
                "status_msg": "ok",
            }
        )
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )

        try:
            result = asyncio.run(
                _generate_large_format_raster(
                    image_path=image_path,
                    lut_path=lut_path,
                    source_basename="poster",
                    recipe_overrides=None,
                    recipe_override_masks_path=None,
                    material_matrix_path=None,
                    total_width_mm=40.0,
                    total_height_mm=40.0,
                    tile_width_mm=40.0,
                    tile_height_mm=40.0,
                    request=request,
                    session_data={},
                    sid=sid,
                    store=store,
                    registry=registry,
                    pool=mock_pool,
                )
            )

            download_id = result["download_url"].rsplit("/", 1)[-1]
            zip_path, _filename = registry.resolve(download_id)
            assert os.path.exists(zip_path)
            assert not os.path.exists(threemf_path)
            assert not os.path.exists(glb_path)
        finally:
            store.clear_all()
            for path in (image_path, lut_path, threemf_path, glb_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_raster_helper_cleans_collected_outputs_when_zip_creation_fails(self) -> None:
        fd_img, image_path = tempfile.mkstemp(suffix=".png")
        os.close(fd_img)
        fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
        os.close(fd_lut)
        fd_3mf, threemf_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_3mf)
        fd_glb, glb_path = tempfile.mkstemp(suffix=".glb")
        os.close(fd_glb)

        Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8)).save(image_path)
        with open(lut_path, "wb") as lut_file:
            lut_file.write(b"lut")
        with open(threemf_path, "wb") as threemf_file:
            threemf_file.write(b"3mf")
        with open(glb_path, "wb") as glb_file:
            glb_file.write(b"glb")

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        sid = store.create()
        mock_pool = MagicMock(spec=WorkerPoolManager)
        mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": threemf_path,
                "glb_path": glb_path,
                "status_msg": "ok",
            }
        )
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )

        try:
            with patch("api.routers.converter.generate.zipfile.ZipFile", side_effect=RuntimeError("zip failed")):
                with pytest.raises(RuntimeError, match="zip failed"):
                    asyncio.run(
                        _generate_large_format_raster(
                            image_path=image_path,
                            lut_path=lut_path,
                            source_basename="poster",
                            recipe_overrides=None,
                            recipe_override_masks_path=None,
                            material_matrix_path=None,
                            total_width_mm=40.0,
                            total_height_mm=40.0,
                            tile_width_mm=40.0,
                            tile_height_mm=40.0,
                            request=request,
                            session_data={},
                            sid=sid,
                            store=store,
                            registry=registry,
                            pool=mock_pool,
                        )
                    )

            assert not os.path.exists(threemf_path)
            assert not os.path.exists(glb_path)
        finally:
            store.clear_all()
            for path in (image_path, lut_path, threemf_path, glb_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_rejects_fridge_magnet_flag_even_with_empty_list(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 80.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "enable_fridge_magnet": True,
                    "fridge_magnets": [],
                },
            },
        }

        response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 422
        assert "fridge magnet" in response.json()["detail"].lower()


def test_convert_generate_request_accepts_native_bundle_source() -> None:
    """ConvertGenerateRequest should support native-bundle source selection fields."""

    request = ConvertGenerateRequest(
        source_kind="native_bundle",
        material_type="PLA",
        vendor="BambuLab",
        db_names=["RYBW_008_5L"],
    )

    assert request.source_kind == "native_bundle"
    assert request.material_type == "PLA"
    assert request.vendor == "BambuLab"
    assert request.db_names == ["RYBW_008_5L"]
    assert request.nozzle_size == "0.4"


def test_resolve_recipe_overrides_prefers_explicit_empty_request_over_session_value() -> None:
    request = ConvertGenerateRequest(
        lut_name="test-lut",
        recipe_overrides=[],
    )

    resolved = _resolve_recipe_overrides(
        {"recipe_overrides": [{"region_id": "region-1", "recipe": [1, 1, 1, 1, 1], "layer_order": "Top2Bottom"}]},
        request,
    )

    assert resolved is None


def test_resolve_recipe_overrides_backfills_session_virtual_materials_when_request_omits_them() -> None:
    """Backend safety: session-persisted virtual_materials must survive when the
    request body's recipe_overrides (same region_id) forgets to send them.

    apply 端点会把用户声明的 virtual_materials 随 recipe_overrides 一起持久化
    到 session。前端旧版本 / 第三方调用方可能在 /generate 时只回传
    ``{region_id, recipe, layer_order}``——若 backend 简单用 request 覆盖 session，
    virtual_materials 就整条丢失，worker 无法扩展 ctx["slot_names"]，
    S07 只会给 LUT 原生通道生成 mesh，表现为 3MF 缺少自定义颜色对象、
    该通道像素无网格（看起来像"方块 / 透明失效"）。

    回归保证：当 request 的某个 region_id 没带 virtual_materials、session
    同一 region_id 有持久化的 virtuals 时，resolver 必须把它们合并回来。
    """
    session_data = {
        "recipe_overrides": [
            {
                "region_id": "region-1",
                "recipe": [4, 0, 0, 0, 0, 4],
                "layer_order": "Top2Bottom",
                "virtual_materials": [{"name": "Black", "hex": "#111111"}],
            }
        ]
    }
    request = ConvertGenerateRequest(
        lut_name="test-lut",
        recipe_overrides=[
            {
                "region_id": "region-1",
                "recipe": [4, 0, 0, 0, 0, 4],
                "layer_order": "Top2Bottom",
                # Intentionally no ``virtual_materials`` — old-client scenario.
            }
        ],
    )

    resolved = _resolve_recipe_overrides(session_data, request)

    assert resolved is not None
    assert len(resolved) == 1
    assert resolved[0]["region_id"] == "region-1"
    assert resolved[0]["recipe"] == [4, 0, 0, 0, 0, 4]
    assert resolved[0]["virtual_materials"] == [
        {"name": "Black", "hex": "#111111"}
    ]


def test_resolve_recipe_overrides_prefers_request_virtual_materials_when_provided() -> None:
    """When both request and session carry virtuals for the same region, request wins.

    新前端会在 apply 后把 virtual_materials 一起存进 store，generate 时随
    recipe_overrides 再发一遍。此时请求体是事实来源，resolver 不得用 session
    的版本覆盖掉用户最新的虚拟耗材声明。
    """
    session_data = {
        "recipe_overrides": [
            {
                "region_id": "region-1",
                "recipe": [4, 0, 0, 0, 0, 4],
                "layer_order": "Top2Bottom",
                "virtual_materials": [{"name": "Black", "hex": "#000000"}],
            }
        ]
    }
    request = ConvertGenerateRequest(
        lut_name="test-lut",
        recipe_overrides=[
            {
                "region_id": "region-1",
                "recipe": [4, 0, 0, 0, 0, 4],
                "layer_order": "Top2Bottom",
                "virtual_materials": [{"name": "Crimson", "hex": "#DC143C"}],
            }
        ],
    )

    resolved = _resolve_recipe_overrides(session_data, request)

    assert resolved is not None
    assert resolved[0]["virtual_materials"] == [
        {"name": "Crimson", "hex": "#DC143C"}
    ]


def test_resolve_recipe_overrides_keeps_other_region_virtuals_untouched() -> None:
    """Backfill must be scoped by region_id, not applied globally.

    region-1 带了 virtuals、region-2 没带时，resolver 只应为 region-2 从 session
    回补对应的 virtuals；不应把 region-1 的 virtuals 覆盖或跨 region 乱涂。
    """
    session_data = {
        "recipe_overrides": [
            {
                "region_id": "region-1",
                "recipe": [4, 0, 0, 0, 0, 4],
                "layer_order": "Top2Bottom",
                "virtual_materials": [{"name": "Black", "hex": "#000000"}],
            },
            {
                "region_id": "region-2",
                "recipe": [5, 0, 0, 0, 0, 5],
                "layer_order": "Top2Bottom",
                "virtual_materials": [{"name": "Red", "hex": "#FF0000"}],
            },
        ]
    }
    request = ConvertGenerateRequest(
        lut_name="test-lut",
        recipe_overrides=[
            {
                "region_id": "region-1",
                "recipe": [4, 0, 0, 0, 0, 4],
                "layer_order": "Top2Bottom",
                "virtual_materials": [{"name": "Black", "hex": "#111111"}],
            },
            {
                "region_id": "region-2",
                "recipe": [5, 0, 0, 0, 0, 5],
                "layer_order": "Top2Bottom",
                # Missing virtuals — must be backfilled from session["region-2"].
            },
        ],
    )

    resolved = _resolve_recipe_overrides(session_data, request)

    assert resolved is not None
    by_region = {item["region_id"]: item for item in resolved}
    assert by_region["region-1"]["virtual_materials"] == [
        {"name": "Black", "hex": "#111111"}
    ]
    assert by_region["region-2"]["virtual_materials"] == [
        {"name": "Red", "hex": "#FF0000"}
    ]


class TestUserSettingsBaseLayerModifierCompatibility:
    """Verify persisted user settings keep the new base-layer flag compatible."""

    def test_user_settings_default_enables_base_layer_modifier(self) -> None:
        settings = UserSettings()

        assert settings.enable_base_layer_height_modifier is True

    def test_user_settings_accepts_missing_base_layer_modifier_key(self) -> None:
        settings = UserSettings(
            **{
                "printer_model": "bambu-h2d",
                "slicer_software": "BambuStudio",
                "nozzle_size": "0.4",
            }
        )

        assert settings.enable_base_layer_height_modifier is True

    def test_user_settings_roundtrip_preserves_base_layer_modifier_false(self) -> None:
        payload = {
            "last_lut": "",
            "last_modeling_mode": "high-fidelity",
            "last_color_mode": "4-Color (RYBW)",
            "last_slicer": "",
            "palette_mode": "swatch",
            "enable_crop_modal": True,
            "printer_model": "bambu-h2d",
            "slicer_software": "BambuStudio",
            "nozzle_size": "0.4",
            "enable_base_layer_height_modifier": False,
        }
        mock_file = MagicMock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = json.dumps(payload)

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            post_response = client.post("/api/system/settings", json=payload)
            get_response = client.get("/api/system/settings")

        assert post_response.status_code == 200
        written_payload = json.loads(mock_file.write_text.call_args.args[0])
        assert written_payload["enable_base_layer_height_modifier"] is False
        assert get_response.status_code == 200
        assert get_response.json()["settings"]["enable_base_layer_height_modifier"] is False


class TestConverterEntryAcceptsBaseLayerModifierKwarg:
    """Contract tests: the ctx key plumbed by the /api/convert/generate router
    must be accepted by every downstream entry point that is called via
    ``**kwargs`` with the router ``params`` dict, otherwise the worker process
    raises ``TypeError`` and the API returns a generic 500.

    契约测试：/api/convert/generate 路由组装的 ctx 键必须被每一个通过 ``**kwargs``
    消费 params 字典的下游入口接受，否则 worker 进程抛 ``TypeError``，API 返回 500。
    """

    def test_generate_final_model_signature_accepts_enable_base_layer_modifier(self) -> None:
        import inspect

        from core.converter import generate_final_model

        params = inspect.signature(generate_final_model).parameters
        assert "enable_base_layer_height_modifier" in params
        assert params["enable_base_layer_height_modifier"].default is True

    def test_convert_image_to_3d_signature_accepts_enable_base_layer_modifier(self) -> None:
        import inspect

        from core.converter import convert_image_to_3d

        params = inspect.signature(convert_image_to_3d).parameters
        assert "enable_base_layer_height_modifier" in params
        assert params["enable_base_layer_height_modifier"].default is True
