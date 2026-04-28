"""Integration tests for LUT router structured log canaries."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.dependencies import get_session_store
from api.schemas.lut import LutInfoResponseV2, PaletteEntrySchema
from config import LUTMetadata, PaletteEntry
from utils.lut_manager import LUTManager


def _client() -> TestClient:
    app = create_app()
    return TestClient(app)


def _client_with_store(store: object) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session_store] = lambda: store
    return TestClient(app)


def _capture_lut_logger(caplog: pytest.LogCaptureFixture) -> logging.Logger:
    target_logger = logging.getLogger("lumina.api.routers.lut")
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


def _metadata(color_mode: str = "8-Color Max") -> LUTMetadata:
    return LUTMetadata(
        color_mode=color_mode,
        palette=[
            PaletteEntry(
                color="White",
                material="PLA",
                hex_color="#FFFFFF",
                color_name="White",
            ),
            PaletteEntry(
                color="Red",
                material="PLA",
                hex_color="#FF0000",
                color_name="Red",
            ),
        ],
    )


def _axis_range(min_value: float = 0.0, max_value: float = 255.0) -> SimpleNamespace:
    return SimpleNamespace(min=min_value, max=max_value)


def _plot_point() -> SimpleNamespace:
    return SimpleNamespace(
        x=1.0,
        y=2.0,
        hex_color="#FFFFFF",
        rgb=[255, 255, 255],
        label="White",
    )


def _plot_point_3d() -> SimpleNamespace:
    return SimpleNamespace(
        l=100.0,
        a=0.0,
        b=0.0,
        hex_color="#FFFFFF",
        rgb=[255, 255, 255],
        label="White",
    )


def _lut_detail() -> SimpleNamespace:
    return SimpleNamespace(
        name="detail-lut",
        path="detail-lut.json",
        fingerprint="abc123",
        manufacturer="Aliz",
        manufacturer_source="filename",
        material_type="PLA",
        material_source="filename",
        color_mode="4-Color",
        color_count=4,
        source_kind="legacy_lookup",
        schema_version="1.0",
        capabilities=["custom_recipe"],
        supported_modes=[],
        raw_metadata={"color_mode": "4-Color"},
        palette=[],
        coverage_stats=SimpleNamespace(
            entry_count=2,
            plotted_point_count=1,
            l_range=_axis_range(),
            a_range=_axis_range(-128.0, 127.0),
            b_range=_axis_range(-128.0, 127.0),
            r_range=_axis_range(),
            g_range=_axis_range(),
            b_rgb_range=_axis_range(),
        ),
        lab_points=[_plot_point()],
        lab_points_3d=[_plot_point_3d()],
        lab_hull=[(1.0, 2.0)],
        rgb_points=[_plot_point()],
        max_color_layers=5,
        layer_height_mm=0.08,
        line_width_mm=0.42,
        base_layers=10,
        base_channel_idx=0,
        layer_order="Top2Bottom",
    )


def _keyed_json_bytes() -> bytes:
    return (
        b'{"schema_version":"keyed-v1","color_mode":"4-Color (RYBW)",'
        b'"palette":{"White":{"material":"PLA","hex_color":"#FFFFFF"},'
        b'"Red":{"material":"PLA","hex_color":"#FF0000"}},'
        b'"entries":[{"rgb":[255,255,255],"recipe":["White"]}]}'
    )


def _lut_info(*, source_kind: str = "lut") -> LutInfoResponseV2:
    return LutInfoResponseV2(
        name="session-lut",
        color_mode="4-Color",
        color_count=2,
        palette=[
            PaletteEntrySchema(
                color="White",
                material="PLA",
                hex_color="#FFFFFF",
                color_name="White",
            ),
            PaletteEntrySchema(
                color="Red",
                material="PLA",
                hex_color="#FF0000",
                color_name="Red",
            ),
        ],
        source_kind=source_kind,
    )


class TestLutMergeCanary:
    def test_merge_luts_logs_sessionless_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client = _client()
        monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(tmp_path))

        def _stub_get_lut_path(name: str) -> str | None:
            paths = {
                "primary": str(tmp_path / "primary.json"),
                "secondary": str(tmp_path / "secondary.json"),
            }
            return paths.get(name)

        def _stub_detect_color_mode(path: str) -> tuple[str, int]:
            if path.endswith("primary.json"):
                return "8-Color Max", 2
            return "4-Color", 2

        def _stub_load_lut_with_stacks(
            _path: str,
            _mode: str,
        ) -> tuple[np.ndarray, np.ndarray]:
            return (
                np.array([[255, 255, 255], [255, 0, 0]], dtype=np.uint8),
                np.zeros((2, 2), dtype=np.int32),
            )

        def _stub_merge_luts(*_args: object, **_kwargs: object):
            return (
                np.array([[255, 255, 255], [255, 0, 0]], dtype=np.uint8),
                np.zeros((2, 2), dtype=np.int32),
                {
                    "total_before": 4,
                    "total_after": 2,
                    "exact_dupes": 1,
                    "similar_removed": 1,
                    "merged_metadata": _metadata(),
                    "warnings": ["duplicate"],
                    "entry_sources": ["primary", "secondary"],
                },
            )

        monkeypatch.setattr(
            "api.routers.lut.LUTManager.get_lut_path",
            _stub_get_lut_path,
        )
        monkeypatch.setattr(
            "api.routers.lut.LUTMerger.detect_color_mode",
            _stub_detect_color_mode,
        )
        monkeypatch.setattr(
            "api.routers.lut.LUTMerger.load_lut_with_stacks",
            _stub_load_lut_with_stacks,
        )
        monkeypatch.setattr(
            "api.routers.lut.LUTMerger.validate_compatibility",
            lambda _modes: (True, ""),
        )
        monkeypatch.setattr(
            "api.routers.lut.LUTManager.load_lut_with_metadata",
            lambda _path: (
                np.zeros((2, 3), dtype=np.uint8),
                np.zeros((2, 2), dtype=np.int32),
                _metadata(),
            ),
        )
        monkeypatch.setattr(
            "api.routers.lut.LUTMerger.merge_luts",
            _stub_merge_luts,
        )
        monkeypatch.setattr(
            "api.routers.lut.LUTMerger.reindex_canonical_stacks_for_palette",
            lambda stacks, _palette: stacks,
        )
        monkeypatch.setattr(
            "api.routers.lut.LUTManager.save_keyed_json",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            "api.routers.lut.LUTMerger.save_merged_lut",
            lambda *_args, **_kwargs: None,
        )
        target_logger = _capture_lut_logger(caplog)

        try:
            response = client.post(
                "/api/lut/merge",
                json={
                    "primary_name": "primary",
                    "secondary_names": ["secondary"],
                    "dedup_threshold": 0.0,
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["filename"].startswith("Merged_")

        records = _records_for_event(caplog, "lut_merge_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.primary_lut_name == "primary"
        assert record.secondary_count == 1
        assert record.merged_filename == body["filename"]
        assert record.total_before == 4
        assert record.total_after == 2
        assert record.exact_dupes == 1
        assert record.similar_removed == 1
        assert record.palette_size == 2
        assert record.warning_count == 1


class TestLutCompareCanary:
    def test_compare_luts_logs_sessionless_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client = _client()

        def _stub_get_lut_path(name: str) -> str | None:
            paths = {
                "lut-a": str(tmp_path / "lut_a.json"),
                "lut-b": str(tmp_path / "lut_b.json"),
            }
            return paths.get(name)

        def _stub_detect_color_mode(path: str) -> tuple[str, int]:
            if path.endswith("lut_a.json"):
                return "4-Color", 2
            return "8-Color Max", 2

        def _stub_load_lut_with_stacks(
            _path: str,
            _mode: str,
        ) -> tuple[np.ndarray, np.ndarray]:
            return (
                np.array([[255, 255, 255], [255, 0, 0]], dtype=np.uint8),
                np.zeros((2, 2), dtype=np.int32),
            )

        def _stub_compare_luts_by_recipe(*_args: object, **_kwargs: object) -> dict:
            return {
                "stats": {
                    "matched_recipe_count": 2,
                    "recipe_coverage_a": 1.0,
                    "recipe_coverage_b": 1.0,
                    "mean_delta_e00": 0.5,
                    "median_delta_e00": 0.5,
                    "p95_delta_e00": 0.5,
                    "max_delta_e00": 0.5,
                    "identical_rgb_count": 1,
                    "recipes_only_in_a": 0,
                    "recipes_only_in_b": 0,
                },
                "warnings": ["comparison warning"],
                "worst_diffs": [
                    {
                        "recipe": ["White", "Red"],
                        "rgb_a": [255, 255, 255],
                        "rgb_b": [255, 0, 0],
                        "hex_a": "#FFFFFF",
                        "hex_b": "#FF0000",
                        "delta_e00": 0.5,
                    }
                ],
            }

        monkeypatch.setattr(
            "api.routers.lut.LUTManager.get_lut_path",
            _stub_get_lut_path,
        )
        monkeypatch.setattr(
            "api.routers.lut.LUTMerger.detect_color_mode",
            _stub_detect_color_mode,
        )
        monkeypatch.setattr(
            "api.routers.lut.LUTMerger.load_lut_with_stacks",
            _stub_load_lut_with_stacks,
        )
        monkeypatch.setattr(
            "api.routers.lut.LUTManager.load_lut_with_metadata",
            lambda _path: (
                np.zeros((2, 3), dtype=np.uint8),
                np.zeros((2, 2), dtype=np.int32),
                _metadata(),
            ),
        )
        monkeypatch.setattr(
            "api.routers.lut.LUTMerger.compare_luts_by_recipe",
            _stub_compare_luts_by_recipe,
        )
        monkeypatch.setattr(
            "api.routers.lut.LUTMerger.validate_print_params",
            lambda _metadata_items: (True, ["print warning"]),
        )
        target_logger = _capture_lut_logger(caplog)

        try:
            response = client.post(
                "/api/lut/compare",
                json={
                    "lut_a_name": "lut-a",
                    "lut_b_name": "lut-b",
                    "top_n": 5,
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["stats"]["matched_recipe_count"] == 2

        records = _records_for_event(caplog, "lut_compare_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.lut_a_name == "lut-a"
        assert record.lut_b_name == "lut-b"
        assert record.lut_a_mode == "4-Color"
        assert record.lut_b_mode == "8-Color Max"
        assert record.matched_recipe_count == 2
        assert record.warning_count == 3
        assert record.top_n == 5
        assert record.worst_diffs_count == 1


class TestLutDetailsCanary:
    def test_get_lut_details_logs_sessionless_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client = _client()
        service = SimpleNamespace(
            get_lut_details=lambda lut_name: _lut_detail(),
        )
        monkeypatch.setattr(
            "api.routers.lut._resolve_lut_details_service",
            lambda: service,
        )
        target_logger = _capture_lut_logger(caplog)

        try:
            response = client.get("/api/lut/detail-lut/details")
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "detail-lut"
        assert body["color_count"] == 4
        assert body["coverage_stats"]["entry_count"] == 2

        records = _records_for_event(caplog, "lut_details_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.lut_name == "detail-lut"
        assert record.color_mode == "4-Color"
        assert record.color_count == 4
        assert record.entry_count == 2
        assert record.lab_points_count == 1
        assert record.rgb_points_count == 1
        assert record.manufacturer == "Aliz"
        assert record.source_kind == "legacy_lookup"


class TestLutUploadCanary:
    def test_upload_lut_logs_sessionless_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client = _client()
        monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(tmp_path))
        payload = _keyed_json_bytes()
        target_logger = _capture_lut_logger(caplog)

        try:
            response = client.post(
                "/api/lut/upload",
                files={
                    "file": (
                        "synthetic_lut.json",
                        payload,
                        "application/json",
                    )
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["name"] == "Custom - synthetic_lut"

        records = _records_for_event(caplog, "lut_upload_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.original_filename == "synthetic_lut.json"
        assert record.file_extension == ".json"
        assert record.dest_filename == "synthetic_lut.json"
        assert record.display_name == "Custom - synthetic_lut"
        assert record.file_size_bytes == len(payload)
        assert record.was_converted is False


class TestLutSessionInfoCanary:
    def test_session_lut_info_logs_filesystem_branch_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        lut_path = tmp_path / "session_lut.json"
        lut_path.write_text("{}", encoding="utf-8")
        store = SimpleNamespace(
            get=lambda session_id: {
                "lut_path": str(lut_path),
                "lut_name": "session-lut",
            }
            if session_id == "test-sess-fs"
            else None
        )
        client = _client_with_store(store)
        monkeypatch.setattr(
            "api.routers.lut._build_lut_info_from_path",
            lambda _path, _display_name: _lut_info(source_kind="lut"),
        )
        target_logger = _capture_lut_logger(caplog)

        try:
            response = client.get("/api/lut/session/test-sess-fs/info")
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["source_kind"] == "lut"

        records = _records_for_event(caplog, "lut_session_info_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == "test-sess-fs"
        assert record.lut_name == "session-lut"
        assert record.color_mode == "4-Color"
        assert record.color_count == 2
        assert record.source_kind == "lut"
        assert record.palette_size == 2

    def test_session_lut_info_logs_material_archive_branch_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store = SimpleNamespace(
            get=lambda session_id: {
                "material_source": "material_archive",
                "selected_materials": ["red"],
                "preview_cache": {
                    "slot_names": ["Red PLA"],
                    "preview_colors": {0: "#FF0000"},
                },
            }
            if session_id == "test-sess-ma"
            else None
        )
        client = _client_with_store(store)
        monkeypatch.setattr(
            "api.routers.lut._build_material_archive_lut_info",
            lambda _session_data: _lut_info(source_kind="material_archive"),
        )
        target_logger = _capture_lut_logger(caplog)

        try:
            response = client.get("/api/lut/session/test-sess-ma/info")
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        body = response.json()
        assert body["source_kind"] == "material_archive"

        records = _records_for_event(caplog, "lut_session_info_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert record.session_id == "test-sess-ma"
        assert record.lut_name == "session-lut"
        assert record.color_mode == "4-Color"
        assert record.color_count == 2
        assert record.source_kind == "material_archive"
        assert record.palette_size == 2
