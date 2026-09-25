"""Integration tests for single-stage pt2 structured log canaries."""

from __future__ import annotations

import concurrent.futures
import json
import logging
import threading
import time
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
import numpy as np

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from api.routers.single_stage import (
    MATERIAL_SOLVER_CACHE_BUILD_FAILED_DETAIL,
    MATERIAL_SOLVER_RUNTIME_BUILD_FAILED_DETAIL,
    _validate_candidate_budget,
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
        }
    )
    return data


def _solver_runtime_form_data() -> dict[str, str]:
    return {
        "material_directory_names": json.dumps(
            ["stub_material_a", "stub_material_b"]
        ),
        "layer_count": "8",
        "layer_height_mm": "0.04",
        "substrate": "white",
        "candidate_budget": "32",
    }


def _solver_runtime_metadata(
    *,
    palette_hash: str = "stub_hash",
    layer_count: int = 8,
    layer_height_mm: float = 0.04,
    substrate: str = "white",
    candidate_budget: int = 32,
) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "mode": "candidate_hybrid",
        "palette_hash": palette_hash,
        "canonical_materials": [
            {"directory_name": "stub_material_a"},
            {"directory_name": "stub_material_b"},
        ],
        "layer_count": layer_count,
        "layer_height_mm": layer_height_mm,
        "substrate": substrate,
        "grid_resolution": 64,
        "lab_grid_resolution": 64,
        "candidate_budget": candidate_budget,
        "candidate_count": 32,
        "candidate_pool_multiplier": 2,
        "batch_recipe_count": 524288,
        "seed": 0,
        "inverse_refinement": {
            "enabled": True,
            "max_refine_materials": 8,
            "max_refine_top_suffixes": 4096,
            "max_refine_bottom_prefixes": 4096,
            "refine_bottom_neighbors": 2,
        },
        "built_at": "2024-01-01T00:00:00",
    }


def test_material_solver_runtime_candidate_budget_accepts_64m_limit() -> None:
    _validate_candidate_budget(67_108_864)

    with pytest.raises(HTTPException):
        _validate_candidate_budget(67_108_865)


def _axis_range_stub(min_value: float, max_value: float) -> SimpleNamespace:
    return SimpleNamespace(min=min_value, max=max_value)


def _runtime_details_stub() -> SimpleNamespace:
    coverage_stats = SimpleNamespace(
        entry_count=32,
        plotted_point_count=2,
        l_range=_axis_range_stub(10.0, 90.0),
        a_range=_axis_range_stub(-20.0, 30.0),
        b_range=_axis_range_stub(-10.0, 40.0),
        r_range=_axis_range_stub(1.0, 200.0),
        g_range=_axis_range_stub(2.0, 210.0),
        b_rgb_range=_axis_range_stub(3.0, 220.0),
    )
    lab_points = [
        SimpleNamespace(
            x=1.0,
            y=2.0,
            hex_color="#010203",
            rgb=(1, 2, 3),
            label="1",
        ),
        SimpleNamespace(
            x=3.0,
            y=4.0,
            hex_color="#040506",
            rgb=(4, 5, 6),
            label="2",
        ),
    ]
    lab_points_3d = [
        SimpleNamespace(
            l=10.0,
            a=1.0,
            b=2.0,
            hex_color="#010203",
            rgb=(1, 2, 3),
            label="1",
        ),
        SimpleNamespace(
            l=20.0,
            a=3.0,
            b=4.0,
            hex_color="#040506",
            rgb=(4, 5, 6),
            label="2",
        ),
    ]
    return SimpleNamespace(
        palette_hash="stub_hash",
        layer_count=8,
        layer_height_mm=0.04,
        substrate="white",
        grid_resolution=64,
        valid_cell_count=32,
        total_cell_count=32,
        candidate_budget=32,
        candidate_count=32,
        coverage_stats=coverage_stats,
        lab_points=lab_points,
        lab_points_3d=lab_points_3d,
        lab_hull=((1.0, 2.0), (3.0, 4.0), (5.0, 6.0)),
        rgb_points=lab_points,
    )


class _StubSuggestion:
    matched_rgb = np.array([255, 0, 0], dtype=np.uint8)
    delta_e = 1.5
    recipe = np.array([1, 0, 1], dtype=np.int32)


UNTRUSTED_ORIGIN_HEADERS = {"Origin": "https://attacker.example"}
LOCAL_FRONTEND_ORIGIN_HEADERS = {"Origin": "http://localhost:5174"}


def _patch_material_solver_management_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> list[str]:
    calls: list[str] = []
    cache_path = tmp_path / "solver_cache.npz"
    runtime_path = tmp_path / "candidate-runtime.npz"
    cache_path.write_bytes(b"cache bytes")
    runtime_path.write_bytes(b"runtime bytes")

    cache = SimpleNamespace(
        metadata=_solver_cache_metadata(),
        valid_cell_count=200,
        total_cell_count=256,
    )
    runtime = SimpleNamespace(
        metadata=_solver_runtime_metadata(),
        valid_cell_count=32,
    )
    runtime_metadata = SimpleNamespace(
        metadata=_solver_runtime_metadata(),
        cache_file_path=runtime_path,
        cache_file_size_bytes=runtime_path.stat().st_size,
    )

    def _load_multiple_materials(directory_names):
        calls.append("load_multiple_materials")
        return [
            SimpleNamespace(directory_name=name)
            for name in directory_names
        ]

    def _build_solver_cache(*args, **kwargs):
        calls.append("build_material_solver_cache")
        return cache

    def _delete_cached_entry(*args, **kwargs):
        calls.append("delete_cached_entry")
        return True

    def _delete_candidate_runtime(*args, **kwargs):
        calls.append("delete_material_candidate_runtime")
        return True

    def _suggest_colors(*args, **kwargs):
        calls.append("suggest_colors_for_target")
        return [_StubSuggestion()]

    monkeypatch.setattr(
        "api.routers.single_stage.load_multiple_materials",
        _load_multiple_materials,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.fingerprint_palette",
        lambda materials: "stub_hash",
    )
    monkeypatch.setattr(
        "api.routers.single_stage.cache_file_path",
        lambda *args, **kwargs: cache_path,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.load_material_solver_cache",
        lambda *args, **kwargs: cache,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.load_material_solver_cache_with_fallback",
        lambda *args, **kwargs: (cache, 64),
    )
    monkeypatch.setattr(
        "api.routers.single_stage.build_material_solver_cache",
        _build_solver_cache,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.save_material_solver_cache",
        lambda cache: cache_path,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.delete_cached_entry",
        _delete_cached_entry,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.load_material_candidate_runtime_metadata",
        lambda *args, **kwargs: runtime_metadata,
        raising=False,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.load_material_candidate_runtime",
        lambda *args, **kwargs: runtime,
        raising=False,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.build_material_candidate_runtime",
        lambda *args, **kwargs: runtime,
        raising=False,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.save_material_candidate_runtime",
        lambda runtime: runtime_path,
        raising=False,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.delete_material_candidate_runtime",
        _delete_candidate_runtime,
        raising=False,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.build_material_cache_details",
        lambda *args, **kwargs: _runtime_details_stub(),
    )
    monkeypatch.setattr(
        "api.routers.single_stage.build_material_runtime_details",
        lambda *args, **kwargs: _runtime_details_stub(),
        raising=False,
    )
    monkeypatch.setattr(
        "api.routers.single_stage.suggest_colors_for_target",
        _suggest_colors,
    )
    return calls


@pytest.mark.parametrize(
    ("path", "data_factory"),
    [
        ("/api/extractor/material-solver-cache/status", _solver_cache_form_data),
        ("/api/extractor/material-solver-cache/build", _solver_cache_form_data),
        ("/api/extractor/material-solver-cache/delete", _solver_cache_form_data),
        ("/api/extractor/material-solver-cache/details", _solver_cache_form_data),
        (
            "/api/extractor/material-solver-cache/suggest-colors",
            _solver_cache_suggest_form_data,
        ),
        ("/api/extractor/material-solver-runtime/status", _solver_runtime_form_data),
        ("/api/extractor/material-solver-runtime/build", _solver_runtime_form_data),
        ("/api/extractor/material-solver-runtime/delete", _solver_runtime_form_data),
        ("/api/extractor/material-solver-runtime/details", _solver_runtime_form_data),
    ],
)
def test_material_solver_management_posts_reject_untrusted_origin_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    path: str,
    data_factory,
) -> None:
    client, _, _ = _client_with_state()
    calls = _patch_material_solver_management_dependencies(monkeypatch, tmp_path)

    response = client.post(
        path,
        data=data_factory(),
        headers=UNTRUSTED_ORIGIN_HEADERS,
    )

    assert response.status_code == 403
    assert calls == []


@pytest.mark.parametrize(
    ("path", "data_factory"),
    [
        ("/api/extractor/material-solver-cache/status", _solver_cache_form_data),
        ("/api/extractor/material-solver-cache/build", _solver_cache_form_data),
        ("/api/extractor/material-solver-cache/delete", _solver_cache_form_data),
        ("/api/extractor/material-solver-cache/details", _solver_cache_form_data),
        (
            "/api/extractor/material-solver-cache/suggest-colors",
            _solver_cache_suggest_form_data,
        ),
        ("/api/extractor/material-solver-runtime/status", _solver_runtime_form_data),
        ("/api/extractor/material-solver-runtime/build", _solver_runtime_form_data),
        ("/api/extractor/material-solver-runtime/delete", _solver_runtime_form_data),
        ("/api/extractor/material-solver-runtime/details", _solver_runtime_form_data),
    ],
)
def test_material_solver_management_posts_allow_untrusted_origin_for_public_gray_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    path: str,
    data_factory,
) -> None:
    monkeypatch.setenv("LUMINA_ALLOW_PUBLIC_GRAY_API", "1")
    client, _, _ = _client_with_state()
    calls = _patch_material_solver_management_dependencies(monkeypatch, tmp_path)

    response = client.post(
        path,
        data=data_factory(),
        headers=UNTRUSTED_ORIGIN_HEADERS,
    )

    assert response.status_code != 403
    assert calls != []


def test_material_solver_cache_list_rejects_untrusted_origin_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _ = _client_with_state()
    called = False
    private_path = "/Users/min/private/materials/_solver_cache/cache.npz"

    def _list_cached_entries():
        nonlocal called
        called = True
        return [
            {
                **_solver_cache_metadata(),
                "cache_file_size_bytes": 128,
                "cache_file_path": private_path,
            }
        ]

    monkeypatch.setattr(
        "api.routers.single_stage.list_cached_entries",
        _list_cached_entries,
    )

    response = client.get(
        "/api/extractor/material-solver-caches",
        headers=UNTRUSTED_ORIGIN_HEADERS,
    )

    assert response.status_code == 403
    assert called is False


def test_material_solver_cache_list_allows_untrusted_origin_for_public_gray_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_ALLOW_PUBLIC_GRAY_API", "1")
    client, _, _ = _client_with_state()
    called = False
    private_path = "/Users/min/private/materials/_solver_cache/cache.npz"

    def _list_cached_entries():
        nonlocal called
        called = True
        return [
            {
                **_solver_cache_metadata(),
                "cache_file_size_bytes": 128,
                "cache_file_path": private_path,
            }
        ]

    monkeypatch.setattr(
        "api.routers.single_stage.list_cached_entries",
        _list_cached_entries,
    )

    response = client.get(
        "/api/extractor/material-solver-caches",
        headers=UNTRUSTED_ORIGIN_HEADERS,
    )

    assert response.status_code == 200
    assert called is True
    assert private_path not in response.text


def test_material_solver_management_allows_local_frontend_origin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, _, _ = _client_with_state()
    calls = _patch_material_solver_management_dependencies(monkeypatch, tmp_path)

    response = client.post(
        "/api/extractor/material-solver-cache/status",
        data=_solver_cache_form_data(),
        headers=LOCAL_FRONTEND_ORIGIN_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "load_multiple_materials" in calls


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
        for item in body["imported_materials"]:
            assert "archive_path" not in item
            assert "stage_a_params_path" not in item
        assert str(tmp_path / "material_1.json") not in response.text
        assert str(tmp_path / "params_1.json") not in response.text
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
            "api.routers.single_stage.load_material_candidate_runtime",
            lambda *args, **kwargs: None,
            raising=False,
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
    def test_material_solver_cache_build_hides_save_error_detail(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, _, _ = _client_with_state()
        private_path = "/Users/min/private/material-cache/solver-cache.npz"
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

        def _fail_save_cache(_cache):
            raise OSError(f"cannot write {private_path}: permission denied")

        monkeypatch.setattr(
            "api.routers.single_stage.save_material_solver_cache",
            _fail_save_cache,
        )

        response = client.post(
            "/api/extractor/material-solver-cache/build",
            data=_solver_cache_form_data(),
        )

        assert response.status_code == 500
        assert response.json()["detail"] == MATERIAL_SOLVER_CACHE_BUILD_FAILED_DETAIL
        assert private_path not in response.text
        assert "permission denied" not in response.text



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
        assert "cache_file_path" not in body["entry"]
        assert str(cache_path) not in response.text

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


class TestMaterialSolverRuntimeCanary:
    def test_material_solver_runtime_status_cache_miss_logs_canary(
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
            "api.routers.single_stage.load_material_candidate_runtime_metadata",
            lambda *args, **kwargs: None,
            raising=False,
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/material-solver-runtime/status",
                data=_solver_runtime_form_data(),
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["cached"] is False
        assert body["palette_hash"] == "stub_hash"
        assert body["candidate_budget"] == 32
        assert body["entry"] is None

        records = _records_for_event(caplog, "material_solver_runtime_status_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.cached is False
        assert record.palette_hash == "stub_hash"
        assert record.material_count == 2
        assert record.candidate_budget == 32

    def test_material_solver_runtime_status_uses_metadata_without_loading_runtime(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        client, _, _ = _client_with_state()
        cache_path = tmp_path / "candidate-runtime.npz"
        cache_path.write_bytes(b"x" * 64)
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

        def _fail_full_runtime_load(*args, **kwargs):
            raise AssertionError("status endpoint must not load runtime arrays")

        monkeypatch.setattr(
            "api.routers.single_stage.load_material_candidate_runtime",
            _fail_full_runtime_load,
            raising=False,
        )
        monkeypatch.setattr(
            "api.routers.single_stage.load_material_candidate_runtime_metadata",
            lambda *args, **kwargs: SimpleNamespace(
                metadata=_solver_runtime_metadata(),
                cache_file_path=cache_path,
                cache_file_size_bytes=cache_path.stat().st_size,
            ),
            raising=False,
        )

        response = client.post(
            "/api/extractor/material-solver-runtime/status",
            data=_solver_runtime_form_data(),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["cached"] is True
        assert body["entry"]["candidate_count"] == 32
        assert body["entry"]["cache_file_size_bytes"] == 64
        assert "cache_file_path" not in body["entry"]
        assert str(cache_path) not in response.text

    def test_material_solver_runtime_build_logs_sessionless_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, _, _ = _client_with_state()
        cache_path = tmp_path / "candidate-runtime.npz"
        cache_path.write_bytes(b"x" * 64)
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

        seen_configs = []

        def _build_runtime_stub(*args, **kwargs):
            seen_configs.append(kwargs["config"])
            return SimpleNamespace(
                metadata=_solver_runtime_metadata(),
                valid_cell_count=32,
            )

        monkeypatch.setattr(
            "api.routers.single_stage.build_material_candidate_runtime",
            _build_runtime_stub,
            raising=False,
        )
        monkeypatch.setattr(
            "api.routers.single_stage.load_material_candidate_runtime_metadata",
            lambda *args, **kwargs: None,
            raising=False,
        )
        monkeypatch.setattr(
            "api.routers.single_stage.save_material_candidate_runtime",
            lambda runtime: cache_path,
            raising=False,
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/material-solver-runtime/build",
                data=_solver_runtime_form_data(),
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["entry"]["mode"] == "candidate_hybrid"
        assert body["entry"]["candidate_budget"] == 32
        assert body["entry"]["candidate_count"] == 32
        assert body["entry"]["cache_file_size_bytes"] == 64
        assert len(seen_configs) == 1
        assert seen_configs[0].candidate_budget == 32
        assert seen_configs[0].max_refine_top_suffixes == 32_768
        assert seen_configs[0].max_refine_bottom_prefixes == 65_536

        records = _records_for_event(caplog, "material_solver_runtime_build_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.material_count == 2
        assert record.layer_count == 8
        assert record.layer_height_mm == 0.04
        assert record.substrate == "white"
        assert record.candidate_budget == 32
        assert record.candidate_count == 32
        assert record.cache_file_size_bytes == 64

    def test_material_solver_runtime_build_hides_save_error_detail(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, _, _ = _client_with_state()
        private_path = "/Users/min/private/material-runtime/candidate-runtime.npz"
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
            "api.routers.single_stage.load_material_candidate_runtime_metadata",
            lambda *args, **kwargs: None,
            raising=False,
        )
        monkeypatch.setattr(
            "api.routers.single_stage.build_material_candidate_runtime",
            lambda *args, **kwargs: SimpleNamespace(
                metadata=_solver_runtime_metadata(),
                valid_cell_count=32,
            ),
            raising=False,
        )

        def _fail_save_runtime(_runtime):
            raise OSError(f"cannot write {private_path}: permission denied")

        monkeypatch.setattr(
            "api.routers.single_stage.save_material_candidate_runtime",
            _fail_save_runtime,
            raising=False,
        )

        response = client.post(
            "/api/extractor/material-solver-runtime/build",
            data=_solver_runtime_form_data(),
        )

        assert response.status_code == 500
        assert response.json()["detail"] == MATERIAL_SOLVER_RUNTIME_BUILD_FAILED_DETAIL
        assert private_path not in response.text
        assert "permission denied" not in response.text

    def test_material_solver_runtime_build_single_flights_same_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        client, _, _ = _client_with_state()
        cache_path = tmp_path / "candidate-runtime.npz"
        build_started = threading.Event()
        release_build = threading.Event()
        calls_lock = threading.Lock()
        build_call_count = 0

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

        def _metadata_if_saved(*args, **kwargs):
            if not cache_path.exists():
                return None
            return SimpleNamespace(
                metadata=_solver_runtime_metadata(),
                cache_file_path=cache_path,
                cache_file_size_bytes=cache_path.stat().st_size,
            )

        def _build_runtime_stub(*args, **kwargs):
            nonlocal build_call_count
            with calls_lock:
                build_call_count += 1
            build_started.set()
            assert release_build.wait(timeout=5)
            return SimpleNamespace(
                metadata=_solver_runtime_metadata(),
                valid_cell_count=32,
            )

        def _save_runtime_stub(runtime):
            cache_path.write_bytes(b"x" * 64)
            return cache_path

        monkeypatch.setattr(
            "api.routers.single_stage.load_material_candidate_runtime_metadata",
            _metadata_if_saved,
            raising=False,
        )
        monkeypatch.setattr(
            "api.routers.single_stage.build_material_candidate_runtime",
            _build_runtime_stub,
            raising=False,
        )
        monkeypatch.setattr(
            "api.routers.single_stage.save_material_candidate_runtime",
            _save_runtime_stub,
            raising=False,
        )

        def _post_build():
            return client.post(
                "/api/extractor/material-solver-runtime/build",
                data=_solver_runtime_form_data(),
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(_post_build)
            assert build_started.wait(timeout=5)
            second = executor.submit(_post_build)
            time.sleep(0.1)
            release_build.set()
            first_response = first.result(timeout=5)
            second_response = second.result(timeout=5)

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert build_call_count == 1
        assert first_response.json()["entry"]["cache_file_size_bytes"] == 64
        assert second_response.json()["entry"]["cache_file_size_bytes"] == 64

    def test_material_solver_runtime_details_logs_sessionless_canary(
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
            "api.routers.single_stage.load_material_candidate_runtime",
            lambda *args, **kwargs: SimpleNamespace(
                metadata=_solver_runtime_metadata(),
                valid_cell_count=32,
            ),
            raising=False,
        )
        monkeypatch.setattr(
            "api.routers.single_stage.build_material_runtime_details",
            lambda *args, **kwargs: _runtime_details_stub(),
            raising=False,
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/material-solver-runtime/details",
                data={**_solver_runtime_form_data(), "max_points": "512"},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["palette_hash"] == "stub_hash"
        assert body["candidate_budget"] == 32
        assert body["candidate_count"] == 32
        assert body["coverage_stats"]["entry_count"] == 32
        assert len(body["lab_points"]) == 2
        assert len(body["rgb_points"]) == 2

        records = _records_for_event(caplog, "material_solver_runtime_details_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.palette_hash == "stub_hash"
        assert record.material_count == 2
        assert record.candidate_budget == 32
        assert record.candidate_count == 32
        assert record.plotted_point_count == 2

    @pytest.mark.parametrize("deleted", [True, False])
    def test_material_solver_runtime_delete_logs_sessionless_canary(
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
            "api.routers.single_stage.delete_material_candidate_runtime",
            lambda *args, **kwargs: deleted,
            raising=False,
        )
        target_logger = _capture_single_stage_logger(caplog)

        try:
            response = client.post(
                "/api/extractor/material-solver-runtime/delete",
                data=_solver_runtime_form_data(),
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["deleted"] is deleted
        assert body["palette_hash"] == "stub_hash"
        assert body["candidate_budget"] == 32

        records = _records_for_event(caplog, "material_solver_runtime_delete_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.deleted is deleted
        assert record.palette_hash == "stub_hash"
        assert record.candidate_budget == 32


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
        assert "cache_file_path" not in body["entry"]
        assert "solver_cache.npz" not in response.text

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
