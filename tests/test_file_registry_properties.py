"""Property-based tests for File Registry register/resolve consistency (Property 4).

Uses Hypothesis to verify:
- register_path() returns valid UUID4
- resolve(file_id) returns (path, filename) consistent with registration
- resolve(unknown_id) returns None
- cleanup_session() invalidates all file_ids for that session

**Validates: Requirements 1.2**
"""

import os
import tempfile
import uuid
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from api.file_registry import FileRegistry

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Session IDs: non-empty printable strings
session_ids = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=30,
)

# Filenames: simple alphanumeric names with common extensions
_extensions = st.sampled_from([".3mf", ".glb", ".png", ".jpg", ".npy", ".npz", ".zip", ".bin"])
filenames = st.builds(
    lambda name, ext: name + ext,
    name=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=20,
    ),
    ext=_extensions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_temp_file() -> str:
    """Create a real temporary file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".tmp")
    try:
        os.write(fd, b"test-content")
    finally:
        os.close(fd)
    return path


class _RegisterPathFailingRegistry(FileRegistry):
    """Registry stub that records the byte temp path before failing."""

    def __init__(self) -> None:
        super().__init__()
        self.temp_path: str | None = None

    def register_path(self, *args: object, **kwargs: object) -> str:
        path = kwargs.get("path")
        self.temp_path = str(path) if path is not None else None
        raise RuntimeError("registry backend unavailable")


# ---------------------------------------------------------------------------
# Property 4: File Registry Register/Resolve Consistency
# ---------------------------------------------------------------------------


# **Validates: Requirements 1.2**
@given(sid=session_ids, filename=filenames)
@settings(max_examples=100)
def test_register_path_returns_valid_uuid4(sid: str, filename: str) -> None:
    """register_path() returns a valid UUID4 format string."""
    registry = FileRegistry()
    path = _create_temp_file()
    try:
        file_id = registry.register_path(sid, path, filename)

        parsed = uuid.UUID(file_id, version=4)
        assert str(parsed) == file_id
        assert parsed.version == 4
    finally:
        os.unlink(path)


# **Validates: Requirements 1.2**
@given(sid=session_ids, filename=filenames)
@settings(max_examples=100)
def test_register_resolve_consistency(sid: str, filename: str) -> None:
    """register_path(sid, path, filename) then resolve(file_id) returns (path, filename)."""
    registry = FileRegistry()
    path = _create_temp_file()
    try:
        file_id = registry.register_path(sid, path, filename)

        result = registry.resolve(file_id)
        assert result is not None

        resolved_path, resolved_filename = result
        assert resolved_path == path
        assert resolved_filename == filename
    finally:
        os.unlink(path)


# **Validates: Requirements 1.2**
@given(unknown_id=st.uuids().map(str))
@settings(max_examples=100)
def test_resolve_unknown_id_returns_none(unknown_id: str) -> None:
    """resolve() with a random UUID that was never registered returns None."""
    registry = FileRegistry()

    result = registry.resolve(unknown_id)
    assert result is None


# **Validates: Requirements 1.2**
@given(
    sid=session_ids,
    file_data=st.lists(filenames, min_size=1, max_size=5),
)
@settings(max_examples=50)
def test_cleanup_session_invalidates_file_ids(sid: str, file_data: list[str]) -> None:
    """After cleanup_session(), all file_ids for that session resolve to None."""
    registry = FileRegistry()
    temp_paths: list[str] = []
    file_ids: list[str] = []

    try:
        for fname in file_data:
            path = _create_temp_file()
            temp_paths.append(path)
            fid = registry.register_path(sid, path, fname)
            file_ids.append(fid)

        # All file_ids should resolve before cleanup
        for fid in file_ids:
            assert registry.resolve(fid) is not None

        # Cleanup the session
        cleaned = registry.cleanup_session(sid)
        assert cleaned == len(file_ids)

        # All file_ids should resolve to None after cleanup
        for fid in file_ids:
            assert registry.resolve(fid) is None
    finally:
        for p in temp_paths:
            if os.path.exists(p):
                os.unlink(p)


# **Validates: Requirements 1.2**
@given(sid=session_ids, filename=filenames)
@settings(max_examples=50)
def test_ttl_entry_expires_and_resolve_invalidates_file_id(sid: str, filename: str) -> None:
    """TTL entry should become inaccessible after expiry and be removed from disk."""
    registry = FileRegistry()
    path = _create_temp_file()
    with patch("api.file_registry.time.time", return_value=100.0):
        file_id = registry.register_path(sid, path, filename, ttl_seconds=1)

    with patch("api.file_registry.time.time", return_value=102.0):
        assert registry.resolve(file_id) is None

    assert not os.path.exists(path)


def test_ttl_entry_under_materials_dir_expires_without_deleting_file(
    monkeypatch,
    tmp_path,
) -> None:
    """TTL expiry should invalidate persistent material links without deleting material files."""
    materials_root = tmp_path / "materials"
    material_path = materials_root / "PLA Basic" / "material.json"
    material_path.parent.mkdir(parents=True)
    material_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("api.file_registry.MATERIALS_DIR", str(materials_root))
    registry = FileRegistry()

    with patch("api.file_registry.time.time", return_value=100.0):
        file_id = registry.register_path(
            "material:test",
            str(material_path),
            "material.json",
            ttl_seconds=1,
        )

    entry = registry.get_entry(file_id)
    assert entry is not None
    assert entry["delete_on_cleanup"] is False

    with patch("api.file_registry.time.time", return_value=102.0):
        assert registry.resolve(file_id) is None

    assert material_path.exists() is True


def test_register_bytes_removes_temp_file_when_register_path_fails() -> None:
    """Byte registration should not leak the temp file if metadata registration fails."""
    registry = _RegisterPathFailingRegistry()

    with pytest.raises(RuntimeError, match="registry backend unavailable"):
        registry.register_bytes(
            "session-1",
            b"preview-bytes",
            "preview.png",
            ttl_seconds=1,
        )

    assert registry.temp_path is not None
    assert not os.path.exists(registry.temp_path)


# **Validates: Requirements 1.2**
@given(sid=session_ids, filename=filenames)
@settings(max_examples=50)
def test_cleanup_expired_removes_only_expired_entries(sid: str, filename: str) -> None:
    """cleanup_expired removes expired entries but preserves active and session-bound entries."""
    registry = FileRegistry()
    expired_path = _create_temp_file()
    active_path = _create_temp_file()
    session_bound_path = _create_temp_file()

    try:
        with patch("api.file_registry.time.time", return_value=100.0):
            expired_id = registry.register_path(sid, expired_path, f"expired-{filename}", ttl_seconds=1)
            active_id = registry.register_path(sid, active_path, f"active-{filename}", ttl_seconds=100)
            session_bound_id = registry.register_path(sid, session_bound_path, f"bound-{filename}")

        with patch("api.file_registry.time.time", return_value=102.0):
            removed = registry.cleanup_expired()

        assert removed == 1
        with patch("api.file_registry.time.time", return_value=102.0):
            assert registry.resolve(expired_id) is None
            assert registry.resolve(active_id) is not None
            assert registry.resolve(session_bound_id) is not None
    finally:
        for p in (expired_path, active_path, session_bound_path):
            if os.path.exists(p):
                os.unlink(p)


def test_ttl_resolve_renews_expiry_and_exposes_entry_metadata() -> None:
    """TTL entries should store ttl_seconds and extend expiry on successful resolve()."""
    registry = FileRegistry()
    path = _create_temp_file()

    try:
        with patch("api.file_registry.time.time", return_value=100.0):
            file_id = registry.register_path("session-1", path, "lease.bin", ttl_seconds=10)

        entry = registry.get_entry(file_id)
        assert entry is not None
        assert entry["ttl_seconds"] == 10
        assert entry["expires_at"] == 110.0

        with patch("api.file_registry.time.time", return_value=105.0):
            assert registry.resolve(file_id) == (path, "lease.bin")

        renewed_entry = registry.get_entry(file_id)
        assert renewed_entry is not None
        assert renewed_entry["expires_at"] == 115.0

        with patch("api.file_registry.time.time", return_value=114.0):
            assert registry.resolve(file_id) == (path, "lease.bin")
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_expired_resolve_keeps_tracking_when_delete_fails_and_file_still_exists() -> None:
    """Expired resolve() should retain tracking if delete fails and the file still exists."""
    registry = FileRegistry()
    path = _create_temp_file()

    try:
        with patch("api.file_registry.time.time", return_value=100.0):
            file_id = registry.register_path("session-1", path, "locked.bin", ttl_seconds=1)

        with patch("api.file_registry.time.time", return_value=102.0), patch(
            "api.file_registry.os.remove",
            side_effect=PermissionError("locked"),
        ):
            assert registry.resolve(file_id) is None

        entry = registry.get_entry(file_id)
        assert entry is not None
        assert entry["path"] == path
        assert os.path.exists(path) is True
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_cleanup_session_preserves_tracking_when_delete_fails() -> None:
    """cleanup_session() should retain failed session-bound entries as expired retry candidates."""
    registry = FileRegistry()
    path = _create_temp_file()

    try:
        with patch("api.file_registry.time.time", return_value=100.0):
            file_id = registry.register_path("session-1", path, "locked.bin")

        with patch("api.file_registry.time.time", return_value=120.0), patch(
            "api.file_registry.os.remove",
            side_effect=PermissionError("locked"),
        ):
            cleaned = registry.cleanup_session("session-1")

        assert cleaned == 0
        entry = registry.get_entry(file_id)
        assert entry is not None
        assert entry["lifecycle"] == "session_bound"
        assert entry["session_id"] == "session-1"
        assert entry["expires_at"] == 120.0
        assert os.path.exists(path) is True
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_cleanup_session_except_keeps_selected_file_ids() -> None:
    """cleanup_session_except() should preserve requested file IDs and remove the rest."""
    registry = FileRegistry()
    kept_path = _create_temp_file()
    removed_path = _create_temp_file()

    try:
        kept_id = registry.register_path("session-1", kept_path, "keep.bin")
        removed_id = registry.register_path("session-1", removed_path, "remove.bin")

        cleaned = registry.cleanup_session_except("session-1", keep_file_ids={kept_id})

        assert cleaned == 1
        assert registry.resolve(kept_id) == (kept_path, "keep.bin")
        assert registry.resolve(removed_id) is None
        assert os.path.exists(kept_path) is True
        assert os.path.exists(removed_path) is False
    finally:
        for path in (kept_path, removed_path):
            if os.path.exists(path):
                os.unlink(path)


def test_clear_all_preserves_tracking_when_delete_fails() -> None:
    """clear_all() should retain metadata for files that still exist after delete failure."""
    registry = FileRegistry()
    path = _create_temp_file()

    try:
        file_id = registry.register_path("session-1", path, "locked.bin")

        with patch(
            "api.file_registry.os.remove",
            side_effect=PermissionError("locked"),
        ):
            cleaned = registry.clear_all()

        assert cleaned == 0
        assert registry.get_entry(file_id) is not None
        assert os.path.exists(path) is True
    finally:
        if os.path.exists(path):
            os.unlink(path)
