"""Property-based tests for Session Store TTL expiration (Property 2).

Verifies that TTL=0 SessionStore cleanup_expired() removes sessions
and their registered temporary files from disk.

**Validates: Requirements 1.5, 1.6**
"""

import os
import tempfile
import time
from typing import List, Tuple
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from api.session_store import SessionStore

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

session_keys = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=20,
)

session_values = st.one_of(
    st.text(max_size=50),
    st.integers(min_value=-(2**31), max_value=2**31),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
)

kv_pairs = st.lists(
    st.tuples(session_keys, session_values),
    min_size=1,
    max_size=5,
)

temp_file_count = st.integers(min_value=1, max_value=5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_temp_files(n: int) -> List[Tuple[str, int]]:
    """Create *n* real temporary files, return list of (path, fd)."""
    results: List[Tuple[str, int]] = []
    for _ in range(n):
        fd, path = tempfile.mkstemp(prefix="session_ttl_test_")
        os.write(fd, b"test data")
        os.close(fd)
        results.append((path, fd))
    return results


# ---------------------------------------------------------------------------
# Property 2: Session Store TTL Expiration
# ---------------------------------------------------------------------------


# **Validates: Requirements 1.5, 1.6**
@given(kvs=kv_pairs, n_files=temp_file_count)
@settings(max_examples=100)
def test_ttl_zero_cleanup_removes_session(
    kvs: List[Tuple[str, object]],
    n_files: int,
) -> None:
    """TTL=0 store: cleanup_expired() removes session, data, and temp files."""
    store = SessionStore(ttl=0)
    sid = store.create()

    # Store arbitrary key-value data
    for k, v in kvs:
        store.put(sid, k, v)

    # Create and register real temp files
    temp_paths: List[str] = []
    for path, _ in _create_temp_files(n_files):
        store.register_temp_file(sid, path)
        temp_paths.append(path)

    # Preconditions: session and files exist
    assert store.exists(sid) is True
    for p in temp_paths:
        assert os.path.exists(p), f"Temp file should exist before cleanup: {p}"

    # Small sleep so that time.time() - timestamp > 0 (TTL=0)
    time.sleep(0.01)

    # Cleanup
    expired_sids = store.cleanup_expired()
    assert len(expired_sids) >= 1, "At least one session should be cleaned up"

    # Post-conditions: session is gone
    assert store.get(sid) is None, "get() should return None after cleanup"
    assert store.exists(sid) is False, "exists() should return False after cleanup"

    # Post-conditions: temp files are deleted from disk
    for p in temp_paths:
        assert not os.path.exists(p), f"Temp file should be deleted after cleanup: {p}"


def test_touch_renews_session_lease_until_new_expiry() -> None:
    """touch() should renew the lease, and cleanup_expired() should use the renewed expiry."""
    store = SessionStore(ttl=10)

    with patch("api.session_store.time.time", return_value=100.0):
        session_id = store.create()

    with patch("api.session_store.time.time", return_value=105.0):
        expires_at = store.touch(session_id)

    assert expires_at == 115.0

    with patch("api.session_store.time.time", return_value=111.0):
        assert store.cleanup_expired() == []
        assert store.exists(session_id) is True

    with patch("api.session_store.time.time", return_value=116.0):
        assert store.cleanup_expired() == [session_id]
        assert store.exists(session_id) is False


def test_close_counts_missing_temp_file_as_cleaned() -> None:
    """close() should treat missing tracked temp files as already cleaned."""
    store = SessionStore(ttl=30)
    session_id = store.create()
    path = _create_temp_files(1)[0][0]
    store.register_temp_file(session_id, path)
    os.unlink(path)

    cleaned = store.close(session_id)

    assert cleaned == 1
    assert store.exists(session_id) is False


def test_put_does_not_recreate_closed_session_id() -> None:
    """put() must not recreate a session that has already been fully closed."""
    store = SessionStore(ttl=30)
    session_id = store.create()

    assert store.close(session_id) == 0

    store.put(session_id, "stale", "write")

    assert store.exists(session_id) is False
    assert store.get(session_id) is None


def test_put_does_not_modify_closing_session_or_extend_lease() -> None:
    """put() must no-op for closing sessions and leave existing state untouched."""
    store = SessionStore(ttl=30)
    blocked_path = _create_temp_files(1)[0][0]

    try:
        with patch("api.session_store.time.time", return_value=100.0):
            session_id = store.create()
            store.put(session_id, "original", "value")
            store.register_temp_file(session_id, blocked_path)

        with patch("api.session_store.os.remove", side_effect=PermissionError("locked")):
            cleaned = store.close(session_id)

        assert cleaned == 0
        previous_data = dict(store._store[session_id])
        previous_expiry = store._timestamps[session_id]

        with patch("api.session_store.time.time", return_value=150.0):
            store.put(session_id, "stale", "write")

        assert store._store[session_id] == previous_data
        assert store._timestamps[session_id] == previous_expiry
        assert store.exists(session_id) is False
        assert store.get(session_id) is None
    finally:
        if os.path.exists(blocked_path):
            os.unlink(blocked_path)


def test_register_temp_file_does_not_append_paths_for_closing_session() -> None:
    """register_temp_file() must ignore stale writes once a session is closing."""
    store = SessionStore(ttl=30)
    blocked_path = _create_temp_files(1)[0][0]
    new_path = _create_temp_files(1)[0][0]

    try:
        session_id = store.create()
        store.register_temp_file(session_id, blocked_path)

        with patch("api.session_store.os.remove", side_effect=PermissionError("locked")):
            cleaned = store.close(session_id)

        assert cleaned == 0
        previous_paths = list(store._temp_files[session_id])

        store.register_temp_file(session_id, new_path)

        assert store._temp_files[session_id] == previous_paths
        assert new_path not in store._temp_files[session_id]
    finally:
        for path in (blocked_path, new_path):
            if os.path.exists(path):
                os.unlink(path)


def test_retired_session_tombstone_expires_and_allows_unknown_sid_reuse() -> None:
    """After tombstone expiry, a closed session ID should be treated like an unknown ID."""
    store = SessionStore(ttl=10)

    with patch("api.session_store.time.time", return_value=100.0):
        session_id = store.create()
        assert store.close(session_id) == 0

    with patch("api.session_store.time.time", return_value=105.0):
        store.put(session_id, "stale", "write")
        assert store.exists(session_id) is False

    with patch("api.session_store.time.time", return_value=111.0):
        store.put(session_id, "fresh", "write")

    assert store.exists(session_id) is True
    assert store.get(session_id) == {"fresh": "write"}


def test_close_except_preserves_session_tracking_when_delete_fails() -> None:
    """close_except() must keep tracking, but the closing session should no longer appear live."""
    store = SessionStore(ttl=30)
    session_id = store.create()
    kept_path = _create_temp_files(1)[0][0]
    blocked_path = _create_temp_files(1)[0][0]
    store.register_temp_file(session_id, kept_path)
    store.register_temp_file(session_id, blocked_path)

    try:
        def _remove(path: str) -> None:
            if path == blocked_path:
                raise PermissionError("locked")
            os.unlink(path)

        with patch("api.session_store.os.remove", side_effect=_remove):
            cleaned = store.close_except(session_id, keep_paths={kept_path})

        assert cleaned == 0
        assert store.exists(session_id) is False
        assert store.touch(session_id) is None
        assert session_id in store._temp_files
        assert session_id in store._closing_sessions
        assert blocked_path in store._temp_files[session_id]
        assert os.path.exists(blocked_path) is True
    finally:
        for path in (kept_path, blocked_path):
            if os.path.exists(path):
                os.unlink(path)


def test_close_except_removes_session_but_preserves_kept_paths() -> None:
    """close_except() should remove the session while leaving keep_paths untouched on disk."""
    store = SessionStore(ttl=30)
    session_id = store.create()
    kept_path = _create_temp_files(1)[0][0]
    removed_path = _create_temp_files(1)[0][0]
    store.register_temp_file(session_id, kept_path)
    store.register_temp_file(session_id, removed_path)

    try:
        cleaned = store.close_except(session_id, keep_paths={kept_path})

        assert cleaned == 1
        assert store.exists(session_id) is False
        assert os.path.exists(kept_path) is True
        assert os.path.exists(removed_path) is False
    finally:
        for path in (kept_path, removed_path):
            if os.path.exists(path):
                os.unlink(path)


def test_cleanup_expired_keeps_session_when_delete_fails() -> None:
    """cleanup_expired() should retain tracking, but expired closing sessions must stay inaccessible."""
    store = SessionStore(ttl=10)
    blocked_path = _create_temp_files(1)[0][0]

    try:
        with patch("api.session_store.time.time", return_value=100.0):
            session_id = store.create()
            store.register_temp_file(session_id, blocked_path)

        with patch("api.session_store.time.time", return_value=111.0), patch(
            "api.session_store.os.remove",
            side_effect=PermissionError("locked"),
        ):
            assert store.cleanup_expired() == []

        assert store.exists(session_id) is False
        assert store.touch(session_id) is None
        assert session_id in store._temp_files
        assert session_id in store._closing_sessions
        assert blocked_path in store._temp_files[session_id]
        assert os.path.exists(blocked_path) is True
    finally:
        if os.path.exists(blocked_path):
            os.unlink(blocked_path)


def test_get_inactive_session_ids_includes_expired_closing_session() -> None:
    """Expired sessions that cannot fully close should still be exposed for follow-up cleanup."""
    store = SessionStore(ttl=10)
    blocked_path = _create_temp_files(1)[0][0]

    try:
        with patch("api.session_store.time.time", return_value=100.0):
            session_id = store.create()
            store.register_temp_file(session_id, blocked_path)

        with patch("api.session_store.time.time", return_value=111.0), patch(
            "api.session_store.os.remove",
            side_effect=PermissionError("locked"),
        ):
            assert store.cleanup_expired() == []

        assert store.get_inactive_session_ids() == [session_id]
    finally:
        if os.path.exists(blocked_path):
            os.unlink(blocked_path)
