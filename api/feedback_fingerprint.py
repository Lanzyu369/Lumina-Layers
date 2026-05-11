"""SHA256 fingerprint + MIME guessing utilities for the feedback subsystem.

反馈子系统使用的 SHA256 指纹与 MIME 类型嗅探工具函数。

The ticket assembler records a content-addressed fingerprint for every
attachment it copies into a bug-report ticket (original image, final 3MF,
LUT snapshot, materials bundle, screenshot). Two tiny helpers are enough to
cover that surface:

* :func:`file_sha256` streams a file's bytes through :mod:`hashlib` in
  fixed-size chunks so we never load a multi-hundred-megabyte artifact into
  memory just to hash it.
* :func:`guess_mime` maps a path's extension to a best-effort MIME type,
  falling back to ``application/octet-stream`` instead of raising when the
  extension is unknown — useful when annotating manifests for attachments we
  still want to include but cannot classify.

工单装配器会为它拷贝到 Bug 报告目录中的每个附件（原图、最终 3MF、LUT 快照、
材料档案 zip、截图）记录一个内容哈希指纹。这里两个小工具函数覆盖了这一需求：

* :func:`file_sha256` 通过 :mod:`hashlib` 按固定大小分块流式读取文件，
  避免为了计算哈希而把几百 MB 的产物一次性载入内存。
* :func:`guess_mime` 尽力从路径后缀推断 MIME 类型，未知后缀时回退为
  ``application/octet-stream`` 而不抛异常，方便在 manifest 里标注那些
  需要带上但无法归类的附件。

This module intentionally stays a pure utility: no logging, no I/O side
effects beyond reading the target file, and no dependencies outside the
standard library. It mirrors the "no business ``print``, no ambient logging"
shape of :mod:`api.feedback_time`.

本模块刻意保持为纯工具：不写日志，不产生除读取目标文件以外的 I/O 副作用，
也不依赖标准库之外的任何东西，风格与 :mod:`api.feedback_time` 一致。
"""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

__all__ = ["file_sha256", "guess_mime"]


# Extra MIME mappings for feedback-relevant binary formats that :mod:`mimetypes`
# does not recognize out of the box on every platform. Keys are lower-cased
# extensions including the leading dot.
#
# 针对反馈流程常见的二进制格式，补充 :mod:`mimetypes` 在部分平台不识别的
# 映射表。键为带点的小写后缀。
_FEEDBACK_EXTENSION_MIME: dict[str, str] = {
    ".3mf": "model/3mf",
    ".npy": "application/x-numpy",
    ".msgpack": "application/x-msgpack",
    # NPZ is a zip archive of numpy arrays; treat it as a generic zip for
    # MIME purposes so email clients and browsers handle it sanely.
    # NPZ 本质是打包 numpy 数组的 zip 文件，按通用 zip 标注即可，
    # 让邮件客户端/浏览器按压缩包正常处理。
    ".npz": "application/zip",
}


def file_sha256(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return the lowercase hex SHA256 digest of ``path``'s byte contents.

    以小写十六进制字符串形式返回 ``path`` 文件内容的 SHA256 摘要。

    The file is opened in binary mode and read in ``chunk_size`` byte chunks
    (default 1 MiB) so a single large artifact — e.g. a 200 MB sparse 3MF —
    never has to be materialized in memory in full. Only the file's raw
    bytes participate in the digest; timestamps, permissions, and other
    filesystem metadata are ignored.

    文件以二进制方式打开，每次读取 ``chunk_size`` 字节（默认 1 MiB），
    避免像 200 MB 的稀疏 3MF 这种大产物被整段加载到内存。只有文件字节
    参与哈希，时间戳、权限等文件系统元数据不会影响结果。

    Args:
        path: Filesystem path to the file being hashed. Either a
            :class:`str` or a :class:`~pathlib.Path` is accepted.
        chunk_size: Streaming read buffer size in bytes. Must be a positive
            integer. Larger values reduce syscalls for large files; the 1 MiB
            default is a reasonable tradeoff between memory and throughput.

    Returns:
        str: A 64-character lowercase hexadecimal digest string.

    Raises:
        FileNotFoundError: If ``path`` does not exist. Raised by
            :func:`builtins.open` and deliberately not swallowed.
        IsADirectoryError: If ``path`` refers to a directory rather than a
            regular file. Also raised by :func:`builtins.open`.
        PermissionError: If the current process is not allowed to read
            ``path``. Propagated from the underlying ``open`` call.
        ValueError: If ``chunk_size`` is not a positive integer.
    """
    if not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError(
            f"chunk_size must be a positive int, got {chunk_size!r}"
        )

    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def guess_mime(path: str | Path) -> str:
    """Guess a MIME type for ``path`` based on its extension.

    根据 ``path`` 的后缀推断 MIME 类型。

    The stdlib :func:`mimetypes.guess_type` is consulted first. When it
    returns ``None`` — which happens for a handful of feedback-specific
    binary formats that are not in the system MIME database on every OS —
    the function consults a small built-in table covering ``.3mf``,
    ``.npy``, ``.npz`` and ``.msgpack``. If nothing matches, the caller
    receives the safe generic fallback ``application/octet-stream``.

    先调用标准库的 :func:`mimetypes.guess_type`；若返回 ``None``——部分
    平台上 ``.3mf`` / ``.npy`` 等后缀不在系统 MIME 库里——再查一张内置
    小表，覆盖 ``.3mf`` / ``.npy`` / ``.npz`` / ``.msgpack``。都不命中时
    返回通用回退值 ``application/octet-stream``。

    This function never raises: MIME guessing is a labelling aid for
    manifests, not a validation gate, so invalid or empty paths quietly
    degrade to the fallback.

    该函数不会抛异常：MIME 嗅探只是 manifest 里的标注辅助，不是校验
    关口，因此空路径、非法路径都只会静默回退到默认值。

    Args:
        path: Filesystem path whose extension will be inspected. May be
            a :class:`str` or a :class:`~pathlib.Path`. The file does not
            need to exist; only the path text is used.

    Returns:
        str: A MIME type string such as ``"image/png"``,
        ``"application/zip"``, ``"model/3mf"``, or the fallback
        ``"application/octet-stream"`` when the extension is unknown.
    """
    path_str = str(path)

    # Try the stdlib first; it covers the long tail (image/png, image/jpeg,
    # application/zip, application/json, text/plain, ...).
    guessed, _encoding = mimetypes.guess_type(path_str)
    if guessed:
        return guessed

    # Fall back to our feedback-specific extension table. Use Path.suffix so
    # that multi-dotted paths (e.g. "foo.tar.npy") still resolve correctly.
    suffix = Path(path_str).suffix.lower()
    if suffix in _FEEDBACK_EXTENSION_MIME:
        return _FEEDBACK_EXTENSION_MIME[suffix]

    return "application/octet-stream"
