"""Unit tests for Calibration endpoint integration.

Validates:
- 4 color_mode routing dispatches to correct core functions (Requirement 3.1-3.4)
- Parameter mapping from Pydantic fields to core function args (Requirement 3.5)
- Core exception returns HTTP 500 (Requirement 3.6)
"""

from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.dependencies import get_file_registry
from api.file_registry import FileRegistry
from api.routers.calibration import CALIBRATION_GENERATION_FAILED_DETAIL
from config import DEFAULT_PRINTER_ID, DEFAULT_SLICER_ID

client: TestClient = TestClient(create_app())

# Shared mock return value: (file_path, PIL preview image, status string)
_mock_preview: Image.Image = Image.fromarray(
    np.zeros((10, 10, 3), dtype=np.uint8)
)
_mock_return = ("/tmp/fake.3mf", _mock_preview, "OK")


class _RegisterPathFailingRegistry(FileRegistry):
    """Registry stub that records the generated path before failing."""

    def __init__(self) -> None:
        super().__init__()
        self.generated_path: str | None = None

    def register_path(self, *args: object, **kwargs: object) -> str:
        if "path" in kwargs:
            self.generated_path = str(kwargs["path"])
        elif len(args) >= 2:
            self.generated_path = str(args[1])
        raise RuntimeError("registry backend unavailable")


def _assert_default_device_kwargs(kwargs: dict) -> None:
    assert kwargs["printer_id"] == DEFAULT_PRINTER_ID
    assert kwargs["slicer"] == DEFAULT_SLICER_ID
    assert kwargs["nozzle_size"] == "0.4"


# =========================================================================
# 1. Color mode routing - Requirement 3
# =========================================================================


class TestColorModeRouting:
    """Verify each color_mode dispatches to the correct core function."""

    def test_generate_cleans_output_when_registry_fails(
        self,
        tmp_path: Path,
    ) -> None:
        output_path = tmp_path / "calibration.3mf"
        output_path.write_bytes(b"placeholder-3mf")
        registry = _RegisterPathFailingRegistry()
        app = create_app()
        app.dependency_overrides[get_file_registry] = lambda: registry
        failing_client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "api.routers.calibration.generate_bw_calibration_board",
            return_value=(str(output_path), None, "OK"),
        ):
            response = failing_client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "BW (Black & White)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.6,
                },
            )

        assert response.status_code == 500
        assert registry.generated_path == str(output_path)
        assert not output_path.exists()

    def test_bw_mode_routes_to_generate_bw(self) -> None:
        with patch(
            "api.routers.calibration.generate_bw_calibration_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "BW (Black & White)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.6,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["block_size_mm"] == 5.0
            assert mock_fn.call_args.kwargs["gap_mm"] == 0.84
            assert mock_fn.call_args.kwargs["backing_color"] == "White"
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 1.6
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)

    def test_four_color_mode_routes_to_generate_calibration_board(self) -> None:
        with patch(
            "api.routers.calibration.generate_calibration_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "4-Color (RYBW)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.6,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["color_mode"] == "RYBW"
            assert mock_fn.call_args.kwargs["block_size_mm"] == 5.0
            assert mock_fn.call_args.kwargs["gap_mm"] == 0.84
            assert mock_fn.call_args.kwargs["backing_color"] == "White"
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 1.6
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)

    def test_six_color_mode_routes_to_generate_smart_board(self) -> None:
        with patch(
            "api.routers.calibration.generate_smart_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "6-Color (CMYWGK 1296)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.6,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["block_size_mm"] == 5.0
            assert mock_fn.call_args.kwargs["gap_mm"] == 0.84
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 1.6
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)

    def test_eight_color_full_export_routes_to_generate_8color_full_batch_zip(self) -> None:
        with patch(
            "api.routers.calibration.generate_8color_full_batch_zip",
            return_value=("/tmp/fake_full.zip", _mock_preview, "OK"),
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "8-Color Max",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.6,
                    "eight_color_full_export": True,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["block_size_mm"] == 5.0
            assert mock_fn.call_args.kwargs["gap_mm"] == 0.84
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 1.6
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)

    def test_eight_color_mode_routes_to_generate_8color_batch_zip(self) -> None:
        with patch(
            "api.routers.calibration.generate_8color_batch_zip",
            return_value=("/tmp/fake.zip", _mock_preview, "OK"),
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "8-Color Max",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.6,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["block_size_mm"] == 5.0
            assert mock_fn.call_args.kwargs["gap_mm"] == 0.84
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 1.6
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)


# =========================================================================
# 2. Parameter mapping - Requirement 3.5
# =========================================================================


class TestParameterMapping:
    """Verify Pydantic request fields map correctly to core function args."""

    def test_block_size_and_gap_mapped_correctly(self) -> None:
        with patch(
            "api.routers.calibration.generate_bw_calibration_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "BW (Black & White)",
                    "block_size": 8,
                    "gap": 1.5,
                    "backing_thickness": 2.4,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["block_size_mm"] == 8.0
            assert mock_fn.call_args.kwargs["gap_mm"] == 1.5
            assert mock_fn.call_args.kwargs["backing_color"] == "White"
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 2.4
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)
            # Verify block_size is passed as float and backing color is hard-coded.
            call_kwargs = mock_fn.call_args.kwargs
            assert isinstance(call_kwargs["block_size_mm"], float)
            assert call_kwargs["backing_color"] == "White"

    def test_fractional_block_size_is_accepted(self) -> None:
        with patch(
            "api.routers.calibration.generate_calibration_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "4-Color (RYBW)",
                    "block_size": 5.5,
                    "gap": 0.84,
                    "backing_thickness": 1.2,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["color_mode"] == "RYBW"
            assert mock_fn.call_args.kwargs["block_size_mm"] == 5.5
            assert mock_fn.call_args.kwargs["gap_mm"] == 0.84
            assert mock_fn.call_args.kwargs["backing_color"] == "White"
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 1.2
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)

    def test_backing_thickness_defaults_when_omitted(self) -> None:
        """Omitting backing_thickness in the payload should fall back to the schema default (1.2 mm)."""
        with patch(
            "api.routers.calibration.generate_calibration_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "4-Color (RYBW)",
                    "block_size": 5,
                    "gap": 0.84,
                },
            )
            assert response.status_code == 200
            mock_fn.assert_called_once()
            assert mock_fn.call_args.kwargs["color_mode"] == "RYBW"
            assert mock_fn.call_args.kwargs["block_size_mm"] == 5.0
            assert mock_fn.call_args.kwargs["gap_mm"] == 0.84
            assert mock_fn.call_args.kwargs["backing_color"] == "White"
            assert mock_fn.call_args.kwargs["backing_thickness_mm"] == 1.2
            _assert_default_device_kwargs(mock_fn.call_args.kwargs)

    def test_device_settings_are_forwarded_to_core_generator(self) -> None:
        with patch(
            "api.routers.calibration.generate_calibration_board",
            return_value=_mock_return,
        ) as mock_fn:
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "4-Color (RYBW)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.2,
                    "printer_id": "bambu-p1s",
                    "slicer": "OrcaSlicer",
                    "nozzle_size": "0.2",
                },
            )

        assert response.status_code == 200
        assert response.json()["threemf_disk_path"] == "/tmp/fake.3mf"
        mock_fn.assert_called_once()
        kwargs = mock_fn.call_args.kwargs
        assert kwargs["printer_id"] == "bambu-p1s"
        assert kwargs["slicer"] == "OrcaSlicer"
        assert kwargs["nozzle_size"] == "0.2"



# =========================================================================
# 3. Error handling - Requirement 3.6
# =========================================================================


class TestErrorHandling:
    """Verify core exceptions are translated to HTTP 500 responses."""

    def test_core_exception_returns_500(self) -> None:
        private_path = "/Users/min/private/calibration.3mf"

        with patch(
            "api.routers.calibration.generate_calibration_board",
            side_effect=RuntimeError(f"disk full while writing {private_path}"),
        ):
            response = client.post(
                "/api/calibration/generate",
                json={
                    "color_mode": "4-Color (RYBW)",
                    "block_size": 5,
                    "gap": 0.84,
                    "backing_thickness": 1.6,
                },
            )
            assert response.status_code == 500
            assert response.json()["detail"] == CALIBRATION_GENERATION_FAILED_DETAIL
            assert "disk full" not in response.text
            assert private_path not in response.text
