"""Unit tests for ``api.feedback_fingerprint`` — SHA256 + MIME helpers.

验证 ``api.feedback_fingerprint`` 中的 SHA256 指纹与 MIME 嗅探工具：
小文件 / 空文件 / 大稀疏文件的流式哈希、标准错误语义，以及未知后缀降级。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from api.feedback_fingerprint import file_sha256, guess_mime


# ---------------------------------------------------------------------------
# file_sha256
# ---------------------------------------------------------------------------


def test_sha256_small_file(tmp_path: Path) -> None:
    """A known-content file hashes to the documented SHA256 of ``b"hello world"``."""
    target = tmp_path / "hello.txt"
    target.write_bytes(b"hello world")

    # Published SHA256 of the literal bytes ``hello world``.
    expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    assert file_sha256(str(target)) == expected


def test_sha256_empty_file(tmp_path: Path) -> None:
    """A 0-byte file hashes to the canonical SHA256 of the empty byte string."""
    target = tmp_path / "empty.bin"
    target.write_bytes(b"")

    expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert file_sha256(str(target)) == expected


def test_sha256_large_sparse_file(tmp_path: Path) -> None:
    """A 200 MB sparse zero-filled file matches ``sha256(b"\\0" * N)``.

    The file is created with :meth:`io.BufferedWriter.truncate` so it takes
    effectively no disk space on macOS/Linux (sparse allocation), yet the
    streaming hash must still read and digest all 200 MB of zeros. This
    proves that :func:`file_sha256` actually streams rather than reading
    only the first chunk.
    """
    size = 200 * 1024 * 1024  # 200 MiB
    target = tmp_path / "sparse.bin"
    with open(target, "wb") as fh:
        fh.truncate(size)

    expected = hashlib.sha256(b"\0" * size).hexdigest()
    assert file_sha256(str(target)) == expected


def test_sha256_nonexistent_raises_file_not_found(tmp_path: Path) -> None:
    """Missing path surfaces the stdlib :class:`FileNotFoundError` unchanged."""
    missing = tmp_path / "does_not_exist.bin"
    with pytest.raises(FileNotFoundError):
        file_sha256(str(missing))


def test_sha256_directory_raises_is_a_directory(tmp_path: Path) -> None:
    """A directory path consistently raises :class:`IsADirectoryError`."""
    with pytest.raises(IsADirectoryError):
        file_sha256(str(tmp_path))


def test_sha256_accepts_pathlib_path(tmp_path: Path) -> None:
    """Passing a :class:`pathlib.Path` produces the same digest as ``str``."""
    target = tmp_path / "payload.bin"
    target.write_bytes(b"The quick brown fox jumps over the lazy dog")

    assert file_sha256(target) == file_sha256(str(target))


def test_sha256_custom_chunk_size_matches_default(tmp_path: Path) -> None:
    """Changing ``chunk_size`` must not change the resulting digest."""
    target = tmp_path / "chunked.bin"
    # Size chosen so it is not a multiple of the custom chunk sizes, to
    # exercise the final short-read path in both.
    target.write_bytes(b"abc123" * 10_000)

    default_digest = file_sha256(target)
    assert file_sha256(target, chunk_size=1) == default_digest
    assert file_sha256(target, chunk_size=4096) == default_digest


def test_sha256_rejects_non_positive_chunk_size(tmp_path: Path) -> None:
    """Zero and negative ``chunk_size`` are programmer errors, not silent."""
    target = tmp_path / "x.bin"
    target.write_bytes(b"x")
    with pytest.raises(ValueError):
        file_sha256(target, chunk_size=0)
    with pytest.raises(ValueError):
        file_sha256(target, chunk_size=-1)


# ---------------------------------------------------------------------------
# guess_mime
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("image.png", "image/png"),
        ("image.jpg", "image/jpeg"),
        ("archive.zip", "application/zip"),
        ("data.json", "application/json"),
    ],
)
def test_guess_mime_common_types(filename: str, expected: str) -> None:
    """Common web-standard extensions resolve to stable MIME labels."""
    assert guess_mime(filename) == expected


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("model.3mf", "model/3mf"),
        ("palette.npy", "application/x-numpy"),
        ("state.msgpack", "application/x-msgpack"),
        ("arrays.npz", "application/zip"),
    ],
)
def test_guess_mime_feedback_extensions(filename: str, expected: str) -> None:
    """Feedback-specific binary formats resolve via the built-in table."""
    assert guess_mime(filename) == expected


def test_guess_mime_unknown_falls_back_to_octet_stream() -> None:
    """Unknown extensions quietly degrade to the generic binary fallback."""
    assert guess_mime("file.xyz123") == "application/octet-stream"


def test_guess_mime_does_not_raise_on_invalid_path() -> None:
    """Empty and nonexistent paths still return a string; no exception escapes."""
    assert isinstance(guess_mime(""), str)
    assert isinstance(guess_mime("/no/such/path/file.unknownext"), str)


def test_guess_mime_accepts_pathlib_path(tmp_path: Path) -> None:
    """A :class:`pathlib.Path` is accepted in addition to ``str``."""
    p = tmp_path / "pic.png"
    # File does not need to exist; guess_mime inspects the name only.
    assert guess_mime(p) == "image/png"


def test_guess_mime_is_case_insensitive_for_feedback_extensions() -> None:
    """Uppercase feedback extensions also resolve via the fallback table."""
    assert guess_mime("MODEL.3MF") == "model/3mf"
    assert guess_mime("PALETTE.NPY") == "application/x-numpy"
