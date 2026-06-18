import io
import os
import tempfile
import zlib
from contextlib import suppress
from typing import Optional
from urllib.parse import quote

import numpy as np
from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image, ImageOps
from PIL import UnidentifiedImageError
from api.structured_logging import get_logger

log = get_logger(__name__)

# HEIC/HEIF support (optional dependency)
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HAS_HEIF: bool = True
except ImportError:
    HAS_HEIF: bool = False
    log.warning(
        "pillow-heif not installed. HEIC/HEIF support disabled.",
        extra={"event": "optional_dependency_missing", "dependency": "pillow_heif"},
    )

# RAW support (optional dependency)
try:
    import rawpy

    HAS_RAW: bool = True
except ImportError:
    rawpy = None
    HAS_RAW: bool = False
    log.warning(
        "rawpy not installed. Camera RAW support disabled.",
        extra={"event": "optional_dependency_missing", "dependency": "rawpy"},
    )

HEIC_EXTENSIONS: set[str] = {".heic", ".heif"}
RAW_EXTENSIONS: set[str] = {
    ".dng",
    ".cr2",
    ".cr3",
    ".nef",
    ".arw",
    ".orf",
    ".rw2",
    ".raf",
    ".pef",
    ".srw",
    ".raw",
}
_PASSTHROUGH_IMAGE_EXTENSIONS: set[str] = {
    ".bmp",
    ".gif",
    ".jpg",
    ".jpeg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}
_SUPPORTED_UPLOAD_IMAGE_EXTENSIONS = (
    _PASSTHROUGH_IMAGE_EXTENSIONS | HEIC_EXTENSIONS | RAW_EXTENSIONS
)
_GZIP_CHUNK_SIZE = 1024 * 1024
_GLB_GZIP_MIN_BYTES = 1024
_UPLOAD_CHUNK_SIZE = 1024 * 1024
_UNSUPPORTED_IMAGE_UPLOAD_DETAIL = (
    "不支持的图像文件类型: "
    "请上传 PNG、JPEG、SVG、WebP、HEIC/HEIF、RAW、BMP、GIF 或 TIFF 图片。"
)
_UPLOAD_IMAGE_UNREADABLE_DETAIL = (
    "无法解码图像文件: 请重新上传有效的 PNG、JPEG、HEIC 或 RAW 图片后再试。"
)
_HEIC_UNREADABLE_DETAIL = (
    "HEIC/HEIF 文件解码失败: 请重新上传有效的 HEIC/HEIF 图片，"
    "或先转换为 PNG/JPEG 后再试。"
)
_RAW_UNREADABLE_DETAIL = (
    "RAW 文件解码失败: 请重新上传有效的 RAW 图片，或先转换为 PNG/JPEG 后再试。"
)
RAW_DECODE_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    RuntimeError,
)
if rawpy is not None and hasattr(rawpy, "LibRawError"):
    RAW_DECODE_ERRORS = RAW_DECODE_ERRORS + (rawpy.LibRawError,)


class UploadTooLargeError(ValueError):
    """Raised when an upload exceeds a caller-specified byte limit."""


def _write_all(fd: int, data: bytes) -> None:
    """Write every byte to ``fd``, retrying POSIX short writes."""

    view = memoryview(data)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise OSError("Failed to write uploaded file chunk")
        offset += written


def _decode_raw_to_pil(data: bytes) -> Image.Image:
    """用 rawpy 将 RAW 字节解码为 PIL Image（RGB）。

    Args:
        data: RAW 文件字节内容

    Returns:
        PIL Image，RGB 模式

    Raises:
        ValueError: rawpy 未安装或解码失败
    """
    if not HAS_RAW:
        raise ValueError("RAW 格式需要 rawpy 库。请执行: pip install rawpy")
    import rawpy  # noqa: PLC0415

    try:
        with rawpy.imread(io.BytesIO(data)) as raw:
            rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
    except RAW_DECODE_ERRORS as exc:
        raise ValueError(_RAW_UNREADABLE_DETAIL) from exc
    return Image.fromarray(rgb)


def _normalize_pil_orientation(img: Image.Image) -> Image.Image:
    """Normalize PIL image orientation according to EXIF metadata.
    根据 EXIF 元数据归一化 PIL 图像方向。
    """
    return ImageOps.exif_transpose(img)


async def upload_to_ndarray(file: UploadFile) -> np.ndarray:
    """将 UploadFile 图像转换为 RGB NumPy ndarray。

    Args:
        file: FastAPI UploadFile 对象

    Returns:
        np.ndarray: shape (H, W, 3), dtype uint8, RGB 格式（已归一化 EXIF 方向）

    Raises:
        ValueError: 文件格式无效或无法解码
    """
    contents = await file.read()
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext in RAW_EXTENSIONS:
        img = _decode_raw_to_pil(contents)
        return np.array(img, dtype=np.uint8)
    try:
        img = Image.open(io.BytesIO(contents))
        img = _normalize_pil_orientation(img)
        if img.mode != "RGB":
            img = img.convert("RGB")
        return np.array(img, dtype=np.uint8)
    except (UnidentifiedImageError, OSError, ValueError) as e:
        if ext in HEIC_EXTENSIONS and not HAS_HEIF:
            raise ValueError("HEIC/HEIF 格式需要 pillow-heif 库。请执行: pip install pillow-heif")
        raise ValueError(_UPLOAD_IMAGE_UNREADABLE_DETAIL) from e


async def upload_to_tempfile(
    file: UploadFile,
    suffix: Optional[str] = None,
    max_bytes: int | None = None,
) -> str:
    """将 UploadFile 保存为临时文件，返回路径。

    Args:
        file: FastAPI UploadFile 对象
        suffix: 文件后缀（如 ".png"、".svg"）

    Returns:
        str: 临时文件绝对路径
    """
    if suffix is None:
        suffix = os.path.splitext(file.filename or "")[1] or ".tmp"
    from config import TEMP_DIR

    fd, path = tempfile.mkstemp(suffix=suffix, dir=TEMP_DIR)
    try:
        if max_bytes is None:
            contents = await file.read()
            _write_all(fd, contents)
            os.close(fd)
            return path

        total_bytes = 0
        while True:
            chunk = await file.read(_UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise UploadTooLargeError(
                    f"Uploaded file exceeds maximum size: {max_bytes} bytes"
                )
            _write_all(fd, chunk)
        os.close(fd)
    except (OSError, RuntimeError, ValueError):
        with suppress(OSError):
            os.close(fd)
        with suppress(OSError):
            os.unlink(path)
        raise
    return path


async def ensure_png_tempfile(file: UploadFile) -> str:
    """Validate and save uploaded image to temp; convert HEIC/HEIF/RAW to PNG.
    校验并保存上传图片为临时文件；若为 HEIC/HEIF/RAW 则转换为 PNG。

    Args:
        file (UploadFile): FastAPI upload. (FastAPI 上传文件)

    Returns:
        str: Temp file path (PNG if converted). (临时文件路径)

    Raises:
        HTTPException: unsupported image type, missing dependency, or decode failure.
        (不支持的图像类型、依赖缺失或解码失败)
    """
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _SUPPORTED_UPLOAD_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=422, detail=_UNSUPPORTED_IMAGE_UPLOAD_DETAIL)

    raw_path = await upload_to_tempfile(file)

    if ext not in HEIC_EXTENSIONS and ext not in RAW_EXTENSIONS:
        return raw_path

    if ext in HEIC_EXTENSIONS and not HAS_HEIF:
        with suppress(OSError):
            os.unlink(raw_path)
        raise HTTPException(
            status_code=422,
            detail="HEIC/HEIF 格式需要 pillow-heif 库。请执行: pip install pillow-heif",
        )

    if ext in RAW_EXTENSIONS and not HAS_RAW:
        with suppress(OSError):
            os.unlink(raw_path)
        raise HTTPException(
            status_code=422,
            detail="RAW 格式需要 rawpy 库。请执行: pip install rawpy",
        )

    png_path: str | None = None
    try:
        if ext in RAW_EXTENSIONS:
            with open(raw_path, "rb") as f:
                data = f.read()
            img = _decode_raw_to_pil(data)
        else:
            img = Image.open(raw_path)
        img = _normalize_pil_orientation(img)
        if img.mode != "RGB":
            img = img.convert("RGB")
        from config import TEMP_DIR

        fd, png_path = tempfile.mkstemp(suffix=".png", dir=TEMP_DIR)
        os.close(fd)
        img.save(png_path, "PNG")
        os.unlink(raw_path)
        converted_path = png_path
        png_path = None
        return converted_path
    except HTTPException:
        with suppress(OSError):
            os.unlink(raw_path)
        if png_path is not None:
            with suppress(OSError):
                os.unlink(png_path)
        raise
    except (UnidentifiedImageError, OSError, ValueError, RuntimeError) as e:
        with suppress(OSError):
            os.unlink(raw_path)
        if png_path is not None:
            with suppress(OSError):
                os.unlink(png_path)
        detail = _RAW_UNREADABLE_DETAIL if ext in RAW_EXTENSIONS else _HEIC_UNREADABLE_DETAIL
        raise HTTPException(
            status_code=422,
            detail=detail,
        ) from e


def pil_to_png_bytes(img: Image.Image) -> bytes:
    """将 PIL Image 编码为 PNG 字节流。"""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def ndarray_to_png_bytes(arr: np.ndarray) -> bytes:
    """将 NumPy ndarray 编码为 PNG 字节流。"""
    img = Image.fromarray(arr)
    return pil_to_png_bytes(img)


def pil_to_streaming_response(img: Image.Image, fmt: str = "PNG") -> StreamingResponse:
    """将 PIL Image 编码为 StreamingResponse。"""
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    media_type = "image/png" if fmt.upper() == "PNG" else f"image/{fmt.lower()}"
    return StreamingResponse(buf, media_type=media_type)


def file_to_response(
    path: str,
    filename: Optional[str] = None,
    *,
    accept_encoding: str | None = None,
    range_header: str | None = None,
) -> FileResponse | StreamingResponse:
    """Wrap a file path as an HTTP response.
    将文件路径包装为 HTTP 响应。
    """
    if filename is None:
        filename = os.path.basename(path)
    media_type = _guess_media_type(path)
    # Disable browser caching for image previews to ensure fresh content
    # after color replacement / reset operations.
    headers = {"Cache-Control": "no-cache, no-store, must-revalidate"}
    if _should_gzip_glb_response(
        path,
        filename,
        accept_encoding=accept_encoding,
        range_header=range_header,
    ):
        return StreamingResponse(
            _iter_gzip_file(path),
            media_type=media_type,
            headers={
                **headers,
                "Content-Encoding": "gzip",
                "Vary": "Accept-Encoding",
                "Content-Disposition": _content_disposition(filename),
            },
        )
    return FileResponse(path=path, filename=filename, media_type=media_type, headers=headers)


def _should_gzip_glb_response(
    path: str,
    filename: str,
    *,
    accept_encoding: str | None,
    range_header: str | None,
) -> bool:
    if range_header:
        return False
    if not _accepts_gzip(accept_encoding):
        return False
    if (
        os.path.splitext(filename)[1].lower() != ".glb"
        and os.path.splitext(path)[1].lower() != ".glb"
    ):
        return False
    try:
        return os.path.getsize(path) >= _GLB_GZIP_MIN_BYTES
    except OSError:
        return False


def _accepts_gzip(accept_encoding: str | None) -> bool:
    if not accept_encoding:
        return False
    for raw_item in accept_encoding.split(","):
        item = raw_item.strip()
        if not item:
            continue
        token, *params = item.split(";")
        token = token.strip().lower()
        if token not in {"gzip", "*"}:
            continue
        q_value = 1.0
        for param in params:
            key, sep, value = param.strip().partition("=")
            if sep and key.lower() == "q":
                try:
                    q_value = float(value)
                except ValueError:
                    q_value = 0.0
        return q_value > 0.0
    return False


def _iter_gzip_file(path: str):
    compressor = zlib.compressobj(
        level=6,
        method=zlib.DEFLATED,
        wbits=16 + zlib.MAX_WBITS,
    )
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_GZIP_CHUNK_SIZE)
            if not chunk:
                break
            compressed = compressor.compress(chunk)
            if compressed:
                yield compressed
    tail = compressor.flush()
    if tail:
        yield tail


def _content_disposition(filename: str) -> str:
    content_disposition_filename = quote(filename)
    if content_disposition_filename != filename:
        return f"attachment; filename*=utf-8''{content_disposition_filename}"
    return f'attachment; filename="{filename}"'


def _guess_media_type(path: str) -> str:
    """根据文件扩展名推断 MIME 类型。"""
    ext = os.path.splitext(path)[1].lower()
    return {
        ".3mf": "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
        ".glb": "model/gltf-binary",
        ".zip": "application/zip",
        ".npy": "application/octet-stream",
        ".npz": "application/octet-stream",
        ".json": "application/json",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".svg": "image/svg+xml",
        ".dng": "image/x-adobe-dng",
        ".cr2": "image/x-canon-cr2",
        ".cr3": "image/x-canon-cr3",
        ".nef": "image/x-nikon-nef",
        ".arw": "image/x-sony-arw",
        ".orf": "image/x-olympus-orf",
        ".rw2": "image/x-panasonic-rw2",
        ".raf": "image/x-fuji-raf",
        ".pef": "image/x-pentax-pef",
        ".srw": "image/x-samsung-srw",
        ".raw": "image/x-raw",
    }.get(ext, "application/octet-stream")
