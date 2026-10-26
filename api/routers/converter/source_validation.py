"""Converter-specific validation for newly uploaded artwork."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import BinaryIO
from xml.etree import ElementTree

from PIL import Image, UnidentifiedImageError

SOURCE_IMAGE_UNREADABLE_ERROR = "source_image_unreadable"
SOURCE_IMAGE_TOO_LARGE_ERROR = "source_image_too_large"
SOURCE_SVG_INVALID_ERROR = "source_svg_invalid"
SOURCE_SVG_NO_RENDERABLE_GEOMETRY_ERROR = "source_svg_no_renderable_geometry"

SOURCE_IMAGE_UNREADABLE_DETAIL = (
    "The image could not be read. Check that the file is not damaged, then "
    "re-export it as PNG, JPEG, or WebP and upload it again."
)
SOURCE_IMAGE_TOO_LARGE_DETAIL = (
    "The image dimensions are too large to process safely. Reduce the image "
    "resolution and upload it again."
)
SOURCE_SVG_INVALID_DETAIL = (
    "The SVG could not be parsed. Re-export a valid SVG from your design "
    "application and upload it again."
)
SOURCE_SVG_NO_RENDERABLE_GEOMETRY_DETAIL = (
    "The SVG has no visible filled geometry supported by Vector mode. Make "
    "the artwork visible, convert strokes and text to filled paths, or switch "
    "to High-Fidelity mode."
)


class ConverterSourceValidationError(ValueError):
    """Describe a safe validation failure for newly uploaded artwork.

    描述可安全返回给用户的新上传图稿校验失败。
    """

    def __init__(
        self,
        error_code: str,
        public_message: str,
        *,
        status_code: int = 422,
    ) -> None:
        super().__init__(public_message)
        self.error_code = error_code
        self.public_message = public_message
        self.status_code = status_code

    @property
    def detail(self) -> dict[str, str]:
        """Return the stable structured API detail. 返回稳定的结构化 API 详情。"""

        return {
            "error": self.error_code,
            "message": self.public_message,
        }


def _validate_svg_document(source_file: BinaryIO) -> None:
    try:
        document = ElementTree.parse(source_file)
    except ElementTree.ParseError as exc:
        raise ConverterSourceValidationError(
            SOURCE_SVG_INVALID_ERROR,
            SOURCE_SVG_INVALID_DETAIL,
        ) from exc

    root_tag = str(document.getroot().tag)
    if root_tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
        raise ConverterSourceValidationError(
            SOURCE_SVG_INVALID_ERROR,
            SOURCE_SVG_INVALID_DETAIL,
        )


def _validate_raster_document(source_file: BinaryIO) -> None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source_file) as image:
                image.verify()
            # ``verify()`` checks container structure but does not decode every
            # pixel. Truncated JPEGs can pass it and fail later in the worker,
            # so rewind and force a complete decode at this request boundary.
            source_file.seek(0)
            with Image.open(source_file) as image:
                image.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ConverterSourceValidationError(
            SOURCE_IMAGE_TOO_LARGE_ERROR,
            SOURCE_IMAGE_TOO_LARGE_DETAIL,
            status_code=413,
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise ConverterSourceValidationError(
            SOURCE_IMAGE_UNREADABLE_ERROR,
            SOURCE_IMAGE_UNREADABLE_DETAIL,
        ) from exc


def validate_converter_source(source_path: str | Path) -> None:
    """Validate a persisted converter upload before worker submission.

    在提交工作进程前校验已持久化的转换器上传文件。

    Filesystem-open errors intentionally propagate. Only decode failures after
    the file is open are classified as user-input errors.
    文件系统打开错误会原样传播；仅文件打开后的解码失败归类为用户输入错误。
    """

    path = Path(source_path)
    with path.open("rb") as source_file:
        if path.suffix.lower() == ".svg":
            _validate_svg_document(source_file)
        else:
            _validate_raster_document(source_file)
