"""Integration tests for miscellaneous router structured log canaries."""

from __future__ import annotations

import asyncio
import io
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import config
from api.app import create_app
from api.dependencies import get_file_registry, get_worker_pool
from api.file_registry import FileRegistry


def _client_with_registry() -> tuple[TestClient, FileRegistry]:
    app = create_app()
    registry = FileRegistry()
    app.dependency_overrides[get_file_registry] = lambda: registry
    return TestClient(app), registry


def _capture_router_logger(
    caplog: pytest.LogCaptureFixture,
    module_name: str,
) -> logging.Logger:
    target_logger = logging.getLogger(f"lumina.api.routers.{module_name}")
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
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


class TestCalibrationGenerateCanary:
    def test_success_emits_sessionless_calibration_generate_done(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        output_path = tmp_path / "calibration.3mf"
        output_path.write_bytes(b"3mf")

        def _stub_generate_calibration_board(**_kwargs):
            return str(output_path), Image.new("RGB", (4, 4), (0, 0, 0)), "ok"

        monkeypatch.setattr(
            "api.routers.calibration.generate_calibration_board",
            _stub_generate_calibration_board,
        )
        client, _registry = _client_with_registry()
        target_logger = _capture_router_logger(caplog, "calibration")
        try:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "4-Color (RYBW)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing": "White",
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["download_url"].startswith("/api/files/")
        assert body["preview_url"].startswith("/api/files/")

        records = _records_for_event(caplog, "calibration_generate_done")
        assert len(records) == 1
        record = records[0]
        assert record.color_mode == "4-Color (RYBW)"
        assert record.download_id == body["download_url"].rsplit("/", 1)[-1]
        assert record.preview_id == body["preview_url"].rsplit("/", 1)[-1]
        assert record.block_size_mm == 5.0
        assert record.gap_mm == 0.84
        assert record.backing_color == "White"
        assert "session_id" not in record.__dict__


class TestCalibrationGenerateSingleStageKitCanary:
    def test_success_emits_sessionless_single_stage_kit_done(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        zip_path = tmp_path / "single_stage.zip"
        manifest_path = tmp_path / "manifest.json"
        zip_path.write_bytes(b"zip")
        manifest_path.write_text("{}", encoding="utf-8")
        jobs = [
            {
                "color": "White",
                "color_name": "White",
                "material": "PLA Basic",
                "substrate_id": "white",
                "substrate_display_name": "White",
                "filename": "white.3mf",
            }
        ]

        def _stub_generate_single_stage_kit(**_kwargs):
            return SimpleNamespace(
                zip_path=str(zip_path),
                manifest_path=str(manifest_path),
                preview_image=Image.new("RGB", (4, 4), (0, 0, 0)),
                jobs=jobs,
                message="ok",
            )

        monkeypatch.setattr(
            "api.routers.calibration.generate_single_stage_kit",
            _stub_generate_single_stage_kit,
        )
        client, _registry = _client_with_registry()
        target_logger = _capture_router_logger(caplog, "calibration")
        try:
            response = client.post(
                "/api/calibration/generate-single-stage-kit",
                json={
                    "palette": [
                        {
                            "color": "White",
                            "material": "PLA Basic",
                            "hex_color": "#FFFFFF",
                            "color_name": "White",
                        }
                    ],
                    "substrate_id": "white",
                    "substrate_display_name": "White",
                    "material_default": "PLA Basic",
                    "layer_height_mm": 0.04,
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["kit_download_url"].startswith("/api/files/")
        assert body["manifest_url"].startswith("/api/files/")
        assert body["preview_url"].startswith("/api/files/")
        assert body["jobs"] == jobs

        records = _records_for_event(
            caplog,
            "calibration_generate_single_stage_kit_done",
        )
        assert len(records) == 1
        record = records[0]
        assert record.kit_id == body["kit_download_url"].rsplit("/", 1)[-1]
        assert record.manifest_id == body["manifest_url"].rsplit("/", 1)[-1]
        assert record.preview_id == body["preview_url"].rsplit("/", 1)[-1]
        assert record.palette_size == 1
        assert record.substrate_id == "white"
        assert record.layer_height_mm == 0.04
        assert record.jobs_count == 1
        assert "session_id" not in record.__dict__


class _FiveColorQueryEngine:
    color_count = 5

    def accepted_selection_lengths(self):
        return (5,)

    def query(self, selected_indices):
        return SimpleNamespace(
            found=True,
            selected_indices=list(selected_indices),
            result_rgb=(1, 2, 3),
            row_index=7,
            message="ok",
            source="stub-source",
        )

    def get_base_colors(self):
        return [
            (255, 255, 255),
            (255, 0, 0),
            (255, 255, 0),
            (0, 128, 255),
            (0, 0, 0),
        ]

    def get_color_names(self):
        return ["White", "Red", "Yellow", "Blue", "Black"]


class _FiveColorBaseColorsEngine(_FiveColorQueryEngine):
    def __init__(self, stack_lut):
        self.stack_lut = stack_lut

    def get_combinations(self):
        if self.stack_lut is None:
            return None
        return self.stack_lut.tolist()


class TestFiveColorQueryCanary:
    def test_success_emits_sessionless_five_color_query_done(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(
            "api.routers.five_color._load_engine",
            lambda lut_name: (_FiveColorQueryEngine(), lut_name),
        )
        client, _registry = _client_with_registry()
        target_logger = _capture_router_logger(caplog, "five_color")
        try:
            response = client.post(
                "/api/five-color/query",
                json={
                    "lut_name": "stub-lut",
                    "selected_indices": [0, 1, 2, 3, 4],
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["found"] is True
        assert body["result_hex"] == "#010203"
        assert body["source"] == "stub-source"

        records = _records_for_event(caplog, "five_color_query_done")
        assert len(records) == 1
        record = records[0]
        assert record.lut_name == "stub-lut"
        assert record.selected_indices_count == 5
        assert record.found is True
        assert record.result_hex == "#010203"
        assert record.source == "stub-source"
        assert "session_id" not in record.__dict__


class TestFiveColorGenerateSwatchCanary:
    def test_success_emits_sessionless_generate_swatch_done(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        swatch_path = tmp_path / "swatch.3mf"
        swatch_path.write_bytes(b"3mf")

        def _stub_generate_recipe_swatch(**_kwargs):
            return str(swatch_path), Image.new("RGB", (4, 4), (0, 0, 0)), "ok"

        monkeypatch.setattr(
            "api.routers.five_color._load_engine",
            lambda lut_name: (_FiveColorQueryEngine(), lut_name),
        )
        monkeypatch.setattr(
            "core.recipe_swatch.generate_recipe_swatch",
            _stub_generate_recipe_swatch,
        )
        client, _registry = _client_with_registry()
        target_logger = _capture_router_logger(caplog, "five_color")
        try:
            response = client.post(
                "/api/five-color/generate-swatch",
                json={
                    "lut_name": "stub-lut",
                    "recipes": [
                        {
                            "selected_indices": [0, 1, 2, 3, 4],
                            "result_hex": "#123456",
                            "base_color_names": [],
                            "base_color_hexes": [],
                        }
                    ],
                    "block_size_mm": 12.5,
                    "gap_mm": 1.5,
                    "cols": 2,
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["download_url"].startswith("/api/files/")
        assert body["preview_url"].startswith("/api/files/")
        assert body["recipe_count"] == 1

        records = _records_for_event(caplog, "five_color_generate_swatch_done")
        assert len(records) == 1
        record = records[0]
        assert record.lut_name == "stub-lut"
        assert record.recipe_count == 1
        assert record.download_id == body["download_url"].rsplit("/", 1)[-1]
        assert record.preview_id == body["preview_url"].rsplit("/", 1)[-1]
        assert record.block_size_mm == 12.5
        assert record.gap_mm == 1.5
        assert record.cols == 2
        assert "session_id" not in record.__dict__


class TestFiveColorBaseColorsCanary:
    def test_success_with_stack_emits_sessionless_base_colors_done(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        engine = _FiveColorBaseColorsEngine(
            np.array([[0, 1, 2, 3, 4]], dtype=np.uint8)
        )
        monkeypatch.setattr(
            "api.routers.five_color._load_engine",
            lambda lut_name: (engine, lut_name),
        )
        client, _registry = _client_with_registry()
        target_logger = _capture_router_logger(caplog, "five_color")
        try:
            response = client.get(
                "/api/five-color/base-colors",
                params={"lut_name": "stub-lut"},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["color_count"] == 5
        assert body["combinations"] == [[0, 1, 2, 3, 4]]

        records = _records_for_event(caplog, "five_color_base_colors_done")
        assert len(records) == 1
        record = records[0]
        assert record.lut_name == "stub-lut"
        assert record.color_count == 5
        assert record.combination_count == 1
        assert record.stack_present is True
        assert "session_id" not in record.__dict__

    def test_success_without_stack_warns_and_emits_base_colors_done(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        engine = _FiveColorBaseColorsEngine(None)
        monkeypatch.setattr(
            "api.routers.five_color._load_engine",
            lambda lut_name: (engine, lut_name),
        )
        client, _registry = _client_with_registry()
        target_logger = _capture_router_logger(caplog, "five_color")
        try:
            response = client.get(
                "/api/five-color/base-colors",
                params={"lut_name": "stub-lut"},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["color_count"] == 5
        assert body["combinations"] is None

        warning_records = _records_for_event(
            caplog,
            "five_color_stack_lut_missing",
        )
        assert len(warning_records) == 1
        assert warning_records[0].lut_name == "stub-lut"
        assert warning_records[0].color_count == 5

        records = _records_for_event(caplog, "five_color_base_colors_done")
        assert len(records) == 1
        record = records[0]
        assert record.lut_name == "stub-lut"
        assert record.color_count == 5
        assert record.combination_count == 0
        assert record.stack_present is False
        assert "session_id" not in record.__dict__


class TestVectorizeImageCanary:
    def test_success_emits_sessionless_vectorize_image_done(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        svg_path = tmp_path / "output.svg"
        svg_path.write_text("<svg/>", encoding="utf-8")
        mock_pool = SimpleNamespace(
            submit=AsyncMock(
                return_value={
                    "svg_path": str(svg_path),
                    "num_shapes": 5,
                    "num_colors": 3,
                    "width": 64,
                    "height": 64,
                    "palette": [
                        [255, 0, 0],
                        [0, 255, 0],
                        [0, 0, 255],
                    ],
                }
            )
        )
        app = create_app()
        registry = FileRegistry()
        app.dependency_overrides[get_file_registry] = lambda: registry
        app.dependency_overrides[get_worker_pool] = lambda: mock_pool
        client = TestClient(app)
        target_logger = _capture_router_logger(caplog, "vectorizer")
        try:
            response = client.post(
                "/api/vectorize",
                files={"image": ("input.png", _png_bytes(), "image/png")},
                data={"params": "{}"},
            )
        finally:
            target_logger.removeHandler(caplog.handler)
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["svg_url"].startswith("/api/files/")
        assert body["num_shapes"] == 5
        assert body["num_colors"] == 3
        assert body["width"] == 64
        assert body["height"] == 64

        records = _records_for_event(caplog, "vectorize_image_done")
        assert len(records) == 1
        record = records[0]
        assert record.svg_file_id == body["svg_url"].rsplit("/", 1)[-1]
        assert record.num_shapes == 5
        assert record.num_colors == 3
        assert record.width == 64
        assert record.height == 64
        assert record.palette_size == 3
        assert "session_id" not in record.__dict__

    @pytest.mark.parametrize("params_value", [[], None, "bad", True, 123])
    def test_non_object_params_return_422_before_worker(
        self,
        params_value: object,
    ) -> None:
        mock_pool = SimpleNamespace(submit=AsyncMock())
        app = create_app()
        app.dependency_overrides[get_worker_pool] = lambda: mock_pool
        client = TestClient(app, raise_server_exceptions=False)
        try:
            response = client.post(
                "/api/vectorize",
                files={"image": ("input.png", _png_bytes(), "image/png")},
                data={"params": json.dumps(params_value)},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422
        assert "params" in response.text
        mock_pool.submit.assert_not_called()

    def test_timeout_returns_504_and_cleans_upload_temp_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path))
        mock_pool = SimpleNamespace(
            submit=AsyncMock(side_effect=asyncio.TimeoutError())
        )
        app = create_app()
        registry = FileRegistry()
        app.dependency_overrides[get_file_registry] = lambda: registry
        app.dependency_overrides[get_worker_pool] = lambda: mock_pool
        client = TestClient(app)
        try:
            response = client.post(
                "/api/vectorize",
                files={"image": ("input.png", _png_bytes(), "image/png")},
                data={"params": "{}"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 504
        assert response.json()["detail"] == "Vectorization timed out"
        assert sorted(tmp_path.iterdir()) == []

    def test_worker_error_cleans_upload_temp_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path))
        mock_pool = SimpleNamespace(
            submit=AsyncMock(side_effect=RuntimeError("vector failed"))
        )
        app = create_app()
        registry = FileRegistry()
        app.dependency_overrides[get_file_registry] = lambda: registry
        app.dependency_overrides[get_worker_pool] = lambda: mock_pool
        client = TestClient(app)
        try:
            response = client.post(
                "/api/vectorize",
                files={"image": ("input.png", _png_bytes(), "image/png")},
                data={"params": "{}"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 500
        assert response.json()["detail"] == "Vectorization failed: vector failed"
        assert sorted(tmp_path.iterdir()) == []

    def test_registry_failure_cleans_upload_and_unregistered_svg(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        class FailingRegistry(FileRegistry):
            def register_path(self, *args: object, **kwargs: object) -> str:
                raise RuntimeError("registry unavailable")

        monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path))
        svg_path = tmp_path / "output.svg"
        svg_path.write_text("<svg/>", encoding="utf-8")
        mock_pool = SimpleNamespace(
            submit=AsyncMock(
                return_value={
                    "svg_path": str(svg_path),
                    "num_shapes": 1,
                    "num_colors": 1,
                    "width": 4,
                    "height": 4,
                    "palette": [],
                }
            )
        )
        app = create_app()
        app.dependency_overrides[get_file_registry] = lambda: FailingRegistry()
        app.dependency_overrides[get_worker_pool] = lambda: mock_pool
        client = TestClient(app)
        try:
            with pytest.raises(RuntimeError, match="registry unavailable"):
                client.post(
                    "/api/vectorize",
                    files={"image": ("input.png", _png_bytes(), "image/png")},
                    data={"params": "{}"},
                )
        finally:
            app.dependency_overrides.clear()

        assert sorted(tmp_path.iterdir()) == []
