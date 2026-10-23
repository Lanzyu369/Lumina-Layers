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

    try:
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

        result = nv.vectorize(_native_image_input(image_path), config)

        from config import TEMP_DIR

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
        if os.path.exists(image_path):
            os.unlink(image_path)
