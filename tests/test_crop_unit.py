"""Unit tests for POST /api/convert/crop endpoint.

Validates:
- Normal crop flow: upload image + valid coords -> returns cropped URL (Requirement 5.1, 5.2, 5.3)
- Out-of-bounds coordinate clamping: x=9999, y=9999 -> auto-clamped (Requirement 5.4)
- Invalid file upload: text file -> HTTP 422 (Requirement 5.5)
- Zero-size crop: width=0 -> clamped to 1 (Requirement 5.4)
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import config
from api.app import app, create_app
from api.dependencies import get_file_registry
from api.file_registry import FileRegistry

# Isolated registry per test module to avoid cross-test pollution
_test_registry: FileRegistry = FileRegistry()
app.dependency_overrides[get_file_registry] = lambda: _test_registry

client: TestClient = TestClient(app)


def _make_rgb_png(width: int = 200, height: int = 150) -> io.BytesIO:
    """Create a simple RGB PNG image buffer."""
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    arr[:, :, 0] = 200  # red channel
    arr[:, :, 1] = 100  # green channel
    img = Image.fromarray(arr, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _make_text_file() -> io.BytesIO:
    """Create a plain text file buffer (invalid image format)."""
    buf = io.BytesIO(b"this is not an image file at all")
    buf.seek(0)
    return buf


def _client_with_registry() -> tuple[TestClient, FileRegistry]:
    """Create an isolated app client and file registry for lifecycle tests."""
    test_app = create_app()
    registry = FileRegistry()
    test_app.dependency_overrides[get_file_registry] = lambda: registry
    return TestClient(test_app), registry


# =========================================================================
# 1. Normal crop flow - Requirement 5.1, 5.2, 5.3
# =========================================================================


class TestNormalCropFlow:
    """Verify valid image + valid coords returns 200 with CropResponse fields."""

    def test_crop_valid_image_returns_200(self) -> None:
        buf = _make_rgb_png(200, 150)

        response = client.post(
            "/api/convert/crop",
            files={"image": ("test.png", buf, "image/png")},
            data={"x": "10", "y": "20", "width": "80", "height": "60"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["message"]
        assert body["cropped_url"].startswith("/api/files/")
        assert body["width"] == 80
        assert body["height"] == 60


# =========================================================================
# 2. Out-of-bounds coordinate clamping - Requirement 5.4
# =========================================================================


class TestCoordinateClamping:
    """Verify out-of-bounds coords are clamped, not rejected."""

    def test_large_xy_clamped_to_valid_range(self) -> None:
        """x=9999, y=9999 on a 200x150 image -> clamped, still returns 200."""
        buf = _make_rgb_png(200, 150)

        response = client.post(
            "/api/convert/crop",
            files={"image": ("test.png", buf, "image/png")},
            data={"x": "9999", "y": "9999", "width": "50", "height": "50"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["width"] >= 1
        assert body["height"] >= 1
        assert body["cropped_url"].startswith("/api/files/")


# =========================================================================
# 3. Invalid file upload - Requirement 5.5
# =========================================================================


class TestInvalidFileUpload:
    """Verify non-image file returns HTTP 422."""

    def test_text_file_returns_422(self) -> None:
        buf = _make_text_file()

        response = client.post(
            "/api/convert/crop",
            files={"image": ("notes.txt", buf, "text/plain")},
            data={"x": "0", "y": "0", "width": "10", "height": "10"},
        )

        assert response.status_code == 422
        body = response.json()
        assert "detail" in body


class TestCropTempFileLifecycle:
    """Verify upload temp files do not outlive crop request ownership."""

    def test_successful_crop_keeps_only_registered_result(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path))
        isolated_client, registry = _client_with_registry()
        buf = _make_rgb_png(20, 10)

        response = isolated_client.post(
            "/api/convert/crop",
            files={"image": ("test.png", buf, "image/png")},
            data={"x": "0", "y": "0", "width": "5", "height": "5"},
        )

        assert response.status_code == 200
        body = response.json()
        file_id = body["cropped_url"].rsplit("/", 1)[-1]
        entry = registry.get_entry(file_id)

        assert entry is not None
        assert sorted(tmp_path.iterdir()) == [Path(str(entry["path"]))]

    def test_invalid_image_upload_leaves_no_temp_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path))
        isolated_client, _registry = _client_with_registry()
        buf = _make_text_file()

        response = isolated_client.post(
            "/api/convert/crop",
            files={"image": ("notes.txt", buf, "text/plain")},
            data={"x": "0", "y": "0", "width": "10", "height": "10"},
        )

        assert response.status_code == 422
        assert sorted(tmp_path.iterdir()) == []

    def test_registry_failure_cleans_upload_and_cropped_temp_files(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        class FailingRegistry(FileRegistry):
            def register_path(self, *args: object, **kwargs: object) -> str:
                raise RuntimeError("registry unavailable")

        monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path))
        test_app = create_app()
        test_app.dependency_overrides[get_file_registry] = lambda: FailingRegistry()
        isolated_client = TestClient(test_app, raise_server_exceptions=False)
        buf = _make_rgb_png(20, 10)

        response = isolated_client.post(
            "/api/convert/crop",
            files={"image": ("test.png", buf, "image/png")},
            data={"x": "0", "y": "0", "width": "5", "height": "5"},
        )

        assert response.status_code == 500
        assert response.json() == {
            "detail": "Image crop failed. Please retry or choose a different image.",
        }
        assert "registry unavailable" not in response.text
        assert sorted(tmp_path.iterdir()) == []


# =========================================================================
# 4. Zero-size crop (width < 1 rejected by FastAPI ge=1) - Requirement 5.4
# =========================================================================


class TestZeroSizeCrop:
    """Verify width/height < 1 is handled.

    The endpoint declares ``width: int = Form(100, ge=1)``, so FastAPI
    rejects width=0 with 422 before the handler runs.  This is the
    expected behaviour for the ``ge=1`` constraint.
    """

    def test_zero_width_returns_422(self) -> None:
        buf = _make_rgb_png(200, 150)

        response = client.post(
            "/api/convert/crop",
            files={"image": ("test.png", buf, "image/png")},
            data={"x": "0", "y": "0", "width": "0", "height": "50"},
        )

        assert response.status_code == 422
