"""Integration tests for converter puzzle router log canaries."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.routers.converter import puzzle as puzzle_router
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from core.puzzle import PuzzlePiece


@pytest.fixture()
def puzzle_harness():
    """Create an isolated puzzle-router test client."""

    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    pool = MagicMock(spec=WorkerPoolManager)

    test_app = FastAPI()
    test_app.include_router(puzzle_router.router, prefix="/api/convert")
    test_app.dependency_overrides[get_session_store] = lambda: store
    test_app.dependency_overrides[get_file_registry] = lambda: registry
    test_app.dependency_overrides[get_worker_pool] = lambda: pool

    with TestClient(test_app, raise_server_exceptions=False) as client:
        yield {"client": client, "store": store, "registry": registry, "pool": pool}

    store.clear_all()


def _capture_puzzle_logger(caplog: pytest.LogCaptureFixture) -> logging.Logger:
    logger = logging.getLogger("lumina.api.routers.converter.puzzle")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=logger.name)
    return logger


def _seed_puzzle_preview_session(store: SessionStore) -> str:
    session_id = store.create()
    matched_rgb = np.zeros((80, 120, 3), dtype=np.uint8)
    matched_rgb[:40, :, :] = [255, 0, 0]
    matched_rgb[40:, :, :] = [0, 255, 0]
    mask_solid = np.ones((80, 120), dtype=bool)
    preview_rgba = np.zeros((80, 120, 4), dtype=np.uint8)
    preview_rgba[..., :3] = matched_rgb
    preview_rgba[..., 3] = 255
    store.put(
        session_id,
        "preview_cache",
        {
            "matched_rgb": matched_rgb,
            "mask_solid": mask_solid,
            "preview_rgba": preview_rgba,
            "preview_colors": {"White": (255, 255, 255, 255)},
            "slot_names": ["White"],
        },
    )
    return session_id


def _seed_puzzle_generate_session(store: SessionStore, tmp_path) -> str:
    session_id = _seed_puzzle_preview_session(store)
    image_path = tmp_path / "puzzle.png"
    lut_path = tmp_path / "palette.npy"
    image_data = np.zeros((80, 120, 3), dtype=np.uint8)
    image_data[:, :60, :] = [255, 0, 0]
    image_data[:, 60:, :] = [0, 255, 0]
    Image.fromarray(image_data).save(image_path)
    np.save(lut_path, np.zeros((1,), dtype=np.uint8))
    store.put(session_id, "image_path", str(image_path))
    store.put(session_id, "lut_path", str(lut_path))
    store.register_temp_file(session_id, str(image_path))
    store.register_temp_file(session_id, str(lut_path))
    return session_id


def _layout_preview_body(session_id: str) -> dict[str, object]:
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
        },
    }


def _generate_puzzle_body(session_id: str) -> dict[str, object]:
    return {
        "session_id": session_id,
        "params": {
            "target_height_mm": 60.0,
            "puzzle_style": "regular",
            "sizing_mode": "grid",
            "piece_width_mm": 20.0,
            "piece_height_mm": 20.0,
            "rows": 2,
            "cols": 2,
            "target_piece_count": 4,
            "seed": 7,
            "connector_style": "classic",
            "labels_enabled": False,
            "engrave_back_labels": False,
            "irregularity_strength": 0.35,
            "min_neck_width_mm": 1.2,
            "params": {
                "lut_name": "test_lut",
                "target_width_mm": 90.0,
                "modeling_mode": "high-fidelity",
                "color_mode": "4-Color (RYBW)",
                "add_loop": False,
                "enable_fridge_magnet": False,
                "enable_relief": False,
            },
        },
    }


def test_prepare_piece_worker_assets_adds_actual_cut_clearance() -> None:
    """Puzzle worker boundaries should remove 0.1mm total kerf from generated geometry."""

    source_rgba = np.full((40, 40, 4), 255, dtype=np.uint8)
    matched_rgb = np.full((40, 40, 3), 127, dtype=np.uint8)
    piece = PuzzlePiece(
        row=1,
        col=1,
        label="A1",
        polygon_px=((0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)),
        bbox_px=(0, 0, 40, 40),
        bbox_mm=(0.0, 0.0, 4.0, 4.0),
        centroid_mm=(2.0, 2.0),
    )

    _bbox_px, _piece_rgba, _piece_matched, boundary_payload = (
        puzzle_router._prepare_piece_worker_assets(source_rgba, matched_rgb, piece)
    )

    polygon = boundary_payload["polygon_px"]
    x_values = [point[0] for point in polygon]
    y_values = [point[1] for point in polygon]

    assert min(x_values) == pytest.approx(0.5)
    assert min(y_values) == pytest.approx(0.5)
    assert max(x_values) == pytest.approx(39.5)
    assert max(y_values) == pytest.approx(39.5)
    assert boundary_payload["bbox_px"] == [0, 0, 40, 40]


class TestPuzzleLayoutPreviewCanary:
    """Successful puzzle-layout-preview requests emit the renamed done canary."""

    def test_puzzle_layout_preview_emits_renamed_contract_canary(
        self,
        puzzle_harness,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = puzzle_harness["store"]
        client: TestClient = puzzle_harness["client"]
        session_id = _seed_puzzle_preview_session(store)

        target_logger = _capture_puzzle_logger(caplog)
        try:
            response = client.post(
                "/api/convert/puzzle-layout-preview",
                json=_layout_preview_body(session_id),
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["overlay_url"].startswith("/api/files/")

        old_event = "converter_puzzle_layout" + "_preview"
        old_records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == old_event
        ]
        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "converter_puzzle_layout_preview_done"
        ]
        assert old_records == []
        assert len(records) == 1

        record = records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.piece_count == body["piece_count"]
        assert record.grid_cols == body["grid_cols"]
        assert record.grid_rows == body["grid_rows"]
        assert record.derived_piece_width_mm == body["derived_piece_width_mm"]
        assert record.derived_piece_height_mm == body["derived_piece_height_mm"]
        assert record.warning_count == len(body["warnings"])
        assert record.labels_enabled is True


class TestGeneratePuzzleCanary:
    """Successful generate-puzzle requests emit the full structured contract."""

    def test_generate_puzzle_emits_extended_contract_canary(
        self,
        puzzle_harness,
        tmp_path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store: SessionStore = puzzle_harness["store"]
        pool: MagicMock = puzzle_harness["pool"]
        client: TestClient = puzzle_harness["client"]
        session_id = _seed_puzzle_generate_session(store, tmp_path)
        piece_index = 0

        async def _submit_stub(*_args, **_kwargs) -> dict[str, object]:
            nonlocal piece_index
            piece_index += 1
            path = tmp_path / f"piece-{piece_index}.3mf"
            path.write_bytes(b"piece-3mf")
            return {"threemf_path": str(path), "glb_path": None, "status_msg": "ok"}

        def _assemble_stub(*, output_path: str, **_kwargs) -> str:
            with open(output_path, "wb") as handle:
                handle.write(b"combined-3mf")
            return output_path

        pool.submit = AsyncMock(side_effect=_submit_stub)
        target_logger = _capture_puzzle_logger(caplog)
        try:
            with patch(
                "api.routers.converter.puzzle.assemble_puzzle_3mf",
                side_effect=_assemble_stub,
            ):
                response = client.post(
                    "/api/convert/generate-puzzle",
                    json=_generate_puzzle_body(session_id),
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["piece_count"] == 4
        download_id = body["download_url"].rsplit("/", 1)[-1]

        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_puzzle_generate_done"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.piece_count == body["piece_count"]
        assert record.grid_cols == body["grid_cols"]
        assert record.grid_rows == body["grid_rows"]
        assert record.warning_count == len(body["warnings"])
        assert record.skipped_transparent_count == 0
        assert record.download_id == download_id
