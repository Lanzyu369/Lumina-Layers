"""Regression tests for bounded editor-operation confirmation receipts."""

from __future__ import annotations

import pytest

from api.editor_commit import (
    advance_editor_content_revision,
    begin_editor_commit,
    EditorCommitReplayError,
    fail_editor_commit,
    get_editor_commit_receipt,
    publish_editor_commit,
)
from api.session_store import SessionStore


def test_editor_commit_receipt_distinguishes_pending_failed_and_committed() -> None:
    store = SessionStore(ttl=1800)
    session_id = store.create()
    session_data = store.get(session_id)
    assert session_data is not None

    failed_id = begin_editor_commit(
        session_id,
        store,
        session_data,
        operation_id="failed-operation",
        operation="replace_color",
    )
    assert get_editor_commit_receipt(session_data, failed_id)["status"] == "pending"

    failed = fail_editor_commit(
        session_id,
        store,
        session_data,
        operation_id=failed_id,
        error_type="preview_cache_unavailable",
    )
    assert failed["status"] == "failed"
    assert get_editor_commit_receipt(session_data, failed_id)["status"] == "failed"

    with pytest.raises(EditorCommitReplayError):
        begin_editor_commit(
            session_id,
            store,
            session_data,
            operation_id=failed_id,
            operation="replace_color",
        )

    committed_id = begin_editor_commit(
        session_id,
        store,
        session_data,
        operation_id="committed-operation",
        operation="replace_color",
    )
    revision = advance_editor_content_revision(session_id, store, session_data)
    committed = publish_editor_commit(
        session_id,
        store,
        session_data,
        operation_id=committed_id,
        editor_content_revision=revision,
        selection_revision=3,
        result={
            "preview_url": "/api/files/committed.png",
            "replacement_regions": [{"replacement_hex": "#0000ff"}],
            "recipe_overrides": [{"region_id": "region-a", "recipe": [1]}],
            "free_color_set": [],
        },
    )
    assert committed["status"] == "committed"
    assert committed["editor_content_revision"] == revision
    assert committed["selection_revision"] == 3
    assert committed["result"]["preview_url"] == "/api/files/committed.png"
    assert committed["result"]["recipe_overrides"][0]["region_id"] == "region-a"

    with pytest.raises(EditorCommitReplayError):
        begin_editor_commit(
            session_id,
            store,
            session_data,
            operation_id=committed_id,
            operation="replace_color",
        )


def test_editor_commit_receipts_are_bounded() -> None:
    store = SessionStore(ttl=1800)
    session_id = store.create()
    session_data = store.get(session_id)
    assert session_data is not None

    for index in range(70):
        begin_editor_commit(
            session_id,
            store,
            session_data,
            operation_id=f"operation-{index}",
            operation="free_colors",
        )

    receipts = session_data["editor_commit_receipts"]
    assert len(receipts) == 64
    assert "operation-0" not in receipts
    assert "operation-69" in receipts
