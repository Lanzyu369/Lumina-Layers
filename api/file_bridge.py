import io
import os
import tempfile
import zlib
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
_GZIP_CHUNK_SIZE = 1024 * 1024
_GLB_GZIP_MIN_BYTES = 1024
_UPLOAD_CHUNK_SIZE = 1024 * 1024


class UploadTooLargeError(ValueError):
    """Raised when an upload exceeds a caller-specified byte limit."""


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

    with rawpy.imread(io.BytesIO(data)) as raw:
        rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
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
        raise ValueError(f"无法解码图像文件: {e}")


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
    if max_bytes is None:
        contents = await file.read()
        try:
            os.write(fd, contents)
        finally:
            os.close(fd)
        return path

    try:
        total_bytes = 0
        with os.fdopen(fd, "wb") as handle:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise UploadTooLargeError(
                        f"Uploaded file exceeds maximum size: {max_bytes} bytes"
                    )
                handle.write(chunk)
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    return path


async def ensure_png_tempfile(file: UploadFile) -> str:
    """Save uploaded file to temp; convert HEIC/HEIF to PNG.
    保存上传文件为临时文件；若为 HEIC/HEIF 则转换为 PNG。

    Args:
        file (UploadFile): FastAPI upload. (FastAPI 上传文件)

    Returns:
        str: Temp file path (PNG if converted). (临时文件路径)

    Raises:
        HTTPException: pillow-heif missing or decode failure. (解码失败)
    """
    ext = os.path.splitext(file.filename or "")[1].lower()
    raw_path = await upload_to_tempfile(file)

    if ext not in HEIC_EXTENSIONS and ext not in RAW_EXTENSIONS:
        return raw_path

    if ext in HEIC_EXTENSIONS and not HAS_HEIF:
        os.unlink(raw_path)
        raise HTTPException(
            status_code=422,
            detail="HEIC/HEIF 格式需要 pillow-heif 库。请执行: pip install pillow-heif",
        )

    if ext in RAW_EXTENSIONS and not HAS_RAW:
        os.unlink(raw_path)
        raise HTTPException(
            status_code=422,
            detail="RAW 格式需要 rawpy 库。请执行: pip install rawpy",
        )

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
        return png_path
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, RuntimeError) as e:
        os.unlink(raw_path)
        fmt = "RAW" if ext in RAW_EXTENSIONS else "HEIC/HEIF"
        raise HTTPException(
            status_code=422,
            detail=f"{fmt} 文件解码失败: {e}",
        )


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
