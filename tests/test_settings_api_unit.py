"""Unit tests for Settings and Stats API endpoints.

Validates:
- GET /api/system/settings returns defaults when file missing (Requirement 5.1, 5.2)
- GET /api/system/settings returns correct data when file exists (Requirement 5.1)
- POST /api/system/settings writes successfully (Requirement 5.3)
- POST /api/system/settings returns 500 on I/O error (Requirement 5.5)
- GET /api/system/stats returns correct data (Requirement 6.1)
- GET /api/system/stats returns zeros when stats file missing (Requirement 6.2)
"""

import json
import logging
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.routers.system import SETTINGS_SAVE_FAILED_DETAIL

client: TestClient = TestClient(app)
UNTRUSTED_ORIGIN_HEADERS = {"Origin": "https://attacker.example"}
LOCAL_FRONTEND_ORIGIN_HEADERS = {"Origin": "http://localhost:5174"}


def _records_for_event(
    caplog: pytest.LogCaptureFixture,
    event_name: str,
) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == event_name
    ]

# =========================================================================
# 1. GET /api/system/settings — Requirements 5.1, 5.2
# =========================================================================


class TestGetSettings:
    """Verify GET /api/system/settings returns correct data."""

    def test_get_settings_file_not_exists(self) -> None:
        """文件不存在时返回默认值。"""
        with patch("api.routers.system.SETTINGS_FILE") as mock_file:
            mock_file.exists.return_value = False
            response = client.get("/api/system/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        settings = data["settings"]
        assert settings["last_lut"] == ""
        assert settings["last_modeling_mode"] == "high-fidelity"
        assert settings["last_color_mode"] == "4-Color (RYBW)"
        assert settings["last_slicer"] == ""
        assert settings["palette_mode"] == "swatch"
        assert settings["enable_crop_modal"] is True
        assert settings["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.4"
        assert settings["nozzle_size"] == "0.4"

    def test_get_settings_rejects_untrusted_origin_before_reading_file(self) -> None:
        """外部网页不能读取本地持久设置。"""
        mock_file = MagicMock()
        mock_file.exists.side_effect = AssertionError("settings file should not be read")

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client.get(
                "/api/system/settings",
                headers=UNTRUSTED_ORIGIN_HEADERS,
            )

        assert response.status_code == 403
        assert "local Lumina Studio app" in response.json()["detail"]

    def test_get_settings_file_exists(self) -> None:
        """文件存在时返回正确数据。"""
        custom_settings = {
            "last_lut": "MyLUT",
            "last_modeling_mode": "pixel",
            "last_color_mode": "6-Color",
            "last_slicer": "bambu",
            "palette_mode": "grid",
            "enable_crop_modal": False,
            "device_profile_id": "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
            "nozzle_size": "0.2",
        }
        mock_file = MagicMock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = json.dumps(custom_settings)

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client.get("/api/system/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        settings = data["settings"]
        assert settings["last_lut"] == "MyLUT"
        assert settings["last_modeling_mode"] == "pixel"
        assert settings["last_color_mode"] == "6-Color"
        assert settings["last_slicer"] == "bambu"
        assert settings["palette_mode"] == "grid"
        assert settings["enable_crop_modal"] is False
        assert settings["device_profile_id"] == "OrcaSlicer:bbl:bambu-lab-p1s:0.2"
        assert settings["nozzle_size"] == "0.2"

    def test_get_settings_allows_local_frontend_origin(self) -> None:
        """本地前端仍可读取设置。"""
        custom_settings = {
            "last_lut": "LocalLUT",
            "last_modeling_mode": "vector",
            "last_color_mode": "4-Color (RYBW)",
            "palette_mode": "swatch",
            "enable_crop_modal": True,
            "custom_slicer_path": "/Applications/Bambu Studio.app",
        }
        mock_file = MagicMock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = json.dumps(custom_settings)

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client.get(
                "/api/system/settings",
                headers=LOCAL_FRONTEND_ORIGIN_HEADERS,
            )

        assert response.status_code == 200
        assert response.json()["settings"]["last_lut"] == "LocalLUT"

    @pytest.mark.parametrize("raw_json", ["[]", "null", '"oops"', "123", "true", "1.5"])
    def test_get_settings_non_object_json_returns_defaults(self, raw_json: str) -> None:
        """合法 JSON 但顶层不是对象时返回默认值，不让设置 API 500。"""
        mock_file = MagicMock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = raw_json
        client_no_raise = TestClient(app, raise_server_exceptions=False)

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client_no_raise.get("/api/system/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        settings = data["settings"]
        assert settings["last_lut"] == ""
        assert settings["last_modeling_mode"] == "high-fidelity"
        assert settings["last_color_mode"] == "4-Color (RYBW)"
        assert settings["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.4"

    def test_get_settings_read_error_returns_defaults_without_unhandled_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """I/O read failures fall back to defaults without app-level 500."""
        mock_file = MagicMock()
        private_path = "/Users/min/private/user_settings.json"
        mock_file.exists.return_value = True
        mock_file.read_text.side_effect = OSError(
            f"permission denied: {private_path}"
        )
        client_no_raise = TestClient(app, raise_server_exceptions=False)
        system_logger = logging.getLogger("lumina.api.routers.system")
        app_logger = logging.getLogger("lumina.api.app")
        system_logger.addHandler(caplog.handler)
        app_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=system_logger.name)
        caplog.set_level(logging.WARNING, logger=app_logger.name)

        try:
            with patch("api.routers.system.SETTINGS_FILE", mock_file):
                response = client_no_raise.get("/api/system/settings")
        finally:
            system_logger.removeHandler(caplog.handler)
            app_logger.removeHandler(caplog.handler)

        assert response.status_code == 200
        assert private_path not in response.text
        data = response.json()
        assert data["status"] == "success"
        settings = data["settings"]
        assert settings["last_lut"] == ""
        assert settings["last_modeling_mode"] == "high-fidelity"
        assert settings["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.4"
        records = _records_for_event(caplog, "system_settings_load_failed")
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert records[0].error_type == "OSError"
        assert records[0].settings_path == str(mock_file)
        assert private_path in records[0].error_message
        assert _records_for_event(caplog, "api_unhandled_exception") == []

    def test_get_settings_exists_error_returns_defaults(self) -> None:
        """Even checking for settings file presence is a recoverable read failure."""
        mock_file = MagicMock()
        private_path = "/Users/min/private/user_settings.json"
        mock_file.exists.side_effect = OSError(f"stat failed: {private_path}")
        client_no_raise = TestClient(app, raise_server_exceptions=False)

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client_no_raise.get("/api/system/settings")

        assert response.status_code == 200
        assert private_path not in response.text
        settings = response.json()["settings"]
        assert settings["last_lut"] == ""
        assert settings["last_modeling_mode"] == "high-fidelity"
        assert settings["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.4"


# =========================================================================
# 2. POST /api/system/settings — Requirements 5.3, 5.5
# =========================================================================


class TestPostSettings:
    """Verify POST /api/system/settings writes and handles errors."""

    def test_post_settings_success(self) -> None:
        """写入成功返回 200。"""
        payload = {
            "last_lut": "TestLUT",
            "last_modeling_mode": "vector",
            "last_color_mode": "8-Color Max",
            "last_slicer": "orca",
            "palette_mode": "swatch",
            "enable_crop_modal": True,
            "device_profile_id": "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
            "nozzle_size": "0.2",
        }
        mock_file = MagicMock()
        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client.post("/api/system/settings", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["message"] == "Settings saved"
        mock_file.write_text.assert_called_once()
        written = json.loads(mock_file.write_text.call_args.args[0])
        assert written["device_profile_id"] == "OrcaSlicer:bbl:bambu-lab-p1s:0.2"

    def test_post_settings_rejects_untrusted_origin_before_writing_file(self) -> None:
        """外部网页不能改写本地持久设置。"""
        payload = {
            "last_lut": "attacker-lut",
            "last_modeling_mode": "vector",
            "last_color_mode": "8-Color Max",
            "last_slicer": "attacker",
            "palette_mode": "swatch",
            "enable_crop_modal": False,
            "printer_model": "attacker-printer",
            "slicer_software": "AttackerSlicer",
            "device_profile_id": "Attacker:profile:0.8",
            "custom_slicer_path": "/tmp/attacker.app",
            "custom_slicer_id": "attacker-custom",
            "nozzle_size": "0.8",
            "enable_base_layer_height_modifier": False,
        }
        mock_file = MagicMock()
        mock_file.write_text.side_effect = AssertionError("settings file should not be written")

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client.post(
                "/api/system/settings",
                json=payload,
                headers=UNTRUSTED_ORIGIN_HEADERS,
            )

        assert response.status_code == 403
        assert "local Lumina Studio app" in response.json()["detail"]
        mock_file.write_text.assert_not_called()

    def test_post_settings_io_error(self) -> None:
        """I/O 错误返回 500，但不暴露本机路径或底层异常。"""
        payload = {
            "last_lut": "",
            "last_modeling_mode": "high-fidelity",
            "last_color_mode": "4-Color",
            "last_slicer": "",
            "palette_mode": "swatch",
            "enable_crop_modal": True,
            "nozzle_size": "0.4",
        }
        mock_file = MagicMock()
        private_path = "/Users/min/private/user_settings.json"
        mock_file.write_text.side_effect = OSError(
            f"cannot write {private_path}: disk full"
        )

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client.post("/api/system/settings", json=payload)

        assert response.status_code == 500
        assert response.json()["detail"] == SETTINGS_SAVE_FAILED_DETAIL
        assert private_path not in response.text
        assert "disk full" not in response.text


# =========================================================================
# 3. GET /api/system/stats — Requirements 6.1, 6.2
# =========================================================================


class TestGetStats:
    """Verify GET /api/system/stats returns correct data."""

    def test_get_stats_success(self) -> None:
        """Stats.get_all() 返回数据时正确映射。"""
        mock_data = {"calibrations": 10, "extractions": 5, "conversions": 20}
        with patch("utils.stats.Stats.get_all", return_value=mock_data):
            response = client.get("/api/system/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["calibrations"] == 10
        assert data["extractions"] == 5
        assert data["conversions"] == 20

    def test_get_stats_no_file(self) -> None:
        """统计文件不存在时返回零值。"""
        mock_data: dict = {"calibrations": 0, "extractions": 0, "conversions": 0}
        with patch("utils.stats.Stats.get_all", return_value=mock_data):
            response = client.get("/api/system/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["calibrations"] == 0
        assert data["extractions"] == 0
        assert data["conversions"] == 0


class TestGetPrinters:
    """Verify GET /api/system/printers exposes nozzle-size metadata."""

    def test_get_printers_exposes_supported_nozzle_sizes(self) -> None:
        response = client.get("/api/system/printers")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["printers"]
        first = data["printers"][0]
        assert "supported_nozzle_sizes" in first
        assert "nozzle_count" not in first
        assert "is_dual_head" not in first

    def test_get_printers_attaches_registry_device_profiles(self, tmp_path, monkeypatch) -> None:
        registry_root = tmp_path / "machine_registry"
        registry_root.mkdir()
        (registry_root / "registry.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generated_at": "2026-06-09T00:00:00+08:00",
                    "slicers": [
                        {
                            "slicer_id": "BambuStudio",
                            "display_name": "Bambu Studio",
                            "source_kind": "local_install",
                            "source_version": "02.07.01.57",
                            "profile_format": "bambu_orca",
                            "application_metadata": "BambuStudio-02.07.01.57",
                            "sidecar_policy": "bambu_studio",
                            "machines": [
                                {
                                    "machine_profile_id": "BambuStudio:bbl:bambu-lab-h2d",
                                    "display_name": "Bambu Lab H2D",
                                    "brand": "Bambu Lab",
                                    "vendor_key": "BBL",
                                    "bed_width": 350,
                                    "bed_depth": 320,
                                    "bed_height": 325,
                                    "thumbnail": "slicers/BambuStudio/assets/h2d.png",
                                    "nozzles": [
                                        {
                                            "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
                                            "nozzle_size": "0.4",
                                            "source_profile_name": "Bambu Lab H2D 0.4 nozzle",
                                            "template": "slicers/BambuStudio/templates/h2d_0_4.json",
                                            "revision": "sha256:abc",
                                            "supported": True,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

        response = client.get("/api/system/printers")

        assert response.status_code == 200
        printers = response.json()["printers"]
        h2d = next(printer for printer in printers if printer["id"] == "bambu-h2d")
        assert h2d["thumbnail"] == "slicers/BambuStudio/assets/h2d.png"
        assert h2d["device_profiles"] == [
            {
                "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
                "slicer_id": "BambuStudio",
                "nozzle_size": "0.4",
                "source_profile_name": "Bambu Lab H2D 0.4 nozzle",
                "revision": "sha256:abc",
                "supported": True,
            }
        ]

    def test_get_printers_includes_registry_only_orca_multicolor_machine(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        registry_root = tmp_path / "machine_registry"
        registry_root.mkdir()
        (registry_root / "registry.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generated_at": "2026-06-09T00:00:00+08:00",
                    "slicers": [
                        {
                            "slicer_id": "OrcaSlicer",
                            "display_name": "OrcaSlicer",
                            "source_kind": "local_install",
                            "source_version": "02.04.00.00",
                            "profile_format": "bambu_orca",
                            "application_metadata": "OrcaSlicer-02.04.00.00",
                            "sidecar_policy": "orca_like",
                            "machines": [
                                {
                                    "machine_profile_id": "OrcaSlicer:snapmaker:snapmaker-artisan",
                                    "display_name": "Snapmaker Artisan",
                                    "brand": "Snapmaker",
                                    "vendor_key": "Snapmaker",
                                    "bed_width": 400,
                                    "bed_depth": 400,
                                    "bed_height": 400,
                                    "thumbnail": "slicers/OrcaSlicer/assets/snapmaker-artisan.png",
                                    "nozzles": [
                                        {
                                            "device_profile_id": "OrcaSlicer:snapmaker:snapmaker-artisan:0.4",
                                            "nozzle_size": "0.4",
                                            "source_profile_name": "Snapmaker Artisan 0.4 nozzle",
                                            "template": "slicers/OrcaSlicer/templates/snapmaker-artisan_0_4.json",
                                            "revision": "sha256:artisan",
                                            "supported": True,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

        response = client.get("/api/system/printers")

        assert response.status_code == 200
        printers = response.json()["printers"]
        snapmaker_artisan = next(printer for printer in printers if printer["id"] == "snapmaker-artisan")
        assert snapmaker_artisan["display_name"] == "Snapmaker Artisan"
        assert snapmaker_artisan["supported_slicers"] == ["OrcaSlicer"]
        assert snapmaker_artisan["supported_nozzle_sizes"] == ["0.4"]
        assert snapmaker_artisan["thumbnail"] == "slicers/OrcaSlicer/assets/snapmaker-artisan.png"
        assert snapmaker_artisan["device_profiles"][0]["device_profile_id"] == (
            "OrcaSlicer:snapmaker:snapmaker-artisan:0.4"
        )

    def test_machine_registry_asset_serves_thumbnail_inside_registry(self, tmp_path, monkeypatch) -> None:
        registry_root = tmp_path / "machine_registry"
        asset_path = registry_root / "slicers" / "BambuStudio" / "assets" / "h2d.png"
        asset_path.parent.mkdir(parents=True)
        asset_path.write_bytes(b"fake-thumbnail")
        monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

        response = client.get("/api/system/machine-registry/assets/slicers/BambuStudio/assets/h2d.png")

        assert response.status_code == 200
        assert response.content == b"fake-thumbnail"
        assert response.headers["content-type"].startswith("image/png")

    def test_machine_registry_asset_rejects_path_traversal(self, tmp_path, monkeypatch) -> None:
        registry_root = tmp_path / "machine_registry"
        registry_root.mkdir()
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"outside")
        monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

        response = client.get("/api/system/machine-registry/assets/../outside.png")

        assert response.status_code in {400, 404}
