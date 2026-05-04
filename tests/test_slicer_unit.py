# -*- coding: utf-8 -*-
"""Unit tests for slicer detection and launch (core/slicer.py, api/routers/slicer.py).

Validates registry scanning, slicer detection, launch logic,
Pydantic schema validation, and REST endpoint behaviour.
Requirements: 1.3, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.6
"""

import os
import plistlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.schemas.slicer import (
    SlicerDetectResponse,
    SlicerCustomPathRequest,
    SlicerCustomPathResponse,
    SlicerInfo,
    SlicerLaunchRequest,
    SlicerLaunchResponse,
)
from core.slicer import (
    DetectedSlicer,
    _match_slicer_id,
    detect_installed_slicers,
    launch_slicer,
    scan_registry,
    scan_macos_app_bundles,
    validate_custom_slicer_path,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app():
    """Build a minimal FastAPI app with only the slicer router."""
    from fastapi import FastAPI
    from api.routers.slicer import router

    app = FastAPI()
    app.include_router(router)
    return app


def _make_client() -> TestClient:
    return TestClient(_make_app())


def _make_macos_app(root: Path, app_name: str, info: dict) -> Path:
    app_path = root / app_name
    contents_path = app_path / "Contents"
    contents_path.mkdir(parents=True)
    with (contents_path / "Info.plist").open("wb") as handle:
        plistlib.dump(info, handle)
    return app_path


# =========================================================================
# 1. scan_registry — non-Windows returns empty list (Requirement 1.3)
# =========================================================================


class TestScanRegistry:
    """scan_registry() must return [] on non-Windows platforms."""

    @patch("core.slicer.platform.system", return_value="Linux")
    def test_scan_registry_non_windows_linux(self, _mock_sys):
        assert scan_registry() == []

    @patch("core.slicer.platform.system", return_value="Darwin")
    def test_scan_registry_non_windows_darwin(self, _mock_sys):
        assert scan_registry() == []


class TestMacOSAppScanning:
    """macOS .app bundle detection and custom-path validation."""

    @patch("core.slicer.platform.system", return_value="Linux")
    def test_scan_macos_app_bundles_non_darwin_returns_empty(self, _mock_sys, tmp_path):
        assert scan_macos_app_bundles(search_roots=[tmp_path], include_spotlight=False) == []

    @patch("core.slicer.platform.system", return_value="Darwin")
    def test_scan_macos_app_bundles_finds_known_app(self, _mock_sys, tmp_path):
        app_path = _make_macos_app(
            tmp_path,
            "Bambu Studio.app",
            {
                "CFBundleName": "Bambu Studio",
                "CFBundleDisplayName": "Bambu Studio",
                "CFBundleIdentifier": "com.bambulab.bambu-studio",
            },
        )

        result = scan_macos_app_bundles(search_roots=[tmp_path], include_spotlight=False)

        assert len(result) == 1
        assert result[0].id == "bambu_studio"
        assert result[0].exe_path == str(app_path.resolve())
        assert result[0].source == "macos_app"

    @pytest.mark.parametrize(
        ("app_name", "info", "expected_id"),
        [
            (
                "OrcaSlicer.app",
                {
                    "CFBundleName": "OrcaSlicer",
                    "CFBundleIdentifier": "io.github.softfever.OrcaSlicer",
                },
                "orca_slicer",
            ),
            (
                "Snapmaker Orca.app",
                {
                    "CFBundleDisplayName": "Snapmaker Orca",
                    "CFBundleIdentifier": "com.snapmaker.SnapmakerOrca",
                },
                "snapmaker_orca",
            ),
            (
                "ElegooSlicer.app",
                {
                    "CFBundleName": "ElegooSlicer",
                    "CFBundleIdentifier": "com.elegoo.ElegooSlicer",
                },
                "elegoo_slicer",
            ),
            (
                "Anycubic Slicer Next.app",
                {
                    "CFBundleName": "Anycubic Slicer Next",
                    "CFBundleIdentifier": "com.anycubic.AnycubicSlicerNext",
                },
                "anycubic_slicer_next",
            ),
        ],
    )
    @patch("core.slicer.platform.system", return_value="Darwin")
    def test_scan_macos_app_bundles_finds_orca_family_apps(
        self,
        _mock_sys,
        tmp_path,
        app_name,
        info,
        expected_id,
    ):
        _make_macos_app(tmp_path, app_name, info)

        result = scan_macos_app_bundles(search_roots=[tmp_path], include_spotlight=False)

        assert [slicer.id for slicer in result] == [expected_id]

    @patch("core.slicer.platform.system", return_value="Darwin")
    def test_validate_custom_slicer_path_accepts_known_app(self, _mock_sys, tmp_path):
        app_path = _make_macos_app(
            tmp_path,
            "OrcaSlicer.app",
            {
                "CFBundleName": "OrcaSlicer",
                "CFBundleIdentifier": "io.github.softfever.OrcaSlicer",
            },
        )

        result = validate_custom_slicer_path(str(app_path))

        assert result is not None
        assert result.id == "orca_slicer"
        assert result.exe_path == str(app_path.resolve())
        assert result.source == "custom_macos_app"

    @patch("core.slicer.platform.system", return_value="Darwin")
    def test_validate_custom_slicer_path_rejects_unknown_app(self, _mock_sys, tmp_path):
        app_path = _make_macos_app(
            tmp_path,
            "Notes.app",
            {"CFBundleName": "Notes", "CFBundleIdentifier": "com.apple.Notes"},
        )

        assert validate_custom_slicer_path(str(app_path)) is None


# =========================================================================
# 2. detect_installed_slicers — mock data (Requirement 1.3, 1.5)
# =========================================================================


class TestDetectInstalledSlicers:
    """detect_installed_slicers() filters out entries with invalid exe_path."""

    @patch("core.slicer.platform.system", return_value="Windows")
    def test_filters_invalid_paths(self, _mock_sys, tmp_path):
        real_exe = tmp_path / "bambu.exe"
        real_exe.write_text("fake")

        mock_results = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path=str(real_exe)),
            DetectedSlicer(id="orca_slicer", display_name="OrcaSlicer", exe_path="/nonexistent/orca.exe"),
        ]

        with patch("core.slicer.scan_registry", return_value=mock_results):
            result = detect_installed_slicers()

        assert len(result) == 1
        assert result[0].id == "bambu_studio"

    @patch("core.slicer.platform.system", return_value="Windows")
    def test_returns_empty_when_all_invalid(self, _mock_sys):
        mock_results = [
            DetectedSlicer(id="x", display_name="X", exe_path="/no/such/file.exe"),
        ]
        with patch("core.slicer.scan_registry", return_value=mock_results):
            result = detect_installed_slicers()
        assert result == []

    @patch("core.slicer.platform.system", return_value="Windows")
    def test_returns_empty_when_scan_empty(self, _mock_sys):
        with patch("core.slicer.scan_registry", return_value=[]):
            result = detect_installed_slicers()
        assert result == []


class TestKnownSlicerMatches:
    """Known registry names map to the configured slicer IDs."""

    def test_anycubic_display_name_matches_anycubic_slicer_next(self):
        assert _match_slicer_id("Anycubic Slicer Next 1.3.9.4") == (
            "anycubic_slicer_next",
            "Anycubic Slicer Next",
        )


# =========================================================================
# 3. launch_slicer — success / failure scenarios (Requirements 2.2-2.5)
# =========================================================================


class TestLaunchSlicer:
    """launch_slicer() success and failure paths."""

    def test_success(self, tmp_path):
        """Mock Popen, verify (True, message). Requirement 2.4"""
        f = tmp_path / "model.3mf"
        f.write_text("data")
        slicers = [DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe")]

        with patch("core.slicer.subprocess.Popen") as mock_popen:
            ok, msg = launch_slicer("bambu_studio", str(f), slicers)

        assert ok is True
        assert "Bambu Studio" in msg
        mock_popen.assert_called_once()

    @patch("core.slicer.platform.system", return_value="Darwin")
    def test_macos_app_launch_uses_open_a(self, _mock_sys, tmp_path):
        f = tmp_path / "model.3mf"
        f.write_text("data")
        slicers = [
            DetectedSlicer(
                id="bambu_studio",
                display_name="Bambu Studio",
                exe_path="/Applications/Bambu Studio.app",
                source="macos_app",
            )
        ]

        with patch("core.slicer.subprocess.Popen") as mock_popen:
            ok, msg = launch_slicer("bambu_studio", str(f), slicers)

        assert ok is True
        assert "Bambu Studio" in msg
        mock_popen.assert_called_once_with(
            ["open", "-a", "/Applications/Bambu Studio.app", str(f)]
        )

    def test_unknown_slicer_id(self, tmp_path):
        """Unknown slicer_id → (False, error). Requirement 2.2"""
        f = tmp_path / "model.3mf"
        f.write_text("data")
        slicers = [DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe")]

        ok, msg = launch_slicer("unknown_slicer", str(f), slicers)
        assert ok is False
        assert "not found" in msg.lower()

    def test_file_not_found(self):
        """Non-existent file_path → (False, error). Requirement 2.3"""
        slicers = [DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe")]
        ok, msg = launch_slicer("bambu_studio", "/no/such/file.3mf", slicers)
        assert ok is False
        assert "does not exist" in msg.lower() or "not exist" in msg.lower()

    def test_process_error(self, tmp_path):
        """Popen raises exception → (False, error). Requirement 2.5"""
        f = tmp_path / "model.3mf"
        f.write_text("data")
        slicers = [DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe")]

        with patch("core.slicer.subprocess.Popen", side_effect=OSError("permission denied")):
            ok, msg = launch_slicer("bambu_studio", str(f), slicers)

        assert ok is False
        assert "permission denied" in msg.lower() or "failed" in msg.lower()


# =========================================================================
# 4. Pydantic model validation (Requirements 6.1-6.6)
# =========================================================================


class TestPydanticModels:
    """Pydantic schema validation for slicer models."""

    def test_slicer_info_valid(self):
        info = SlicerInfo(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe")
        assert info.id == "bambu_studio"
        assert info.display_name == "Bambu Studio"

    def test_slicer_info_empty_id_rejected(self):
        """id with min_length=1 rejects empty string. Requirement 6.5"""
        with pytest.raises(ValidationError):
            SlicerInfo(id="", display_name="X", exe_path="C:\\x.exe")

    def test_launch_request_valid(self):
        req = SlicerLaunchRequest(slicer_id="bambu_studio", file_path="/tmp/model.3mf")
        assert req.slicer_id == "bambu_studio"

    def test_custom_path_models_valid(self):
        req = SlicerCustomPathRequest(path="/Applications/Bambu Studio.app")
        resp = SlicerCustomPathResponse(
            status="success",
            message="ok",
            slicer=SlicerInfo(
                id="bambu_studio",
                display_name="Bambu Studio",
                exe_path="/Applications/Bambu Studio.app",
                source="custom_macos_app",
            ),
        )

        assert req.path.endswith(".app")
        assert resp.slicer is not None
        assert resp.slicer.source == "custom_macos_app"

    def test_launch_request_empty_path_rejected(self):
        """file_path with min_length=1 rejects empty string. Requirement 6.6"""
        with pytest.raises(ValidationError):
            SlicerLaunchRequest(slicer_id="bambu_studio", file_path="")

    def test_detect_response_defaults_to_empty_list(self):
        resp = SlicerDetectResponse()
        assert resp.slicers == []

    def test_launch_response_valid(self):
        resp = SlicerLaunchResponse(status="success", message="ok")
        assert resp.status == "success"


# =========================================================================
# 5. Router endpoint tests (Requirements 3.1, 3.2, 3.6)
# =========================================================================


class TestRouterEndpoints:
    """FastAPI TestClient tests for slicer router."""

    def test_detect_endpoint_returns_200(self):
        """GET /api/slicer/detect returns 200 with slicer list. Requirement 3.1"""
        client = _make_client()
        mock_slicers = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe"),
        ]
        with patch("api.routers.slicer.detect_installed_slicers", return_value=mock_slicers):
            resp = client.get("/api/slicer/detect")

        assert resp.status_code == 200
        data = resp.json()
        assert "slicers" in data
        assert len(data["slicers"]) == 1
        assert data["slicers"][0]["id"] == "bambu_studio"

    def test_detect_endpoint_empty(self):
        """GET /api/slicer/detect with no slicers returns empty list."""
        client = _make_client()
        with patch("api.routers.slicer.detect_installed_slicers", return_value=[]):
            resp = client.get("/api/slicer/detect")

        assert resp.status_code == 200
        assert resp.json()["slicers"] == []

    def test_custom_path_validate_success(self):
        client = _make_client()
        slicer = DetectedSlicer(
            id="bambu_studio",
            display_name="Bambu Studio",
            exe_path="/Applications/Bambu Studio.app",
            source="custom_macos_app",
        )

        with patch("api.routers.slicer.validate_custom_slicer_path", return_value=slicer):
            resp = client.post(
                "/api/slicer/custom-path/validate",
                json={"path": "/Applications/Bambu Studio.app"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["slicer"]["source"] == "custom_macos_app"

    def test_custom_path_validate_failure(self):
        client = _make_client()

        with patch("api.routers.slicer.validate_custom_slicer_path", return_value=None):
            resp = client.post(
                "/api/slicer/custom-path/validate",
                json={"path": "/Applications/Notes.app"},
            )

        assert resp.status_code == 400
        assert resp.json()["status"] == "error"

    def test_launch_success(self, tmp_path):
        """POST /api/slicer/launch with valid data returns success. Requirement 3.2"""
        f = tmp_path / "model.3mf"
        f.write_text("data")
        launch_copy = tmp_path / "launch_copy.3mf"
        launch_copy.write_text("data")

        client = _make_client()
        mock_slicers = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe"),
        ]
        with patch("api.routers.slicer.detect_installed_slicers", return_value=mock_slicers), patch(
            "api.routers.slicer._create_launch_copy",
            return_value=str(launch_copy),
        ) as mock_copy, patch(
            "api.routers.slicer.launch_slicer",
            return_value=(True, "Opened in Bambu Studio"),
        ) as mock_launch:
            resp = client.post(
                "/api/slicer/launch",
                json={
                    "slicer_id": "bambu_studio",
                    "file_path": str(f),
                },
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        mock_copy.assert_called_once()
        mock_launch.assert_called_once_with("bambu_studio", str(launch_copy), mock_slicers)

    def test_launch_uses_valid_custom_path(self, tmp_path):
        f = tmp_path / "model.3mf"
        f.write_text("data")
        launch_copy = tmp_path / "launch_copy.3mf"
        launch_copy.write_text("data")
        client = _make_client()
        auto_slicers = []
        custom_slicer = DetectedSlicer(
            id="bambu_studio",
            display_name="Bambu Studio",
            exe_path="/Applications/Bambu Studio.app",
            source="custom_macos_app",
        )

        with patch("api.routers.slicer.detect_installed_slicers", return_value=auto_slicers), patch(
            "api.routers.slicer.validate_custom_slicer_path",
            return_value=custom_slicer,
        ), patch(
            "api.routers.slicer._create_launch_copy",
            return_value=str(launch_copy),
        ), patch(
            "api.routers.slicer.launch_slicer",
            return_value=(True, "Opened in Bambu Studio"),
        ) as mock_launch:
            resp = client.post(
                "/api/slicer/launch",
                json={
                    "slicer_id": "bambu_studio",
                    "file_path": str(f),
                    "slicer_path": "/Applications/Bambu Studio.app",
                },
            )

        assert resp.status_code == 200
        mock_launch.assert_called_once_with("bambu_studio", str(launch_copy), [custom_slicer])

    def test_launch_file_not_found(self):
        """POST with non-existent file returns 400. Requirement 2.3"""
        client = _make_client()
        resp = client.post(
            "/api/slicer/launch",
            json={
                "slicer_id": "bambu_studio",
                "file_path": "/nonexistent/model.3mf",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["status"] == "error"

    def test_launch_invalid_body_returns_422(self):
        """POST with invalid body returns 422. Requirement 3.6"""
        client = _make_client()
        resp = client.post("/api/slicer/launch", json={"bad_field": "value"})
        assert resp.status_code == 422

    def test_launch_empty_body_returns_422(self):
        """POST with empty body returns 422. Requirement 3.6"""
        client = _make_client()
        resp = client.post("/api/slicer/launch", json={})
        assert resp.status_code == 422

    def test_launch_slicer_not_found_returns_404(self, tmp_path):
        """POST with unknown slicer_id returns 404. Requirement 2.2"""
        f = tmp_path / "model.3mf"
        f.write_text("data")

        client = _make_client()
        with patch("api.routers.slicer.detect_installed_slicers", return_value=[]), patch(
            "api.routers.slicer._create_launch_copy",
        ) as mock_copy, patch(
            "api.routers.slicer.launch_slicer",
            return_value=(False, "Slicer not found: unknown"),
        ):
            resp = client.post(
                "/api/slicer/launch",
                json={
                    "slicer_id": "unknown",
                    "file_path": str(f),
                },
            )

        assert resp.status_code == 404
        assert resp.json()["status"] == "error"
        mock_copy.assert_not_called()
