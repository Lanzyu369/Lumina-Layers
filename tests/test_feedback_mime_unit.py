"""Feedback attachment MIME labels. 反馈附件 MIME 标注。"""

from pathlib import Path

import pytest

from api.feedback_mime import guess_mime


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
