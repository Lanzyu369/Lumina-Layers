"""Top-level worker functions for vectorizer CPU tasks.
Vectorizer CPU 任务的顶层工作函数。

These functions run in separate processes via ProcessPoolExecutor.
All arguments must be picklable (file paths, scalars, dicts of scalars).
这些函数通过 ProcessPoolExecutor 在独立进程中运行。
所有参数必须可序列化（文件路径、标量、标量字典）。

Design rules:
- Top-level functions only (no methods) — must be picklable.
- Accept only file paths (str) and scalar parameters.
- Large results (SVG content) are written to temp files; paths are returned.
- All imports of neroued_vectorizer are lazy (inside function body).
"""

# Accepted upload formats the native loader cannot decode, detected by content.
# 已接受但原生加载器无法解码的格式（按文件内容识别）。
_NATIVE_UNREADABLE_FORMATS = frozenset({"WEBP", "TIFF"})
_TIFF_SIGNATURES = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")
_PNG_NATIVE_MODES = frozenset({"1", "L", "LA", "P", "RGB", "RGBA", "I;16"})


def _is_native_unreadable(image_path: str) -> bool:
    """Return True when the file starts with a WebP or TIFF signature.
    文件头为 WebP 或 TIFF 签名时返回 True。
    """
    with open(image_path, "rb") as f:
        head = f.read(12)
    is_webp = head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return is_webp or head[:4] in _TIFF_SIGNATURES


def _transcode_for_native_loader(image_path: str, temp_dir: str) -> str | None:
    """Re-encode WebP/TIFF content as a lossless PNG temp file.
    将 WebP/TIFF 内容无损重编码为临时 PNG 文件。

    Only files with a WebP/TIFF signature are opened with Pillow, so formats
    the native loader reads (PNG/JPEG/BMP/...) keep their original handling.
    The PNG carries Pillow's decoded pixels and alpha: Pillow applies the TIFF
    Orientation tag while decoding, but not WebP EXIF orientation (which the
    native loader also ignores for PNG/JPEG). Unsigned 16-bit grey keeps its
    full 0..65535 range in every byte order. Signed 16-bit grey keeps positive
    samples and saturates negatives to black, matching the native loader.
    If Pillow cannot open, decode or size-check the file, the native loader
    gets the original path.
    仅对 WebP/TIFF 签名的文件使用 Pillow，原生可读格式保持原有处理。PNG 保存
    Pillow 解码后的像素与透明度（TIFF 方向标签由 Pillow 解码时应用，WebP EXIF
    方向不应用）；任意字节序的无符号 16 位灰度保留 0..65535 完整范围，
    有符号 16 位灰度保留正值并将负值饱和为黑色，与原生加载器一致。
    Pillow 无法打开、解码或超出像素限制时，原样交给原生加载器。

    Args:
        image_path (str): Uploaded image temp path. (上传图像临时路径)
        temp_dir (str): Directory for the PNG temp file. (PNG 临时文件目录)

    Returns:
        str | None: PNG temp path the caller must delete, or None when the
            original path should be used. (调用方需删除的 PNG 路径，或 None)
    """
    import os
    import tempfile

    from PIL import Image, UnidentifiedImageError

    try:
        if not _is_native_unreadable(image_path):
            return None
        img = Image.open(image_path)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
        return None

    with img:
        if img.format not in _NATIVE_UNREADABLE_FORMATS:
            return None
        try:
            img.load()
        except (Image.DecompressionBombError, OSError):
            return None
        if (
            img.format == "TIFF"
            and img.mode == "I"
            and img.tag_v2.get(258) == (16,)  # BitsPerSample
            and img.tag_v2.get(339) == (2,)  # SampleFormat: signed integer
        ):
            # Pillow decodes signed 16-bit grey as I. PNG cannot store signed
            # samples; clamp negatives to zero and retain positive values so
            # the native loader applies its existing 1/256 scaling once.
            img = img.convert("I;16")
        elif img.mode.startswith("I;16") and img.mode != "I;16":
            # Other 16-bit grey byte orders (e.g. big-endian I;16B) clip at 255
            # when converted directly; go through 32-bit I to keep 0..65535.
            # 其他字节序的 16 位灰度直接转换会截断到 255，经 I 中转以保留完整范围。
            img = img.convert("I").convert("I;16")
        elif img.mode not in _PNG_NATIVE_MODES:
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        fd, png_path = tempfile.mkstemp(suffix=".png", dir=temp_dir)
        os.close(fd)
        try:
            img.save(png_path, "PNG")
        except Exception:
            os.unlink(png_path)
            raise
    return png_path


def _native_image_input(image_path: str) -> str | bytes:
    """Return the input to hand to the native loader for ``image_path``.
    返回交给原生加载器的输入。

    The native path loader opens files with a narrow (non-Unicode) API on
    Windows, so a path with non-ASCII characters (e.g. a Chinese user name in
    TEMP_DIR) fails with "Failed to load image". For such paths the file is
    read in Python and passed as encoded bytes, which the native library
    decodes with the same flags as its path loader. ASCII paths, and files
    Python cannot read, keep the original path handoff and native errors.
    原生路径加载器在 Windows 上使用非 Unicode 接口打开文件，含非 ASCII 字符的
    路径（如 TEMP_DIR 中的中文用户名）会报 "Failed to load image"。此类路径在
    Python 中读取后以编码字节传入，原生库按与路径加载相同的标志解码。ASCII
    路径以及 Python 无法读取的文件保持原路径传入和原生错误。

    Args:
        image_path (str): Uploaded image temp path. (上传图像临时路径)

    Returns:
        str | bytes: The original path, or the file's encoded bytes.
            (原路径，或文件的编码字节)
    """
    if image_path.isascii():
        return image_path
    try:
        with open(image_path, "rb") as f:
            return f.read()
    except OSError:
        return image_path


def worker_vectorize(image_path: str, params: dict) -> dict:
    """Execute image vectorization in a worker process.
    在工作进程中执行图像矢量化。

    Calls ``neroued_vectorizer.vectorize()`` with the supplied parameters,
    writes the SVG output to a temporary file, and returns a dict of
    results including file path and statistics.

    Args:
        image_path (str): Path to the input image file. (输入图像文件路径)
        params (dict): Dict of scalar parameters matching VectorizerConfig
            attributes (e.g. num_colors, smoothness, detail_level, etc.).
            (标量参数字典，对应 VectorizerConfig 属性)

    Returns:
        dict: Result dictionary with keys: (结果字典，包含以下键)
            - svg_path (str): Path to the generated SVG file.
            - width (int): Source image width in pixels.
            - height (int): Source image height in pixels.
            - num_shapes (int): Number of shapes in the SVG.
            - num_colors (int): Number of resolved colors.
            - palette (list[str]): Hex color strings of the palette.
    """
    import os
    import re
    import tempfile

    import neroued_vectorizer as nv
    from api.structured_logging import get_logger

    log = get_logger(__name__)

    native_input_path: str | None = None
    try:
        from config import TEMP_DIR

        config = nv.VectorizerConfig()
        for key, value in params.items():
            if hasattr(config, key):
                setattr(config, key, value)

        log.info(
            "Worker vectorization started",
            extra={
                "event": "worker_vectorize_started",
                "image_path": image_path,
                "params": params,
            },
        )

        native_input_path = _transcode_for_native_loader(image_path, TEMP_DIR)
        result = nv.vectorize(_native_image_input(native_input_path or image_path), config)

        svg_content = result.svg_content
        if "data-lumina-origin=" not in svg_content:
            svg_content = re.sub(
                r"(<svg\b)",
                r'\1 data-lumina-origin="image-vectorizer"',
                svg_content,
                count=1,
                flags=re.IGNORECASE,
            )

        fd, svg_path = tempfile.mkstemp(suffix=".svg", dir=TEMP_DIR)
        os.close(fd)
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg_content)

        palette_hex = []
        for rgb in result.palette:
            r, g, b = rgb.to_rgb255()
            palette_hex.append(f"#{r:02x}{g:02x}{b:02x}")

        return {
            "svg_path": svg_path,
            "width": result.width,
            "height": result.height,
            "num_shapes": result.num_shapes,
            "num_colors": result.resolved_num_colors,
            "palette": palette_hex,
        }
    finally:
        for path in (image_path, native_input_path):
            if path and os.path.exists(path):
                os.unlink(path)
