"""Deterministic MIME labels for local feedback attachments.
本地反馈附件的确定性 MIME 标注。
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

_FEEDBACK_EXTENSION_MIME: dict[str, str] = {
    ".3mf": "model/3mf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".npy": "application/x-numpy",
    ".msgpack": "application/x-msgpack",
    ".npz": "application/zip",
    ".zip": "application/zip",
}


def guess_mime(path: str | Path) -> str:
    """Label an attachment by filename without reading its contents.
    根据附件文件名标注类型，不读取文件内容。

    Args:
        path: Filename or path; the file need not exist.
            文件名或路径，文件不必存在。

    Returns:
        MIME label, falling back to ``application/octet-stream``.
        MIME 类型，无法识别时返回 ``application/octet-stream``。
    """
    path_str = str(path)
    suffix = Path(path_str).suffix.lower()
    if suffix in _FEEDBACK_EXTENSION_MIME:
        return _FEEDBACK_EXTENSION_MIME[suffix]
    guessed, _encoding = mimetypes.guess_type(path_str)
    return guessed or "application/octet-stream"
