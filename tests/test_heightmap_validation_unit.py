"""Read-only validation of original share-card heightmap attachments."""

import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import config
from api.routers import system
from core.heightmap_loader import HeightmapLoader


FIXTURES = Path(__file__).resolve().parents[1] / "frontend/src/__tests__/fixtures/heightmap"
FORMATS = [
    ("heightmap.png", "image/png"),
    ("heightmap.jpg", "image/jpeg"),
    ("heightmap.bmp", "image/bmp"),
    ("heightmap.tiff", "image/tiff"),
]


@pytest.fixture
def validation_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TEMP_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(system.router)
    with TestClient(app) as client:
        yield client, tmp_path


@pytest.mark.parametrize("filename,mime", FORMATS)
def test_real_heightmap_decode_preserves_source_and_cleans_temp(
    validation_client, monkeypatch, filename, mime,
):
    client, temp_dir = validation_client
    contents = (FIXTURES / filename).read_bytes()
    decode = HeightmapLoader.load_and_validate
    observed = []

    def record_real_decode(path):
        assert Path(path).read_bytes() == contents
        result = decode(path)
        observed.append(result)
        return result

    monkeypatch.setattr(HeightmapLoader, "load_and_validate", record_real_decode)
    response = client.post(
        "/api/system/validate-heightmap",
        files={"file": (filename, contents, mime)},
    )
    assert response.status_code == 200
    assert response.json() == {"width": 2, "height": 2}
    assert len(observed) == 1
    assert observed[0]["success"]
    if filename != "heightmap.jpg":
        np.testing.assert_array_equal(
            observed[0]["grayscale"], [[0, 85], [170, 255]],
        )
    assert not list(temp_dir.iterdir())


@pytest.mark.parametrize("filename,mime", FORMATS)
def test_bad_heightmap_is_rejected_without_paths_and_temp_is_removed(
    validation_client, filename, mime,
):
    client, temp_dir = validation_client
    response = client.post(
        "/api/system/validate-heightmap",
        files={"file": (filename, b"not an image", mime)},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid or damaged heightmap image."}
    assert str(temp_dir) not in response.text
    assert not list(temp_dir.iterdir())


@pytest.mark.parametrize("filename,mime", [
    ("heightmap.svg", "image/svg+xml"),
    ("heightmap.gif", "image/gif"),
    ("heightmap.txt", "text/plain"),
])
def test_unsupported_heightmap_is_rejected_before_creating_temp(
    validation_client, filename, mime,
):
    client, temp_dir = validation_client
    response = client.post(
        "/api/system/validate-heightmap",
        files={"file": (filename, (FIXTURES / "heightmap.png").read_bytes(), mime)},
    )
    assert response.status_code == 422
    assert not list(temp_dir.iterdir())


@pytest.mark.parametrize("error_type", [ValueError, cv2.error])
def test_decoder_exception_cleans_temp_and_hides_internal_details(
    validation_client, monkeypatch, error_type,
):
    client, temp_dir = validation_client

    def fail_decode(path):
        assert Path(path).exists()
        raise error_type(f"Decoder error: {path}")

    monkeypatch.setattr(HeightmapLoader, "load_and_validate", fail_decode)
    response = client.post(
        "/api/system/validate-heightmap",
        files={"file": ("heightmap.tiff", (FIXTURES / "heightmap.tiff").read_bytes(), "image/tiff")},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid or damaged heightmap image."}
    assert str(temp_dir) not in response.text
    assert not list(temp_dir.iterdir())


@pytest.mark.parametrize("size", [(1, 201), (201, 1)])
def test_narrow_heightmap_decodes_with_nonempty_thumbnail(validation_client, size):
    client, temp_dir = validation_client
    contents = io.BytesIO()
    Image.new("L", size, 128).save(contents, format="PNG")
    response = client.post(
        "/api/system/validate-heightmap",
        files={"file": ("narrow.png", contents.getvalue(), "image/png")},
    )
    assert response.status_code == 200
    assert response.json() == {"width": size[0], "height": size[1]}
    assert not list(temp_dir.iterdir())


def test_oversized_heightmap_cleans_partial_temp_file(validation_client, monkeypatch):
    client, temp_dir = validation_client
    monkeypatch.setattr(system, "_HEIGHTMAP_VALIDATION_MAX_BYTES", 16)
    response = client.post(
        "/api/system/validate-heightmap",
        files={"file": ("heightmap.png", (FIXTURES / "heightmap.png").read_bytes(), "image/png")},
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "Heightmap image exceeds 128 MiB."}
    assert not list(temp_dir.iterdir())
