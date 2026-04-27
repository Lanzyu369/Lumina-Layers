"""Unit tests for converter puzzle endpoints.

Validates:
- Layout preview returns an overlay and resolved grid summary
- Puzzle generation crops per-piece matched RGB inputs
- Puzzle generation assembles a single 3MF output instead of a ZIP archive
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config as runtime_config
from api.workers.converter_workers import worker_generate_model
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.routers.converter import puzzle as puzzle_router
from api.routers.converter.puzzle import _crop_piece_arrays, _submit_puzzle_worker
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from config import ModelingMode
from core.converter import generate_preview_cached
from core.puzzle import (
    PuzzleLayoutConfig,
    build_puzzle_layout,
    export_piece_boundary_geometry,
    rasterize_piece_mask,
)

_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()
_mock_pool = MagicMock(spec=WorkerPoolManager)
_TEST_TEMP_DIR = tempfile.gettempdir()

runtime_config.TEMP_DIR = _TEST_TEMP_DIR
puzzle_router.TEMP_DIR = _TEST_TEMP_DIR


def _make_puzzle_client() -> TestClient:
    """Create a puzzle-only API client without app lifespan side effects.
    创建不触发完整应用 lifespan 副作用的拼图专用测试客户端。

    Returns:
        TestClient: Lightweight puzzle endpoint client. (轻量拼图接口测试客户端)
    """

    test_app = FastAPI()
    test_app.include_router(puzzle_router.router, prefix="/api/convert")
    test_app.dependency_overrides[get_session_store] = lambda: _test_store
    test_app.dependency_overrides[get_file_registry] = lambda: _test_registry
    test_app.dependency_overrides[get_worker_pool] = lambda: _mock_pool
    return TestClient(test_app, raise_server_exceptions=False)


client = _make_puzzle_client()


def _make_session() -> tuple[str, dict[str, Any]]:
    """Create a preview-ready session for puzzle endpoint tests.

    Returns:
        tuple[str, dict[str, Any]]: Session ID and the preview cache.
            (Session ID 与预览缓存)
    """

    session_id = _test_store.create()

    matched_rgb = np.zeros((80, 120, 3), dtype=np.uint8)
    matched_rgb[:40, :, :] = (255, 0, 0)
    matched_rgb[40:, :, :] = (0, 255, 0)
    mask_solid = np.ones((80, 120), dtype=bool)
    preview_rgba = np.zeros((80, 120, 4), dtype=np.uint8)
    preview_rgba[..., :3] = matched_rgb
    preview_rgba[..., 3] = 255

    fd_img, image_path = tempfile.mkstemp(suffix=".png")
    os.close(fd_img)
    fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
    os.close(fd_lut)
    np.save(lut_path, np.zeros((1,), dtype=np.uint8))

    preview_cache = {
        "matched_rgb": matched_rgb,
        "mask_solid": mask_solid,
        "preview_rgba": preview_rgba,
        "preview_colors": {"White": (255, 255, 255, 255)},
        "slot_names": ["White"],
    }

    _test_store.put(session_id, "image_path", image_path)
    _test_store.put(session_id, "lut_path", lut_path)
    _test_store.put(session_id, "preview_cache", preview_cache)
    _test_store.register_temp_file(session_id, image_path)
    _test_store.register_temp_file(session_id, lut_path)
    return session_id, preview_cache


def _build_generate_body(session_id: str) -> dict[str, Any]:
    """Build a valid puzzle generate request body.

    Args:
        session_id: Active session ID. (当前 Session ID)

    Returns:
        dict[str, Any]: JSON payload for the generate endpoint. (生成接口请求体)
    """

    return {
        "session_id": session_id,
        "params": {
            "target_height_mm": 60.0,
            "puzzle_style": "regular",
            "sizing_mode": "grid",
            "piece_width_mm": 20.0,
            "piece_height_mm": 20.0,
            "rows": 2,
            "cols": 3,
            "target_piece_count": 6,
            "seed": 7,
            "connector_style": "classic",
            "labels_enabled": True,
            "engrave_back_labels": False,
            "irregularity_strength": 0.35,
            "min_neck_width_mm": 1.2,
            "params": {
                "lut_name": "test_lut",
                "target_width_mm": 90,
                "color_mode": "4-Color (RYBW)",
                "modeling_mode": "high-fidelity",
                "quantize_colors": 48,
                "enable_cleanup": True,
                "hue_weight": 0.0,
                "chroma_gate": 0,
                "is_dark": False,
                "spacer_thick": 1.2,
                "structure_mode": "Double-sided",
                "separate_backing": False,
                "add_loop": False,
                "loop_width": 4.0,
                "loop_length": 8.0,
                "loop_hole": 2.5,
                "loop_angle": 0,
                "loop_offset_x": 0,
                "loop_offset_y": 0,
                "loop_position_preset": "top-center",
                "enable_relief": False,
                "heightmap_max_height": 3.0,
                "enable_outline": False,
                "outline_width": 2.0,
                "enable_cloisonne": False,
                "wire_width_mm": 0.4,
                "wire_height_mm": 0.4,
                "enable_coating": False,
                "coating_height_mm": 0.08,
                "printer_id": "bambu-h2d",
                "slicer": "BambuStudio",
                "nozzle_size": "0.2",
            },
        },
    }


def test_puzzle_layout_preview_returns_overlay_and_grid_summary() -> None:
    """The layout preview endpoint should emit a transparent overlay resource."""

    session_id, _preview_cache = _make_session()
    response = client.post(
        "/api/convert/puzzle-layout-preview",
        json={
            "session_id": session_id,
            "params": {
                "target_height_mm": 60.0,
                "puzzle_style": "regular",
                "sizing_mode": "grid",
                "piece_width_mm": 20.0,
                "piece_height_mm": 20.0,
                "rows": 2,
                "cols": 3,
                "target_piece_count": 6,
                "seed": 7,
                "connector_style": "classic",
                "labels_enabled": True,
                "engrave_back_labels": False,
                "irregularity_strength": 0.35,
                "min_neck_width_mm": 1.2,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["overlay_url"].startswith("/api/files/")
    assert body["piece_count"] == 6
    assert body["grid_rows"] == 2
    assert body["grid_cols"] == 3


def test_puzzle_layout_preview_reuses_cached_layout_and_overlay() -> None:
    """Repeated preview requests with identical params should reuse cached preview assets."""

    session_id, _preview_cache = _make_session()
    preview_body = {
        "session_id": session_id,
        "params": {
            "target_height_mm": 60.0,
            "puzzle_style": "regular",
            "sizing_mode": "grid",
            "piece_width_mm": 20.0,
            "piece_height_mm": 20.0,
            "rows": 2,
            "cols": 3,
            "target_piece_count": 6,
            "seed": 7,
            "connector_style": "classic",
            "labels_enabled": True,
            "engrave_back_labels": False,
            "irregularity_strength": 0.35,
            "min_neck_width_mm": 1.2,
        },
    }

    first_response = client.post("/api/convert/puzzle-layout-preview", json=preview_body)

    assert first_response.status_code == 200

    with patch("api.routers.converter.puzzle.build_puzzle_layout", side_effect=AssertionError("layout cache missed")), patch(
        "api.routers.converter.puzzle.render_puzzle_overlay",
        side_effect=AssertionError("overlay cache missed"),
    ):
        second_response = client.post("/api/convert/puzzle-layout-preview", json=preview_body)

    assert second_response.status_code == 200
    assert first_response.json()["overlay_url"] == second_response.json()["overlay_url"]


def test_generate_puzzle_assembles_single_3mf_and_passes_piece_matched_rgb() -> None:
    """Puzzle generation should align per-piece helper assets to the worker raster grid."""

    session_id, preview_cache = _make_session()
    submitted_params: list[dict[str, Any]] = []
    assembled_calls: list[dict[str, Any]] = []
    async def _submit_stub(
        func: object,
        piece_image_path: str,
        lut_path: str,
        worker_params: dict[str, Any],
    ) -> dict[str, Any]:
        submitted_params.append(worker_params)
        fd_piece, piece_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_piece)
        with open(piece_path, "wb") as handle:
            handle.write(b"piece-3mf")
        return {"threemf_path": piece_path, "glb_path": None, "status_msg": "ok"}

    def _assemble_stub(
        *,
        piece_sources: list[Any],
        output_path: str,
        preview_colors: dict[object, object] | None,
        slot_names: list[str] | None,
        printer_id: str,
        slicer: str,
        nozzle_size: str = "0.4",
        overview_png_bytes: bytes | None = None,
    ) -> str:
        assembled_calls.append(
            {
                "piece_count": len(piece_sources),
                "printer_id": printer_id,
                "slicer": slicer,
                "nozzle_size": nozzle_size,
                "slot_names": slot_names,
                "overview_bytes": overview_png_bytes,
            }
        )
        with open(output_path, "wb") as handle:
            handle.write(b"combined-3mf")
        return output_path

    _mock_pool.submit = AsyncMock(side_effect=_submit_stub)

    with patch(
        "api.routers.converter.puzzle.assemble_puzzle_3mf",
        side_effect=_assemble_stub,
    ):
        response = client.post(
            "/api/convert/generate-puzzle",
            json=_build_generate_body(session_id),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["piece_count"] == 6
    assert body["download_url"].startswith("/api/files/")
    assert body["threemf_disk_path"].endswith(".3mf")
    assert len(submitted_params) == 6
    assert all(os.path.exists(params["piece_boundary_geometry_path"]) for params in submitted_params)
    assert all(params["disable_material_dilation"] is True for params in submitted_params)
    assert all(params["add_loop"] is False for params in submitted_params)
    assert all(params["enable_fridge_magnet"] is False for params in submitted_params)
    assert all(params["fridge_magnets"] == [] for params in submitted_params)
    assert len(assembled_calls) == 1
    assert assembled_calls[0]["piece_count"] == 6
    assert assembled_calls[0]["printer_id"] == "bambu-h2d"
    assert assembled_calls[0]["slicer"] == "BambuStudio"
    assert assembled_calls[0]["nozzle_size"] == "0.2"
    assert assembled_calls[0]["slot_names"] == ["White"]
    assert isinstance(assembled_calls[0]["overview_bytes"], bytes)
    assert assembled_calls[0]["overview_bytes"].startswith(b"\x89PNG")

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=120,
            height_px=80,
            total_width_mm=90.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=2,
            cols=3,
            seed=7,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
        )
    )
    first_piece = layout.pieces[0]
    first_boundary_path = Path(submitted_params[0]["piece_boundary_geometry_path"])
    with first_boundary_path.open("r", encoding="utf-8") as handle:
        boundary = json.load(handle)

    assert boundary["bbox_px"] == list(first_piece.bbox_px)
    assert len(boundary["polygon_px"]) == len(first_piece.polygon_px)
    assert len(boundary["holes_px"]) == len(first_piece.holes_px)
    first_matched_path = Path(submitted_params[0]["matched_rgb_path"])
    saved_matched = np.load(first_matched_path)
    bbox_px, local_mask = rasterize_piece_mask(first_piece)
    x0, y0, x1, y1 = bbox_px
    expected_worker_w = max(1, int(round((first_piece.bbox_mm[2] - first_piece.bbox_mm[0]) * 10.0)))
    expected_worker_h = max(1, int(round((first_piece.bbox_mm[3] - first_piece.bbox_mm[1]) * 10.0)))
    assert saved_matched.shape == (expected_worker_h, expected_worker_w, 3)

    expected_matched = np.array(preview_cache["matched_rgb"][y0:y1, x0:x1], copy=True)
    expected_matched[local_mask == 0] = 0
    expected_matched = np.array(
        Image.fromarray(expected_matched).resize((expected_worker_w, expected_worker_h), Image.Resampling.NEAREST),
        copy=False,
    )
    assert np.array_equal(saved_matched, expected_matched)
    assert np.any(saved_matched != 0)

    original_boundary = export_piece_boundary_geometry(first_piece)
    source_w = max(1, first_piece.bbox_px[2] - first_piece.bbox_px[0])
    source_h = max(1, first_piece.bbox_px[3] - first_piece.bbox_px[1])
    scale_x = expected_worker_w / float(source_w)
    scale_y = expected_worker_h / float(source_h)
    assert boundary["polygon_px"][0] == [
        original_boundary["polygon_px"][0][0] * scale_x,
        original_boundary["polygon_px"][0][1] * scale_y,
    ]
    assert max(point[0] for point in boundary["polygon_px"]) <= expected_worker_w + 1e-6
    assert max(point[1] for point in boundary["polygon_px"]) <= expected_worker_h + 1e-6


def test_generate_puzzle_rejects_fridge_magnet_mode() -> None:
    """Puzzle generation should reject fridge-magnet mode instead of duplicating cavities per piece."""

    session_id, _preview_cache = _make_session()
    body = _build_generate_body(session_id)
    body["params"]["params"]["enable_fridge_magnet"] = True
    body["params"]["params"]["fridge_magnets"] = [
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
    ]

    response = client.post("/api/convert/generate-puzzle", json=body)

    assert response.status_code == 422
    assert "fridge magnet" in response.json()["detail"].lower()


def test_generate_puzzle_rejects_fridge_magnet_flag_even_with_empty_list() -> None:
    """Puzzle generation should reject the opt-in flag even when no cavity list is supplied."""

    session_id, _preview_cache = _make_session()
    body = _build_generate_body(session_id)
    body["params"]["params"]["enable_fridge_magnet"] = True
    body["params"]["params"]["fridge_magnets"] = []

    response = client.post("/api/convert/generate-puzzle", json=body)

    assert response.status_code == 422
    assert "fridge magnet" in response.json()["detail"].lower()


def test_generate_puzzle_resizes_heightmap_crop_to_worker_grid() -> None:
    """Heightmap relief inputs should stay aligned with the worker raster grid."""

    session_id, _preview_cache = _make_session()
    submitted_params: list[dict[str, Any]] = []
    heightmap = np.tile(np.arange(120, dtype=np.uint8), (80, 1))
    _test_store.put(session_id, "heightmap_grayscale", heightmap)

    async def _submit_stub(
        func: object,
        piece_image_path: str,
        lut_path: str,
        worker_params: dict[str, Any],
    ) -> dict[str, Any]:
        submitted_params.append(worker_params)
        fd_piece, piece_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_piece)
        with open(piece_path, "wb") as handle:
            handle.write(b"piece-3mf")
        return {"threemf_path": piece_path, "glb_path": None, "status_msg": "ok"}

    def _assemble_stub(
        *,
        piece_sources: list[Any],
        output_path: str,
        preview_colors: dict[object, object] | None,
        slot_names: list[str] | None,
        printer_id: str,
        slicer: str,
        nozzle_size: str = "0.4",
        overview_png_bytes: bytes | None = None,
    ) -> str:
        with open(output_path, "wb") as handle:
            handle.write(b"combined-3mf")
        return output_path

    _mock_pool.submit = AsyncMock(side_effect=_submit_stub)
    body = _build_generate_body(session_id)
    body["params"]["params"]["enable_relief"] = True
    body["params"]["params"]["height_mode"] = "heightmap"
    body["params"]["params"]["heightmap_max_height"] = 4.0

    with patch(
        "api.routers.converter.puzzle.assemble_puzzle_3mf",
        side_effect=_assemble_stub,
    ):
        response = client.post("/api/convert/generate-puzzle", json=body)

    assert response.status_code == 200
    assert submitted_params
    assert all("heightmap_path" in params for params in submitted_params)

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=120,
            height_px=80,
            total_width_mm=90.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=2,
            cols=3,
            seed=7,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
        )
    )
    first_piece = layout.pieces[0]
    expected_worker_w = max(1, int(round((first_piece.bbox_mm[2] - first_piece.bbox_mm[0]) * 10.0)))
    expected_worker_h = max(1, int(round((first_piece.bbox_mm[3] - first_piece.bbox_mm[1]) * 10.0)))
    saved_heightmap = np.array(Image.open(submitted_params[0]["heightmap_path"]))

    assert saved_heightmap.shape == (expected_worker_h, expected_worker_w)
    assert np.any(saved_heightmap != 0)


def test_generate_puzzle_emits_hybrid_boundary_log_for_each_piece() -> None:
    """Each submitted puzzle piece should emit the structured hybrid-boundary log."""

    session_id, _preview_cache = _make_session()
    submitted_params: list[dict[str, Any]] = []

    async def _submit_stub(
        func: object,
        piece_image_path: str,
        lut_path: str,
        worker_params: dict[str, Any],
    ) -> dict[str, Any]:
        submitted_params.append(worker_params)
        fd_piece, piece_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_piece)
        with open(piece_path, "wb") as handle:
            handle.write(b"piece-3mf")
        return {"threemf_path": piece_path, "glb_path": None, "status_msg": "ok"}

    def _assemble_stub(
        *,
        piece_sources: list[Any],
        output_path: str,
        preview_colors: dict[object, object] | None,
        slot_names: list[str] | None,
        printer_id: str,
        slicer: str,
        nozzle_size: str = "0.4",
        overview_png_bytes: bytes | None = None,
    ) -> str:
        with open(output_path, "wb") as handle:
            handle.write(b"combined-3mf")
        return output_path

    _mock_pool.submit = AsyncMock(side_effect=_submit_stub)

    body = _build_generate_body(session_id)
    with patch("api.routers.converter.puzzle.assemble_puzzle_3mf", side_effect=_assemble_stub), patch.object(
        puzzle_router.log,
        "info",
    ) as log_info:
        response = client.post("/api/convert/generate-puzzle", json=body)

    assert response.status_code == 200
    assert len(submitted_params) == 6
    hybrid_boundary_calls = [
        call for call in log_info.call_args_list if call.kwargs["extra"]["event"] == "converter_puzzle_hybrid_boundary_enabled"
    ]
    assert len(hybrid_boundary_calls) == 6

    logged_piece_labels = {
        call.kwargs["extra"]["piece_label"]
        for call in hybrid_boundary_calls
    }
    assert logged_piece_labels == {"A1", "A2", "A3", "B1", "B2", "B3"}
    assert all(call.kwargs["extra"]["session_id"] == session_id for call in hybrid_boundary_calls)


def test_submit_puzzle_worker_preserves_boundary_params() -> None:
    """The worker submission shim should forward puzzle boundary params unchanged."""

    captured: dict[str, Any] = {}

    def _worker_stub(image_path: str, lut_path: str, params: dict[str, Any]) -> dict[str, Any]:
        captured["image_path"] = image_path
        captured["lut_path"] = lut_path
        captured["params"] = params
        return {"status_msg": "ok"}

    with patch("api.routers.converter.puzzle.worker_generate_model", side_effect=_worker_stub):
        result = _submit_puzzle_worker(
            "piece.png",
            "lut.npy",
            {
                "piece_boundary_geometry_path": "boundary.json",
                "disable_material_dilation": True,
            },
        )

    assert result["status_msg"] == "ok"
    assert captured["image_path"] == "piece.png"
    assert captured["lut_path"] == "lut.npy"
    assert captured["params"]["piece_boundary_geometry_path"] == "boundary.json"
    assert captured["params"]["disable_material_dilation"] is True


def test_generate_puzzle_reuses_cached_layout_after_preview() -> None:
    """Generate should reuse the authoritative preview layout instead of rebuilding it."""

    session_id, _preview_cache = _make_session()

    async def _submit_stub(
        func: object,
        piece_image_path: str,
        lut_path: str,
        worker_params: dict[str, Any],
    ) -> dict[str, Any]:
        fd_piece, piece_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_piece)
        with open(piece_path, "wb") as handle:
            handle.write(b"piece-3mf")
        return {"threemf_path": piece_path, "glb_path": None, "status_msg": "ok"}

    def _assemble_stub(
        *,
        piece_sources: list[Any],
        output_path: str,
        preview_colors: dict[object, object] | None,
        slot_names: list[str] | None,
        printer_id: str,
        slicer: str,
        nozzle_size: str = "0.4",
        overview_png_bytes: bytes | None = None,
    ) -> str:
        with open(output_path, "wb") as handle:
            handle.write(b"combined-3mf")
        return output_path

    preview_body = {
        "session_id": session_id,
        "params": {
            "target_height_mm": 60.0,
            "puzzle_style": "regular",
            "sizing_mode": "grid",
            "piece_width_mm": 20.0,
            "piece_height_mm": 20.0,
            "rows": 2,
            "cols": 3,
            "target_piece_count": 6,
            "seed": 7,
            "connector_style": "classic",
            "labels_enabled": True,
            "engrave_back_labels": False,
            "irregularity_strength": 0.35,
            "min_neck_width_mm": 1.2,
        },
    }
    _mock_pool.submit = AsyncMock(side_effect=_submit_stub)

    preview_response = client.post("/api/convert/puzzle-layout-preview", json=preview_body)
    assert preview_response.status_code == 200

    with patch("api.routers.converter.puzzle.build_puzzle_layout", side_effect=AssertionError("layout cache missed")), patch(
        "api.routers.converter.puzzle.assemble_puzzle_3mf",
        side_effect=_assemble_stub,
    ):
        generate_response = client.post(
            "/api/convert/generate-puzzle",
            json=_build_generate_body(session_id),
        )

    assert generate_response.status_code == 200


def test_generate_puzzle_rejects_unimplemented_back_label_engraving() -> None:
    """Puzzle generation should fail fast when back-label engraving is requested."""

    session_id, _preview_cache = _make_session()
    body = _build_generate_body(session_id)
    body["params"]["engrave_back_labels"] = True

    response = client.post("/api/convert/generate-puzzle", json=body)

    assert response.status_code == 422
    assert "not implemented yet" in response.json()["detail"]


def test_crop_piece_arrays_preserves_source_transparency_inside_piece_mask() -> None:
    """Puzzle crops should preserve alpha instead of turning transparent regions into white tiles."""

    source_rgba = np.zeros((90, 120, 4), dtype=np.uint8)
    matched_rgb = np.zeros((90, 120, 3), dtype=np.uint8)
    source_rgba[45:80, 60:110, :3] = (20, 80, 200)
    source_rgba[45:80, 60:110, 3] = 255
    matched_rgb[45:80, 60:110] = (20, 80, 200)

    layout = build_puzzle_layout(
        PuzzleLayoutConfig(
            width_px=120,
            height_px=90,
            total_width_mm=80.0,
            total_height_mm=60.0,
            style="regular",
            sizing_mode="grid",
            rows=3,
            cols=3,
            seed=5,
            connector_style="classic",
            irregularity_strength=0.35,
            min_neck_width_mm=1.2,
        )
    )
    source_transparent_inside_piece: np.ndarray | None = None
    source_opaque_inside_piece: np.ndarray | None = None
    piece_rgba: np.ndarray | None = None
    piece_matched: np.ndarray | None = None
    for candidate in layout.pieces:
        bbox_px, local_mask = rasterize_piece_mask(candidate)
        x0, y0, x1, y1 = bbox_px
        source_alpha_crop = source_rgba[y0:y1, x0:x1, 3]
        inside_piece = local_mask > 0
        candidate_source_transparent_inside = inside_piece & (source_alpha_crop == 0)
        candidate_source_opaque_inside = inside_piece & (source_alpha_crop > 0)
        if np.any(candidate_source_transparent_inside) and np.any(candidate_source_opaque_inside):
            _bbox_px, candidate_rgba, candidate_matched = _crop_piece_arrays(source_rgba, matched_rgb, candidate)
            piece_rgba = candidate_rgba
            piece_matched = candidate_matched
            source_transparent_inside_piece = candidate_source_transparent_inside
            source_opaque_inside_piece = candidate_source_opaque_inside
            break

    assert piece_rgba is not None
    assert piece_matched is not None
    assert source_transparent_inside_piece is not None
    assert source_opaque_inside_piece is not None

    assert np.any(source_transparent_inside_piece)
    assert np.any(source_opaque_inside_piece)
    assert np.all(piece_rgba[source_transparent_inside_piece] == 0)
    assert np.all(piece_matched[source_transparent_inside_piece] == 0)
    assert np.any(piece_rgba[..., 3][source_opaque_inside_piece] > 0)
    assert np.any(piece_matched[source_opaque_inside_piece] != 0)


def test_generate_puzzle_filters_fully_transparent_pieces_during_layout() -> None:
    """Transparent-only tiles should be removed by layout resolution before worker submission."""

    session_id, preview_cache = _make_session()
    preview_rgba = np.array(preview_cache["preview_rgba"], copy=True)
    preview_rgba[:, :90] = 0
    matched_rgb = np.array(preview_cache["matched_rgb"], copy=True)
    matched_rgb[:, :90] = 0
    preview_cache["preview_rgba"] = preview_rgba
    preview_cache["matched_rgb"] = matched_rgb
    preview_cache["mask_solid"] = preview_rgba[..., 3] > 0
    _test_store.put(session_id, "preview_cache", preview_cache)

    submitted_params: list[dict[str, Any]] = []

    async def _submit_stub(
        func: object,
        piece_image_path: str,
        lut_path: str,
        worker_params: dict[str, Any],
    ) -> dict[str, Any]:
        submitted_params.append(worker_params)
        fd_piece, piece_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_piece)
        with open(piece_path, "wb") as handle:
            handle.write(b"piece-3mf")
        return {"threemf_path": piece_path, "glb_path": None, "status_msg": "ok"}

    def _assemble_stub(
        *,
        piece_sources: list[Any],
        output_path: str,
        preview_colors: dict[object, object] | None,
        slot_names: list[str] | None,
        printer_id: str,
        slicer: str,
        nozzle_size: str = "0.4",
        overview_png_bytes: bytes | None = None,
    ) -> str:
        with open(output_path, "wb") as handle:
            handle.write(b"combined-3mf")
        return output_path

    body = _build_generate_body(session_id)
    body["params"]["rows"] = 1
    body["params"]["cols"] = 2
    body["params"]["target_piece_count"] = 2

    _mock_pool.submit = AsyncMock(side_effect=_submit_stub)

    with patch(
        "api.routers.converter.puzzle.assemble_puzzle_3mf",
        side_effect=_assemble_stub,
    ):
        response = client.post(
            "/api/convert/generate-puzzle",
            json=body,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["piece_count"] == 1
    assert len(submitted_params) == 1
    assert not any("Skipped" in warning for warning in payload["warnings"])


def test_worker_generate_model_handles_tiny_piece_with_large_quantize_request() -> None:
    """Tiny puzzle-piece rasters should not fail when quantize_colors exceeds pixel count.

    This reproduces the reported SVG+puzzle failure mode at the real worker/model
    path: the rasterized piece is tiny, but the request still carries the normal
    UI quantization value (e.g. 48).
    """

    fd_image, image_path_str = tempfile.mkstemp(prefix="tiny_piece_worker_", suffix=".png", dir=str(Path.cwd()))
    os.close(fd_image)
    fd_lut, lut_path_str = tempfile.mkstemp(prefix="tiny_piece_worker_", suffix=".npz", dir=str(Path.cwd()))
    os.close(fd_lut)
    image_path = Path(image_path_str)
    lut_path = Path(lut_path_str)

    rgb = np.array(
        [
            [[255, 0, 0], [0, 255, 0]],
            [[0, 0, 255], [255, 255, 0]],
        ],
        dtype=np.uint8,
    )
    Image.fromarray(rgb).save(image_path)

    lut_rgb = np.array(
        [
            [255, 0, 0],
            [0, 255, 0],
            [0, 0, 255],
            [255, 255, 0],
        ],
        dtype=np.uint8,
    )
    ref_stacks = np.array(
        [
            [0, 0, 0, 0, 0],
            [1, 1, 1, 1, 1],
            [2, 2, 2, 2, 2],
            [3, 3, 3, 3, 3],
        ],
        dtype=np.int16,
    )
    np.savez(lut_path, rgb=lut_rgb, stacks=ref_stacks)

    params = {
        "target_width_mm": 10.0,
        "spacer_thick": 1.2,
        "structure_mode": "Double-sided",
        "color_mode": "4-Color (RYBW)",
        "add_loop": False,
        "loop_width": 4.0,
        "loop_length": 8.0,
        "loop_hole": 2.5,
        "loop_pos": None,
        "modeling_mode": ModelingMode.HIGH_FIDELITY,
        "quantize_colors": 48,
        "enable_cleanup": True,
        "hue_weight": 0.0,
        "chroma_gate": 0.0,
        "separate_backing": False,
        "enable_relief": False,
        "height_mode": "color",
        "color_height_map": None,
        "heightmap_max_height": 3.0,
        "enable_outline": False,
        "outline_width": 2.0,
        "enable_cloisonne": False,
        "wire_width_mm": 0.4,
        "wire_height_mm": 0.4,
        "free_color_set": set(),
        "enable_coating": False,
        "coating_height_mm": 0.08,
        "matched_rgb_path": None,
        "loop_angle": 0.0,
        "loop_offset_x": 0.0,
        "loop_offset_y": 0.0,
        "loop_position_preset": "top-center",
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "nozzle_size": "0.2",
        "relief_global_max_height": None,
    }

    with patch("core.pipeline.s09_export_3mf.export_scene_with_bambu_metadata", return_value=None), patch(
        "core.pipeline.s11_glb_preview.generate_segmented_glb",
        return_value=None,
    ):
        result = worker_generate_model(str(image_path), str(lut_path), params)

    try:
        assert isinstance(result["threemf_path"], str)
        assert result["threemf_path"].endswith(".3mf")
        assert isinstance(result["status_msg"], str)
        assert result["status_msg"]
    finally:
        for path in (image_path, lut_path):
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass


def test_worker_generate_model_preserves_svg_puzzle_piece_dimensions_for_matched_override() -> None:
    """SVG puzzle pieces should keep their exact crop dimensions in the worker.

    The puzzle route passes ``target_width_mm`` using piece metadata, and some
    SVG-derived widths are represented as values like ``7.799999999999997``.
    If the worker truncates instead of rounding, the piece shrinks by one pixel,
    ``matched_rgb_path`` is ignored due to a shape mismatch, and thin SVG detail
    can disappear completely.
    """

    with tempfile.TemporaryDirectory(prefix="svg_puzzle_piece_") as temp_dir:
        tmp_path = Path(temp_dir)
        svg_path = tmp_path / "thin.svg"
        svg_path.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 80">'
                '<path d="M10 10 L110 70" stroke="#ff0000" stroke-width="1" fill="none"/>'
                '<path d="M10 70 L110 10" stroke="#0000ff" stroke-width="1" fill="none"/>'
                '<circle cx="60" cy="40" r="6" fill="#00ff00"/>'
                "</svg>"
            ),
            encoding="utf-8",
        )

        lut_path = tmp_path / "test_lut.npz"
        lut_rgb = np.array(
            [
                [255, 0, 0],
                [0, 255, 0],
                [0, 0, 255],
                [255, 255, 255],
            ],
            dtype=np.uint8,
        )
        ref_stacks = np.array(
            [
                [0, 0, 0, 0, 0],
                [1, 1, 1, 1, 1],
                [2, 2, 2, 2, 2],
                [3, 3, 3, 3, 3],
            ],
            dtype=np.int16,
        )
        np.savez(lut_path, rgb=lut_rgb, stacks=ref_stacks)

        _preview_img, cache, status = generate_preview_cached(
            image_path=str(svg_path),
            lut_path=str(lut_path),
            target_width_mm=120.0,
            color_mode="4-Color (RYBW)",
            modeling_mode=ModelingMode.VECTOR,
            quantize_colors=48,
            enable_cleanup=True,
            is_dark=False,
            hue_weight=0.0,
            chroma_gate=0.0,
        )
        assert status.startswith("[OK]")

        layout = build_puzzle_layout(
            PuzzleLayoutConfig(
                width_px=cache["matched_rgb"].shape[1],
                height_px=cache["matched_rgb"].shape[0],
                total_width_mm=120.0,
                total_height_mm=80.0,
                style="regular",
                sizing_mode="grid",
                rows=3,
                cols=6,
                target_piece_count=18,
                seed=7,
                connector_style="classic",
                irregularity_strength=0.35,
                min_neck_width_mm=1.2,
                solid_mask=cache["mask_solid"],
            )
        )

        piece = next(
            candidate
            for candidate in layout.pieces
            if int((candidate.bbox_mm[2] - candidate.bbox_mm[0]) * 10) != (candidate.bbox_px[2] - candidate.bbox_px[0])
        )
        _bbox_px, piece_rgba, piece_matched = _crop_piece_arrays(cache["preview_rgba"], cache["matched_rgb"], piece)
        assert piece_matched.shape[1] > 0

        piece_image_path = tmp_path / f"{piece.label}.png"
        piece_matched_path = tmp_path / f"{piece.label}.npy"
        piece_boundary_path = tmp_path / f"{piece.label}.json"
        Image.fromarray(piece_rgba).save(piece_image_path)
        np.save(piece_matched_path, piece_matched)
        piece_boundary_path.write_text(
            json.dumps(export_piece_boundary_geometry(piece), ensure_ascii=False),
            encoding="utf-8",
        )

        params = {
            "target_width_mm": piece.bbox_mm[2] - piece.bbox_mm[0],
            "spacer_thick": 1.2,
            "structure_mode": "Double-sided",
            "color_mode": "4-Color (RYBW)",
            "add_loop": False,
            "loop_width": 4.0,
            "loop_length": 8.0,
            "loop_hole": 2.5,
            "loop_pos": None,
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
            "quantize_colors": 48,
            "enable_cleanup": True,
            "hue_weight": 0.0,
            "chroma_gate": 0.0,
            "separate_backing": False,
            "enable_relief": False,
            "height_mode": "color",
            "color_height_map": None,
            "heightmap_max_height": 3.0,
            "enable_outline": False,
            "outline_width": 2.0,
            "enable_cloisonne": False,
            "wire_width_mm": 0.4,
            "wire_height_mm": 0.4,
            "free_color_set": set(),
            "enable_coating": False,
            "coating_height_mm": 0.08,
            "matched_rgb_path": str(piece_matched_path),
            "piece_boundary_geometry_path": str(piece_boundary_path),
            "disable_material_dilation": True,
            "loop_angle": 0.0,
            "loop_offset_x": 0.0,
            "loop_offset_y": 0.0,
            "loop_position_preset": "top-center",
            "printer_id": "bambu-h2d",
            "slicer": "BambuStudio",
            "nozzle_size": "0.2",
            "relief_global_max_height": None,
        }

        with patch("core.pipeline.s09_export_3mf.export_scene_with_bambu_metadata", return_value=None), patch(
            "core.pipeline.s11_glb_preview.generate_segmented_glb",
            return_value=None,
        ), patch("core.pipeline.s03_color_replacement._log.warning") as warning_mock:
            result = worker_generate_model(str(piece_image_path), str(lut_path), params)

        assert isinstance(result["threemf_path"], str)
        assert result["threemf_path"].endswith(".3mf")
        assert not any("matched_rgb_path shape" in str(call.args[0]) for call in warning_mock.call_args_list)
