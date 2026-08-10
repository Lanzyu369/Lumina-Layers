"""Unit contracts for converter-specific artwork validation."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from api.routers.converter import source_validation
from api.routers.converter.source_validation import (
    ConverterSourceValidationError,
    validate_converter_source,
)


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 3), (12, 34, 56)).save(buffer, format="PNG")
    return buffer.getvalue()


def _truncated_jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (100, 100), (12, 34, 56)).save(buffer, format="JPEG")
    return buffer.getvalue()[:-10]


def _assert_validation_error(
    path: Path,
    *,
    code: str,
    status_code: int,
) -> ConverterSourceValidationError:
    with pytest.raises(ConverterSourceValidationError) as exc_info:
        validate_converter_source(path)

    error = exc_info.value
    assert error.error_code == code
    assert error.status_code == status_code
    assert str(path) not in error.public_message
    return error


def test_validate_converter_source_accepts_valid_raster_content(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(_png_bytes())

    validate_converter_source(source)


def test_validate_converter_source_accepts_raster_to_raster_mismatch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(_png_bytes())

    validate_converter_source(source)


def test_validate_converter_source_accepts_converted_heic_png_output(
    tmp_path: Path,
) -> None:
    converted = tmp_path / "converted-heic.png"
    converted.write_bytes(_png_bytes())

    validate_converter_source(converted)


@pytest.mark.parametrize("payload", [b"not-an-image", b""])
def test_validate_converter_source_rejects_unreadable_raster(
    tmp_path: Path,
    payload: bytes,
) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(payload)

    _assert_validation_error(
        source,
        code="source_image_unreadable",
        status_code=422,
    )


def test_validate_converter_source_rejects_truncated_jpeg_pixels(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(_truncated_jpeg_bytes())

    _assert_validation_error(
        source,
        code="source_image_unreadable",
        status_code=422,
    )


def test_validate_converter_source_uses_declared_svg_path_for_png_bytes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.svg"
    source.write_bytes(_png_bytes())

    _assert_validation_error(
        source,
        code="source_svg_invalid",
        status_code=422,
    )


def test_validate_converter_source_uses_declared_raster_path_for_svg_bytes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    source.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")

    _assert_validation_error(
        source,
        code="source_image_unreadable",
        status_code=422,
    )


@pytest.mark.parametrize(
    "payload",
    [
        b"<svg><path></svg>",
        b'<?xml version="1.0"?><document/>',
        b'<svg xmlns="urn:not-svg"/>',
    ],
)
def test_validate_converter_source_rejects_invalid_svg_document(
    tmp_path: Path,
    payload: bytes,
) -> None:
    source = tmp_path / "source.svg"
    source.write_bytes(payload)

    _assert_validation_error(
        source,
        code="source_svg_invalid",
        status_code=422,
    )


def test_validate_converter_source_accepts_structurally_valid_svg(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.svg"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>',
        encoding="utf-8",
    )

    validate_converter_source(source)


def test_validate_converter_source_maps_decompression_bomb_to_413(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"opened-before-pillow")
    monkeypatch.setattr(
        source_validation.Image,
        "open",
        lambda _handle: (_ for _ in ()).throw(
            Image.DecompressionBombError("private decode diagnostic")
        ),
    )

    error = _assert_validation_error(
        source,
        code="source_image_too_large",
        status_code=413,
    )
    assert "private decode diagnostic" not in error.public_message


def test_validate_converter_source_promotes_decompression_warning_to_413(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(_png_bytes())
    # The fixture has 12 pixels: above 8 emits Pillow's warning, but stays
    # below the 16-pixel hard-error threshold.
    monkeypatch.setattr(source_validation.Image, "MAX_IMAGE_PIXELS", 8)

    _assert_validation_error(
        source,
        code="source_image_too_large",
        status_code=413,
    )


def test_validate_converter_source_maps_post_open_decode_io_error_to_422(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"opened-before-pillow")
    monkeypatch.setattr(
        source_validation.Image,
        "open",
        lambda _handle: (_ for _ in ()).throw(OSError("decode failed")),
    )

    _assert_validation_error(
        source,
        code="source_image_unreadable",
        status_code=422,
    )


def test_validate_converter_source_maps_post_open_syntax_error_to_422(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"opened-before-pillow")
    monkeypatch.setattr(
        source_validation.Image,
        "open",
        lambda _handle: (_ for _ in ()).throw(SyntaxError("invalid image header")),
    )

    _assert_validation_error(
        source,
        code="source_image_unreadable",
        status_code=422,
    )


def test_validate_converter_source_does_not_reclassify_file_open_failure(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.png"

    with pytest.raises(FileNotFoundError):
        validate_converter_source(missing)
