"""Tests for ColorChecker image decoding helpers."""

from __future__ import annotations

import io

from PIL import Image

import core.colorchecker.image_io as image_io


def test_standard_decode_applies_exif_orientation(monkeypatch) -> None:
    """Standard JPEG decoding should match browser-visible EXIF orientation."""
    source = Image.new("RGB", (2, 3), (0, 0, 0))
    exif = source.getexif()
    exif[274] = 6
    buffer = io.BytesIO()
    source.save(buffer, format="JPEG", exif=exif)

    def fail_imdecode(*_args, **_kwargs):
        raise AssertionError("decode_standard_image_bytes should not use cv2.imdecode")

    monkeypatch.setattr(image_io.cv2, "imdecode", fail_imdecode)

    decoded = image_io.decode_standard_image_bytes(buffer.getvalue())

    assert decoded is not None
    assert decoded.shape[:2] == (2, 3)
