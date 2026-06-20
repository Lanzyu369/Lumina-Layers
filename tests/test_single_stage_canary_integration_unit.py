"""Integration tests for single-stage structured log canaries."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import numpy as np
from PIL import Image

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from core.single_stage import (
    GradientCardStageAResult,
    MaterialArchiveDeleteResult,
    MaterialArchiveSaveResult,
    MaterialArchiveUpdateResult,
    SingleStageExtractResult,
    StageAFitResult,
)


def _client_with_state() -> tuple[TestClient, SessionStore, FileRegistry]:
    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    return TestClient(app, base_url="http://localhost:8000"), store, registry


def _capture_single_stage_logger(
    caplog: pytest.LogCaptureFixture,
) -> logging.Logger:
    target_logger = logging.getLogger("lumina.api.routers.single_stage")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=target_logger.name)
    return target_logger


def _records_for_event(
    caplog: pytest.LogCaptureFixture,
    event_name: str,
) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == event_name
    ]


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(np.zeros((16, 16, 3), dtype=np.uint8), mode="RGB").save(
        buffer,
        format="PNG",
    )
    return buffer.getvalue()


def _stage_a_fit_summary() -> dict[str, object]:
    return {
        "substrate_count": 2,
        "channel_count": 6,
        "substrates": ["white", "black"],
        "colors": ["stub"],
        "overall_validation": {"mean_delta_e": 0.001},
        "warnings": [],
        "orientation_ranking": {
            "orientation_reliable": True,
            "delta_e_gap": 1.0,
            "top_candidates": [],
        },
    }


def _gradient_material_summary() -> dict[str, object]:
    return {
        "sample_count": 1,
        "per_substrate_sample_count": 1,
        "grid_rows": 1,
        "grid_cols": 1,
        "layer_height_mm": 0.04,
        "warp_width_px": 8,
        "warp_height_px": 8,
        "thickness_layers": [0],
        "sample_boxes": [],
        "white_zero_rgb": [255, 255, 255],
        "black_zero_rgb": [0, 0, 0],
        "estimated_rgb": [128, 130, 132],
        "estimated_k": [0.1, 0.1, 0.1],
    }


class TestExtractSingleStageCanary:
    def test_extract_single_stage_logs_success_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, store, _ = _client_with_state()
        stage_json_path = tmp_path / "single_stage.json"
        extract_root = tmp_path / "extract_root"
        stage_json_path.write_text("{}", encoding="utf-8")
        extract_root.mkdir()

        def _stub_extract_single_stage_dataset(zip_path: str):
            assert zip_path.endswith(".zip")
            return SingleStageExtractResult(
                stage_json_path=str(stage_json_path),
                dataset_summary={
                    "substrate_count": 1,
                    "color_count": 1,
                    "dataset_count": 1,
                    "image_count": 1,
                    "substrates": ["white"],
                    "coverage": [{"substrate_id": "white", "colors": ["White"]}],
                    "datasets": [],
                },
                warnings=[],
                extracted_root=str(extract_root),
            )

        monkeypatch.setattr(
            "api.routers.single_stage.extract_single_stage_dataset",
            _stub_extract_single_stage_dataset,
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/extract-single-stage",
                files={"dataset_zip": ("dataset.zip", b"zip", "application/zip")},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["stage_json_url"].startswith("/api/files/")
        session = store.get(body["session_id"])
        assert session is not None
        assert session["single_stage_stage_json_path"] == str(stage_json_path)

        records = _records_for_event(
            caplog,
            "extractor_extract_single_stage_done",
        )
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == body["session_id"]
        assert record.dataset_summary_count == 7
        assert record.warning_count == 0
        assert record.stage_json_id == body["stage_json_url"].rsplit("/", 1)[-1]


class TestFitStageACanary:
    def test_fit_stage_a_logs_session_source_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, store, _ = _client_with_state()
        stage_json_path = tmp_path / "single_stage.json"
        params_path = tmp_path / "stage_a_params.json"
        stage_json_path.write_text("{}", encoding="utf-8")
        params_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
        session_id = store.create()
        store.put(session_id, "single_stage_stage_json_path", str(stage_json_path))

        def _stub_fit_stage_a_from_stage_json(path: str):
            assert path == str(stage_json_path)
            return StageAFitResult(
                params_path=str(params_path),
                fit_summary={
                    "substrate_count": 1,
                    "channel_count": 6,
                    "substrates": ["white"],
                    "colors": ["White"],
                    "overall_validation": {"mean_delta_e": 0.001},
                    "warnings": [],
                },
            )

        monkeypatch.setattr(
            "api.routers.single_stage.fit_stage_a_from_stage_json",
            _stub_fit_stage_a_from_stage_json,
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/fit-stage-a",
                data={"session_id": session_id},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["stage_a_params_url"].startswith("/api/files/")

        records = _records_for_event(caplog, "extractor_fit_stage_a_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.params_id == body["stage_a_params_url"].rsplit("/", 1)[-1]
        assert record.source_mode == "session"
        assert record.fit_summary_count == 6

    def test_fit_stage_a_logs_upload_source_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, store, _ = _client_with_state()
        params_path = tmp_path / "stage_a_params.json"
        params_path.write_text(json.dumps({"ok": True}), encoding="utf-8")

        def _stub_fit_stage_a_from_stage_json(path: str):
            assert path.endswith(".json")
            return StageAFitResult(
                params_path=str(params_path),
                fit_summary={
                    "substrate_count": 1,
                    "channel_count": 6,
                    "substrates": ["white"],
                    "colors": ["White"],
                    "overall_validation": {"mean_delta_e": 0.001},
                    "warnings": [],
                },
            )

        monkeypatch.setattr(
            "api.routers.single_stage.fit_stage_a_from_stage_json",
            _stub_fit_stage_a_from_stage_json,
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/fit-stage-a",
                files={"stage_json": ("single_stage.json", b"{}", "application/json")},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        records = _records_for_event(caplog, "extractor_fit_stage_a_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert isinstance(record.session_id, str)
        assert store.get(record.session_id) is not None
        assert record.params_id == body["stage_a_params_url"].rsplit("/", 1)[-1]
        assert record.source_mode == "upload"
        assert record.fit_summary_count == 6


class TestExtractGradientCardStageACanary:
    def test_extract_gradient_card_stage_a_logs_success_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, _, _ = _client_with_state()
        params_path = tmp_path / "stage_a_params.json"
        params_path.write_text(json.dumps({"version": "stage_a/v1"}), encoding="utf-8")

        def _stub_extract_gradient_card(
            white_rgb: np.ndarray,
            black_rgb: np.ndarray,
            white_points: list[list[float]],
            black_points: list[list[float]],
            dataset_zip_path: str,
            *,
            manual_white_orientation: str | None,
            manual_black_orientation: str | None,
            image_source: str | None = None,
        ) -> GradientCardStageAResult:
            assert white_rgb.shape == (16, 16, 3)
            assert black_rgb.shape == (16, 16, 3)
            assert white_points == [[0, 0], [15, 0], [15, 15], [0, 15]]
            assert black_points == [[0, 0], [15, 0], [15, 15], [0, 15]]
            assert dataset_zip_path.endswith(".zip")
            assert manual_white_orientation == "rotate_90_cw"
            assert manual_black_orientation is None
            assert image_source is None
            return GradientCardStageAResult(
                params_path=str(params_path),
                params_payload={"version": "stage_a/v1"},
                fit_summary=_stage_a_fit_summary(),
                material_summary=_gradient_material_summary(),
                source_summary={
                    "white_image_size": [16, 16],
                    "black_image_size": [16, 16],
                },
                warnings=[],
                white_warp_rgb=np.zeros((8, 8, 3), dtype=np.uint8),
                black_warp_rgb=np.zeros((8, 8, 3), dtype=np.uint8),
            )

        monkeypatch.setattr(
            "api.routers.single_stage.extract_stage_a_material_from_gradient_cards",
            _stub_extract_gradient_card,
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/extract-gradient-card-stage-a",
                files={
                    "white_image": ("white.png", _png_bytes(), "image/png"),
                    "black_image": ("black.png", _png_bytes(), "image/png"),
                    "dataset_zip": ("kit.zip", b"zip", "application/zip"),
                },
                data={
                    "white_corner_points": "[[0,0],[15,0],[15,15],[0,15]]",
                    "black_corner_points": "[[0,0],[15,0],[15,15],[0,15]]",
                    "manual_white_orientation": "rotate_90_cw",
                    "manual_black_orientation": "auto",
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["stage_a_params_url"].startswith("/api/files/")
        assert body["warnings"] == []

        records = _records_for_event(
            caplog,
            "extractor_extract_gradient_card_stage_a_done",
        )
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == body["session_id"]
        assert record.warning_count == 0
        assert record.material_summary_count == 13
        assert record.manual_white_orientation == "rotate_90_cw"
        assert record.manual_black_orientation is None
        assert record.stage_a_id == body["stage_a_params_url"].rsplit("/", 1)[-1]


class TestSaveGradientCardMaterialCanary:
    def test_save_gradient_card_material_logs_success_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, store, _ = _client_with_state()
        archive_path = tmp_path / "stub_material_v1" / "material_archive.json"
        params_path = tmp_path / "stub_material_v1" / "stage_a_params.json"
        archive_path.parent.mkdir()
        archive_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
        params_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
        session_id = store.create()
        store.put(session_id, "gradient_card_stage_a_params", {"version": "stage_a/v1"})
        store.put(session_id, "gradient_card_fit_summary", _stage_a_fit_summary())
        store.put(session_id, "gradient_card_material_summary", _gradient_material_summary())
        store.put(
            session_id,
            "gradient_card_source_summary",
            {"white_image_size": [16, 16], "black_image_size": [16, 16]},
        )

        def _stub_save_stage_a_material_archive(**kwargs) -> MaterialArchiveSaveResult:
            assert kwargs["material_name"] == "Stub PLA"
            assert kwargs["save_mode"] == "override"
            assert kwargs["brand"] == "Lumina"
            return MaterialArchiveSaveResult(
                archive_path=str(archive_path),
                stage_a_params_path=str(params_path),
                material_summary={
                    "material_name": "Stub PLA",
                    "directory_name": "stub_material_v1",
                    "brand": "Lumina",
                    "archive_path": str(archive_path),
                    "stage_a_params_path": str(params_path),
                    "verification_count": 2,
                },
            )

        monkeypatch.setattr(
            "api.routers.single_stage.save_stage_a_material_archive",
            _stub_save_stage_a_material_archive,
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/save-gradient-card-material",
                data={
                    "session_id": session_id,
                    "material_name": "  Stub PLA  ",
                    "save_mode": "override",
                    "brand": " Lumina ",
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["material_file_url"].startswith("/api/files/")
        assert body["material_summary"]["verification_count"] == 2

        records = _records_for_event(
            caplog,
            "extractor_save_gradient_card_material_done",
        )
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == session_id
        assert record.material_name == "Stub PLA"
        assert record.directory_name == "stub_material_v1"
        assert record.verification_count == 2
        assert record.save_mode == "override"
        assert record.material_id == body["material_file_url"].rsplit("/", 1)[-1]


class TestDeleteGradientCardMaterialCanary:
    def test_delete_gradient_card_material_logs_sessionless_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, _, _ = _client_with_state()
        deleted_path = tmp_path / "stub_material_v1"

        def _stub_delete_saved_stage_a_material_archive(
            *,
            directory_name: str,
        ) -> MaterialArchiveDeleteResult:
            assert directory_name == "stub_material_v1"
            return MaterialArchiveDeleteResult(
                directory_name=directory_name,
                material_name="Stub PLA",
                deleted_path=str(deleted_path),
            )

        monkeypatch.setattr(
            "api.routers.single_stage.delete_saved_stage_a_material_archive",
            _stub_delete_saved_stage_a_material_archive,
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.delete(
                "/api/extractor/gradient-card-materials/stub_material_v1",
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "status": "ok",
            "message": "Gradient card material deleted successfully",
            "directory_name": "stub_material_v1",
            "material_name": "Stub PLA",
        }

        records = _records_for_event(
            caplog,
            "extractor_delete_gradient_card_material_done",
        )
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.directory_name == "stub_material_v1"
        assert record.material_name == "Stub PLA"


class TestUpdateGradientCardMaterialCanary:
    @pytest.mark.parametrize(
        ("payload", "expected_count"),
        [
            ({"material_name": "Renamed PLA"}, 1),
            ({"material_name": "Renamed PLA", "brand": "Lumina"}, 2),
            (
                {
                    "material_name": "Renamed PLA",
                    "brand": "Lumina",
                    "estimated_rgb": [255, 0, 0],
                },
                3,
            ),
        ],
    )
    def test_update_gradient_card_material_logs_sessionless_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        payload: dict[str, object],
        expected_count: int,
    ) -> None:
        client, _, _ = _client_with_state()
        materials_root = tmp_path / "materials"
        material_dir = materials_root / "stub_material_v1"
        material_dir.mkdir(parents=True, exist_ok=True)
        archive_path = material_dir / "material.json"
        params_path = material_dir / "stage_A_parameters.json"
        archive_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
        params_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
        monkeypatch.setattr(
            "core.single_stage.materials.MATERIALS_DIR",
            str(materials_root),
        )

        def _stub_update_saved_stage_a_material_archive_metadata(
            **kwargs,
        ) -> MaterialArchiveUpdateResult:
            assert kwargs["directory_name"] == "stub_material_v1"
            assert kwargs["material_name"] == payload["material_name"]
            assert kwargs["brand"] == payload.get("brand")
            if "estimated_rgb" in payload:
                assert kwargs["estimated_rgb"] == payload["estimated_rgb"]
            else:
                assert "estimated_rgb" not in kwargs
            return MaterialArchiveUpdateResult(
                archive_path=str(archive_path),
                stage_a_params_path=str(params_path),
                material_summary={
                    "material_name": payload["material_name"],
                    "directory_name": "stub_material_v1",
                    "brand": payload.get("brand"),
                    "archive_path": str(archive_path),
                    "stage_a_params_path": str(params_path),
                    "estimated_rgb": payload.get("estimated_rgb") or [128, 130, 132],
                    "verification_count": 1,
                },
            )

        monkeypatch.setattr(
            "api.routers.single_stage.update_saved_stage_a_material_archive_metadata",
            _stub_update_saved_stage_a_material_archive_metadata,
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.patch(
                "/api/extractor/gradient-card-materials/stub_material_v1",
                json=payload,
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["material"]["material_name"] == payload["material_name"]

        records = _records_for_event(
            caplog,
            "extractor_update_gradient_card_material_done",
        )
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.directory_name == "stub_material_v1"
        assert record.material_name == payload["material_name"]
        assert record.metadata_keys_updated == expected_count
