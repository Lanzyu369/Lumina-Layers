"""Integration tests for single-stage pt2 structured log canaries."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import numpy as np

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore


def _client_with_state() -> tuple[TestClient, SessionStore, FileRegistry]:
    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    return TestClient(app), store, registry


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


def _solver_cache_metadata(
    *,
    palette_hash: str = "stub_hash",
    layer_count: int = 8,
    layer_height_mm: float = 0.04,
    substrate: str = "white",
    grid_resolution: int = 64,
) -> dict[str, object]:
    return {
        "palette_hash": palette_hash,
        "canonical_materials": [
            {"directory_name": "stub_material_a"},
            {"directory_name": "stub_material_b"},
        ],
        "layer_count": layer_count,
        "layer_height_mm": layer_height_mm,
        "substrate": substrate,
        "grid_resolution": grid_resolution,
        "total_combinations": 256,
        "valid_cell_count": 200,
        "total_cell_count": 256,
        "mean_delta_e": 1.5,
        "max_delta_e": 4.0,
        "build_time_seconds": 1.0,
        "built_at": "2024-01-01T00:00:00",
    }


def _patch_solver_cache_common(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    cache: object | None,
) -> Path:
    npz_path = tmp_path / "solver_cache.npz"
    npz_path.write_bytes(b"cache bytes")
    monkeypatch.setattr(
        "api.routers.single_stage.load_multiple_materials",
        lambda directory_names: [SimpleNamespace(directory_name=name) for name in directory_names],
    )
    monkeypatch.setattr(
        "api.routers.single_stage.fingerprint_palette",
        lambda materials: "stub_hash",
    )
    monkeypatch.setattr(
        "api.routers.single_stage.cache_file_path",
        lambda *args, **kwargs: npz_path,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.load_material_solver_cache",
        lambda *args, **kwargs: cache,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.load_material_solver_cache_with_fallback",
        lambda *args, **kwargs: (cache, 0 if cache is not None else None),
    )
    return npz_path


def _solver_cache_form_data() -> dict[str, str]:
    return {
        "material_directory_names": json.dumps(
            ["stub_material_a", "stub_material_b"]
        ),
        "layer_count": "8",
        "layer_height_mm": "0.04",
        "substrate": "white",
        "grid_resolution": "64",
    }


def _solver_cache_suggest_form_data() -> dict[str, str]:
    data = _solver_cache_form_data()
    data.update(
        {
            "target_hex": "#ff0000",
            "top_k": "3",
            "min_spacing": "1.0",
            "max_combinations": "100000",
        }
    )
    return data


class _StubSuggestion:
    matched_rgb = np.array([255, 0, 0], dtype=np.uint8)
    delta_e = 1.5
    recipe = np.array([1, 0, 1], dtype=np.int32)


class TestExportGradientCardMaterialsCanary:
    def test_export_gradient_card_materials_logs_sessionless_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, _, _ = _client_with_state()
        archive_path = tmp_path / "exported_materials.zip"
        archive_path.write_bytes(b"stub zip")

        def _stub_export_saved_stage_a_material_archives(*, directory_names: list[str]):
            assert directory_names == ["stub_material_a", "stub_material_b"]
            return SimpleNamespace(
                archive_path=str(archive_path),
                download_filename="exported_materials.zip",
                exported_directory_names=["stub_material_a", "stub_material_b"],
            )

        monkeypatch.setattr(
            "api.routers.single_stage.export_saved_stage_a_material_archives",
            _stub_export_saved_stage_a_material_archives,
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/gradient-card-materials/export",
                json={"directory_names": ["stub_material_a", "stub_material_b"]},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["download_url"].startswith("/api/files/")
        assert body["filename"] == "exported_materials.zip"
        assert body["exported_count"] == 2

        records = _records_for_event(
            caplog,
            "extractor_export_gradient_card_materials_done",
        )
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.exported_count == 2
        assert record.download_id == body["download_url"].rsplit("/", 1)[-1]
        assert record.download_filename == "exported_materials.zip"


class TestImportGradientCardMaterialsCanary:
    def test_import_gradient_card_materials_logs_one_sessionless_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, _, _ = _client_with_state()
        calls: list[str] = []

        def _stub_import_saved_stage_a_material_archives(*, archive_path: str):
            calls.append(archive_path)
            index = len(calls)
            return SimpleNamespace(
                imported_materials=[
                    {
                        "directory_name": f"stub_material_v{index}",
                        "material_name": f"Stub V{index}",
                        "archive_path": str(tmp_path / f"material_{index}.json"),
                        "stage_a_params_path": str(tmp_path / f"params_{index}.json"),
                    }
                ],
            )

        monkeypatch.setattr(
            "api.routers.single_stage.import_saved_stage_a_material_archives",
            _stub_import_saved_stage_a_material_archives,
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/gradient-card-materials/import",
                files=[
                    ("archives", ("one.zip", b"zip-one", "application/zip")),
                    ("archives", ("two.zip", b"zip-two", "application/zip")),
                ],
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["imported_count"] == 2
        assert [item["directory_name"] for item in body["imported_materials"]] == [
            "stub_material_v1",
            "stub_material_v2",
        ]
        assert len(calls) == 2

        records = _records_for_event(
            caplog,
            "extractor_import_gradient_card_materials_done",
        )
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.imported_count == 2
        assert record.imported_directory_names_count == 2
        assert record.archives_received == 2


class TestMaterialSolverCacheStatusCanary:
    def test_canary_fires_for_cache_miss(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, _, _ = _client_with_state()
        _patch_solver_cache_common(monkeypatch, tmp_path, cache=None)
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/material-solver-cache/status",
                data=_solver_cache_form_data(),
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["cached"] is False
        assert body["palette_hash"] == "stub_hash"
        assert body["entry"] is None

        records = _records_for_event(caplog, "material_solver_cache_status_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.cached is False
        assert record.palette_hash == "stub_hash"
        assert record.material_count == 2
        assert record.layer_count == 8
        assert record.layer_height_mm == 0.04
        assert record.substrate == "white"
        assert record.grid_resolution == 64


class TestMaterialSolverCacheSuggestColorsCanary:
    def test_canary_fires_for_cache_source(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, _, _ = _client_with_state()
        monkeypatch.setattr(
            "api.routers.single_stage.load_multiple_materials",
            lambda directory_names: [
                SimpleNamespace(directory_name=name) for name in directory_names
            ],
        )
        monkeypatch.setattr(
            "api.routers.single_stage.fingerprint_palette",
            lambda materials: "stub_hash",
        )

        class _StubCache:
            valid_cell_count = 200

            def lookup_top_k(self, *args, **kwargs):
                assert kwargs["top_k"] == 3
                return [_StubSuggestion()]

        monkeypatch.setattr(
            "api.routers.single_stage.load_material_solver_cache",
            lambda *args, **kwargs: _StubCache(),
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/material-solver-cache/suggest-colors",
                data=_solver_cache_suggest_form_data(),
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["source"] == "cache"
        assert body["target_hex"] == "#FF0000"
        assert len(body["suggestions"]) == 1

        records = _records_for_event(
            caplog,
            "material_solver_cache_suggest_colors_done",
        )
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.source == "cache"
        assert record.palette_hash == "stub_hash"
        assert record.material_count == 2
        assert record.target_hex == "#FF0000"
        assert record.suggestions_count == 1
        assert record.top_k == 3

    def test_canary_fires_for_mitm_source(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, _, _ = _client_with_state()
        monkeypatch.setattr(
            "api.routers.single_stage.load_multiple_materials",
            lambda directory_names: [
                SimpleNamespace(directory_name=name) for name in directory_names
            ],
        )
        monkeypatch.setattr(
            "api.routers.single_stage.fingerprint_palette",
            lambda materials: "stub_hash",
        )
        monkeypatch.setattr(
            "api.routers.single_stage.load_material_solver_cache",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            "api.routers.single_stage.suggest_colors_for_target",
            lambda *args, **kwargs: [_StubSuggestion()],
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/material-solver-cache/suggest-colors",
                data=_solver_cache_suggest_form_data(),
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["source"] == "mitm"
        assert body["target_hex"] == "#FF0000"
        assert len(body["suggestions"]) == 1

        records = _records_for_event(
            caplog,
            "material_solver_cache_suggest_colors_done",
        )
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.source == "mitm"
        assert record.palette_hash == "stub_hash"
        assert record.material_count == 2
        assert record.target_hex == "#FF0000"
        assert record.suggestions_count == 1
        assert record.top_k == 3


class TestMaterialSolverCacheBuildCanary:
    def test_material_solver_cache_build_logs_sessionless_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, _, _ = _client_with_state()
        cache_path = tmp_path / "built_cache.npz"
        cache_path.write_bytes(b"x" * 64)
        monkeypatch.setattr(
            "api.routers.single_stage.load_multiple_materials",
            lambda directory_names: [
                SimpleNamespace(directory_name=name) for name in directory_names
            ],
        )
        monkeypatch.setattr(
            "api.routers.single_stage.build_material_solver_cache",
            lambda *args, **kwargs: SimpleNamespace(metadata=_solver_cache_metadata()),
        )
        monkeypatch.setattr(
            "api.routers.single_stage.save_material_solver_cache",
            lambda cache: cache_path,
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/material-solver-cache/build",
                data=_solver_cache_form_data(),
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["entry"]["valid_cell_count"] == 200
        assert body["entry"]["total_cell_count"] == 256
        assert body["entry"]["mean_delta_e"] == 1.5
        assert body["entry"]["cache_file_size_bytes"] == 64

        records = _records_for_event(caplog, "material_solver_cache_build_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.material_count == 2
        assert record.layer_count == 8
        assert record.layer_height_mm == 0.04
        assert record.substrate == "white"
        assert record.grid_resolution == 64
        assert record.valid_cell_count == 200
        assert record.total_cell_count == 256
        assert record.mean_delta_e == 1.5
        assert record.cache_file_size_bytes == 64


class TestMaterialSolverCacheDeleteCanary:
    @pytest.mark.parametrize("deleted", [True, False])
    def test_material_solver_cache_delete_logs_sessionless_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        deleted: bool,
    ) -> None:
        client, _, _ = _client_with_state()
        monkeypatch.setattr(
            "api.routers.single_stage.load_multiple_materials",
            lambda directory_names: [
                SimpleNamespace(directory_name=name) for name in directory_names
            ],
        )
        monkeypatch.setattr(
            "api.routers.single_stage.fingerprint_palette",
            lambda materials: "stub_hash",
        )
        monkeypatch.setattr(
            "api.routers.single_stage.delete_cached_entry",
            lambda *args, **kwargs: deleted,
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/material-solver-cache/delete",
                data=_solver_cache_form_data(),
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["deleted"] is deleted
        assert body["palette_hash"] == "stub_hash"

        records = _records_for_event(caplog, "material_solver_cache_delete_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.deleted is deleted
        assert record.palette_hash == "stub_hash"
        assert record.material_count == 2
        assert record.layer_count == 8
        assert record.layer_height_mm == 0.04
        assert record.substrate == "white"
        assert record.grid_resolution == 64

    def test_canary_fires_for_cache_hit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, _, _ = _client_with_state()
        cache = SimpleNamespace(metadata=_solver_cache_metadata())
        _patch_solver_cache_common(monkeypatch, tmp_path, cache=cache)
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/material-solver-cache/status",
                data=_solver_cache_form_data(),
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["cached"] is True
        assert body["entry"]["valid_cell_count"] == 200

        records = _records_for_event(caplog, "material_solver_cache_status_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.cached is True
        assert record.palette_hash == "stub_hash"
        assert record.material_count == 2
        assert record.layer_count == 8
        assert record.layer_height_mm == 0.04
        assert record.substrate == "white"
        assert record.grid_resolution == 64
