"""JFIF uploads must pass extension validation and produce readable previews."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.dependencies import get_file_registry
from api.file_registry import FileRegistry


@pytest.mark.parametrize("filename", ["photo.jfif", "photo.JFIF"])
@pytest.mark.parametrize("content_type", ["image/jpeg", "application/octet-stream"])
def test_jfif_upload_preview_is_readable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    filename: str,
    content_type: str,
) -> None:
    monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
    buffer = io.BytesIO()
    Image.new("RGB", (6, 5), (230, 40, 70)).save(buffer, format="JPEG")
    payload = buffer.getvalue()
    assert b"JFIF\x00" in payload

    app = create_app()
    registry = FileRegistry()
    app.dependency_overrides[get_file_registry] = lambda: registry
    with TestClient(app) as client:
        response = client.post(
            "/api/system/image-preview",
            files={"file": (filename, payload, content_type)},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["width"], body["height"]) == (6, 5)

        preview = client.get(body["preview_url"])
        assert preview.status_code == 200
        assert preview.headers["content-type"] == "image/jpeg"
        assert preview.content == payload
        with Image.open(io.BytesIO(preview.content)) as image:
            image.load()
            assert image.format == "JPEG"
            assert image.size == (6, 5)


def test_corrupt_jfif_upload_is_rejected_and_cleaned_up(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/system/image-preview",
            files={"file": ("broken.jfif", b"not an image", "image/jpeg")},
        )
    assert response.status_code == 422, response.text
    assert list(tmp_path.iterdir()) == []
