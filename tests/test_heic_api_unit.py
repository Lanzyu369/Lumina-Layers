# -*- coding: utf-8 -*-
"""
Unit tests for HEIC/HEIF API layer error handling and endpoint integration.

Feature: heic-api-support
Validates: Requirements 4.1, 4.2, 1.2
"""

import asyncio
import io
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from PIL import Image

import api.file_bridge as file_bridge
from api.file_bridge import (
    HAS_HEIF,
    _guess_media_type,
    ensure_png_tempfile,
    upload_to_tempfile,
)


def _make_upload_file(filename: str, content: bytes = b"fake") -> MagicMock:
    """Create a mock UploadFile with given filename and content.
    创建具有指定文件名和内容的模拟 UploadFile。
    """
    mock = MagicMock()
    mock.filename = filename
    mock.read = AsyncMock(return_value=content)
    return mock


def _make_png_bytes() -> bytes:
    """Create a tiny valid PNG payload for extension-based conversion tests."""

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (255, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


class TestUploadToTempfileWriteSafety:
    """Shared upload persistence should write complete files or clean up."""

    def test_short_os_write_is_retried_until_payload_is_complete(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        payload = b"abcdefghijklmnopqrstuvwxyz"
        original_write = file_bridge.os.write
        written_lengths: list[int] = []

        def short_write(fd: int, data) -> int:  # noqa: ANN001
            chunk = bytes(data[:5])
            written_lengths.append(len(chunk))
            return original_write(fd, chunk)

        monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
        monkeypatch.setattr(file_bridge.os, "write", short_write)

        path = asyncio.run(upload_to_tempfile(_make_upload_file("sample.bin", payload)))
        try:
            with open(path, "rb") as saved:
                assert saved.read() == payload
            assert len(written_lengths) > 1
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_write_failure_removes_created_temp_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        def raise_write_error(fd: int, data: bytes) -> int:
            raise OSError("simulated short write failure")

        monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
        monkeypatch.setattr(file_bridge.os, "write", raise_write_error)

        with pytest.raises(OSError, match="simulated short write failure"):
            asyncio.run(upload_to_tempfile(_make_upload_file("sample.bin", b"payload")))

        assert list(tmp_path.iterdir()) == []

    def test_zero_byte_write_removes_created_temp_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        def write_zero_bytes(fd: int, data: bytes) -> int:
            return 0

        monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
        monkeypatch.setattr(file_bridge.os, "write", write_zero_bytes)

        with pytest.raises(OSError, match="Failed to write uploaded file chunk"):
            asyncio.run(upload_to_tempfile(_make_upload_file("sample.bin", b"payload")))

        assert list(tmp_path.iterdir()) == []


# ── Test 1: ensure_png_tempfile raises 422 when HAS_HEIF=False ────────
# Validates: Requirement 4.1
class TestEnsurePngRaises422WhenHeifNotInstalled:
    """HAS_HEIF=False + HEIC upload → HTTP 422 with install guidance."""

    def test_heic_extension(self) -> None:
        mock_file = _make_upload_file("photo.heic")
        with patch("api.file_bridge.HAS_HEIF", False):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(ensure_png_tempfile(mock_file))
            assert exc_info.value.status_code == 422
            assert "pillow-heif" in exc_info.value.detail

    def test_heif_extension(self) -> None:
        mock_file = _make_upload_file("photo.heif")
        with patch("api.file_bridge.HAS_HEIF", False):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(ensure_png_tempfile(mock_file))
            assert exc_info.value.status_code == 422
            assert "pillow-heif" in exc_info.value.detail

    def test_uppercase_heic_extension(self) -> None:
        """Filename with .HEIC (uppercase) should also trigger 422."""
        mock_file = _make_upload_file("photo.HEIC")
        with patch("api.file_bridge.HAS_HEIF", False):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(ensure_png_tempfile(mock_file))
            assert exc_info.value.status_code == 422

    def test_cleanup_failure_preserves_unsupported_heic_422(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        mock_file = _make_upload_file("photo.heic", content=_make_png_bytes())

        def raise_cleanup_error(path: str) -> None:
            raise OSError(f"simulated cleanup failure for {path}")

        monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
        monkeypatch.setattr(file_bridge.os, "unlink", raise_cleanup_error)

        with patch("api.file_bridge.HAS_HEIF", False):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(ensure_png_tempfile(mock_file))

        assert exc_info.value.status_code == 422
        assert "pillow-heif" in exc_info.value.detail


class TestEnsurePngConversionFailureCleanup:
    """HEIC conversion failures should not leave unregistered PNG files."""

    def test_save_failure_removes_created_png_temp_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        mock_file = _make_upload_file("photo.heic", content=_make_png_bytes())

        def fail_save(self, path, *args, **kwargs):  # noqa: ANN001
            raise RuntimeError("simulated conversion save failure")

        monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))

        with (
            patch("api.file_bridge.HAS_HEIF", True),
            patch.object(Image.Image, "save", fail_save),
        ):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(ensure_png_tempfile(mock_file))

        assert exc_info.value.status_code == 422
        assert "simulated conversion save failure" in exc_info.value.detail
        assert list(tmp_path.iterdir()) == []

    def test_raw_cleanup_failure_does_not_leak_png_or_escape_as_oserror(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        mock_file = _make_upload_file("photo.heic", content=_make_png_bytes())
        original_unlink = file_bridge.os.unlink

        def fail_raw_unlink(path: str) -> None:
            if str(path).endswith(".heic"):
                raise OSError("simulated raw cleanup failure")
            original_unlink(path)

        monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
        monkeypatch.setattr(file_bridge.os, "unlink", fail_raw_unlink)

        with patch("api.file_bridge.HAS_HEIF", True):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(ensure_png_tempfile(mock_file))

        assert exc_info.value.status_code == 422
        assert "simulated raw cleanup failure" in exc_info.value.detail
        assert not any(path.suffix == ".png" for path in tmp_path.iterdir())


# ── Test 2: HAS_HEIF flag consistency with pillow_heif install ─────────
# Validates: Requirement 1.2
class TestHasHeifFlagConsistency:
    """HAS_HEIF flag must match actual pillow_heif availability."""

    def test_flag_matches_import(self) -> None:
        try:
            import pillow_heif  # noqa: F401
            heif_available = True
        except ImportError:
            heif_available = False

        assert HAS_HEIF is heif_available, (
            f"HAS_HEIF={HAS_HEIF} but pillow_heif importable={heif_available}"
        )


# ── Test 3: _guess_media_type unknown extension → default ──────────────
# Validates: Requirement 2.1, 2.2 (inverse — unknown ext)
class TestGuessMediaTypeUnknown:
    """Unknown extensions return application/octet-stream."""

    def test_unknown_extension_returns_default(self) -> None:
        assert _guess_media_type("/tmp/file.xyz") == "application/octet-stream"

    def test_no_extension_returns_default(self) -> None:
        assert _guess_media_type("/tmp/noext") == "application/octet-stream"


# ── Test 4 & 5: _guess_media_type HEIC/HEIF → correct MIME ────────────
# Validates: Requirement 2.1, 2.2
class TestGuessMediaTypeHeic:
    """HEIC/HEIF extensions map to correct MIME types."""

    def test_heic_returns_image_heic(self) -> None:
        assert _guess_media_type("/tmp/photo.heic") == "image/heic"

    def test_heif_returns_image_heif(self) -> None:
        assert _guess_media_type("/tmp/photo.heif") == "image/heif"


# ── Test 6: ensure_png_tempfile non-HEIC returns original path ─────────
# Validates: Requirement 3.4
class TestEnsurePngNonHeicPassthrough:
    """Non-HEIC files pass through without conversion."""

    def test_png_returns_original_path(self) -> None:
        mock_file = _make_upload_file("image.png", content=b"PNG data")
        path = asyncio.run(ensure_png_tempfile(mock_file))
        try:
            assert path.endswith(".png")
            assert os.path.exists(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_jpg_returns_original_path(self) -> None:
        mock_file = _make_upload_file("image.jpg", content=b"JPEG data")
        path = asyncio.run(ensure_png_tempfile(mock_file))
        try:
            assert path.endswith(".jpg")
            assert os.path.exists(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)
