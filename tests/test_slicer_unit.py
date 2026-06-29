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
from api.dependencies import get_file_registry
from api.file_registry import FileRegistry
from api.routers.slicer import (
    SLICER_LAUNCH_COPY_FAILED_MESSAGE,
    SLICER_LAUNCH_FAILED_MESSAGE,
    SLICER_LAUNCH_SOURCE_MISSING_MESSAGE,
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

UNTRUSTED_ORIGIN_HEADERS = {"Origin": "https://attacker.example"}
LOCAL_FRONTEND_ORIGIN_HEADERS = {"Origin": "http://localhost:5174"}

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


def _configure_slicer_output(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
) -> Path:
    """Point slicer launch validation and copies at an isolated output tree."""
    import api.routers.slicer as slicer_router

    output_root = root / "output"
    temp_root = output_root / "temp"
    temp_root.mkdir(parents=True)
    monkeypatch.setattr(slicer_router, "OUTPUT_DIR", str(output_root), raising=False)
    monkeypatch.setattr(slicer_router, "TEMP_DIR", str(temp_root))
    return output_root


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

    @patch("core.slicer.platform.system", return_value="Darwin")
    def test_scan_macos_app_bundles_skips_malformed_info_plist(self, _mock_sys, tmp_path):
        """A bundle with corrupt Info.plist must not abort the entire scan.

        某些 .app 的 Info.plist 损坏会触发 plistlib 未声明的异常（如 ExpatError），
        必须被吞掉以保证 /api/slicer/detect 不被一个坏 bundle 拖垮。
        """
        # Bad bundle: Info.plist contains malformed XML that triggers
        # xml.parsers.expat.ExpatError, which is *not* in plistlib's
        # declared exception set.
        bad_app = tmp_path / "Broken.app"
        (bad_app / "Contents").mkdir(parents=True)
        (bad_app / "Contents" / "Info.plist").write_bytes(
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            b'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            b'<plist version="1.0">\n<dict>\n<key>BadKey</key>\n'
            b'<string>this < is not & valid xml</string>\n'
            b'</dict>\n</plist>\n'
        )

        # Good bundle alongside the bad one: detection must still find it.
        _make_macos_app(
            tmp_path,
            "OrcaSlicer.app",
            {
                "CFBundleName": "OrcaSlicer",
                "CFBundleIdentifier": "io.github.softfever.OrcaSlicer",
            },
        )

        # Must not raise; the bad bundle is silently skipped.
        result = scan_macos_app_bundles(
            search_roots=[tmp_path], include_spotlight=False
        )
        assert [s.id for s in result] == ["orca_slicer"]


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
        info = SlicerInfo(id="bambu_studio", display_name="Bambu Studio")
        assert info.id == "bambu_studio"
        assert info.display_name == "Bambu Studio"
        assert info.exe_path is None

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
        private_path = "/Users/min/Applications/Private Bambu Studio.app"
        mock_slicers = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path=private_path),
        ]
        with patch("api.routers.slicer.detect_installed_slicers", return_value=mock_slicers):
            resp = client.get("/api/slicer/detect")

        assert resp.status_code == 200
        data = resp.json()
        assert "slicers" in data
        assert len(data["slicers"]) == 1
        assert data["slicers"][0]["id"] == "bambu_studio"
        assert data["slicers"][0]["display_name"] == "Bambu Studio"
        assert data["slicers"][0]["exe_path"] is None
        assert private_path not in resp.text

    def test_detect_endpoint_preserves_items_without_exposing_executable_paths(self):
        client = _make_client()
        private_bambu_path = "/Users/min/Applications/Private Bambu Studio.app"
        private_orca_path = "/Users/min/Applications/Private OrcaSlicer.app"
        mock_slicers = [
            DetectedSlicer(
                id="bambu_studio",
                display_name="Bambu Studio",
                exe_path=private_bambu_path,
                source="macos_app",
            ),
            DetectedSlicer(
                id="orca_slicer",
                display_name="OrcaSlicer",
                exe_path=private_orca_path,
                source="macos_app",
            ),
        ]

        with patch("api.routers.slicer.detect_installed_slicers", return_value=mock_slicers):
            resp = client.get("/api/slicer/detect")

        assert resp.status_code == 200
        data = resp.json()
        assert [item["id"] for item in data["slicers"]] == ["bambu_studio", "orca_slicer"]
        assert all(item["exe_path"] is None for item in data["slicers"])
        assert private_bambu_path not in resp.text
        assert private_orca_path not in resp.text

    def test_detect_endpoint_empty(self):
        """GET /api/slicer/detect with no slicers returns empty list."""
        client = _make_client()
        with patch("api.routers.slicer.detect_installed_slicers", return_value=[]):
            resp = client.get("/api/slicer/detect")

        assert resp.status_code == 200
        assert resp.json()["slicers"] == []

    def test_detect_rejects_untrusted_origin_by_default(self):
        client = _make_client()
        with patch(
            "api.routers.slicer.detect_installed_slicers",
            return_value=[],
        ) as detect:
            resp = client.get(
                "/api/slicer/detect",
                headers=UNTRUSTED_ORIGIN_HEADERS,
            )

        assert resp.status_code == 403
        detect.assert_not_called()

    def test_detect_allows_untrusted_origin_for_public_gray_api(self, monkeypatch):
        monkeypatch.setenv("LUMINA_ALLOW_PUBLIC_GRAY_API", "1")
        client = _make_client()
        with patch(
            "api.routers.slicer.detect_installed_slicers",
            return_value=[],
        ):
            resp = client.get(
                "/api/slicer/detect",
                headers=UNTRUSTED_ORIGIN_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["slicers"] == []

    def test_detect_allows_local_frontend_origin(self):
        client = _make_client()
        private_path = "/Applications/Bambu Studio.app"
        slicer = DetectedSlicer(
            id="bambu_studio",
            display_name="Bambu Studio",
            exe_path=private_path,
            source="auto_macos_app",
        )
        with patch(
            "api.routers.slicer.detect_installed_slicers",
            return_value=[slicer],
        ):
            resp = client.get(
                "/api/slicer/detect",
                headers=LOCAL_FRONTEND_ORIGIN_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["slicers"][0]["id"] == "bambu_studio"
        assert data["slicers"][0]["source"] == "auto_macos_app"
        assert data["slicers"][0]["exe_path"] is None
        assert private_path not in resp.text

    def test_custom_path_validate_success(self):
        client = _make_client()
        private_path = "/Users/min/Applications/Private Bambu Studio.app"
        slicer = DetectedSlicer(
            id="bambu_studio",
            display_name="Bambu Studio",
            exe_path=private_path,
            source="custom_macos_app",
        )

        with patch("api.routers.slicer.validate_custom_slicer_path", return_value=slicer):
            resp = client.post(
                "/api/slicer/custom-path/validate",
                json={"path": private_path},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["slicer"]["id"] == "bambu_studio"
        assert data["slicer"]["source"] == "custom_macos_app"
        assert data["slicer"]["exe_path"] is None
        assert private_path not in resp.text

    def test_custom_path_validate_rejects_untrusted_origin_by_default(self):
        client = _make_client()
        validator = MagicMock(return_value=None)
        with patch(
            "api.routers.slicer.validate_custom_slicer_path",
            validator,
        ):
            resp = client.post(
                "/api/slicer/custom-path/validate",
                json={"path": "/Applications/Bambu Studio.app"},
                headers=UNTRUSTED_ORIGIN_HEADERS,
            )

        assert resp.status_code == 403
        validator.assert_not_called()

    def test_custom_path_validate_allows_untrusted_origin_for_public_gray_api(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("LUMINA_ALLOW_PUBLIC_GRAY_API", "1")
        client = _make_client()
        validator = MagicMock(return_value=None)
        with patch(
            "api.routers.slicer.validate_custom_slicer_path",
            validator,
        ):
            resp = client.post(
                "/api/slicer/custom-path/validate",
                json={"path": "/Applications/Bambu Studio.app"},
                headers=UNTRUSTED_ORIGIN_HEADERS,
            )

        assert resp.status_code == 400
        assert resp.json()["status"] == "error"
        validator.assert_called_once()

    def test_custom_path_validate_failure(self):
        client = _make_client()

        with patch("api.routers.slicer.validate_custom_slicer_path", return_value=None):
            resp = client.post(
                "/api/slicer/custom-path/validate",
                json={"path": "/Applications/Notes.app"},
            )

        assert resp.status_code == 400
        assert resp.json()["status"] == "error"

    def test_launch_success(self, tmp_path, monkeypatch):
        """POST /api/slicer/launch with valid data returns success. Requirement 3.2"""
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        f = output_root / "model.3mf"
        f.write_text("data")
        launch_copy = output_root / "temp" / "launch_copy.3mf"
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

    def test_launch_resolves_download_url_without_public_disk_path(
        self,
        tmp_path,
        monkeypatch,
    ):
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        f = output_root / "model.3mf"
        f.write_text("data")
        registry = FileRegistry()
        file_id = registry.register_path("generated-model", str(f), filename="model.3mf")
        launch_copy = output_root / "temp" / "launch_copy.3mf"
        launch_copy.write_text("data")
        client = _make_client()
        client.app.dependency_overrides[get_file_registry] = lambda: registry
        mock_slicers = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe"),
        ]
        try:
            with patch(
                "api.routers.slicer.detect_installed_slicers",
                return_value=mock_slicers,
            ), patch(
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
                        "download_url": f"/api/files/{file_id}",
                    },
                )
        finally:
            client.app.dependency_overrides.pop(get_file_registry, None)

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "success"
        mock_copy.assert_called_once_with(str(f), registry)
        mock_launch.assert_called_once_with("bambu_studio", str(launch_copy), mock_slicers)

    def test_launch_rejects_absolute_download_url(
        self,
        tmp_path,
        monkeypatch,
    ):
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        f = output_root / "model.3mf"
        f.write_text("data")
        registry = FileRegistry()
        file_id = registry.register_path("generated-model", str(f), filename="model.3mf")
        client = _make_client()
        client.app.dependency_overrides[get_file_registry] = lambda: registry
        try:
            resp = client.post(
                "/api/slicer/launch",
                json={
                    "slicer_id": "bambu_studio",
                    "download_url": f"https://example.test/api/files/{file_id}",
                },
            )
        finally:
            client.app.dependency_overrides.pop(get_file_registry, None)

        assert resp.status_code == 400
        assert resp.json()["message"] == SLICER_LAUNCH_SOURCE_MISSING_MESSAGE

    def test_launch_rejects_private_download_url_entry(
        self,
        tmp_path,
        monkeypatch,
    ):
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        f = output_root / "model.3mf"
        f.write_text("data")
        registry = FileRegistry()
        file_id = registry.register_path(
            "private-model",
            str(f),
            filename="model.3mf",
            is_public=False,
        )
        client = _make_client()
        client.app.dependency_overrides[get_file_registry] = lambda: registry
        try:
            resp = client.post(
                "/api/slicer/launch",
                json={
                    "slicer_id": "bambu_studio",
                    "download_url": f"/api/files/{file_id}",
                },
            )
        finally:
            client.app.dependency_overrides.pop(get_file_registry, None)

        assert resp.status_code == 400
        assert resp.json()["message"] == SLICER_LAUNCH_SOURCE_MISSING_MESSAGE

    def test_launch_rejects_untrusted_origin_by_default(
        self,
        tmp_path,
        monkeypatch,
    ):
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        f = output_root / "model.3mf"
        f.write_text("data")

        client = _make_client()
        auto_slicer = DetectedSlicer(
            id="bambu_studio",
            display_name="Bambu Studio",
            exe_path="/Applications/Bambu Studio.app",
            source="auto_macos_app",
        )
        launch_copy = output_root / "temp" / "launch_copy.3mf"
        launch_copy.parent.mkdir(parents=True, exist_ok=True)
        launch_copy.write_text("data")
        with patch(
            "api.routers.slicer.detect_installed_slicers",
            return_value=[auto_slicer],
        ) as detect, patch(
            "api.routers.slicer._create_launch_copy",
            return_value=launch_copy,
        ) as create_copy, patch(
            "api.routers.slicer.launch_slicer",
            return_value=(True, "launched"),
        ) as launch:
            resp = client.post(
                "/api/slicer/launch",
                json={
                    "slicer_id": "bambu_studio",
                    "file_path": str(f),
                },
                headers=UNTRUSTED_ORIGIN_HEADERS,
            )

        assert resp.status_code == 403
        detect.assert_not_called()
        create_copy.assert_not_called()
        launch.assert_not_called()

    def test_launch_allows_untrusted_origin_for_public_gray_api(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setenv("LUMINA_ALLOW_PUBLIC_GRAY_API", "1")
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        f = output_root / "model.3mf"
        f.write_text("data")

        client = _make_client()
        auto_slicer = DetectedSlicer(
            id="bambu_studio",
            display_name="Bambu Studio",
            exe_path="/Applications/Bambu Studio.app",
            source="auto_macos_app",
        )
        launch_copy = output_root / "temp" / "launch_copy.3mf"
        launch_copy.parent.mkdir(parents=True, exist_ok=True)
        launch_copy.write_text("data")
        with patch(
            "api.routers.slicer.detect_installed_slicers",
            return_value=[auto_slicer],
        ), patch(
            "api.routers.slicer._create_launch_copy",
            return_value=launch_copy,
        ), patch(
            "api.routers.slicer.launch_slicer",
            return_value=(True, "launched"),
        ):
            resp = client.post(
                "/api/slicer/launch",
                json={
                    "slicer_id": "bambu_studio",
                    "file_path": str(f),
                },
                headers=UNTRUSTED_ORIGIN_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_launch_uses_valid_custom_path(self, tmp_path, monkeypatch):
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        f = output_root / "model.3mf"
        f.write_text("data")
        launch_copy = output_root / "temp" / "launch_copy.3mf"
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

    def test_launch_rejects_existing_3mf_outside_output(
        self,
        tmp_path,
        monkeypatch,
    ):
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        f = outside_dir / "model.3mf"
        f.write_text("data")
        launch_copy = output_root / "temp" / "launch_copy.3mf"
        mock_slicers = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe"),
        ]

        client = _make_client()
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

        assert resp.status_code == 400
        assert resp.json()["status"] == "error"
        mock_copy.assert_not_called()
        mock_launch.assert_not_called()

    def test_launch_rejects_non_3mf_inside_output(
        self,
        tmp_path,
        monkeypatch,
    ):
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        f = output_root / "probe.txt"
        f.write_text("NOT_A_3MF_SENTINEL")
        launch_copy = output_root / "temp" / "probe_launch.txt"
        mock_slicers = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe"),
        ]

        client = _make_client()
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

        assert resp.status_code == 400
        assert resp.json()["status"] == "error"
        mock_copy.assert_not_called()
        mock_launch.assert_not_called()

    def test_launch_rejects_output_symlink_to_external_file(
        self,
        tmp_path,
        monkeypatch,
    ):
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        outside_file = outside_dir / "secret.3mf"
        outside_file.write_text("external-data")
        symlink_path = output_root / "fake.3mf"
        try:
            symlink_path.symlink_to(outside_file)
        except (NotImplementedError, OSError) as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
        launch_copy = output_root / "temp" / "fake_launch.3mf"
        mock_slicers = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe"),
        ]

        client = _make_client()
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
                    "file_path": str(symlink_path),
                },
            )

        assert resp.status_code == 400
        assert resp.json()["status"] == "error"
        mock_copy.assert_not_called()
        mock_launch.assert_not_called()

    def test_launch_rejects_output_symlink_to_non_3mf_target(
        self,
        tmp_path,
        monkeypatch,
    ):
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        target_file = output_root / "secret.txt"
        target_file.write_text("not-a-3mf")
        symlink_path = output_root / "fake.3mf"
        try:
            symlink_path.symlink_to(target_file)
        except (NotImplementedError, OSError) as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
        launch_copy = output_root / "temp" / "fake_launch.3mf"
        mock_slicers = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe"),
        ]

        client = _make_client()
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
                    "file_path": str(symlink_path),
                },
            )

        assert resp.status_code == 400
        assert resp.json()["status"] == "error"
        mock_copy.assert_not_called()
        mock_launch.assert_not_called()

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

    def test_launch_missing_output_file_uses_safe_message(self, tmp_path, monkeypatch):
        """Missing Lumina output files should not echo local paths."""
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        missing_path = output_root / "missing.3mf"
        client = _make_client()

        resp = client.post(
            "/api/slicer/launch",
            json={
                "slicer_id": "bambu_studio",
                "file_path": str(missing_path),
            },
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["status"] == "error"
        assert body["message"] == SLICER_LAUNCH_SOURCE_MISSING_MESSAGE
        assert str(missing_path) not in resp.text

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

    def test_launch_slicer_not_found_returns_404(self, tmp_path, monkeypatch):
        """POST with unknown slicer_id returns 404. Requirement 2.2"""
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        f = output_root / "model.3mf"
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

    def test_launch_copy_failure_uses_safe_message(self, tmp_path, monkeypatch):
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        f = output_root / "model.3mf"
        f.write_text("data")
        private_path = "/Users/min/private/model.3mf"
        mock_slicers = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe"),
        ]

        client = _make_client()
        with patch("api.routers.slicer.detect_installed_slicers", return_value=mock_slicers), patch(
            "api.routers.slicer._create_launch_copy",
            side_effect=RuntimeError(f"cannot copy {private_path}: permission denied"),
        ), patch(
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

        assert resp.status_code == 500
        body = resp.json()
        assert body["status"] == "error"
        assert body["message"] == SLICER_LAUNCH_COPY_FAILED_MESSAGE
        assert private_path not in resp.text
        assert "permission denied" not in resp.text
        mock_launch.assert_not_called()

    def test_launch_exception_uses_safe_message(self, tmp_path, monkeypatch):
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        f = output_root / "model.3mf"
        f.write_text("data")
        launch_copy = output_root / "temp" / "launch_copy.3mf"
        launch_copy.write_text("data")
        private_path = "/Applications/Private/Slicer.app"
        mock_slicers = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe"),
        ]

        client = _make_client()
        with patch("api.routers.slicer.detect_installed_slicers", return_value=mock_slicers), patch(
            "api.routers.slicer._create_launch_copy",
            return_value=str(launch_copy),
        ), patch(
            "api.routers.slicer.launch_slicer",
            side_effect=OSError(f"cannot execute {private_path}: launch denied"),
        ):
            resp = client.post(
                "/api/slicer/launch",
                json={
                    "slicer_id": "bambu_studio",
                    "file_path": str(f),
                },
            )

        assert resp.status_code == 500
        body = resp.json()
        assert body["status"] == "error"
        assert body["message"] == SLICER_LAUNCH_FAILED_MESSAGE
        assert private_path not in resp.text
        assert "launch denied" not in resp.text

    def test_launch_failure_message_is_not_exposed(self, tmp_path, monkeypatch):
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        f = output_root / "model.3mf"
        f.write_text("data")
        launch_copy = output_root / "temp" / "launch_copy.3mf"
        launch_copy.write_text("data")
        private_path = "/Applications/Private/Slicer.app"
        mock_slicers = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe"),
        ]

        client = _make_client()
        with patch("api.routers.slicer.detect_installed_slicers", return_value=mock_slicers), patch(
            "api.routers.slicer._create_launch_copy",
            return_value=str(launch_copy),
        ), patch(
            "api.routers.slicer.launch_slicer",
            return_value=(False, f"open failed {private_path}: code 500"),
        ):
            resp = client.post(
                "/api/slicer/launch",
                json={
                    "slicer_id": "bambu_studio",
                    "file_path": str(f),
                },
            )

        assert resp.status_code == 500
        body = resp.json()
        assert body["status"] == "error"
        assert body["message"] == SLICER_LAUNCH_FAILED_MESSAGE
        assert private_path not in resp.text
        assert "code 500" not in resp.text

    def test_launch_download_url_failure_message_is_not_exposed(
        self,
        tmp_path,
        monkeypatch,
    ):
        output_root = _configure_slicer_output(monkeypatch, tmp_path)
        f = output_root / "model.3mf"
        f.write_text("data")
        registry = FileRegistry()
        file_id = registry.register_path("generated-model", str(f), filename="model.3mf")
        launch_copy = output_root / "temp" / "launch_copy.3mf"
        launch_copy.write_text("data")
        mock_slicers = [
            DetectedSlicer(id="bambu_studio", display_name="Bambu Studio", exe_path="C:\\bs.exe"),
        ]

        client = _make_client()
        client.app.dependency_overrides[get_file_registry] = lambda: registry
        try:
            with patch(
                "api.routers.slicer.detect_installed_slicers",
                return_value=mock_slicers,
            ), patch(
                "api.routers.slicer._create_launch_copy",
                return_value=str(launch_copy),
            ), patch(
                "api.routers.slicer.launch_slicer",
                return_value=(False, f"open failed {f}: code 500"),
            ):
                resp = client.post(
                    "/api/slicer/launch",
                    json={
                        "slicer_id": "bambu_studio",
                        "download_url": f"/api/files/{file_id}",
                    },
                )
        finally:
            client.app.dependency_overrides.pop(get_file_registry, None)

        assert resp.status_code == 500
        body = resp.json()
        assert body["status"] == "error"
        assert body["message"] == SLICER_LAUNCH_FAILED_MESSAGE
        assert str(f) not in resp.text
        assert str(launch_copy) not in resp.text
        assert "code 500" not in resp.text
