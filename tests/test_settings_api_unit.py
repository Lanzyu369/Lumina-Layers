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
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from api.app import app

client: TestClient = TestClient(app)


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
        assert settings["nozzle_size"] == "0.4"

    def test_get_settings_file_exists(self) -> None:
        """文件存在时返回正确数据。"""
        custom_settings = {
            "last_lut": "MyLUT",
            "last_modeling_mode": "pixel",
            "last_color_mode": "6-Color",
            "last_slicer": "bambu",
            "palette_mode": "grid",
            "enable_crop_modal": False,
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
        assert settings["nozzle_size"] == "0.2"


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

    def test_post_settings_io_error(self) -> None:
        """I/O 错误返回 500。"""
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
        mock_file.write_text.side_effect = OSError("disk full")

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            response = client.post("/api/system/settings", json=payload)

        assert response.status_code == 500
        assert "Failed to save settings" in response.json()["detail"]


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
